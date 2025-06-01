import logging
from telegram import Bot # For type hinting the bot instance

# Assuming these modules are in the root or accessible via PYTHONPATH
import google_services
import time_util
import handler.message_formatter # Corrected import path

logger = logging.getLogger(__name__)

async def send_daily_event_summary(bot: Bot, user_id: int, user_timezone_str: str):
    """
    Fetches and sends the daily event summary for a specific user.
    """
    logger.info(f"Attempting to send daily summary for user {user_id} in timezone {user_timezone_str}")
    try:
        # 1. Calculate "next day" date range for the user's timezone
        start_iso, end_iso = time_util.get_next_day_range_iso(user_timezone_str)
        logger.debug(f"User {user_id}: Calculated next day range: {start_iso} to {end_iso}")

        # 2. Fetch calendar events for that range
        events = await google_services.get_calendar_events(user_id, start_iso, end_iso)

        if events is None:
            logger.warning(f"User {user_id}: Failed to fetch calendar events (received None). Skipping daily summary.")
            # Optionally send a message about the failure, or just log
            # await bot.send_message(chat_id=user_id, text="Sorry, I couldn't fetch your calendar events for tomorrow's summary.")
            return

        logger.debug(f"User {user_id}: Fetched {len(events)} events for daily summary.")

        # 3. Format the events into a message
        # The format_daily_summary function already handles the "no events" case by returning a specific message.
        message = handler.message_formatter.format_daily_summary(events, user_timezone_str)
        logger.debug(f"User {user_id}: Formatted daily summary message.")

        # 4. Send the message
        # The message will either be the "no events" message or the formatted list of events.
        if message: # Ensure message is not empty if format_daily_summary could return empty for some reason
            await bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')
            logger.info(f"Successfully sent daily summary to user {user_id}")
        else:
            logger.info(f"User {user_id}: Daily summary message was empty after formatting. Not sending.")

    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"User {user_id}: Invalid timezone '{user_timezone_str}'. Cannot generate daily summary.")
        # Optionally inform the user they have an invalid timezone set.
        # await bot.send_message(chat_id=user_id, text=f"Your configured timezone '{user_timezone_str}' is invalid. Please set a valid one using /set_timezone.")
    except Exception as e:
        logger.error(f"Error sending daily summary to user {user_id}: {e}", exc_info=True)
        # Optionally, send a generic error message to the user
        # await bot.send_message(chat_id=user_id, text="Sorry, an error occurred while generating your daily summary.")


async def send_weekly_event_summary(bot: Bot, user_id: int, user_timezone_str: str):
    """
    Fetches and sends the weekly event summary for a specific user.
    """
    logger.info(f"Attempting to send weekly summary for user {user_id} in timezone {user_timezone_str}")
    try:
        # 1. Calculate "next week" date range for the user's timezone
        start_iso, end_iso = time_util.get_next_week_range_iso(user_timezone_str)
        logger.debug(f"User {user_id}: Calculated next week range: {start_iso} to {end_iso}")

        # 2. Fetch calendar events for that range
        events = await google_services.get_calendar_events(user_id, start_iso, end_iso)

        if events is None:
            logger.warning(f"User {user_id}: Failed to fetch calendar events (received None). Skipping weekly summary.")
            # await bot.send_message(chat_id=user_id, text="Sorry, I couldn't fetch your calendar events for the weekly summary.")
            return

        logger.debug(f"User {user_id}: Fetched {len(events)} events for weekly summary.")

        # 3. Format the events into a message
        # The format_weekly_summary function already handles the "no events" case.
        message = handler.message_formatter.format_weekly_summary(events, user_timezone_str)
        logger.debug(f"User {user_id}: Formatted weekly summary message.")

        # 4. Send the message
        if message:
            await bot.send_message(chat_id=user_id, text=message, parse_mode='HTML')
            logger.info(f"Successfully sent weekly summary to user {user_id}")
        else:
            logger.info(f"User {user_id}: Weekly summary message was empty after formatting. Not sending.")

    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"User {user_id}: Invalid timezone '{user_timezone_str}'. Cannot generate weekly summary.")
        # await bot.send_message(chat_id=user_id, text=f"Your configured timezone '{user_timezone_str}' is invalid for the weekly summary. Please set a valid one using /set_timezone.")
    except Exception as e:
        logger.error(f"Error sending weekly summary to user {user_id}: {e}", exc_info=True)
        # await bot.send_message(chat_id=user_id, text="Sorry, an error occurred while generating your weekly summary.")
