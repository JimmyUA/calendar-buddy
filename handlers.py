# handlers.py
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
import re # Keep for potential simple logic
# Timezone libraries
import pytz
from pytz.exceptions import UnknownTimeZoneError

import config
import google_services as gs # For Calendar and Auth services
import llm_service          # Import LLM Service
from agent import initialize_agent

logger = logging.getLogger(__name__)

# Define history constants
MAX_HISTORY_TURNS = 10 # Remember last 10 back-and-forth turns
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2
ASKING_TIMEZONE = range(1)
# === Helper Function ===

# === Helper Function ===

def _format_event_time(event: dict, user_tz: pytz.BaseTzInfo) -> str:
    """Formats event start/end time nicely for display in user's timezone."""
    start_data = event.get('start', {}) # Use .get() for safety
    end_data = event.get('end', {})   # Use .get() for safety

    start_str = start_data.get('dateTime', start_data.get('date'))
    end_str = end_data.get('dateTime', end_data.get('date'))

    # ===> ADD Check for None/Empty strings <===
    if not start_str:
        logger.warning(f"Event missing start date/time info. Event ID: {event.get('id')}")
        return "[Unknown Start Time]"
    # ===> END Check <===

    try:
        if 'date' in start_data: # All day event
            # Check end date for multi-day all-day events
            end_dt_str = end_data.get('date')
            start_dt = dateutil_parser.isoparse(start_str).date()
            if end_dt_str:
                 # Google API end date for all-day is exclusive, subtract a day for display
                end_dt = dateutil_parser.isoparse(end_dt_str).date() - timedelta(days=1)
                if end_dt > start_dt: # Multi-day all-day event
                    return f"{start_dt.strftime('%a, %b %d')} - {end_dt.strftime('%a, %b %d')} (All day)"
            # Single all-day event
            return f"{start_dt.strftime('%a, %b %d')} (All day)"
        else: # Timed event
             # Check end_str existence before parsing
             if not end_str:
                 logger.warning(f"Timed event missing end time. Event ID: {event.get('id')}")
                 end_str = start_str # Fallback to start time if end is missing (shouldn't happen)

             start_dt_aware = dateutil_parser.isoparse(start_str).astimezone(user_tz)
             end_dt_aware = dateutil_parser.isoparse(end_str).astimezone(user_tz)

             start_fmt = start_dt_aware.strftime('%a, %b %d, %Y at %I:%M %p %Z') # %Z shows tz abbr
             end_fmt = end_dt_aware.strftime('%I:%M %p %Z')
             if start_dt_aware.date() != end_dt_aware.date():
                 end_fmt = end_dt_aware.strftime('%b %d, %Y %I:%M %p %Z')
             return f"{start_fmt} - {end_fmt}"
    except Exception as e:
        logger.error(f"Error parsing/formatting event time: {e}. Event ID: {event.get('id')}, Start: '{start_str}', End: '{end_str}'", exc_info=True) # Log full traceback
        # Fallback to showing raw start time string if formatting fails
        return f"{start_str} [Error Formatting]"
async def _get_user_tz_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> pytz.BaseTzInfo | None:
    """Gets user timezone object or prompts them to set it, returning None if prompt sent."""
    user_id = update.effective_user.id
    tz_str = gs.get_user_timezone_str(user_id)
    if tz_str:
        try:
            return pytz.timezone(tz_str)
        except UnknownTimeZoneError:
            logger.warning(f"Invalid timezone '{tz_str}' found in DB for user {user_id}. Prompting.")
            # Optionally delete invalid tz from DB here
    # If no valid timezone found
    await update.message.reply_text("Please set your timezone first using the /set_timezone command so I can understand times correctly.")
    return None

# === Core Action Handlers (Internal) ===

async def _handle_general_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles general chat messages, managing conversation history."""
    user_id = update.effective_user.id
    logger.info(f"Handling GENERAL_CHAT for user {user_id} with history")

    # 1. Retrieve or initialize history from user_data
    # user_data is a dict unique to each user in each chat
    if 'llm_history' not in context.user_data:
        context.user_data['llm_history'] = []
    history: list[dict] = context.user_data['llm_history']

    # 2. Add current user message to history (using the simple structure for storage)
    history.append({'role': 'user', 'content': text})

    # 3. Call LLM service with history
    response_text = await llm_service.get_chat_response(history) # Pass the history

    # 4. Process response and update history
    if response_text:
        await update.message.reply_text(response_text)
        # Add bot's response to history
        history.append({'role': 'model', 'content': response_text})
    else:
        # Handle LLM failure or blocked response
        await update.message.reply_text("Sorry, I couldn't process that chat message right now.")
        # Remove the last user message from history if the bot failed to respond
        if history and history[-1]['role'] == 'user':
            history.pop()

    # 5. Trim history to MAX_HISTORY_MESSAGES (e.g., 20 messages for 10 turns)
    if len(history) > MAX_HISTORY_MESSAGES:
        logger.debug(f"Trimming history for user {user_id} from {len(history)} to {MAX_HISTORY_MESSAGES}")
        # Keep the most recent messages
        context.user_data['llm_history'] = history[-MAX_HISTORY_MESSAGES:]
        # Alternative: history = history[-MAX_HISTORY_MESSAGES:] # Reassign if not using user_data directly

async def _handle_calendar_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, parameters: dict):
    """Handles CALENDAR_SUMMARY intent using user's timezone."""
    user_id = update.effective_user.id
    logger.info(f"Handling CALENDAR_SUMMARY for user {user_id}")

    user_tz = await _get_user_tz_or_prompt(update, context)
    if not user_tz: return # Stop if user needs to set timezone

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

        except ValueError as e: logger.error(...); start_date = None

    if start_date is None or end_date is None:
        logger.warning(f"Date range parsing failed/fallback for '{time_period_str}'. Using local today.")
        await update.message.reply_text(f"Had trouble with '{time_period_str}', showing today ({now_local.strftime('%Y-%m-%d')}) instead.")
        start_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        display_period_str = f"today ({now_local.strftime('%Y-%m-%d')})"

    if end_date <= start_date: end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999); # Ensure valid range

    # 2. Fetch events (using the calculated datetimes, which are now timezone-aware)
    events = await gs.get_calendar_events(user_id, time_min=start_date, time_max=end_date)

    # 3. Format and send response
    if events is None: await update.message.reply_text("Sorry, couldn't fetch events."); return
    if not events: await update.message.reply_text(f"No events found for '{display_period_str}'."); return

    summary_lines = [f"🗓️ Events for {display_period_str} (Times in {user_tz.zone}):"]
    for event in events:
        time_str = _format_event_time(event, user_tz) # Pass user_tz for formatting
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
        start_str = event_details.get('start_time') # ISO string from LLM (should have offset)
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
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': user_tz.zone}, # Add IANA timeZone
            'end': {'dateTime': final_end_dt.isoformat(), 'timeZone': user_tz.zone}, # Add IANA timeZone
        }

        # Format confirmation message using the parsed (and potentially timezone-converted) times
        start_confirm = start_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z') # Display in local TZ
        end_confirm = final_end_dt.astimezone(user_tz).strftime('%a, %b %d, %Y at %I:%M %p %Z')
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
        try: search_start = dateutil_parser.isoparse(parsed_range['start_iso']); search_end = dateutil_parser.isoparse(parsed_range['end_iso']); search_start-=timedelta(minutes=1); search_end+=timedelta(minutes=1)
        except ValueError: search_start = None
    if not search_start: now = datetime.now(timezone.utc); search_start = now.replace(hour=0, minute=0, second=0, microsecond=0); search_end = now + timedelta(days=3)
    logger.info(f"Delete search window: {search_start.isoformat()} to {search_end.isoformat()}")

    # 2. Fetch potential events (gs)
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
        time_confirm = _format_event_time(event_to_delete, user_tz)

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
    """Handles non-command messages by invoking the LangChain agent."""
    if not update.message or not update.message.text:
        logger.warning("handle_message received update without message text.")
        return
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"Agent Handler: Received message from user {user_id}: '{text[:50]}...'")

    # 1. Check connection status
    if not gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect your Google Calendar first using /connect_calendar.")
        return

    # 2. Get user timezone (prompt if needed)
    user_timezone_str = gs.get_user_timezone_str(user_id)
    if not user_timezone_str:
        # Instead of blocking, maybe default and inform? Or stick to blocking.
        # Let's default to UTC for agent calls if not set, but inform user.
        user_timezone_str = 'UTC'
        await update.message.reply_text("Note: Your timezone isn't set. Using UTC. Use /set_timezone for accurate local times.")
        # Alternative: Block until set
        # await update.message.reply_text("Please set timezone first (/set_timezone).")
        # return

    # 3. Retrieve/Initialize conversation history from context.user_data
    if 'lc_history' not in context.user_data:
        context.user_data['lc_history'] = []
    chat_history: list[dict] = context.user_data['lc_history'] # Stores {'role': '...', 'content': '...'}

    # Add current user message to simple history list
    chat_history.append({'role': 'user', 'content': text})

    # 4. Initialize Agent Executor (with user context and history)
    try:
        # Pass the simple history list; the initialize function converts it for LangChain memory
        agent_executor = initialize_agent(user_id, user_timezone_str, chat_history)
    except Exception as e:
        logger.error(f"Failed to initialize agent for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, there was an error setting up the AI agent.")
        chat_history.pop() # Remove user message if agent failed to init
        return

    # 5. Invoke Agent Executor
    await update.message.chat.send_action(action="typing") # Indicate thinking
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
        chat_history.pop() # Remove user message if agent failed

    # 6. Send response and update history
    await update.message.reply_text(agent_response)
    if agent_response and "error" not in agent_response.lower(): # Avoid saving error messages as model response
        chat_history.append({'role': 'model', 'content': agent_response})

    # 7. Trim history
    if len(chat_history) > config.MAX_HISTORY_MESSAGES:
        context.user_data['lc_history'] = chat_history[-config.MAX_HISTORY_MESSAGES:]


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


# --- NEW /set_timezone Conversation Handler ---
async def set_timezone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the /set_timezone conversation."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started /set_timezone.")
    current_tz = gs.get_user_timezone_str(user_id)
    prompt = "Please tell me your timezone in IANA format (e.g., 'America/New_York', 'Europe/London', 'Asia/Tokyo').\n"
    prompt += "You can find a list here: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones\n\n"
    if current_tz:
        prompt += f"Your current timezone is set to: `{current_tz}`"
    else:
        prompt += "Your timezone is not set yet."

    await update.message.reply_text(prompt, parse_mode=ParseMode.MARKDOWN)
    return ASKING_TIMEZONE # Transition to the next state

async def received_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives potential timezone string, validates, saves, and ends."""
    user_id = update.effective_user.id
    timezone_str = update.message.text.strip()
    logger.info(f"User {user_id} provided timezone: {timezone_str}")

    try:
        # Validate using pytz
        pytz.timezone(timezone_str)
        # Save using google_services function
        success = gs.set_user_timezone(user_id, timezone_str)
        if success:
            await update.message.reply_text(f"✅ Timezone set to `{timezone_str}` successfully!", parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Successfully set timezone for user {user_id}")
            return ConversationHandler.END # End conversation
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
        return ASKING_TIMEZONE # Stay in the same state to allow retry
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