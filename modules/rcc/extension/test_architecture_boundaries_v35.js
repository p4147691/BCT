const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = __dirname;
const loader = fs.readFileSync(path.join(root, 'background_loader.js'), 'utf8');
const relay = fs.readFileSync(path.join(root, 'relay/contract.js'), 'utf8');
const envelope = fs.readFileSync(path.join(root, 'relay/envelope.js'), 'utf8');
const network = fs.readFileSync(path.join(root, 'network/directory.js'), 'utf8');
const browserReadAdapter = fs.readFileSync(path.join(root, 'browser/read_adapter.js'), 'utf8');
const tabMoveContract = fs.readFileSync(path.join(root, 'browser/tab_move_contract.js'), 'utf8');
const tabMoveAdapter = fs.readFileSync(path.join(root, 'browser/tab_move_adapter.js'), 'utf8');
const tabCreateContract = fs.readFileSync(path.join(root, 'browser/tab_create_contract.js'), 'utf8');
const tabCreateAdapter = fs.readFileSync(path.join(root, 'browser/tab_create_adapter.js'), 'utf8');
const tabCloseContract = fs.readFileSync(path.join(root, 'browser/tab_close_contract.js'), 'utf8');
const tabCloseAdapter = fs.readFileSync(path.join(root, 'browser/tab_close_adapter.js'), 'utf8');
const windowCreateContract = fs.readFileSync(path.join(root, 'browser/window_create_contract.js'), 'utf8');
const windowCreateAdapter = fs.readFileSync(path.join(root, 'browser/window_create_adapter.js'), 'utf8');
const tabReloadContract = fs.readFileSync(path.join(root, 'browser/tab_reload_contract.js'), 'utf8');
const tabReloadAdapter = fs.readFileSync(path.join(root, 'browser/tab_reload_adapter.js'), 'utf8');
const background = fs.readFileSync(path.join(root, 'background.js'), 'utf8');

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
assert(!tabMoveContract.includes('chrome.'), 'Tab move receipt contract must not depend on Chrome');
assert(!tabMoveContract.includes('storage.'), 'Tab move receipt contract must not persist state');
for (const prohibited of ['tabs.create', 'tabs.remove', 'tabs.reload', 'windows.create', 'windows.update', 'sendMessage']) {
  assert(!tabMoveAdapter.includes(prohibited), `Tab move adapter must not contain ${prohibited}`);
}
assert(tabMoveAdapter.includes('tabs.move'), 'Tab move adapter must own the single tab move effect');
assert(!background.includes('chrome.tabs.move'), 'Background must delegate tab movement to the adapter');
assert(!tabCreateContract.includes('chrome.'), 'Tab create receipt contract must not depend on Chrome');
assert(!tabCreateContract.includes('storage.'), 'Tab create receipt contract must not persist state');
for (const prohibited of ['tabs.move', 'tabs.remove', 'tabs.reload', 'windows.create', 'windows.update', 'sendMessage']) {
  assert(!tabCreateAdapter.includes(prohibited), `Tab create adapter must not contain ${prohibited}`);
}
assert(tabCreateAdapter.includes('tabs.create'), 'Tab create adapter must own the tab create effect');
assert(!background.includes('chrome.tabs.create'), 'Background must delegate tab creation to the adapter');
assert(!tabCloseContract.includes('chrome.'), 'Tab close receipt contract must not depend on Chrome');
assert(!tabCloseContract.includes('storage.'), 'Tab close receipt contract must not persist state');
for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.reload', 'windows.create', 'windows.update', 'sendMessage']) {
  assert(!tabCloseAdapter.includes(prohibited), `Tab close adapter must not contain ${prohibited}`);
}
assert(tabCloseAdapter.includes('tabs.remove'), 'Tab close adapter must own the tab close effect');
assert(!background.includes('chrome.tabs.remove'), 'Background must delegate tab closing to the adapter');
assert(!windowCreateContract.includes('chrome.'), 'Window create receipt contract must not depend on Chrome');
assert(!windowCreateContract.includes('storage.'), 'Window create receipt contract must not persist state');
for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.remove', 'tabs.reload', 'windows.update', 'sendMessage']) {
  assert(!windowCreateAdapter.includes(prohibited), `Window create adapter must not contain ${prohibited}`);
}
assert(windowCreateAdapter.includes('windows.create'), 'Window create adapter must own the window create effect');
assert(!background.includes('chrome.windows.create'), 'Background must delegate window creation to the adapter');
assert(!tabReloadContract.includes('chrome.'), 'Tab reload receipt contract must not depend on Chrome');
assert(!tabReloadContract.includes('storage.'), 'Tab reload receipt contract must not persist state');
for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.remove', 'windows.create', 'windows.update', 'sendMessage']) {
  assert(!tabReloadAdapter.includes(prohibited), `Tab reload adapter must not contain ${prohibited}`);
}
assert(tabReloadAdapter.includes('tabs.reload'), 'Tab reload adapter must own the tab reload effect');
assert(!background.includes('chrome.tabs.reload'), 'Background must delegate tab reload to the adapter');
for (const prohibited of ['tabs.create', 'tabs.move', 'tabs.remove', 'tabs.reload', 'windows.create', 'windows.update']) {
  assert(!browserReadAdapter.includes(prohibited), `Browser read adapter must not contain ${prohibited}`);
}
assert(loader.includes("importScripts('relay/contract.js');"), 'loader must select canonical Relay contract');
assert(loader.includes("importScripts('relay/envelope.js');"), 'loader must select relay envelope contract');
assert(loader.includes("importScripts('network/directory.js');"), 'loader must select conversation network contract');
assert(loader.includes("importScripts('browser/read_adapter.js');"), 'loader must select Browser read adapter');
for (const optional of [
  'browser/tab_move_contract.js', 'browser/tab_move_adapter.js',
  'browser/tab_create_contract.js', 'browser/tab_create_adapter.js',
  'browser/tab_close_contract.js', 'browser/tab_close_adapter.js',
  'browser/window_create_contract.js', 'browser/window_create_adapter.js',
  'browser/tab_reload_contract.js', 'browser/tab_reload_adapter.js',
]) {
  assert(!loader.includes(`importScripts('${optional}');`), `${optional} must remain optional and unloaded`);
}
assert(!loader.includes("importScripts('act_bridge.js');"), 'retired ACT bridge must not load');
assert(!loader.includes("importScripts('simple_relay_v0.js');"), 'loader must not select legacy Relay contract');

console.log('rcc architecture boundaries v3.5: PASS');
