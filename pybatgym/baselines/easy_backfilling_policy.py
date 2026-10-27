from __future__ import annotations
from typing import TYPE_CHECKING

from ._window import running_estimates, wait_index, window

if TYPE_CHECKING:
    from pybatgym.envs import PyBatGymEnv


def easy_backfilling_policy(env: PyBatGymEnv) -> int:
    """EASY Backfilling.

    1. Job đầu hàng đợi vừa core rảnh -> chạy ngay.
    2. Ngược lại, tính shadow time (lúc sớm nhất job đầu có đủ core, theo walltime ước tính của
       các job đang chạy) và số core dư tại thời điểm đó.
    3. Backfill job đứng sau nếu nó vừa core rảnh hiện tại VÀ (kết thúc trước shadow time
       HOẶC chỉ dùng core dư), nên không làm trễ job đầu hàng đợi.
    Chỉ xét K job đầu hàng đợi (cùng cửa sổ với agent RL).
    """
    wait = wait_index(env)
    jobs = window(env)
    if not jobs:
        return wait

    resource = env._state["resource"]
    head = jobs[0]
    if resource.can_allocate(head.requested_resources):
        return 0

    now = env._adapter.get_current_time()
    free = resource.free_cores
    shadow = now
    for finish, cores in sorted(running_estimates(env)):
        free += cores
        shadow = finish
        if free >= head.requested_resources:
            break
    else:
        return wait  # không tính được shadow time (head không bao giờ vừa theo ước tính)
    extra = free - head.requested_resources

    for i in range(1, len(jobs)):
        job = jobs[i]
        if not resource.can_allocate(job.requested_resources):
            continue
        if now + job.requested_walltime <= shadow or job.requested_resources <= extra:
            return i
    return wait
