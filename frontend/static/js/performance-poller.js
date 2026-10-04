(() => {
  const STORAGE_KEY = 'ros2log.performance.v1';
  const configuredSeconds = Number(document.body.dataset.performancePollInterval);
  const intervalMs = Number.isFinite(configuredSeconds) && configuredSeconds > 0
    ? configuredSeconds * 1000
    : 300000;
  let timer = null;
  let inFlight = false;
  let memoryState = emptyState();

  function emptyState() {
    return {
      lastAttemptMs: 0,
      lastPollAt: null,
      polling: false,
      sampledAt: null,
      latest: null,
      error: null,
      histories: { application: [], runner: [] },
    };
  }

  function readState() {
    try {
      const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
      if (value && value.histories?.application && value.histories?.runner) {
        memoryState = value;
      }
    } catch (_) {
      // sessionStorage may be disabled; in-memory polling still works.
    }
    return memoryState;
  }

  function writeState(state) {
    memoryState = state;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      // Keep the current page functional if session storage is unavailable.
    }
  }

  function notify() {
    window.dispatchEvent(new CustomEvent('performance:update', {
      detail: readState(),
    }));
  }

  function addSamples(state, response) {
    ['application', 'runner'].forEach((name) => {
      const target = response.targets?.[name];
      if (target?.status !== 'ok' || !target.metrics) return;
      state.histories[name].push({
        sampledAt: response.sampled_at,
        cpuPercent: target.metrics.cpu_percent,
        memoryPercent: target.metrics.memory?.percent ?? null,
      });
      state.histories[name] = state.histories[name].slice(-30);
    });
  }

  function schedule(delay = intervalMs) {
    clearTimeout(timer);
    timer = setTimeout(poll, Math.max(0, delay));
  }

  async function poll() {
    if (inFlight) return;
    inFlight = true;
    const state = readState();
    state.lastAttemptMs = Date.now();
    state.polling = true;
    state.error = null;
    writeState(state);
    notify();

    try {
      const response = await fetch('/api/performance', { cache: 'no-store' });
      const data = await response.json();
      if (!data || !data.targets || !data.sampled_at) {
        throw new Error('The server returned an incomplete performance reading.');
      }
      state.latest = data;
      state.sampledAt = data.sampled_at;
      addSamples(state, data);
      if (!response.ok) {
        state.error = 'Performance data is currently unavailable.';
      }
    } catch (error) {
      state.error = error.message || 'Unable to retrieve performance data.';
    } finally {
      state.lastPollAt = new Date().toISOString();
      state.polling = false;
      writeState(state);
      inFlight = false;
      notify();
      schedule();
    }
  }

  function start() {
    const state = readState();
    const elapsed = Date.now() - (state.lastAttemptMs || 0);
    if (!state.latest || elapsed >= intervalMs) {
      poll();
    } else {
      schedule(intervalMs - elapsed);
      notify();
    }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    const elapsed = Date.now() - (readState().lastAttemptMs || 0);
    if (elapsed >= intervalMs) poll();
  });

  window.performanceMonitor = {
    getState: () => readState(),
    refresh: poll,
    intervalMs,
  };
  start();
})();
