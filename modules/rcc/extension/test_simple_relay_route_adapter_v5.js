const assert = require('assert');
const fs = require('fs');
const path = require('path');

const content = fs.readFileSync(path.join(__dirname, 'content.js'), 'utf8');
const background = fs.readFileSync(path.join(__dirname, 'background.js'), 'utf8');
const execute = content.split('async function executeSimpleRelayV0(message) {')[1]
  .split('// This read is intentionally narrow:', 1)[0];
const read = content.split('async function readSimpleRelayV0Reply(message) {')[1]
  .split('function currentConversationKey()', 1)[0];

assert(execute.includes('beforeTurnKeys: getConversationTurns().map(turnIdentity).filter(Boolean)'));
assert(execute.includes('sendPrompt(text, record, false)'));
assert(execute.includes('const routed = resolveRoutedTurn(persistedRecord)'));
assert(execute.includes('persistedRecord.routeTurnKey = routed.turnKey'));
assert(read.includes('const record = loadRelayExecution()'));
assert(read.includes('record?.relayId !== relayId'));
assert(read.includes('recoverCompletedReplyFromDom(record)'));
assert(!read.includes('getAssistantNodes().length'));
assert(background.includes('afterAssistantCount: source.beforeAssistantCount, relayId: sourceOperationId'));
assert(background.includes('function publicSimpleRelayV0Receipt(receipt)'));
assert(background.includes('relayReceipt: publicSimpleRelayV0Receipt(result.receipt)'));

console.log('simple relay route adapter v5: PASS');
