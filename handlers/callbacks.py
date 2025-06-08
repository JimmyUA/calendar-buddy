import logging
import time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import google_services as gs
import calendar_services as cs
from google_services import (
    get_pending_event,
    delete_pending_event,
    get_pending_deletion,
    delete_pending_deletion,
)
from utils import _format_event_time, escape_markdown_v2
from .helpers import _format_iso_datetime_for_display

logger = logging.getLogger(__name__)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    callback_data = query.data
    logger.info(f"Callback: Received query from user {user_id}: {callback_data}")

    if callback_data == "confirm_event_create":
        event_details = await get_pending_event(user_id)
        if not event_details:
            await query.edit_message_text("Event details expired or not found.")
            return
        await query.edit_message_text(f"Adding '{event_details.get('summary', 'event')}' to your calendar...")
        success, msg, link = await cs.create_calendar_event(user_id, event_details)
        final_msg = msg + (f"\nView: <a href='{link}'>Event Link</a>" if link else "")
        await query.edit_message_text(final_msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        await delete_pending_event(user_id)
        if not success and "Authentication failed" in msg and not await gs.is_user_connected(user_id):
            logger.info(f"Token potentially cleared for {user_id} during failed create confirmation.")

    elif callback_data == "cancel_event_create":
        await delete_pending_event(user_id)
        await query.edit_message_text("Event creation cancelled.")

    elif callback_data == "confirm_event_delete":
        pending_deletion_data = await get_pending_deletion(user_id)
        if not pending_deletion_data:
            await query.edit_message_text("Confirmation for deletion expired or not found.")
            return
        event_id = pending_deletion_data.get('event_id')
        summary = pending_deletion_data.get('summary', 'the event')
        if not event_id:
            logger.error(f"Missing event_id in pending_deletion_data for user {user_id}")
            await query.edit_message_text("Error: Missing event ID for deletion.")
            await delete_pending_deletion(user_id)
            return
        await query.edit_message_text(f"Deleting '{summary}'...")
        success, msg = await cs.delete_calendar_event(user_id, event_id)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
        await delete_pending_deletion(user_id)
        if not success and "Authentication failed" in msg and not await gs.is_user_connected(user_id):
            logger.info(f"Token potentially cleared for {user_id} during failed delete confirmation.")

    elif callback_data == "cancel_event_delete":
        await delete_pending_deletion(user_id)
        await query.edit_message_text("Event deletion cancelled.")

    elif callback_data.startswith("approve_access_"):
        request_id = callback_data.split("_")[-1]
        logger.info(f"[REQ_ID: {request_id}] Entered approve_access block at {time.time()}")
        await query.answer()
        request_data = await gs.get_calendar_access_request(request_id)
        if not request_data:
            await query.edit_message_text("This access request was not found or may have expired.")
            return
        if request_data.get('status') not in ("pending", "error_notifying_target"):
            await query.edit_message_text(f"This request has already been actioned (status: {request_data.get('status')}).")
            return

        target_user_id = str(user_id)
        if target_user_id != request_data.get('target_user_id'):
            logger.warning(f"User {user_id} tried to approve request {request_id} not meant for them (target: {request_data.get('target_user_id')})")
            await query.edit_message_text("Error: This request is not for you.")
            return

        if not await gs.is_user_connected(int(target_user_id)):
            await query.edit_message_text("You (target user) need to connect your Google Calendar first via /connect_calendar before approving requests.")
            return

        status_updated = await gs.update_calendar_access_request_status(request_id, "approved")
        if status_updated:
            requester_id = request_data['requester_id']
            start_time_iso = request_data['start_time_iso']
            end_time_iso = request_data['end_time_iso']

            events = await cs.get_calendar_events(int(target_user_id), start_time_iso, end_time_iso)

            escaped_requester_name = escape_markdown_v2(str(request_data.get('requester_name', 'them')))
            events_summary_message = f"🗓️ Calendar events for {escaped_requester_name} " \
                                     f"\(from your calendar\) for the period:\n"
            target_tz_str = await gs.get_user_timezone_str(int(target_user_id))
            target_tz = pytz.timezone(target_tz_str) if target_tz_str else pytz.utc

            if events is None:
                events_summary_message += "Could not retrieve events. There might have been an API error."
            elif not events:
                events_summary_message += "No events found in this period."
            else:
                for event in events:
                    time_str = _format_event_time(event, target_tz)
                    raw_summary = event.get('summary')
                    summary_content_for_escaping = "(No title)" if not raw_summary or raw_summary.isspace() else raw_summary
                    summary_text = escape_markdown_v2(summary_content_for_escaping)
                    escaped_time_str = escape_markdown_v2(time_str)
                    events_summary_message += f"\nEvent: {summary_text} \(Time: {escaped_time_str}\)"

            try:
                target_user_display = escape_markdown_v2(str(request_data.get('target_user_id', 'the user')))
                period_start_display = escape_markdown_v2(_format_iso_datetime_for_display(start_time_iso))
                period_end_display = escape_markdown_v2(_format_iso_datetime_for_display(end_time_iso))

                requester_notification_text = (
                    f"🎉 Your calendar access request for {target_user_display}"
                    f"\(for period {period_start_display} to {period_end_display}\) was APPROVED.\n\n"
                    f"{events_summary_message}"
                )

                await context.bot.send_message(
                    chat_id=requester_id,
                    text=requester_notification_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception as e:
                logger.error(f"[REQ_ID: {request_id}] Failed to send approved notification to requester {requester_id}: {e}")

            await query.edit_message_text(text="Access request APPROVED. The requester has been notified with the events.")
        else:
            await query.edit_message_text("Failed to update request status. Please try again.")

    elif callback_data.startswith("deny_access_"):
        await query.answer()
        request_id = callback_data.split("_")[-1]
        logger.info(f"User {user_id} (target) attempts to deny access request {request_id}")
        request_data = await gs.get_calendar_access_request(request_id)

        if not request_data:
            await query.edit_message_text("This access request was not found or may have expired.")
            return
        if request_data.get('status') not in ("pending", "error_notifying_target"):
            await query.edit_message_text(f"This request has already been actioned (status: {request_data.get('status')}).")
            return

        target_user_id = str(user_id)
        if target_user_id != request_data.get('target_user_id'):
            logger.warning(f"User {user_id} tried to deny request {request_id} not meant for them (target: {request_data.get('target_user_id')})")
            await query.edit_message_text("Error: This request is not for you.")
            return

        if await gs.update_calendar_access_request_status(request_id, "denied"):
            requester_id = request_data['requester_id']
            try:
                await context.bot.send_message(
                    chat_id=requester_id,
                    text=f"😔 Your calendar access request for user (ID: {html.escape(request_data.get('target_user_id'))}) "
                         f"for the period {_format_iso_datetime_for_display(request_data['start_time_iso'])} to "
                         f"{_format_iso_datetime_for_display(request_data['end_time_iso'])} was DENIED."
                )
            except Exception as e:
                logger.error(f"Failed to send denied notification to requester {requester_id} for request {request_id}: {e}")

            await query.edit_message_text(text="Access request DENIED. The requester has been notified.")
        else:
            await query.edit_message_text("Failed to update request status. Please try again.")

    elif callback_data.startswith("glist_accept_"):
        await query.answer()
        request_id = callback_data.split("_")[-1]
        request_data = await gs.get_grocery_share_request(request_id)
        if not request_data or request_data.get("status") != "pending":
            await query.edit_message_text("This share request is no longer valid.")
            return
        if str(user_id) != request_data.get("target_user_id"):
            await query.edit_message_text("Error: This request is not for you.")
            return
        if await gs.update_grocery_share_request_status(request_id, "accepted"):
            await gls.merge_grocery_lists(int(request_data["requester_id"]), int(request_data["target_user_id"]))
            await context.bot.send_message(
                chat_id=request_data["requester_id"],
                text="Your grocery list share request was accepted!",
            )
            await query.edit_message_text("You now share the grocery list.")
        else:
            await query.edit_message_text("Failed to update request status.")

    elif callback_data.startswith("glist_decline_"):
        await query.answer()
        request_id = callback_data.split("_")[-1]
        request_data = await gs.get_grocery_share_request(request_id)
        if not request_data or request_data.get("status") != "pending":
            await query.edit_message_text("This share request is no longer valid.")
            return
        if str(user_id) != request_data.get("target_user_id"):
            await query.edit_message_text("Error: This request is not for you.")
            return
        if await gs.update_grocery_share_request_status(request_id, "declined"):
            await context.bot.send_message(
                chat_id=request_data["requester_id"],
                text="Your grocery list share request was declined.",
            )
            await query.edit_message_text("Share request declined.")
        else:
            await query.edit_message_text("Failed to update request status.")

    else:
        await query.answer()
        logger.warning(f"Callback: Unhandled callback data: {callback_data}")
        try:
            await query.edit_message_text("Action not understood or expired.")
        except Exception:
            pass
