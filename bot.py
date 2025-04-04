import os
import asyncio
import requests
import threading
import random
import sys
import atexit
import re
import psutil
from flask import Flask
from tenacity import retry, stop_after_attempt, wait_exponential
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

# --- Constants ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BIBLE_KEY = os.getenv("API_BIBLE_KEY")
WAITING_FOR_EMOTION = 1
LOCKFILE_PATH = "/tmp/bot.lock"

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
    """Run Flask server with dynamic port handling"""
    port = int(os.environ.get("PORT", 10000))
    try:
        app.run(host='0.0.0.0', port=port)
    except OSError as e:
        logger.error(f"Failed to start Flask: {e}")

async def enforce_single_instance():
    """Ensure only one instance runs"""
    current_pid = os.getpid()
    try:
        if os.path.exists(LOCKFILE_PATH):
            with open(LOCKFILE_PATH, 'r') as f:
                pid_str = f.read().strip()
                if pid_str and pid_str.isdigit():
                    existing_pid = int(pid_str)
                    if existing_pid != current_pid and psutil.pid_exists(existing_pid):
                        logger.warning(f"Active instance detected (PID: {existing_pid})")
                        return False
        
        with open(LOCKFILE_PATH, 'w') as f:
            f.write(str(current_pid))
        return True
    except Exception as e:
        logger.error(f"Instance check error: {e}")
        return False

async def cleanup_lock():
    """Safe lock removal"""
    try:
        if os.path.exists(LOCKFILE_PATH):
            with open(LOCKFILE_PATH, 'r') as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(LOCKFILE_PATH)
                    logger.info("🔒 Lock released")
    except Exception as e:
        logger.error(f"Lock cleanup error: {e}")

# --- Helper Functions ---
def fetch_bible_verse(reference):
    """Fetch Bible verse from API"""
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
        logger.error(f"API Error: {e}")
    return None

def get_bible_verse(emotion):
    """Get random Bible verse for given emotion"""
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
    """Handle /start command"""
    try:
        await update.message.reply_text(
            "Hello! How are you feeling? (sad, anxious, lonely, angry, etc)",
            reply_markup=ReplyKeyboardMarkup(
                [list(bible_references.keys())], 
                one_time_keyboard=True
            )
        )
        return WAITING_FOR_EMOTION
    except Exception as e:
        logger.error(f"Start command error: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try /start again.")
        return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages"""
    try:
        text = update.message.text.lower()
        if text in bible_references:
            verse, message = get_bible_verse(text)
            await update.message.reply_text(f"{verse}\n\n{message}")
        else:
            await update.message.reply_text("Please choose one of the suggested emotions")
        return WAITING_FOR_EMOTION
    except Exception as e:
        logger.error(f"Message handler error: {e}")
        await update.message.reply_text("Sorry, I didn't understand that. Please try /start again.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    await update.message.reply_text("Goodbye! Type /start to chat again.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify user"""
    logger.error(f"⚠️ Error: {context.error}")
    if update and update.message:
        await update.message.reply_text("Sorry, something went wrong. Please try again.")

async def run_bot():
    """Main bot running routine"""
    application = None
    try:
        # Verify single instance
        if not await enforce_single_instance():
            logger.error("Duplicate instance detected")
            return
        
        # Initialize application
        application = Application.builder() \
            .token(TELEGRAM_BOT_TOKEN) \
            .build()

        # Add handlers
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                WAITING_FOR_EMOTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)

        # Start polling
        logger.info("🚀 Starting bot...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep the bot running
        while True:
            await asyncio.sleep(3600)
            
    except asyncio.CancelledError:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"💥 Bot crashed: {e}")
    finally:
        logger.info("🧹 Cleaning up resources...")
        if application:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        await cleanup_lock()

def main():
    """Main entry point"""
    if not all([TELEGRAM_BOT_TOKEN, API_BIBLE_KEY]):
        logger.error("❌ Missing required environment variables")
        return
    
    # Start Flask in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Run the bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        logger.info("🏁 Application terminated")

if __name__ == "__main__":
    main()
