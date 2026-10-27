"""Test các baseline (FCFS, SJF, EASY, Random) và ràng buộc của cửa sổ top-K."""
from types import SimpleNamespace as NS

from pybatgym.baselines import (
    RandomMaskedPolicy, easy_backfilling_policy, fcfs_policy, sjf_policy,
)
from pybatgym.config.base_config import PyBatGymConfig
from pybatgym.core import Job, Resource
from pybatgym.envs import PyBatGymEnv

K = 10


def _job(i, submit, cores, walltime, start=None):
    j = Job(job_id=i, submit_time=submit, requested_walltime=walltime,
            actual_runtime=walltime * 0.8, requested_resources=cores)
    j.start_time = start
    return j


def _env(pending, used=0, total=32, running=None, now=0.0):
    res = Resource(total_nodes=total, total_cores_per_node=1, used_cores=used)
    adapter = NS(get_current_time=lambda: now, _running_jobs=running if running is not None else {})
    return NS(_state={"pending_jobs": pending, "resource": res}, _adapter=adapter,
              _action_mapper=NS(wait_action=K), action_space=NS(n=K + 2))


# ── FCFS ────────────────────────────────────────────────────────────────────

def test_fcfs_runs_head_when_it_fits():
    env = _env([_job(0, 0, 4, 10), _job(1, 1, 1, 10)])
    assert fcfs_policy(env) == 0


def test_fcfs_waits_when_head_is_blocked():
    # head cần 8 core nhưng chỉ còn 4; job sau vừa 1 core nhưng FCFS không được nhảy qua
    env = _env([_job(0, 0, 8, 10), _job(1, 1, 1, 10)], used=28)
    assert fcfs_policy(env) == K


def test_fcfs_waits_when_queue_empty():
    assert fcfs_policy(_env([])) == K


# ── SJF ─────────────────────────────────────────────────────────────────────

def test_sjf_picks_shortest_fitting_job():
    env = _env([_job(0, 0, 4, 100), _job(1, 1, 4, 10), _job(2, 2, 40, 1)])
    assert sjf_policy(env) == 1  # job 2 ngắn nhất nhưng không vừa core


def test_sjf_stays_inside_top_k_window():
    pending = [_job(i, i, 2, 100) for i in range(15)]
    pending[12] = _job(12, 12, 2, 1)  # job ngắn nhất nằm ngoài cửa sổ K=10
    action = sjf_policy(_env(pending))
    assert 0 <= action < K


def test_sjf_waits_when_nothing_fits():
    assert sjf_policy(_env([_job(0, 0, 8, 10)], used=30)) == K


# ── EASY ────────────────────────────────────────────────────────────────────

def _running_mock(job_id, cores, walltime, start=0.0):
    job = _job(job_id, 0, cores, walltime, start=start)
    return {job_id: NS(job=job, cores=cores, finish_time=start + walltime * 0.8)}


def test_easy_runs_head_when_it_fits():
    assert easy_backfilling_policy(_env([_job(0, 0, 4, 10)])) == 0


def test_easy_backfills_job_that_ends_before_shadow_time():
    # head cần 8, còn 2 core; job chạy 6 core ước tính xong lúc t=100 => shadow=100, extra=0
    pending = [_job(0, 0, 8, 500), _job(1, 1, 2, 50)]
    env = _env(pending, used=30, running=_running_mock(9, 6, 100))
    assert easy_backfilling_policy(env) == 1


def test_easy_does_not_backfill_job_that_would_delay_head():
    pending = [_job(0, 0, 8, 500), _job(1, 1, 2, 150)]  # ước tính xong sau shadow, extra=0
    env = _env(pending, used=30, running=_running_mock(9, 6, 100))
    assert easy_backfilling_policy(env) == K


def test_easy_backfills_job_that_only_uses_extra_cores():
    # head cần 4; sau khi job 6 core xong còn 8 => extra=4; job 2 core chạy lâu vẫn được vì dùng core dư
    pending = [_job(0, 0, 4, 500), _job(1, 1, 2, 900)]
    env = _env(pending, used=30, running=_running_mock(9, 6, 100))
    assert easy_backfilling_policy(env) == 1


def test_easy_supports_real_adapter_running_list():
    running = [_job(9, 0, 6, 100, start=0.0)]  # RealBatsimAdapter lưu list[Job]
    pending = [_job(0, 0, 8, 500), _job(1, 1, 2, 50)]
    assert easy_backfilling_policy(_env(pending, used=30, running=running)) == 1


# ── Chạy trên env thật: hàng đợi dài hơn K, mọi job phải hoàn tất ──────────

def _synthetic_config():
    return PyBatGymConfig.model_validate({
        "mode": "mock",
        "platform": {"total_nodes": 8, "cores_per_node": 1},
        "workload": {"source": "synthetic", "num_jobs": 40, "max_job_runtime": 50.0,
                     "max_job_cores": 8, "seed": 3},
        "episode": {"max_simulation_time": 100000.0, "max_steps": 5000},
        "observation": {"top_k_jobs": 3, "max_queue_length": 200,
                        "max_waiting_time": 5000.0, "max_bounded_slowdown": 100.0},
    })


def _run(policy, seed=0):
    env = PyBatGymEnv(config=_synthetic_config())
    env.reset(seed=seed)
    if hasattr(policy, "reset"):
        policy.reset(seed)
    done, invalid, actions, max_queue = False, 0, [], 0
    while not done:
        mask = env.action_masks()
        action = policy(env)
        invalid += 0 if mask[action] else 1
        actions.append(action)
        max_queue = max(max_queue, len(env._state["pending_jobs"]))
        _, _, terminated, truncated, _ = env.step(action)
        done = terminated or truncated
    completed = len(env._adapter.get_completed_jobs())
    env.close()
    return completed, terminated, invalid, actions, max_queue


def test_all_policies_finish_every_job_with_queue_longer_than_k():
    for policy in (fcfs_policy, sjf_policy, easy_backfilling_policy, RandomMaskedPolicy(0)):
        completed, terminated, invalid, _, max_queue = _run(policy)
        assert max_queue > 3, "kịch bản phải có hàng đợi dài hơn K"
        assert completed == 40 and terminated, policy
        assert invalid == 0, policy


def test_random_masked_policy_is_reproducible():
    a = _run(RandomMaskedPolicy(0), seed=7)[3]
    b = _run(RandomMaskedPolicy(0), seed=7)[3]
    c = _run(RandomMaskedPolicy(0), seed=8)[3]
    assert a == b
    assert a != c
