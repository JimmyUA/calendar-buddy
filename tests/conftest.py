# tests/conftest.py
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import datetime
import pytz
import os

from telegram.ext import ContextTypes

# Load test environment variables if using .env.test
# from dotenv import load_dotenv
# load_dotenv(".env.test")

# --- Constants for Tests ---
TEST_USER_ID = 123456789
TEST_CHAT_ID = 987654321
TEST_USERNAME = "testuser"
TEST_TIMEZONE_STR = "America/Los_Angeles"
TEST_TIMEZONE = pytz.timezone(TEST_TIMEZONE_STR)
TEST_EVENT_ID = "google_event_id_123"

# --- Mock Telegram Objects ---

@pytest.fixture
def mock_user():
    user = MagicMock()
    user.id = TEST_USER_ID
    user.username = TEST_USERNAME
    user.mention_html.return_value = f'<a href="tg://user?id={TEST_USER_ID}">@{TEST_USERNAME}</a>'
    return user

@pytest.fixture
def mock_chat():
    chat = MagicMock()
    chat.id = TEST_CHAT_ID
    return chat

@pytest.fixture
def mock_message(mock_user, mock_chat):
    message = MagicMock()
    message.from_user = mock_user
    message.chat = mock_chat
    message.message_id = 123
    message.text = "" # Default empty text, override in tests
    # Mock reply methods (make them async)
    message.reply_text = AsyncMock()
    message.reply_html = AsyncMock()
    message.reply_markdown = AsyncMock()
    message.chat.send_action = AsyncMock() # For typing indicator
    return message

@pytest.fixture
def mock_callback_query(mock_user, mock_message):
    query = MagicMock()
    query.id = "callback_query_id_123"
    query.from_user = mock_user
    query.message = mock_message # Message the button was attached to
    query.data = "" # Default empty data, override in tests
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    return query

@pytest.fixture
def mock_update(mock_message, mock_callback_query):
    update = MagicMock(spec=['effective_user', 'effective_chat', 'effective_message', 'callback_query']) # Specify common attributes
    update.effective_user = mock_message.from_user
    update.effective_chat = mock_message.chat
    update.effective_message = mock_message
    update.callback_query = None # Default to no callback query
    # Helper to simulate a message update
    def _set_message_text(text):
        update.effective_message.text = text
        update.message = update.effective_message # Some handlers might use update.message
        update.callback_query = None
    # Helper to simulate a callback query update
    def _set_callback_data(data):
        update.callback_query = mock_callback_query
        update.callback_query.data = data
        update.effective_message = None # Callback updates don't usually have a *new* message
        update.message = None
    update.set_message_text = _set_message_text
    update.set_callback_data = _set_callback_data
    return update


@pytest.fixture
def mock_context(mock_user):
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE) # Make sure this class exists or mock it
    context.bot = AsyncMock() # Mock bot object if needed for API calls
    context.args = [] # Default empty args
    context.user_data = {} # Simulate user-specific storage
    context.chat_data = {}
    context.application = MagicMock() # Mock application if needed
    context.error = None
    # Add TEST_USER_ID for convenience if needed directly in tests
    context.user_id_for_test = TEST_USER_ID
    return context


# --- Mock External Services ---

@pytest.fixture
def mock_firestore_db(mocker):
    """Mocks the Firestore client and its methods."""
    # Mock the client constructor used in config.py
    mock_client_constructor = mocker.patch('config.firestore.Client')
    mock_db = MagicMock() # The client instance
    mock_client_constructor.return_value = mock_db

    # Mock collection().document().<method> chain
    mock_collection = MagicMock()
    mock_document = MagicMock()
    mock_snapshot = MagicMock()

    mock_db.collection.return_value = mock_collection
    mock_collection.document.return_value = mock_document

    # Configure common doc methods
    mock_document.get.return_value = mock_snapshot
    mock_document.set = MagicMock()
    mock_document.delete = MagicMock()
    mock_document.update = MagicMock() # If you use update

    # Default snapshot state (not found)
    mock_snapshot.exists = False
    mock_snapshot.to_dict.return_value = {}
    mock_snapshot.get = MagicMock(return_value=None) # For field_path gets

    # Make snapshot reusable for setting data in tests
    def _set_snapshot_data(data, exists=True):
        mock_snapshot.exists = exists
        mock_snapshot.to_dict.return_value = data if exists else {}
        # Make snapshot.get('field_name') work
        mock_snapshot.get = lambda key, default=None: data.get(key, default) if exists else default
    mock_snapshot.configure_mock_data = _set_snapshot_data

    # Mock transaction
    mock_transaction = MagicMock()
    mock_db.transaction.return_value = mock_transaction
    # If needed, mock methods used within transaction functions

    # Return the mocked DB instance so tests can configure collections/docs as needed
    return mock_db, mock_collection, mock_document, mock_snapshot

@pytest_asyncio.fixture
async def mock_google_calendar_service(mocker):
    """Mocks the Google Calendar API client build and service methods."""
    mock_build = mocker.patch('google_services.build')
    mock_service = MagicMock()
    mock_build.return_value = mock_service

    # Mock the events() resource and its methods (make execute async)
    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    # Mock common methods (return AsyncMocks for execute)
    # Using AsyncMock directly for execute is often simpler than mock_events.method().execute = AsyncMock()
    mock_events.list = AsyncMock(return_value={'items': []}) # Default: empty list
    mock_events.get = AsyncMock(return_value={'summary': 'Mock Event', 'id': TEST_EVENT_ID})
    mock_events.insert = AsyncMock(return_value={'summary': 'New Mock Event', 'id': 'new_event_id_456', 'htmlLink': 'http://example.com/new'})
    mock_events.delete = AsyncMock(return_value=None) # Delete returns empty body on success

    # --- CORRECTED Helper functions to configure mocks ---
    def configure_events(items):
        # Update the return_value of the list mock directly
        mock_events.list.return_value = {'items': items}

    def configure_get(event_data):
        mock_events.get.return_value = event_data

    def configure_insert(event_data):
        mock_events.insert.return_value = event_data

    def configure_delete_error(error):
        mock_events.delete.side_effect = error # Assign error to side_effect

    def configure_list_error(error):
        mock_events.list.side_effect = error # Assign error to side_effect

    # Attach the helper functions to the mock_service object
    mock_service.configure_mock_events = configure_events
    mock_service.configure_mock_get = configure_get
    mock_service.configure_mock_insert = configure_insert
    mock_service.configure_mock_delete_error = configure_delete_error
    mock_service.configure_mock_list_error = configure_list_error
    # ... add more config helpers as needed

    return mock_service


@pytest_asyncio.fixture
async def mock_llm_service(mocker):
    """Mocks the Gemini LLM service."""
    # Mock the model object used in llm_service.py
    mock_model = AsyncMock() # Use AsyncMock for async methods
    mocker.patch('llm.llm_service.gemini_model', mock_model)
    mocker.patch('llm.llm_service.llm_available', True) # Assume available for tests

    # Mock the primary method
    mock_response = MagicMock()
    mock_response.text = "" # Default empty response
    mock_response.prompt_feedback = None # Default no blocking
    mock_model.generate_content_async.return_value = mock_response

    # Allow tests to configure the response text
    def configure_response(text, blocked=False, block_reason="TEST_BLOCK"):
        mock_response.text = text
        if blocked:
            mock_response.prompt_feedback = MagicMock()
            mock_response.prompt_feedback.block_reason = block_reason
        else:
            mock_response.prompt_feedback = None
    mock_model.configure_response = configure_response

    return mock_model

# Fixture to mock the AgentExecutor for handler tests
@pytest_asyncio.fixture
async def mock_agent_executor(mocker):
    mock_executor = AsyncMock() # Mock the executor instance
    mock_executor.ainvoke = AsyncMock(return_value={'output': 'Agent response'}) # Default response
    # Mock the initializer function in agent.py to return our mock executor
    mocker.patch('handlers.initialize_agent', return_value=mock_executor)
    return mock_executor

# Fixture to automatically patch config state (useful if directly used)
@pytest.fixture(autouse=True) # Apply automatically to all tests
def patch_config_state(mocker):
    """Clear pending states before each test."""
    mocker.patch('config.pending_events', {})
    mocker.patch('config.pending_deletions', {})