import unittest

from tkwin11.motion import blend, ease


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


if __name__ == '__main__':
    unittest.main()
