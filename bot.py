import os
import asyncio
import requests
import threading
import re
import psutil
import atexit
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
import logging 

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BIBLE_KEY = os.getenv("API_BIBLE_KEY")
WAITING_FOR_EMOTION = 1
# --- Single Instance Enforcement ---
LOCKFILE_PATH = "/tmp/bot.lock"


# --- Lightweight Instance Check ---
def check_previous_instance():
    """Simple check without persistent lockfile"""
    try:
        # Check running processes (Render-specific)
        if os.system("ps aux | grep 'python bot.py' | grep -v grep | wc -l") > "1":
            print("⚠️ Another bot instance detected")
            return True
    except:
        pass
    return False

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
    max_retries = 3
    for attempt in range(max_retries):
        try:
            app.run(host='0.0.0.0', port=port)
            break
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(f"Port {port} in use, trying port {port + 1}")
                port += 1
                if attempt == max_retries - 1:
                    logger.error("Failed to find available port")
                    raise
            else:
                raise
    # app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))

async def enforce_single_instance():
    """Improved instance check that won't detect current process"""
    current_pid = os.getpid()
    
    try:
        if os.path.exists(LOCKFILE_PATH):
            with open(LOCKFILE_PATH, 'r') as f:
                pid_str = f.read().strip()
                if pid_str and pid_str.isdigit():
                    existing_pid = int(pid_str)
                    
                    # Check if the process is actually running and isn't ourselves
                    if existing_pid != current_pid and psutil.pid_exists(existing_pid):
                        logger.warning(f"Active instance detected (PID: {existing_pid})")
                        return False
        
        # Create/update lockfile
        with open(LOCKFILE_PATH, 'w') as f:
            f.write(str(current_pid))
        return True
    except Exception as e:
        logger.error(f"Instance check error: {e}")
        return False
    # """Atomic instance check using file locks"""
    # try:
    #     fd = os.open(LOCKFILE_PATH, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
    #     with os.fdopen(fd, 'w') as f:
    #         f.write(str(os.getpid()))
    #     return True
    # except FileExistsError:
    #     logger.error("⚠️ Another instance detected")
    #     return False

# def create_application():
#     """Configure with all necessary safeguards"""
#     return Application.builder() \
#         .token(os.getenv("TELEGRAM_BOT_TOKEN")) \
#         .concurrent_updates(False) \
#         .post_init(post_init) \
#         .post_stop(post_stop) \
#         .build()

async def cleanup_webhook(app):
    """Ensure no webhook conflicts"""
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Bot initialized - Ready to poll")

async def remove_lock(app):
    """Cleanup lockfile"""
    try:
        os.remove(LOCKFILE_PATH)
        print("🔒 Lockfile removed")
    except:
        pass
async def post_init(application):
    """Initialization tasks"""
    if not await enforce_single_instance():
        logger.error("Duplicate instance detected")
        await application.stop()
        sys.exit(0)
    logger.info("✅ Bot instance verified - Starting poll")

async def post_stop(application):
    """Cleanup tasks"""
    await cleanup_lock()
    logger.info("🛑 Bot stopped")
    
# @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))

def check_single_instance():
    """Ensure only one instance runs"""
    try:
        if os.path.exists(LOCKFILE_PATH):
            with open(LOCKFILE_PATH, 'r') as f:
                pid = f.read()
                print(f"⚠️ Another instance is running (PID: {pid}). Exiting.")
            sys.exit(1)
        
        with open(LOCKFILE_PATH, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"Lockfile error: {e}")
        sys.exit(1)

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

async def post_stop(application):
    """Cleanup tasks"""
    try:
        await cleanup_lock()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")

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
    return 1

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("I'm here to listen...")
    return 1
    # try:
    #     if not update.message or not update.message.text:
    #         await update.message.reply_text("Please send a text message")
    #         return 1
            
    #     response, new_state = await conversation_mgr.generate_response(
    #         update.message.text,
    #         context.user_data.get('state', ConversationState.WAITING_INITIAL)
    #     )
        
    #     if not response or not new_state:  # Add null check
    #         raise ValueError("Invalid response from conversation manager")
            
    #     await update.message.reply_text(response)
    #     context.user_data['state'] = new_state
    #     return 1
        
    # except Exception as e:
    #     print(f"⚠️ Handle message error: {e}")
    #     await update.message.reply_text("Let's start fresh. How are you feeling?")
    #     return 1
        
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Goodbye! Type /start to chat again.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify user"""
    logger.error(f"⚠️ Error:  {context.error}")
    try:
        if update and update.message:
            await update.message.reply_text("Sorry, something went wrong. Please try again.")
        # await context.bot.send_message(
        #     chat_id=update.effective_chat.id,
        #     text="Sorry, something went wrong. Please try again."
        # )
    except:
        pass  # Prevent error loops

async def main_async():
    """Main async entry point"""
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .post_init(post_init) \
        .post_stop(post_stop) \
        .build()

# Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            WAITING_FOR_EMOTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    try:
        await application.initialize()
        await application.start()
        logger.info("🚀 Bot started successfully")
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await application.stop()
        await application.shutdown()
    
def main():
    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Verify single instance
    check_single_instance()
    atexit.register(cleanup_lock)
    
    # Start Flask health check
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Create application ONCE
    application = Application.builder() \
        .token(TELEGRAM_BOT_TOKEN) \
        .concurrent_updates(False) \
        .post_init(post_init) \
        .post_stop(post_stop) \
        .build()

    
    # conv_handler = ConversationHandler(
    #     entry_points=[CommandHandler('start', start)],
    #     states={
    #         ConversationState.WAITING_INITIAL: [
    #             MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    #         ],
    #         ConversationState.DISCUSSING_VERSE: [
    #             MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    #         ],
    #         ConversationState.DEEP_DIVE: [
    #             MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    #         ]
    #     },
    #     fallbacks=[CommandHandler('cancel', cancel)]
    # )
    


    # Run the application properly
    try:
        asyncio.run(main_async())
        # logger.info("🚀 Bot starting...")
        # application.run_polling(
        #     poll_interval=5.0,
        #     drop_pending_updates=True,
        #     close_loop=False
        # )
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        # Ensure cleanup runs
        loop = asyncio.new_event_loop()
        loop.run_until_complete(cleanup_lock())
        loop.close()
    
if __name__ == "__main__":
     # Verify environment variables
    if not all([TELEGRAM_BOT_TOKEN, API_BIBLE_KEY]):
        logger.error("❌ Missing required environment variables")
        sys.exit(1)

    main()
    

    # try:
    #     main()
    # except KeyboardInterrupt:
    #     print("🛑 Bot stopped by user")
    # except Exception as e:
    #     print(f"💥 Error: {e}")
    #     sys.exit(1)
    # finally:
    #     cleanup_lock()
