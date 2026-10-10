(() => {
  const topic = document.getElementById('recording-topic');
  const state = document.getElementById('recording-state');
  const output = document.getElementById('recording-output');
  const prefix = document.getElementById('recording-prefix');
  const hours = document.getElementById('recording-hours');
  const minutes = document.getElementById('recording-minutes');
  const seconds = document.getElementById('recording-seconds');
  const start = document.getElementById('recording-start');
  const stop = document.getElementById('recording-stop');
  const error = document.getElementById('recording-error');
  const elapsedBadge = document.getElementById('recording-elapsed');
  const elapsedStorageKey = 'ros2log.recording.elapsedStartedAt';
  let pollId = null;
  let selectedTopics = [];
  let elapsedStartedAt = null;
  let elapsedTimerId = null;

  function isActiveState(value) {
    return value === 'running' || value === 'stopping';
  }

  function readStoredElapsedStart() {
    try {
      const value = window.localStorage.getItem(elapsedStorageKey);
      const parsed = value === null ? NaN : Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    } catch {
      return null;
    }
  }

  function storeElapsedStart(value) {
    try {
      if (value === null) {
        window.localStorage.removeItem(elapsedStorageKey);
      } else {
        window.localStorage.setItem(elapsedStorageKey, String(value));
      }
    } catch {
      // Ignore storage failures and keep the live timer working.
    }
  }

  function setElapsedStart(value) {
    elapsedStartedAt = value;
    storeElapsedStart(value);
  }

  function selectedTopicLabels() {
    if (!selectedTopics.length) return 'Select one or more topics from the list.';
    if (selectedTopics.length === 1) return selectedTopics[0];
    return `${selectedTopics.length} topics selected`;
  }

  function syncTopic() {
    topic.textContent = isActiveState(state.dataset.state)
      ? (selectedTopics.length ? selectedTopics.join(', ') : 'Recording in progress.')
      : selectedTopicLabels();
    start.disabled = isActiveState(state.dataset.state) || !selectedTopics.length;
  }

  function showError(message = '') {
    error.textContent = message;
    error.style.display = message ? 'block' : 'none';
  }

  function getDurationSeconds() {
    const hourValue = hours.value === '' ? 0 : Number(hours.value);
    const minuteValue = minutes.value === '' ? 0 : Number(minutes.value);
    const secondValue = seconds.value === '' ? 0 : Number(seconds.value);

    if (
      !Number.isInteger(hourValue) ||
      !Number.isInteger(minuteValue) ||
      !Number.isInteger(secondValue) ||
      hourValue < 0 ||
      minuteValue < 0 ||
      minuteValue > 59 ||
      secondValue < 0 ||
      secondValue > 59
    ) {
      throw new Error('Enter a valid recording duration.');
    }

    const totalSeconds =
      (hourValue * 3600) +
      (minuteValue * 60) +
      secondValue;

    if (totalSeconds > 86400) {
      throw new Error('Recording duration cannot exceed 24 hours.');
    }

    return totalSeconds > 0 ? totalSeconds : null;
  }

  function formatElapsedSeconds(totalSeconds) {
    const safeSeconds = Math.max(0, Math.floor(totalSeconds));
    const hoursValue = String(Math.floor(safeSeconds / 3600)).padStart(2, '0');
    const minutesValue = String(Math.floor((safeSeconds % 3600) / 60)).padStart(2, '0');
    const secondsValue = String(safeSeconds % 60).padStart(2, '0');
    return `${hoursValue}:${minutesValue}:${secondsValue}`;
  }

  function updateElapsedBadge() {
    if (state.dataset.state !== 'running' || elapsedStartedAt === null) {
      elapsedBadge.textContent = '00:00';
      return;
    }

    const elapsedSeconds = (Date.now() - elapsedStartedAt) / 1000;
    elapsedBadge.textContent = formatElapsedSeconds(elapsedSeconds);
  }

  function clearElapsedTimer({ clearStorage = true } = {}) {
    if (clearStorage) {
      setElapsedStart(null);
    }
    if (elapsedTimerId) {
      clearInterval(elapsedTimerId);
      elapsedTimerId = null;
    }
    elapsedBadge.textContent = '00:00';
  }

  function setState(value = 'idle') {
    const current = value.toLowerCase();
    state.dataset.state = current;
    state.className = `recording-state ${current}`;
    state.textContent = current[0].toUpperCase() + current.slice(1);
    start.disabled = isActiveState(current) || !selectedTopics.length;
    stop.disabled = current !== 'running';
    prefix.disabled = isActiveState(current);
    hours.disabled = isActiveState(current);
    minutes.disabled = isActiveState(current);
    seconds.disabled = isActiveState(current);
    syncTopic();

    if (isActiveState(current)) {
      if (elapsedStartedAt === null) {
        const storedElapsedStart = readStoredElapsedStart();
        setElapsedStart(storedElapsedStart === null ? Date.now() : storedElapsedStart);
      }
      if (!elapsedTimerId) {
        elapsedTimerId = setInterval(updateElapsedBadge, 250);
      }
      updateElapsedBadge();
      if (!pollId) {
        pollId = setInterval(checkStatus, 2000);
      }
    } else {
      clearElapsedTimer({ clearStorage: elapsedStartedAt !== null });
      if (pollId) {
        clearInterval(pollId);
        pollId = null;
      }
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

    let durationSeconds;

    try {
      durationSeconds = getDurationSeconds();
    } catch (failure) {
      showError(failure.message);
      return;
    }

    const body = {
      topics: selectedTopics,
      prefix: prefix.value.trim(),
    };

    if (durationSeconds !== null) {
      body.duration_seconds = durationSeconds;
    }

    start.disabled = true;
    prefix.disabled = true;
    hours.disabled = true;
    minutes.disabled = true;
    seconds.disabled = true;

    try {
      const data = await request('/api/record/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      setElapsedStart(Date.now());
      render(data);
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
