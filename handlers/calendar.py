import html
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUsers
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import pytz

import google_services as gs
import calendar_services as cs
from google_services import (
    add_pending_event,
    get_pending_event,
    delete_pending_event,
    add_pending_deletion,
    get_pending_deletion,
    delete_pending_deletion,
)
from llm import llm_service
from llm.agent import initialize_agent
from handler.message_formatter import create_final_message
from utils import _format_event_time, escape_markdown_v2
from .helpers import _get_user_tz_or_prompt, _format_iso_datetime_for_display

logger = logging.getLogger(__name__)


async def _handle_calendar_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_SUMMARY for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz:
        return

    time_period_str = parameters.get("time_period", "today")
    await update.message.reply_text(f"Okay, checking your calendar for '{time_period_str}'...")

    now_local = datetime.now(user_tz)
    parsed_range = await llm_service.parse_date_range_llm(time_period_str, now_local.isoformat())

    start_date, end_date = None, None
    display_period_str = time_period_str

    if parsed_range:
        try:
            start_date = dateutil_parser.isoparse(parsed_range['start_iso'])
            end_date = dateutil_parser.isoparse(parsed_range['end_iso'])
            if time_period_str.lower() == "today":
                start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            start_date = None

    if start_date is None or end_date is None:
        logger.warning(f"Date range parsing failed/fallback for '{time_period_str}'. Using local today.")
        await update.message.reply_text(
            f"Had trouble with '{time_period_str}', showing today ({now_local.strftime('%Y-%m-%d')}) instead.")
        start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        display_period_str = f"today ({now_local.strftime('%Y-%m-%d')})"

    if end_date <= start_date:
        end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    events = await cs.get_calendar_events(user_id, time_min=start_date, time_max=end_date)

    if events is None:
        await update.message.reply_text("Sorry, couldn't fetch events.")
        return
    if not events:
        await update.message.reply_text(f"No events found for '{display_period_str}'.")
        return

    summary_lines = [f"🗓️ Events for {display_period_str} (Times in {user_tz.zone}):"]
    for event in events:
        time_str = _format_event_time(event, user_tz)
        summary_lines.append(f"- *{event.get('summary', 'No Title')}* ({time_str})")
    await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)


async def _handle_calendar_create(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_CREATE for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz:
        return

    event_description = parameters.get("event_description")
    if not event_description:
        await update.message.reply_text("I need a description of the event.")
        return

    await update.message.reply_text("Okay, processing that event...")

    now_local = datetime.now(user_tz)
    event_details = await llm_service.extract_event_details_llm(event_description, now_local.isoformat())

    if not event_details:
        await update.message.reply_text("Sorry, I couldn't parse that event.")
        return

    try:
        summary = event_details.get('summary')
        start_str = event_details.get('start_time')
        if not summary or not start_str:
            raise ValueError("Missing essential details")

        start_dt = dateutil_parser.isoparse(start_str)
        end_str = event_details.get('end_time')
        end_dt = dateutil_parser.isoparse(end_str) if end_str else None

        final_end_dt = end_dt if end_dt else start_dt + timedelta(hours=1)
        if final_end_dt <= start_dt:
            final_end_dt = start_dt + timedelta(hours=1)

        google_event_data = {
            'summary': summary,
            'location': event_details.get('location'),
            'description': event_details.get('description'),
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': user_tz.zone},
            'end': {'dateTime': final_end_dt.isoformat(), 'timeZone': user_tz.zone},
        }

        start_confirm = start_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z')
        end_confirm = final_end_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z')
        confirm_text = (
            "Create this event?\n\n"
            f"<b>Summary:</b> {summary}\n<b>Start:</b> {start_confirm}\n"
            f"<b>End:</b> {end_confirm}\n<b>Desc:</b> {event_details.get('description', 'N/A')}\n"
            f"<b>Loc:</b> {event_details.get('location', 'N/A')}"
        )

        if await add_pending_event(user_id, google_event_data):
            keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm_event_create"),
                         InlineKeyboardButton("❌ Cancel", callback_data="cancel_event_create")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_html(confirm_text, reply_markup=reply_markup)
        else:
            logger.error(f"Failed to store pending event for user {user_id} in Firestore.")
            await update.message.reply_text("Sorry, there was an issue preparing your event. Please try again.")
    except Exception as e:
        logger.error(f"Error preparing create confirmation for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "Sorry, I had trouble processing the event details (e.g., date/time format). Please try phrasing it differently.")


async def _handle_calendar_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_DELETE for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz:
        return

    event_description = parameters.get("event_description")
    if not event_description:
        await update.message.reply_text("I need a description of the event to delete.")
        return

    await update.message.reply_text(f"Okay, looking for events matching '{event_description[:50]}...'")

    now_local = datetime.now(user_tz)
    parsed_range = await llm_service.parse_date_range_llm(event_description, now_local.isoformat())
    search_start, search_end = None, None
    if parsed_range:
        try:
            search_start = dateutil_parser.isoparse(parsed_range['start_iso'])
            search_end = dateutil_parser.isoparse(parsed_range['end_iso'])
            search_start -= timedelta(minutes=1)
            search_end += timedelta(minutes=1)
        except ValueError:
            search_start = None
    if not search_start:
        now = datetime.now(timezone.utc)
        search_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        search_end = now + timedelta(days=3)
    logger.info(f"Delete search window: {search_start.isoformat()} to {search_end.isoformat()}")

    potential_events = await cs.get_calendar_events(user_id, time_min=search_start, time_max=search_end, max_results=25)

    if potential_events is None:
        await update.message.reply_text("Sorry, couldn't search your calendar now.")
        return
    if not potential_events:
        await update.message.reply_text(
            f"Didn't find any events around that time matching '{event_description[:50]}...'.")
        return

    logger.info(f"Asking LLM to match '{event_description}' against {len(potential_events)} candidates.")
    await update.message.reply_text("Analyzing potential matches...")
    match_result = await llm_service.find_event_match_llm(event_description, potential_events)

    if match_result is None:
        await update.message.reply_text("Sorry, had trouble analyzing potential matches.")
        return

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

        if not event_id:
            logger.error(f"Matched event missing ID: {event_to_delete}")
            await update.message.reply_text("Sorry, internal error retrieving event ID.")
            return

        confirm_text = f"Delete this event?\n\n<b>{event_summary}</b>\n({time_confirm})"
        pending_deletion_data = {'event_id': event_id, 'summary': event_summary}
        if await add_pending_deletion(user_id, pending_deletion_data):
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


async def request_calendar_access_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_user is not None
    assert update.message is not None
    assert context.user_data is not None

    requester_id = update.effective_user.id
    logger.info(f"User {requester_id} initiated /request_access (Step 1) with args: {context.args}")

    if not context.args:
        await update.message.reply_text(
            "Usage: /request_access <time period description>\n"
            "Example: /request_access tomorrow 10am to 2pm"
        )
        return

    time_period_str = " ".join(context.args)

    if not await gs.is_user_connected(requester_id):
        await update.message.reply_text("You need to connect your Google Calendar first. Use /connect_calendar.")
        return

    requester_tz = await _get_user_tz_or_prompt(update, context)
    if not requester_tz:
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

    context.user_data['calendar_request_period'] = {
        'original': time_period_str,
        'start_iso': start_time_iso,
        'end_iso': end_time_iso,
    }

    keyboard_request_id = int(datetime.now().timestamp())
    context.user_data['select_user_request_id'] = keyboard_request_id

    button_request_users_config = KeyboardButtonRequestUsers(
        request_id=keyboard_request_id,
        user_is_bot=False,
        max_quantity=1,
    )
    button_select_user = KeyboardButton(
        text="Select User To Request Access From",
        request_users=button_request_users_config,
    )
    reply_markup = ReplyKeyboardMarkup(
        keyboard=[[button_select_user]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    await update.message.reply_text(
        "Okay, I have the time period: "
        f"\"<b>{html.escape(time_period_str)}</b>\".\n"
        "Now, please select the user you want to request calendar access from using the button below.",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"User {requester_id} prompted to select target user for calendar access request (KB request ID: {keyboard_request_id}).")


async def users_shared_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_user is not None
    assert update.message is not None
    assert update.message.users_shared is not None
    assert context.user_data is not None

    requester_id = str(update.effective_user.id)

    if context.user_data.get("share_glist_flow"):
        context.user_data.pop("share_glist_flow", None)
        from .grocery import _handle_glist_share_selection
        await _handle_glist_share_selection(update, context)
        return

    requester_name = update.effective_user.first_name or "User"
    requester_username = update.effective_user.username

    received_request_id = update.message.users_shared.request_id
    expected_request_id = context.user_data.get('select_user_request_id')

    logger.info(f"User {requester_id} shared users for keyboard request ID {received_request_id}. Expecting: {expected_request_id}")

    from telegram import ReplyKeyboardRemove
    await update.message.reply_text("Processing your selection...", reply_markup=ReplyKeyboardRemove())

    if expected_request_id is None or received_request_id != expected_request_id:
        logger.warning(
            f"User {requester_id} triggered UsersShared with unexpected/expired request_id: "
            f"Received {received_request_id}, expected {expected_request_id}."
        )
        await context.bot.send_message(chat_id=requester_id, text="This user selection is unexpected or has expired. Please try the /request_access command again.")
        return

    if not update.message.users_shared.users:
        logger.warning(f"User {requester_id} used user picker but shared no users for request_id {received_request_id}.")
        await context.bot.send_message(chat_id=requester_id, text="No user was selected. Please try again if you want to request access.")
        context.user_data.pop('select_user_request_id', None)
        context.user_data.pop('calendar_request_period', None)
        return

    target_user = update.message.users_shared.users[0]
    target_user_id = str(target_user.user_id)
    target_user_first_name = target_user.first_name or target_user.username or f"User ID {target_user_id}"

    request_period_data = context.user_data.get('calendar_request_period')
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

    request_doc_id = await gs.add_calendar_access_request(
        requester_id=requester_id,
        requester_name=requester_name,
        target_user_id=target_user_id,
        start_time_iso=start_iso,
        end_time_iso=end_iso,
    )

    if not request_doc_id:
        await context.bot.send_message(chat_id=requester_id, text="Sorry, there was an internal error trying to store your access request. Please try again later.")
        return

    await context.bot.send_message(
        chat_id=requester_id,
        text=f"Great! Your calendar access request for '<b>{html.escape(original_period_str)}</b>' "
             f"has been sent to <b>{html.escape(target_user_first_name)}</b>." \
             f" (Request ID: `{request_doc_id}`)",
        parse_mode=ParseMode.HTML,
    )

    target_user_tz_str = await gs.get_user_timezone_str(int(target_user_id))
    start_display_for_target = _format_iso_datetime_for_display(start_iso, target_user_tz_str)
    end_display_for_target = _format_iso_datetime_for_display(end_iso, target_user_tz_str)

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
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Sent access request notification (ID: {request_doc_id}) to target user {target_user_id}.")
    except Exception as e:
        logger.error(f"Failed to send access request notification to target user {target_user_id} for request {request_doc_id}: {e}", exc_info=True)
        await context.bot.send_message(
             chat_id=requester_id,
             text=f"I've stored your request for <b>{html.escape(target_user_first_name)}</b> (Request ID: `{request_doc_id}`), "
                  "but I couldn't send them a direct notification. This can happen if they haven't started a chat with me, "
                  "or if they have blocked the bot. You might need to share the Request ID with them manually.",
             parse_mode=ParseMode.HTML,
        )
        await gs.update_calendar_access_request_status(request_doc_id, "error_notifying_target")


async def connect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated calendar connection.")
    if await gs.is_user_connected(user_id):
        service = await gs._build_calendar_service_client(user_id)
        if service:
            await update.message.reply_text("Calendar already connected!")
            return
        else:
            await update.message.reply_text("Issue with stored connection. Reconnecting...")
            await gs.delete_user_token(user_id)

    flow = gs.get_google_auth_flow()
    if not flow:
        await update.message.reply_text("Error setting up connection.")
        return

    state = await gs.generate_oauth_state(user_id)
    if not state:
        await update.message.reply_text("Error generating secure state.")
        return

    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent', state=state)
    keyboard = [[InlineKeyboardButton("Connect Google Calendar", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Click to connect your Google Calendar:", reply_markup=reply_markup)


async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if await gs.is_user_connected(user_id):
        service = await gs._build_calendar_service_client(user_id)
        if service:
            await update.message.reply_text("✅ Calendar connected & credentials valid.")
        else:
            await update.message.reply_text(
                "⚠️ Calendar connected, but credentials invalid. Try /disconnect_calendar and /connect_calendar.")
    else:
        await update.message.reply_text("❌ Calendar not connected. Use /connect_calendar.")


async def disconnect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    deleted = await gs.delete_user_token(user_id)
    await delete_pending_event(user_id)
    await delete_pending_deletion(user_id)
    logger.info(f"Cleared pending event and deletion data for user {user_id} during disconnect.")
    await update.message.reply_text("Calendar connection removed." if deleted else "Calendar wasn't connected.")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} used /summary command. Args: {context.args}")
    if not await gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect calendar first (/connect_calendar).")
        return
    time_period_str = " ".join(context.args) if context.args else "today"
    await _handle_calendar_summary(update, context, {"time_period": time_period_str})
