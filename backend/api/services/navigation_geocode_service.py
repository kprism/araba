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


def _school_stem(value):
    """Normalize only explicit high-school endings, not arbitrary fuzzy names."""
    text = _canonical(value)
    if text.endswith("고등학교"):
        return text[:-len("고등학교")]
    if text.endswith("고") and len(text) >= 3:
        return text[:-1]
    return None


def _same_school(query, place):
    """A municipal name prefix is valid only if supported by the place address."""
    requested = _school_stem(query)
    actual = _school_stem(place["name"])
    if not requested or not actual:
        return False
    if requested == actual:
        return True
    longer, shorter = (
        (requested, actual)
        if len(requested) > len(actual)
        else (actual, requested)
    )
    if not longer.endswith(shorter):
        return False
    prefix = longer[:-len(shorter)]
    return 2 <= len(prefix) <= 6 and prefix in _canonical(place["address"])


def _school_search_queries(query):
    """Try common school spelling variants only after the user phrase fails."""
    parts = query.split()
    ending = parts[-1] if parts else ""
    if not _school_stem(ending) and not _school_stem(query):
        return [query]
    variants = [query]
    compact = query.replace(" ", "")
    if compact != query:
        variants.append(compact)
    # "북면고" is colloquial; the official name often ends in "고등학교".
    if ending.endswith("고") and not ending.endswith("고등학교"):
        official = ending[:-1] + "고등학교"
        if len(parts) > 1:
            variants.append(" ".join([*parts[:-1], official]))
        variants.append(official)
    elif len(parts) > 1:
        variants.append(ending)
    return list(dict.fromkeys(variants))[:4]


def _identity_verified(query, place, region):
    label = _canonical(place["name"])
    address = _canonical(place["address"])
    requested = _canonical(query)
    target, _ = _place_and_area(query)
    target = _canonical(target)
    if region and _canonical(region) not in address and _canonical(region) not in label:
        return False
    if _same_school(query, place) or _same_school(target, place):
        return True
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


def _candidate_rank(query, place):
    """Display priority only. A high score never makes an unverified place safe
    to auto-navigate to; only explicit user selection can confirm a suggestion.
    """
    requested, city = _place_and_area(query)
    requested_name = _canonical(requested)
    actual_name = _canonical(place["name"])
    address = _canonical(place["address"])
    score = 0
    if actual_name == requested_name:
        score += 120
    elif _same_school(requested, place):
        score += 110
    elif requested_name and requested_name in actual_name:
        score += 65
    elif actual_name and actual_name in requested_name:
        score += 38
    else:
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,}", requested)
        score += sum(8 for token in tokens if _canonical(token) in actual_name)
    if city and _canonical(city) in address:
        score += 28
    if requested_name and requested_name in address:
        score += 12
    return score


def _rank_candidates(query, places):
    ranked = sorted(
        places,
        key=lambda place: (
            -_candidate_rank(query, place),
            place["name"],
            place["address"],
        ),
    )
    result = []
    seen = set()
    for place in ranked:
        identity = (round(place["latitude"], 5), round(place["longitude"], 5))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(place)
        if len(result) >= 5:
            break
    return result


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
        return {"status": "ambiguous", "candidates": _rank_candidates(query, verified)}
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
        return {"status": "ambiguous", "candidates": _rank_candidates(query, list(unique.values()))}
    return {"status": "not_found", "candidates": []}


def resolve_navigation_place(query, api_key=None):
    name = " ".join(str(query or "").strip().split())
    if not 2 <= len(name) <= 140:
        return {"status": "invalid_query", "candidates": []}
    key = str(api_key or os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    if not key:
        return {"status": "missing_key", "candidates": []}

    # Search the phrase first, then bounded school-name variants. Do not
    # mistake weak same-region results for verified coordinates.
    all_places = []
    probes = [(KEYWORD_URL, item) for item in _school_search_queries(name)]
    probes.append((ADDRESS_URL, name))
    partial_failure = False
    for url, term in probes:
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"KakaoAK {key}"},
                params={"query": term, "size": 8},
                timeout=httpx.Timeout(2.8, connect=1.0),
            )
        except httpx.HTTPError:
            # A completed earlier search still supplies evidence; do not
            # silently choose an unrelated place on a transient failure.
            if not all_places:
                return {"status": "provider_error", "candidates": []}
            partial_failure = True
            break
        if response.status_code != 200:
            if not all_places:
                return {"status": "provider_error", "candidates": []}
            break
        try:
            data = response.json()
        except (ValueError, TypeError):
            continue
        items = data.get("documents") if isinstance(data, dict) else None
        matches = _to_places(
            [item for item in items if isinstance(item, dict)]
            if isinstance(items, list) else [],
            name,
        )
        all_places.extend(matches)
        # Verify against the *user's original destination*, not just the
        # broadened spelling used for an external search.
        result = _result_for(name, all_places)
        if result["status"] == "resolved":
            return result
        if result["status"] == "ambiguous":
            target, region = _place_and_area(name)
            if any(_identity_verified(name, place, region) for place in all_places):
                # Multiple independently plausible exact destinations are
                # never silently reduced to a first provider result.
                return result

    result = _result_for(name, all_places)
    if partial_failure and result["status"] == "not_found":
        return {"status": "provider_error", "candidates": []}
    return result
