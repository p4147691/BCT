const fs = require('fs');
const vm = require('vm');
const { randomUUID } = require('crypto');
const assert = require('assert');

const background = fs.readFileSync('background.js', 'utf8');
const source = background + '\n;globalThis.__renameReceiptRetention = { getCompletedOperation, reserveRenameReceipt, saveCompletedOperation, handleNativeCommand };';
const store = {
  registrations: {}, settings: { token: 't', armed: false, budget: 0, instanceId: 'instance1234' },
  pending: {}, results: [], processed: [], operations: {},
};
let raceSnapshots = false;
const nativeMessages = [];
const port = { onMessage: { addListener() {} }, onDisconnect: { addListener() {} }, postMessage: (message) => nativeMessages.push(message) };
const context = {
  console, URL, setTimeout, clearTimeout, setInterval: () => 0,
  crypto: { randomUUID },
  RelayCore: { conversationKey: () => '', normalizeRole: (v) => String(v || '').toUpperCase() },
  RccLegacyCommandPolicy: require('./legacy/command_policy.js'),
  chrome: {
    storage: { local: {
      get: async (keys) => {
        const snapshot = JSON.parse(JSON.stringify(store));
        if (raceSnapshots && Array.isArray(keys) && keys.includes('renameReceiptsV1')) {
          await new Promise((resolve) => setTimeout(resolve, 0));
        }
        return snapshot;
      },
      set: async (patch) => Object.assign(store, patch),
    }, session: { get: async () => ({}), set: async () => {} } },
    tabs: { query: async () => [], get: async () => { throw Error('not used'); } },
    windows: { get: async () => ({}) }, scripting: { executeScript: async () => [] },
    runtime: { id: 'x', onMessage: { addListener() {} }, connectNative: () => port, onStartup: { addListener() {} }, onInstalled: { addListener() {} } },
  },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: 'background.js' });

(async () => {
  const { getCompletedOperation, reserveRenameReceipt, saveCompletedOperation, handleNativeCommand } = context.__renameReceiptRetention;
  const result = { ok: true, operationId: 'rename-1', savedTitle: 'Title', tabId: 7, conversationKey: 'conv-1' };
  await reserveRenameReceipt('rename-1', '["conv-1",7,"session-1","Title"]');
  await assert.rejects(
    () => getCompletedOperation('rename-1', 'rename-conversation', '["conv-1",7,"session-1","Title"]'),
    /RENAME_RECEIPT_PREPARED_OUTCOME_UNKNOWN/,
  );
  await handleNativeCommand({ type: 'host:command', requestId: 'inspect-prepared', command: 'rename-receipt', text: 'rename-1', tabId: 7, conversationKey: 'conv-1' });
  const preparedInspection = nativeMessages.find((message) => message.requestId === 'inspect-prepared');
  assert.strictEqual(preparedInspection.receipt, null, 'prepared reservation must not be reconciliation evidence');
  assert.strictEqual(preparedInspection.receiptState, 'PREPARED');
  await saveCompletedOperation('rename-1', 'rename-conversation', '["conv-1",7,"session-1","Title"]', result);
  // Keep ordering deterministic without waiting in the test: the generic
  // cache's eviction decision is timestamp-based.
  store.operations['rename-1'].at = 0;
  for (let i = 0; i < 101; i += 1) {
    await saveCompletedOperation(`other-${i}`, 'send', `fp-${i}`, { ok: true, operationId: `other-${i}` });
  }
  assert.strictEqual(store.operations['rename-1'], undefined, 'generic cache must be bounded');
  assert.deepStrictEqual(store.renameReceiptsV1['rename-1'].result, result);
  const duplicate = await getCompletedOperation('rename-1', 'rename-conversation', '["conv-1",7,"session-1","Title"]');
  assert.deepStrictEqual(duplicate, result, 'rename duplicate must be fenced by retained receipt');
  await assert.rejects(
    () => getCompletedOperation('rename-1', 'rename-conversation', '["conv-1",7,"session-1","Different"]'),
    /OPERATION_ID_REUSE_MISMATCH/,
  );
  const firstFingerprint = '["conv-2",8,"session-2","Second"]';
  const secondFingerprint = '["conv-3",9,"session-3","Third"]';
  raceSnapshots = true;
  await Promise.all([
    reserveRenameReceipt('rename-2', firstFingerprint),
    reserveRenameReceipt('rename-3', secondFingerprint),
  ]);
  assert(store.renameReceiptsV1['rename-2'] && store.renameReceiptsV1['rename-3'],
    'concurrent reservations must retain both operation IDs');
  await Promise.all([
    saveCompletedOperation('rename-2', 'rename-conversation', firstFingerprint,
      { ok: true, operationId: 'rename-2', savedTitle: 'Second', tabId: 8, conversationKey: 'conv-2' }),
    saveCompletedOperation('rename-3', 'rename-conversation', secondFingerprint,
      { ok: true, operationId: 'rename-3', savedTitle: 'Third', tabId: 9, conversationKey: 'conv-3' }),
  ]);
  raceSnapshots = false;
  assert.strictEqual(store.renameReceiptsV1['rename-2'].terminal, true);
  assert.strictEqual(store.renameReceiptsV1['rename-3'].terminal, true);
  console.log('rename receipt retention tests: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
