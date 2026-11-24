"""Data models for PyBatGym simulation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class JobStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()


class EventType(Enum):
    JOB_SUBMITTED = auto()
    JOB_STARTED = auto()
    JOB_COMPLETED = auto()
    SIMULATION_ENDED = auto()
    RESOURCE_FREED = auto()


class ScheduleCommandType(Enum):
    EXECUTE_JOB = auto()
    RESERVE_RESOURCE = auto()
    BACKFILL_JOB = auto()
    WAIT = auto()


@dataclass
class Job:
    """Simulated HPC job; all timestamps and durations are simulation seconds.

    requested_walltime is the simulated job's requested time limit, not the
    wall-clock duration of the Python program or runner timeout.
    """

    job_id: int
    submit_time: float
    requested_walltime: float
    actual_runtime: float
    requested_resources: int
    status: JobStatus = JobStatus.PENDING
    start_time: Optional[float] = None
    finish_time: Optional[float] = None

    @property
    def waiting_time(self) -> float:
        if self.start_time is None:
            return 0.0
        return self.start_time - self.submit_time

    @property
    def bounded_slowdown(self) -> float:
        if self.finish_time is None or self.actual_runtime <= 0:
            return 1.0
        turnaround = self.finish_time - self.submit_time
        return max(1.0, turnaround / max(self.actual_runtime, 1.0))

    @property
    def is_schedulable(self) -> bool:
        return self.status == JobStatus.PENDING


@dataclass
class Resource:
    """Represents a cluster resource pool."""

    total_nodes: int
    total_cores_per_node: int
    used_cores: int = 0

    @property
    def total_cores(self) -> int:
        return self.total_nodes * self.total_cores_per_node

    @property
    def free_cores(self) -> int:
        return self.total_cores - self.used_cores

    @property
    def utilization(self) -> float:
        if self.total_cores == 0:
            return 0.0
        return self.used_cores / self.total_cores

    def can_allocate(self, cores: int) -> bool:
        return self.free_cores >= cores

    def allocate(self, cores: int) -> None:
        if not self.can_allocate(cores):
            raise ValueError(f"Cannot allocate {cores} cores, only {self.free_cores} free")
        self.used_cores += cores

    def release(self, cores: int) -> None:
        self.used_cores = max(0, self.used_cores - cores)


@dataclass
class Event:
    """Represents a simulation event from BatSim."""

    event_type: EventType
    timestamp: float
    job: Optional[Job] = None
    data: dict = field(default_factory=dict)


@dataclass
class ScheduleCommand:
    """Command sent to the simulator."""

    command_type: ScheduleCommandType
    job: Optional[Job] = None
    allocated_cores: int = 0


# ---------------------------------------------------------------------------
# Internal simulator event types (used by EventDrivenMockAdapter, NOT by RL)
# ---------------------------------------------------------------------------

class SimEventType(Enum):
    """Internal event types for the mock event queue."""

    JOB_SUBMISSION = auto()
    JOB_COMPLETION = auto()
    CALL_ME_LATER = auto()
    SIMULATION_END = auto()


@dataclass
class SimEvent:
    """A scheduled event in the mock simulator's priority queue.

    Ordered by (timestamp, _tiebreaker) so ``heapq`` pops the earliest
    event first, with FIFO ordering for simultaneous events.
    """

    timestamp: float
    event_type: SimEventType
    job: Optional[Job] = None
    data: dict = field(default_factory=dict)
    _tiebreaker: int = 0

    def __lt__(self, other: "SimEvent") -> bool:
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        return self._tiebreaker < other._tiebreaker
