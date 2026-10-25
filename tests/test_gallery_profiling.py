import unittest

from tk_support import TkTestCase
from tkwin11 import profiling
from tkwin11.motion import Tween


class GalleryProfilingTests(TkTestCase):
    def setUp(self):
        super().setUp()
        self.previous = profiling._ENABLED
        profiling._ENABLED = True
        self.addCleanup(setattr, profiling, '_ENABLED', self.previous)

    def test_disabled_operations_have_no_state(self):
        profiling._ENABLED = False
        self.assertIsNone(profiling.operation_start(self.root, 'page_open', 'cold'))
        with profiling.span(self.root, 'page_prepare'):
            pass
        self.assertIsNone(profiling.snapshot(self.root))
        self.assertFalse(hasattr(self.root, '_tkwin11_profile'))

    def test_operation_markers_spans_and_reset(self):
        operation = profiling.operation_start(self.root, 'page_open', 'cold', {'page': 'all'})
        with profiling.span(self.root, 'page_prepare', 'page'):
            pass
        with profiling.span(self.root, 'raster', 'image', sample=False):
            pass
        with profiling.span(self.root, 'raster', 'image', sample=False):
            pass
        profiling.operation_mark(self.root, operation)
        profiling.operation_mark(self.root, operation)
        profiling.operation_finish(self.root, operation)
        result = profiling.snapshot(self.root)
        measured = result['operations'][0]
        self.assertEqual(measured['details'], {'page': 'all'})
        self.assertEqual(measured['status'], 'done')
        self.assertIsNotNone(measured['first_visual_ms'])
        self.assertIsNotNone(measured['settled_ms'])
        self.assertGreaterEqual(measured['settled_ms'], measured['first_visual_ms'])
        self.assertEqual(len(measured['spans']), 1)
        self.assertEqual(measured['span_totals']['raster']['count'], 2)
        self.assertEqual(profiling.state(self.root)['active_operations'], [])
        profiling.snapshot(self.root, reset=True)
        self.assertEqual(profiling.snapshot(self.root)['operations'], [])

    def test_tween_samples_follow_starting_operation(self):
        operation = profiling.operation_start(self.root, 'expansion_toggle', 'layout')
        done = []
        tween = Tween(self.root)
        tween.start(0, 1, lambda value: None, duration=35, done=lambda: done.append(1))
        self.wait_until(lambda: done == [1])
        profiling.operation_finish(self.root, operation)
        measured = profiling.snapshot(self.root)['operations'][0]
        self.assertGreater(measured['tween_update_count'], 0)
        self.assertGreater(measured['tween_update_ms_total'], 0)
        self.assertEqual(len(measured['sched_delay_ms']), len(measured['gap_ms']))


if __name__ == '__main__':
    unittest.main()
