"""PyBatGym - Gymnasium-compatible RL environment for HPC scheduling.

Usage:
    import gymnasium
    env = gymnasium.make("PyBatGym-v0")
    obs, info = env.reset()
    obs, reward, terminated, truncated, info = env.step(action)
"""

from __future__ import annotations

from typing import Any, Optional

import gymnasium as gym
import numpy as np

from pybatgym.spaces import (
    ActionMapper,
    DefaultActionMapper,
    DefaultObservationBuilder,
    ObservationBuilder,
)
from pybatgym.adapters import BatsimAdapter, MockAdapter
from pybatgym.config import PyBatGymConfig, load_config
from pybatgym.core import ScheduleCommandType
from pybatgym.rewards import DefaultRewardCalculator, RewardCalculator


class PyBatGymEnv(gym.Env):
    """Gymnasium environment for HPC job scheduling with BatSim.

    Attributes:
        metadata: Gymnasium metadata dict.
        observation_space: Dict space with 'features' and 'action_mask'.
        action_space: Discrete(K+1) where K = top_k_jobs.
    """

    metadata = {"render_modes": ["human", "ansi"]}

    def __init__(
        self,
        config_path: Optional[str] = None,
        config: Optional[PyBatGymConfig] = None,
        render_mode: Optional[str] = None,
        *,
        adapter: Optional[BatsimAdapter] = None,
        obs_builder: Optional[ObservationBuilder] = None,
        action_mapper: Optional[ActionMapper] = None,
        reward_calc: Optional[RewardCalculator] = None,
    ) -> None:
        super().__init__()

        self._config = config or load_config(config_path)
        self.render_mode = render_mode

        # Dependency injection for testability
        if adapter is not None:
            self._adapter = adapter
        elif self._config.mode == "real":
            from pybatgym.adapters import RealBatsimAdapter
            self._adapter = RealBatsimAdapter(self._config)
        else:
            self._adapter = MockAdapter(self._config)  # EventDrivenMockAdapter
        self._obs_builder = obs_builder or DefaultObservationBuilder(self._config.observation)
        self._action_mapper = action_mapper or DefaultActionMapper(self._config.observation.top_k_jobs)
        self._reward_calc = reward_calc or DefaultRewardCalculator(
            self._config.reward_weights, self._config.reward_type,
        )

        self.observation_space = self._obs_builder.get_observation_space()
        self.action_space = self._action_mapper.get_action_space()

        # Episode state
        self._step_count = 0
        self._cumulative_reward = 0.0
        self._state: dict[str, Any] = {}
        self._plugins: list[Any] = []

        # Auto-register plugins from config
        for plugin in getattr(self._config, "plugins", []):
            if hasattr(plugin, "on_step"):
                self._plugins.append(plugin)

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        super().reset(seed=seed)

        self._step_count = 0
        self._cumulative_reward = 0.0
        self._reward_calc.reset()

        events, resource = self._adapter.reset()

        self._state = {
            "current_time": self._adapter.get_current_time(),
            "max_time": self._config.episode.max_simulation_time,
            "pending_jobs": self._adapter.get_pending_jobs(),
            "resource": self._adapter.get_resource(),
            "events": events,
        }

        obs = self._obs_builder.build(self._state)
        info = self._build_info(events)

        for plugin in self._plugins:
            plugin.on_reset(self._state)

        return obs, info

    def step(
        self, action: int,
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        self._step_count += 1

        command = self._action_mapper.map(action, self._state)
        action_type = command.command_type if command else ScheduleCommandType.WAIT

        events, sim_done = self._adapter.step(command)

        self._state = {
            "current_time": self._adapter.get_current_time(),
            "max_time": self._config.episode.max_simulation_time,
            "pending_jobs": self._adapter.get_pending_jobs(),
            "resource": self._adapter.get_resource(),
            "events": events,
        }

        step_reward = self._reward_calc.compute_step_reward(events, action_type, self._state)

        terminated = sim_done
        truncated = self._step_count >= self._config.episode.max_steps

        if terminated or truncated:
            episode_reward = self._reward_calc.compute_episode_reward(
                self._adapter.get_completed_jobs(),
                self._adapter.get_current_time(),
                total_cores=self._config.platform.total_cores,  # RWD-1 fix
            )
            step_reward += episode_reward

        self._cumulative_reward += step_reward

        obs = self._obs_builder.build(self._state)
        info = self._build_info(events)
        if terminated or truncated:
            info["episode_metrics"] = self._build_episode_metrics()

        for plugin in self._plugins:
            plugin.on_step(action, step_reward, self._state, terminated or truncated)

        return obs, step_reward, terminated, truncated, info

    def render(self) -> Optional[str]:
        if self.render_mode == "ansi":
            return self._render_ansi()
        if self.render_mode == "human":
            print(self._render_ansi())
        return None

    def close(self) -> None:
        self._adapter.close()
        for plugin in self._plugins:
            plugin.on_close()

    def register_plugin(self, plugin: Any) -> None:
        self._plugins.append(plugin)

    def action_masks(self) -> np.ndarray:
        """Return current valid action mask as boolean array.

        This is the standard interface expected by sb3-contrib's MaskablePPO.
        MaskablePPO auto-detects this method and calls it every step to zero-out
        probabilities of invalid actions before sampling.

        Returns:
            Boolean numpy array of shape (action_space.n,).
            True = action is valid, False = action is invalid.
        """
        obs = self._obs_builder.build(self._state)
        return obs["action_mask"].astype(bool)

    # -- Private helpers --

    def _build_info(self, events: list) -> dict[str, Any]:
        obs = self._obs_builder.build(self._state)
        return {
            "step": self._step_count,
            "sim_time": self._adapter.get_current_time(),
            "pending": len(self._state.get("pending_jobs", [])),
            "completed": len(self._adapter.get_completed_jobs()),
            "utilization": self._state["resource"].utilization,
            "cumulative_reward": self._cumulative_reward,
            "num_events": len(events),
            "action_mask": obs.get("action_mask"),
        }

    def _build_episode_metrics(self) -> dict[str, Any]:
        """Return metrics before auto-reset; durations use simulator seconds.

        Makespan is the final simulator clock from episode origin, including any
        idle time before the first submit. Throughput is jobs/simulation-second.
        """
        completed = self._adapter.get_completed_jobs()
        completed_count = len(completed)
        makespan = self._adapter.get_current_time()
        total_cores = self._config.platform.total_cores

        avg_wait = 0.0
        avg_slowdown = 0.0
        utilization = 0.0
        throughput = 0.0
        if completed:
            avg_wait = sum(j.waiting_time for j in completed) / completed_count
            avg_slowdown = sum(j.bounded_slowdown for j in completed) / completed_count
            if makespan > 0 and total_cores > 0:
                busy = sum(j.actual_runtime * j.requested_resources for j in completed)
                utilization = min(1.0, busy / (makespan * total_cores))
            throughput = completed_count / makespan if makespan > 0 else 0.0

        return {
            "completed_jobs": completed_count,
            "makespan": makespan,
            "avg_waiting_time": avg_wait,
            "avg_bounded_slowdown": avg_slowdown,
            "utilization": utilization,
            "throughput": throughput,
            "total_reward": self._cumulative_reward,
        }

    def _render_ansi(self) -> str:
        resource = self._state.get("resource")
        if resource is None:
            return "Environment not initialized. Call reset() first."

        lines = [
            f"╔══ PyBatGym ══════════════════════╗",
            f"║ Step: {self._step_count:<6} Sim time: {self._adapter.get_current_time():.1f} s_sim ║",
            f"║ Pending: {len(self._state.get('pending_jobs', [])):<5} "
            f"Completed: {len(self._adapter.get_completed_jobs()):<5}║",
            f"║ Util: {resource.utilization:.1%}  "
            f"Free: {resource.free_cores}/{resource.total_cores} cores ║",
            f"║ Reward: {self._cumulative_reward:<+10.4f}              ║",
            f"╚══════════════════════════════════╝",
        ]
        return "\n".join(lines)
