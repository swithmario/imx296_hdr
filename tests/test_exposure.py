import unittest

from rpicam_radiance.exposure import build_bracket, shutter_angle_to_exposure_us


class ExposureTests(unittest.TestCase):
    def test_shutter_angles_at_24_fps(self) -> None:
        expected = {
            1: 116,
            10: 1157,
            45: 5208,
            90: 10417,
            180: 20833,
        }
        actual = {
            angle: shutter_angle_to_exposure_us(angle, 24)
            for angle in expected
        }
        self.assertEqual(actual, expected)

    def test_bracket_summary(self) -> None:
        plan = build_bracket([1, 10, 45, 90, 180], 24)
        self.assertEqual(plan.integration_total_us, 37731)
        self.assertEqual(plan.angle_total_deg, 326)
        self.assertEqual(plan.raw_frames_per_reference_second, 120)
        # Span is calculated from the whole-microsecond values above.
        self.assertAlmostEqual(plan.exposure_span_stops, 7.48860, places=5)

    def test_angles_must_increase(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            build_bracket([10, 1], 24)

    def test_invalid_values(self) -> None:
        for angle in (0, -1, 361):
            with self.subTest(angle=angle):
                with self.assertRaises(ValueError):
                    shutter_angle_to_exposure_us(angle, 24)
        with self.assertRaises(ValueError):
            shutter_angle_to_exposure_us(180, 0)


if __name__ == "__main__":
    unittest.main()
