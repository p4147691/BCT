const assert = require('node:assert/strict');
const path = require('node:path');

const contract = require(path.join(__dirname, 'browser/tab_group_contract.js'));
const adapterFactory = require(path.join(__dirname, 'browser/tab_group_adapter.js'));

function harness() {
  const tabs = new Map([
    [11, { id: 11, windowId: 1, index: 0, groupId: -1, url: 'https://chatgpt.com/c/a' }],
    [12, { id: 12, windowId: 1, index: 1, groupId: -1, url: 'https://chatgpt.com/c/b' }],
    [13, { id: 13, windowId: 2, index: 0, groupId: -1, url: 'https://chatgpt.com/c/c' }],
    [99, { id: 99, windowId: 1, index: 2, groupId: -1, url: 'https://example.test/' }],
  ]);
  const groups = new Map();
  let nextGroupId = 7;
  const chromeApi = {
    tabs: {
      get: async (id) => ({ ...tabs.get(Number(id)) }),
      query: async (query) => [...tabs.values()].filter((tab) =>
        query.groupId === undefined || Number(tab.groupId) === Number(query.groupId)).map((tab) => ({ ...tab })),
      group: async ({ groupId, tabIds }) => {
        const id = groupId === undefined ? nextGroupId++ : Number(groupId);
        const members = tabIds.map(Number);
        const windowId = tabs.get(members[0]).windowId;
        if (!groups.has(id)) groups.set(id, { id, windowId, title: '', color: 'grey', collapsed: false });
        for (const tabId of members) tabs.set(tabId, { ...tabs.get(tabId), groupId: id });
        return id;
      },
      ungroup: async (tabId) => tabs.set(Number(tabId), { ...tabs.get(Number(tabId)), groupId: -1 }),
    },
    tabGroups: {
      get: async (id) => ({ ...groups.get(Number(id)) }),
      query: async () => [...groups.values()].map((group) => ({ ...group })),
      update: async (id, patch) => {
        groups.set(Number(id), { ...groups.get(Number(id)), ...patch });
        return { ...groups.get(Number(id)) };
      },
      move: async (id, { windowId, index }) => {
        const group = groups.get(Number(id));
        groups.set(Number(id), { ...group, windowId });
        for (const [tabId, tab] of tabs) {
          if (tab.groupId === Number(id)) tabs.set(tabId, { ...tab, windowId, index });
        }
        return { ...groups.get(Number(id)) };
      },
    },
  };
  const adapter = adapterFactory.create(chromeApi, contract);
  return { adapter, tabs, groups };
}

(async () => {
  const { adapter, tabs } = harness();
  const created = await adapter.apply({ command: 'create-tab-group', operationId: 'group-1', sessionId: 's',
    tabIds: [11, 12], title: '작업 A', color: 'blue', collapsed: false });
  assert.equal(created.state, 'APPLIED');
  assert.equal(created.group.groupId, 7);
  assert.deepEqual(created.group.memberTabIds, [11, 12]);

  const moved = await adapter.apply({ command: 'move-tab-group', operationId: 'group-2', sessionId: 's',
    groupId: 7, windowId: 1, targetWindowId: 2, index: -1 });
  assert.equal(moved.state, 'APPLIED');
  assert.equal(moved.group.windowId, 2);
  assert.equal(tabs.get(11).windowId, 2);
  assert.equal(tabs.get(12).windowId, 2);

  const added = await adapter.apply({ command: 'add-tab-to-group', operationId: 'group-3', sessionId: 's', groupId: 7, tabId: 13 });
  assert.equal(added.state, 'APPLIED');
  assert(added.group.memberTabIds.includes(13));
  const removed = await adapter.apply({ command: 'remove-tab-from-group', operationId: 'group-4', sessionId: 's', groupId: 7, tabId: 13 });
  assert.equal(removed.state, 'APPLIED');
  assert.equal(tabs.get(13).groupId, -1);

  const renamed = await adapter.apply({ command: 'update-tab-group', operationId: 'group-5', sessionId: 's',
    groupId: 7, title: '작업 B', color: 'purple', collapsed: true });
  assert.equal(renamed.state, 'APPLIED');
  assert.equal(renamed.group.title, '작업 B');
  assert.equal(renamed.group.collapsed, true);

  const generic = await adapter.apply({ command: 'create-tab-group', operationId: 'group-6', sessionId: 's',
    tabIds: [99], title: '개발 도구', color: 'red', collapsed: false });
  assert.equal(generic.state, 'APPLIED');
  assert.equal(generic.group.groupId, 8);
  const regrouped = await adapter.apply({ command: 'create-tab-group', operationId: 'group-7', sessionId: 's',
    tabIds: [11, 12], title: '새 그룹', color: 'red', collapsed: false });
  assert.equal(regrouped.state, 'APPLIED');
  assert.equal(regrouped.group.groupId, 9);
  const listed = await adapter.list();
  assert(listed.some((group) => group.groupId === 8 && group.eligible));
  assert(listed.some((group) => group.groupId === 9 && group.eligible));
  console.log('rcc browser tab group adapter v1: PASS');
})().catch((error) => { console.error(error); process.exitCode = 1; });
