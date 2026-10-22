const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content/conversation_dom.js', 'utf8');
const from = source.indexOf('function connectionProblem() {');
const to = source.indexOf('function isConnectionHealthy()', from);
assert(from >= 0 && to > from);
const functionSource = source.slice(from, to);

function inspect({message='',taggedAsConversation=false,offline=false}={}) {
  const banner = {
    textContent: message,
    innerText: message,
    closest: () => taggedAsConversation ? {} : null,
    querySelector: () => null,
  };
  const context = vm.createContext({
    navigator:{onLine:!offline},
    document:{querySelectorAll:(selector) =>
      selector === '[role="alert"]' && message ? [banner] : []}
  });
  return vm.runInContext(functionSource + '\nconnectionProblem()',context);
}
assert.equal(inspect().disconnected,false);
assert.equal(inspect({message:'메시지 전송 시간이 초과되었습니다. 다시 시도하세요.'}).disconnected,true);
assert.equal(inspect({message:'네트워크 오류. 전체 답변을 기다리는 중입니다.'}).disconnected,true);
assert.equal(inspect({message:'stream recovery polling timed out'}).disconnected,true);
assert.equal(inspect({message:'Message sending timed out'}).disconnected,true);
assert.equal(inspect({message:'메시지 전송 시간이 초과되었습니다.',
  taggedAsConversation:true}).disconnected,false,'user-provided text is not a network alert');
assert.equal(inspect({message:'일반적인 상태 안내'}).disconnected,false);
assert.equal(inspect({offline:true}).reason,'browser-offline');
console.log('RCC chat stream signal detection v1: PASS');
