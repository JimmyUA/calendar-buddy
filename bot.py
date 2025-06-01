# bot.py
import logging
import threading # Import threading
import atexit
from flask import Flask # Import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import google_services
import scheduler_jobs # Assuming this is in the root directory
from datetime import datetime, time
import pytz
from telegram import Bot, Update # Ensure Bot is imported
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

# --- Initialize Scheduler ---
scheduler = BackgroundScheduler(timezone="UTC") # Or configure as needed

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

async def scheduled_daily_job_wrapper(bot: Bot):
    logger.info("Scheduler: Running daily job wrapper...")
    users_to_notify = google_services.get_all_connected_user_ids_with_timezone()
    if not users_to_notify:
        logger.info("Scheduler: No users found for daily notifications.")
        return

    for user_info in users_to_notify:
        user_id = user_info['user_id']
        user_timezone_str = user_info['timezone']
        try:
            user_tz = pytz.timezone(user_timezone_str)
            now_user_local = datetime.now(user_tz)

            # Check if it's 22:00 in user's local time
            if now_user_local.hour == 22:
                logger.info(f"Scheduler: Triggering daily summary for user {user_id} at local time {now_user_local.strftime('%H:%M:%S')}")
                await scheduler_jobs.send_daily_event_summary(bot, user_id, user_timezone_str)
            # else:
                # logger.debug(f"Scheduler: Daily check for user {user_id}, local time {now_user_local.strftime('%H:%M')}, not 22:00.")

        except pytz.exceptions.UnknownTimeZoneError:
            logger.error(f"Scheduler: Unknown timezone '{user_timezone_str}' for user {user_id}. Cannot process daily job.")
        except Exception as e:
            logger.error(f"Scheduler: Error processing daily job for user {user_id}: {e}", exc_info=True)

async def scheduled_weekly_job_wrapper(bot: Bot):
    logger.info("Scheduler: Running weekly job wrapper...")
    users_to_notify = google_services.get_all_connected_user_ids_with_timezone()
    if not users_to_notify:
        logger.info("Scheduler: No users found for weekly notifications.")
        return

    for user_info in users_to_notify:
        user_id = user_info['user_id']
        user_timezone_str = user_info['timezone']
        try:
            user_tz = pytz.timezone(user_timezone_str)
            now_user_local = datetime.now(user_tz)

            # Check if it's Sunday (weekday() == 6) and 20:00 local time
            if now_user_local.weekday() == 6 and now_user_local.hour == 20:
                logger.info(f"Scheduler: Triggering weekly summary for user {user_id} at local time {now_user_local.strftime('%H:%M:%S')}")
                await scheduler_jobs.send_weekly_event_summary(bot, user_id, user_timezone_str)
            # else:
                # logger.debug(f"Scheduler: Weekly check for user {user_id}, local time {now_user_local.strftime('%A %H:%M')}, not Sunday 20:00.")

        except pytz.exceptions.UnknownTimeZoneError:
            logger.error(f"Scheduler: Unknown timezone '{user_timezone_str}' for user {user_id}. Cannot process weekly job.")
        except Exception as e:
            logger.error(f"Scheduler: Error processing weekly job for user {user_id}: {e}", exc_info=True)

def shutdown_scheduler():
    if scheduler.running:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()
        logger.info("Scheduler shut down.")

atexit.register(shutdown_scheduler)

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

    try:
        scheduler.start()
        logger.info("Scheduler started.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}", exc_info=True)
        # Decide if bot should exit or continue without scheduler
        # Depending on severity, might want to: return

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

    # Error Handler (Register last)
    application.add_error_handler(handlers.error_handler)

    # --- Add Jobs to Scheduler ---
    if scheduler.running: # Ensure scheduler started correctly
        # Pass application.bot to the job wrappers
        # Run daily check job e.g. every 15 minutes.
        # Users will only get actual message if it's their local 22:00.
        scheduler.add_job(
            scheduled_daily_job_wrapper,
            trigger=CronTrigger(minute='*/15'), # Check every 15 minutes
            args=[application.bot], # Pass bot instance
            id="daily_notifications_job",
            name="Daily Event Notifications Wrapper",
            replace_existing=True
        )
        # Run weekly check job e.g. every 15 minutes.
        scheduler.add_job(
            scheduled_weekly_job_wrapper,
            trigger=CronTrigger(minute='*/15'), # Check every 15 minutes
            args=[application.bot], # Pass bot instance
            id="weekly_notifications_job",
            name="Weekly Event Notifications Wrapper",
            replace_existing=True
        )
        logger.info("Scheduled daily and weekly notification wrapper jobs.")
    else:
        logger.error("Scheduler not running. Cannot schedule notification jobs.")

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