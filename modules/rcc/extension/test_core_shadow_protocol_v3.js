const assert = require('assert');
const fs = require('fs');

const background = fs.readFileSync('domain/endpoint_service.js', 'utf8')
  + fs.readFileSync('domain/readonly_diagnostics.js', 'utf8');
const content = fs.readFileSync('content/content_router.js', 'utf8');
const loader = fs.readFileSync('background_loader.js', 'utf8');

const activity = content.split("message.type === 'relay:activityProbe'")[1]
  .split("message.type === 'relay:probe'")[0];
assert(activity.includes('generating: isGenerating()'));
assert(activity.includes('reasoning: currentReasoningObservation()'));
assert(activity.includes('connection: connectionProblem()'));
assert(activity.includes('telemetry: typeof telemetry === \'object\''));

const snapshot = background.split('async function endpointFromTabWithActivity(')[1]
  .split('async function captureEndpointSnapshot(', 1)[0];
assert(snapshot.includes('browserGateway.probeActivity(tab.id)'));
assert(snapshot.includes('endpoint.generating = !!probe?.generating'));
assert(snapshot.includes("endpoint.reasoning = probe?.reasoning"));
assert(snapshot.includes('endpoint.telemetry = probe?.telemetry'));
assert(snapshot.includes('endpoint.connection = probe?.connection'));
assert(!snapshot.includes('executeScript'));
assert(!snapshot.includes('sendToChatTab('));

const capture = background.split('async function captureEndpointSnapshot(')[1]
  .split('async function postEndpointPresence(', 1)[0];
assert(background.includes("surfaceKind === 'UNKNOWN'"));
assert(background.includes('function preserveKnownSurface(endpoint, prior)'));
assert(background.includes('newConversationInSameTab'));
assert(background.includes("['CHAT', 'WORK', 'CODEX'].includes(priorSurfaceKind)"));
const preserveKnownSurfaceSource = background.match(/function preserveKnownSurface\(endpoint, prior\) \{[\s\S]*?\n\}/)?.[0];
assert(preserveKnownSurfaceSource, 'surface continuity helper must be extractable');
const preserveKnownSurface = Function(`${preserveKnownSurfaceSource}; return preserveKnownSurface;`)();
const knownChat = { kind: 'CHAT', evidence: 'mode-control' };
const createdConversation = preserveKnownSurface(
  { conversationKey: 'conversation-a', surface: { kind: 'UNKNOWN' } },
  { conversationKey: '', surface: knownChat },
);
assert.strictEqual(createdConversation.surface, knownChat,
  'a known blank-tab mode must survive first-message navigation in the same tab');
const unrelatedConversation = preserveKnownSurface(
  { conversationKey: 'conversation-b', surface: { kind: 'UNKNOWN' } },
  { conversationKey: 'conversation-a', surface: knownChat },
);
assert.strictEqual(unrelatedConversation.surface.kind, 'UNKNOWN',
  'surface evidence must not leak across two different existing conversations');

const nativeState = background.split("if (message.command === 'state')")[1]
  .split("if (message.command === 'simple-relay-bind')", 1)[0];
assert(nativeState.includes('coreShadowSnapshot(tabs, endpoints, state.simpleRelayV0Binding)'));
assert(nativeState.includes('coreShadow,'));
for (const name of ['identity.js', 'state.js', 'conversation.js', 'transport.js', 'shadow.js']) {
  assert(loader.includes(`core/${name}`));
}
assert(loader.includes('platform/browser_gateway.js'));

console.log('core shadow content protocol v3: PASS');
