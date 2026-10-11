"""Tương đương command.rb trong tutorial OSC (ps-to-quota).

Luồng giống hệt tutorial:
    1. to_s   -> lệnh shell sẽ chạy
    2. exec   -> chạy lệnh, lấy raw output
    3. parse  -> biến raw output thành object trung gian (Table)
View (Jinja template) chỉ dùng object trung gian này để render.
"""
import csv
import shlex
import subprocess
from collections import namedtuple

# Tương đương `Quota = Struct.new(...)` trong tutorial.
# Cột KHÔNG hard-code: lấy từ dòng header của CSV, nên không phụ thuộc
# việc benchmark_summary.csv / per_episode_metrics.csv có những cột nào.
Table = namedtuple("Table", ["columns", "rows"])


class Command:
    def __init__(self, csv_path):
        self.csv_path = csv_path

    def to_s(self):
        # Tutorial: "quota -spw". Ở đây: đọc file CSV do BenchmarkLogger xuất ra.
        return "cat " + shlex.quote(self.csv_path)

    def exec(self):
        """Trả về (Table, error). error = None nếu thành công."""
        try:
            proc = subprocess.run(
                self.to_s(), shell=True, capture_output=True, text=True, timeout=10
            )
        except subprocess.TimeoutExpired:
            return Table([], []), "Lệnh chạy quá 10 giây: " + self.to_s()
        if proc.returncode != 0:
            msg = proc.stderr.strip() or "exit code %d" % proc.returncode
            return Table([], []), msg
        return self.parse(proc.stdout), None

    def parse(self, output):
        """Parse CSV text -> Table(columns, rows). rows là list[dict]."""
        lines = output.strip().splitlines()
        if not lines:
            return Table([], [])
        reader = csv.DictReader(lines)
        rows = [dict(r) for r in reader]
        return Table(list(reader.fieldnames or []), rows)


def numeric_columns(table):
    """Các cột mà mọi giá trị đều parse được thành số (dùng để vẽ biểu đồ)."""
    cols = []
    for c in table.columns:
        try:
            [float(r[c]) for r in table.rows]
        except (ValueError, TypeError, KeyError):
            continue
        if table.rows:
            cols.append(c)
    return cols


GROUP_COLS = ("policy", "workload", "platform")
SKIP_METRICS = ("seed", "episode_idx", "experiment_id", "terminated", "truncated")


def aggregate(table, group_cols=GROUP_COLS, skip=SKIP_METRICS):
    """Gom các dòng theo (policy, workload, platform) -> 'mean ± std' cho từng chỉ số số học.

    benchmark_summary.csv hiện ghi từng lượt chạy (không phải bảng tổng hợp),
    nên cần gom lại để so sánh policy.
    """
    import statistics
    keys = [c for c in group_cols if c in table.columns]
    metrics = [c for c in numeric_columns(table) if c not in skip and c not in keys]
    groups = {}
    for r in table.rows:
        groups.setdefault(tuple(r[k] for k in keys), []).append(r)
    out = []
    for gk, rows in groups.items():
        row = dict(zip(keys, gk))
        row["n"] = str(len(rows))
        for m in metrics:
            vals = [float(r[m]) for r in rows]
            mean = statistics.fmean(vals)
            std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            row[m] = "%.4g ± %.2g" % (mean, std)
        out.append(row)
    return Table(keys + ["n"] + metrics, out)
