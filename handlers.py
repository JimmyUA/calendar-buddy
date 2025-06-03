# handlers.py
import html
import logging
import time # Added for timestamp logging
from datetime import datetime, timedelta, timezone # Ensure datetime is imported from datetime
from dateutil import parser as dateutil_parser # type: ignore
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, KeyboardButtonRequestUsers
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
# Timezone libraries
import pytz
from pytz.exceptions import UnknownTimeZoneError

import config
import google_services as gs  # For Calendar and Auth services
from google_services import (
    add_pending_event,
    get_pending_event,
    delete_pending_event,
    add_pending_deletion,
    get_pending_deletion,
    delete_pending_deletion,
)
import grocery_services as gls
from handler.message_formatter import create_final_message
from llm import llm_service
from llm.agent import initialize_agent
from time_util import format_to_nice_date
from utils import _format_event_time, escape_markdown_v2

logger = logging.getLogger(__name__)

# Define history constants
MAX_HISTORY_TURNS = 10  # Remember last 10 back-and-forth turns
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2
ASKING_TIMEZONE = range(1)


# === Helper Function ===

# === Helper Function ===
def _format_iso_datetime_for_display(iso_string: str, target_tz_str: str | None = None) -> str:
    """
    Formats an ISO datetime string for display, optionally converting to a target timezone.
    """
    try:
        dt_object = dateutil_parser.isoparse(iso_string)
        if target_tz_str:
            try:
                target_tz = pytz.timezone(target_tz_str)
                dt_object = dt_object.astimezone(target_tz)
                return dt_object.strftime('%Y-%m-%d %I:%M %p %Z')
            except UnknownTimeZoneError:
                logger.warning(f"Unknown timezone string '{target_tz_str}'. Falling back to UTC display.")
                dt_object = dt_object.astimezone(pytz.utc)
                return dt_object.strftime('%Y-%m-%d %I:%M %p UTC')
        # If no target_tz_str, format as is, ensuring it's identifiable (e.g. UTC if offset is Z)
        if dt_object.tzinfo:
            return dt_object.strftime('%Y-%m-%d %I:%M %p %Z') # Includes timezone if available
        else: # Naive datetime, assume UTC for clarity or raise error
            # For this bot, naive datetimes from LLM parsing should ideally be UTC or have offset.
            # If truly naive, it's ambiguous. Defaulting to show it as is with a note or UTC.
            return dt_object.strftime('%Y-%m-%d %I:%M %p (Timezone not specified, assumed UTC)')

    except ValueError:
        logger.error(f"Could not parse ISO string: {iso_string}")
        return iso_string # Return original if parsing fails


async def _get_user_tz_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> pytz.BaseTzInfo | None:
    """Gets user timezone object or prompts them to set it, returning None if prompt sent."""
    user_id = update.effective_user.id
    assert update.message is not None, "Update message should not be None for _get_user_tz_or_prompt"
    tz_str = await gs.get_user_timezone_str(user_id) # MODIFIED
    if tz_str:
        try:
            return pytz.timezone(tz_str)
        except UnknownTimeZoneError:
            logger.warning(f"Invalid timezone '{tz_str}' found in DB for user {user_id}. Prompting.")
            # Optionally delete invalid tz from DB here
    # If no valid timezone found
    await update.message.reply_text(
        "Please set your timezone first using the /set_timezone command so I can understand times correctly.")
    return None


# === Core Action Handlers (Internal) ===

async def _handle_general_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles general chat messages, managing conversation history."""
    user_id = update.effective_user.id
    logger.info(f"Handling GENERAL_CHAT for user {user_id} with history")

    # 1. Retrieve or initialize history from user_data
    # Old in-memory history:
    # if 'llm_history' not in context.user_data:
    #     context.user_data['llm_history'] = []
    # history: list[dict] = context.user_data['llm_history']

    # Load history from Firestore
    history = await gs.get_chat_history(user_id, "general")
    logger.debug(f"General Chat: Loaded {len(history)} messages from Firestore for user {user_id}")

    # 2. Add current user message to history (using the simple structure for storage)
    history.append({'role': 'user', 'content': text})
    # Save user message to Firestore
    await gs.add_chat_message(user_id, 'user', text, "general")

    # 3. Call LLM service with history
    response_text = await llm_service.get_chat_response(history)  # Pass the history

    # 4. Process response and update history
    if response_text:
        await update.message.reply_text(response_text)
        # Add bot's response to history
        history.append({'role': 'model', 'content': response_text})
        # Save bot response to Firestore
        await gs.add_chat_message(user_id, 'model', response_text, "general")
    else:
        # Handle LLM failure or blocked response
        await update.message.reply_text("Sorry, I couldn't process that chat message right now.")
        # Remove the last user message from history if the bot failed to respond
        # Note: With Firestore, this local pop() won't affect stored history.
        # The user message was already saved. This is a transient adjustment for the current interaction.
        if history and history[-1]['role'] == 'user':
            history.pop()

    # 5. Trim history - This is now handled by add_chat_message in Firestore
    # if len(history) > MAX_HISTORY_MESSAGES:
    #     logger.debug(f"Trimming history for user {user_id} from {len(history)} to {MAX_HISTORY_MESSAGES}")
    #     # Keep the most recent messages
    #     context.user_data['llm_history'] = history[-MAX_HISTORY_MESSAGES:]
    #     # Alternative: history = history[-MAX_HISTORY_MESSAGES:] # Reassign if not using user_data directly


async def _handle_calendar_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_SUMMARY intent using user's timezone."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_SUMMARY for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz: return  # Stop if user needs to set timezone

    time_period_str = parameters.get("time_period", "today")
    await update.message.reply_text(f"Okay, checking your calendar for '{time_period_str}'...")

    # 1. Parse date range using LLM with local time context
    now_local = datetime.now(user_tz)
    parsed_range = await llm_service.parse_date_range_llm(time_period_str, now_local.isoformat())

    start_date, end_date = None, None
    display_period_str = time_period_str

    if parsed_range:
        try:
            # Parse ISO strings (which have offset/Z)
            start_date = dateutil_parser.isoparse(parsed_range['start_iso'])
            end_date = dateutil_parser.isoparse(parsed_range['end_iso'])
            # Convert to user's timezone for accurate day/week boundaries if needed,
            # although passing ISO with offset to Google API often works well.
            # For calculating *local* start/end of day, we need user_tz
            # Example: If user asks for "today"
            if time_period_str.lower() == "today":
                start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
            # Need more sophisticated logic for "next week", "this weekend" based on user_tz

        except ValueError as e:
            logger.error(...); start_date = None

    if start_date is None or end_date is None:
        logger.warning(f"Date range parsing failed/fallback for '{time_period_str}'. Using local today.")
        await update.message.reply_text(
            f"Had trouble with '{time_period_str}', showing today ({now_local.strftime('%Y-%m-%d')}) instead.")
        start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        display_period_str = f"today ({now_local.strftime('%Y-%m-%d')})"

    if end_date <= start_date: end_date = start_date.replace(hour=23, minute=59, second=59,
                                                             microsecond=999999);  # Ensure valid range

    # 2. Fetch events (using the calculated datetimes, which are now timezone-aware)
    events = await gs.get_calendar_events(user_id, time_min=start_date, time_max=end_date)

    # 3. Format and send response
    if events is None: await update.message.reply_text("Sorry, couldn't fetch events."); return
    if not events: await update.message.reply_text(f"No events found for '{display_period_str}'."); return

    summary_lines = [f"🗓️ Events for {display_period_str} (Times in {user_tz.zone}):"]
    for event in events:
        time_str = _format_event_time(event, user_tz)  # Pass user_tz for formatting
        summary_lines.append(f"- *{event.get('summary', 'No Title')}* ({time_str})")
    await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)


async def _handle_calendar_create(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_CREATE intent using user's timezone."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_CREATE for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz: return

    event_description = parameters.get("event_description")
    if not event_description: logger.error(...); await update.message.reply_text(...); return

    await update.message.reply_text("Okay, processing that event...")

    # 1. Extract details using LLM with local time context
    now_local = datetime.now(user_tz)
    event_details = await llm_service.extract_event_details_llm(event_description, now_local.isoformat())

    if not event_details: await update.message.reply_text(...); return

    # 2. Prepare confirmation (parsing dates needs care)
    try:
        summary = event_details.get('summary')
        start_str = event_details.get('start_time')  # ISO string from LLM (should have offset)
        if not summary or not start_str: raise ValueError("Missing essential details")

        # Parse ISO string into aware datetime object
        start_dt = dateutil_parser.isoparse(start_str)
        # Convert to user's timezone for consistent display/handling if needed
        # start_dt_local = start_dt.astimezone(user_tz)

        end_str = event_details.get('end_time')
        end_dt = dateutil_parser.isoparse(end_str) if end_str else None
        # end_dt_local = end_dt.astimezone(user_tz) if end_dt else None

        # Default end time based on start time
        final_end_dt = end_dt if end_dt else start_dt + timedelta(hours=1)
        if final_end_dt <= start_dt: final_end_dt = start_dt + timedelta(hours=1)
        # final_end_dt_local = final_end_dt.astimezone(user_tz)

        # Prepare data for Google API: MUST include timeZone field
        google_event_data = {
            'summary': summary, 'location': event_details.get('location'),
            'description': event_details.get('description'),
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': user_tz.zone},  # Add IANA timeZone
            'end': {'dateTime': final_end_dt.isoformat(), 'timeZone': user_tz.zone},  # Add IANA timeZone
        }

        # Format confirmation message using the parsed (and potentially timezone-converted) times
        start_confirm = start_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z')  # Display in local TZ
        end_confirm = final_end_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z')
        confirm_text = f"Create this event?\n\n" \
                       f"<b>Summary:</b> {summary}\n<b>Start:</b> {start_confirm}\n" \
                       f"<b>End:</b> {end_confirm}\n<b>Desc:</b> {event_details.get('description', 'N/A')}\n" \
                       f"<b>Loc:</b> {event_details.get('location', 'N/A')}"

        if await add_pending_event(user_id, google_event_data): # MODIFIED
            keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm_event_create"),
                         InlineKeyboardButton("❌ Cancel", callback_data="cancel_event_create")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            logger.debug(f"Pending event data stored for user {user_id}: {google_event_data}. Confirmation text: {confirm_text}")
            await update.message.reply_html(confirm_text, reply_markup=reply_markup)
        else:
            logger.error(f"Failed to store pending event for user {user_id} in Firestore.")
            await update.message.reply_text("Sorry, there was an issue preparing your event. Please try again.")

    except Exception as e:
        logger.error(f"Error preparing create confirmation for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Sorry, I had trouble processing the event details (e.g., date/time format). Please try phrasing it "
            "differently.")


async def _handle_calendar_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_DELETE intent using user's timezone."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_DELETE for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz: return

    event_description = parameters.get("event_description")
    if not event_description: logger.error(...); await update.message.reply_text(...); return

    await update.message.reply_text(f"Okay, looking for events matching '{event_description[:50]}...'")

    # 1. Determine search window using LLM with local time context
    now_local = datetime.now(user_tz)
    parsed_range = await llm_service.parse_date_range_llm(event_description, now_local.isoformat())
    search_start, search_end = None, None
    if parsed_range:
        try:
            search_start = dateutil_parser.isoparse(parsed_range['start_iso']); search_end = dateutil_parser.isoparse(
                parsed_range['end_iso']); search_start -= timedelta(minutes=1); search_end += timedelta(minutes=1)
        except ValueError:
            search_start = None
    if not search_start: now = datetime.now(timezone.utc); search_start = now.replace(hour=0, minute=0, second=0,
                                                                                      microsecond=0); search_end = now + timedelta(
        days=3)
    logger.info(f"Delete search window: {search_start.isoformat()} to {search_end.isoformat()}")

    # 2. Fetch potential events (gs)
    potential_events = await gs.get_calendar_events(user_id, time_min=search_start, time_max=search_end, max_results=25)

    if potential_events is None: await update.message.reply_text("Sorry, couldn't search your calendar now."); return
    if not potential_events: await update.message.reply_text(
        f"Didn't find any events around that time matching '{event_description[:50]}...'."); return

    # 3. Ask LLM service to find the best match
    logger.info(f"Asking LLM to match '{event_description}' against {len(potential_events)} candidates.")
    await update.message.reply_text("Analyzing potential matches...")
    match_result = await llm_service.find_event_match_llm(event_description, potential_events)

    if match_result is None: await update.message.reply_text("Sorry, had trouble analyzing potential matches."); return

    # 4. Process LLM result
    match_type = match_result.get('match_type')
    if match_type == 'NONE':
        await update.message.reply_text(
            f"Couldn't confidently match an event to '{event_description[:50]}...'. Can you be more specific?")
    elif match_type == 'SINGLE':
        event_index = match_result.get('event_index')
        if not (isinstance(event_index, int) and 0 <= event_index < len(potential_events)):
            logger.error(f"Handler received invalid event_index {event_index} from LLM matching.")
            await update.message.reply_text("Sorry, internal error identifying the matched event.")
            return

        event_to_delete = potential_events[event_index]
        event_id = event_to_delete.get('id')
        event_summary = event_to_delete.get('summary', 'No Title')
        time_confirm = _format_event_time(event_to_delete, user_tz)

        if not event_id: logger.error(f"Matched event missing ID: {event_to_delete}"); await update.message.reply_text(
            "Sorry, internal error retrieving event ID."); return

        confirm_text = f"Delete this event?\n\n<b>{event_summary}</b>\n({time_confirm})"
        pending_deletion_data = {'event_id': event_id, 'summary': event_summary}
        if await add_pending_deletion(user_id, pending_deletion_data): # MODIFIED
            keyboard = [[InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                         InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_html(confirm_text, reply_markup=reply_markup)
        else:
            logger.error(f"Failed to store pending deletion for user {user_id} in Firestore.")
            await update.message.reply_text("Sorry, there was an issue preparing for event deletion. Please try again.")

    elif match_type == 'MULTIPLE':
        await update.message.reply_text(
            "Found multiple events that might match. Please be more specific (e.g., include exact time or more title details).")


# === Telegram Update Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
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
        "- Manage your shopping with `/glist_show`\n\n" # Added grocery list example
        "Use /connect_calendar to link your Google Account.\n"
        "Type /help for more commands.",
        disable_web_page_preview=True
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a help message listing commands."""
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
    /request_access `<time_period>` - Request calendar access from another user for a specific period.
    /help - Show this help message.
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays a reply keyboard with available commands."""
    assert update.message is not None, "Update message should not be None"
    keyboard = [
        ["/connect_calendar", "/my_status"],
        ["/set_timezone", "/disconnect_calendar"],
        ["/summary", "/glist_add"],
        ["/glist_show", "/glist_clear"],
        ["/request_access", "/help"],
    ]
    try:
        reply_markup = ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=True
        )
    except TypeError:
        reply_markup = ReplyKeyboardMarkup()
        reply_markup.keyboard = keyboard
    await update.message.reply_text("Choose a command:", reply_markup=reply_markup)


async def request_calendar_access_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /request_access command.
    Step 1: Parses time period and prompts user to select a target user.
    Expected format: /request_access <natural language time period>
    Example: /request_access tomorrow from 10am to 2pm
    """
    assert update.effective_user is not None, "Effective user should not be None"
    assert update.message is not None, "Update message should not be None"
    assert context.user_data is not None, "Context user_data should not be None"

    requester_id = update.effective_user.id
    logger.info(f"User {requester_id} initiated /request_access (Step 1) with args: {context.args}")

    if not context.args:
        await update.message.reply_text(
            "Usage: /request_access <time period description>\n"
            "Example: /request_access tomorrow 10am to 2pm"
        )
        return

    time_period_str = " ".join(context.args)

    # 1. Check if requester is connected to Google Calendar
    if not await gs.is_user_connected(requester_id): # MODIFIED
        await update.message.reply_text("You need to connect your Google Calendar first. Use /connect_calendar.")
        return

    # 2. Parse the time period
    requester_tz = await _get_user_tz_or_prompt(update, context)
    if not requester_tz: # _get_user_tz_or_prompt already sent a message
        return

    now_local_requester = datetime.now(requester_tz)
    parsed_range = await llm_service.parse_date_range_llm(time_period_str, now_local_requester.isoformat())

    if not parsed_range or 'start_iso' not in parsed_range or 'end_iso' not in parsed_range:
        await update.message.reply_text(
            f"Sorry, I couldn't understand the time period: '{html.escape(time_period_str)}'. "
            "Please try being more specific, e.g., 'tomorrow from 10am to 2pm' or 'next Monday'."
        )
        return

    start_time_iso = parsed_range['start_iso']
    end_time_iso = parsed_range['end_iso']

    # Store parsed period in user_data for the next step (handling UsersShared)
    context.user_data['calendar_request_period'] = {
        'original': time_period_str,
        'start_iso': start_time_iso,
        'end_iso': end_time_iso
    }

    # Log the parsed times for verification
    try:
        start_dt_req_tz = dateutil_parser.isoparse(start_time_iso).astimezone(requester_tz)
        end_dt_req_tz = dateutil_parser.isoparse(end_time_iso).astimezone(requester_tz)
        logger.info(f"User {requester_id} stored time period for calendar request: {start_dt_req_tz.strftime('%Y-%m-%d %H:%M:%S %Z')} to {end_dt_req_tz.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    except Exception as e:
        logger.error(f"Error formatting parsed dates for logging (user {requester_id}): {e}")

    # 3. Send "Select User" prompt with KeyboardButtonRequestUsers
    keyboard_request_id = int(datetime.now().timestamp())
    context.user_data['select_user_request_id'] = keyboard_request_id

    button_request_users_config = KeyboardButtonRequestUsers(
        request_id=keyboard_request_id,
        user_is_bot=False,
        max_quantity=1
    )
    button_select_user = KeyboardButton(
        text="Select User To Request Access From",
        request_users=button_request_users_config
    )
    reply_markup = ReplyKeyboardMarkup(
        keyboard=[[button_select_user]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        "Okay, I have the time period: "
        f"\"<b>{html.escape(time_period_str)}</b>\".\n"
        "Now, please select the user you want to request calendar access from using the button below.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    logger.info(f"User {requester_id} prompted to select target user for calendar access request (KB request ID: {keyboard_request_id}).")


async def users_shared_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the response from KeyboardButtonRequestUsers.
    This is Step 2 of the calendar access request flow.
    """
    assert update.effective_user is not None, "Effective user (requester) should not be None"
    assert update.message is not None, "Update message should not be None for users_shared"
    assert update.message.users_shared is not None, "users_shared should not be None"
    assert context.user_data is not None, "Context user_data should not be None"

    requester_id = str(update.effective_user.id)
    requester_name = update.effective_user.first_name or "User" # Fallback for requester name
    requester_username = update.effective_user.username # May be None

    received_request_id = update.message.users_shared.request_id
    expected_request_id = context.user_data.get('select_user_request_id')

    logger.info(f"User {requester_id} shared users for keyboard request ID {received_request_id}. Expecting: {expected_request_id}")

    # Remove the reply keyboard as soon as possible.
    # We need to send a new message to do this if the users_shared update doesn't allow direct reply_markup removal.
    # A simple ack message is fine.
    # Note: The `update.message.reply_text` here is associated with the `users_shared` status update,
    # not a new command from the user. It effectively sends a new message to the chat.
    from telegram import ReplyKeyboardRemove # Local import for clarity
    await update.message.reply_text("Processing your selection...", reply_markup=ReplyKeyboardRemove())


    if expected_request_id is None or received_request_id != expected_request_id:
        logger.warning(
            f"User {requester_id} triggered UsersShared with unexpected/expired request_id: "
            f"Received {received_request_id}, expected {expected_request_id}."
        )
        # Send message via context.bot as update.message might not be suitable for a new message here
        await context.bot.send_message(chat_id=requester_id, text="This user selection is unexpected or has expired. Please try the /request_access command again.")
        return

    if not update.message.users_shared.users:
        logger.warning(f"User {requester_id} used user picker but shared no users for request_id {received_request_id}.")
        await context.bot.send_message(chat_id=requester_id, text="No user was selected. Please try again if you want to request access.")
        # Clear data as the flow is aborted
        context.user_data.pop('select_user_request_id', None)
        context.user_data.pop('calendar_request_period', None)
        return

    target_user = update.message.users_shared.users[0]
    target_user_id = str(target_user.user_id)
    # Use target_user.first_name, and if not available, try target_user.username, then a generic fallback.
    target_user_first_name = target_user.first_name or target_user.username or f"User ID {target_user_id}"


    request_period_data = context.user_data.get('calendar_request_period')

    # Clear temporary data now that we have the target user and period
    context.user_data.pop('select_user_request_id', None)
    context.user_data.pop('calendar_request_period', None)

    if not request_period_data:
        logger.error(f"User {requester_id}: calendar_request_period missing after user selection for target {target_user_id}.")
        await context.bot.send_message(chat_id=requester_id, text="Something went wrong, I don't have the time period for your request. Please start over with /request_access.")
        return

    start_iso = request_period_data['start_iso']
    end_iso = request_period_data['end_iso']
    original_period_str = request_period_data['original']

    if target_user_id == requester_id:
        await context.bot.send_message(chat_id=requester_id, text="You cannot request calendar access from yourself. Please try again with a different user.")
        return

    logger.info(f"User {requester_id} selected target user {target_user_id} ({target_user_first_name}) for period '{original_period_str}'")

    # Store Access Request in Firestore
    request_doc_id = await gs.add_calendar_access_request( # MODIFIED
        requester_id=requester_id,
        requester_name=requester_name,
        target_user_id=target_user_id,
        start_time_iso=start_iso,
        end_time_iso=end_iso
    )

    if not request_doc_id:
        await context.bot.send_message(chat_id=requester_id, text="Sorry, there was an internal error trying to store your access request. Please try again later.")
        return

    # Inform Requester
    await context.bot.send_message(
        chat_id=requester_id,
        text=f"Great! Your calendar access request for '<b>{html.escape(original_period_str)}</b>' "
             f"has been sent to <b>{html.escape(target_user_first_name)}</b>."
             f" (Request ID: `{request_doc_id}`)", # Added request ID for requester's reference
        parse_mode=ParseMode.HTML
    )

    # Notify Target User
    target_user_tz_str = await gs.get_user_timezone_str(int(target_user_id)) # MODIFIED # Fetch target's TZ for display
    start_display_for_target = _format_iso_datetime_for_display(start_iso, target_user_tz_str)
    end_display_for_target = _format_iso_datetime_for_display(end_iso, target_user_tz_str)

    # Get target user's Telegram username if available (from the shared user object)
    target_telegram_username = target_user.username or "N/A"


    target_message = (
        f"🔔 Calendar Access Request\n\n"
        f"User <b>{html.escape(requester_name)}</b> (Telegram: @{requester_username or 'N/A'}) "
        f"would like to view your calendar events for the period:\n"
        f"<b>From:</b> {start_display_for_target}\n"
        f"<b>To:</b>   {end_display_for_target}\n"
        f"(Original request from user: \"<i>{html.escape(original_period_str)}</i>\")\n\n"
        f"Do you approve this request?"
    )

    inline_keyboard = [
        [
            InlineKeyboardButton("✅ Approve Access", callback_data=f"approve_access_{request_doc_id}"),
            InlineKeyboardButton("❌ Deny Access", callback_data=f"deny_access_{request_doc_id}")
        ]
    ]
    inline_reply_markup = InlineKeyboardMarkup(inline_keyboard)

    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=target_message,
            reply_markup=inline_reply_markup,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Sent access request notification (ID: {request_doc_id}) to target user {target_user_id}.")
    except Exception as e:
        logger.error(f"Failed to send access request notification to target user {target_user_id} for request {request_doc_id}: {e}", exc_info=True)
        # Inform requester
        await context.bot.send_message(
             chat_id=requester_id,
             text=f"I've stored your request for <b>{html.escape(target_user_first_name)}</b> (Request ID: `{request_doc_id}`), "
                  "but I couldn't send them a direct notification. This can happen if they haven't started a chat with me, "
                  "or if they have blocked the bot. You might need to share the Request ID with them manually.",
             parse_mode=ParseMode.HTML
        )
        await gs.update_calendar_access_request_status(request_doc_id, "error_notifying_target") # MODIFIED


async def connect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the Google Calendar OAuth flow."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated calendar connection.")
    if await gs.is_user_connected(user_id): # MODIFIED
        service = await gs._build_calendar_service_client(user_id) # MODIFIED
        if service:
            await update.message.reply_text("Calendar already connected!"); return
        else:
            await update.message.reply_text("Issue with stored connection. Reconnecting...");
            await gs.delete_user_token(user_id) # MODIFIED

    flow = gs.get_google_auth_flow() # This remains synchronous as it doesn't involve I/O
    if not flow: await update.message.reply_text("Error setting up connection."); return

    state = await gs.generate_oauth_state(user_id) # MODIFIED
    if not state: await update.message.reply_text("Error generating secure state."); return

    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent', state=state)
    keyboard = [[InlineKeyboardButton("Connect Google Calendar", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Click to connect your Google Calendar:", reply_markup=reply_markup)


async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks connection status."""
    user_id = update.effective_user.id
    if await gs.is_user_connected(user_id): # MODIFIED
        service = await gs._build_calendar_service_client(user_id) # MODIFIED
        if service:
            await update.message.reply_text("✅ Calendar connected & credentials valid.")
        else:
            await update.message.reply_text(
                "⚠️ Calendar connected, but credentials invalid. Try /disconnect_calendar and /connect_calendar.")
    else:
        await update.message.reply_text("❌ Calendar not connected. Use /connect_calendar.")


async def disconnect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes user's stored credentials."""
    user_id = update.effective_user.id
    deleted = await gs.delete_user_token(user_id) # MODIFIED
    # Clear any pending states associated with the user from Firestore
    await delete_pending_event(user_id) # MODIFIED
    await delete_pending_deletion(user_id) # MODIFIED
    logger.info(f"Cleared pending event and deletion data for user {user_id} during disconnect.")
    await update.message.reply_text("Calendar connection removed." if deleted else "Calendar wasn't connected.")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the explicit /summary command."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} used /summary command. Args: {context.args}")
    if not await gs.is_user_connected(user_id): # MODIFIED
        await update.message.reply_text("Please connect calendar first (/connect_calendar).");
        return
    time_period_str = " ".join(context.args) if context.args else "today"
    await _handle_calendar_summary(update, context, {"time_period": time_period_str})  # Pass params dict


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles non-command messages by invoking the LangChain agent."""
    if not update.message or not update.message.text:
        logger.warning("handle_message received update without message text.")
        return
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"Agent Handler: Received message from user {user_id}: '{text[:50]}...'")

    # 1. Check connection status
    if not await gs.is_user_connected(user_id): # MODIFIED
        await update.message.reply_text("Please connect your Google Calendar first using /connect_calendar.")
        return

    # 2. Get user timezone (prompt if needed)
    user_timezone_str = await gs.get_user_timezone_str(user_id) # MODIFIED
    if not user_timezone_str:
        # Instead of blocking, maybe default and inform? Or stick to blocking.
        # Let's default to UTC for agent calls if not set, but inform user.
        user_timezone_str = 'UTC'
        await update.message.reply_text(
            "Note: Your timezone isn't set. Using UTC. Use /set_timezone for accurate local times.")
        # Alternative: Block until set
        # await update.message.reply_text("Please set timezone first (/set_timezone).")
        # return

    # 3. Retrieve/Initialize conversation history from context.user_data
    # Old in-memory history:
    # if 'lc_history' not in context.user_data:
    #     context.user_data['lc_history'] = []
    # chat_history: list[dict] = context.user_data['lc_history']  # Stores {'role': '...', 'content': '...'}
    
    # Load history from Firestore
    chat_history = await gs.get_chat_history(user_id, "lc")
    logger.debug(f"Agent Handler: Loaded {len(chat_history)} messages from Firestore for user {user_id}")

    # Add current user message to simple history list (for agent context)
    chat_history.append({'role': 'user', 'content': text})
    # Save user message to Firestore
    await gs.add_chat_message(user_id, 'user', text, "lc")

    # 4. Initialize Agent Executor (with user context and history)
    try:
        # Pass the simple history list; the initialize function converts it for LangChain memory
        agent_executor = initialize_agent(user_id, user_timezone_str, chat_history)
    except Exception as e:
        logger.error(f"Failed to initialize agent for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, there was an error setting up the AI agent.")
        chat_history.pop()  # Remove user message if agent failed to init
        return

    # 5. Invoke Agent Executor
    await update.message.chat.send_action(action="typing")  # Indicate thinking
    try:
        # Use ainvoke for async execution
        # Input structure depends on the prompt template (e.g., 'input' key)
        response = await agent_executor.ainvoke({
            "input": text
            # chat_history is handled by the memory object passed to AgentExecutor
        })
        agent_response = response.get('output', "Sorry, I didn't get a response.")

    except Exception as e:
        logger.error(f"Agent execution error for user {user_id}: {e}", exc_info=True)
        agent_response = "Sorry, an error occurred while processing your request with the agent."
        chat_history.pop()  # Remove user message if agent failed

        # --- Send Response & Check for Pending Actions ---
    final_message_to_send = agent_response  # Start with agent's direct output
    reply_markup = None

    # Check for pending event creation
    pending_event_data = await get_pending_event(user_id) # MODIFIED
    if pending_event_data:
        logger.info(f"Pending event create found for user {user_id} from Firestore. Formatting confirmation.")
        try:
            user_tz = pytz.timezone(user_timezone_str if user_timezone_str else 'UTC')
            final_message_to_send = await create_final_message(pending_event_data)
            keyboard = [[InlineKeyboardButton("✅ Confirm Create", callback_data="confirm_event_create"),
                         InlineKeyboardButton("❌ Cancel Create", callback_data="cancel_event_create")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Error formatting create confirmation in handler from Firestore data: {e}", exc_info=True)
            final_message_to_send = f"Error preparing event confirmation: {e}. Please try again."
            await delete_pending_event(user_id) # MODIFIED # Clear broken pending data
    else:
        # Only check for pending deletion if no pending creation
        pending_deletion_data = await get_pending_deletion(user_id) # MODIFIED
        if pending_deletion_data:
            logger.info(f"Pending event delete found for user {user_id} from Firestore. Formatting confirmation.")
            event_id_to_delete = pending_deletion_data.get('event_id')
            # Fetch full event details again to ensure the summary and time are current and correctly formatted
            event_details_for_confirm = await gs.get_calendar_event_by_id(user_id, event_id_to_delete)

            if event_details_for_confirm:
                try:
                    user_tz = pytz.timezone(user_timezone_str if user_timezone_str else 'UTC')
                    summary = event_details_for_confirm.get('summary', 'this event')
                    time_confirm = _format_event_time(event_details_for_confirm, user_tz)
                    final_message_to_send = (
                        f"Found event: '<b>{summary}</b>' ({time_confirm}).\n\n"
                        f"Should I delete this event?"
                    )
                except Exception as e:
                    logger.error(f"Error formatting delete confirmation in handler from Firestore data: {e}", exc_info=True)
                    summary = pending_deletion_data.get('summary', 'the selected event') # Fallback
                    final_message_to_send = f"Are you sure you want to delete '{summary}'?"
            else:
                # Event might have been deleted by something else
                summary = pending_deletion_data.get('summary', f'event ID {event_id_to_delete}')
                final_message_to_send = f"Could not re-fetch details for '{summary}' for deletion confirmation. It might no longer exist. Proceed with deleting?"
                # delete_pending_deletion(user_id) # Optional: Clear if event not found for confirm

            keyboard = [[InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                         InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the final message (either agent's direct output or handler-formatted confirmation)
    await update.message.reply_text(
        final_message_to_send, # Use the potentially overridden message
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    if agent_response and "error" not in agent_response.lower():  # Avoid saving error messages as model response
        chat_history.append({'role': 'model', 'content': agent_response})
        # Save agent response to Firestore
        await gs.add_chat_message(user_id, 'model', agent_response, "lc")

    # 7. Trim history - This is now handled by add_chat_message in Firestore
    # if len(chat_history) > config.MAX_HISTORY_MESSAGES:
    #     context.user_data['lc_history'] = chat_history[-config.MAX_HISTORY_MESSAGES:]

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    # await query.answer() # Moved into specific blocks
    user_id = query.from_user.id
    callback_data = query.data
    logger.info(f"Callback: Received query from user {user_id}: {callback_data}")

    # --- Event Creation ---
    if callback_data == "confirm_event_create":
        event_details = await get_pending_event(user_id) # MODIFIED # type: ignore
        if not event_details:
            await query.edit_message_text("Event details expired or not found.")
            return
        await query.edit_message_text(f"Adding '{event_details.get('summary', 'event')}' to your calendar...")
        success, msg, link = await gs.create_calendar_event(user_id, event_details)
        final_msg = msg + (f"\nView: <a href='{link}'>Event Link</a>" if link else "")
        await query.edit_message_text(final_msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await delete_pending_event(user_id) # MODIFIED # Clear after attempt
        if not success and "Authentication failed" in msg and not await gs.is_user_connected(user_id): # MODIFIED
            logger.info(f"Token potentially cleared for {user_id} during failed create confirmation.")

    elif callback_data == "cancel_event_create":
        await delete_pending_event(user_id) # MODIFIED
        await query.edit_message_text("Event creation cancelled.")

    # --- Event Deletion ---
    elif callback_data == "confirm_event_delete":
        pending_deletion_data = await get_pending_deletion(user_id) # MODIFIED # type: ignore
        if not pending_deletion_data:
            await query.edit_message_text("Confirmation for deletion expired or not found.")
            return
        event_id = pending_deletion_data.get('event_id')
        summary = pending_deletion_data.get('summary', 'the event')
        if not event_id:
            logger.error(f"Missing event_id in pending_deletion_data for user {user_id}")
            await query.edit_message_text("Error: Missing event ID for deletion.")
            await delete_pending_deletion(user_id) # MODIFIED # type: ignore # Clear broken data
            return
        await query.edit_message_text(f"Deleting '{summary}'...")
        success, msg = await gs.delete_calendar_event(user_id, event_id)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
        await delete_pending_deletion(user_id) # MODIFIED # type: ignore # Clear after attempt
        if not success and "Authentication failed" in msg and not await gs.is_user_connected(user_id): # MODIFIED # type: ignore
            logger.info(f"Token potentially cleared for {user_id} during failed delete confirmation.")

    elif callback_data == "cancel_event_delete":
        await delete_pending_deletion(user_id) # MODIFIED # type: ignore
        await query.edit_message_text("Event deletion cancelled.")

    # --- Calendar Access Request Handling ---
    elif callback_data.startswith("approve_access_"):
        request_id = callback_data.split("_")[-1]
        logger.info(f"[REQ_ID: {request_id}] Entered approve_access block at {time.time()}")
        logger.info(f"[REQ_ID: {request_id}] About to call query.answer() at {time.time()}")
        await query.answer() # Moved to the top
        logger.info(f"[REQ_ID: {request_id}] query.answer() completed at {time.time()}")

        logger.info(f"[REQ_ID: {request_id}] Calling gs.get_calendar_access_request at {time.time()}")
        request_data = await gs.get_calendar_access_request(request_id) # MODIFIED
        logger.info(f"[REQ_ID: {request_id}] gs.get_calendar_access_request returned at {time.time()}")

        if not request_data:
            await query.edit_message_text("This access request was not found or may have expired.")
            return
        if request_data.get('status') != "pending" and request_data.get('status') != "error_notifying_target":
            await query.edit_message_text(f"This request has already been actioned (status: {request_data.get('status')}).")
            return

        target_user_id = str(user_id) # The user clicking is the target
        if target_user_id != request_data.get('target_user_id'):
            logger.warning(f"User {user_id} tried to approve request {request_id} not meant for them (target: {request_data.get('target_user_id')})")
            await query.edit_message_text("Error: This request is not for you.")
            return

        if not await gs.is_user_connected(int(target_user_id)): # MODIFIED
            await query.edit_message_text("You (target user) need to connect your Google Calendar first via /connect_calendar before approving requests.")
            return

        logger.info(f"[REQ_ID: {request_id}] Calling gs.update_calendar_access_request_status at {time.time()}")
        status_updated = await gs.update_calendar_access_request_status(request_id, "approved") # MODIFIED
        logger.info(f"[REQ_ID: {request_id}] gs.update_calendar_access_request_status returned at {time.time()}")

        if status_updated:
            requester_id = request_data['requester_id']
            start_time_iso = request_data['start_time_iso']
            end_time_iso = request_data['end_time_iso']

            logger.info(f"[REQ_ID: {request_id}] Calling gs.get_calendar_events at {time.time()}")
            events = await gs.get_calendar_events(int(target_user_id), start_time_iso, end_time_iso)
            logger.info(f"[REQ_ID: {request_id}] gs.get_calendar_events returned at {time.time()}")

            escaped_requester_name = escape_markdown_v2(str(request_data.get('requester_name', 'them')))
            events_summary_message = f"🗓️ Calendar events for {escaped_requester_name} " \
                                     f"\(from your calendar\) for the period:\n" # Note the escaped \( and \)
            target_tz_str = await gs.get_user_timezone_str(int(target_user_id)) # MODIFIED
            target_tz = pytz.timezone(target_tz_str) if target_tz_str else pytz.utc

            if events is None:
                events_summary_message += "Could not retrieve events. There might have been an API error."
            elif not events:
                events_summary_message += "No events found in this period."
            else:
                for event in events:
                    time_str = _format_event_time(event, target_tz)

                    # New logic to ensure summary_content is never empty or just whitespace
                    raw_summary = event.get('summary') # Or event.get('summary', '')
                    if not raw_summary or raw_summary.isspace():
                        summary_content_for_escaping = "(No title)"
                    else:
                        summary_content_for_escaping = raw_summary

                    summary_text = escape_markdown_v2(summary_content_for_escaping)
                    escaped_time_str = escape_markdown_v2(time_str)
# Simplified format for diagnostics
                    events_summary_message += f"\nEvent: {summary_text} \(Time: {escaped_time_str}\)"
            
            try:
                logger.info(f"[REQ_ID: {request_id}] About to send message to requester at {time.time()}")

                # Escape dynamic parts for the main message
                target_user_display = escape_markdown_v2(str(request_data.get('target_user_id', 'the user')))
                period_start_display = escape_markdown_v2(_format_iso_datetime_for_display(start_time_iso))
                period_end_display = escape_markdown_v2(_format_iso_datetime_for_display(end_time_iso))

                requester_notification_text = (
                    f"🎉 Your calendar access request for {target_user_display} "
                    f"\(for period {period_start_display} to {period_end_display}\) was APPROVED\.\n\n"  # Escaped \(, \), and \.
                    f"{events_summary_message}" # events_summary_message components are already individually escaped
                )

                await context.bot.send_message(
                    chat_id=requester_id,
                    text=requester_notification_text,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                logger.info(f"[REQ_ID: {request_id}] Message sent to requester at {time.time()}")
            except Exception as e:
                logger.error(f"[REQ_ID: {request_id}] Failed to send approved notification to requester {requester_id}: {e}")

            logger.info(f"[REQ_ID: {request_id}] About to edit original message at {time.time()}")
            await query.edit_message_text(text="Access request APPROVED. The requester has been notified with the events.")
            logger.info(f"[REQ_ID: {request_id}] Original message edited at {time.time()}")
        else:
            await query.edit_message_text("Failed to update request status. Please try again.")

    elif callback_data.startswith("deny_access_"):
        await query.answer() # Moved to the top
        request_id = callback_data.split("_")[-1]
        logger.info(f"User {user_id} (target) attempts to deny access request {request_id}")
        request_data = await gs.get_calendar_access_request(request_id) # MODIFIED

        if not request_data:
            await query.edit_message_text("This access request was not found or may have expired.")
            return
        if request_data.get('status') != "pending" and request_data.get('status') != "error_notifying_target":
            await query.edit_message_text(f"This request has already been actioned (status: {request_data.get('status')}).")
            return

        target_user_id = str(user_id) # The user clicking is the target
        if target_user_id != request_data.get('target_user_id'):
            logger.warning(f"User {user_id} tried to deny request {request_id} not meant for them (target: {request_data.get('target_user_id')})")
            await query.edit_message_text("Error: This request is not for you.")
            return

        if await gs.update_calendar_access_request_status(request_id, "denied"): # MODIFIED
            requester_id = request_data['requester_id']
            try:
                await context.bot.send_message(
                    chat_id=requester_id,
                    text=f"😔 Your calendar access request for user (ID: {html.escape(request_data.get('target_user_id'))}) "
                         f"for the period {_format_iso_datetime_for_display(request_data['start_time_iso'])} to "
                         f"{_format_iso_datetime_for_display(request_data['end_time_iso'])} was DENIED."
                )
            except Exception as e:
                logger.error(f"Failed to send denied notification to requester {requester_id} for request {request_id}: {e}")

            await query.edit_message_text(text="Access request DENIED. The requester has been notified.")
        else:
            await query.edit_message_text("Failed to update request status. Please try again.")

    else:
        await query.answer() # Ensure it's called early for unhandled
        logger.warning(f"Callback: Unhandled callback data: {callback_data}")
        try:
            await query.edit_message_text("Action not understood or expired.")
        except Exception: # query may have expired
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    # Add more detailed logging if needed, e.g., context.chat_data, context.user_data
    # Consider using traceback module for full trace
    # import traceback
    # tb_string = traceback.format_exception(None, context.error, context.error.__traceback__)
    # logger.error("\n".join(tb_string))

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Sorry, an internal error occurred. Please try again.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")


# --- NEW /set_timezone Conversation Handler ---
async def set_timezone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the /set_timezone conversation."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started /set_timezone.")
    current_tz = await gs.get_user_timezone_str(user_id) # MODIFIED
    prompt = "Please tell me your timezone in IANA format (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo').\n"
    prompt += "You can find a list here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones\n\n"
    if current_tz:
        prompt += f"Your current timezone is set to: `{current_tz}`"
    else:
        prompt += "Your timezone is not set yet."

    await update.message.reply_text(prompt, parse_mode=ParseMode.MARKDOWN)
    return ASKING_TIMEZONE  # Transition to the next state


async def received_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives potential timezone string, validates, saves, and ends."""
    user_id = update.effective_user.id
    assert update.effective_user is not None, "Effective user should not be None in received_timezone"
    username = update.effective_user.username # Can be None
    timezone_str = update.message.text.strip()
    logger.info(f"User {user_id} (Username: {username}) provided timezone: {timezone_str}")

    try:
        # Validate using pytz
        pytz.timezone(timezone_str)
        # Save using google_services function
        success = await gs.set_user_timezone(user_id, timezone_str) # MODIFIED
        if success:
            await update.message.reply_text(f"✅ Timezone set to `{timezone_str}` successfully!",
                                            parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Successfully set timezone for user {user_id} (username not stored).")
            return ConversationHandler.END  # End conversation
        else:
            await update.message.reply_text("Sorry, there was an error saving your timezone. Please try again.")
            # Stay in the same state or end? Let's end for simplicity.
            return ConversationHandler.END

    except UnknownTimeZoneError:
        logger.warning(f"Invalid timezone provided by user {user_id}: {timezone_str}")
        await update.message.reply_text(
            f"Sorry, '{timezone_str}' doesn't look like a valid IANA timezone.\n"
            "Please use formats like 'Continent/City' (e.g., 'America/Los_Angeles'). "
            "Check the list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones\n"
            "Or type /cancel."
        )
        return ASKING_TIMEZONE  # Stay in the same state to allow retry
    except Exception as e:
        logger.error(f"Error processing timezone for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("An unexpected error occurred. Please try again later or /cancel.")
        return ConversationHandler.END


async def cancel_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the timezone setting conversation."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled timezone setting.")
    await update.message.reply_text("Timezone setup cancelled.")
    return ConversationHandler.END


# === Grocery List Handlers ===

async def glist_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adds items to the user's grocery list."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempting to add items to grocery list. Args: {context.args}")

    if not context.args:
        logger.info(f"User {user_id} called /glist_add without items.")
        await update.message.reply_text(
            "Please provide items to add. Usage: /glist_add item1 item2 ..."
        )
        return

    items_to_add = list(context.args) # context.args is a tuple

    if await gls.add_to_grocery_list(user_id, items_to_add):
        logger.info(f"Successfully added {len(items_to_add)} items for user {user_id}.")
        await update.message.reply_text(
            f"Added: {', '.join(items_to_add)} to your grocery list."
        )
    else:
        logger.error(f"Failed to add items to grocery list for user {user_id}.")
        await update.message.reply_text(
            "Sorry, there was a problem adding items to your grocery list."
        )


async def glist_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows the user's grocery list."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requesting to show grocery list.")

    grocery_list = await gls.get_grocery_list(user_id)

    if grocery_list is None:
        logger.error(f"Failed to retrieve grocery list for user {user_id} (gs returned None).")
        await update.message.reply_text(
            "Sorry, there was an error trying to get your grocery list."
        )
    elif not grocery_list: # Empty list
        logger.info(f"Grocery list is empty for user {user_id}.")
        await update.message.reply_text(
            "🛒 Your grocery list is empty! Add items with /glist_add item1 item2 ..."
        )
    else:
        logger.info(f"Retrieved {len(grocery_list)} items for user {user_id}.")
        message_lines = ["🛒 Your Grocery List:"]
        for item in grocery_list:
            message_lines.append(f"- {html.escape(item)}") # Escape HTML special chars
        
        await update.message.reply_text("\n".join(message_lines), parse_mode=ParseMode.HTML)


async def glist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears the user's grocery list."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requesting to clear grocery list.")

    if await gls.delete_grocery_list(user_id):
        logger.info(f"Successfully cleared grocery list for user {user_id}.")
        await update.message.reply_text("🗑️ Your grocery list has been cleared.")
    else:
        logger.error(f"Failed to clear grocery list for user {user_id}.")
        await update.message.reply_text(
            "Sorry, there was a problem clearing your grocery list."
        )
