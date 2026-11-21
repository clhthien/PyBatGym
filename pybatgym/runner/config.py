"""Strict public request schema. Paths and container controls are server-owned."""
from pathlib import Path
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pybatgym.config.loader import load_preset

REPO = Path(__file__).resolve().parents[2]


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    backend: Literal['mock', 'real'] = 'mock'
    workload: str = Field(default='gen_c32_s0', pattern=r'^[A-Za-z0-9_-]+$')
    preset: str = Field(default='medium_batsim', pattern=r'^[A-Za-z0-9_-]+$')
    policies: list[Literal['fcfs', 'sjf', 'easy', 'random']] = Field(default_factory=lambda: ['fcfs', 'sjf'], min_length=1, max_length=4)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    random_seeds: int = Field(default=1, ge=1, le=20)
    timeout_seconds: float = Field(default=120.0, ge=0.1, le=86400.0)
    max_steps: int | None = Field(default=None, ge=1, le=1000000)

    @field_validator('policies')
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Duplicate policies are not allowed')
        return value


def inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(parent.resolve()):
        raise ValueError(f'Path is outside the permitted directory: {path.name}')
    return resolved


def resolve(request: Request) -> tuple[dict, dict]:
    workload_path = inside(REPO / 'data/workloads' / (request.workload + '.json'), REPO / 'data/workloads')
    preset_path = inside(REPO / 'configs' / (request.preset + '.yaml'), REPO / 'configs')
    cfg = load_preset(request.preset)
    workload = json.loads(workload_path.read_text(encoding='utf-8'))
    jobs = workload.get('jobs', [])
    if not jobs or len(jobs) > 100000:
        raise ValueError('Workload must contain 1..100000 jobs')
    ids = [str(j['id']) for j in jobs]
    if len(ids) != len(set(ids)) or any(not i.isdigit() for i in ids):
        raise ValueError('Job IDs must be unique non-negative integers')
    for job in jobs:
        if type(job['res']) is not int or not 1 <= job['res'] <= cfg.platform.total_cores:
            raise ValueError('A job requests more resources than the simulation platform')
        if not math.isfinite(float(job['subtime'])) or float(job['subtime']) < 0:
            raise ValueError('Invalid job submission time')
        if not math.isfinite(float(job['walltime'])) or float(job['walltime']) <= 0:
            raise ValueError('Invalid job walltime')
        if job['profile'] not in workload.get('profiles', {}):
            raise ValueError('Missing workload profile')
        profile = workload['profiles'][job['profile']]
        if profile.get('type') == 'delay' and (not math.isfinite(float(profile['delay'])) or float(profile['delay']) <= 0):
            raise ValueError('Delay profile must have a finite positive runtime')
    if int(workload['nb_res']) != cfg.platform.total_cores:
        raise ValueError('Workload nb_res and preset platform size must match')
    cfg.mode = request.backend
    cfg.workload.source = 'trace'
    cfg.workload.trace_path = str(workload_path)
    cfg.workload.num_jobs = len(jobs)
    cfg.workload.seed = request.seed
    if request.max_steps is not None:
        cfg.episode.max_steps = request.max_steps
    hashes = {str(workload_path.relative_to(REPO)): hashlib.sha256(workload_path.read_bytes()).hexdigest(),
              str(preset_path.relative_to(REPO)): hashlib.sha256(preset_path.read_bytes()).hexdigest()}
    if request.backend == 'real':
        platform_name = {
            'medium_1000_batsim': 'medium',
            'medium_10000_batsim': 'medium',
        }.get(request.preset, request.preset.removesuffix('_batsim'))
        platform = inside(REPO / 'data/platforms' / (platform_name + '_platform.xml'), REPO / 'data/platforms')
        # Existing presets medium_batsim/small_batsim map to their platform files.
        count = sum(h.get('id') != 'master_host' for h in ET.parse(platform).iter('host'))
        if count != cfg.platform.total_cores:
            raise ValueError('BatSim XML compute host count does not match preset')
        cfg.platform.platform_path = str(platform)
        hashes[str(platform.relative_to(REPO))] = hashlib.sha256(platform.read_bytes()).hexdigest()
    return cfg.model_dump(mode='json'), hashes
