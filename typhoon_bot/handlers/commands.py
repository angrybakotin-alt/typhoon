from datetime import datetime, timedelta, timezone
import calendar
import logging
from zoneinfo import ZoneInfo
from pathlib import Path

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputProfilePhotoStatic,
                      ReplyKeyboardMarkup, Update)
from telegram.error import TelegramError
from telegram.ext import (CommandHandler, ContextTypes, ConversationHandler,
                          CallbackQueryHandler, MessageHandler, PollAnswerHandler,
                          filters)

from ..database import Database

NAME, PHONE, EXTRA, EDIT, GROUP_SELECTION = range(5)
NEW_NAME, NEW_BIRTH_DATE, NEW_GENDER, NEW_HEIGHT, NEW_WEIGHT, NEW_EXPERIENCE, NEW_CITY, NEW_PHONE, NEW_TELEGRAM = range(10, 19)

REGISTER_BUTTON = "📝 Зареєструватися"
NEWCOMER_BUTTON = "🆕 Я новачок"
PROFILE_BUTTON = "👤 Моя анкета"
EDIT_BUTTON = "✏️ Редагувати анкету"
SCHEDULE_BUTTON = "📅 Розклад"
ADMIN_BUTTON = "🛠 Панель адміністратора"
BOT_DESCRIPTION = (
    "Волейбольний клуб Typhoon: три тренувальні групи, розклад і голосування за відвідування. "
    "Подайте заявку до клубу або залиште анкету новачка — адміністратор зв’яжеться з вами після розгляду."
)
BOT_SHORT_DESCRIPTION = "Волейбольний клуб Typhoon: розклад, заявки та голосування за тренування."


def db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(update.effective_user and update.effective_user.id in context.application.bot_data["settings"].admin_ids)


def main_keyboard(admin=False):
    keyboard = [[REGISTER_BUTTON, NEWCOMER_BUTTON], [PROFILE_BUTTON, EDIT_BUTTON],
                [SCHEDULE_BUTTON]]
    if admin:
        keyboard.append([ADMIN_BUTTON])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_keyboard():
    return ReplyKeyboardMarkup([["↩️ Скасувати"]], resize_keyboard=True, one_time_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return await update.message.reply_text("Напишіть мені в особисті повідомлення, щоб відкрити меню.")
    welcome = ("Вітаємо у волейбольному клубі Typhoon!\n\n"
               "Щоб подати заявку:\n"
               "• Якщо ви вже тренуєтеся в клубі — натисніть «📝 Зареєструватися», заповніть анкету й оберіть свою групу.\n"
               "• Якщо хочете приєднатися або спробувати тренування — натисніть «🆕 Я новачок» і заповніть анкету: ПІБ, дату народження, стать, зріст, вагу, досвід, місто, телефон та посилання на Telegram.\n\n"
               "Після відправлення заявка надійде адміністратору. Якщо ви новачок, адміністратор зв’яжеться з вами за телефоном або посиланням Telegram.\n"
               "Розклад тренувань можна переглянути кнопкою «📅 Розклад». Оберіть потрібну дію в меню нижче.")
    await update.message.reply_text(welcome,
                                    reply_markup=main_keyboard(is_admin(update, context)))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def set_bot_avatar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_bot_avatar"):
        return
    if not is_admin(update, context) or update.effective_chat.type != "private":
        return await update.message.reply_text("Змінювати аватар бота може лише адміністратор в особистому чаті.")
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = bytes(await photo_file.download_as_bytearray())
        await context.bot.set_my_profile_photo(InputProfilePhotoStatic(photo=photo_bytes))
    except TelegramError:
        logging.getLogger(__name__).exception("Could not update the bot profile photo")
        return await update.message.reply_text("Не вдалося змінити аватарку. Надішліть звичайне фото JPG і спробуйте ще раз.")
    context.user_data.pop("awaiting_bot_avatar", None)
    await update.message.reply_text("Аватар бота успішно змінено.",
                                    reply_markup=main_keyboard(is_admin(update, context)))


async def show_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.effective_message.message_thread_id
    await update.message.reply_text(
        f"Ваш Telegram ID: {update.effective_user.id}\n"
        f"ID цього чату: {update.effective_chat.id}\n"
        f"ID цієї гілки: {thread_id if thread_id is not None else 'це загальний чат, гілки немає'}"
    )


async def begin_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    table, person = db(context).person(update.effective_user.id)
    if table == "players" and person["status"] == "active":
        await update.message.reply_text("Ваша анкета вже активна. Щоб змінити дані, оберіть «✏️ Редагувати анкету».")
        return ConversationHandler.END
    if table == "players" and person["status"] == "pending":
        await update.message.reply_text("Ваша анкета вже на розгляді адміністратора.")
        return ConversationHandler.END
    context.user_data["person_table"] = "players"
    context.user_data["person_extra"] = ""
    await update.message.reply_text("Як вас звати повністю?", reply_markup=cancel_keyboard())
    return NAME


async def begin_newcomer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    table, person = db(context).person(update.effective_user.id)
    if table == "newcomers" and person["status"] == "new":
        await update.message.reply_text("Вашу анкету новачка вже надіслано адміністратору.")
        return ConversationHandler.END
    if table == "newcomers" and person["status"] == "invited":
        await update.message.reply_text("Вашу анкету прийнято. Адміністратор зв’яжеться з вами за вказаними контактами.")
        return ConversationHandler.END
    context.user_data["person_table"] = "newcomers"
    await update.message.reply_text("Вкажіть ПІБ:", reply_markup=cancel_keyboard())
    return NEW_NAME


async def newcomer_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["full_name"] = update.message.text.strip()[:160]
    await update.message.reply_text("Дата народження у форматі ДД.ММ.РРРР:", reply_markup=cancel_keyboard())
    return NEW_BIRTH_DATE


async def newcomer_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = datetime.strptime(update.message.text.strip(), "%d.%m.%Y").date()
        if value > datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone)).date():
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введіть дату у форматі ДД.ММ.РРРР, не пізніше сьогодні.")
        return NEW_BIRTH_DATE
    context.user_data["birth_date"] = value.isoformat()
    keyboard = ReplyKeyboardMarkup([["Жіноча"], ["Чоловіча"], ["↩️ Скасувати"]], resize_keyboard=True)
    await update.message.reply_text("Оберіть стать:", reply_markup=keyboard)
    return NEW_GENDER


async def newcomer_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if value not in {"Жіноча", "Чоловіча"}:
        await update.message.reply_text("Оберіть «Жіноча» або «Чоловіча».")
        return NEW_GENDER
    context.user_data["gender"] = value
    await update.message.reply_text("Вкажіть зріст у сантиметрах (наприклад, 178):", reply_markup=cancel_keyboard())
    return NEW_HEIGHT


async def newcomer_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = int(update.message.text.strip())
        if not 80 <= value <= 260:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Вкажіть зріст числом у сантиметрах, від 80 до 260.")
        return NEW_HEIGHT
    context.user_data["height_cm"] = value
    await update.message.reply_text("Вкажіть вагу у кілограмах (наприклад, 72):", reply_markup=cancel_keyboard())
    return NEW_WEIGHT


async def newcomer_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text.strip().replace(",", "."))
        if not 20 <= value <= 300:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Вкажіть вагу числом у кілограмах, від 20 до 300.")
        return NEW_WEIGHT
    context.user_data["weight_kg"] = value
    await update.message.reply_text("Опишіть ваш волейбольний досвід:", reply_markup=cancel_keyboard())
    return NEW_EXPERIENCE


async def newcomer_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["experience"] = update.message.text.strip()[:500]
    await update.message.reply_text("Укажіть місто проживання:", reply_markup=cancel_keyboard())
    return NEW_CITY


async def newcomer_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["city"] = update.message.text.strip()[:120]
    await update.message.reply_text("Контактний номер телефону:", reply_markup=cancel_keyboard())
    return NEW_PHONE


async def newcomer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()[:40]
    await update.message.reply_text("Посилання на ваш Telegram: @username або https://t.me/username:",
                                    reply_markup=cancel_keyboard())
    return NEW_TELEGRAM


async def newcomer_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    if " " in value:
        await update.message.reply_text("Надішліть @username або посилання t.me без пробілів.")
        return NEW_TELEGRAM
    if value.startswith("@"):
        value = "https://t.me/" + value[1:]
    elif value.startswith("t.me/"):
        value = "https://" + value
    elif value.startswith("http://t.me/"):
        value = "https://" + value[len("http://"):]
    if not value.startswith("https://t.me/") or len(value) <= len("https://t.me/"):
        await update.message.reply_text("Посилання має бути у форматі @username або https://t.me/username.")
        return NEW_TELEGRAM
    context.user_data["telegram_link"] = value[:180]
    await complete_newcomer(update, context)
    return ConversationHandler.END


async def got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["full_name"] = update.message.text.strip()[:120]
    await update.message.reply_text("Вкажіть номер телефону або надішліть «-», щоб пропустити.",
                                    reply_markup=cancel_keyboard())
    return PHONE


async def got_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = "" if update.message.text.strip() == "-" else update.message.text.strip()[:40]
    if context.user_data["person_table"] == "players":
        await update.message.reply_text("Ігрова позиція (або «-», щоб пропустити)?", reply_markup=cancel_keyboard())
        return EXTRA
    await update.message.reply_text("Коротко розкажіть про ігровий досвід (або «-», щоб пропустити).",
                                    reply_markup=cancel_keyboard())
    return EXTRA


async def got_extra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    extra = "" if update.message.text.strip() == "-" else update.message.text.strip()[:160]
    table = context.user_data["person_table"]
    if table == "players":
        context.user_data["position"] = extra
        groups = db(context).list_groups()
        context.user_data["group_choices"] = {row["name"]: row["id"] for row in groups}
        context.user_data["selected_groups"] = set()
        if groups:
            labels = [[name] for name in context.user_data["group_choices"]]
            labels.append(["✅ Готово", "↩️ Скасувати"])
            await update.message.reply_text(
                "Оберіть свою тренувальну групу або кілька груп, потім натисніть «✅ Готово».",
                reply_markup=ReplyKeyboardMarkup(labels, resize_keyboard=True))
            return GROUP_SELECTION
        await complete_registration(update, context, extra)
    else:
        await complete_registration(update, context, extra)
    return ConversationHandler.END


async def select_player_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip()
    if choice == "↩️ Скасувати":
        return await cancel(update, context)
    if choice == "✅ Готово":
        selected = context.user_data.get("selected_groups", set())
        if not selected:
            await update.message.reply_text("Оберіть щонайменше одну групу.")
            return GROUP_SELECTION
        await complete_registration(update, context, context.user_data.get("position", ""))
        return ConversationHandler.END
    group_id = context.user_data.get("group_choices", {}).get(choice)
    if group_id is None:
        await update.message.reply_text("Оберіть групу кнопкою нижче або натисніть «✅ Готово».")
        return GROUP_SELECTION
    selected = context.user_data.setdefault("selected_groups", set())
    if group_id in selected:
        selected.remove(group_id)
    else:
        selected.add(group_id)
    selected_names = [name for name, gid in context.user_data["group_choices"].items() if gid in selected]
    labels = [[name] for name in context.user_data["group_choices"]]
    labels.append(["✅ Готово", "↩️ Скасувати"])
    await update.message.reply_text("Обрано: " + (", ".join(selected_names) or "поки жодної"),
                                    reply_markup=ReplyKeyboardMarkup(labels, resize_keyboard=True))
    return GROUP_SELECTION


async def complete_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, extra: str):
    user_id = update.effective_user.id
    table = context.user_data["person_table"]
    if table != "players":
        return await complete_newcomer(update, context)
    db(context).save_person(table, user_id, context.user_data["full_name"], context.user_data["phone"], extra)
    group_ids = list(context.user_data.get("selected_groups", set()))
    db(context).set_player_groups(user_id, group_ids)
    groups = db(context).group_names(group_ids)
    group_names = ", ".join(group["name"] for group in groups) or "не обрано"
    await update.message.reply_text("Анкету надіслано адміністратору. Після підтвердження ви станете активним гравцем.",
                                    reply_markup=main_keyboard(is_admin(update, context)))
    details = (f"Заявка гравця: {context.user_data['full_name']}\n"
               f"Телефон: {context.user_data['phone'] or '—'}\n"
               f"Позиція: {extra or '—'}\nГрупи: {group_names}\nTelegram ID: {user_id}")
    controls = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Підтвердити", callback_data=f"review:{user_id}:approve"),
                                     InlineKeyboardButton("❌ Відхилити", callback_data=f"review:{user_id}:reject")]])
    await notify_admins(context, details, controls)
    context.user_data.clear()


async def complete_newcomer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = {key: context.user_data[key] for key in (
        "full_name", "birth_date", "gender", "height_cm", "weight_kg", "experience", "city", "phone", "telegram_link")}
    db(context).save_newcomer(user_id, profile)
    await update.message.reply_text("Анкету надіслано адміністратору. Після розгляду з вами зв’яжуться за вказаними контактами.",
                                    reply_markup=main_keyboard(is_admin(update, context)))
    details = (f"Заявка новачка: {profile['full_name']}\nПІБ: {profile['full_name']}\n"
               f"Дата народження: {datetime.fromisoformat(profile['birth_date']).strftime('%d.%m.%Y')}\n"
               f"Стать: {profile['gender']}\nЗріст: {profile['height_cm']} см\nВага: {profile['weight_kg']:g} кг\n"
               f"Досвід: {profile['experience']}\nМісто: {profile['city']}\nТелефон: {profile['phone']}\n"
               f"Telegram: {profile['telegram_link']}\nTelegram ID: {user_id}")
    controls = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Прийняти", callback_data=f"nr:{user_id}:approve"),
                                     InlineKeyboardButton("❌ Відхилити", callback_data=f"nr:{user_id}:reject")]])
    await notify_newcomer_admins(context, user_id, details, controls)
    context.user_data.clear()


async def notify_admins(context, text, reply_markup=None):
    for admin_id in context.application.bot_data["settings"].admin_ids:
        try:
            await context.bot.send_message(admin_id, text, reply_markup=reply_markup)
        except Exception:
            logging.getLogger(__name__).exception("Could not notify admin %s", admin_id)


async def notify_newcomer_admins(context, newcomer_id, text, reply_markup=None):
    for admin_id in context.application.bot_data["settings"].admin_ids:
        try:
            message = await context.bot.send_message(admin_id, text, reply_markup=reply_markup)
            db(context).record_newcomer_notice(newcomer_id, admin_id, message.message_id)
        except Exception:
            logging.getLogger(__name__).exception("Could not notify admin %s about newcomer", admin_id)


async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context) or update.effective_chat.type != "private":
        return await update.message.reply_text("Ця панель доступна лише адміністратору в особистому чаті з ботом.")
    groups = db(context).list_groups()
    pending_count = len(db(context).pending_players())
    newcomer_count = len(db(context).pending_newcomers())
    rows = [[InlineKeyboardButton(f"📨 Гравці ({pending_count})", callback_data="adm:pending")],
            [InlineKeyboardButton(f"🆕 Новачки ({newcomer_count})", callback_data="adm:newcomers")],
            [InlineKeyboardButton("📊 Статистика відвідування", callback_data="adm:stats")],
            [InlineKeyboardButton("🗑 Видалити зареєстрованого гравця", callback_data="adm:delete")],
            [InlineKeyboardButton("🖼 Змінити аватар бота", callback_data="adm:avatar")]]
    rows.extend([[InlineKeyboardButton(f"👥 {group['name']}", callback_data=f"adm:group:{group['id']}")]
                 for group in groups])
    rows.append([InlineKeyboardButton("📅 Розклад", callback_data="adm:schedule")])
    await update.message.reply_text("Панель адміністратора", reply_markup=InlineKeyboardMarkup(rows))


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    await query.answer()
    action = query.data.split(":")
    if action[1] == "home":
        await query.edit_message_text("Панель адміністратора", reply_markup=admin_keyboard(context))
    elif action[1] == "avatar":
        context.user_data["awaiting_bot_avatar"] = True
        await query.edit_message_text(
            "Надішліть нову аватарку бота як фото в особистому чаті. Для аватарки краще підійде квадратне зображення JPG.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Скасувати", callback_data="adm:avatarcancel")]]))
    elif action[1] == "avatarcancel":
        context.user_data.pop("awaiting_bot_avatar", None)
        await query.edit_message_text("Зміну аватарки скасовано.", reply_markup=admin_keyboard(context))
    elif action[1] == "pending":
        pending = db(context).pending_players()
        if not pending:
            await query.edit_message_text("Нових заявок немає.", reply_markup=admin_keyboard(context))
            return
        await query.edit_message_text(f"Заявок на розгляд: {len(pending)}", reply_markup=admin_keyboard(context))
        for player in pending:
            text = (f"Заявка гравця: {player['full_name']}\nТелефон: {player['phone'] or '—'}\n"
                    f"Позиція: {player['position'] or '—'}\nГрупи: {player['groups'] or 'не обрано'}\n"
                    f"Telegram ID: {player['telegram_id']}")
            controls = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Підтвердити", callback_data=f"review:{player['telegram_id']}:approve"),
                                             InlineKeyboardButton("❌ Відхилити", callback_data=f"review:{player['telegram_id']}:reject")]])
            await context.bot.send_message(query.message.chat.id, text, reply_markup=controls)
    elif action[1] == "newcomers":
        newcomers = db(context).pending_newcomers()
        if not newcomers:
            await query.edit_message_text("Нових анкет новачків немає.", reply_markup=admin_keyboard(context))
            return
        await query.edit_message_text(f"Анкет новачків на розгляді: {len(newcomers)}",
                                      reply_markup=admin_keyboard(context))
        for applicant in newcomers:
            text = newcomer_card_text(applicant)
            controls = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Прийняти", callback_data=f"nr:{applicant['telegram_id']}:approve"),
                                             InlineKeyboardButton("❌ Відхилити", callback_data=f"nr:{applicant['telegram_id']}:reject")]])
            await context.bot.send_message(query.message.chat.id, text, reply_markup=controls)
    elif action[1] == "group" and len(action) == 3:
        await show_group_roster(query, context, int(action[2]))
    elif action[1] == "stats" and len(action) == 2:
        await show_attendance_group_picker(query, context)
    elif action[1] == "stats" and len(action) == 3:
        await show_attendance_stats(query, context, int(action[2]))
    elif action[1] == "delete" and len(action) == 2:
        groups = db(context).list_groups()
        rows = [[InlineKeyboardButton(group["name"], callback_data=f"adm:deletegroup:{group['id']}")]
                for group in groups]
        rows.append([InlineKeyboardButton("↩️ До панелі", callback_data="adm:home")])
        await query.edit_message_text("Оберіть групу, щоб знайти гравця для видалення:",
                                      reply_markup=InlineKeyboardMarkup(rows))
    elif action[1] == "deletegroup" and len(action) == 3:
        group_id = int(action[2])
        group = db(context).get_group(group_id)
        if not group:
            return await query.edit_message_text("Групу не знайдено.", reply_markup=admin_keyboard(context))
        players = db(context).player_cards_in_group(
            group_id, payment_month(datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone))))
        rows = [[InlineKeyboardButton(player["full_name"],
                                      callback_data=f"adm:deleteplayer:{group_id}:{player['telegram_id']}")]
                for player in players]
        rows.append([InlineKeyboardButton("↩️ До груп", callback_data="adm:delete")])
        await query.edit_message_text(f"Оберіть гравця з групи «{group['name']}»:",
                                      reply_markup=InlineKeyboardMarkup(rows))
    elif action[1] == "deleteplayer" and len(action) == 4:
        group_id, player_id = int(action[2]), int(action[3])
        person_type, player = db(context).person(player_id)
        if person_type != "players" or not player or player["status"] != "active":
            return await query.answer("Активного гравця не знайдено.", show_alert=True)
        controls = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Так, видалити всі дані",
                                  callback_data=f"adm:deleteconfirm:{group_id}:{player_id}")],
            [InlineKeyboardButton("↩️ Скасувати", callback_data=f"adm:deletegroup:{group_id}")]])
        await query.edit_message_text(
            f"Назавжди видалити гравця «{player['full_name']}»? Анкета, відвідування, оплати та знижки будуть стерті.",
            reply_markup=controls)
    elif action[1] == "deleteconfirm" and len(action) == 4:
        group_id, player_id = int(action[2]), int(action[3])
        person_type, player = db(context).person(player_id)
        if person_type != "players" or not player or not db(context).delete_player(player_id):
            return await query.answer("Гравця вже видалено або не знайдено.", show_alert=True)
        await query.edit_message_text(
            f"Гравця «{player['full_name']}» та всі пов’язані з ним дані видалено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Видалити іншого", callback_data=f"adm:deletegroup:{group_id}")],
                [InlineKeyboardButton("До панелі", callback_data="adm:home")]]))
    elif action[1] == "schedule":
        rows = db(context).schedule()
        text = format_schedule(rows)
        controls = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Повністю замінити розклад групи", callback_data="adm:replaceschedule")],
            [InlineKeyboardButton("➕ Додати тренування", callback_data="adm:addschedule")],
            [InlineKeyboardButton("↩️ До панелі", callback_data="adm:home")],
        ])
        await query.edit_message_text(text, reply_markup=controls)
    elif action[1] == "replaceschedule" and len(action) == 2:
        groups = db(context).list_groups()
        choices = [[InlineKeyboardButton(group["name"], callback_data=f"adm:replacegroup:{group['id']}")]
                   for group in groups]
        choices.append([InlineKeyboardButton("↩️ До розкладу", callback_data="adm:schedule")])
        await query.edit_message_text("Оберіть групу, для якої потрібно повністю замінити розклад:",
                                      reply_markup=InlineKeyboardMarkup(choices))
    elif action[1] == "replacegroup" and len(action) == 3:
        group_id = int(action[2])
        group = db(context).get_group(group_id)
        if not group:
            return await query.edit_message_text("Групу не знайдено.", reply_markup=admin_keyboard(context))
        context.user_data.pop("schedule_setup", None)
        context.user_data["schedule_replacement"] = {"group_id": group_id}
        await query.edit_message_text(
            f"Надішліть новий розклад для «{group['name']}» — по одному тренуванню на рядок.\n"
            "Формат: День ГГ:ХХ-ГГ:ХХ\nНаприклад:\nП’ятниця 16:30-18:00\nСубота 16:30-18:00\n"
            "Старий розклад зміниться лише після вашого підтвердження. Щоб повністю очистити його, надішліть «без тренувань».",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Скасувати", callback_data="adm:replacecancel")]]))
    elif action[1] == "replaceconfirm" and len(action) == 3:
        group_id = int(action[2])
        draft = context.user_data.get("schedule_replacement_preview")
        if not draft or draft["group_id"] != group_id:
            return await query.answer("Чернетку розкладу не знайдено. Почніть заміну ще раз.", show_alert=True)
        db(context).replace_schedule(group_id, draft["sessions"])
        context.user_data.pop("schedule_replacement_preview", None)
        await query.edit_message_text(f"Розклад групи «{draft['group_name']}» повністю оновлено.\n"
                                      f"{format_schedule_preview(draft['sessions'])}",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("До розкладу", callback_data="adm:schedule")],
                                          [InlineKeyboardButton("До панелі", callback_data="adm:home")]]))
    elif action[1] == "replacecancel":
        context.user_data.pop("schedule_replacement", None)
        context.user_data.pop("schedule_replacement_preview", None)
        await query.edit_message_text("Заміну розкладу скасовано.",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("До розкладу", callback_data="adm:schedule")],
                                          [InlineKeyboardButton("До панелі", callback_data="adm:home")]]))
    elif action[1] == "addschedule":
        groups = db(context).list_groups()
        choices = [[InlineKeyboardButton(group["name"], callback_data=f"adm:slotgroup:{group['id']}")]
                   for group in groups]
        choices.append([InlineKeyboardButton("↩️ До розкладу", callback_data="adm:schedule")])
        await query.edit_message_text("Оберіть групу для нового тренування:", reply_markup=InlineKeyboardMarkup(choices))
    elif action[1] == "slotgroup" and len(action) == 3:
        group_id = int(action[2])
        group = db(context).get_group(group_id)
        if not group:
            return await query.edit_message_text("Групу не знайдено.", reply_markup=admin_keyboard(context))
        context.user_data["schedule_setup"] = {"group_id": group_id}
        weekdays = [("Понеділок", "понеділок"), ("Вівторок", "вівторок"), ("Середа", "середа"),
                    ("Четвер", "четвер"), ("П’ятниця", "п’ятниця"), ("Субота", "субота"),
                    ("Неділя", "неділя")]
        choices = [[InlineKeyboardButton(label, callback_data=f"slotday:{value}")]
                   for label, value in weekdays]
        choices.append([InlineKeyboardButton("Скасувати", callback_data="slotcancel")])
        await query.edit_message_text(f"Оберіть день тренування для «{group['name']}»:",
                                      reply_markup=InlineKeyboardMarkup(choices))


async def schedule_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    setup = context.user_data.get("schedule_setup")
    if not setup:
        return await query.answer("Розпочніть додавання тренування з панелі адміністратора.", show_alert=True)
    weekday = query.data.split(":", 1)[1]
    setup.update({"weekday": weekday, "step": "time"})
    await query.answer()
    await query.edit_message_text(f"День: {weekday}. Введіть час у форматі 18:30-20:30.",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Скасувати", callback_data="slotcancel")]]))


async def schedule_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replacement = context.user_data.get("schedule_replacement")
    if replacement and is_admin(update, context) and update.effective_chat.type == "private":
        value = update.message.text.strip()
        if value == "↩️ Скасувати":
            context.user_data.pop("schedule_replacement", None)
            return await update.message.reply_text("Заміну розкладу скасовано.",
                reply_markup=main_keyboard(is_admin(update, context)))
        group = db(context).get_group(replacement["group_id"])
        if not group:
            context.user_data.pop("schedule_replacement", None)
            return await update.message.reply_text("Групу не знайдено. Розклад не змінено.")
        try:
            sessions = parse_schedule_lines(value)
        except ValueError as error:
            return await update.message.reply_text(
                f"{error}\nНадішліть рядки у форматі «П’ятниця 16:30-18:00» або «без тренувань».")
        context.user_data.pop("schedule_replacement", None)
        context.user_data["schedule_replacement_preview"] = {
            "group_id": group["id"], "group_name": group["name"], "sessions": sessions}
        controls = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Підтвердити заміну", callback_data=f"adm:replaceconfirm:{group['id']}")],
            [InlineKeyboardButton("Скасувати", callback_data="adm:replacecancel")]])
        return await update.message.reply_text(
            f"Новий розклад для «{group['name']}»:\n{format_schedule_preview(sessions)}\n\n"
            "Після підтвердження старий розклад цієї групи буде повністю замінено.", reply_markup=controls)
    setup = context.user_data.get("schedule_setup")
    if not setup or not is_admin(update, context) or update.effective_chat.type != "private":
        return
    value = update.message.text.strip()
    if value == "↩️ Скасувати":
        context.user_data.pop("schedule_setup", None)
        return await update.message.reply_text("Додавання тренування скасовано.",
                                               reply_markup=main_keyboard(is_admin(update, context)))
    if setup.get("step") == "time":
        try:
            setup["start_time"], setup["end_time"] = parse_time_range(value)
        except ValueError:
            return await update.message.reply_text("Введіть час як 18:30-20:30 або натисніть «↩️ Скасувати».")
        setup["step"] = "location"
        return await update.message.reply_text("Введіть місце тренування або надішліть «-», якщо його не потрібно вказувати.",
                                               reply_markup=cancel_keyboard())
    if setup.get("step") == "location":
        location = "" if value == "-" else value[:120]
        db(context).add_schedule(setup["group_id"], setup["weekday"], setup["start_time"],
                                 location, setup["end_time"])
        context.user_data.pop("schedule_setup", None)
        return await update.message.reply_text("Тренування додано до розкладу.",
                                              reply_markup=main_keyboard(is_admin(update, context)))


async def cancel_schedule_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    context.user_data.pop("schedule_setup", None)
    await query.answer("Додавання скасовано.")
    await query.edit_message_text("Додавання тренування скасовано.", reply_markup=admin_keyboard(context))


def admin_keyboard(context):
    groups = db(context).list_groups()
    rows = [[InlineKeyboardButton(f"👥 {group['name']}", callback_data=f"adm:group:{group['id']}")]
            for group in groups]
    rows.insert(0, [InlineKeyboardButton(f"📨 Заявки ({len(db(context).pending_players())})", callback_data="adm:pending")])
    rows.insert(1, [InlineKeyboardButton(f"🆕 Новачки ({len(db(context).pending_newcomers())})", callback_data="adm:newcomers")])
    rows.insert(2, [InlineKeyboardButton("📊 Статистика відвідування", callback_data="adm:stats")])
    rows.insert(3, [InlineKeyboardButton("🗑 Видалити зареєстрованого гравця", callback_data="adm:delete")])
    rows.insert(4, [InlineKeyboardButton("🖼 Змінити аватар бота", callback_data="adm:avatar")])
    rows.append([InlineKeyboardButton("📅 Розклад", callback_data="adm:schedule")])
    return InlineKeyboardMarkup(rows)


def newcomer_card_text(applicant):
    birth_date = applicant["birth_date"]
    try:
        birth_date = datetime.fromisoformat(birth_date).strftime("%d.%m.%Y")
    except ValueError:
        pass
    return (f"Заявка новачка: {applicant['full_name']}\nПІБ: {applicant['full_name']}\n"
            f"Дата народження: {birth_date or '—'}\nСтать: {applicant['gender'] or '—'}\n"
            f"Зріст: {applicant['height_cm'] or '—'} см\nВага: {applicant['weight_kg'] or '—'} кг\n"
            f"Досвід: {applicant['experience'] or '—'}\nМісто: {applicant['city'] or '—'}\n"
            f"Телефон: {applicant['phone'] or '—'}\nTelegram: {applicant['telegram_link'] or '—'}\n"
            f"Telegram ID: {applicant['telegram_id']}")


def format_schedule(rows):
    if not rows:
        return "Розклад ще не додано."
    grouped = {}
    for row in rows:
        grouped.setdefault(row["name"], []).append(row)
    blocks = ["Розклад:"]
    for name, sessions in sorted(grouped.items(), key=lambda item: item[1][0]["id"]):
        blocks.append(name + "\n" + "\n".join(
            f"• {row['weekday']}: {row['time']}" + (f"–{row['end_time']}" if row["end_time"] else "")
            + (f" — {row['location']}" if row["location"] else "") for row in sessions))
    return "\n\n".join(blocks)


def payment_month(now):
    # Before the monthly reminder window, mark this month's payment; from the 20th,
    # the payment refers to the next month, as stated in the club reminders.
    year, month = now.year, now.month
    if now.day >= 20:
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return f"{year:04d}-{month:02d}"


async def show_group_roster(query, context, group_id):
    groups = {group["id"]: group["name"] for group in db(context).list_groups()}
    group_name = groups.get(group_id)
    if not group_name:
        return await query.edit_message_text("Групу не знайдено.", reply_markup=admin_keyboard(context))
    settings = context.application.bot_data["settings"]
    now = datetime.now(ZoneInfo(settings.timezone))
    month = payment_month(now)
    players = db(context).player_cards_in_group(group_id, month)
    await query.edit_message_text(f"База гравців: {group_name} ({len(players)})",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Статистика відвідування", callback_data=f"adm:stats:{group_id}")],
            [InlineKeyboardButton("↩️ До панелі", callback_data="adm:home")]]))
    if not players:
        await context.bot.send_message(query.message.chat.id, "У цій групі ще немає зареєстрованих гравців.")
        return
    for player in players:
        if player["status"] != "active":
            state = "Анкету зупинено/видалено"
        elif player["training_paused"]:
            state = "Тренування тимчасово призупинені"
        else:
            state = "Активний"
        text, controls = player_card_view(player, group_id, context, now, state)
        await context.bot.send_message(query.message.chat.id, text, reply_markup=controls)


def player_card_view(player, group_id, context, now, state=None):
    database = db(context)
    month = payment_month(now)
    season = season_key(now)
    next_season = next_season_key(season)
    now_utc = now.astimezone(timezone.utc)
    missed = database.missed_workouts_in_period(player["telegram_id"],
                                               three_months_before(now_utc).isoformat(), now_utc.isoformat())
    certificates = database.discount_certificates(player["telegram_id"])
    current15 = next((item for item in certificates if item["percent"] == 15 and item["valid_season"] == season), None)
    current30 = next((item for item in certificates if item["percent"] == 30 and item["valid_season"] == season), None)
    next30 = next((item for item in certificates if item["percent"] == 30 and item["valid_season"] == next_season), None)
    payment = {"paid": "Заплатив", "unpaid": "Не оплачено", "seat_paid": "Оплачено за місце"}[player["payment_status"]]
    state = state or ("Тренування тимчасово призупинені" if player["training_paused"] else "Активний")
    text = (f"{player['full_name']}\nТелефон: {player['phone'] or '—'}\n"
            f"Позиція: {player['position'] or '—'}\nСтатус: {state}\nОплата за {month}: {payment}\n"
            f"Пропуски за останні 3 місяці: {missed} (відповіді «-»)\n"
            f"Знижка 15% на сезон {season}: " +
            ("використана" if current15 and current15["redeemed_at"] else "надана" if current15 else "не надана") + "\n"
            f"Знижка 30% на наступний сезон {next_season}: " + ("надана" if next30 else "не надана") + "\n"
            f"Знижка 30% на поточний сезон: " +
            ("використана" if current30 and current30["redeemed_at"] else "надана" if current30 else "не надана"))
    player_id = player["telegram_id"]
    rows = [[InlineKeyboardButton("✅ Заплатив", callback_data=f"pa:{player_id}:paid:{group_id}"),
             InlineKeyboardButton("❌ Не оплачено", callback_data=f"pa:{player_id}:unpaid:{group_id}")],
            [InlineKeyboardButton("💺 Оплачено за місце", callback_data=f"pa:{player_id}:seat:{group_id}")]]
    if player["status"] == "active":
        control = (InlineKeyboardButton("▶️ Відновити тренування", callback_data=f"pa:{player_id}:resume:{group_id}")
                   if player["training_paused"] else
                   InlineKeyboardButton("⏸ Призупинити тренування", callback_data=f"pa:{player_id}:pause:{group_id}"))
        rows.append([control, InlineKeyboardButton("🗑 Прибрати з реєстрації", callback_data=f"pa:{player_id}:remove:{group_id}")])
        if missed < 4 and current15 is None:
            rows.append([InlineKeyboardButton("🏷 Надати знижку 15%", callback_data=f"disc:{player_id}:15:{group_id}")])
        if next30 is None:
            rows.append([InlineKeyboardButton("🏅 Надати знижку 30%", callback_data=f"disc:{player_id}:30:{group_id}")])
        if current15 and current15["redeemed_at"] is None:
            rows.append([InlineKeyboardButton("✅ Позначити 15% використаною", callback_data=f"redeemdisc:{player_id}:15:{group_id}")])
        if current30 and current30["redeemed_at"] is None:
            rows.append([InlineKeyboardButton("✅ Позначити 30% використаною", callback_data=f"redeemdisc:{player_id}:30:{group_id}")])
    return text, InlineKeyboardMarkup(rows)


def season_key(now):
    start_year = now.year if now.month >= 9 else now.year - 1
    return f"{start_year}-{start_year + 1}"


def next_season_key(current):
    start_year = int(current.split("-", 1)[0]) + 1
    return f"{start_year}-{start_year + 1}"


def three_months_before(value):
    total_month = value.year * 12 + value.month - 1 - 3
    year, month_zero = divmod(total_month, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def show_attendance_group_picker(query, context):
    groups = db(context).list_groups()
    rows = [[InlineKeyboardButton(group["name"], callback_data=f"adm:stats:{group['id']}")]
            for group in groups]
    rows.append([InlineKeyboardButton("↩️ До панелі", callback_data="adm:home")])
    await query.edit_message_text("Оберіть групу для статистики за поточний місяць:",
                                  reply_markup=InlineKeyboardMarkup(rows))


async def show_attendance_stats(query, context, group_id):
    group = db(context).get_group(group_id)
    if not group:
        return await query.edit_message_text("Групу не знайдено.", reply_markup=admin_keyboard(context))
    settings = context.application.bot_data["settings"]
    now = datetime.now(ZoneInfo(settings.timezone))
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    players = db(context).attendance_stats(group_id, month_start.astimezone(timezone.utc).isoformat(),
                                           now.astimezone(timezone.utc).isoformat())
    month_names = ("січень", "лютий", "березень", "квітень", "травень", "червень",
                   "липень", "серпень", "вересень", "жовтень", "листопад", "грудень")
    period = f"{month_names[now.month - 1]} {now.year}"
    lines = [f"Статистика відвідування — {group['name']}\nЗа {period}:"
             if players else f"Для групи «{group['name']}» за {period} поки немає гравців або тренувань."]
    for player in players:
        person_type, profile = db(context).person(player["telegram_id"])
        registration = f"{profile['phone'] or 'телефон не вказаний'}, {profile['position'] or 'позиція не вказана'}" if profile else ""
        lines.append(f"• {player['full_name']} ({registration}) — відвідувань: {player['attended'] or 0}; "
                     f"пропусків: {player['missed'] or 0}; "
                     f"не відповів: {player['no_response'] or 0}")
    report = "\n".join(lines)
    chunks = []
    chunk = ""
    for line in report.splitlines():
        if chunk and len(chunk) + len(line) + 1 > 3800:
            chunks.append(chunk)
            chunk = ""
        chunk += ("\n" if chunk else "") + line
    if chunk:
        chunks.append(chunk)
    controls = InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ До вибору групи", callback_data="adm:stats")],
        [InlineKeyboardButton("До панелі", callback_data="adm:home")]])
    await query.edit_message_text(chunks[0], reply_markup=controls)
    for extra_chunk in chunks[1:]:
        await context.bot.send_message(query.message.chat.id, extra_chunk)


async def player_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, raw_player_id, action, raw_group_id = query.data.split(":")
        player_id, group_id = int(raw_player_id), int(raw_group_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося виконати дію.", show_alert=True)
    if action in {"paid", "unpaid", "seat"}:
        settings = context.application.bot_data["settings"]
        month = payment_month(datetime.now(ZoneInfo(settings.timezone)))
        status, message = {"paid": ("paid", "Ваша оплата підтверджена"),
                           "unpaid": ("unpaid", "Нагадування про оплату"),
                           "seat": ("seat_paid", "Оплата за місце підтверджена")}[action]
        db(context).set_payment_status(player_id, month, status)
        delivered = True
        try:
            await context.bot.send_message(player_id, message)
        except Exception:
            delivered = False
            logging.getLogger(__name__).info("Could not send payment notice to player %s", player_id)
        await query.answer("Статус збережено." if delivered else
                           "Статус збережено, але гравцю не надіслати повідомлення. Нехай він відкриє чат із ботом.",
                           show_alert=not delivered)
        await query.edit_message_text(query.message.text.rsplit("\nОплата за ", 1)[0] + f"\nОплата за {month}: " +
                                      {"paid": "Заплатив", "unpaid": "Не оплачено", "seat_paid": "Оплачено за місце"}[status],
                                      reply_markup=query.message.reply_markup)
        return
    if action == "remove":
        controls = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Так, видалити всі дані",
                                  callback_data=f"pa:{player_id}:removeconfirm:{group_id}")],
            [InlineKeyboardButton("Скасувати", callback_data=f"adm:group:{group_id}")]])
        return await query.edit_message_text(
            f"Назавжди видалити гравця? Анкета, відвідування, оплати та знижки будуть стерті.",
            reply_markup=controls)
    if action == "removeconfirm":
        _, player = db(context).person(player_id)
        if not player or not db(context).delete_player(player_id):
            return await query.answer("Гравця вже видалено або не знайдено.", show_alert=True)
        await query.answer("Гравця та всі його дані видалено.")
        return await query.edit_message_text(f"Гравця «{player['full_name']}» та всі пов’язані з ним дані видалено.",
                                             reply_markup=None)
    changed = db(context).change_player_state(player_id, action, update.effective_user.id)
    if not changed:
        return await query.answer("Статус гравця вже змінився.", show_alert=True)
    text = {"pause": "Тренування призупинено. За цей період гравець не враховується у статистиці.",
            "resume": "Тренування гравця відновлено."}.get(action, "Зміни збережено.")
    await query.answer("Зміни збережено.")
    if action in {"pause", "resume"}:
        rows = db(context).player_cards_in_group(group_id, payment_month(datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone))))
        player = next((row for row in rows if row["telegram_id"] == player_id), None)
        if player:
            now = datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone))
            card_text, markup = player_card_view(player, group_id, context, now)
        else:
            card_text = query.message.text
            markup = None
    else:
        markup = query.message.reply_markup
        card_text = query.message.text
    await query.edit_message_text(card_text + "\n\n" + text, reply_markup=markup)


async def discount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, raw_player_id, raw_percent, raw_group_id = query.data.split(":")
        player_id, percent, group_id = int(raw_player_id), int(raw_percent), int(raw_group_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося прочитати сертифікат.", show_alert=True)
    if percent not in {15, 30}:
        return await query.answer("Невідомий розмір знижки.", show_alert=True)
    settings = context.application.bot_data["settings"]
    now = datetime.now(ZoneInfo(settings.timezone))
    issued_season = season_key(now)
    valid_season = issued_season if percent == 15 else next_season_key(issued_season)
    player_type, player = db(context).person(player_id)
    if player_type != "players" or not player or player["status"] != "active":
        return await query.answer("Знижку можна надати лише активному гравцеві.", show_alert=True)
    if percent == 15:
        now_utc = now.astimezone(timezone.utc)
        missed = db(context).missed_workouts_in_period(player_id,
            three_months_before(now_utc).isoformat(), now_utc.isoformat())
        if missed >= 4:
            return await query.answer(f"Знижка недоступна: за 3 місяці {missed} пропусків.", show_alert=True)
    certificate_id = db(context).create_discount_certificate(player_id, percent, issued_season, valid_season)
    if certificate_id is None:
        return await query.answer(f"Сертифікат {percent}% на цей сезон уже надавали.", show_alert=True)
    caption = (f"Вітаємо! Вам доступна одноразова знижка 15% на місячний абонемент протягом сезону {valid_season}. "
               "Сертифікат можна використати один раз."
               if percent == 15 else
               f"Вітаємо! Вам надано сертифікат на знижку 30% від вартості місячного абонемента. "
               f"Використати його можна протягом наступного сезону {valid_season}.")
    gif_path = Path(__file__).resolve().parent.parent / "assets" / f"discount{percent}.gif"
    try:
        with gif_path.open("rb") as animation:
            await context.bot.send_animation(chat_id=player_id, animation=animation, caption=caption)
    except Exception:
        db(context).discard_discount_certificate(certificate_id)
        logging.getLogger(__name__).exception("Could not send discount certificate to player %s", player_id)
        return await query.answer("Не вдалося надіслати GIF. Гравець має відкрити чат із ботом.", show_alert=True)
    await query.answer(f"Сертифікат {percent}% надіслано гравцеві.")
    rows = db(context).player_cards_in_group(group_id, payment_month(now))
    refreshed = next((row for row in rows if row["telegram_id"] == player_id), None)
    if refreshed:
        card_text, markup = player_card_view(refreshed, group_id, context, now)
        await query.edit_message_text(card_text + f"\n\nGIF-сертифікат {percent}% надіслано.", reply_markup=markup)


async def redeem_discount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, raw_player_id, raw_percent, raw_group_id = query.data.split(":")
        player_id, percent, group_id = int(raw_player_id), int(raw_percent), int(raw_group_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося прочитати сертифікат.", show_alert=True)
    current_season = season_key(datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone)))
    if not db(context).redeem_discount_certificate(player_id, percent, current_season):
        return await query.answer("Чинний сертифікат не знайдено або його вже використано.", show_alert=True)
    await query.answer(f"Знижку {percent}% позначено використаною.")
    now = datetime.now(ZoneInfo(context.application.bot_data["settings"].timezone))
    rows = db(context).player_cards_in_group(group_id, payment_month(now))
    refreshed = next((row for row in rows if row["telegram_id"] == player_id), None)
    if refreshed:
        card_text, markup = player_card_view(refreshed, group_id, context, now)
        await query.edit_message_text(card_text + f"\n\nЗнижку {percent}% використано в сезоні {current_season}.",
                                      reply_markup=markup)


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, player_id, decision = query.data.split(":")
        player_id = int(player_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося прочитати заявку.", show_alert=True)
    approved = decision == "approve"
    if approved and not db(context).player_group_ids(player_id):
        groups = db(context).list_groups()
        choices = [[InlineKeyboardButton(group["name"], callback_data=f"reviewgroup:{player_id}:{group['id']}")]
                   for group in groups]
        await query.answer()
        return await query.edit_message_text("Для цієї заявки ще не обрано групу. Оберіть її, щоб підтвердити гравця.",
                                             reply_markup=InlineKeyboardMarkup(choices))
    changed = db(context).review_player(player_id, approved, update.effective_user.id)
    if not changed:
        return await query.answer("Заявку вже оброблено.", show_alert=True)
    await query.answer("Заявку оброблено.")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✅ Гравця підтверджено." if approved else "❌ Заявку відхилено.")
    try:
        message = ("Вашу анкету підтверджено. Ласкаво просимо до Typhoon!" if approved
                   else "Вашу заявку на вступ до Typhoon відхилено. Якщо це помилка, зв’яжіться з адміністратором.")
        await context.bot.send_message(player_id, message)
    except Exception:
        logging.getLogger(__name__).exception("Could not notify player %s after review", player_id)


async def review_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, player_id, group_id = query.data.split(":")
        player_id, group_id = int(player_id), int(group_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося прочитати вибір групи.", show_alert=True)
    player_type, player = db(context).person(player_id)
    if player_type != "players" or not player or player["status"] != "pending":
        return await query.answer("Заявку вже оброблено.", show_alert=True)
    db(context).set_player_groups(player_id, [group_id])
    changed = db(context).review_player(player_id, True, update.effective_user.id)
    if not changed:
        return await query.answer("Не вдалося підтвердити заявку.", show_alert=True)
    await query.answer("Гравця підтверджено.")
    await query.edit_message_text(f"✅ Гравця підтверджено та додано до групи {group_id}.")
    try:
        await context.bot.send_message(player_id, "Вашу анкету підтверджено. Ласкаво просимо до Typhoon!")
    except Exception:
        logging.getLogger(__name__).exception("Could not notify player %s after review", player_id)


async def newcomer_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(update, context) or query.message.chat.type != "private":
        return await query.answer("Ця дія доступна лише адміністратору.", show_alert=True)
    try:
        _, raw_id, decision = query.data.split(":")
        applicant_id = int(raw_id)
    except (ValueError, TypeError):
        return await query.answer("Не вдалося прочитати заявку.", show_alert=True)
    if decision not in {"approve", "reject"}:
        return await query.answer("Невідома дія.", show_alert=True)
    approved = decision == "approve"
    if not db(context).review_newcomer(applicant_id, approved, update.effective_user.id):
        return await query.answer("Заявку вже оброблено.", show_alert=True)
    await query.answer("Рішення збережено.")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✅ Анкету новачка прийнято." if approved else "❌ Анкету відхилено.")
    message = ("Вашу анкету прийнято. Адміністратор Typhoon зв’яжеться з вами за телефоном або Telegram."
               if approved else "Дякуємо за інтерес до Typhoon. Наразі вашу анкету не прийнято.")
    try:
        await context.bot.send_message(applicant_id, message)
    except Exception:
        logging.getLogger(__name__).info("Could not notify newcomer %s", applicant_id)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Заповнення скасовано.",
                                    reply_markup=main_keyboard(is_admin(update, context)))
    return ConversationHandler.END


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    table, row = db(context).person(update.effective_user.id)
    if not row:
        await update.message.reply_text("Анкету не знайдено. Оберіть реєстрацію в меню нижче.",
                                        reply_markup=main_keyboard(is_admin(update, context)))
        return
    extra = row.get("position", row.get("experience", "")) or "—"
    status = {"pending": "очікує підтвердження", "active": "активний", "inactive": "неактивний",
              "new": "новий", "invited": "запрошений", "converted": "переведений до гравців", "closed": "закритий"}.get(row.get("status", ""), "")
    if table == "newcomers":
        try:
            birth_date = datetime.fromisoformat(row.get("birth_date", "")).strftime("%d.%m.%Y")
        except ValueError:
            birth_date = row.get("birth_date", "") or "—"
        details = (f"ПІБ: {row['full_name']}\nДата народження: {birth_date}\nСтать: {row.get('gender') or '—'}\n"
                   f"Зріст: {row.get('height_cm') or '—'} см\nВага: {row.get('weight_kg') or '—'} кг\n"
                   f"Досвід: {extra}\nМісто: {row.get('city') or '—'}\nТелефон: {row['phone'] or '—'}\n"
                   f"Telegram: {row.get('telegram_link') or '—'}")
    else:
        details = f"Ім’я: {row['full_name']}\nТелефон: {row['phone'] or '—'}\nПозиція: {extra}"
    controls = None
    if table == "newcomers":
        controls = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Видалити анкету", callback_data="nd:ask")]])
    await update.message.reply_text(f"Тип анкети: {'гравець' if table == 'players' else 'новачок'}\n{details}\nСтатус: {status}",
                                    reply_markup=controls or main_keyboard(is_admin(update, context)))


async def newcomer_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.message.chat.type != "private" or not update.effective_user:
        return await query.answer("Видалити анкету можна лише в особистому чаті з ботом.", show_alert=True)
    decision = query.data.split(":", 1)[1]
    player_type, person = db(context).person(update.effective_user.id)
    if player_type != "newcomers" or not person:
        return await query.answer("Анкету новачка не знайдено.", show_alert=True)
    if decision == "ask":
        await query.answer()
        return await query.edit_message_text(
            "Видалити вашу анкету новачка? Вона зникне з адмін-панелі, а адміністратору надійде повідомлення.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Так, видалити", callback_data="nd:confirm")],
                [InlineKeyboardButton("Скасувати", callback_data="nd:cancel")]]))
    if decision == "cancel":
        await query.answer("Видалення скасовано.")
        return await query.edit_message_text("Анкету залишено.")
    if decision != "confirm":
        return await query.answer("Невідома дія.", show_alert=True)
    notices = db(context).delete_newcomer(update.effective_user.id)
    if notices is None:
        return await query.answer("Анкету вже видалено.", show_alert=True)
    failed_notice = False
    for notice in notices:
        try:
            await context.bot.delete_message(chat_id=notice["admin_id"], message_id=notice["message_id"])
        except Exception:
            failed_notice = True
            logging.getLogger(__name__).info("Could not remove a newcomer notice from admin %s", notice["admin_id"])
    for admin_id in context.application.bot_data["settings"].admin_ids:
        try:
            await context.bot.send_message(admin_id, "Новачок видалив свою анкету. Заявку прибрано з адмін-панелі.")
        except Exception:
            logging.getLogger(__name__).info("Could not notify admin %s about withdrawn newcomer", admin_id)
    await query.answer("Анкету видалено.")
    text = "Анкету видалено. Адміністратора повідомлено."
    if failed_notice:
        text += " Якщо попереднє повідомлення не вдалося прибрати, воно більше не дає змоги обробити заявку."
    await query.edit_message_text(text, reply_markup=main_keyboard(is_admin(update, context)))


async def begin_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    table, row = db(context).person(update.effective_user.id)
    if not row:
        await update.message.reply_text("Спочатку оберіть реєстрацію в меню.",
                                        reply_markup=main_keyboard(is_admin(update, context)))
        return ConversationHandler.END
    choices = ["Ім’я", "Телефон", "Позиція"] if table == "players" else ["Ім’я", "Телефон", "Досвід"]
    await update.message.reply_text("Що змінити? Оберіть поле кнопкою нижче.",
        reply_markup=ReplyKeyboardMarkup([[choice] for choice in choices] + [["↩️ Скасувати"]], resize_keyboard=True))
    return EDIT


async def edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = update.message.text.strip().lower()
    if field == "↩️ скасувати":
        return await cancel(update, context)
    mapping = {"ім’я": "name", "ім'я": "name", "телефон": "phone", "позиція": "position", "досвід": "experience"}
    if field not in mapping:
        await update.message.reply_text("Оберіть поле зі списку вище.")
        return EDIT
    context.user_data["edit_field"] = mapping[field]
    await update.message.reply_text("Введіть нове значення або натисніть «↩️ Скасувати»:")
    return EXTRA


async def edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ok = db(context).edit_person(update.effective_user.id, context.user_data.pop("edit_field", ""), update.message.text.strip()[:160])
    await update.message.reply_text("Анкету оновлено." if ok else "Не вдалося оновити анкету.",
                                    reply_markup=main_keyboard(is_admin(update, context)))
    return ConversationHandler.END


async def deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Так, припинити", callback_data=f"deactivate:{update.effective_user.id}:yes"),
                                      InlineKeyboardButton("Скасувати", callback_data=f"deactivate:{update.effective_user.id}:no")]])
    await update.message.reply_text("Підтвердьте припинення тренувань? Анкету можна буде активувати знову через адміністратора.",
                                    reply_markup=keyboard)


async def deactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, owner_id, decision = query.data.split(":")
    except ValueError:
        return await query.answer("Дія недоступна.", show_alert=True)
    if int(owner_id) != update.effective_user.id:
        return await query.answer("Це не ваша анкета.", show_alert=True)
    await query.answer()
    if decision == "no":
        return await query.edit_message_text("Дію скасовано.")
    with db(context).connect() as conn:
        conn.execute("UPDATE players SET status='inactive',updated_at=? WHERE telegram_id=? AND status='active'",
                     (db(context).now(), update.effective_user.id))
        changed = conn.execute("SELECT changes()").fetchone()[0]
    if changed:
        db(context).log(update.effective_user.id, "player_deactivated", update.effective_user.id)
        await query.edit_message_text("Анкету деактивовано. Вас більше не враховуватимуть у відвідуваності.")
    else:
        await query.edit_message_text("Активну анкету гравця не знайдено.")


async def groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db(context).list_groups()
    await update.message.reply_text("Групи:\n" + ("\n".join(f"{r['id']}. {r['name']}" for r in rows) or "Груп поки немає."))


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db(context).schedule()
    await update.message.reply_text(format_schedule(rows))


def parse_time_range(value):
    pieces = value.split("-", maxsplit=1)
    start = datetime.strptime(pieces[0], "%H:%M").strftime("%H:%M")
    end = datetime.strptime(pieces[1], "%H:%M").strftime("%H:%M") if len(pieces) == 2 else ""
    return start, end


async def group_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    args = update.message.text.partition(" ")[2].split(maxsplit=3)
    if len(args) != 4:
        return await update.message.reply_text("Формат: /group_add НАЗВА ДЕНЬ ПОЧАТОК-КІНЕЦЬ МІСЦЕ")
    try:
        start_time, end_time = parse_time_range(args[2])
    except ValueError:
        return await update.message.reply_text("Час вкажіть у форматі 16:30-18:00.")
    with db(context).connect() as conn:
        conn.execute("INSERT INTO training_groups(name,weekday,time,location) VALUES(?,?,?,?)",
                     (args[0], args[1], start_time, args[3]))
        group_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO training_schedules(group_id,weekday,time,end_time,location) VALUES(?,?,?,?,?)",
                     (group_id, args[1], start_time, end_time, args[3]))
    await update.message.reply_text(f"Групу створено. ID: {group_id}.")


async def schedule_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    args = update.message.text.partition(" ")[2].split(maxsplit=3)
    if len(args) != 4:
        return await update.message.reply_text("Формат: /schedule_add GROUP_ID ДЕНЬ ПОЧАТОК-КІНЕЦЬ МІСЦЕ")
    try:
        group_id = int(args[0])
        start_time, end_time = parse_time_range(args[2])
    except ValueError:
        return await update.message.reply_text("Перевірте ID групи й час у форматі ГГ:ХХ.")
    weekday = args[1].lower()
    if weekday not in {day for day_names in WEEKDAYS.values() for day in day_names}:
        return await update.message.reply_text("Вкажіть день тижня українською, наприклад: п’ятниця.")
    with db(context).connect() as conn:
        group = conn.execute("SELECT id FROM training_groups WHERE id=? AND active=1", (group_id,)).fetchone()
        if not group:
            return await update.message.reply_text("Активну групу з таким ID не знайдено.")
        conn.execute("INSERT INTO training_schedules(group_id,weekday,time,end_time,location) VALUES(?,?,?,?,?)",
                     (group_id, weekday, start_time, end_time, args[3]))
    await update.message.reply_text("Тренування додано до розкладу.")


async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    try:
        player_id, group_id = int(context.args[0]), int(context.args[1])
    except (ValueError, IndexError):
        return await update.message.reply_text("Формат: /join_group TELEGRAM_ID GROUP_ID")
    with db(context).connect() as conn:
        player = conn.execute("SELECT status FROM players WHERE telegram_id=?", (player_id,)).fetchone()
        group = conn.execute("SELECT id FROM training_groups WHERE id=? AND active=1", (group_id,)).fetchone()
        if not player or player["status"] != "active" or not group:
            return await update.message.reply_text("Потрібні підтверджений активний гравець і наявна група.")
        conn.execute("INSERT OR IGNORE INTO player_groups(player_id,group_id) VALUES(?,?)", (player_id, group_id))
    await update.message.reply_text("Гравця додано до групи.")


async def set_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    try:
        group_id, chat_id, thread_id = (int(value) for value in context.args[:3])
    except (ValueError, TypeError):
        return await update.message.reply_text("Формат: /set_destination GROUP_ID CHAT_ID THREAD_ID (для загального чату THREAD_ID=0)")
    with db(context).connect() as conn:
        conn.execute("UPDATE training_groups SET destination_chat_id=?,topic_thread_id=? WHERE id=? AND active=1",
                     (chat_id, thread_id or None, group_id))
        changed = conn.execute("SELECT changes()").fetchone()[0]
    await update.message.reply_text("Чат і гілку призначення збережено." if changed else "Активну групу з таким ID не знайдено.")


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    try:
        player_id = int(context.args[0])
    except (ValueError, IndexError):
        return await update.message.reply_text("Формат: /approve TELEGRAM_ID")
    with db(context).connect() as conn:
        conn.execute("UPDATE players SET status='active',updated_at=? WHERE telegram_id=? AND status='pending'", (db(context).now(), player_id))
        changed = conn.execute("SELECT changes()").fetchone()[0]
    if changed:
        db(context).log(update.effective_user.id, "player_approved", player_id)
        try:
            await context.bot.send_message(player_id, "Вашу анкету підтверджено. Ласкаво просимо до Typhoon! Адміністратор додасть вас до тренувальної групи.")
        except Exception:
            pass
    await update.message.reply_text("Гравця підтверджено." if changed else "Заявку не знайдено.")


async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        return await update.message.reply_text("Команда доступна лише адміністраторам.")
    try:
        group_id = int(context.args[0])
        date_text = " ".join(context.args[1:3])
        settings = context.application.bot_data["settings"]
        starts = datetime.strptime(date_text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(settings.timezone)).isoformat()
    except (ValueError, IndexError, KeyError):
        return await update.message.reply_text("Формат: /attendance GROUP_ID YYYY-MM-DD HH:MM")
    if not update.effective_chat or update.effective_chat.type == "private":
        return await update.message.reply_text("Створіть голосування у груповому чаті клубу.")
    configured_chat = context.application.bot_data["settings"].club_chat_id
    if configured_chat is None:
        return await update.message.reply_text("Адміністратор має налаштувати CLUB_CHAT_ID перед створенням голосувань.")
    if update.effective_chat.id != configured_chat:
        return await update.message.reply_text("Голосування дозволені лише в налаштованому чаті клубу.")
    group = db(context).get_group(group_id)
    if not group:
        return await update.message.reply_text("Групу не знайдено.")
    created = await send_attendance_poll(context, group, starts, update.effective_chat.id,
                                         update.effective_message.message_thread_id)
    if created:
        await update.message.reply_text("Голосування опубліковано.")


async def send_attendance_poll(context, group, starts_at, chat_id, thread_id=None):
    """Create a session and publish a visible Telegram poll to its destination."""
    db_instance = context.application.bot_data["db"]
    with db_instance.connect() as conn:
        date_key = starts_at[:10]
        exists = conn.execute("SELECT 1 FROM training_sessions WHERE group_id=? AND starts_at LIKE ? LIMIT 1",
                              (group["id"], f"{date_key}%")).fetchone()
        if exists:
            return False
        conn.execute("INSERT INTO training_sessions(group_id,starts_at,poll_chat_id) VALUES(?,?,?)",
                     (group["id"], starts_at, chat_id))
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    try:
        local_dt = datetime.fromisoformat(starts_at)
        question = local_dt.strftime("%d.%m.%y (%H:%M")
        if group.get("end_time"):
            question += f"-{group['end_time']}"
        question += ")"
        target_thread = thread_id if thread_id is not None else group.get("topic_thread_id")
        send_options = {"message_thread_id": target_thread} if target_thread else {}
        msg = await context.bot.send_poll(chat_id=chat_id, question=question, options=["+", "-"],
            is_anonymous=False, allows_multiple_answers=False, **send_options)
    except Exception:
        with db_instance.connect() as conn:
            conn.execute("DELETE FROM training_sessions WHERE id=?", (session_id,))
        raise
    with db_instance.connect() as conn:
        conn.execute("UPDATE training_sessions SET poll_message_id=?,poll_id=? WHERE id=?",
                     (msg.message_id, msg.poll.id, session_id))
    return True


WEEKDAYS = {
    0: {"понеділок", "понедельник", "monday", "пн"},
    1: {"вівторок", "вторник", "tuesday", "вт"},
    2: {"середа", "среда", "wednesday", "ср"},
    3: {"четвер", "четверг", "thursday", "чт"},
    4: {"п’ятниця", "пятниця", "пятница", "friday", "пт"},
    5: {"субота", "суббота", "saturday", "сб"},
    6: {"неділя", "воскресенье", "sunday", "нд"},
}


def parse_schedule_lines(value):
    if value.strip().casefold() in {"без тренировок", "немає тренувань", "нет тренировок"}:
        return []
    sessions = []
    seen = set()
    canonical_days = ("понеділок", "вівторок", "середа", "четвер", "п’ятниця", "субота", "неділя")
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.rsplit(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Не вдалося прочитати рядок «{line}».")
        normalized_day = parts[0].casefold().replace("'", "’")
        weekday_index = next((index for index, aliases in WEEKDAYS.items()
                              if normalized_day in {alias.replace("'", "’") for alias in aliases}), None)
        if weekday_index is None:
            raise ValueError(f"Не впізнав день у рядку «{line}».")
        try:
            start_time, end_time = parse_time_range(parts[1].replace("–", "-").replace("—", "-"))
        except ValueError as error:
            raise ValueError(f"Перевірте час у рядку «{line}»: використайте формат 16:30-18:00.") from error
        key = (weekday_index, start_time)
        if key in seen:
            raise ValueError(f"Тренування {canonical_days[weekday_index]} о {start_time} вказано двічі.")
        seen.add(key)
        sessions.append((canonical_days[weekday_index], start_time, end_time, ""))
    if not sessions:
        raise ValueError("Додайте щонайменше одне тренування або надішліть «без тренировок».")
    return sessions


def format_schedule_preview(sessions):
    if not sessions:
        return "Тренувань у розкладі не буде."
    return "\n".join(f"• {weekday}: {start_time}" + (f"–{end_time}" if end_time else "")
                     for weekday, start_time, end_time, _ in sessions)


async def scheduled_attendance(context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.bot_data["settings"]
    now = datetime.now(ZoneInfo(settings.timezone))
    # Publish at 16:00 local time on the calendar day before each training.
    # If the process was offline at 16:00, publish on its first run later that day.
    if now.hour < 16:
        return
    training_day = now.date() + timedelta(days=1)
    weekday = training_day.weekday()
    groups_today = db(context).schedule()
    for group in groups_today:
        if group["weekday"].strip().lower() not in WEEKDAYS[weekday]:
            continue
        try:
            training_time = datetime.strptime(group["time"].strip(), "%H:%M").time()
        except ValueError:
            continue
        starts_at = datetime.combine(training_day, training_time, tzinfo=ZoneInfo(settings.timezone)).isoformat()
        target_chat = group.get("destination_chat_id") or settings.club_chat_id
        if target_chat is None:
            continue
        try:
            await send_attendance_poll(context, group, starts_at, target_chat)
        except Exception:
            logging.getLogger(__name__).exception("Could not publish scheduled attendance poll for group %s", group["id"])


async def scheduled_payment_reminders(context: ContextTypes.DEFAULT_TYPE):
    settings = context.application.bot_data["settings"]
    now = datetime.now(ZoneInfo(settings.timezone))
    if now.hour < 10 or now.day < 20:
        return
    reminder_day = 20 if now.day < 26 else 26
    month_key = now.strftime("%Y-%m")
    message = ("Вітаю! Нагадування про початок оплати абонемента за наступний місяць"
               if reminder_day == 20 else
               "Вітаю! Сьогодні останній день оплати абонементу за наступний місяць")
    database = context.application.bot_data["db"]
    for group in database.list_groups():
        target_chat = group["destination_chat_id"] or settings.club_chat_id
        if target_chat is None:
            continue
        with database.connect() as conn:
            sent = conn.execute("SELECT 1 FROM club_reminders WHERE group_id=? AND month=? AND reminder_day=?",
                                (group["id"], month_key, reminder_day)).fetchone()
        if sent:
            continue
        try:
            # No message_thread_id: payment reminders belong in each group's main chat.
            await context.bot.send_message(chat_id=target_chat, text=message)
            with database.connect() as conn:
                conn.execute("INSERT OR IGNORE INTO club_reminders(group_id,month,reminder_day,sent_at) VALUES(?,?,?,?)",
                             (group["id"], month_key, reminder_day, database.now()))
        except Exception:
            logging.getLogger(__name__).exception("Could not send payment reminder for group %s", group["id"])


async def record_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll_answer = update.poll_answer
    if not poll_answer.user:
        return
    user_id = poll_answer.user.id
    answer = ("yes" if poll_answer.option_ids[0] == 0 else "no") if poll_answer.option_ids else None
    with db(context).connect() as conn:
        session = conn.execute("SELECT s.id,s.group_id,s.status FROM training_sessions s WHERE s.poll_id=?",
                               (poll_answer.poll_id,)).fetchone()
        # The poll itself identifies its training group. Count active registered
        # players who vote in that poll; no separate group assignment is needed.
        eligible = conn.execute("SELECT 1 FROM players p JOIN player_groups pg ON pg.player_id=p.telegram_id "
                                "WHERE p.telegram_id=? AND p.status='active' AND p.training_paused=0 AND pg.group_id=?",
                                (user_id, session["group_id"] if session else -1)).fetchone()
        if not session or session["status"] != "open" or not eligible:
            return
        if answer is None:
            conn.execute("DELETE FROM attendance_votes WHERE session_id=? AND player_id=?",
                         (session["id"], user_id))
            return
        conn.execute("INSERT INTO attendance_votes(session_id,player_id,answer,voted_at) VALUES(?,?,?,?) "
                     "ON CONFLICT(session_id,player_id) DO UPDATE SET answer=excluded.answer,voted_at=excluded.voted_at",
                     (session["id"], user_id, answer, db(context).now()))


def handlers():
    conversation_text = filters.TEXT & ~filters.COMMAND & ~filters.Regex("^↩️ Скасувати$")
    register = ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{REGISTER_BUTTON}$"), begin_player)],
        states={NAME: [MessageHandler(conversation_text, got_name)],
                PHONE: [MessageHandler(conversation_text, got_phone)],
                EXTRA: [MessageHandler(conversation_text, got_extra)],
                GROUP_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_player_groups)]},
        fallbacks=[MessageHandler(filters.Regex("^↩️ Скасувати$"), cancel)],
        name="player_registration", persistent=False)
    newcomer = ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{NEWCOMER_BUTTON}$"), begin_newcomer)],
        states={NEW_NAME: [MessageHandler(conversation_text, newcomer_name)],
                NEW_BIRTH_DATE: [MessageHandler(conversation_text, newcomer_birth_date)],
                NEW_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex("^↩️ Скасувати$"), newcomer_gender)],
                NEW_HEIGHT: [MessageHandler(conversation_text, newcomer_height)],
                NEW_WEIGHT: [MessageHandler(conversation_text, newcomer_weight)],
                NEW_EXPERIENCE: [MessageHandler(conversation_text, newcomer_experience)],
                NEW_CITY: [MessageHandler(conversation_text, newcomer_city)],
                NEW_PHONE: [MessageHandler(conversation_text, newcomer_phone)],
                NEW_TELEGRAM: [MessageHandler(conversation_text, newcomer_telegram)]},
        fallbacks=[MessageHandler(filters.Regex("^↩️ Скасувати$"), cancel)],
        name="newcomer_registration", persistent=False)
    edit = ConversationHandler(entry_points=[MessageHandler(filters.Regex(f"^{EDIT_BUTTON}$"), begin_edit)],
        states={EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field)],
                EXTRA: [MessageHandler(conversation_text, edit_value)]},
        fallbacks=[MessageHandler(filters.Regex("^↩️ Скасувати$"), cancel)],
        name="profile_edit", persistent=False)
    return [CommandHandler("start", start), CommandHandler("help", help_command), CommandHandler("id", show_ids),
            register, newcomer, edit,
            MessageHandler(filters.Regex(f"^{PROFILE_BUTTON}$"), profile),
            MessageHandler(filters.Regex(f"^{SCHEDULE_BUTTON}$"), schedule),
            MessageHandler(filters.Regex(f"^{ADMIN_BUTTON}$"), show_admin_menu),
            MessageHandler(filters.PHOTO, set_bot_avatar),
            CallbackQueryHandler(admin_callback, pattern=r"^adm:"),
            CallbackQueryHandler(player_action_callback, pattern=r"^pa:"),
            CallbackQueryHandler(discount_callback, pattern=r"^disc:"),
            CallbackQueryHandler(redeem_discount_callback, pattern=r"^redeemdisc:"),
            CallbackQueryHandler(review_callback, pattern=r"^review:"),
            CallbackQueryHandler(review_group_callback, pattern=r"^reviewgroup:"),
            CallbackQueryHandler(newcomer_review_callback, pattern=r"^nr:"),
            CallbackQueryHandler(newcomer_delete_callback, pattern=r"^nd:"),
            CallbackQueryHandler(deactivate_callback, pattern=r"^deactivate:"),
            CallbackQueryHandler(schedule_day_callback, pattern=r"^slotday:"),
            CallbackQueryHandler(cancel_schedule_setup, pattern=r"^slotcancel$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_input),
            PollAnswerHandler(record_poll_answer)]
