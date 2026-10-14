const assert = require('assert');
const fs = require('fs');
const path = require('path');
const core = require('./relay_core.js');

const source = fs.readFileSync(path.join(__dirname, 'content.js'), 'utf8');
assert(source.includes("const scope = node.closest('[data-turn-key], [data-content-search-turn-key], [data-testid^=\"conversation-turn-\"]') || node.parentElement || node;"));
assert(source.includes('const completionUiReady = hasCompletionAction();'));
assert(!source.includes('const completionUiReady = hasCompletionAction() || isSendReady();'));

const partial = { sawNewAssistant: true, sawGeneration: false, generating: false, completionUiReady: false, textChanged: true, stableForMs: 5000 };
assert.strictEqual(core.shouldPromoteReply(partial), false, 'partial first token must not promote');

const transientGenerationGap = { ...partial, sawGeneration: true, stableForMs: 30000 };
assert.strictEqual(core.shouldPromoteReply(transientGenerationGap), false, 'generation history alone must never promote');

const completed = { ...partial, completionUiReady: true, stableForMs: 15000 };
assert.strictEqual(core.shouldPromoteReply(completed), true, 'final assistant action proves completion');

const backgroundCompleted = { ...partial, sawGeneration: true, generationLifecycleComplete: true, stableForMs: 15000 };
assert.strictEqual(core.shouldPromoteReply(backgroundCompleted), true, 'authoritative generation lifecycle proves background completion');

const fastBackgroundCompleted = { ...partial, sawGeneration: false, generationLifecycleComplete: true, stableForMs: 15000 };
assert.strictEqual(core.shouldPromoteReply(fastBackgroundCompleted), true, 'timestamped lifecycle survives polling gaps');

const tooSoon = { ...partial, completionUiReady: true, stableForMs: 14999 };
assert.strictEqual(core.shouldPromoteReply(tooSoon), false, 'completion action still requires full settle');

const stillStreaming = { ...completed, sawGeneration: true, generating: true, stableForMs: 20000 };
assert.strictEqual(core.shouldPromoteReply(stillStreaming), false, 'streaming text must never promote');

console.log('full result capture relay tests: PASS');
