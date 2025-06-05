import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
import pytz
from pytz.exceptions import UnknownTimeZoneError

import google_services as gs
from .helpers import ASKING_TIMEZONE

logger = logging.getLogger(__name__)


async def set_timezone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started /set_timezone.")
    current_tz = await gs.get_user_timezone_str(user_id)
    prompt = "Please tell me your timezone in IANA format (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo').\n"
    prompt += "You can find a list here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones\n\n"
    if current_tz:
        prompt += f"Your current timezone is set to: `{current_tz}`"
    else:
        prompt += "Your timezone is not set yet."

    await update.message.reply_text(prompt, parse_mode=ParseMode.MARKDOWN)
    return ASKING_TIMEZONE


async def received_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    assert update.effective_user is not None
    username = update.effective_user.username
    timezone_str = update.message.text.strip()
    logger.info(f"User {user_id} (Username: {username}) provided timezone: {timezone_str}")

    try:
        pytz.timezone(timezone_str)
        success = await gs.set_user_timezone(user_id, timezone_str)
        if success:
            await update.message.reply_text(f"✅ Timezone set to `{timezone_str}` successfully!", parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Successfully set timezone for user {user_id}.")
            return ConversationHandler.END
        else:
            await update.message.reply_text("Sorry, there was an error saving your timezone. Please try again.")
            return ConversationHandler.END
    except UnknownTimeZoneError:
        logger.warning(f"Invalid timezone provided by user {user_id}: {timezone_str}")
        await update.message.reply_text(
            f"Sorry, '{timezone_str}' doesn't look like a valid IANA timezone.\n"
            "Please use formats like 'Continent/City' (e.g., 'America/Los_Angeles'). "
            "Check the list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones\n"
            "Or type /cancel."
        )
        return ASKING_TIMEZONE
    except Exception as e:
        logger.error(f"Error processing timezone for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later or /cancel.")
        return ConversationHandler.END


async def cancel_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled timezone setting.")
    await update.message.reply_text("Timezone setup cancelled.")
    return ConversationHandler.END
