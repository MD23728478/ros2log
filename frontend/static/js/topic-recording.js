(() => {
  const topic = document.getElementById('recording-topic');
  const state = document.getElementById('recording-state');
  const output = document.getElementById('recording-output');
  const start = document.getElementById('recording-start');
  const stop = document.getElementById('recording-stop');
  const error = document.getElementById('recording-error');
  let pollId = null;
  let selectedTopics = [];

  function selectedTopicLabels() {
    if (!selectedTopics.length) return 'Select one or more topics from the list.';
    if (selectedTopics.length === 1) return selectedTopics[0];
    return `${selectedTopics.length} topics selected`;
  }

  function syncTopic() {
    topic.textContent = state.dataset.state === 'running'
      ? (selectedTopics.length ? selectedTopics.join(', ') : 'Recording in progress.')
      : selectedTopicLabels();
    start.disabled = state.dataset.state === 'running' || !selectedTopics.length;
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
    start.disabled = current === 'running' || !selectedTopics.length;
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

  function updateSelection(topics = []) {
    selectedTopics = Array.isArray(topics) ? topics : [];
    syncTopic();
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
    try {
      render(await request('/api/record/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topics: selectedTopics }),
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

  window.addEventListener('topics:selected', (event) => updateSelection(event.detail));
  start.addEventListener('click', startRecording);
  stop.addEventListener('click', stopRecording);
  setState('idle');
  syncTopic();
  checkStatus(true);
})();
