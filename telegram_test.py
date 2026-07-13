import asyncio
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = "8883747585:AAFVbvLiUSf_1n_nShLHpUHFSU6ccThaP7E"
CHAT_ID = 8702856139   # Integer, not a string

bot = Bot(token=TOKEN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Sentinel Connected Successfully!"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📡 Sentinel Status\n\n"
        "Camera : Connected\n"
        "Motion : Running\n"
        "AI : Running\n"
        "Telegram : Connected"
    )


async def snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open("snapshots/test.jpg", "rb") as photo:
            await bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption="📸 Test Snapshot",
            )
    except FileNotFoundError:
        await update.message.reply_text(
            "No test image found."
        )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏓 Pong!"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Received:", update.message.text)


async def startup(app):
    await bot.send_message(
        chat_id=CHAT_ID,
        text="🚀 Sentinel Telegram Test Started"
    )


app = Application.builder().token(TOKEN).post_init(startup).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("snapshot", snapshot))
app.add_handler(CommandHandler("ping", ping))
app.add_handler(MessageHandler(filters.TEXT, echo))

print("=" * 50)
print("Sentinel Telegram Integration Test")
print("=" * 50)
print("Bot Running...")
print("Press CTRL+C to stop")
print("=" * 50)

app.run_polling()