"""令和表記 → ISO 8601 (YYYY-MM-DD) への変換ユーティリティ。"""

import re

REIWA_START_YEAR = 2018  # 令和1年 = 2019年 なので 2018 + reiwa_year

_PATTERN = re.compile(r"令和(\d+)年(\d+)月(\d+)日")


def extract_date(text: str) -> str | None:
    """
    文字列中から最初に見つかった「令和X年Y月Z日」をISO日付文字列に変換する。
    見つからなければ None を返す。
    """
    m = _PATTERN.search(text)
    if not m:
        return None
    reiwa_year, month, day = (int(g) for g in m.groups())
    year = REIWA_START_YEAR + reiwa_year
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None
