"""Small chat helper. No key, chat or uploaded file is saved to disk."""
import base64
import io
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SETTINGS_PATH = Path(__file__).with_name("settings.json")
API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_VISION_MODEL = "qwen/qwen3.8-27b"

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".py", ".log",
                   ".yaml", ".yml", ".html", ".css", ".js", ".ts"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ALL_EXTENSIONS = sorted(TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {".pdf"})
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 3_000_000  # base64 grows this ~33%; stay under Groq's free image limit
MAX_FILE_CHARS = 8000
MAX_REPLY_TOKENS = 6144       # far above the old 768 that cut long code answers
CONTINUATION_TOKENS = 4096
CONTINUATION_WAIT_SECONDS = 20  # free plan allows 8K tokens per minute


class ChatError(Exception):
    """An error that is safe to show without revealing a key."""


def load_settings():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    for field in ("name", "personality", "model"):
        if not isinstance(settings.get(field), str) or not settings[field].strip():
            raise ValueError("Settings need non-empty name, personality and model fields.")
    vision = settings.get("vision_model")
    if not isinstance(vision, str) or not vision.strip():
        settings["vision_model"] = DEFAULT_VISION_MODEL
    return settings


def truncate_text(text, limit=MAX_FILE_CHARS):
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[file cut here: only this first part is sent]"


def extract_pdf_text(name, data):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ChatError("PDF reading needs one more install. Run: py -m pip install pypdf  then restart the app.") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(reader.pages[i].extract_text() or "") for i in range(min(len(reader.pages), 20))]
    except Exception:
        raise ChatError("I could not read that PDF (" + str(name) + "). Try a text file or a different PDF.") from None
    text = "\n".join(pages).strip()
    if not text:
        raise ChatError("That PDF (" + str(name) + ") has no readable text. It may be only photos of pages, which I cannot read yet.")
    return truncate_text(text)


def prepare_upload(name, data):
    """Return (kind, payload): kind is 'text' or 'image'. Raises ChatError with a safe message."""
    ext = Path(name or "file").suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        if len(data) > MAX_IMAGE_BYTES:
            raise ChatError(str(name) + " is too big for the free image limit. Please use an image under 3 MB.")
        mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
        return "image", "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
    if ext == ".pdf":
        return "text", extract_pdf_text(name, data)
    if ext in TEXT_EXTENSIONS:
        return "text", truncate_text(data.decode("utf-8", errors="replace"))
    raise ChatError("I cannot read " + (ext or "this") + " files yet. You can attach text, csv, json, code, PDF, or an image (png, jpg, webp).")


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


def strip_thinking(text):
    # Some models wrap rough work in <think> tags. Never show that to the user.
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def post_completion(key, payload):
    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + key.strip(),
                 "Content-Type": "application/json", "User-Agent": "PersonalAssistant/1.1"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.load(response)
        choice = result["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty reply")
        return content.strip(), choice.get("finish_reason")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ChatError("Key or model access was rejected. Check your Groq key and free-plan model access.") from None
        if error.code == 429:
            raise ChatError("Groq's free limit is reached. Wait a minute and try again. Do not upgrade or add a card.") from None
        if error.code in (400, 404, 413, 422):
            raise ChatError("Groq could not use this request or model. The file may be too large, or the model in settings.json may be wrong.") from None
        raise ChatError("Groq is unavailable right now. Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ChatError("Cannot reach Groq. Check your internet connection and try again.") from None
    except (KeyError, IndexError, ValueError, TypeError):
        raise ChatError("Groq returned an unreadable or empty reply. Try again.") from None


def get_reply(key, settings, history, prompt, uploads=(), model=None):
    """uploads is a list of (filename, bytes). model overrides the chat model.
    Returns the visible reply text."""
    images = []
    text_parts = []
    for name, data in uploads:
        kind, payload = prepare_upload(name, data)
        if kind == "image":
            images.append(payload)
        else:
            text_parts.append("--- Start of file: " + name + " ---\n" + payload + "\n--- End of file: " + name + " ---")
    if len(images) > MAX_IMAGES:
        raise ChatError("You can send at most " + str(MAX_IMAGES) + " images in one message on the free plan.")

    full_prompt = prompt
    if text_parts:
        full_prompt = "\n\n".join(text_parts) + "\n\n" + prompt

    if images:
        # Images need the vision model. File text travels with the same message.
        content = [{"type": "text", "text": full_prompt}]
        content += [{"type": "image_url", "image_url": {"url": url}} for url in images]
        messages = [{"role": "system", "content": settings["personality"]},
                    {"role": "user", "content": content}]
        model = settings["vision_model"]
    else:
        messages = build_messages(settings["personality"], history, full_prompt)
        model = model or settings["model"]

    payload = {"model": model, "messages": messages,
               "temperature": 0.6, "max_completion_tokens": MAX_REPLY_TOKENS}
    reply, finish = post_completion(key, payload)

    # Long answers (like full code) can still hit the token cap. Ask for the
    # rest once, after a short wait so the free per-minute limit can recover.
    if finish == "length":
        partial = reply
        time.sleep(CONTINUATION_WAIT_SECONDS)
        try:
            more_messages = messages + [
                {"role": "assistant", "content": partial},
                {"role": "user", "content": "Continue exactly where you stopped. Do not repeat anything."}]
            more, _ = post_completion(key, {"model": model, "messages": more_messages,
                                            "temperature": 0.6,
                                            "max_completion_tokens": CONTINUATION_TOKENS})
            reply = partial.rstrip() + "\n" + more.lstrip()
        except ChatError:
            reply = partial + "\n\n_(The free limit cut this answer. Send 'continue' to get the rest.)_"

    reply = strip_thinking(reply)
    if not reply:
        raise ChatError("Groq returned an empty reply. Try again.")
    return reply
