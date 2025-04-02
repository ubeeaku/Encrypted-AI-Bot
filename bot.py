import os
import requests
import threading
from flask import Flask
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
    "sad": ["Psalm 34:18", "Matthew 11:28", "Matthew 5:4", "Psalm 147:3"],
    "anxious": ["Philippians 4:6-7", "1 Peter 5:7", "Matthew 6:25-34"],
    "lonely": ["Hebrews 13:5", "Psalm 68:6", "Deuteronomy 31:6"],
    "angry": ["Ephesians 4:26", "Proverbs 15:1", "James 1:19-20"],
    "scared": ["2 Timothy 1:7", "Isaiah 41:10", "Psalm 56:3"],
     "discouraged": ["Isaiah 41:10", "Joshua 1:9", "Galatians 6:9"],
    "overwhelmed": ["Matthew 11:28-30", "Psalm 61:2", "2 Corinthians 12:9"],
    "guilty": ["1 John 1:9", "Psalm 103:12", "Romans 8:1"],
    "insecure": ["Psalm 139:14", "Ephesians 2:10", "Jeremiah 1:5"],
    "grieving": ["Revelation 21:4", "Psalm 34:18", "Mathew 5:4"]
}

# --- Helper Functions ---
def fetch_bible_verse(reference):
    url = f"{API_BIBLE_URL}/{DEFAULT_BIBLE_ID}/search"
    headers = {"api-key": API_BIBLE_KEY}
    params = {"query": reference, "limit": 1}
    
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

def get_bible_verse(emotion):
    if emotion in bible_references:
        reference = random.choice(bible_references[emotion])
        verse_text = fetch_bible_verse(reference)
        if verse_text:
            return verse_text, f"This verse reminds us that {emotion} is natural, but God is with us."
    return (
        "John 16:33 - In this world you will have trouble. But take heart! I have overcome the world.",
        "This verse reminds us that Jesus has overcome the world's challenges."
    )


# --- Handler Functions ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! How are you feeling? (sad, anxious, lonely, angry, scared, discouraged, overwhelmed, guilty, insecure, grieving)"
    )
    return WAITING_FOR_EMOTION

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()
    
    if user_input in bible_references:
        verse = get_bible_verse(random.choice(bible_references[user_input]))
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

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

# --- Main Application ---
def main():
    # Initialize application with single instance setting
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .concurrent_updates(False) \
        .read_timeout(30)
        .get_updates_read_timeout(30) \
        .build()
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
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
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,  # Important for Render
        stop_signals=None  # Prevent signal handling issues
    )

if __name__ == "__main__":
    main()
