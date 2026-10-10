(() => {
  const updated = document.getElementById('performance-updated');
  const pollButton = document.getElementById('performance-poll-now');
  const cards = Object.fromEntries(
    Array.from(document.querySelectorAll('[data-performance-target]'))
      .map((card) => [card.dataset.performanceTarget, card])
  );

  const role = (card, name) => card.querySelector(`[data-role="${name}"]`);

  function formatBytes(value) {
    if (!Number.isFinite(value)) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let index = 0;
    while (size >= 1000 && index < units.length - 1) {
      size /= 1000;
      index += 1;
    }
    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
  }

  function formatUptime(seconds) {
    if (!Number.isFinite(seconds)) return 'Not available';
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return [days ? `${days}d` : '', hours ? `${hours}h` : '', `${minutes}m`]
      .filter(Boolean).join(' ');
  }

  function drawChart(svg, values) {
    svg.replaceChildren();
    const grid = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    grid.setAttribute('d', 'M0 0H300 M0 40H300 M0 79H300');
    grid.setAttribute('class', 'performance-chart-grid');
    svg.append(grid);
    if (!values.length) return;

    const coordinates = values.map((value, index) => {
      const x = values.length === 1 ? 150 : index / (values.length - 1) * 300;
      const y = 79 - Math.max(0, Math.min(100, value)) / 100 * 79;
      return [x, y];
    });
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', coordinates.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '));
    line.setAttribute('class', 'performance-chart-line');
    svg.append(line);
    const [latestX, latestY] = coordinates.at(-1);
    const point = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    point.setAttribute('cx', latestX.toFixed(1));
    point.setAttribute('cy', latestY.toFixed(1));
    point.setAttribute('r', '3');
    point.setAttribute('class', 'performance-chart-point');
    svg.append(point);
  }

  function renderTarget(name, target, history) {
    const card = cards[name];
    if (!card) return;
    const status = role(card, 'status');
    if (!target || target.status !== 'ok') {
      card.classList.add('error');
      status.textContent = target?.error || 'Unavailable';
      return;
    }

    card.classList.remove('error');
    status.textContent = '';
    const metrics = target.metrics;
    role(card, 'hostname').textContent = `(${metrics.hostname || 'Not available'})`;
    role(card, 'cpu-value').textContent = Number.isFinite(metrics.cpu_percent)
      ? `${metrics.cpu_percent.toFixed(1)}%` : 'Not available';
    role(card, 'memory-value').textContent = metrics.memory
      ? `${metrics.memory.percent.toFixed(1)}%` : 'Not available';
    role(card, 'memory-detail').textContent = metrics.memory
      ? `${formatBytes(metrics.memory.used_bytes)} of ${formatBytes(metrics.memory.total_bytes)}` : '—';
    if (metrics.storage) role(card, 'storage-path').textContent = metrics.storage.path;
    const freeBytes = metrics.storage && name === 'application'
      ? (metrics.storage.free_bytes ?? metrics.storage.total_bytes - metrics.storage.used_bytes)
      : null;
    const storagePercent = metrics.storage
      ? (freeBytes === null ? metrics.storage.percent : freeBytes / metrics.storage.total_bytes * 100)
      : 0;
    role(card, 'storage-value').textContent = metrics.storage
      ? `${storagePercent.toFixed(1)}%` : 'Not available';
    role(card, 'storage-detail').textContent = metrics.storage
      ? `${formatBytes(freeBytes ?? metrics.storage.used_bytes)} ${freeBytes === null ? 'used' : 'free'} of ${formatBytes(metrics.storage.total_bytes)}` : '—';
    const storageBar = role(card, 'storage-bar');
    storageBar.style.width = `${storagePercent}%`;
    if (metrics.storage) {
      storageBar.parentElement.setAttribute('aria-valuenow', String(storagePercent));
      storageBar.parentElement.removeAttribute('aria-valuetext');
    } else {
      storageBar.parentElement.removeAttribute('aria-valuenow');
      storageBar.parentElement.setAttribute('aria-valuetext', 'Not available');
    }
    role(card, 'uptime').textContent = `Uptime: ${formatUptime(metrics.uptime_seconds)}`;

    drawChart(
      role(card, 'cpu-chart'),
      history.map((sample) => sample.cpuPercent).filter(Number.isFinite)
    );
    drawChart(
      role(card, 'memory-chart'),
      history.map((sample) => sample.memoryPercent).filter(Number.isFinite)
    );
  }

  function render(state) {
    if (!state) return;
    updated.textContent = state.lastPollAt
      ? `Last: ${new Date(state.lastPollAt).toLocaleTimeString()}`
      : 'Last: —';
    pollButton.disabled = Boolean(state.polling);
    pollButton.textContent = state.polling ? 'Polling…' : pollButton.dataset.label;
    const targets = state.latest?.targets || {};
    renderTarget('application', targets.application, state.histories.application || []);
    renderTarget('runner', targets.runner, state.histories.runner || []);
  }

  window.addEventListener('performance:update', (event) => render(event.detail));
  pollButton.addEventListener('click', () => window.performanceMonitor?.refresh());
  render(window.performanceMonitor?.getState());
})();
