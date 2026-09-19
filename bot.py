import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)

import config
import database as db

logging.basicConfig(level=logging.INFO)

router = Router()

# user_id -> id файла в БД, ожидающего подтверждения подписки
pending_downloads: dict[int, int] = {}


def is_admin(user_id: int) -> bool:
    return user_id == config.ADMIN_ID


def photo() -> FSInputFile:
    return FSInputFile(config.PHOTO_PATH)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗝Наш канал", url=config.CHANNEL_URL)],
            [InlineKeyboardButton(text="👤Профиль", callback_data="profile")],
        ]
    )


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]]
    )


def extract_chat_id(link: str) -> str:
    """Превращает https://t.me/name или @name в формат для get_chat_member."""
    link = link.strip()
    if link.startswith("https://t.me/"):
        username = link.split("https://t.me/")[1].split("/")[0]
        return f"@{username}"
    if link.startswith("@"):
        return link
    return f"@{link}"


async def check_subscriptions(bot: Bot, user_id: int) -> list[str]:
    """Возвращает список каналов (ссылок), на которые пользователь НЕ подписан."""
    not_subscribed = []
    for link in db.get_channels():
        chat_id = extract_chat_id(link)
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ("left", "kicked"):
                not_subscribed.append(link)
        except Exception:
            # Если бот не админ канала / не может проверить — считаем, что не подписан
            not_subscribed.append(link)
    return not_subscribed


def subscribe_kb(channels: list[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="📢 Подписаться", url=link)] for link in channels]
    buttons.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_file_to_user(bot: Bot, user_id: int, file_db_id: int):
    file_row = db.get_file(file_db_id)
    if file_row is None:
        await bot.send_message(user_id, "⚠️ Файл не найден.")
        return

    file_type = file_row["file_type"] or "document"
    caption = file_row["caption"]
    file_id = file_row["file_id"]

    if file_type == "video":
        await bot.send_video(user_id, video=file_id, caption=caption)
    elif file_type == "audio":
        await bot.send_audio(user_id, audio=file_id, caption=caption)
    elif file_type == "photo":
        await bot.send_photo(user_id, photo=file_id, caption=caption)
    else:
        await bot.send_document(user_id, document=file_id, caption=caption)

    db.increment_files_received(user_id)


# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot):
    user = message.from_user
    db.add_user(user.id, user.first_name or "", user.username or "")

    payload = command.args  # то, что идёт после /start (диплинк)

    if payload and payload.startswith("file_"):
        try:
            file_db_id = int(payload.split("_", 1)[1])
        except ValueError:
            file_db_id = None

        if file_db_id is not None:
            not_subscribed = await check_subscriptions(bot, user.id)
            if not_subscribed:
                pending_downloads[user.id] = file_db_id
                await message.answer_photo(
                    photo=photo(),
                    caption="🚫 Для получения файла подпишитесь на канал(ы):",
                    reply_markup=subscribe_kb(not_subscribed),
                )
                return

            await send_file_to_user(bot, user.id, file_db_id)
            return

    await message.answer_photo(
        photo=photo(),
        caption="🔥 Привет! Тут можно скачать файлы с канала «WerareMods!»",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    file_db_id = pending_downloads.get(user_id)
    if file_db_id is None:
        await callback.answer("Нет ожидающих файлов.", show_alert=True)
        return

    not_subscribed = await check_subscriptions(bot, user_id)
    if not_subscribed:
        await callback.answer("❌ Вы подписались не на все каналы.", show_alert=True)
        return

    await callback.answer("✅ Подписка подтверждена!")
    pending_downloads.pop(user_id, None)
    await send_file_to_user(bot, user_id, file_db_id)


@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = callback.from_user
    row = db.get_user(user.id)
    files_received = row["files_received"] if row else 0
    text = (
        "👤 Ваш Профиль:\n\n"
        f"🆔 ID: {user.id}\n"
        f"👤 Имя: {user.first_name}\n"
        f"🌐 Username: @{user.username if user.username else '-'}\n"
        f"📥 Файлов получено: {files_received}"
    )
    await callback.message.edit_caption(caption=text, reply_markup=back_kb())
    await callback.answer()


@router.callback_query(F.data == "back_main")
async def cb_back_main(callback: CallbackQuery):
    await callback.message.edit_caption(
        caption="🔥 Привет! Тут можно скачать файлы с канала «WerareMods!»",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


# ==================== /post ====================

class PostStates(StatesGroup):
    waiting_content = State()


def confirm_post_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="post_cancel"),
                InlineKeyboardButton(text="✅ Отправить", callback_data="post_send"),
            ]
        ]
    )


@router.message(Command("post"))
async def cmd_post(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer_photo(photo=photo(), caption="🚫 Доступ ограничен")
        return
    await message.answer(
        "✏️ Отправьте пост для рассылки:\n\n"
        "— просто текст (без фото), либо\n"
        "— фото с подписью (текст в подписи к фото).\n\n"
        "Затем нажмёте «Отправить» или «Отмена»."
    )
    await state.set_state(PostStates.waiting_content)


@router.message(PostStates.waiting_content, F.photo)
async def post_photo_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.caption or ""
    photo_id = message.photo[-1].file_id
    await state.update_data(post_text=text, post_photo=photo_id)
    await message.answer_photo(
        photo=photo_id,
        caption=f"Предпросмотр рассылки:\n\n{text}" if text else "Предпросмотр рассылки (без текста)",
        reply_markup=confirm_post_kb(),
    )


@router.message(PostStates.waiting_content, F.text)
async def post_text_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text or ""
    await state.update_data(post_text=text, post_photo=None)
    await message.answer(
        f"Предпросмотр рассылки:\n\n{text}",
        reply_markup=confirm_post_kb(),
    )


@router.callback_query(F.data == "post_cancel")
async def cb_post_cancel(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await callback.answer()
    await callback.message.answer("🚫 Рассылка отменена.")


@router.callback_query(F.data == "post_send")
async def cb_post_send(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    text = data.get("post_text", "")
    post_photo = data.get("post_photo")
    await state.clear()
    await callback.answer("Рассылка запущена...")

    users = db.get_all_users()
    sent = 0
    for uid in users:
        try:
            if post_photo:
                await bot.send_photo(uid, photo=post_photo, caption=text)
            else:
                await bot.send_message(uid, text=text)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)  # чтобы не словить flood-limit Telegram

    await callback.message.answer(f"✅ Рассылка завершена. Отправлено: {sent}/{len(users)}")


# ==================== /admintool ====================

class AdminStates(StatesGroup):
    waiting_add_channel = State()
    waiting_remove_channel = State()
    waiting_file = State()


def admintool_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📌 Обяз. подписка", callback_data="at_subs")],
            [InlineKeyboardButton(text="📁 Файлы", callback_data="at_files")],
        ]
    )


@router.message(Command("admintool"))
async def cmd_admintool(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer_photo(photo=photo(), caption="🚫 Доступ ограничен")
        return
    await message.answer_photo(
        photo=photo(),
        caption="👋 Приветствую тебя, админ!",
        reply_markup=admintool_kb(),
    )


def subs_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить канал", callback_data="sub_add")],
            [InlineKeyboardButton(text="➖ Убрать канал", callback_data="sub_remove")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="at_back")],
        ]
    )


@router.callback_query(F.data == "at_subs")
async def cb_at_subs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    channels = db.get_channels()
    text = "📌 Текущие обязательные каналы:\n\n"
    text += "\n".join(channels) if channels else "— пусто —"
    await callback.message.edit_caption(caption=text, reply_markup=subs_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "at_back")
async def cb_at_back(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_caption(caption="👋 Приветствую тебя, админ!", reply_markup=admintool_kb())
    await callback.answer()


@router.callback_query(F.data == "sub_add")
async def cb_sub_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_caption(caption="Отправьте ссылку на канал, который нужно добавить:")
    await state.set_state(AdminStates.waiting_add_channel)
    await callback.answer()


@router.message(AdminStates.waiting_add_channel)
async def add_channel_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    link = message.text.strip()
    db.add_channel(link)
    await state.clear()
    await message.answer_photo(photo=photo(), caption=f"✅ Канал добавлен:\n{link}")


@router.callback_query(F.data == "sub_remove")
async def cb_sub_remove(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_caption(caption="Отправьте ссылку на канал, который нужно убрать:")
    await state.set_state(AdminStates.waiting_remove_channel)
    await callback.answer()


@router.message(AdminStates.waiting_remove_channel)
async def remove_channel_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    link = message.text.strip()
    ok = db.remove_channel(link)
    await state.clear()
    if ok:
        await message.answer_photo(photo=photo(), caption=f"✅ Канал убран:\n{link}")
    else:
        await message.answer_photo(photo=photo(), caption="⚠️ Такой канал не найден в списке.")


def files_menu_kb(files) -> InlineKeyboardMarkup:
    buttons = []
    for f in files:
        label = f"🗑 {f['file_name']} (ID {f['id']})"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"file_del_{f['id']}")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить файл", callback_data="at_addfile")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="at_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def files_list_text(files) -> str:
    text = "📁 Добавленные файлы:\n\n"
    if files:
        text += "\n".join(f"• {f['file_name']} (ID {f['id']})" for f in files)
        text += "\n\nНажми на файл в списке, чтобы удалить его."
    else:
        text += "— пусто —"
    return text


@router.callback_query(F.data == "at_files")
async def cb_at_files(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    files = db.get_all_files()
    await callback.message.edit_caption(caption=files_list_text(files), reply_markup=files_menu_kb(files))
    await callback.answer()


@router.callback_query(F.data.startswith("file_del_"))
async def cb_file_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    file_db_id = int(callback.data.split("_")[-1])
    db.delete_file(file_db_id)

    files = db.get_all_files()
    await callback.message.edit_caption(caption=files_list_text(files), reply_markup=files_menu_kb(files))
    await callback.answer("✅ Файл удалён")


@router.callback_query(F.data == "at_addfile")
async def cb_at_addfile(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.message.edit_caption(
        caption="📁 Отправьте файл (документ, apk, видео, аудио, фото — любой тип).\n"
        "Можно сразу подписать его — просто добавьте текст к файлу как подпись."
    )
    await state.set_state(AdminStates.waiting_file)
    await callback.answer()


@router.message(AdminStates.waiting_file, F.document | F.video | F.audio | F.photo)
async def file_received(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return

    caption = message.caption or None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "file"
        file_type = "document"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video.mp4"
        file_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio.mp3"
        file_type = "audio"
    else:  # message.photo
        file_id = message.photo[-1].file_id
        file_name = "photo.jpg"
        file_type = "photo"

    file_db_id = db.add_file(file_id, file_name, file_type=file_type, caption=caption)
    await state.clear()

    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=file_{file_db_id}"

    await message.answer_photo(
        photo=photo(),
        caption=f"✅ Файл добавлен!\n\nСсылка для скачивания:\n{link}",
    )


# ==================== запуск ====================

async def main():
    db.init_db()
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
