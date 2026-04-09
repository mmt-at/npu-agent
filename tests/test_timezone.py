import unittest
from datetime import timedelta, timezone as fixed_timezone
from unittest import mock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from server.common import timezone as timezone_mod


class TimezoneTests(unittest.TestCase):
    def test_load_timezone_prefers_zoneinfo(self):
        timezone_mod._load_timezone.cache_clear()
        tz = timezone_mod.get_timezone("UTC")
        self.assertIsInstance(tz, ZoneInfo)
        self.assertEqual(str(tz), "UTC")

    def test_load_timezone_falls_back_when_zoneinfo_missing(self):
        timezone_mod._load_timezone.cache_clear()
        with mock.patch.object(
            timezone_mod,
            "ZoneInfo",
            side_effect=ZoneInfoNotFoundError("missing"),
        ):
            tz = timezone_mod._load_timezone("Asia/Shanghai")
        self.assertEqual(tz, fixed_timezone(timedelta(hours=8), "Asia/Shanghai"))


if __name__ == "__main__":
    unittest.main()
