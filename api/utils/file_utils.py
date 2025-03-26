import base64
import os
from telegram import Bot
from config import TELEGRAM_TOKEN

bot = Bot(token=TELEGRAM_TOKEN)

async def download_and_encode_image(file_id: str) -> str:
    """
    Downloads an image from Telegram and encodes it in Base64.

    Args:
        file_id (str): Telegram file ID.

    Returns:
        str: Base64-encoded image data.
    """
    try:
        file_obj = await bot.get_file(file_id)
        temp_file_path = f"/tmp/{file_id}.jpg"
        await file_obj.download_to_drive(custom_path=temp_file_path)

        with open(temp_file_path, "rb") as image_file:
            image_bytes = image_file.read()
            base64_encoded = base64.b64encode(image_bytes).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{base64_encoded}"

        # Remove temp file after encoding
        os.remove(temp_file_path)

        return data_uri
    except Exception as e:
        logger.error(f"Error downloading or encoding image: {e}")
        return None
