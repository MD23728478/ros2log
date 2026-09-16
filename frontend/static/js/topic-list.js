(() => {
  const list = document.getElementById('topic-list');
  const refresh = document.getElementById('topic-list-refresh');
  const search = document.getElementById('topic-list-search');
  const selectionEventName = 'topics:selected';
  const selectedTopics = new Set();
  let allTopics = [];
  let query = '';

  function emitSelection() {
    const topics = Array.from(selectedTopics);
    window.dispatchEvent(new CustomEvent(selectionEventName, { detail: topics }));
  }

  function normalize(value) {
    return value.trim().toLowerCase();
  }

  function filteredTopics() {
    const needle = normalize(query);
    if (!needle) return allTopics;
    return allTopics.filter((topic) => topic.toLowerCase().includes(needle));
  }

  function showStatus(message, error = false) {
    const status = document.createElement('p');
    status.className = `topic-list-status${error ? ' topic-list-error' : ''}`;
    status.textContent = message;
    list.replaceChildren(status);
  }

  function renderTopics(topics) {
    if (!topics.length) {
      showStatus(query ? `No topics match “${query.trim()}”.` : 'No topics found.');
      emitSelection();
      return;
    }

    const items = topics.map((topic) => {
      const item = document.createElement('label');
      item.className = 'topic-list-item form-check';

      const checkbox = document.createElement('input');
      checkbox.className = 'form-check-input';
      checkbox.type = 'checkbox';
      checkbox.value = topic;
      checkbox.checked = selectedTopics.has(topic);
      checkbox.addEventListener('change', () => {
        if (checkbox.checked) {
          selectedTopics.add(topic);
        } else {
          selectedTopics.delete(topic);
        }
        item.classList.toggle('active', checkbox.checked);
        emitSelection();
      });

      const text = document.createElement('span');
      text.className = 'form-check-label';
      text.textContent = topic;

      item.append(checkbox, text);
      item.classList.toggle('active', checkbox.checked);
      return item;
    });
    list.replaceChildren(...items);
    emitSelection();
  }

  function render() {
    renderTopics(filteredTopics());
  }

  function syncSelectionToAvailableTopics() {
    const availableTopics = new Set(allTopics);
    Array.from(selectedTopics).forEach((topic) => {
      if (!availableTopics.has(topic)) {
        selectedTopics.delete(topic);
      }
    });
  }

  async function loadTopics() {
    refresh.disabled = true;
    showStatus('Loading topics…');
    try {
      const response = await fetch('/api/topics', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      allTopics = Array.isArray(data.topics) ? data.topics : [];
      syncSelectionToAvailableTopics();
      render();
    } catch (error) {
      showStatus(error.message || 'Could not load topics.', true);
    } finally {
      refresh.disabled = false;
    }
  }

  refresh.addEventListener('click', loadTopics);
  search.addEventListener('input', () => {
    query = search.value;
    render();
  });
  loadTopics();
})();
