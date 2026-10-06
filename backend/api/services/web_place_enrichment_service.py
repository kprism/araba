import html
import ipaddress
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx


NAVER_BLOG_SEARCH_URL = (
    "https://openapi.naver.com/v1/search/blog.json"
)
NAVER_WEB_SEARCH_URL = (
    "https://openapi.naver.com/v1/search/webkr.json"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Mobile Safari/537.36"
)


def _strip_tags(value):
    text = re.sub(
        r"<[^>]+>",
        "",
        str(value or ""),
    )
    return html.unescape(text).strip()


def _normalize(value):
    return re.sub(
        r"[^0-9a-zA-Z가-힣]",
        "",
        _strip_tags(value).lower(),
    )


def _resolve_credentials(
    client_id=None,
    client_secret=None,
):
    resolved_id = str(
        client_id
        or os.environ.get("NAVER_CLIENT_ID")
        or ""
    ).strip()
    resolved_secret = str(
        client_secret
        or os.environ.get("NAVER_CLIENT_SECRET")
        or ""
    ).strip()

    if not resolved_id or not resolved_secret:
        return None, None

    return resolved_id, resolved_secret


def _safe_public_url(value):
    try:
        parsed = urlparse(
            str(value or "").strip()
        )
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    ):
        return False

    return True


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )
        self.text_parts = []
        self.meta = {}
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        lower = tag.lower()
        if lower in {
            "script",
            "style",
            "noscript",
            "svg",
        }:
            self._ignored_depth += 1
            return

        if lower == "meta":
            values = {
                str(key or "").lower():
                str(value or "")
                for key, value in attrs
            }
            key = (
                values.get("property")
                or values.get("name")
                or ""
            ).lower()
            content = values.get("content")
            if key and content:
                self.meta[key] = content

    def handle_endtag(
        self,
        tag,
    ):
        if (
            tag.lower()
            in {
                "script",
                "style",
                "noscript",
                "svg",
            }
            and self._ignored_depth > 0
        ):
            self._ignored_depth -= 1

    def handle_data(
        self,
        data,
    ):
        if self._ignored_depth:
            return
        text = " ".join(
            str(data or "").split()
        ).strip()
        if len(text) >= 2:
            self.text_parts.append(text)


def _read_public_page(url):
    page_url = str(url or "").strip()
    if not _safe_public_url(page_url):
        return {
            "checked": False,
            "url": page_url or None,
            "text": "",
            "image_url": None,
        }

    try:
        response = httpx.get(
            page_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": (
                    "ko-KR,ko;q=0.9,en;q=0.7"
                ),
            },
            timeout=httpx.Timeout(
                2.5,
                connect=0.8,
            ),
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return {
            "checked": False,
            "url": page_url,
            "text": "",
            "image_url": None,
        }

    if (
        response.status_code < 200
        or response.status_code >= 300
    ):
        return {
            "checked": False,
            "url": page_url,
            "text": "",
            "image_url": None,
        }

    content_type = str(
        response.headers.get(
            "content-type",
            "",
        )
    ).lower()
    if "html" not in content_type:
        return {
            "checked": False,
            "url": page_url,
            "text": "",
            "image_url": None,
        }

    parser = _PageParser()
    try:
        parser.feed(
            response.text[:500000]
        )
    except Exception:
        pass

    text = " ".join(
        parser.text_parts
    )
    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    image_url = str(
        parser.meta.get("og:image")
        or parser.meta.get("twitter:image")
        or ""
    ).strip()
    if not _safe_public_url(image_url):
        image_url = ""

    return {
        "checked": True,
        "url": page_url,
        "text": text[:120000],
        "image_url": image_url or None,
    }


def _search_naver(
    endpoint,
    query,
    *,
    client_id,
    client_secret,
):
    try:
        response = httpx.get(
            endpoint,
            headers={
                "X-Naver-Client-Id":
                    client_id,
                "X-Naver-Client-Secret":
                    client_secret,
            },
            params={
                "query": query,
                "display": 5,
                "start": 1,
                **(
                    {"sort": "sim"}
                    if endpoint
                    == NAVER_BLOG_SEARCH_URL
                    else {}
                ),
            },
            timeout=httpx.Timeout(
                2.0,
                connect=0.8,
            ),
        )
    except httpx.HTTPError:
        return []

    if response.status_code != 200:
        return []

    payload = response.json()
    items = payload.get("items", [])
    return [
        item
        for item in items
        if isinstance(item, dict)
    ]


def _missing_keywords(
    business,
    mission,
):
    naver = business.get("naver")
    naver = (
        dict(naver)
        if isinstance(naver, dict)
        else {}
    )

    keywords = []

    hours = naver.get(
        "opening_hours"
    )
    if not isinstance(hours, list) or not hours:
        keywords.append("영업시간")

    if naver.get("parking_available") is None:
        keywords.append("주차")

    prices = naver.get("prices")
    if not isinstance(prices, list) or not prices:
        keywords.append("가격")

    if not str(
        business.get("image_url") or ""
    ).strip():
        keywords.append("사진")

    if not str(
        business.get("phone") or ""
    ).strip():
        keywords.append("전화번호")

    required = mission.get(
        "required_facts"
    )
    if isinstance(required, list):
        for fact in required:
            text = str(fact or "").strip()
            if text and text not in keywords:
                keywords.append(text)

    constraints = mission.get("constraints")
    if isinstance(constraints, list):
        for constraint in constraints:
            text = str(
                constraint or ""
            ).strip()
            if text and text not in keywords:
                keywords.append(text)

    return keywords[:6]


def _candidate_score(
    item,
    *,
    business,
    location,
    keywords,
):
    title = _strip_tags(
        item.get("title")
    )
    description = _strip_tags(
        item.get("description")
    )
    text = f"{title} {description}"
    compact = _normalize(text)
    name = _normalize(
        business.get("name")
    )
    score = 0

    if name and name in compact:
        score += 70

    location_tokens = [
        _normalize(token)
        for token in re.findall(
            r"[0-9A-Za-z가-힣]{2,}",
            str(location or ""),
        )
    ]
    if any(
        token
        and token in compact
        for token in location_tokens
    ):
        score += 15

    matched_keywords = sum(
        1
        for keyword in keywords
        if _normalize(keyword)
        and _normalize(keyword) in compact
    )
    score += min(
        15,
        matched_keywords * 5,
    )

    return score


def _extract_hours(text):
    normalized = re.sub(
        r"\s+",
        " ",
        str(text or ""),
    )
    patterns = (
        r"(?:영업시간|운영시간|진료시간)\s*[:：]?\s*([^|]{3,120})",
        r"(?:평일|월요일|월~금|월-금)\s*[:：]?\s*([0-2]?\d[:시][0-5]?\d?\s*[~-]\s*[0-2]?\d[:시][0-5]?\d?)",
    )
    for pattern in patterns:
        match = re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )
        if match:
            value = re.split(
                r"(?:전화|주소|주차|가격|예약|문의)",
                match.group(1),
            )[0].strip(" ,.;")
            if 3 <= len(value) <= 120:
                return [value]
    return []


def _extract_parking(text):
    normalized = re.sub(
        r"\s+",
        " ",
        str(text or "").lower(),
    )

    negative = (
        r"주차\s*(?:불가|안됨|불가능)",
        r"주차장\s*(?:없음|없습니다)",
    )
    if any(
        re.search(pattern, normalized)
        for pattern in negative
    ):
        return False

    positive = (
        r"주차\s*(?:가능|됩니다|가능함)",
        r"무료\s*주차",
        r"전용\s*주차",
    )
    if any(
        re.search(pattern, normalized)
        for pattern in positive
    ):
        return True

    return None


def _extract_prices(text):
    normalized = re.sub(
        r"\s+",
        " ",
        str(text or ""),
    )
    values = []

    pattern = re.compile(
        r"([가-힣A-Za-z][가-힣A-Za-z0-9 ()·/+_-]{0,31}?)"
        r"\s*[:：-]?\s*"
        r"([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*원"
    )

    for match in pattern.finditer(
        normalized
    ):
        name = " ".join(
            match.group(1).split()
        ).strip(" -,:")
        price = (
            match.group(2).strip()
            + "원"
        )
        if not name:
            continue
        item = {
            "name": name[-32:],
            "price": price,
            "currency": "KRW",
        }
        if item not in values:
            values.append(item)
        if len(values) >= 4:
            break

    return values


def _extract_phone(text):
    match = re.search(
        r"(?<!\d)(?:02|0[3-6][1-5])[- .]?\d{3,4}[- .]?\d{4}(?!\d)",
        str(text or ""),
    )
    if not match:
        return None
    return re.sub(
        r"[ .]",
        "-",
        match.group(0),
    )


def _source_item(
    raw,
    source_type,
    *,
    score,
):
    return {
        "type": source_type,
        "title": _strip_tags(
            raw.get("title")
        ),
        "url": str(
            raw.get("link") or ""
        ).strip(),
        "snippet": _strip_tags(
            raw.get("description")
        ),
        "score": score,
        "postdate": str(
            raw.get("postdate") or ""
        ).strip() or None,
    }


def enrich_one_business_with_web(
    business,
    mission,
    *,
    client_id,
    client_secret,
):
    item = dict(business)
    keywords = _missing_keywords(
        item,
        mission,
    )

    if not keywords:
        item["web"] = {
            "status": "not_needed",
            "sources": [],
        }
        return item

    name = str(
        item.get("name") or ""
    ).strip()
    location = str(
        mission.get("location")
        or item.get("address")
        or ""
    ).strip()

    query = " ".join(
        part
        for part in (
            location,
            name,
            " ".join(keywords[:3]),
        )
        if part
    ).strip()

    with ThreadPoolExecutor(
        max_workers=2
    ) as executor:
        futures = {
            executor.submit(
                _search_naver,
                endpoint,
                query,
                client_id=client_id,
                client_secret=client_secret,
            ): source_type
            for endpoint, source_type in (
                (
                    NAVER_BLOG_SEARCH_URL,
                    "naver_blog",
                ),
                (
                    NAVER_WEB_SEARCH_URL,
                    "naver_web",
                ),
            )
        }

        raw_sources = []
        for future in as_completed(futures):
            source_type = futures[future]
            try:
                results = future.result()
            except Exception:
                results = []
            for raw in results:
                score = _candidate_score(
                    raw,
                    business=item,
                    location=location,
                    keywords=keywords,
                )
                if score >= 70:
                    raw_sources.append(
                        _source_item(
                            raw,
                            source_type,
                            score=score,
                        )
                    )

    raw_sources.sort(
        key=lambda value: (
            int(value.get("score") or 0),
            str(value.get("postdate") or ""),
        ),
        reverse=True,
    )
    sources = raw_sources[:3]

    if not sources:
        item["web"] = {
            "status": "not_found",
            "query": query,
            "sources": [],
        }
        return item

    evidence_texts = []
    best_image = None
    for source in sources:
        snippet = str(
            source.get("snippet") or ""
        ).strip()
        page = _read_public_page(
            source.get("url")
        )
        page_text = str(
            page.get("text") or ""
        ).strip()

        combined = " ".join(
            part
            for part in (
                source.get("title"),
                snippet,
                page_text,
            )
            if part
        )
        source["page_checked"] = (
            page.get("checked") is True
        )
        source["evidence_excerpt"] = (
            combined[:500]
            if combined
            else None
        )
        evidence_texts.append(
            combined
        )

        if (
            best_image is None
            and str(
                page.get("image_url") or ""
            ).strip()
        ):
            best_image = str(
                page.get("image_url")
            ).strip()

    combined_evidence = " ".join(
        evidence_texts
    )
    hours = _extract_hours(
        combined_evidence
    )
    parking = _extract_parking(
        combined_evidence
    )
    prices = _extract_prices(
        combined_evidence
    )
    phone = _extract_phone(
        combined_evidence
    )

    price_link = None
    if prices:
        for source in sources:
            snippet = " ".join(
                [
                    str(
                        source.get("title")
                        or ""
                    ),
                    str(
                        source.get("snippet")
                        or ""
                    ),
                    str(
                        source.get(
                            "evidence_excerpt"
                        )
                        or ""
                    ),
                ]
            )
            if _extract_prices(snippet):
                price_link = source.get(
                    "url"
                )
                break

    item["web"] = {
        "status": "matched",
        "query": query,
        "sources": sources,
        "opening_hours": hours,
        "parking_available": parking,
        "prices": prices,
        "price_link": price_link,
        "phone": phone,
        "image_url": best_image,
    }

    naver = item.get("naver")
    naver = (
        dict(naver)
        if isinstance(naver, dict)
        else {}
    )

    if (
        not str(
            item.get("image_url") or ""
        ).strip()
        and best_image
    ):
        item["image_url"] = best_image
        item["image_source"] = "web_evidence"

    if (
        not str(
            item.get("phone") or ""
        ).strip()
        and phone
    ):
        item["phone"] = phone

    if (
        not naver.get("opening_hours")
        and hours
    ):
        naver["opening_hours"] = hours
        naver["opening_hours_source"] = (
            "web_evidence"
        )

    if (
        naver.get("parking_available")
        is None
        and parking is not None
    ):
        naver["parking_available"] = parking
        naver["parking_source"] = (
            "web_evidence"
        )

    if (
        not naver.get("prices")
        and prices
    ):
        naver["prices"] = prices
        naver["prices_source"] = (
            "web_evidence"
        )
        naver["price_link"] = price_link

    item["naver"] = naver
    return item


def enrich_businesses_with_web(
    businesses,
    mission,
    *,
    client_id=None,
    client_secret=None,
):
    if not isinstance(businesses, list):
        return []

    safe = [
        dict(item)
        for item in businesses
        if isinstance(item, dict)
    ]
    if not safe:
        return []

    resolved_id, resolved_secret = (
        _resolve_credentials(
            client_id,
            client_secret,
        )
    )
    if not resolved_id or not resolved_secret:
        return [
            {
                **item,
                "web": {
                    "status": "not_configured",
                    "sources": [],
                },
            }
            for item in safe
        ]

    results = [None] * len(safe)

    with ThreadPoolExecutor(
        max_workers=min(
            5,
            len(safe),
        )
    ) as executor:
        future_to_index = {
            executor.submit(
                enrich_one_business_with_web,
                item,
                mission,
                client_id=resolved_id,
                client_secret=resolved_secret,
            ): index
            for index, item in enumerate(safe)
        }

        for future in as_completed(
            future_to_index
        ):
            index = future_to_index[
                future
            ]
            try:
                results[index] = (
                    future.result()
                )
            except Exception:
                results[index] = {
                    **safe[index],
                    "web": {
                        "status":
                            "enrichment_error",
                        "sources": [],
                    },
                }

    return [
        item
        for item in results
        if isinstance(item, dict)
    ]
