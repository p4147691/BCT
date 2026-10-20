const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const loader = fs.readFileSync(path.join(root, 'background_loader.js'), 'utf8');
const relay = fs.readFileSync(path.join(root, 'relay/contract.js'), 'utf8');

for (const file of ['identity.js', 'state.js', 'conversation.js', 'transport.js', 'shadow.js']) {
  const source = fs.readFileSync(path.join(root, 'core', file), 'utf8');
  assert(!source.includes('chrome.'), `Core/${file} must not depend on Chrome`);
}
assert(!relay.includes('chrome.'), 'Relay contract must not depend on Chrome');
assert(!relay.includes('sessionStorage'), 'Relay contract must not persist state');
assert(!relay.includes('retry'), 'Relay contract must not retry side effects');
assert(loader.includes("importScripts('relay/contract.js');"), 'loader must select canonical Relay contract');
assert(!loader.includes("importScripts('simple_relay_v0.js');"), 'loader must not select legacy Relay contract');

console.log('rcc architecture boundaries v3.5: PASS');
