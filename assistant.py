"""Small chat helper. No key or chat is saved to a file."""
import json
import urllib.error
import urllib.request
from pathlib import Path

SETTINGS_PATH = Path(__file__).with_name("settings.json")
API_URL = "https://api.groq.com/openai/v1/chat/completions"


class ChatError(Exception):
    """An error that is safe to show without revealing a key."""


def load_settings():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    for field in ("name", "personality", "model"):
        if not isinstance(settings.get(field), str) or not settings[field].strip():
            raise ValueError("Settings need non-empty name, personality and model fields.")
    return settings


def build_messages(personality, history, prompt):
    # Keep the newest complete turns. Older chat stays visible but is not sent.
    messages = [{"role": "system", "content": personality}]
    recent = []
    remaining = 6000 - len(prompt)
    for i in range(len(history) - 2, -1, -2):
        pair = history[i:i + 2]
        if len(pair) != 2 or [m.get("role") for m in pair] != ["user", "assistant"]:
            continue
        size = sum(len(m["content"]) for m in pair)
        if size > remaining:
            break
        recent = pair + recent
        remaining -= size
    return messages + recent + [{"role": "user", "content": prompt}]


def get_reply(key, settings, history, prompt):
    payload = {"model": settings["model"],
               "messages": build_messages(settings["personality"], history, prompt),
               "temperature": 0.6, "max_completion_tokens": 768}
    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key.strip(),
                 "Content-Type": "application/json", "User-Agent": "PersonalAssistant/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.load(response)
        reply = result["choices"][0]["message"]["content"]
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Empty reply")
        return reply.strip()
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ChatError("Key or model access was rejected. Check your Groq key and free-plan model access.") from None
        if error.code == 429:
            raise ChatError("Groq's free limit is reached. Wait and try again later. Do not upgrade or add a card.") from None
        if error.code in (400, 404):
            raise ChatError("Groq could not use this request or model. Check the model in settings.json against Groq's supported models.") from None
        raise ChatError("Groq is unavailable right now. Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ChatError("Cannot reach Groq. Check your internet connection and try again.") from None
    except (KeyError, IndexError, ValueError, TypeError):
        raise ChatError("Groq returned an unreadable or empty reply. Try again.") from None
