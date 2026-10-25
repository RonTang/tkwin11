import tkinter as tk
from tkinter import ttk
import unittest

import tkwin11 as ui
from tk_support import TkTestCase
from tkwin11.slider import ScaleController


ui.enable_dpi_awareness()


def pixels(image):
    return [[image.get(x, y) for x in range(image.width())] for y in range(image.height())]


class CopyTk:
    def __init__(self, real, controller):
        self.real = real
        self.controller = controller
        self.copies = 0
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def splitlist(self, value):
        return self.real.splitlist(value)

    def call(self, *args):
        if (len(args) >= 2 and str(args[0]) == str(self.controller.track_image)
                and args[1] == 'copy'):
            self.copies += 1
            if self.fail:
                raise tk.TclError('controlled scale copy failure')
        return self.real.call(*args)


class ScaleDirtyCheckTests(TkTestCase):
    def setUp(self):
        super().setUp()
        ui.apply_theme(self.root)
        self.root.deiconify()
        self.widget = ttk.Scale(self.root, from_=0, to=100, length=240)
        self.widget.pack()
        self.controller = ScaleController(self.widget)
        self.root.update()
        self.assertGreater(self.widget.winfo_width(), 100)
        self.copy_tk = CopyTk(self.widget.tk, self.controller)
        self.widget.tk = self.copy_tk

    def draw(self, value, radius=6):
        self.controller.visual = value
        self.controller.radius = radius
        self.controller.draw()

    def test_subpixel_position_and_radius_match_forced_render(self):
        self.draw(25, 6.01)
        expected = pixels(self.controller.track_image)
        copies = self.copy_tk.copies
        self.draw(25.0001, 6.02)
        self.assertEqual(self.copy_tk.copies, copies)
        self.assertEqual(pixels(self.controller.track_image), expected)
        self.controller._rendered_key = None
        self.controller.draw()
        self.assertEqual(pixels(self.controller.track_image), expected)
        self.assertEqual(self.copy_tk.copies, copies+1)

    def test_distinct_position_and_aba_each_repaint(self):
        self.draw(25)
        self.draw(50)
        self.draw(25)
        self.assertEqual(self.copy_tk.copies, 3)

    def test_state_and_orientation_match_forced_render(self):
        cases = [
            (30, 6, False, [], 'horizontal'),
            (60, 6.5, True, ['focus'], 'horizontal'),
            (80, 6, False, ['disabled', '!focus'], 'horizontal'),
            (40, 7, False, ['!disabled'], 'vertical'),
        ]
        for value, radius, keyboard, states, orient in cases:
            with self.subTest(value=value, states=states, orient=orient):
                self.widget.configure(orient=orient)
                self.widget.state(states)
                self.controller.keyboard = keyboard
                self.controller._rendered_key = None
                self.draw(value, radius)
                expected = pixels(self.controller.track_image)
                copies = self.copy_tk.copies
                self.controller.draw()
                self.assertEqual(self.copy_tk.copies, copies)
                self.controller._rendered_key = None
                self.controller.draw()
                self.assertEqual(pixels(self.controller.track_image), expected)

    def test_geometry_change_repaints(self):
        self.draw(25)
        copies = self.copy_tk.copies
        self.widget.configure(length=320)
        self.root.update_idletasks()
        self.controller.draw()
        self.assertEqual(self.copy_tk.copies, copies+1)

    def test_two_controllers_each_initialize_their_slot(self):
        self.draw(25)
        second_widget = ttk.Scale(self.root, from_=0, to=100, length=240)
        second_widget.pack(fill='x')
        second = ScaleController(second_widget)
        self.root.update()
        self.assertEqual(second_widget.winfo_width(), self.widget.winfo_width())
        self.assertIsNot(self.controller.slot, second.slot)
        second.visual = 25
        second.radius = 6
        ScaleController.draw(second)
        self.assertEqual(pixels(second.track_image), pixels(self.controller.track_image))

    def test_copy_failure_preserves_key_and_allows_retry(self):
        self.draw(25)
        previous = self.controller._rendered_key
        expected = pixels(self.controller.track_image)
        self.copy_tk.fail = True
        with self.assertRaises(tk.TclError):
            self.draw(50)
        self.assertEqual(self.controller._rendered_key, previous)
        self.assertEqual(pixels(self.controller.track_image), expected)
        self.copy_tk.fail = False
        self.controller.draw()
        self.assertNotEqual(self.controller._rendered_key, previous)
        self.assertNotEqual(pixels(self.controller.track_image), expected)


if __name__ == '__main__':
    unittest.main()
