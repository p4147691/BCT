import unittest
from bct.features.window_layout import Rect
from bct.features.window_layout_operations import plan_window_operations

class LayoutOperationContractTests(unittest.TestCase):
    def test_four_windows_exact_existing_manage_contract(self):
        leases = {str(i): f"{i:032x}" for i in range(1,5)}
        result = plan_window_operations(Rect(-1920, 40, 1920, 1040), leases)
        self.assertEqual(len(result), 4)
        self.assertEqual(result["1"]["operation"], "move_resize")
        self.assertEqual((result["4"]["x"], result["4"]["y"],result["4"]["width"],result["4"]["height"]),(-960,560,960,520))

    def test_multimonitor_negative_origin(self):
        r = plan_window_operations(Rect(-2560, -100, 2560, 1400), {str(i):f"{i:032x}" for i in range(1,7)},columns=3)
        self.assertEqual(len(r),6)
        self.assertEqual(min(item["x"] for item in r.values()),-2560)

    def test_invalid_lease_and_unsupported_bounds(self):
        with self.assertRaises(ValueError):
            plan_window_operations(Rect(0,0,1000,900), {"x":"bogus"})
        with self.assertRaises(ValueError):
            plan_window_operations(Rect(0,0,9000,900), {"x":"a"*32},columns=1)

if __name__ == "__main__":
    unittest.main()
