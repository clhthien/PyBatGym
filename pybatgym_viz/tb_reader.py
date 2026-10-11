"""Đọc scalar từ các file TensorBoard (events.out.tfevents.*) trong logs/.

Khác command.py: nguồn dữ liệu là file nhị phân TensorBoard, không phải lệnh shell,
nên dùng thư viện `tensorboard` (đã có sẵn trong image PyBatGym) để đọc.
"""
import os
from command import Table


def load_runs(logs_dir):
    """Trả về {nhãn_run: {tag: [(step, value), ...]}}. Nhãn = đường dẫn tương đối, vd 'PPO_Run_x/FCFS'."""
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    runs = {}
    for root, _dirs, files in os.walk(logs_dir):
        if not any(f.startswith("events.out.tfevents") for f in files):
            continue
        ea = EventAccumulator(root, size_guidance={"scalars": 0})
        ea.Reload()
        label = os.path.relpath(root, logs_dir)
        runs[label] = {
            tag: [(e.step, e.value) for e in ea.Scalars(tag)]
            for tag in ea.Tags().get("scalars", [])
        }
    return runs


def short_labels(labels):
    """'PPO_Run_1790349914/FCFS' -> 'FCFS'. Nếu rút gọn bị trùng tên thì giữ nguyên nhãn đầy đủ."""
    short = {lb: lb.split("/")[-1] for lb in labels}
    if len(set(short.values())) != len(short):
        return {lb: lb for lb in labels}
    return short


def last_value_table(runs):
    """Bảng: mỗi dòng là 1 tag, mỗi cột là 1 run, giá trị = điểm cuối cùng của tag đó."""
    labels = sorted(runs)
    short = short_labels(labels)
    tags = sorted({t for r in runs.values() for t in r})
    rows = []
    for t in tags:
        row = {"tag": t}
        for lb in labels:
            pts = runs[lb].get(t)
            row[short[lb]] = "%.4g" % pts[-1][1] if pts else ""
        rows.append(row)
    return Table(["tag"] + [short[lb] for lb in labels], rows)
