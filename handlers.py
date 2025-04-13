# handlers.py
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import re

import config
import google_services as gs

logger = logging.getLogger(__name__)

# --- Helper Function for Summary ---
async def _get_and_send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, time_period_str: str):
    """Parses date range, fetches events, and sends summary message."""
    logger.info(f"Helper: Getting summary for user {user_id}, period '{time_period_str}'")

    # Use AI to parse the date range
    parsed_range = await gs.parse_date_range_llm(time_period_str)

    start_date = None
    end_date = None
    display_period_str = time_period_str # Use original string unless fallback

    if parsed_range:
        try:
            start_date = dateutil_parser.isoparse(parsed_range['start_iso'])
            end_date = dateutil_parser.isoparse(parsed_range['end_iso'])
            if start_date.tzinfo is None: start_date = start_date.replace(tzinfo=timezone.utc)
            if end_date.tzinfo is None: end_date = end_date.replace(tzinfo=timezone.utc)
            logger.info(f"Helper: AI parsed '{time_period_str}' as: {start_date.isoformat()} to {end_date.isoformat()}")
        except Exception as e:
            logger.error(f"Helper: Failed parsing AI dates for '{time_period_str}': {e}. Range: {parsed_range}")
            start_date = None # Fallback
    else:
        logger.warning(f"Helper: AI date range parsing failed for '{time_period_str}'. Falling back.")
        start_date = None # Fallback

    # Fallback to 'today' if AI parsing failed
    if start_date is None or end_date is None:
        logger.info("Helper: Falling back to 'today' for date range.")
        await update.message.reply_text(f"Sorry, I couldn't quite figure out '{time_period_str}'. Fetching for today instead.")
        now = datetime.now(timezone.utc)
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        display_period_str = "today"

    # Ensure end date is valid
    if end_date <= start_date:
        end_date = start_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        if end_date <= start_date: end_date = start_date + timedelta(seconds=1)

    await update.message.reply_text(f"Okay, fetching events for {display_period_str} ({start_date.strftime('%b %d')} - {end_date.strftime('%b %d %Y')})...")

    events = await gs.get_calendar_events(user_id, time_min=start_date, time_max=end_date)

    if events is None:
        if not gs.is_user_connected(user_id):
             await update.message.reply_text("Authentication failed fetching events. Please /connect_calendar again.")
        else:
            await update.message.reply_text("Could not fetch calendar events. There might be a temporary issue, or stored credentials might be invalid. Try /disconnect_calendar and /connect_calendar.")
        return

    if not events:
        await update.message.reply_text(f"No upcoming events found for '{display_period_str}'.")
        return

    # Format the events
    summary_lines = [f"🗓️ Events for {display_period_str}:"]
    for event in events:
        start_str = event['start'].get('dateTime', event['start'].get('date'))
        end_str = event['end'].get('dateTime', event['end'].get('date'))
        try:
            if 'date' in event['start']: # All day event
                start_dt = dateutil_parser.isoparse(start_str).date()
                time_str = f"{start_dt.strftime('%a, %b %d')} (All day)"
            else: # Timed event
                 start_dt = dateutil_parser.isoparse(start_str)
                 end_dt = dateutil_parser.isoparse(end_str)
                 start_fmt = start_dt.strftime('%a, %b %d %I:%M %p %Z')
                 end_fmt = end_dt.strftime('%I:%M %p %Z')
                 if start_dt.date() != end_dt.date(): end_fmt = end_dt.strftime('%b %d %I:%M %p %Z')
                 time_str = f"{start_fmt} - {end_fmt}"
        except Exception as e:
            logger.error(f"Error parsing event time for '{event.get('summary')}': {e}. Start: {start_str}, End: {end_str}")
            time_str = start_str
        summary_lines.append(f"- *{event.get('summary', 'No Title')}* ({time_str})")

    await update.message.reply_text("\n".join(summary_lines), parse_mode=ParseMode.MARKDOWN)


# --- Command Handlers ---

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
        "- 'Add dentist appointment July 1st 9:30am'\n\n"
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
    - `Add reminder to buy milk tonight`

    Or use these commands:
    /start - Welcome message.
    /connect_calendar - Authorize access to your Google Calendar.
    /my_status - Check if your calendar is connected.
    /disconnect_calendar - Revoke access to your calendar.
    /summary `[time period]` - Explicitly request a summary (e.g., `/summary tomorrow`).
    /help - Show this help message.
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def connect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (connect_calendar function remains the same) ...
    user_id = update.effective_user.id
    logger.info(f"User {user_id} initiated calendar connection.")
    if gs.is_user_connected(user_id):
         service = gs.build_google_calendar_service(user_id)
         if service:
             await update.message.reply_text("It looks like your calendar is already connected and working!")
             logger.info(f"User {user_id} tried to connect but already connected.")
             return
         else:
            await update.message.reply_text("There seems to be an issue with your stored connection. Please reconnect.")
            gs.delete_user_token(user_id)

    flow = gs.get_google_auth_flow()
    if not flow:
        await update.message.reply_text("Sorry, there was an error setting up the connection. Please try again later.")
        return

    state = gs.generate_oauth_state(user_id)
    if not state:
         await update.message.reply_text("Sorry, couldn't generate a secure state for connection. Please try again.")
         return

    auth_url, _ = flow.authorization_url(access_type='offline', prompt='consent', state=state)
    logger.info(f"Generated auth URL for user {user_id}: {auth_url}")
    keyboard = [[InlineKeyboardButton("Connect Google Calendar", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Click the button below to connect your Google Calendar. "
        "You'll be asked to grant permission in your browser.",
        reply_markup=reply_markup
    )

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (my_status function remains the same) ...
    user_id = update.effective_user.id
    if gs.is_user_connected(user_id): # Use DB check
        service = gs.build_google_calendar_service(user_id)
        if service:
             await update.message.reply_text("✅ Your Google Calendar is connected and credentials seem valid.")
             logger.info(f"Status check for user {user_id}: Connected and valid.")
        else:
            await update.message.reply_text("⚠️ Your Google Calendar was connected, but the credentials seem invalid. Please /disconnect_calendar and /connect_calendar again.")
            logger.info(f"Status check for user {user_id}: Connected but invalid.")
    else:
        await update.message.reply_text("❌ Your Google Calendar is not connected. Use /connect_calendar to link it.")
        logger.info(f"Status check for user {user_id}: Not connected.")

async def disconnect_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (disconnect_calendar function remains the same) ...
    user_id = update.effective_user.id
    deleted = gs.delete_user_token(user_id)
    if user_id in config.pending_events: del config.pending_events[user_id]
    if deleted: await update.message.reply_text("Your Google Calendar connection has been removed.")
    else: await update.message.reply_text("Your Google Calendar wasn't connected.")

async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the explicit /summary command by calling the helper."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} used /summary command. Args: {context.args}")

    if not gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect your Google Calendar first using /connect_calendar.")
        return

    time_period_str = " ".join(context.args) if context.args else "today"
    # Call the refactored helper function
    await _get_and_send_summary(update, context, user_id, time_period_str)


# --- Main Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles non-command messages using AI intent classification."""
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"Handler: Received message from user {user_id}: '{text[:50]}...'")

    # 1. Classify Intent
    intent_data = await gs.classify_intent_and_extract_params(text)
    intent = "GENERAL_CHAT" # Default intent
    parameters = {}

    if intent_data:
        intent = intent_data.get("intent", "GENERAL_CHAT")
        parameters = intent_data.get("parameters", {})
    else:
        logger.warning(f"Handler: Intent classification failed for user {user_id}. Defaulting to GENERAL_CHAT.")

    # 2. Check Connection for Calendar Actions
    if intent in ["CALENDAR_SUMMARY", "CALENDAR_CREATE", "CALENDAR_DELETE"]:
        if not gs.is_user_connected(user_id):
            action_word = "view your calendar"
            if intent == "CALENDAR_CREATE": action_word = "add events"
            if intent == "CALENDAR_DELETE": action_word = "delete events"
            await update.message.reply_text(f"To {action_word}, please connect your Google Calendar first using /connect_calendar.")
            return # Stop processing if not connected for calendar actions

    # 3. Act based on Intent
    # --- CALENDAR_SUMMARY Intent ---
    if intent == "CALENDAR_SUMMARY":
        logger.info(f"Handler: Intent CALENDAR_SUMMARY detected for user {user_id}")
        time_period_str = parameters.get("time_period", "today")
        await _get_and_send_summary(update, context, user_id, time_period_str)

    # --- CALENDAR_CREATE Intent ---
    elif intent == "CALENDAR_CREATE":
        logger.info(f"Handler: Intent CALENDAR_CREATE detected for user {user_id}")
        event_description = parameters.get("event_description")
        if not event_description:
            # This case should ideally be caught by validation in classify_intent_and_extract_params
            logger.error(f"Handler: CALENDAR_CREATE intent but no event_description parameter found.")
            await update.message.reply_text("I understood you want to create an event, but couldn't get the details. Please try again.")
            return

        await update.message.reply_text("Okay, let me process that event...")
        event_details = await gs.extract_event_details_llm(event_description)

        if event_details and event_details.get('summary') and event_details.get('start_time'):
            # --- Event Creation Confirmation Flow (same as before) ---
            try:
                # ... (Code for formatting confirmation and setting pending_events) ...
                 # Use dateutil_parser for robustness
                start_dt_str = event_details.get('start_time')
                start_dt = dateutil_parser.isoparse(start_dt_str) if start_dt_str else None
                if not start_dt: raise ValueError("Start time could not be parsed")
                if start_dt.tzinfo is None: start_dt = start_dt.replace(tzinfo=timezone.utc)

                end_dt_str = event_details.get('end_time')
                end_dt = dateutil_parser.isoparse(end_dt_str) if end_dt_str else None
                if end_dt and end_dt.tzinfo is None: end_dt = end_dt.replace(tzinfo=timezone.utc)
                final_end_dt = end_dt if end_dt else start_dt + timedelta(hours=1)
                if final_end_dt <= start_dt: final_end_dt = start_dt + timedelta(hours=1)

                start_confirm = start_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')
                end_confirm = final_end_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')

                confirm_text = f"Okay, create this event?\n\n" \
                               f"<b>Summary:</b> {event_details.get('summary', 'N/A')}\n" \
                               f"<b>Start:</b> {start_confirm}\n" \
                               f"<b>End:</b> {end_confirm}\n" \
                               f"<b>Description:</b> {event_details.get('description', 'N/A')}\n" \
                               f"<b>Location:</b> {event_details.get('location', 'N/A')}"

                google_event_data = {
                    'summary': event_details.get('summary'),
                    'location': event_details.get('location'),
                    'description': event_details.get('description'),
                    'start': {'dateTime': start_dt.isoformat()},
                    'end': {'dateTime': final_end_dt.isoformat()},
                }
                config.pending_events[user_id] = google_event_data
                keyboard = [[
                        InlineKeyboardButton("✅ Confirm", callback_data="confirm_event_create"),
                        InlineKeyboardButton("❌ Cancel", callback_data="cancel_event_create"),
                    ]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_html(confirm_text, reply_markup=reply_markup)
            except Exception as e:
                logger.error(f"Error formatting/processing extracted event details for create: {e}", exc_info=True)
                await update.message.reply_text("Sorry, I understood the event but had trouble processing the details (e.g., date/time). Please try phrasing it differently.")
        # ... (Handle failures from extract_event_details_llm as before) ...
        elif event_details is None and gs.gemini_model is not None:
             await update.message.reply_text("Sorry, I couldn't understand the event details from your message. Could you try phrasing it differently?")
        elif gs.gemini_model is None:
             await update.message.reply_text("Event creation requires the LLM, which is not configured.")
        else:
             await update.message.reply_text("I had trouble understanding the specifics of that event (e.g., missing title or start time). Can you try again?")


    # --- CALENDAR_DELETE Intent ---
    elif intent == "CALENDAR_DELETE":
        logger.info(f"Handler: Intent CALENDAR_DELETE detected for user {user_id}")
        event_description = parameters.get("event_description")
        if not event_description:
            logger.error(f"Handler: CALENDAR_DELETE intent but no event_description parameter found.")
            await update.message.reply_text("I understood you want to delete an event, but couldn't get the details. Please try again.")
            return

        await update.message.reply_text(f"Okay, searching your calendar based on '{event_description[:50]}...'")

        # 1. Try to parse a date range from the description using AI (for search window)
        parsed_range = await gs.parse_date_range_llm(event_description)
        search_start = None
        search_end = None
        # ... (logic for setting search_start/search_end based on parsed_range or default remains the same) ...
        if parsed_range:
            try:
                search_start = dateutil_parser.isoparse(parsed_range['start_iso'])
                search_end = dateutil_parser.isoparse(parsed_range['end_iso'])
                search_start = search_start - timedelta(minutes=1) # Widen slightly
                search_end = search_end + timedelta(minutes=1)
            except ValueError: search_start = None
        if not search_start:
            now = datetime.now(timezone.utc)
            search_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            search_end = now + timedelta(days=3) # Search today and next 2 days for delete targets
            logger.info(f"Searching for event to delete within default range: {search_start.isoformat()} to {search_end.isoformat()}")
        else:
             logger.info(f"Searching for event to delete within AI parsed range: {search_start.isoformat()} to {search_end.isoformat()}")

        # 2. Fetch events in the potential time window
        potential_events = await gs.get_calendar_events(user_id, time_min=search_start, time_max=search_end, max_results=25)

        if potential_events is None:
            await update.message.reply_text("Sorry, I couldn't search your calendar right now.")
            return
        if not potential_events:
             await update.message.reply_text(f"I didn't find any events in the period around '{event_description[:50]}...'.")
             return

        # ----------------------------------------------------------
        # 3. Use LLM to find the best match (Replaces keyword filter)
        # ----------------------------------------------------------
        logger.info(f"Asking LLM to match '{event_description}' against {len(potential_events)} candidates.")
        await update.message.reply_text("Analyzing potential matches...") # Let user know AI is thinking

        match_result = await gs.find_event_match_llm(event_description, potential_events)

        if match_result is None:
            # LLM call failed
            await update.message.reply_text("Sorry, I had trouble analyzing the potential events. Please try again.")
            return

        match_type = match_result.get('match_type')

        # 4. Handle LLM Match Result
        if match_type == 'NONE':
            await update.message.reply_text(f"Sorry, I looked at the events around that time but couldn't confidently match one to '{event_description[:50]}...'. Could you be more specific?")

        elif match_type == 'SINGLE':
            event_index = match_result.get('event_index')
            # Validate index again just in case (should be caught in service layer too)
            if not (isinstance(event_index, int) and 0 <= event_index < len(potential_events)):
                 logger.error(f"Handler received invalid event_index {event_index} from LLM matching.")
                 await update.message.reply_text("Sorry, there was an internal error identifying the matched event. Please try again.")
                 return

            # Found unique match - proceed to confirmation
            event_to_delete = potential_events[event_index]
            event_id = event_to_delete.get('id')
            event_summary = event_to_delete.get('summary', 'No Title')

            start_str = event_to_delete['start'].get('dateTime', event_to_delete['start'].get('date'))
            try:
                if 'date' in event_to_delete['start']:
                    start_dt = dateutil_parser.isoparse(start_str).date()
                    time_confirm = f"{start_dt.strftime('%a, %b %d')} (All day)"
                else:
                    start_dt = dateutil_parser.isoparse(start_str)
                    time_confirm = start_dt.strftime('%a, %b %d, %Y at %I:%M %p %Z')
            except Exception: time_confirm = start_str # Fallback

            confirm_text = f"Okay, I think you mean this event. Please confirm deletion:\n\n" \
                           f"<b>Summary:</b> {event_summary}\n" \
                           f"<b>Time:</b> {time_confirm}"

            config.pending_deletions[user_id] = {'event_id': event_id, 'summary': event_summary}

            keyboard = [[
                    InlineKeyboardButton("✅ Yes, Delete This", callback_data="confirm_event_delete"),
                    InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete"),
                ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_html(confirm_text, reply_markup=reply_markup)

        elif match_type == 'MULTIPLE':
            # LLM found multiple plausible matches
            # TODO: Implement better clarification flow if needed
            await update.message.reply_text("I found multiple events that might match your description. Could you please be more specific about which one you want to delete (e.g., include the exact time or more details from the title)?")

    # --- GENERAL_CHAT Intent ---
    else: # Handles GENERAL_CHAT or fallback from failed classification/validation
        logger.info(f"Handler: Intent GENERAL_CHAT detected for user {user_id}")
        response = await gs.get_llm_chat_response(text)
        await update.message.reply_text(response)


# --- Callback Query Handler ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    callback_data = query.data
    logger.info(f"Callback: Received query from user {user_id}: {callback_data}")

    # --- Event Creation Callbacks ---
    if callback_data == "confirm_event_create":
        if user_id not in config.pending_events:
            await query.edit_message_text(text="Sorry, I don't remember the event details to create. Please try again.")
            return
        event_details = config.pending_events.pop(user_id)
        await query.edit_message_text(text=f"Okay, adding '{event_details.get('summary')}' to your calendar...")
        success, message = await gs.create_calendar_event(user_id, event_details)
        await query.edit_message_text(text=message)
        if not success and "Authentication failed" in message and not gs.is_user_connected(user_id):
             logger.info(f"Token for user {user_id} was cleared during failed event creation.")

    elif callback_data == "cancel_event_create":
        if user_id in config.pending_events: del config.pending_events[user_id]
        await query.edit_message_text(text="Event creation cancelled.")

    # --- Event Deletion Callbacks ---
    elif callback_data == "confirm_event_delete":
        if user_id not in config.pending_deletions:
            await query.edit_message_text(text="Sorry, I don't remember which event to delete. Please try asking again.")
            return

        pending_info = config.pending_deletions.pop(user_id) # Get and remove pending deletion
        event_id = pending_info.get('event_id')
        event_summary = pending_info.get('summary', 'the event')

        if not event_id:
             logger.error(f"Callback: Missing event_id in pending_deletions for user {user_id}")
             await query.edit_message_text(text="Sorry, something went wrong trying to find the event ID to delete.")
             return

        await query.edit_message_text(text=f"Okay, deleting '{event_summary}'...")
        success, message = await gs.delete_calendar_event(user_id, event_id)
        await query.edit_message_text(text=message) # Show success or failure message
        # Check if token was cleared due to auth error during delete attempt
        if not success and "Authentication failed" in message and not gs.is_user_connected(user_id):
             logger.info(f"Token for user {user_id} was cleared during failed event deletion.")

    elif callback_data == "cancel_event_delete":
        if user_id in config.pending_deletions:
            del config.pending_deletions[user_id] # Clear pending deletion
        await query.edit_message_text(text="Event deletion cancelled.")

    else:
        logger.warning(f"Callback: Unhandled callback data received: {callback_data}")
        await query.edit_message_text(text="Sorry, I didn't understand that action.")


# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (error_handler function remains the same) ...
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
         try:
            await update.effective_message.reply_text("Sorry, something went wrong processing your request. Please try again later.")
         except Exception as e:
             logger.error(f"Failed to send error message to user: {e}")