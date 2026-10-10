import json
from urllib.parse import urlparse

import httpx


AGENT_PROTOCOL = "araba-business-agent/1.0"
ALLOWED_SCHEMES = {"https"}


def _safe_endpoint(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if (
        parsed.scheme not in ALLOWED_SCHEMES
        or not parsed.hostname
    ):
        return None
    return text


def _agent_config(business):
    raw = business.get("business_agent")
    return (
        dict(raw)
        if isinstance(raw, dict)
        else {}
    )


def build_agent_request(
    mission,
    business,
):
    criteria = mission.get("criteria")
    criteria = (
        [
            dict(item)
            for item in criteria
            if isinstance(item, dict)
        ]
        if isinstance(criteria, list)
        else []
    )
    return {
        "protocol": AGENT_PROTOCOL,
        "request_type": "capability_check",
        "business": {
            "name": str(
                business.get("name") or ""
            ).strip(),
            "provider_place_id": str(
                business.get("id")
                or business.get("provider_place_id")
                or ""
            ).strip(),
            "address": str(
                business.get("address") or ""
            ).strip(),
        },
        "goal": str(
            mission.get("user_goal")
            or mission.get("summary")
            or ""
        ).strip(),
        "criteria": criteria,
        "requested_facts": list(
            mission.get("required_facts")
            or []
        )[:20],
    }


def query_business_agent(
    mission,
    business,
):
    config = _agent_config(business)
    endpoint = _safe_endpoint(
        config.get("endpoint")
    )
    if not endpoint:
        return {
            "status": "not_connected",
            "protocol": AGENT_PROTOCOL,
        }

    token = str(
        config.get("token") or ""
    ).strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ARABA-Business-Agent/1.0",
    }
    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

    try:
        response = httpx.post(
            endpoint,
            headers=headers,
            json=build_agent_request(
                mission,
                business,
            ),
            timeout=httpx.Timeout(
                5.0,
                connect=1.5,
            ),
        )
    except httpx.HTTPError:
        return {
            "status": "provider_error",
            "protocol": AGENT_PROTOCOL,
        }

    if response.status_code != 200:
        return {
            "status": "provider_error",
            "protocol": AGENT_PROTOCOL,
            "http_status": response.status_code,
        }

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        return {
            "status": "invalid_response",
            "protocol": AGENT_PROTOCOL,
        }

    if not isinstance(payload, dict):
        return {
            "status": "invalid_response",
            "protocol": AGENT_PROTOCOL,
        }

    if (
        payload.get("protocol")
        != AGENT_PROTOCOL
    ):
        return {
            "status": "invalid_response",
            "protocol": AGENT_PROTOCOL,
        }

    return {
        "status": "connected",
        "protocol": AGENT_PROTOCOL,
        "capabilities": (
            payload.get("capabilities")
            if isinstance(
                payload.get("capabilities"),
                dict,
            )
            else {}
        ),
        "facts": (
            payload.get("facts")
            if isinstance(
                payload.get("facts"),
                dict,
            )
            else {}
        ),
        "offers": (
            payload.get("offers")
            if isinstance(
                payload.get("offers"),
                list,
            )
            else []
        ),
        "reservation": (
            payload.get("reservation")
            if isinstance(
                payload.get("reservation"),
                dict,
            )
            else {}
        ),
    }


def enrich_business_with_agent(
    mission,
    business,
):
    item = dict(business)
    result = query_business_agent(
        mission,
        item,
    )
    item["business_agent_result"] = result

    if result.get("status") != "connected":
        return item

    facts = result.get("facts") or {}
    if (
        "orderable_now" in facts
        and isinstance(
            facts.get("orderable_now"),
            bool,
        )
    ):
        item["verified_available_slots"] = (
            ["business_agent_now"]
            if facts["orderable_now"]
            else []
        )
        item["availability_source"] = (
            "business_agent"
        )

    if (
        "stock_available" in facts
        and isinstance(
            facts.get("stock_available"),
            bool,
        )
    ):
        item["verified_stock"] = facts[
            "stock_available"
        ]

    return item


def enrich_businesses_with_agents(
    mission,
    businesses,
):
    return [
        enrich_business_with_agent(
            mission,
            item,
        )
        for item in businesses
        if isinstance(item, dict)
    ]
