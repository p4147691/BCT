"""Fixed, narrowly scoped ChatGPT DOM action for official Chrome DevTools MCP.

The caller cannot supply arbitrary JavaScript. The exact static function checks
the origin, conversation UUID, clean editor and prior delivery fingerprint BEFORE
one physical send-button click. It then observes a new user turn. A timeout after
the click is deliberately UNKNOWN and must never be automatically replayed.
"""
from __future__ import annotations

import hashlib
import json
import re


_UUID = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")

# The placeholder must occur exactly once. Do not interpolate user text into JS
# except as JSON data, to keep quote, newline and Unicode handling safe.
_SCRIPT = r"""async () => {
  const cfg = /*BCT_SEND_PAYLOAD*/null;
  const result = (status, code) => ({status, code, pageId: cfg.pageId,
    conversationUUID: cfg.uuid, intent: cfg.intent});
  if (location.origin !== 'https://chatgpt.com' ||
      location.pathname.toLowerCase() !== '/c/' + cfg.uuid)
    return result('NOT_SUBMITTED', 'TARGET_CONVERSATION_MISMATCH');
  const storageKey = 'bct-cdp-send-once-v1:' + cfg.intent;
  let prior;
  try { prior = sessionStorage.getItem(storageKey); }
  catch (_) { return result('NOT_SUBMITTED', 'SESSION_STORAGE_UNAVAILABLE'); }
  if (prior !== null)
    return result('ALREADY_ATTEMPTED', 'DUPLICATE_OR_UNCERTAIN');
  const users = () => Array.from(
    document.querySelectorAll('[data-message-author-role="user"]'));
  const originalUsers = users();
  if (originalUsers.some(node => (node.innerText || node.textContent || '').trim() === cfg.text))
    return result('NOT_SUBMITTED', 'IDENTICAL_MESSAGE_ALREADY_VISIBLE');
  const editor = document.querySelector('#prompt-textarea[contenteditable="true"]');
  if (!editor || !editor.isConnected)
    return result('NOT_SUBMITTED', 'EDITOR_NOT_FOUND');
  if ((editor.innerText || editor.textContent || '').trim())
    return result('NOT_SUBMITTED', 'EDITOR_NOT_EMPTY');
  if (document.querySelector('button[data-testid="stop-button"]'))
    return result('NOT_SUBMITTED', 'RESPONSE_IN_PROGRESS');
  editor.focus();
  // execCommand fires the editable input events used by the ChatGPT composer.
  if (!document.execCommand('insertText', false, cfg.text))
    return result('NOT_SUBMITTED', 'EDITOR_INSERT_REJECTED');
  await new Promise(resolve => setTimeout(resolve, 150));
  if (!editor.isConnected || (editor.innerText || editor.textContent || '').trim() !== cfg.text)
    return result('NOT_SUBMITTED', 'EDITOR_CONTENT_NOT_EXACT');
  if (location.origin !== 'https://chatgpt.com' ||
      location.pathname.toLowerCase() !== '/c/' + cfg.uuid)
    return result('NOT_SUBMITTED', 'TARGET_CHANGED_BEFORE_SEND');
  const send = document.querySelector('button[data-testid="send-button"]');
  if (!send || !send.isConnected || send.disabled ||
      send.getAttribute('aria-disabled') === 'true')
    return result('NOT_SUBMITTED', 'SEND_CONTROL_NOT_READY');
  // Record the intent before the only click. A lost response never resends.
  try { sessionStorage.setItem(storageKey, 'INTENT'); }
  catch (_) { return result('NOT_SUBMITTED', 'INTENT_RECORD_FAILED'); }
  try { send.click(); }
  catch (_) { return result('UNCERTAIN', 'CLICK_EXCEPTION_AFTER_INTENT'); }
  const deadline = Date.now() + 6000;
  while (Date.now() < deadline) {
    if (location.pathname.toLowerCase() !== '/c/' + cfg.uuid)
      return result('UNCERTAIN', 'TARGET_CHANGED_AFTER_CLICK');
    const after = users().slice(originalUsers.length);
    if (after.some(node => (node.innerText || node.textContent || '').trim() === cfg.text)) {
      try { sessionStorage.setItem(storageKey, 'CONFIRMED'); } catch (_) {}
      return result('CONFIRMED', 'USER_TURN_VISIBLE');
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  return result('UNCERTAIN', 'USER_TURN_NOT_CONFIRMED');
}"""


def delivery_fingerprint(conversation_uuid: str, text: str) -> str:
    return hashlib.sha256((conversation_uuid + "\n" + text).encode("utf-8")).hexdigest()


def build_submit_function(page_id: int, conversation_uuid: str, text: str) -> str:
    if (type(page_id) is not int or page_id < 1
            or not isinstance(conversation_uuid, str)
            or not _UUID.fullmatch(conversation_uuid)
            or not isinstance(text, str) or not text or not text.strip()
            or len(text) > 5000 or "\x00" in text):
        raise ValueError("CDP_SEND_INPUT_INVALID")
    payload = {
        "pageId": page_id,
        "uuid": conversation_uuid,
        "text": text,
        "intent": delivery_fingerprint(conversation_uuid, text),
    }
    return _SCRIPT.replace(
        "/*BCT_SEND_PAYLOAD*/null",
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
    )


def validate_submit_function(page_id: int, function: str) -> bool:
    if type(page_id) is not int or page_id < 1 or not isinstance(function, str):
        return False
    prefix, suffix = _SCRIPT.split("/*BCT_SEND_PAYLOAD*/null")
    if not function.startswith(prefix) or not function.endswith(suffix):
        return False
    encoded = function[len(prefix):len(function) - len(suffix)]
    try:
        payload = json.loads(encoded)
        if set(payload) != {"pageId", "uuid", "text", "intent"}:
            return False
        expected = build_submit_function(payload["pageId"], payload["uuid"], payload["text"])
        return (payload["pageId"] == page_id and function == expected
                and payload["intent"] == delivery_fingerprint(payload["uuid"], payload["text"]))
    except (ValueError, TypeError, KeyError):
        return False
