"""Real popup tests; ReportedMenu reproduces the issue's empty cget result."""
import tkinter as tk
from types import SimpleNamespace
import unittest

import tkwin11 as ui
from tkwin11.extras import MenuPopup


ui.enable_dpi_awareness()


class ReportedMenu(ui.ThemedMenu):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reported_underlines = {}

    def entrycget(self, index, option):
        number = self.index(index)
        if option == 'underline' and number in self.reported_underlines:
            return self.reported_underlines[number]
        return super().entrycget(index, option)


class MenuUnderlineTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry('400x300+80+80')
        self.root.motion_enabled = False
        ui.apply_theme(self.root)
        self.root.update()
        self.menu = ReportedMenu(self.root, tearoff=False)
        self.calls = []

    def add(self, label, underline=-1, state='normal'):
        self.menu.add_command(label=label, underline=underline, state=state,
                              command=lambda: self.calls.append(label))

    def popup(self):
        p = MenuPopup(self.root, self.menu, 180, 180)
        self.addCleanup(lambda: p.close(restore_focus=False) if not p._closed else None)
        return p

    def key(self, popup, char, state=0):
        popup.mnemonic(SimpleNamespace(char=char, state=state))

    def test_empty_underlines_open_and_prefix_only_selects(self):
        self.add('Alpha')
        self.add('Beta')
        self.menu.reported_underlines = {0: '', 1: ''}
        p = self.popup()
        self.assertEqual(int(p.rows[1][1][-1].cget('underline')), -1)
        self.key(p, 'b')
        self.assertEqual(p.cursor, 1)
        self.assertFalse(self.calls)
        self.assertFalse(p._closed)

    def test_explicit_zero_index_executes_once(self):
        self.add('Open', 0)
        p = self.popup()
        self.assertEqual(int(p.rows[0][1][-1].cget('underline')), 0)
        self.key(p, 'O')
        self.assertEqual(self.calls, ['Open'])
        self.assertTrue(p._closed)

    def test_prefix_does_not_execute_different_explicit_mnemonic(self):
        self.add('Open', 1)
        p = self.popup()
        self.key(p, 'o')
        self.assertFalse(self.calls)
        self.assertFalse(p._closed)
        self.key(p, 'p')
        self.assertEqual(self.calls, ['Open'])

    def test_duplicate_mnemonics_cycle_and_skip_disabled(self):
        self.add('Open', 0)
        self.add('Other', 0)
        self.add('Off', 0, state='disabled')
        p = self.popup()
        self.key(p, 'o')
        self.assertEqual(p.cursor, 1)
        self.key(p, 'o')
        self.assertEqual(p.cursor, 0)
        self.assertFalse(self.calls)

    def test_out_of_range_and_empty_labels_have_no_mnemonic(self):
        self.add('Alpha', 99)
        self.add('', 0)
        p = self.popup()
        self.assertEqual(int(p.rows[0][1][-1].cget('underline')), -1)
        self.assertEqual(int(p.rows[1][1][-1].cget('underline')), -1)
        self.key(p, 'a')
        self.assertFalse(self.calls)

    def test_control_key_does_not_activate(self):
        self.add('Open', 0)
        p = self.popup()
        self.key(p, 'o', 4)
        self.assertFalse(self.calls)

    def test_unique_cascade_mnemonic_opens_child(self):
        submenu = ui.ThemedMenu(self.menu, tearoff=False)
        submenu.add_command(label='CSV', underline=0)
        self.menu.add_cascade(label='Export', underline=0, menu=submenu)
        p = self.popup()
        self.key(p, 'e')
        self.assertIsNotNone(p.child_popup)
        self.assertFalse(p._closed)

    def test_checkbutton_and_radiobutton_keep_native_invoke(self):
        check = tk.BooleanVar(self.root, False)
        radio = tk.StringVar(self.root, 'old')
        self.menu.add_checkbutton(label='Show', underline=0, variable=check)
        self.menu.add_radiobutton(label='Name', underline=0, variable=radio, value='name')
        p = self.popup()
        self.key(p, 's')
        self.assertTrue(check.get())
        p = self.popup()
        self.key(p, 'n')
        self.assertEqual(radio.get(), 'name')


if __name__ == '__main__':
    unittest.main()
