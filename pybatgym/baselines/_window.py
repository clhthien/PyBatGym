"""Helper dùng chung cho các baseline: cùng "cửa sổ" top-K với agent RL.

Action mapper chỉ cho chọn một trong K job cũ nhất (sắp theo submit_time), index K là WAIT,
index K+1 là SCHEDULE_SMALLEST_FITTING. Baseline phải trả về index nằm trong cùng không gian
này, nên chỉ được xét K job đầu hàng đợi (giống agent) để so sánh công bằng.
"""
from __future__ import annotations


def wait_index(env) -> int:
    """Index của action WAIT (= K)."""
    mapper = getattr(env, "_action_mapper", None)
    idx = getattr(mapper, "wait_action", None)
    return int(idx) if idx is not None else env.action_space.n - 2


def window(env) -> list:
    """K job cũ nhất đang chờ, cùng thứ tự với DefaultActionMapper."""
    pending = env._state.get("pending_jobs", [])
    return sorted(pending, key=lambda j: j.submit_time)[: wait_index(env)]


def running_estimates(env) -> list[tuple[float, int]]:
    """[(thời điểm kết thúc ƯỚC TÍNH, số core)] của các job đang chạy.

    Ước tính theo walltime người dùng khai (start_time + requested_walltime), không dùng
    runtime thật để baseline không biết trước tương lai. Hỗ trợ cả MockAdapter
    (dict job_id -> _RunningJobInfo) và RealBatsimAdapter (list[Job]).
    """
    adapter = env._adapter
    now = adapter.get_current_time()
    raw = getattr(adapter, "_running_jobs", None)
    items = raw.values() if isinstance(raw, dict) else (raw or [])
    out = []
    for rj in items:
        job = getattr(rj, "job", rj)
        start = job.start_time if job.start_time is not None else now
        cores = getattr(rj, "cores", None) or job.requested_resources
        out.append((max(start + job.requested_walltime, now), int(cores)))
    return out
