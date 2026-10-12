// Runs in the existing service worker. Caller identity never comes from model JSON.
const actPending = new Map();

function acceptActNativeResult(message) {
  if (message?.type !== 'host:act-result') return false;
  const pending = actPending.get(message.requestId);
  if (pending) {
    clearTimeout(pending.timer);
    actPending.delete(message.requestId);
    pending.resolve(message.response);
  }
  return true;
}

async function actNativeRequest(op, caller, directive) {
  if (!nativePort && typeof connectNativeHost === 'function') await connectNativeHost();
  if (!nativePort) throw new Error('NATIVE_BRIDGE_UNAVAILABLE');
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      actPending.delete(requestId);
      reject(new Error('ACT_NATIVE_DELIVERY_UNCERTAIN:reuse_same_request_id'));
    }, 10000);
    actPending.set(requestId, { resolve, reject, timer });
    try { nativePort.postMessage({ type: 'host:act', requestId, op, caller, directive }); }
    catch (error) { clearTimeout(timer); actPending.delete(requestId); reject(error); }
  });
}

async function requestActBootstrapResync(tab) {
  if (!tab || !isChatTab(tab)) throw new Error('ACT_INVALID_CHAT_ENDPOINT');
  const firstKey = RelayCore.conversationKey(tab.url);
  const current = await chrome.tabs.get(tab.id);
  if (!firstKey || RelayCore.conversationKey(current.url) !== firstKey) throw new Error('ACT_ENDPOINT_DRIFT');
  const state = await loadState();
  const caller = { conversation_key: firstKey, transport_instance_id: state.settings.instanceId,
    session_id: endpointSessionId, tab_id: tab.id };
  const endpoint = endpointFromTab(current, 'OPEN', 'act-bootstrap');
  endpointPresence.set(tab.id, endpoint);
  await publishEndpointDelta(endpoint, 'act-bootstrap');
  const result = await actNativeRequest('bootstrap', caller);
  if (!result?.ok) throw new Error(result?.error || 'ACT_BOOTSTRAP_UNAVAILABLE');
  const identity = result.bootstrap_contract?.identity;
  if (result.self?.conversation_key !== firstKey || result.self?.generation !== identity?.binding_generation) {
    throw new Error('ACT_BOOTSTRAP_IDENTITY_DRIFT');
  }
  for (const field of Object.keys(caller)) {
    if (identity?.[field] !== caller[field]) throw new Error('ACT_BOOTSTRAP_IDENTITY_DRIFT');
  }
  if (RelayCore.conversationKey((await chrome.tabs.get(tab.id)).url) !== firstKey) throw new Error('ACT_ENDPOINT_DRIFT');
  return result;
}

async function requestActNaturalCommand(sender, text) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab) ||
      RelayCore.conversationKey(sender.url) !== RelayCore.conversationKey(sender.tab.url)) {
    throw new Error('ACT_UNTRUSTED_SENDER');
  }
  const commandText = String(text || '').trim();
  if (!commandText || commandText.length > 500) throw new Error('ACT_COMMAND_INVALID');
  const bootstrap = await requestActBootstrapResync(sender.tab);
  const identity = bootstrap.bootstrap_contract.identity;
  const caller = Object.fromEntries(['conversation_key', 'transport_instance_id', 'session_id', 'tab_id', 'window_instance_id']
    .map((key) => [key, identity[key]]));
  if (!caller.window_instance_id) throw new Error('ACT_WINDOW_IDENTITY_UNAVAILABLE');
  const response = await actNativeRequest('command', caller, { text: commandText });
  if (RelayCore.conversationKey((await chrome.tabs.get(sender.tab.id)).url) !== caller.conversation_key) {
    throw new Error('ACT_RESULT_ENDPOINT_DRIFT');
  }
  return response;
}

async function requestActDirectTask(sender, directive) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab) ||
      RelayCore.conversationKey(sender.url) !== RelayCore.conversationKey(sender.tab.url)) {
    throw new Error('ACT_UNTRUSTED_SENDER');
  }
  const fields = directive?.op === 'submit' ? ['op', 'id', 'operation'] : ['op', 'task_id'];
  if (!directive || !['submit', 'status', 'result'].includes(directive.op) ||
      Object.keys(directive).sort().join(',') !== fields.sort().join(',')) throw new Error('ACT_DIRECTIVE_INVALID');
  const bootstrap = await requestActBootstrapResync(sender.tab);
  const identity = bootstrap.bootstrap_contract.identity;
  const caller = Object.fromEntries(['conversation_key', 'transport_instance_id', 'session_id', 'tab_id',
    'binding_generation'].map((key) => [key, identity[key]]));
  const response = await actNativeRequest(directive.op, caller, directive);
  if (RelayCore.conversationKey((await chrome.tabs.get(sender.tab.id)).url) !== caller.conversation_key) {
    throw new Error('ACT_RESULT_ENDPOINT_DRIFT');
  }
  return { ...response, conversation_key: caller.conversation_key };
}

async function requestActLocalExecution(sender, directive) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab) ||
      RelayCore.conversationKey(sender.url) !== RelayCore.conversationKey(sender.tab.url)) {
    throw new Error('ACT_UNTRUSTED_SENDER');
  }
  if (!directive || Object.keys(directive).sort().join(',') !== 'arguments,attempt_id,id,operation,task_id' ||
      typeof directive.operation !== 'string' || !directive.operation ||
      typeof directive.task_id !== 'string' || !directive.task_id ||
      typeof directive.attempt_id !== 'string' || !directive.attempt_id ||
      !directive.arguments || typeof directive.arguments !== 'object' || Array.isArray(directive.arguments)) {
    throw new Error('ACT_LOCAL_EXEC_DIRECTIVE_INVALID');
  }
  const bootstrap = await requestActBootstrapResync(sender.tab);
  const identity = bootstrap.bootstrap_contract.identity;
  const caller = Object.fromEntries(['conversation_key', 'transport_instance_id', 'session_id', 'tab_id',
    'binding_generation'].map((key) => [key, identity[key]]));
  const response = await actNativeRequest('local-exec', caller, directive);
  if (RelayCore.conversationKey((await chrome.tabs.get(sender.tab.id)).url) !== caller.conversation_key) {
    throw new Error('ACT_RESULT_ENDPOINT_DRIFT');
  }
  return { ...response, conversation_key: caller.conversation_key };
}

async function requestActWorkerOperation(sender, directive) {
  if (sender.id !== chrome.runtime.id || sender.frameId !== 0 || !isChatTab(sender.tab) ||
      RelayCore.conversationKey(sender.url) !== RelayCore.conversationKey(sender.tab.url)) {
    throw new Error('ACT_UNTRUSTED_SENDER');
  }
  const op = String(directive?.op || '');
  const schema = {
    'worker-status': { required: ['task_id'], optional: [] },
    'worker-claim': { required: ['task_id'], optional: [] },
    'worker-start': { required: ['task_id', 'attempt_id'], optional: [] },
    'worker-result': { required: ['task_id', 'attempt_id', 'summary'], optional: ['changed_files', 'tests', 'artifacts', 'checkpoint', 'blockers', 'follow_up'] },
    'worker-complete': { required: ['task_id', 'attempt_id'], optional: [] },
    'worker-return-status': { required: ['task_id'], optional: [] },
  }[op];
  if (!schema || !directive || typeof directive !== 'object') throw new Error('ACT_WORKER_DIRECTIVE_INVALID');
  const allowed = new Set(['op', ...schema.required, ...schema.optional]);
  if (Object.keys(directive).some((key) => !allowed.has(key)) ||
      schema.required.some((key) => directive[key] == null || directive[key] === '')) {
    throw new Error('ACT_WORKER_DIRECTIVE_INVALID');
  }
  const bootstrap = await requestActBootstrapResync(sender.tab);
  const identity = bootstrap.bootstrap_contract.identity;
  const caller = Object.fromEntries(['conversation_key', 'transport_instance_id', 'session_id', 'tab_id', 'binding_generation']
    .map((key) => [key, identity[key]]));
  const args = { ...directive };
  delete args.op;
  const response = await actNativeRequest(op, caller, args);
  if (RelayCore.conversationKey((await chrome.tabs.get(sender.tab.id)).url) !== caller.conversation_key) {
    throw new Error('ACT_RESULT_ENDPOINT_DRIFT');
  }
  return { ...response, conversation_key: caller.conversation_key };
}

