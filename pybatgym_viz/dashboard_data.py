"""Read-only, bounded dashboard projections over run-owned artifacts."""
import bisect
import csv
import json
import math
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

_CACHE = OrderedDict()
_LOCK = threading.Lock()


def artifact(directory, relative):
    path = directory / relative
    if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        return None
    return path


def read_json(directory, relative, default=None):
    path = artifact(directory, relative)
    if path:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    return default


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite metric')
    return result


def rows(directory, relative):
    path = artifact(directory, relative)
    if not path:
        return []
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def allocations(text, cores):
    result = []
    for token in text.split():
        parts = token.split('-')
        start, end = int(parts[0]), int(parts[-1])
        if start < 0 or end >= cores or end < start:
            raise ValueError('Invalid native allocation')
        result.extend(range(start, end + 1))
    return sorted(set(result))


def dataset(directory):
    names = ['results/jobs.csv', 'results/per_episode_metrics.csv', 'config_resolved.json',
             'verification.json', 'status.json', 'simulator/manifest.json']
    signature = tuple((name, path.stat().st_mtime_ns, path.stat().st_size)
                      for name in names if (path := artifact(directory, name)))
    key = str(directory.resolve())
    with _LOCK:
        old = _CACHE.get(key)
        if old and old[0] == signature:
            _CACHE.move_to_end(key)
            return old[1]
    cfg = read_json(directory, 'config_resolved.json', {})
    cores = int(cfg.get('platform', {}).get('total_nodes', 32)) * int(cfg.get('platform', {}).get('cores_per_node', 1))
    groups = OrderedDict()
    for r in rows(directory, 'results/jobs.csv'):
        try:
            group_key = r['policy'] + ':' + r['seed']
            job = dict(id=r['job_id'], submit=number(r['submit_time']), start=number(r['start_time']),
                       finish=number(r['finish_time']), wait=number(r['waiting_time']),
                       resources=int(r['requested_resources']), allocation=[])
            if not 0 <= job['submit'] <= job['start'] <= job['finish'] or not 1 <= job['resources'] <= cores:
                continue
            group = groups.setdefault(group_key, dict(key=group_key, policy=r['policy'], seed=int(r['seed']), jobs=[]))
            group['jobs'].append(job)
        except (KeyError, ValueError, TypeError):
            continue  # The last row may still be being written.
    episodes = rows(directory, 'results/per_episode_metrics.csv')
    for index, ep in enumerate(episodes):
        group = groups.get(ep.get('policy', '') + ':' + ep.get('seed', ''))
        if not group:
            continue
        group['metrics'] = {k: number(ep[k]) for k in ('utilization', 'makespan', 'avg_bounded_slowdown') if ep.get(k)}
        by_id = {j['id']: j for j in group['jobs']}
        for native in rows(directory, f'simulator/{index}/batsim_jobs.csv'):
            try:
                if native['job_id'] in by_id:
                    by_id[native['job_id']]['allocation'] = allocations(native['allocated_resources'], cores)
            except (KeyError, ValueError):
                continue
    for group in groups.values():
        events = {}
        for j in group['jobs']:
            for t, delta in ((j['submit'], (1, 0, 0, 0)), (j['start'], (-1, 1, 0, j['resources'])),
                             (j['finish'], (0, -1, 1, -j['resources']))):
                values = events.setdefault(t, [0, 0, 0, 0])
                for i, v in enumerate(delta):
                    values[i] += v
        state = [0, 0, 0, 0]
        points = [dict(t=0, queued=0, running=0, completed=0, busy=0)]
        for t, delta in sorted(events.items()):
            state = [a+b for a, b in zip(state, delta)]
            points.append(dict(zip(('t', 'queued', 'running', 'completed', 'busy'), [t, *state])))
        group['points'] = points
        group['times'] = [p['t'] for p in points]
        waits = sorted(j['wait'] for j in group['jobs'])
        group['p95_wait'] = waits[max(0, math.ceil(len(waits)*.95)-1)]
        group['mean_wait'] = sum(waits)/len(waits)
    result = dict(cores=cores, total=int(cfg.get('workload', {}).get('num_jobs', 0)), groups=groups,
                  verification=read_json(directory, 'verification.json', {}))
    with _LOCK:
        _CACHE[key] = (signature, result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > 4:
            _CACHE.popitem(last=False)
    return result


def sampled(points, limit=900):
    if len(points) <= limit:
        return points
    # Preserve endpoints and queue/utilization peaks within each bucket.
    stride = math.ceil(len(points)/(limit//3))
    output = []
    for offset in range(0, len(points), stride):
        bucket = points[offset:offset+stride]
        for p in sorted({p['t']: p for p in (bucket[0], max(bucket, key=lambda p:p['queued']),
                                              max(bucket, key=lambda p:p['busy']))}.values(), key=lambda p:p['t']):
            output.append(p)
    if output[-1] != points[-1]:
        output.append(points[-1])
    return output


def core_timeline(jobs, cores, lo, hi, limit=2500):
    """Exact job intervals when small; bounded occupancy bins for full overviews.

    A density bin stores the fraction of that time bin really occupied by native
    allocations. It is not a synthetic job and must not get a job-ID tooltip.
    """
    visible = [j for j in jobs if j['start'] < hi and j['finish'] > lo]
    count = sum(len(j['allocation']) for j in visible)
    if count <= limit:
        return 'jobs', [dict(core=c, id=j['id'], start=j['start'], finish=j['finish'])
                        for j in visible for c in j['allocation']]
    bins = max(1, limit // max(1, cores))
    width = max(.000001, hi - lo) / bins
    by_core = [[] for _ in range(cores)]
    for job in visible:
        for core in job['allocation']:
            by_core[core].append((max(lo, job['start']), min(hi, job['finish'])))
    output = []
    for core, intervals in enumerate(by_core):
        # Union intervals first: overlapping records never double-count busy time.
        merged = []
        for start, finish in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], finish))
            else:
                merged.append((start, finish))
        busy = [0.] * bins
        for start, finish in merged:
            first = max(0, min(bins - 1, int((start - lo) / width)))
            last = max(0, min(bins - 1, int((finish - lo) / width)))
            for index in range(first, last + 1):
                a, b = lo + index * width, lo + (index + 1) * width
                busy[index] += max(0., min(finish, b) - max(start, a))
        output.extend(dict(core=core, start=lo+i*width, finish=lo+(i+1)*width,
                           busy_fraction=min(1., duration/width))
                      for i, duration in enumerate(busy) if duration > 0)
    return 'density', output


def projection(directory, episode=None, fraction=1.0, timeline_view='full'):
    data = dataset(directory)
    status = read_json(directory, 'status.json', {})
    request = read_json(directory, 'request.json', {})
    live = read_json(directory, 'progress.json', {})
    groups = data['groups']
    selected = groups.get(episode) if episode else None
    if selected is None and groups:
        selected = next(iter(groups.values()))
    terminal = status.get('state') in {'SUCCEEDED','FAILED','CANCELLED','TIMED_OUT'}
    live_key = f"{live.get('policy')}:{live.get('seed')}"
    completed_run = sum(len(g['jobs']) for g in groups.values() if terminal or g['key'] != live_key)
    if live and not terminal:
        completed_run += int(live.get('completed', 0))
    episode_count = sum(request.get('random_seeds', 1) if p == 'random' else 1 for p in request.get('policies', [])) or len(groups)
    verified = status.get('state') == 'SUCCEEDED' and data['verification'].get('status') == 'PASS'
    elapsed = None
    try:
        start = datetime.fromisoformat(status['started_at'])
        end = datetime.fromisoformat(status['finished_at']) if status.get('finished_at') else datetime.now(timezone.utc)
        elapsed = max(0, (end-start).total_seconds())
    except (KeyError, ValueError, TypeError):
        pass
    live_age = None
    if live:
        try:
            live_age = max(0, (datetime.now(timezone.utc)-datetime.fromisoformat(live['at'])).total_seconds())
        except (KeyError, ValueError, TypeError):
            pass
    payload = dict(state=status.get('state','CREATED'), verified=verified, terminal=terminal,
                   backend=request.get('backend'), total=data['total'], cores=data['cores'], elapsed=elapsed,
                   run_completed=completed_run, run_total=data['total']*episode_count,
                   episodes=[dict(key=g['key'], policy=g['policy'], seed=g['seed']) for g in groups.values()],
                   history=status.get('history', []), live=live, live_age=live_age,
                   comparison=[dict(policy=g['policy'],seed=g['seed'],mean_wait=g['mean_wait'],p95_wait=g['p95_wait'], **g.get('metrics', {})) for g in groups.values()],
                   series=[], timeline=[], jobs_count=0, source='waiting', sampled=False,
                   time_units={'simulation':'seconds', 'elapsed':'wall_clock_seconds', 'live_age':'wall_clock_seconds'},
                   percentile_method='nearest_rank', timeline_view=timeline_view)
    if selected:
        points = selected['points']
        horizon = points[-1]['t']
        cursor = horizon * max(0, min(1, fraction))
        state = points[max(0, bisect.bisect_right(selected['times'], cursor)-1)]
        jobs = selected['jobs']
        span = max(.001, horizon*.04)
        # Narrow the viewport rather than silently dropping allocations and
        # making busy cores appear idle in the right half of the chart.
        lo, hi = 0., horizon
        if timeline_view == 'window':
            for _ in range(32):
                lo, hi = max(0,cursor-span/2), min(horizon,cursor+span/2)
                visible = [j for j in jobs if j['start'] < hi and j['finish'] > lo]
                if sum(len(j['allocation']) for j in visible) <= 2500:
                    break
                span /= 2
        mode, segments = core_timeline(jobs, data['cores'], lo, hi)
        used_cores = sorted({c for j in jobs for c in j['allocation']})
        payload.update(source='replay',selected=selected['key'],policy=selected['policy'],seed=selected['seed'],
                       series=sampled(points), sampled=len(points)>900, cursor=cursor, horizon=horizon,
                       snapshot=state,timeline=segments,window=[lo,hi],timeline_limited=mode=='density',
                       timeline_mode=mode, used_cores=used_cores,
                       jobs_count=len(jobs),native_allocation=any(j['allocation'] for j in jobs))
    # New runs have measured worker snapshots. Old runs remain Replay-only.
    if not terminal and live and (not episode or episode == f"{live.get('policy')}:{live.get('seed')}"):
        history_path = artifact(directory, 'progress.jsonl')
        points = []
        if history_path:
            with history_path.open('rb') as stream:
                stream.seek(max(0, history_path.stat().st_size-2*1024*1024))
                if stream.tell():
                    stream.readline()
                for line in stream:
                    try:
                        p=json.loads(line)
                        if p['policy']==live['policy'] and p['seed']==live['seed']:
                            points.append(dict(t=p['sim_time'],queued=p['queued'],running=p['running'],completed=p['completed'],busy=p['busy']))
                    except (ValueError,KeyError):
                        continue
        payload.update(source='live',policy=live['policy'],seed=live['seed'],selected=f"{live['policy']}:{live['seed']}",
                       snapshot=dict(t=live['sim_time'],queued=live['queued'],running=live['running'],completed=live['completed'],busy=live['busy']),
                       series=sampled(points),cursor=live['sim_time'],horizon=live['sim_time'],timeline=[],native_allocation=False,
                       live_core_map=live.get('core_map', []), timeline_mode='snapshot')
    return payload


def job_page(directory, episode, page, query=''):
    data=dataset(directory)
    group=data['groups'].get(episode)
    jobs=group['jobs'] if group else []
    if query:
        jobs=[j for j in jobs if query in j['id']]
    start=(page-1)*25
    return dict(total=len(jobs),page=page,page_size=25,jobs=[{k:v for k,v in j.items() if k!='allocation'} for j in jobs[start:start+25]])
