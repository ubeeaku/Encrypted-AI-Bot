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

# --- Single Instance Enforcement ---
LOCKFILE = "/tmp/bot.lock"
lock = FileLock(LOCKFILE + ".lock", timeout=1)

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

def manage_instance_lock():
    """Smart lock management for Render's environment"""
    try:
        # Try to acquire lock (non-blocking)
        with lock:
            # Write our PID
            with open(LOCKFILE, 'w') as f:
                f.write(str(os.getpid()))
            
            # Register cleanup
            atexit.register(cleanup_lock)
            
            print("🔒 Instance lock acquired")
            return True
            
    except:
        print("⚠️ Another instance is running - Exiting gracefully")
        sys.exit(0)

def cleanup_lock():
    """Safe lock removal"""
    try:
        if os.path.exists(LOCKFILE):
            os.remove(LOCKFILE)
            print("🔓 Lock released")
    except:
        pass

def create_application():
    """Configure bot with conflict prevention settings"""
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
    """Runs after bot initialization"""
    await app.bot.delete_webhook(drop_pending_updates=True)
    print("Bot initialized successfully")
    await application.bot.set_webhook()  # Ensure no webhook is set

async def post_stop(application):
    """Cleanup before shutdown"""
    try:
        os.remove('/tmp/bot.lock')
    except:
        pass
    print("Bot shutting down gracefully")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))

def check_single_instance():
    """Prevent multiple instances using file lock"""
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
            # Extract raw HTML content
            html_content = data['data']['passages'][0]['content']
            
            # Method 1: Simple regex cleanup (faster)
            clean_text = re.sub(r'<[^>]+>', '', html_content)  # Remove all HTML tags
            clean_text = ' '.join(clean_text.split())  # Normalize whitespace
            
            # Method 2: BeautifulSoup (more robust)
            # soup = BeautifulSoup(html_content, 'html.parser')
            # clean_text = soup.get_text(separator=' ', strip=True)
            
            return clean_text
            
    except Exception as e:
        print(f"API Error: {type(e).__name__} - {str(e)}")
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
    user_input = update.message.text.lower().strip()  # clean input

    # Debug: Show what emotion we detected
    print(f"User input: '{user_input}'")
    print(f"Matching against: {list(bible_references.keys())}")
    
    # Find the closest matching emotion
    matched_emotion = None
    for emotion in bible_references.keys():
        if emotion in user_input:  # Checks for partial matches
            matched_emotion = emotion
            break
    
    if matched_emotion:
        print(f"Matched emotion: {matched_emotion}")
        
        # Get random verse reference for this emotion
        verse_reference = random.choice(bible_references[matched_emotion])
        print(f"Selected verse: {verse_reference}")
        
        # Fetch verse text from API
        verse_text = fetch_bible_verse(reference)
        if verse_text:
            # Remove verse numbers if present (e.g., "3 He healeth..." → "He healeth...")
            clean_verse = re.sub(r'^\d+\s*', '', verse_text)
            explanation = (
                f"This verse reminds us that {matched_emotion} is a natural feeling, "
                f"but God is always with us to provide comfort and guidance."
            )
            response = (
                f"I'm sorry you're feeling {matched_emotion}. Here's a verse for you:\n\n"
                f"{verse_reference}\n{verse_text}\n\n"
                f"What this means:\n{explanation}"
            )
        else:
            # Fallback if API fails
            response = (
                f"I wanted to share a verse about {matched_emotion}, but couldn't connect to the Bible API. "
                f"Try again later or read {verse_reference} in your Bible."
            )
    else:
        # Default response for no match
        response = (
            "I'm here to listen. You can share feelings like:\n"
            "'sad', 'anxious', 'lonely', 'angry', or 'scared'.\n\n"
            "Or type /cancel to end our chat."
        )
    
    await update.message.reply_text(response)
    
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

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error occurred: {context.error}")

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

# --- Main Application ---
def main():
    if not manage_instance_lock():
        return  # Exit if couldn't acquire lock
    
    if not API_BIBLE_KEY or API_BIBLE_KEY == "your_api_key_here":
        raise ValueError("Missing or invalid API_BIBLE_KEY")
    
    print(" 🚀 Starting single-instance bot...")
    
    # Create and configure application
    application = create_application()

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
    
    # Initialize application with single instance setting
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .concurrent_updates(False) \
        .read_timeout(30) \
        .get_updates_read_timeout(30) \
        .build()
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    
    print("Current PID:", os.getpid())
    print("Lock file contents:", open('/tmp/bot.lock').read())
    
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    
    print("Bot is running...")

    # Start polling with conflict prevention
    application.run_polling(
        poll_interval=5.0,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        close_loop=False,# Critical for Render
        bootstrap_retries=0, # Disable retries
        stop_signals=[]    # Prevent signal handling issues
    )

if __name__ == "__main__":
    # Ensure only one instance runs
    try:
        main()
    except Exception as e:
        print(f"💥 Fatal error: {e}")
        try:
            os.remove(LOCKFILE)
        except:
            pass
        sys.exit(1)
