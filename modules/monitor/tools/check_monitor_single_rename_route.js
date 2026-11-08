const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const shared = fs.readFileSync(path.join(root, 'domains', 'shared-ui.js'), 'utf8');
const conversations = fs.readFileSync(path.join(root, 'domains', 'conversations.js'), 'utf8');
const bootstrap = fs.readFileSync(path.join(root, 'source-parts', '00-bootstrap-ui.js'), 'utf8');
const runtime = fs.readFileSync(path.join(root, 'extension', 'monitor.js'), 'utf8');

const attach = shared.match(/\/\/@@FN_START:attachMonitorContextTitleMenu\n([\s\S]*?)\n\/\/@@FN_END:attachMonitorContextTitleMenu/);
assert(attach, 'shared ChatGPT row rename binding must exist');
assert.match(attach[1], /openMonitorBctRenameEditor\(/);
assert.doesNotMatch(attach[1], /requestMonitorConversationRename|window\.prompt|actFetch/);
for (const text of [conversations, bootstrap, runtime]) {
  assert.doesNotMatch(text, /requestMonitorConversationRename|ORCHESTRATOR_CONVERSATION_RENAME_URL|act:\/monitor\/conversation-title\/rename/);
}
assert.match(runtime, /monitorBctShell\.renameConversation/);
console.log('monitor single rename route: PASS');
