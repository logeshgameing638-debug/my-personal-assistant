"""Tests never call the real API or use a real key."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from assistant import (ChatError, MAX_REPLY_TOKENS, build_messages, get_reply,
                       load_settings, prepare_upload, strip_thinking)


def fake_response(content, finish="stop"):
    return io.BytesIO(json.dumps(
        {"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode())


class AssistantTests(unittest.TestCase):
    def test_settings(self):
        settings = load_settings()
        self.assertEqual(settings['model'], 'openai/gpt-oss-20b')
        self.assertTrue(settings['vision_model'])

    def test_memory(self):
        history = [{'role': 'user', 'content': 'My name is Sam'},
                   {'role': 'assistant', 'content': 'Hello Sam'}]
        self.assertEqual(build_messages('Be kind', history, 'My name?')[1:3], history)

    def test_memory_budget(self):
        history = [{'role': 'user', 'content': 'a' * 4000},
                   {'role': 'assistant', 'content': 'b' * 4000}]
        self.assertEqual(len(build_messages('Be kind', history, 'Hello')), 2)

    def test_reply_token_cap_raised(self):
        with patch('urllib.request.urlopen', return_value=fake_response('Hello!')) as call:
            self.assertEqual(get_reply('not-a-real-key', load_settings(), [], 'Hi'), 'Hello!')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['messages'][-1]['content'], 'Hi')
        self.assertEqual(data['max_completion_tokens'], MAX_REPLY_TOKENS)

    def test_long_answer_auto_continues(self):
        cut = fake_response('def f(x): return', finish='length')
        rest = fake_response('x * 2', finish='stop')
        with patch('urllib.request.urlopen', side_effect=[cut, rest]) as call, \
                patch('time.sleep'):
            reply = get_reply('not-a-real-key', load_settings(), [], 'code please')
        self.assertEqual(reply, 'def f(x): return\nx * 2')
        self.assertEqual(call.call_count, 2)

    def test_continuation_failure_keeps_partial(self):
        cut = fake_response('partial answer', finish='length')
        error = urllib.error.HTTPError('https://example.invalid', 429, 'x', {}, None)
        with patch('urllib.request.urlopen', side_effect=[cut, error]), patch('time.sleep'):
            reply = get_reply('not-a-real-key', load_settings(), [], 'Hi')
        self.assertIn('partial answer', reply)
        self.assertIn('continue', reply)

    def test_text_file_goes_into_prompt(self):
        with patch('urllib.request.urlopen', return_value=fake_response('Summary')) as call:
            get_reply('not-a-real-key', load_settings(), [], 'Summarize',
                      uploads=[('notes.txt', b'hello world')])
        data = json.loads(call.call_args.args[0].data)
        last = data['messages'][-1]['content']
        self.assertIn('hello world', last)
        self.assertIn('notes.txt', last)

    def test_image_uses_vision_model(self):
        with patch('urllib.request.urlopen', return_value=fake_response('A cat')) as call:
            get_reply('not-a-real-key', load_settings(), [], 'What is this?',
                      uploads=[('cat.png', b'\x89PNG\r\n\x1a\n' + b'0' * 100)])
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['model'], load_settings()['vision_model'])
        content = data['messages'][-1]['content']
        self.assertEqual(content[0]['type'], 'text')
        self.assertEqual(content[1]['type'], 'image_url')
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_big_image_rejected(self):
        with self.assertRaises(ChatError):
            prepare_upload('big.jpg', b'0' * 3_500_000)

    def test_unsupported_file_rejected(self):
        with self.assertRaises(ChatError) as caught:
            prepare_upload('sheet.xlsx', b'0' * 10)
        self.assertIn('xlsx', str(caught.exception))

    def test_too_many_images_rejected(self):
        uploads = [('a.png', b'0' * 10)] * 4
        with self.assertRaises(ChatError):
            get_reply('not-a-real-key', load_settings(), [], 'Hi', uploads)

    def test_strip_thinking(self):
        self.assertEqual(strip_thinking('<think>secret work</think>Real answer'), 'Real answer')

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
