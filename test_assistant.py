"""Tests never call the real API, the real web or a real key."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from assistant import (ChatError, MAX_REPLY_TOKENS, build_messages, fetch_page_text,
                       get_reply, is_public_url, load_settings, prepare_upload,
                       research_reply, speak_text, strip_thinking, transcribe_audio,
                       web_search)
import portfolio
from portfolio import PortfolioError


def fake_response(content, finish="stop"):
    return io.BytesIO(json.dumps(
        {"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode())


SAMPLE_SEARCH_HTML = """
<html><body>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fnews">Big news story</a>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fother">Other story</a>
</body></html>
"""


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

    def test_transcribe_sends_multipart(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"text":"hello there"}')) as call:
            self.assertEqual(transcribe_audio('not-a-real-key', b'RIFF....'), 'hello there')
        body = call.call_args.args[0].data
        self.assertIn(b'whisper-large-v3-turbo', body)
        self.assertIn(b'RIFF....', body)

    def test_speak_returns_audio(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'RIFFwavebytes')) as call:
            self.assertEqual(speak_text('not-a-real-key', 'Say hi'), b'RIFFwavebytes')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['model'], 'canopylabs/orpheus-v1-english')
        self.assertEqual(data['response_format'], 'wav')

    def test_private_urls_rejected(self):
        for bad in ['http://example.com', 'https://localhost/x', 'https://127.0.0.1/x',
                    'https://192.168.1.5/x', 'https://10.0.0.2/x', 'not a url']:
            self.assertFalse(is_public_url(bad), bad)
            self.assertEqual(fetch_page_text(bad), '')

    def test_web_search_parses_results(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(SAMPLE_SEARCH_HTML.encode())):
            results = web_search('test query')
        self.assertEqual(results[0][0], 'Big news story')
        self.assertEqual(results[0][1], 'https://example.com/news')

    def test_research_fallback_uses_sources(self):
        tool_error = urllib.error.HTTPError('https://example.invalid', 400, 'x', {}, None)
        with patch('urllib.request.urlopen') as call:
            call.side_effect = [tool_error,                                   # browser search rejected
                                io.BytesIO(SAMPLE_SEARCH_HTML.encode()),      # duckduckgo
                                io.BytesIO(b'<html><body><p>Page facts here.</p></body></html>'),  # page 1
                                io.BytesIO(b'<html><body><p>More facts.</p></body></html>'),       # page 2
                                fake_response('Researched answer')]
            with patch('assistant.is_public_url', return_value=True):
                reply = research_reply('not-a-real-key', load_settings(), [], 'latest news')
        self.assertIn('Researched answer', reply)
        self.assertIn('Basic web research', reply)
        last_payload = json.loads(call.call_args.args[0].data)
        sent = json.dumps(last_payload)
        self.assertIn('UNTRUSTED WEB PAGE', sent)
        self.assertIn('Page facts here.', sent)

    def test_research_browser_search_first(self):
        with patch('urllib.request.urlopen', return_value=fake_response('Fresh answer')) as call:
            reply = research_reply('not-a-real-key', load_settings(), [], 'news today')
        self.assertIn('Fresh answer', reply)
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['tools'], [{'type': 'browser_search'}])
        self.assertEqual(data['model'], 'openai/gpt-oss-120b')

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


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self._path = portfolio.PORTFOLIO_PATH
        portfolio.PORTFOLIO_PATH = portfolio.Path('/tmp/test-portfolio.json')
        portfolio.PORTFOLIO_PATH.unlink(missing_ok=True)

    def tearDown(self):
        portfolio.PORTFOLIO_PATH.unlink(missing_ok=True)
        portfolio.PORTFOLIO_PATH = self._path

    def test_add_and_load(self):
        portfolio.add_holding('reliance.ns', '10', '2500')
        rows = portfolio.load_portfolio()
        self.assertEqual(rows, [{'symbol': 'RELIANCE.NS', 'qty': 10.0, 'buy_price': 2500.0}])

    def test_bad_inputs_rejected(self):
        for symbol, qty, buy in [('', '1', '1'), ('BAD SYMBOL!', '1', '1'),
                                 ('OK.NS', '0', '1'), ('OK.NS', '1', '-5'), ('OK.NS', 'x', '1')]:
            with self.assertRaises(PortfolioError):
                portfolio.add_holding(symbol, qty, buy)

    def test_remove(self):
        portfolio.add_holding('A.NS', 1, 100)
        portfolio.remove_holding('A.NS')
        self.assertEqual(portfolio.load_portfolio(), [])

    def test_pnl_math(self):
        portfolio.add_holding('A.NS', 10, 100)
        quote = {'chart': {'result': [{'meta': {'regularMarketPrice': 120.0}}]}}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(quote).encode())):
            lines, totals = portfolio.pnl_table(portfolio.load_portfolio())
        self.assertEqual(lines[0]['pnl'], 200.0)
        self.assertEqual(totals['invested'], 1000.0)
        self.assertEqual(totals['current'], 1200.0)

    def test_price_failure_is_honest(self):
        portfolio.add_holding('A.NS', 10, 100)
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            lines, totals = portfolio.pnl_table(portfolio.load_portfolio())
        self.assertIsNone(lines[0]['price'])
        self.assertIn('A.NS', totals['missing'])


if __name__ == '__main__':
    unittest.main()
