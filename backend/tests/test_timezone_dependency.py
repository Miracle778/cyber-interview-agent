from datetime import datetime
from zoneinfo import TZPATH, ZoneInfo, reset_tzpath


def test_packaged_timezone_data_supports_windows_style_environment() -> None:
    original_tzpath = TZPATH
    try:
        reset_tzpath([])
        ZoneInfo.clear_cache()

        beijing = ZoneInfo("Asia/Shanghai")
        localized = datetime(2026, 1, 1, tzinfo=beijing)

        assert localized.utcoffset().total_seconds() == 8 * 60 * 60
    finally:
        reset_tzpath(original_tzpath)
        ZoneInfo.clear_cache()
