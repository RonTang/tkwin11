import tkinter as tk
from tkinter import ttk

import tkwin11 as ui
from tk_support import TkTestCase
from tkwin11.core import icon
from tkwin11.switches import attach_switch, frame


ui.enable_dpi_awareness()


def pixels(image):
    return [[image.get(x, y) for x in range(image.width())] for y in range(image.height())]


class SwitchTests(TkTestCase):
    def setUp(self):
        super().setUp()
        ui.apply_theme(self.root)

    def controller(self):
        widget = ttk.Checkbutton(self.root, style='Switch.TCheckbutton')
        return widget, attach_switch(widget)

    def test_static_faces_and_cache_identity(self):
        off = frame(self.root, 0)
        on = frame(self.root, 12)
        self.assertIs(off, frame(self.root, 0))
        self.assertIs(on, frame(self.root, 12))
        self.assertIsNot(off, on)
        self.assertEqual((off.width(), off.height()), (on.width(), on.height()))
        layout = ttk.Style(self.root).layout('Switch.TCheckbutton')
        self.assertIn('Fluent.Switch.indicator', str(layout))
        spec = self.root._dpi_resources.elements['Fluent.Switch.indicator']
        self.assertEqual(spec[0], 'image')
        self.assertEqual(str(spec[1]).split()[0], str(off))
        self.assertIn(str(on), str(spec[1]))

    def test_feedback_quantization_and_disabled_cache_keys(self):
        base = frame(self.root, 6, hover_amount=.24, press_amount=.24)
        self.assertIs(base, frame(self.root, 6, hover_amount=.26, press_amount=.26))
        self.assertIsNot(base, frame(self.root, 6, hover_amount=.5, press_amount=.24))
        disabled = frame(self.root, 6, disabled=True)
        self.assertIs(disabled, frame(self.root, 6, hover=True, pressed=True, disabled=True))

    def test_factory_registration_copy_propagation_and_ratios(self):
        source = frame(self.root, 0)
        resources = self.root._dpi_resources
        self.assertIn(str(source), resources.image_factories)
        factory = resources.image_factories[str(source)]
        for ratio in (1, 1.5, 2):
            rebuilt = factory(ratio)
            self.assertEqual(rebuilt.width(), max(1, round(source.width() * ratio)))
            self.assertEqual(rebuilt.height(), max(1, round(source.height() * ratio)))
        copied = tk.PhotoImage(master=self.root)
        self.root.tk.call(str(copied), 'copy', str(source))
        self.assertIs(resources.image_factories[str(copied)], factory)

    def test_slot_pixels_match_current_quantized_state(self):
        widget, controller = self.controller()
        cases = [
            (0, 0, 0, [], False),
            (.26, .5, .25, [], False),
            (.5, 1, 1, ['focus'], True),
            (1, 0, 0, ['disabled'], False),
        ]
        for position, hover, press, states, keyboard in cases:
            with self.subTest(position=position, states=states):
                controller.hover_amount = hover
                controller.press_amount = press
                controller.native('state', states)
                self.root._switch_keyboard_focus = keyboard
                controller.draw(position)
                expected = frame(
                    self.root, round(position * 12),
                    disabled='disabled' in states,
                    focus='focus' in states and keyboard,
                    hover_amount=hover, press_amount=press,
                )
                self.assertEqual(pixels(controller.slot['image']), pixels(expected))
        widget.destroy()

    def test_disabled_state_clears_feedback_and_reaches_target(self):
        self.root.motion_enabled = False
        variable = tk.BooleanVar(self.root, value=False)
        widget = ttk.Checkbutton(self.root, variable=variable, style='Switch.TCheckbutton')
        controller = attach_switch(widget)
        variable.set(True)
        self.pump()
        self.assertEqual(controller.position, 1)
        controller.hover_amount = controller.press_amount = 1
        widget.state(['disabled'])
        self.assertEqual(controller.hover_amount, 0)
        self.assertEqual(controller.press_amount, 0)
        self.assertEqual(controller.position, 1)
        widget.destroy()

    def test_two_controllers_have_independent_slots(self):
        first, first_controller = self.controller()
        second, second_controller = self.controller()
        self.assertIsNot(first_controller.slot, second_controller.slot)
        first_controller.draw(1)
        second_controller.draw(0)
        self.assertEqual(pixels(first_controller.slot['image']), pixels(frame(self.root, 12)))
        self.assertEqual(pixels(second_controller.slot['image']), pixels(frame(self.root, 0)))
        first.destroy()
        second.destroy()

    def test_icon_cache_uses_pixel_identity_not_background(self):
        first = icon(self.root, 'edit', 16, color='#606060', background='#EEF5F9')
        second = icon(self.root, 'edit', 16, color='#606060', background='#E4EBF0')
        self.assertIs(second, first)
        factory = self.root._dpi_resources.image_factories[str(first)]
        self.assertEqual(factory.cache_key, ('icon', 'edit', 16, '#606060'))
        scaled = factory(1.5)
        expected = icon(self.root, 'edit', 24, color='#606060', background='#FDFEFE')
        self.assertEqual(pixels(scaled), pixels(expected))
        for image in (scaled, expected):
            for y in range(image.height()):
                for x in range(image.width()):
                    self.assertEqual(bool(image.tk.call(image, 'transparency', 'get', x, y)),
                                     bool(expected.tk.call(expected, 'transparency', 'get', x, y)))

    def test_root_destroy_cleans_switch_callbacks(self):
        widget, controller = self.controller()
        controller.draw(.5)
        self.root.destroy()
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
