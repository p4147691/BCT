import unittest
from bct.features.window_layout import Rect
from bct.features.window_layout_multimonitor import plan_monitors

class MultiMonitorTests(unittest.TestCase):
    def test_separate_monitor_four_way(self):
        areas={"left":Rect(-1920,0,1920,1040),"right":Rect(0,0,2560,1400)}
        assignments={"left":["a","b","c","d"],"right":["e","f","g","h"]}
        result=plan_monitors(areas,assignments)
        self.assertEqual(len(result),8)
        self.assertEqual(result["d"],Rect(-960,520,960,520))
        self.assertEqual(result["h"],Rect(1280,700,1280,700))
    def test_reject_collision(self):
        with self.assertRaises(ValueError):
            plan_monitors({"a":Rect(0,0,1920,1080),"b":Rect(1920,0,1920,1080)},{"a":["1"],"b":["1"]})
    def test_unknown_monitor(self):
        with self.assertRaises(ValueError):
            plan_monitors({"a":Rect(0,0,1920,1080)},{"b":["1"]})
    def test_unsupported_window_minimum(self):
        with self.assertRaises(ValueError):
            plan_monitors({"a":Rect(0,0,150,100)},{"a":["1","2"]},min_width=100)
