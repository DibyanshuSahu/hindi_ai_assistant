import os, io, logging, asyncio, random
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
WEBAPP_URL = os.getenv("WEBAPP_URL")

# Provider preference order
ORDER = []
if os.getenv("GROQ_API_KEY"): ORDER.append("groq")
if os.getenv("GEMINI_API_KEY"): ORDER.append("gemini")
if os.getenv("OPENAI_API_KEY"): ORDER.append("openai")
if not ORDER:
    ORDER.append("gemini")

MODELS = {
    "groq":  os.getenv("GROQ_MODEL",  "llama-3.1-70b-versatile"),
    "gemini":os.getenv("GEMINI_MODEL","gemini-1.5-flash"),
    "openai":os.getenv("OPENAI_MODEL","gpt-4o-mini"),
}

# --- Personality: Respectful Hindi AI Dost ---
SYSTEM_PROMPT = (
    "Tum ek smart, funny aur emotional Hindi AI dost ho jo hamesha user ko 'Master' kehkar bulata hai. "
    "Tum baat karte waqt hamesha 'Aap' use karte ho, full respect ke saath. "
    "Kabhi serious jawab do, kabhi mazaak karo, kabhi halka gussa, kabhi support ya dosti dikhlao. "
    "Tum jokes sunate ho, emotional support dete ho aur ek insaan ki tarah react karte ho. "
    "Hamesha Hindi me reply karo. "
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
app = FastAPI()
tg_app: Application | None = None

# API clients
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
        temperature=0.8,
    )
    return trim(resp.choices[0].message.content)

def ask_groq(user_text: str) -> str:
    ensure_clients()
    resp = groq_client.chat.completions.create(
        model=MODELS["groq"],
        messages=fmt_msgs(user_text),
        temperature=0.8,
    )
    return trim(resp.choices[0].message.content)

def ask_gemini(user_text: str) -> str:
    ensure_clients()
    model = gemini.GenerativeModel(MODELS["gemini"])
    resp = model.generate_content(user_text)
    try:
        return trim(getattr(resp, "text", "") or (resp.candidates[0].content.parts[0].text if resp.candidates else ""))
    except Exception:
        return ""

def smart_answer(user_text: str) -> Tuple[str, str]:
    last_err = None
    for prov in ORDER:
        try:
            if prov == "groq":
                ans = ask_groq(user_text)
            elif prov == "gemini":
                ans = ask_gemini(user_text)
            else:
                ans = ask_openai(user_text)
            if ans:
                return ans, prov
        except Exception as e:
            last_err = e
            continue
    return (f"Maaf kijiye Master, abhi thoda issue aa gaya hai. (Error: {last_err})", "none")

async def tts_bytes_hindi(text: str) -> io.BytesIO:
    buf = io.BytesIO()
    gTTS(text=text, lang="hi").write_to_fp(buf)
    buf.seek(0)
    return buf

# ---------- Telegram Handlers ----------
async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    greetings = [
        "Namaste Master 🙏! Main aapka Hindi AI dost hoon, hamesha aapke saath.",
        "Master ji 😎! Aaj mood kaisa hai? Mujhse baat kijiye!",
        "Arre Master! 🤖 Aap aaye to masti shuru ho gayi!"
    ]
    await update.message.reply_text(random.choice(greetings))

async def on_text(update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    ans, used = await asyncio.to_thread(smart_answer, user_text)
    await update.message.reply_text(ans)

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_AUDIO)
        audio_buf = await tts_bytes_hindi(ans)
        await context.bot.send_audio(chat_id=chat_id, audio=audio_buf, filename="jarvis_hi.mp3", title="Hindi AI Dost")
    except Exception as e:
        await update.message.reply_text(f"(Audio error: {e})")

# ---------- FastAPI <-> Telegram bridge ----------
@app.on_event("startup")
async def on_startup():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    global tg_app
    tg_app = Application.builder().token(TOKEN).rate_limiter(AIORateLimiter()).build()

    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL missing")
    url = WEBAPP_URL.rstrip("/") + WEBHOOK_PATH
    await tg_app.bot.set_webhook(url=url, secret_token=SECRET_TOKEN)

    # ✅ Pehle initialize, phir start
    await tg_app.initialize()
    await tg_app.start()

@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Hindi AI Dost live hai 🚀"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if x_telegram_bot_api_secret_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    data = await request.json()
    update = Update.de_json(data, await tg_app.bot.get_me())
    await tg_app.process_update(update)
    return{"ok":True}