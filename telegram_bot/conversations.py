import logging
from telegram import Update, InlineKeyboardMarkup, ForceReply
from telegram.ext import ContextTypes, ConversationHandler
from telegram_bot.keyboards import generate_prompt_buttons
from ai_services.runway_client import RunwayClient

logger = logging.getLogger(__name__)
video_generator = RunwayClient()

# Define conversation states
IMAGE, PROMPT_TEMPLATES, PROMPT = range(3)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 1: User clicks 'Generate AI Video'. Prompt them to upload an image.
    """
    query = update.callback_query
    await query.answer()
    user_identifier = query.from_user.username or query.from_user.first_name

    msg = await query.message.reply_text(
        f"@{user_identifier}, please reply to this message with an image from your camera roll.",
        reply_markup=ForceReply(selective=True, input_field_placeholder="Attach your image here")
    )

    context.user_data["image_prompt_message_id"] = msg.message_id
    return IMAGE

async def receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 2: User uploads an image. Save it and ask them to pick a prompt template.
    """
    if update.message and update.message.photo:
        photo = update.message.photo[-1]
        context.user_data["file_id"] = photo.file_id

        await update.message.reply_text(
            "Choose a prompt template or select 'Custom' for your own prompt:",
            reply_markup=generate_prompt_buttons()
        )
        return PROMPT_TEMPLATES
    else:
        await update.message.reply_text("That doesn't seem like an image. Please send a valid image.")
        return IMAGE

async def prompt_templates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 3: User selects a predefined prompt or chooses 'Custom'.
    """
    query = update.callback_query
    await query.answer()
    selected = query.data  # Either "TO THE MOON", "WEN LAMBO", "WAGMI", or "CUSTOM"

    if selected == "CUSTOM":
        msg = await query.message.reply_text(
            "Please type your custom prompt:",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Enter your prompt here")
        )
        context.user_data["prompt_prompt_message_id"] = msg.message_id
        return PROMPT
    else:
        await generate_video(update, context, prompt_text=selected)
        return ConversationHandler.END

async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Step 4 (if 'Custom' was selected): Process user's custom text prompt.
    """
    prompt_text = update.message.text
    await generate_video(update, context, prompt_text=prompt_text)
    return ConversationHandler.END

async def generate_video(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt_text: str):
    """
    Final Step: Uses RunwayClient to generate a video and send it back.
    """
    chat_id = update.effective_chat.id
    file_id = context.user_data.get("file_id")

    if not file_id:
        await update.message.reply_text("Error: No image found. Please restart the process.")
        return

    file_obj = await update.message.bot.get_file(file_id)
    temp_file_path = f"/tmp/{file_id}.jpg"
    await file_obj.download_to_drive(custom_path=temp_file_path)

    # Read and encode image as Base64
    with open(temp_file_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode("utf-8")

    video_url = await video_generator.create_video(image_data, prompt_text)

    if video_url:
        await update.message.reply_text(f"✅ Your AI-generated video is ready!\n{video_url}")
    else:
        await update.message.reply_text("❌ Error generating video. Please try again.")

    # Cleanup
    os.remove(temp_file_path)
