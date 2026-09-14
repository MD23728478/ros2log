(() => {
  const input = document.getElementById('topic-monitor-input');
  const topic = document.getElementById('recording-topic');
  const state = document.getElementById('recording-state');
  const output = document.getElementById('recording-output');
  const start = document.getElementById('recording-start');
  const stop = document.getElementById('recording-stop');
  const error = document.getElementById('recording-error');
  let pollId = null;
  let activeTopic = '';

  function selectedTopic() {
    return input.value.trim();
  }

  function syncTopic() {
    topic.textContent = state.dataset.state === 'running'
      ? activeTopic || 'Recording in progress.'
      : selectedTopic() || 'Select a topic from the list.';
    start.disabled = state.dataset.state === 'running' || !selectedTopic();
  }

  function showError(message = '') {
    error.textContent = message;
    error.style.display = message ? 'block' : 'none';
  }

  function setState(value = 'idle') {
    const current = value.toLowerCase();
    state.dataset.state = current;
    state.className = `recording-state ${current}`;
    state.textContent = current[0].toUpperCase() + current.slice(1);
    start.disabled = current === 'running' || !selectedTopic();
    stop.disabled = current !== 'running';
    syncTopic();

    if (current === 'running' && !pollId) {
      pollId = setInterval(checkStatus, 2000);
    } else if (current !== 'running' && pollId) {
      clearInterval(pollId);
      pollId = null;
    }
  }

  function render(data) {
    setState(data.state || 'idle');
    if (data.output) output.textContent = data.output;
  }

  async function request(url, options) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok) {
      const failure = new Error(data.error || `HTTP ${response.status}`);
      failure.status = response.status;
      throw failure;
    }
    return data;
  }

  async function checkStatus(initial = false) {
    try {
      render(await request('/api/record/status'));
    } catch (failure) {
      if (initial && failure.status === 404) return;
      showError(failure.message);
      setState('error');
    }
  }

  async function startRecording() {
    showError();
    start.disabled = true;
    activeTopic = selectedTopic();
    try {
      render(await request('/api/record/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topics: [activeTopic] }),
      }));
    } catch (failure) {
      showError(failure.message);
      setState('error');
    }
  }

  async function stopRecording() {
    showError();
    stop.disabled = true;
    try {
      render(await request('/api/record/stop', { method: 'POST' }));
    } catch (failure) {
      showError(failure.message);
      setState('error');
    }
  }

  input.addEventListener('input', syncTopic);
  start.addEventListener('click', startRecording);
  stop.addEventListener('click', stopRecording);
  setState('idle');
  syncTopic();
  checkStatus(true);
})();
