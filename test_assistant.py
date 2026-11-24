"""Tests never call the real API, the real web or a real key."""
import io
import json
import socket
import unittest
import urllib.error
import zipfile
from unittest.mock import patch
import assistant
from assistant import (ChatError, MAX_REPLY_TOKENS, build_messages, extract_docx_text,
                       fetch_page_text, get_reply, is_public_url, load_settings,
                       prepare_upload, research_reply, speak_text, strip_thinking,
                       transcribe_audio, web_search)
import portfolio
from portfolio import PortfolioError


def fake_response(content, finish="stop"):
    return io.BytesIO(json.dumps(
        {"choices": [{"message": {"content": content}, "finish_reason": finish}]}).encode())


def sse_response(pieces, finish="stop"):
    lines = b""
    for piece in pieces:
        lines += b'data: {"choices":[{"delta":{"content":' + json.dumps(piece).encode() + b'}}]}\n\n'
    lines += b'data: {"choices":[{"delta":{},"finish_reason":"' + finish.encode() + b'"}]}\n\ndata: [DONE]\n\n'
    return io.BytesIO(lines)


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
        self.assertNotIn('cannot browse the web', settings['personality'].replace('only discuss the web when', ''))

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
        with patch('urllib.request.urlopen', side_effect=[cut, error, error]), patch('time.sleep'):
            reply = get_reply('not-a-real-key', load_settings(), [], 'Hi')
        self.assertIn('partial answer', reply)
        self.assertIn('continue', reply)

    def test_streaming_tokens_and_final_text(self):
        with patch('urllib.request.urlopen',
                   return_value=sse_response(['Hel', 'lo ', 'world'])) as call:
            seen = []
            reply = get_reply('not-a-real-key', load_settings(), [], 'Hi', on_token=seen.append)
        self.assertEqual(''.join(seen), 'Hello world')
        self.assertEqual(reply, 'Hello world')
        data = json.loads(call.call_args.args[0].data)
        self.assertTrue(data['stream'])

    def test_model_fallback_when_rejected(self):
        rejected = urllib.error.HTTPError('https://example.invalid', 400, 'x', {}, None)
        with patch('urllib.request.urlopen', side_effect=[rejected, fake_response('Fallback works')]) as call:
            reply = get_reply('not-a-real-key', load_settings(), [], 'Hi')
        self.assertEqual(reply, 'Fallback works')
        second = json.loads(call.call_args_list[1].args[0].data)
        self.assertEqual(second['model'], 'openai/gpt-oss-120b')

    def test_one_retry_on_rate_limit(self):
        limited = urllib.error.HTTPError('https://example.invalid', 429, 'x', {}, None)
        with patch('urllib.request.urlopen', side_effect=[limited, fake_response('After retry')]) as call, \
                patch('time.sleep'):
            reply = get_reply('not-a-real-key', load_settings(), [], 'Hi')
        self.assertEqual(reply, 'After retry')
        self.assertEqual(call.call_count, 2)

    def test_text_file_goes_into_prompt(self):
        with patch('urllib.request.urlopen', return_value=fake_response('Summary')) as call:
            get_reply('not-a-real-key', load_settings(), [], 'Summarize',
                      uploads=[('notes.txt', b'hello world')])
        data = json.loads(call.call_args.args[0].data)
        last = data['messages'][-1]['content']
        self.assertIn('hello world', last)
        self.assertIn('notes.txt', last)

    def test_docx_text_extracted(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as zf:
            zf.writestr('word/document.xml',
                        '<w:body><w:p><w:r><w:t>Hello from Word</w:t></w:r></w:p>'
                        '<w:p><w:r><w:t>Second line</w:t></w:r></w:p></w:body>')
        text = extract_docx_text('doc.docx', buffer.getvalue())
        self.assertIn('Hello from Word', text)
        self.assertIn('Second line', text)
        kind, payload = prepare_upload('doc.docx', buffer.getvalue())
        self.assertEqual(kind, 'text')
        with self.assertRaises(ChatError):
            extract_docx_text('bad.docx', b'not a zip')

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

    def test_transcribe_filename_sanitized(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"text":"hi"}')) as call:
            transcribe_audio('not-a-real-key', b'RIFF', 'evil "name";\r\n.wav')
        body = call.call_args.args[0].data
        self.assertNotIn(b'evil "name"', body)
        self.assertIn(b'evil__name__', body)

    def test_speak_returns_audio(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'RIFFwavebytes')) as call:
            self.assertEqual(speak_text('not-a-real-key', 'Say hi'), b'RIFFwavebytes')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['model'], 'canopylabs/orpheus-v1-english')
        self.assertEqual(data['response_format'], 'wav')

    def test_speak_voice_choice(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'RIFF')) as call:
            speak_text('not-a-real-key', 'Say hi', voice='hannah')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['voice'], 'hannah')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'RIFF')) as call:
            speak_text('not-a-real-key', 'Say hi', voice='not-a-voice')
        data = json.loads(call.call_args.args[0].data)
        self.assertEqual(data['voice'], 'troy')

    def test_private_urls_rejected(self):
        for bad in ['http://example.com', 'https://localhost/x', 'https://127.0.0.1/x',
                    'https://192.168.1.5/x', 'https://10.0.0.2/x', 'not a url']:
            self.assertFalse(is_public_url(bad), bad)
            self.assertEqual(fetch_page_text(bad), '')

    def test_dns_rebinding_blocked(self):
        # Host resolves to a private address at check time: refused before any connection.
        private = [(socket.AF_INET, 2, 6, '', ('169.254.169.254', 0))]
        with patch('socket.getaddrinfo', return_value=private):
            self.assertFalse(is_public_url('https://sneaky.example.com'))
            self.assertEqual(fetch_page_text('https://sneaky.example.com/page'), '')

    def test_redirect_to_private_blocked(self):
        redirect = urllib.error.HTTPError('https://example.com', 302, 'x',
                                          {'Location': 'http://169.254.169.254/latest'}, None)
        with patch('assistant._public_addresses', return_value=[(socket.AF_INET, '93.184.216.34')]):
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = redirect
                self.assertEqual(assistant._fetch_checked('https://example.com/start'), b'')

    def test_safe_redirect_followed_and_revalidated(self):
        redirect = urllib.error.HTTPError('https://example.com', 302, 'x',
                                          {'Location': 'https://example.org/page2'}, None)
        with patch('assistant._public_addresses', return_value=[(socket.AF_INET, '93.184.216.34')]) as check:
            with patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = [redirect, _Ctx(b'<p>Final page</p>')]
                result = assistant._fetch_checked('https://example.com/start')
        self.assertEqual(result, b'<p>Final page</p>')
        self.assertEqual(check.call_count, 2)  # both hops validated

    def test_web_search_parses_results(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(SAMPLE_SEARCH_HTML.encode())):
            results = web_search('test query')
        self.assertEqual(results[0][0], 'Big news story')
        self.assertEqual(results[0][1], 'https://example.com/news')

    def test_research_fallback_uses_sources(self):
        tool_error = urllib.error.HTTPError('https://example.invalid', 400, 'x', {}, None)
        tool_error2 = urllib.error.HTTPError('https://example.invalid', 400, 'x', {}, None)
        pages = {'https://example.com/news': b'<html><body><p>Page facts here.</p></body></html>',
                 'https://example.org/other': b''}  # second page fails to open
        with patch('urllib.request.urlopen', side_effect=[tool_error, tool_error2, fake_response('Researched answer')]), \
                patch('assistant.web_search', return_value=[('Big news story', 'https://example.com/news'),
                                                            ('Other story', 'https://example.org/other')]), \
                patch('assistant._fetch_checked', side_effect=lambda url: pages.get(url, b'')):
            reply = research_reply('not-a-real-key', load_settings(), [], 'latest news')
        self.assertIn('Researched answer', reply)
        self.assertIn('actually read 1 page(s)', reply)
        self.assertIn('https://example.com/news', reply)

    def test_research_fallback_prompt_contains_page_text(self):
        tool_error = urllib.error.HTTPError('https://example.invalid', 400, 'x', {}, None)
        calls = []
        def fake_urlopen(request, timeout=0):
            calls.append(request)
            if len(calls) <= 1:
                raise tool_error
            return fake_response('Researched answer')
        with patch('urllib.request.urlopen', side_effect=fake_urlopen), \
                patch('assistant.web_search', return_value=[('Big news story', 'https://example.com/news')]), \
                patch('assistant._fetch_checked', return_value=b'<p>Page facts here.</p>'):
            reply = research_reply('not-a-real-key', load_settings(), [], 'latest news')
        sent = json.dumps(json.loads(calls[-1].data))
        self.assertIn('UNTRUSTED WEB PAGE', sent)
        self.assertIn('Page facts here.', sent)
        self.assertIn('actually read 1 page(s)', reply)

    def test_research_processes_text_attachment(self):
        with patch('urllib.request.urlopen', return_value=fake_response('Answer with file')) as call:
            reply = research_reply('not-a-real-key', load_settings(), [], 'What does my file say?',
                                   uploads=[('notes.txt', b'my secret shopping list')])
        self.assertIn('Answer with file', reply)
        sent = call.call_args.args[0].data.decode()
        self.assertIn('my secret shopping list', sent)
        data = json.loads(sent)
        self.assertEqual(data['tools'], [{'type': 'browser_search'}])

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
            with patch('urllib.request.urlopen', side_effect=error), patch('time.sleep'):
                with self.assertRaises(ChatError) as caught:
                    get_reply('not-a-real-key', load_settings(), [], 'Hi')
                self.assertNotIn('private-detail', str(caught.exception))
                self.assertNotIn('not-a-real-key', str(caught.exception))

    def test_timeout(self):
        with patch('urllib.request.urlopen', side_effect=TimeoutError()), patch('time.sleep'):
            with self.assertRaises(ChatError):
                get_reply('not-a-real-key', load_settings(), [], 'Hi')

    def test_bad_response(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ChatError):
                get_reply('not-a-real-key', load_settings(), [], 'Hi')


class _Ctx:
    """Context manager wrapper like a real HTTP response."""
    def __init__(self, data):
        self.data = data
    def read(self, n=-1):
        return self.data
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self._path = portfolio.PORTFOLIO_PATH
        self._tx = portfolio.TRANSACTIONS_PATH
        portfolio.PORTFOLIO_PATH = portfolio.Path('/tmp/test-portfolio.json')
        portfolio.TRANSACTIONS_PATH = portfolio.Path('/tmp/test-transactions.json')
        portfolio.PORTFOLIO_PATH.unlink(missing_ok=True)
        portfolio.TRANSACTIONS_PATH.unlink(missing_ok=True)
        portfolio.Path('/tmp/portfolio.backup.json').unlink(missing_ok=True)

    def tearDown(self):
        portfolio.PORTFOLIO_PATH.unlink(missing_ok=True)
        portfolio.TRANSACTIONS_PATH.unlink(missing_ok=True)
        portfolio.Path('/tmp/portfolio.backup.json').unlink(missing_ok=True)
        portfolio.PORTFOLIO_PATH = self._path
        portfolio.TRANSACTIONS_PATH = self._tx

    def test_add_and_load(self):
        portfolio.add_holding('reliance.ns', '10', '2500')
        rows = portfolio.load_portfolio()
        self.assertEqual(rows, [{'symbol': 'RELIANCE.NS', 'qty': 10.0, 'buy_price': 2500.0}])

    def test_add_to_existing_merges_weighted_average(self):
        portfolio.add_holding('A.NS', 10, 100)
        portfolio.add_holding('A.NS', 10, 200)
        rows = portfolio.load_portfolio()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['qty'], 20.0)
        self.assertAlmostEqual(rows[0]['buy_price'], 150.0)

    def test_backup_created_before_first_change(self):
        # An existing holdings file is copied to portfolio.backup.json before it is changed.
        portfolio.PORTFOLIO_PATH.write_text(json.dumps([{'symbol': 'OLD.NS', 'qty': 1, 'buy_price': 50}]))
        portfolio.add_holding('OLD.NS', 1, 60)
        backup = portfolio.Path('/tmp/portfolio.backup.json')
        self.assertTrue(backup.exists())
        self.assertEqual(json.loads(backup.read_text())[0]['buy_price'], 50)  # original preserved

    def test_nan_and_infinity_rejected(self):
        for bad in [float('nan'), float('inf'), float('-inf')]:
            with self.assertRaises(PortfolioError):
                portfolio.add_holding('OK.NS', bad, 1)
            with self.assertRaises(PortfolioError):
                portfolio.add_holding('OK.NS', 1, bad)

    def test_bad_inputs_rejected(self):
        for symbol, qty, buy in [('', '1', '1'), ('BAD SYMBOL!', '1', '1'),
                                 ('OK.NS', '0', '1'), ('OK.NS', '1', '-5'), ('OK.NS', 'x', '1')]:
            with self.assertRaises(PortfolioError):
                portfolio.add_holding(symbol, qty, buy)

    def test_remove(self):
        portfolio.add_holding('A.NS', 1, 100)
        portfolio.remove_holding('A.NS')
        self.assertEqual(portfolio.load_portfolio(), [])

    def test_transactions_logged(self):
        portfolio.add_holding('A.NS', 10, 100)
        portfolio.add_holding('A.NS', 5, 120)
        portfolio.remove_holding('A.NS')
        log = portfolio.load_transactions()
        self.assertEqual([r['kind'] for r in log], ['buy', 'buy', 'remove'])
        self.assertEqual(log[0]['qty'], 10.0)
        csv_text = portfolio.transactions_csv()
        self.assertIn('A.NS', csv_text)
        self.assertIn('remove', csv_text)

    def test_pnl_math(self):
        portfolio.add_holding('A.NS', 10, 100)
        quote = {'chart': {'result': [{'meta': {'regularMarketPrice': 120.0}}]}}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(quote).encode())):
            lines, totals = portfolio.pnl_table(portfolio.load_portfolio())
        self.assertEqual(lines[0]['pnl'], 200.0)
        self.assertEqual(lines[0]['pnl_pct'], 20.0)
        self.assertEqual(totals['invested'], 1000.0)
        self.assertEqual(totals['current'], 1200.0)

    def test_broken_quotes_are_unavailable_not_losses(self):
        for bad_price in [0, -5, None]:
            quote = {'chart': {'result': [{'meta': {'regularMarketPrice': bad_price}}]}}
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(quote).encode())):
                self.assertIsNone(portfolio.fetch_price('A.NS'), bad_price)

    def test_price_failure_is_honest(self):
        portfolio.add_holding('A.NS', 10, 100)
        with patch('urllib.request.urlopen', side_effect=TimeoutError()):
            lines, totals = portfolio.pnl_table(portfolio.load_portfolio())
        self.assertIsNone(lines[0]['price'])
        self.assertIn('A.NS', totals['missing'])

    def test_totals_exclude_missing_prices(self):
        portfolio.add_holding('A.NS', 10, 100)   # will be priced at 120
        portfolio.add_holding('B.NS', 10, 500)   # price unavailable
        quote = {'chart': {'result': [{'meta': {'regularMarketPrice': 120.0}}]}}

        def fake_urlopen(request, timeout=0):
            if 'A.NS' in request.full_url:
                return io.BytesIO(json.dumps(quote).encode())
            raise TimeoutError()

        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            lines, totals = portfolio.pnl_table(portfolio.load_portfolio())
        self.assertEqual(totals['missing'], ['B.NS'])
        self.assertEqual(totals['invested'], 1000.0)   # only A counted
        self.assertEqual(totals['current'], 1200.0)
        self.assertEqual(totals['pnl'], 200.0)         # not -4800: B is excluded, not a loss
        self.assertIn('B.NS', [l['symbol'] for l in lines if l['price'] is None])

    def test_holdings_csv(self):
        portfolio.add_holding('A.NS', 10, 100)
        text = portfolio.holdings_csv(portfolio.load_portfolio())
        self.assertIn('symbol,qty,buy_price,invested', text)
        self.assertIn('A.NS', text)

    def test_allocation_only_priced(self):
        lines = [{'symbol': 'A.NS', 'value': 1200.0}, {'symbol': 'B.NS', 'value': None}]
        self.assertEqual(portfolio.allocation(lines), {'A.NS': 1200.0})


if __name__ == '__main__':
    unittest.main()
