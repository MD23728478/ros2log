(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('topic-monitor-form');
  const input = $('topic-monitor-input');
  const btn = $('topic-monitor-btn');
  const autoBtn = $('topic-monitor-auto');
  const result = $('topic-monitor-result');
  const err = $('topic-monitor-error');
  const selectedCount = $('topic-monitor-selected-count');

  let auto = false;
  let intervalId = null;
  let selectedTopics = [];
  let currentTopic = '';

  function setError(message) {
    err.textContent = message || '';
    err.style.display = message ? 'block' : 'none';
  }

  function setSelectedCount() {
    if (!selectedTopics.length) {
      selectedCount.textContent = 'Select topics in the list.';
      return;
    }
    if (selectedTopics.length === 1) {
      selectedCount.textContent = '1 topic selected.';
      return;
    }
    selectedCount.textContent = `${selectedTopics.length} topics selected.`;
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
    selectedTopics = Array.isArray(topics) ? topics : [];
    setSelectedCount();
    rebuildTopicOptions();
    if (!currentTopic && auto) {
      stopAuto();
    }
    syncControls();
  }

  function syncControls() {
    const hasTopic = Boolean(currentTopic);
    input.disabled = !selectedTopics.length;
    btn.disabled = !hasTopic;
    autoBtn.disabled = !hasTopic;
  }

  function updateFields(data) {
    $('tm-source').textContent = data.source || '—';
    $('tm-topic').textContent = data.topic || '—';
    $('tm-frequency').textContent = data.frequency_hz != null ? data.frequency_hz.toFixed(2) : '—';
    $('tm-bandwidth').textContent = data.bandwidth_bytes_per_second != null ? Math.round(data.bandwidth_bytes_per_second) : '—';
  }

  async function measure() {
    setError('');
    const topic = currentTopic.trim();
    if (!topic) {
      setError('Select a topic from the dropdown.');
      return;
    }
    setLoading(true);
    try {
      const url = `/api/topic-monitor?topic=${encodeURIComponent(topic)}`;
      const res = await fetch(url, { cache: 'no-store' });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error || `HTTP ${res.status}`);
      } else {
        updateFields(json);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  function setLoading(isLoading) {
    if (isLoading) {
      btn.disabled = true;
      btn.classList.add('loading');
      btn.innerHTML = '<span class="topic-spinner" aria-hidden="true"></span>Measuring';
      result.setAttribute('aria-busy', 'true');
    } else {
      syncControls();
      btn.classList.remove('loading');
      btn.textContent = 'Measure';
      result.removeAttribute('aria-busy');
    }
  }

  function startAuto() {
    if (intervalId) return;
    if (!currentTopic) return;
    intervalId = setInterval(measure, 3000);
    auto = true;
    autoBtn.textContent = 'Stop';
  }

  function stopAuto() {
    if (!intervalId) return;
    clearInterval(intervalId);
    intervalId = null;
    auto = false;
    autoBtn.textContent = 'Auto';
  }

  btn.addEventListener('click', measure);
  input.addEventListener('change', () => {
    currentTopic = input.value;
    syncControls();
  });
  autoBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (auto) stopAuto(); else startAuto();
  });

  window.addEventListener('topics:selected', (event) => {
    syncTopicPicker(event.detail);
  });

  // Initialize: hide error
  setError('');
  syncTopicPicker([]);
})();
