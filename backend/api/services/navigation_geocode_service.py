"""Evidence-checked navigation endpoint lookup. Never navigate to a fuzzy,
single-provider match in the wrong city. Keep provider work bounded for speed."""
import os
import re

import httpx

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def _canonical(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _place_and_area(query):
    """Recognize explicit city context without assuming user's own city."""
    query = " ".join(str(query or "").strip().split())
    pattern = re.compile(
        r"^(?:(?:경남|경북|강원|경기|전남|전북|충남|충북|"
        r"경상남도|경상북도|강원도|경기도|전라남도|전라북도|"
        r"충청남도|충청북도)\s+)?"
        r"([가-힣]{2,}(?:특별시|광역시|시|군))\s+(.+)$"
    )
    match = pattern.match(query)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    return query, ""


def _identity_verified(query, place, region):
    label = _canonical(place["name"])
    address = _canonical(place["address"])
    requested = _canonical(query)
    target, _ = _place_and_area(query)
    target = _canonical(target)
    if region and _canonical(region) not in address and _canonical(region) not in label:
        return False
    # An exact place-name match (or a full address fragment) is evidence.
    # "의창소방서" must never be replaced by "인제소방서".
    return (
        label in (requested, target)
        or requested in address and len(requested) >= 5
        or (
            region
            and target in label
            and len(target) >= 4
            and len(label) - len(target) <= 8
        )
    )


def _to_places(rows, query):
    matches = []
    for row in rows:
        try:
            latitude = float(row["y"])
            longitude = float(row["x"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (33 <= latitude <= 39 and 124 <= longitude <= 132):
            continue
        label = str(row.get("place_name") or row.get("address_name") or query).strip()
        address = str(
            row.get("road_address_name") or row.get("address_name") or ""
        ).strip()
        matches.append({
            "name": label,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "source": "kakao_local_verified",
        })
    return matches


def _result_for(query, places):
    _, region = _place_and_area(query)
    verified = [
        place for place in places
        if _identity_verified(query, place, region)
    ]
    if verified:
        distinct = {
            (round(place["latitude"], 5), round(place["longitude"], 5))
            for place in verified
        }
        if len(distinct) == 1:
            return {"status": "resolved", "place": verified[0], "candidates": []}
        return {"status": "ambiguous", "candidates": verified[:5]}
    regional = [
        place for place in places
        if not region or _canonical(region) in _canonical(place["address"])
    ]
    # The same weak suggestion returned from keyword and address endpoints is
    # still one unverified place, not two independent candidates.
    unique = {
        (
            round(place["latitude"], 5),
            round(place["longitude"], 5),
            _canonical(place["name"]),
        ): place
        for place in regional
    }
    if len(unique) > 1:
        return {"status": "ambiguous", "candidates": list(unique.values())[:5]}
    return {"status": "not_found", "candidates": []}


def resolve_navigation_place(query, api_key=None):
    name = " ".join(str(query or "").strip().split())
    if not 2 <= len(name) <= 140:
        return {"status": "invalid_query", "candidates": []}
    key = str(api_key or os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    if not key:
        return {"status": "missing_key", "candidates": []}

    # Most navigation destinations are named places. The address lookup is
    # a bounded fallback if keyword search has no verified exact candidate.
    all_places = []
    for url in (KEYWORD_URL, ADDRESS_URL):
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"KakaoAK {key}"},
                params={"query": name, "size": 8},
                timeout=httpx.Timeout(2.8, connect=1.0),
            )
        except httpx.HTTPError:
            return {"status": "provider_error", "candidates": []}
        if response.status_code != 200:
            return {"status": "provider_error", "candidates": []}
        data = response.json()
        items = data.get("documents")
        matches = _to_places(
            [item for item in items if isinstance(item, dict)]
            if isinstance(items, list) else [],
            name,
        )
        all_places.extend(matches)
        result = _result_for(name, matches)
        if result["status"] == "resolved":
            return result
        # Multiple close-looking matches need user clarification; never
        # spend additional time resolving an ambiguous result automatically.
        if result["status"] == "ambiguous":
            return result

    return _result_for(name, all_places)
