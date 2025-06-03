# tests/conftest.py
import pytest
import pytest_asyncio

pytest_plugins = ["pytest_mock"]
from unittest.mock import MagicMock, AsyncMock, patch
import datetime
import pytz
import os

# --- Option 1: Load .env file using pytest_configure (if not using pytest-dotenv) ---
# Ensure python-dotenv is installed: pip install python-dotenv
# from dotenv import load_dotenv
# def pytest_configure(config_hook): # 'config' is pytest's internal config object
#     """
#     Load environment variables from .env.test or .env file before tests run.
#     """
#     project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # Project root
#     dotenv_path_test = os.path.join(project_root, '.env.test')
#     dotenv_path_main = os.path.join(project_root, '.env')

#     loaded_path = None
#     if os.path.exists(dotenv_path_test):
#         load_dotenv(dotenv_path=dotenv_path_test, override=True)
#         loaded_path = dotenv_path_test
#     elif os.path.exists(dotenv_path_main):
#         load_dotenv(dotenv_path=dotenv_path_main, override=True)
#         loaded_path = dotenv_path_main

#     if loaded_path:
#         print(f"\nLoaded environment variables from: {loaded_path} (via conftest.py)")
#     else:
#         print("\nNo .env or .env.test file found by conftest.py to load.")
#     # Ensure critical env vars are present after attempting to load
#     # This is a good place for an early check if pytest-dotenv isn't used or fails
#     # for key in ["TELEGRAM_BOT_TOKEN", "GOOGLE_CLIENT_SECRETS_CONTENT", "OAUTH_REDIRECT_URI"]:
#     #     if not os.getenv(key):
#     #         raise RuntimeError(f"Critical environment variable {key} not set after .env load attempt.")


# --- Constants for Tests ---
TEST_USER_ID = 123456789
TEST_CHAT_ID = 987654321
TEST_USERNAME = "testuser"
TEST_TIMEZONE_STR = "America/Los_Angeles" # Example, ensure it's valid for pytz
TEST_TIMEZONE = pytz.timezone(TEST_TIMEZONE_STR) if TEST_TIMEZONE_STR else pytz.utc
TEST_EVENT_ID = "google_event_id_123"

# --- NEW: Fixture to mock Firestore client globally for tests ---
@pytest.fixture(scope="session", autouse=True)
def mock_firestore_client_globally():
    """
    Mocks the firestore.Client constructor *before* config.py tries to use it.
    This prevents the real client from initializing and failing.
    Uses unittest.mock.patch directly for session scope.
    """
    mock_client_instance = MagicMock(name="MockFirestoreClientInstance")

    mock_collection_obj = MagicMock(name="MockCollection")
    mock_document_obj = MagicMock(name="MockDocument")
    mock_snapshot_obj = MagicMock(name="MockSnapshot")

    mock_client_instance.collection.return_value = mock_collection_obj
    mock_collection_obj.document.return_value = mock_document_obj
    mock_document_obj.get.return_value = mock_snapshot_obj
    mock_document_obj.set = MagicMock(name="MockDocSet")
    mock_document_obj.delete = MagicMock(name="MockDocDelete")
    mock_document_obj.update = MagicMock(name="MockDocUpdate")
    mock_snapshot_obj.exists = False
    mock_snapshot_obj.to_dict.return_value = {}
    mock_snapshot_obj.get = MagicMock(name="MockSnapshotGetField", return_value=None)

    def _set_snapshot_data(data_dict, exists_val=True):
        mock_snapshot_obj.exists = exists_val
        mock_snapshot_obj.to_dict.return_value = data_dict if exists_val else {}
        if exists_val and isinstance(data_dict, dict):
            mock_snapshot_obj.get = lambda key, default=None: data_dict.get(key, default)
        else:
            mock_snapshot_obj.get = MagicMock(name="MockSnapshotGetField_NotExists", return_value=None)

    mock_snapshot_obj.configure_mock_data = _set_snapshot_data

    mock_transaction_obj = MagicMock(name="MockTransaction")
    mock_client_instance.transaction.return_value = mock_transaction_obj
    # --- End of mock_client_instance setup ---

    print("\nStarting global patch for google.cloud.firestore.Client (session scope)...")
    patcher = patch('google.cloud.firestore.Client', return_value=mock_client_instance)

    patcher.start()  # Start the patch
    yield mock_client_instance  # This is what config.FIRESTORE_DB will be assigned

    print("\nStopping global patch for google.cloud.firestore.Client (session scope)...")
    patcher.stop()  # Ensure patch is stopped


# --- Mock Telegram Objects ---
@pytest.fixture
def mock_user():
    user = MagicMock(name="MockUser")
    user.id = TEST_USER_ID
    user.username = TEST_USERNAME
    user.mention_html.return_value = f'<a href="tg://user?id={TEST_USER_ID}">@{TEST_USERNAME}</a>'
    return user

@pytest.fixture
def mock_chat():
    chat = MagicMock(name="MockChat")
    chat.id = TEST_CHAT_ID
    return chat

@pytest.fixture
def mock_message(mock_user, mock_chat):
    message = MagicMock(name="MockMessage")
    message.from_user = mock_user
    message.chat = mock_chat
    message.message_id = 123
    message.text = "" # Default empty text, override in tests
    message.reply_text = AsyncMock(name="MockReplyText")
    message.reply_html = AsyncMock(name="MockReplyHtml")
    message.reply_markdown = AsyncMock(name="MockReplyMarkdown") # If you use it
    message.chat.send_action = AsyncMock(name="MockSendAction")
    return message

@pytest.fixture
def mock_callback_query(mock_user, mock_message):
    query = MagicMock(name="MockCallbackQuery")
    query.id = "callback_query_id_123"
    query.from_user = mock_user
    query.message = mock_message
    query.data = ""
    query.answer = AsyncMock(name="MockQueryAnswer")
    query.edit_message_text = AsyncMock(name="MockQueryEditMessageText")
    query.edit_message_reply_markup = AsyncMock(name="MockQueryEditReplyMarkup") # If you use it
    return query

@pytest.fixture
def mock_update(mock_message, mock_callback_query, mock_user, mock_chat): # Added mock_user, mock_chat
    update = MagicMock(name="MockUpdate", spec=['effective_user', 'effective_chat', 'effective_message', 'callback_query', 'message'])
    update.effective_user = mock_user
    update.effective_chat = mock_chat
    update.effective_message = mock_message
    update.message = mock_message # Often interchangeable with effective_message
    update.callback_query = None

    def _set_message_text(text):
        update.effective_message.text = text
        update.message = update.effective_message
        update.callback_query = None
    def _set_callback_data(data):
        update.callback_query = mock_callback_query
        update.callback_query.data = data
        # When a callback query happens, effective_message might be the message the button was on
        # but update.message might be None as no new message was sent by the user.
        # For simplicity, let's keep effective_message as the button's message.
        update.effective_message = mock_callback_query.message
        update.message = None # No new direct user message for a callback
    update.set_message_text = _set_message_text
    update.set_callback_data = _set_callback_data
    return update

@pytest.fixture
def mock_context(mock_user): # mock_user implicitly provides TEST_USER_ID
    # Ensure ContextTypes.DEFAULT_TYPE exists or mock it if it's a specific class
    # from telegram.ext import ContextTypes # if ContextTypes is real
    # context = MagicMock(spec=ContextTypes.DEFAULT_TYPE, name="MockContext")
    context = MagicMock(name="MockContext") # Simpler if spec causes issues
    context.bot = AsyncMock(name="MockBot")
    context.args = []
    context.user_data = {}
    context.chat_data = {} # If you use chat_data
    context.application = MagicMock(name="MockApplication")
    context.error = None
    return context

# --- Mock External Services (excluding Firestore which is now globally mocked) ---

@pytest_asyncio.fixture
async def mock_google_calendar_service(mocker):
    """Mocks the Google Calendar API client build and service methods."""
    mock_build_func = mocker.patch('google_services.build', name="MockGoogleServicesBuild") # Patch where it's imported
    mock_service_instance = MagicMock(name="MockCalendarServiceInstance")
    mock_build_func.return_value = mock_service_instance

    mock_events_resource = MagicMock(name="MockEventsResource")
    mock_service_instance.events.return_value = mock_events_resource

    # Configure default behaviors for common event methods
    mock_events_resource.list = AsyncMock(name="MockEventsList", return_value={'items': []})
    mock_events_resource.get = AsyncMock(name="MockEventsGet", return_value={'summary': 'Mock Event', 'id': TEST_EVENT_ID})
    mock_events_resource.insert = AsyncMock(name="MockEventsInsert", return_value={'summary': 'New Mock Event', 'id': 'new_event_id_456', 'htmlLink': 'http://example.com/new'})
    mock_events_resource.delete = AsyncMock(name="MockEventsDelete", return_value=None) # Successful delete returns no body

    # Helper functions to configure mock responses from tests
    def configure_list_items(items_list):
        mock_events_resource.list.return_value = {'items': items_list}
    def configure_get_event(event_dict):
        mock_events_resource.get.return_value = event_dict
    def configure_insert_event(event_dict):
        mock_events_resource.insert.return_value = event_dict
    def configure_list_error(exception_to_raise):
        mock_events_resource.list.side_effect = exception_to_raise
    def configure_get_error(exception_to_raise):
        mock_events_resource.get.side_effect = exception_to_raise
    def configure_insert_error(exception_to_raise):
        mock_events_resource.insert.side_effect = exception_to_raise
    def configure_delete_error(exception_to_raise):
        mock_events_resource.delete.side_effect = exception_to_raise

    mock_service_instance.configure_mock_list_items = configure_list_items
    mock_service_instance.configure_mock_get_event = configure_get_event
    mock_service_instance.configure_mock_insert_event = configure_insert_event
    mock_service_instance.configure_mock_list_error = configure_list_error
    mock_service_instance.configure_mock_get_error = configure_get_error
    mock_service_instance.configure_mock_insert_error = configure_insert_error
    mock_service_instance.configure_mock_delete_error = configure_delete_error

    return mock_service_instance


@pytest_asyncio.fixture
async def mock_llm_service(mocker):
    """Mocks the Gemini LLM service in llm.llm_service."""
    mock_model_instance = AsyncMock(name="MockGeminiModelInstance") # The GenerativeModel instance
    # Patch where gemini_model is defined in your llm_service.py
    mocker.patch('llm.llm_service.gemini_model', mock_model_instance)
    mocker.patch('llm.llm_service.llm_available', True) # Assume available for tests

    mock_response_obj = MagicMock(name="MockGeminiResponse")
    mock_response_obj.text = "" # Default empty response
    mock_response_obj.prompt_feedback = None # Default no blocking
    # If your code accesses response.parts
    # mock_response_obj.parts = [MagicMock(text="")]
    mock_model_instance.generate_content_async.return_value = mock_response_obj

    def configure_response(text_content, is_blocked=False, block_reason_val="TEST_BLOCK_REASON"):
        mock_response_obj.text = text_content
        # if hasattr(mock_response_obj, 'parts'):
        #     mock_response_obj.parts = [MagicMock(text=text_content)]
        if is_blocked:
            mock_response_obj.prompt_feedback = MagicMock(block_reason=block_reason_val)
        else:
            mock_response_obj.prompt_feedback = None
    mock_model_instance.configure_response = configure_response
    return mock_model_instance

@pytest_asyncio.fixture
async def mock_agent_executor(mocker):
    """Mocks the agent executor and its ainvoke method."""
    mock_executor_instance = AsyncMock(name="MockAgentExecutorInstance")
    mock_executor_instance.ainvoke.return_value = {'output': 'Default Agent Response'} # Default
    # Patch the initialize_agent function in the module where it's CALLED from (e.g., handlers)
    # This ensures that when handlers.initialize_agent is called, it returns our mock_executor_instance
    mocker.patch('handlers.initialize_agent', return_value=mock_executor_instance, name="MockInitializeAgentInHandlers")
    return mock_executor_instance


# This fixture re-provides the globally mocked Firestore client parts for easier use in tests
# that need to configure specific document behaviors.
@pytest.fixture
def mock_firestore_db(mock_firestore_client_globally): # Depends on the global mock
    """
    Provides access to the components of the already mocked Firestore client.
    (config.FIRESTORE_DB will be mock_firestore_client_globally).
    """
    # mock_firestore_client_globally is the instance that config.FIRESTORE_DB becomes.
    # Retrieve the sub-mocks that were set up on it for convenience.
    db_instance = mock_firestore_client_globally
    collection_mock = db_instance.collection.return_value
    document_mock = collection_mock.document.return_value
    snapshot_mock = document_mock.get.return_value # The snapshot returned by get()

    # Important: Reset mocks for document/snapshot if they are reused across tests
    # to avoid state leakage from one test to another.
    # Or, ensure tests always reconfigure the snapshot via snapshot_mock.configure_mock_data()
    document_mock.reset_mock() # Resets call counts, return_values, side_effects
    snapshot_mock.reset_mock()
    snapshot_mock.configure_mock_data({}, exists_val=False) # Reset to default "not found" state

    return db_instance, collection_mock, document_mock, snapshot_mock


@pytest.fixture(autouse=True)
def patch_config_dictionaries_in_memory(mocker):
    """
    Clears the module-level dictionaries in config.py before each test.
    This is for in-memory state, not Firestore.
    It patches the dictionaries themselves to be empty.
    """
    # We need to import config *after* the global Firestore mock is in place
    # to avoid the real Firestore init error.
    # This fixture will run for every test.
    try:
        import config
        # Use patch.dict to modify the dictionaries in place for the duration of the test
        mocker.patch.dict(config.pending_events, clear=True)
        mocker.patch.dict(config.pending_deletions, clear=True)
    except RuntimeError as e:
        # This might happen if config.py still fails to import due to other reasons
        # (e.g., missing environment variables if pytest-dotenv/pytest_configure isn't working)
        print(f"Warning: Could not patch config dictionaries due to import error: {e}")
        # Depending on your setup, you might want to raise this or just warn.
        # If tests rely on these being clear, they might fail if this patching doesn't happen.
        pass