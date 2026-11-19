import datetime as dt
import unittest
from unittest.mock import patch

import generate_widget as widget


class StatsTests(unittest.TestCase):
    def test_private_access_is_required(self):
        with patch.object(widget, "api", return_value=({"public_repos": 1}, {})):
            with self.assertRaisesRegex(RuntimeError, "Private contribution access"):
                widget.fetch_account("test")

    def test_missing_private_count_is_rejected(self):
        with patch.object(widget, "api", return_value=(
            {"public_repos": 1}, {"X-OAuth-Scopes": "read:user"}
        )):
            with self.assertRaisesRegex(RuntimeError, "owned_private_repos"):
                widget.fetch_account("test")

    def test_private_counts_and_all_account_years(self):
        account = {"login": "example", "public_repos": 2, "owned_private_repos": 23}
        viewer = {"viewer": {"login": "example", "createdAt": "2024-01-01T00:00:00Z"}}
        def calendar(date, count):
            return {"viewer": {"contributionsCollection": {"contributionCalendar": {
                "totalContributions": count,
                "weeks": [{"contributionDays": [
                    {"date": date, "contributionCount": count},
                ]}],
            }}}}
        responses = [viewer, calendar("2024-06-30", 3), calendar("2024-07-01", 4),
                     calendar("2025-06-30", 0), calendar("2025-12-31", 5),
                     calendar("2026-01-01", 6), calendar("2026-11-19", 7)]
        with patch.object(widget, "fetch_account", return_value=account), \
             patch.object(widget, "gql", side_effect=responses) as gql:
            stats = widget.fetch_stats("test", "example", dt.date(2026, 11, 19))
        self.assertEqual(stats["repositories"], 25)
        self.assertEqual(stats["contributions"], 25)
        self.assertEqual(stats["active_days"], 5)
        self.assertEqual(gql.call_count, 7)

    def test_wrong_account_is_rejected(self):
        with patch.object(widget, "fetch_account", return_value={"login": "other"}), \
             patch.object(widget, "gql", return_value={"viewer": {
                 "login": "other", "createdAt": "2024-01-01T00:00:00Z"
             }}):
            with self.assertRaisesRegex(RuntimeError, "expected example"):
                widget.fetch_stats("test", "example")

    def test_half_year_boundaries_include_leap_day_without_overlap(self):
        windows = list(widget.year_windows(2024, dt.date(2024, 12, 31)))
        dates = []
        for start, end in windows:
            dates.extend(start + dt.timedelta(days=n) for n in range((end - start).days + 1))
        self.assertEqual(len(dates), 366)
        self.assertEqual(len(set(dates)), 366)
        self.assertIn(dt.date(2024, 2, 29), dates)


if __name__ == "__main__":
    unittest.main()
