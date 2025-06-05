import html
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot.")
    await update.message.reply_html(
        f"Hi {user.mention_html()}!\n\n"
        "I'm your Calendar Assistant.\n"
        "Try asking:\n"
        "- 'What's on my calendar tomorrow?'\n"
        "- 'Show me next week'\n"
        "- 'Schedule lunch with Sarah Tuesday at 1pm'\n"
        "- 'Delete team meeting Thursday morning'\n"
        "- Manage your shopping with `/glist_show`\n\n"
        "Use /connect_calendar to link your Google Account.\n"
        "Type /help for more commands.",
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message listing commands."""
    logger.info(f"User {update.effective_user.id} requested help.")
    help_text = """
    You can talk to me naturally! Try things like:
    - `What's happening this weekend?`
    - `Summarize my Friday`
    - `Schedule team sync Wednesday 11 AM - 12 PM`
    - `Cancel the 3pm meeting tomorrow`
    - `Delete dentist appointment next month`

    Or use these commands:
    /start - Welcome message.
    /connect_calendar - Authorize access to your Google Calendar.
    /my_status - Check if your calendar is connected.
    /set_timezone - Set your timezone for accurate event times.
    /disconnect_calendar - Revoke access to your calendar.
    /summary `[time period]` - Explicitly request a summary.
    /glist_add `<item1> [item2 ...]` - Adds items to your grocery list.
    /glist_show - Shows your current grocery list.
    /glist_clear - Clears your entire grocery list.
    /share_glist - Share your grocery list with another user.
    /request_access `<time_period>` - Request calendar access from another user for a specific period.
    /help - Show this help message.
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display a reply keyboard with available commands."""
    assert update.message is not None
    keyboard = [
        ["/connect_calendar", "/my_status"],
        ["/set_timezone", "/disconnect_calendar"],
        ["/summary", "/glist_add"],
        ["/glist_show", "/glist_clear"],
        ["/share_glist", "/request_access"],
        ["/help"],
    ]
    try:
        reply_markup = ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=True
        )
    except TypeError:
        reply_markup = ReplyKeyboardMarkup()
        reply_markup.keyboard = keyboard
    await update.message.reply_text("Choose a command:", reply_markup=reply_markup)
