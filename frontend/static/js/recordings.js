(() => {
  const rows = Array.from(document.querySelectorAll('.recording-row'));
  if (!rows.length) return;

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
      try {
        await request(`/api/recordings/${id}/rename`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: nextName.trim() }),
        });
        window.location.reload();
      } catch (error) {
        window.alert(error.message);
      }
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