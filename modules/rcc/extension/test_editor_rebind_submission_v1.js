const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(
  require('node:path').join(__dirname, 'content/simple_relay_executor.js'), 'utf8'
);
const domSource = fs.readFileSync(
  require('node:path').join(__dirname, 'content/conversation_dom.js'), 'utf8'
);

function slice(sourceText, start, end) {
  const first = sourceText.indexOf(start);
  const last = sourceText.indexOf(end, first);
  assert(first >= 0 && last > first, `missing source boundary ${start}`);
  return sourceText.slice(first, last);
}

const expected = '한글 😀\nsecond line';
const original = {text: expected, focus() { this.focused = true; }};
const replacement = {text: expected, focus() { this.focused = true; }};
let current = replacement;
let clicked = 0;
const button = {click() { clicked += 1; }};

const context = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  getEditor: () => current,
  editorDraftText: editor => editor.text,
  waitForReadySendButton: async () => button,
  findReadySendButton: editor => editor === current ? button : null,
});
vm.runInContext(
  slice(source, 'async function submitEditor(', 'async function waitForReply(')
    + ';globalThis.submitEditorForTest = submitEditor;',
  context
);

const draftContext = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
});
vm.runInContext(
  slice(source, 'function editorDraftText(', 'function waitForExactUserSubmission(')
    + ';globalThis.editorDraftTextForTest = editorDraftText;',
  draftContext
);

const paragraph = (innerText, textContent) => ({tagName: 'P', innerText, textContent});
const proseMirrorDraft = {
  tagName: 'DIV',
  children: [
    paragraph('첫째', '첫째'),
    // A real ProseMirror empty paragraph exposes a layout newline through
    // innerText even though its logical textContent is empty.
    paragraph('\n', ''),
    paragraph('둘째 😀', '둘째 😀'),
  ],
  innerText: '첫째\n\n\n둘째 😀',
  textContent: '첫째둘째 😀',
};
assert.equal(
  draftContext.editorDraftTextForTest(proseMirrorDraft),
  '첫째\n\n둘째 😀',
  'blank ProseMirror paragraphs reconstruct one source blank line',
);

const artifactEditor = {id: 'artifact-editor'};
const promptEditor = {id: 'prompt-editor'};
const selectorMatches = new Map([
  ['#prompt-textarea', null],
  ['div[contenteditable="true"][data-virtualkeyboard="true"]', promptEditor],
  ['textarea[name="prompt-textarea"]', null],
  ['form div[contenteditable="true"][role="textbox"]', promptEditor],
  ['div[contenteditable="true"][role="textbox"]', artifactEditor],
]);
const targetContext = vm.createContext({
  document: {querySelector: selector => selectorMatches.get(selector) || null},
});
vm.runInContext(
  slice(domSource, 'function editorCandidates()', 'function conversationObserveRoot()')
    + ';globalThis.getEditorForTest = getEditor; globalThis.editorCandidatesForTest = editorCandidates;',
  targetContext
);
assert.equal(
  targetContext.getEditorForTest(),
  promptEditor,
  'the prompt-specific virtual-keyboard editor wins over an earlier artifact textbox',
);
assert.equal(
  Array.from(targetContext.editorCandidatesForTest()).includes(
    'div[contenteditable="true"][role="textbox"]'
  ),
  false,
  'an unscoped rich-text textbox is never a composer fallback',
);

(async () => {
  const accepted = await context.submitEditorForTest(original, {
    expectedText: expected,
    beforeSubmit: async () => ({binding: true}),
  });
  assert.equal(accepted.method, 'send-button');
  assert.equal(clicked, 1, 'the verified replacement editor submits exactly once');

  current = {text: expected + ' changed', focus() {}};
  await assert.rejects(
    context.submitEditorForTest(original, {expectedText: expected}),
    /RELAY_EDITOR_TEXT_MISMATCH/
  );
  assert.equal(clicked, 1, 'a changed replacement draft is never submitted');

  current = replacement;
  await assert.rejects(
    context.submitEditorForTest(original),
    /RELAY_EDITOR_TEXT_MISMATCH/,
    'without an exact expected draft, replacement identity stays forbidden'
  );
  assert.equal(clicked, 1);
  console.log('editor rebind and paragraph draft v2: PASS');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
