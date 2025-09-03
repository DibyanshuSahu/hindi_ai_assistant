import os
import logging
import random
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------- Load env ----------------
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET_TOKEN = os.getenv("SECRET_TOKEN", "set-a-secret")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBAPP_URL = os.getenv("WEBAPP_URL")

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- FastAPI ----------------
app = FastAPI()

# ---------------- Telegram Application ----------------
tg_app = Application.builder().token(TOKEN).build()

# /start command
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    greetings = [
        "👋 Namaste Master! Main aapka Hindi Jarvis hoon.",
        "🙏 Master ji, main hamesha aapke liye tayyar hoon.",
        "😎 Arre Master! Aap aaye to masti shuru ho gayi!"
    ]
    await update.message.reply_text(random.choice(greetings))

# Normal text handler
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Master, aapne kaha: {update.message.text}")

# Add handlers
tg_app.add_handler(CommandHandler("start", cmd_start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

# ---------------- FastAPI + Telegram bridge ----------------
@app.on_event("startup")
async def on_startup():
    # Initialize Telegram app
    await tg_app.initialize()

    # Set webhook (IMPORTANT: don't call tg_app.start in webhook mode)
    url = WEBAPP_URL.rstrip("/") + WEBHOOK_PATH
    await tg_app.bot.set_webhook(url=url, secret_token=SECRET_TOKEN)
    logger.info(f"Webhook set to {url}")

@app.on_event("shutdown")
async def on_shutdown():
    await tg_app.shutdown()
    await tg_app.stop()

@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Hindi Jarvis live hai 🚀"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(None)):
    if x_telegram_bot_api_secret_token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return{"ok":True}