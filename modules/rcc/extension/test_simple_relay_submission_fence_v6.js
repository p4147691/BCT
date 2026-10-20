const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(
  path.join(__dirname, 'content/simple_relay_executor.js'), 'utf8'
);

class MutationObserverStub {
  constructor(callback) { this.callback = callback; }
  observe() {}
  disconnect() {}
}

const context = {
  clearTimeout,
  setTimeout,
  MutationObserver: MutationObserverStub,
  document: { body: {} },
  conversationObserveRoot: () => ({}),
  resolveRoutedTurn: (record) => ({
    ok: record.relayId === 'route-by-identity',
    terminal: false,
    turnKey: record.relayId === 'route-by-identity' ? 'turn-new-user' : '',
  }),
};
vm.createContext(context);
vm.runInContext(
  `${source}\n;globalThis.__waitForExactUserSubmission = waitForExactUserSubmission;`,
  context
);

(async () => {
  const turnKey = await context.__waitForExactUserSubmission(
    { relayId: 'route-by-identity', beforeTurnKeys: ['turn-old-user'] }, 20
  );
  assert.equal(turnKey, 'turn-new-user');
  console.log('simple relay submission fence v6: PASS');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
