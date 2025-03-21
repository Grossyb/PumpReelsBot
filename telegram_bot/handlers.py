import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from firestore.client import FirestoreClient
from telegram_bot.messages import START_MESSAGE, CREDITS_MESSAGE
from telegram_bot.keyboards import generate_credit_buttons

logger = logging.getLogger(__name__)
firestore_client = FirestoreClient()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        START_MESSAGE,
        parse_mode="MarkdownV2"
    )
    return ConversationHandler.END

async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    group_data = firestore_client.get_group(str(chat_id))
    credits = group_data.get("credits", 0) if group_data else 0

    credit_info = CREDITS_MESSAGE.format(credits=credits)
    await update.message.reply_text(
        credit_info,
        reply_markup=generate_credit_buttons(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def pumpreels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    group_data = firestore_client.get_group(str(chat_id))

    if not group_data:
        await update.message.reply_text("Your group is not registered. Please contact admin.")
        return ConversationHandler.END

    credits = group_data.get("credits", 0)
    if credits == 0:
        await update.message.reply_text("Your group has no credits left. Please purchase more credits to continue.",
                                        reply_markup=generate_credit_buttons())
        return ConversationHandler.END

    await update.message.reply_text(f"Welcome to PumpReels! Your group has {credits} credits remaining.")
    return ConversationHandler.END
