"""Real-Tk regression checks for source and DPI-specific scale images."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import tkwin11 as ui


ui.enable_dpi_awareness()


class CopyRecorder:
    def __init__(self, tkapp, image):
        self.tkapp = tkapp
        self.image = str(image)
        self.count = 0
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.tkapp, name)

    def call(self, *args):
        if len(args) > 1 and str(args[0]) == self.image and args[1] == 'copy':
            self.count += 1
            if self.fail:
                raise tk.TclError('injected copy failure')
        return self.tkapp.call(*args)


class ScaleDpiDirtyTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry('640x400+80+80')
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        ui.apply_theme(self.root)
        self.widget = ttk.Scale(self.root, from_=0, to=1, length=500)
        self.widget.pack()
        self.root.update()
        self.controller = self.widget._tkwin11_scale
        self.controller.position_animator.cancel()
        self.controller.animator.cancel()
        self.resources = self.controller.resources
        self.assertFalse(self.errors)

    def pixels(self, image):
        return self.root.tk.call(str(image), 'data', '-format', 'png')

    def draw(self, value):
        self.controller.visual = value
        self.controller.draw()

    def force_draw(self):
        self.controller._rendered_key = None
        self.controller.draw()

    def adjacent_values(self, factor=2):
        c = self.controller
        vertical = str(self.widget.cget('orient')) == 'vertical'
        ratio = self.resources.window_dpi(self.root) / self.resources.base_dpi
        length = max(round(24*c.scale), round((self.widget.winfo_height() if vertical else self.widget.winfo_width())/ratio))
        def position(value, scale):
            margin = round(12*c.scale*scale)
            extent = max(1, round(length*scale))
            return round(margin + (max(margin, extent-margin)-margin)*value)
        previous = 0.
        for i in range(1, 10001):
            current = i / 10000
            if position(previous, 1) == position(current, 1) and position(previous, factor) != position(current, factor):
                return previous, current
            previous = current
        self.fail('No suitable adjacent positions')

    def test_existing_dpi_view_updates_at_subpixel_boundary(self):
        first, second = self.adjacent_values()
        self.draw(first)
        target = self.resources.image(self.controller.track_image, self.resources.base_dpi*2)
        before = self.pixels(target)
        self.draw(second)
        actual = self.pixels(target)
        self.force_draw()
        expected = self.pixels(target)
        self.assertNotEqual(before, expected)
        self.assertEqual(actual, expected)

    def test_future_dpi_view_uses_latest_continuous_value(self):
        first, second = self.adjacent_values()
        self.draw(first)
        self.draw(second)
        target = self.resources.image(self.controller.track_image, self.resources.base_dpi*2)
        actual = self.pixels(target)
        self.force_draw()
        self.assertEqual(actual, self.pixels(target))

    def test_vertical_and_multiple_retained_dpi_views(self):
        self.widget.configure(orient='vertical', length=300)
        self.root.update()
        self.controller.position_animator.cancel()
        self.controller.animator.cancel()
        first, second = self.adjacent_values()
        self.draw(first)
        targets = [self.resources.image(self.controller.track_image, round(self.resources.base_dpi*r)) for r in (1.25, 1.5, 2)]
        self.draw(second)
        actual = [self.pixels(target) for target in targets]
        self.force_draw()
        self.assertEqual(actual, [self.pixels(target) for target in targets])

    def test_identical_pixels_still_skip_copy(self):
        self.draw(.5)
        self.resources.image(self.controller.track_image, self.resources.base_dpi*2)
        self.draw(.5)  # establish the key for both views
        recorder = CopyRecorder(self.widget.tk, self.controller.track_image)
        with patch.object(self.widget, 'tk', recorder):
            for value in [.5]*30 + [.500000001]:
                self.draw(value)
        self.assertEqual(recorder.count, 0)

    def test_failed_copy_is_retried(self):
        self.draw(0)
        recorder = CopyRecorder(self.widget.tk, self.controller.track_image)
        with patch.object(self.widget, 'tk', recorder):
            recorder.fail = True
            with self.assertRaises(tk.TclError):
                self.draw(1)
            recorder.fail = False
            self.draw(1)
        self.assertEqual(recorder.count, 2)
        actual = self.pixels(self.controller.track_image)
        self.force_draw()
        self.assertEqual(actual, self.pixels(self.controller.track_image))

    def test_state_and_size_changes_match_forced_render(self):
        for orientation in ('horizontal', 'vertical'):
            for limits in ((0, 1), (1, 0)):
                self.widget.configure(orient=orientation, from_=limits[0], to=limits[1])
                for length in (180, 300):
                    self.widget.configure(length=length)
                    self.root.update()
                    self.controller.position_animator.cancel()
                    self.controller.animator.cancel()
                    for state in (('!disabled', '!focus'), ('!disabled', 'focus'), ('disabled',)):
                        self.widget.state(state)
                        self.controller.keyboard = True
                        for radius in (4.5, 6, 6.01, 7):
                            self.controller.radius = radius
                            for value in (0, .25, 1, 0):
                                self.draw(value)
                                targets = [self.controller.track_image, self.resources.image(self.controller.track_image, self.resources.base_dpi*2)]
                                actual = [self.pixels(target) for target in targets]
                                self.force_draw()
                                self.assertEqual(actual, [self.pixels(target) for target in targets])
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
