import unittest


from app.services.video_editor import decide_video_time_adjustment


class TestDecideVideoTimeAdjustment(unittest.TestCase):
    def test_none_when_close(self) -> None:
        mode, factor = decide_video_time_adjustment(src_duration=10.0, target_duration=10.15, epsilon_ratio=0.02)
        self.assertEqual(mode, "none")
        self.assertIsNone(factor)

    def test_trim_when_target_shorter_by_default(self) -> None:
        mode, factor = decide_video_time_adjustment(src_duration=10.0, target_duration=7.0)
        self.assertEqual(mode, "trim")
        self.assertIsNone(factor)

    def test_setpts_speedup_only_if_allowed(self) -> None:
        mode, factor = decide_video_time_adjustment(src_duration=10.0, target_duration=7.0, allow_speedup=True)
        self.assertEqual(mode, "setpts")
        self.assertIsNotNone(factor)
        self.assertLess(float(factor), 1.0)

    def test_setpts_slowdown_capped(self) -> None:
        mode, factor = decide_video_time_adjustment(src_duration=10.0, target_duration=30.0, max_slowdown_factor=1.35)
        self.assertEqual(mode, "setpts")
        self.assertAlmostEqual(float(factor), 1.35, places=6)

    def test_invalid_durations_raise(self) -> None:
        with self.assertRaises(ValueError):
            decide_video_time_adjustment(src_duration=0.0, target_duration=10.0)
        with self.assertRaises(ValueError):
            decide_video_time_adjustment(src_duration=10.0, target_duration=0.0)


if __name__ == "__main__":
    unittest.main()

