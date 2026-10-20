const assert = require('assert');
const network = require('./network/directory.js');
const envelope = require('./relay/envelope.js');

const manager = '6ad5afa4-b1e0-83ee-8692-aec4bb51523e';
const worker = '6ad4bb5d-6624-83ee-b045-e57fdad5120e';

const directory = network.directory({
  project: { projectId: 'bct.rcc', displayName: 'BCT RCC' },
  nodes: [
    { conversationKey: manager, displayName: '오류 병목 감시 측정기', roleTags: ['조정', '병목 분석'] },
    { conversationKey: worker, displayName: '대화 기록 조회 구현', roleTags: ['구현', '테스트', '구현'] },
  ],
});
assert.equal(directory.version, 1);
assert.deepEqual(directory.nodes[1].roleTags, ['구현', '테스트']);
assert.equal(directory.nodes[0].activity, network.NODE_ACTIVITY.ACTIVE);
assert.throws(() => network.directory({ project: directory.project, nodes: [directory.nodes[0], directory.nodes[0]] }), /RCC_NETWORK_NODE_DUPLICATE/);

const handoff = envelope.compose({
  direction: envelope.DIRECTION.HANDOFF,
  sourceLabel: directory.nodes[0].displayName,
  targetLabel: directory.nodes[1].displayName,
  body: '재현 원인과 수정안을 확인해줘.',
});
assert.equal(handoff.body, '재현 원인과 수정안을 확인해줘.');
assert(handoff.text.includes('[BCT 반환 안내 v1]'));
assert(handoff.text.includes('오류 병목 감시 측정기'));
assert.throws(() => envelope.compose({
  direction: envelope.DIRECTION.HANDOFF,
  sourceLabel: directory.nodes[0].displayName,
  targetLabel: directory.nodes[1].displayName,
  body: '',
}), /RCC_CORE_TEXT_INVALID/);

const returned = envelope.compose({
  direction: envelope.DIRECTION.RETURN,
  sourceLabel: directory.nodes[1].displayName,
  targetLabel: directory.nodes[0].displayName,
  body: '원인은 API 응답 처리 오류입니다.',
});
assert(returned.text.includes('[BCT 후속 판단 안내 v1]'));
assert(returned.text.includes('다음 전달서를 작성'));

const draft = network.relayRecord({
  relayId: 'relay.42', sourceConversationKey: manager, targetConversationKey: worker,
  originalText: handoff.body, guidance: handoff.guidance,
});
const sending = network.transitionRelay(draft, network.RELAY_STATE.SENDING, '2026-10-20T11:52:00+09:00');
const delivered = network.transitionRelay(sending, network.RELAY_STATE.DELIVERED, '2026-10-20T11:52:01+09:00');
const waiting = network.transitionRelay(delivered, network.RELAY_STATE.AWAITING_REPLY, '2026-10-20T11:52:01+09:00');
assert.equal(waiting.state, network.RELAY_STATE.AWAITING_REPLY);
assert.equal(waiting.originalText, handoff.body);
assert.throws(() => network.transitionRelay(waiting, network.RELAY_STATE.RETURNED, '2026-10-20T11:52:02+09:00'), /RCC_NETWORK_RELAY_TRANSITION_INVALID/);

const returnRelay = network.relayRecord({
  relayId: 'relay.42.return', parentRelayId: 'relay.42',
  sourceConversationKey: worker, targetConversationKey: manager,
  originalText: '원인은 API 응답 처리 오류입니다.', guidance: returned.guidance,
});
assert.equal(returnRelay.parentRelayId, 'relay.42');
assert.equal(returnRelay.sourceConversationKey, worker);

console.log('conversation network v7: PASS');
