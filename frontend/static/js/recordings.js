(() => {
  const rows = Array.from(document.querySelectorAll('.recording-row'));
  const dialog = document.getElementById('recording-metadata-dialog');
  const metadataName = document.getElementById('recording-metadata-name');
  const metadataStatus = document.getElementById('recording-metadata-status');
  const metadataContent = document.getElementById('recording-metadata-content');

  function closeMetadata() {
    if (dialog.open) dialog.close();
  }

  dialog?.querySelector('.recording-metadata-close').addEventListener('click', closeMetadata);

  function closeMenus(exceptRow = null) {
    rows.forEach((row) => {
      if (row === exceptRow) return;
      const button = row.querySelector('.recording-manage-button');
      const menu = row.querySelector('.recording-manage-menu');
      button.setAttribute('aria-expanded', 'false');
      menu.hidden = true;
    });
  }

  async function request(url, options) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function appendText(parent, tagName, text, className = '') {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text == null || text === '' ? '—' : String(text);
    parent.append(element);
    return element;
  }

  function appendTable(parent, title, headings, values, emptyMessage) {
    const section = document.createElement('section');
    section.className = 'recording-metadata-section';
    appendText(section, 'h3', title);
    const wrap = document.createElement('div');
    wrap.className = 'recording-metadata-table-wrap';
    const table = document.createElement('table');
    table.className = 'recording-metadata-table';
    const head = table.createTHead().insertRow();
    headings.forEach((heading) => appendText(head, 'th', heading));
    const body = table.createTBody();

    if (!values.length) {
      const cell = appendText(body.insertRow(), 'td', emptyMessage);
      cell.colSpan = headings.length;
      cell.className = 'recordings-table-empty';
    } else {
      values.forEach((valuesRow) => {
        const row = body.insertRow();
        valuesRow.forEach((value) => appendText(row, 'td', value));
      });
    }

    wrap.append(table);
    section.append(wrap);
    parent.append(section);
  }

  function renderMetadata(data) {
    metadataContent.replaceChildren();
    const summary = data.summary || {};
    const duration = summary.duration && summary.duration.seconds != null
      ? `${Number(summary.duration.seconds).toFixed(2)} s`
      : '—';
    const compression = summary.compression
      ? [summary.compression.mode, summary.compression.format].filter(Boolean).join(' / ') || 'None'
      : '—';
    const summarySection = document.createElement('section');
    summarySection.className = 'recording-metadata-section';
    appendText(summarySection, 'h3', 'Summary');
    const summaryList = document.createElement('dl');
    summaryList.className = 'recording-metadata-summary';
    [
      ['Started', summary.started_at],
      ['Duration', duration],
      ['Messages', summary.message_count],
      ['Topics', summary.topic_count],
      ['ROS distribution', summary.ros_distro],
      ['Storage', summary.storage_identifier],
      ['Compression', compression],
    ].forEach(([label, value]) => {
      const item = document.createElement('div');
      item.className = 'recording-metadata-stat';
      appendText(item, 'dt', label);
      appendText(item, 'dd', value);
      summaryList.append(item);
    });
    summarySection.append(summaryList);
    metadataContent.append(summarySection);

    const topics = Array.isArray(data.topics) ? data.topics : [];
    appendTable(
      metadataContent,
      'Topics',
      ['Topic', 'Message type', 'Messages'],
      topics.map((topic) => [topic.name, topic.type, topic.message_count]),
      'No topic information is available.'
    );

    const files = Array.isArray(data.files) ? data.files : [];
    appendTable(
      metadataContent,
      'Bag files',
      ['File', 'Started', 'Duration', 'Messages'],
      files.map((file) => [
        file.path,
        file.started_at,
        file.duration && file.duration.seconds != null
          ? `${Number(file.duration.seconds).toFixed(2)} s`
          : null,
        file.message_count,
      ]),
      'No bag file details are available.'
    );

    const advanced = document.createElement('details');
    advanced.className = 'recording-metadata-advanced';
    appendText(advanced, 'summary', 'Advanced metadata');
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(data.advanced || {}, null, 2);
    advanced.append(pre);
    metadataContent.append(advanced);
    metadataStatus.textContent = '';
    metadataStatus.hidden = true;
    metadataContent.hidden = false;
  }

  async function openMetadata(id, name) {
    metadataName.textContent = name;
    metadataContent.hidden = true;
    metadataContent.replaceChildren();
    metadataStatus.textContent = 'Loading metadata…';
    metadataStatus.hidden = false;
    metadataStatus.classList.remove('error');
    dialog.showModal();

    try {
      const data = await request(`/api/recordings/${id}/metadata`);
      renderMetadata(data);
    } catch (error) {
      metadataStatus.textContent = error.message;
      metadataStatus.classList.add('error');
    }
  }

  rows.forEach((row) => {
    const button = row.querySelector('.recording-manage-button');
    const menu = row.querySelector('.recording-manage-menu');
    const name = row.dataset.recordingName;
    const id = row.dataset.recordingId;

    button.addEventListener('click', (event) => {
      event.stopPropagation();
      const willOpen = menu.hidden;
      closeMenus(row);
      menu.hidden = !willOpen;
      button.setAttribute('aria-expanded', String(willOpen));
    });

    menu.querySelector('[data-action="rename"]').addEventListener('click', async () => {
      const nextName = window.prompt('Rename recording', name);
      closeMenus();
      if (!nextName || !nextName.trim() || nextName.trim() === name) return;

      const trimmedName = nextName.trim();
      const nameElement = row.querySelector('.recording-name');
      const button = row.querySelector('.recording-manage-button');

      try {
        const result = await request(`/api/recordings/${id}/rename`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: trimmedName }),
        });

        row.dataset.recordingName = result.name;
        if (nameElement) {
          nameElement.textContent = result.name;
        }
        if (button) {
          button.setAttribute('aria-label', `Manage ${result.name}`);
        }

        window.location.reload();
      } catch (error) {
        window.alert(error.message);
      }
    });

    menu.querySelector('[data-action="metadata"]').addEventListener('click', () => {
      closeMenus();
      openMetadata(id, name);
    });

    menu.querySelector('[data-action="delete"]').addEventListener('click', async () => {
      closeMenus();
      if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;
      try {
        await request(`/api/recordings/${id}/delete`, { method: 'POST' });
        row.remove();
      } catch (error) {
        window.alert(error.message);
      }
    });
  });

  document.addEventListener('click', () => closeMenus());
})();