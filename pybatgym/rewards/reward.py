"""Reward calculator for PyBatGym.

Supports three reward modes:
- step: dense reward at every scheduling event
- episodic: sparse reward at episode end
- hybrid: combines step + episodic terminal bonus

Bản này giữ nguyên công thức cũ, chỉ thêm `last_components`: dict tách reward của bước gần nhất
thành từng thành phần (tổng các thành phần == reward trả về) để ghi vào log từng bước.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pybatgym.config.base_config import RewardWeights
from pybatgym.core import Event, EventType, Job, Resource, ScheduleCommandType


class RewardCalculator(ABC):
    """Abstract base class for reward computation."""

    @abstractmethod
    def compute_step_reward(
        self,
        events: list[Event],
        action_type: ScheduleCommandType,
        state: dict[str, Any],
    ) -> float:
        """Compute reward for a single step."""

    @abstractmethod
    def compute_episode_reward(
        self, completed_jobs: list[Job], total_time: float, total_cores: int = 64,
    ) -> float:
        """Compute reward at episode end."""


class DefaultRewardCalculator(RewardCalculator):
    """Multi-objective reward with configurable weights.

    Step reward:  r = α·ΔU − β·W_inc + schedule_bonus − invalid_penalty
    Episode reward: r = wU·U + wT·T − wW·W − wS·S
    Hybrid: accumulates step rewards + terminal bonus
    """

    SCHEDULE_BONUS = 0.1
    INVALID_PENALTY = -0.05
    IDLE_PENALTY_FACTOR = 0.01

    COMPONENT_KEYS = (
        "delta_utilization", "completed_wait", "completed_slowdown",
        "schedule_bonus", "wait_penalty", "idle_penalty",
    )

    def __init__(self, weights: RewardWeights, reward_type: str = "hybrid") -> None:
        self._w = weights
        self._type = reward_type
        self._prev_utilization = 0.0
        self.last_components: dict[str, float] = {k: 0.0 for k in self.COMPONENT_KEYS}

    def reset(self) -> None:
        """Reset internal state for new episode."""
        self._prev_utilization = 0.0
        self.last_components = {k: 0.0 for k in self.COMPONENT_KEYS}

    def compute_step_reward(
        self,
        events: list[Event],
        action_type: ScheduleCommandType,
        state: dict[str, Any],
    ) -> float:
        comp = {k: 0.0 for k in self.COMPONENT_KEYS}
        self.last_components = comp
        if self._type == "episodic":
            return 0.0

        resource: Resource = state["resource"]

        # Utilization improvement
        delta_util = resource.utilization - self._prev_utilization
        comp["delta_utilization"] = delta_util * self._w.utilization

        # Schedule bonus / invalid penalty
        if action_type == ScheduleCommandType.EXECUTE_JOB:
            comp["schedule_bonus"] = self.SCHEDULE_BONUS
        elif action_type == ScheduleCommandType.WAIT and state.get("pending_jobs"):
            comp["wait_penalty"] = self.INVALID_PENALTY

        # Job completion rewards
        for event in events:
            if event.event_type == EventType.JOB_COMPLETED and event.job:
                job = event.job
                comp["completed_wait"] -= self._w.waiting_time * _normalize(job.waiting_time, 1000.0)
                comp["completed_slowdown"] -= self._w.slowdown * _normalize(job.bounded_slowdown - 1.0, 100.0)

        # Idle penalty
        if resource.free_cores > 0 and state.get("pending_jobs"):
            idle_ratio = resource.free_cores / max(resource.total_cores, 1)
            comp["idle_penalty"] = -self.IDLE_PENALTY_FACTOR * idle_ratio

        self._prev_utilization = resource.utilization
        return sum(comp.values())

    def compute_episode_reward(
        self, completed_jobs: list[Job], total_time: float, total_cores: int = 64,
    ) -> float:
        if not completed_jobs:
            return -1.0

        avg_wait = sum(j.waiting_time for j in completed_jobs) / len(completed_jobs)
        avg_sd = sum(j.bounded_slowdown for j in completed_jobs) / len(completed_jobs)
        throughput = len(completed_jobs) / max(total_time, 1.0)

        # Utilization from finished jobs (uses actual platform size, not hardcode)
        total_core_seconds = sum(
            j.actual_runtime * j.requested_resources for j in completed_jobs
        )
        max_core_seconds = total_time * total_cores  # RWD-1 fixed: was hardcoded 64
        util = min(1.0, total_core_seconds / max(max_core_seconds, 1.0))

        reward = (
            self._w.utilization * util
            + self._w.throughput * _normalize(throughput, 1.0)
            - self._w.waiting_time * _normalize(avg_wait, 1000.0)
            - self._w.slowdown * _normalize(avg_sd - 1.0, 100.0)
        )
        return reward


def _normalize(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return min(1.0, max(0.0, value / max_value))
