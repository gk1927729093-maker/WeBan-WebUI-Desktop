import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from client import WeBanClient


def response(status, body):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(body).encode()
    result.url = 'https://example.invalid/chat/completions'
    return result


class AIRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(WeBanClient)
        self.client.ai_config = {'enable': True, 'api_key': 'AI_TEST_KEY',
                                 'base_url': 'https://example.invalid', 'model': 'test-model',
                                 'timeout': 5, 'max_retries': 2}
        self.client._ai_disabled_reason = ''
        self.client._ai_key_warned = False
        self.client.log = Mock()
        self.client.api = SimpleNamespace(session=Mock())
        self.question = {'title': '测试题', 'typeLabel': '单选题',
                         'optionList': [{'id': 'A', 'content': '选项一'}, {'id': 'B', 'content': '选项二'}]}
        self.good_response = response(200, {'choices': [{'message': {'content': '{"answers":[1]}'}}]})

    def test_ai_request_does_not_use_learning_session(self):
        with patch('client.requests.post', return_value=self.good_response) as request:
            self.assertEqual(self.client._ai_search_question(self.question), ['A'])
        self.client.api.session.post.assert_not_called()
        headers = request.call_args.kwargs['headers']
        self.assertEqual(set(headers), {'Authorization', 'Content-Type'})

    def test_quota_failure_stops_retries_for_current_account(self):
        exhausted = response(429, {'error': {'type': 'FreeUsageLimitError', 'message': 'Free usage limit reached'}})
        with patch('client.requests.post', return_value=exhausted) as request, patch('client.time.sleep') as sleep:
            self.assertEqual(self.client._ai_search_question(self.question), [])
            self.assertEqual(self.client._ai_search_question(self.question), [])
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()
        self.assertIn('额度', self.client._ai_disabled_reason)

    def test_retired_model_is_reported_without_repeated_calls(self):
        retired = response(400, {'error': {'message': 'Upstream request failed: Model is unavailable.'}})
        with patch('client.requests.post', return_value=retired) as request:
            self.assertEqual(self.client._ai_search_question(self.question), [])
            self.assertEqual(request.call_count, 1)
        self.assertIn('模型', self.client._ai_disabled_reason)

    def test_temporary_server_error_can_recover(self):
        with patch('client.requests.post', side_effect=[response(503, {}), self.good_response]) as request, patch('client.time.sleep'):
            self.assertEqual(self.client._ai_search_question(self.question), ['A'])
            self.assertEqual(request.call_count, 2)

    def test_empty_reasoning_response_does_not_crash(self):
        empty = response(200, {'choices': [{'message': {'content': None}}]})
        with patch('client.requests.post', return_value=empty), patch('client.time.sleep'):
            self.assertEqual(self.client._ai_search_question(self.question), [])


if __name__ == '__main__':
    unittest.main()
