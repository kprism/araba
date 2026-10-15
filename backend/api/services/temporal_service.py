import re
from datetime import datetime
from zoneinfo import ZoneInfo


SEOUL_TZ = ZoneInfo("Asia/Seoul")
DAY_NAMES = (
    "월요일",
    "화요일",
    "수요일",
    "목요일",
    "금요일",
    "토요일",
    "일요일",
)
DAY_SHORT = {
    "월요일": "월",
    "화요일": "화",
    "수요일": "수",
    "목요일": "목",
    "금요일": "금",
    "토요일": "토",
    "일요일": "일",
}
DAY_ENGLISH = {
    "월요일": ("monday", "mon"),
    "화요일": ("tuesday", "tue"),
    "수요일": ("wednesday", "wed"),
    "목요일": ("thursday", "thu"),
    "금요일": ("friday", "fri"),
    "토요일": ("saturday", "sat"),
    "일요일": ("sunday", "sun"),
}


def seoul_now(now=None):
    if now is None:
        return datetime.now(SEOUL_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=SEOUL_TZ)
    return now.astimezone(SEOUL_TZ)


def current_time_context(now=None):
    local = seoul_now(now)
    return {
        "timezone": "Asia/Seoul",
        "iso": local.isoformat(),
        "date": local.date().isoformat(),
        "weekday": DAY_NAMES[local.weekday()],
        "hour": local.hour,
        "minute": local.minute,
        "minute_of_day": local.hour * 60 + local.minute,
    }


def _text(value):
    return str(value or "").strip()


def _naver(business):
    value = business.get("naver")
    return dict(value) if isinstance(value, dict) else {}


def _google(business):
    value = business.get("google_places")
    return dict(value) if isinstance(value, dict) else {}


def _hours_lines(business):
    google = _google(business)
    if google.get("matched") is True:
        for key in (
            "current_opening_hours",
            "regular_opening_hours",
        ):
            value = google.get(key)
            if isinstance(value, list) and value:
                return [
                    _text(item)
                    for item in value
                    if _text(item)
                ], "google_places"

    naver = _naver(business)
    # Identity matched AND detailed page inspected are required for factual
    # operating hours. Never trust an unrelated search snippet.
    if naver.get("matched") is not True or naver.get("page_checked") is not True:
        return [], "opening_hours_unverified"

    raw = naver.get("opening_hours")
    if isinstance(raw, list) and raw:
        return [
            _text(item)
            for item in raw
            if _text(item)
        ], "naver_verified_page"

    return [], "opening_hours"


def _day_applies(text, target_day):
    compact = re.sub(r"\s+", "", text)
    lower = text.lower()
    short = DAY_SHORT[target_day]
    target_index = DAY_NAMES.index(target_day)

    if "매일" in compact or "daily" in lower:
        return True

    if target_day in text or f"{short}요일" in text:
        return True

    if re.search(
        rf"(?<![월화수목금토일]){short}(?![월화수목금토일])",
        compact,
    ):
        return True

    if any(
        re.search(rf"\b{re.escape(alias)}\b", lower)
        for alias in DAY_ENGLISH[target_day]
    ):
        return True
    # Schema.org hours may use "Mo-Fr" or "Mon-Fri".
    english_short = {
        "mo": 0, "mon": 0, "tu": 1, "tue": 1,
        "we": 2, "wed": 2, "th": 3, "thu": 3,
        "fr": 4, "fri": 4, "sa": 5, "sat": 5,
        "su": 6, "sun": 6,
    }
    english_range = re.search(
        r"\b(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)"
        r"\s*[-~–]\s*"
        r"(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)\b",
        lower,
    )
    if english_range:
        first = english_short[english_range.group(1)]
        last = english_short[english_range.group(2)]
        if first <= last:
            return first <= target_index <= last
        return target_index >= first or target_index <= last

    range_pattern = re.compile(
        r"([월화수목금토일])(?:요일)?\s*[~\-–]\s*"
        r"([월화수목금토일])(?:요일)?"
    )
    reverse = {
        value: index
        for index, value in enumerate(
            ["월", "화", "수", "목", "금", "토", "일"]
        )
    }
    for match in range_pattern.finditer(text):
        start = reverse[match.group(1)]
        end = reverse[match.group(2)]
        if start <= end:
            indices = set(range(start, end + 1))
        else:
            indices = set(range(start, 7)) | set(range(0, end + 1))
        if target_index in indices:
            return True

    if target_index in {5, 6} and "주말" in compact:
        return True

    if target_index <= 4 and "평일" in compact:
        return True

    return False


def _clock_tokens(text):
    """Extract 12/24-hour clock values without losing AM/PM modifiers."""
    pattern = re.compile(
        r"(?i)(?<![\da-z])(?:(오전|오후|am|pm)\s*)?"
        r"(\d{1,2})(?::(\d{2})|시(?:\s*(\d{1,2})분)?)"
        r"\s*(오전|오후|am|pm)?(?!\d)"
    )
    tokens = []
    for match in pattern.finditer(text):
        hour = int(match.group(2))
        minute = int(match.group(3) or match.group(4) or 0)
        period = (match.group(1) or match.group(5) or "").lower()
        if hour > 24 or minute >= 60 or (period and not 1 <= hour <= 12):
            continue
        if period in {"pm", "오후"} and hour < 12:
            hour += 12
        elif period in {"am", "오전"} and hour == 12:
            hour = 0
        if not period and hour == 24 and minute:
            continue
        tokens.append((hour * 60 + minute, period))
    return tokens


def _time_ranges(text):
    """Parse inclusive operating windows; keep source day separate."""
    compact = re.sub(r"\s+", "", str(text or ""))
    lower = compact.lower()
    if ("24시간" in compact or "24hours" in lower
            or "open24hours" in lower):
        return [(0, 24 * 60)]
    tokens = _clock_tokens(str(text or ""))
    ranges = []
    # Pair consecutive times. A daily split shift may contain two pairs.
    for index in range(0, len(tokens) - 1, 2):
        opening, open_period = tokens[index]
        closing, close_period = tokens[index + 1]
        if open_period in {"pm", "오후"} and not close_period and closing < 720:
            closing += 720
        if closing <= opening:
            closing += 24 * 60
        ranges.append((opening, closing))
    return ranges


def structured_business_hours(business):
    """Verified weekday / start / end records, never guessed from snippets.

    Google current periods take precedence over regular periods and textual
    descriptions. Verified Naver page hours are the fallback, not a rival
    set of contradictory hours.
    """
    google = _google(business)
    if google.get("matched") is True:
        for key, source in (
            ("current_periods", "google_places_current"),
            ("regular_periods", "google_places_regular"),
        ):
            raw = google.get(key)
            rows = []
            if not isinstance(raw, list):
                continue
            for period in raw:
                if not isinstance(period, dict):
                    continue
                start = period.get("open")
                close = period.get("close")
                if not isinstance(start, dict):
                    continue
                first_day = start.get("day")
                if not isinstance(first_day, int) or not 0 <= first_day <= 6:
                    continue
                opening = int(start.get("hour") or 0) * 60 + int(start.get("minute") or 0)
                if not 0 <= opening < 1440:
                    continue
                if isinstance(close, dict):
                    close_day = close.get("day")
                    if not isinstance(close_day, int) or not 0 <= close_day <= 6:
                        continue
                    closing = (
                        (close_day - first_day) % 7 * 1440
                        + int(close.get("hour") or 0) * 60
                        + int(close.get("minute") or 0)
                    )
                    if closing <= opening:
                        closing += 1440
                else:
                    # Google omits close for all-day, seven-day businesses.
                    opening, closing = 0, 1440
                weekday = DAY_NAMES[(first_day + 6) % 7]
                rows.append({
                    "weekday": weekday,
                    "start_time": f"{opening // 60:02d}:{opening % 60:02d}",
                    "end_time": f"{closing // 60:02d}:{closing % 60:02d}",
                    "start_minute": opening,
                    "end_minute": closing,
                    "source": source,
                })
            if rows:
                return rows

        for key, source in (
            ("current_opening_hours", "google_places_current"),
            ("regular_opening_hours", "google_places_regular"),
        ):
            raw = google.get(key)
            if not isinstance(raw, list):
                continue
            rows = _structured_hours_from_lines(raw, source)
            if rows:
                return rows

    naver = _naver(business)
    if naver.get("matched") is True and naver.get("page_checked") is True:
        raw = naver.get("opening_hours")
        if isinstance(raw, list):
            return _structured_hours_from_lines(raw, "naver_verified_page")
    return []


def _structured_hours_from_lines(lines, source):
    rows = []
    for text in lines:
        if not isinstance(text, str):
            continue
        applicable = [day for day in DAY_NAMES if _day_applies(text, day)]
        if not applicable:
            continue
        closed = _line_closed(text)
        ranges = [] if closed else _time_ranges(text)
        for day in applicable:
            if closed:
                rows.append({"weekday": day, "closed": True, "source": source})
            for opening, closing in ranges:
                rows.append({
                    "weekday": day,
                    "start_time": f"{opening // 60:02d}:{opening % 60:02d}",
                    "end_time": f"{closing // 60:02d}:{closing % 60:02d}",
                    "start_minute": opening,
                    "end_minute": closing,
                    "source": source,
                })
    return rows


def weekly_hours_table(business):
    """7-day evidence table. Unknown is not closed; split shifts are retained."""
    rows = structured_business_hours(business)
    table = []
    for weekday in DAY_NAMES:
        day_rows = [row for row in rows if row.get('weekday') == weekday]
        closed = any(row.get('closed') is True for row in day_rows)
        sessions = [
            {
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'source': row['source'],
            }
            for row in day_rows
            if 'start_time' in row and 'end_time' in row
        ]
        table.append({
            'weekday': weekday,
            'status': 'closed' if closed else ('open' if sessions else 'unknown'),
            'sessions': [] if closed else sessions,
            'source': day_rows[0].get('source') if day_rows else None,
        })
    return table

def _line_closed(text):
    lower = text.lower()
    return bool(
        re.search(
            r"휴무|휴점|정기휴무|closed|영업안함|운영안함",
            lower,
        )
    )


def _evaluate_lines(lines, local):
    target_day = DAY_NAMES[local.weekday()]
    previous_day = DAY_NAMES[(local.weekday() - 1) % 7]
    minute = local.hour * 60 + local.minute

    had_day_evidence = False

    for text in lines:
        if not _day_applies(text, target_day):
            continue
        had_day_evidence = True
        if _line_closed(text):
            return False, text

        ranges = _time_ranges(text)
        for opening, closing in ranges:
            if opening <= minute < min(closing, 24 * 60):
                return True, text

    # Overnight range that started on the previous calendar day.
    for text in lines:
        if not _day_applies(text, previous_day):
            continue
        if _line_closed(text):
            continue
        for opening, closing in _time_ranges(text):
            if closing <= 24 * 60:
                continue
            extended_minute = minute + 24 * 60
            if opening <= extended_minute < closing:
                return True, text

    if had_day_evidence:
        # A matching day line existed but no active time range matched.
        return False, None

    return None, None


def evaluate_business_now(business, now=None):
    local = seoul_now(now)
    google = _google(business)

    google_open = google.get("open_now")
    if isinstance(google_open, bool):
        is_open = google_open
        basis = "google_places.currentOpeningHours"
        evidence = google.get("open_now_evidence")
    else:
        lines, source = _hours_lines(business)
        if lines:
            is_open, evidence = _evaluate_lines(
                lines,
                local,
            )
        else:
            is_open = None
            evidence = None
        basis = source

    # User product rule: if the current KST time falls inside confirmed
    # business hours, treat the shop as currently orderable by hours.
    # This does not claim inventory/payment/order-channel confirmation.
    orderable = is_open if isinstance(is_open, bool) else None

    return {
        "timezone": "Asia/Seoul",
        "checked_at": local.isoformat(),
        "weekday": DAY_NAMES[local.weekday()],
        "is_open_now": is_open,
        "orderable_now": orderable,
        "basis": basis,
        "evidence": evidence,
        "scope": "business_hours",
    }


def annotate_business_now(business, now=None):
    item = dict(business)
    status = evaluate_business_now(item, now=now)
    item["structured_opening_hours"] = structured_business_hours(item)
    item["weekly_opening_hours"] = weekly_hours_table(item)
    item["current_status"] = status
    item["is_open_now"] = status["is_open_now"]
    item["orderable_now"] = status["orderable_now"]
    return item


def annotate_businesses_now(businesses, now=None):
    return [
        annotate_business_now(item, now=now)
        for item in businesses
        if isinstance(item, dict)
    ]
