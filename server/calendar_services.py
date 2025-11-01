import asyncio
import logging
import json

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request

import config
from google_services import USER_TOKENS_COLLECTION, store_user_credentials, delete_user_token

logger = logging.getLogger(__name__)


async def _build_calendar_service_client(user_id: int):
    """Get an authorized Google Calendar service client for the user."""
    if not USER_TOKENS_COLLECTION:
        logger.error("Firestore unavailable for Calendar service.")
        return None

    creds_json = None
    doc_ref = USER_TOKENS_COLLECTION.document(str(user_id))
    try:
        snapshot = await asyncio.to_thread(doc_ref.get)
        if snapshot.exists:
            creds_json = snapshot.get('credentials_json')
        else:
            logger.info(f"_build_calendar_service_client: No creds found for {user_id}.")
            return None
    except Exception as e:
        logger.error(f"Error fetching token for Calendar service for {user_id}: {e}")
        return None

    if not creds_json:
        return None

    try:
        creds_info = json.loads(creds_json)
        creds = Credentials.from_authorized_user_info(creds_info, config.GOOGLE_CALENDAR_SCOPES)
    except Exception as e:
        logger.error(f"Failed to load creds from info for {user_id}: {e}")
        return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info(f"Refreshing Calendar credentials for user {user_id}")
                await asyncio.to_thread(creds.refresh, Request())
                if not await store_user_credentials(user_id, creds):
                    logger.error(f"Failed to store refreshed credentials for user {user_id}")
                    return None
                logger.info(f"Calendar Credentials refreshed successfully for {user_id}")
            except Exception as e:
                logger.error(f"Failed to refresh Calendar credentials for {user_id}: {e}")
                try:
                    logger.warning(
                        f"Clearing invalid token from Firestore for {user_id} after refresh failure."
                    )
                    await asyncio.to_thread(doc_ref.delete)
                except Exception as db_e:
                    logger.error(f"Failed to delete token for {user_id}: {db_e}")
                return None
        else:
            logger.warning(f"Stored Calendar credentials for {user_id} invalid/missing refresh token.")
            try:
                await asyncio.to_thread(doc_ref.delete)
            except Exception:
                pass
            return None

    try:
        service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        return service
    except HttpError as error:
        logger.error(f"API error building Calendar service for {user_id}: {error}")
        if error.resp.status == 401:
            logger.warning(
                f"Auth error (401) building Calendar service for {user_id}. Clearing token."
            )
            await delete_user_token(user_id)
        return None
    except Exception as e:
        logger.error(f"Unexpected error building Calendar service for {user_id}: {e}")
        return None


async def get_calendar_event_by_id(user_id: int, event_id: str) -> dict | None:
    """Fetch a single calendar event by its ID."""
    service = await _build_calendar_service_client(user_id)
    if not service:
        return None
    logger.info(f"GS: Fetching event details for ID {event_id} for user {user_id}")
    try:
        event_request = service.events().get(calendarId='primary', eventId=event_id)
        event = await asyncio.to_thread(event_request.execute)
        return event
    except HttpError as error:
        logger.error(f"GS: API error fetching event {event_id} for {user_id}: {error}")
        if error.resp.status in (404, 410):
            logger.warning(f"GS: Event {event_id} not found for user {user_id}.")
        elif error.resp.status == 401:
            await delete_user_token(user_id)
        return None
    except Exception as e:
        logger.error(
            f"GS: Unexpected error fetching event {event_id} for {user_id}: {e}",
            exc_info=True,
        )
        return None


async def get_calendar_events(
    user_id: int,
    time_min_iso: str,
    time_max_iso: str,
    max_results: int = 25,
) -> list | None:
    """Fetch events within a time range."""
    service = await _build_calendar_service_client(user_id)
    if not service:
        return None
    logger.debug(f"GS: Fetching events for {user_id} from {time_min_iso} to {time_max_iso}")
    try:
        events_request = service.events().list(
            calendarId='primary',
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime',
        )
        events_result = await asyncio.to_thread(events_request.execute)
        events = events_result.get('items', [])
        return [
            {
                'id': e.get('id'),
                'summary': e.get('summary'),
                'start': e.get('start'),
                'end': e.get('end'),
                'description': e.get('description'),
                'location': e.get('location'),
            }
            for e in events
        ]
    except HttpError as error:
        logger.error(f"GS: API error fetching events for {user_id}: {error}")
        if error.resp.status == 401:
            await delete_user_token(user_id)
        return None
    except Exception as e:
        logger.error(
            f"GS: Unexpected error fetching events for {user_id}: {e}", exc_info=True
        )
        return None


async def search_calendar_events(
    user_id: int,
    query: str,
    time_min_iso: str,
    time_max_iso: str,
    max_results: int = 10,
) -> list | None:
    """Search events by query string within a time range."""
    service = await _build_calendar_service_client(user_id)
    if not service:
        return None
    logger.info(
        f"GS: Searching events for {user_id} with query '{query}' from {time_min_iso} to {time_max_iso}"
    )
    try:
        events_request = service.events().list(
            calendarId='primary',
            q=query,
            timeMin=time_min_iso,
            timeMax=time_max_iso,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime',
        )
        events_result = await asyncio.to_thread(events_request.execute)
        events = events_result.get('items', [])
        logger.info(f"GS: Found {len(events)} events matching search.")
        return [
            {
                'id': e.get('id'),
                'summary': e.get('summary'),
                'start': e.get('start'),
                'end': e.get('end'),
            }
            for e in events
        ]
    except HttpError as error:
        logger.error(f"GS: API error searching events for {user_id}: {error}")
        if error.resp.status == 401:
            await delete_user_token(user_id)
        return None
    except Exception as e:
        logger.error(
            f"GS: Unexpected error searching events for {user_id}: {e}", exc_info=True
        )
        return None


async def create_calendar_event(user_id: int, event_data: dict) -> tuple[bool, str, str | None]:
    """Create an event and return (success, message, event_link)."""
    service = await _build_calendar_service_client(user_id)
    if not service:
        return False, "Authentication failed or required.", None

    logger.info(f"Attempting to create event for user {user_id}: {event_data.get('summary')}")
    try:
        event_request = service.events().insert(calendarId='primary', body=event_data)
        event = await asyncio.to_thread(event_request.execute)
        link = event.get('htmlLink')
        summary = event.get('summary', 'Event')
        logger.info(f"Event created for {user_id}: {link}")
        return True, f"Event '{summary}' created successfully.", link
    except HttpError as error:
        logger.error(f"API error creating event for {user_id}: {error}")
        error_details = f"API Error ({error.resp.status}): {error.resp.reason}"
        try:
            error_content = json.loads(error.content.decode())
            error_details = error_content.get('error', {}).get('message', error_details)
        except Exception:
            pass
        if error.resp.status == 401:
            logger.warning(f"Auth error (401) creating event for {user_id}. Clearing token.")
            await delete_user_token(user_id)
            return False, "Authentication failed. Please /connect_calendar again.", None
        return False, f"Failed to create event. {error_details}", None
    except Exception as e:
        logger.error(f"Unexpected error creating event for {user_id}: {e}", exc_info=True)
        return False, "An unexpected error occurred.", None


async def delete_calendar_event(user_id: int, event_id: str) -> tuple[bool, str]:
    """Delete a specific event."""
    service = await _build_calendar_service_client(user_id)
    if not service:
        return False, "Authentication failed or required."

    logger.info(f"Attempting to delete event ID {event_id} for user {user_id}")
    try:
        delete_request = service.events().delete(calendarId='primary', eventId=event_id)
        await asyncio.to_thread(delete_request.execute)
        logger.info(f"Successfully deleted event ID {event_id} for user {user_id}.")
        return True, "Event successfully deleted."
    except HttpError as error:
        logger.error(f"API error deleting event {event_id} for {user_id}: {error}")
        error_details = f"API Error ({error.resp.status}): {error.resp.reason}"
        try:
            error_content = json.loads(error.content.decode())
            error_details = error_content.get('error', {}).get('message', error_details)
        except Exception:
            pass
        if error.resp.status in (404, 410):
            return False, "Couldn't delete event (not found or already deleted)."
        elif error.resp.status == 401:
            logger.warning(f"Auth error (401) deleting event for {user_id}. Clearing token.")
            await delete_user_token(user_id)
            return False, "Authentication failed. Please /connect_calendar again."
        return False, f"Failed to delete event. {error_details}"
    except Exception as e:
        logger.error(
            f"Unexpected error deleting event {event_id} for {user_id}: {e}", exc_info=True
        )
        return False, "An unexpected error occurred."
