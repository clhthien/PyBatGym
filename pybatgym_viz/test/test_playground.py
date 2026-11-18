"""Passenger-prefix, form, process, and artifact acceptance tests."""
import importlib
import json
from pathlib import Path
import re
import sys
import time

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from pybatgym.runner.service import allocate
from pybatgym.runner.storage import Status, write_json


@pytest.fixture
def web(tmp_path, monkeypatch):
    app = importlib.import_module('app').app
    directory = tmp_path / 'runs'
    directory.mkdir()
    for key, value in {'TESTING': True, 'SECRET_KEY': 'test-secret-not-for-production',
                       'PLAYGROUND_RUNS_ROOT': directory, 'PLAYGROUND_EXECUTION_MODE': 'local'}.items():
        monkeypatch.setitem(app.config, key, value)
    return app, app.test_client(), directory


def form(client, **changes):
    text = client.get('/playground/').get_data(as_text=True)
    tokens = {k: re.search(r'name="' + k + r'" value="([^"]+)"', text).group(1)
              for k in ('csrf_token', 'launch_token')}
    return {**tokens, 'backend': 'mock', 'workload': 'gen_c32_s0', 'preset': 'medium_batsim',
            'policies': ['fcfs', 'sjf'], 'seed': '0', 'random_seeds': '1', 'timeout_seconds': '120', **changes}


def test_passenger_prefix_applies_to_links_forms_and_polling(web):
    _, client, directory = web
    prefix = '/pun/dev/pybatgym_playground'
    response = client.get('/playground/', environ_overrides={'SCRIPT_NAME': prefix})
    html = response.get_data(as_text=True)
    urls = re.findall(r'(?:href|src|action)="([^"]+)"', html)
    assert urls and all(url.startswith(prefix + '/') for url in urls)
    run = allocate(directory)
    html = client.get('/playground/runs/' + run.name, environ_overrides={'SCRIPT_NAME': prefix}).get_data(as_text=True)
    assert f'data-status-url="{prefix}/playground/runs/{run.name}/status"' in html


def test_passenger_entrypoint_redirects_to_prefixed_playground(web):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    from passenger_wsgi import application
    client = Client(application, Response)
    response = client.get('/', environ_overrides={'SCRIPT_NAME': '/pun/dev/pybatgym_playground'})
    assert response.status_code == 302
    assert response.headers['Location'] == '/pun/dev/pybatgym_playground/playground/'


def test_default_passenger_store_is_per_user_and_execution_disabled(tmp_path, monkeypatch):
    import playground
    from flask import Flask
    monkeypatch.delenv('PYBATGYM_RUNS_DIR', raising=False)
    monkeypatch.delenv('PYBATGYM_EXECUTION_MODE', raising=False)
    monkeypatch.setattr(playground.Path, 'home', classmethod(lambda cls: tmp_path))
    app = Flask('per_user_test')
    playground.initialize(app)
    assert app.config['PLAYGROUND_RUNS_ROOT'] == tmp_path / 'ondemand/data/pybatgym_playground/runs'
    assert app.config['PLAYGROUND_EXECUTION_MODE'] == 'disabled'


def test_missing_csrf_is_rejected_without_creating_run(web):
    _, client, directory = web
    response = client.post('/playground/', data={'backend': 'mock'})
    assert response.status_code == 400
    assert not list(directory.glob('*/status.json'))


@pytest.mark.parametrize('values', [{'workload': '../secret'}, {'policies': []}, {'seed': '-1'},
                                    {'network': 'other'}, {'workload': 'missing'}, {'seed': 'not-a-number'}])
def test_invalid_form_stays_on_page_and_does_not_launch(web, values):
    _, client, directory = web
    response = client.post('/playground/', data=form(client, **values))
    assert response.status_code == 400
    assert 'Cấu hình chưa hợp lệ' in response.get_data(as_text=True)
    assert not list(directory.glob('*/status.json'))


def test_ood_default_mode_does_not_run_compute_on_portal(web, monkeypatch):
    app, client, directory = web
    data = form(client)
    monkeypatch.setitem(app.config, 'PLAYGROUND_EXECUTION_MODE', 'disabled')
    assert client.post('/playground/', data=data).status_code == 503
    assert not list(directory.glob('*/status.json'))


def test_duplicate_launch_returns_same_run(web, monkeypatch):
    _, client, directory = web
    import playground
    calls = []
    def fake_submit(config, output_root):
        calls.append(config)
        path = allocate(output_root)
        write_json(path / 'submission.json', config)
        Status(path, resume=True).set('QUEUED')
        return path
    monkeypatch.setattr(playground, 'submit', fake_submit)
    data = form(client)
    a = client.post('/playground/', data=data)
    b = client.post('/playground/', data=data)
    assert a.status_code == b.status_code == 303
    assert a.location == b.location and len(calls) == 1


def test_browser_launch_is_background_and_survives_new_client(web):
    app, client, directory = web
    started = time.monotonic()
    response = client.post('/playground/', data=form(client, seed='17'))
    assert response.status_code == 303
    assert time.monotonic() - started < 5
    run_id = response.location.rsplit('/', 1)[1]
    second_client = app.test_client()
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        state = second_client.get(response.location + '/status').get_json()
        if state['terminal']:
            break
        time.sleep(0.1)
    assert state['state'] == 'SUCCEEDED', state
    saved = json.loads((directory / run_id / 'request.json').read_text())
    assert saved['seed'] == 17 and saved['policies'] == ['fcfs', 'sjf']
    html = second_client.get(response.location).get_data(as_text=True)
    assert 'PASS' in html and 'FCFS' in html and 'SJF' in html
    csv = second_client.get(response.location + '/download/results/comparison_table.csv')
    assert csv.status_code == 200 and b'FCFS' in csv.data
    assert 'attachment' in csv.headers['Content-Disposition']
    assert 'no-store' in second_client.get(response.location + '/status').headers['Cache-Control']
    assert run_id in second_client.get('/playground/').get_data(as_text=True)


def test_download_allowlist_and_path_escape_protection(web, tmp_path):
    _, client, directory = web
    path = allocate(directory)
    base = '/playground/runs/' + path.name
    assert client.get(base + '/download/metadata.json').status_code == 404
    assert client.get(base + '/download/runtime.json').status_code == 404
    assert client.get('/playground/runs/not-a-run/status').status_code == 404
    external = tmp_path / 'secret.log'
    external.write_text('private')
    (path / 'stdout.log').unlink()
    (path / 'stdout.log').symlink_to(external)
    assert client.get(base + '/download/stdout.log').status_code == 404
    assert client.get(base + '/status').get_json()['stdout'] == ''


def test_log_is_escaped_and_tail_is_bounded(web):
    _, client, directory = web
    path = allocate(directory)
    (path / 'stdout.log').write_text('x' * 100000 + '<script>alert(1)</script>')
    response = client.get('/playground/runs/' + path.name)
    html = response.get_data(as_text=True)
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    payload = client.get('/playground/runs/' + path.name + '/status').get_json()
    assert len(payload['stdout'].encode()) <= 65536


def test_health_does_not_expose_paths_or_secrets(web):
    _, client, _ = web
    payload = client.get('/playground/health').get_json()
    assert payload == {'status': 'ok', 'execution_mode': 'local', 'e2e_workspace': False, 'artifact_schema': 1}
