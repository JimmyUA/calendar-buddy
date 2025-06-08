import logging
from dateutil import parser as dateutil_parser
from telegram import Update
from telegram.ext import ContextTypes
import pytz
from pytz.exceptions import UnknownTimeZoneError
import google_services as gs
from llm import llm_service

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 10  # Remember last 10 back-and-forth turns
MAX_HISTORY_MESSAGES = MAX_HISTORY_TURNS * 2
ASKING_TIMEZONE = range(1)


def _format_iso_datetime_for_display(iso_string: str, target_tz_str: str | None = None) -> str:
    """Format an ISO datetime string for display, optionally converting to a target timezone."""
    try:
        dt_object = dateutil_parser.isoparse(iso_string)
        if target_tz_str:
            try:
                target_tz = pytz.timezone(target_tz_str)
                dt_object = dt_object.astimezone(target_tz)
                return dt_object.strftime('%Y-%m-%d %I:%M %p %Z')
            except UnknownTimeZoneError:
                logger.warning(f"Unknown timezone string '{target_tz_str}'. Falling back to UTC display.")
                dt_object = dt_object.astimezone(pytz.utc)
                return dt_object.strftime('%Y-%m-%d %I:%M %p UTC')
        if dt_object.tzinfo:
            return dt_object.strftime('%Y-%m-%d %I:%M %p %Z')
        return dt_object.strftime('%Y-%m-%d %I:%M %p (Timezone not specified, assumed UTC)')
    except ValueError:
        logger.error(f"Could not parse ISO string: {iso_string}")
        return iso_string


async def _get_user_tz_or_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> pytz.BaseTzInfo | None:
    """Get user's timezone object or prompt them to set it."""
    user_id = update.effective_user.id
    assert update.message is not None, "Update message should not be None for _get_user_tz_or_prompt"
    tz_str = await gs.get_user_timezone_str(user_id)
    if tz_str:
        try:
            return pytz.timezone(tz_str)
        except UnknownTimeZoneError:
            logger.warning(f"Invalid timezone '{tz_str}' found in DB for user {user_id}. Prompting.")
    await update.message.reply_text(
        "Please set your timezone first using the /set_timezone command so I can understand times correctly.")
    return None


async def extract_media_text(update: Update) -> str:
    """Extract text from photo, voice or audio in the update using LLM service."""
    if not update.message:
        return ""

    text_parts: list[str] = []

    if update.message.photo:
        try:
            file = await update.message.photo[-1].get_file()
            image_bytes = await file.download_as_bytearray()
            img_text = await llm_service.extract_text_from_image(bytes(image_bytes))
            if img_text:
                text_parts.append(img_text)
        except Exception as e:  # pragma: no cover - logging only
            logger.error(f"Error processing photo: {e}")

    if update.message.voice or update.message.audio:
        try:
            voice_or_audio = update.message.voice or update.message.audio
            file = await voice_or_audio.get_file()
            audio_bytes = await file.download_as_bytearray()
            audio_text = await llm_service.transcribe_audio(bytes(audio_bytes))
            if audio_text:
                text_parts.append(audio_text)
        except Exception as e:  # pragma: no cover - logging only
            logger.error(f"Error processing audio: {e}")

    return "\n".join(text_parts)
