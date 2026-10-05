import logging

from telegram.ext import Application, Defaults

from .config import Settings
from .database import Database
from .handlers.commands import handlers, scheduled_attendance, scheduled_payment_reminders
from .handlers.commands import BOT_DESCRIPTION, BOT_SHORT_DESCRIPTION


async def configure_bot_profile(app):
    for method, value in ((app.bot.set_my_description, BOT_DESCRIPTION),
                          (app.bot.set_my_short_description, BOT_SHORT_DESCRIPTION)):
        try:
            await method(value)
        except Exception:
            logging.getLogger(__name__).exception("Could not set the public bot description")


def main():
    settings = Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = (Application.builder().token(settings.bot_token)
           .defaults(Defaults(tzinfo=__import__("zoneinfo").ZoneInfo(settings.timezone)))
           .post_init(configure_bot_profile).build())
    app.bot_data["settings"] = settings
    app.bot_data["db"] = Database(settings.database_path)
    for handler in handlers():
        app.add_handler(handler)
    app.job_queue.run_repeating(scheduled_attendance, interval=30, first=5, name="scheduled_attendance")
    app.job_queue.run_repeating(scheduled_payment_reminders, interval=30, first=10, name="scheduled_payment_reminders")
    logging.getLogger(__name__).info("Typhoon Bot started")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])
