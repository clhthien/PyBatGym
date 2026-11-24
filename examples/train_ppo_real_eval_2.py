"""Phase 2 + Real BatSim validation: Mock training with periodic real BatSim evaluation.

Architecture:
  - PPO trains fast on MockAdapter (synthetic workload ~ medium_workload schedule)
  - Every eval_freq steps: RealEvalCallback runs 1 episode on actual BatSim 3.1.0
  - Competitive stopping: win_rate vs SJF >= 80% over last 50 Mock episodes
  - Final validation: N episodes on real BatSim after training converges

Prerequisites (inside Docker):
  # Terminal 1 — start BatSim service
  docker-compose up batsim

  # Terminal 2 — run training
  source /workspace/.venv_ubuntu/bin/activate
  python3 examples/train_ppo_real_eval.py

  # Terminal 3 — TensorBoard
  tensorboard --logdir logs/tensorboard_real_eval --bind_all --port 6006

TensorBoard metrics:
  HPC/*        — from Mock (every episode, fast)
  Real/*       — from real BatSim (every eval_freq steps)
  Baseline/*   — SJF/FCFS/EASY reference lines
"""

from __future__ import annotations

import os
import time
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
_PLATFORM  = _WORKSPACE / "data" / "platforms" / "small_platform.xml"
_WORKLOAD  = _WORKSPACE / "data" / "workloads" / "medium_workload.json"
# ZMQ endpoint for real BatSim (docker-compose service name "batsim")
_BATSIM_SOCKET = os.environ.get("BATSIM_SOCKET", "tcp://*:28000")


# ── CompetitiveCallback (reused from phase2, inline here for self-containment) ─

class _CompetitiveCallback(BaseCallback):
    """Stop training when PPO beats SJF win_rate >= threshold."""

    def __init__(
        self,
        baselines: dict,
        log_dir: str,
        win_window: int = 50,
        win_rate_threshold: float = 0.80,
        min_episodes: int = 100,
        max_timesteps: int = 2_000_000,
        check_every: int = 2000,
        save_path: Optional[str] = None,
        verbose: int = 1,
    ) -> None:
        super().__init__(verbose)
        self.baselines = baselines
        self.sjf_wait = baselines.get("sjf", {}).get("avg_waiting_time", 0.0)
        self.sjf_util = baselines.get("sjf", {}).get("avg_utilization", 0.0)
        self.win_window = win_window
        self.win_rate_threshold = win_rate_threshold
        self.min_episodes = min_episodes
        self.max_timesteps = max_timesteps
        self.check_every = check_every
        self.save_path = save_path
        
        # Multi-run writers for overlay charts
        self.writers = {
            "PPO": SummaryWriter(f"{log_dir}/Agent"),
            "SJF": SummaryWriter(f"{log_dir}/SJF"),
            "FCFS": SummaryWriter(f"{log_dir}/FCFS"),
            "EASY": SummaryWriter(f"{log_dir}/EASY"),
        }

        self._wins: list[bool] = []
        self._episode_waits: list[float] = []
        self._episode_utils: list[float] = []
        self._n_episodes = 0
        self._last_check = 0
        self._best_win_rate = 0.0
        self._start_time = 0.0
        self.sjf_util = 0.0  # set after baseline computation

    def _on_training_start(self) -> None:
        self._start_time = time.time()
        # Clean start: log initial baseline points at step 0 for horizontal line origin
        for name, metrics in self.baselines.items():
            tag = name.upper()
            if tag in self.writers:
                self.writers[tag].add_scalar("Comparison/Waiting_Time", metrics.get("avg_waiting_time", 0), 0)
                self.writers[tag].add_scalar("Comparison/Utilization", metrics.get("avg_utilization", 0), 0)
                self.writers[tag].add_scalar("Comparison/Slowdown", metrics.get("avg_slowdown", 0), 0)

    def _on_step(self) -> bool:
        dones = self.locals.get("dones", [])
        for i, done in enumerate(dones):
            if not done:
                continue
            self._n_episodes += 1
            env = self._get_env(i)
            if env is not None:
                self._collect(env)

        if self.num_timesteps >= self.max_timesteps:
            print(f"\n[STOP] Hard cap {self.max_timesteps:,} steps. Episodes={self._n_episodes}")
            return False

        if self._n_episodes < self.min_episodes:
            return True
        if self.num_timesteps - self._last_check < self.check_every:
            return True
        self._last_check = self.num_timesteps
        return self._check()

    def _get_env(self, idx: int = 0):
        vec_env = self.training_env
        return vec_env.envs[idx] if hasattr(vec_env, "envs") else None

    def _collect(self, env) -> None:
        raw = getattr(env, "unwrapped", env)
        adapter = getattr(raw, "_adapter", None)
        if adapter is None:
            return
        completed = adapter.get_completed_jobs()
        if not completed:
            return

        n = len(completed)
        avg_wait = sum(j.waiting_time for j in completed) / n
        makespan = adapter.get_current_time()
        total_cores = raw._config.platform.total_cores
        avg_sd = sum(j.bounded_slowdown for j in completed) / n
        util = 0.0
        if makespan > 0 and total_cores > 0:
            busy = sum(j.actual_runtime * j.requested_resources for j in completed)
            util = min(1.0, busy / (makespan * total_cores))  # clamp to [0,1]

        won = avg_wait < self.sjf_wait
        self._wins.append(won)
        self._episode_waits.append(avg_wait)
        self._episode_utils.append(util)

        recent = self._wins[-self.win_window:]
        win_rate = sum(recent) / len(recent)
        advantage = (self.sjf_wait - avg_wait) / max(self.sjf_wait, 1e-8)

        # --- Log Overlay Metrics (This is the KEY for combined charts) ---
        step = self.num_timesteps
        # We use identical tag names across different writers so TB overlays them
        self.writers["PPO"].add_scalar("Comparison/Waiting_Time", avg_wait, step)
        self.writers["PPO"].add_scalar("Comparison/Utilization", util, step)
        self.writers["PPO"].add_scalar("Comparison/Slowdown", avg_sd, step)

        for name, metrics in self.baselines.items():
            tag = name.upper()
            if tag in self.writers:
                # Log baseline value at the SAME step as the Agent for a horizontal line
                if "avg_waiting_time" in metrics:
                    self.writers[tag].add_scalar("Comparison/Waiting_Time", metrics["avg_waiting_time"], step)
                if "avg_utilization" in metrics:
                    self.writers[tag].add_scalar("Comparison/Utilization", metrics["avg_utilization"], step)
                if "avg_slowdown" in metrics:
                    self.writers[tag].add_scalar("Comparison/Slowdown", metrics["avg_slowdown"], step)

        if win_rate > self._best_win_rate and self.save_path:
            self._best_win_rate = win_rate
            self.model.save(self.save_path + "_best")

    def _check(self) -> bool:
        if len(self._wins) < self.win_window:
            return True
        recent = self._wins[-self.win_window:]
        win_rate = sum(recent) / len(recent)
        avg_wait = float(np.mean(self._episode_waits[-self.win_window:]))
        elapsed = time.time() - self._start_time

        if self.verbose >= 1:
            print(
                f"  [{self.num_timesteps:>9,}] "
                f"eps={self._n_episodes:>4}  "
                f"win_rate={win_rate:.0%}  "
                f"avg_wait={avg_wait:.1f} s_sim  "
                f"SJF_wait={self.sjf_wait:.1f} s_sim  "
                f"wall_elapsed={elapsed:.0f} s_wall"
            )

        if win_rate >= self.win_rate_threshold:
            recent_util = float(np.mean(self._episode_utils[-self.win_window:])) if self._episode_utils else 0.0
            # Guard: only stop if utilization is also reasonably high
            # (prevents trivial win when scheduler WAIT-s and SJF baseline is broken)
            if self.sjf_util > 0 and recent_util < self.sjf_util * 0.8:
                if self.verbose >= 1:
                    print(
                        f"  [SKIP STOP] win_rate={win_rate:.0%} but util={recent_util:.1%} "
                        f"< 80% of SJF util={self.sjf_util:.1%} — model not truly better"
                    )
                return True
            print(
                f"\n{'='*70}\n"
                f"[TARGET REACHED] Mock PPO beats SJF!\n"
                f"  Win rate  : {win_rate:.1%}\n"
                f"  avg_wait  : {avg_wait:.2f} s_sim vs SJF={self.sjf_wait:.2f} s_sim\n"
                f"  util      : {recent_util:.1%}\n"
                f"  Episodes  : {self._n_episodes}\n"
                f"{'='*70}"
            )
            return False
        return True


# ── Env factories ─────────────────────────────────────────────────────────────

def make_mock_env(workload_path: str) -> PyBatGymEnv:
    """MockAdapter training env — fast, no BatSim needed."""
    config = load_preset("small_batsim")
    config.workload.trace_path = workload_path
    return PyBatGymEnv(config=config)


def make_real_config() -> PyBatGymConfig:
    """RealBatsimAdapter config — connects to docker-compose batsim service."""
    config = load_preset("small_batsim")
    config.mode = "real"
    return config


# ── Final validation on real BatSim ──────────────────────────────────────────

def validate_on_real(model: PPO, real_config: PyBatGymConfig, num_episodes: int = 3) -> dict:
    """Run trained PPO on real BatSim and return averaged metrics."""
    print(f"\n  Running {num_episodes} validation episode(s) on real BatSim...")

    waits, utils, sds, rewards = [], [], [], []
    env = None
    try:
        env = PyBatGymEnv(config=real_config)
        for ep in range(num_episodes):
            obs, _ = env.reset(seed=200 + ep)
            done, ep_reward = False, 0.0
            while not done:
                action, _ = model.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, _ = env.step(int(action))
                ep_reward += reward
                done = terminated or truncated

            raw = getattr(env, "unwrapped", env)
            adapter = getattr(raw, "_adapter", None)
            if adapter is None:
                continue
            completed = adapter.get_completed_jobs()
            if not completed:
                continue
            n = len(completed)
            makespan = adapter.get_current_time()
            tc = raw._config.platform.total_cores
            waits.append(sum(j.waiting_time for j in completed) / n)
            sds.append(sum(j.bounded_slowdown for j in completed) / n)
            if makespan > 0 and tc > 0:
                busy = sum(j.actual_runtime * j.requested_resources for j in completed)
                utils.append(busy / (makespan * tc))
            rewards.append(ep_reward)
            print(f"    ep {ep+1}: wait={waits[-1]:.1f} s_sim  util={utils[-1] if utils else 0:.1%}  reward={ep_reward:.2f}")
    except Exception as exc:
        print(f"  [Real validation] Failed: {exc}")
        return {}
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass

    n = max(len(waits), 1)
    return {
        "avg_waiting_time": float(np.mean(waits)) if waits else 0.0,
        "avg_slowdown":     float(np.mean(sds))   if sds   else 0.0,
        "avg_utilization":  float(np.mean(utils))  if utils  else 0.0,
        "avg_reward":       float(np.mean(rewards)) if rewards else 0.0,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("  PyBatGym: Mock Training + Real BatSim Validation")
    print("  PPO trains on MockAdapter; real BatSim eval every 50k steps")
    print("=" * 70)

    # Validate paths
    if not _WORKLOAD.exists():
        print(f"[ERROR] Workload not found: {_WORKLOAD}")
        return
    if not _PLATFORM.exists():
        print(f"[ERROR] Platform not found: {_PLATFORM}")
        return

    # ── Compute heuristic baselines (Mock, fast) ────────────────────────────
    print("\n[1/5] Computing heuristic baselines on Mock...")
    _tmp = make_mock_env(str(_WORKLOAD))
    fcfs_m = run_baseline(_tmp, fcfs_policy,             num_episodes=3)
    sjf_m  = run_baseline(_tmp, sjf_policy,              num_episodes=3)
    easy_m = run_baseline(_tmp, easy_backfilling_policy, num_episodes=3)
    _tmp.close()

    sjf_wait = sjf_m["avg_waiting_time"]
    sjf_util = sjf_m["avg_utilization"]
    print(f"  FCFS  wait={fcfs_m['avg_waiting_time']:.1f} s_sim  sd={fcfs_m['avg_slowdown']:.2f}  util={fcfs_m['avg_utilization']:.1%}")
    print(f"  SJF   wait={sjf_wait:.1f} s_sim  sd={sjf_m['avg_slowdown']:.2f}  util={sjf_util:.1%}")
    print(f"  EASY  wait={easy_m['avg_waiting_time']:.1f} s_sim  sd={easy_m['avg_slowdown']:.2f}  util={easy_m['avg_utilization']:.1%}")
    if sjf_util < 0.05:
        print(f"  ⚠️  SJF util={sjf_util:.1%} is suspiciously low (< 5%). Check workload/platform sizing.")
    print(f"\n  → PPO target: win_rate > 80% vs SJF wait={sjf_wait:.1f} s_sim  util >= {sjf_util*0.8:.1%}")

    # ── Create envs ─────────────────────────────────────────────────────────
    print("\n[2/5] Creating Mock training env...")
    env = make_mock_env(str(_WORKLOAD))
    real_config = make_real_config()

    # ── Build PPO model ──────────────────────────────────────────────────────
    print("\n[3/5] Building PPO model...")
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    save_path = str(model_dir / "ppo_real_eval")

    model = PPO(
        "MultiInputPolicy",
        env,
        verbose=0,
        n_steps=512,
        batch_size=128,
        learning_rate=3e-4,
        ent_coef=0.02,
        clip_range=0.2,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        tensorboard_log="logs/tensorboard_comparison",
    )
    print("  Policy: MultiInputPolicy  n_steps=512  batch=128  lr=3e-4  ent_coef=0.02")

    # ── Callbacks ────────────────────────────────────────────────────────────
    baselines = {
        "fcfs": fcfs_m,
        "sjf": sjf_m,
        "easy": easy_m,
    }

    # Use a unique but clean run name
    run_id = int(time.time())
    log_dir = f"logs/tensorboard_comparison/PPO_Run_{run_id}"

    competitive_cb = _CompetitiveCallback(
        baselines=baselines,
        log_dir=log_dir,
        win_window=50,
        win_rate_threshold=0.80,
        min_episodes=100,
        max_timesteps=2_000_000,
        check_every=2000,
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
    # Share writers for Real evaluation overlay as well
    real_eval_cb.writers = competitive_cb.writers

    # ── Train ────────────────────────────────────────────────────────────────
    print("\n[4/5] Training (Mock + periodic Real BatSim eval)...")
    print(f"  Max steps     : 2,000,000")
    print(f"  Real eval     : every 25,000 steps (requires docker-compose up batsim)")
    print(f"  BatSim socket : {_BATSIM_SOCKET}")
    print(f"  Platform      : {_PLATFORM}")
    print(f"  Workload      : {_WORKLOAD} (100 jobs, max_cores=4)")
    print(f"\n{'─'*70}")

    t0 = time.time()
    model.learn(
        total_timesteps=2_000_000,
        callback=CallbackList([competitive_cb, real_eval_cb]),
        reset_num_timesteps=True,
    )
    train_time = time.time() - t0

    model.save(save_path)
    print(f"\n  Final model : {save_path}.zip")
    print(f"  Training    : {train_time:.0f} s_wall ({train_time/60:.1f} min)")
    print(f"  Steps       : {model.num_timesteps:,}")
    print(f"  Episodes    : {competitive_cb._n_episodes}")
    print(f"  Best Mock win rate vs SJF: {competitive_cb._best_win_rate:.1%}")

    # ── Final real BatSim validation ─────────────────────────────────────────
    print("\n[5/5] Final validation on REAL BatSim (3 episodes)...")
    best_path = save_path + "_best.zip"
    val_model = PPO.load(best_path, env=env) if Path(best_path).exists() else model
    real_m = validate_on_real(val_model, real_config, num_episodes=3)

    if real_m:
        print(f"\n{'='*70}")
        print(f"  FINAL RESULTS (Real BatSim 3.1.0 — ground truth)")
        print(f"{'─'*70}")
        print(f"  {'Metric':<28} | {'Mock SJF':>10} | {'PPO (Real)':>12}")
        print(f"{'─'*70}")
        print(f"  {'Avg Waiting Time (s_sim)':<28} | {sjf_wait:>10.2f} | {real_m['avg_waiting_time']:>12.2f}")
        print(f"  {'Avg Slowdown':<28} | {sjf_m['avg_slowdown']:>10.2f} | {real_m['avg_slowdown']:>12.2f}")
        print(f"  {'Avg Utilization (%)':<28} | {sjf_m['avg_utilization']:>9.1%}  | {real_m['avg_utilization']:>11.1%}")
        print(f"{'='*70}")

    else:
        print("  Real BatSim validation skipped (BatSim unavailable).")

    print(f"\n  TensorBoard: tensorboard --logdir logs/tensorboard_real_eval --bind_all --port 6006")
    env.close()


if __name__ == "__main__":
    main()
