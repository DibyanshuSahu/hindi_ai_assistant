import os
import io
import time
import logging
import asyncio
from typing import Tuple
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, AIORateLimiter, filters
from gtts import gTTS

# ----- Load env -----
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "set-a-secret")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBAPP_URL = os.getenv("WEBAPP_URL")  # e.g., https://your-service.onrender.com

# Provider order: free/cheap first
ORDER = []
if os.getenv("GROQ_API_KEY"): ORDER.append("groq")
if os.getenv("GEMINI_API_KEY"): ORDER.append("gemini")
if os.getenv("OPENAI_API_KEY"): ORDER.append("openai")
if not ORDER:
    ORDER.append("gemini")  # fallback

MODELS = {
    "groq": os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
    "gemini": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
    "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
}

SYSTEM_PROMPT = (
    "Tum ek helpful, accurate assistant ho jo HINDI me seedha aur clear jawab deta hai. "
    "Jarurat par bullet points aur exact dates/numbers do. Galti ho to vinamrata se sudharo. "
    "Unsafe/toxic cheezein avoid karo."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI()
tg_app: Application | None = None

# ---------- LLM clients ----------
openai_client = None
groq_client = None
gemini = None

def ensure_clients():
    global openai_client, groq_client, gemini
    if os.getenv("OPENAI_API_KEY") and openai_client is None:
        from openai import OpenAI
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    if os.getenv("GROQ_API_KEY") and groq_client is None:
        from groq import Groq
        groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    if os.getenv("GEMINI_API_KEY") and gemini is None:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        gemini = genai

def trim(s: str) -> str:
    return (s or "").strip()


def fmt_msgs(user_text: str):
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]


def ask_openai(user_text: str) -> str:
    ensure_clients()
    resp = openai_client.chat.completions.create(
        model=MODELS["openai"],
        messages=fmt_msgs(user_text),
        temperature=0.4,
    )
    return trim(resp.choices[0].message.content)


def ask_groq(user_text: str) -> str:
    ensure_clients()
    resp = groq_client.chat.completions.create(
        model=MODELS["groq"],
        messages=fmt_msgs(user_text),
        temperature=0.4,
    )
    return trim(resp.choices[0].message.content)


def ask_gemini(user_text: str) -> str:
    ensure_clients()
    model = gemini.GenerativeModel(MODELS["gemini"])
    prompt = f"{SYSTEM_PROMPT}\n\nUser: {user_text}\nAssistant (Hindi):"
    resp = model.generate_content(prompt)
    try:
        return trim(getattr(resp, "text", "") or (resp.candidates[0].content.parts[0].text if resp.candidates else ""))
    except Exception:
        return ""


def smart_answer(user_text: str) -> Tuple[str, str]:
    last_err = None
    for prov in ORDER:
        for attempt in range(3):
            try:
                if prov == "groq":
                    ans = ask_groq(user_text)
                elif prov == "gemini":
                    ans = ask_gemini(user_text)
                else:
                    ans = ask_openai(user_text)
                if ans:
                    return ans, prov
                raise RuntimeError("Empty response")
            except Exception as e:
                last_err = e
                time.sleep(0.7 * (attempt + 1))
                continue
    return (f"Maaf kijiye, abhi servers vyast hain. Thodi der baad koshish karein.\n(Tech: {last_err})", "none")


async def tts_bytes_hindi(text: str) -> io.BytesIO:
    buf = io.BytesIO()
    gTTS(text=text, lang="hi").write_to_fp(buf)
    buf.seek(0)
    return buf

# ---------- Telegram Handlers ----------
async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Namaste! Main aapka Hindi Jarvis hoon 🤖\n"
        "Kuch bhi poochhiye — main Hindi me text + audio reply dunga.\n"
        "Commands: /help /mode"
    )


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bas apna sawaal bhejiye. Main Hindi me seedha jawab dunga.\n"
        "Tips:\n• Lambi query ko ek message me bhejein\n• Dates/numbers clear likhein\n"
        "Mode: pehle Groq/Gemini try, phir OpenAI (agar key di hai)."
    )


async def cmd_mode(update, context: ContextTypes.DEFAULT_TYPE):
    active = " → ".join(ORDER) if ORDER else "none"
    await update.message.reply_text(f"Provider order: {active}\nModels: {MODELS}")


async def on_text(update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    ans, used = await asyncio.to_thread(smart_answer, user_text)
    # text
    await update.message.reply_text(ans)

    # audio
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_AUDIO)
        audio_buf = await tts_bytes_hindi(ans)
        await update.message.reply_audio(audio=audio_buf, filename="jarvis_hi.mp3", title="Jarvis (Hindi)")
    except Exception as e:
        await update.message.reply_text(f"(Audio issue: {e})")

# ---------- FastAPI <-> Telegram bridge ----------
@app.on_event("startup")
async def on_startup():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    global tg_app
    tg_app = Application.builder().token(TOKEN).rate_limiter(AIORateLimiter()).build()

    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("help", cmd_help))
    tg_app.add_handler(CommandHandler("mode", cmd_mode))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    # Set webhook
    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL missing (your public https URL)")
    url = WEBAPP_URL.rstrip("/") + WEBHOOK_PATH
    await tg_app.bot.set_webhook(url=url, secret_token=SECRET_TOKEN)
    asyncio.create_task(tg_app.initialize())
    asyncio.create_task(tg_app.start())


@app.on_event("shutdown")
async def on_shutdown():
    if tg_app:
        await tg_app.stop()
        await tg_app.shutdown()


@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Hindi Jarvis bot is live."


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if x_telegram_bot_api_secret_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    data = await request.json()
    update = Update.de_json(data, await tg_app.bot.get_me())
    await tg_app.process_update(update)
    return{"ok":True}