const assert = require('assert');
const fs = require('fs');

const source = fs.readFileSync('content.js', 'utf8');
assert(!source.includes('RCC_DONE_'), 'active content script must not require RCC_DONE markers');
assert(!source.includes('makeCompletionMarker'), 'marker generator must be removed');
assert(!source.includes('wrapPromptWithMarker'), 'prompt marker wrapping must be removed');
assert(source.includes('nodes.length > beforeCount'), 'completion must require a new assistant turn');
assert(source.includes("document.querySelector(selector)"),
  'generation detection must work when a background tab is not visually rendered');
assert(source.includes('const requiredStableMs = 15000'),
  'completion must require the current conservative stable non-streaming window');
assert(source.includes('return waitForReply(beforeCount, beforeText);'),
  'sendPrompt must use markerless completion lifecycle');
assert(source.includes('delivery ambiguous'),
  'markerless timeout must fail closed as ambiguous delivery');
console.log('markerless completion lifecycle tests: PASS (8/8)');
