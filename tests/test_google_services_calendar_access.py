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

    # --- Tests for add_calendar_access_request ---
    @patch('google_services.CalendarAccessRequest') # Mock the Pydantic model
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP) # Ensure it's the sentinel
    async def test_add_calendar_access_request_success(self, mock_server_timestamp, MockCalendarAccessRequest):
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
        
        # Call the async function with await
        request_id = await gs.add_calendar_access_request(
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
    async def test_add_calendar_access_request_firestore_error(self, MockCalendarAccessRequest):
        mock_request_model_instance = MagicMock()
        mock_request_model_instance.model_dump.return_value = {} # Doesn't matter for this test
        MockCalendarAccessRequest.return_value = mock_request_model_instance

        # Mock the set method on the document reference that would be called by asyncio.to_thread
        mock_doc_ref = MagicMock()
        mock_doc_ref.set.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_id = await gs.add_calendar_access_request(
            "r", "R", "t", "s", "e"
        )
        self.assertIsNone(request_id)
        mock_doc_ref.set.assert_called_once() # Ensure the mocked method was reached

    # --- Tests for get_calendar_access_request ---
    async def test_get_calendar_access_request_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = True
        mock_snapshot.to_dict.return_value = {"requester_id": "req123", "status": "pending"}
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = mock_snapshot # Mock the sync method called by to_thread
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request("req_id_abc")
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with("req_id_abc")
        mock_doc_ref.get.assert_called_once()
        self.assertEqual(request_data, {"requester_id": "req123", "status": "pending"})

    async def test_get_calendar_access_request_not_exists(self):
        mock_snapshot = MagicMock()
        mock_snapshot.exists = False
        
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = mock_snapshot
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request("req_id_nonexistent")
        
        mock_doc_ref.get.assert_called_once()
        self.assertIsNone(request_data)

    async def test_get_calendar_access_request_firestore_error(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        request_data = await gs.get_calendar_access_request("req_id_abc")
        
        mock_doc_ref.get.assert_called_once()
        self.assertIsNone(request_data)
        
    # --- Tests for update_calendar_access_request_status ---
    @patch('google_services.firestore.SERVER_TIMESTAMP', new_callable=lambda: SERVER_TIMESTAMP)
    async def test_update_calendar_access_request_status_success(self, mock_server_timestamp):
        mock_doc_ref = MagicMock()
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status("req_id_xyz", "approved")
        
        self.mock_calendar_access_requests_collection.document.assert_called_once_with("req_id_xyz")
        mock_doc_ref.update.assert_called_once_with({
            "status": "approved",
            "response_timestamp": SERVER_TIMESTAMP
        })
        self.assertTrue(success)

    async def test_update_calendar_access_request_status_not_found(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.update.side_effect = NotFound("Request not found")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status("req_id_nonexistent", "approved")
        
        mock_doc_ref.update.assert_called_once()
        self.assertFalse(success)

    async def test_update_calendar_access_request_status_firestore_error(self):
        mock_doc_ref = MagicMock()
        mock_doc_ref.update.side_effect = Exception("Firestore unavailable")
        self.mock_calendar_access_requests_collection.document.return_value = mock_doc_ref
        
        success = await gs.update_calendar_access_request_status("req_id_xyz", "approved")
        
        self.assertFalse(success)

if __name__ == '__main__':
    unittest.main()
