import unittest
from pydantic import ValidationError
from google.cloud.firestore import SERVER_TIMESTAMP

from models import GroceryList, GroceryListShareRequest

class TestGroceryModels(unittest.TestCase):

    def test_grocery_list_instantiation_defaults(self):
        """Test GroceryList model with default values."""
        list_data = {"owner_id": "user123"}
        gl = GroceryList(**list_data)
        self.assertEqual(gl.owner_id, "user123")
        self.assertEqual(gl.items, [])
        self.assertEqual(gl.shared_with, [])
        self.assertIsNone(gl.created_at) # Default before Firestore sets it
        self.assertIsNone(gl.updated_at)

    def test_grocery_list_instantiation_with_values(self):
        """Test GroceryList model with provided values."""
        list_data = {
            "owner_id": "user456",
            "items": ["milk", "eggs"],
            "shared_with": ["user789"],
            "created_at": "2024-01-01T00:00:00Z", # Example, though usually SERVER_TIMESTAMP
            "updated_at": "2024-01-02T00:00:00Z"
        }
        gl = GroceryList(**list_data)
        self.assertEqual(gl.owner_id, "user456")
        self.assertEqual(gl.items, ["milk", "eggs"])
        self.assertEqual(gl.shared_with, ["user789"])
        self.assertEqual(gl.created_at, "2024-01-01T00:00:00Z")
        self.assertEqual(gl.updated_at, "2024-01-02T00:00:00Z")

    def test_grocery_list_pydantic_validation(self):
        """Test GroceryList Pydantic validation for field types."""
        # Example: owner_id should be a string
        with self.assertRaises(ValidationError):
            GroceryList(owner_id=123) # Invalid type for owner_id
        
        # Example: items should be a list of strings
        with self.assertRaises(ValidationError):
            GroceryList(owner_id="user123", items=["apple", 123]) # Invalid item type in list

    def test_grocery_list_server_timestamp_usage(self):
        """Test preparing data for Firestore with SERVER_TIMESTAMP."""
        gl = GroceryList(owner_id="user123")
        data_to_store = gl.model_dump(exclude_none=True)
        data_to_store['created_at'] = SERVER_TIMESTAMP
        data_to_store['updated_at'] = SERVER_TIMESTAMP
        
        self.assertEqual(data_to_store['created_at'], SERVER_TIMESTAMP)
        self.assertEqual(data_to_store['updated_at'], SERVER_TIMESTAMP)

    def test_grocery_list_share_request_instantiation_defaults(self):
        """Test GroceryListShareRequest model with default values."""
        request_data = {
            "requester_id": "userABC",
            "requester_name": "Alice",
            "target_user_id": "userXYZ",
            "list_id": "list123"
        }
        gsr = GroceryListShareRequest(**request_data)
        self.assertEqual(gsr.requester_id, "userABC")
        self.assertEqual(gsr.requester_name, "Alice")
        self.assertEqual(gsr.target_user_id, "userXYZ")
        self.assertEqual(gsr.list_id, "list123")
        self.assertEqual(gsr.status, "pending") # Default status
        self.assertIsNone(gsr.request_timestamp)
        self.assertIsNone(gsr.response_timestamp)

    def test_grocery_list_share_request_instantiation_with_values(self):
        """Test GroceryListShareRequest model with provided values."""
        request_data = {
            "requester_id": "userABC",
            "requester_name": "Alice",
            "target_user_id": "userXYZ",
            "list_id": "list123",
            "status": "approved",
            "request_timestamp": "2024-01-03T00:00:00Z",
            "response_timestamp": "2024-01-04T00:00:00Z"
        }
        gsr = GroceryListShareRequest(**request_data)
        self.assertEqual(gsr.status, "approved")
        self.assertEqual(gsr.request_timestamp, "2024-01-03T00:00:00Z")
        self.assertEqual(gsr.response_timestamp, "2024-01-04T00:00:00Z")

    def test_grocery_list_share_request_pydantic_validation(self):
        """Test GroceryListShareRequest Pydantic validation."""
        # Example: requester_id is required
        with self.assertRaises(ValidationError):
            GroceryListShareRequest(
                requester_name="Bob", 
                target_user_id="userDEF", 
                list_id="list456"
            )
        
        # Example: status should be a string
        with self.assertRaises(ValidationError):
            GroceryListShareRequest(
                requester_id="user1",
                requester_name="Charlie",
                target_user_id="user2",
                list_id="list789",
                status=123 # Invalid type for status
            )

    def test_grocery_list_share_request_server_timestamp_usage(self):
        """Test preparing share request data for Firestore with SERVER_TIMESTAMP."""
        gsr = GroceryListShareRequest(
            requester_id="user1",
            requester_name="David",
            target_user_id="user2",
            list_id="listABC"
        )
        data_to_store = gsr.model_dump(exclude_none=True)
        data_to_store['request_timestamp'] = SERVER_TIMESTAMP
        # response_timestamp might be set later
        
        self.assertEqual(data_to_store['request_timestamp'], SERVER_TIMESTAMP)

if __name__ == '__main__':
    unittest.main()
