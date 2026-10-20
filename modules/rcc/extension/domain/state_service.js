const RELAY_RESULT_RECEIPTS_KEY = 'relayResultReceiptsV1';
// Generic completed operations are an idempotency cache and are intentionally
// bounded.  Rename recovery is different: an UNKNOWN rename must be
// inspectable long after unrelated operations have displaced that cache.
// These compact, terminal records are therefore never pruned automatically.
// They may only be removed by a future explicit, authenticated retention
// protocol after BCT has durably established a terminal outcome.
const RENAME_RECEIPTS_KEY = 'renameReceiptsV1';
const BINDING_SUBMIT_LEASES_KEY = 'bindingSubmitLeasesV1';
// V0 is deliberately independent from the legacy role/lease registry.  It is
// only an address book for one Manager and one Worker plus compact delivery
// receipts; it never creates nodes, queues work, or promotes replies.
const SIMPLE_RELAY_V0_BINDING_KEY = 'simpleRelayV0Binding';
const SIMPLE_RELAY_V0_RECEIPTS_KEY = 'simpleRelayV0Receipts';

let bindingLeaseMutationChain = Promise.resolve();

async function loadState() {

  const data = await stateRepository.getLocal(['registrations', 'settings', 'pending', 'results', 'processed', 'operations', RELAY_RESULT_RECEIPTS_KEY, RENAME_RECEIPTS_KEY, BINDING_SUBMIT_LEASES_KEY, SIMPLE_RELAY_V0_BINDING_KEY]);

  const settings = data.settings || {};

  let settingsDirty = false;

  if (!settings.token) {

    settings.token = crypto.randomUUID();

    settings.armed = false;

    settings.budget = 0;

    settingsDirty = true;

  }

  if (!settings.instanceId) {

    settings.instanceId = crypto.randomUUID().replaceAll('-', '');

    settingsDirty = true;

  }

  if (settingsDirty) await stateRepository.setLocal({ settings });

  return {

    registrations: data.registrations || {},

    settings,

    pending: data.pending || {},

    results: data.results || [],

    processed: data.processed || [],

    operations: data.operations || {},

    resultReceipts: data[RELAY_RESULT_RECEIPTS_KEY] || {},

    renameReceipts: data[RENAME_RECEIPTS_KEY] || {},

    bindingSubmitLeases: data[BINDING_SUBMIT_LEASES_KEY] || {},

    simpleRelayV0Binding: data[SIMPLE_RELAY_V0_BINDING_KEY] || null

  };

}

