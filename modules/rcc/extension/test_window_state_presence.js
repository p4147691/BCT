const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync('domain/endpoint_service.js', 'utf8')
  + fs.readFileSync('domain/runtime_message_service.js', 'utf8');
const a = src.indexOf('function endpointFromTab(');
const b = src.indexOf('async function endpointFromTabWithActivity(', a);
if (a < 0 || b < 0) throw new Error('presence helpers missing');
const ctx = { result: null, RelayCore: { conversationKey: () => 'chat-x' }, browserGateway: { getWindow: async () => ({ left: 10, top: 20, width: 800, height: 600, state: 'minimized', focused: false }) } };
vm.createContext(ctx);
vm.runInContext(`${src.slice(a,b)}; result={endpointFromTab,endpointComparable,attachEndpointWindowBounds};`, ctx);
(async () => {
  const e = ctx.result.endpointFromTab({ id: 1, windowId: 2, url: 'https://chatgpt.com/c/chat-x', title: 'X', active: false });
  await ctx.result.attachEndpointWindowBounds(e);
  if (e.windowBounds.state !== 'minimized' || e.windowBounds.activeTab !== false) throw new Error('window state/active tab missing');
  const moved = JSON.parse(JSON.stringify(e)); moved.windowBounds.left = 30;
  if (ctx.result.endpointComparable(e) === ctx.result.endpointComparable(moved)) throw new Error('bounds changes must publish');
  if (!src.includes('endpointComparable(previous) === endpointComparable(endpoint)')) throw new Error('poll must compare fresh bounds');
  console.log('RELAY_WINDOW_STATE_PRESENCE_PASS');
})().catch((e) => { console.error(e); process.exitCode = 1; });
