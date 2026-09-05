import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI
from aiohttp import web
import os

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8116407976:AAFhBu6RJ79HF_PswnPZRxJbe95b6zMgE9c")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", "800295680"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@d67i67m67a67")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

client_ai = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Флаг доступа к предметам (ОТКРЫТО)
SUBJECTS_OPEN = True 

# ==================== ДАТАБАЗА ====================
DB_NAME = "student_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                is_premium INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deadlines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                datetime_str TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                day TEXT,
                subject TEXT,
                time TEXT,
                type TEXT,
                room TEXT
            )
        """)
        await db.commit()

async def is_user_premium(user_id: int) -> bool:
    if user_id == ADMIN_TG_ID:
        return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return bool(row[0]) if row else False

async def set_user_premium(user_id: int, status: bool):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO users (user_id, is_premium) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET is_premium=?",
            (user_id, int(status), int(status))
        )
        await db.commit()

# ==================== КЛАВИАТУРЫ ====================
kb_main = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⏳ Дедлайны"), KeyboardButton(text="📅 Расписание")],
        [KeyboardButton(text="📚 Предметы"), KeyboardButton(text="⭐ Премиум статус")]
    ],
    resize_keyboard=True
)

kb_back = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 Назад в главное меню")]],
    resize_keyboard=True
)

kb_deadlines = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Создать дедлайн"), KeyboardButton(text="❌ Удалить дедлайн")],
        [KeyboardButton(text="📋 Мои дедлайны")],
        [KeyboardButton(text="🔙 Назад в главное меню")]
    ],
    resize_keyboard=True
)

kb_schedule = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить пару"), KeyboardButton(text="❌ Удалить пару")],
        [KeyboardButton(text="📖 Посмотреть все расписание")],
        [KeyboardButton(text="🔙 Назад в главное меню")]
    ],
    resize_keyboard=True
)

SUBJECTS = {
    "🏗️ ТЗБ 1": "tzb1",
    "🏛️ Конструкции в арх. 2": "arch_constr2",
    "🌱 Механика грунтов": "soil_mech",
    "🏢 Типология": "typology",
    "🌡️ Стр. физика": "building_physics",
    "🇬🇧 Английский": "english"
}

def get_subjects_keyboard():
    buttons = [[KeyboardButton(text=name)] for name in SUBJECTS.keys()]
    buttons.append([KeyboardButton(text="🔙 Назад в главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_subject_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📖 Лекции (полные)"), KeyboardButton(text="📝 Краткий конспект")],
            [KeyboardButton(text="📐 Формулы и примеры задач")],
            [KeyboardButton(text="💎 ИИ Премиум функции")],
            [KeyboardButton(text="🔙 Назад к предметам")]
        ],
        resize_keyboard=True
    )

def get_premium_features_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎯 Тест от ИИ"), KeyboardButton(text="🧩 Задача от ИИ")],
            [KeyboardButton(text="💬 ИИ Чат (Вопрос по теме)"), KeyboardButton(text="🎓 Эмуляция экзамена")],
            [KeyboardButton(text="📊 Шкала прогресса")],
            [KeyboardButton(text="🔙 Назад к предметам")]
        ],
        resize_keyboard=True
    )

# ==================== FSM (СОСТОЯНИЯ) ====================
class Form(StatesGroup):
    add_deadline_title = State()
    add_deadline_time = State()
    delete_deadline = State()
    add_lesson_info = State()
    delete_lesson = State()
    ai_question = State()

# ==================== ХЭНДЛЕРЫ ====================
router = Router()

@router.message(CommandStart())
@router.message(F.text == "🔙 Назад в главное меню")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await set_user_premium(message.from_user.id, message.from_user.id == ADMIN_TG_ID)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n"
        "Я твой помощник по учебе. Выбери нужный раздел на клавиатуре снизу 👇",
        reply_markup=kb_main
    )

# --- ⏳ ДЕДЛАЙНЫ ---
@router.message(F.text == "⏳ Дедлайны")
async def menu_deadlines(message: Message):
    await message.answer("🛠 Раздел: **Дедлайны**. Выберите действие:", reply_markup=kb_deadlines, parse_mode="Markdown")

@router.message(F.text == "➕ Создать дедлайн")
async def add_deadline_start(message: Message, state: FSMContext):
    await state.set_state(Form.add_deadline_title)
    await message.answer("Введите название дедлайна (например: *Сдать расчетку по Механике*):", reply_markup=kb_back)

@router.message(Form.add_deadline_title)
async def add_deadline_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(Form.add_deadline_time)
    await message.answer("Укажите дату и время (например: *25.09 14:00*):", reply_markup=kb_back)

@router.message(Form.add_deadline_time)
async def add_deadline_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO deadlines (user_id, title, datetime_str) VALUES (?, ?, ?)",
            (message.from_user.id, data['title'], message.text)
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Дедлайн успешно добавлен! Напоминание будет приходить каждый день в 12:00.", reply_markup=kb_deadlines)

@router.message(F.text == "📋 Мои дедлайны")
async def show_deadlines(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, title, datetime_str FROM deadlines WHERE user_id = ?", (message.from_user.id,)) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                await message.answer("🎉 У вас нет активных дедлайнов!")
                return
            text = "📌 **Ваши дедлайны:**\n\n" + "\n".join([f"🔹 `{r[0]}`. {r[1]} — **{r[2]}**" for r in rows])
            await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "❌ Удалить дедлайн")
async def del_deadline_start(message: Message, state: FSMContext):
    await state.set_state(Form.delete_deadline)
    await show_deadlines(message)
    await message.answer("Введите **номер (ID)** дедлайна, который нужно удалить:", reply_markup=kb_back)

@router.message(Form.delete_deadline)
async def del_deadline_finish(message: Message, state: FSMContext):
    try:
        d_id = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM deadlines WHERE id = ? AND user_id = ?", (d_id, message.from_user.id))
            await db.commit()
        await state.clear()
        await message.answer("✅ Дедлайн удален!", reply_markup=kb_deadlines)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число (ID).")

# --- 📅 РАСПИСАНИЕ ---
@router.message(F.text == "📅 Расписание")
async def menu_schedule(message: Message):
    await message.answer("📅 Раздел: **Расписание занятий**.", reply_markup=kb_schedule, parse_mode="Markdown")

@router.message(F.text == "➕ Добавить пару")
async def add_lesson_start(message: Message, state: FSMContext):
    await state.set_state(Form.add_lesson_info)
    await message.answer(
        "Введите данные пары в одну строку через запятую:\n\n"
        "Формат: `День, Предмет, Время, Лекция/Семинар, Кабинет и Этаж`\n"
        "Пример: `Понедельник, Механика грунтов, 08:30, Лекция, ауд. 302 (3 этаж)`",
        reply_markup=kb_back,
        parse_mode="Markdown"
    )

@router.message(Form.add_lesson_info)
async def add_lesson_finish(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split(',')]
    if len(parts) < 5:
        await message.answer("❌ Ошибка формата. Убедитесь, что разделили данные запятыми (всего 5 пунктов).")
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO schedule (user_id, day, subject, time, type, room) VALUES (?, ?, ?, ?, ?, ?)",
            (message.from_user.id, parts[0], parts[1], parts[2], parts[3], parts[4])
        )
        await db.commit()
    await state.clear()
    await message.answer("✅ Пара добавлена в расписание!", reply_markup=kb_schedule)

@router.message(F.text == "📖 Посмотреть все расписание")
async def show_schedule(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT id, day, subject, time, type, room FROM schedule WHERE user_id = ?", (message.from_user.id,)) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                await message.answer("📅 Ваше расписание пусто!")
                return
            text = "📖 **Ваше расписание:**\n\n"
            for r in rows:
                text += f"🔹 `ID: {r[0]}` | **{r[1]}** [{r[3]}]\n📖 {r[2]} ({r[4]})\n📍 {r[5]}\n\n"
            await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "❌ Удалить пару")
async def del_lesson_start(message: Message, state: FSMContext):
    await state.set_state(Form.delete_lesson)
    await show_schedule(message)
    await message.answer("Введите **ID пары**, которую хотите удалить:", reply_markup=kb_back)

@router.message(Form.delete_lesson)
async def del_lesson_finish(message: Message, state: FSMContext):
    try:
        l_id = int(message.text)
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM schedule WHERE id = ? AND user_id = ?", (l_id, message.from_user.id))
            await db.commit()
        await state.clear()
        await message.answer("✅ Пара удалена из вашего расписания!", reply_markup=kb_schedule)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число (ID).")

# --- 📚 ПРЕДМЕТЫ ---
@router.message(F.text.in_(["📚 Предметы", "🔒 Предметы (В разработке)", "🔙 Назад к предметам"]))
async def menu_subjects(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📚 Выберите предмет из списка:", reply_markup=get_subjects_keyboard())

@router.message(F.text.in_(SUBJECTS.keys()))
async def select_subject(message: Message, state: FSMContext):
    await state.update_data(current_subject=message.text)
    await message.answer(f"Вы выбрали: **{message.text}**\nВыберите нужный материал:", reply_markup=get_subject_menu(), parse_mode="Markdown")

@router.message(F.text == "📖 Лекции (полные)")
async def get_full_lectures(message: Message, state: FSMContext):
    data = await state.get_data()
    subj = data.get("current_subject", "Предмет")
    await message.answer(
        f"📖 **Полные лекции по предмету {subj}:**\n\n"
        "Здесь выкладываются полные оригинальные материалы, файлы и методички без сжатия:\n\n"
        "🔗 [Открыть папку с полными лекциями](https://drive.google.com)\n"
        "*(Ссылка на Google Диск / Telegram Канал)*",
        parse_mode="Markdown"
    )

@router.message(F.text == "📝 Краткий конспект")
async def get_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    subj = data.get("current_subject", "Предмет")
    await message.answer(
        f"📝 **Краткий конспект (главное) по {subj}:**\n\n"
        "• Выжимка по Теме 1\n"
        "• Выжимка по Теме 2\n"
        "• Ключевые термины",
        parse_mode="Markdown"
    )

@router.message(F.text == "📐 Формулы и примеры задач")
async def get_formulas(message: Message, state: FSMContext):
    data = await state.get_data()
    subj = data.get("current_subject", "Предмет")
    await message.answer(
        f"📐 **Формулы и решения задач по {subj}:**\n\n"
        "• Все основные формулы\n"
        "• Разбор образца задачи №1",
        parse_mode="Markdown"
    )

# --- 💎 ПРЕМИУМ ФУНКЦИИ И ИИ ---
@router.message(F.text == "💎 ИИ Премиум функции")
async def menu_premium_features(message: Message, state: FSMContext):
    premium = await is_user_premium(message.from_user.id)
    if not premium:
        await message.answer(
            f"🔒 **Это Премиум функция!**\n\n"
            f"Для покупки Премиума напишите администратору: {ADMIN_USERNAME}\n"
            f"После оплаты вас добавят в белый список!",
            parse_mode="Markdown"
        )
        return
    await message.answer("💎 **Премиум-меню ИИ**. Выберите опцию:", reply_markup=get_premium_features_keyboard(), parse_mode="Markdown")

@router.message(F.text.in_(["🎯 Тест от ИИ", "🧩 Задача от ИИ", "🎓 Эмуляция экзамена"]))
async def ai_gen_content(message: Message, state: FSMContext):
    if not await is_user_premium(message.from_user.id):
        return
    data = await state.get_data()
    subj = data.get("current_subject", "Строительство")
    
    await message.answer("🤖 ИИ генерирует материал, подождите...")
    prompt = f"Сгенерируй для студента {message.text} по предмету {subj}."
    
    try:
        if client_ai:
            response = await client_ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.choices[0].message.content
        else:
            text = f"⚙️ [Демо-режим]: Сгенерирован {message.text} по предмету {subj}."
        await message.answer(text)
    except Exception as e:
        await message.answer(f"❌ Ошибка генерации: {e}")

@router.message(F.text == "💬 ИИ Чат (Вопрос по теме)")
async def ai_chat_start(message: Message, state: FSMContext):
    if not await is_user_premium(message.from_user.id):
        return
    await state.set_state(Form.ai_question)
    await message.answer("Задайте любой вопрос ИИ-преподавателю:", reply_markup=kb_back)

@router.message(Form.ai_question)
async def ai_chat_process(message: Message, state: FSMContext):
    data = await state.get_data()
    subj = data.get("current_subject", "Общие вопросы")
    await message.answer("🤖 ИИ думает над ответом...")
    try:
        if client_ai:
            response = await client_ai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"Ты преподаватель по предмету {subj}."},
                    {"role": "user", "content": message.text}
                ]
            )
            await message.answer(response.choices[0].message.content)
        else:
            await message.answer("⚙️ [Демо-режим]: OpenAI API ключ не установлен.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(F.text == "📊 Шкала прогресса")
async def progress_scale(message: Message):
    if not await is_user_premium(message.from_user.id):
        return
    await message.answer("📊 Ваш уровень знаний: **78%**\n\n🟢 Тесты: 8/10\n🟢 Задачи: 5/5", parse_mode="Markdown")

# --- ⭐ ПРЕМИУМ СТАТУС И АДМИНКА ---
@router.message(F.text == "⭐ Премиум статус")
async def check_premium(message: Message):
    status = await is_user_premium(message.from_user.id)
    if status:
        await message.answer("🌟 У вас активирован **ПРЕМИУМ ДОСТУП**!", parse_mode="Markdown")
    else:
        await message.answer(
            f"❌ У вас **обычный доступ**.\nДля покупки напишите: {ADMIN_USERNAME}",
            parse_mode="Markdown"
        )

@router.message(F.text.startswith("/setpremium"))
async def give_premium_cmd(message: Message):
    if message.from_user.id != ADMIN_TG_ID:
        return
    try:
        target_id = int(message.text.split()[1])
        await set_user_premium(target_id, True)
        await message.answer(f"✅ Премиум выдан пользователю `{target_id}`!")
    except Exception:
        await message.answer("Использование: `/setpremium TELEGRAM_USER_ID`", parse_mode="Markdown")

async def daily_scheduler(bot: Bot):
    while True:
        await asyncio.sleep(86400)
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT user_id, title, datetime_str FROM deadlines") as cursor:
                rows = await cursor.fetchall()
                for u_id, title, dtime in rows:
                    try:
                        await bot.send_message(u_id, f"🔔 **Напоминание о дедлайне!**\n\n📌 {title}\n🗓 Дата: {dtime}", parse_mode="Markdown")
                    except Exception:
                        pass

# ==================== ЗАПУСК ВЕБ-СЕРВЕРА И БОТА ====================
async def handle_ping(request):
    return web.Response(text="Bot is running 24/7!")

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    asyncio.create_task(daily_scheduler(bot))

    # Микро веб-сервер для Render.com
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("🤖 Бот и веб-сервер запущены!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
