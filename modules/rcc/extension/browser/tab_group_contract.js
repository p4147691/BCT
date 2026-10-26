(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabGroupContract = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const COLORS = new Set([
    'grey', 'blue', 'red', 'yellow', 'green', 'pink', 'purple', 'cyan', 'orange',
  ]);
  const STATES = Object.freeze({
    APPLIED: 'APPLIED',
    NOT_APPLIED: 'NOT_APPLIED',
    UNKNOWN: 'UNKNOWN',
  });

  function positiveInteger(value, code) {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 1) throw new Error(code);
    return number;
  }

  function groupId(value) {
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 0) throw new Error('TAB_GROUP_ID_INVALID');
    return number;
  }

  function tabIds(value) {
    if (!Array.isArray(value) || !value.length || value.length > 32) {
      throw new Error('TAB_GROUP_TAB_IDS_INVALID');
    }
    const normalized = value.map((item) => positiveInteger(item, 'TAB_GROUP_TAB_ID_INVALID'));
    if (new Set(normalized).size !== normalized.length) throw new Error('TAB_GROUP_TAB_IDS_DUPLICATE');
    return normalized;
  }

  function title(value, required = false) {
    if (value === undefined || value === null) {
      if (required) throw new Error('TAB_GROUP_TITLE_REQUIRED');
      return '';
    }
    const normalized = String(value).trim();
    if ((required && !normalized) || normalized.length > 100) throw new Error('TAB_GROUP_TITLE_INVALID');
    return normalized;
  }

  function color(value) {
    if (value === undefined || value === null || value === '') return '';
    const normalized = String(value).trim().toLowerCase();
    if (!COLORS.has(normalized)) throw new Error('TAB_GROUP_COLOR_INVALID');
    return normalized;
  }

  function optionalBoolean(value, code) {
    if (value === undefined || value === null) return null;
    if (typeof value !== 'boolean') throw new Error(code);
    return value;
  }

  function normalizeIntent(value) {
    const intent = value || {};
    const operationId = String(intent.operationId || '').trim();
    const command = String(intent.command || '').trim();
    const sessionId = String(intent.sessionId || '').trim();
    if (!operationId) throw new Error('TAB_GROUP_OPERATION_ID_REQUIRED');
    if (!sessionId) throw new Error('TAB_GROUP_SESSION_ID_REQUIRED');
    if (!['create-tab-group', 'add-tab-to-group', 'remove-tab-from-group',
      'move-tab-group', 'update-tab-group'].includes(command)) {
      throw new Error('TAB_GROUP_COMMAND_INVALID');
    }
    const base = { operationId, command, sessionId };
    if (command === 'create-tab-group') {
      return Object.freeze({ ...base, tabIds: tabIds(intent.tabIds), title: title(intent.title, true),
        color: color(intent.color) || 'grey', collapsed: optionalBoolean(intent.collapsed, 'TAB_GROUP_COLLAPSED_INVALID') ?? false });
    }
    if (command === 'add-tab-to-group') {
      return Object.freeze({ ...base, groupId: groupId(intent.groupId), tabId: positiveInteger(intent.tabId, 'TAB_GROUP_TAB_ID_INVALID') });
    }
    if (command === 'remove-tab-from-group') {
      return Object.freeze({ ...base, groupId: groupId(intent.groupId), tabId: positiveInteger(intent.tabId, 'TAB_GROUP_TAB_ID_INVALID') });
    }
    if (command === 'move-tab-group') {
      const index = Number(intent.index);
      if (!Number.isSafeInteger(index) || index < -1) throw new Error('TAB_GROUP_INDEX_INVALID');
      return Object.freeze({ ...base, groupId: groupId(intent.groupId),
        expectedWindowId: positiveInteger(intent.windowId ?? intent.expectedWindowId, 'TAB_GROUP_WINDOW_ID_INVALID'),
        targetWindowId: positiveInteger(intent.targetWindowId, 'TAB_GROUP_TARGET_WINDOW_ID_INVALID'), index });
    }
    const changedTitle = intent.title === undefined ? null : title(intent.title, true);
    const changedColor = intent.color === undefined ? null : color(intent.color);
    const collapsed = optionalBoolean(intent.collapsed, 'TAB_GROUP_COLLAPSED_INVALID');
    if (changedTitle === null && changedColor === null && collapsed === null) {
      throw new Error('TAB_GROUP_UPDATE_EMPTY');
    }
    return Object.freeze({ ...base, groupId: groupId(intent.groupId), title: changedTitle,
      color: changedColor, collapsed });
  }

  function fingerprint(value) {
    const intent = normalizeIntent(value);
    return JSON.stringify(intent);
  }

  function publicGroup(group, memberTabIds = []) {
    return Object.freeze({
      groupId: Number.isSafeInteger(Number(group?.id)) ? Number(group.id) : null,
      windowId: Number.isSafeInteger(Number(group?.windowId)) ? Number(group.windowId) : null,
      title: String(group?.title || ''), color: String(group?.color || ''),
      collapsed: group?.collapsed === true,
      memberTabIds: memberTabIds.map(Number).filter(Number.isSafeInteger),
    });
  }

  function receipt(value, state, details = {}) {
    const intent = normalizeIntent(value);
    if (!Object.values(STATES).includes(state)) throw new Error('TAB_GROUP_RECEIPT_STATE_INVALID');
    const applied = state === STATES.APPLIED;
    return Object.freeze({
      schema: 'rcc.browser.tab-group.receipt.v1', command: intent.command,
      operationId: intent.operationId, fingerprint: fingerprint(intent), state,
      effectState: applied ? 'APPLIED_CONFIRMED' : state === STATES.NOT_APPLIED ? 'NOT_APPLIED' : 'UNKNOWN',
      ok: applied, retrySafe: false, group: details.group ? publicGroup(details.group, details.memberTabIds || []) : null,
      error: applied ? '' : String(details.error || state),
    });
  }

  return Object.freeze({ COLORS, STATES, normalizeIntent, fingerprint, publicGroup, receipt });
});
