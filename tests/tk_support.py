import time
import tkinter as tk
import traceback
import unittest


class TkTestCase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = self.callback_error

    def tearDown(self):
        self.destroy(self.root)
        self.assertEqual(self.errors, [])
        super().tearDown()

    def callback_error(self, *args):
        self.errors.append(''.join(traceback.format_exception(*args)))

    def destroy(self, root):
        try:
            if root.winfo_exists():
                root.destroy()
        except tk.TclError:
            pass

    def pump(self, root=None, duration=.05):
        root = root or self.root
        root.after(max(1, round(duration * 1000)), root.quit)
        root.mainloop()
        self.assertEqual(self.errors, [])

    def wait_until(self, predicate, *, root=None, timeout=3):
        root = root or self.root
        deadline = time.monotonic() + timeout
        failure = []

        def check():
            if predicate():
                root.quit()
            elif time.monotonic() >= deadline:
                failure.append('condition was not met before timeout')
                root.quit()
            else:
                root.after(5, check)

        root.after(0, check)
        root.mainloop()
        self.assertEqual(self.errors, [])
        self.assertFalse(failure, failure[0] if failure else '')
