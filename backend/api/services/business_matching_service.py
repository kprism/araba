import re

from .temporal_service import evaluate_business_now


TIME_FIELDS = {"closing_time", "opening_time"}
RANK_OPERATORS = {"min", "max"}


def _text(value):
    return str(value or "").strip()


def _naver(business):
    value = business.get("naver")
    return dict(value) if isinstance(value, dict) else {}


def _time_to_minutes(value):
    text = _text(value)
    match = re.search(r"(\d{1,2})\s*:\s*(\d{2})", text)
    if not match:
        hour_match = re.search(r"(\d{1,2})\s*시", text)
        if not hour_match:
            return None
        hour = int(hour_match.group(1))
        minute = 0
    else:
        hour = int(match.group(1))
        minute = int(match.group(2))

    if hour < 0 or hour > 35 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _opening_ranges(business):
    raw = _naver(business).get("opening_hours")
    if not isinstance(raw, list):
        return []

    ranges = []
    pattern = re.compile(
        r"(\d{1,2}):(\d{2})\s*[~\-–]\s*(\d{1,2}):(\d{2})"
    )
    for item in raw:
        for match in pattern.finditer(_text(item)):
            opening = int(match.group(1)) * 60 + int(match.group(2))
            closing = int(match.group(3)) * 60 + int(match.group(4))
            if closing <= opening:
                closing += 24 * 60
            ranges.append((opening, closing, _text(item)))
    return ranges


DAY_ORDER = {
    "월요일": 0,
    "화요일": 1,
    "수요일": 2,
    "목요일": 3,
    "금요일": 4,
    "토요일": 5,
    "일요일": 6,
}

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


def _canonical_day(value):
    text = _text(value).lower()
    for day, short in DAY_SHORT.items():
        if day in text or f"{short}요일" in text:
            return day
        if text == short:
            return day
        if any(
            text == alias
            for alias in DAY_ENGLISH[day]
        ):
            return day
    return None


def _day_in_korean_range(text, target_day):
    target_index = DAY_ORDER[target_day]
    pattern = re.compile(
        r"([월화수목금토일])(?:요일)?\s*[~\-–]\s*"
        r"([월화수목금토일])(?:요일)?"
    )
    reverse = {
        value: DAY_ORDER[day]
        for day, value in DAY_SHORT.items()
    }
    for match in pattern.finditer(text):
        start = reverse[match.group(1)]
        end = reverse[match.group(2)]
        if start <= end:
            indices = range(start, end + 1)
        else:
            indices = list(range(start, 7)) + list(
                range(0, end + 1)
            )
        if target_index in indices:
            return True
    return False


def _opening_day_state(business, target):
    target_day = _canonical_day(target)
    if target_day is None:
        return None

    naver_hours = _naver(business).get("opening_hours")
    google = business.get("google_places")
    google = google if isinstance(google, dict) else {}
    # Only use hours attached to the identity-matched business.
    raw = [
        *(naver_hours if isinstance(naver_hours, list) else []),
        *(
            google.get("current_opening_hours")
            if isinstance(google.get("current_opening_hours"), list)
            else []
        ),
        *(
            google.get("regular_opening_hours")
            if isinstance(google.get("regular_opening_hours"), list)
            else []
        ),
    ]
    if not raw:
        return None

    short = DAY_SHORT[target_day]
    english = DAY_ENGLISH[target_day]
    target_index = DAY_ORDER[target_day]

    for item in raw:
        text = _text(item)
        if not text:
            continue
        lower = text.lower()
        compact = re.sub(r"\s+", "", text)

        applies = False
        if "매일" in compact or "daily" in lower:
            applies = True
        if target_day in text or f"{short}요일" in text:
            applies = True
        if re.search(
            rf"(?<![월화수목금토일]){short}(?![월화수목금토일])",
            compact,
        ):
            applies = True
        if any(
            re.search(
                rf"\b{re.escape(alias)}\b",
                lower,
            )
            for alias in english
        ):
            applies = True
        if _day_in_korean_range(
            text,
            target_day,
        ):
            applies = True

        if (
            target_index in {5, 6}
            and "주말" in compact
        ):
            applies = True

        if not applies:
            continue

        closed = bool(
            re.search(
                r"휴무|휴점|정기휴무|closed|영업안함|운영안함",
                lower,
            )
        )
        if closed:
            return False

        if (
            re.search(
                r"\d{1,2}:\d{2}",
                text,
            )
            or "24시간" in compact
            or "영업" in compact
            or "운영" in compact
        ):
            return True

    return None


def _price_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)

    text = _text(value).replace(",", "")
    if not text:
        return None

    manwon = re.search(r"(\d+(?:\.\d+)?)\s*만\s*원?", text)
    if manwon:
        return float(manwon.group(1)) * 10000

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def _prices(business):
    verified = business.get("verified_total_price")
    verified_number = _price_number(verified)
    if verified_number is not None:
        return [(verified_number, "verified_total_price", _text(verified))]

    raw = _naver(business).get("prices")
    if not isinstance(raw, list):
        return []

    values = []
    for item in raw:
        if isinstance(item, dict):
            number = _price_number(item.get("price"))
            label = _text(item.get("name")) or "가격"
            raw_value = _text(item.get("price"))
        else:
            number = _price_number(item)
            label = "가격"
            raw_value = _text(item)
        if number is not None:
            values.append((number, label, raw_value))
    return values


def _distance_value(business):
    for key in ("distance_m", "distance"):
        raw = business.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return float(raw)
        text = _text(raw).replace(",", "")
        if text:
            try:
                return float(text)
            except ValueError:
                pass
    return None


def _criterion_value(business, criterion):
    field = _text(criterion.get("field"))

    if field == "parking_available":
        value = _naver(business).get("parking_available")
        return (
            value if isinstance(value, bool) else None,
            "naver_or_openai_web",
        )

    if field in TIME_FIELDS:
        ranges = _opening_ranges(business)
        if not ranges:
            return None, "opening_hours"
        if field == "closing_time":
            return max(value[1] for value in ranges), "opening_hours"
        return min(value[0] for value in ranges), "opening_hours"

    if field == "opening_day":
        expected_day = _text(criterion.get("value"))
        state = _opening_day_state(
            business,
            expected_day,
        )
        if state is True:
            return expected_day, "opening_hours"
        if state is False:
            return "휴무", "opening_hours"
        return None, "opening_hours"

    if field == "price":
        values = _prices(business)
        if not values:
            return None, "verified_price"
        target = _text(criterion.get("target"))
        if target:
            matching = [
                row for row in values
                if target.lower() in row[1].lower()
            ]
            if matching:
                values = matching
        return min(row[0] for row in values), "verified_price"

    if field == "distance_m":
        return _distance_value(business), "kakao_distance"

    if field == "availability":
        for key in (
            "verified_available_slots",
            "available_slots",
            "mock_available_slots",
        ):
            value = business.get(key)
            if isinstance(value, list):
                return bool(value), key

        label = _text(criterion.get("label"))
        if any(
            marker in label
            for marker in (
                "주문",
                "배달",
                "포장",
                "현재",
                "지금",
            )
        ):
            current = evaluate_business_now(
                business
            )
            value = current.get("orderable_now")
            if isinstance(value, bool):
                return value, "business_hours_kst"

        return None, "availability"

    if field == "stock":
        for key in (
            "verified_stock",
            "in_stock",
            "stock",
            "mock_stock",
        ):
            if key in business and business.get(key) is not None:
                return business.get(key), key
        return None, "stock"

    if field == "rating":
        for key in ("rating", "score"):
            value = business.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value), key
        naver = _naver(business)
        value = naver.get("rating")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), "naver_rating"
        return None, "rating"

    if field == "service":
        haystack = " ".join(
            [
                _text(business.get("description")),
                _text(business.get("category")),
                _text(_naver(business).get("description")),
                " ".join(
                    _text(item.get("name"))
                    for item in _naver(business).get("prices", [])
                    if isinstance(item, dict)
                ),
            ]
        ).strip()
        return haystack or None, "business_text"

    return None, "unsupported_field"


def _normalized_expected(field, value):
    if field in TIME_FIELDS:
        return _time_to_minutes(value)
    if field in {"price", "distance_m", "rating"}:
        return _price_number(value)
    return value


def _compare(value, criterion):
    operator = _text(criterion.get("operator")).lower() or "eq"
    expected = _normalized_expected(
        _text(criterion.get("field")),
        criterion.get("value"),
    )

    if operator in RANK_OPERATORS:
        return None

    if operator == "exists":
        return value is not None

    if value is None:
        return None

    if operator == "eq":
        if isinstance(expected, str):
            return _text(value).lower() == expected.strip().lower()
        return value == expected

    if operator == "contains":
        if expected is None:
            return None
        return _text(expected).lower() in _text(value).lower()

    if operator in {"gte", "lte"}:
        if expected is None:
            return None
        try:
            left = float(value)
            right = float(expected)
        except (TypeError, ValueError):
            return None
        return left >= right if operator == "gte" else left <= right

    return None


def _legacy_criteria(mission):
    comparison = _text(mission.get("comparison"))
    mapping = {
        "latest_closing": {
            "field": "closing_time",
            "operator": "max",
            "value": None,
            "label": "가장 늦게 영업",
        },
        "parking_available": {
            "field": "parking_available",
            "operator": "eq",
            "value": True,
            "label": "주차 가능",
        },
        "nearest": {
            "field": "distance_m",
            "operator": "min",
            "value": None,
            "label": "가장 가까운 곳",
        },
        "lowest_price": {
            "field": "price",
            "operator": "min",
            "value": None,
            "label": "가장 저렴한 곳",
        },
    }
    item = mapping.get(comparison)
    if not item:
        return []
    return [{"id": "legacy-1", "required": True, **item}]


def _criteria(mission):
    raw = mission.get("criteria")
    if isinstance(raw, list):
        result = [
            dict(item)
            for item in raw
            if isinstance(item, dict)
            and _text(item.get("field"))
        ]
        if result:
            return result[:12]
    return _legacy_criteria(mission)


def match_businesses(mission, businesses):
    safe_businesses = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
        and _text(item.get("name"))
    ] if isinstance(businesses, list) else []

    criteria = _criteria(mission if isinstance(mission, dict) else {})
    if not criteria:
        return {
            "criteria": [],
            "matrix": [],
            "matched_businesses": safe_businesses,
            "unverified_businesses": [],
            "excluded_businesses": [],
            "display_businesses": safe_businesses,
            "matched_count": len(safe_businesses),
            "unverified_count": 0,
            "excluded_count": 0,
            "answer_ready": bool(safe_businesses),
            "summary": (
                f"조건 판정 없이 후보 {len(safe_businesses)}곳을 유지했습니다."
                if safe_businesses
                else "판정할 후보가 없습니다."
            ),
        }

    matrix = []
    ranking_criteria = [
        item for item in criteria
        if _text(item.get("operator")).lower() in RANK_OPERATORS
    ]
    filter_criteria = [
        item for item in criteria
        if _text(item.get("operator")).lower() not in RANK_OPERATORS
    ]

    rows = []
    for business in safe_businesses:
        results = []
        has_fail = False
        has_unknown = False

        for criterion in criteria:
            value, source = _criterion_value(business, criterion)
            operator = _text(criterion.get("operator")).lower() or "eq"
            required = criterion.get("required") is not False

            if operator in RANK_OPERATORS:
                state = "match" if value is not None else "unknown"
            else:
                compared = _compare(value, criterion)
                if compared is True:
                    state = "match"
                elif compared is False:
                    state = "fail"
                else:
                    state = "unknown"

            if required and state == "fail":
                has_fail = True
            if required and state == "unknown":
                has_unknown = True

            results.append(
                {
                    "id": _text(criterion.get("id")),
                    "label": _text(criterion.get("label")) or _text(criterion.get("field")),
                    "field": _text(criterion.get("field")),
                    "operator": operator,
                    "expected": criterion.get("value"),
                    "actual": value,
                    "state": state,
                    "source": source,
                    "required": required,
                }
            )

        base_status = (
            "excluded"
            if has_fail
            else ("unverified" if has_unknown else "matched")
        )
        rows.append(
            {
                "business": business,
                "criteria": results,
                "base_status": base_status,
            }
        )

    eligible = [row for row in rows if row["base_status"] != "excluded"]

    for criterion in ranking_criteria:
        criterion_id = _text(criterion.get("id"))
        operator = _text(criterion.get("operator")).lower()
        values = []
        for row in eligible:
            result = next(
                (
                    item
                    for item in row["criteria"]
                    if item["id"] == criterion_id
                ),
                None,
            )
            if result and result["actual"] is not None:
                values.append(result["actual"])

        if not values:
            continue

        best = min(values) if operator == "min" else max(values)
        for row in eligible:
            result = next(
                (
                    item
                    for item in row["criteria"]
                    if item["id"] == criterion_id
                ),
                None,
            )
            if not result or result["actual"] is None:
                continue
            if result["actual"] != best:
                result["state"] = "fail"
                row["base_status"] = "excluded"

    matched = []
    unverified = []
    excluded = []

    for row in rows:
        status = row["base_status"]
        # Ranking may have converted an eligible row to excluded.
        required_states = [
            item["state"]
            for item in row["criteria"]
            if item["required"]
        ]
        if "fail" in required_states:
            status = "excluded"
        elif "unknown" in required_states:
            status = "unverified"
        else:
            status = "matched"

        business = row["business"]
        if status == "matched":
            matched.append(business)
        elif status == "unverified":
            unverified.append(business)
        else:
            excluded.append(business)

        matrix.append(
            {
                "business_id": _text(business.get("id")),
                "business_name": _text(business.get("name")),
                "status": status,
                "criteria": row["criteria"],
            }
        )

    # Never present unverified candidates as if they satisfied the filter.
    # They remain in matching.unverified_businesses for follow-up evidence work,
    # but the visible recommendation set contains confirmed matches only.
    display = matched
    answer_ready = bool(matched)

    if matched:
        summary = (
            f"필수 조건을 모두 확인한 업체 {len(matched)}곳을 골랐습니다. "
            f"조건 미확인 {len(unverified)}곳, 조건 불일치 {len(excluded)}곳입니다."
        )
    elif unverified:
        summary = (
            "조건에 명확히 어긋난 업체는 제외했지만, "
            f"{len(unverified)}곳은 일부 조건의 근거가 부족해 최종 확정하지 않았습니다."
        )
    else:
        summary = "현재 확인된 데이터로 모든 필수 조건을 만족하는 업체가 없습니다."

    return {
        "criteria": criteria,
        "matrix": matrix,
        "matched_businesses": matched,
        "unverified_businesses": unverified,
        "excluded_businesses": excluded,
        "display_businesses": display,
        "matched_count": len(matched),
        "unverified_count": len(unverified),
        "excluded_count": len(excluded),
        "answer_ready": answer_ready,
        "summary": summary,
    }
