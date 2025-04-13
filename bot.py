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

import config # Load config first (initializes Firestore, etc.)
import handlers # Import our handler functions

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO # Or logging.DEBUG
)
# Set higher logging level for libraries that produce too much noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

def main() -> None:
    """Start the bot."""
    if not config.TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not found. Exiting.")
        return
    # Check if essential services initialized correctly
    if config.FIRESTORE_DB is None:
        logger.critical("Firestore client failed initialization. Exiting.")
        return
    # LLM service availability check (optional, bot can run without LLM for basic auth/commands)
    # if not llm_service.llm_available:
    #     logger.warning("LLM Service not available. Some features will be disabled.")

    logger.info("Starting bot...")

    # --- Create the Application ---
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # --- Register Handlers ---
    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("connect_calendar", handlers.connect_calendar))
    application.add_handler(CommandHandler("my_status", handlers.my_status))
    application.add_handler(CommandHandler("disconnect_calendar", handlers.disconnect_calendar))
    application.add_handler(CommandHandler("summary", handlers.summary_command))

    # Message Handler (for natural language processing)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    # Callback Query Handler (for inline buttons)
    application.add_handler(CallbackQueryHandler(handlers.button_callback))

    # Error Handler (Register last)
    application.add_error_handler(handlers.error_handler)

    # --- Start the Bot ---
    logger.info("Running bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot stopped.")

if __name__ == "__main__":
    # **IMPORTANT:** Remember to run oauth_server.py in a separate terminal first!
    # `python oauth_server.py`
    # Then run this bot script:
    # `python bot.py`
    main()