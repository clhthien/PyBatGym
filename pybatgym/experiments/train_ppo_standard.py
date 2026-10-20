"""Phase 2 + Real BatSim validation: Mock training with periodic real BatSim evaluation.
(Standard PPO version - No Action Masking)

Architecture:
  - PPO trains fast on MockAdapter (synthetic workload ~ medium_workload schedule)
  - Every eval_freq steps: RealEvalCallback runs 1 episode on actual BatSim 3.1.0
  - Final validation: N episodes on real BatSim after training converges

Prerequisites (inside Docker):
  # Terminal 1 — start BatSim service
  docker-compose up batsim

  # Terminal 2 — run training
  python3 pybatgym/experiments/train_ppo_standard.py
"""

from __future__ import annotations

import os
import time
import json
from pathlib import Path
from typing import Optional

import numpy as np
from torch.utils.tensorboard import SummaryWriter
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CallbackList

from pybatgym.config.base_config import PyBatGymConfig
from pybatgym.config.loader import load_preset
from pybatgym.envs import PyBatGymEnv
from pybatgym.callbacks import RealEvalCallback
from pybatgym.baselines import (
    run_baseline, sjf_policy, easy_backfilling_policy, fcfs_policy,
)


# ── Platform / workload paths ─────────────────────────────────────────────────

_WORKSPACE = Path("/workspace")
_PLATFORM  = _WORKSPACE / "data" / "platforms" / "medium_platform.xml"
_WORKLOAD  = _WORKSPACE / "data" / "workloads" / "medium_workload.json"
# ZMQ endpoint for real BatSim (docker-compose service name "batsim")
_BATSIM_SOCKET = os.environ.get("BATSIM_SOCKET", "tcp://*:28000")


# ── CompetitiveCallback (reused from phase2, inline here for self-containment) ─

class _MockEpisodeDiagnosticsCallback(BaseCallback):
    """Log MockAdapter episode health without stopping on SJF win-rate."""

    def __init__(
        self,
        expected_jobs: int,
        writers: dict[str, SummaryWriter],
        print_every: int = 1,
        max_timesteps: int = 2_000_000,
        save_path: Optional[str] = None,
        verbose: int = 1,
    ) -> None:
        super().__init__(verbose)
        self.expected_jobs = expected_jobs
        self.print_every = max(1, print_every)
        self.max_timesteps = max_timesteps
        self.save_path = save_path
        self.writers = writers
        self.writer = writers["PPO"]

        self._n_episodes = 0
        self._best_completed = -1
        self._start_time = 0.0

    def _on_training_start(self) -> None:
        self._start_time = time.time()
        if self.verbose >= 1:
            print(
                "  Mock diagnostics enabled: "
                "completed_jobs, makespan, avg_wait, utilization, total_reward"
            )

    def _on_step(self) -> bool:
        dones = self.locals.get("dones", [])
        infos = self.locals.get("infos", [])

        for i, done in enumerate(dones):
            if not done:
                continue
            env = self._get_env(i)
            info = infos[i] if i < len(infos) else {}
            if env is not None:
                self._n_episodes += 1
                self._collect(env, info)

        if self.num_timesteps >= self.max_timesteps:
            print(f"\n[STOP] Hard cap {self.max_timesteps:,} steps. Episodes={self._n_episodes}")
            return False
        return True

    def _get_env(self, idx: int = 0):
        vec_env = self.training_env
        return vec_env.envs[idx] if hasattr(vec_env, "envs") else None

    def _collect(self, env, info: dict) -> None:
        raw = getattr(env, "unwrapped", env)
        adapter = getattr(raw, "_adapter", None)
        if adapter is None:
            return

        metrics = info.get("episode_metrics", {})
        completed_count = int(metrics.get("completed_jobs", 0))
        makespan = float(metrics.get("makespan", 0.0))
        avg_wait = float(metrics.get("avg_waiting_time", 0.0))
        avg_sd = float(metrics.get("avg_bounded_slowdown", 0.0))
        util = float(metrics.get("utilization", 0.0))
        total_reward = float(metrics.get("total_reward", info.get("cumulative_reward", 0.0)))

        complete_ok = completed_count == self.expected_jobs
        status = "OK" if complete_ok else "INCOMPLETE"
        step = self.num_timesteps

        self.writer.add_scalar("Mock/Completed_Jobs", completed_count, step)
        self.writer.add_scalar("Mock/Makespan", makespan, step)
        self.writer.add_scalar("Mock/Avg_Waiting_Time", avg_wait, step)
        self.writer.add_scalar("Mock/Utilization", util, step)
        self.writer.add_scalar("Mock/Avg_Bounded_Slowdown", avg_sd, step)
        self.writer.add_scalar("Mock/Total_Reward", total_reward, step)
        self.writer.add_scalar("Training/Reward", total_reward, step)

        # Log baselines as reference lines
        for name in ["SJF", "FCFS", "EASY"]:
            w = self.writers.get(name)
            metrics_b = self.writers.get(f"{name}_metrics", {})
            if w is not None and hasattr(w, "add_scalar"):
                val_wait = metrics_b.get("avg_waiting_time", 0)
                val_util = metrics_b.get("avg_utilization", 0)
                val_make = metrics_b.get("avg_makespan", 0)
                val_sd = metrics_b.get("avg_slowdown", 0)
                w.add_scalar("Mock/Avg_Waiting_Time", val_wait, step)
                w.add_scalar("Mock/Utilization", val_util, step)
                w.add_scalar("Mock/Makespan", val_make, step)
                w.add_scalar("Mock/Avg_Bounded_Slowdown", val_sd, step)

        if completed_count > self._best_completed and self.save_path:
            self._best_completed = completed_count
            self.model.save(self.save_path + "_best")

        if self.verbose >= 1 and self._n_episodes % self.print_every == 0:
            elapsed = time.time() - self._start_time
            print(
                f"  [Mock ep {self._n_episodes:>4}] "
                f"completed={completed_count}/{self.expected_jobs} {status:<10} "
                f"wait={avg_wait:>8.2f}s  "
                f"util={util:>6.1%}  "
                f"reward={total_reward:>+10.4f}  "
                f"steps={step:>8,}"
            )

    def _on_training_end(self) -> None:
        self.writer.close()


# ── Env factories ─────────────────────────────────────────────────────────────

def make_mock_env(workload_path: str, preset: str = "medium_batsim") -> PyBatGymEnv:
    """MockAdapter training env — fast, no BatSim needed."""
    config = load_preset(preset)
    config.workload.trace_path = workload_path
    return PyBatGymEnv(config=config)


def make_real_config(preset: str = "medium_batsim") -> PyBatGymConfig:
    """RealBatsimAdapter config — connects to docker-compose batsim service."""
    config = load_preset(preset)
    config.mode = "real"
    return config


# ── Final validation on real BatSim ──────────────────────────────────────────

def validate_on_real(model: PPO, real_config: PyBatGymConfig, num_episodes: int = 3) -> dict:
    """Run trained PPO on real BatSim and return averaged metrics."""
    print(f"\n  Running {num_episodes} validation episode(s) on real BatSim...")

    from pybatgym.plugins.benchmark_logger import BenchmarkLogger
    logger = BenchmarkLogger()
    
    policy_name = "PPO_Standard"
    # Resolve paths via adapter logic to get actual names
    env_tmp = PyBatGymEnv(config=real_config)
    p_path, w_path = env_tmp._adapter._resolve_paths()
    platform_name = Path(p_path).stem
    workload_name = Path(w_path).stem
    env_tmp.close()

    waits, utils, sds, rewards = [], [], [], []
    env = None
    try:
        env = PyBatGymEnv(config=real_config)
        for ep in range(num_episodes):
            seed = 200 + ep
            obs, _ = env.reset(seed=seed)
            done, ep_reward, steps = False, 0.0, 0
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, _ = env.step(int(action))
                ep_reward += reward
                steps += 1
                done = terminated or truncated

            raw = getattr(env, "unwrapped", env)
            adapter = getattr(raw, "_adapter", None)
            if adapter is None: continue
            completed = adapter.get_completed_jobs()
            if not completed: continue
            
            n = len(completed)
            makespan = adapter.get_current_time()
            tc = raw._config.platform.total_cores
            
            avg_wait = sum(j.waiting_time for j in completed) / n
            avg_sd = sum(j.bounded_slowdown for j in completed) / n
            util = 0.0
            if makespan > 0 and tc > 0:
                busy = sum(j.actual_runtime * j.requested_resources for j in completed)
                util = busy / (makespan * tc)
            
            ep_metrics = {
                "total_reward": ep_reward,
                "completed_jobs": n,
                "avg_waiting_time": avg_wait,
                "avg_bounded_slowdown": avg_sd,
                "utilization": util,
                "makespan": makespan,
                "num_steps": steps,
                "terminated": int(terminated),
                "truncated": int(truncated),
            }
            
            logger.log_episode(
                episode_idx=ep,
                metrics=ep_metrics,
                policy=policy_name,
                workload=workload_name,
                platform=platform_name,
                seed=seed
            )
        
            waits.append(avg_wait)
            utils.append(util)
            sds.append(avg_sd)
            rewards.append(ep_reward)
            print(f"    ep {ep+1}: wait={waits[-1]:.1f}s  util={utils[-1] if utils else 0:.1%}  reward={ep_reward:.2f}")
    except Exception as exc:
        print(f"  [Real validation] Failed: {exc}")
        return {}
    finally:
        if env is not None:
            try: env.close()
            except: pass

    avg_metrics = {
        "avg_waiting_time": float(np.mean(waits)) if waits else 0.0,
        "avg_slowdown":     float(np.mean(sds))   if sds   else 0.0,
        "avg_utilization":  float(np.mean(utils))  if utils  else 0.0,
        "avg_reward":       float(np.mean(rewards)) if rewards else 0.0,
    }
    
    # Log summary to CSV
    summary_metrics = {
        "total_reward": avg_metrics["avg_reward"],
        "completed_jobs": n if waits else 0,
        "avg_waiting_time": avg_metrics["avg_waiting_time"],
        "avg_bounded_slowdown": avg_metrics["avg_slowdown"],
        "utilization": avg_metrics["avg_utilization"],
        "makespan": makespan if waits else 0,
        "num_steps": steps if waits else 0,
    }
    logger.log_summary(
        metrics=summary_metrics,
        policy=policy_name,
        workload=workload_name,
        platform=platform_name
    )

    return avg_metrics


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    preset = "medium_batsim"
    print("=" * 70)
    print("  PyBatGym: Standard PPO Training + Real BatSim Validation")
    print("=" * 70)

    # Resolve paths and job count
    if not _WORKLOAD.exists():
        print(f"[ERROR] Workload not found: {_WORKLOAD}")
        return

    with open(_WORKLOAD, "r") as f:
        workload_data = json.load(f)
        num_jobs = len(workload_data.get("jobs", []))
    print(f"  Workload: {_WORKLOAD} ({num_jobs} jobs)")

    # ── Compute heuristic baselines (Mock, fast) ────────────────────────────
    print("\n[1/5] Computing heuristic baselines on Mock...")
    _tmp = make_mock_env(str(_WORKLOAD), preset=preset)
    fcfs_m = run_baseline(_tmp, fcfs_policy,             num_episodes=3)
    sjf_m  = run_baseline(_tmp, sjf_policy,              num_episodes=3)
    easy_m = run_baseline(_tmp, easy_backfilling_policy, num_episodes=3)
    _tmp.close()

    sjf_wait = sjf_m["avg_waiting_time"]
    print(f"  FCFS wait={fcfs_m['avg_waiting_time']:.1f}s  util={fcfs_m['avg_utilization']:.1%}")
    print(f"  SJF  wait={sjf_wait:.1f}s  util={sjf_m['avg_utilization']:.1%}")
    print(f"  EASY wait={easy_m['avg_waiting_time']:.1f}s  util={easy_m['avg_utilization']:.1%}")

    # ── Create envs ─────────────────────────────────────────────────────────
    print("\n[2/5] Creating Mock training env...")
    env = make_mock_env(str(_WORKLOAD), preset=preset)
    
    real_config = make_real_config(preset=preset)
    real_config.workload.trace_path = str(_WORKLOAD)
    real_config.workload.num_jobs = num_jobs

    # ── Build PPO model ──────────────────────────────────────────────────────
    print("\n[3/5] Building PPO model...")
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    save_path = str(model_dir / "ppo_standard")

    model = PPO(
        "MultiInputPolicy",
        env,
        verbose=0,
        n_steps=512,
        batch_size=128,
        learning_rate=3e-4,
        ent_coef=0.01,
        clip_range=0.2,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        tensorboard_log="logs/tensorboard_standard",
    )

    # ── Callbacks ────────────────────────────────────────────────────────────
    baselines = {"fcfs": fcfs_m, "sjf": sjf_m, "easy": easy_m}
    run_id = int(time.time())
    log_dir = f"logs/tensorboard_standard/PPO_Run_{run_id}"

    writers = {
        "PPO": SummaryWriter(f"{log_dir}/PPO"),
        "SJF": SummaryWriter(f"{log_dir}/SJF"),
        "FCFS": SummaryWriter(f"{log_dir}/FCFS"),
        "EASY": SummaryWriter(f"{log_dir}/EASY"),
        "SJF_metrics": sjf_m,
        "FCFS_metrics": fcfs_m,
        "EASY_metrics": easy_m,
    }

    diagnostics_cb = _MockEpisodeDiagnosticsCallback(
        expected_jobs=num_jobs,
        writers=writers,
        print_every=1,
        max_timesteps=1_000_000,
        save_path=save_path,
        verbose=1,
    )

    real_eval_cb = RealEvalCallback(
        real_config=real_config,
        eval_freq=25_000,
        eval_episodes=2,
        baselines=baselines,
        verbose=1,
    )
    real_eval_cb.writers = writers

    # ── Train ────────────────────────────────────────────────────────────────
    print("\n[4/5] Training (Mock + periodic Real BatSim eval)...")
    t0 = time.time()
    model.learn(
        total_timesteps=1_000_000,
        callback=CallbackList([diagnostics_cb, real_eval_cb]),
    )
    elapsed = time.time() - t0

    model.save(save_path)
    print(f"\n  Final model : {save_path}.zip")

    # ── Final real BatSim validation ─────────────────────────────────────────
    print("\n[5/5] Final validation on REAL BatSim (3 episodes)...")
    best_path = save_path + "_best.zip"
    val_model = PPO.load(best_path, env=env) if Path(best_path).exists() else model
    real_m = validate_on_real(val_model, real_config, num_episodes=3)
    
    if real_m:
        print(f"\n{'='*70}")
        print(f"  FINAL RESULTS (Real BatSim)")
        print(f"  Metric                     | SJF (Mock) | PPO (Real)")
        print(f"  Wait Time (s)              | {sjf_wait:>10.2f} | {real_m['avg_waiting_time']:>10.2f}")
        print(f"  Utilization (%)            | {sjf_m['avg_utilization']:>9.1%} | {real_m['avg_utilization']:>9.1%}")
        print(f"{'='*70}")

    env.close()


if __name__ == "__main__":
    main()
