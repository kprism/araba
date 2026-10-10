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

    raw = _naver(business).get("opening_hours")
    if isinstance(raw, list) and raw:
        return [
            _text(item)
            for item in raw
            if _text(item)
        ], "naver_or_web"

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


def _time_ranges(text):
    compact = re.sub(r"\s+", "", text)
    if "24시간" in compact or "24hours" in compact.lower():
        return [(0, 24 * 60)]

    ranges = []
    pattern = re.compile(
        r"(\d{1,2}):(\d{2})\s*[~\-–]\s*(\d{1,2}):(\d{2})"
    )
    for match in pattern.finditer(text):
        opening = int(match.group(1)) * 60 + int(match.group(2))
        closing = int(match.group(3)) * 60 + int(match.group(4))
        if not (
            0 <= opening <= 24 * 60
            and 0 <= closing <= 24 * 60
        ):
            continue
        if closing <= opening:
            closing += 24 * 60
        ranges.append((opening, closing))

    return ranges


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
