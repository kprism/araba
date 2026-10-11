"""Resolve named route endpoints without guessing coordinates or choosing
between different places with the same name."""
import os
import re

import httpx

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def _canonical(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def resolve_navigation_place(query, api_key=None):
    name = " ".join(str(query or "").strip().split())
    if not 2 <= len(name) <= 140:
        return {"status": "invalid_query", "candidates": []}
    key = str(api_key or os.environ.get("KAKAO_REST_API_KEY") or "").strip()
    if not key:
        return {"status": "missing_key", "candidates": []}

    documents = []
    for url in (KEYWORD_URL, ADDRESS_URL):
        try:
            response = httpx.get(
                url,
                headers={"Authorization": f"KakaoAK {key}"},
                params={"query": name, "size": 8},
                timeout=httpx.Timeout(4.0, connect=1.8),
            )
        except httpx.HTTPError:
            return {"status": "provider_error", "candidates": []}
        if response.status_code != 200:
            return {"status": "provider_error", "candidates": []}
        data = response.json()
        items = data.get("documents")
        if isinstance(items, list):
            documents = [item for item in items if isinstance(item, dict)]
        if documents:
            break

    matches = []
    for row in documents:
        try:
            latitude = float(row["y"])
            longitude = float(row["x"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (33 <= latitude <= 39 and 124 <= longitude <= 132):
            continue
        label = str(row.get("place_name") or row.get("address_name") or name).strip()
        address = str(
            row.get("road_address_name") or row.get("address_name") or ""
        ).strip()
        place = {
            "name": label,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "source": "kakao_local_verified",
        }
        matches.append(place)

    if not matches:
        return {"status": "not_found", "candidates": []}
    exact = [
        value for value in matches
        if _canonical(name) in (
            _canonical(value["name"]),
            _canonical(value["address"]),
        )
    ]
    if exact:
        matches = exact
    elif len(matches) > 1:
        # Avoid silently choosing the first ranked business from a loose query.
        return {"status": "ambiguous", "candidates": matches[:5]}

    distinct = {
        (round(place["latitude"], 5), round(place["longitude"], 5))
        for place in matches
    }
    if len(distinct) != 1:
        return {"status": "ambiguous", "candidates": matches[:5]}

    return {"status": "resolved", "place": matches[0], "candidates": []}
