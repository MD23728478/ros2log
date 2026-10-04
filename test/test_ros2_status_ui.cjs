const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { setImmediate } = require('node:timers/promises');
const { test } = require('node:test');
const { runInNewContext } = require('node:vm');
const { join } = require('node:path');

const source = readFileSync(join(__dirname, '../frontend/static/js/ros2-status.js'), 'utf8');

function dashboard() {
  const status = { dataset: { state: 'checking' }, textContent: 'CHECKING' };
  const requests = [];
  const timers = [];
  runInNewContext(source, {
    document: {
      getElementById(id) {
        assert.equal(id, 'ros2-status');
        return status;
      },
    },
    AbortSignal,
    fetch(url, options) {
      assert.equal(url, '/api/ros2/status');
      assert.equal(options.cache, 'no-store');
      assert.ok(options.signal instanceof AbortSignal);
      return new Promise((resolve, reject) => requests.push({ resolve, reject }));
    },
    setTimeout(callback, delay) {
      assert.equal(delay, 5000);
      timers.push(callback);
    },
  });
  return { status, requests, timers };
}

function reply(request, state) {
  request.resolve({ ok: true, json: async () => ({ status: state }) });
}

test('polling waits for completion and keeps the last status while checking', async () => {
  const { status, requests, timers } = dashboard();
  assert.equal(status.textContent, 'CHECKING');
  assert.equal(requests.length, 1);
  assert.equal(timers.length, 0);
  reply(requests[0], 'available');
  await setImmediate();
  assert.equal(status.textContent, 'AVAILABLE');
  assert.equal(timers.length, 1);
  timers.shift()();
  await setImmediate();
  assert.equal(requests.length, 2);
  assert.equal(timers.length, 0);
  assert.equal(status.textContent, 'AVAILABLE');
  reply(requests[1], 'available');
  await setImmediate();
  assert.equal(timers.length, 1);
});

const failures = {
  ros2: request => reply(request, 'ros2_unavailable'),
  runner: request => reply(request, 'runner_unavailable'),
  http: request => request.resolve({ ok: false, json: async () => ({ status: 'available' }) }),
  network: request => request.reject(new Error('Connection lost')),
  timeout: request => request.reject(new DOMException('Timed out', 'TimeoutError')),
  json: request => request.resolve({ ok: true, json: async () => { throw new SyntaxError(); } }),
  invalid: request => reply(request, '__proto__'),
};

for (const [name, fail] of Object.entries(failures)) {
  test(`recovers from ${name} failure on the next check`, async () => {
    const { status, requests, timers } = dashboard();
    fail(requests[0]);
    await setImmediate();
    assert.equal(status.textContent, 'NOT AVAILABLE');
    timers.shift()();
    reply(requests[1], 'available');
    await setImmediate();
    assert.equal(status.dataset.state, 'available');
    assert.equal(status.textContent, 'AVAILABLE');
    assert.equal(timers.length, 1);
  });
}
