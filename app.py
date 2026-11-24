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

st.set_page_config(page_title="Aria - Personal AI Assistant", page_icon="✨", layout="centered")

# Selective premium styling on top of the dark theme from .streamlit/config.toml.
st.markdown("""<style>
[data-testid="stChatMessage"] {border-radius: 14px; padding: 10px 14px; margin-bottom: 6px;
    border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.03);}
section[data-testid="stSidebar"] {background: linear-gradient(180deg, #101623 0%, #0b0f17 100%);}
section[data-testid="stSidebar"] .stButton button {border-radius: 10px;}
.stButton button {border-radius: 10px;}
[data-testid="stExpander"] {border-radius: 12px; border: 1px solid rgba(255,255,255,0.08);}
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


def forget_key():
    st.session_state["groq_key"] = ""


with st.sidebar:
    st.title("✨ ARIA")
    st.caption("Your personal AI assistant")
    st.caption("Keep your Groq account on the Free plan. Never add billing for this app.")
    pasted_key = st.text_input("Groq API key", type="password", key="groq_key",
                               help="Paste it here on your own laptop, never in a message or GitHub file.")
    key = pasted_key.strip() or os.environ.get("GROQ_API_KEY", "").strip()
    st.caption("Key ready" if key else "Paste a key above, or set GROQ_API_KEY.")
    free_ok = st.checkbox("I checked: my Groq account is on the Free plan")
    st.caption("The app cannot check your billing plan. A paid account can incur charges.")
    st.divider()
    model_choices = {"Fast (gpt-oss-20b)": "openai/gpt-oss-20b",
                     "Smart (gpt-oss-120b)": "openai/gpt-oss-120b",
                     "Qwen 3.8 (many languages)": "qwen/qwen3.8-27b"}
    picked = st.selectbox("AI brain (all free on Groq)", list(model_choices))
    chat_model = model_choices[picked]
    research_on = st.checkbox("Research the web first (slower, basic)")
    voice_on = st.checkbox("Read answers aloud")
    voice_name = "troy"
    if voice_on:
        voice_name = st.selectbox("Voice", ["troy", "hannah", "austin"])
    st.caption("Images are always read by " + settings["vision_model"] + ". Voice uses free Whisper (in) and Orpheus (out, English only).")
    st.caption("You can attach: text, csv, json, code, Word (.docx), PDF, images (png, jpg, webp). Not Excel or zip files yet.")
    st.divider()
    save_chats_on = st.checkbox("Save my chats on this laptop", value=False,
                                help="Off: chats vanish when the app restarts. On: stored in chats.json on this laptop only, never in the repo.")
    if save_chats_on:
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
        if save_chats_on:
            save_chats([])
        st.rerun()
    st.button("Forget pasted key", width="stretch", on_click=forget_key)
    st.caption("An environment-variable key stays until you remove it from your computer.")
    st.divider()
    st.subheader("Status")
    try:
        holding_count = len(load_portfolio())
    except PortfolioError:
        holding_count = 0
    st.caption("Groq key: " + ("ready" if key else "missing")
               + "  |  Brain: " + chat_model
               + "  |  Research: " + ("on" if research_on else "off"))
    st.caption("Holdings: " + str(holding_count)
               + "  |  Chat this session: " + str(len(st.session_state.messages)) + " messages"
               + "  |  Chat saving: " + ("on" if save_chats_on else "off"))

st.title("✨ " + settings["name"] + ", your personal assistant")
st.caption("Chat, files, images, voice and basic web research. Runs on your laptop, with online answers from Groq.")
st.info("No full laptop control, account access or background listening. Attachments, voice and web results go to Groq only to answer that message. Do not send secrets or sensitive personal data.")
if not st.session_state.messages:
    st.markdown("### What would you like help with?")
    st.write("Try: Explain Python simply, summarize an attached PDF, describe an image, or tick Research and ask about today's news.")

# --- Voice input: record once, it becomes your next message ---
voice_prompt = ""
if hasattr(st, "audio_input"):
    audio = st.audio_input("Speak instead of typing (optional)")
    if audio is not None:
        blob = audio.getvalue()
        heard_hash = hashlib.md5(blob).hexdigest()
        if blob and heard_hash != st.session_state.get("heard_hash"):
            if key and free_ok:
                try:
                    with st.spinner("Listening..."):
                        st.session_state["voice_prompt"] = transcribe_audio(key, blob, audio.name or "speech.wav")
                    st.session_state["heard_hash"] = heard_hash
                    st.success("Heard: " + st.session_state["voice_prompt"])
                except ChatError as error:
                    st.session_state["heard_hash"] = heard_hash
                    st.error(str(error))
            else:
                st.caption("Paste your Groq key and tick the Free-plan box above to use voice.")
    voice_prompt = st.session_state.pop("voice_prompt", "")

# --- Laptop files: only files you point the app at ---
with st.expander("Laptop files (only what you choose)"):
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
                    st.success("Attached " + target.name + ". It will go with your next message.")
            else:
                st.warning("No such file or folder. Check the path.")
        except (OSError, PermissionError):
            st.error("Windows would not let the app read that path.")
    if st.session_state.get("path_attachment"):
        st.caption("Ready to send with next message: " + st.session_state["path_attachment"][0])

# --- Portfolio: local holdings, analysis only ---
with st.expander("My portfolio (analysis only, no trades)"):
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
            if st.button("Ask the assistant about my portfolio"):
                st.session_state["queued_prompt"] = (
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

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
if st.session_state.get("last_audio") and not st.session_state.get("audio_played"):
    st.audio(st.session_state["last_audio"], format="audio/wav", autoplay=True)
    st.session_state["audio_played"] = True

if len(st.session_state.messages) >= 2 and key and free_ok:
    if st.button("Regenerate last answer"):
        last_pair = st.session_state.messages[-2:]
        if [m["role"] for m in last_pair] == ["user", "assistant"]:
            st.session_state.messages = st.session_state.messages[:-2]
            if save_chats_on:
                save_chats(st.session_state.messages)
            st.session_state["queued_prompt"] = last_pair[0]["content"]
            st.session_state.pop("last_audio", None)
            st.rerun()

st.caption("Recent chat is sent to Groq for context. Older messages may be left out. Restarting clears chat unless saving is on.")

input_kwargs = {"placeholder": "Message your assistant", "max_chars": 2000,
                "disabled": not key or not free_ok}
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

# Priority when nothing was typed: a queued portfolio question, then the voice recording.
queued = st.session_state.pop("queued_prompt", None)
if not prompt and queued:
    prompt = queued
if not prompt and voice_prompt:
    prompt = voice_prompt

# A file chosen in Laptop files joins this message. It stays attached until a message actually goes.
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
    try:
        if research_on:
            with st.spinner("Researching..."):
                reply = research_reply(key, settings, st.session_state.messages, prompt, uploads)
        else:
            placeholder = st.empty()
            pieces = []

            def on_token(piece):
                pieces.append(piece)
                placeholder.markdown("".join(pieces) + " ▌")

            reply = get_reply(key, settings, st.session_state.messages, prompt, uploads,
                              model=chat_model, on_token=on_token)
            placeholder.empty()
        voice_audio = None
        if voice_on:
            try:
                voice_audio = speak_text(key, reply, voice=voice_name)
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
        if save_chats_on:
            save_chats(st.session_state.messages)
        if voice_audio:
            st.session_state["last_audio"] = voice_audio
            st.session_state["audio_played"] = False
        else:
            st.session_state.pop("last_audio", None)
        st.rerun()
