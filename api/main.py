import os
import io
import time
import asyncio
import aiofiles
import logging
import uvicorn
import base64
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, UploadFile, File, Form, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from storage.firestore_client import FirestoreClient
from storage.gcs_client import GCSClient
from ai_services.pika_client import PikaClient
from telegram import Update, KeyboardButton, InlineKeyboardButton, WebAppInfo, InlineKeyboardMarkup, ForceReply, ReplyKeyboardMarkup
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

VIDEO_CREDITS = 100

RADOM_TEST_KEY = os.environ.get('RADOM_TEST_KEY')
RADOM_TEST_WEBHOOK_KEY = os.environ.get('RADOM_TEST_WEBHOOK_KEY')

# TESTING
#     "100":  "6cdaa60f-4e45-48b9-bff8-2b06ed51873a",
CREDIT_PLANS = {
    "1000":  "7fcfb9f4-2b2a-4309-af77-b6ac7914fb8e",
    "5000":  "b31886b4-fa4e-41e2-abb5-323f193fc1d8",
    "10000": "688ca38e-ad12-4198-81bc-062bbc7fadf5",
    "25000": "92d3a12c-16fd-45fa-9bec-2afb4fb60cd5",
    "50000": "b9046661-1442-4d87-af62-1b598c957f12",
    "100000": "a5ddd99e-d728-472c-ad51-53562653d1b8"
}

CURRENCY = "USD"
SELECT_GROUP_FOR_CREDITS = range(1)

# "https://pay.radom.com/pay/342b688b-c051-4820-ba9f-26c648cddde3"
# "https://pay.radom.com/pay/fd243359-b3a6-4c7e-a082-6cbab298328b"
# "https://pay.radom.com/pay/22084efe-2acc-46dc-aa83-255e40ec550c"
# "https://pay.radom.com/pay/176362cb-e739-47d3-9232-c025b5d859fc"

firestore_client = FirestoreClient()

gcs_client = GCSClient(bucket_name="pumpreels_files")
pika_client = PikaClient()

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_SECRET_TOKEN = os.environ.get("TELEGRAM_SECRET_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not set!")
    exit(1)

# Create the Telegram Application (PTB v20+)
application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()



async def get_chat_administrators(chat_id: int) -> list:
    """
    Fetches the list of chat administrators for the given chat.

    Parameters:
      chat_id (int): Unique identifier for the target chat or username.

    Returns:
      List of User objects (admins).
    """
    try:
        admins = await application.bot.get_chat_administrators(chat_id)
        return admins
    except Exception as e:
        logger.error(f"Failed to get chat administrators for chat {chat_id}: {e}")
        return []


async def dm_admin_to_buy_credits(admin_user_id: int, group_title: str, group_chat_id: int):
    """
    Sends a private message to the group admin to prompt credit purchase.

    Parameters:
      admin_user_id (int): Telegram user ID of the admin.
      group_title (str): Name of the group.
      group_chat_id (int): Telegram chat ID of the group.
    """
    try:
        safe_title = group_title.replace('-', '\\-').replace('(', '\\(').replace(')', '\\)').replace('.', '\\.').replace('!', '\\!')

        await application.bot.send_message(
            chat_id=admin_user_id,
            text=(
                f"👋 Thanks for adding me to *{safe_title}*\\!\n\n"
                f"Before I can start working in the group, you\\'ll need to activate me by purchasing credits 💰\\.\n\n"
                f"👇 Tap below to top up and pump your coin with PumpReels\\:\n\n"
                f"You can always use /credits to purchase more credits later\\."
            ),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("💳 Buy Credits", callback_data="credits")]]
            )
        )
    except Exception as e:
        logger.error(f"Failed to DM admin {admin_user_id}: {e}")


async def handle_new_group_update(update_json):
    """
    Processes a Telegram update payload and adds a group to Firestore
    when PumpReelsBot is added to the group.

    Parameters:
      update_json (dict): The update payload from Telegram.
    """
    message = update_json.get('message')
    logger.info(message)
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
    # MARK: CHANGE THIS to PumpReelsBot
    if username == 'pumpreelsbot':
        group = message.get('chat')
        # Add the group to Firestore using your client

        # After confirming it's pumpreelsbot:
        group_chat_id = group.get('id')
        group_title = group.get('title')

        admins = await get_chat_administrators(group_chat_id)
        if not admins:
            logger.warning("No admins found, can't prompt to buy credits.")
            return

        # Find the creator or someone with can_manage_chat
        for admin in admins:
            if admin.status == 'creator' or admin.can_manage_chat:
                creator_user_id = admin.user.id
                await dm_admin_to_buy_credits(creator_user_id, group_title, group_chat_id)
                break
        doc_id = firestore_client.create_group(data=group, creator_user_id=creator_user_id)
        logger.info(f"Group added to Firestore: {doc_id}")
    else:
        logger.info("New bot added is not pumpreelsbot. No action taken.")


async def get_video_url(video_id: str, chat_id: int, message_id: int, user_identifier: str) -> str:
    start_time = time.monotonic()
    max_wait_seconds = 300  # 5 minutes
    while time.monotonic() - start_time < max_wait_seconds:
        try:
            # Fetch current status info
            video = pika_client.check_video_status(video_id=video_id)
            logger.info(video)
            status = video.get('status', 'queued')
            progress = video.get('progress', 0)
            url = video.get('url', '')

            logger.info("Pika Video Status: %s", status)
            logger.info("Pika Video URL: %s", url)

            # Handle different statuses
            if status in ['queued', 'pending']:
                # Not started yet, just keep polling
                logger.info("Task is in '%s' state. Waiting for it to start...", status)

            elif status == 'started':
                logger.info("Task {} with {}% progress".format(status, progress))

                try:
                    await application.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=f"@{user_identifier} your video is rendering... {progress}%"
                    )
                except BadRequest as e:
                    # If the error message is "Message is not modified", ignore it.
                    # Otherwise, re-raise the exception.
                    if "Message is not modified" in str(e):
                        pass
                    else:
                        raise e

            elif status == 'finished':
                logger.info(video)
                url = video.get('url', '')
                # All done, return URL if found
                if url and len(url) > 0:
                    return url
                else:
                    logger.error("Video succeeded but no output found: %s", video)
                    return None

            elif status in ['failed', 'canceled']:
                try:
                    firestore_client.add_credits(str(chat_id), VIDEO_CREDITS)
                    logger.info(f"Refunded {VIDEO_CREDITS} credit to group %s", group_id)
                except Exception as e:
                    logger.error("Failed to refund credit to %s: %s", group_id, e)
                return None

            else:
                # Handle unexpected status values with a log
                logger.info("Task status is '%s'. Waiting...", status)

        except Exception as e:
            logger.error("Error retrieving task: %s", e)
            return None

        # Sleep briefly before polling again
        await asyncio.sleep(0.1)

# ------------------
# Helper function to process the video generation.
# This function downloads the image, encodes it, calls the runway API,
# deletes temporary files and bot messages, and sends the final video.
# ------------------
async def process_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_text: str):
    chat_id = update.effective_chat.id
    user_identifier = update.message.from_user.username or update.message.from_user.first_name

    # MARK: DECREMENT CREDITS
    try:
        firestore_client.decrement_credits(str(chat_id), VIDEO_CREDITS)
    except ValueError as e:
        await update.message.reply_text(
            f"⚠️ Your group ran out of credits!"
            f"The admin needs to buy more credits to continue the pump 🚀"
        )
        return ConversationHandler.END

    processing_msg = await application.bot.send_animation(
        chat_id=chat_id,
        animation="https://pumpreels-mini-app.netlify.app/rendering.gif",
        caption=f"@{user_identifier} video is in queue..."
    )

    msg_chat_id = processing_msg.chat.id
    msg_id = processing_msg.message_id

    file_id = context.user_data.get("file_id")
    file_obj = await application.bot.get_file(file_id)
    file_bytes = await file_obj.download_as_bytearray()

    image_io = io.BytesIO(file_bytes)
    image_io.name = "image.jpg"

    video_url = None
    try:
        pika_result = pika_client.generate_video(
            image_file="image.jpg",
            image_bytes=image_io,
            prompt_text=prompt_text,
            negative_prompt='blurry, low quality, distorted, warped, deformed, color shifted, miscolored, incomplete subject, missing subject, cropped subject',
            duration=5,
            resolution='720p'
        )
        video_id = pika_result.get('video_id', '')
        logger.info("Video started with id: %s", video_id)
        video_url = await get_video_url(video_id, msg_chat_id, msg_id, user_identifier)
    except Exception as e:
        logger.error("Error generating video: %s", e)

    try:
        await application.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
        logger.info("Deleted processing message: %s", processing_msg.message_id)
    except Exception as e:
        logger.error("Failed to delete processing message (%s): %s", processing_msg.message_id, e)

    # Send the final video or an error message.
    if video_url:
        caption = f"@{user_identifier} your video is ready!\n\n{prompt_text}"
        await application.bot.send_video(chat_id=chat_id, video=video_url, caption=caption)
    else:
        await application.bot.send_message(chat_id=chat_id, text="Sorry, an error occurred while processing your video.")

# ------------------
# Telegram Handlers (Async)
# ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    args = context.args

    if args:
        payload = args[0]

        if payload == "payment_success":
            await update.message.reply_text(
                "✅ Payment successful\\! Your group can start generating videos",
                parse_mode="MarkdownV2"
            )
            return ConversationHandler.END

        elif payload == "payment_cancelled":
            await update.message.reply_text(
                "❌ Payment was canceled. You can try again with /credits",
                parse_mode="MarkdownV2"
            )
            return ConversationHandler.END

    start_info = """🚀 *Experience the future of Telegram community engagement with PumpReelsBot\!*

🔥 Transform your *memecoin* into viral AI\-powered videos that captivate your audience and boost engagement\.

🎥 *What PumpReelsBot Can Do for You:*
\- 🧠 *AI\-Generated Videos* that bring your memecoin to life
\- 🚀 *Automated Content Creation* for your Telegram community
\- 🎯 *Drive Hype & Engagement* like never before

🔹 Simply upload an image and select a theme—our AI will generate a high\-quality video in seconds\.

📢 *To get started, add* [@pumpreels\\_bot](https://t.me/pumpreelsbot) *to your chat and you will receive a message with further instructions\!* 🚀🔥
"""

    await update.message.reply_text(
        start_info.strip(),
        parse_mode="MarkdownV2"
    )

    return ConversationHandler.END


async def show_credits_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, group_data: dict) -> int:
    message = update.message or update.callback_query.message

    credits = group_data.get('credits', 0)
    group_title = group_data.get('title', 'your group')

    credit_info = f"""🚀 *PumpReels Video Credit System – {group_title}*

🎥 *Current Credits:* `{credits}` credits
💰 *1 Video (5 sec) = 100 credits*

📦 *Top Up Options:*
➤ 1,000 credits → `$9.50`
➤ 5,000 credits → `$45.00`
➤ 10,000 credits → `$88.00`
➤ 25,000 credits → `$212.50`
➤ 50,000 credits → `$420.00`
➤ 100,000 credits → `$800.00`
"""

    keyboard = [
        [InlineKeyboardButton("1,000 Credits", callback_data="1000"),
         InlineKeyboardButton("5,000 Credits", callback_data="5000")],
        [InlineKeyboardButton("10,000 Credits", callback_data="10000"),
         InlineKeyboardButton("25,000 Credits", callback_data="25000")],
        [InlineKeyboardButton("50,000 Credits", callback_data="50000"),
         InlineKeyboardButton("100,000 Credits", callback_data="100000")]
    ]

    credit_info_msg = await message.reply_text(
        credit_info.strip(),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    context.user_data['credit_info_msg_id'] = credit_info_msg.message_id
    return ConversationHandler.END


async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    message = update.message or update.callback_query.message
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    # 🔒 Check 1: If this is a group/supergroup, reject it
    if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply_text(
            f"⚠️ Please have the *admin of {chat.title}* top up your credits in a private chat with @pumpreelsbot.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # 🧠 Get all groups this user manages
    groups = firestore_client.get_groups_by_creator(user.id)
    if not groups:
        await message.reply_text(
            "❌ You’re not an admin of any PumpReels groups.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # ✅ If one group, skip selection
    if len(groups) == 1:
        logger.info(groups)
        context.user_data['selected_group_id'] = groups[0]['group_id']
        return await show_credits_menu(update, context, groups[0])

    # 🎯 If multiple groups, prompt user to pick one
    keyboard = [
        [InlineKeyboardButton(group["title"], callback_data=f"select_chat_{group['group_id']}")]
        for group in groups
    ]
    select_group_msg = await message.reply_text(
        "🪙 Which group would you like to buy credits for?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    context.user_data['select_group_msg_id'] = select_group_msg.message_id
    return SELECT_GROUP_FOR_CREDITS


async def pumpreels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await send_open_mini_app_card(update, context)


async def generate_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows user to create a video by sending `/generate_video my text here` as the caption
    of an attached photo. If missing image/text, send a fallback with a "rich card" that
    links to the mini app.
    """
    chat = update.effective_chat
    chat_id = chat.id

    if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await update.message.reply_text("Use this command in a group chat!")
        return ConversationHandler.END

    group_data = firestore_client.get_group(str(chat_id))

    if group_data is None:
        await update.message.reply_text("Your group is not registered. Please contact PumpReels for help.")
        return ConversationHandler.END

    credits = group_data.get('credits', 0)

    if credits == 0 or credits < VIDEO_CREDITS:
        await update.message.reply_text(
            f"⚠️ Your group has {credits} credits left.\n"
            f"The admin needs to buy more credits to continue the pump 🚀"
        )
        return ConversationHandler.END

    # 1) Check if user posted a photo.
    #    If the user typed `/generate_video` + text in a text-only message, there's no photo -> fallback.
    #    We expect a single message that has BOTH photo + caption (the command plus user text).
    if not update.message or not update.message.photo:
        # Missing the photo -> fallback
        await send_open_mini_app_card(update, context)
        return

    # 2) Extract the text from the photo caption (where the user typed `/generate_video ...`).
    #    - update.message.caption might look like "/generate_video my text here"
    #    - We want to parse out "my text here"
    caption = update.message.caption or ""  # fallback empty string if somehow missing
    pieces = caption.split(None, 1)  # split into two parts: command and the rest
    if len(pieces) < 2:
        # Means they only typed "/generate_video" with no extra text
        await send_open_mini_app_card(update, context)
        return

    # pieces[0] == "/generate_video"
    # pieces[1] == "my text here"
    prompt_text = pieces[1].strip()
    logger.info(prompt_text)
    if not prompt_text:
        # no user text
        await send_open_mini_app_card(update, context)
        return

    # 3) We have a photo and the user text -> proceed to process_video
    photo = update.message.photo[-1]  # the largest resolution photo
    file_id = photo.file_id
    context.user_data["file_id"] = file_id

    # Now call process_video with the user prompt
    await process_video(update, context, prompt_text)


async def send_group_mini_app_card(group_id: str):
    group_data = firestore_client.get_group(group_id)
    if not group_data:
        return

    caption = (
        f"{group_data.get('title')} has {group_data.get('credits')} credits remaining\n"
        f"Generate your AI Video with our Mini App\\\n"
        f"📱 [Open Mini App](https://t.me/pumpreelsbot/pumpreelsapp?startapp={group_id})\n\n"
        f"OR ENTER\n"
        f"\\/generate\\_video \\[your prompt\\] and attach an image to create your AI video instantly\\\n\n"
        f"Powered by \\@PumpReelsBot"
    )

    keyboard = [
        [InlineKeyboardButton(text="📱Open Mini App", url=f"https://t.me/pumpreelsbot/pumpreelsapp?startapp={group_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await application.bot.send_animation(
        chat_id=int(group_id),
        animation="https://pumpreels-mini-app.netlify.app/rendering.gif",
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )


async def send_open_mini_app_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    group_data = firestore_client.get_group(str(chat_id))
    caption = (
        f"{group_data.get('title')} has {group_data.get('credits')} credits remaining\n"
        f"Generate your AI Video with our Mini App\\\n"
        f"📱 [Open Mini App](https://t.me/pumpreelsbot/pumpreelsapp?startapp={chat_id})\n\n"
        f"OR ENTER\n"
        f"\\/generate\\_video \\[your prompt\\] and attach an image to create your AI video instantly\\\n\n"
        f"Powered by \\@PumpReelsBot"
    )


    keyboard = [
        [InlineKeyboardButton(text="📱Open Mini App", url=f"https://t.me/pumpreelsbot/pumpreelsapp?startapp={chat_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_animation(
        animation="https://pumpreels-mini-app.netlify.app/rendering.gif",
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=reply_markup
    )


async def handle_group_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    select_group_msg_id = context.user_data.get("select_group_msg_id")
    if select_group_msg_id:
        try:
            await query.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete group selection message: {e}")

    data = query.data
    logging.info(' --- TESTING --- ')
    logging.info(f'data received: {data}')
    if not data.startswith("select_chat_"):
        return ConversationHandler.END

    group_id = data.replace("select_chat_", "")
    group_data = firestore_client.get_group(group_id)
    if not group_data:
        await query.message.reply_text("❌ Group not found or deleted.")
        return ConversationHandler.END

    context.user_data['selected_group_id'] = group_id
    return await show_credits_menu(update, context, group_data)


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.message.web_app_data.data
    logger.info(f"Received data from web app: {data}")

    try:
        payload = json.loads(data)
        video_url = payload.get("video_url")

        if not video_url:
            await update.message.reply_text("Something went wrong — no video URL received.")
            return

        await update.message.reply_video(
            video=video_url,
            caption="🎬 Here's your AI-generated video!"
        )

    except Exception as e:
        logger.error(f"Error handling web_app_data: {e}")
        await update.message.reply_text("Error processing video. Please try again.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Video cancelled.")
    return ConversationHandler.END


async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    await cq.answer()
    credits_str = cq.data
    group_id = context.user_data.get('selected_group_id')

    if not group_id:
        await cq.message.reply_text("❌Command timed out. Please restart the /credits flow.")
        return

    # Build the Radom checkout
    try:
        checkout_url = create_checkout_session(
            CREDIT_PLANS[credits_str],
            group_id,
            credits_str
        )
    except Exception:
        await cq.answer("❌ Couldn’t start checkout, try again.", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(f"💳 Get {credits_str} credits", url=checkout_url)]
    ]

    await cq.message.reply_text(
        "Your checkout session is ready:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def create_checkout_session(product_id: str, chat_id: int, credits_str: str) -> str:
    """
    Returns a checkoutSessionUrl with telegram_group_id metadata.
    """
    payload = {
        "lineItems":  [{"productId": product_id}],
        "currency":   "USD",
        "gateway": {
                "managed": {
                    "methods": [
                        # MARK: CHANGE THESE TO PROD NETWORKS
                        {"network": "Bitcoin"},
                        {"network": "Solana"},
                        {"network": "Ethereum"},
                        # {"network": "Base"},
                        # {"network": "Fiat"},
                    ]
                }
            },
        "successUrl": "https://t.me/pumpreelsbot?start=payment_success",
        "cancelUrl": "https://t.me/pumpreelsbot?start=payment_cancelled",
        "metadata": [
            {
                "key": "telegram_group_id",
                "value": str(chat_id)
            },
            {
                "key": "credits_str",
                "value": credits_str
            }
        ],
        "expiresAt": 9999999999,
    }
    logger.info(payload)
    logger.info("PAYLOAD")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"{RADOM_TEST_KEY}",
    }
    r = requests.post(
        "https://api.radom.com/checkout_session",
        json=payload, headers=headers, timeout=10
    )
    logger.info("Radom status %s", r.status_code)
    logger.info("Radom body   %s", r.text)
    r.raise_for_status()
    return r.json()["checkoutSessionUrl"]


credits_conversation_handler = ConversationHandler(
    entry_points=[
        CommandHandler("credits", credits),
        CallbackQueryHandler(credits, pattern=r"^credits$"),
    ],
    states={
        SELECT_GROUP_FOR_CREDITS: [
            CallbackQueryHandler(handle_group_selection, pattern=r"^select_chat_-?\d+")
        ]
    },
    fallbacks=[],
)
application.add_handler(credits_conversation_handler)


application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("pumpreels", pumpreels))
application.add_handler(CommandHandler("generate_video", generate_video_command))
generate_video_handler = MessageHandler(
    filters.PHOTO & filters.CaptionRegex(r"^/generate_video\b"),
    generate_video_command
)
application.add_handler(generate_video_handler)
# application.add_handler(
#     CallbackQueryHandler(credits, pattern=r"^credits$")
# )
application.add_handler(CallbackQueryHandler(
        pay_callback,
        pattern=r"^(1000|5000|10000|25000|50000|100000)$"
))
application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))


# ------------------
# FastAPI App with Lifespan Event Handlers
# ------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Telegram Application...")
    await application.initialize()
    logger.info("Telegram Application initialized.")
    yield

app = FastAPI(lifespan=lifespan)

origins = [
    "https://pumpreels-mini-app.netlify.app",  # your web app origin
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # or ["*"] for all
    allow_credentials=True,
    allow_methods=["*"],  # or limit to ["GET", "POST"] etc.
    allow_headers=["*"],
)

# MARK: GET RID OF THIS EVENTUALLY
# logger.info(update_json)
# logger.info('\n==========\n')
@app.post("/webhook")
async def telegram_webhook(request: Request):
    update_json = await request.json()
    logger.info(update_json)
    header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    logger.info(header_token)

    if header_token != TELEGRAM_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    update_json = await request.json()
    await handle_new_group_update(update_json)

    update = Update.de_json(update_json, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.post("/radomWebhook")
async def radom_webhook(request: Request):
    radom_data = await request.json()
    logger.info(f"Received Radom Webhook: {radom_data}")

    event_type = radom_data.get("eventType")

    if event_type == "managedPayment":
        try:
            firestore_client.create_transaction(radom_data)
            logger.info("✅ Transaction document created.")
        except Exception as e:
            logger.error(f"❌ Failed to create transaction: {e}")
    elif event_type == "paymentTransactionConfirmed":
        try:
            event_data = radom_data.get("eventData", {}).get("paymentTransactionConfirmed", {})
            transaction_hash = event_data.get("transactionHash")
            if not transaction_hash:
                logger.warning("⚠️ No transactionHash found.")
                return {"ok": False}

            result = firestore_client.confirm_transaction_by_tx_hash(transaction_hash)

            if isinstance(result, str) and result.startswith("-"):  # group_id is returned
                await send_group_mini_app_card(result)
                logger.info(f"✅ Confirmed and notified group {result}")
            elif result == "already_confirmed":
                logger.info(f"⚠️ Transaction {transaction_hash} was already confirmed.")
            else:
                logger.warning(f"❌ No transaction found for hash {transaction_hash}")

        except Exception as e:
            logger.error(f"❌ Error in paymentTransactionConfirmed handler: {e}")
    else:
        logger.info(f"Unhandled Radom event type: {event_type}")

    return {"ok": True}


# ENDPOINTS FOR MINI APP
@app.post("/getGroup")
async def get_group(
    group_id: str = Form(...),
):
    group_data = firestore_client.get_group(group_id)
    return group_data


@app.post("/generateVideo")
async def generate_video(
    prompt_text: str = Form(...),
    image: UploadFile = File(...),
    group_id: str = Form(...)
):
    """
    1) Receives an image + prompt text.
    2) Calls PikaClient to start video generation.
    3) Returns an immediate response with video_id, not the final video.
    """

    try:
        firestore_client.decrement_credits(group_id, VIDEO_CREDITS)
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": "insufficient_credits", "message": "Your group ran out of credits! The admin needs to buy more credits to continue the pump 🚀"}
        )

    # Read the uploaded file into memory
    try:
        image_bytes = await image.read()
    except Exception as e:
        logger.error("Failed to read uploaded image: %s", e)
        raise HTTPException(status_code=400, detail="Could not read the image file.")

    # Optional: do any validation or modifications of prompt_text
    user_prompt = prompt_text.strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="No prompt_text was provided.")

    # Example negative prompt, resolution, etc.
    negative_prompt = "blurry, low quality, distorted, warped, deformed, color shifted"
    duration = 5
    resolution = "720p"
    image_io = io.BytesIO(image_bytes)
    image_io.name = "image.jpg"

    # Call your PikaClient generate_video method
    try:
        result = pika_client.generate_video(
            image_file="image.jpg",
            image_bytes=image_io,
            prompt_text=user_prompt,
            negative_prompt=negative_prompt,
            duration=duration,
            resolution=resolution
        )
    except Exception as e:
        logger.error("Error calling generate_video: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create the video.")

    video_id = result.get("video_id")
    if not video_id:
        raise HTTPException(status_code=500, detail="No video_id returned from PikaClient.")

    # Return an immediate JSON response with the new video_id
    return {
        "video_id": video_id,
        "status": "queued"  # or whatever initial status you want to indicate
    }


@app.get("/getVideoStatus")
async def get_video_status(
    video_id: str,
    group_id: str
):
    """
    1) Takes a 'video_id' as a query param.
    2) Checks with PikaClient for the current status, progress, or final URL.
    3) Returns the info as JSON (including the final video URL if finished).
    """
    try:
        video_data = pika_client.check_video_status(video_id=video_id)
    except Exception as e:
        logger.error("Error checking video status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to check video status.")

    # PikaClient might return something like:
    # {
    #   'status': 'finished',  # or 'queued' / 'started' / 'failed'
    #   'progress': 100,
    #   'url': 'https://...'
    # }
    if not video_data:
        raise HTTPException(status_code=404, detail="Video data not found for that video_id.")

    status = video_data.get('status', 'unknown')
    progress = video_data.get('progress', 0)
    url = video_data.get('url', '')

    if status in ["failed", "canceled"]:
        try:
            firestore_client.add_credits(group_id, VIDEO_CREDITS)
            logger.info("Refunded %s credits to group %s for failed video %s", VIDEO_CREDITS, group_id, video_id)
        except Exception as e:
            logger.error("Failed to refund credits to group %s: %s", group_id, e)

    # If you want to return the entire dictionary:
    return {
        "video_id": video_id,
        "status": status,
        "progress": progress,
        "url": url  # Only valid if status == 'finished'
    }


@app.post("/sendVideo")
async def send_video(
    group_id: int = Form(...),
    video_url: str = Form(...),
    user_identifier: str = Form(...),
    prompt_text: str = Form(...)
):
    try:
        await application.bot.send_video(
            chat_id=group_id,
            video=video_url,
            caption = f"@{user_identifier} your video is ready!\n\n{prompt_text}"
        )
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/")
async def root():
    return {"message": "Hello, FastAPI Telegram bot!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
