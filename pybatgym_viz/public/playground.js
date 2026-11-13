document.querySelectorAll('time[datetime]').forEach(el => {
  const date = new Date(el.dateTime);
  if (!Number.isNaN(date.getTime())) el.textContent = new Intl.DateTimeFormat('vi-VN', {dateStyle:'short',timeStyle:'medium'}).format(date);
});
const form = document.getElementById('launch-form');
if (form) {
  const workload = document.getElementById('workload'), preset = document.getElementById('preset');
  const button = document.getElementById('launch-button');
  const check = () => {
    const mismatch = workload.selectedOptions[0]?.dataset.cores !== preset.selectedOptions[0]?.dataset.cores;
    document.getElementById('compatibility').hidden = !mismatch;
    button.disabled = mismatch;
  };
  workload.addEventListener('change', check); preset.addEventListener('change', check); check();
  form.addEventListener('submit', () => {button.disabled = true; button.textContent = 'Đang tiếp nhận…';});
}
const monitor = document.getElementById('run-monitor');
if (monitor && monitor.dataset.terminal === 'false') {
  const poll = async () => {
    try {
      const response = await fetch(monitor.dataset.statusUrl, {cache:'no-store',credentials:'same-origin'});
      if (!response.ok) throw new Error('Status unavailable');
      const data = await response.json();
      document.getElementById('poll-error').hidden = true;
      const badge = document.getElementById('run-state');
      badge.textContent = data.label; badge.className = 'badge large ' + data.state.toLowerCase();
      document.getElementById('stdout-log').textContent = data.stdout || 'Đang chờ log…';
      document.getElementById('stderr-log').textContent = data.stderr || 'Chưa ghi nhận thông tin lỗi.';
      if (data.terminal) {window.location.reload(); return;}
    } catch (_) {document.getElementById('poll-error').hidden = false;}
    window.setTimeout(poll, 2000);
  };
  window.setTimeout(poll, 1000);
}
