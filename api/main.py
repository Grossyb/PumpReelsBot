import os
import io
import time
import asyncio
import aiofiles
import logging
import uvicorn
import base64
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from storage.firestore_client import FirestoreClient
from storage.gcs_client import GCSClient
from ai_services.pika_client import PikaClient
from telegram import Update, InlineKeyboardButton, WebAppInfo, InlineKeyboardMarkup, ForceReply
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

# Conversation states: IMAGE -> PROMPT_TEMPLATES -> PROMPT
# IMAGE, PROMPT_TEMPLATES, PROMPT = range(3) FIX THIS
IMAGE, PROMPT = range(2)

prompt_templates = {
    "TO THE MOON": "It is in the cockpit of a spacecraft, pressing buttons and gazing out at the Moon through the window",
    "WEN LAMBO": "it is driving a red lamborghini down a road in South Beach, sunny, luxurious background",
    "WAGMI": "It is dressed in a black suit with a tie, sitting in private jet seat next to window. Champagne on table, luxurious interior",
}


VIDEO_CREDITS = 50

# RADOM_TEST_KEY = os.environ.get('RADOM_TEST_KEY')
# RADOM_WEBHOOK_KEY = os.environ.get('RADOM_WEBHOOK_KEY')

firestore_client = FirestoreClient()

gcs_client = GCSClient(bucket_name="pumpreels_files")
pika_client = PikaClient()

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN not set!")
    exit(1)

# Create the Telegram Application (PTB v20+)
application = Application.builder().token(TELEGRAM_TOKEN).build()

def handle_new_group_update(update_json):
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
        doc_id = firestore_client.create_group(data=group)
        logger.info("Group added to Firestore:", doc_id)
    else:
        logger.info("New bot added is not pumpreelsbot. No action taken.")


async def get_video_url(video_id: str, chat_id: int, message_id: int) -> str:
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
                        caption=f"Rendering your video... {progress}%"
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
                logger.error("Task failed or was canceled: %s", video)
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

    processing_msg = await application.bot.send_animation(
        chat_id=chat_id,
        animation="https://comforting-druid-bafd91.netlify.app/rendering.gif",
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
        video_url = await get_video_url(video_id, msg_chat_id, msg_id)
    except Exception as e:
        logger.error("Error generating video: %s", e)

    # Delete previous bot messages.
    message_keys = [
        "inline_button_message_id",
        "image_prompt_message_id",
        "prompt_templates_message_id",
        "prompt_prompt_message_id"
    ]
    for key in message_keys:
        message_id = context.user_data.get(key)
        if message_id:
            try:
                await application.bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.info("Deleted bot message %s: %s", key, message_id)
            except Exception as e:
                logger.error("Failed to delete bot message %s (%s): %s", key, message_id, e)

    try:
        await application.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
        logger.info("Deleted processing message: %s", processing_msg.message_id)
    except Exception as e:
        logger.error("Failed to delete processing message (%s): %s", processing_msg.message_id, e)

    # Send the final video or an error message.
    if video_url:
        caption = f"@{user_identifier} video is ready!\n\n{prompt_text}"
        await application.bot.send_video(chat_id=chat_id, video=video_url, caption=caption)
    else:
        await application.bot.send_message(chat_id=chat_id, text="Sorry, an error occurred while sprocessing your video.")

# ------------------
# Telegram Handlers (Async)
# ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    start_info = """🚀 *Experience the future of Telegram community engagement with PumpReelsBot\!*

🔥 Transform your *memecoin* into viral AI\-powered videos that captivate your audience and boost engagement\.

🎥 *What PumpReelsBot Can Do for You:*
\- 🧠 *AI\-Generated Videos* that bring your memecoin to life
\- 🚀 *Automated Content Creation* for your Telegram community
\- 🎯 *Drive Hype & Engagement* like never before

🔹 Simply upload an image and select a theme—our AI will generate a high\-quality video in seconds\.

📢 *To get started, add* [@pumpreels\\_bot](https://t.me/pumpreels_bot) *to your group and start creating\!* 🚀🔥
"""

    await update.message.reply_text(
        start_info.strip(),
        parse_mode="MarkdownV2"
    )

    return ConversationHandler.END



async def credits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    group_data = firestore_client.get_group(str(chat_id))

    # Default to 0 if no data found
    credits = group_data.get('credits', 0) if group_data else 0
    credit_info = f"""🚀 *PumpReels Video Credit System*

🎥 *Your Current Credits:* `{credits}` credits (updated in real-time)
💰 *1 Video (5 sec) = 25 credits* (5 credits per second)

🔹 *Need more credits? Purchase below!*

📦 *Bulk Credit Discounts (Best Value!)*
Pre-purchase credits at a discounted rate and get more value!

➤ *100 Videos (2,500 credits) →* `$140.00`  _(🚀 $1.40 per video)_
➤ *250 Videos (6,250 credits) →* `$325.00`  _(🔥 $1.30 per video)_
➤ *500 Videos (12,500 credits) →* `$550.00`  _(⚡ $1.10 per video)_
➤ *1,000 Videos (25,000 credits) →* `$1,000.00`  _(💎 $1.00 per video)_
"""

    keyboard = [
        [InlineKeyboardButton("2,500 Credits", url="https://pay.radom.com/pay/342b688b-c051-4820-ba9f-26c648cddde3"),
         InlineKeyboardButton("6,250 Credits", url="https://pay.radom.com/pay/fd243359-b3a6-4c7e-a082-6cbab298328b")],
        [InlineKeyboardButton("12,500 Credits", url="https://pay.radom.com/pay/22084efe-2acc-46dc-aa83-255e40ec550c"),
         InlineKeyboardButton("25,000 Credits", url="https://pay.radom.com/pay/176362cb-e739-47d3-9232-c025b5d859fc")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        credit_info.strip(),
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    return ConversationHandler.END


async def pumpreels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id

    try:
        group_data = firestore_client.get_group(str(chat_id))

        if group_data is None:
            await update.message.reply_text("Your group is not registered. Please contact PumpReels for help.")
            return ConversationHandler.END

        credits = group_data.get('credits', 0)

        if credits == 0 or credits < VIDEO_CREDITS:
            keyboard = [[InlineKeyboardButton("Buy Credits", callback_data="buy_credits")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"Your group has {credits} credits left. Please purchase more credits to continue.",
                reply_markup=reply_markup
            )
            return ConversationHandler.END

        keyboard = [[InlineKeyboardButton("Generate AI Video", callback_data="generate_video")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message:
            sent = await update.message.reply_text(
                f"Welcome to PumpReels! Your group has {credits} credits remaining.",
                reply_markup=reply_markup
            )
            context.user_data["inline_button_message_id"] = sent.message_id

        return ConversationHandler.END

    except Exception as e:
        # Handle any errors
        print(f"Error in start command: {str(e)}")
        await update.message.reply_text("An error occurred. Please try again later.")
        return ConversationHandler.END


async def generate_video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Allows user to create a video by sending `/generate_video my text here` as the caption
    of an attached photo. If missing image/text, send a fallback with a "rich card" that
    links to the mini app.
    """
    chat_id = update.effective_chat.id

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
    logger.info("THEON GREYJOY")
    logger.info(caption)
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
    #    Same logic as your existing “receive_image” or “process_video” flow
    photo = update.message.photo[-1]  # the largest resolution photo
    file_id = photo.file_id
    context.user_data["file_id"] = file_id

    # Now call process_video with the user prompt
    await process_video(update, context, prompt_text)


async def send_open_mini_app_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) Build an inline keyboard with a link
    #    Replace the URL with your actual Web App link, for example:
    #    https://t.me/<your_bot_username>?start=someWebappParam
    caption = (
        "✨ Generate AI videos for your memecoin!\n"
        "Generate your AI Video with our Mini App\n"
        "📱 [Open Mini App](https://t.me/pumpreelsbot/pumpreelsapp)\n\n"
        "OR TYPE\n"
        "/generate_video [your prompt] and attach an image to create your AI video instantly!\n\n"
        "Powered by @PumpReelsBot"
    )

    # 2) Send an animation (GIF) + caption
    await update.message.reply_animation(
        animation="https://comforting-druid-bafd91.netlify.app/rendering.gif",
        caption=caption,
        parse_mode="Markdown"
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="This thread has expired. Please try again."
            )
            return
        else:
            raise

    user_identifier = query.from_user.username or query.from_user.first_name
    msg = await query.message.reply_text(
        f"@{user_identifier}, please reply to this message with an image from your camera roll.",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Attach your image here")
    )
    context.user_data["image_prompt_message_id"] = msg.message_id
    return IMAGE


async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if update.message and update.message.photo:
        user_identifier = update.message.from_user.username or update.message.from_user.first_name

        photo = update.message.photo[-1]
        file_id = photo.file_id
        context.user_data["file_id"] = file_id
        context.user_data["image_message_id"] = update.message.message_id

        # Delete the ForceReply prompt for the image.
        if "image_prompt_message_id" in context.user_data:
            try:
                await application.bot.delete_message(
                    chat_id=chat_id,
                    message_id=context.user_data["image_prompt_message_id"]
                )
                logger.info("Deleted image prompt message: %s", context.user_data["image_prompt_message_id"])
            except Exception as e:
                logger.error("Failed to delete image prompt message: %s", e)

        msg = await update.message.reply_text(
            f"@{user_identifier}, please type your custom prompt:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Enter your prompt here")
        )
        context.user_data["prompt_prompt_message_id"] = msg.message_id
        return PROMPT

        # # Send inline keyboard with prompt templates (2x2 grid)
        # keyboard = [
        #     [InlineKeyboardButton("TO THE MOON", callback_data="TO THE MOON"),
        #      InlineKeyboardButton("WEN LAMBO", callback_data="WEN LAMBO")],
        #     [InlineKeyboardButton("WAGMI", callback_data="WAGMI"),
        #      InlineKeyboardButton("Custom", callback_data="CUSTOM")]
        # ]
        # reply_markup = InlineKeyboardMarkup(keyboard)
        # template_msg = await update.message.reply_text(
        #     "Choose a prompt template or select Custom for your own prompt:",
        #     reply_markup=reply_markup
        # )
        # context.user_data["prompt_templates_message_id"] = template_msg.message_id
        # return PROMPT
    else:
        await update.message.reply_text("That doesn't seem like an image. Please send a valid image.")
        return IMAGE

async def prompt_templates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_identifier = query.from_user.username or query.from_user.first_name
    selected = query.data  # Either "TO THE MOON", "WEN LAMBO", "WAGMI", or "CUSTOM"
    if selected == "CUSTOM":
        # Ask for a custom prompt via ForceReply.
        msg = await query.message.reply_text(
            f"@{user_identifier}, please type your custom prompt:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Enter your prompt here")
        )
        context.user_data["prompt_prompt_message_id"] = msg.message_id
        return PROMPT
    else:
        # MARK: DO WE NEED THIS?

        await process_video(update, context, prompt_text=prompt_templates[selected])
        return ConversationHandler.END

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles text prompt reception when 'Custom' is selected,
    then calls process_video to generate the video.
    """
    prompt_text = update.message.text
    await process_video(update, context, prompt_text=prompt_text)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Video cancelled.")
    return ConversationHandler.END

# ------------------
# Conversation Handler
# ------------------
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_callback, pattern="^generate_video$")],
    states={
        IMAGE: [MessageHandler(filters.PHOTO, receive_image)],
        # PROMPT_TEMPLATES: [CallbackQueryHandler(prompt_templates_callback, pattern="^(TO THE MOON|WEN LAMBO|WAGMI|CUSTOM)$")], FIX THIS
        PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_chat=True,
    per_user=True,
)

application.add_handler(CommandHandler("start", start))

application.add_handler(CommandHandler("pumpreels", pumpreels))
generate_video_handler = MessageHandler(
    filters.PHOTO & filters.CaptionRegex(r"^/generate_video\b"),
    generate_video_command
)

application.add_handler(generate_video_handler)
application.add_handler(CommandHandler("generate_video", generate_video_command))
application.add_handler(CommandHandler("credits", credits))
application.add_handler(conv_handler)

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

@app.post("/webhook")
async def telegram_webhook(request: Request):
    update_json = await request.json()
    logger.info(update_json)
    logger.info('\n==========\n')
    handle_new_group_update(update_json)

    update = Update.de_json(update_json, application.bot)
    await application.process_update(update)
    return {"ok": True}


@app.post("/radomWebhook")
async def radom_webhook(request: Request):
    radom_data = await request.json()
    logger.info(f"Received Radom Webhook: {radom_data}")
    # VERIFY WEBHOOK VERIFICATION KEY
    # get the group id from metadata
    # add the credits to the group document in Firestore

    return {"ok": True}


# ENDPOINTS FOR MINI APP
@app.post("/generateVideo")
async def generate_video_endpoint(
    prompt_text: str = Form(...),
    image: UploadFile = File(...),
):
    """
    1) Receives an image + prompt text.
    2) Calls PikaClient to start video generation.
    3) Returns an immediate response with video_id, not the final video.
    """

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

    # Call your PikaClient generate_video method
    try:
        result = pika_client.generate_video(
            image_file="image.jpg",       # Arbitrary name
            image_bytes=io.BytesIO(image_bytes),
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
async def get_video_status_endpoint(
    video_id: str = Query(..., description="The ID of the video to poll")
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

    # If you want to return the entire dictionary:
    return {
        "video_id": video_id,
        "status": status,
        "progress": progress,
        "url": url  # Only valid if status == 'finished'
    }

@app.get("/")
async def root():
    return {"message": "Hello, FastAPI Telegram bot!"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=True)
