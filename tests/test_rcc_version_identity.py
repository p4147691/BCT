"""RCC visible/runtime release identities stay tied to the installed payload."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / 'modules/rcc/extension'


class RccVersionIdentityTests(unittest.TestCase):
    def test_manifest_background_and_content_identify_same_release(self):
        manifest = json.loads((EXT / 'manifest.json').read_text())
        background = re.search(r"RCC_BACKGROUND_BUILD_ID = '([^']+)'", (EXT / 'boot/platform_context.js').read_text())[1]
        content = re.search(r"RCC_BUILD_VERSION = '([^']+)'", (EXT / 'content/conversation_dom.js').read_text())[1]
        self.assertEqual(background, content)
        self.assertIn(manifest['version'], background)
        self.assertTrue(manifest['version_name'].startswith(manifest['version'] + ' '))

    @unittest.skipUnless(shutil.which('node'), 'Node required for popup runtime verification')
    def test_popup_reads_installed_manifest_and_uses_text_content(self):
        script = r'''
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
for (const manifest of [{version:'9.8.7',version_name:'9.8.7 <release>'},{version:'9.8.6'}]) {
  const elements = new Map();
  const element = () => ({textContent:'',addEventListener(){},append(){}});
  const document = {getElementById(id){if(!elements.has(id)) elements.set(id,element());return elements.get(id);},createElement:element};
  const chrome = {runtime:{getManifest:()=>manifest,sendMessage:()=>new Promise(()=>{})}};
  vm.runInNewContext(source,{document,chrome});
  assert.equal(elements.get('versionLabel').textContent, manifest.version_name || manifest.version);
}
'''
        subprocess.run(['node', '-e', script, str(EXT / 'popup.js')], check=True, capture_output=True)
        self.assertIn('id="versionLabel"', (EXT / 'popup.html').read_text())
