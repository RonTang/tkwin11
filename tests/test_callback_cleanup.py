import tkinter as tk
from tkinter import ttk
import unittest

import tkwin11 as ui
from tkwin11.switches import attach_switch


ui.enable_dpi_awareness()


class CallbackCleanupTests(unittest.TestCase):
    def root(self):
        root = tk.Tk()
        root.withdraw()
        ui.apply_theme(root)
        return root

    def destroy(self, root):
        try:
            root.destroy()
        finally:
            if tk._default_root is root:
                tk._default_root = None

    def test_switch_destroy_cleans_class_callbacks(self):
        root = self.root()
        widget = ttk.Checkbutton(root, style='Switch.TCheckbutton')
        controller = attach_switch(widget)
        controller.draw(.5)
        self.destroy(root)

    def test_switch_can_be_destroyed_before_root(self):
        root = self.root()
        widget = ttk.Checkbutton(root, style='Switch.TCheckbutton')
        attach_switch(widget)
        widget.destroy()
        self.destroy(root)

    def test_input_dropdown_and_scale_destroy_cleanly(self):
        root = self.root()
        ttk.Entry(root).pack()
        ttk.Combobox(root, values=('one', 'two')).pack()
        ttk.Scale(root).pack()
        root.after(30, root.quit)
        root.mainloop()
        self.destroy(root)


if __name__ == '__main__':
    unittest.main()
