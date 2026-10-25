import tkinter as tk
from tkinter import ttk
import unittest

from tk_support import TkTestCase
from tkwin11.motion import Tween, blend, ease


class MotionMathTests(unittest.TestCase):
    def test_ease_endpoints_are_exact(self):
        self.assertEqual(ease(0), 0)
        self.assertEqual(ease(1), 1)

    def test_ease_is_monotonic(self):
        values = [ease(index / 1000) for index in range(1001)]
        self.assertTrue(all(a <= b for a, b in zip(values, values[1:])))

    def test_blend_endpoints_and_midpoint(self):
        self.assertEqual(blend('#000000', '#ffffff', 0), '#000000')
        self.assertEqual(blend('#000000', '#ffffff', 1), '#ffffff')
        self.assertEqual(blend('#000000', '#ffffff', .5), '#808080')
        self.assertEqual(blend('#0067c0', '#1975c5', .5), '#0c6ec2')


class TweenTests(TkTestCase):
    def test_equal_endpoints_and_disabled_motion_finish_immediately(self):
        tween = Tween(self.root)
        updates = []
        done = []
        tween.start(2, 2, updates.append, done=lambda: done.append('equal'))
        self.root.motion_enabled = False
        tween.start(0, 1, updates.append, done=lambda: done.append('disabled'))
        self.assertEqual(updates, [2, 1])
        self.assertEqual(done, ['equal', 'disabled'])
        self.assertIsNone(tween.job)

    def test_cancel_prevents_later_updates_and_done(self):
        tween = Tween(self.root)
        updates = []
        done = []
        tween.start(0, 1, updates.append, duration=40, done=lambda: done.append(1))
        tween.cancel()
        count = len(updates)
        self.pump(duration=.08)
        self.assertEqual(len(updates), count)
        self.assertEqual(done, [])
        self.assertIsNone(tween.job)

    def test_restart_invalidates_old_animation(self):
        tween = Tween(self.root)
        done = []
        updates = []
        tween.start(0, 1, updates.append, duration=40, done=lambda: done.append('old'))
        tween.start(2, 3, updates.append, duration=40, done=lambda: done.append('new'))
        self.wait_until(lambda: done == ['new'])
        self.assertEqual(done, ['new'])
        self.assertEqual(updates[-1], 3)
        self.assertIsNone(tween.job)

    def test_update_can_cancel_without_done(self):
        tween = Tween(self.root)
        updates = []
        done = []

        def update(value):
            updates.append(value)
            tween.cancel()

        tween.start(0, 1, update, duration=40, done=lambda: done.append(1))
        self.pump(duration=.08)
        self.assertEqual(len(updates), 1)
        self.assertEqual(done, [])
        self.assertIsNone(tween.job)

    def test_update_can_restart_without_stale_done(self):
        tween = Tween(self.root)
        done = []
        updates = []

        def replacement(value):
            updates.append(value)

        def update(value):
            tween.start(5, 6, replacement, duration=30, done=lambda: done.append('new'))

        tween.start(0, 1, update, duration=40, done=lambda: done.append('old'))
        self.wait_until(lambda: done == ['new'])
        self.assertEqual(done, ['new'])
        self.assertEqual(updates[-1], 6)

    def test_done_can_restart(self):
        tween = Tween(self.root)
        done = []

        def first_done():
            done.append('first')
            tween.start(1, 2, lambda value: None, duration=30,
                        done=lambda: done.append('second'))

        tween.start(0, 1, lambda value: None, duration=30, done=first_done)
        self.wait_until(lambda: done == ['first', 'second'])
        self.assertIsNone(tween.job)

    def test_destroying_owner_cancels_animation(self):
        owner = ttk.Frame(self.root)
        tween = Tween(owner)
        updates = []
        tween.start(0, 1, updates.append, duration=100)
        owner.destroy()
        count = len(updates)
        self.pump(duration=.15)
        self.assertEqual(len(updates), count)
        self.assertFalse(tween.alive())
        self.assertIsNone(tween.job)

    def test_two_roots_have_independent_tweens(self):
        second = tk.Tk()
        second.withdraw()
        self.addCleanup(self.destroy, second)
        done = []
        first = Tween(self.root)
        other = Tween(second)
        first.start(0, 1, lambda value: None, duration=30, done=lambda: done.append('first'))
        other.start(0, 1, lambda value: None, duration=30, done=lambda: done.append('second'))
        self.wait_until(lambda: len(done) == 2)
        self.assertCountEqual(done, ['first', 'second'])
        self.assertIsNone(first.job)
        self.assertIsNone(other.job)


if __name__ == '__main__':
    unittest.main()
