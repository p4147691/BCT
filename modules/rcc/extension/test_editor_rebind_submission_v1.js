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
let generating = false;
const button = {click() { clicked += 1; }};
let waitBehavior = async () => button;

const context = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  getEditor: () => current,
  editorDraftText: editor => editor.text,
  waitForReadySendButton: (...args) => waitBehavior(...args),
  findReadySendButton: editor => editor === current ? button : null,
  isGenerating: () => generating,
  focusEditorAtEnd: editor => {
    editor.focus();
    return true;
  },
  ensureCurrentEditorFocusAtEnd: async () => {
    current.focus();
    return current;
  },
  wakeEditorWithTrailingSpace: () => true,
});
vm.runInContext(
  slice(source, 'async function submitEditor(', 'async function waitForReply(')
    + ';globalThis.submitEditorForTest = submitEditor;',
  context
);

const cleanupEditor = {text: ''};
const cleanupContext = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  isGenerating: () => false,
  waitForEditor: async () => cleanupEditor,
  getEditor: () => cleanupEditor,
  editorDraftText: editor => String(editor.text || '').trim(),
  getAssistantNodes: () => [],
  lastAssistantText: () => '',
  setEditorText: (editor, value) => { editor.text = value; },
  submitEditor: async () => { throw new Error('RELAY_TARGET_GENERATING'); },
  currentConversationKey: () => '22222222-2222-2222-2222-222222222222',
  waitForExactUserSubmission: async () => 'unused',
  saveRelayExecution() {},
  waitForReply: async () => 'unused',
});
vm.runInContext(
  slice(source, 'async function sendPrompt(', '// V0 is a one-way')
    + ';globalThis.sendPromptForTest = sendPrompt;',
  cleanupContext
);

const draftContext = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
});

const caretDocument = {activeElement: null};
const caretContext = vm.createContext({
  document: caretDocument,
  window: {getSelection() { throw new Error('textarea must not use DOM selection'); }},
});
vm.runInContext(
  slice(source, 'function focusEditorAtEnd(', 'function wakeEditorWithTrailingSpace(')
    + ';globalThis.focusEditorAtEndForTest = focusEditorAtEnd;',
  caretContext
);
const textarea = {
  tagName: 'TEXTAREA', value: expected, selectionStart: 0, selectionEnd: 0,
  focus() { caretDocument.activeElement = this; },
  contains() { return false; },
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
};
assert.equal(caretContext.focusEditorAtEndForTest(textarea), true);
assert.equal(textarea.selectionStart, expected.length);
assert.equal(textarea.selectionEnd, expected.length);

// React can rebind a valid composer one task after editor.focus().  The relay
// must wait for that non-mutating focus transition, then still require the
// exact end-of-draft caret before any activation is attempted.
const delayedFocusDocument = {activeElement: null};
let focusCalls = 0;
const delayedFocusContext = vm.createContext({
  document: delayedFocusDocument,
  window: {getSelection() { throw new Error('textarea must not use DOM selection'); }},
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  editorDraftText: editor => editor.value,
  getEditor: () => delayedTextarea,
  setTimeout(callback) { callback(); return 0; },
});
vm.runInContext(
  slice(source, 'function focusEditorAtEnd(', 'function wakeEditorWithTrailingSpace(')
    + ';globalThis.ensureCurrentEditorFocusAtEndForTest = ensureCurrentEditorFocusAtEnd;',
  delayedFocusContext
);
const delayedTextarea = {
  tagName: 'TEXTAREA', value: expected, selectionStart: 0, selectionEnd: 0,
  focus() {
    focusCalls += 1;
    if (focusCalls > 1) delayedFocusDocument.activeElement = this;
  },
  contains() { return false; },
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
};
const delayedFocusCheck = delayedFocusContext.ensureCurrentEditorFocusAtEndForTest(expected);

// A React commit can replace the composer root itself. Retrying the stale
// object is insufficient; reacquire the current exact-draft editor each time.
const reboundDocument = {activeElement: null};
const staleTextarea = {
  tagName: 'TEXTAREA', value: expected, isConnected: false,
  focus() {}, contains() { return false; }, setSelectionRange() {},
};
const liveTextarea = {
  tagName: 'TEXTAREA', value: expected, selectionStart: 0, selectionEnd: 0,
  focus() { reboundDocument.activeElement = this; },
  contains() { return false; },
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
};
let editorReads = 0;
const reboundContext = vm.createContext({
  document: reboundDocument,
  window: {getSelection() { throw new Error('textarea must not use DOM selection'); }},
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  editorDraftText: editor => editor.value,
  getEditor() { editorReads += 1; return editorReads === 1 ? staleTextarea : liveTextarea; },
  setTimeout(callback) { callback(); return 0; },
});
vm.runInContext(
  slice(source, 'function focusEditorAtEnd(', 'function wakeEditorWithTrailingSpace(')
    + ';globalThis.ensureCurrentEditorFocusAtEndForTest = ensureCurrentEditorFocusAtEnd;',
  reboundContext
);
const reboundFocusCheck = reboundContext.ensureCurrentEditorFocusAtEndForTest(expected);

// The composer wake pulse must never become part of the submitted payload.
// A previous implementation appended one space and immediately compared the
// draft with the unmodified expected text, producing a false UNKNOWN before
// any physical submit.
const pulseDocument = {activeElement: null};
class PulseTextarea {
  constructor(value) {
    this.tagName = 'TEXTAREA'; this.value = value;
    this.selectionStart = 0; this.selectionEnd = 0; this.isConnected = true;
  }
  focus() { pulseDocument.activeElement = this; }
  contains() { return false; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  dispatchEvent() { return true; }
}
const pulseContext = vm.createContext({
  RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
  document: pulseDocument,
  window: {getSelection() { throw new Error('textarea must not use DOM selection'); }},
  HTMLTextAreaElement: PulseTextarea,
  InputEvent: class InputEvent { constructor(type, init) { this.type = type; this.init = init; } },
  editorDraftText: editor => String(editor.value || '').replace(/\r\n?/g, '\n').trim(),
});
vm.runInContext(
  slice(source, 'function setEditorText(', 'function findReadySendButton(')
    + ';globalThis.wakeEditorForTest = wakeEditorWithTrailingSpace;',
  pulseContext
);
const pulseTextarea = new PulseTextarea(expected);
assert.equal(pulseContext.wakeEditorForTest(pulseTextarea, expected), true);
assert.equal(pulseTextarea.value, expected,
  'trailing-space wake restores the exact planned payload before submission');

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
  assert.equal(await delayedFocusCheck, delayedTextarea,
    'a delayed active-editor transition retries without typing or clicking');
  assert.equal(focusCalls, 2);
  assert.equal(delayedTextarea.selectionStart, expected.length);
  assert.equal(delayedTextarea.selectionEnd, expected.length);
  assert.equal(await reboundFocusCheck, liveTextarea,
    'a replaced composer is reacquired only when its exact draft is preserved');
  assert.equal(editorReads, 2);

  await assert.rejects(
    cleanupContext.sendPromptForTest('queued payload', {
      submitPolicy: {allowKeyboardFallback: false},
    }, false),
    /RELAY_TARGET_GENERATING/,
  );
  assert.equal(cleanupEditor.text, '',
    'a proven pre-activation failure removes only the exact BCT draft before queueing');

  const uncertainEditor = {text: ''};
  let recoveredRecord = null;
  const uncertainContext = vm.createContext({
    RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
    isGenerating: () => false,
    waitForEditor: async () => uncertainEditor,
    getEditor: () => uncertainEditor,
    editorDraftText: editor => String(editor.text || '').trim(),
    getAssistantNodes: () => [],
    lastAssistantText: () => '',
    setEditorText: (editor, value) => { editor.text = value; },
    submitEditor: async (_editor, options) => {
      options.submissionState.activationAttempted = true;
      options.submissionState.method = 'send-button';
      uncertainEditor.text = '';
      throw new Error('provider activation acknowledgement lost');
    },
    currentConversationKey: () => '22222222-2222-2222-2222-222222222222',
    waitForExactUserSubmission: async () => 'semantic:user:exact-return',
    saveRelayExecution: value => { recoveredRecord = value; },
    waitForReply: async () => 'unused',
  });
  vm.runInContext(
    slice(source, 'async function sendPrompt(', '// V0 is a one-way')
      + ';globalThis.sendPromptForTest = sendPrompt;',
    uncertainContext
  );
  const recoveredSubmit = await uncertainContext.sendPromptForTest('exact return', {
    relayId: 'return-001', submittedText: 'exact return', beforeTurnKeys: ['old-turn'],
    conversationKey: '22222222-2222-2222-2222-222222222222',
  }, false);
  assert.equal(recoveredSubmit.recoveredAfterSubmitError, true);
  assert.equal(recoveredRecord.phase, 'submitted');
  assert.equal(recoveredRecord.routeTurnKey, 'semantic:user:exact-return');

  // If the provider replaces the composer before any click/Enter activation,
  // a vanished BCT draft is evidence of a failed preparation, not an
  // ambiguous external send. Preserve the original stage in the error and do
  // not misclassify it as RELAY_DRAFT_CLEAR_UNPROVEN.
  const preActivationEditor = {text: ''};
  const preActivationState = {current: preActivationEditor};
  const preActivationContext = vm.createContext({
    RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
    isGenerating: () => false,
    waitForEditor: async () => preActivationEditor,
    getEditor: () => preActivationState.current,
    editorDraftText: editor => String(editor.text || '').trim(),
    getAssistantNodes: () => [],
    lastAssistantText: () => '',
    setEditorText: (editor, value) => { editor.text = value; },
    submitEditor: async (_editor, options) => {
      preActivationState.current = null;
      assert.equal(options.submissionState.activationAttempted, false);
      throw new Error('RELAY_SEND_BUTTON_CHANGED');
    },
    currentConversationKey: () => '22222222-2222-2222-2222-222222222222',
    waitForExactUserSubmission: async () => { throw new Error('must not recover an unactivated send'); },
    saveRelayExecution() {},
    waitForReply: async () => 'unused',
  });
  vm.runInContext(
    slice(source, 'async function sendPrompt(', '// V0 is a one-way')
      + ';globalThis.sendPromptForTest = sendPrompt;',
    preActivationContext
  );
  await assert.rejects(
    preActivationContext.sendPromptForTest('pre-activation draft', {
      relayId: 'pre-activation-001', submittedText: 'pre-activation draft',
      beforeTurnKeys: ['old-turn'],
      conversationKey: '22222222-2222-2222-2222-222222222222',
    }, false),
    /RELAY_SUBMIT_NOT_ACTIVATED:RELAY_SEND_BUTTON_CHANGED/,
  );

  // Once a click/Enter activation was attempted, the same missing draft is
  // still ambiguous unless the exact rendered user turn can be recovered.
  const postActivationEditor = {text: ''};
  const postActivationContext = vm.createContext({
    RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
    isGenerating: () => false,
    waitForEditor: async () => postActivationEditor,
    getEditor: () => null,
    editorDraftText: editor => String(editor.text || '').trim(),
    getAssistantNodes: () => [],
    lastAssistantText: () => '',
    setEditorText: (editor, value) => { editor.text = value; },
    submitEditor: async (_editor, options) => {
      options.submissionState.activationAttempted = true;
      options.submissionState.method = 'send-button';
      throw new Error('provider activation acknowledgement lost');
    },
    currentConversationKey: () => '22222222-2222-2222-2222-222222222222',
    waitForExactUserSubmission: async () => { throw new Error('exact turn not observed'); },
    saveRelayExecution() {},
    waitForReply: async () => 'unused',
  });
  vm.runInContext(
    slice(source, 'async function sendPrompt(', '// V0 is a one-way')
      + ';globalThis.sendPromptForTest = sendPrompt;',
    postActivationContext
  );
  await assert.rejects(
    postActivationContext.sendPromptForTest('post-activation draft', {
      relayId: 'post-activation-001', submittedText: 'post-activation draft',
      beforeTurnKeys: ['old-turn'],
      conversationKey: '22222222-2222-2222-2222-222222222222',
    }, false),
    /RELAY_DRAFT_CLEAR_UNPROVEN/,
  );

  const classificationContext = vm.createContext({
    RelayCore: {normalizeMessageText: value => String(value).replace(/\r\n?/g, '\n').trim()},
    currentConversationKey: () => '22222222-2222-2222-2222-222222222222',
    loadRelayExecution: () => null,
    getConversationTurns: () => [],
    turnIdentity: () => '',
    sendPrompt: async () => {
      throw new Error('RELAY_SUBMIT_NOT_ACTIVATED:RELAY_SEND_BUTTON_CHANGED');
    },
  });
  vm.runInContext(
    slice(source, 'async function executeSimpleRelayV0(', '// This read is intentionally narrow')
      + ';globalThis.executeSimpleRelayV0ForTest = executeSimpleRelayV0;',
    classificationContext
  );
  const notActivated = await classificationContext.executeSimpleRelayV0ForTest({
    relayId: 'not-activated-001',
    conversationKey: '22222222-2222-2222-2222-222222222222',
    text: 'pre-activation draft',
  });
  assert.equal(notActivated.effectState, 'NOT_APPLIED');
  assert.equal(notActivated.error,
    'RELAY_SUBMIT_NOT_ACTIVATED:RELAY_SEND_BUTTON_CHANGED');

  const accepted = await context.submitEditorForTest(original, {
    expectedText: expected,
    beforeSubmit: async () => ({binding: true}),
  });
  assert.equal(accepted.method, 'send-button');
  assert.equal(clicked, 1, 'the verified replacement editor submits exactly once');

  current = {text: expected + ' transient', focus() {}};
  waitBehavior = async () => {
    current = replacement;
    return button;
  };
  const settled = await context.submitEditorForTest(original, {expectedText: expected});
  assert.equal(settled.method, 'send-button');
  assert.equal(clicked, 2, 'a transient draft mismatch waits for the exact settled draft');

  waitBehavior = async () => button;
  current = {text: expected + ' changed', focus() {}};
  await assert.rejects(
    context.submitEditorForTest(original, {expectedText: expected}),
    /RELAY_EDITOR_TEXT_MISMATCH/
  );
  assert.equal(clicked, 2, 'a changed replacement draft is never submitted');

  current = replacement;
  generating = true;
  await assert.rejects(
    context.submitEditorForTest(original, {expectedText: expected}),
    /RELAY_TARGET_GENERATING/,
    'a visible send button never overrides active generation'
  );
  generating = false;
  assert.equal(clicked, 2, 'generation guard prevents a stop/send race click');

  current = replacement;
  await assert.rejects(
    context.submitEditorForTest(original),
    /RELAY_EDITOR_TEXT_MISMATCH/,
    'without an exact expected draft, replacement identity stays forbidden'
  );
  assert.equal(clicked, 2);
  console.log('editor rebind, paragraph draft, and settle fence v3: PASS');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
