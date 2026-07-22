import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from export_still_bracket_tiffs import percentile_minmax  # noqa: E402
from render_colour_response import LUMA, coordinate_safe_tonemap  # noqa: E402


def srgb_to_linear(value: np.ndarray) -> np.ndarray:
    return np.where(
        value <= 0.04045,
        value / 12.92,
        ((value + 0.055) / 1.055) ** 2.4,
    )


class ColourCoordinateTests(unittest.TestCase):
    def test_percentile_minmax_ignores_extreme_tails(self) -> None:
        values = np.arange(10002, dtype=np.float32)
        values[0] = -1e9
        values[-1] = 1e9
        normalized, lower, upper = percentile_minmax(values, tail_percent=0.01)
        self.assertGreater(lower, -1e8)
        self.assertLess(upper, 1e8)
        self.assertEqual(float(normalized.min()), 0.0)
        self.assertEqual(float(normalized.max()), 1.0)

    def test_neutral_axis_stays_neutral(self) -> None:
        rgb = np.array([[[0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1e6, 1e6, 1e6]]])
        output = coordinate_safe_tonemap(rgb, 1000.0)
        self.assertTrue(np.all(np.isfinite(output)))
        np.testing.assert_allclose(output[..., 0], output[..., 1], atol=1e-7)
        np.testing.assert_allclose(output[..., 1], output[..., 2], atol=1e-7)

    def test_chroma_direction_is_preserved_inside_gamut(self) -> None:
        rgb = np.array([[[4000.0, 1000.0, 8000.0]]])
        output = srgb_to_linear(coordinate_safe_tonemap(rgb, 2000.0))[0, 0]
        input_y = float(rgb[0, 0] @ LUMA)
        output_y = float(output @ LUMA)
        input_direction = rgb[0, 0] - input_y
        output_direction = output - output_y
        cosine = float(
            input_direction @ output_direction
            / (np.linalg.norm(input_direction) * np.linalg.norm(output_direction))
        )
        self.assertAlmostEqual(cosine, 1.0, places=6)
        self.assertGreaterEqual(float(output.min()), 0.0)
        self.assertLessEqual(float(output.max()), 1.0)


if __name__ == "__main__":
    unittest.main()
