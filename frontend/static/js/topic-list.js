(() => {
  const list = document.getElementById('topic-list');
  const refresh = document.getElementById('topic-list-refresh');
  const input = document.getElementById('topic-monitor-input');

  function updateSelection() {
    const selected = input.value.trim();
    list.querySelectorAll('.topic-list-item').forEach((item) => {
      const active = item.dataset.topic === selected;
      item.classList.toggle('active', active);
      item.setAttribute('aria-pressed', active);
    });
  }

  function showStatus(message, error = false) {
    const status = document.createElement('p');
    status.className = `topic-list-status${error ? ' topic-list-error' : ''}`;
    status.textContent = message;
    list.replaceChildren(status);
  }

  function renderTopics(topics) {
    if (!topics.length) {
      showStatus('No topics found.');
      return;
    }

    const items = topics.map((topic) => {
      const item = document.createElement('button');
      item.className = 'topic-list-item';
      item.type = 'button';
      item.dataset.topic = topic;
      item.textContent = topic;
      item.addEventListener('click', () => {
        input.value = topic;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        updateSelection();
      });
      return item;
    });
    list.replaceChildren(...items);
    updateSelection();
  }

  async function loadTopics() {
    refresh.disabled = true;
    showStatus('Loading topics…');
    try {
      const response = await fetch('/api/topics', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      renderTopics(data.topics || []);
    } catch (error) {
      showStatus(error.message || 'Could not load topics.', true);
    } finally {
      refresh.disabled = false;
    }
  }

  refresh.addEventListener('click', loadTopics);
  input.addEventListener('input', updateSelection);
  loadTopics();
})();
