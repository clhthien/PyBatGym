
from __future__ import annotations

import os
import time
from typing import Optional

import numpy as np
from stable_baselines3.common.callbacks import BaseCallback

from pybatgym.config.base_config import PyBatGymConfig


class RealEvalCallback(BaseCallback):
    """Evaluate current PPO policy on real BatSim every N training steps.

    Args:
        real_config:    PyBatGymConfig with mode="real" pointing to BatSim service.
        eval_freq:      Evaluate every this many *training* steps.
        eval_episodes:  Number of real BatSim episodes per evaluation.
        sjf_wait:       SJF baseline avg_waiting_time for comparison.
        verbose:        0=silent, 1=key events.
    """

    def __init__(
        self,
        real_config: PyBatGymConfig,
        eval_freq: int = 50_000,
        eval_episodes: int = 1,
        baselines: Optional[dict] = None,
        verbose: int = 1,
    ) -> None:
        super().__init__(verbose)
        self.real_config = real_config
        self.eval_freq = eval_freq
        self.eval_episodes = eval_episodes
        self.baselines = baselines or {}
        # SJF wait baseline for competitive logic
        self.sjf_wait = self.baselines.get("sjf", {}).get("avg_waiting_time", 0.0)
        self.writers: Optional[dict] = None  # Injected from train script
        self._last_eval: int = 0
        self._eval_count: int = 0
        
        # Persistent CSV Logger
        from pybatgym.plugins.benchmark_logger import BenchmarkLogger
        self.csv_logger = BenchmarkLogger()
        self.policy_name = "PPO_Agent" # Default, will try to resolve later

    def _on_step(self) -> bool:
        if self.num_timesteps - self._last_eval < self.eval_freq:
            return True
        self._last_eval = self.num_timesteps
        self._run_real_eval()
        return True

    def _run_real_eval(self) -> None:
        """Run eval_episodes with real BatSim and log Real/* metrics."""
        from pybatgym.envs import PyBatGymEnv

        self._eval_count += 1
        t0 = time.time()
        if self.verbose >= 1:
            print(
                f"\n  [RealEval #{self._eval_count} @ {self.num_timesteps:,} steps] "
                f"Running {self.eval_episodes} real episode(s)..."
            )

        waits, utils, sds, rewards, makespans = [], [], [], [], []
        ep_steps, ep_invalids = [], []

        env = None
        try:
            env = PyBatGymEnv(config=self.real_config)

            for ep in range(self.eval_episodes):
                # Vary seed per eval call so consecutive evals test different conditions
                seed = 100 + self._eval_count * self.eval_episodes + ep
                obs, _ = env.reset(seed=seed)
                done = False
                ep_reward, steps, invalids = 0.0, 0, 0

                while not done:
                    # Extract action masks for MaskablePPO support
                    action_masks = None
                    if isinstance(obs, dict) and "action_mask" in obs:
                        action_masks = obs["action_mask"]
                    
                    # Robust predict call: handle both standard PPO and MaskablePPO
                    if action_masks is not None:
                        try:
                            action, _ = self.model.predict(obs, deterministic=True, action_masks=action_masks)
                        except TypeError:
                            # Standard SB3 PPO does not support action_masks keyword
                            action, _ = self.model.predict(obs, deterministic=True)
                    else:
                        action, _ = self.model.predict(obs, deterministic=True)
                    
                    obs, reward, terminated, truncated, info = env.step(int(action))
                    ep_reward += reward
                    steps += 1
                    if info.get("invalid_action", False):
                        invalids += 1
                    done = terminated or truncated

                # Give BatSim time to flush output files before ZMQ closes
                time.sleep(2)

                raw = getattr(env, "unwrapped", env)
                adapter = getattr(raw, "_adapter", None)
                if adapter is None:
                    continue

                completed = adapter.get_completed_jobs()
                if not completed:
                    continue

                # ── Write jobs CSV from Python (more reliable than BatSim file output) ──
                # try:
                #     import csv, os, pathlib
                #     out_dir = pathlib.Path("/workspace/data")
                #     out_dir.mkdir(parents=True, exist_ok=True)
                #     csv_path = out_dir / f"ppo_eval_{self._eval_count}_jobs.csv"
                #     with open(csv_path, "w", newline="") as f:
                #         writer = csv.writer(f)
                #         writer.writerow([
                #             "job_id", "submit_time", "requested_resources",
                #             "starting_time", "finish_time",
                #             "waiting_time", "execution_time", "bounded_slowdown",
                #         ])
                #         for j in completed:
                #             writer.writerow([
                #                 j.id,
                #                 round(j.submit_time, 3),
                #                 j.requested_resources,
                #                 round(j.start_time, 3),
                #                 round(j.finish_time, 3),
                #                 round(j.waiting_time, 3),
                #                 round(j.actual_runtime, 3),
                #                 round(j.bounded_slowdown, 3),
                #             ])
                #     print(f"  [RealEval #{self._eval_count}] Saved {len(completed)} jobs → {csv_path.name}")
                # except Exception as e:
                #     print(f"  [RealEval #{self._eval_count}] CSV write failed: {e}")

                n = len(completed)
                makespan = adapter.get_current_time()
                total_cores = raw._config.platform.total_cores

                avg_wait = sum(j.waiting_time for j in completed) / n
                avg_sd = sum(j.bounded_slowdown for j in completed) / n
                util = 0.0
                if makespan > 0 and total_cores > 0:
                    busy = sum(j.actual_runtime * j.requested_resources for j in completed)
                    util = min(1.0, busy / (makespan * total_cores))  # clamp to [0,1]

                waits.append(avg_wait)
                utils.append(util)
                sds.append(avg_sd)
                rewards.append(ep_reward)
                makespans.append(makespan)
                ep_steps.append(steps)
                ep_invalids.append(invalids)

                # Log to per_episode_metrics.csv immediately
                ep_metrics = {
                    "total_reward": ep_reward,
                    "completed_jobs": n,
                    "avg_waiting_time": avg_wait,
                    "avg_bounded_slowdown": avg_sd,
                    "utilization": util,
                    "makespan": makespan,
                    "num_steps": steps,
                    "invalid_actions": invalids,
                    "terminated": 1 if terminated else 0,
                    "truncated": 1 if truncated else 0
                }
                # Try to resolve names from adapter on first success
                if self._eval_count == 1 and ep == 0:
                    p_path, w_path = adapter._resolve_paths()
                    self._platform_name = os.path.basename(p_path)
                    self._workload_name = os.path.basename(w_path)
                
                self.csv_logger.log_episode(
                    episode_idx=self._eval_count,
                    metrics=ep_metrics,
                    experiment_id=f"eval_{self.num_timesteps}",
                    policy=getattr(self.model, "policy_class", self.policy_name),
                    workload=getattr(self, "_workload_name", "unknown"),
                    platform=getattr(self, "_platform_name", "unknown"),
                    seed=seed
                )

        except Exception as exc:
            if self.verbose >= 1:
                print(f"  [RealEval] Skipped — BatSim unavailable: {exc}")
            return
        finally:
            if env is not None:
                try:
                    env.close()
                except Exception:
                    pass
            # Allow ZMQ port to be released before BatSim restarts
            time.sleep(3)

        if not waits:
            return

        avg_wait = float(np.mean(waits))
        avg_util = float(np.mean(utils))
        avg_sd = float(np.mean(sds))
        avg_rew = float(np.mean(rewards))
        avg_makespan = float(np.mean(makespans)) if makespans else 0.0
        advantage = (self.sjf_wait - avg_wait) / max(self.sjf_wait, 1e-8)
        elapsed = time.time() - t0

        # --- Log Overlay Metrics (Comparison_Real Folder) ---
        if self.writers:
            step = self.num_timesteps
            # Use unified tag names for overlay
            self.writers["PPO"].add_scalar("Comparison_Real/Waiting_Time", avg_wait, step)
            self.writers["PPO"].add_scalar("Comparison_Real/Utilization", avg_util, step)
            self.writers["PPO"].add_scalar("Comparison_Real/Slowdown", avg_sd, step)
            self.writers["PPO"].add_scalar("Comparison_Real/Makespan", avg_makespan, step)
            self.writers["PPO"].add_scalar("Evaluation/Reward", avg_rew, step)

            for name, metrics in self.baselines.items():
                tag = name.upper()
                if tag in self.writers:
                    # Log baseline values at the SAME step for horizontal reference
                    w = self.writers[tag]
                    w.add_scalar("Comparison_Real/Waiting_Time", metrics.get("avg_waiting_time", 0), step)
                    w.add_scalar("Comparison_Real/Utilization", metrics.get("avg_utilization", 0), step)
                    w.add_scalar("Comparison_Real/Slowdown", metrics.get("avg_slowdown", 0), step)
                    w.add_scalar("Comparison_Real/Makespan", metrics.get("avg_makespan", 0), step)

        if self.verbose >= 1:
            print(
                f"  [RealEval #{self._eval_count}] "
                f"wait={avg_wait:.1f} s_sim  util={avg_util:.1%}  sd={avg_sd:.2f}  "
                f"reward={avg_rew:.2f}  wall_elapsed={elapsed:.0f} s_wall"
            )
