const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const loader = fs.readFileSync(path.join(root, 'background_loader.js'), 'utf8');
const relay = fs.readFileSync(path.join(root, 'relay/contract.js'), 'utf8');
const envelope = fs.readFileSync(path.join(root, 'relay/envelope.js'), 'utf8');
const network = fs.readFileSync(path.join(root, 'network/directory.js'), 'utf8');
const browserReadAdapter = fs.readFileSync(path.join(root, 'browser/read_adapter.js'), 'utf8');

for (const file of ['identity.js', 'state.js', 'conversation.js', 'transport.js', 'shadow.js']) {
  const source = fs.readFileSync(path.join(root, 'core', file), 'utf8');
  assert(!source.includes('chrome.'), `Core/${file} must not depend on Chrome`);
}
assert(!relay.includes('chrome.'), 'Relay contract must not depend on Chrome');
assert(!relay.includes('sessionStorage'), 'Relay contract must not persist state');
assert(!relay.includes('retry'), 'Relay contract must not retry side effects');
assert(!envelope.includes('chrome.'), 'Relay envelope must not depend on Chrome');
assert(!network.includes('chrome.'), 'Conversation network must not depend on Chrome');
assert(!network.includes('storage.'), 'Conversation network must not persist state');
for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.remove', 'tabs.reload', 'windows.create', 'windows.update']) {
  assert(!browserReadAdapter.includes(prohibited), `Browser read adapter must not contain ${prohibited}`);
}
assert(loader.includes("importScripts('relay/contract.js');"), 'loader must select canonical Relay contract');
assert(loader.includes("importScripts('relay/envelope.js');"), 'loader must select relay envelope contract');
assert(loader.includes("importScripts('network/directory.js');"), 'loader must select conversation network contract');
assert(loader.includes("importScripts('browser/read_adapter.js');"), 'loader must select Browser read adapter');
assert(!loader.includes("importScripts('simple_relay_v0.js');"), 'loader must not select legacy Relay contract');

console.log('rcc architecture boundaries v3.5: PASS');
