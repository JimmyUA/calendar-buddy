# llm_service.py
import logging
import json
import ast
from datetime import datetime, timezone

# Google AI specific imports
from google import genai
from google.api_core.exceptions import GoogleAPIError

# Date parsing library (needed for formatting dates within prompts)
from dateutil import parser as dateutil_parser

import config # For API Key

logger = logging.getLogger(__name__)

# --- Google Gemini Setup ---
gemini_client = None
llm_available = False
if config.GOOGLE_API_KEY:
    try:
        gemini_client = genai.Client(api_key=config.GOOGLE_API_KEY)
        # The model is now specified in each call, so we don't initialize it here.
        # We can do a quick test if needed by making a sample call.
        llm_available = True
        logger.info("LLM Service: Google GenAI Client configured successfully.")
    except Exception as e:
        logger.error(f"LLM Service: Failed to configure Google GenAI Client: {e}", exc_info=True)
else:
    logger.warning("LLM Service: Google API Key not found. LLM features disabled.")


# === LLM Interaction Functions ===

async def extract_text_from_image(image_bytes: bytes) -> str | None:
    """Extract text or a short description from an image."""
    if not llm_available or not gemini_client:
        logger.error("LLM Service (Image): LLM not available.")
        return None

    prompt = "Describe any text or important details in this image."
    try:
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=[
                {"inline_data": {"mime_type": "image/jpeg", "data": image_bytes}},
                {"text": prompt},
            ]
        )

        if getattr(response, "prompt_feedback", None) and getattr(response.prompt_feedback, "block_reason", None):
            logger.warning(f"LLM image description blocked: {response.prompt_feedback.block_reason}")
            return None

        if hasattr(response, "text"):
            return response.text
        if hasattr(response, "parts") and response.parts:
            return "".join(part.text for part in response.parts if hasattr(part, "text"))
        logger.warning("LLM image description response missing text content.")
        return None

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Image): Google API Error - {api_err}")
        return None
    except Exception as e:
        logger.error(f"LLM Service (Image): Unexpected error - {e}", exc_info=True)
        return None


async def transcribe_audio(audio_bytes: bytes) -> str | None:
    """Transcribe audio bytes to text using the Gemini model."""
    if not llm_available or not gemini_client:
        logger.error("LLM Service (Audio): LLM not available.")
        return None

    prompt = "Transcribe the spoken words in this audio into text."
    try:
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=[
                {"inline_data": {"mime_type": "audio/ogg", "data": audio_bytes}},
                {"text": prompt},
            ]
        )

        if getattr(response, "prompt_feedback", None) and getattr(
            response.prompt_feedback, "block_reason", None
        ):
            logger.warning(
                f"LLM audio transcription blocked: {response.prompt_feedback.block_reason}"
            )
            return None

        if hasattr(response, "text"):
            return response.text
        if hasattr(response, "parts") and response.parts:
            return "".join(
                part.text for part in response.parts if hasattr(part, "text")
            )
        logger.warning("LLM audio transcription response missing text content.")
        return None

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Audio): Google API Error - {api_err}")
        return None
    except Exception as e:
        logger.error(f"LLM Service (Audio): Unexpected error - {e}", exc_info=True)
        return None


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
    if not llm_available or not gemini_client:
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
        # Pass the history directly to generate_content
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=formatted_history,
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
    if not llm_available or not gemini_client:
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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )

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
    if not llm_available or not gemini_client: logger.error("LLM Service (Date Range): LLM not available."); return None

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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )

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
    if not llm_available or not gemini_client: logger.error("LLM Service (Event Extract): LLM not available."); return None

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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )

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
    if not llm_available or not gemini_client: logger.error("LLM Service (Event Match): LLM not available."); return None
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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )

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
    if not llm_available or not gemini_client: logger.error("LLM Service (Read Args): LLM not available."); return None
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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )
        # --- Standard Response Handling ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning("LLM read args blocked."); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for read args missing 'text'."); return None
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
    if not llm_available or not gemini_client: logger.error("LLM Service (Search Args): LLM not available."); return None
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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )
        # --- Standard Response Handling & Parsing ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning("LLM search args blocked."); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for search args missing 'text'."); return None
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
    if not llm_available or not gemini_client: logger.error("LLM Service (Create Args): LLM not available."); return None
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
        response = await gemini_client.aio.models.generate_content(
            model='gemini-1.5-flash-latest',
            contents=prompt
        )
        # --- Standard Response Handling & Parsing ---
        if response.prompt_feedback and response.prompt_feedback.block_reason: logger.warning("LLM create args blocked."); return None
        if not hasattr(response, 'text'): logger.warning("LLM response for create args missing 'text'."); return None
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
