"""Opt-in local browser tests. Never submit experiments to a non-E2E workspace."""
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import pytest


def pytest_addoption(parser):
    parser.addoption('--e2e-url', default='http://127.0.0.1:5051', help='Isolated local preview URL')
    parser.addoption('--e2e-channel', default='chrome', choices=['chrome', 'msedge', 'chromium'])
    parser.addoption('--e2e-artifacts', default='test-results/e2e', help='Screenshots/traces and JSON report directory')


@pytest.fixture(scope='session')
def e2e_browser(pytestconfig):
    if os.environ.get('PYBATGYM_E2E') != '1':
        pytest.skip('Opt-in E2E: use scripts/test_e2e.ps1 or PYBATGYM_E2E=1')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.fail('Install tests/e2e/requirements.txt in an isolated test environment')
    base = pytestconfig.getoption('--e2e-url').rstrip('/')
    url = urlparse(base)
    if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1'):
        pytest.fail('E2E is restricted to an isolated loopback workspace')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,
                    channel=None if pytestconfig.getoption('--e2e-channel') == 'chromium' else pytestconfig.getoption('--e2e-channel'))
        context = browser.new_context()
        health = context.request.get(base + '/pun/dev/pybatgym_playground/playground/health')
        assert health.ok, 'Local E2E service is unavailable'
        value = health.json()
        assert value.get('e2e_workspace') is True and value.get('execution_mode') == 'local', \
            'Refusing to run against the normal user workspace'
        context.close()
        yield browser, base
        browser.close()


class Case:
    def __init__(self, browser, base, directory):
        self.directory = directory
        self.base = base
        self.context = browser.new_context(accept_downloads=True, viewport={'width': 1280, 'height': 900}, locale='vi-VN')
        self.context.tracing.start(screenshots=True, snapshots=True, sources=False)
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        self.runs = []
        self.console_errors = []
        self.page.on('pageerror', lambda error: self.console_errors.append(str(error)))
        self.home = base + '/pun/dev/pybatgym_playground/playground/'

    def open(self):
        self.page.goto(self.home)
        self.page.get_by_role('heading', name='Thí nghiệm mới', exact=True).wait_for()

    def launch(self, backend='mock', policies=('fcfs', 'sjf'), seed=0, timeout=120):
        self.page.locator(f'input[name="backend"][value="{backend}"]').check()
        for policy in ('fcfs', 'sjf', 'easy', 'random'):
            self.page.locator(f'input[name="policies"][value="{policy}"]').set_checked(policy in policies)
        self.page.locator('input[name="seed"]').fill(str(seed))
        self.page.locator('input[name="timeout_seconds"]').fill(str(timeout))
        self.page.get_by_role('button', name='Launch experiment').click()
        self.page.wait_for_url(re.compile(r'/runs/\d{8}T\d{6}-[a-f0-9]{12}$'))
        run_id = self.page.url.rsplit('/', 1)[-1]
        self.runs.append(run_id)
        return run_id

    def state(self, run_id):
        response = self.context.request.get(self.home + 'runs/' + run_id + '/status')
        assert response.ok
        return response.json()

    def wait(self, run_id, timeout=160):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.state(run_id)
            if state['terminal']:
                (self.directory / (run_id + '-status.json')).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
                return state
            time.sleep(.25)
        pytest.fail(f'Run did not terminate: {run_id}')

    def artifact(self, run_id, artifact):
        response = self.context.request.get(self.home + 'runs/' + run_id + '/download/' + artifact)
        assert response.ok, (artifact, response.status)
        return response


@pytest.fixture
def case(e2e_browser, pytestconfig, request):
    browser, base = e2e_browser
    directory = Path(pytestconfig.getoption('--e2e-artifacts')).resolve() / request.node.name
    directory.mkdir(parents=True, exist_ok=True)
    value = Case(browser, base, directory)
    yield value
    # Leave the service and user containers alone. Let only our submitted runs finish.
    states = {}
    for run_id in value.runs:
        try:
            states[run_id] = value.wait(run_id, timeout=130)['state']
        except (Exception, pytest.fail.Exception) as exc:
            states[run_id] = str(exc)
    try:
        value.page.screenshot(path=str(directory / 'page.png'), full_page=True)
    except Exception:
        pass
    (directory / 'case.json').write_text(json.dumps({'test': request.node.name, 'runs': states,
        'console_errors': value.console_errors, 'url': value.page.url}, indent=2, ensure_ascii=False), encoding='utf-8')
    value.context.tracing.stop(path=str(directory / 'trace.zip'))
    value.context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    item.stash.setdefault('e2e_reports', []).append(report)


def pytest_sessionfinish(session, exitstatus):
    if os.environ.get('PYBATGYM_E2E') != '1':
        return
    reports = []
    for item in session.items:
        for report in item.stash.get('e2e_reports', []):
            if report.when == 'call' or (report.when == 'setup' and not report.passed):
                reports.append({'test': item.name, 'outcome': report.outcome, 'duration_seconds': report.duration,
                                'error': str(report.longrepr) if report.failed else None})
    directory = Path(session.config.getoption('--e2e-artifacts')).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'report.json').write_text(json.dumps({'exit_code': exitstatus, 'tests': reports}, indent=2), encoding='utf-8')
