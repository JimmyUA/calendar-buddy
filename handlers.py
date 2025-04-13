# handlers.py
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re # Keep for potential simple logic

import config
import google_services as gs # For Calendar and Auth services
import llm_service          # Import LLM Service

logger = logging.getLogger(__name__)

# === Helper Function ===

def _format_event_time(event: dict) -> str:
    """Formats event start/end time nicely for display."""
    start_str = event['start'].get('dateTime', event['start'].get('date'))
    end_str = event['end'].get('dateTime', event['end'].get('date'))
    try:
        if 'date' in event['start']: # All day event
            start_dt = dateutil_parser.isoparse(start_str).date()
            return f"{start_dt.strftime('%a, %b %d')} (All day)"
        else: # Timed event
             start_dt = dateutil_parser.isoparse(start_str)
             end_dt = dateutil_parser.isoparse(end_str)
             start_fmt = start_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')
             end_fmt = end_dt.strftime('%I:%M %p %Z')
             if start_dt.date() != end_dt.date():
                 end_fmt = end_dt.strftime('%b %d, %Y %I:%M %p %Z')
             return f"{start_fmt} - {end_fmt}"
    except Exception as e:
        logger.error(f"Error parsing event time for formatting: {e}. Event: {event.get('id')}")
        return start_str # Fallback

# === Core Action Handlers (Internal) ===

async def _handle_general_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles general chat messages."""
    logger.info(f"Handling GENERAL_CHAT for user {update.effective_user.id}")
    # Call llm_service
    response_text = await llm_service.get_chat_response(text)
    if response_text:
        await update.message.reply_text(response_text)
    else:
        await update.message.reply_text("Sorry, I couldn't process that chat message right now.")

async def _handle_calendar_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_SUMMARY intent."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_SUMMARY for user {user_id}")
    time_period_str = parameters.get("time_period", "today")

    await update.message.reply_text(f"Okay, let me check your calendar for '{time_period_str}'...")

    # 1. Parse date range using LLM service
    parsed_range = await llm_service.parse_date_range_llm(time_period_str)
    start_date, end_date = None, None
    display_period_str = time_period_str

    if parsed_range:
        try:
            start_date = dateutil_parser.isoparse(parsed_range['start_iso'])
            end_date = dateutil_parser.isoparse(parsed_range['end_iso'])
            if start_date.tzinfo is None: start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None: end_date = end_date.replace(tzinfo=timezone.utc)
        except ValueError as e: logger.error(f"Error parsing ISO dates from LLM: {e}"); start_date = None

    if start_date is None or end_date is None:
        logger.warning(f"Date range parsing failed/fallback for '{time_period_str}'. Using today.")
        await update.message.reply_text(f"Had trouble understanding '{time_period_str}', showing today instead.")
        now = datetime.now(timezone.utc)
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        display_period_str = "today"

    if end_date <= start_date: # Ensure valid range
        end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        if end_date <= start_date: end_date = start_date + timedelta(seconds=1)

    # 2. Fetch events using Google service
    events = await gs.get_calendar_events(user_id, time_min=start_date, time_max=end_date)

    # 3. Format and send response
    if events is None:
        await update.message.reply_text("Sorry, I couldn't fetch your calendar events. Please ensure I have permission (/my_status) or try again later.")
    elif not events:
        await update.message.reply_text(f"No events found for '{display_period_str}'.")
    else:
        summary_lines = [f"🗓️ Events for {display_period_str}:"]
        for event in events:
            time_str = _format_event_time(event)
            summary_lines.append(f"- *{event.get('summary', 'No Title')}* ({time_str})")
        await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)


async def _handle_calendar_create(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_CREATE intent."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_CREATE for user {user_id}")
    event_description = parameters.get("event_description")

    if not event_description:
        logger.error(f"CALENDAR_CREATE handler called without event_description.")
        await update.message.reply_text("I understood you want to create an event, but missed the details. Please try again.")
        return

    await update.message.reply_text("Okay, processing that event...")

    # 1. Extract structured details using LLM service
    event_details = await llm_service.extract_event_details_llm(event_description)

    if not event_details:
         await update.message.reply_text("Sorry, I couldn't understand the event details well enough to schedule it. Could you try phrasing it differently?")
         return

    # 2. Prepare confirmation
    try:
        summary = event_details.get('summary')
        start_str = event_details.get('start_time')
        if not summary or not start_str: raise ValueError("Missing summary or start time")

        start_dt = dateutil_parser.isoparse(start_str)
        if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=timezone.utc)

        end_str = event_details.get('end_time')
        end_dt = dateutil_parser.isoparse(end_str) if end_str else None
        if end_dt and end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)
        final_end_dt = end_dt if end_dt else start_dt + timedelta(hours=1)
        if final_end_dt <= start_dt: final_end_dt = start_dt + timedelta(hours=1)

        google_event_data = {
            'summary': summary, 'location': event_details.get('location'),
            'description': event_details.get('description'),
            'start': {'dateTime': start_dt.isoformat()},
            'end': {'dateTime': final_end_dt.isoformat()}, }

        start_confirm = start_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')
        end_confirm = final_end_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')
        confirm_text = f"Create this event?\n\n" \
                       f"<b>Summary:</b> {summary}\n<b>Start:</b> {start_confirm}\n" \
                       f"<b>End:</b> {end_confirm}\n<b>Desc:</b> {event_details.get('description', 'N/A')}\n" \
                       f"<b>Loc:</b> {event_details.get('location', 'N/A')}"

        config.pending_events[user_id] = google_event_data
        keyboard = [[ InlineKeyboardButton("✅ Confirm", callback_data="confirm_event_create"),
                      InlineKeyboardButton("❌ Cancel", callback_data="cancel_event_create") ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_html(confirm_text, reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error preparing create confirmation for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I had trouble processing the event details (e.g., date/time format). Please try phrasing it differently.")


async def _handle_calendar_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_DELETE intent."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_DELETE for user {user_id}")
    event_description = parameters.get("event_description")

    if not event_description:
        logger.error(f"CALENDAR_DELETE handler called without event_description.")
        await update.message.reply_text("I understood you want to delete an event, but missed the details. Please try again.")
        return

    await update.message.reply_text(f"Okay, looking for events matching '{event_description[:50]}...'")

    # 1. Determine search window using LLM service
    parsed_range = await llm_service.parse_date_range_llm(event_description)
    search_start, search_end = None, None
    if parsed_range:
        try: search_start = dateutil_parser.isoparse(parsed_range['start_iso']); search_end = dateutil_parser.isoparse(parsed_range['end_iso']); search_start-=timedelta(minutes=1); search_end+=timedelta(minutes=1)
        except ValueError: search_start = None
    if not search_start: now = datetime.now(timezone.utc); search_start = now.replace(hour=0, minute=0, second=0, microsecond=0); search_end = now + timedelta(days=3)
    logger.info(f"Delete search window: {search_start.isoformat()} to {search_end.isoformat()}")

    # 2. Fetch potential events using Google service
    potential_events = await gs.get_calendar_events(user_id, time_min=search_start, time_max=search_end, max_results=25)

    if potential_events is None: await update.message.reply_text("Sorry, couldn't search your calendar now."); return
    if not potential_events: await update.message.reply_text(f"Didn't find any events around that time matching '{event_description[:50]}...'."); return

    # 3. Ask LLM service to find the best match
    logger.info(f"Asking LLM to match '{event_description}' against {len(potential_events)} candidates.")
    await update.message.reply_text("Analyzing potential matches...")
    match_result = await llm_service.find_event_match_llm(event_description, potential_events)

    if match_result is None: await update.message.reply_text("Sorry, had trouble analyzing potential matches."); return

    # 4. Process LLM result
    match_type = match_result.get('match_type')
    if match_type == 'NONE':
        await update.message.reply_text(f"Couldn't confidently match an event to '{event_description[:50]}...'. Can you be more specific?")
    elif match_type == 'SINGLE':
        event_index = match_result.get('event_index')
        if not (isinstance(event_index, int) and 0 <= event_index < len(potential_events)):
             logger.error(f"Handler received invalid event_index {event_index} from LLM matching.")
             await update.message.reply_text("Sorry, internal error identifying the matched event.")
             return

        event_to_delete = potential_events[event_index]
        event_id = event_to_delete.get('id')
        event_summary = event_to_delete.get('summary', 'No Title')
        time_confirm = _format_event_time(event_to_delete)

        if not event_id: logger.error(f"Matched event missing ID: {event_to_delete}"); await update.message.reply_text("Sorry, internal error retrieving event ID."); return

        confirm_text = f"Delete this event?\n\n<b>{event_summary}</b>\n({time_confirm})"
        config.pending_deletions[user_id] = {'event_id': event_id, 'summary': event_summary}
        keyboard = [[ InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                      InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete") ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_html(confirm_text, reply_markup=reply_markup)

    elif match_type == 'MULTIPLE':
        await update.message.reply_text("Found multiple events that might match. Please be more specific (e.g., include exact time or more title details).")


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
        "- 'Delete team meeting Thursday morning'\n\n" # Added delete example
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
    /disconnect_calendar - Revoke access to your calendar.
    /summary `[time period]` - Explicitly request a summary.
    /help - Show this help message.
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def connect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the Google Calendar OAuth flow."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated calendar connection.")
    if gs.is_user_connected(user_id):
         service = gs._build_calendar_service_client(user_id)
         if service: await update.message.reply_text("Calendar already connected!"); return
         else: await update.message.reply_text("Issue with stored connection. Reconnecting..."); gs.delete_user_token(user_id)

    flow = gs.get_google_auth_flow()
    if not flow: await update.message.reply_text("Error setting up connection."); return

    state = gs.generate_oauth_state(user_id)
    if not state: await update.message.reply_text("Error generating secure state."); return

    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent', state=state)
    keyboard = [[InlineKeyboardButton("Connect Google Calendar", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Click to connect your Google Calendar:", reply_markup=reply_markup)

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks connection status."""
    user_id = update.effective_user.id
    if gs.is_user_connected(user_id):
        service = gs._build_calendar_service_client(user_id)
        if service: await update.message.reply_text("✅ Calendar connected & credentials valid.")
        else: await update.message.reply_text("⚠️ Calendar connected, but credentials invalid. Try /disconnect_calendar and /connect_calendar.")
    else: await update.message.reply_text("❌ Calendar not connected. Use /connect_calendar.")

async def disconnect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Removes user's stored credentials."""
    user_id = update.effective_user.id
    deleted = gs.delete_user_token(user_id)
    # Clear any pending states associated with the user
    if user_id in config.pending_events: del config.pending_events[user_id]
    if user_id in config.pending_deletions: del config.pending_deletions[user_id]
    await update.message.reply_text("Calendar connection removed." if deleted else "Calendar wasn't connected.")

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the explicit /summary command."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} used /summary command. Args: {context.args}")
    if not gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect calendar first (/connect_calendar)."); return
    time_period_str = " ".join(context.args) if context.args else "today"
    await _handle_calendar_summary(update, context, {"time_period": time_period_str}) # Pass params dict

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles non-command messages using AI intent classification and delegates."""
    user_id = update.effective_user.id
    text = update.message.text
    if not text: return
    logger.info(f"Handler: Received message from user {user_id}: '{text[:50]}...'")

    # 1. Classify Intent using LLM service
    intent_data = await llm_service.classify_intent_and_extract_params(text)

    intent = "GENERAL_CHAT"; parameters = {}
    if intent_data: intent = intent_data.get("intent", "GENERAL_CHAT"); parameters = intent_data.get("parameters", {})
    else: logger.warning(f"Intent classification failed for user {user_id}. Defaulting to GENERAL_CHAT.")

    # 2. Check Connection if needed
    if intent in ["CALENDAR_SUMMARY", "CALENDAR_CREATE", "CALENDAR_DELETE"]:
        if not gs.is_user_connected(user_id):
            action = {"CALENDAR_SUMMARY": "view calendar", "CALENDAR_CREATE": "add events", "CALENDAR_DELETE": "delete events"}.get(intent, "manage calendar")
            await update.message.reply_text(f"To {action}, please connect calendar first (/connect_calendar)."); return

    # 3. Route to specific internal handler
    if intent == "CALENDAR_SUMMARY": await _handle_calendar_summary(update, context, parameters)
    elif intent == "CALENDAR_CREATE": await _handle_calendar_create(update, context, parameters)
    elif intent == "CALENDAR_DELETE": await _handle_calendar_delete(update, context, parameters)
    elif intent == "GENERAL_CHAT": await _handle_general_chat(update, context, text)
    else: logger.error(f"Handler: Unknown intent state: {intent}"); await _handle_general_chat(update, context, text)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data
    logger.info(f"Callback: Received query from user {user_id}: {callback_data}")

    # --- Event Creation ---
    if callback_data == "confirm_event_create":
        if user_id not in config.pending_events: await query.edit_message_text("Event details expired."); return
        event_details = config.pending_events.pop(user_id)
        await query.edit_message_text(f"Adding '{event_details.get('summary')}'...")
        success, msg, link = await gs.create_calendar_event(user_id, event_details)
        final_msg = msg + (f"\nView: {link}" if link else ""); await query.edit_message_text(final_msg)
        if not success and "Authentication failed" in msg and not gs.is_user_connected(user_id): logger.info(f"Token cleared for {user_id} during failed create.")

    elif callback_data == "cancel_event_create":
        if user_id in config.pending_events: del config.pending_events[user_id]
        await query.edit_message_text("Event creation cancelled.")

    # --- Event Deletion ---
    elif callback_data == "confirm_event_delete":
        if user_id not in config.pending_deletions: await query.edit_message_text("Confirmation expired."); return
        pending = config.pending_deletions.pop(user_id)
        event_id, summary = pending.get('event_id'), pending.get('summary', 'event')
        if not event_id: logger.error(f"Missing event_id for {user_id}"); await query.edit_message_text("Error: Missing event ID."); return
        await query.edit_message_text(f"Deleting '{summary}'...")
        success, msg = await gs.delete_calendar_event(user_id, event_id)
        await query.edit_message_text(msg)
        if not success and "Authentication failed" in msg and not gs.is_user_connected(user_id): logger.info(f"Token cleared for {user_id} during failed delete.")

    elif callback_data == "cancel_event_delete":
        if user_id in config.pending_deletions: del config.pending_deletions[user_id]
        await query.edit_message_text("Event deletion cancelled.")

    else:
        logger.warning(f"Callback: Unhandled callback data: {callback_data}")
        try: await query.edit_message_text("Action not understood or expired.")
        except Exception: pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    # Add more detailed logging if needed, e.g., context.chat_data, context.user_data
    # Consider using traceback module for full trace
    # import traceback
    # tb_string = traceback.format_exception(None, context.error, context.error.__traceback__)
    # logger.error("\n".join(tb_string))

    if isinstance(update, Update) and update.effective_message:
         try: await update.effective_message.reply_text("Sorry, an internal error occurred. Please try again.")
         except Exception as e: logger.error(f"Failed to send error message to user: {e}")