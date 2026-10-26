import unittest
from pathlib import Path
class RCCSendSchemaContract(unittest.TestCase):
 def test_error_and_resource_scope_unchanged(self):
  source=(Path(__file__).parents[1]/"src/bct/features/rcc.py").read_text(encoding="utf-8")
  self.assertIn("RCC_SEND_TARGET_AND_TEXT_REQUIRED:send_requires_to_and_text;existing_tab_use_send-to-tab",source)
  self.assertIn(":direct-tab:",source)
  self.assertIn(":delivery:",source)
  self.assertIn("rcc-instance:",source)
 def test_no_legacy_alias(self):
  source=(Path(__file__).parents[1]/"src/bct/features/rcc.py").read_text(encoding="utf-8")
  self.assertIn("allowed.update(",source)
if __name__=="__main__":unittest.main()
