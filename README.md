# My Personal Assistant

A small Python chat app for your Windows laptop. Its starting name is Aria. You can change the name and personality in one settings file.

This is an independent starter project, not a copy of another assistant. It chats, helps with writing, explains topics, writes code and suggests plans. You can attach text files, PDFs and images, talk to it by voice, hear answers read aloud, run basic web research, read files you point it at on your laptop, and track a stock portfolio (analysis only, no trades). You can switch between three free Groq models in the sidebar. It does not control your computer, open your accounts, listen in the background or send reminders.

## Cost and privacy first

- The app and Python are free. It needs internet, plus your own Groq account on the **Free** plan. Your normal internet costs still apply.
- Groq's free plan has usage limits. If you hit one, wait. Do not add a card, upgrade to Developer or enable paid billing for this project.
- The app cannot check your billing plan. If you use a key from a paid account, usage can cost money. Check the plan yourself before chatting.
- Groq receives your message, the personality setting, some recent chat and any file, image or voice recording you send to generate each answer. This is not offline AI. Do not paste passwords, bank details or private documents.
- Portfolio holdings are stored only on your laptop in `portfolio.json` (kept out of the public repo by `.gitignore`). They leave the laptop only if you press **Ask the assistant about my portfolio**, which sends the holdings summary to Groq for analysis. Prices come from a public quote page and can be delayed or unavailable. Analysis only: no trading, no broker login. Check your broker app before acting.
- Web research is basic: it searches and reads a few public pages, or uses Groq's browser search when your free key allows it. It can be wrong or blocked. Always check the listed sources yourself.
- The microphone records only when you press the mic button. Nothing listens in the background.
- Your key is not written into the project. A pasted key stays in the running session. Never send it in WhatsApp, email, a screenshot or GitHub.
- Chat memory is temporary, not permanent. The app keeps up to 20 recent question-and-answer pairs in the session and sends only the most recent pairs that fit its small context budget. Older details may be forgotten. A restart or lost session clears it. Clear conversation removes the current app memory, not records Groq may retain.
- Keep the app on your own laptop. It is set to localhost only. Do not expose its port to the internet or deploy this starter as a shared service.
- AI can be wrong. It has no live web search here. Check important answers yourself.

## 1. Install Python once

1. On your laptop, open https://www.python.org/downloads/windows/.
2. Install Python 3.12 or 3.13 for Windows. During installation, tick **Add Python to PATH** if shown.
3. Close and reopen Command Prompt after installing.
4. Type `python --version` and press Enter. You should see a Python version.

If Windows opens the Store or says Python is missing, run the Python installer again and enable PATH. On some Windows installations, `py` works instead of `python`; if so, use `py` wherever these steps say `python`.

## 2. Extract this project

1. Save the project ZIP on your laptop.
2. Right-click the ZIP and choose **Extract All**. Do not run it from inside the ZIP.
3. Open the extracted folder that contains `app.py`, `assistant.py` and `requirements.txt`.
4. Click the folder's address bar, type `cmd` and press Enter. A Command Prompt opens in that folder.

## 3. Install and run

Run these commands one at a time in that Command Prompt:

```bat
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Leave Command Prompt open. The app should open in your browser. If it does not, open the Local URL printed in Command Prompt, normally `http://localhost:8501`.

Next time, open the folder and double-click `START.bat`. Or run the second command above again. To stop the app, click Command Prompt and press Ctrl+C.

## 4. Create your own Groq key

1. Open https://console.groq.com/ in your laptop browser and create an account or sign in.
2. Open **Settings > Billing** and confirm the plan is **Free ($0)**. Do not add payment details or upgrade. The plan page is https://console.groq.com/settings/billing/plans.
3. Open **API Keys** from the Groq menu. Choose **Create API Key** and give it a name such as Personal Assistant.
4. Copy the new key directly into the **Groq API key** password box in the app's left sidebar. Keep it private. Do not paste it into the source files or a message to anyone.
5. Tick **I checked: my Groq account is on the Free plan** in the app. Start chatting.

Already have a Groq key? Use it only after checking that its account/organization is on the Free plan. If your key is lost, create a new one and revoke the old one in Groq. Never ask someone else to send you their key.

The app also accepts `GROQ_API_KEY` from your computer's environment. This is optional; beginners should use the sidebar. If both exist, the pasted key wins. Forget pasted key does not remove an environment variable. The app does not load `.env` files.

## Attachments and model choice

- Use the paperclip in the chat box to attach files: text, markdown, csv, json, code, PDF (first 20 pages of text) and images (png, jpg, webp, up to 3 per message, each under 3 MB).
- Word, Excel and zip files are not supported yet. Copy their text into a .txt file and attach that instead.
- A photo-only PDF has no readable text and cannot be read.
- The **AI brain** box in the sidebar switches between Fast (`openai/gpt-oss-20b`), Smart (`openai/gpt-oss-120b`) and Qwen 3.8 (`qwen/qwen3.8-27b`, good for many languages). Images are always read by the vision model `qwen/qwen3.8-27b`. All are on Groq's Free plan when this project was made.
- Long answers (like full code) can take up to a minute. If the free limit still cuts an answer, send `continue` and the assistant goes on.

## Voice

- Press **Speak instead of typing**, talk, then stop. Your words become the next message.
- Tick **Read answers aloud** to hear replies. Voice uses Groq's free Whisper and Orpheus models; free limits apply, and long replies are read only up to about the first 1200 characters.

## Web research

Tick **Research the web first** in the sidebar before sending a question. It is slower and uses more of the free limits. The answer ends with the sources it actually used. Untick it for normal chat.

## Laptop files

In **Laptop files**, type a path such as `C:\Users\vijay\Documents`. The app lists that folder, or reads one file you choose when you press **Attach this file to my next message**. It never changes, moves or deletes anything.

## Portfolio

In **My portfolio**, add holdings as symbol, quantity and buy price (use NSE symbols like `RELIANCE.NS`). Press **Refresh prices and P&L** for live values, and **Ask the assistant about my portfolio** for a simple analysis. This is not financial advice and cannot place trades.

## Change the name or personality

1. Stop the app with Ctrl+C.
2. Right-click `settings.json` and open it with Notepad.
3. Change only the text inside the quotes for `name` or `personality`. Keep the quotes, commas and braces. Do not put a key here.
4. Save, then start the app again. Use **Clear conversation** for a fresh chat.

The default model is `openai/gpt-oss-20b`, listed by Groq when this project was made. Models and free access can change. If the model stops working, check https://console.groq.com/docs/models and your Groq account, then replace the `model` value with a model available to your Free plan. Never upgrade just to make a model work.

## If something goes wrong

- **No module named streamlit or pypdf:** Run the install command again using the same `python` or `py` command used to start the app.
- **Could not open requirements.txt:** You are in the wrong folder. Open Command Prompt in the folder containing `app.py`.
- **Key or model access rejected:** Check the key in Groq, recreate it if needed, and confirm free model access. Do not share the key while asking for help.
- **Free limit reached:** Wait and try later. The exact limits depend on the model and your Groq organization. Voice has its own separate free limits.
- **Voice or research feature was rejected:** Your free key may not have that model or tool yet. Chat, files and images still work. Do not upgrade.
- **Live price unavailable:** The free quote source can fail or block. Holdings and P&L from buy prices still work; check your broker app for real prices.
- **Cannot reach Groq:** Check your internet connection. No offline answers are available.
- **Port already in use:** Stop the previous app window with Ctrl+C. Or run `python -m streamlit run app.py --server.port 8502`.
- **Cannot read settings.json:** Restore the original settings file. A missing comma or quote can break JSON.
- **File too big / cannot read this file:** Check the attachment rules above and try a smaller image or a supported file type.

## Files

- `app.py`: chat screen, voice, laptop files, portfolio panel and session memory
- `assistant.py`: settings, attachments, voice, web research, context budget and safe Groq request handling
- `portfolio.py`: local holdings storage and best-effort live prices
- `settings.json`: editable name, personality and model
- `requirements.txt`: the Python packages needed
- `START.bat`: Windows launcher after first install
- `.streamlit/config.toml`: local-only server and theme
- `.gitignore`: prevents common local files from being committed
- `test_assistant.py`: tests with fake responses, no API key required
- `README.md`: these instructions

## Test without a key

```bat
python -m unittest -v
```

The tests use simulated responses. A real Groq answer still requires your own working key and Free-plan model access.

## Provider references

- Setup: https://console.groq.com/docs/quickstart
- Models: https://console.groq.com/docs/models
- Limits: https://console.groq.com/docs/rate-limits
- Plans: https://console.groq.com/settings/billing/plans
- Billing: https://console.groq.com/docs/billing-faqs
