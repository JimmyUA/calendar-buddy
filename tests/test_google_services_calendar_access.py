import unittest
from unittest.mock import patch, MagicMock, ANY
from google.cloud.firestore import SERVER_TIMESTAMP
from google.api_core.exceptions import NotFound

# Assuming google_services.py is in the parent directory or accessible via PYTHONPATH
import google_services as gs

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

    # --- Tests for get_user_id_by_username ---
    def test_get_user_id_by_username_exists(self):
        mock_doc = MagicMock()
        mock_doc.id = "test_user_id_123"
        self.mock_user_prefs_collection.where().limit().stream.return_value = [mock_doc]
        
        user_id = gs.get_user_id_by_username("testuser")
        
        self.mock_user_prefs_collection.where.assert_called_once_with(
            filter=gs.FieldFilter("telegram_username", "==", "testuser")
        )
        self.assertEqual(user_id, "test_user_id_123")

    def test_get_user_id_by_username_not_exists(self):
        self.mock_user_prefs_collection.where().limit().stream.return_value = []
        
        user_id = gs.get_user_id_by_username("nonexistentuser")
        
        self.mock_user_prefs_collection.where.assert_called_once_with(
            filter=gs.FieldFilter("telegram_username", "==", "nonexistentuser")
        )
        self.assertIsNone(user_id)

    def test_get_user_id_by_username_firestore_error(self):
        self.mock_user_prefs_collection.where().limit().stream.side_effect = Exception("Firestore unavailable")
        
        user_id = gs.get_user_id_by_username("testuser")
        
        self.assertIsNone(user_id)
        # Optionally, check log for error (requires more mock setup for logger)

    # --- Tests for add_calendar_access_request ---
    @patch('google_services.CalendarAccessRequest') # Mock the Pydantic model
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP) # Ensure it's the sentinel
    def test_add_calendar_access_request_success(self, mock_server_timestamp, MockCalendarAccessRequest):
        mock_request_model_instance = MagicMock()
        mock_request_model_instance.model_dump.return_value = {
            "requester_id": "req123", "requester_name": "Requester",
            "target_user_id": "target456", "start_time_iso": "start", "end_time_iso": "end",
            "status": "pending"
        }
        MockCalendarAccessRequest.return_value = mock_request_model_instance

        mock_doc_ref = MagicMock()
        mock_doc_ref.id = "new_request_id_789"
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_id = gs.add_calendar_access_request(
            requester_id="req123", requester_name="Requester", target_user_id="target456",
            start_time_iso="start", end_time_iso="end"
        )
        
        MockCalendarAccessRequest.assert_called_once_with(
            requester_id="req123", requester_name="Requester", target_user_id="target456",
            start_time_iso="start", end_time_iso="end", status="pending"
        )
        self.mock_calendar_access_requests_collection.document.assert_called_once_with() # Auto-generated ID
        mock_doc_ref.set.assert_called_once_with({
            "requester_id": "req123", "requester_name": "Requester",
            "target_user_id": "target456", "start_time_iso": "start", "end_time_iso": "end",
            "status": "pending", "request_timestamp": SERVER_TIMESTAMP
        })
        self.assertEqual(request_id, "new_request_id_789")

    @patch('google_services.CalendarAccessRequest')
    def test_add_calendar_access_request_firestore_error(self, MockCalendarAccessRequest):
        mock_request_model_instance = MagicMock()
        mock_request_model_instance.model_dump.return_value = {} # Doesn't matter for this test
        MockCalendarAccessRequest.return_value = mock_request_model_instance

        self.mock_calendar_access_requests_collection.document().set.side_effect = Exception("Firestore unavailable")
        
        request_id = gs.add_calendar_access_request(
            "r", "R", "t", "s", "e"
        )
        self.assertIsNone(request_id)

    # --- Tests for get_calendar_access_request ---
    def test_get_calendar_access_request_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {"requester_id": "req123", "status": "pending"}
        self.mock_calendar_access_requests_collection.document().get.return_value = mock_snapshot
        
        request_data = gs.get_calendar_access_request("req_id_abc")
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with("req_id_abc")
        self.assertEqual(request_data, {"requester_id": "req123", "status": "pending"})

    def test_get_calendar_access_request_not_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        self.mock_calendar_access_requests_collection.document().get.return_value = mock_snapshot
        
        request_data = gs.get_calendar_access_request("req_id_nonexistent")
        
        self.assertIsNone(request_data)

    def test_get_calendar_access_request_firestore_error(self):
        self.mock_calendar_access_requests_collection.document().get.side_effect = Exception("Firestore unavailable")
        
        request_data = gs.get_calendar_access_request("req_id_abc")
        
        self.assertIsNone(request_data)
        
    # --- Tests for update_calendar_access_request_status ---
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP)
    def test_update_calendar_access_request_status_success(self, mock_server_timestamp):
        mock_doc_ref = MagicMock()
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = gs.update_calendar_access_request_status("req_id_xyz", "approved")
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with("req_id_xyz")
        mock_doc_ref.update.assert_called_once_with({
            "status": "approved",
            "response_timestamp": SERVER_TIMESTAMP
        })
        self.assertTrue(success)

    def test_update_calendar_access_request_status_not_found(self):
        self.mock_calendar_access_requests_collection.document().update.side_effect = NotFound("Request not found")
        
        success = gs.update_calendar_access_request_status("req_id_nonexistent", "approved")
        
        self.assertFalse(success)

    def test_update_calendar_access_request_status_firestore_error(self):
        self.mock_calendar_access_requests_collection.document().update.side_effect = Exception("Firestore unavailable")
        
        success = gs.update_calendar_access_request_status("req_id_xyz", "approved")
        
        self.assertFalse(success)

if __name__ == '__main__':
    unittest.main()
