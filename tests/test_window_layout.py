import unittest
from bct.features.window_layout import Rect, plan_grid

class WindowLayoutTests(unittest.TestCase):
    def test_four_quadrants_with_offset(self):
        result = plan_grid(Rect(-1920, 40, 1920, 1040), ["N71", "N72", "N73", "N74"])
        self.assertEqual(result["N71"], Rect(-1920, 40, 960, 520))
        self.assertEqual(result["N74"], Rect(-960, 560, 960, 520))

    def test_six_and_eight(self):
        for total, columns in ((6, 3), (8, 4)):
            slots = plan_grid(Rect(0, 0, 1920, 1080), [str(i) for i in range(total)], columns=columns, gap=8)
            self.assertEqual(len(slots), total)
            self.assertTrue(all(s.width > 0 and s.height > 0 for s in slots.values()))

    def test_minimum_size_and_identity(self):
        with self.assertRaises(ValueError):
            plan_grid(Rect(0, 0, 100, 100), ["a", "b", "c", "d"], min_width=60)
        with self.assertRaises(ValueError):
            plan_grid(Rect(0, 0, 500, 500), ["a", "a"])

    def test_two_and_three(self):
        self.assertEqual(len(plan_grid(Rect(0, 0, 1000, 800), ["a", "b"], columns=2)), 2)
        self.assertEqual(len(plan_grid(Rect(0, 0, 1000, 800), ["a", "b", "c"], columns=2)), 3)

if __name__ == "__main__":
    unittest.main()
