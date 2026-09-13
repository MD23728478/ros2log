(() => {
  const $ = (id) => document.getElementById(id);
  const form = $('topic-monitor-form');
  const input = $('topic-monitor-input');
  const btn = $('topic-monitor-btn');
  const autoBtn = $('topic-monitor-auto');
  const result = $('topic-monitor-result');
  const err = $('topic-monitor-error');

  let auto = false;
  let intervalId = null;

  function setError(message) {
    err.textContent = message || '';
    err.style.display = message ? 'block' : 'none';
  }

  function updateFields(data) {
    $('tm-source').textContent = data.source || '—';
    $('tm-topic').textContent = data.topic || '—';
    $('tm-frequency').textContent = data.frequency_hz != null ? data.frequency_hz.toFixed(2) : '—';
    $('tm-bandwidth').textContent = data.bandwidth_bytes_per_second != null ? Math.round(data.bandwidth_bytes_per_second) : '—';
  }

  async function measure() {
    setError('');
    const topic = input.value.trim();
    if (!topic) {
      setError('Enter a topic name. Example: /example/topic');
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
      input.disabled = true;
      btn.disabled = true;
      btn.classList.add('loading');
      btn.innerHTML = '<span class="topic-spinner" aria-hidden="true"></span>Measuring';
      result.setAttribute('aria-busy', 'true');
    } else {
      input.disabled = false;
      btn.disabled = false;
      btn.classList.remove('loading');
      btn.textContent = 'Measure';
      result.removeAttribute('aria-busy');
    }
  }

  function startAuto() {
    if (intervalId) return;
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
  autoBtn.addEventListener('click', (e) => {
    e.preventDefault();
    if (auto) stopAuto(); else startAuto();
  });

  // Initialize: hide error
  setError('');
})();
