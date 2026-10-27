"""Benchmark runner độc lập: chạy nhiều policy trên cùng bộ workload và cùng backend.

Không phụ thuộc quá trình huấn luyện. Mỗi lần chạy tạo một thư mục riêng chứa đủ artifact:

  <out>/config_resolved.json     cấu hình đã nạp + tham số dòng lệnh
  <out>/env_info.json            git commit, phiên bản Python/numpy, thời điểm chạy
  <out>/per_episode_metrics.csv  mỗi dòng một episode (cùng schema BenchmarkLogger)
  <out>/benchmark_summary.csv    mỗi dòng một policy (trung bình các episode)
  <out>/comparison_table.csv     mean ± std theo workload cho từng policy
  <out>/steps.csv                log từng bước ra quyết định (action, mask, reward theo thành phần)
  <out>/jobs.csv                 từng job: submit/start/finish (nguồn dữ liệu cho Gantt)

Ví dụ:
  python pybatgym/experiments/run_benchmark.py --preset medium_batsim \
      --workloads "data/workloads/gen_c32_s*.json" --policies fcfs sjf easy random --out runs/bench_mock
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import platform as _platform
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from pybatgym.baselines import (
    RandomMaskedPolicy,
    easy_backfilling_policy,
    fcfs_policy,
    sjf_policy,
)
from pybatgym.config.loader import load_config, load_preset
from pybatgym.core import ScheduleCommandType
from pybatgym.envs import PyBatGymEnv
from pybatgym.plugins.benchmark_logger import BenchmarkLogger

POLICY_LABELS = {
    "fcfs": "FCFS",
    "sjf": "SJF",
    "easy": "EASY",
    "random": "Random",
    "ppo_maskable": "PPO_Maskable",
}
METRIC_COLS = [
    "total_reward", "completed_jobs", "avg_waiting_time", "avg_bounded_slowdown",
    "utilization", "makespan", "throughput", "num_steps", "invalid_actions",
]
STEP_COLS = [
    "run_id", "policy", "workload", "seed", "step", "sim_time", "n_pending", "free_cores",
    "n_valid_actions", "action", "action_name", "valid", "chosen_job_id", "chosen_job_cores",
    "chosen_job_walltime", "chosen_job_wait", "reward", "delta_utilization", "completed_wait",
    "completed_slowdown", "schedule_bonus", "wait_penalty", "idle_penalty", "episode_bonus", "mask",
]
JOB_COLS = [
    "run_id", "policy", "workload", "seed", "job_id", "submit_time", "start_time", "finish_time",
    "requested_resources", "requested_walltime", "actual_runtime", "waiting_time", "bounded_slowdown",
]
BATSIM_WORKLOAD_FILE = "/workspace/data/.batsim_workload"


# ── Policies ────────────────────────────────────────────────────────────────

class ModelPolicy:
    """Bọc MaskablePPO đã huấn luyện thành policy(env) -> action."""

    def __init__(self, model_path: str) -> None:
        from sb3_contrib import MaskablePPO  # import muộn: chỉ cần khi dùng ppo_maskable
        self.model = MaskablePPO.load(model_path)

    def __call__(self, env) -> int:
        obs = env._obs_builder.build(env._state)
        action, _ = self.model.predict(
            obs, deterministic=True, action_masks=obs["action_mask"].astype(bool),
        )
        return int(action)


def build_policy(name: str, model_path: Optional[str]) -> Callable:
    if name == "fcfs":
        return fcfs_policy
    if name == "sjf":
        return sjf_policy
    if name == "easy":
        return easy_backfilling_policy
    if name == "random":
        return RandomMaskedPolicy(0)
    if name == "ppo_maskable":
        if not model_path:
            raise SystemExit("Policy ppo_maskable cần --model <đường dẫn file .zip>")
        return ModelPolicy(model_path)
    raise SystemExit("Policy không hợp lệ: %s (chọn trong %s)" % (name, sorted(POLICY_LABELS)))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _fmt(x: Any) -> Any:
    return round(x, 6) if isinstance(x, float) else x


def _action_name(action: int, k: int) -> str:
    if action < k:
        return "JOB_%d" % action
    return "WAIT" if action == k else "BACKFILL"


def _count_jobs(path: str) -> int:
    with open(path, "r", encoding="utf-8") as f:
        return len(json.load(f).get("jobs", []))


def _make_config(args, workload_path: str):
    cfg = load_config(args.config) if args.config else load_preset(args.preset)
    cfg.mode = "real" if args.backend == "real" else "mock"
    cfg.workload.source = "trace"
    cfg.workload.trace_path = str(Path(workload_path).resolve())
    cfg.workload.num_jobs = _count_jobs(workload_path)
    return cfg


def _set_batsim_workload(path: str) -> None:
    """Backend real: báo cho container BatSim biết dùng workload nào ở lần restart tới.

    Cần scripts/batsim_start.sh bản mới (đọc file này khi khởi động).
    """
    target = Path(BATSIM_WORKLOAD_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(Path(path).resolve()) + "\n", encoding="utf-8")


# ── One episode ─────────────────────────────────────────────────────────────

def run_episode(cfg, policy: Callable, policy_label: str, workload_path: str, seed: int,
                run_id: str, step_w, job_w) -> dict[str, Any]:
    workload = Path(workload_path).stem
    env = PyBatGymEnv(config=cfg)
    try:
        env.reset(seed=seed)
        if hasattr(policy, "reset"):
            policy.reset(seed)
        k = env._action_mapper.wait_action
        done, step, invalid, info, terminated, truncated = False, 0, 0, {}, False, False
        while not done:
            state = env._state
            mask = np.asarray(env.action_masks(), dtype=bool)
            action = max(0, min(int(policy(env)), env.action_space.n - 1))
            valid = bool(mask[action])
            invalid += 0 if valid else 1
            cmd = env._action_mapper.map(action, state)
            chosen = cmd.job if (cmd and cmd.command_type == ScheduleCommandType.EXECUTE_JOB) else None
            sim_time = env._adapter.get_current_time()
            n_pending = len(state.get("pending_jobs", []))
            free_cores = state["resource"].free_cores

            _, reward, terminated, truncated, info = env.step(action)
            comp = dict(getattr(env._reward_calc, "last_components", {}) or {})
            step_w.writerow([
                run_id, policy_label, workload, seed, step, _fmt(sim_time), n_pending, free_cores,
                int(mask.sum()), action, _action_name(action, k), int(valid),
                chosen.job_id if chosen else "", chosen.requested_resources if chosen else "",
                _fmt(chosen.requested_walltime) if chosen else "",
                _fmt(sim_time - chosen.submit_time) if chosen else "",
                _fmt(reward),
                _fmt(comp.get("delta_utilization", 0.0)), _fmt(comp.get("completed_wait", 0.0)),
                _fmt(comp.get("completed_slowdown", 0.0)), _fmt(comp.get("schedule_bonus", 0.0)),
                _fmt(comp.get("wait_penalty", 0.0)), _fmt(comp.get("idle_penalty", 0.0)),
                _fmt(reward - sum(comp.values())),
                "".join("1" if m else "0" for m in mask),
            ])
            step += 1
            done = terminated or truncated

        completed = env._adapter.get_completed_jobs()
        for j in sorted(completed, key=lambda j: j.job_id):
            job_w.writerow([
                run_id, policy_label, workload, seed, j.job_id, _fmt(j.submit_time), _fmt(j.start_time),
                _fmt(j.finish_time), j.requested_resources, _fmt(j.requested_walltime),
                _fmt(j.actual_runtime), _fmt(j.waiting_time), _fmt(j.bounded_slowdown),
            ])
        m = dict(info.get("episode_metrics", {}))
        m.update(num_steps=step, invalid_actions=invalid,
                 terminated=int(bool(terminated)), truncated=int(bool(truncated)))
        m["expected_jobs"] = cfg.workload.num_jobs
        return m
    finally:
        env.close()
        if cfg.mode == "real":
            time.sleep(3)  # để cổng ZMQ được giải phóng trước lần restart BatSim kế tiếp


# ── Aggregation ─────────────────────────────────────────────────────────────

def _mean_std(values: list[float]) -> tuple[float, float]:
    mean = statistics.fmean(values)
    return mean, (statistics.stdev(values) if len(values) > 1 else 0.0)


def write_comparison(path: Path, episodes: list[dict]) -> list[dict]:
    """Mỗi workload tính trung bình các episode của policy trước, rồi mean ± std qua các workload."""
    rows = []
    for label in dict.fromkeys(e["policy"] for e in episodes):
        eps = [e for e in episodes if e["policy"] == label]
        per_wl = {}
        for e in eps:
            per_wl.setdefault(e["workload"], []).append(e)
        row = {"policy": label, "n_workloads": len(per_wl), "n_episodes": len(eps),
               "n_incomplete": sum(1 for e in eps if e["completed_jobs"] != e["expected_jobs"]),
               "invalid_actions_total": sum(e["invalid_actions"] for e in eps)}
        for col in METRIC_COLS:
            if col in ("completed_jobs", "num_steps", "invalid_actions"):
                continue
            means = [statistics.fmean(float(x[col]) for x in group) for group in per_wl.values()]
            mean, std = _mean_std(means)
            row[col + "_mean"], row[col + "_std"] = round(mean, 6), round(std, 6)
        rows.append(row)
    cols = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return rows


def print_table(rows: list[dict]) -> None:
    head = ["policy", "workloads", "incomplete", "avg_wait (s)", "bounded_sd", "util", "makespan (s)"]
    print("\n" + " | ".join("%-14s" % h for h in head))
    for r in rows:
        print(" | ".join("%-14s" % v for v in [
            r["policy"], r["n_workloads"], r["n_incomplete"],
            "%.1f ± %.1f" % (r["avg_waiting_time_mean"], r["avg_waiting_time_std"]),
            "%.2f ± %.2f" % (r["avg_bounded_slowdown_mean"], r["avg_bounded_slowdown_std"]),
            "%.3f" % r["utilization_mean"],
            "%.0f ± %.0f" % (r["makespan_mean"], r["makespan_std"]),
        ]))


# ── Main ────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="medium_batsim", help="tên file trong configs/ (không có .yaml)")
    ap.add_argument("--config", help="đường dẫn file YAML (ưu tiên hơn --preset)")
    ap.add_argument("--workloads", nargs="+", required=True, help="file JSON hoặc glob, vd data/workloads/gen_c32_s*.json")
    ap.add_argument("--policies", nargs="+", default=["fcfs", "sjf", "easy", "random"], choices=sorted(POLICY_LABELS))
    ap.add_argument("--backend", choices=["mock", "real"], default="mock")
    ap.add_argument("--model", help="file .zip của MaskablePPO (khi dùng ppo_maskable)")
    ap.add_argument("--random-seeds", type=int, default=3, help="số seed cho policy random trên mỗi workload")
    ap.add_argument("--out", help="thư mục kết quả (mặc định runs/<thời gian>_<backend>)")
    args = ap.parse_args(argv)

    files: list[str] = []
    for pat in args.workloads:
        files.extend(sorted(glob.glob(pat)) or ([pat] if Path(pat).exists() else []))
    files = list(dict.fromkeys(files))
    if not files:
        raise SystemExit("Không tìm thấy workload nào: %s" % args.workloads)

    run_id = time.strftime("%Y%m%d-%H%M%S") + "_" + args.backend
    out = Path(args.out or ("runs/" + run_id))
    if out.exists() and any(out.iterdir()):
        raise SystemExit("Thư mục %s đã có dữ liệu. Chọn --out khác để không trộn kết quả." % out)
    out.mkdir(parents=True, exist_ok=True)

    first_cfg = _make_config(args, files[0])
    plat = "%dx%d" % (first_cfg.platform.total_nodes, first_cfg.platform.cores_per_node)
    with open(out / "config_resolved.json", "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "workload_files": files, "config": first_cfg}, f, indent=2,
                  default=lambda o: getattr(o, "__dict__", str(o)))
    with open(out / "env_info.json", "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run_id, "git_commit": _git_commit(), "python": sys.version.split()[0],
            "numpy": np.__version__, "platform": _platform.platform(), "argv": sys.argv,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)

    logger = BenchmarkLogger(output_dir=str(out))
    episodes: list[dict] = []
    ep_idx = 0
    with open(out / "steps.csv", "w", newline="", encoding="utf-8") as sf, \
            open(out / "jobs.csv", "w", newline="", encoding="utf-8") as jf:
        step_w, job_w = csv.writer(sf), csv.writer(jf)
        step_w.writerow(STEP_COLS)
        job_w.writerow(JOB_COLS)
        for wl in files:
            for name in args.policies:
                label = POLICY_LABELS[name]
                policy = build_policy(name, args.model)
                seeds = range(args.random_seeds) if name == "random" else [0]
                for seed in seeds:
                    cfg = _make_config(args, wl)
                    if args.backend == "real":
                        _set_batsim_workload(wl)
                    m = run_episode(cfg, policy, label, wl, seed, run_id, step_w, job_w)
                    ok = m["completed_jobs"] == m["expected_jobs"] and m["terminated"] == 1
                    print("[%s] %-12s %-22s seed=%d  jobs=%d/%d  wait=%.1f  util=%.3f  makespan=%.0f  steps=%d  invalid=%d%s" % (
                        "OK " if ok else "WARN", label, Path(wl).stem, seed, m["completed_jobs"], m["expected_jobs"],
                        m["avg_waiting_time"], m["utilization"], m["makespan"], m["num_steps"],
                        m["invalid_actions"], "" if ok else "  <-- episode không hoàn tất"))
                    logger.log_episode(ep_idx, m, experiment_id=run_id, policy=label,
                                       workload=Path(wl).stem, platform=plat, seed=seed)
                    episodes.append(dict(m, policy=label, workload=Path(wl).stem))
                    ep_idx += 1
                    sf.flush()
                    jf.flush()

    for label in dict.fromkeys(e["policy"] for e in episodes):
        eps = [e for e in episodes if e["policy"] == label]
        mean_m = {c: statistics.fmean(float(e[c]) for e in eps) for c in METRIC_COLS}
        mean_m["completed_jobs"] = int(round(mean_m["completed_jobs"]))
        mean_m["num_steps"] = int(round(mean_m["num_steps"]))
        mean_m["invalid_actions"] = int(sum(e["invalid_actions"] for e in eps))
        mean_m["terminated"] = statistics.fmean(e["terminated"] for e in eps)
        mean_m["truncated"] = statistics.fmean(e["truncated"] for e in eps)
        logger.log_summary(mean_m, experiment_id=run_id, policy=label,
                           workload="mean_of_%d_workloads" % len(files), platform=plat,
                           seed="n=%d" % len(eps))

    rows = write_comparison(out / "comparison_table.csv", episodes)
    print_table(rows)
    print("\nKết quả đã ghi vào: %s" % out)
    return out


if __name__ == "__main__":
    main()
