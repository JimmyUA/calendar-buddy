# bot.py
import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import config # Load config first
import handlers # Import our handler functions

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# Set higher logging level for httpx to avoid excessive DEBUG messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR) # Silence cache warnings

logger = logging.getLogger(__name__)

def main() -> None:
    """Start the bot."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not found in environment/config. Exiting.")
        return

    # Check if Firestore client is available after import
    if config.FIRESTORE_DB is None:
        logger.critical("FATAL: Firestore client failed to initialize. Exiting.")
        return

    logger.info("Starting bot...")

    # --- Create the Application ---
    # You can configure persistence here if using PTB's built-in options later
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- Register Handlers ---
    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("connect_calendar", handlers.connect_calendar))
    application.add_handler(CommandHandler("my_status", handlers.my_status))
    application.add_handler(CommandHandler("disconnect_calendar", handlers.disconnect_calendar))
    application.add_handler(CommandHandler("summary", handlers.summary_command))

    # Message Handler (for chat and natural language event creation)
    # Ensure it doesn't process commands
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    # Callback Query Handler (for inline buttons)
    application.add_handler(CallbackQueryHandler(handlers.button_callback))

    # Error Handler (Register last)
    application.add_error_handler(handlers.error_handler)

    # --- Start the Bot ---
    logger.info("Running bot polling...")
    # Start polling - this blocks until interrupted
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot stopped.")

if __name__ == "__main__":
    # **IMPORTANT:** Before running this, start the oauth_server.py in a separate terminal:
    # `python oauth_server.py`
    # Then run this bot script:
    # `python bot.py`
    main()