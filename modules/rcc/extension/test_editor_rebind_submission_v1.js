const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(
  require('node:path').join(__dirname, 'content/simple_relay_executor.js'), 'utf8'
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
  console.log('editor rebind submission v1: PASS');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
