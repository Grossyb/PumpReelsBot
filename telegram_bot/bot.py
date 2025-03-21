from telegram.ext import ConversationHandler
from telegram_bot.conversations import button_callback, receive_image, prompt_templates_callback, receive_prompt, IMAGE, PROMPT_TEMPLATES, PROMPT

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_callback, pattern="^generate_video$")],
    states={
        IMAGE: [MessageHandler(filters.PHOTO, receive_image)],
        PROMPT_TEMPLATES: [CallbackQueryHandler(prompt_templates_callback, pattern="^(TO THE MOON|WEN LAMBO|WAGMI|CUSTOM)$")],
        PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
    per_chat=True,
    per_user=True,
)

application.add_handler(conv_handler)
