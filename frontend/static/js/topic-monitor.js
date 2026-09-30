(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('topic-monitor-form');
  const input = $('topic-monitor-input');
  const topicHelp = $('topic-monitor-topic-help');
  const windowInput = $('topic-monitor-window');
  const btn = $('topic-monitor-btn');
  const btnLabel = $('topic-monitor-btn-label');
  const autoBtn = $('topic-monitor-auto');
  const result = $('topic-monitor-result');
  const err = $('topic-monitor-error');

  let auto = false;
  let refreshTimer = null;
  let inFlight = false;
  let selectionRevision = 0;
  let selectedTopics = [];
  let currentTopic = '';

  function setError(message) {
    err.textContent = message || '';
    err.style.display = message ? 'block' : 'none';
  }

  function rebuildTopicOptions() {
    const previous = input.value;
    input.replaceChildren();

    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = selectedTopics.length
      ? 'Select a topic from the selected list'
      : 'Select topics in the list first';
    input.appendChild(placeholder);

    selectedTopics.forEach((topic) => {
      const option = document.createElement('option');
      option.value = topic;
      option.textContent = topic;
      input.appendChild(option);
    });

    const nextValue = selectedTopics.includes(previous) ? previous : selectedTopics[0] || '';
    input.value = nextValue;
    currentTopic = nextValue;
  }

  function syncTopicPicker(topics = []) {
    const previousTopic = currentTopic;
    selectedTopics = Array.isArray(topics) ? topics : [];
    topicHelp.hidden = selectedTopics.length > 0;
    rebuildTopicOptions();
    // Searching the list or checking another topic must not reset this reading.
    if (currentTopic !== previousTopic) {
      settingsChanged();
    }
    syncControls();
  }

  function syncControls() {
    const hasTopic = Boolean(currentTopic);
    input.disabled = !selectedTopics.length;
    windowInput.disabled = !hasTopic;
    btn.disabled = !hasTopic || inFlight || auto;
    autoBtn.disabled = !hasTopic || (inFlight && !auto);
    autoBtn.textContent = auto ? 'Stop auto' : 'Auto';
    autoBtn.setAttribute('aria-pressed', String(auto));
  }

  function clearFields() {
    ['tm-frequency', 'tm-bandwidth'].forEach((id) => {
      $(id).textContent = '\u2014';
    });
  }

  function settingsChanged() {
    selectionRevision += 1;
    stopAuto();
    clearFields();
    setError('');
    syncControls();
  }

  function updateFields(data) {
    $('tm-frequency').textContent = data.frequency_hz != null ? data.frequency_hz.toFixed(2) : '—';
    $('tm-bandwidth').textContent = data.bandwidth_bytes_per_second != null ? Math.round(data.bandwidth_bytes_per_second) : '—';
  }

  async function measure() {
    if (inFlight) return;
    if (!currentTopic || !form.reportValidity()) {
      stopAuto();
      return;
    }
    clearTimeout(refreshTimer);
    refreshTimer = null;
    setError('');
    const topic = currentTopic;
    const sampleWindow = windowInput.valueAsNumber;
    const revision = selectionRevision;
    inFlight = true;
    setLoading(true);
    try {
      const query = new URLSearchParams({ topic, window: String(sampleWindow) });
      const url = `/api/topic-monitor?${query}`;
      const res = await fetch(url, { cache: 'no-store' });
      const json = await res.json();
      if (revision !== selectionRevision) return;
      if (!res.ok) {
        throw new Error(json?.error || `Unable to measure this topic (HTTP ${res.status}).`);
      }
      if (!json || json.topic !== topic || json.window !== sampleWindow ||
          !Number.isFinite(json.frequency_hz) || json.frequency_hz < 0 ||
          !Number.isFinite(json.bandwidth_bytes_per_second) || json.bandwidth_bytes_per_second < 0) {
        throw new Error('The server returned an incomplete reading. Please try again.');
      }
      updateFields(json);
    } catch (e) {
      if (revision === selectionRevision) {
        clearFields();
        stopAuto();
        setError(e.message || 'Unable to reach the monitor. Please try again.');
      }
    } finally {
      inFlight = false;
      setLoading(false);
      if (revision === selectionRevision && auto) {
        // ROS measurements take longer than three seconds. Never overlap requests.
        refreshTimer = setTimeout(measure, 3000);
      }
    }
  }

  function setLoading(isLoading) {
    btn.classList.toggle('loading', isLoading);
    btnLabel.textContent = isLoading ? 'Measuring\u2026' : 'Measure';
    result.setAttribute('aria-busy', String(isLoading));
    syncControls();
  }

  function startAuto() {
    if (auto || inFlight || !currentTopic || !form.reportValidity()) return;
    auto = true;
    syncControls();
    measure();
  }

  function stopAuto() {
    clearTimeout(refreshTimer);
    refreshTimer = null;
    auto = false;
    syncControls();
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (inFlight) return;
    stopAuto();
    measure();
  });
  input.addEventListener('change', () => {
    currentTopic = input.value;
    settingsChanged();
  });
  windowInput.addEventListener('input', settingsChanged);
  autoBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (auto) stopAuto(); else startAuto();
  });

  window.addEventListener('topics:selected', (event) => {
    syncTopicPicker(event.detail);
  });
  window.addEventListener('pagehide', stopAuto);
  window.addEventListener('DOMContentLoaded', () => {
    if (window.bootstrap?.Tooltip) {
      new window.bootstrap.Tooltip(topicHelp);
    }
  });

  // Initialize: hide error
  setError('');
  syncTopicPicker([]);
})();
