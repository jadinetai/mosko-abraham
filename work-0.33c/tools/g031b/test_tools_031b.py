"""ABRAHAM 0.31b hosted tests of the corrected tools (F-029-02, F-029-03). Label: SIMULATED.

  python -I -B -m unittest discover -s tools/g031b -p "test_tools_031b.py" -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


timing = load("timing_probe_031b", TOOLS / "g4" / "timing_probe.py")
diag = load("diag_reset_031b", TOOLS / "diag_reset.py")


class F02DiagResetLabel(unittest.TestCase):
    def test_t01_firmware_only_run(self):
        self.assertEqual(diag.run_label(None), "DIAGNOSTIC (firmware only, no Abraham code)")

    def test_t02_abraham_run_names_the_kernel(self):
        sha = "ca" * 32
        label = diag.run_label(sha)
        self.assertIn("Abraham staged", label)
        self.assertIn(sha, label)
        self.assertNotIn("firmware only", label)

    def test_t03_the_old_constant_is_not_used_for_abraham_runs(self):
        # 0.29: every run got this label, even --abraham ones (DIAG-RESET-0110).
        self.assertNotEqual(diag.run_label("00" * 32), diag.FIRMWARE_ONLY)


class F03TimingWindow(unittest.TestCase):
    # (host_ns, uptime_s, rest): one heartbeat per host second from t = 1 s to 10 s
    TICKS = [(s * 1_000_000_000, s, "") for s in range(1, 11)]

    def test_t04_window_keeps_only_ticks_inside(self):
        w = timing.select_window(self.TICKS, 3_000_000_000, 7_000_000_000)
        self.assertEqual([s for _, s, _ in w], [3, 4, 5, 6, 7], "both ends included, outside excluded")

    def test_t05_empty_and_full_windows(self):
        self.assertEqual(timing.select_window(self.TICKS, 20_000_000_000, 30_000_000_000), [])
        self.assertEqual(timing.select_window(self.TICKS, 0, 10**12), self.TICKS)

    def test_t06_the_old_expression_selected_everything(self):
        # The 0.29 line, verbatim in substance: `... <= t / 1e9 - 0 or True` is always true.
        wall_start, t0 = 1e9, 0  # a window start far after every tick
        old = [(t, s) for t, s, _ in self.TICKS if (wall_start - t0 / 1e9) <= t / 1e9 - 0 or True]
        self.assertEqual(len(old), len(self.TICKS))
        self.assertEqual(timing.select_window(self.TICKS, int(wall_start * 1e9), int(wall_start * 1e9) + 1), [])

    def test_t07_analysis_on_window_matches_hand_computation(self):
        a = timing.analyse(timing.select_window(self.TICKS, 2_000_000_000, 9_000_000_000))
        # ticks 2..9; the first (2) is skipped as partial: 3..9 = 6 guest s over 6 host s
        self.assertEqual((a["tick_lines"], a["guest_seconds"], a["host_seconds"], a["guest_per_host_ratio"]), (8, 6, 6.0, 1.0))
        self.assertTrue(a["consecutive"])

    def test_t08_too_few_ticks_reports_count_only(self):
        self.assertEqual(timing.analyse(self.TICKS[:2]), {"tick_lines": 2})


if __name__ == "__main__":
    unittest.main()
