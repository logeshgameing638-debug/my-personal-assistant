"""ARIA - your personal AI assistant. Run with: py -m streamlit run app.py"""
import hashlib
import inspect
import json
import os
from pathlib import Path
import streamlit as st
from assistant import (ALL_EXTENSIONS, ChatError, get_reply, load_settings,
                       research_reply, speak_text, transcribe_audio)
import portfolio
from portfolio import (PortfolioError, add_holding, allocation, holdings_csv,
                       load_portfolio, pnl_table, portfolio_summary_text,
                       remove_holding, transactions_csv)

CHATS_PATH = Path(__file__).with_name("chats.json")

st.set_page_config(page_title="Aria - Personal AI Assistant", layout="centered")

# Editorial light styling on top of the warm theme from .streamlit/config.toml.
# Original CSS written for this app (no third-party code); direction inspired by the
# MIT-licensed jmedia65/awesome-streamlit-themes "Editorial" preset (serif display,
# warm paper background). System fonts only, so nothing extra downloads on the laptop.
st.markdown("""<style>
/* Serif display headings over a warm paper canvas */
h1, h2, h3, [data-testid="stHeading"] {font-family: Georgia, "Times New Roman", serif !important;}

/* Masthead */
.aria-eyebrow {font-size: 11px; letter-spacing: .22em; text-transform: uppercase;
    color: #78716c; margin-bottom: 2px;}
.aria-wordmark {font-family: Georgia, "Times New Roman", serif; font-size: 46px;
    font-weight: 700; color: #1c1917; line-height: 1.05;}
.aria-tagline {font-size: 15px; color: #57534e; margin-top: 4px;}
.aria-rule {height: 3px; width: 72px; background: #c2410c;
    margin: 14px 0 6px 0; border-radius: 2px;}
@media (max-width: 480px) {.aria-wordmark {font-size: 34px;}}
.aria-page-head {font-family: Georgia, "Times New Roman", serif; font-size: 30px;
    font-weight: 700; color: #1c1917; line-height: 1.15; margin-bottom: 2px;}

/* Sidebar: warm rail with serif brand and the section menu */
section[data-testid="stSidebar"] {background: #f6f1e9; border-right: 1px solid #e7e0d4;}
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {font-family: Georgia, "Times New Roman", serif !important;}
.aria-side-brand {font-family: Georgia, "Times New Roman", serif; font-size: 27px;
    font-weight: 700; letter-spacing: .14em; color: #1c1917;}
.aria-side-sub {font-size: 12px; color: #78716c; margin-bottom: 10px;}
.aria-side-status {font-size: 11px; letter-spacing: .18em; text-transform: uppercase;
    color: #a8a29e; margin-top: 4px;}

/* Chat turns as paper cards */
[data-testid="stChatMessage"] {background: #ffffff; border: 1px solid #e9e2d6;
    border-radius: 14px; padding: 10px 14px; margin-bottom: 8px;
    box-shadow: 0 1px 2px rgba(28,25,23,.05);}

/* Pill buttons and rounded inputs */
.stButton button, [data-testid="stDownloadButton"] button {border-radius: 999px;
    border: 1px solid #d6cdbd; background: #ffffff; color: #292524;}
.stButton button:hover, [data-testid="stDownloadButton"] button:hover {
    border-color: #c2410c; color: #c2410c;}
.stTextInput input, .stSelectbox div[data-baseweb="select"], .stChatInput textarea {
    border-radius: 10px;}

/* Expanders and alerts as cards */
[data-testid="stExpander"] {background: #ffffff; border: 1px solid #e9e2d6; border-radius: 14px;}
[data-testid="stExpander"] summary {font-family: Georgia, "Times New Roman", serif; font-size: 1.05rem;}
[data-testid="stAlert"] {border-radius: 12px;}

/* Empty-state */
.aria-empty-head {font-family: Georgia, "Times New Roman", serif; font-size: 24px;
    color: #1c1917; margin: 6px 0 2px 0;}
.aria-empty-sub {font-size: 14px; color: #78716c; margin-bottom: 10px;}
</style>""", unsafe_allow_html=True)

try:
    settings = load_settings()
except (OSError, ValueError, json.JSONDecodeError):
    st.error("Cannot read settings.json. Restore the original file or fix its name, personality and model fields.")
    st.stop()


def load_chats():
    try:
        rows = json.loads(CHATS_PATH.read_text(encoding="utf-8"))
        if isinstance(rows, list):
            return [m for m in rows if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                    and isinstance(m.get("content"), str)]
    except (OSError, ValueError):
        pass
    return []


def save_chats(messages):
    try:
        CHATS_PATH.write_text(json.dumps(messages, indent=1), encoding="utf-8")
    except OSError:
        pass


@st.cache_data(ttl=120, show_spinner=False)
def cached_price(symbol):
    """One Yahoo call per symbol per 2 minutes, so reruns do not hammer the quote page."""
    return portfolio.fetch_price(symbol)


# Session memory belongs only to the open browser session unless saving is switched on.
if "messages" not in st.session_state:
    st.session_state.messages = []


# Streamlit deletes widget-keyed state when a page unmounts, so every setting is
# mirrored into a plain session key (the *_saved names), which survives page changes.
def current_key():
    return (st.session_state.get("groq_key_saved", "").strip()
            or os.environ.get("GROQ_API_KEY", "").strip())


def assistant_ready():
    return bool(current_key()) and bool(st.session_state.get("free_ok_saved"))


def chat_saving_on():
    return bool(st.session_state.get("save_chats_on_saved"))


def forget_key():
    st.session_state["groq_key_saved"] = ""


def queue_and_open_chat(text):
    st.session_state["queued_prompt"] = text
    st.switch_page(st.session_state["_aria_chat_page"])


def page_header(title, tagline):
    st.markdown('<div class="aria-eyebrow">Aria &middot; personal AI assistant</div>'
                '<div class="aria-page-head">' + title + '</div>'
                '<div class="aria-tagline">' + tagline + '</div>'
                '<div class="aria-rule"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- Chat page
def page_chat():
    key = current_key()
    ready = assistant_ready()
    st.markdown('<div class="aria-eyebrow">Personal AI assistant &middot; runs on your laptop</div>'
                '<div class="aria-wordmark">' + settings["name"] + '</div>'
                '<div class="aria-tagline">Chat, files, images, voice and basic web research, '
                'with online answers from Groq\'s free tier.</div>'
                '<div class="aria-rule"></div>', unsafe_allow_html=True)
    st.info("No full laptop control, account access or background listening. Attachments, voice and web results go to Groq only to answer that message. Do not send secrets or sensitive personal data.")
    if not ready:
        st.caption("The assistant is off until you add your free Groq key on the Settings page and tick the Free-plan box there.")
    if not st.session_state.messages:
        st.markdown('<div class="aria-empty-head">What would you like help with?</div>'
                    '<div class="aria-empty-sub">Pick a starter below, or type your own message. '
                    'For questions about the news, use the Research page.</div>',
                    unsafe_allow_html=True)
        s1, s2 = st.columns(2)
        if s1.button("Explain Python simply", disabled=not ready, width="stretch"):
            st.session_state["queued_prompt"] = "Explain Python simply, like I am new to coding."
            st.rerun()
        if s2.button("Summarize an attached PDF", disabled=not ready, width="stretch"):
            st.session_state["queued_prompt"] = "Please summarize the PDF I attach with this message."
            st.rerun()
        s3, s4 = st.columns(2)
        if s3.button("Describe an image", disabled=not ready, width="stretch"):
            st.session_state["queued_prompt"] = "Please describe the image I attach with this message."
            st.rerun()
        if s4.button("What is in the news today?", disabled=not ready, width="stretch"):
            st.session_state["queued_prompt"] = "What is in the news today? Give me a short roundup."
            st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    if st.session_state.get("last_audio") and not st.session_state.get("audio_played"):
        st.audio(st.session_state["last_audio"], format="audio/wav", autoplay=True)
        st.session_state["audio_played"] = True

    if len(st.session_state.messages) >= 2 and ready:
        if st.button("Regenerate last answer"):
            last_pair = st.session_state.messages[-2:]
            if [m["role"] for m in last_pair] == ["user", "assistant"]:
                st.session_state.messages = st.session_state.messages[:-2]
                if chat_saving_on():
                    save_chats(st.session_state.messages)
                st.session_state["queued_prompt"] = last_pair[0]["content"]
                st.session_state.pop("last_audio", None)
                st.rerun()

    st.caption("Recent chat is sent to Groq for context. Older messages may be left out. Restarting clears chat unless saving is on.")

    input_kwargs = {"placeholder": "Message your assistant", "max_chars": 2000,
                    "disabled": not ready}
    can_attach = "accept_file" in inspect.signature(st.chat_input).parameters
    if can_attach:
        incoming = st.chat_input(accept_file="multiple", file_type=ALL_EXTENSIONS, **input_kwargs)
    else:
        # Older Streamlit: text-only box plus a separate uploader.
        incoming = st.chat_input(**input_kwargs)
        st.info("Update Streamlit for the paperclip attach button: py -m pip install --upgrade streamlit")

    prompt = ""
    uploads = []
    if incoming:
        if hasattr(incoming, "text"):
            prompt = (incoming.text or "").strip()
            uploads = [(f.name, f.getvalue()) for f in (incoming.files or [])]
        else:
            prompt = str(incoming).strip()

    # Priority when nothing was typed: a queued question from another page, then a voice transcript.
    queued = st.session_state.pop("queued_prompt", None)
    if not prompt and queued:
        prompt = queued
    voice_prompt = st.session_state.pop("voice_prompt", "")
    if not prompt and voice_prompt:
        prompt = voice_prompt

    # A file chosen on the Files page joins this message. It stays attached until a message actually goes.
    path_attachment = st.session_state.get("path_attachment")
    if path_attachment and (prompt or uploads):
        uploads = uploads + [path_attachment]

    if prompt or uploads:
        if not prompt:
            prompt = "Please look at the attached file(s) and describe or summarize them."
        with st.chat_message("user"):
            st.markdown(prompt)
            for name, data in uploads:
                lower = name.lower()
                if lower.endswith((".png", ".jpg", ".jpeg", ".webp")) and len(data) <= 3_000_000:
                    st.image(data, caption=name, width=220)
                else:
                    st.caption("Attached: " + name)
        chat_model = st.session_state.get("model_pick") or "openai/gpt-oss-20b"
        try:
            placeholder = st.empty()
            pieces = []

            def on_token(piece):
                pieces.append(piece)
                placeholder.markdown("".join(pieces) + " ▌")

            reply = get_reply(key, settings, st.session_state.messages, prompt, uploads,
                              model=chat_model, on_token=on_token)
            placeholder.empty()
            voice_audio = None
            if st.session_state.get("voice_on_saved"):
                try:
                    voice_audio = speak_text(key, reply, voice=st.session_state.get("voice_name_saved", "troy"))
                except ChatError as voice_error:
                    st.caption(str(voice_error))
        except ChatError as error:
            st.error(str(error))
            st.caption("Your message was not added to memory. You can send it again.")
        else:
            if path_attachment and path_attachment in uploads:
                st.session_state.pop("path_attachment", None)
            shown = prompt
            if uploads:
                shown += "\n\n" + " ".join("[" + name + "]" for name, _ in uploads)
            st.session_state.messages.extend([
                {"role": "user", "content": shown}, {"role": "assistant", "content": reply}])
            # Bound session memory too, so very long chats do not grow forever.
            st.session_state.messages = st.session_state.messages[-40:]
            if chat_saving_on():
                save_chats(st.session_state.messages)
            if voice_audio:
                st.session_state["last_audio"] = voice_audio
                st.session_state["audio_played"] = False
            else:
                st.session_state.pop("last_audio", None)
            st.rerun()


# ------------------------------------------------------------ Research page
def page_research():
    page_header("Research", "Bounded web research before answering. Slower than chat, and basic on purpose.")
    st.caption("Aria fetches a few public pages for your question and sends short extracts to Groq. "
               "This is not deep research: it covers a handful of sources and can miss or misread pages. "
               "For anything important, check the sources yourself.")
    ready = assistant_ready()
    if not ready:
        st.caption("Add your free Groq key on the Settings page and tick the Free-plan box to use research.")
    query = st.text_input("Question to research", placeholder="What changed in Indian tax rules this year?",
                          disabled=not ready)
    picked = st.file_uploader("Attach files for this question (optional)", type=ALL_EXTENSIONS,
                              accept_multiple_files=True, disabled=not ready)
    pending = st.session_state.get("path_attachment")
    if pending:
        st.caption("The file you picked on the Files page (" + pending[0] + ") is included in this research run too.")
    if st.button("Research this question", disabled=not ready or not query.strip()):
        uploads = [(f.name, f.getvalue()) for f in (picked or [])]
        if pending:
            uploads = uploads + [pending]
        with st.spinner("Researching..."):
            try:
                reply = research_reply(current_key(), settings, [], query.strip(), uploads)
                st.session_state["research_result"] = (query.strip(), reply)
                # The research run consumed the Files-page attachment.
                if pending:
                    st.session_state.pop("path_attachment", None)
            except ChatError as error:
                st.error(str(error))
    result = st.session_state.get("research_result")
    if result:
        st.markdown("#### " + result[0])
        st.markdown(result[1])
        if st.button("Save this exchange to my chat history"):
            st.session_state.messages.extend([
                {"role": "user", "content": result[0]},
                {"role": "assistant", "content": result[1]}])
            st.session_state.messages = st.session_state.messages[-40:]
            if chat_saving_on():
                save_chats(st.session_state.messages)
            st.session_state.pop("research_result", None)
            st.success("Saved. Open the Chat page to continue from it.")


# --------------------------------------------------------------- Files page
def page_files():
    page_header("Files", "Attach laptop files to your next chat message. Only files you choose, read-only.")
    st.caption("You can attach: text, csv, json, code, Word (.docx), PDF, images (png, jpg, webp). Not Excel or zip files yet. "
               "The paperclip in the chat box also attaches files.")
    st.subheader("Pick a file from this laptop")
    st.caption("Type a path on this laptop. The app only reads what you ask for; it never changes or deletes files.")
    path_text = st.text_input("Folder or file path", placeholder=r"C:\Users\vijay\Documents")
    if path_text.strip():
        target = Path(path_text.strip().strip('"'))
        try:
            if target.is_dir():
                entries = sorted(target.iterdir(), key=lambda p: p.name.lower())[:100]
                for entry in entries:
                    kind = "folder" if entry.is_dir() else str(entry.stat().st_size) + " bytes"
                    st.write(("📁 " if entry.is_dir() else "📄 ") + entry.name + " — " + kind)
            elif target.is_file():
                if target.stat().st_size > 5_000_000:
                    st.error("That file is too big (over 5 MB).")
                elif st.button("Attach this file to my next message"):
                    st.session_state["path_attachment"] = (target.name, target.read_bytes())
                    st.success("Attached " + target.name + ". It will go with your next chat message or research question.")
            else:
                st.warning("No such file or folder. Check the path.")
        except (OSError, PermissionError):
            st.error("Windows would not let the app read that path.")
    pending = st.session_state.get("path_attachment")
    if pending:
        st.info("Ready to send with your next chat message or research question: " + pending[0])
        if st.button("Remove this attachment"):
            st.session_state.pop("path_attachment", None)
            st.rerun()
        if st.button("Open Chat to send it"):
            st.switch_page(st.session_state["_aria_chat_page"])


# --------------------------------------------------------------- Voice page
def page_voice():
    page_header("Voice", "Speak instead of typing, and hear answers read aloud.")
    st.caption("Voice in: free Whisper on Groq, understands Tamil and English. "
               "Voice out: free Orpheus on Groq, English only.")
    ready = assistant_ready()
    voices = ["troy", "hannah", "austin"]
    voice_on = st.checkbox("Read chat answers aloud", key="voice_on",
                           value=bool(st.session_state.get("voice_on_saved")))
    st.session_state["voice_on_saved"] = voice_on
    if voice_on:
        saved_voice = st.session_state.get("voice_name_saved", "troy")
        voice_name = st.selectbox("Voice", voices,
                                  index=voices.index(saved_voice) if saved_voice in voices else 0,
                                  key="voice_name")
        st.session_state["voice_name_saved"] = voice_name
    st.divider()
    if not ready:
        st.caption("Add your free Groq key on the Settings page and tick the Free-plan box to use voice.")
    if hasattr(st, "audio_input"):
        audio = st.audio_input("Record a message", disabled=not ready)
        if audio is not None:
            blob = audio.getvalue()
            heard_hash = hashlib.md5(blob).hexdigest()
            if blob and heard_hash != st.session_state.get("heard_hash"):
                try:
                    with st.spinner("Listening..."):
                        st.session_state["voice_transcript"] = transcribe_audio(
                            current_key(), blob, audio.name or "speech.wav")
                    st.session_state["heard_hash"] = heard_hash
                except ChatError as error:
                    st.session_state["heard_hash"] = heard_hash
                    st.error(str(error))
        transcript = st.session_state.get("voice_transcript", "")
        if transcript:
            st.caption("Heard (you can fix the words before sending):")
            edited = st.text_area("Transcript", value=transcript, label_visibility="collapsed")
            v1, v2 = st.columns(2)
            if v1.button("Send as my next chat message", disabled=not edited.strip(), width="stretch"):
                st.session_state.pop("voice_transcript", None)
                queue_and_open_chat(edited.strip())
            if v2.button("Discard", width="stretch"):
                st.session_state.pop("voice_transcript", None)
                st.rerun()
    else:
        st.info("This Streamlit version has no microphone input. Update with: py -m pip install --upgrade streamlit")
    if st.session_state.get("last_audio"):
        st.divider()
        st.caption("Last spoken reply from the assistant:")
        st.audio(st.session_state["last_audio"], format="audio/wav")


# ----------------------------------------------------------- Portfolio page
def page_portfolio():
    page_header("My portfolio", "Local holdings, analysis only. No trades, no broker login.")
    st.caption("Holdings are stored only on this laptop in portfolio.json - not in the cloud or on GitHub. Refreshing prices sends your stock symbols to Yahoo; prices can be delayed, so check your broker app before acting.")
    try:
        holdings = load_portfolio()
    except PortfolioError as error:
        holdings = []
        st.error(str(error))
    col1, col2, col3 = st.columns(3)
    new_symbol = col1.text_input("Symbol", placeholder="RELIANCE.NS", key="pf_symbol")
    new_qty = col2.text_input("Quantity", placeholder="10", key="pf_qty")
    new_buy = col3.text_input("Buy price", placeholder="2500", key="pf_buy")
    st.caption("Adding a symbol you already hold merges the two buys: quantities add and the buy price becomes the weighted average.")
    if st.button("Add to my holdings"):
        try:
            holdings = add_holding(new_symbol, new_qty, new_buy)
            st.session_state.pop("pf_result", None)
            st.success("Saved " + new_symbol.strip().upper())
        except PortfolioError as error:
            st.error(str(error))
    if holdings:
        if st.button("Refresh prices and P&L"):
            with st.spinner("Getting prices..."):
                st.session_state["pf_result"] = pnl_table(holdings, price_fn=cached_price)
        if st.session_state.get("pf_result"):
            lines, totals = st.session_state["pf_result"]
            st.dataframe([{ "Symbol": l["symbol"], "Qty": l["qty"], "Buy": round(l["buy_price"], 2),
                            "Now": (round(l["price"], 2) if l["price"] is not None else "unavailable"),
                            "P&L": (round(l["pnl"], 2) if l["pnl"] is not None else "—"),
                            "P&L %": (round(l["pnl_pct"], 1) if l["pnl_pct"] is not None else "—")}
                          for l in lines], width="stretch", hide_index=True)
            st.write("**Priced holdings only — invested %.2f, value %.2f, P&L %+.2f (%s)**" % (
                totals["invested"], totals["current"], totals["pnl"],
                ("%+.1f%%" % totals["pnl_pct"]) if totals["pnl_pct"] is not None else "—"))
            if totals["missing"]:
                st.warning("No live price for: " + ", ".join(totals["missing"])
                           + ". These are excluded from the totals above - the totals are not a loss on them. Use NSE symbols like RELIANCE.NS.")
            chart = allocation(lines)
            if len(chart) > 1:
                st.caption("Where your money is (holdings with a live price)")
                st.bar_chart(chart)
            st.caption("The button below sends your holdings summary to Groq for analysis.")
            if st.button("Ask the assistant about my portfolio", disabled=not assistant_ready()):
                queue_and_open_chat(
                    portfolio_summary_text(holdings, price_fn=cached_price)
                    + "\n\nPlease analyze this simply: what looks strong, what looks weak, and general learning points. Not financial advice.")
            dl1, dl2 = st.columns(2)
            dl1.download_button("Download holdings (CSV)", holdings_csv(holdings),
                                file_name="holdings.csv", mime="text/csv", width="stretch")
            dl2.download_button("Download activity log (CSV)", transactions_csv(),
                                file_name="transactions.csv", mime="text/csv", width="stretch")
            with st.expander("Activity log (starts from this upgrade; older buys are not in it)"):
                log = portfolio.load_transactions()
                if log:
                    for row in log[-10:][::-1]:
                        st.caption("%s — %s %s x%s @ %s" % (row.get("ts", ""), row.get("kind", ""),
                                                            row.get("symbol", ""), row.get("qty", ""),
                                                            row.get("buy_price", "")))
                else:
                    st.caption("No activity yet.")
        else:
            st.write(", ".join(r["symbol"] for r in holdings) + " — press Refresh prices and P&L.")
        drop = st.selectbox("Remove a holding", [""] + [r["symbol"] for r in holdings])
        if drop and st.button("Remove " + drop):
            holdings = remove_holding(drop)
            st.session_state.pop("pf_result", None)
            st.rerun()


# ------------------------------------------------------------ Settings page
def page_settings():
    page_header("Settings", "Your free Groq key, the AI brain, chat saving and app status.")
    st.subheader("Groq key")
    st.caption("Keep your Groq account on the Free plan. Never add billing for this app.")
    pasted = st.text_input("Groq API key", type="password", key="groq_key",
                           value=st.session_state.get("groq_key_saved", ""),
                           help="Paste it here on your own laptop, never in a message or GitHub file.")
    st.session_state["groq_key_saved"] = pasted
    key = current_key()
    st.caption("Key ready" if key else "Paste a key above, or set GROQ_API_KEY.")
    free_ok = st.checkbox("I checked: my Groq account is on the Free plan", key="free_ok",
                          value=bool(st.session_state.get("free_ok_saved")))
    st.session_state["free_ok_saved"] = free_ok
    st.caption("The app cannot check your billing plan. A paid account can incur charges.")
    st.divider()
    st.subheader("AI brain")
    model_choices = {"Fast (gpt-oss-20b)": "openai/gpt-oss-20b",
                     "Smart (gpt-oss-120b)": "openai/gpt-oss-120b",
                     "Qwen 3.8 (many languages)": "qwen/qwen3.8-27b"}
    labels = list(model_choices)
    saved_label = st.session_state.get("model_pick_label_saved", labels[0])
    picked = st.selectbox("AI brain (all free on Groq)", labels,
                          index=labels.index(saved_label) if saved_label in labels else 0,
                          key="model_pick_label")
    st.session_state["model_pick_label_saved"] = picked
    st.session_state["model_pick"] = model_choices[picked]
    st.caption("Images are always read by " + settings["vision_model"] + ". Voice settings live on the Voice page.")
    st.divider()
    st.subheader("Chat saving")
    save_on = st.checkbox("Save my chats on this laptop", key="save_chats_on",
                          value=bool(st.session_state.get("save_chats_on_saved")),
                          help="Off: chats vanish when the app restarts. On: stored in chats.json on this laptop only, never in the repo.")
    st.session_state["save_chats_on_saved"] = save_on
    if chat_saving_on():
        if not st.session_state.get("chats_loaded"):
            st.session_state.messages = load_chats()
            st.session_state["chats_loaded"] = True
        if st.button("Delete my saved chats", width="stretch"):
            CHATS_PATH.unlink(missing_ok=True)
            st.session_state.messages = []
            st.session_state.pop("last_audio", None)
            st.rerun()
    if st.button("Clear conversation", width="stretch"):
        st.session_state.messages = []
        st.session_state.pop("last_audio", None)
        if chat_saving_on():
            save_chats([])
        st.rerun()
    st.button("Forget pasted key", width="stretch", on_click=forget_key)
    st.caption("An environment-variable key stays until you remove it from your computer.")
    st.divider()
    st.markdown('<div class="aria-side-status">Status</div>', unsafe_allow_html=True)
    try:
        holding_count = len(load_portfolio())
    except PortfolioError:
        holding_count = 0
    st.caption("Groq key: " + ("ready" if key else "missing")
               + "  |  Brain: " + (st.session_state.get("model_pick") or "openai/gpt-oss-20b")
               + "  |  Voice replies: " + ("on" if st.session_state.get("voice_on_saved") else "off"))
    st.caption("Holdings: " + str(holding_count)
               + "  |  Chat this session: " + str(len(st.session_state.messages)) + " messages"
               + "  |  Chat saving: " + ("on" if chat_saving_on() else "off"))


# ------------------------------------------------------------------ Shell
chat_page = st.Page(page_chat, title="Chat", icon=":material/chat:", default=True)
research_page = st.Page(page_research, title="Research", icon=":material/travel_explore:")
files_page = st.Page(page_files, title="Files", icon=":material/attach_file:")
voice_page = st.Page(page_voice, title="Voice", icon=":material/mic:")
portfolio_page = st.Page(page_portfolio, title="Portfolio", icon=":material/show_chart:")
settings_page = st.Page(page_settings, title="Settings", icon=":material/settings:")
st.session_state["_aria_chat_page"] = chat_page

with st.sidebar:
    st.markdown('<div class="aria-side-brand">ARIA</div>'
                '<div class="aria-side-sub">Your personal AI assistant</div>', unsafe_allow_html=True)

nav = st.navigation([chat_page, research_page, files_page, voice_page, portfolio_page, settings_page])
nav.run()
