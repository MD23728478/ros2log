(() => {
  const input = document.getElementById('config-loader-input');
  const selectButton = document.getElementById('config-loader-select');
  const fileRow = document.getElementById('config-loader-file');
  const fileName = document.getElementById('config-loader-file-name');
  const removeButton = document.getElementById('config-loader-remove');
  const applyButton = document.getElementById('config-loader-apply');
  const status = document.getElementById('config-loader-status');
  const error = document.getElementById('config-loader-error');

  const storageKey = 'ros2log.recording.appliedConfig';

  let selectedFile = null;
  let appliedConfig = null;
  let busy = false;
  let locked = false;

  function showStatus(message = '', type = '') {
    status.textContent = message;
    status.className = 'config-loader-status';

    if (message && type) {
      status.classList.add(type);
    }
  }

  function showError(message = '') {
    error.textContent = message;
    error.classList.toggle('visible', Boolean(message));
  }

  function readStoredConfig() {
    try {
      const stored = window.sessionStorage.getItem(storageKey);
      if (!stored) return null;

      const parsed = JSON.parse(stored);

      if (
        !parsed ||
        typeof parsed.configPath !== 'string' ||
        typeof parsed.output !== 'string' ||
        typeof parsed.filename !== 'string'
      ) {
        return null;
      }

      return parsed;
    } catch {
      return null;
    }
  }

  function storeAppliedConfig() {
    try {
      if (appliedConfig) {
        window.sessionStorage.setItem(
          storageKey,
          JSON.stringify(appliedConfig)
        );
      } else {
        window.sessionStorage.removeItem(storageKey);
      }
    } catch {
      // The loader can still work if browser storage is unavailable.
    }
  }

  function currentFileName() {
    if (appliedConfig) return appliedConfig.filename;
    if (selectedFile) return selectedFile.name;
    return '';
  }

  function render() {
    const name = currentFileName();
    const hasFile = Boolean(name);
    const isApplied = Boolean(appliedConfig);

    fileRow.hidden = !hasFile;
    fileName.textContent = name;

    selectButton.disabled = busy || isApplied || locked;
    removeButton.disabled = busy || locked;

    applyButton.hidden = !selectedFile && !isApplied;

    applyButton.disabled =
      busy ||
      locked ||
      isApplied ||
      !selectedFile;

    applyButton.textContent = busy
      ? 'Applying…'
      : 'Apply Configuration';

    if (isApplied) {
      showStatus('Configuration ready', 'success');
    }
  }

  function emitApplied() {
    if (!appliedConfig) return;

    window.dispatchEvent(
      new CustomEvent('recording:config-applied', {
        detail: { ...appliedConfig },
      })
    );
  }

  function emitCleared() {
    window.dispatchEvent(
      new CustomEvent('recording:config-cleared')
    );
  }

  function clearConfiguration({ emit = true } = {}) {
    selectedFile = null;
    appliedConfig = null;
    input.value = '';

    storeAppliedConfig();
    showStatus();
    showError();
    render();

    if (emit) {
      emitCleared();
    }
  }

  async function applyConfiguration() {
    if (!selectedFile || busy || locked) return;

    busy = true;
    showError();
    showStatus('Validating configuration…', 'loading');
    render();

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const response = await fetch('/api/record/config', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.error || `Unable to apply configuration (HTTP ${response.status}).`
        );
      }

      if (
        typeof data.config_path !== 'string' ||
        typeof data.output !== 'string'
      ) {
        throw new Error('The server returned an incomplete configuration response.');
      }

      appliedConfig = {
        configPath: data.config_path,
        output: data.output,
        filename: selectedFile.name,
      };

      selectedFile = null;
      input.value = '';

      storeAppliedConfig();
      showError();
      showStatus('Configuration ready', 'success');
      emitApplied();
    } catch (failure) {
      showStatus();
      showError(
        failure.message || 'Unable to apply the recording configuration.'
      );
    } finally {
      busy = false;
      render();
    }
  }

  selectButton.addEventListener('click', () => {
    if (busy || locked || appliedConfig) return;
    input.click();
  });

  input.addEventListener('change', () => {
    selectedFile = input.files?.[0] || null;

    showStatus();
    showError();
    render();
  });

  removeButton.addEventListener('click', () => {
    if (busy || locked) return;

    if (appliedConfig) {
      clearConfiguration();
      return;
    }

    selectedFile = null;
    input.value = '';
    showStatus();
    showError();
    render();
  });

  applyButton.addEventListener('click', applyConfiguration);

  /*
   * These events will be emitted by topic-recording.js once we wire
   * configuration mode into the recording lifecycle.
   */
  window.addEventListener('recording:config-lock', () => {
    locked = true;
    render();
  });

  window.addEventListener('recording:config-unlock', () => {
    locked = false;
    render();
  });

  window.addEventListener('recording:config-consumed', () => {
    locked = false;
    clearConfiguration();
  });

  appliedConfig = readStoredConfig();
  render();

  /*
   * Wait until all dashboard scripts have loaded before announcing a
   * restored configuration. topic-recording.js is loaded after this file.
   */
  window.addEventListener('DOMContentLoaded', () => {
    if (appliedConfig) {
      emitApplied();
    }
  });
})();