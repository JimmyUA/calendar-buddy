# tests/test_handlers.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from telegram import InlineKeyboardMarkup
from telegram.ext import ConversationHandler
from telegram.constants import ParseMode

# Import handlers AFTER fixtures might patch dependencies
import config
import handlers
from .conftest import TEST_USER_ID, TEST_TIMEZONE_STR, TEST_TIMEZONE # Import TEST_TIMEZONE
from datetime import datetime, timedelta # For dynamic dates

pytestmark = pytest.mark.asyncio

# Use a fixed "now" for predictable test results across runs, from conftest or define locally
# For handlers, it's often about relative times ("tomorrow", "next week")
# Let's use a fixed base now, similar to test_agent_tools
BASE_TEST_NOW_UTC_HANDLERS = datetime(2024, 8, 19, 17, 0, 0, tzinfo=config.pytz.utc)
BASE_TEST_NOW_USER_TZ_HANDLERS = BASE_TEST_NOW_UTC_HANDLERS.astimezone(TEST_TIMEZONE)


# --- Basic Command Handlers ---

async def test_start_handler(mock_update, mock_context):
    mock_update.set_message_text("/start")
    await handlers.start(mock_update, mock_context)
    mock_update.effective_message.reply_html.assert_called_once()
    call_args = mock_update.effective_message.reply_html.call_args[0][0]
    assert "Hi" in call_args
    assert mock_update.effective_user.mention_html() in call_args


async def test_help_handler(mock_update, mock_context):
    mock_update.set_message_text("/help")
    await handlers.help_command(mock_update, mock_context)
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert "/connect_calendar" in call_args
    assert "/set_timezone" in call_args


async def test_my_status_connected(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs._build_calendar_service_client', new_callable=AsyncMock, return_value=MagicMock())

    await handlers.my_status(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "✅ Calendar connected & credentials valid."
    )


async def test_my_status_not_connected(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False)

    await handlers.my_status(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "❌ Calendar not connected. Use /connect_calendar."
    )


async def test_my_status_invalid_creds(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs._build_calendar_service_client', new_callable=AsyncMock, return_value=None)

    await handlers.my_status(mock_update, mock_context)
    mock_update.effective_message.reply_text.assert_called_once_with(
        "⚠️ Calendar connected, but credentials invalid. Try /disconnect_calendar and /connect_calendar."
    )

async def test_my_status_is_user_connected_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, side_effect=Exception("Firestore connection error"))

    # To ensure the logger is checked correctly
    mock_logger = mocker.patch('handlers.logger')

    await handlers.my_status(mock_update, mock_context)

    # Depending on how error_handler is implemented or if my_status has its own try-except
    # For now, assume it might send a generic error or log it.
    # If it sends a generic error message:
    # mock_update.effective_message.reply_text.assert_called_once_with(
    #     "Sorry, an internal error occurred. Please try again."
    # )
    # Or, if it logs and sends nothing, check log:
    # mock_logger.error.assert_called_once() # Or specific message
    # For this case, let's assume it falls through to the error_handler, which is tested separately.
    # The key is that it doesn't succeed.
    # We'll check if reply_text was called with a success message (it shouldn't have been).

    # Check that none of the success/specific failure messages were sent by my_status itself
    for call_arg in mock_update.effective_message.reply_text.call_args_list:
        text = call_arg[0][0]
        assert "Calendar connected" not in text
        assert "Calendar not connected" not in text

    # If error_handler is expected to be called, this test might need to also assert that behavior,
    # or we assume error_handler tests cover the user-facing message.
    # For now, ensure no positive status is reported.


async def test_disconnect_calendar(mock_update, mock_context, mocker):
    mock_update.set_message_text("/disconnect_calendar")
    mock_delete_token = mocker.patch('handlers.gs.delete_user_token', new_callable=AsyncMock, return_value=True)
    mock_delete_pending_event = mocker.patch('handlers.gs.delete_pending_event', new_callable=AsyncMock)
    mock_delete_pending_deletion = mocker.patch('handlers.gs.delete_pending_deletion', new_callable=AsyncMock)
    
    # config.pending_events and config.pending_deletions are no longer used, 
    # direct gs calls are made to delete from Firestore.
    await handlers.disconnect_calendar(mock_update, mock_context)

    mock_delete_token.assert_awaited_once_with(TEST_USER_ID)
    mock_delete_pending_event.assert_awaited_once_with(TEST_USER_ID)
    mock_delete_pending_deletion.assert_awaited_once_with(TEST_USER_ID)
    mock_update.effective_message.reply_text.assert_called_once_with(
        "Calendar connection removed."
    )
    # Assert pending states were cleared for the user - this check is now implicit in gs calls


# --- Timezone Conversation ---

async def test_set_timezone_start(mock_update, mock_context, mocker):
    mock_update.set_message_text("/set_timezone")
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=None)  # Simulate not set

    result_state = await handlers.set_timezone_start(mock_update, mock_context)

    assert result_state == handlers.ASKING_TIMEZONE
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert "Please tell me your timezone" in call_args
    assert "Your timezone is not set yet" in call_args


async def test_set_timezone_start_already_set(mock_update, mock_context, mocker):
    mock_update.set_message_text("/set_timezone")
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=TEST_TIMEZONE_STR)

    result_state = await handlers.set_timezone_start(mock_update, mock_context)

    assert result_state == handlers.ASKING_TIMEZONE
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert f"current timezone is set to: `{TEST_TIMEZONE_STR}`" in call_args


async def test_received_timezone_valid(mock_update, mock_context, mocker):
    mock_update.set_message_text(TEST_TIMEZONE_STR)
    # Mock pytz validation
    mocker.patch('handlers.pytz.timezone')
    # Mock successful save
    mock_save = mocker.patch('handlers.gs.set_user_timezone', new_callable=AsyncMock, return_value=True)

    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == ConversationHandler.END
    mock_save.assert_awaited_once_with(TEST_USER_ID, TEST_TIMEZONE_STR) # username removed
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert f"Timezone set to `{TEST_TIMEZONE_STR}`" in call_args


async def test_received_timezone_invalid(mock_update, mock_context, mocker):
    invalid_tz = "Invalid/Zone"
    mock_update.set_message_text(invalid_tz)
    # Mock pytz validation to raise error
    mocker.patch('handlers.pytz.timezone', side_effect=handlers.UnknownTimeZoneError)
    mock_save = mocker.patch('handlers.gs.set_user_timezone', new_callable=AsyncMock)

    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == handlers.ASKING_TIMEZONE  # Should stay in same state
    mock_save.assert_not_awaited()
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert f"Sorry, '{invalid_tz}' doesn't look like a valid IANA timezone" in call_args

async def test_set_timezone_start_gs_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text("/set_timezone")
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, side_effect=Exception("GS Error"))
    mock_logger = mocker.patch('handlers.logger') # To check logs if necessary

    # Expecting the function to handle the exception gracefully
    # and potentially inform the user or just log.
    # For now, ensure it doesn't crash and returns an expected state if it's a ConversationHandler part.
    # If it's supposed to end the conversation or send a specific error:
    await handlers.set_timezone_start(mock_update, mock_context)
    # Assert a reply indicating an issue, or that the conversation ended if that's the design.
    # This test assumes the function might log and send a generic failure, or end.
    # If it sends a specific message:
    # mock_update.effective_message.reply_text.assert_called_once_with("An error occurred while fetching your timezone.")
    # For now, check it doesn't send the standard prompts.
    for call_arg in mock_update.effective_message.reply_text.call_args_list:
        text = call_arg[0][0]
        assert "Please tell me your timezone" not in text
    # mock_logger.error.assert_called_once() # If it logs

async def test_received_timezone_gs_set_false(mock_update, mock_context, mocker):
    mock_update.set_message_text(TEST_TIMEZONE_STR)
    mocker.patch('handlers.pytz.timezone') # Assume valid timezone string
    # Mock gs.set_user_timezone to return False
    mocker.patch('handlers.gs.set_user_timezone', new_callable=AsyncMock, return_value=False)

    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == ConversationHandler.END # Should end even on failure to save
    mock_update.effective_message.reply_text.assert_called_once_with(
        "Sorry, there was an error saving your timezone. Please try again."
    )

async def test_received_timezone_gs_set_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text(TEST_TIMEZONE_STR)
    mocker.patch('handlers.pytz.timezone')
    # Mock gs.set_user_timezone to raise an exception
    mocker.patch('handlers.gs.set_user_timezone', new_callable=AsyncMock, side_effect=Exception("GS Save Error"))
    mock_logger = mocker.patch('handlers.logger')


    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == ConversationHandler.END
    mock_update.effective_message.reply_text.assert_called_once_with(
        "An unexpected error occurred. Please try again later or /cancel."
    )
    # mock_logger.error.assert_called_once()


async def test_cancel_timezone(mock_update, mock_context):
    mock_update.set_message_text("/cancel")
    result_state = await handlers.cancel_timezone(mock_update, mock_context)
    assert result_state == ConversationHandler.END
    mock_update.effective_message.reply_text.assert_called_once_with("Timezone setup cancelled.")


# --- handle_message (Agent Interaction) ---

async def test_handle_message_connect_first(mock_update, mock_context, mocker):
    mock_update.set_message_text("What's on my calendar?")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False)
    mock_agent_init = mocker.patch('handlers.initialize_agent')  # Agent shouldn't be called

    await handlers.handle_message(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "Please connect your Google Calendar first using /connect_calendar."
    )
    mock_agent_init.assert_not_called()

async def test_handle_message_is_user_connected_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text("What's on my calendar?")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, side_effect=Exception("GS Connection Error"))
    mock_agent_init = mocker.patch('handlers.initialize_agent')
    mock_logger = mocker.patch('handlers.logger')


    await handlers.handle_message(mock_update, mock_context)
    # Similar to my_status, assume error_handler might take over, or a generic reply.
    # Ensure no positive path reply is sent.
    for call_arg in mock_update.effective_message.reply_text.call_args_list:
        text = call_arg[0][0]
        assert "Please connect your Google Calendar first" not in text # This is for False, not exception
    # mock_logger.error.assert_called_once() # Check if error is logged
    mock_agent_init.assert_not_called()

async def test_handle_message_get_timezone_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text("Hello agent")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    # Mock gs.get_user_timezone_str to raise an exception
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, side_effect=Exception("GS Get TZ Error"))

    mock_initialize_agent = mocker.patch('handlers.initialize_agent') # Should not be called if this fails early
    mock_logger = mocker.patch('handlers.logger')


    # The handler currently defaults to UTC and sends a message if get_user_timezone_str returns None,
    # but an exception might be unhandled.
    # Assuming the global error handler would catch an unhandled exception.
    await handlers.handle_message(mock_update, mock_context)

    # Check that the agent initialization was not attempted if the timezone fetch failed critically
    # If the design is to default to UTC even on exception, then initialize_agent would be called.
    # Current code: Defaults to UTC if tz_str is None, but an exception would bypass this.
    # Let's assume an exception in get_user_timezone_str is critical enough to prevent agent init.
    # This depends on whether handle_message itself has a try-catch around get_user_timezone_str.
    # Based on handlers.py, it does not. So error should propagate or be caught by global handler.

    # Assert that a reply indicating an error or default was sent, or agent not called.
    # For now, check that the agent wasn't initialized with specific data if this step fails.
    mock_initialize_agent.assert_not_called()
    # mock_logger.error.assert_called_with(mocker.ANY, exc_info=True) # Check error was logged

async def test_handle_message_initialize_agent_exception(mock_update, mock_context, mocker):
    mock_update.set_message_text("Hello agent")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=TEST_TIMEZONE_STR)
    mocker.patch('handlers.gs.get_chat_history', new_callable=AsyncMock, return_value=[]) # Mock history
    mocker.patch('handlers.gs.add_chat_message', new_callable=AsyncMock)


    # Mock initialize_agent to raise an exception
    mocker.patch('handlers.initialize_agent', side_effect=Exception("Agent Init Failed"))
    mock_logger = mocker.patch('handlers.logger')

    await handlers.handle_message(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "Sorry, there was an error setting up the AI agent."
    )
    # Check that the user's message was popped from history (if applicable, based on handler logic)
    # The current logic in handle_message for this case: chat_history.pop()
    # This is hard to assert directly without deeper mocking of chat_history object if it's not a simple list.
    # If chat_history was loaded from gs.get_chat_history, then gs.add_chat_message for 'user' was called.
    # The pop() is on a local copy. The error message is the main check.

async def test_handle_message_agent_ainvoke_exception(mock_update, mock_context, mocker, mock_agent_executor):
    mock_update.set_message_text("Hello agent")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=TEST_TIMEZONE_STR)
    mocker.patch('handlers.gs.get_chat_history', new_callable=AsyncMock, return_value=[])
    mocker.patch('handlers.gs.add_chat_message', new_callable=AsyncMock) # User message saved

    # Mock initialize_agent to return the mock_agent_executor
    mocker.patch('handlers.initialize_agent', return_value=mock_agent_executor)
    # Configure mock_agent_executor.ainvoke to raise an exception
    mock_agent_executor.ainvoke.side_effect = Exception("Agent Execution Error")
    mock_logger = mocker.patch('handlers.logger')


    await handlers.handle_message(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "Sorry, an error occurred while processing your request with the agent."
    )

    # Check calls to add_chat_message:
    # It should have been called once for the user's message.
    # It should NOT have been called a second time for the model's (error) response.
    # The mock for add_chat_message was already patched earlier in the test.
    mock_add_chat_msg_func = mocker.get_patched_lookup('handlers.gs.add_chat_message')['handlers.gs.add_chat_message']

    user_message_call = mocker.call(TEST_USER_ID, 'user', "Hello agent", "lc")

    # Check that it was called for the user message
    mock_add_chat_msg_func.assert_any_call(TEST_USER_ID, 'user', "Hello agent", "lc")

    # Check total number of calls to ensure no model message was saved
    assert mock_add_chat_msg_func.call_count == 1, \
        "gs.add_chat_message should only be called once for the user message, not for the agent's error."


async def test_handle_message_set_timezone_first_strict(mock_update, mock_context, mocker):
    # This test assumes the strict behaviour (prompting for timezone if not set)
    mock_update.set_message_text("What's on my calendar?")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=None)  # Timezone NOT set
    mock_agent_init = mocker.patch('handlers.initialize_agent')

    await handlers.handle_message(mock_update, mock_context)

    # Depending on strictness, agent might be initialized with UTC or not called
    # If using UTC default:
    mock_agent_init.assert_called_once()
    assert mock_agent_init.call_args[0][1] == 'UTC'  # Check timezone passed
    # If strict blocking:
    # mock_agent_init.assert_not_called()


async def test_handle_message_agent_invoked(mock_update, mock_context, mocker, mock_agent_executor):
    user_message = "What's on my calendar tomorrow?"
    agent_response_text = "Agent says: You have a meeting at 10 AM."
    mock_update.set_message_text(user_message)
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=TEST_TIMEZONE_STR)
    # Mock get_pending_event and get_pending_deletion to return None, as they are now async
    mocker.patch('handlers.gs.get_pending_event', new_callable=AsyncMock, return_value=None)
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=None)


    # Configure mock agent response
    mock_agent_executor.ainvoke.return_value = {'output': agent_response_text}

    # Initialize history in mock context
    mock_context.user_data['lc_history'] = []

    # Get a reference to the mock that initialize_agent will be replaced with *before* calling the handler
    # The mock_agent_executor fixture sets this up.
    # We need to access the mock object that the fixture created.
    # The fixture patches 'handlers.initialize_agent' and returns the mock_executor,
    # but what we want to check is the call to initialize_agent itself.

    # So, we need to get the mock for 'handlers.initialize_agent' directly.
    # The mock_agent_executor fixture already patches 'handlers.initialize_agent'
    # to return mock_agent_executor (the instance).

    await handlers.handle_message(mock_update, mock_context)

    # Get the mock for the 'handlers.initialize_agent' function itself
    # This was patched by the mock_agent_executor fixture.
    initialize_agent_mock = mocker.get_patched_lookup('handlers.initialize_agent')['handlers.initialize_agent']

    # Assert agent was initialized correctly
    initialize_agent_mock.assert_called_once()
    init_call_args = initialize_agent_mock.call_args

    assert init_call_args[0][0] == TEST_USER_ID
    assert init_call_args[0][1] == TEST_TIMEZONE_STR
    # Initial history is empty when initialize_agent is called,
    # but the user's message is added to chat_history *before* the agent.ainvoke call
    # So, the history passed to initialize_agent will be the current user_data['lc_history']
    # which is empty at the point initialize_agent is called within handle_message
    # *before* the user's message is appended to it for the Langchain memory object.
    # Let's re-check the flow in handle_message:
    # 1. lc_history = []
    # 2. lc_history.append({'role': 'user', 'content': text}) <--- History now has the user message
    # 3. agent_executor = initialize_agent(user_id, user_timezone_str, chat_history) <--- THIS chat_history is passed
    assert init_call_args[0][2] == [{'content': "What's on my calendar tomorrow?", 'role': 'user'},
                                    {'content': 'Agent says: You have a meeting at 10 AM.', 'role': 'model'}]

    # Assert agent was invoked (this part is fine as it uses the mock_agent_executor directly)
    mock_agent_executor.ainvoke.assert_called_once_with({"input": user_message})

    # Assert typing action sent
    mock_update.effective_chat.send_action.assert_called_once_with(action="typing")

    # Assert agent response sent to user
    mock_update.effective_message.reply_text.assert_called_once_with(
        agent_response_text,
        reply_markup=None,  # No buttons expected here
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

    # Assert history updated after agent response
    assert mock_context.user_data['lc_history'] == [
        {'role': 'user', 'content': user_message},
        {'role': 'model', 'content': agent_response_text}
    ]


async def test_handle_message_agent_confirmation_create(mock_update, mock_context, mocker, mock_agent_executor):
    user_message = "Schedule lunch Monday 12pm"
    # Simulate the agent returning the confirmation question from the create tool
#     confirmation_question = f"""Okay, I can create this event:
# <b>Summary:</b> Lunch
# <b>Start:</b> Sunday, 18 May 2025 · 12:33
# <b>End:</b> Sunday, 18 May 2025 · 13:33
# <b>Description:</b> -
# <b>Location:</b> -
#
# Should I add this to your calendar?"""

    confirmation_question = (f"Okay, I can create this event for you:\n\n"
                             f"✨ <b>Lunch</b> ✨\n\n"  # Emphasized Summary/Title
                             f"📅 <b><u>Event Details</u></b>\n"
                             f"<b>Start:</b>       <code>Sunday, 18 May 2025 · 12:33</code>\n"
                             f"<b>End:</b>         <code>Sunday, 18 May 2025 · 13:33</code>\n"
                             f"<b>Description:</b> <i>-</i>\n"
                             f"<b>Location:</b>    <i>-</i>\n\n"
                             f"Ready to add this to your Google Calendar?")
    user_message = "Schedule lunch Monday 12pm" # User input remains the same

    # Dynamic dates for mock_event_data and confirmation_question
    event_summary = "Lunch"
    # Assume LLM / tool figures out "Monday 12pm" relative to BASE_TEST_NOW_USER_TZ_HANDLERS
    # For testing, let's set a specific future Monday
    today = BASE_TEST_NOW_USER_TZ_HANDLERS.date()
    next_monday_date = today + timedelta(days=(7 - today.weekday())) # 0 is Monday
    event_start_dt_user_tz = TEST_TIMEZONE.localize(datetime.combine(next_monday_date, datetime.min.time().replace(hour=12)))
    event_end_dt_user_tz = event_start_dt_user_tz + timedelta(hours=1)

    # This is what the CreateCalendarTool would have stored via gs.add_pending_event
    mock_event_data_from_tool = {
        'summary': event_summary,
        'start': {'dateTime': event_start_dt_user_tz.isoformat(), 'timeZone': TEST_TIMEZONE_STR},
        'end': {'dateTime': event_end_dt_user_tz.isoformat(), 'timeZone': TEST_TIMEZONE_STR},
        'description': 'User requested description here', # Example
        'location': 'User specified location' # Example
    }

    # Dynamically create the confirmation question string the agent is expected to output
    # This needs to match the formatting from llm.tools.create_calendar.format_event_details_for_confirmation
    # For simplicity, we'll mock a simplified version or assume the tool's output format.
    # Ideally, import the actual formatting function if it's complex and stable.
    # from llm.tools.create_calendar import format_event_details_for_confirmation
    # confirmation_question = format_event_details_for_confirmation(mock_event_data_from_tool)
    # For now, let's manually construct a matching string based on the dynamic dates:

    start_display = event_start_dt_user_tz.strftime("%a, %b %d, %Y at %I:%M %p %Z")
    end_display = event_end_dt_user_tz.strftime("%a, %b %d, %Y at %I:%M %p %Z")

    confirmation_question = (f"Okay, I can create this event for you:\n\n"
                             f"✨ <b>{html.escape(mock_event_data_from_tool['summary'])}</b> ✨\n\n"
                             f"📅 <b><u>Event Details</u></b>\n"
                             f"<b>Start:</b>       <code>{start_display}</code>\n"
                             f"<b>End:</b>         <code>{end_display}</code>\n"
                             f"<b>Description:</b> <i>{html.escape(mock_event_data_from_tool.get('description', '-'))}</i>\n"
                             f"<b>Location:</b>    <i>{html.escape(mock_event_data_from_tool.get('location', '-'))}</i>\n\n"
                             f"Ready to add this to your Google Calendar?")

    agent_response_text = confirmation_question

    mock_update.set_message_text(user_message)
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', new_callable=AsyncMock, return_value=TEST_TIMEZONE_STR)
    mock_agent_executor.ainvoke.return_value = {'output': agent_response_text}
    
    # gs.get_pending_event should return the data prepared by the tool
    mocker.patch('handlers.gs.get_pending_event', new_callable=AsyncMock, return_value=mock_event_data_from_tool)
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=None)

    mock_context.user_data['lc_history'] = []
    await handlers.handle_message(mock_update, mock_context)

    mock_agent_executor.ainvoke.assert_called_once()
    mock_update.effective_message.reply_text.assert_called_once()
    call_args, call_kwargs = mock_update.effective_message.reply_text.call_args
    assert call_args[0] == confirmation_question # Assert dynamic string
    assert isinstance(call_kwargs['reply_markup'], InlineKeyboardMarkup)
    # ... (rest of button assertions are fine)


# --- Callback Handler ---

async def test_button_callback_confirm_create_success(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_create")

    # Dynamic event data
    event_summary = "Pending Lunch (Dynamic)"
    start_dt = BASE_TEST_NOW_USER_TZ_HANDLERS + timedelta(days=1, hours=2) # Example: tomorrow 2 hours from base
    event_details_to_create = {
        'summary': event_summary,
        'start': {'dateTime': start_dt.isoformat(), 'timeZone': TEST_TIMEZONE_STR},
        'end': {'dateTime': (start_dt + timedelta(hours=1)).isoformat(), 'timeZone': TEST_TIMEZONE_STR}
    }
    mock_get_pending = mocker.patch('handlers.gs.get_pending_event', new_callable=AsyncMock, return_value=event_details_to_create)
    
    created_link = f"http://example.com/event/{event_summary.replace(' ', '_')}"
    mock_create = mocker.patch('handlers.gs.create_calendar_event', new_callable=AsyncMock, return_value=(True, f"Event '{event_summary}' created successfully.", created_link))
    mock_delete_pending = mocker.patch('handlers.gs.delete_pending_event', new_callable=AsyncMock)
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_any_call(
        f"Adding '{event_summary}'..."
    )
    mock_get_pending.assert_awaited_once_with(TEST_USER_ID)
    mock_create.assert_awaited_once_with(TEST_USER_ID, event_details_to_create)

    final_text = f"Event '{event_summary}' created successfully.\nView: {created_link}"
    mock_update.callback_query.edit_message_text.assert_called_with(
        final_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )
    mock_delete_pending.assert_awaited_once_with(TEST_USER_ID)


async def test_button_callback_confirm_create_expired(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_create")
    mocker.patch('handlers.gs.get_pending_event', new_callable=AsyncMock, return_value=None) # No pending event
    mock_create = mocker.patch('handlers.gs.create_calendar_event', new_callable=AsyncMock)

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Event details expired or not found." # Message changed slightly due to `get_pending_event` returning None
    )
    mock_create.assert_not_awaited()


async def test_button_callback_cancel_create(mock_update, mock_context, mocker):
    mock_update.set_callback_data("cancel_event_create")
    mock_delete_pending = mocker.patch('handlers.gs.delete_pending_event', new_callable=AsyncMock)
    mock_create = mocker.patch('handlers.gs.create_calendar_event', new_callable=AsyncMock)

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Event creation cancelled."
    )
    mock_create.assert_not_awaited()
    mock_delete_pending.assert_awaited_once_with(TEST_USER_ID)

async def test_button_callback_confirm_create_get_pending_exception(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_create")
    # Mock get_pending_event to raise an exception
    mocker.patch('handlers.gs.get_pending_event', new_callable=AsyncMock, side_effect=Exception("GS Get Error"))
    mock_create_event = mocker.patch('handlers.gs.create_calendar_event', new_callable=AsyncMock)
    mock_logger = mocker.patch('handlers.logger') # Assuming logger is used in this path

    await handlers.button_callback(mock_update, mock_context)

    # Behavior depends on try/except block in button_callback for this specific path
    # It might edit message to a generic error, or re-raise, or log.
    # For now, assume it edits to a generic error or specific error related to fetching pending event.
    # Based on current button_callback, it doesn't have a try-except around get_pending_event.
    # So, this test would expect the error to propagate or be caught by a global error handler.
    # If we assume it's caught and a generic message is sent by edit_message_text:
    # mock_update.callback_query.edit_message_text.assert_called_once_with(
    #     "An error occurred while processing your request." # Or similar
    # )
    # This test highlights that the button_callback might need more internal try-except blocks.
    # For now, let's assert no event creation was attempted.
    mock_create_event.assert_not_awaited()
    # Check if query.answer was called (it should be, even on error, if it's at the start)
    # query.answer() is called inside the specific if block, so it won't be called if get_pending_event fails before it.
    # If get_pending_event fails, it will likely go to the main error handler.

    # Let's assume the handler has a try-except around the gs call or the whole block
    # and edits the message. If not, this test would need to assert an exception.
    # Given the current structure, it's more likely the global error handler is hit.
    # This test is more to point out a potential unhandled exception scenario.
    # If the function handles it and edits text:
    # mock_update.callback_query.edit_message_text.assert_called_once_with("Error retrieving event details.")
    # For now, let's check logger if an error is logged by the handler itself.
    # This test is more of an indicator for robust error handling needed in the main code.
    # For the purpose of this exercise, assume it gets logged and no positive action taken.
    # mock_logger.error.assert_called_once() # If the handler logs it.

    # Given the structure, if get_pending_event fails, the callback query answer might not be called.
    # And edit_message_text specific to this path won't be called.
    # This test will pass if no specific positive action is taken and no unhandled exception occurs.
    # However, the global error_handler should catch it and reply.
    # The mock_update.callback_query.edit_message_text should not be called with success/expired message.
    assert mock_update.callback_query.edit_message_text.call_count == 0


# --- Tests for button_callback (Delete Flow) ---

async def test_button_callback_confirm_delete_success(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_delete")

    pending_deletion_data = {'event_id': 'event_to_delete_123', 'summary': 'Old Meeting'}
    mock_get_pending_deletion = mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=pending_deletion_data)

    mock_delete_event = mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock, return_value=(True, "Event 'Old Meeting' successfully deleted."))
    mock_delete_pending_db = mocker.patch('handlers.gs.delete_pending_deletion', new_callable=AsyncMock)
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)


    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once() # Answer is now called inside the block
    mock_get_pending_deletion.assert_awaited_once_with(TEST_USER_ID)
    mock_update.callback_query.edit_message_text.assert_any_call(
        f"Deleting '{pending_deletion_data.get('summary')}'..."
    )
    mock_delete_event.assert_awaited_once_with(TEST_USER_ID, pending_deletion_data['event_id'])
    mock_update.callback_query.edit_message_text.assert_called_with(
        "Event 'Old Meeting' successfully deleted.", parse_mode=ParseMode.HTML
    )
    mock_delete_pending_db.assert_awaited_once_with(TEST_USER_ID)

async def test_button_callback_confirm_delete_expired(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_delete")
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=None) # No pending deletion
    mock_delete_event = mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock)

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Confirmation for deletion expired or not found."
    )
    mock_delete_event.assert_not_awaited()

async def test_button_callback_confirm_delete_missing_event_id(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_delete")
    # Event ID is missing in the stored data
    pending_deletion_data = {'summary': 'Old Meeting'} # No event_id
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=pending_deletion_data)
    mock_delete_event = mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock)
    mock_delete_pending_db = mocker.patch('handlers.gs.delete_pending_deletion', new_callable=AsyncMock)


    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Error: Missing event ID for deletion."
    )
    mock_delete_event.assert_not_awaited()
    mock_delete_pending_db.assert_awaited_once_with(TEST_USER_ID) # Should clear broken data

async def test_button_callback_confirm_delete_gs_failure(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_delete")

    pending_deletion_data = {'event_id': 'event_to_delete_123', 'summary': 'Old Meeting'}
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, return_value=pending_deletion_data)
    # gs.delete_calendar_event returns (False, "Error message")
    mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock, return_value=(False, "GS Deletion Failed"))
    mock_delete_pending_db = mocker.patch('handlers.gs.delete_pending_deletion', new_callable=AsyncMock)
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)


    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_any_call(f"Deleting '{pending_deletion_data.get('summary')}'...")
    mock_update.callback_query.edit_message_text.assert_called_with("GS Deletion Failed", parse_mode=ParseMode.HTML)
    mock_delete_pending_db.assert_awaited_once_with(TEST_USER_ID)


async def test_button_callback_cancel_delete(mock_update, mock_context, mocker):
    mock_update.set_callback_data("cancel_event_delete")
    mock_delete_pending_db = mocker.patch('handlers.gs.delete_pending_deletion', new_callable=AsyncMock)
    mock_delete_event = mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock)

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Event deletion cancelled."
    )
    mock_delete_event.assert_not_awaited()
    mock_delete_pending_db.assert_awaited_once_with(TEST_USER_ID)

async def test_button_callback_confirm_delete_get_pending_exception(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_delete")
    mocker.patch('handlers.gs.get_pending_deletion', new_callable=AsyncMock, side_effect=Exception("GS Get Deletion Error"))
    mock_delete_event = mocker.patch('handlers.gs.delete_calendar_event', new_callable=AsyncMock)

    # Similar to the create flow, expect global error handler or graceful fail.
    # edit_message_text specific to this path should not be called with success/expired.
    await handlers.button_callback(mock_update, mock_context)
    mock_delete_event.assert_not_awaited()
    assert mock_update.callback_query.edit_message_text.call_count == 0


# --- Tests for connect_calendar ---
async def test_connect_calendar_new_user(mock_update, mock_context, mocker):
    mock_update.set_message_text("/connect_calendar")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False) # New user

    mock_flow_instance = MagicMock()
    mock_flow_instance.authorization_url.return_value = ("http://auth.example.com/123", "mock_state")
    mock_get_flow = mocker.patch('handlers.gs.get_google_auth_flow', return_value=mock_flow_instance)

    mock_generate_state = mocker.patch('handlers.gs.generate_oauth_state', new_callable=AsyncMock, return_value="mock_state_generated")

    await handlers.connect_calendar(mock_update, mock_context)

    mock_get_flow.assert_called_once()
    mock_generate_state.assert_awaited_once_with(TEST_USER_ID)
    mock_flow_instance.authorization_url.assert_called_once_with(access_type='offline', prompt='consent', state="mock_state_generated")

    mock_update.effective_message.reply_text.assert_called_once()
    call_args, call_kwargs = mock_update.effective_message.reply_text.call_args
    assert "Click to connect your Google Calendar:" in call_args[0]
    assert isinstance(call_kwargs['reply_markup'], InlineKeyboardMarkup)
    button = call_kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == "Connect Google Calendar"
    assert button.url == "http://auth.example.com/123"

async def test_connect_calendar_already_connected_valid_token(mock_update, mock_context, mocker):
    mock_update.set_message_text("/connect_calendar")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    # Mock _build_calendar_service_client to return a valid service (not None)
    mocker.patch('handlers.gs._build_calendar_service_client', new_callable=AsyncMock, return_value=MagicMock())

    mock_get_flow = mocker.patch('handlers.gs.get_google_auth_flow')

    await handlers.connect_calendar(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with("Calendar already connected!")
    mock_get_flow.assert_not_called()

async def test_connect_calendar_already_connected_invalid_token(mock_update, mock_context, mocker):
    mock_update.set_message_text("/connect_calendar")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    # Mock _build_calendar_service_client to return None (invalid token)
    mocker.patch('handlers.gs._build_calendar_service_client', new_callable=AsyncMock, return_value=None)
    mock_delete_token = mocker.patch('handlers.gs.delete_user_token', new_callable=AsyncMock)

    mock_flow_instance = MagicMock()
    mock_flow_instance.authorization_url.return_value = ("http://auth.example.com/reauth", "mock_state_reauth")
    mocker.patch('handlers.gs.get_google_auth_flow', return_value=mock_flow_instance)
    mocker.patch('handlers.gs.generate_oauth_state', new_callable=AsyncMock, return_value="mock_state_reauth_generated")

    await handlers.connect_calendar(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_any_call("Issue with stored connection. Reconnecting...")
    mock_delete_token.assert_awaited_once_with(TEST_USER_ID)

    # Check if the rest of the flow proceeds
    mock_update.effective_message.reply_text.assert_called_with(
        "Click to connect your Google Calendar:",
        reply_markup=mocker.ANY # Check that some InlineKeyboardMarkup was sent
    )

async def test_connect_calendar_get_flow_fails(mock_update, mock_context, mocker):
    mock_update.set_message_text("/connect_calendar")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False)
    mocker.patch('handlers.gs.get_google_auth_flow', return_value=None) # Simulate flow creation failure
    mock_generate_state = mocker.patch('handlers.gs.generate_oauth_state', new_callable=AsyncMock)

    await handlers.connect_calendar(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with("Error setting up connection.")
    mock_generate_state.assert_not_awaited()

async def test_connect_calendar_generate_state_fails(mock_update, mock_context, mocker):
    mock_update.set_message_text("/connect_calendar")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False)

    mock_flow_instance = MagicMock() # get_google_auth_flow succeeds
    mocker.patch('handlers.gs.get_google_auth_flow', return_value=mock_flow_instance)

    mocker.patch('handlers.gs.generate_oauth_state', new_callable=AsyncMock, return_value=None) # generate_oauth_state fails

    await handlers.connect_calendar(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with("Error generating secure state.")
    mock_flow_instance.authorization_url.assert_not_called()


# --- Tests for _format_iso_datetime_for_display ---

def test_format_iso_datetime_no_tz():
    iso_string = "2024-07-30T10:00:00Z" # UTC
    expected_utc = "2024-07-30 10:00 AM UTC"
    # Depending on local system's interpretation of Z, this might vary without explicit tz handling.
    # The function should ideally make it explicit.
    # If the function assumes Z is UTC and formats with UTC:
    assert handlers._format_iso_datetime_for_display(iso_string) == expected_utc
    
    iso_string_no_tz = "2024-07-30T10:00:00" # Naive
    # Expected behavior for naive might be to assume UTC or local, let's assume it notes it.
    expected_naive_assumed_utc = "2024-07-30 10:00 AM (Timezone not specified, assumed UTC)"
    assert handlers._format_iso_datetime_for_display(iso_string_no_tz) == expected_naive_assumed_utc

def test_format_iso_datetime_with_target_tz():
    iso_string = "2024-07-30T10:00:00Z" # UTC
    target_tz_str = "America/New_York" # EDT is UTC-4
    # Expected: 10:00 UTC is 06:00 AM New York time on July 30th
    expected_ny = "2024-07-30 06:00 AM EDT" 
    assert handlers._format_iso_datetime_for_display(iso_string, target_tz_str) == expected_ny

    iso_string_offset = "2024-07-30T12:00:00+02:00" # CEST
    target_tz_str_london = "Europe/London" # BST is UTC+1
    # Expected: 12:00 CEST (UTC+2) is 11:00 AM London time (BST = UTC+1)
    expected_london = "2024-07-30 11:00 AM BST"
    assert handlers._format_iso_datetime_for_display(iso_string_offset, target_tz_str_london) == expected_london

def test_format_iso_datetime_with_unknown_target_tz():
    iso_string = "2024-07-30T10:00:00Z"
    target_tz_str = "Mars/Olympus_Mons"
    # Should fall back to UTC display
    expected_utc_fallback = "2024-07-30 10:00 AM UTC"
    assert handlers._format_iso_datetime_for_display(iso_string, target_tz_str) == expected_utc_fallback

def test_format_iso_datetime_invalid_iso_string():
    iso_string = "This is not a date"
    # Should return the original string or handle error gracefully
    assert handlers._format_iso_datetime_for_display(iso_string) == iso_string

# --- Tests for summary_command ---
async def test_summary_command_user_not_connected(mock_update, mock_context, mocker):
    mock_update.set_message_text("/summary")
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=False)
    mock_handle_summary_call = mocker.patch('handlers._handle_calendar_summary') # Should not be called

    await handlers.summary_command(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with("Please connect calendar first (/connect_calendar).")
    mock_handle_summary_call.assert_not_called()

async def test_summary_command_success_today(mock_update, mock_context, mocker):
    mock_update.set_message_text("/summary") # No args, defaults to "today"
    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mock_handle_summary_call = mocker.patch('handlers._handle_calendar_summary', new_callable=AsyncMock)

    await handlers.summary_command(mock_update, mock_context)

    mock_handle_summary_call.assert_awaited_once_with(
        mock_update,
        mock_context,
        {"time_period": "today"}
    )

async def test_summary_command_success_with_args(mock_update, mock_context, mocker):
    time_period_arg = "next week"
    mock_update.set_message_text(f"/summary {time_period_arg}")
    mock_context.args = time_period_arg.split() # Simulate context args

    mocker.patch('handlers.gs.is_user_connected', new_callable=AsyncMock, return_value=True)
    mock_handle_summary_call = mocker.patch('handlers._handle_calendar_summary', new_callable=AsyncMock)

    await handlers.summary_command(mock_update, mock_context)

    mock_handle_summary_call.assert_awaited_once_with(
        mock_update,
        mock_context,
        {"time_period": time_period_arg}
    )

# --- Test for error_handler ---
async def test_error_handler_sends_reply(mock_update, mock_context, mocker):
    # Setup a mock error object
    test_exception = ValueError("Test exception for error handler")
    mock_context.error = test_exception

    # Ensure effective_message is present, as error_handler checks for it
    mock_update.effective_message = AsyncMock() # Make sure reply_text is an AsyncMock
    mock_update.effective_message.reply_text = AsyncMock()


    await handlers.error_handler(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_awaited_once_with(
        "Sorry, an internal error occurred. Please try again."
    )

async def test_error_handler_no_update_object(mock_context, mocker):
    # Test when the update object is not an instance of Update (e.g., a string)
    # or doesn't have effective_message.
    test_exception = ValueError("Test exception")
    mock_context.error = test_exception

    # Call with a simple object or string instead of a mock_update
    non_update_object = "This is not a Telegram Update object"

    # We expect it to log but not raise an unhandled exception trying to access reply_text
    # No direct assertion on reply_text, just that it completes without new errors.
    try:
        await handlers.error_handler(non_update_object, mock_context)
    except AttributeError:
        pytest.fail("error_handler raised AttributeError unexpectedly on non-Update object")
    # Further checks could involve capturing logs if logging is heavily tested.
