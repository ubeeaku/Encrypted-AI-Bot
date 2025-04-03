import os
import asyncio
import requests
import threading
import re
import atexit
from filelock import FileLock
from bs4 import BeautifulSoup
from flask import Flask
from tenacity import retry, stop_after_attempt, wait_exponential
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
import sys


# --- Constants ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BIBLE_KEY = os.getenv("API_BIBLE_KEY")
WAITING_FOR_EMOTION = 1
# --- Single Instance Enforcement ---
INSTANCE_LOCK = "/tmp/bot.lock"

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

# Flask app for health checks
app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def enforce_single_instance():
    """Atomic instance check using file locks"""
    try:
        fd = os.open(INSTANCE_LOCK, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        print("⚠️ Another instance detected")
        return False

def create_application():
    """Configure with all necessary safeguards"""
    return Application.builder() \
        .token(os.getenv("TELEGRAM_BOT_TOKEN")) \
        .concurrent_updates(False) \
        .post_init(post_init) \
        .post_stop(post_stop) \
        .build()

async def cleanup_webhook(app):
    """Ensure no webhook conflicts"""
    await app.bot.delete_webhook(drop_pending_updates=True)
    print("✅ Bot initialized - Ready to poll")

async def remove_lock(app):
    """Cleanup lockfile"""
    try:
        os.remove(LOCKFILE)
        print("🔒 Lockfile removed")
    except:
        pass
async def post_init(application):
    """Initialization tasks"""
    if not await enforce_single_instance():
        print("Shutting down duplicate instance")
        await application.stop()
        sys.exit(0)
    
    print("✅ Bot instance verified - Starting poll")

async def post_stop(application):
    """Cleanup tasks"""
    await cleanup_lock()
    
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))

def check_single_instance():
    """Ensure only one instance runs"""
    try:
        if os.path.exists(LOCKFILE):
            with open(LOCKFILE, 'r') as f:
                pid = f.read()
                print(f"⚠️ Another instance is running (PID: {pid}). Exiting.")
            sys.exit(1)
        
        with open(LOCKFILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"Lockfile error: {e}")
        sys.exit(1)
check_single_instance()

def cleanup_lock():
    """Safe lock removal"""
    try:
        os.remove(LOCKFILE)
        print("🔒 Lock released")
    except:
        pass

# --- Helper Functions ---
def fetch_bible_verse(reference):
    """Improved verse fetcher with HTML cleaning"""    
    try:
        response = requests.get(
            f"{API_BIBLE_URL}/{DEFAULT_BIBLE_ID}/search",
            headers={"api-key": API_BIBLE_KEY},
            params={"query": reference, "limit": 1},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get('data', {}).get('passages'):
            html_content = data['data']['passages'][0]['content']
            clean_text = re.sub(r'<[^>]+>', '', html_content)
            return ' '.join(clean_text.split())
    except Exception as e:
        print(f"API Error: {e}")
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
    user_input = update.message.text.lower().strip()
    
    matched_emotion = next(
        (emotion for emotion in bible_references if emotion in user_input),
        None
    )
    
    if matched_emotion:
        verse_ref = random.choice(bible_references[matched_emotion])
        verse_text = fetch_bible_verse(verse_ref)
        
        if verse_text:
            response = f"For {matched_emotion}:\n\n{verse_ref}\n{verse_text}"
        else:
            response = f"Couldn't fetch {verse_ref}. Please try again later."
    else:
        response = "I'm here to listen. Try words like 'sad', 'anxious', etc."
    
    await update.message.reply_text(response)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Goodbye! Type /start to chat again.")
    return ConversationHandler.END

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Update {update} caused error {context.error}")

def main():
    # Check for single instance
    check_single_instance()
    atexit.register(cleanup_lock)
    
    # Start Flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Create Telegram application
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .concurrent_updates(False) \
        .build()

    # Add handlers
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

    print("Bot starting...")
    application.run_polling(
        drop_pending_updates=True,
        close_loop=False
    )
    
if __name__ == "__main__":
     # Verify environment variables
    if not all([TELEGRAM_BOT_TOKEN, API_BIBLE_KEY]):
        print("Error: Missing required environment variables")
        sys.exit(1)
    
    try:
        main()
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup_lock()
