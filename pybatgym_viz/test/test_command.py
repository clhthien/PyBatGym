"""Tương đương test/test_command.rb: test phần parse bằng output mẫu."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from command import Command, numeric_columns

SAMPLE = """policy,avg_wait,utilization
fcfs,120.5,0.71
sjf,80.2,0.69
"""

def test_parse_columns_and_rows():
    t = Command("x.csv").parse(SAMPLE)
    assert t.columns == ["policy", "avg_wait", "utilization"]
    assert len(t.rows) == 2
    assert t.rows[0]["policy"] == "fcfs"
    assert t.rows[1]["avg_wait"] == "80.2"

def test_parse_empty_output():
    t = Command("x.csv").parse("")
    assert t.columns == [] and t.rows == []

def test_numeric_columns():
    t = Command("x.csv").parse(SAMPLE)
    assert numeric_columns(t) == ["avg_wait", "utilization"]

def test_exec_missing_file():
    t, err = Command("/no/such/file.csv").exec()
    assert err and t.rows == []

def test_exec_real_file(tmp_path):
    p = tmp_path / "r.csv"; p.write_text(SAMPLE)
    t, err = Command(str(p)).exec()
    assert err is None and len(t.rows) == 2


REAL = """experiment_id,policy,workload,platform,seed,total_reward,completed_jobs,avg_waiting_time,avg_bounded_slowdown,utilization,makespan,throughput,num_steps,invalid_actions,terminated,truncated
exp,PPO_Maskable,medium_workload,medium_platform,0,8.563740,100,5.157732,1.126173,0.866988,814.160295,0.122826,266,0,0,0
exp,PPO_Maskable,medium_workload,medium_platform,0,9.314671,100,6.884236,1.531984,0.873147,809.690560,0.123504,253,0,0,0
"""


def test_aggregate_real_columns():
    from command import aggregate
    a = aggregate(Command("x.csv").parse(REAL))
    assert a.columns[:4] == ["policy", "workload", "platform", "n"]
    assert len(a.rows) == 1 and a.rows[0]["n"] == "2"
    assert "seed" not in a.columns and "terminated" not in a.columns
    assert "±" in a.rows[0]["avg_waiting_time"]


def test_tb_last_value_table():
    import tb_reader
    runs = {"A/FCFS": {"util": [(0, 0.1), (5, 0.7)]},
            "A/SJF": {"util": [(0, 0.2)], "wait": [(0, 3.0)]}}
    t = tb_reader.last_value_table(runs)
    assert t.columns == ["tag", "FCFS", "SJF"]
    assert t.rows[0] == {"tag": "util", "FCFS": "0.7", "SJF": "0.2"}
    assert t.rows[1]["FCFS"] == ""


def test_short_labels_collision_keeps_full_names():
    import tb_reader
    assert tb_reader.short_labels(["A/PPO", "B/PPO"]) == {"A/PPO": "A/PPO", "B/PPO": "B/PPO"}
    assert tb_reader.short_labels(["Run/FCFS", "MaskablePPO_1"]) == {"Run/FCFS": "FCFS", "MaskablePPO_1": "MaskablePPO_1"}
