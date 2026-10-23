"""Run the fixed CDP send function against a simulated DOM in Node.js.

This never launches Chrome or accesses any ChatGPT account.
"""
import json
import shutil
import subprocess
import unittest

from bct.integrations.cdp_send_script import build_submit_function


PAGE = 6
UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TEXT = "격리 클릭 검증 \n one-message"


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for DOM fixture")
class CDPSendDOMTests(unittest.TestCase):
    def evaluate(self, mode):
        func = build_submit_function(PAGE, UUID, TEXT)
        # Only the fixture owns these DOM shims. The production function is
        # the exact source that the MCP evaluate_script action will execute.
        harness = r"""
const cfg = __CONFIG__;
const mode = cfg.mode;
const storage = new Map();
let clicks = 0;
const users = [];
const location = {origin:'https://chatgpt.com',
                  pathname: mode === 'wrong' ? '/c/wrong' : '/c/' + cfg.uuid};
const sessionStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key,value) {storage.set(key,value);}
};
const editor = {
  isConnected:true, innerText:'', focus(){}
};
const button = {
  isConnected:true,disabled:false,getAttribute(){return null;},
  click() {
    clicks++;
    if (mode === 'throw') throw new Error('click error');
    users.push({innerText:cfg.text});
  }
};
const document = {
  querySelector(selector) {
    if (selector === '#prompt-textarea[contenteditable="true"]') return editor;
    if (selector === 'button[data-testid="send-button"]') return button;
    return null;
  },
  querySelectorAll(selector) {
    if (selector === '[data-message-author-role="user"]') return users;
    return [];
  },
  execCommand(cmd,show,value) {
    if (cmd !== 'insertText') return false;
    editor.innerText = value;
    return true;
  }
};
const run = __FUNCTION__;
(async () => {
 const first = await run();
 const second = await run();
 console.log(JSON.stringify({first,second,clicks,storageCount:storage.size}));
})().catch(err => { console.error(err.stack); process.exit(3); });
"""
        script = (harness
            .replace("__CONFIG__",json.dumps({"mode": mode, "uuid":UUID, "text":TEXT}))
            .replace("__FUNCTION__",func))
        completed = subprocess.run(
            [shutil.which("node"), "-e", script], check=False, timeout=12,
            encoding="utf8", capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[-1000:])
        return json.loads(completed.stdout)

    def test_only_one_physical_click_in_same_tab(self):
        result = self.evaluate("success")
        self.assertEqual(result["first"]["status"], "CONFIRMED")
        self.assertEqual(result["second"]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(result["clicks"], 1)

    def test_wrong_conversation_is_rejected_before_click(self):
        result = self.evaluate("wrong")
        self.assertEqual(result["first"]["status"], "NOT_SUBMITTED")
        self.assertEqual(result["clicks"], 0)

    def test_uncertain_click_is_not_retried(self):
        result = self.evaluate("throw")
        self.assertEqual(result["first"]["status"], "UNCERTAIN")
        self.assertEqual(result["second"]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(result["clicks"], 1)


if __name__ == "__main__":
    unittest.main()
