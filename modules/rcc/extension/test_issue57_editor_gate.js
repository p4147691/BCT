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
    if (mode === 'send' && selector === 'button[data-testid="send-button"]') return button;
    if (mode === 'send-id' && selector === 'button#composer-submit-button') return button;
    if (mode === 'send-composer-testid' && selector === 'button[data-testid="composer-send-button"]') return button;
    return null;
  }};
  const editor = {
    tagName: 'TEXTAREA', value: '', focus() {},
    closest(selector) {
      if (selector === 'form') return scope;
      return null;
    }
  };
  const document = { documentElement: {}, querySelector() { return ['foreign-send','foreign-id'].includes(mode) ? button : null; } };
  class MutationObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe() {}
    disconnect() {}
  }
  let currentEditor = editor;
  const diagnostics = [];
  const context = {
    document, MutationObserver, setTimeout, clearTimeout, getEditor: () => currentEditor,
    RelayCore: { normalizeMessageText: value => String(value || '').trim() },
    console: { ...console, warn: (...args) => diagnostics.push(args) }
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
    clicks() { return clickCount; },
    diagnostics() { return diagnostics; }
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

  // Exact scoped composer IDs are accepted even when data-testid is absent.
  const currentId=makeHarness();
  currentId.editor.value='안전한 ID 기반 전송';
  currentId.setMode('send-id');
  const currentIdResult=await currentId.testing.submitEditor(currentId.editor, options('안전한 ID 기반 전송'));
  assert.equal(currentIdResult.method,'send-button');
  assert.equal(currentId.clicks(),1);

  const currentTestid=makeHarness();
  currentTestid.editor.value='현재 composer testid';
  currentTestid.setMode('send-composer-testid');
  await currentTestid.testing.submitEditor(currentTestid.editor,options('현재 composer testid'));
  assert.equal(currentTestid.clicks(),1);

  const foreignId=makeHarness();
  foreignId.editor.value='외부 버튼 금지';
  foreignId.setMode('foreign-id');
  await assert.rejects(
    foreignId.testing.submitEditor(foreignId.editor,options('외부 버튼 금지',30)),
    error => {
      assert.equal(String(error.message),
        'RELAY_SEND_BUTTON_NOT_READY:SEND_CONTROL_OUTSIDE_EDITOR');
      return true;
    });
  assert.equal(foreignId.clicks(),0);
  assert(foreignId.diagnostics().some(entry =>
    entry[0]==='RELAY_SEND_BUTTON_NOT_READY' &&
    entry[1]==='SEND_CONTROL_OUTSIDE_EDITOR'));

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

  // Direct relay used to allow Enter fallback in existing conversations.
  // Synthetic key events can be received without any browser default submit:
  // a missing send arrow must never yield {ok:true,method:'enter-fallback'}.
  const legacy=makeHarness();
  legacy.editor.value='기존 대화 직접 전송';
  await mustReject(legacy.testing.submitEditor(legacy.editor, {
    expectedText:'기존 대화 직접 전송',
    waitMs:30, allowKeyboardFallback:true, allowDocumentFallback:false
  }), 'RELAY_SEND_BUTTON_NOT_READY');
  assert.equal(legacy.clicks(),0,'no send arrow must never report a send');

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

  const outside=makeHarness();
  outside.editor.value='정확한 입력';
  outside.setMode('foreign-send');
  await mustReject(outside.testing.submitEditor(outside.editor, {
    expectedText:'정확한 입력', waitMs:30,
    allowKeyboardFallback:true, allowDocumentFallback:true
  }), 'RELAY_SEND_BUTTON_NOT_READY');
  assert.equal(outside.clicks(),0,'an unrelated document button must not be clicked');

  // Guard asynchronous authorization against a stale React composer.
  for (const changed of ['disabled', 'detached', 'draft', 'editor', 'voice']) {
    const stale=makeHarness();
    stale.editor.value='?? ??';
    stale.setMode('send');
    const original=stale.button;
    await mustReject(stale.testing.submitEditor(stale.editor, {
      expectedText:'?? ??', waitMs:80, allowDocumentFallback:false,
      beforeActivation:async () => {
        if (changed==='disabled') stale.setDisabled(true);
        if (changed==='detached') original.isConnected=false;
        if (changed==='draft') stale.editor.value='??';
        if (changed==='editor') stale.setCurrentEditor({tagName:'TEXTAREA',value:'?? ??',children:[]});
        if (changed==='voice') stale.setMode('voice');
      }
    }),changed==='draft'||changed==='editor'?'RELAY_EDITOR_TEXT_MISMATCH':'RELAY_SEND_BUTTON_CHANGED');
    assert.equal(stale.clicks(),0,'pre-activation '+changed+' must never click');
  }

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
  console.log('Issue57 editor/send-arrow readiness: 15 tests PASS');
}
main().catch(e=>{console.error(e); process.exitCode=1;});
