"""Tương đương app.rb (Sinatra) trong tutorial. Flask thay cho Sinatra."""
import os
from flask import Flask, render_template, request

from command import Command, numeric_columns, aggregate
import tb_reader

# Trong container `shell`, repo được mount ở /workspace  => kết quả ở đây.
# Đổi bằng biến môi trường nếu thư mục kết quả của bạn khác.
RESULTS_DIR = os.environ.get("PYBATGYM_RESULTS_DIR", "/workspace/pybatgym/results")
SUMMARY_CSV = "benchmark_summary.csv"
EPISODES_CSV = "per_episode_metrics.csv"
LOGS_DIR = os.environ.get("PYBATGYM_LOGS_DIR", "/workspace/logs/tensorboard_comparison")
NOT_METRICS = ("seed", "episode_idx", "experiment_id", "terminated", "truncated")

# template_folder="views", static_folder="public" -> giữ đúng tên thư mục như tutorial
app = Flask(__name__, template_folder="views", static_folder="public")


@app.context_processor
def helpers():
    # Tương đương `helpers do def title ... end` trong app.rb
    return {"title": "PyBatGym Results"}


@app.route("/")
def index():
    cmd = Command(os.path.join(RESULTS_DIR, SUMMARY_CSV))
    table, error = cmd.exec()
    agg = aggregate(table) if not error else None
    return render_template("index.html", table=table, agg=agg, error=error, command=cmd.to_s())


@app.route("/episodes")
def episodes():
    cmd = Command(os.path.join(RESULTS_DIR, EPISODES_CSV))
    table, error = cmd.exec()
    num_cols = [c for c in numeric_columns(table) if c not in NOT_METRICS]
    col = request.args.get("col")
    if col not in num_cols:
        col = num_cols[0] if num_cols else None
    series = [float(r[col]) for r in table.rows] if col else []
    labels = [r["episode_idx"] for r in table.rows] if "episode_idx" in table.columns else list(range(1, len(series) + 1))
    return render_template(
        "episodes.html", table=table, error=error, command=cmd.to_s(),
        num_cols=num_cols, col=col, series=series, labels=labels,
    )


@app.route("/comparison")
def comparison():
    """So sánh các run trong logs/tensorboard_comparison (PPO, FCFS, SJF, EASY, MaskablePPO)."""
    try:
        runs = tb_reader.load_runs(LOGS_DIR)
        error = None if runs else "Không thấy file events.out.tfevents.* trong " + LOGS_DIR
    except Exception as exc:  # thiếu thư viện tensorboard hoặc file hỏng
        runs, error = {}, "%s: %s" % (type(exc).__name__, exc)
    table = tb_reader.last_value_table(runs)
    tags = [r["tag"] for r in table.rows]
    tag = request.args.get("tag")
    if tag not in tags:
        tag = tags[0] if tags else None
    short = tb_reader.short_labels(list(runs))
    datasets = [{"label": short[lb], "points": [{"x": st, "y": v} for st, v in pts[tag]]}
                for lb, pts in sorted(runs.items()) if tag in pts]
    return render_template("comparison.html", table=table, error=error, logs_dir=LOGS_DIR,
                           tags=tags, tag=tag, datasets=datasets)


if __name__ == "__main__":
    # Chạy local/Docker. Dưới OOD thật, Passenger gọi passenger_wsgi.py thay thế.
    app.run(host="0.0.0.0", port=5000, debug=True)
