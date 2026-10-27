from __future__ import annotations
from typing import TYPE_CHECKING

from ._window import wait_index, window

if TYPE_CHECKING:
    from pybatgym.envs import PyBatGymEnv


def sjf_policy(env: PyBatGymEnv) -> int:
    """Shortest-Job-First: trong K job đầu hàng đợi, chọn job vừa core rảnh và có walltime ngắn nhất.

    Chỉ xét cửa sổ top-K (giống agent RL). Hòa thì chọn job đến sớm hơn.
    """
    jobs = window(env)
    resource = env._state["resource"]
    candidates = [(i, j) for i, j in enumerate(jobs) if resource.can_allocate(j.requested_resources)]
    if not candidates:
        return wait_index(env)
    return min(candidates, key=lambda p: (p[1].requested_walltime, p[1].submit_time))[0]
