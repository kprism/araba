import json
from unittest.mock import Mock, patch

import httpx
from django.test import TestCase
from openai import APITimeoutError, NotFoundError
from rest_framework.test import APIClient


class MissionDiagnosticsTests(TestCase):
    def request(self):
        return APIClient().post(
            "/api/missions/create/",
            {"request": "창원시청 주변 타이어점"},
            format="json",
            HTTP_X_OPENAI_API_KEY="sk-private-test",
        )

    @patch("api.services.mission_service.OpenAI")
    def test_timeout_stage_and_no_retry(self, client):
        client.return_value.responses.create.side_effect = (
            APITimeoutError(
                request=httpx.Request(
                    "POST",
                    "https://api.openai.com/v1/responses",
                ),
            )
        )

        with self.assertLogs(
            "api.views",
            level="WARNING",
        ) as logs:
            response = self.request()

        self.assertEqual(
            response.status_code,
            504,
        )
        details = response.data["diagnostics"]
        self.assertEqual(
            details["stage"],
            "intent_core_request",
        )
        self.assertEqual(
            details["architecture"],
            "intent_router_v2",
        )
        self.assertEqual(
            details["exception_type"],
            "APITimeoutError",
        )
        self.assertEqual(details["retries"], 0)
        self.assertEqual(
            details["timeout_seconds"],
            12.0,
        )
        self.assertGreaterEqual(
            details["server_elapsed_ms"],
            details["openai_elapsed_ms"],
        )
        self.assertEqual(
            response["X-Request-ID"],
            details["request_id"],
        )
        self.assertEqual(
            client.return_value.responses.create.call_count,
            1,
        )
        self.assertNotIn(
            "sk-private-test",
            str(logs.output),
        )
        self.assertNotIn(
            "창원시청",
            str(logs.output),
        )

    @patch("api.services.mission_service.OpenAI")
    def test_provider_status_without_sensitive_body(
        self,
        client,
    ):
        request = httpx.Request(
            "POST",
            "https://api.openai.com/v1/responses",
        )
        client.return_value.responses.create.side_effect = (
            NotFoundError(
                "secret provider body",
                response=httpx.Response(
                    404,
                    request=request,
                    headers={
                        "x-request-id": "req_test",
                    },
                ),
                body={
                    "error": {
                        "message": "sk-private-test",
                    }
                },
            )
        )

        response = self.request()
        details = response.data["diagnostics"]

        self.assertEqual(
            details["upstream_http_status"],
            404,
        )
        self.assertEqual(
            details["upstream_request_id"],
            "req_test",
        )
        self.assertEqual(
            details["exception_type"],
            "NotFoundError",
        )
        self.assertNotIn(
            "secret provider body",
            str(response.data),
        )
        self.assertNotIn(
            "sk-private-test",
            str(response.data),
        )

    @patch("api.services.mission_service.OpenAI")
    def test_invalid_json_is_not_timeout(
        self,
        client,
    ):
        client.return_value.responses.create.return_value = (
            Mock(
                output_text="not json",
            )
        )

        response = self.request()

        self.assertEqual(
            response.status_code,
            400,
        )
        self.assertEqual(
            response.data["diagnostics"]["stage"],
            "parse_intent",
        )
        self.assertEqual(
            response.data["diagnostics"][
                "exception_type"
            ],
            "ValueError",
        )

    @patch("api.services.mission_service.OpenAI")
    def test_success_reports_intent_route(
        self,
        client,
    ):
        client.return_value.responses.create.return_value = (
            Mock(
                output_text=json.dumps(
                    {
                        "intent": "place_search",
                        "goal": "타이어점 찾기",
                        "location": {
                            "value": "창원시청",
                            "type": "reference_point",
                            "explicit": True,
                        },
                        "category": "타이어",
                        "subject": "타이어점",
                        "target_business": None,
                        "count": 5,
                        "constraints": [],
                        "attributes": {},
                        "requested_facts": [],
                        "sort": "distance",
                        "needs_fresh_data": True,
                        "needs_clarification": False,
                        "clarification_question": None,
                        "direct_answer": None,
                    },
                    ensure_ascii=False,
                )
            )
        )

        response = self.request()

        self.assertEqual(
            response.status_code,
            200,
        )
        details = response.data["diagnostics"]
        self.assertEqual(
            details["architecture"],
            "intent_router_v2",
        )
        self.assertEqual(
            details["route"],
            "place_search",
        )
