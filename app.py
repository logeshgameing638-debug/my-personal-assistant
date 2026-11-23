"""Run with: python -m streamlit run app.py"""
import json
import os
import streamlit as st
from assistant import ChatError, get_reply, load_settings

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
    st.caption("Model: " + settings["model"])
    st.caption("Change the name and personality in settings.json, then restart the app.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.button("Forget pasted key", use_container_width=True, on_click=forget_key)
    st.caption("An environment-variable key stays until you remove it from your computer.")

st.title(settings["name"] + ", your personal assistant")
st.caption("Chat, write, learn and plan. Runs on your laptop, with online answers from Groq.")
st.info("Text chat only. No laptop control, web browsing, account access or background reminders.")
if not st.session_state.messages:
    st.markdown("### What would you like help with?")
    st.write("Try: Explain Python simply, help me plan tomorrow, or write a polite message.")
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

st.caption("Recent chat is sent to Groq for context. Older messages may be left out. Restarting or losing the session clears chat. Do not send secrets or sensitive personal data.")
prompt = st.chat_input("Message your assistant", max_chars=2000, disabled=not key or not free_ok)
if prompt and prompt.strip():
    prompt = prompt.strip()
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        with st.spinner("Thinking..."):
            reply = get_reply(key, settings, st.session_state.messages, prompt)
    except ChatError as error:
        st.error(str(error))
        st.caption("Your message was not added to memory. You can send it again.")
    else:
        st.session_state.messages.extend([
            {"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
        # Bound session memory too, so very long chats do not grow forever.
        st.session_state.messages = st.session_state.messages[-40:]
        st.rerun()
