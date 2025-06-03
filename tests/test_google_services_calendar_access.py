import unittest
from unittest.mock import patch, MagicMock, ANY
from google.cloud.firestore import SERVER_TIMESTAMP
from google.api_core.exceptions import NotFound

# Assuming google_services.py is in the parent directory or accessible via PYTHONPATH
import google_services as gs
from .conftest import TEST_USER_ID # Import existing constants if needed

# Define constants for this test file
TEST_REQUESTER_ID_STR = "test_requester_user_123"
TEST_REQUESTER_NAME = "Test Requester Name"
TEST_TARGET_USER_ID_STR = "test_target_user_456"
TEST_REQUEST_DOC_ID = "test_firestore_req_doc_789"
MOCK_ISO_START_TIME = "2024-09-01T10:00:00Z"
MOCK_ISO_END_TIME = "2024-09-01T11:00:00Z"
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"


class TestCalendarAccessGoogleServices(unittest.TestCase):

    def setUp(self):
        # Mock the Firestore client and collections
        self.mock_db = MagicMock()
        gs.db = self.mock_db

        self.mock_user_prefs_collection = MagicMock()
        gs.USER_PREFS_COLLECTION = self.mock_user_prefs_collection

        self.mock_calendar_access_requests_collection = MagicMock()
        gs.CALENDAR_ACCESS_REQUESTS_COLLECTION = self.mock_calendar_access_requests_collection
        
        # Reset logger mock for each test if needed, or configure globally
        # For simplicity, we'll rely on patching where gs.logger is used if direct log checks are needed.

    # --- Tests for add_calendar_access_request ---
    @patch('google_services.CalendarAccessRequest') # Mock the Pydantic model
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP) # Ensure it's the sentinel
    async def test_add_calendar_access_request_success(self, mock_server_timestamp, MockCalendarAccessRequest):
        mock_request_model_instance = MagicMock()
        mock_request_model_instance.model_dump.return_value = {
            "requester_id": TEST_REQUESTER_ID_STR, "requester_name": TEST_REQUESTER_NAME,
            "target_user_id": TEST_TARGET_USER_ID_STR,
            "start_time_iso": MOCK_ISO_START_TIME, "end_time_iso": MOCK_ISO_END_TIME,
            "status": STATUS_PENDING
        }
        MockCalendarAccessRequest.return_value = mock_request_model_instance

        mock_doc_ref = MagicMock()
        mock_doc_ref.id = TEST_REQUEST_DOC_ID # Use defined constant
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        # Call the async function with await
        request_id = await gs.add_calendar_access_request(
            requester_id=TEST_REQUESTER_ID_STR,
            requester_name=TEST_REQUESTER_NAME,
            target_user_id=TEST_TARGET_USER_ID_STR,
            start_time_iso=MOCK_ISO_START_TIME,
            end_time_iso=MOCK_ISO_END_TIME
        )
        
        MockCalendarAccessRequest.assert_called_once_with(
            requester_id=TEST_REQUESTER_ID_STR,
            requester_name=TEST_REQUESTER_NAME,
            target_user_id=TEST_TARGET_USER_ID_STR,
            start_time_iso=MOCK_ISO_START_TIME,
            end_time_iso=MOCK_ISO_END_TIME,
            status=STATUS_PENDING
        )
        self.mock_calendar_access_requests_collection.document.assert_called_once_with() # Auto-generated ID
        mock_doc_ref.set.assert_called_once_with({
            "requester_id": TEST_REQUESTER_ID_STR, "requester_name": TEST_REQUESTER_NAME,
            "target_user_id": TEST_TARGET_USER_ID_STR,
            "start_time_iso": MOCK_ISO_START_TIME, "end_time_iso": MOCK_ISO_END_TIME,
            "status": STATUS_PENDING, "request_timestamp": SERVER_TIMESTAMP
        })
        self.assertEqual(request_id, TEST_REQUEST_DOC_ID)

    @patch('google_services.CalendarAccessRequest')
    async def test_add_calendar_access_request_firestore_error(self, MockCalendarAccessRequest):
        mock_request_model_instance = MagicMock()
        mock_request_model_instance.model_dump.return_value = {} # Doesn't matter for this test
        MockCalendarAccessRequest.return_value = mock_request_model_instance

        # Mock the set method on the document reference that would be called by asyncio.to_thread
        mock_doc_ref = MagicMock()
        mock_doc_ref.set.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        # Using less specific values here as the focus is on the exception
        request_id = await gs.add_calendar_access_request(
            TEST_REQUESTER_ID_STR, TEST_REQUESTER_NAME, TEST_TARGET_USER_ID_STR,
            MOCK_ISO_START_TIME, MOCK_ISO_END_TIME
        )
        self.assertIsNone(request_id)
        mock_doc_ref.set.assert_called_once() # Ensure the mocked method was reached

    @patch('google_services.CalendarAccessRequest')
    @patch('google_services.logger') # To check error logging
    async def test_add_calendar_access_request_pydantic_validation_error(self, mock_logger, MockCalendarAccessRequest):
        # Simulate Pydantic ValidationError when CalendarAccessRequest is instantiated
        # This happens if required fields are missing or types are wrong.
        # The function gs.add_calendar_access_request calls CalendarAccessRequest(...)
        # If this call fails, it should be caught by the try-except block.
        from pydantic import ValidationError # Import for raising the error
        mock_validation_error = ValidationError.from_exception_data(
            title="Test ValidationError",
            line_errors=[{'type': 'missing', 'loc': ('requester_id',), 'msg': 'Field required', 'input': {}}]
        )
        MockCalendarAccessRequest.side_effect = mock_validation_error

        mock_doc_set = self.mock_calendar_access_requests_collection.document.return_value.set

        request_id = await gs.add_calendar_access_request(
            requester_id=None, # Invalid input to trigger validation error
            requester_name=TEST_REQUESTER_NAME,
            target_user_id=TEST_TARGET_USER_ID_STR,
            start_time_iso=MOCK_ISO_START_TIME,
            end_time_iso=MOCK_ISO_END_TIME
        )

        self.assertIsNone(request_id)
        MockCalendarAccessRequest.assert_called_once() # Check it was attempted
        mock_doc_set.assert_not_called() # Firestore .set should not be called
        # Check that an error was logged
        mock_logger.error.assert_called_once()
        self.assertIn("Failed to add calendar access request", mock_logger.error.call_args[0][0])


    # --- Tests for get_calendar_access_request ---
    async def test_get_calendar_access_request_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        # Use constants for the mock data
        mock_data = {"requester_id": TEST_REQUESTER_ID_STR, "status": STATUS_PENDING}
        mock_snapshot.to_dict.return_value = mock_data
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = mock_snapshot
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request(TEST_REQUEST_DOC_ID) # Use constant
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with(TEST_REQUEST_DOC_ID)
        mock_doc_ref.get.assert_called_once()
        self.assertEqual(request_data, mock_data)

    async def test_get_calendar_access_request_not_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = mock_snapshot
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request("non_existent_doc_id") # Descriptive non-constant
        
        mock_doc_ref.get.assert_called_once()
        self.assertIsNone(request_data)

    async def test_get_calendar_access_request_firestore_error(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request(TEST_REQUEST_DOC_ID) # Use constant
        
        mock_doc_ref.get.assert_called_once()
        self.assertIsNone(request_data)
        
    # --- Tests for update_calendar_access_request_status ---
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP)
    async def test_update_calendar_access_request_status_success(self, mock_server_timestamp):
        mock_doc_ref = MagicMock()
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status(TEST_REQUEST_DOC_ID, STATUS_APPROVED) # Use constants
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with(TEST_REQUEST_DOC_ID)
        mock_doc_ref.update.assert_called_once_with({
            "status": STATUS_APPROVED,
            "response_timestamp": SERVER_TIMESTAMP
        })
        self.assertTrue(success)

    async def test_update_calendar_access_request_status_not_found(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.update.side_effect = NotFound("Request not found")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status("non_existent_doc_id", STATUS_APPROVED) # Descriptive
        
        mock_doc_ref.update.assert_called_once()
        self.assertFalse(success)

    async def test_update_calendar_access_request_status_firestore_error(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.update.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status(TEST_REQUEST_DOC_ID, STATUS_APPROVED) # Use constants
        
        self.assertFalse(success)

if __name__ == '__main__':
    unittest.main()
