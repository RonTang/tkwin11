import tkinter as tk
from tkinter import ttk
import unittest

import tkwin11 as ui
from tk_support import TkTestCase
from tkwin11.core import PALETTE
from tkwin11.switches import attach_switch, frame


ui.enable_dpi_awareness()


def pixels(image):
    return [[image.get(x, y) for x in range(image.width())] for y in range(image.height())]


class CopyTk:
    def __init__(self, real, slot):
        self.real = real
        self.slot = str(slot)
        self.copies = 0
        self.fail = False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def splitlist(self, value):
        return self.real.splitlist(value)

    def call(self, *args):
        if len(args) >= 2 and str(args[0]) == self.slot and args[1] == 'copy':
            self.copies += 1
            if self.fail:
                raise tk.TclError('controlled copy failure')
        return self.real.call(*args)


class SwitchDirtyCheckTests(TkTestCase):
    def setUp(self):
        super().setUp()
        ui.apply_theme(self.root)
        self.widget = ttk.Checkbutton(self.root, style='Switch.TCheckbutton')
        self.controller = attach_switch(self.widget)
        self.copy_tk = CopyTk(self.controller.tk, self.controller.slot['image'])
        self.controller.tk = self.copy_tk

    def test_same_frame_draws_only_first_copy_and_aba_copies_again(self):
        for _ in range(60):
            self.controller.draw(0)
        self.assertEqual(self.copy_tk.copies, 0)
        self.controller.draw(1)
        self.controller.draw(0)
        self.assertEqual(self.copy_tk.copies, 2)

    def test_state_changes_and_quantized_position_match_expected_pixels(self):
        original_accent = PALETTE['accent']
        self.addCleanup(PALETTE.__setitem__, 'accent', original_accent)
        cases = [
            (0, 0, 0, [], False, original_accent),
            (.26, 0, 0, [], False, original_accent),
            (.261, .5, .25, [], False, original_accent),
            (.5, 1, 1, ['focus'], True, original_accent),
            (1, 0, 0, ['disabled'], False, original_accent),
            (.5, 0, 0, ['!disabled', '!focus'], False, '#0078D4'),
        ]
        for position, hover, press, states, keyboard, accent in cases:
            with self.subTest(position=position, states=states, accent=accent):
                PALETTE['accent'] = accent
                self.controller.hover_amount = hover
                self.controller.press_amount = press
                self.controller.native('state', states)
                self.root._switch_keyboard_focus = keyboard
                self.controller.draw(position)
                expected = frame(
                    self.root, max(0, min(12, round(position*12))),
                    disabled='disabled' in states,
                    focus='focus' in states and keyboard,
                    hover_amount=hover, press_amount=press,
                )
                self.assertEqual(pixels(self.controller.slot['image']), pixels(expected))

    def test_two_controllers_each_initialize_their_slot(self):
        second_widget = ttk.Checkbutton(self.root, style='Switch.TCheckbutton')
        second = attach_switch(second_widget)
        self.assertIsNot(self.controller.slot, second.slot)
        self.assertIs(self.controller._last_frame, second._last_frame)
        self.assertEqual(pixels(self.controller.slot['image']), pixels(frame(self.root, 0)))
        self.assertEqual(pixels(second.slot['image']), pixels(frame(self.root, 0)))

    def test_copy_failure_preserves_identity_and_allows_retry(self):
        previous = self.controller._last_frame
        self.copy_tk.fail = True
        with self.assertRaises(tk.TclError):
            self.controller.draw(1)
        self.assertIs(self.controller._last_frame, previous)
        self.copy_tk.fail = False
        self.controller.draw(1)
        self.assertIs(self.controller._last_frame, frame(self.root, 12))
        self.assertEqual(pixels(self.controller.slot['image']), pixels(frame(self.root, 12)))


if __name__ == '__main__':
    unittest.main()
