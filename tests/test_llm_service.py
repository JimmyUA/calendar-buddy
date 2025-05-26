import pytest
from unittest.mock import AsyncMock, patch
import json # For parsing mock LLM responses if they are strings

from llm import llm_service # Import the module to be tested

# Define sample inputs
SAMPLE_USER_REQUEST_FOR_SEARCH_EXTRACTION = "Reschedule my meeting with Bob from 3pm today to 4pm and change location to Main Hall."
SAMPLE_CURRENT_TIME_ISO = "2024-03-15T10:00:00-04:00"

SAMPLE_NATURAL_LANGUAGE_CHANGES = "Change summary to 'Updated Meeting Title' and move it to tomorrow 4pm."
SAMPLE_ORIGINAL_EVENT_DETAILS = {
    "id": "event123",
    "summary": "Original Meeting Title",
    "start": {"dateTime": "2024-03-15T15:00:00-04:00", "timeZone": "America/New_York"},
    "end": {"dateTime": "2024-03-15T16:00:00-04:00", "timeZone": "America/New_York"},
    "description": "Initial description",
    "location": "Old Location"
}
SAMPLE_USER_TIMEZONE_STR = "America/New_York"


@pytest.mark.asyncio
# The patch target must be where the object is *looked up*,
# which is in the llm.llm_service module.
@patch('llm.llm_service.gemini_model', new_callable=AsyncMock) # Adjust if a different client is used directly
async def test_extract_update_search_and_changes_success(mock_gemini_model_instance):
    # Mock the response from the underlying LLM call (gemini_model.generate_content_async)
    # This mock should simulate what _parse_llm_json_output would return after processing LLM output
    
    # The functions extract_update_search_and_changes and extract_calendar_update_details_llm
    # internally call _parse_llm_json_output(response.text).
    # So, we need to mock response.text that _parse_llm_json_output can handle.
    # The mock_gemini_model_instance is the mock for the `gemini_model` object itself.
    # We need to configure its method `generate_content_async` to return an object
    # that has a `text` attribute, and potentially a `prompt_feedback` attribute.

    mock_response_obj = AsyncMock() # This will be the return value of generate_content_async
    mock_response_obj.prompt_feedback = None # Simulate no blocking
    
    mock_llm_json_output_str = json.dumps({
        "search_query": "meeting with Bob 3pm today",
        "changes_description": "Reschedule to 4pm and change location to Main Hall",
        "search_start_iso": "2024-03-15T00:00:00-04:00",
        "search_end_iso": "2024-03-15T23:59:59-04:00"
    })
    mock_response_obj.text = mock_llm_json_output_str
    mock_gemini_model_instance.generate_content_async.return_value = mock_response_obj

    result = await llm_service.extract_update_search_and_changes(
        SAMPLE_USER_REQUEST_FOR_SEARCH_EXTRACTION,
        SAMPLE_CURRENT_TIME_ISO
    )

    assert result is not None
    assert result["search_query"] == "meeting with Bob 3pm today"
    assert result["changes_description"] == "Reschedule to 4pm and change location to Main Hall"
    assert result["search_start_iso"] is not None
    mock_gemini_model_instance.generate_content_async.assert_called_once() # Verify LLM was called


@pytest.mark.asyncio
@patch('llm.llm_service.gemini_model', new_callable=AsyncMock)
async def test_extract_update_search_and_changes_llm_failure(mock_gemini_model_instance):
    # Simulate LLM call itself failing or returning a response that leads to None
    # For example, if response.text is missing or _parse_llm_json_output returns None
    mock_response_obj = AsyncMock()
    mock_response_obj.prompt_feedback = None
    mock_response_obj.text = "This is not valid JSON" # _parse_llm_json_output will return None
    mock_gemini_model_instance.generate_content_async.return_value = mock_response_obj
    # Alternative: mock_gemini_model_instance.generate_content_async.side_effect = Exception("LLM API Error")
    # or mock _parse_llm_json_output directly if its failure is what we want to test

    result = await llm_service.extract_update_search_and_changes(
        SAMPLE_USER_REQUEST_FOR_SEARCH_EXTRACTION,
        SAMPLE_CURRENT_TIME_ISO
    )
    assert result is None


@pytest.mark.asyncio
@patch('llm.llm_service.gemini_model', new_callable=AsyncMock)
async def test_extract_calendar_update_details_llm_success(mock_gemini_model_instance):
    mock_response_obj = AsyncMock()
    mock_response_obj.prompt_feedback = None
    mock_llm_json_output_str = json.dumps({
        "summary": "Updated Meeting Title",
        "start": {"dateTime": "2024-03-16T16:00:00-04:00", "timeZone": SAMPLE_USER_TIMEZONE_STR},
        "end": {"dateTime": "2024-03-16T17:00:00-04:00", "timeZone": SAMPLE_USER_TIMEZONE_STR}
    })
    mock_response_obj.text = mock_llm_json_output_str
    mock_gemini_model_instance.generate_content_async.return_value = mock_response_obj

    result = await llm_service.extract_calendar_update_details_llm(
        SAMPLE_NATURAL_LANGUAGE_CHANGES,
        SAMPLE_ORIGINAL_EVENT_DETAILS,
        SAMPLE_CURRENT_TIME_ISO,
        SAMPLE_USER_TIMEZONE_STR
    )

    assert result is not None
    assert result["summary"] == "Updated Meeting Title"
    assert "start" in result
    assert result["start"]["dateTime"] == "2024-03-16T16:00:00-04:00"
    assert result["start"]["timeZone"] == SAMPLE_USER_TIMEZONE_STR
    mock_gemini_model_instance.generate_content_async.assert_called_once()


@pytest.mark.asyncio
@patch('llm.llm_service.gemini_model', new_callable=AsyncMock)
async def test_extract_calendar_update_details_llm_failure(mock_gemini_model_instance):
    mock_response_obj = AsyncMock()
    mock_response_obj.prompt_feedback = None
    mock_response_obj.text = "Invalid JSON to cause _parse_llm_json_output to return None"
    mock_gemini_model_instance.generate_content_async.return_value = mock_response_obj

    result = await llm_service.extract_calendar_update_details_llm(
        SAMPLE_NATURAL_LANGUAGE_CHANGES,
        SAMPLE_ORIGINAL_EVENT_DETAILS,
        SAMPLE_CURRENT_TIME_ISO,
        SAMPLE_USER_TIMEZONE_STR
    )
    assert result is None

@pytest.mark.asyncio
@patch('llm.llm_service.gemini_model', new_callable=AsyncMock)
async def test_extract_calendar_update_details_llm_adds_timezone_if_missing(mock_gemini_model_instance):
    mock_response_obj = AsyncMock()
    mock_response_obj.prompt_feedback = None
    # Simulate LLM returning start/end without timeZone, but with dateTime
    mock_llm_json_output_str = json.dumps({
        "start": {"dateTime": "2024-03-16T16:00:00-04:00"} # Missing timeZone
    })
    mock_response_obj.text = mock_llm_json_output_str
    mock_gemini_model_instance.generate_content_async.return_value = mock_response_obj
    
    result = await llm_service.extract_calendar_update_details_llm(
        "Move to tomorrow 4pm",
        SAMPLE_ORIGINAL_EVENT_DETAILS,
        SAMPLE_CURRENT_TIME_ISO,
        SAMPLE_USER_TIMEZONE_STR
    )

    assert result is not None
    assert "start" in result
    assert result["start"]["dateTime"] == "2024-03-16T16:00:00-04:00"
    # Check if the function added the timezone as per its internal logic
    assert result["start"]["timeZone"] == SAMPLE_USER_TIMEZONE_STR

# Add more tests:
# - Cases where LLM returns malformed JSON or unexpected structure for each function.
#   (Covered by _llm_failure tests if _parse_llm_json_output returns None on bad JSON)
# - Different types of natural language inputs to ensure prompts are robust.
# - For extract_calendar_update_details_llm:
#   - Relative time changes (e.g., "delay by 1 hour").
#   - Changes to all-day events.
#   - Clearing fields (e.g., "remove description").
#   - Only changing one field vs. multiple.
# - Test for prompt_feedback.block_reason being set.
# - Test for response having no 'text' attribute.
# - Test for specific validation failures inside the functions, e.g. invalid ISO strings returned by LLM.
# - For extract_update_search_and_changes:
#   - Test when search_start_iso is null and when it's present.
#   - Test validation of start_iso without end_iso.
# - For extract_calendar_update_details_llm:
#   - Test validation of all-day event 'date' field.
#   - Test when 'start' or 'end' is a dict but lacks 'dateTime' or 'date'.
#   - Test when 'start' or 'end' is not a dict.
#   - Test when response_data is empty after parsing.
```
