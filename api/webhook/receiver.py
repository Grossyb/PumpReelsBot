from fastapi import APIRouter, Request
from telegram import Update
from telegram_bot.bot import application  # Import the Telegram bot
from firestore.client import FirestoreClient
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

firestore_client = FirestoreClient()

def handle_new_group_update(update_json: dict):
    """
    Processes a Telegram update payload and adds a group to Firestore
    when PumpReelsBot is added to a new group.

    Args:
        update_json (dict): The update payload from Telegram.
    """
    message = update_json.get('message')
    if not message:
        return  # No message, nothing to do

    new_chat_participant = message.get('new_chat_participant')
    if not new_chat_participant:
        return  # No new participant data

    # Check if the new participant is a bot
    is_bot = new_chat_participant.get('is_bot', False)
    if not is_bot:
        return  # Not a bot; no action needed

    # Check if this is our bot (PumpReelsBot)
    username = new_chat_participant.get('username')
    if username == 'PumpReelsBot':  # Change this to your bot's username
        group = message.get('chat')
        doc_id = firestore_client.create_group(data=group)
        logger.info(f"Group added to Firestore: {doc_id}")
    else:
        logger.info(f"New bot added is not PumpReelsBot. No action taken.")

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """
    FastAPI endpoint to receive and process Telegram webhook updates.
    """
    update_json = await request.json()
    logger.info(f"Received update: {update_json}")

    # Handle group updates separately
    handle_new_group_update(update_json)

    # Convert JSON into a Telegram Update object
    update = Update.de_json(update_json, application.bot)

    # Process the update through the Telegram bot
    await application.process_update(update)

    return {"ok": True}

@router.get("/")
async def root():
    """
    Basic endpoint to check if the FastAPI server is running.
    """
    return {"message": "PumpReels Telegram Bot is running!"}
