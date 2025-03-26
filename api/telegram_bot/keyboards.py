from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def generate_credit_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("2,500 Credits", url="https://pay.radom.com/pay/342b688b-c051-4820-ba9f-26c648cddde3"),
         InlineKeyboardButton("6,250 Credits", url="https://pay.radom.com/pay/fd243359-b3a6-4c7e-a082-6cbab298328b")],
        [InlineKeyboardButton("12,500 Credits", url="https://pay.radom.com/pay/22084efe-2acc-46dc-aa83-255e40ec550c"),
         InlineKeyboardButton("25,000 Credits", url="https://pay.radom.com/pay/176362cb-e739-47d3-9232-c025b5d859fc")]
    ])
