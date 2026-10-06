from unittest.mock import Mock, patch

import httpx
from django.test import TestCase
from openai import APITimeoutError, NotFoundError
from rest_framework.test import APIClient


class MissionDiagnosticsTests(TestCase):
    def request(self):
        return APIClient().post(
            '/api/missions/create/', {'request': '창원시청 주변 타이어점'},
            format='json', HTTP_X_OPENAI_API_KEY='sk-private-test',
        )

    @patch('api.services.mission_service.active_rules_text', return_value='')
    @patch('api.services.mission_service.OpenAI')
    def test_timeout_stage_and_no_retry(self, client, rules):
        client.return_value.responses.create.side_effect = APITimeoutError(
            request=httpx.Request('POST', 'https://api.openai.com/v1/responses'),
        )
        with self.assertLogs('api.views', level='WARNING') as logs:
            response = self.request()
        self.assertEqual(response.status_code, 504)
        details = response.data['diagnostics']
        self.assertEqual(details['stage'], 'openai_request')
        self.assertEqual(details['exception_type'], 'APITimeoutError')
        self.assertEqual(details['retries'], 0)
        self.assertEqual(details['timeout_seconds'], 7.0)
        self.assertGreaterEqual(details['server_elapsed_ms'], details['openai_elapsed_ms'])
        self.assertEqual(response['X-Request-ID'], details['request_id'])
        self.assertEqual(client.return_value.responses.create.call_count, 1)
        self.assertNotIn('sk-private-test', str(logs.output))
        self.assertNotIn('창원시청', str(logs.output))

    @patch('api.services.mission_service.active_rules_text', return_value='')
    @patch('api.services.mission_service.OpenAI')
    def test_provider_status_without_sensitive_body(self, client, rules):
        request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
        client.return_value.responses.create.side_effect = NotFoundError(
            'secret provider body',
            response=httpx.Response(404, request=request, headers={'x-request-id': 'req_test'}),
            body={'error': {'message': 'sk-private-test'}},
        )
        response = self.request()
        details = response.data['diagnostics']
        self.assertEqual(details['upstream_http_status'], 404)
        self.assertEqual(details['upstream_request_id'], 'req_test')
        self.assertEqual(details['exception_type'], 'NotFoundError')
        self.assertNotIn('secret provider body', str(response.data))
        self.assertNotIn('sk-private-test', str(response.data))

    @patch('api.services.mission_service.active_rules_text', return_value='')
    @patch('api.services.mission_service.OpenAI')
    def test_invalid_json_is_not_timeout(self, client, rules):
        client.return_value.responses.create.return_value = Mock(output_text='not json')
        response = self.request()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['diagnostics']['stage'], 'parse_response')
        self.assertEqual(response.data['diagnostics']['exception_type'], 'ValueError')

    @patch('api.services.mission_service.active_rules_text', side_effect=RuntimeError('db failed'))
    @patch('api.services.mission_service.OpenAI')
    def test_rules_failure_precedes_openai(self, client, rules):
        response = self.request()
        self.assertEqual(response.data['diagnostics']['stage'], 'load_rules')
        self.assertNotIn('openai_elapsed_ms', response.data['diagnostics'])
        client.return_value.responses.create.assert_not_called()
