"""Per-user OOD Passenger UI over Stage 2's durable runner artifacts."""
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, send_file, session, url_for
from pybatgym.runner.config import REPO, Request, resolve
from pybatgym.runner.submit import reap, submit
from pybatgym.runner.storage import write_json

bp = Blueprint('playground', __name__, url_prefix='/playground')
RUN_ID = re.compile(r'^\d{8}T\d{6}-[0-9a-f]{12}$')
TERMINAL = {'SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED'}
STATE_LABELS = {'CREATED': 'Đã tạo', 'QUEUED': 'Đã tiếp nhận', 'VALIDATING': 'Kiểm tra cấu hình',
                'RUNNING': 'Đang chạy', 'VERIFYING': 'Kiểm chứng kết quả', 'SUCCEEDED': 'Thành công',
                'FAILED': 'Thất bại', 'TIMED_OUT': 'Hết thời gian', 'CANCELLED': 'Đã hủy'}
DOWNLOADS = {'request.json', 'config_resolved.json', 'status.json', 'verification.json',
             'stdout.log', 'stderr.log', 'results/comparison_table.csv', 'results/per_episode_metrics.csv',
             'results/jobs.csv', 'results/steps.csv', 'results/benchmark_summary.csv'}


def initialize(app):
    # Passenger runs per Unix user: system-installed source must not be a shared
    # writable result store. Local Compose explicitly selects the repo bind mount.
    default_root = Path.home() / 'ondemand/data/pybatgym_playground/runs'
    root = Path(os.environ.get('PYBATGYM_RUNS_DIR', str(default_root))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app.config.update(PLAYGROUND_RUNS_ROOT=root,
                      PLAYGROUND_EXECUTION_MODE=os.environ.get('PYBATGYM_EXECUTION_MODE', 'disabled'),
                      MAX_CONTENT_LENGTH=16 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    # Stable across Passenger workers/restarts, outside the public artifact allowlist.
    secret_file = root / '.web-session-key'
    try:
        fd = os.open(secret_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    app.secret_key = secret_file.read_text().strip()
    if len(app.secret_key) < 32:
        raise RuntimeError('Invalid web session key')
    app.register_blueprint(bp)


def root():
    return Path(current_app.config['PLAYGROUND_RUNS_ROOT']).resolve()


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def run_dir(run_id):
    if not RUN_ID.fullmatch(run_id):
        abort(404)
    path = root() / run_id
    if path.is_symlink() or not path.is_dir() or path.resolve().parent != root():
        abort(404)
    return path


def safe_file(directory, relative):
    path = directory / relative
    if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        abort(404)
    return path


def tail(directory, relative):
    path = directory / relative
    if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        return ''
    with path.open('rb') as f:
        f.seek(max(0, path.stat().st_size - 64 * 1024))
        return f.read().decode('utf-8', errors='replace')


def catalog():
    presets = []
    for path in sorted((REPO / 'configs').glob('*.yaml')):
        try:
            from pybatgym.config.loader import load_preset
            cfg = load_preset(path.stem)
            presets.append({'id': path.stem, 'cores': cfg.platform.total_cores})
        except Exception:
            continue
    workloads = []
    for path in sorted((REPO / 'data/workloads').glob('*.json')):
        value = read_json(path, {})
        if value.get('nb_res') in {p['cores'] for p in presets} and value.get('jobs'):
            workloads.append({'id': path.stem, 'cores': value['nb_res'], 'jobs': len(value['jobs'])})
    return presets, workloads


def run_summary(directory):
    status = read_json(directory / 'status.json', {})
    config = read_json(directory / 'request.json') or read_json(directory / 'submission.json', {})
    return {'run_id': directory.name, 'state': status.get('state', 'CREATED'),
            'label': STATE_LABELS.get(status.get('state'), 'Chưa xác định'),
            'created_at': status.get('created_at', ''), 'backend': config.get('backend', ''),
            'workload': config.get('workload', ''), 'policies': config.get('policies', []), 'status': status}


def recent_runs():
    reap()
    directories = sorted((d for d in root().iterdir() if RUN_ID.fullmatch(d.name)
                          and d.is_dir() and not d.is_symlink()), key=lambda p: p.name, reverse=True)
    return [run_summary(d) for d in directories[:50]]


def form_values():
    allowed = {'backend', 'workload', 'preset', 'policies', 'seed', 'random_seeds', 'timeout_seconds', 'csrf_token', 'launch_token'}
    if set(request.form) - allowed:
        raise ValueError('Cấu hình có trường không được hỗ trợ.')
    return {'backend': request.form.get('backend', 'mock'), 'workload': request.form.get('workload', ''),
            'preset': request.form.get('preset', ''), 'policies': request.form.getlist('policies'),
            'seed': int(request.form.get('seed', '0')), 'random_seeds': int(request.form.get('random_seeds', '1')),
            'timeout_seconds': float(request.form.get('timeout_seconds', '120'))}


def show_form(values=None, error=None, code=200):
    session.setdefault('csrf', secrets.token_hex(32))
    presets, workloads = catalog()
    values = values or Request().model_dump(mode='json')
    return render_template('playground/home.html', values=values, presets=presets, workloads=workloads,
                           recent=recent_runs(), error=error, csrf=session['csrf'], launch_token=secrets.token_hex(24),
                           execution_enabled=current_app.config['PLAYGROUND_EXECUTION_MODE'] == 'local'), code


@bp.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'GET':
        return show_form()
    token = request.form.get('csrf_token', '')
    if not token or not hmac.compare_digest(token, session.get('csrf', '')):
        abort(400, 'Phiên biểu mẫu đã hết hạn. Hãy tải lại trang.')
    if current_app.config['PLAYGROUND_EXECUTION_MODE'] != 'local':
        return show_form(error='Khởi chạy local chưa được bật trong môi trường này.', code=503)
    launch_token = request.form.get('launch_token', '')
    if not re.fullmatch(r'[a-f0-9]{48}', launch_token):
        abort(400)
    # Atomic idempotency claim handles refresh/double-click across WSGI workers.
    claims = root() / '.launch-claims'
    claims.mkdir(exist_ok=True)
    claim = claims / hashlib.sha256((session['csrf'] + launch_token).encode()).hexdigest()
    values = None
    try:
        values = form_values()
        config = Request.model_validate(values)
        resolve(config)
    except Exception as exc:
        return show_form(values=values, error=f'Cấu hình chưa hợp lệ: {exc}', code=400)
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        record = read_json(claim, {})
        if record.get('run_id'):
            return redirect(url_for('playground.detail', run_id=record['run_id']), code=303)
        return show_form(values=values, error='Yêu cầu này đang được tiếp nhận. Hãy xem danh sách thí nghiệm.', code=409)
    else:
        os.close(fd)
    try:
        directory = submit(config.model_dump(mode='json'), root())
        write_json(claim, {'run_id': directory.name})
    except Exception as exc:
        write_json(claim, {'error': str(exc)})
        return show_form(values=values, error=f'Không thể khởi chạy: {exc}', code=503)
    return redirect(url_for('playground.detail', run_id=directory.name), code=303)


def results_table(directory):
    path = directory / 'results/comparison_table.csv'
    if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
        return []
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))[:20]


@bp.get('/runs/<run_id>')
def detail(run_id):
    directory = run_dir(run_id)
    summary = run_summary(directory)
    return render_template('playground/detail.html', run=summary, terminal=summary['state'] in TERMINAL,
                           stdout=tail(directory, 'stdout.log'), stderr=tail(directory, 'stderr.log'),
                           verification=read_json(directory / 'verification.json', {}),
                           metrics=results_table(directory),
                           downloads=[name for name in sorted(DOWNLOADS) if (directory / name).is_file()])


@bp.get('/runs/<run_id>/status')
def status(run_id):
    directory = run_dir(run_id)
    summary = run_summary(directory)
    payload = {key: summary[key] for key in ('run_id', 'state', 'label')}
    payload.update(terminal=summary['state'] in TERMINAL, updated_at=summary['status'].get('updated_at'),
                   history=summary['status'].get('history', []), error=summary['status'].get('error'),
                   error_code=summary['status'].get('error_code'), stdout=tail(directory, 'stdout.log'),
                   stderr=tail(directory, 'stderr.log'))
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('/runs/<run_id>/download/<path:artifact>')
def download(run_id, artifact):
    if artifact not in DOWNLOADS:
        abort(404)
    path = safe_file(run_dir(run_id), artifact)
    return send_file(path, as_attachment=True, download_name=f'{run_id}-{path.name}', conditional=True)


@bp.after_request
def response_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response
