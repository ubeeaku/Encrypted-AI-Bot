import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import random
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Retrieve environment variables securely
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BIBLE_KEY = os.getenv("API_BIBLE_KEY")

# Check for missing environment variables
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")
if not API_BIBLE_KEY:
    raise ValueError("Missing API_BIBLE_KEY environment variable")

# API.Bible configuration
API_BIBLE_URL = "https://api.scripture.api.bible/v1/bibles"
DEFAULT_BIBLE_ID = "de4e12af7f28f599-01"  # English Standard Version (ESV)

# Function to fetch a Bible verse from API.Bible
def fetch_bible_verse(reference):
    url = f"{API_BIBLE_URL}/{DEFAULT_BIBLE_ID}/search"
    headers = {
        "api-key": API_BIBLE_KEY
    }
    params = {
        "query": reference,
        "limit": 1
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data["data"]["verses"]:
            verse_text = data["data"]["verses"][0]["text"]
            return verse_text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching Bible verse: {e}")
    return None

# Dictionary of emotions and corresponding Bible references
bible_references = {
    "sadness": ["Psalm 34:18", "Matthew 11:28"],
    "anxiety": ["Philippians 4:6-7", "1 Peter 5:7"],
    "loneliness": ["Hebrews 13:5", "Psalm 68:6"],
    "anger": ["Ephesians 4:26", "Proverbs 15:1"],
    "fear": ["2 Timothy 1:7", "Isaiah 41:10"]
}

def get_bible_verse(emotion):
    if emotion in bible_references:
        reference = random.choice(bible_references[emotion])
        verse_text = fetch_bible_verse(reference)
        if verse_text:
            return verse_text, f"This verse reminds us that {emotion} is a natural feeling, but God is always with us to provide comfort and guidance."
    return (
        "John 16:33 - In this world you will have trouble. But take heart! I have overcome the world.",
        "This verse reminds us that life can be hard, but Jesus has already overcome the world. We can find hope and peace in Him."
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I'm Encrypted, here to help you feel better. You can talk to me about anything.\n"
        "If you're feeling down, anxious, lonely, or just need someone to listen, I'm here for you.\n\n"
        "How are you feeling today? (You can say 'sad', 'anxious', 'lonely', 'angry', 'scared')"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.lower()

    if user_input in bible_references:
        verse, explanation = get_bible_verse(user_input)
        response = (
            f"I'm sorry you're feeling {user_input}. Remember, it's okay to feel this way. Here's a Bible verse to encourage you:\n\n"
            f"{verse}\n\n"
            f"What this means:\n"
            f"{explanation}\n\n"
            "For more encouragement, you can use a Bible app like YouVersion or Bible Gateway to explore more verses and devotionals."
        )
    else:
        response = (
            "I'm here to listen. Sometimes, just talking about how you feel can help. Would you like to share more?\n\n"
            "You can say 'sad', 'anxious', 'lonely', 'angry', or 'scared'."
        )

    await update.message.reply_text(response)

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
    
def main():
     import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

    print("Starting Encrypted AI bot...")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    app.add_error_handler(error)

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
