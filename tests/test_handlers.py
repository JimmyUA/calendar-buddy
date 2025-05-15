# tests/test_handlers.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, call
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler
from telegram.constants import ParseMode

# Import handlers AFTER fixtures might patch dependencies
import handlers
import config
import google_services as gs  # To mock functions called by handlers
from .conftest import TEST_USER_ID, TEST_CHAT_ID, TEST_TIMEZONE_STR, TEST_EVENT_ID

pytestmark = pytest.mark.asyncio


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
    # Mock gs.is_user_connected to return True
    mocker.patch('handlers.gs.is_user_connected', return_value=True)
    # Mock _build_calendar_service_client to simulate valid connection
    mocker.patch('handlers.gs._build_calendar_service_client', return_value=MagicMock())

    await handlers.my_status(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "✅ Calendar connected & credentials valid."
    )


async def test_my_status_not_connected(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', return_value=False)

    await handlers.my_status(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "❌ Calendar not connected. Use /connect_calendar."
    )


async def test_my_status_invalid_creds(mock_update, mock_context, mocker):
    mock_update.set_message_text("/my_status")
    mocker.patch('handlers.gs.is_user_connected', return_value=True)
    # Mock _build_calendar_service_client to simulate invalid connection
    mocker.patch('handlers.gs._build_calendar_service_client', return_value=None)

    await handlers.my_status(mock_update, mock_context)
    mock_update.effective_message.reply_text.assert_called_once_with(
        "⚠️ Calendar connected, but credentials invalid. Try /disconnect_calendar and /connect_calendar."
    )


async def test_disconnect_calendar(mock_update, mock_context, mocker):
    mock_update.set_message_text("/disconnect_calendar")
    mock_delete = mocker.patch('handlers.gs.delete_user_token', return_value=True)
    # Patch config state directly if needed
    with patch.dict(config.pending_events, {TEST_USER_ID: {}}), \
            patch.dict(config.pending_deletions, {TEST_USER_ID: {}}):
        await handlers.disconnect_calendar(mock_update, mock_context)

        mock_delete.assert_called_once_with(TEST_USER_ID)
        mock_update.effective_message.reply_text.assert_called_once_with(
            "Calendar connection removed."
        )
        # Assert pending states were cleared for the user
        assert TEST_USER_ID not in config.pending_events
        assert TEST_USER_ID not in config.pending_deletions


# --- Timezone Conversation ---

async def test_set_timezone_start(mock_update, mock_context, mocker):
    mock_update.set_message_text("/set_timezone")
    mocker.patch('handlers.gs.get_user_timezone_str', return_value=None)  # Simulate not set

    result_state = await handlers.set_timezone_start(mock_update, mock_context)

    assert result_state == handlers.ASKING_TIMEZONE
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert "Please tell me your timezone" in call_args
    assert "Your timezone is not set yet" in call_args


async def test_set_timezone_start_already_set(mock_update, mock_context, mocker):
    mock_update.set_message_text("/set_timezone")
    mocker.patch('handlers.gs.get_user_timezone_str', return_value=TEST_TIMEZONE_STR)

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
    mock_save = mocker.patch('handlers.gs.set_user_timezone', return_value=True)

    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == ConversationHandler.END
    mock_save.assert_called_once_with(TEST_USER_ID, TEST_TIMEZONE_STR)
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert f"Timezone set to `{TEST_TIMEZONE_STR}`" in call_args


async def test_received_timezone_invalid(mock_update, mock_context, mocker):
    invalid_tz = "Invalid/Zone"
    mock_update.set_message_text(invalid_tz)
    # Mock pytz validation to raise error
    mocker.patch('handlers.pytz.timezone', side_effect=handlers.UnknownTimeZoneError)
    mock_save = mocker.patch('handlers.gs.set_user_timezone')

    result_state = await handlers.received_timezone(mock_update, mock_context)

    assert result_state == handlers.ASKING_TIMEZONE  # Should stay in same state
    mock_save.assert_not_called()
    mock_update.effective_message.reply_text.assert_called_once()
    call_args = mock_update.effective_message.reply_text.call_args[0][0]
    assert f"Sorry, '{invalid_tz}' doesn't look like a valid IANA timezone" in call_args


async def test_cancel_timezone(mock_update, mock_context):
    mock_update.set_message_text("/cancel")
    result_state = await handlers.cancel_timezone(mock_update, mock_context)
    assert result_state == ConversationHandler.END
    mock_update.effective_message.reply_text.assert_called_once_with("Timezone setup cancelled.")


# --- handle_message (Agent Interaction) ---

async def test_handle_message_connect_first(mock_update, mock_context, mocker):
    mock_update.set_message_text("What's on my calendar?")
    mocker.patch('handlers.gs.is_user_connected', return_value=False)
    mock_agent_init = mocker.patch('handlers.initialize_agent')  # Agent shouldn't be called

    await handlers.handle_message(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once_with(
        "Please connect your Google Calendar first using /connect_calendar."
    )
    mock_agent_init.assert_not_called()


async def test_handle_message_set_timezone_first_strict(mock_update, mock_context, mocker):
    # This test assumes the strict behaviour (prompting for timezone if not set)
    mock_update.set_message_text("What's on my calendar?")
    mocker.patch('handlers.gs.is_user_connected', return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', return_value=None)  # Timezone NOT set
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
    mocker.patch('handlers.gs.is_user_connected', return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', return_value=TEST_TIMEZONE_STR)

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
    # The fixture mock_agent_executor already does this:
    # mocker.patch('handlers.initialize_agent', return_value=mock_executor)
    # We need to get that specific mock object.

    # --- Corrected approach to get the right mock ---
    # 1. Get the mock for initialize_agent directly before the call
    mock_init_agent_func = mocker.patch('handlers.initialize_agent', return_value=mock_agent_executor)
    # This mock_init_agent_func is the one that will be called by handlers.handle_message

    await handlers.handle_message(mock_update, mock_context)

    # Assert agent was initialized correctly using the mock we captured
    mock_init_agent_func.assert_called_once()  # First, ensure it was called
    init_call_args = mock_init_agent_func.call_args

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
    confirmation_question = f"""Okay, I can create this event:
<b>Summary:</b> Lunch
<b>Start:</b> Mon, Aug 19, 2024 at 12:00 PM PDT
<b>End:</b> Tue, Aug 20, 2024 at 04:00 PM PDT
<b>Description:</b> -
<b>Location:</b> -

Should I add this to your calendar?"""
    agent_response_text = confirmation_question  # Agent's final output IS the question

    mock_update.set_message_text(user_message)
    mocker.patch('handlers.gs.is_user_connected', return_value=True)
    mocker.patch('handlers.gs.get_user_timezone_str', return_value=TEST_TIMEZONE_STR)

    # Configure agent response
    mock_agent_executor.ainvoke.return_value = {'output': agent_response_text}

    # Simulate that the *tool run* (mocked within agent execution usually)
    # placed data into the config pending state before agent finished
    mock_event_data = {'summary': 'Lunch', 'start': 'Mon, Aug 19, 2024 at 12:00 PM PDT',
                       'end': 'Tue, Aug 20, 2024 at 04:00 PM PDT', }  # Example
    config.pending_events[TEST_USER_ID] = mock_event_data  # Manually set state for test

    mock_context.user_data['lc_history'] = []

    await handlers.handle_message(mock_update, mock_context)

    # Assert agent invoked etc. (as above)
    mock_agent_executor.ainvoke.assert_called_once()

    # Assert reply has the confirmation text AND the buttons
    mock_update.effective_message.reply_text.assert_called_once()
    call_args, call_kwargs = mock_update.effective_message.reply_text.call_args
    assert call_args[0] == confirmation_question
    assert isinstance(call_kwargs['reply_markup'], InlineKeyboardMarkup)
    button = call_kwargs['reply_markup'].inline_keyboard[0][0]
    assert button.text == "✅ Confirm Create"
    assert button.callback_data == "confirm_event_create"

    # Assert history updated correctly
    assert mock_context.user_data['lc_history'] == [
        {'role': 'user', 'content': user_message},
        {'role': 'model', 'content': confirmation_question}  # History contains the confirmation Q
    ]


# --- Callback Handler ---

async def test_button_callback_confirm_create_success(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_create")

    # Simulate pending event data exists
    event_details_to_create = {'summary': 'Pending Lunch', 'start': {...}, 'end': {...}}
    config.pending_events[TEST_USER_ID] = event_details_to_create

    # Mock the actual Google service call
    created_link = "http://example.com/created_event"
    mock_create = mocker.patch('handlers.gs.create_calendar_event',
                               return_value=(True, "Event 'Pending Lunch' created successfully.", created_link))

    await handlers.button_callback(mock_update, mock_context)

    # Assert query answered and message edited initially
    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_any_call(
        f"Adding '{event_details_to_create.get('summary')}'..."
    )

    # Assert gs create called with correct data
    mock_create.assert_called_once_with(TEST_USER_ID, event_details_to_create)

    # Assert final message edit
    final_text = f"Event 'Pending Lunch' created successfully.\nView: {created_link}"
    mock_update.callback_query.edit_message_text.assert_called_with(
        final_text, parse_mode=ParseMode.HTML
    )

    # Assert pending state cleared
    assert TEST_USER_ID not in config.pending_events


async def test_button_callback_confirm_create_expired(mock_update, mock_context, mocker):
    mock_update.set_callback_data("confirm_event_create")
    # Ensure no pending data exists
    if TEST_USER_ID in config.pending_events: del config.pending_events[TEST_USER_ID]
    mock_create = mocker.patch('handlers.gs.create_calendar_event')

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Event details expired."
    )
    mock_create.assert_not_called()


async def test_button_callback_cancel_create(mock_update, mock_context, mocker):
    mock_update.set_callback_data("cancel_event_create")
    # Simulate pending data exists initially
    config.pending_events[TEST_USER_ID] = {'summary': 'something'}
    mock_create = mocker.patch('handlers.gs.create_calendar_event')

    await handlers.button_callback(mock_update, mock_context)

    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once_with(
        "Event creation cancelled."
    )
    mock_create.assert_not_called()
    assert TEST_USER_ID not in config.pending_events  # Assert state cleared

# --- Add similar tests for delete confirmations ---
# test_button_callback_confirm_delete_success
# test_button_callback_confirm_delete_expired
# test_button_callback_cancel_delete
