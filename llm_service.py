# llm_service.py
import logging
import json
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

async def get_chat_response(prompt: str) -> str | None:
    """Gets a general chat response from the LLM."""
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Chat): LLM not available.")
        return None # Return None explicitly if LLM is unavailable
    try:
        logger.debug(f"LLM Chat Request: {prompt[:100]}...")
        response = await gemini_model.generate_content_async(prompt)

        if response.prompt_feedback and response.prompt_feedback.block_reason:
             logger.warning(f"LLM chat response blocked: {response.prompt_feedback.block_reason}")
             return None # Indicate blocked content

        if hasattr(response, 'text'):
            return response.text
        elif hasattr(response, 'parts') and response.parts:
            logger.warning("LLM chat response missing 'text', attempting parts.")
            return "".join(part.text for part in response.parts if hasattr(part, 'text'))
        else:
             logger.error(f"LLM chat response missing text and parts. Full response: {response}")
             return None

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Chat): Google API Error - {api_err}", exc_info=False) # Less verbose traceback for API errors
        return None
    except Exception as e:
        logger.error(f"LLM Service (Chat): Unexpected error - {e}", exc_info=True)
        return None


async def classify_intent_and_extract_params(text: str) -> dict | None:
    """Uses LLM to classify user intent and extract parameters."""
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Intent): LLM not available.")
        return None

    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()

    prompt = f"""
    Analyze the user's message based on the current time ({current_time_str}).
    Classify the user's primary intent into one of these categories:
    CALENDAR_SUMMARY, CALENDAR_CREATE, CALENDAR_DELETE, GENERAL_CHAT

    Extract relevant parameters based on the intent:
    - CALENDAR_SUMMARY: {{"time_period": "extracted period like 'today', 'next week'"}}
    - CALENDAR_CREATE: {{"event_description": "extracted full description for event creation"}}
    - CALENDAR_DELETE: {{"event_description": "extracted description identifying the event to delete"}}
    - GENERAL_CHAT: {{}}

    Respond ONLY with a JSON object containing 'intent' (string) and 'parameters' (object).

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

        try:
            intent_data = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            logger.error(f"LLM Intent JSON Parse Error: {e}. Raw: {cleaned_text}")
            return None

        # --- Validation ---
        if not isinstance(intent_data, dict) or 'intent' not in intent_data or 'parameters' not in intent_data:
             logger.error(f"LLM Intent structure invalid: {intent_data}"); return None
        valid_intents = ["CALENDAR_SUMMARY", "CALENDAR_CREATE", "CALENDAR_DELETE", "GENERAL_CHAT"]
        intent_val = intent_data.get('intent'); params = intent_data.get('parameters', {})
        if intent_val not in valid_intents:
            logger.warning(f"LLM returned unknown intent '{intent_val}'. Defaulting to GENERAL_CHAT.")
            intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}; intent_val = 'GENERAL_CHAT'
        # Parameter validation
        if intent_val == "CALENDAR_SUMMARY" and not params.get("time_period"): logger.warning(f"LLM SUMMARY intent missing time_period."); intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        elif intent_val == "CALENDAR_CREATE" and not params.get("event_description"): logger.warning(f"LLM CREATE intent missing event_description."); intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        elif intent_val == "CALENDAR_DELETE" and not params.get("event_description"): logger.warning(f"LLM DELETE intent missing event_description."); intent_data = {'intent': 'GENERAL_CHAT', 'parameters': {}}
        # --- End Validation ---

        logger.info(f"LLM Intent Result: {intent_data.get('intent')}, Params: {params}")
        return intent_data

    except GoogleAPIError as api_err:
        logger.error(f"LLM Service (Intent): Google API Error - {api_err}", exc_info=False)
        return None
    except Exception as e:
        logger.error(f"LLM Service (Intent): Unexpected error - {e}", exc_info=True)
        return None


async def parse_date_range_llm(text_period: str) -> dict | None:
    """Uses LLM to parse a natural language time period into start/end ISO dates."""
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Date Range): LLM not available.")
        return None

    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()

    prompt = f"""
    Analyze the time period description relative to current time ({current_time_str}).
    Determine the precise start and end datetime. Assume standard interpretations (e.g., 'today' 00:00-23:59, 'next week' Mon-Sun).
    Output JSON: {{"start_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ", "end_iso": "YYYY-MM-DDTHH:MM:SS+ZZ:ZZ"}}
    Use UTC ('Z') or appropriate offset.

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


async def extract_event_details_llm(text: str) -> dict | None:
    """Uses LLM to extract structured event details from text."""
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Event Extract): LLM not available.")
        return None

    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()

    prompt = f"""
    Extract calendar event details from the text based on current time ({current_time_str}).
    Output JSON: {{"summary": "...", "start_time": "ISO8601", "end_time": "ISO8601", "description": "...", "location": "..."}}
    Assume 1-hour duration if end time missing. Use appropriate timezone offset (e.g., Z or +/-HH:MM).

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


async def find_event_match_llm(user_request: str, candidate_events: list) -> dict | None:
    """Uses LLM to determine which candidate event best matches the user's request."""
    if not llm_available or not gemini_model:
        logger.error("LLM Service (Event Match): LLM not available.")
        return None
    if not candidate_events:
        logger.info("LLM Event Match: No candidate events provided.")
        return {'match_type': 'NONE'}

    now = datetime.now(timezone.utc)
    current_time_str = now.isoformat()

    # Format candidate events for the prompt
    formatted_events = []
    for i, event in enumerate(candidate_events):
        summary = event.get('summary', 'No Title')
        start_str = event['start'].get('dateTime', event['start'].get('date'))
        try:
            if 'date' in event['start']: time_disp = dateutil_parser.isoparse(start_str).strftime('%Y-%m-%d (All day)')
            else: time_disp = dateutil_parser.isoparse(start_str).strftime('%Y-%m-%d %H:%M %Z')
        except Exception: time_disp = start_str # Fallback
        formatted_events.append(f"{i}: Title='{summary}', Time='{time_disp}'")
    events_list_str = "\n".join(formatted_events)

    prompt = f"""
    Current time: {current_time_str}. User request: "{user_request}"
    Analyze the event list and find the best match for the user's request based on title, time, etc.

    Event List:
    ---
    {events_list_str}
    ---

    Respond ONLY with JSON:
    - If ONE match: {{"match_type": "SINGLE", "event_index": <index_number>}}
    - If MULTIPLE plausible matches: {{"match_type": "MULTIPLE"}}
    - If NO match: {{"match_type": "NONE"}}

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