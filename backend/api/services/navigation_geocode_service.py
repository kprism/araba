"""Evidence-checked navigation endpoint lookup. Never navigate to a fuzzy,
single-provider match in the wrong city. Keep provider work bounded for speed."""
import os
import re

import httpx

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def _canonical(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


# This is a geographic vocabulary, not a list of particular businesses.
# Bare city names occur frequently in spoken Korean ("창원 대산고등학교").
_BARE_CITIES = frozenset("""
서울 부산 대구 인천 광주 대전 울산 세종 제주 창원 김해 진주 양산 밀양
통영 거제 사천 고성 고양 수원 성남 용인 안양 안산 화성 평택 파주
남양주 의정부 광명 부천 시흥 군포 하남 김포 광주 이천 여주
춘천 원주 강릉 속초 동해 삼척 태백 포항 경주 구미 안동 김천
영주 상주 문경 경산 청주 충주 제천 천안 아산 공주 보령 서산
당진 논산 계룡 전주 군산 익산 정읍 남원 김제 목포 여수 순천
광양 나주 영암 영광 무안 해남 서귀포
""".split())
_PROVINCES = frozenset("""
경남 경북 경기 강원 전남 전북 충남 충북 제주 경상남도 경상북도
경기도 강원도 전라남도 전라북도 충청남도 충청북도 제주특별자치도
""".split())
_METROPOLITAN_ALIASES = {
    "서울": "서울특별시", "부산": "부산광역시",
    "대구": "대구광역시", "인천": "인천광역시",
    "광주": "광주광역시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시",
    "제주": "제주시",
}


def _place_and_area(query):
    """Extract an EXPLICIT location as a hard constraint for any place type.

    No GPS/user-city inference here. Even when the search term is colloquial,
    "창원 대산고등학교" must never return a school in Seoul or Gyeonggi.
    """
    query = " ".join(str(query or "").strip().split())
    parts = query.split()
    if not parts:
        return "", ""
    if parts[0] in _PROVINCES and len(parts) > 1:
        # Provinces may be followed by a city, or used as an area themselves.
        if len(parts) == 2:
            return parts[1], parts[0]
        query = " ".join(parts[1:])
        parts = query.split()
    if len(parts) >= 2:
        leading = parts[0]
        if (
            leading in _BARE_CITIES
            or re.fullmatch(r"[가-힣]{2,}(?:특별시|광역시|특별자치시|시|군|구)", leading)
        ):
            return " ".join(parts[1:]), leading
    return query, ""


def _region_matches(region, place):
    if not region:
        return True
    address = _canonical(place.get("address"))
    region_name = _canonical(region)
    forms = {region_name}
    if region_name.endswith("시"):
        forms.add(region_name[:-1])
    if region_name.endswith("군"):
        forms.add(region_name[:-1])
    else:
        forms.add(region_name + "시")
    expanded = _METROPOLITAN_ALIASES.get(region_name)
    if expanded:
        forms.add(_canonical(expanded))
    return any(len(form) >= 2 and form in address for form in forms)


def _venue_type(text):
    name = _canonical(text)
    for token, kind in (
        ("고등학교", "high"), ("중학교", "middle"),
        ("초등학교", "elementary"), ("대학교", "university"),
        ("병원", "hospital"), ("약국", "pharmacy"),
    ):
        if token in name:
            return kind
    return ""


def _name_core(text):
    name = _canonical(text)
    for suffix in ("고등학교", "중학교", "초등학교", "대학교", "병원", "약국"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _related_name(query, place):
    from difflib import SequenceMatcher

    target, _ = _place_and_area(query)
    if _same_school(query, place) or _same_school(target, place):
        return True
    requested_type = _venue_type(target)
    candidate_type = _venue_type(place["name"])
    if requested_type and requested_type != candidate_type:
        return False
    asked = _name_core(target)
    actual = _name_core(place["name"])
    if not asked or not actual:
        return False
    if asked in actual or actual in asked:
        return min(len(asked), len(actual)) >= 2
    # Restrict fuzzy fallback to substantive names, never generic categories.
    return (
        len(asked) >= 3 and len(actual) >= 3
        and SequenceMatcher(None, asked, actual).ratio() >= 0.75
    )


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
    """Try compact and regional/name variants, without dropping region checks."""
    target, city = _place_and_area(query)
    variants = [query]
    compact = query.replace(" ", "")
    if compact != query:
        variants.append(compact)
    if city:
        if target not in variants:
            variants.append(target)
        joined = city + target.replace(" ", "")
        if joined not in variants:
            variants.append(joined)
    ending = target.replace(" ", "")
    if ending.endswith("고") and not ending.endswith("고등학교"):
        variants.append(ending[:-1] + "고등학교")
    if target.endswith("고등학교") and " " in target:
        variants.append(ending)
    return list(dict.fromkeys(variants))[:5]



def _identity_verified(query, place, region):
    label = _canonical(place["name"])
    address = _canonical(place["address"])
    requested = _canonical(query)
    target, _ = _place_and_area(query)
    target = _canonical(target)
    if not _region_matches(region, place):
        return False
    if not _related_name(query, place):
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
    if city and _region_matches(city, place):
        score += 100
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
        if _region_matches(region, place) and _related_name(query, place)
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
    if unique:
        # Even one fuzzy match requires an explicit tap; never auto-launch.
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
