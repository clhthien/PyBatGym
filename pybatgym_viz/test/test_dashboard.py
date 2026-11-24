"""Dashboard projections must represent events, not decorative progress."""
import csv
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard_data import projection, job_page, core_timeline


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture_run(tmp_path):
    d=tmp_path/'20261119T000000-123456789abc'
    write(d/'config_resolved.json', {'platform':{'total_nodes':4,'cores_per_node':1},'workload':{'num_jobs':2}})
    write(d/'request.json', {'backend':'real'})
    write(d/'status.json', {'state':'SUCCEEDED'})
    write(d/'verification.json', {'status':'PASS'})
    for name, records in {
        'results/jobs.csv': [dict(policy='FCFS',seed=0,job_id=0,submit_time=0,start_time=2,finish_time=6,waiting_time=2,requested_resources=2),dict(policy='FCFS',seed=0,job_id=1,submit_time=1,start_time=6,finish_time=8,waiting_time=5,requested_resources=4)],
        'results/per_episode_metrics.csv': [dict(policy='FCFS',seed=0,utilization=.5,makespan=8,avg_bounded_slowdown=1)],
        'simulator/0/batsim_jobs.csv': [dict(job_id=0,allocated_resources='0-1'),dict(job_id=1,allocated_resources='0-3')],
    }.items():
        p=d/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=records[0]);w.writeheader();w.writerows(records)
    return d


def test_replay_uses_event_sweep_and_native_core_allocation(tmp_path):
    d=fixture_run(tmp_path)
    value=projection(d,'FCFS:0',.5,'window')
    assert value['verified'] and value['snapshot']==dict(t=2.,queued=1,running=1,completed=0,busy=2)
    assert {s['core'] for s in value['timeline']}=={0,1}
    end=projection(d,'FCFS:0',1)
    assert end['snapshot']['completed']==2 and end['snapshot']['busy']==0
    assert end['comparison'][0]['p95_wait']==5
    assert end['comparison'][0]['mean_wait']==3.5
    assert len(job_page(d,'FCFS:0',1,'1')['jobs'])==1


def test_default_timeline_keeps_all_cores_not_only_last_jobs(tmp_path):
    d=fixture_run(tmp_path)
    full=projection(d,'FCFS:0',1)
    assert full['window']==[0.,8.]
    assert {s['core'] for s in full['timeline']}=={0,1,2,3}
    assert full['used_cores']==[0,1,2,3]
    assert full['time_units']['simulation']=='seconds'
    assert full['time_units']['elapsed']=='wall_clock_seconds'
    assert full['comparison'][0]['mean_wait']==3.5  # No divide-by-1000 conversion.


def test_large_overview_bins_preserve_busy_time_on_every_core():
    jobs=[dict(id=str(i),start=float(i),finish=float(i+1),allocation=[0,3]) for i in range(6)]
    mode, segments=core_timeline(jobs,4,0.,10.,limit=4)
    assert mode=='density' and len(segments)<=4
    assert {s['core'] for s in segments}=={0,3}
    assert sum((s['finish']-s['start'])*s['busy_fraction'] for s in segments)==pytest.approx(12.)
    assert all('id' not in s for s in segments)  # Occupancy is not a fake job.


def test_timeline_density_unions_overlapping_native_intervals():
    jobs=[dict(id=str(i),start=1.,finish=4.,allocation=[0]) for i in range(3)]
    mode, segments=core_timeline(jobs,1,0.,10.,limit=1)
    assert mode=='density' and segments[0]['busy_fraction']==pytest.approx(.3)


def test_failed_run_never_gets_pass_from_leftover_verification(tmp_path):
    d=fixture_run(tmp_path);write(d/'status.json',{'state':'FAILED'})
    assert not projection(d)['verified']


def test_live_uses_measured_snapshot_not_replay_and_marks_age(tmp_path):
    d=fixture_run(tmp_path);write(d/'status.json',{'state':'RUNNING'})
    sample=dict(policy='SJF',seed=7,at='2026-01-01T00:00:00+00:00',sim_time=3,total=2,completed=0,queued=1,running=1,busy=2,cores=4,done=False)
    write(d/'progress.json',sample)
    (d/'progress.jsonl').write_text(json.dumps(sample)+'\n')
    value=projection(d)
    assert value['source']=='live' and value['policy']=='SJF' and value['live_age']>8
    assert value['snapshot']['busy']==2 and not value['verified']
    assert value['timeline']==[]


def test_dashboard_routes_prefix_validation_and_pagination(tmp_path, monkeypatch):
    app=importlib.import_module('app').app
    monkeypatch.setitem(app.config,'PLAYGROUND_RUNS_ROOT',tmp_path)
    d=fixture_run(tmp_path);client=app.test_client();base='/playground/runs/'+d.name+'/dashboard'
    html=client.get(base,environ_overrides={'SCRIPT_NAME':'/pun/dev/test'}).get_data(as_text=True)
    assert 'data-url="/pun/dev/test'+base+'/data"' in html
    assert client.get(base+'/data?position=nan').status_code==400
    assert client.get(base+'/data?timeline_view=invalid').status_code==400
    assert client.get(base+'/jobs?page=0').status_code==400
    assert client.get(base+'/data?position=.5').json['snapshot']['busy']==2
    assert client.get('/playground/runs/invalid/dashboard/data').status_code==404
    assert len(client.get(base+'/jobs?episode=FCFS:0').json['jobs'])==2


def test_symlink_artifacts_cannot_escape_run(tmp_path):
    from dashboard_data import read_json
    d=fixture_run(tmp_path);outside=tmp_path/'outside.json';write(outside,{'secret':1})
    p=d/'progress.json'
    try:p.symlink_to(outside)
    except OSError:pytest.skip('Symlinks unavailable')
    assert read_json(d,'progress.json',{})=={}
