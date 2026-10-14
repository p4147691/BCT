const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content.js', 'utf8');
function sliceBetween(startText, endText) {
  const start = source.indexOf(startText);
  const end = source.indexOf(endText, start);
  assert(start >= 0 && end > start, 'source function boundary missing');
  return source.slice(start, end);
}
const gateSource = sliceBetween('function findReadySendButton(', 'async function waitForReply(');
const draftSource = sliceBetween('function editorDraftText(', 'function waitForExactUserSubmission(');
assert(source.indexOf('setEditorText(editor, requestedText);') < source.indexOf('await submitEditor(editor, {'));
assert(source.includes('editor = await waitForExactDraftEditor(requestedText);'));
assert(source.includes('allowKeyboardFallback: message.bootstrapCreatedTab !== true'));

function makeHarness() {
  let mode = 'voice', ariaDisabled = false, disabled = false, clickCount = 0;
  const observers = [];
  const button = {
    isConnected: true,
    get disabled() { return disabled; },
    getAttribute(name) { return name === 'aria-disabled' && ariaDisabled ? 'true' : null; },
    getClientRects() { return [{}]; },
    click() { ++clickCount; }
  };
  const scope = {querySelector(selector) {
    return mode === 'send' && selector === 'button[data-testid="send-button"]' ? button : null;
  }};
  const editor = {
    tagName: 'TEXTAREA', value: '', focus() {},
    closest(selector) {
      if (selector === 'form') return scope;
      return null;
    }
  };
  const document = { documentElement: {}, querySelector() { return mode === 'foreign-send' ? button : null; } };
  class MutationObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() {}
  }
  let currentEditor = editor;
  const context = {
    document, MutationObserver, setTimeout, clearTimeout, getEditor: () => currentEditor,
    RelayCore: { normalizeMessageText: value => String(value || '').trim() },
    console
  };
  vm.createContext(context);
  vm.runInContext(gateSource + '\n' + draftSource +
    '\nglobalThis.testing = {submitEditor, findReadySendButton, waitForReadySendButton, editorDraftText, reacquireExactDraftEditor, waitForExactDraftEditor};', context);
  return {
    editor, button, testing: context.testing,
    setMode(value) { mode = value; observers.forEach(o=>o.callback()); },
    setDisabled(value) { disabled = value; observers.forEach(o=>o.callback()); },
    setAriaDisabled(value) { ariaDisabled = value; observers.forEach(o=>o.callback()); },
    setCurrentEditor(value) { currentEditor = value; observers.forEach(o=>o.callback()); },
    clicks() { return clickCount; }
  };
}
const options = (text, timeout=80) => ({
  expectedText:text, waitMs:timeout, allowKeyboardFallback:false, allowDocumentFallback:false
});
async function mustReject(promise, code) {
  await assert.rejects(promise, error => {
    assert(String(error.message).includes(code), String(error.message));
    return true;
  });
}
async function main() {
  const a=makeHarness();
  a.editor.value='연결 테스트입니다.';
  const waiting=a.testing.submitEditor(a.editor,options('연결 테스트입니다.',250));
  assert.equal(a.clicks(),0,'voice-mode must not click');
  setTimeout(()=>a.setMode('send'),15);
  const result=await waiting;
  assert.equal(result.method,'send-button');
  assert.equal(a.clicks(),1,'exactly one send click after mode transition');

  const b=makeHarness();
  b.editor.value='잘못된 글자';
  b.setMode('send');
  await mustReject(b.testing.submitEditor(b.editor,options('원래 글자')), 'RELAY_EDITOR_TEXT_MISMATCH');
  assert.equal(b.clicks(),0,'wrong draft must not click');

  const c=makeHarness();
  c.editor.value='확인';
  c.setMode('send');
  c.setAriaDisabled(true);
  const blocked=c.testing.submitEditor(c.editor,options('확인',250));
  assert.equal(c.clicks(),0,'aria-disabled must not click');
  setTimeout(()=>c.setAriaDisabled(false),15);
  await blocked;
  assert.equal(c.clicks(),1);

  const d=makeHarness();
  d.editor.value='확인';
  d.setMode('send');
  d.setDisabled(true);
  const pending=d.testing.submitEditor(d.editor,options('확인',250));
  setTimeout(()=>d.setDisabled(false),15);
  await pending;
  assert.equal(d.clicks(),1);

  const e=makeHarness();
  e.editor.value='확인';
  await mustReject(e.testing.submitEditor(e.editor,options('확인',30)), 'RELAY_SEND_BUTTON_NOT_READY');
  assert.equal(e.clicks(),0,'mic-only mode must never Enter-submit');

  const f=makeHarness();
  f.editor.value='확인';
  const stale=f.testing.submitEditor(f.editor,options('확인',150));
  f.setMode('send');
  f.setMode('voice');
  await mustReject(stale,'RELAY_SEND_BUTTON_CHANGED');
  assert.equal(f.clicks(),0,'stale send button must not click');

  const g=makeHarness();
  g.editor.value='확인';
  g.setMode('foreign-send');
  await mustReject(g.testing.submitEditor(g.editor,options('확인',30)), 'RELAY_SEND_BUTTON_NOT_READY');
  assert.equal(g.clicks(),0,'out-of-composer send button must not click');

  const h=makeHarness();
  const paragraphEditor={
    tagName:'DIV',
    innerText:'header\n\npayload',
    textContent:'headerpayload',
    children:[
      {tagName:'P',innerText:'header',textContent:'header'},
      {tagName:'P',innerText:'payload',textContent:'payload'}
    ]
  };
  assert.equal(h.testing.editorDraftText(paragraphEditor),'header\npayload',
    'ProseMirror paragraph spacing must preserve the inserted newline');

  const i=makeHarness();
  const replacement={tagName:'TEXTAREA',value:'bounded task',children:[]};
  i.setCurrentEditor(replacement);
  assert.equal(i.testing.reacquireExactDraftEditor('bounded task'),replacement,
    'an exact ProseMirror replacement must become the fenced submission editor');
  replacement.value='changed task';
  assert.equal(i.testing.reacquireExactDraftEditor('bounded task'),null,
    'a replacement with changed draft text must remain blocked');

  const j=makeHarness();
  const settling={tagName:'TEXTAREA',value:'partial',children:[]};
  j.setCurrentEditor(settling);
  const stable=j.testing.waitForExactDraftEditor('bounded task',250);
  setTimeout(()=>{ settling.value='bounded task'; j.setCurrentEditor(settling); },15);
  assert.equal(await stable,settling,
    'the exact asynchronously stabilized draft must be accepted');

  const k=makeHarness();
  k.setCurrentEditor({tagName:'TEXTAREA',value:'different task',children:[]});
  assert.equal(await k.testing.waitForExactDraftEditor('bounded task',20),null,
    'a draft that never becomes exact must remain blocked');
  console.log('Issue57 editor/send-arrow readiness: 12 tests PASS');
}
main().catch(e=>{console.error(e); process.exitCode=1;});
