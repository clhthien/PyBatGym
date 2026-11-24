
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RewardWeights(BaseModel):
    """Weights for multi-objective reward calculation."""

    utilization: float = Field(default=0.3, ge=0.0, le=1.0)
    waiting_time: float = Field(default=0.3, ge=0.0, le=1.0)
    slowdown: float = Field(default=0.3, ge=0.0, le=1.0)
    throughput: float = Field(default=0.1, ge=0.0, le=1.0)

    @field_validator("*", mode="after")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class PlatformConfig(BaseModel):
    """HPC cluster platform configuration."""

    total_nodes: int = Field(default=4, gt=0)
    cores_per_node: int = Field(default=1, gt=0)
    platform_path: Optional[str] = None

    @property
    def total_cores(self) -> int:
        return self.total_nodes * self.cores_per_node


class WorkloadConfig(BaseModel):
    """Workload generation/loading configuration."""

    source: str = Field(default="synthetic", pattern=r"^(synthetic|trace)$")
    trace_path: Optional[str] = None
    num_jobs: int = Field(default=100, gt=0)
    max_job_runtime: float = Field(default=100.0, gt=0, description='Simulation seconds')
    max_job_cores: int = Field(default=4, gt=0)
    seed: int = Field(default=42)


class EpisodeConfig(BaseModel):
    """Episode lifecycle configuration."""

    max_simulation_time: float = Field(default=10000.0, gt=0, description='Simulation seconds, not elapsed computer time')
    max_steps: int = Field(default=500, gt=0)


class ObservationConfig(BaseModel):
    """Observation space configuration."""

    top_k_jobs: int = Field(default=10, gt=0, le=50)
    max_queue_length: int = Field(default=200, gt=0)
    max_waiting_time: float = Field(default=1000.0, gt=0, description='Simulation seconds; observation normalization scale')
    max_bounded_slowdown: float = Field(default=100.0, gt=0)


class PyBatGymConfig(BaseModel):
    """Root configuration for PyBatGym environment."""

    model_config = {"arbitrary_types_allowed": True}

    mode: str = Field(default="mock", pattern=r"^(mock|mock_tick|real)$")
    platform: PlatformConfig = Field(default_factory=PlatformConfig)
    workload: WorkloadConfig = Field(default_factory=WorkloadConfig)
    episode: EpisodeConfig = Field(default_factory=EpisodeConfig)
    observation: ObservationConfig = Field(default_factory=ObservationConfig)
    reward_weights: RewardWeights = Field(default_factory=RewardWeights)
    reward_type: str = Field(default="hybrid", pattern=r"^(step|episodic|hybrid)$")
    plugins: list = Field(default_factory=list)
