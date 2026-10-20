from __future__ import annotations

import os
import time
import json
from pathlib import Path
from typing import Optional

import numpy as np
from torch.utils.tensorboard import SummaryWriter
from sb3_contrib import MaskablePPO
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
    """Log MockAdapter episode health without stopping on SJF win-rate.

    This callback is intentionally diagnostic-only: it verifies whether each
    mock episode completes the expected workload and prints the core metrics
    needed to decide if PPO training is meaningful.
    """

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
        self.writer = writers["PPO"]  # Default to PPO writer for diagnostics

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
        self.writer.add_scalar("Mock/Expected_Jobs", self.expected_jobs, step)
        self.writer.add_scalar("Mock/Makespan", makespan, step)
        self.writer.add_scalar("Mock/Avg_Waiting_Time", avg_wait, step)
        self.writer.add_scalar("Mock/Avg_Bounded_Slowdown", avg_sd, step)
        self.writer.add_scalar("Mock/Utilization", util, step)
        self.writer.add_scalar("Mock/Total_Reward", total_reward, step)
        self.writer.add_scalar("Training/Reward", total_reward, step)
        self.writer.add_scalar("Mock/Completed_All_Jobs", 1.0 if complete_ok else 0.0, step)

        # Log baselines as reference lines in the same "Mock" tags
        for name in ["SJF", "FCFS", "EASY"]:
            w = self.writers.get(name)
            metrics_b = self.writers.get(f"{name}_metrics", {}) # If you use this pattern
            # Or if writers keys are already the dicts in some contexts
            if w is not None and hasattr(w, "add_scalar"):
                # Fallback to metrics from dict if available
                m = self.writers.get(f"{name}_metrics", {})
                val_wait = m.get("avg_waiting_time", 0)
                val_util = m.get("avg_utilization", 0)
                val_make = m.get("avg_makespan", 0)
                val_sd = m.get("avg_slowdown", 0)
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
                f"makespan={makespan:>8.2f}s  "
                f"avg_wait={avg_wait:>8.2f}s  "
                f"util={util:>6.1%}  "
                f"reward={total_reward:>+10.4f}  "
                f"steps={step:>8,}  "
                f"t={elapsed:.0f}s"
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

def validate_on_real(model: MaskablePPO, real_config: PyBatGymConfig, num_episodes: int = 3) -> dict:
    """Run trained PPO on real BatSim and return averaged metrics."""
    print(f"\n  Running {num_episodes} validation episode(s) on real BatSim...")

    from pybatgym.plugins.benchmark_logger import BenchmarkLogger
    logger = BenchmarkLogger()
    
    policy_name = "PPO_Maskable"
    # Resolve paths via adapter logic to get actual names
    env_tmp = PyBatGymEnv(config=real_config)
    p_path, w_path = env_tmp._adapter._resolve_paths()
    platform_name = Path(p_path).stem
    workload_name = Path(w_path).stem
    env_tmp.close()

    waits, utils, sds, rewards = [], [], [], []
    makespans, step_counts, completed_counts, terms, truncs = [], [], [], [], []

    env = None
    try:
        env = PyBatGymEnv(config=real_config)
        for ep in range(num_episodes):
            seed = 200 + ep
            obs, _ = env.reset(seed=seed)
            done, ep_reward, steps = False, 0.0, 0
            while not done:
                # Robust predict call: handle both standard PPO and MaskablePPO
                action_masks = obs["action_mask"] if isinstance(obs, dict) and "action_mask" in obs else None
                action, _ = model.predict(obs, deterministic=True, action_masks=action_masks)
                
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

            makespans.append(makespan)
            step_counts.append(steps)
            completed_counts.append(n)
            terms.append(int(terminated))
            truncs.append(int(truncated))
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
        "completed_jobs": int(round(np.mean(completed_counts))) if completed_counts else 0,
        "avg_waiting_time": avg_metrics["avg_waiting_time"],
        "avg_bounded_slowdown": avg_metrics["avg_slowdown"],
        "utilization": avg_metrics["avg_utilization"],
        "makespan": float(np.mean(makespans)) if makespans else 0.0,
        "num_steps": int(round(np.mean(step_counts))) if step_counts else 0,
        "terminated": float(np.mean(terms)) if terms else 0.0,   # tỉ lệ episode kết thúc tự nhiên
        "truncated": float(np.mean(truncs)) if truncs else 0.0,
    }
    logger.log_summary(
        metrics=summary_metrics,
        policy=policy_name,
        workload=workload_name,
        platform=platform_name,
        seed=f"200-{200 + num_episodes - 1}",
    )

    return avg_metrics


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    preset = "medium_batsim"
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
    _tmp = make_mock_env(str(_WORKLOAD), preset=preset)
    fcfs_m = run_baseline(_tmp, fcfs_policy,             num_episodes=3)
    sjf_m  = run_baseline(_tmp, sjf_policy,              num_episodes=3)
    easy_m = run_baseline(_tmp, easy_backfilling_policy, num_episodes=3)
    _tmp.close()

    sjf_wait = sjf_m["avg_waiting_time"]
    sjf_util = sjf_m["avg_utilization"]
    print(f"  FCFS  wait={fcfs_m['avg_waiting_time']:.1f}  sd={fcfs_m['avg_slowdown']:.2f}  util={fcfs_m['avg_utilization']:.1%}")
    print(f"  SJF   wait={sjf_wait:.1f}  sd={sjf_m['avg_slowdown']:.2f}  util={sjf_util:.1%}")
    print(f"  EASY  wait={easy_m['avg_waiting_time']:.1f}  sd={easy_m['avg_slowdown']:.2f}  util={easy_m['avg_utilization']:.1%}")
    if sjf_util < 0.05:
        print(f"  ⚠️  SJF util={sjf_util:.1%} is suspiciously low (< 5%). Check workload/platform sizing.")
    print(f"\n  → PPO target: win_rate > 80% vs SJF wait={sjf_wait:.1f}s  util >= {sjf_util*0.8:.1%}")

    # ── Resolve workload and count jobs ─────────────────────────────────────
    workload_path = Path(_WORKLOAD)
    if not workload_path.is_absolute():
        workload_path = _WORKSPACE / workload_path
    
    if not workload_path.exists():
        print(f"[ERROR] Workload not found: {workload_path}")
        return

    with open(workload_path, "r") as f:
        workload_data = json.load(f)
        num_jobs = len(workload_data.get("jobs", []))
    print(f"  Workload size: {num_jobs} jobs")

    # ── Load Configuration ───────────────────────────────────────────────────
    print(f"[1/5] Loading config preset: {preset}...")
    real_config = load_preset(preset)
    real_config.mode = "real"          # ← BẮT BUỘC: dùng RealBatsimAdapter
    real_config.workload.trace_path = str(workload_path)
    real_config.workload.num_jobs = num_jobs

    # ── Create envs ─────────────────────────────────────────────────────────
    print("\n[2/5] Creating Mock training env...")
    env = make_mock_env(str(workload_path), preset=preset)

    # ── Build PPO model ──────────────────────────────────────────────────────
    print("\n[3/5] Building PPO model...")
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)
    save_path = str(model_dir / "ppo_real_eval")

    model = MaskablePPO(
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

    # Create unified writers for multi-run overlay on TensorBoard
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
    # Share writers for Real evaluation overlay
    real_eval_cb.writers = writers

    # ── Train ────────────────────────────────────────────────────────────────
    print("\n[4/5] Training (Mock + periodic Real BatSim eval)...")
    print(f"  Max steps     : 2,000,000")
    print(f"  Real eval     : every 25,000 steps (requires docker-compose up batsim)")
    print(f"  BatSim socket : {_BATSIM_SOCKET}")
    print(f"  Platform      : {_PLATFORM}")
    print(f"  Workload      : {_WORKLOAD} ({num_jobs} jobs, max_cores=4)")
    print(f"\n{'─'*70}")

    t0 = time.time()
    model.learn(
        total_timesteps=2_000_000,
        callback=CallbackList([diagnostics_cb, real_eval_cb]),
        reset_num_timesteps=True,
    )
    train_time = time.time() - t0

    model.save(save_path)
    print(f"\n  Final model : {save_path}.zip")
    print(f"  Training    : {train_time:.0f}s ({train_time/60:.1f} min)")
    print(f"  Steps       : {model.num_timesteps:,}")
    print(f"  Episodes    : {diagnostics_cb._n_episodes}")
    print(f"  Best completed jobs in one Mock episode: {diagnostics_cb._best_completed}/{num_jobs}")

    # ── Final real BatSim validation ─────────────────────────────────────────
    print("\n[5/5] Final validation on REAL BatSim (3 episodes)...")
    best_path = save_path + "_best.zip"
    val_model = MaskablePPO.load(best_path, env=env) if Path(best_path).exists() else model
    real_m = validate_on_real(val_model, real_config, num_episodes=3)

    if real_m:
        print(f"\n{'='*70}")
        print(f"  FINAL RESULTS (Real BatSim 3.1.0 — ground truth)")
        print(f"{'─'*70}")
        print(f"  {'Metric':<28} | {'Mock SJF':>10} | {'PPO (Real)':>12}")
        print(f"{'─'*70}")
        print(f"  {'Avg Waiting Time (s)':<28} | {sjf_wait:>10.2f} | {real_m['avg_waiting_time']:>12.2f}")
        print(f"  {'Avg Slowdown':<28} | {sjf_m['avg_slowdown']:>10.2f} | {real_m['avg_slowdown']:>12.2f}")
        print(f"  {'Avg Utilization (%)':<28} | {sjf_m['avg_utilization']:>9.1%}  | {real_m['avg_utilization']:>11.1%}")
        print(f"{'='*70}")

    else:
        print("  Real BatSim validation skipped (BatSim unavailable).")

    print(f"\n  TensorBoard: tensorboard --logdir logs/tensorboard_real_eval --bind_all --port 6006")
    env.close()


if __name__ == "__main__":
    main()
