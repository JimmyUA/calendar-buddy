import html
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, KeyboardButtonRequestUsers
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .helpers import _get_user_tz_or_prompt

logger = logging.getLogger(__name__)


async def _handle_glist_share_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None and update.message.users_shared is not None
    requester_id = str(update.effective_user.id)
    received_request_id = update.message.users_shared.request_id
    expected_request_id = context.user_data.pop("select_user_request_id", None)

    if expected_request_id is None or received_request_id != expected_request_id:
        await context.bot.send_message(chat_id=requester_id, text="This user selection is invalid or expired.")
        return

    if not update.message.users_shared.users:
        await context.bot.send_message(chat_id=requester_id, text="No user was selected.")
        return

    target_user = update.message.users_shared.users[0]
    target_user_id = str(target_user.user_id)
    if target_user_id == requester_id:
        await context.bot.send_message(chat_id=requester_id, text="You cannot share the list with yourself.")
        return

    requester_name = update.effective_user.first_name or "User"
    mcp_client = context.application.bot_data["mcp_client"]
    request_doc_id = await mcp_client.call_tool("add_grocery_share_request", requester_id=requester_id, requester_name=requester_name, target_user_id=target_user_id)
    if not request_doc_id:
        await context.bot.send_message(chat_id=requester_id, text="Failed to store share request.")
        return

    await context.bot.send_message(
        chat_id=requester_id,
        text=f"Grocery list share request sent to {target_user.first_name or target_user.username}.",
    )

    inline_keyboard = [
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"glist_accept_{request_doc_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"glist_decline_{request_doc_id}")
        ]
    ]
    inline_reply_markup = InlineKeyboardMarkup(inline_keyboard)
    await context.bot.send_message(
        chat_id=target_user_id,
        text=f"{requester_name} wants to share grocery lists with you.",
        reply_markup=inline_reply_markup,
    )


async def glist_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempting to add items to grocery list. Args: {context.args}")

    if not context.args:
        logger.info(f"User {user_id} called /glist_add without items.")
        await update.message.reply_text(
            "Please provide items to add. Usage: /glist_add item1 item2 ...",
        )
        return

    items_to_add = list(context.args)
    mcp_client = context.application.bot_data["mcp_client"]
    if await mcp_client.call_tool("add_to_grocery_list", user_id=user_id, items_to_add=items_to_add):
        logger.info(f"Successfully added {len(items_to_add)} items for user {user_id}.")
        await update.message.reply_text(
            f"Added: {', '.join(items_to_add)} to your grocery list.",
        )
    else:
        logger.error(f"Failed to add items to grocery list for user {user_id}.")
        await update.message.reply_text(
            "Sorry, there was a problem adding items to your grocery list.",
        )


async def glist_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requesting to show grocery list.")

    mcp_client = context.application.bot_data["mcp_client"]
    grocery_list = await mcp_client.call_tool("get_grocery_list", user_id=user_id)

    if grocery_list is None:
        logger.error(f"Failed to retrieve grocery list for user {user_id} (gs returned None).")
        await update.message.reply_text(
            "Sorry, there was an error trying to get your grocery list.",
        )
    elif not grocery_list:
        logger.info(f"Grocery list is empty for user {user_id}.")
        await update.message.reply_text(
            "🛒 Your grocery list is empty! Add items with /glist_add item1 item2 ...",
        )
    else:
        logger.info(f"Retrieved {len(grocery_list)} items for user {user_id}.")
        message_lines = ["🛒 Your Grocery List:"]
        for item in grocery_list:
            message_lines.append(f"- {html.escape(item)}")

        await update.message.reply_text("\n".join(message_lines), parse_mode=ParseMode.HTML)


async def glist_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    logger.info(f"User {user_id} requesting to clear grocery list.")
    mcp_client = context.application.bot_data["mcp_client"]
    if await mcp_client.call_tool("delete_grocery_list", user_id=user_id):
        logger.info(f"Successfully cleared grocery list for user {user_id}.")
        await update.message.reply_text("🗑️ Your grocery list has been cleared.")
    else:
        logger.error(f"Failed to clear grocery list for user {user_id}.")
        await update.message.reply_text(
            "Sorry, there was a problem clearing your grocery list.",
        )


async def share_glist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    assert context.user_data is not None

    requester_id = update.effective_user.id
    keyboard_request_id = int(datetime.now().timestamp())
    context.user_data["share_glist_flow"] = True
    context.user_data["select_user_request_id"] = keyboard_request_id

    button_request_users_config = KeyboardButtonRequestUsers(
        request_id=keyboard_request_id, user_is_bot=False, max_quantity=1
    )
    button_select_user = KeyboardButton(
        text="Select User To Share GList", request_users=button_request_users_config
    )
    reply_markup = ReplyKeyboardMarkup(
        keyboard=[[button_select_user]], resize_keyboard=True, one_time_keyboard=True
    )

    await update.message.reply_text(
        "Choose a contact to share your grocery list with:", reply_markup=reply_markup
    )
