# handlers.py
import html
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
# Timezone libraries
import pytz
from pytz.exceptions import UnknownTimeZoneError

import config
import google_services as gs  # For Calendar and Auth services
from handler.message_formatter import create_final_message
from llm import llm_service
from llm.agent import initialize_agent
from time_util import format_to_nice_date
from utils import _format_event_time

logger = logging.getLogger(__name__)

# Define history constants
MAX_HISTORY_TURNS = 10  # Remember last 10 back-and-forth turns
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2
ASKING_TIMEZONE = range(1)


# === Helper Function ===

# === Helper Function ===
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
    await update.message.reply_text(
        "Please set your timezone first using the /set_timezone command so I can understand times correctly.")
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
    response_text = await llm_service.get_chat_response(history)  # Pass the history

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

        config.pending_events[user_id] = google_event_data
        keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data="confirm_event_create"),
                     InlineKeyboardButton("❌ Cancel", callback_data="cancel_event_create")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        logger.log(logging.DEBUG, f"Pending event data for user {user_id}: {google_event_data} and confirmation text: {confirm_text}")
        await update.message.reply_html(confirm_text, reply_markup=reply_markup)

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
        config.pending_deletions[user_id] = {'event_id': event_id, 'summary': event_summary}
        keyboard = [[InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                     InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_html(confirm_text, reply_markup=reply_markup)

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
    /help - Show this help message.
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def connect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Starts the Google Calendar OAuth flow."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated calendar connection.")
    if gs.is_user_connected(user_id):
        service = gs._build_calendar_service_client(user_id)
        if service:
            await update.message.reply_text("Calendar already connected!"); return
        else:
            await update.message.reply_text("Issue with stored connection. Reconnecting..."); gs.delete_user_token(
                user_id)

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
    if not gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect your Google Calendar first using /connect_calendar.")
        return

    # 2. Get user timezone (prompt if needed)
    user_timezone_str = gs.get_user_timezone_str(user_id)
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
    if 'lc_history' not in context.user_data:
        context.user_data['lc_history'] = []
    chat_history: list[dict] = context.user_data['lc_history']  # Stores {'role': '...', 'content': '...'}

    # Add current user message to simple history list
    chat_history.append({'role': 'user', 'content': text})

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
    # Check if a pending action was stored by a tool during the agent run
    if user_id in config.pending_events:
        logger.info(f"Pending event create found for user {user_id}. Formatting confirmation from pending data.")
        pending_event_data = config.pending_events[user_id]
        try:
            user_tz = pytz.timezone(user_timezone_str if user_timezone_str else 'UTC') # Get user TZ

            final_message_to_send = await create_final_message(pending_event_data)

            keyboard = [[InlineKeyboardButton("✅ Confirm Create", callback_data="confirm_event_create"),
                         InlineKeyboardButton("❌ Cancel Create", callback_data="cancel_event_create")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Error formatting create confirmation in handler: {e}", exc_info=True)
            final_message_to_send = "Error preparing event confirmation. Please try again. {e}"
    elif user_id in config.pending_deletions:
        logger.info(f"Pending event delete found for user {user_id}. Formatting confirmation from pending data.")
        pending_deletion_data = config.pending_deletions[user_id]
        event_id_to_delete = pending_deletion_data.get('event_id')
        # Fetch full event details again to ensure the summary and time are current and correctly formatted
        # This adds an API call but ensures accuracy for the confirmation.
        # Alternatively, trust the summary stored during the tool run, but it might be less detailed.
        event_details_for_confirm = await gs.get_calendar_event_by_id(user_id, event_id_to_delete)

        if event_details_for_confirm:
            try:
                user_tz = pytz.timezone(user_timezone_str if user_timezone_str else 'UTC')
                summary = event_details_for_confirm.get('summary', 'this event')
                time_confirm = _format_event_time(event_details_for_confirm, user_tz) # Use your existing util

                final_message_to_send = (
                    f"Found event: '<b>{summary}</b>' ({time_confirm}).\n\n"
                    f"Should I delete this event?"
                )
            except Exception as e:
                logger.error(f"Error formatting delete confirmation in handler: {e}", exc_info=True)
                # Fallback to summary stored by the tool if fresh fetch/format fails
                summary = pending_deletion_data.get('summary', 'the selected event')
                final_message_to_send = f"Are you sure you want to delete '{summary}'?"
        else:
            # Event might have been deleted by something else in the meantime
            final_message_to_send = f"Could not re-fetch details for event ID '{event_id_to_delete}' for deletion confirmation. It might no longer exist. Proceed with deleting by ID?"
            # Or, simply state:
            # final_message_to_send = f"Are you sure you want to delete the previously selected event (ID: {event_id_to_delete})?"

        keyboard = [[InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                     InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    # Send the agent's final text response, potentially with buttons
    # Send the final message (either agent's direct output or handler-formatted confirmation)
    await update.message.reply_text(
        final_message_to_send, # Use the potentially overridden message
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    if agent_response and "error" not in agent_response.lower():  # Avoid saving error messages as model response
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
        final_msg = msg + (f"\nView: {link}" if link else "");
        await query.edit_message_text(final_msg, parse_mode=ParseMode.HTML)
        if not success and "Authentication failed" in msg and not gs.is_user_connected(user_id): logger.info(
            f"Token cleared for {user_id} during failed create.")

    elif callback_data == "cancel_event_create":
        if user_id in config.pending_events: del config.pending_events[user_id]
        await query.edit_message_text("Event creation cancelled.")

    # --- Event Deletion ---
    elif callback_data == "confirm_event_delete":
        if user_id not in config.pending_deletions: await query.edit_message_text("Confirmation expired."); return
        pending = config.pending_deletions.pop(user_id)
        event_id, summary = pending.get('event_id'), pending.get('summary', 'event')
        if not event_id: logger.error(f"Missing event_id for {user_id}"); await query.edit_message_text(
            "Error: Missing event ID."); return
        await query.edit_message_text(f"Deleting '{summary}'...")
        success, msg = await gs.delete_calendar_event(user_id, event_id)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
        if not success and "Authentication failed" in msg and not gs.is_user_connected(user_id): logger.info(
            f"Token cleared for {user_id} during failed delete.")

    elif callback_data == "cancel_event_delete":
        if user_id in config.pending_deletions: del config.pending_deletions[user_id]
        await query.edit_message_text("Event deletion cancelled.")

    else:
        logger.warning(f"Callback: Unhandled callback data: {callback_data}")
        try:
            await query.edit_message_text("Action not understood or expired.")
        except Exception:
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
    current_tz = gs.get_user_timezone_str(user_id)
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
    timezone_str = update.message.text.strip()
    logger.info(f"User {user_id} provided timezone: {timezone_str}")

    try:
        # Validate using pytz
        pytz.timezone(timezone_str)
        # Save using google_services function
        success = gs.set_user_timezone(user_id, timezone_str)
        if success:
            await update.message.reply_text(f"✅ Timezone set to `{timezone_str}` successfully!",
                                            parse_mode=ParseMode.MARKDOWN)
            logger.info(f"Successfully set timezone for user {user_id}")
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

    if gs.add_to_grocery_list(user_id, items_to_add):
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

    grocery_list = gs.get_grocery_list(user_id)

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

    if gs.delete_grocery_list(user_id):
        logger.info(f"Successfully cleared grocery list for user {user_id}.")
        await update.message.reply_text("🗑️ Your grocery list has been cleared.")
    else:
        logger.error(f"Failed to clear grocery list for user {user_id}.")
        await update.message.reply_text(
            "Sorry, there was a problem clearing your grocery list."
        )
