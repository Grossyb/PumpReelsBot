from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_credit_buttons():
    """
    Creates inline buttons for credit purchases.

    Returns:
        InlineKeyboardMarkup: The keyboard layout.
    """
    keyboard = [
        [InlineKeyboardButton("2,500 Credits", url="https://pay.radom.com/pay/2500"),
         InlineKeyboardButton("6,250 Credits", url="https://pay.radom.com/pay/6250")],
        [InlineKeyboardButton("12,500 Credits", url="https://pay.radom.com/pay/12500"),
         InlineKeyboardButton("25,000 Credits", url="https://pay.radom.com/pay/25000")]
    ]
    return InlineKeyboardMarkup(keyboard)

def format_credit_info():
    """
    Formats the credit information message.

    Returns:
        str: The formatted message.
    """
    return """
🚀 PumpReels Video Credit System

🎥 Your Current Credits: [X] credits (updated in real-time)
💰 1 Video (5 sec) = 25 credits (5 credits per second)

🔹 Need more credits? Purchase directly below!

📦 Bulk Credit Discounts (Best Value!)

Pre-purchase credits at a discounted rate and get more value!

100 Videos (2500 credits) → $140.00 ($1.40 per video)
250 Videos (6250 credits) → $325.00 ($1.30 per video)
500 Videos (12,500 credits) → $550.00 ($1.10 per video)
1000 Videos (25,000 credits) → $1,000.00 ($1.00 per video) 🔥 Best Deal!
    """.strip()
s
