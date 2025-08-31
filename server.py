import os, io, logging, asyncio, random
from typing import Tuple
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from gtts import gTTS

# ----- Load env -----
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "set-a-secret")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBAPP_URL = os.getenv("WEBAPP_URL")

# --- Personality
SYSTEM_PROMPT = (
    "Tum ek smart aur funny Hindi AI dost ho jo hamesha user ko 'Master' kehkar bulata hai. "
    "Hamesha Hindi me respect ke saath 'Aap' bolkar jawab do."
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# --- FastAPI app
app = FastAPI()

# --- Telegram Application
tg_app = Application.builder().token(TOKEN).build()

# Handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    greetings = [
        "Namaste Master 🙏! Main aapka Hindi AI dost hoon.",
        "Master ji 😎! Kaise ho aap?",
        "Arre Master! 🤖 Aap aaye to masti shuru!"
    ]
    await update.message.reply_text(random.choice(greetings))

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""
    await update.message.reply_text(f"Master, aapne likha: {user_text}")

tg_app.add_handler(CommandHandler("start", cmd_start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))


# --- Startup hook
@app.on_event("startup")
async def on_startup():
    # webhook set
    url = WEBAPP_URL.rstrip("/") + WEBHOOK_PATH
    await tg_app.bot.set_webhook(url=url, secret_token=SECRET_TOKEN)


# --- Routes
@app.api_route("/", methods=["GET", "HEAD"], response_class=PlainTextResponse)
async def root():
    return "Hindi AI Dost live hai 🚀"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if x_telegram_bot_api_secret_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return{"ok":True}