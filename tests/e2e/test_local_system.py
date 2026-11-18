"""Real browser -> WSGI UI -> detached runner -> Mock/BatSim -> verified output.

No fake scheduler, mocked runner, or substituted simulator in this suite.
"""
import csv
import io
import json
import os
from pathlib import Path
import re
import time

import pytest

pytestmark = pytest.mark.e2e
RUNS = Path(os.environ.get('PYBATGYM_E2E_RUNS_DIR', str(Path(__file__).resolve().parents[2] / 'runs/e2e')))


def current_ids():
    return {p.name for p in RUNS.iterdir() if p.is_dir() and re.fullmatch(r'\d{8}T\d{6}-[a-f0-9]{12}', p.name)} if RUNS.exists() else set()


def payload(case, **changes):
    return {'csrf_token': case.page.locator('input[name="csrf_token"]').get_attribute('value'),
            'launch_token': case.page.locator('input[name="launch_token"]').get_attribute('value'),
            'backend': 'mock', 'workload': 'gen_c32_s0', 'preset': 'medium_batsim',
            'policies': 'fcfs', 'seed': '0', 'random_seeds': '1', 'timeout_seconds': '120', **changes}


def verify_success(case, run_id, backend, policies=('FCFS', 'SJF')):
    state = case.wait(run_id)
    assert state['state'] == 'SUCCEEDED', state
    verification = case.artifact(run_id, 'verification.json').json()
    assert verification['status'] == 'PASS' and verification['backend'] == backend
    assert {ep['policy'] for ep in verification['episodes']} == set(policies)
    assert all(ep['completed_jobs'] == 100 for ep in verification['episodes'])
    jobs = list(csv.DictReader(io.StringIO(case.artifact(run_id, 'results/jobs.csv').text())))
    assert len(jobs) == 100 * len(policies)
    assert all(float(j['actual_runtime']) > 0 for j in jobs)
    if backend == 'real':
        assert all(ep['native_max_error_seconds'] < .001 for ep in verification['episodes'])
        for i in range(len(policies)):
            directory = RUNS / run_id / 'simulator' / str(i)
            exported = list(csv.DictReader((directory / 'batsim_jobs.csv').open(encoding='utf-8')))
            container = json.loads((directory / 'container.json').read_text())
            assert len(exported) == 100 and all(j['success'] == '1' for j in exported)
            assert container['state']['Running'] is False and container['state']['ExitCode'] == 0
    return state, verification


def test_tc01_form_and_ood_prefix(case):
    case.open()
    assert '/pun/dev/pybatgym_playground/playground/' in case.page.url
    assert case.page.locator('#launch-button').is_enabled()
    links = case.page.locator('a[href],link[href],script[src],form[action]').evaluate_all(
        "els => els.map(e => e.getAttribute('href') || e.getAttribute('src') || e.getAttribute('action'))")
    assert all(url.startswith('/pun/dev/pybatgym_playground/') for url in links)
    assert not case.console_errors


def test_tc02_mock_launch_to_verified_results(case):
    case.open()
    run_id = case.launch(seed=23)
    state, _ = verify_success(case, run_id, 'mock')
    history = [e['state'] for e in state['history']]
    assert all(phase in history for phase in ('QUEUED', 'VALIDATING', 'RUNNING', 'VERIFYING', 'SUCCEEDED'))
    case.page.locator('#run-state.succeeded').wait_for(timeout=15000)
    assert 'PASS' in case.page.locator('.summary-grid').inner_text()
    saved = case.artifact(run_id, 'request.json').json()
    assert saved['seed'] == 23 and saved['backend'] == 'mock'
    rows = case.page.locator('tbody tr').all_inner_texts()
    assert any('1405.379' in r for r in rows) and any('539.403' in r for r in rows)
    assert not case.console_errors


def test_tc03_real_launch_logs_csv_and_native_exports(case):
    case.open()
    run_id = case.launch(backend='real')
    verify_success(case, run_id, 'real')
    case.page.locator('#run-state.succeeded').wait_for(timeout=15000)
    log = case.page.locator('#stdout-log').inner_text()
    assert 'Simulation ENDS' in log and 'jobs=100/100' in log
    assert '[BatSim thread] Exception' not in log
    with case.page.expect_download() as event:
        case.page.get_by_role('link', name='Tải CSV ↓', exact=True).click()
    download = event.value
    target = case.directory / 'comparison.csv'
    download.save_as(target)
    assert target.read_bytes() == (RUNS / run_id / 'results/comparison_table.csv').read_bytes()
    table = list(csv.DictReader(target.open(encoding='utf-8')))
    assert {r['policy'] for r in table} == {'FCFS', 'SJF'}
    assert all(r['n_incomplete'] == '0' for r in table)


def test_tc04_missing_policy_is_rejected(case):
    case.open()
    before = current_ids()
    for value in ('fcfs', 'sjf', 'easy', 'random'):
        case.page.locator(f'input[name="policies"][value="{value}"]').uncheck()
    case.page.get_by_role('button', name='Launch experiment').click()
    case.page.get_by_role('alert').wait_for()
    assert 'Cấu hình chưa hợp lệ' in case.page.get_by_role('alert').inner_text()
    assert current_ids() == before


def test_tc05_workload_platform_mismatch_blocks_launch(case):
    case.open()
    before = current_ids()
    case.page.locator('#preset').select_option('small_batsim')
    assert case.page.locator('#compatibility').is_visible()
    assert not case.page.locator('#launch-button').is_enabled()
    case.page.locator('#preset').select_option('medium_batsim')
    assert case.page.locator('#launch-button').is_enabled()
    assert current_ids() == before


def test_tc06_duplicate_post_creates_only_one_run(case):
    case.open()
    before = current_ids()
    data = payload(case)
    a = case.context.request.post(case.home, form=data, max_redirects=0)
    b = case.context.request.post(case.home, form=data, max_redirects=0)
    assert a.status == b.status == 303
    assert a.headers['location'] == b.headers['location']
    run_id = a.headers['location'].rsplit('/', 1)[1]
    case.runs.append(run_id)
    verify_success(case, run_id, 'mock', ('FCFS',))
    assert current_ids() - before == {run_id}
    case.page.goto(case.base + a.headers['location'])


def test_tc07_real_timeout_is_visible_and_cleaned_up(case):
    case.open()
    run_id = case.launch(backend='real', policies=('fcfs',), timeout=1)
    state = case.wait(run_id)
    assert state['state'] == 'TIMED_OUT' and state['error_code'] == 'TIMEOUT'
    case.page.locator('#run-state.timed_out').wait_for(timeout=15000)
    assert 'TIMEOUT' in case.page.get_by_role('alert').inner_text()
    assert not (RUNS / run_id / 'verification.json').exists()
    for info in (RUNS / run_id / 'simulator').glob('*/container.json'):
        assert json.loads(info.read_text())['state']['Running'] is False


def test_tc08_second_real_run_reports_busy_without_interference(case):
    case.open()
    first = case.launch(backend='real', policies=('fcfs',))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and case.state(first)['state'] != 'RUNNING':
        time.sleep(.05)
    assert case.state(first)['state'] == 'RUNNING'
    case.page = case.context.new_page()
    case.open()
    second = case.launch(backend='real', policies=('fcfs',))
    busy = case.wait(second)
    assert busy['state'] == 'FAILED' and busy['error_code'] == 'REAL_BUSY'
    verify_success(case, first, 'real', ('FCFS',))
    assert not (RUNS / second / 'simulator').exists()
    case.page.locator('#run-state.failed').wait_for(timeout=15000)
    assert 'REAL_BUSY' in case.page.get_by_role('alert').inner_text()


def test_tc09_close_and_reopen_page_keeps_run(case):
    case.open()
    run_id = case.launch(policies=('fcfs',))
    detail = case.page.url
    case.page.close()
    case.page = case.context.new_page()
    case.page.goto(detail)
    case.page.reload()
    verify_success(case, run_id, 'mock', ('FCFS',))
    case.page.locator('#run-state.succeeded').wait_for(timeout=15000)
    case.page.get_by_role('link', name='← Tất cả thí nghiệm').click()
    assert case.page.get_by_role('link', name=run_id, exact=True).is_visible()


def test_tc10_repeat_runs_have_separate_immutable_output(case):
    case.open()
    first = case.launch(policies=('fcfs',), seed=5)
    verify_success(case, first, 'mock', ('FCFS',))
    original = (RUNS / first / 'results/jobs.csv').read_bytes()
    case.open()
    second = case.launch(policies=('fcfs',), seed=5)
    verify_success(case, second, 'mock', ('FCFS',))
    assert first != second
    assert (RUNS / first / 'results/jobs.csv').read_bytes() == original
    assert (RUNS / first / 'status.json').resolve() != (RUNS / second / 'status.json').resolve()


def test_tc11_csrf_and_download_boundaries(case):
    case.open()
    before = current_ids()
    response = case.context.request.post(case.home, form={'backend': 'mock'})
    assert response.status == 400 and current_ids() == before
    run_id = case.launch(policies=('fcfs',))
    verify_success(case, run_id, 'mock', ('FCFS',))
    base = case.home + 'runs/' + run_id + '/download/'
    for name in ('metadata.json', 'runtime.json', '../../.web-session-key'):
        assert case.context.request.get(base + name).status == 404


def test_tc12_mobile_form_remains_usable(case):
    case.page.set_viewport_size({'width': 390, 'height': 844})
    case.open()
    assert case.page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    case.page.locator('#launch-button').scroll_into_view_if_needed()
    assert case.page.locator('#launch-button').is_visible() and case.page.locator('#launch-button').is_enabled()


def test_tc13_unknown_run_has_no_data_leak(case):
    case.open()
    response = case.context.request.get(case.home + 'runs/20000101T000000-000000000000/status')
    assert response.status == 404
    response = case.context.request.get(case.home + 'runs/invalid/download/stdout.log')
    assert response.status == 404


def test_tc14_tampered_input_rejected_server_side(case):
    case.open()
    before = current_ids()
    response = case.context.request.post(case.home, form=payload(case, workload='../secret'), max_redirects=0)
    assert response.status == 400
    assert current_ids() == before
    case.page.get_by_role('heading', name='Thí nghiệm mới').wait_for()


def test_tc15_temporary_browser_disconnect_recovers(case):
    case.open()
    run_id = case.launch(policies=('fcfs',))
    case.page.wait_for_load_state('load')
    case.context.set_offline(True)
    try:
        case.page.locator('#poll-error').wait_for(state='visible', timeout=10000)
    finally:
        case.context.set_offline(False)
    verify_success(case, run_id, 'mock', ('FCFS',))
    case.page.locator('#run-state.succeeded').wait_for(timeout=15000)
    assert not case.page.locator('#poll-error').is_visible()
