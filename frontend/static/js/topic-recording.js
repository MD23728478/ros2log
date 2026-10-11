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
  const configModeNotice = document.getElementById('recording-config-mode');

  const elapsedStorageKey = 'ros2log.recording.elapsedStartedAt';
  const configRecordingStorageKey = 'ros2log.recording.configInUse';

  let pollId = null;
  let selectedTopics = [];
  let elapsedStartedAt = null;
  let elapsedTimerId = null;

  let activeConfig = null;
  let configRecordingActive = readStoredConfigRecordingState();
  let configLoaderLocked = false;

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

  function readStoredConfigRecordingState() {
    try {
      return window.sessionStorage.getItem(configRecordingStorageKey) === 'true';
    } catch {
      return false;
    }
  }

  function storeConfigRecordingState(value) {
    configRecordingActive = value;

    try {
      if (value) {
        window.sessionStorage.setItem(configRecordingStorageKey, 'true');
      } else {
        window.sessionStorage.removeItem(configRecordingStorageKey);
      }
    } catch {
      // The live recording state can still work without browser storage.
    }
  }

  function setConfigLoaderLocked(value) {
    if (configLoaderLocked === value) return;

    configLoaderLocked = value;

    window.dispatchEvent(
      new CustomEvent(
        value
          ? 'recording:config-lock'
          : 'recording:config-unlock'
      )
    );
  }

  function selectedTopicLabels() {
    if (!selectedTopics.length) {
      return 'Select one or more topics from the list.';
    }

    if (selectedTopics.length === 1) {
      return selectedTopics[0];
    }

    return `${selectedTopics.length} topics selected`;
  }

  function syncTopic() {
    const currentState = state.dataset.state;

    if (
      activeConfig &&
      (configRecordingActive || !isActiveState(currentState))
    ) {
      topic.textContent = 'Managed by configuration.';
      return;
    }

    topic.textContent = isActiveState(currentState)
      ? (
          selectedTopics.length
            ? selectedTopics.join(', ')
            : 'Recording in progress.'
        )
      : selectedTopicLabels();
  }

  function syncStartButton() {
    const currentState = state.dataset.state;
    const hasRecordingInput =
      Boolean(activeConfig) || selectedTopics.length > 0;

    start.disabled =
      isActiveState(currentState) ||
      !hasRecordingInput;
  }

  function syncManualControls() {
    const locked =
      isActiveState(state.dataset.state) ||
      Boolean(activeConfig);

    prefix.disabled = locked;
    hours.disabled = locked;
    minutes.disabled = locked;
    seconds.disabled = locked;
  }

  function syncConfigModeNotice() {
  configModeNotice.hidden = !activeConfig;
}

  function syncControls() {
    syncTopic();
    syncStartButton();
    syncManualControls();
    syncConfigModeNotice();
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

    const hoursValue = String(
      Math.floor(safeSeconds / 3600)
    ).padStart(2, '0');

    const minutesValue = String(
      Math.floor((safeSeconds % 3600) / 60)
    ).padStart(2, '0');

    const secondsValue = String(
      safeSeconds % 60
    ).padStart(2, '0');

    return `${hoursValue}:${minutesValue}:${secondsValue}`;
  }

  function updateElapsedBadge() {
    if (
      state.dataset.state !== 'running' ||
      elapsedStartedAt === null
    ) {
      elapsedBadge.textContent = '00:00';
      return;
    }

    const elapsedSeconds =
      (Date.now() - elapsedStartedAt) / 1000;

    elapsedBadge.textContent =
      formatElapsedSeconds(elapsedSeconds);
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
    state.textContent =
      current[0].toUpperCase() + current.slice(1);

    stop.disabled = current !== 'running';

    syncControls();

    if (isActiveState(current)) {
      setConfigLoaderLocked(true);

      if (elapsedStartedAt === null) {
        const storedElapsedStart = readStoredElapsedStart();

        setElapsedStart(
          storedElapsedStart === null
            ? Date.now()
            : storedElapsedStart
        );
      }

      if (!elapsedTimerId) {
        elapsedTimerId =
          setInterval(updateElapsedBadge, 250);
      }

      updateElapsedBadge();

      if (!pollId) {
        pollId = setInterval(checkStatus, 2000);
      }
    } else {
      setConfigLoaderLocked(false);

      clearElapsedTimer({
        clearStorage: elapsedStartedAt !== null,
      });

      if (pollId) {
        clearInterval(pollId);
        pollId = null;
      }
    }
  }

  function consumeConfiguration() {
    storeConfigRecordingState(false);

    window.dispatchEvent(
      new CustomEvent('recording:config-consumed')
    );
  }

  function render(data) {
    const nextState = data.state || 'idle';

    setState(nextState);

    if (data.output) {
      output.textContent =
        data.display_output || data.output;
    }

    /*
     * Only clear an applied configuration if this browser actually
     * started a recording using it.
     *
     * This prevents an old "finished" runner status from clearing a
     * configuration that has merely been uploaded and is waiting to run.
     */
    if (
      nextState.toLowerCase() === 'finished' &&
      configRecordingActive
    ) {
      consumeConfiguration();
    }
  }

  function updateSelection(topics = []) {
    selectedTopics =
      Array.isArray(topics) ? topics : [];

    syncControls();
  }

  function applyConfiguration(config) {
    if (
      !config ||
      typeof config.configPath !== 'string' ||
      !config.configPath
    ) {
      return;
    }

    activeConfig = config;

    prefix.value = '';
    hours.value = '';
    minutes.value = '';
    seconds.value = '';

    showError();
    syncControls();
  }

  function clearConfiguration() {
    activeConfig = null;
    storeConfigRecordingState(false);
    syncControls();
  }

  async function request(url, options) {
    const response = await fetch(
      url,
      {
        cache: 'no-store',
        ...options,
      }
    );

    const data = await response.json();

    if (!response.ok) {
      const failure = new Error(
        data.error || `HTTP ${response.status}`
      );

      failure.status = response.status;
      throw failure;
    }

    return data;
  }

  async function checkStatus(initial = false) {
    try {
      render(
        await request('/api/record/status')
      );
    } catch (failure) {
      if (initial && failure.status === 404) {
        /*
         * If the browser remembered that a config recording was active,
         * but the backend no longer has a background command, do not
         * leave the Config Loader permanently locked.
         */
        storeConfigRecordingState(false);
        setConfigLoaderLocked(false);
        return;
      }

      showError(failure.message);
      setState('error');
    }
  }

  async function startRecording() {
    showError();

    const usingConfig = Boolean(activeConfig);
    let body;

    if (usingConfig) {
      body = {
        config_path: activeConfig.configPath,
      };
    } else {
      let durationSeconds;

      try {
        durationSeconds = getDurationSeconds();
      } catch (failure) {
        showError(failure.message);
        return;
      }

      body = {
        topics: selectedTopics,
        prefix: prefix.value.trim(),
      };

      if (durationSeconds !== null) {
        body.duration_seconds = durationSeconds;
      }
    }

    /*
     * Lock both setup workflows while the start request is in flight.
     * This prevents changing/removing the configuration between clicking
     * Start and receiving confirmation from the backend.
     */
    start.disabled = true;
    prefix.disabled = true;
    hours.disabled = true;
    minutes.disabled = true;
    seconds.disabled = true;
    setConfigLoaderLocked(true);

    try {
      const data = await request(
        '/api/record/start',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(body),
        }
      );

      if (usingConfig) {
        storeConfigRecordingState(true);
      }

      setElapsedStart(Date.now());
      render(data);
    } catch (failure) {
      if (usingConfig) {
        storeConfigRecordingState(false);
      }

      setConfigLoaderLocked(false);
      showError(failure.message);
      setState('error');
    }
  }

  async function stopRecording() {
    showError();
    stop.disabled = true;

    try {
      render(
        await request(
          '/api/record/stop',
          {
            method: 'POST',
          }
        )
      );
    } catch (failure) {
      showError(failure.message);
      setState('error');
    }
  }

  window.addEventListener(
    'topics:selected',
    (event) => {
      updateSelection(event.detail);
    }
  );

  window.addEventListener(
    'recording:config-applied',
    (event) => {
      applyConfiguration(event.detail);
    }
  );

  window.addEventListener(
    'recording:config-cleared',
    () => {
      clearConfiguration();
    }
  );

  start.addEventListener(
    'click',
    startRecording
  );

  stop.addEventListener(
    'click',
    stopRecording
  );

  setState('idle');
  syncControls();
  checkStatus(true);
})();