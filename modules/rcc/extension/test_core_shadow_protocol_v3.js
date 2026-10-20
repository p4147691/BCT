const assert = require('assert');
const fs = require('fs');

const background = fs.readFileSync('background.js', 'utf8');
const content = fs.readFileSync('content.js', 'utf8');
const loader = fs.readFileSync('background_loader.js', 'utf8');

const activity = content.split("message.type === 'relay:activityProbe'")[1]
  .split("message.type === 'relay:probe'")[0];
assert(activity.includes('generating: isGenerating()'));
assert(activity.includes('connection: connectionProblem()'));
assert(activity.includes('telemetry: typeof telemetry === \'object\''));

const snapshot = background.split('async function endpointFromTabWithActivity(')[1]
  .split('async function captureEndpointSnapshot(', 1)[0];
assert(snapshot.includes('browserGateway.probeActivity(tab.id)'));
assert(snapshot.includes('endpoint.generating = !!probe?.generating'));
assert(snapshot.includes('endpoint.telemetry = probe?.telemetry'));
assert(snapshot.includes('endpoint.connection = probe?.connection'));
assert(!snapshot.includes('executeScript'));
assert(!snapshot.includes('sendToChatTab('));

const nativeState = background.split("if (message.command === 'state')")[1]
  .split("if (message.command === 'simple-relay-bind')", 1)[0];
assert(nativeState.includes('coreShadowSnapshot(tabs, endpoints, state.simpleRelayV0Binding)'));
assert(nativeState.includes('coreShadow,'));
for (const name of ['identity.js', 'state.js', 'conversation.js', 'transport.js', 'shadow.js']) {
  assert(loader.includes(`core/${name}`));
}
assert(loader.includes('platform/browser_gateway.js'));

console.log('core shadow content protocol v3: PASS');
