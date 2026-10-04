(() => {
  const status = document.getElementById('ros2-status');
  const labels = {
    available: 'AVAILABLE',
    ros2_unavailable: 'NOT AVAILABLE',
    runner_unavailable: 'NOT AVAILABLE',
  };

  function render(state) {
    if (status.dataset.state === state) return;
    status.dataset.state = state;
    status.textContent = labels[state] || 'NOT AVAILABLE';
  }

  async function checkStatus() {
    try {
      const response = await fetch('/api/ros2/status', {
        cache: 'no-store',
        signal: AbortSignal.timeout(10000),
      });
      const data = await response.json();
      if (!response.ok || !Object.hasOwn(labels, data?.status)) {
        throw new Error('Invalid ROS 2 status response');
      }
      render(data.status);
    } catch {
      render('unknown');
    } finally {
      setTimeout(checkStatus, 5000);
    }
  }

  checkStatus();
})();
