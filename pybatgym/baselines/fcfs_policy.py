from __future__ import annotations
from typing import TYPE_CHECKING

from ._window import wait_index, window

if TYPE_CHECKING:
    from pybatgym.envs import PyBatGymEnv


def fcfs_policy(env: PyBatGymEnv) -> int:
    """First-Come-First-Served thuần túy: chỉ xét job cũ nhất.

    Nếu job đầu hàng đợi chưa đủ core thì WAIT (head-of-line blocking), không nhảy qua
    job khác. Đây là định nghĩa chuẩn của FCFS.
    """
    jobs = window(env)
    if not jobs:
        return wait_index(env)
    resource = env._state["resource"]
    return 0 if resource.can_allocate(jobs[0].requested_resources) else wait_index(env)
