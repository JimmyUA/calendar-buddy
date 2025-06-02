from typing import Optional, Any
from pydantic import BaseModel
from google.cloud.firestore import SERVER_TIMESTAMP

class CalendarAccessRequest(BaseModel):
    """
    Represents a request for accessing another user's calendar.
    """
    requester_id: str
    requester_name: str # Name of the user requesting access
    target_user_id: str # User ID of the calendar owner
    start_time_iso: str # ISO 8601 format
    end_time_iso: str   # ISO 8601 format
    status: str = "pending"  # e.g., "pending", "approved", "denied", "expired"

    # Timestamps:
    # `request_timestamp` will be set to Firestore.SERVER_TIMESTAMP when the document is created.
    # `response_timestamp` will be set to Firestore.SERVER_TIMESTAMP when the request is responded to.
    request_timestamp: Any = None # Placeholder for Firestore.SERVER_TIMESTAMP
    response_timestamp: Optional[Any] = None # Placeholder for Firestore.SERVER_TIMESTAMP

    class Config:
        # Allow Firestore SERVER_TIMESTAMP to be used
        arbitrary_types_allowed = True

# Removed the duplicated __main__ block that was here.

class GroceryList(BaseModel):
    """
    Represents a grocery list.
    """
    owner_id: str  # ID of the user who owns the list
    shared_with: list[str] = []  # IDs of users with whom the list is shared
    items: list[str] = []  # Grocery items
    created_at: Any = None  # Placeholder for Firestore.SERVER_TIMESTAMP
    updated_at: Any = None  # Placeholder for Firestore.SERVER_TIMESTAMP

    class Config:
        arbitrary_types_allowed = True


class GroceryListShareRequest(BaseModel):
    """
    Represents a request to share a grocery list.
    """
    requester_id: str  # ID of the user requesting to share
    requester_name: str  # Name of the user requesting to share
    target_user_id: str  # ID of the user being asked to share
    list_id: str  # ID of the grocery list to be shared
    status: str = "pending"  # e.g., "pending", "approved", "denied"
    request_timestamp: Any = None  # Placeholder for Firestore.SERVER_TIMESTAMP
    response_timestamp: Optional[Any] = None  # Placeholder for Firestore.SERVER_TIMESTAMP

    class Config:
        arbitrary_types_allowed = True


if __name__ == '__main__':
    # --- Existing CalendarAccessRequest Example Usage ---
    # This section demonstrates usage of the CalendarAccessRequest model.

    # Creating a new CalendarAccessRequest (client-side, before sending to Firestore)
    new_calendar_request_data = {
        "requester_id": "user123",
        "requester_name": "Alice",
        "target_user_id": "user456",
        "start_time_iso": "2024-07-30T10:00:00Z",
        "end_time_iso": "2024-07-30T12:00:00Z",
        # status defaults to "pending"
        # request_timestamp would be set by Firestore
    }
    calendar_request_obj = CalendarAccessRequest(**new_calendar_request_data) # Changed from request_obj to avoid collision
    print("New CalendarAccessRequest (Client-side):") # Clarified print output
    print(calendar_request_obj.model_dump_json(indent=2))

    # Simulating a CalendarAccessRequest retrieved from Firestore
    retrieved_calendar_request_data = {
        **new_calendar_request_data,
        "status": "pending",
        "request_timestamp": "2024-07-28T10:00:00.000Z" # Example Firestore timestamp
    }
    retrieved_calendar_request_obj = CalendarAccessRequest(**retrieved_calendar_request_data)
    print("\nRetrieved CalendarAccessRequest (Simulated from Firestore):") # Clarified print output
    print(retrieved_calendar_request_obj.model_dump_json(indent=2))

    # Simulating an approved CalendarAccessRequest
    approved_calendar_request_data = {
        **retrieved_calendar_request_data,
        "status": "approved",
        "response_timestamp": "2024-07-28T10:05:00.000Z" # Example Firestore timestamp
    }
    approved_calendar_request_obj = CalendarAccessRequest(**approved_calendar_request_data)
    print("\nApproved CalendarAccessRequest (Simulated from Firestore):") # Clarified print output
    print(approved_calendar_request_obj.model_dump_json(indent=2))

    # Data to store for a new CalendarAccessRequest in Firestore
    data_to_store_new_calendar_request = calendar_request_obj.model_dump(exclude_none=True)
    data_to_store_new_calendar_request['request_timestamp'] = SERVER_TIMESTAMP
    # response_timestamp is not set yet
    print("\nData to store (New CalendarAccessRequest) in Firestore:") # Clarified print output
    print(data_to_store_new_calendar_request)

    # Data to update for an existing CalendarAccessRequest in Firestore (e.g., approving it)
    update_calendar_data = {
        "status": "approved",
        "response_timestamp": SERVER_TIMESTAMP
    }
    print("\nData to update (Approve CalendarAccessRequest) in Firestore:") # Clarified print output
    print(update_calendar_data)

    print("\n" + "="*50 + "\n") # Separator

    # --- New GroceryList and GroceryListShareRequest Example Usage ---

    # Example usage for GroceryList:

    # Creating a new grocery list (client-side)
    new_list_data = {
        "owner_id": "user789",
        "items": ["Milk", "Eggs", "Bread"]
    }
    grocery_list_obj = GroceryList(**new_list_data)
    print("\nNew Grocery List (Client-side):")
    print(grocery_list_obj.model_dump_json(indent=2))

    # Data to store for a new grocery list in Firestore
    data_to_store_new_list = grocery_list_obj.model_dump(exclude_none=True)
    data_to_store_new_list['created_at'] = SERVER_TIMESTAMP
    data_to_store_new_list['updated_at'] = SERVER_TIMESTAMP
    print("\nData to store (New Grocery List) in Firestore:")
    print(data_to_store_new_list)

    # Simulating updating an existing grocery list
    # (e.g., adding an item and sharing with a user)
    updated_list_data = {
        "items": grocery_list_obj.items + ["Cheese"], # Add "Cheese"
        "shared_with": grocery_list_obj.shared_with + ["userABC"] # Share with "userABC"
    }
    # In a real update, you would typically only send the fields that changed.
    # For Firestore, this would be:
    update_fields_for_list = {
        "items": updated_list_data["items"],
        "shared_with": updated_list_data["shared_with"],
        "updated_at": SERVER_TIMESTAMP
    }
    print("\nData to update (Existing Grocery List) in Firestore:")
    print(update_fields_for_list)


    # Example usage for GroceryListShareRequest:

    # Creating a new share request (client-side)
    new_share_request_data = {
        "requester_id": "user123",
        "requester_name": "Bob",
        "target_user_id": "user789", # Owner of the grocery list
        "list_id": "listXYZ" # ID of the grocery list Bob wants access to
    }
    share_request_obj = GroceryListShareRequest(**new_share_request_data)
    print("\nNew Share Request (Client-side):")
    print(share_request_obj.model_dump_json(indent=2))

    # Data to store for a new share request in Firestore
    data_to_store_new_share_request = share_request_obj.model_dump(exclude_none=True)
    data_to_store_new_share_request['request_timestamp'] = SERVER_TIMESTAMP
    print("\nData to store (New Share Request) in Firestore:")
    print(data_to_store_new_share_request)

    # Simulating approving a share request
    approve_share_data = {
        "status": "approved",
        "response_timestamp": SERVER_TIMESTAMP
    }
    print("\nData to update (Approve Share Request) in Firestore:")
    print(approve_share_data)
