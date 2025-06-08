import logging
from datetime import datetime
from dateutil import parser as dateutil_parser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import pytz

import google_services as gs
from google_services import get_pending_event, delete_pending_event, get_pending_deletion, delete_pending_deletion
from handler.message_formatter import create_final_message, create_delete_confirmation_message
from llm.agent import initialize_agent
from llm import llm_service
from utils import _format_event_time
from .helpers import _get_user_tz_or_prompt

logger = logging.getLogger(__name__)


async def _handle_general_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    logger.info(f"Handling GENERAL_CHAT for user {user_id} with history")

    if update.message and update.message.photo:
        try:
            file = await update.message.photo[-1].get_file()
            image_bytes = await file.download_as_bytearray()
            img_text = await llm_service.extract_text_from_image(bytes(image_bytes))
            if img_text:
                text = f"{text}\n{img_text}" if text else img_text
        except Exception as e:
            logger.error(f"Error processing photo for general chat: {e}")

    if update.message and (update.message.voice or update.message.audio):
        try:
            voice_or_audio = update.message.voice or update.message.audio
            file = await voice_or_audio.get_file()
            audio_bytes = await file.download_as_bytearray()
            audio_text = await llm_service.transcribe_audio(bytes(audio_bytes))
            if audio_text:
                text = f"{text}\n{audio_text}" if text else audio_text
        except Exception as e:
            logger.error(f"Error processing audio for general chat: {e}")

    history = await gs.get_chat_history(user_id, "general")
    logger.debug(f"General Chat: Loaded {len(history)} messages from Firestore for user {user_id}")

    history.append({'role': 'user', 'content': text})
    await gs.add_chat_message(user_id, 'user', text, "general")

    response_text = await llm_service.get_chat_response(history)

    if response_text:
        await update.message.reply_text(response_text)
        history.append({'role': 'model', 'content': response_text})
        await gs.add_chat_message(user_id, 'model', response_text, "general")
    else:
        await update.message.reply_text("Sorry, I couldn't process that chat message right now.")
        if history and history[-1]['role'] == 'user':
            history.pop()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not (
        update.message.text
        or update.message.caption
        or update.message.photo
        or update.message.voice
        or update.message.audio
    ):
        logger.warning(
            "handle_message received update without text, caption, photo, or audio."
        )
        return
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""

    if update.message.photo:
        try:
            file = await update.message.photo[-1].get_file()
            image_bytes = await file.download_as_bytearray()
            img_text = await llm_service.extract_text_from_image(bytes(image_bytes))
            if img_text:
                text = f"{text}\n{img_text}" if text else img_text
        except Exception as e:
            logger.error(f"Error processing photo for agent message: {e}")

    if update.message.voice or update.message.audio:
        try:
            voice_or_audio = update.message.voice or update.message.audio
            file = await voice_or_audio.get_file()
            audio_bytes = await file.download_as_bytearray()
            audio_text = await llm_service.transcribe_audio(bytes(audio_bytes))
            if audio_text:
                text = f"{text}\n{audio_text}" if text else audio_text
        except Exception as e:
            logger.error(f"Error processing audio for agent message: {e}")

    logger.info(f"Agent Handler: Received message from user {user_id}: '{text[:50]}...'")

    if not await gs.is_user_connected(user_id):
        await update.message.reply_text("Please connect your Google Calendar first using /connect_calendar.")
        return

    user_timezone_str = await gs.get_user_timezone_str(user_id)
    if not user_timezone_str:
        user_timezone_str = 'UTC'
        await update.message.reply_text(
            "Note: Your timezone isn't set. Using UTC. Use /set_timezone for accurate local times.")

    chat_history = await gs.get_chat_history(user_id, "lc")
    logger.debug(f"Agent Handler: Loaded {len(chat_history)} messages from Firestore for user {user_id}")

    chat_history.append({'role': 'user', 'content': text})
    await gs.add_chat_message(user_id, 'user', text, "lc")

    try:
        agent_executor = initialize_agent(user_id, user_timezone_str, chat_history)
    except Exception as e:
        logger.error(f"Failed to initialize agent for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("Sorry, there was an error setting up the AI agent.")
        chat_history.pop()
        return

    await update.message.chat.send_action(action="typing")
    try:
        response = await agent_executor.ainvoke({"input": text})
        agent_response = response.get('output', "Sorry, I didn't get a response.")
    except Exception as e:
        logger.error(f"Agent execution error for user {user_id}: {e}", exc_info=True)
        agent_response = "Sorry, an error occurred while processing your request with the agent."
        chat_history.pop()

    final_message_to_send = agent_response
    reply_markup = None

    pending_event_data = await get_pending_event(user_id)
    if pending_event_data:
        logger.info(f"Pending event create found for user {user_id} from Firestore. Formatting confirmation.")
        try:
            user_tz = pytz.timezone(user_timezone_str if user_timezone_str else 'UTC')
            final_message_to_send = await create_final_message(pending_event_data)
            keyboard = [[InlineKeyboardButton("✅ Confirm Create", callback_data="confirm_event_create"),
                         InlineKeyboardButton("❌ Cancel Create", callback_data="cancel_event_create")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
        except Exception as e:
            logger.error(f"Error formatting create confirmation in handler from Firestore data: {e}", exc_info=True)
            final_message_to_send = f"Error preparing event confirmation: {e}. Please try again."
            await delete_pending_event(user_id)
    else:
        pending_deletion_data = await get_pending_deletion(user_id)
        if pending_deletion_data:
            logger.info(f"Pending event delete found for user {user_id} from Firestore. Formatting confirmation.")
            event_id_to_delete = pending_deletion_data.get('event_id')
            event_details_for_confirm = await gs.get_calendar_event_by_id(user_id, event_id_to_delete)

            if event_details_for_confirm:
                try:
                    final_message_to_send = await create_delete_confirmation_message(event_details_for_confirm)
                except Exception as e:
                    logger.error(
                        f"Error formatting delete confirmation in handler from Firestore data: {e}",
                        exc_info=True,
                    )
                    summary = pending_deletion_data.get('summary', 'the selected event')
                    final_message_to_send = f"Are you sure you want to delete '{summary}'?"
            else:
                summary = pending_deletion_data.get('summary', f'event ID {event_id_to_delete}')
                final_message_to_send = f"Could not re-fetch details for '{summary}' for deletion confirmation. It might no longer exist. Proceed with deleting?"

            keyboard = [[InlineKeyboardButton("✅ Yes, Delete", callback_data="confirm_event_delete"),
                         InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_event_delete")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        final_message_to_send,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    if agent_response and "error" not in agent_response.lower():
        chat_history.append({'role': 'model', 'content': agent_response})
        await gs.add_chat_message(user_id, 'model', agent_response, "lc")
