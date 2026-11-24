"""Run with: py -m streamlit run app.py"""
import inspect
import json
import os
import streamlit as st
from assistant import ALL_EXTENSIONS, ChatError, get_reply, load_settings

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
                     "Smart (gpt-oss-120b)": "openai/gpt-oss-120b"}
    picked = st.selectbox("AI brain (all free on Groq)", list(model_choices))
    chat_model = model_choices[picked]
    st.caption("Images are always read by " + settings["vision_model"] + ".")
    st.caption("You can attach: text, csv, json, code, PDF, images (png, jpg, webp). Not Word, Excel or zip files yet.")
    st.caption("Change the name and personality in settings.json, then restart the app.")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    st.button("Forget pasted key", use_container_width=True, on_click=forget_key)
    st.caption("An environment-variable key stays until you remove it from your computer.")

st.title(settings["name"] + ", your personal assistant")
st.caption("Chat, write, learn, plan, and ask about files and images. Runs on your laptop, with online answers from Groq.")
st.info("No laptop control, web browsing, account access or background reminders. Attachments are sent to Groq only to answer that message; they are not saved.")
if not st.session_state.messages:
    st.markdown("### What would you like help with?")
    st.write("Try: Explain Python simply, summarize an attached PDF, describe an image, or write a polite message.")
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

st.caption("Recent chat is sent to Groq for context. Older messages may be left out. Restarting or losing the session clears chat. Do not send secrets or sensitive personal data.")

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

if prompt or uploads:
    if not prompt:
        prompt = "Please look at the attached file(s) and describe or summarize them."
    with st.chat_message("user"):
        st.markdown(prompt)
        for name, _ in uploads:
            st.caption("Attached: " + name)
    try:
        with st.spinner("Thinking..."):
            reply = get_reply(key, settings, st.session_state.messages, prompt, uploads, model=chat_model)
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
        st.rerun()
