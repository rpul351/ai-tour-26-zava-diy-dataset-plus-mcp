"""Tests for period resolution: no database needed. Run with: python -m unittest tests.test_periods"""

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "python" / "mcp_server" / "sales_analysis"))
from sales_analysis_postgres import resolve_period  # noqa: E402

TODAY = date(2026, 10, 20)


class PeriodTests(unittest.TestCase):
    def test_this_month_is_compared_with_the_same_elapsed_days_of_last_month(self):
        r = resolve_period("this_month", TODAY, compare="previous_period")
        self.assertEqual((r["window"]["start"], r["window"]["end"], r["window"]["days"]), (date(2026, 10, 1), TODAY, 20))
        self.assertEqual((r["compare"]["start"], r["compare"]["end"], r["compare"]["days"]), (date(2026, 9, 1), date(2026, 9, 20), 20))

    def test_this_season_and_its_comparison_always_have_the_same_length(self):
        for compare in ("previous_period", "same_period_last_year"):
            r = resolve_period("this_season", TODAY, compare=compare)
            self.assertEqual(r["window"]["start"], date(2026, 9, 1))
            self.assertEqual(r["window"]["days"], r["compare"]["days"], compare)
        self.assertEqual(resolve_period("this_season", TODAY, compare="same_period_last_year")["compare"]["start"], date(2025, 9, 1))

    def test_winter_runs_across_the_new_year(self):
        r = resolve_period("this_season", date(2026, 1, 15), compare="previous_period")
        self.assertEqual(r["window"]["start"], date(2025, 12, 1))
        self.assertEqual(r["compare"]["start"], date(2025, 9, 1))

    def test_a_finished_period_is_compared_with_the_whole_previous_period(self):
        r = resolve_period("last_month", TODAY, compare="previous_period")
        self.assertEqual((r["window"]["start"], r["window"]["end"]), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual((r["compare"]["start"], r["compare"]["end"]), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_month_end_and_leap_day_do_not_break(self):
        r = resolve_period("this_month", date(2026, 3, 31), compare="previous_period")
        self.assertEqual(r["compare"]["end"], date(2026, 2, 28))
        r = resolve_period("custom", TODAY, date(2024, 2, 29), date(2024, 3, 10), "same_period_last_year")
        self.assertEqual(r["window"]["days"], r["compare"]["days"])

    def test_rolling_windows_compare_with_the_days_just_before(self):
        r = resolve_period("last_7_days", TODAY, compare="previous_period")
        self.assertEqual((r["window"]["start"], r["compare"]["end"]), (date(2026, 10, 14), date(2026, 10, 13)))

    def test_the_future_is_never_included_and_bad_input_is_refused_in_words(self):
        self.assertEqual(resolve_period("custom", TODAY, date(2026, 10, 1), date(2026, 12, 31))["window"]["end"], TODAY)
        with self.assertRaisesRegex(ValueError, "period must be one of"):
            resolve_period("next_month", TODAY)
        with self.assertRaisesRegex(ValueError, "custom needs"):
            resolve_period("custom", TODAY)
        with self.assertRaisesRegex(ValueError, "starts after today"):
            resolve_period("custom", TODAY, date(2027, 1, 1), date(2027, 2, 1))


if __name__ == "__main__":
    unittest.main()
