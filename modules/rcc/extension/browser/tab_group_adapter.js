(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RccBrowserTabGroupAdapter = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  function create(chromeApi, contract, identity) {
    if (typeof chromeApi?.tabs?.get !== 'function' || typeof chromeApi?.tabs?.query !== 'function'
        || typeof chromeApi?.tabs?.group !== 'function' || typeof chromeApi?.tabs?.ungroup !== 'function'
        || typeof chromeApi?.tabGroups?.get !== 'function' || typeof chromeApi?.tabGroups?.move !== 'function'
        || typeof chromeApi?.tabGroups?.update !== 'function') {
      throw new Error('RCC_BROWSER_TAB_GROUP_API_REQUIRED');
    }
    if (!contract?.STATES || typeof contract.normalizeIntent !== 'function'
        || typeof contract.receipt !== 'function') throw new Error('RCC_BROWSER_TAB_GROUP_CONTRACT_REQUIRED');
    async function members(groupId) {
      return (await chromeApi.tabs.query({ groupId })).filter((tab) => Number(tab?.groupId) === groupId);
    }

    async function eligibleGroup(groupId, expectedWindowId = null) {
      const group = await chromeApi.tabGroups.get(groupId);
      const tabs = await members(groupId);
      if (!tabs.length || (expectedWindowId !== null && Number(group.windowId) !== expectedWindowId)) return null;
      return { group, tabs };
    }

    async function groupSnapshot(groupId) {
      const group = await chromeApi.tabGroups.get(groupId);
      const tabs = await members(groupId);
      return { group, tabs };
    }

    async function apply(value) {
      const intent = contract.normalizeIntent(value);
      let before = null;
      try {
        if (intent.command === 'create-tab-group') {
          const tabs = await Promise.all(intent.tabIds.map((tabId) => chromeApi.tabs.get(tabId)));
          if (new Set(tabs.map((tab) => Number(tab.windowId))).size !== 1) {
            return contract.receipt(intent, contract.STATES.NOT_APPLIED, { error: 'TAB_GROUP_MEMBERS_NOT_SAME_WINDOW' });
          }
          const groupId = await chromeApi.tabs.group({ tabIds: intent.tabIds });
          await chromeApi.tabGroups.update(groupId, { title: intent.title, color: intent.color, collapsed: intent.collapsed });
          const after = await groupSnapshot(groupId);
          if (after.tabs.length !== intent.tabIds.length || after.tabs.some((tab) => Number(tab.groupId) !== groupId)) {
            return contract.receipt(intent, contract.STATES.UNKNOWN, { group: after.group,
              memberTabIds: after.tabs.map((tab) => tab.id), error: 'TAB_GROUP_CREATE_POSTCONDITION_UNPROVEN' });
          }
          return contract.receipt(intent, contract.STATES.APPLIED, { group: after.group, memberTabIds: after.tabs.map((tab) => tab.id) });
        }
        before = await eligibleGroup(intent.groupId, intent.expectedWindowId ?? null);
        if (!before) return contract.receipt(intent, contract.STATES.NOT_APPLIED, { error: 'TAB_GROUP_IDENTITY_MISMATCH' });
        if (intent.command === 'add-tab-to-group') {
          const tab = await chromeApi.tabs.get(intent.tabId);
          if (Number(tab.windowId) !== Number(before.group.windowId)) {
            return contract.receipt(intent, contract.STATES.NOT_APPLIED, { error: 'TAB_GROUP_ADD_TAB_WINDOW_MISMATCH' });
          }
          await chromeApi.tabs.group({ groupId: intent.groupId, tabIds: [intent.tabId] });
        } else if (intent.command === 'remove-tab-from-group') {
          const tab = await chromeApi.tabs.get(intent.tabId);
          if (Number(tab.groupId) !== intent.groupId) {
            return contract.receipt(intent, contract.STATES.NOT_APPLIED, { error: 'TAB_GROUP_REMOVE_TAB_MEMBERSHIP_MISMATCH' });
          }
          await chromeApi.tabs.ungroup(intent.tabId);
          const afterTab = await chromeApi.tabs.get(intent.tabId);
          if (Number(afterTab.groupId) !== -1) {
            return contract.receipt(intent, contract.STATES.UNKNOWN, { group: before.group,
              memberTabIds: before.tabs.map((tab) => tab.id), error: 'TAB_GROUP_REMOVE_POSTCONDITION_UNPROVEN' });
          }
        } else if (intent.command === 'move-tab-group') {
          await chromeApi.tabGroups.move(intent.groupId, { windowId: intent.targetWindowId, index: intent.index });
        } else if (intent.command === 'update-tab-group') {
          const patch = {};
          if (intent.title !== null) patch.title = intent.title;
          if (intent.color !== null) patch.color = intent.color;
          if (intent.collapsed !== null) patch.collapsed = intent.collapsed;
          await chromeApi.tabGroups.update(intent.groupId, patch);
        }
        const resolvedId = intent.command === 'move-tab-group'
          ? Number((await chromeApi.tabGroups.get(intent.groupId))?.id) || intent.groupId : intent.groupId;
        const after = await groupSnapshot(resolvedId);
        if (intent.command === 'add-tab-to-group' && !after.tabs.some((tab) => Number(tab.id) === intent.tabId)
            || intent.command === 'move-tab-group' && Number(after.group.windowId) !== intent.targetWindowId
            || intent.command === 'update-tab-group' && ((intent.title !== null && after.group.title !== intent.title)
              || (intent.color !== null && after.group.color !== intent.color)
              || (intent.collapsed !== null && after.group.collapsed !== intent.collapsed))) {
          return contract.receipt(intent, contract.STATES.UNKNOWN, { group: after.group,
            memberTabIds: after.tabs.map((tab) => tab.id), error: 'TAB_GROUP_POSTCONDITION_UNPROVEN' });
        }
        return contract.receipt(intent, contract.STATES.APPLIED, { group: after.group, memberTabIds: after.tabs.map((tab) => tab.id) });
      } catch (error) {
        return contract.receipt(intent, before ? contract.STATES.UNKNOWN : contract.STATES.NOT_APPLIED, {
          group: before?.group, memberTabIds: before?.tabs?.map((tab) => tab.id) || [],
          error: String(error?.message || error || 'TAB_GROUP_EFFECT_UNKNOWN'),
        });
      }
    }

    async function list() {
      const groups = await chromeApi.tabGroups.query({});
      const snapshots = await Promise.all(groups.map(async (group) => {
        const tabs = await members(Number(group.id));
        return { ...contract.publicGroup(group, tabs.map((tab) => tab.id)), eligible: tabs.length > 0 };
      }));
      return snapshots;
    }

    async function get(groupId) {
      const group = await chromeApi.tabGroups.get(groupId);
      const tabs = await members(groupId);
      return { ...contract.publicGroup(group, tabs.map((tab) => tab.id)), eligible: tabs.length > 0 };
    }

    return Object.freeze({ apply, list, get });
  }

  return Object.freeze({ create });
});
