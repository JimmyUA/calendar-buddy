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


class GroceryShareRequest(BaseModel):
    """Represents a request to share grocery lists between users."""

    requester_id: str
    requester_name: str
    target_user_id: str
    status: str = "pending"
    request_timestamp: Any = None
    response_timestamp: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

if __name__ == '__main__':
    # Example usage:
    # This is just for demonstration and won't be part of the actual application logic
    # In a real scenario, request_timestamp would be set by Firestore upon creation.

    # Creating a new request (client-side, before sending to Firestore)
    new_request_data = {
        "requester_id": "user123",
        "requester_name": "Alice",
        "target_user_id": "user456",
        "start_time_iso": "2024-07-30T10:00:00Z",
        "end_time_iso": "2024-07-30T12:00:00Z",
        # status defaults to "pending"
        # request_timestamp would be set by Firestore
    }
    request_obj = CalendarAccessRequest(**new_request_data)
    print("New Request (Client-side):")
    print(request_obj.model_dump_json(indent=2))

    # Simulating a request retrieved from Firestore (after it's been created)
    # In this case, request_timestamp would be a Firestore Timestamp object
    # For this example, we'll use a string to represent it.
    retrieved_request_data = {
        **new_request_data,
        "status": "pending",
        "request_timestamp": "2024-07-28T10:00:00.000Z" # Example Firestore timestamp
    }
    retrieved_request_obj = CalendarAccessRequest(**retrieved_request_data)
    print("\nRetrieved Request (Simulated from Firestore):")
    print(retrieved_request_obj.model_dump_json(indent=2))

    # Simulating an approved request
    approved_request_data = {
        **retrieved_request_data,
        "status": "approved",
        "response_timestamp": "2024-07-28T10:05:00.000Z" # Example Firestore timestamp
    }
    approved_request_obj = CalendarAccessRequest(**approved_request_data)
    print("\nApproved Request (Simulated from Firestore):")
    print(approved_request_obj.model_dump_json(indent=2))

    # Demonstrating how to prepare data for Firestore, including SERVER_TIMESTAMP
    # For a new request:
    data_to_store_new = request_obj.model_dump(exclude_none=True)
    data_to_store_new['request_timestamp'] = SERVER_TIMESTAMP # Actual server timestamp
    # response_timestamp is not set yet

    print("\nData to store (New Request) in Firestore:")
    print(data_to_store_new)


    # For updating a request (e.g., approving it):
    update_data = {
        "status": "approved",
        "response_timestamp": SERVER_TIMESTAMP # Actual server timestamp
    }
    print("\nData to update (Approve Request) in Firestore:")
    print(update_data)
