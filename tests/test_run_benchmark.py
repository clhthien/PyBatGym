"""Test benchmark runner: artifact đầy đủ, nhất quán và tái lập được."""
import csv
import json
import random
from pathlib import Path

import pytest

from pybatgym.experiments.run_benchmark import main

N_JOBS = 20


def _write_workload(path: Path, seed: int) -> None:
    rng = random.Random(seed)
    t, jobs, profiles = 0.0, [], {}
    for i in range(N_JOBS):
        t += rng.expovariate(0.2)
        walltime = round(rng.uniform(5, 60), 2)
        profiles["delay_%d" % i] = {"type": "delay", "delay": round(walltime * 0.7, 2)}
        jobs.append({"id": i, "subtime": round(t, 2), "walltime": walltime,
                     "res": rng.choice([1, 2, 4, 8, 16, 32]), "profile": "delay_%d" % i})
    path.write_text(json.dumps({"nb_res": 32, "jobs": jobs, "profiles": profiles}), encoding="utf-8")


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _run(tmp_path: Path, name: str) -> Path:
    wl = tmp_path / "wl"
    wl.mkdir(exist_ok=True)
    for s in (0, 1):
        _write_workload(wl / ("w%d.json" % s), s)
    return main(["--preset", "medium_batsim", "--workloads", str(wl / "w*.json"),
                 "--policies", "fcfs", "sjf", "easy", "random", "--random-seeds", "2",
                 "--out", str(tmp_path / name)])


def test_runner_writes_complete_and_consistent_artifacts(tmp_path):
    out = _run(tmp_path, "run1")
    for name in ("config_resolved.json", "env_info.json", "per_episode_metrics.csv",
                 "benchmark_summary.csv", "comparison_table.csv", "steps.csv", "jobs.csv"):
        assert (out / name).is_file(), name

    episodes = _rows(out / "per_episode_metrics.csv")
    assert len(episodes) == 2 * (1 + 1 + 1 + 2)  # 2 workload x (fcfs, sjf, easy, random x2 seed)
    assert all(e["completed_jobs"] == str(N_JOBS) and e["terminated"] == "1" for e in episodes)
    assert all(e["invalid_actions"] == "0" for e in episodes)
    assert {r["policy"] for r in _rows(out / "benchmark_summary.csv")} == {"FCFS", "SJF", "EASY", "Random"}
    assert len(_rows(out / "jobs.csv")) == len(episodes) * N_JOBS

    # tổng reward từng bước phải khớp total_reward của episode; reward = tổng các thành phần + bonus cuối
    sums = {}
    for r in _rows(out / "steps.csv"):
        comp = sum(float(r[k]) for k in ("delta_utilization", "completed_wait", "completed_slowdown",
                                         "schedule_bonus", "wait_penalty", "idle_penalty"))
        assert abs(float(r["reward"]) - comp - float(r["episode_bonus"])) < 1e-4
        key = (r["policy"], r["workload"], r["seed"])
        sums[key] = sums.get(key, 0.0) + float(r["reward"])
    for e in episodes:
        assert abs(sums[(e["policy"], e["workload"], e["seed"])] - float(e["total_reward"])) < 1e-3


def test_runner_is_reproducible(tmp_path):
    a = _rows(_run(tmp_path, "a") / "steps.csv")
    b = _rows(_run(tmp_path, "b") / "steps.csv")
    keys = ("policy", "workload", "seed", "step", "action", "reward")
    assert [tuple(r[k] for k in keys) for r in a] == [tuple(r[k] for k in keys) for r in b]


def test_runner_refuses_to_mix_results_in_non_empty_dir(tmp_path):
    out = _run(tmp_path, "run1")
    with pytest.raises(SystemExit):
        main(["--workloads", str(tmp_path / "wl" / "w0.json"), "--policies", "fcfs", "--out", str(out)])
