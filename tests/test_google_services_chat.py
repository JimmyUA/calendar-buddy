# tests/test_google_services_chat.py
import pytest
from unittest.mock import AsyncMock, call # Import call for checking batch deletes

# Import the google_services module we are testing
import google_services as gs
import config # For MAX_HISTORY_MESSAGES

# Constants
TEST_USER_ID = 12345
TEST_USER_ID_STR = str(TEST_USER_ID)

pytestmark = pytest.mark.asyncio

async def test_get_chat_history_exists(mock_firestore_db):
    """
    Test get_chat_history when history exists and is retrieved correctly.
    """
    history_type = "lc"
    mock_messages_data = [
        ("msg1", {"role": "user", "content": "Hello", "timestamp": 1700000000}),
        ("msg2", {"role": "model", "content": "Hi there!", "timestamp": 1700000001}),
    ]
    expected_history = [
        {"role": "user", "content": "Hello"},
        {"role": "model", "content": "Hi there!"},
    ]

    # Configure the mock query stream results
    # The collection().document().collection().order_by().limit().stream() chain
    # The mock_firestore_db["query"] is what .where(), .order_by(), .limit() return.
    mock_firestore_db["configure_query_stream_results"](mock_messages_data)

    # Call the function
    retrieved_history = await gs.get_chat_history(TEST_USER_ID, history_type)

    # Assertions
    assert retrieved_history == expected_history

    # Check how Firestore was called
    # config.FIRESTORE_DB is mock_firestore_db["client"]
    # First collection call is for FS_COLLECTION_LC_CHAT_HISTORIES
    mock_firestore_db["client"].collection.assert_any_call(config.FS_COLLECTION_LC_CHAT_HISTORIES)

    # The mock_firestore_db["collection"] is the one returned by the first .collection() call
    # Then .document(TEST_USER_ID_STR) is called on it
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)

    # Then .collection('messages') is called on the document mock
    mock_firestore_db["document"].collection.assert_called_with('messages')

    # Then .order_by().limit().stream()
    # The collection mock returned by document.collection() is the same shared one for this test,
    # so we check calls on mock_firestore_db["collection"] again if sub-collection shares the same mock instance.
    # Based on conftest.py: mock_document_obj.collection.return_value = mock_collection_obj
    # So, the sub-collection 'messages' uses the same mock_collection_obj.

    # Check the query calls on the query object
    mock_firestore_db["query"].order_by.assert_called_with('timestamp', direction='DESCENDING') # Corrected from firestore.Query.DESCENDING
    mock_firestore_db["query"].limit.assert_called_with(config.MAX_HISTORY_MESSAGES)
    mock_firestore_db["query"].stream.assert_called_once()

async def test_get_chat_history_no_history(mock_firestore_db):
    """
    Test get_chat_history when no history exists for the user.
    """
    history_type = "general"
    mock_firestore_db["configure_query_stream_results"]([]) # No messages

    retrieved_history = await gs.get_chat_history(TEST_USER_ID, history_type)

    assert retrieved_history == []
    mock_firestore_db["client"].collection.assert_any_call(config.FS_COLLECTION_GENERAL_CHAT_HISTORIES)
    mock_firestore_db["collection"].document.assert_called_with(TEST_USER_ID_STR)
    mock_firestore_db["document"].collection.assert_called_with('messages')
    mock_firestore_db["query"].stream.assert_called_once()


async def test_get_chat_history_firestore_error(mock_firestore_db):
    """
    Test get_chat_history when Firestore raises an error during stream.
    """
    history_type = "lc"
    mock_firestore_db["query"].stream.side_effect = Exception("Firestore boom!")

    retrieved_history = await gs.get_chat_history(TEST_USER_ID, history_type)

    assert retrieved_history == []
    # We can still check that the initial calls to Firestore were attempted
    mock_firestore_db["client"].collection.assert_any_call(config.FS_COLLECTION_LC_CHAT_HISTORIES)

async def test_get_chat_history_unknown_type(mock_firestore_db):
    """
    Test get_chat_history with an unknown history type.
    """
    retrieved_history = await gs.get_chat_history(TEST_USER_ID, "unknown_type")
    assert retrieved_history == []
    mock_firestore_db["client"].collection.assert_not_called() # Should not attempt to get a collection

# --- Tests for add_chat_message ---

async def test_add_chat_message_new_history_no_trim(mock_firestore_db):
    """
    Test add_chat_message when adding to new history, no trimming needed.
    """
    history_type = "lc"
    role = "user"
    content = "Hello bot"

    # Simulate no existing messages for the count query
    # This query happens *after* the add, to check if trimming is needed
    # So, when it queries, it will find the one message we just added.
    mock_firestore_db["configure_query_stream_results"]([
        ("new_msg_id", {"role": role, "content": content, "timestamp": 1700000000})
    ])

    success = await gs.add_chat_message(TEST_USER_ID, role, content, history_type)

    assert success is True
    # Check add call
    # The collection for messages is a subcollection, so it's the one returned by document.collection()
    # which in our mock setup reuses the main mock_firestore_db["collection"]
    # The add method is on this collection mock.
    actual_collection_for_add = mock_firestore_db["document"].collection.return_value
    actual_collection_for_add.add.assert_called_once()
    added_message = actual_collection_for_add.add.call_args[0][0]
    assert added_message["role"] == role
    assert added_message["content"] == content
    assert "timestamp" in added_message # Should be firestore.SERVER_TIMESTAMP

    # Check that no trimming was attempted (batch commit not called)
    mock_firestore_db["batch"].commit.assert_not_called()
    mock_firestore_db["batch"].delete.assert_not_called()


async def test_add_chat_message_with_trimming(mock_firestore_db):
    """
    Test add_chat_message when adding causes history to exceed max, requiring trimming.
    """
    history_type = "general"
    role = "user"
    content = f"message_{config.MAX_HISTORY_MESSAGES + 1}" # This is the newest message

    # Simulate existing messages + the new one, exceeding MAX_HISTORY_MESSAGES
    # Oldest messages should be at the start of this list for the trimming logic

    # Create MAX_HISTORY_MESSAGES + 1 messages.
    # The query for trimming (all_messages_query) orders by ASC timestamp.
    # So, the first ones in this list will be deleted.
    messages_to_simulate = []
    num_to_delete = (config.MAX_HISTORY_MESSAGES + 1) - config.MAX_HISTORY_MESSAGES # Should be 1

    for i in range(config.MAX_HISTORY_MESSAGES + 1):
        msg_content = f"message_{i}"
        # if i == config.MAX_HISTORY_MESSAGES: # This is the message being added
        #     msg_content = content
        messages_to_simulate.append(
            (f"msg{i}", {"role": "user" if i % 2 == 0 else "model", "content": msg_content, "timestamp": 1700000000 + i})
        )

    mock_firestore_db["configure_query_stream_results"](messages_to_simulate)

    # The add method on the collection mock needs to be reset if it was called in a previous test
    # The mock_firestore_db fixture already resets collection_mock which holds 'add'
    # So, mock_firestore_db["collection"].add or actual_collection_for_add.add should be clean.
    actual_collection_for_add = mock_firestore_db["document"].collection.return_value


    success = await gs.add_chat_message(TEST_USER_ID, role, content, history_type)
    assert success is True

    # Check add call for the new message
    actual_collection_for_add.add.assert_called_once()
    added_message = actual_collection_for_add.add.call_args[0][0]
    assert added_message["role"] == role
    assert added_message["content"] == content

    # Check trimming calls (batch delete and commit)
    # The number of messages to delete is (current_count - MAX_HISTORY_MESSAGES)
    # current_count will be MAX_HISTORY_MESSAGES + 1
    # So, 1 message should be deleted.
    assert mock_firestore_db["batch"].delete.call_count == num_to_delete

    # Check that the reference of the oldest message was passed to delete
    # messages_to_simulate[0] is (doc_id, doc_data)
    # configure_query_stream_results creates snapshots with a .reference attribute
    expected_deleted_ref = mock_firestore_db["query"].stream.return_value[0].reference
    mock_firestore_db["batch"].delete.assert_any_call(expected_deleted_ref)

    mock_firestore_db["batch"].commit.assert_called_once()


async def test_add_chat_message_add_fails(mock_firestore_db):
    """
    Test add_chat_message when the Firestore add operation fails.
    """
    history_type = "lc"
    role = "user"
    content = "test"

    actual_collection_for_add = mock_firestore_db["document"].collection.return_value
    actual_collection_for_add.add.side_effect = Exception("Firestore add failed!")

    success = await gs.add_chat_message(TEST_USER_ID, role, content, history_type)
    assert success is False
    mock_firestore_db["batch"].commit.assert_not_called()


async def test_add_chat_message_trimming_commit_fails(mock_firestore_db):
    """
    Test add_chat_message when trimming is needed but batch commit fails.
    """
    history_type = "general"
    role = "user"
    content = f"message_{config.MAX_HISTORY_MESSAGES + 1}"

    messages_to_simulate = []
    for i in range(config.MAX_HISTORY_MESSAGES + 1):
        messages_to_simulate.append(
            (f"msg{i}", {"role": "user", "content": f"m{i}", "timestamp": 1700000000 + i})
        )
    mock_firestore_db["configure_query_stream_results"](messages_to_simulate)

    mock_firestore_db["batch"].commit.side_effect = Exception("Commit failed!")

    success = await gs.add_chat_message(TEST_USER_ID, role, content, history_type)
    assert success is False # Overall operation should fail if trimming fails

    # Add should have been called
    actual_collection_for_add = mock_firestore_db["document"].collection.return_value
    actual_collection_for_add.add.assert_called_once()
    # Delete should have been called on batch
    assert mock_firestore_db["batch"].delete.call_count > 0
    # Commit was called
    mock_firestore_db["batch"].commit.assert_called_once()

async def test_add_chat_message_unknown_type(mock_firestore_db):
    """
    Test add_chat_message with an unknown history type.
    """
    success = await gs.add_chat_message(TEST_USER_ID, "user", "content", "unknown_type")
    assert success is False
    actual_collection_for_add = mock_firestore_db["document"].collection.return_value
    actual_collection_for_add.add.assert_not_called()
    mock_firestore_db["batch"].commit.assert_not_called()
