"""Unit contract: simulator seconds and wall-clock seconds are different clocks.

No scaling is applied to BatSim/workload timestamps. A discrete-event simulator
can advance thousands of simulated seconds in a few wall-clock seconds.
"""

TIME_UNITS = {
    'simulation_time': 'seconds of the simulated system; not elapsed computer time',
    'submit_time': 'simulation seconds from episode origin',
    'start_time': 'simulation seconds from episode origin',
    'finish_time': 'simulation seconds from episode origin',
    'sim_time': 'simulation seconds from episode origin',
    'requested_walltime': 'simulation seconds requested for a simulated job',
    'chosen_job_walltime': 'simulation seconds requested for a simulated job',
    'actual_runtime': 'simulation seconds; finish_time minus start_time',
    'waiting_time': 'simulation seconds; start_time minus submit_time',
    'chosen_job_wait': 'simulation seconds',
    'max_simulation_time': 'simulation seconds allowed for an episode',
    'max_job_runtime': 'simulation seconds, synthetic-workload runtime upper bound',
    'max_waiting_time': 'simulation seconds, observation normalization scale',
    'workload.subtime/walltime/profile.delay': 'simulation seconds in BatSim workload JSON',
    'max_steps': 'decision steps, not seconds',
    'avg_waiting_time': 'mean waiting_time, in simulation seconds',
    'p95_wait': 'nearest-rank 95th percentile of waiting_time, in simulation seconds',
    'makespan': 'final simulator clock, in simulation seconds from episode origin (includes initial idle time)',
    'throughput': 'completed jobs per simulation second',
    'bounded_slowdown': 'dimensionless ratio',
    'utilization': 'dimensionless fraction 0..1 of simulated core-time',
    'timeout_seconds': 'wall-clock seconds allowed for worker execution',
    'elapsed': 'wall-clock seconds from runner started_at to finished_at (or now)',
    'started_at/finished_at': 'ISO 8601 wall-clock timestamps',
    'log_s_sim': 'simulation seconds',
    'log_s_wall': 'wall-clock seconds',
}
