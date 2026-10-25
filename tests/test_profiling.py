import tkinter as tk
from tkinter import ttk

import tkwin11 as ui
from tk_support import TkTestCase
from tkwin11 import profiling
from tkwin11.motion import Tween
from tkwin11.switches import attach_switch, frame


class ProfilingTests(TkTestCase):
    def setUp(self):
        super().setUp()
        self.previous = profiling._ENABLED
        profiling._ENABLED = True
        self.addCleanup(setattr, profiling, '_ENABLED', self.previous)

    def themed_root(self):
        ui.apply_theme(self.root)
        profiling.snapshot(self.root, reset=True)

    def test_disabled_profile_has_no_state_or_samples(self):
        profiling._ENABLED = False
        self.assertIsNone(profiling.state(self.root))
        frame(self.root, 0)
        self.assertIsNone(profiling.snapshot(self.root))
        self.assertFalse(hasattr(self.root, '_tkwin11_profile'))

    def test_cold_frame_stages_hit_count_and_reset(self):
        self.themed_root()
        frame(self.root, 6, hover_amount=.5)
        frame(self.root, 6, hover_amount=.5)
        result = profiling.snapshot(self.root)
        self.assertEqual(result['counters']['frame_cold_count'], 1)
        self.assertEqual(result['counters']['frame_hit_count'], 1)
        for name in ('frame_cold_ms', 'raster_pixels_ms', 'raster_png_ms',
                     'raster_photo_ms', 'frame_other_ms'):
            self.assertEqual(len(result['samples'][name]), 1, name)
            self.assertGreaterEqual(result['samples'][name][0], 0)
        stages = sum(result['samples'][name][0] for name in
                     ('raster_pixels_ms', 'raster_png_ms', 'raster_photo_ms', 'frame_other_ms'))
        self.assertAlmostEqual(stages, result['samples']['frame_cold_ms'][0], delta=.01)
        profiling.snapshot(self.root, reset=True)
        reset = profiling.snapshot(self.root)
        self.assertEqual(reset['counters']['frame_cold_count'], 0)
        self.assertEqual(reset['samples']['frame_cold_ms'], [])

    def test_repeated_copy_count_is_per_controller(self):
        self.themed_root()
        widget = ttk.Checkbutton(self.root, style='Switch.TCheckbutton')
        controller = attach_switch(widget)
        for _ in range(60):
            controller.draw(0)
        result = profiling.snapshot(self.root)
        self.assertEqual(result['counters']['switch_copy_count'], 1)
        self.assertEqual(result['counters']['same_frame_copy_count'], 0)
        controller.draw(1)
        controller.draw(0)
        result = profiling.snapshot(self.root)
        self.assertEqual(result['counters']['switch_copy_count'], 3)
        self.assertEqual(result['counters']['same_frame_copy_count'], 0)

    def test_tween_timing_hidden_accounting_and_terminal_active(self):
        tween = Tween(self.root)
        done = []
        tween.start(0, 1, lambda value: None, duration=35, done=lambda: done.append(1))
        self.wait_until(lambda: done == [1])
        result = profiling.snapshot(self.root)
        counters = result['counters']
        self.assertEqual(done, [1])
        self.assertEqual(counters['active_tween_count_peak'], 1)
        self.assertEqual(counters['active_tween_count'], 0)
        self.assertEqual(counters['hidden_tween_start_count'], 1)
        self.assertEqual(counters['hidden_tween_sched_count'], len(result['samples']['sched_delay_ms']))
        self.assertEqual(len(result['samples']['gap_ms']), len(result['samples']['sched_delay_ms']))
        self.assertAlmostEqual(counters['tween_update_ms_total'],
                               sum(result['samples']['tween_update_ms']))
        self.assertEqual(result['visibility']['unmapped']['update_count'],
                         len(result['samples']['tween_update_ms']))
        self.assertGreater(counters['hidden_tween_update_ms'], 0)

    def test_cancel_stops_active_count(self):
        tween = Tween(self.root)
        tween.start(0, 1, lambda value: None, duration=100)
        tween.cancel()
        counters = profiling.snapshot(self.root)['counters']
        self.assertEqual(counters['active_tween_count_peak'], 1)
        self.assertEqual(counters['active_tween_count'], 0)

    def test_two_roots_have_independent_active_counts(self):
        second = tk.Tk()
        second.withdraw()
        self.addCleanup(self.destroy, second)
        done = []
        first = Tween(self.root)
        other = Tween(second)
        first.start(0, 1, lambda value: None, duration=35, done=lambda: done.append(1))
        other.start(0, 1, lambda value: None, duration=35, done=lambda: done.append(1))
        self.wait_until(lambda: len(done) == 2)
        for root in (self.root, second):
            counters = profiling.snapshot(root)['counters']
            self.assertEqual(counters['active_tween_count_peak'], 1)
            self.assertEqual(counters['active_tween_count'], 0)

    def test_dpi_factory_rebuild_is_counted_once(self):
        self.themed_root()
        source = frame(self.root, 0)
        resources = self.root._dpi_resources
        dpi = resources.base_dpi*2
        resources.image(str(source), dpi)
        resources.image(str(source), dpi)
        result = profiling.snapshot(self.root)
        self.assertEqual(result['counters']['dpi_rebuild_count'], 1)
        self.assertEqual(len(result['samples']['dpi_rebuild_ms']), 1)
        self.assertEqual(len(result['samples']['raster_pixels_ms']), 1)

    def test_visibility_categories(self):
        self.assertEqual(profiling.visibility(self.root), 'unmapped')
        owner = ttk.Frame(self.root, width=40, height=20)
        owner.pack()
        self.root.deiconify()
        self.pump(duration=.08)
        self.assertEqual(profiling.visibility(owner), 'visible')
        owner.place(x=-500, y=10)
        self.pump(duration=.05)
        self.assertEqual(profiling.visibility(owner), 'mapped_outside_viewport')
        owner.destroy()
        self.assertEqual(profiling.visibility(owner), 'destroyed')


if __name__ == '__main__':
    unittest.main()
