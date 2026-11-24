"""Run with: py -m streamlit run app.py"""
import inspect
import json
import os
from pathlib import Path
import streamlit as st
from assistant import (ALL_EXTENSIONS, ChatError, get_reply, load_settings,
                       research_reply, speak_text, transcribe_audio)
from portfolio import (PortfolioError, add_holding, load_portfolio,
                       pnl_table, portfolio_summary_text, remove_holding)

st.set_page_config(page_title="My Personal Assistant", page_icon="💬", layout="centered")
try:
    settings = load_settings()
except (OSError, ValueError, json.JSONDecodeError):
    st.error("Cannot read settings.json. Restore the original file or fix its name, personality and model fields.")
    st.stop()

# This memory belongs only to the open browser session. It is not saved to disk.
if "messages" not in st.session_state:
    st.session_state.messages = []

def forget_key():
    st.session_state["groq_key"] = ""


with st.sidebar:
    st.title("Your settings")
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
    st.caption("Images are always read by " + settings["vision_model"] + ". Voice uses free Whisper (in) and Orpheus (out).")
    st.caption("You can attach: text, csv, json, code, PDF, images (png, jpg, webp). Not Word, Excel or zip files yet.")
    st.caption("Change the name and personality in settings.json, then restart the app.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pop("last_audio", None)
        st.rerun()
    st.button("Forget pasted key", use_container_width=True, on_click=forget_key)
    st.caption("An environment-variable key stays until you remove it from your computer.")

st.title(settings["name"] + ", your personal assistant")
st.caption("Chat, files, images, voice and basic web research. Runs on your laptop, with online answers from Groq.")
st.info("No full laptop control, account access or background listening. Attachments, voice and web results go to Groq only to answer that message. Do not send secrets or sensitive personal data.")
if not st.session_state.messages:
    st.markdown("### What would you like help with?")
    st.write("Try: Explain Python simply, summarize an attached PDF, describe an image, or tick Research and ask about today's news.")

# --- Voice input: record, then it becomes your next message ---
voice_prompt = ""
if hasattr(st, "audio_input"):
    audio = st.audio_input("Speak instead of typing (optional)")
    if audio is not None and key and free_ok:
        try:
            with st.spinner("Listening..."):
                voice_prompt = transcribe_audio(key, audio.getvalue(), audio.name or "speech.wav")
            st.success("Heard: " + voice_prompt)
        except ChatError as error:
            st.error(str(error))

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
    st.caption("Saved only on this laptop in portfolio.json, never uploaded. Prices can be delayed; check your broker app before acting.")
    try:
        holdings = load_portfolio()
    except PortfolioError as error:
        holdings = []
        st.error(str(error))
    col1, col2, col3 = st.columns(3)
    new_symbol = col1.text_input("Symbol", placeholder="RELIANCE.NS", key="pf_symbol")
    new_qty = col2.text_input("Quantity", placeholder="10", key="pf_qty")
    new_buy = col3.text_input("Buy price", placeholder="2500", key="pf_buy")
    if st.button("Add / update holding"):
        try:
            holdings = add_holding(new_symbol, new_qty, new_buy)
            st.session_state.pop("pf_result", None)
            st.success("Saved " + new_symbol.strip().upper())
        except PortfolioError as error:
            st.error(str(error))
    if holdings:
        if st.button("Refresh prices and P&L"):
            with st.spinner("Getting prices..."):
                st.session_state["pf_result"] = pnl_table(holdings)
        if st.session_state.get("pf_result"):
            lines, totals = st.session_state["pf_result"]
            for line in lines:
                if line["price"] is None:
                    st.write("%s — %s shares @ %.2f — live price unavailable" % (
                        line["symbol"], line["qty"], line["buy_price"]))
                else:
                    st.write("%s — %s shares @ %.2f — now %.2f — P&L %+.2f" % (
                        line["symbol"], line["qty"], line["buy_price"], line["price"], line["pnl"]))
            st.write("**Total invested %.2f — value %.2f — P&L %+.2f**" % (
                totals["invested"], totals["current"], totals["pnl"]))
            if totals["missing"]:
                st.caption("No live price for: " + ", ".join(totals["missing"]) + ". Use NSE symbols like RELIANCE.NS.")
            if st.button("Ask the assistant about my portfolio"):
                st.session_state["queued_prompt"] = (
                    portfolio_summary_text(holdings)
                    + "\n\nPlease analyze this simply: what looks strong, what looks weak, and general learning points. Not financial advice.")
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
if st.session_state.get("last_audio"):
    st.audio(st.session_state["last_audio"], format="audio/wav", autoplay=True)

st.caption("Recent chat is sent to Groq for context. Older messages may be left out. Restarting or losing the session clears chat.")

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

# A file chosen in Laptop files joins this message.
path_attachment = st.session_state.pop("path_attachment", None)
if path_attachment and (prompt or uploads):
    uploads = uploads + [path_attachment]

if prompt or uploads:
    if not prompt:
        prompt = "Please look at the attached file(s) and describe or summarize them."
    with st.chat_message("user"):
        st.markdown(prompt)
        for name, _ in uploads:
            st.caption("Attached: " + name)
    try:
        with st.spinner("Thinking..."):
            if research_on:
                reply = research_reply(key, settings, st.session_state.messages, prompt)
            else:
                reply = get_reply(key, settings, st.session_state.messages, prompt, uploads, model=chat_model)
            voice_audio = None
            if voice_on:
                try:
                    voice_audio = speak_text(key, reply)
                except ChatError as voice_error:
                    st.caption(str(voice_error))
    except ChatError as error:
        st.error(str(error))
        st.caption("Your message was not added to memory. You can send it again.")
    else:
        shown = prompt
        if uploads:
            shown += "\n\n" + " ".join("[" + name + "]" for name, _ in uploads)
        st.session_state.messages.extend([
            {"role": "user", "content": shown}, {"role": "assistant", "content": reply}])
        # Bound session memory too, so very long chats do not grow forever.
        st.session_state.messages = st.session_state.messages[-40:]
        if voice_audio:
            st.session_state["last_audio"] = voice_audio
        else:
            st.session_state.pop("last_audio", None)
        st.rerun()
