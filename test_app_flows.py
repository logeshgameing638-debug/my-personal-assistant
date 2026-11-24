"""Cross-page UI flow tests for app.py. Groq calls are mocked; no network, no key needed.

Covers the flows that move between the six pages: starter buttons, voice transcript
send-once, queued prompts, and consent-based chat saving.
"""
import json
from pathlib import Path

import pytest

import assistant

CHATS = Path(__file__).with_name("chats.json")


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _mock_get_reply(key, settings, messages, prompt, uploads=(), model=None, on_token=None):
    text = "MOCK[" + str(model) + "] reply to: " + prompt[:60]
    if on_token:
        on_token(text)
    return text


def _mock_research_reply(key, settings, history, prompt, uploads=()):
    names = ",".join(n for n, _ in uploads) or "none"
    return "MOCK RESEARCH q=" + prompt[:50] + " atts=" + names


@pytest.fixture()
def at_factory(monkeypatch):
    # AppTest loads its own copy of app.py, so patch the shared assistant module
    # and clean the real chats.json around each test instead of patching paths.
    monkeypatch.setattr(assistant, "get_reply", _mock_get_reply)
    monkeypatch.setattr(assistant, "research_reply", _mock_research_reply)
    monkeypatch.setattr(assistant, "speak_text", lambda *a, **k: None)
    monkeypatch.setattr(assistant, "transcribe_audio", lambda k, b, n: "mock words")

    from streamlit.testing.v1 import AppTest
    CHATS.unlink(missing_ok=True)

    def make():
        at = AppTest.from_file("app.py", default_timeout=30)
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        at.session_state["groq_key_saved"] = "gsk_mock"
        at.session_state["free_ok_saved"] = True
        at.run()
        assert not at.exception, [str(e.value) for e in at.exception]
        return at

    yield make
    CHATS.unlink(missing_ok=True)


def _user_texts(at):
    return [m["content"] for m in at.session_state["messages"] if m["role"] == "user"]


def test_starter_button_sends_once(at_factory):
    at = at_factory()
    _button(at, "Explain Python simply").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert _user_texts(at) == ["Explain Python simply, like I am new to coding."]
    assert "MOCK[openai/gpt-oss-20b]" in at.session_state["messages"][1]["content"]
    # Further reruns must not resend it.
    at.run()
    assert _user_texts(at) == ["Explain Python simply, like I am new to coding."]


def test_voice_prompt_consumed_once(at_factory):
    at = at_factory()
    at.session_state["voice_prompt"] = "voice message once"
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert _user_texts(at) == ["voice message once"]
    at.run()
    at.run()
    assert _user_texts(at) == ["voice message once"]


def test_queued_prompt_consumed_once(at_factory):
    at = at_factory()
    at.session_state["queued_prompt"] = "queued question once"
    at.run()
    assert _user_texts(at) == ["queued question once"]
    at.run()
    assert _user_texts(at) == ["queued question once"]


def test_model_choice_reaches_reply(at_factory):
    at = at_factory()
    at.session_state["model_pick"] = "openai/gpt-oss-120b"
    at.session_state["queued_prompt"] = "model check"
    at.run()
    assert "MOCK[openai/gpt-oss-120b]" in at.session_state["messages"][1]["content"]


def test_chat_saving_writes_file(at_factory):
    at = at_factory()
    at.session_state["save_chats_on_saved"] = True
    at.session_state["queued_prompt"] = "remember this question"
    at.run()
    saved = json.loads(CHATS.read_text(encoding="utf-8"))
    contents = [m["content"] for m in saved]
    assert "remember this question" in contents
    assert any(m["role"] == "assistant" and "MOCK[" in m["content"] for m in saved)


def test_sending_blocked_without_key(at_factory):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app.py", default_timeout=30)
    at.run()
    starters = [b for b in at.button if b.label == "Explain Python simply"]
    assert starters and starters[0].disabled is True
    assert at.chat_input[0].disabled is True
