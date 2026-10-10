import os
import re

import httpx


GOOGLE_TEXT_SEARCH_URL = (
    "https://places.googleapis.com/v1/places:searchText"
)
GOOGLE_PHOTO_MEDIA_URL = (
    "https://places.googleapis.com/v1/{photo_name}/media"
)
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.primaryType",
        "places.primaryTypeDisplayName",
        "places.businessStatus",
        "places.currentOpeningHours",
        "places.regularOpeningHours",
        "places.utcOffsetMinutes",
        "places.photos",
        "places.delivery",
        "places.takeout",
        "places.reservable",
        "places.rating",
        "places.googleMapsUri",
    ]
)


def get_google_places_key(value=None):
    explicit = str(value or "").strip()
    if explicit:
        return explicit
    return str(
        os.getenv("GOOGLE_PLACES_API_KEY") or ""
    ).strip()


def _identity(value):
    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(value or "").lower(),
    )


def _address_score(expected, candidate):
    expected_text = _identity(expected)
    candidate_text = _identity(candidate)
    if not expected_text or not candidate_text:
        return 0
    if expected_text in candidate_text or candidate_text in expected_text:
        return 3

    tokens = [
        token
        for token in re.findall(
            r"[가-힣A-Za-z0-9]+",
            str(expected or ""),
        )
        if len(token) >= 2
    ]
    return sum(
        1
        for token in tokens
        if _identity(token) in candidate_text
    )


def _candidate_score(business, place):
    expected_name = _identity(
        business.get("name")
    )
    raw_display = place.get("displayName")
    display_name = (
        raw_display.get("text")
        if isinstance(raw_display, dict)
        else raw_display
    )
    actual_name = _identity(display_name)
    if not expected_name or not actual_name:
        return -1

    if expected_name == actual_name:
        name_score = 8
    elif (
        expected_name in actual_name
        or actual_name in expected_name
    ):
        name_score = 5
    else:
        return -1

    address_score = _address_score(
        business.get("road_address")
        or business.get("address"),
        place.get("formattedAddress"),
    )
    return name_score + address_score


def _weekday_descriptions(hours):
    if not isinstance(hours, dict):
        return []
    raw = hours.get("weekdayDescriptions")
    if not isinstance(raw, list):
        return []
    return [
        str(item).strip()
        for item in raw
        if str(item).strip()
    ]


def _open_now(hours):
    if not isinstance(hours, dict):
        return None
    value = hours.get("openNow")
    return value if isinstance(value, bool) else None


def _photo_uri(api_key, photo):
    if not isinstance(photo, dict):
        return None
    name = str(photo.get("name") or "").strip()
    if not name:
        return None

    try:
        response = httpx.get(
            GOOGLE_PHOTO_MEDIA_URL.format(
                photo_name=name
            ),
            params={
                "key": api_key,
                "maxWidthPx": 1200,
                "skipHttpRedirect": "true",
            },
            timeout=httpx.Timeout(
                4.0,
                connect=1.5,
            ),
        )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None
    payload = response.json()
    uri = str(
        payload.get("photoUri") or ""
    ).strip()
    return uri or None


def enrich_business_with_google_places(
    business,
    *,
    api_key=None,
):
    key = get_google_places_key(api_key)
    if not key:
        return dict(business)

    name = str(
        business.get("name") or ""
    ).strip()
    address = str(
        business.get("road_address")
        or business.get("address")
        or ""
    ).strip()
    if not name:
        return dict(business)

    query = " ".join(
        item
        for item in (name, address)
        if item
    )
    try:
        response = httpx.post(
            GOOGLE_TEXT_SEARCH_URL,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": FIELD_MASK,
                "Content-Type": "application/json",
            },
            json={
                "textQuery": query,
                "languageCode": "ko",
                "regionCode": "KR",
                "pageSize": 3,
            },
            timeout=httpx.Timeout(
                5.0,
                connect=1.5,
            ),
        )
    except httpx.HTTPError:
        return dict(business)

    if response.status_code != 200:
        return dict(business)

    payload = response.json()
    places = payload.get("places")
    if not isinstance(places, list):
        return dict(business)

    ranked = sorted(
        (
            (
                _candidate_score(
                    business,
                    place,
                ),
                place,
            )
            for place in places
            if isinstance(place, dict)
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 9:
        return dict(business)

    _, place = ranked[0]
    current_hours = place.get(
        "currentOpeningHours"
    )
    regular_hours = place.get(
        "regularOpeningHours"
    )
    photos = place.get("photos")
    photo_url = None
    selected_photo = None
    if isinstance(photos, list):
        for photo in photos[:2]:
            photo_url = _photo_uri(
                key,
                photo,
            )
            if photo_url:
                selected_photo = photo
                break

    raw_attributions = (
        selected_photo.get("authorAttributions")
        if isinstance(selected_photo, dict)
        else None
    )
    photo_attributions = (
        [
            {
                "display_name": str(
                    item.get("displayName") or ""
                ).strip(),
                "uri": str(
                    item.get("uri") or ""
                ).strip(),
                "photo_uri": str(
                    item.get("photoUri") or ""
                ).strip(),
            }
            for item in raw_attributions
            if isinstance(item, dict)
        ]
        if isinstance(raw_attributions, list)
        else []
    )

    raw_display = place.get("displayName")
    display_name = (
        raw_display.get("text")
        if isinstance(raw_display, dict)
        else raw_display
    )
    raw_type = place.get(
        "primaryTypeDisplayName"
    )
    type_label = (
        raw_type.get("text")
        if isinstance(raw_type, dict)
        else raw_type
    )

    google = {
        "matched": True,
        "place_id": place.get("id"),
        "display_name": display_name,
        "formatted_address": place.get(
            "formattedAddress"
        ),
        "primary_type": place.get(
            "primaryType"
        ),
        "primary_type_label": type_label,
        "business_status": place.get(
            "businessStatus"
        ),
        "utc_offset_minutes": place.get(
            "utcOffsetMinutes"
        ),
        "open_now": _open_now(
            current_hours
        ),
        "current_opening_hours": (
            _weekday_descriptions(
                current_hours
            )
        ),
        "regular_opening_hours": (
            _weekday_descriptions(
                regular_hours
            )
        ),
        "delivery": place.get("delivery"),
        "takeout": place.get("takeout"),
        "reservable": place.get(
            "reservable"
        ),
        "rating": place.get("rating"),
        "maps_uri": place.get(
            "googleMapsUri"
        ),
        "photo_url": photo_url,
        "photo_attributions": photo_attributions,
        "source": "google_places_new",
    }

    result = dict(business)
    result["google_places"] = google

    # Runtime-only, identity-verified photo. It is attached after DB persistence
    # so a Google photo URL is not treated as ARABA's durable source of truth.
    if photo_url and not str(result.get("image_url") or "").strip():
        # Keep identity-verified durable Kakao/official imagery when present.
        # Google photoUri is refreshed at runtime and may expire.
        result["image_url"] = photo_url
        result["image_source"] = (
            "google_places_verified"
        )
        result["image_identity_verified"] = True
        result["image_attributions"] = (
            photo_attributions
        )
        result["image_google_maps_uri"] = str(
            place.get("googleMapsUri") or ""
        ).strip()

    naver = result.get("naver")
    if not isinstance(naver, dict):
        naver = {}
    else:
        naver = dict(naver)

    google_hours = (
        google["current_opening_hours"]
        or google["regular_opening_hours"]
    )
    if google_hours:
        existing = naver.get(
            "opening_hours"
        )
        if not isinstance(existing, list):
            existing = []
        naver["opening_hours"] = list(
            dict.fromkeys(
                [
                    *[
                        str(item).strip()
                        for item in existing
                        if str(item).strip()
                    ],
                    *google_hours,
                ]
            )
        )[:14]
        naver["opening_hours_source"] = (
            "google_places+stored"
        )

    if naver:
        result["naver"] = naver

    return result


def enrich_businesses_with_google_places(
    businesses,
    *,
    api_key=None,
    limit=5,
):
    key = get_google_places_key(api_key)
    if not key:
        return [
            dict(item)
            for item in businesses
            if isinstance(item, dict)
        ]

    result = []
    for index, item in enumerate(
        businesses
    ):
        if not isinstance(item, dict):
            continue
        if index < limit:
            result.append(
                enrich_business_with_google_places(
                    item,
                    api_key=key,
                )
            )
        else:
            result.append(dict(item))
    return result
