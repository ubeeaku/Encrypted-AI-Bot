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

# Conversation states
WAITING_FOR_EMOTION = 1

# API.Bible configuration
API_BIBLE_URL = "https://api.scripture.api.bible/v1/bibles"
DEFAULT_BIBLE_ID = "de4e12af7f28f599-01"  # English Standard Version (ESV)

# Dictionary of emotions and corresponding Bible references
bible_references = {
    "sadness": ["Psalm 34:18", "Matthew 11:28"],
    "anxiety": ["Philippians 4:6-7", "1 Peter 5:7"],
    "loneliness": ["Hebrews 13:5", "Psalm 68:6"],
    "anger": ["Ephesians 4:26", "Proverbs 15:1"],
    "fear": ["2 Timothy 1:7", "Isaiah 41:10"]
}

# --- Helper Functions ---
def fetch_bible_verse(reference):
    url = f"{API_BIBLE_URL}/{DEFAULT_BIBLE_ID}/search"
    headers = {"api-key": API_BIBLE_KEY}
    params = {"query": reference, "limit": 1}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data["data"]["verses"]:
            return data["data"]["verses"][0]["text"]
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Bible verse: {e}")
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
        "Hello! I'm here to help. How are you feeling today?\n"
        "You can say: 'sad', 'anxious', 'lonely', 'angry', or 'scared'."
    )
    return WAITING_FOR_EMOTION

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()
    
    if user_input in bible_references:
        verse, explanation = get_bible_verse(user_input)
        await update.message.reply_text(
            f"I'm sorry you're feeling {user_input}.\n\n"
            f"{verse}\n\n"
            f"What this means:\n"
            f"{explanation}"
        )
    else:
        await update.message.reply_text(
            "I'm here to listen. You can share how you feel with words like:\n"
            "'sad', 'anxious', 'lonely', 'angry', or 'scared'.\n\n"
            "Or type /cancel to end our chat."
        )
        return WAITING_FOR_EMOTION
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Okay, take care! Type /start anytime you want to talk.")
    return ConversationHandler.END

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

# --- Main Function ---
def main():
    print("Starting bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_FOR_EMOTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    app.add_error_handler(error)
    
    print("Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
