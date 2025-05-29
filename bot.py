# bot.py
import logging
import threading # Import threading
from flask import Flask # Import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler,
)
from handlers import (
    ASKING_TIMEZONE,
    glist_add,
    glist_clear,
    glist_show,
)
import config # Load config first (initializes Firestore, etc.)
import handlers

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO # Or logging.DEBUG
)
# Set higher logging level for libraries that produce too much noise
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

health_app = Flask(__name__)

@health_app.route('/', methods=['GET']) # Use /health endpoint
def health_check():
    # Basic check - just return OK if the server is running
    # More advanced checks could verify if the bot polling thread is alive
    return "OK", 200

def run_health_server():
    # Run Flask app on the port Cloud Run expects
    # Default to 8080 if PORT env var isn't set (for local testing)
    port = int(config.os.getenv('PORT', 8080))
    # Use '0.0.0.0' to be accessible within the container network
    logger.info(f"Starting health check server on port {port}...")
    # Turn off Flask's default logging if too noisy, rely on root logger
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)
    health_app.run(host='0.0.0.0', port=port, use_reloader=False)

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

    # --- Start Health Check Server in a separate thread ---
    # Make the thread a daemon thread so it exits when the main program exits
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("Health check server thread started.")

    # --- Create the Application ---
    application = (Application.builder()
                   .token(config.TELEGRAM_BOT_TOKEN)
                   .connection_pool_size(10)
                   .concurrent_updates(True)
                   .build())

    # --- Setup /set_timezone conversation ---
    timezone_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("set_timezone", handlers.set_timezone_start)],
        states={
            ASKING_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.received_timezone)],
        },
        fallbacks=[CommandHandler("cancel", handlers.cancel_timezone)],
         # Optional: Add conversation timeout, persistence etc.
    )
    application.add_handler(timezone_conv_handler)

    # --- Register Handlers ---
    # Commands
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("connect_calendar", handlers.connect_calendar))
    application.add_handler(CommandHandler("my_status", handlers.my_status))
    application.add_handler(CommandHandler("disconnect_calendar", handlers.disconnect_calendar))
    application.add_handler(CommandHandler("summary", handlers.summary_command))
    application.add_handler(CommandHandler("request_access", handlers.request_calendar_access_command)) # New Command

    # Grocery List Command Handlers
    application.add_handler(CommandHandler("glist_add", handlers.glist_add))
    application.add_handler(CommandHandler("glist_show", handlers.glist_show))
    application.add_handler(CommandHandler("glist_clear", handlers.glist_clear))

    # Message Handler (for natural language processing)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    # Callback Query Handler (for inline buttons)
    application.add_handler(CallbackQueryHandler(handlers.button_callback))

    # Message Handler (now invokes the agent)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_message))

    # Handler for UsersShared status update (for KeyboardButtonRequestUsers)
    application.add_handler(MessageHandler(filters.StatusUpdate.USERS_SHARED, handlers.users_shared_handler))

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