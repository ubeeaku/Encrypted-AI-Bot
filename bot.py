import os
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
import random

# --- Constants ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BIBLE_KEY = os.getenv("API_BIBLE_KEY")
WAITING_FOR_EMOTION = 1

# API.Bible configuration
API_BIBLE_URL = "https://api.scripture.api.bible/v1/bibles"
DEFAULT_BIBLE_ID = "de4e12af7f28f599-01"

# Dictionary of emotions and Bible references
bible_references = {
    "sad": ["Psalm 34:18", "Matthew 11:28"],
    "anxious": ["Philippians 4:6-7", "1 Peter 5:7"],
    "lonely": ["Hebrews 13:5", "Psalm 68:6"],
    "angry": ["Ephesians 4:26", "Proverbs 15:1"],
    "scared": ["2 Timothy 1:7", "Isaiah 41:10"]
}

# --- Helper Functions ---
def fetch_bible_verse(reference):
    try:
        response = requests.get(
            f"{API_BIBLE_URL}/{DEFAULT_BIBLE_ID}/search",
            headers={"api-key": API_BIBLE_KEY},
            params={"query": reference, "limit": 1},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        if data["data"]["verses"]:
            return data["data"]["verses"][0]["text"]
    except Exception as e:
        print(f"Error fetching verse: {e}")
    return None

# --- Handler Functions ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! How are you feeling? (sad, anxious, lonely, angry, scared)"
    )
    return WAITING_FOR_EMOTION

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()
    
    if user_input in bible_references:
        verse = fetch_bible_verse(random.choice(bible_references[user_input]))
        if verse:
            await update.message.reply_text(f"Here's a verse for you:\n\n{verse}")
        else:
            await update.message.reply_text("I couldn't fetch a verse right now. Try again later.")
    else:
        await update.message.reply_text(
            "I'm here to listen. Try one of these feelings:\n"
            "sad, anxious, lonely, angry, scared\n\n"
            "Or /cancel to end our chat."
        )
        return WAITING_FOR_EMOTION
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Take care! Type /start to chat again.")
    return ConversationHandler.END

# --- Main Application ---
def main():
    # Initialize application with single instance setting
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .concurrent_updates(False) \
        .build()
    
    # Set up conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_FOR_EMOTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(conv_handler)
    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
