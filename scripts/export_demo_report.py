"""Export presentation charts from verified runs; never launches simulations.

Requires matplotlib in a separate reporting environment. Repeated --run arguments
may reference different workload sizes. Each panel compares policies within one
workload/seed; it does not average across workloads or imply significance.
"""
import argparse
import csv
import hashlib
import html
import json
import math
from pathlib import Path


def table(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def percentile(values, fraction):
    ordered = sorted(values)
    # Same nearest-rank definition as dashboard_data.py.
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def load_run(directory):
    status = json.loads((directory / 'status.json').read_text(encoding='utf-8'))
    verification = json.loads((directory / 'verification.json').read_text(encoding='utf-8'))
    request = json.loads((directory / 'request.json').read_text(encoding='utf-8'))
    if status['state'] != 'SUCCEEDED' or verification['status'] != 'PASS':
        raise ValueError(f'{directory.name}: only SUCCEEDED/PASS runs may be reported')
    if request['backend'] != 'real':
        raise ValueError('This report is for Real BatSim evidence only')
    metrics_path = directory / 'results/per_episode_metrics.csv'
    jobs_path = directory / 'results/jobs.csv'
    metrics, jobs = table(metrics_path), table(jobs_path)
    rows, distributions = [], []
    for metric in metrics:
        selected = [j for j in jobs if (j['policy'], j['seed']) == (metric['policy'], metric['seed'])]
        if not selected or int(metric['completed_jobs']) != len(selected) or int(metric['invalid_actions']):
            raise ValueError('Job count mismatch or invalid actions')
        waits = [float(j['waiting_time']) for j in selected]
        if not all(math.isfinite(v) and v >= 0 for v in waits):
            raise ValueError('Invalid job waiting times')
        rows.append(dict(run_id=directory.name, backend=request['backend'], workload=metric['workload'],
                         policy=metric['policy'], seed=metric['seed'], jobs=len(selected),
                         mean_wait_seconds=float(metric['avg_waiting_time']), p95_wait_seconds=percentile(waits, .95),
                         utilization_percent=float(metric['utilization']) * 100,
                         makespan_seconds=float(metric['makespan']),
                         bounded_slowdown=float(metric['avg_bounded_slowdown'])))
        distributions.append((metric['policy'] + ' / seed ' + metric['seed'], sorted(waits)))
    return rows, distributions, {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (metrics_path, jobs_path, directory / 'verification.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Refuse to replace an existing report, even if input run IDs repeat.
    args.output.mkdir(parents=True, exist_ok=False)
    all_rows, provenance, sections = [], [], []
    colors = {'FCFS': '#3478bf', 'SJF': '#e18b28', 'EASY': '#259974', 'Random': '#865ab5'}
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    for index, run in enumerate(args.run):
        run = run.resolve(strict=True)
        rows, distributions, hashes = load_run(run)
        all_rows.extend(rows)
        provenance.append({'directory': str(run), 'sha256': hashes})
        labels = [r['policy'] + '\ns' + r['seed'] for r in rows]
        fig, axes = plt.subplots(2, 2, figsize=(10, 6.7), layout='constrained')
        for ax, key, title, unit in zip(axes.flat,
                ('mean_wait_seconds', 'p95_wait_seconds', 'utilization_percent', 'makespan_seconds'),
                ('Mean waiting time (lower is better)', 'p95 waiting time (lower is better)',
                 'Mean utilization', 'Makespan (lower is better)'), ('Simulation seconds', 'Simulation seconds', '%', 'Simulation seconds')):
            values = [r[key] for r in rows]
            bars = ax.bar(labels, values, color=[colors.get(r['policy'], '#65758b') for r in rows], width=.55)
            ax.bar_label(bars, labels=[f'{v:,.2f}' for v in values], padding=4, fontsize=9)
            ax.set(title=title, ylabel=unit, ylim=(0, max(values) * 1.22 if max(values) else 1))
            ax.grid(axis='y', alpha=.15)
            ax.set_axisbelow(True)
        title = f"BatSim | {rows[0]['workload']} | {rows[0]['jobs']:,} jobs / policy"
        fig.suptitle(title + '\nVerified PASS; one workload and seed, no significance claim', fontsize=12)
        stem = f'{index + 1:02d}-policy-comparison'
        fig.savefig(args.output / (stem + '.png'), dpi=170)
        fig.savefig(args.output / (stem + '.pdf'))
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(9, 4.6), layout='constrained')
        for label, waits in distributions:
            ax.step(waits, [(i+1)/len(waits) for i in range(len(waits))], where='post', label=label)
        ax.set(title=title + '\nWaiting-time empirical CDF', xlabel='Waiting time (simulation seconds)',
               ylabel='Fraction of completed jobs', ylim=(0, 1.02))
        ax.grid(alpha=.2)
        ax.legend()
        cdf_stem = f'{index + 1:02d}-waiting-cdf'
        fig.savefig(args.output / (cdf_stem + '.png'), dpi=170)
        fig.savefig(args.output / (cdf_stem + '.pdf'))
        plt.close(fig)
        fcfs = next((r for r in rows if r['policy'] == 'FCFS'), None)
        sjf = next((r for r in rows if r['policy'] == 'SJF' and fcfs and r['seed'] == fcfs['seed']), None)
        note = ''
        if fcfs and sjf and fcfs['mean_wait_seconds'] > 0:
            gain = (1 - sjf['mean_wait_seconds'] / fcfs['mean_wait_seconds']) * 100
            note = f'<p>SJF giảm thời gian chờ trung bình {gain:.2f}% so với FCFS trên workload/seed này.</p>'
        sections.append(f'<section><h2>{html.escape(title)}</h2><code>{html.escape(run.name)}</code>{note}'
                        f'<img src="{stem}.png" alt="Policy comparison"><img src="{cdf_stem}.png" alt="Waiting-time CDF"></section>')
    with (args.output / 'summary.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    (args.output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    document = '''<!doctype html><html lang="vi"><meta charset="utf-8"><title>PyBatGym demo evidence</title>
<style>body{font:17px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#172438}
img{max-width:100%}section{border-top:1px solid #ccd4df;margin-top:30px}code{overflow-wrap:anywhere}</style>
<h1>PyBatGym — kết quả benchmark đã kiểm chứng</h1>
<p>Biểu đồ được xuất từ CSV của từng run SUCCEEDED/PASS. Đây là các workload tổng hợp,
không phải kết quả huấn luyện RL hay tốc độ thực thi job sản xuất trên HPC.</p>
<p>So sánh FCFS/SJF trong cùng workload, platform và seed. SJF dùng cửa sổ top-K của môi trường;
chưa có bằng chứng tổng quát qua nhiều trace/seed. Không cộng các seed thành một mẫu độc lập.</p>
<p>Trục thời gian dùng giây mô phỏng; utilization là core mô phỏng. p95 dùng nearest-rank như dashboard.
CSV tổng hợp: <a href="summary.csv">summary.csv</a>.
Nguồn và hash: <a href="provenance.json">provenance.json</a>.</p>'''
    (args.output / 'index.html').write_text(document + ''.join(sections) + '</html>', encoding='utf-8')
    print(args.output.resolve())


if __name__ == '__main__':
    main()
