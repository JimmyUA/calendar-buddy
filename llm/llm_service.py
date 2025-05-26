# llm_service.py
import logging
import json
import ast
from datetime import datetime, timezone

# Google AI specific imports
import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

# Date parsing library (needed for formatting dates within prompts)
from dateutil import parser as dateutil_parser

import config # For API Key

logger = logging.getLogger(__name__)

# --- Google Gemini Setup ---
gemini_model = None
llm_available = False
if config.GOOGLE_API_KEY:
    try:
        genai.configure(api_key=config.GOOGLE_API_KEY)
        # Add safety settings or other generation configs if needed
        # safety_settings = [...]
        # generation_config=genai.types.GenerationConfig(temperature=0.7)
        gemini_model = genai.GenerativeModel(
            'gemini-1.5-flash', # Or specify your preferred model
            # generation_config=generation_config,
            # safety_settings=safety_settings
            )
        # Optional quick test call (can be commented out)
        # gemini_model.generate_content("test", generation_config=genai.types.GenerationConfig(max_output_tokens=5))
        llm_available = True
        logger.info("LLM Service: Google Generative AI configured successfully.")
    except Exception as e:
        logger.error(f"LLM Service: Failed to configure Google Generative AI: {e}", exc_info=True)
else:
    logger.warning("LLM Service: Google API Key not found. LLM features disabled.")


# === LLM Interaction Functions ===

async def get_chat_response(history: list[dict]) -> str | None:
    """
    Gets a general chat response from the LLM, considering conversation history.

    Args:
        history: A list of message dictionaries, e.g.,
                 [{'role': 'user', 'parts': [Part(text="Hi")]},
                  {'role': 'model', 'parts': [Part(text="Hello!")]}]

    Returns:
        The LLM's response text string or None on error/block.
    """
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Chat): LLM not available.")
        return None
    if not history:
        logger.warning("LLM Service (Chat): Received empty history.")
        return None # Cannot generate response without input

    # Ensure history format is suitable for Gemini API (list of Content objects or dicts)
    # The format using 'parts' is more robust for potential future multi-modal inputs.
    # Convert simple {'role': '...', 'content': '...'} to the required format if needed,
    # but handlers.py will now create it in the correct format directly.
    formatted_history = []
    for msg in history:
        role = msg.get('role')
        content = msg.get('content') # Assume handlers.py provides this structure for now
        if role and content:
             # Ensure parts is a list containing one Part object with the text
            formatted_history.append({'role': role, 'parts': [content]}) # Use genai.Part here
        else:
            logger.warning(f"LLM Service (Chat): Skipping invalid history item: {msg}")


    if not formatted_history:
        logger.error("LLM Service (Chat): History became empty after formatting.")
        return None

    try:
        logger.debug(f"LLM Chat Request History (last 2 items): {formatted_history[-2:]}")
        # Pass the history directly to generate_content_async
        response = await gemini_model.generate_content_async(
            formatted_history,
            # Optional: Add safety settings, generation config here if needed
            # safety_settings=...,
            # generation_config=...
            )

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM chat response blocked: {response.prompt_feedback.block_reason}")
             return None

        # Extract text carefully
        try:
            # Accessing response.text directly might raise ValueError if blocked/empty
            return response.text
        except ValueError as e:
             # Sometimes .text fails but parts might exist
             logger.warning(f"LLM chat response .text failed ('{e}'), trying parts.")
             if hasattr(response, 'parts') and response.parts:
                 return "".join(part.text for part in response.parts if hasattr(part, 'text'))
             else:
                 logger.error(f"LLM chat response missing text and parts after ValueError. Full response: {response}")
                 return None


    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Chat): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLM Service (Chat): Unexpected error - {e}", exc_info=True)
        return None


async def classify_intent_and_extract_params(text: str, current_time_iso: str) -> dict | None:
    """
    Uses LLM (Gemini) to classify user intent and extract relevant parameters.
    Requires user's current time. Handles both strict JSON and Python dict literal responses.

    Intents: CALENDAR_SUMMARY, CALENDAR_CREATE, CALENDAR_DELETE, GENERAL_CHAT
    """
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Intent): LLM not available.")
        return None

    # Use the provided current_time_iso in the prompt
    prompt = f"""
    Analyze the user's message based on the user's current time being {current_time_iso}.
    Classify the user's primary intent into one of these categories:
    CALENDAR_SUMMARY, CALENDAR_CREATE, CALENDAR_DELETE, GENERAL_CHAT

    Extract relevant parameters based on the intent:
    - CALENDAR_SUMMARY: {{"time_period": "extracted period like 'today', 'next week'"}}
    - CALENDAR_CREATE: {{"event_description": "extracted full description for event creation"}}
    - CALENDAR_DELETE: {{"event_description": "extracted description identifying the event to delete"}}
    - GENERAL_CHAT: {{}}

    Respond ONLY with a JSON object containing 'intent' (string) and 'parameters' (object). Ensure keys and string values use double quotes for strict JSON compatibility.

    User Message: "{text}"

    JSON Output:
    """
    try:
        logger.debug(f"LLM Intent Request: '{text[:100]}...'")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM intent classification blocked: {response.prompt_feedback.block_reason}")
             return None
        if not hasattr(response, 'text'):
             logger.warning("LLM response for intent classification missing 'text'.")
             return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"LLM Intent Raw Output: {cleaned_text}")

        intent_data = None
        try:
            # Attempt strict JSON parsing first
            intent_data = json.loads(cleaned_text)
            logger.debug("LLM Intent: Parsed successfully using json.loads.")
        except json.JSONDecodeError as json_err:
            logger.warning(f"LLM Intent JSON Parse Error: {json_err}. Trying ast.literal_eval...")
            try:
                # Fallback: Try parsing as a Python literal
                intent_data = ast.literal_eval(cleaned_text)
                logger.debug("LLM Intent: Parsed successfully using ast.literal_eval.")
                # Basic type check after literal_eval
                if not isinstance(intent_data, dict):
                    logger.error(f"LLM Intent ast.literal_eval did not yield a dict. Type: {type(intent_data)}. Raw: {cleaned_text}")
                    return None
            except (ValueError, SyntaxError, TypeError) as eval_err:
                # Both JSON and literal parsing failed
                logger.error(f"LLM Intent JSON and literal parsing failed: {eval_err}. Raw: {cleaned_text}")
                return None

        # --- Validation (applied to intent_data obtained from either method) ---
        if not intent_data:
            logger.error("Intent data is unexpectedly None after parsing attempts.")
            return None

        if 'intent' not in intent_data or 'parameters' not in intent_data:
             logger.error(f"LLM Intent structure invalid after parsing: {intent_data}")
             return None # Treat bad structure as failure

        valid_intents = ["CALENDAR_SUMMARY", "CALENDAR_CREATE", "CALENDAR_DELETE", "GENERAL_CHAT"]
        intent_val = intent_data.get('intent')
        params = intent_data.get('parameters', {}) # Ensure params is at least an empty dict

        # Ensure parameters is a dictionary
        if not isinstance(params, dict):
             logger.warning(f"LLM Intent parameters field is not a dict: {params}. Defaulting params to {{}}.")
             params = {}
             intent_data['parameters'] = {} # Correct the data structure

        if intent_val not in valid_intents:
            logger.warning(f"LLM returned unknown intent '{intent_val}'. Defaulting to GENERAL_CHAT.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
            intent_val = 'GENERAL_CHAT' # Update local variable too

        # Validate presence of required parameters for specific intents
        if intent_val == "CALENDAR_SUMMARY" and not params.get("time_period"):
            logger.warning(f"LLM SUMMARY intent missing time_period parameter.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}} # Revert to chat if essential param missing
        elif intent_val == "CALENDAR_CREATE" and not params.get("event_description"):
            logger.warning(f"LLM CREATE intent missing event_description parameter.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        elif intent_val == "CALENDAR_DELETE" and not params.get("event_description"):
            logger.warning(f"LLM DELETE intent missing event_description parameter.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        # --- End Validation ---

        logger.info(f"LLM Intent Result: {intent_data.get('intent')}, Params: {intent_data.get('parameters')}")
        return intent_data # Return the potentially modified intent_data

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Intent): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        # Catch any other exceptions during API call or processing
        logger.error(f"LLM Service (Intent): Unexpected error - {e}", exc_info=True)
        return None

async def parse_date_range_llm(text_period: str, current_time_iso: str) -> dict | None:
    """Uses LLM to parse time period. Requires user's current time."""
    if not llm_available or not gemini_model: logger.error(...); return None

    # Use the provided current_time_iso
    prompt = f"""
    Analyze the time period description relative to user's current time ({current_time_iso}).
    Determine precise start/end datetime. Assume standard interpretations (...).
    Output JSON: {{"start_iso": "ISO8601", "end_iso": "ISO8601"}} (Use offset/Z)

    Time Period: "{text_period}"
    JSON Output:
    """
    try:
        logger.debug(f"LLM Date Range Request: '{text_period}'")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(f"LLM date range parsing blocked: {response.prompt_feedback.block_reason}"); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for date range parsing missing 'text'."); return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"LLM Date Range Raw Output: {cleaned_text}")
        try:
            parsed_range = json.loads(cleaned_text)
        except json.JSONDecodeError as e: logger.error(f"LLM Date Range JSON Parse Error: {e}. Raw: {cleaned_text}"); return None

        # Validation
        if not isinstance(parsed_range, dict) or 'start_iso' not in parsed_range or 'end_iso' not in parsed_range: logger.error(f"LLM Date Range structure invalid: {parsed_range}"); return None
        if not isinstance(parsed_range['start_iso'], str) or not isinstance(parsed_range['end_iso'], str): logger.error(f"LLM Date Range values not strings: {parsed_range}"); return None
        try:
            dateutil_parser.isoparse(parsed_range['start_iso']); dateutil_parser.isoparse(parsed_range['end_iso'])
        except ValueError as e: logger.error(f"LLM Date Range Invalid ISO: {e}. Range: {parsed_range}"); return None

        logger.info(f"LLM Date Range Result: {parsed_range}")
        return parsed_range

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Date Range): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLM Service (Date Range): Unexpected error - {e}", exc_info=True)
        return None

async def extract_event_details_llm(text: str, current_time_iso: str) -> dict | None:
    """Uses LLM to extract event details. Requires user's current time."""
    if not llm_available or not gemini_model: logger.error(...); return None

    # Use the provided current_time_iso
    prompt = f"""
    Extract calendar event details from the text based on user's current time ({current_time_iso}).
    Output JSON: {{"summary": "...", "start_time": "ISO8601", "end_time": "ISO8601", "description": "...", "location": "..."}}
    Assume 1-hour duration if end missing. Use appropriate timezone offset (e.g., Z or +/-HH:MM) reflecting the user's likely timezone based on context.

    Text: "{text}"
    JSON Output:
    """
    try:
        logger.debug(f"LLM Event Extract Request: '{text[:100]}...'")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(f"LLM event extract blocked: {response.prompt_feedback.block_reason}"); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for event extract missing 'text'."); return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"LLM Event Extract Raw Output: {cleaned_text}")
        try:
            event_details = json.loads(cleaned_text)
        except json.JSONDecodeError as e: logger.error(f"LLM Event Extract JSON Parse Error: {e}. Raw: {cleaned_text}"); return None

        # Basic Validation
        if not isinstance(event_details, dict) or not event_details.get('summary') or not event_details.get('start_time'):
             logger.warning(f"LLM Event Extract missing essential fields: {event_details}")
             return None # Essential details missing

        logger.info(f"LLM Event Extract Result: {event_details}")
        return event_details

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Event Extract): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLM Service (Event Extract): Unexpected error - {e}", exc_info=True)
        return None


async def find_event_match_llm(user_request: str, candidate_events: list, current_time_iso: str) -> dict | None:
    """Uses LLM to find best event match. Requires user's current time."""
    if not llm_available or not gemini_model: logger.error(...); return None
    if not candidate_events: return {'match_type': 'NONE'}

    # Format candidate events (no change needed here)
    formatted_events = [] # ...
    events_list_str = "\n".join(formatted_events)

    # Use the provided current_time_iso
    prompt = f"""
    User's current time: {current_time_iso}. User request: "{user_request}"
    Analyze the event list and find the best match (...details as before...)

    Event List:
    ---
    {events_list_str}
    ---

    Respond ONLY with JSON: (...as before...)

    JSON Output:
    """
    try:
        logger.debug(f"LLM Event Match Request: '{user_request[:50]}...' with {len(candidate_events)} candidates.")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(f"LLM event matching blocked: {response.prompt_feedback.block_reason}"); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for event matching missing 'text'."); return None

        cleaned_text = response.text.strip().removeprefix("```json").removesuffix("```").strip()
        logger.debug(f"LLM Event Match Raw Output: {cleaned_text}")
        try:
            match_result = json.loads(cleaned_text)
        except json.JSONDecodeError as e: logger.error(f"LLM Event Match JSON Parse Error: {e}. Raw: {cleaned_text}"); return None

        # Validation
        match_type = match_result.get('match_type')
        if match_type not in ['SINGLE', 'MULTIPLE', 'NONE']: logger.error(f"LLM Event Match invalid type: {match_type}"); return None
        if match_type == 'SINGLE':
            if 'event_index' not in match_result: logger.error(f"LLM SINGLE match missing index: {match_result}"); return None
            try:
                event_idx = int(match_result['event_index']); assert 0 <= event_idx < len(candidate_events)
            except (ValueError, TypeError, AssertionError) as e: logger.error(f"LLM SINGLE match invalid index {match_result.get('event_index')}: {e}"); return {'match_type': 'NONE'}

        logger.info(f"LLM Event Match Result: {match_result}")
        return match_result

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Event Match): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLM Service (Event Match): Unexpected error - {e}", exc_info=True)
        return None

# === Safe JSON/Literal Parsing Helper ===
def _parse_llm_json_output(llm_output: str) -> dict | None:
    """Attempts to parse LLM output as JSON, falling back to literal_eval."""
    if not llm_output: return None
    cleaned_text = llm_output.strip().removeprefix("```json").removesuffix("```").strip()
    logger.debug(f"Attempting to parse: {cleaned_text}")
    try:
        # Try strict JSON first
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        logger.warning(f"JSON parsing failed, trying literal_eval for: {cleaned_text}")
        try:
            # Fallback to literal eval (handles single quotes etc.)
            evaluated = ast.literal_eval(cleaned_text)
            if isinstance(evaluated, dict):
                return evaluated
            else:
                logger.error(f"ast.literal_eval did not return a dict. Type: {type(evaluated)}")
                return None
        except (ValueError, SyntaxError, TypeError) as eval_err:
            logger.error(f"JSON and literal parsing failed: {eval_err}. Raw: {cleaned_text}")
            return None


# === LLM Functions for Argument Extraction ===

async def extract_read_args_llm(text_period: str, current_time_iso: str) -> dict | None:
    """Uses LLM to get start_iso and end_iso for reading calendar events."""
    if not llm_available or not gemini_model: logger.error(...); return None
    prompt = f"""
    Analyze the time period description relative to the user's current time ({current_time_iso}).
    Determine the precise start and end datetime. Assume standard interpretations (e.g., 'today' is 00:00 to 23:59, 'next week' is Mon-Sun).
    Output ONLY JSON: {{"start_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ", "end_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ"}}
    Use UTC ('Z') or the appropriate offset based on the current time provided.

    Time Period Description: "{text_period}"

    JSON Output:
    """
    try:
        logger.debug(f"LLM Read Args Request: '{text_period}'")
        response = await gemini_model.generate_content_async(prompt)
        # --- Standard Response Handling ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(...); return None
        if not hasattr(response, 'text'): logger.warning(...); return None
        # --- Parsing ---
        parsed_args = _parse_llm_json_output(response.text)
        # --- Validation ---
        if not parsed_args or 'start_iso' not in parsed_args or 'end_iso' not in parsed_args:
            logger.error(f"LLM Read Args invalid structure: {parsed_args}")
            return None
        # Validate ISO format (optional but good)
        try: dateutil_parser.isoparse(parsed_args['start_iso']); dateutil_parser.isoparse(parsed_args['end_iso'])
        except ValueError: logger.error(f"LLM Read Args invalid ISO format: {parsed_args}"); return None
        logger.info(f"LLM Read Args Result: {parsed_args}")
        return parsed_args
    except Exception as e: logger.error(f"LLM Service (Read Args) Error: {e}", exc_info=True); return None

async def extract_search_args_llm(text_query: str, current_time_iso: str) -> dict | None:
    """Uses LLM to get query, start_iso, and end_iso for searching calendar events."""
    if not llm_available or not gemini_model: logger.error(...); return None
    prompt = f"""
    Analyze the user's search request relative to their current time ({current_time_iso}).
    Identify the core search query keywords/phrase.
    Also determine the relevant start and end datetime for the search window (if a time period like 'next month' or 'last week' is mentioned, otherwise use a sensible default like the next 30 days).
    Output ONLY JSON: {{"query": "search keywords", "start_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ", "end_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ"}}
    Use UTC ('Z') or the appropriate offset based on the current time provided for dates.

    Search Request: "{text_query}"

    JSON Output:
    """
    try:
        logger.debug(f"LLM Search Args Request: '{text_query}'")
        response = await gemini_model.generate_content_async(prompt)
        # --- Standard Response Handling & Parsing ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(...); return None
        if not hasattr(response, 'text'): logger.warning(...); return None
        parsed_args = _parse_llm_json_output(response.text)
        # --- Validation ---
        if not parsed_args or 'query' not in parsed_args or 'start_iso' not in parsed_args or 'end_iso' not in parsed_args:
             logger.error(f"LLM Search Args invalid structure: {parsed_args}"); return None
        try: dateutil_parser.isoparse(parsed_args['start_iso']); dateutil_parser.isoparse(parsed_args['end_iso'])
        except ValueError: logger.error(f"LLM Search Args invalid ISO format: {parsed_args}"); return None
        if not parsed_args.get('query'): logger.warning("LLM Search Args extracted empty query."); # Decide if this is acceptable
        logger.info(f"LLM Search Args Result: {parsed_args}")
        return parsed_args
    except Exception as e: logger.error(f"LLM Service (Search Args) Error: {e}", exc_info=True); return None

async def extract_create_args_llm(event_description: str, current_time_iso: str, user_timezone_str: str) -> dict | None:
    """Uses LLM to extract the full event body dictionary for creation."""
    if not llm_available or not gemini_model: logger.error(...); return None
    prompt = f"""
    Analyze the user's request to create an event, considering their current time is {current_time_iso} and their timezone is {user_timezone_str}.
    Extract all relevant details (summary, start time, end time, description, location).
    Assume a 1-hour duration if only start time is mentioned.
    Format the start and end times as ISO 8601 strings WITH timezone offset or Z.
    Output ONLY JSON representing the Google Calendar Event resource body. It MUST include 'summary', 'start' (with 'dateTime' and 'timeZone'), and 'end' (with 'dateTime' and 'timeZone'). Include 'description' and 'location' if found. The 'timeZone' value should be the user's IANA timezone: '{user_timezone_str}'.

    User Request: "{event_description}"

    JSON Event Body Output:
    """
    try:
        logger.debug(f"LLM Create Args Request: '{event_description[:100]}...'")
        response = await gemini_model.generate_content_async(prompt)
        # --- Standard Response Handling & Parsing ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning(...); return None
        if not hasattr(response, 'text'): logger.warning(...); return None
        event_data = _parse_llm_json_output(response.text)
        # --- Validation ---
        if not event_data or not isinstance(event_data, dict): logger.error(f"LLM Create Args not a dict: {event_data}"); return None
        # Crucial fields for Google API
        if not event_data.get('summary'): logger.error(f"LLM Create Args missing summary: {event_data}"); return None
        start = event_data.get('start'); end = event_data.get('end')
        if not start or not isinstance(start, dict) or not start.get('dateTime') or not start.get('timeZone'): logger.error(f"LLM Create Args invalid start: {start}"); return None
        if not end or not isinstance(end, dict) or not end.get('dateTime') or not end.get('timeZone'): logger.error(f"LLM Create Args invalid end: {end}"); return None
        # Validate timezones and dates (optional but recommended)
        try:
            if start['timeZone'] != user_timezone_str or end['timeZone'] != user_timezone_str: logger.warning("LLM returned different timezone than requested.")
            dateutil_parser.isoparse(start['dateTime']); dateutil_parser.isoparse(end['dateTime'])
        except Exception as e: logger.error(f"LLM Create Args invalid date/tz format: {e}. Data: {event_data}"); return None

        logger.info(f"LLM Create Args Result: {event_data}")
        return event_data
    except Exception as e: logger.error(f"LLM Service (Create Args) Error: {e}", exc_info=True); return None


async def extract_update_search_and_changes(
    natural_language_input: str,
    current_time_iso: str,
    # user_id: int | None = None # Optional: if _get_llm_json_response needs it
) -> dict | None:
    """
    Uses an LLM to extract event search criteria and a description of changes
    from a natural language request.

    Args:
        natural_language_input: The user's raw request string.
        current_time_iso: The current time in ISO format for context.
        # user_id: Optional user ID for logging or context in LLM calls.

    Returns:
        A dictionary with "search_query", "changes_description",
        "search_start_iso", and "search_end_iso", or None if parsing fails.
    """
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Extract Update Search/Changes): LLM not available.")
        return None
        
    logger.info(f"LLMService: Extracting update search/changes from: '{natural_language_input[:100]}...'")

    prompt = f"""
Given the user's request: "{natural_language_input}"
And the current time for context: {current_time_iso} (user's local time where the request is made)

Your task is to analyze the request and extract the following information:
1.  `search_query`: Identify the part of the request that describes the original event the user wants to update. This could be based on title, time, attendees, or a combination. Formulate a concise search query string that can be used to find this event in a calendar. For example, if the user says "my meeting with John tomorrow at 2pm", the search_query could be "meeting with John 2pm tomorrow".
2.  `changes_description`: Identify the part of the request that describes the *desired changes* to the event. For example, if the user says "change my meeting with John tomorrow at 2pm to 3pm and add project docs", the changes_description would be "change to 3pm and add project docs".
3.  `search_start_iso` (optional): If the user's request implies a specific date or a narrow time window for the *original* event (e.g., "my meeting *tomorrow*", "the event on *July 10th*"), provide the start of this window as an ISO 8601 datetime string. If the request is vague about the original event's timing (e.g., "my weekly sync"), set this to null.
4.  `search_end_iso` (optional): If `search_start_iso` is provided, also provide the end of that specific search window as an ISO 8601 datetime string. This helps narrow down the search for the original event. If `search_start_iso` is null, this should also be null.

Return ONLY a JSON object with the following keys: "search_query", "changes_description", "search_start_iso", "search_end_iso".
Ensure `search_start_iso` and `search_end_iso` are null if no specific time window for the original event is mentioned.

Example 1:
User request: "Reschedule my meeting with Bob from 3pm today to 4pm and change location to Main Hall."
Current time: 2024-03-15T10:00:00-04:00
Output:
{{
    "search_query": "meeting with Bob 3pm today",
    "changes_description": "Reschedule to 4pm and change location to Main Hall",
    "search_start_iso": "2024-03-15T00:00:00-04:00",
    "search_end_iso": "2024-03-15T23:59:59-04:00"
}}

Example 2:
User request: "Update the 'Project Alpha Review' event. Add 'Review slides before meeting' to the description."
Current time: 2024-03-15T10:00:00-04:00
Output:
{{
    "search_query": "Project Alpha Review",
    "changes_description": "Add 'Review slides before meeting' to the description.",
    "search_start_iso": null,
    "search_end_iso": null
}}

Example 3:
User request: "Need to change my workout session next Monday. Move it from 9am to 10am."
Current time: 2024-03-15T10:00:00-04:00 (Friday)
Output:
{{
    "search_query": "workout session next Monday 9am",
    "changes_description": "Move it to 10am.",
    "search_start_iso": "2024-03-18T00:00:00-04:00",
    "search_end_iso": "2024-03-18T23:59:59-04:00"
}}
"""

    try:
        logger.debug(f"LLMService: Sending prompt for extract_update_search_and_changes: {prompt[:300]}...")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(f"LLMService: Call blocked for extract_update_search_and_changes: {response.prompt_feedback.block_reason}")
            return None
        if not hasattr(response, 'text'):
            logger.warning("LLMService: Response for extract_update_search_and_changes missing 'text'.")
            return None
            
        response_data = _parse_llm_json_output(response.text)

        if response_data and \
           isinstance(response_data.get("search_query"), str) and \
           isinstance(response_data.get("changes_description"), str):
            # search_start_iso and search_end_iso can be None, so check type if not None
            start_iso = response_data.get("search_start_iso")
            end_iso = response_data.get("search_end_iso")
            if (start_iso is not None and not isinstance(start_iso, str)) or \
               (end_iso is not None and not isinstance(end_iso, str)):
                logger.warning(f"LLMService: Invalid ISO date string types for search window. Start: {type(start_iso)}, End: {type(end_iso)}. Data: {response_data}")
                # Allow nulls, but if present, must be string.
                # If they are present and not strings, this indicates an LLM formatting error.
                return None 

            # Further validation for ISO format if dates are present
            if start_iso:
                try: dateutil_parser.isoparse(start_iso)
                except ValueError: logger.warning(f"LLMService: search_start_iso is not a valid ISO string: {start_iso}"); return None
            if end_iso:
                try: dateutil_parser.isoparse(end_iso)
                except ValueError: logger.warning(f"LLMService: search_end_iso is not a valid ISO string: {end_iso}"); return None
            
            if start_iso and not end_iso:
                logger.warning(f"LLMService: search_start_iso provided but search_end_iso is missing. Data: {response_data}")
                return None # If start is provided, end should also be.
            if not start_iso and end_iso: # Less likely but good to check
                logger.warning(f"LLMService: search_end_iso provided but search_start_iso is missing. Data: {response_data}")
                return None


            logger.info(f"LLMService: Successfully extracted search/changes: {response_data}")
            return response_data
        else:
            logger.warning(f"LLMService: Failed to extract necessary fields or wrong types. Response: {response_data}")
            return None
    except GoogleAPIError as api_err:
        logger.error(f"LLMService (Extract Update Search/Changes): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLMService: Error during LLM call for extract_update_search_and_changes: {e}", exc_info=True)
        return None


async def extract_calendar_update_details_llm(
    natural_language_changes: str,
    original_event_details: dict,
    current_time_iso: str,
    user_timezone_str: str,
    # user_id: int | None = None # Optional for LLM call context
) -> dict | None:
    """
    Uses an LLM to convert natural language event changes into a structured
    dictionary suitable for the Google Calendar API (patch).

    Args:
        natural_language_changes: The string describing the changes (e.g., "move to 4pm and call it 'New Title'").
        original_event_details: The full dictionary of the original event, providing context.
        current_time_iso: The current time in ISO format.
        user_timezone_str: The user's IANA timezone string (e.g., "America/New_York").
        # user_id: Optional user ID for logging or LLM context.

    Returns:
        A dictionary containing only the fields to be updated (e.g., {"summary": "New Title", "start": {"dateTime": ..., "timeZone": ...}}),
        or None if parsing fails or no valid changes are extracted.
    """
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Extract Update Details): LLM not available.")
        return None

    logger.info(f"LLMService: Extracting structured update from NL changes: '{natural_language_changes[:100]}...' for event ID {original_event_details.get('id')}")

    # Prepare a simplified version of the original event for the prompt,
    # including only potentially relevant fields for context.
    original_event_context = {
        "summary": original_event_details.get("summary"),
        "start": original_event_details.get("start"),
        "end": original_event_details.get("end"),
        "description": original_event_details.get("description"),
        "location": original_event_details.get("location"),
    }
    # Ensure no None values are passed to json.dumps to avoid 'null' strings where not desired by prompt,
    # or ensure prompt handles 'null' appropriately. For this prompt, seems okay.
    original_event_context_json = json.dumps(original_event_context, indent=2)

    prompt = f"""
You are a helpful AI assistant that converts natural language descriptions of event changes into a structured JSON format suitable for updating a Google Calendar event via a PATCH request.

Context:
- User's timezone: {user_timezone_str}
- Current time: {current_time_iso}
- Original event details (for context, especially for relative changes like "move it one hour later"):
{original_event_context_json}

User's desired changes: "{natural_language_changes}"

Your task is to analyze the "User's desired changes" and produce a JSON object containing *only* the fields that need to be updated.
- If a field is not mentioned as changed, do not include it in the output.
- For `start` and `end` times:
    - If the change involves a specific time (e.g., "to 3pm", "at 10:30 AM"), output the full ISO 8601 `dateTime` string.
    - The `dateTime` string MUST be in UTC if it's for an all-day event modification or if no specific time is given for a date change, OR it should be in the user's local timezone if a specific time of day is provided. Better yet, always include the correct offset for the user's timezone.
    - Crucially, if you output a `dateTime` field for `start` or `end`, you MUST also include a `timeZone` field with the value `{user_timezone_str}`. For example: `{{"start": {{"dateTime": "YYYY-MM-DDTHH:mm:ss[+/-HH:mm]", "timeZone": "{user_timezone_str}"}}}}`.
    - If the user says something like "move it one hour later", calculate the new time based on the original event's start time and the user's timezone.
    - If only a date is mentioned (e.g., "move to tomorrow"), and the original was a timed event, assume the same time of day in the user's timezone unless specified otherwise. If the original was an all-day event, the update should also be for a date.
    - If the user wants to change an event to be all-day, the format should be `{{"start": {{"date": "YYYY-MM-DD"}}, "end": {{"date": "YYYY-MM-DD"}}}}` (end date is exclusive for all-day events, usually one day after start for a single all-day event).
- For `summary`, `description`, `location`: these should be strings.
- If a field is explicitly being cleared (e.g., "remove the location"), set its value to `null` if the API supports that for PATCH, or an empty string `""` if appropriate. For this task, prefer empty string for text fields and `null` for complex objects if clearing is intended (though the examples focus on setting new values).

Output ONLY the JSON object representing the delta/changes. Do not include fields that are not changing.

Example 1:
User's desired changes: "Change summary to 'Updated Meeting Title' and move it to tomorrow 4pm."
Original event start: "2024-03-15T15:00:00-04:00" (3 PM in user's timezone America/New_York)
Current time: "2024-03-15T10:00:00-04:00"
User timezone: "America/New_York"
Output:
{{
    "summary": "Updated Meeting Title",
    "start": {{"dateTime": "2024-03-16T16:00:00-04:00", "timeZone": "America/New_York"}},
    "end": {{"dateTime": "2024-03-16T17:00:00-04:00", "timeZone": "America/New_York"}} // Assuming 1hr duration from original
}}

Example 2:
User's desired changes: "Add 'Project discussion' to the description."
Output:
{{
    "description": "Project discussion"
}}

Example 3:
User's desired changes: "Set location to 'Room 101'."
Output:
{{
    "location": "Room 101"
}}

Example 4 (relative time change):
User's desired changes: "Delay it by 2 hours."
Original event start: "2024-03-15T15:00:00-04:00" (3 PM America/New_York)
User timezone: "America/New_York"
Output:
{{
    "start": {{"dateTime": "2024-03-15T17:00:00-04:00", "timeZone": "America/New_York"}},
    "end": {{"dateTime": "2024-03-15T18:00:00-04:00", "timeZone": "America/New_York"}} // Assuming 1hr duration
}}
"""

    try:
        logger.debug(f"LLMService: Sending prompt for extract_calendar_update_details: {prompt[:400]}...") # Log more of prompt
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(f"LLMService: Call blocked for extract_calendar_update_details: {response.prompt_feedback.block_reason}")
            return None
        if not hasattr(response, 'text'):
            logger.warning("LLMService: Response for extract_calendar_update_details missing 'text'.")
            return None
            
        response_data = _parse_llm_json_output(response.text)

        if response_data and isinstance(response_data, dict):
            # Basic validation: ensure start/end times, if present, have dateTime and timeZone
            for time_field in ['start', 'end']:
                if time_field in response_data:
                    field_value = response_data[time_field]
                    if isinstance(field_value, dict):
                        if 'dateTime' in field_value:
                            if 'timeZone' not in field_value:
                                logger.warning(f"LLMService: Missing 'timeZone' for '{time_field}.dateTime'. Adding user's timezone '{user_timezone_str}'. Data: {field_value}")
                                response_data[time_field]['timeZone'] = user_timezone_str
                            # Validate ISO format for dateTime
                            try:
                                dateutil_parser.isoparse(field_value['dateTime'])
                            except ValueError:
                                logger.warning(f"LLMService: Invalid ISO dateTime format for '{time_field}': {field_value['dateTime']}. Data: {response_data}")
                                return None 
                        elif 'date' in field_value: # All-day event
                             # Validate ISO format for date
                            try:
                                dateutil_parser.isoparse(field_value['date'])
                            except ValueError:
                                logger.warning(f"LLMService: Invalid ISO date format for '{time_field}': {field_value['date']}. Data: {response_data}")
                                return None
                        else: # Neither dateTime nor date found, but it's a dict.
                            logger.warning(f"LLMService: '{time_field}' is a dict but lacks 'dateTime' or 'date'. Data: {field_value}")
                            return None
                    # If field_value is not a dict (e.g. user tries to set start="tomorrow") - this should be caught by LLM but good to check
                    else:
                        logger.warning(f"LLMService: '{time_field}' value is not a dictionary as expected. Value: {field_value}. Data: {response_data}")
                        return None

            if not response_data: 
                logger.warning(f"LLMService: Extracted update data is empty. Original LLM response was likely empty or invalid. Raw parsed: {response_data}")
                return None
                
            logger.info(f"LLMService: Successfully extracted structured update data: {response_data}")
            return response_data
        else:
            logger.warning(f"LLMService: Failed to extract valid structured update data or not a dict. Response: {response_data}")
            return None
    except GoogleAPIError as api_err:
        logger.error(f"LLMService (Extract Update Details): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLMService: Error during LLM call for extract_calendar_update_details: {e}", exc_info=True)
        return None
