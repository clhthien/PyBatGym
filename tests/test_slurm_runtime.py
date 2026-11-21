import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pybatgym.runner import slurm, podman_runtime
from pybatgym.runner.storage import Status, write_json
from pybatgym.runner.service import allocate


def test_slurm_submit_uses_shared_run_and_deployment_settings(tmp_path, monkeypatch):
    commands = []
    def call(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout='991;cluster\n', stderr='')
    monkeypatch.setattr(slurm.subprocess, 'run', call)
    d = slurm.submit({'backend':'mock'},tmp_path)
    assert json.loads((d/'slurm.json').read_text())['job_id']=='991'
    assert json.loads((d/'status.json').read_text())['state']=='QUEUED'
    assert '--mem=4G' in commands[0] and '--cpus-per-task=1' in commands[0]
    script=(d/'job.sbatch').read_text()
    assert 'PYBATGYM_RUNTIME=podman' in script and 'slurm_entry' in script
    assert str(d) in script


def test_slurm_submit_failure_records_error_not_success(tmp_path, monkeypatch):
    monkeypatch.setattr(slurm.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='account denied'))
    with pytest.raises(RuntimeError,match='account denied'):
        slurm.submit({'backend':'mock'},tmp_path)
    d=next(tmp_path.iterdir())
    assert json.loads((d/'status.json').read_text())['error_code']=='SLURM_SUBMIT_ERROR'


def test_slurm_config_is_not_a_shell_command(tmp_path,monkeypatch):
    monkeypatch.setenv('PYBATGYM_SLURM_PARTITION','compute; echo unsafe')
    with pytest.raises(ValueError):slurm.submit({'backend':'mock'},tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('scheduler,expected',[('TIMEOUT','TIMED_OUT'),('COMPLETED','FAILED'),('CANCELLED','CANCELLED')])
def test_scheduler_end_cannot_produce_pass(tmp_path,monkeypatch,scheduler,expected):
    d=allocate(tmp_path);Status(d,resume=True).set('QUEUED');write_json(d/'slurm.json',{'job_id':'99'})
    monkeypatch.setattr(slurm.time,'time',lambda:10**12)
    monkeypatch.setattr(slurm.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=f'99|{scheduler}|1:0|\n'))
    slurm.reconcile(d)
    assert json.loads((d/'status.json').read_text())['state']==expected


def test_podman_refuses_login_node(tmp_path,monkeypatch):
    monkeypatch.delenv('SLURM_JOB_ID',raising=False)
    with pytest.raises(RuntimeError,match='allocation'):podman_runtime.prepare(tmp_path,tmp_path)


def test_podman_refuses_wrong_owner_before_any_subprocess(tmp_path,monkeypatch):
    write_json(tmp_path/'owner.json',{'run_id':'someone-else','uid':0})
    monkeypatch.setattr(podman_runtime.os,'getuid',lambda:123,raising=False)
    monkeypatch.setattr(podman_runtime.subprocess,'run',lambda *a,**k:pytest.fail('must not execute'))
    with pytest.raises(RuntimeError,match='unowned'):
        podman_runtime.command({'scratch':str(tmp_path),'run_id':'ours'},'stop','anything')


def test_podman_keeps_container_stderr_without_corrupting_inspect_json(tmp_path, monkeypatch):
    write_json(tmp_path/'owner.json', {'run_id':'ours','uid':123})
    monkeypatch.setattr(podman_runtime.os,'getuid',lambda:123,raising=False)
    monkeypatch.setattr(podman_runtime.subprocess,'run',
                        lambda *a,**k:SimpleNamespace(returncode=0,stdout='[]',stderr='native stderr'))
    runtime={'scratch':str(tmp_path),'run_id':'ours'}
    assert podman_runtime.command(runtime,'logs','ours')=='[]native stderr'
    assert json.loads(podman_runtime.command(runtime,'inspect','ours'))==[]
