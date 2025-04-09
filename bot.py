import os
import asyncio
import requests
import threading
import random
import sys
import atexit
import re
import psutil
import openai  # Added for AI conversations
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # New for AI conversations
WAITING_FOR_EMOTION = 1
GENERAL_CONVERSATION = 2  # New state for AI conversations
LOCKFILE_PATH = "/tmp/bot.lock"

# API.Bible configuration
API_BIBLE_URL = "https://api.scripture.api.bible/v1/bibles"
DEFAULT_BIBLE_ID = "de4e12af7f28f599-01"

# Initialize OpenAI
openai.api_key = OPENAI_API_KEY

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
    "grieving": ["Revelation 21:4", "Psalm 34:18", "Mathew 5:4"],
    "hopeless": ["Romans 15:13", "Jeremiah 29:11", "Psalm 42:11"],
    "tempted": ["1 Corinthians 10:13", "James 4:7", "Hebrews 2:18"],
    "thankful": ["1 Thessalonians 5:18", "Psalm 107:1", "Colossians 3:15"],
    "weary": ["Matthew 11:28", "Galatians 6:9", "Isaiah 40:31"],
    "doubtful": ["Mark 9:24", "James 1:6", "Matthew 21:21"]
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
    """More robust instance checking"""
    current_pid = os.getpid()
    try:
        if os.path.exists(LOCKFILE_PATH):
            with open(LOCKFILE_PATH, 'r') as f:
                pid_str = f.read().strip()
                if pid_str and pid_str.isdigit():
                    existing_pid = int(pid_str)
                    # Check if process exists AND isn't ourselves
                    if existing_pid != current_pid and psutil.pid_exists(existing_pid):
                        try:
                            # Send SIGTERM to the existing process
                            os.kill(existing_pid, 15)
                            logger.warning(f"Terminated duplicate instance (PID: {existing_pid})")
                        except:
                            logger.warning(f"Found stale lockfile from PID: {existing_pid}")
                        os.remove(LOCKFILE_PATH)
        
        # Create new lockfile
        with open(LOCKFILE_PATH, 'w') as f:
            f.write(str(current_pid))
        return True
    except Exception as e:
        logger.error(f"Instance check failed: {e}")
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

async def generate_ai_response(prompt):
    """Generate AI response using OpenAI"""
    try:
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a compassionate Christian counselor. Provide biblical wisdom and comfort in your responses."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )
        return response.choices[0].message.content
    except openai.error.APIError as e:
        logger.error(f"OpenAI API Error: {e}")
        return "I'm having technical difficulties. Please try again later."
    except Exception as e:
        logger.error(f"Unexpected AI Error: {e}")
        return "Something went wrong. Could you please rephrase your question?"
# --- Handler Functions ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        logger.info(f"🚩 Start command from {update.effective_user.id}")
        await update.message.reply_text(
            "Hello! I'm here to help. You can:\n"
            "1. Share how you're feeling (sad, anxious, etc)\n"
            "2. Ask me any question about faith or life\n"
            "3. Get biblical encouragement\n\n"
            "How are you feeling today?",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    ["1. Get verse", "2. Talk"],  # Numeric options like in image
                    ["3. Help", "4. Cancel"]
                ],
                one_time_keyboard=True,
                resize_keyboard=True
            )
        )
        return WAITING_FOR_EMOTION
    except Exception as e:
        logger.error(f"Start command error: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try /start again.")
        return ConversationHandler.END

async def handle_emotion_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's choice between verse or conversation"""
    try:
        text = update.message.text.lower()
        
        if "verse" in text or "3874" in text:  # Added numeric code from image
            await update.message.reply_text(
                "How are you feeling?",
                reply_markup=ReplyKeyboardMarkup(
                    [["Sad", "Anxious", "Lonely"], 
                     ["Angry", "Scared", "Discouraged"]], 
                    one_time_keyboard=True
                )
            )
            return WAITING_FOR_EMOTION
        elif "talk" in text:
            await update.message.reply_text(
                "I'm here to listen. What would you like to talk about?",
                reply_markup=ReplyKeyboardMarkup([["/cancel"]], one_time_keyboard=True)
            )
            return GENERAL_CONVERSATION
        elif text in [e.lower() for e in bible_references.keys()]:
            # Handle direct emotion input
            verse, message = get_bible_verse(text)
            await update.message.reply_text(f"{verse}\n\n{message}")
            await update.message.reply_text(
                "Would you like to talk more about this?",
                reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True)
            )
            return GENERAL_CONVERSATION
        else:
            await update.message.reply_text(
                "Please choose 'I need a verse' or 'I want to talk'",
                reply_markup=ReplyKeyboardMarkup(
                    [["I need a verse"], ["I want to talk"]], 
                    one_time_keyboard=True
                )
            )
            return WAITING_FOR_EMOTION
    except Exception as e:
        logger.error(f"Choice handler error: {e}")
        await update.message.reply_text("Sorry, I didn't understand. Please try /start again.")
        return ConversationHandler.END

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages for emotion-based verses"""
    try:
        text = update.message.text.lower()
        if text in bible_references:
            verse, message = get_bible_verse(text)
            await update.message.reply_text(f"{verse}\n\n{message}")
            await update.message.reply_text("Would you like to talk more about this?", 
                                          reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True))
            return GENERAL_CONVERSATION if text == "yes" else WAITING_FOR_EMOTION
        else:
            await update.message.reply_text("Please choose one of the suggested emotions")
            return WAITING_FOR_EMOTION
    except Exception as e:
        logger.error(f"Message handler error: {e}")
        await update.message.reply_text("Sorry, I didn't understand that. Please try /start again.")
        return ConversationHandler.END

async def handle_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle general conversation with AI"""
    try:
        user_message = update.message.text.lower()
        
        # Handle cancellation
        if user_message in ["no", "cancel"]:
            await update.message.reply_text("Okay, no problem. Type /start whenever you'd like to talk again.")
            return ConversationHandler.END
            
        # Show typing indicator
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        
        # First check if message matches any emotional keywords
        emotion_keywords = {
            'alone': ['alone', 'lonely', 'isolated'],
            'mess': ['mess', 'chaos', 'overwhelmed'],
            'anxious': ['anxious', 'worried', 'nervous'],
            'sad': ['sad', 'depressed', 'hopeless'],
            # Add more emotion mappings here
        }
        
        detected_emotion = None
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in user_message for keyword in keywords):
                detected_emotion = emotion
                break
        
        # If emotion detected, provide Bible verse first
        if detected_emotion:
            verse, explanation = get_bible_verse(detected_emotion)
            await update.message.reply_text(f"{verse}\n\n{explanation}")
            await asyncio.sleep(1)  # Small delay
            follow_up = "Would you like to talk more about how you're feeling?"
            await update.message.reply_text(follow_up, 
                                          reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True))
            return GENERAL_CONVERSATION
        
        # Otherwise use AI for general conversation
        system_prompt = """You are a compassionate Christian counselor. Respond with:
        1. Relevant Bible verses (use format "Book Chapter:Verse")
        2. Practical advice
        3. Follow-up questions
        Be kind, concise, and scripture-focused."""
        
        response = await openai.ChatCompletion.acreate(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7,
            max_tokens=300
        )
        
        ai_response = response.choices[0].message.content
        
        # Ensure response isn't empty
        if not ai_response.strip():
            raise ValueError("Empty AI response")
            
        await update.message.reply_text(ai_response)
        return GENERAL_CONVERSATION
        
    except Exception as e:
        logger.error(f"Conversation error: {e}")
        # Provide default Bible verse when errors occur
        verse, explanation = get_bible_verse('sad')  # Default comfort verse
        await update.message.reply_text(f"I want to offer you this encouragement:\n\n{verse}\n\n{explanation}")
        return GENERAL_CONVERSATION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    await update.message.reply_text("Goodbye! Type /start to chat again.")
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify user"""
    logger.error(f"⚠️ Error: {context.error}")
    if update and update.message:
        await update.message.reply_text("Sorry, something went wrong. Please try again.")

async def post_init(application: Application):
    """Run after bot is initialized"""
    try:
        logger.info(f"✅ Bot initialized - PID: {os.getpid()}")
        # Verify single instance
        if not await enforce_single_instance():
            logger.error("Duplicate instance detected")
            await application.stop()
            sys.exit(1)
            
        # Set bot commands
        await application.bot.set_my_commands([
            ("start", "Begin conversation"),
            ("cancel", "End conversation")
        ])
        logger.info("⌨️ Commands set up")
        
    except Exception as e:
        logger.error(f"Post-init error: {e}")
        raise

async def post_stop(application: Application):
    """Run before bot is stopped"""
    try:
        logger.info("🛑 Stopping bot...")
        await cleanup_lock()
    except Exception as e:
        logger.error(f"Post-stop error: {e}")
    finally:
        logger.info("🧹 Cleanup complete")
        
async def run_bot():
    """Main bot running routine with proper lifecycle management"""
    application = None
    try:
        # 1. Instance check
        if not await enforce_single_instance():
            logger.error("❌ Another instance is running. Exiting.")
            return

        # 2. Initialize application
        application = Application.builder() \
            .token(TELEGRAM_BOT_TOKEN) \
            .post_init(post_init) \
            .post_stop(post_stop) \
            .build()

        # 3. Add handlers
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                WAITING_FOR_EMOTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_emotion_choice)
                ],
                GENERAL_CONVERSATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_conversation)
                ]
            },
            fallbacks=[CommandHandler('cancel', cancel)],
            allow_reentry=True
        )
        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)

        # 4. Start with clean state
        await application.initialize()
        await application.bot.delete_webhook(drop_pending_updates=True)
        
        # 5. Start polling
        logger.info("🔄 Starting polling...")
        await application.start()
        await application.updater.start_polling(
            poll_interval=3.0,
            timeout=30,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
        # 6. Keep alive
        while True:
            await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        logger.info("🧹 Cleaning up resources...")
        if application:
            try:
                if hasattr(application, 'updater') and application.updater.running:
                    await application.updater.stop()
                await application.stop()
                await application.shutdown()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
        await cleanup_lock()
        logger.info("🎯 Cleanup complete")

def main():
    """Synchronous entry point"""
    # Start Flask in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()

    # Run the bot with proper cleanup
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
    finally:
        logger.info("🏁 Application terminated")

if __name__ == "__main__":
    if not all([TELEGRAM_BOT_TOKEN, API_BIBLE_KEY, OPENAI_API_KEY]):
        logger.error("❌ Missing required environment variables")
        sys.exit(1)
        
    main()
