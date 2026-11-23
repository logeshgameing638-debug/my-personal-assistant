"""Tests never call the real API or use a real key."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from assistant import ChatError, build_messages, get_reply, load_settings


class AssistantTests(unittest.TestCase):
    def test_settings(self):
        self.assertEqual(load_settings()['model'], 'openai/gpt-oss-20b')

    def test_memory(self):
        history = [{'role': 'user', 'content': 'My name is Sam'},
                   {'role': 'assistant', 'content': 'Hello Sam'}]
        self.assertEqual(build_messages('Be kind', history, 'My name?')[1:3], history)

    def test_memory_budget(self):
        history = [{'role': 'user', 'content': 'a' * 4000},
                   {'role': 'assistant', 'content': 'b' * 4000}]
        self.assertEqual(len(build_messages('Be kind', history, 'Hello')), 2)

    def test_reply(self):
        response = io.BytesIO(json.dumps({'choices': [{'message': {'content': 'Hello!'}}]}).encode())
        with patch('urllib.request.urlopen', return_value=response) as call:
            self.assertEqual(get_reply('not-a-real-key', load_settings(), [], 'Hi'), 'Hello!')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['messages'][-1]['content'], 'Hi')

    def test_errors_do_not_expose_details(self):
        for status in [400, 401, 403, 404, 429, 500]:
            error = urllib.error.HTTPError('https://example.invalid', status, 'private-detail', {}, None)
            with patch('urllib.request.urlopen', side_effect=error):
                with self.assertRaises(ChatError) as caught:
                    get_reply('not-a-real-key', load_settings(), [], 'Hi')
                self.assertNotIn('private-detail', str(caught.exception))
                self.assertNotIn('not-a-real-key', str(caught.exception))

    def test_timeout(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            with self.assertRaises(ChatError):
                get_reply('not-a-real-key', load_settings(), [], 'Hi')

    def test_bad_response(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ChatError):
                get_reply('not-a-real-key', load_settings(), [], 'Hi')


if __name__ == '__main__':
    unittest.main()
