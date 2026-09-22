import logging
import asyncio
import gspread
import aiohttp
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
# ВНИМАНИЕ: СРОЧНО ПОМЕНЯЙ ТОКЕНЫ ПОСЛЕ ТЕСТИРОВАНИЯ!
BOT_TOKEN = "8619004990:AAE92G8vLIKcPzryM6GFjJqwPn5JBC9sCbY"
GOOGLE_API_KEY = "AIzaSyDZUuMn8B8t_REygaEGpEI47hyLSQrDKDk"
SCHEDULE_TABLE_ID = "1X6YF54l1rgP7MFfkTa1b_L6f4f3aWuADZwF8wwTWKK4"
DB_TABLE_ID = "11KbeilP1HRonHQAAZusBS1-ffNo4FxHXa239yZMKJm8"
OWNER_ID = 879365319

GROUPS_BY_COURSE = {
    "1 курс": ["АВМ-110", "ИСП-104", "ИСП-105", "ДОУ-102", "СВП-111", "ОСД-134", "ПКП-121", "СЗС-133", "СРС-111", "ТГО-101", "ТМС-103", "ТОС-103", "ЭМР-107", "ЭМР-108"],
    "2 курс": ["АВМ-208", "ИСП-202", "МПР-202", "ОСД-233", "ПКП-219", "ПКП-220", "СЗС-232", "СРС-209", "ТМС-202", "ТОС-202", "ЭМР-205", "ЮСП-201"],
    "3 курс": ["ДОУ-301", "ИСП-301", "ПКП-317", "ПКП-318", "ПОС-301", "СВП-309", "СВП-310", "СЗС-331", "ТМС-302", "ТОС-301"],
    "4 курс": ["СВП-425", "ПКП-415", "СВП-426", "СЗС-427"]
}

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AdminState(StatesGroup):
    broadcast = State()
    ban = State()
    unban = State()
    new_admin = State()
    del_admin = State()
    add_channel = State()
    del_channel = State()

class UserState(StatesGroup):
    course = State()
    group = State()
    day = State()
    teacher = State()

users_ws = None; blacklist_ws = None; settings_ws = None; channels_ws = None; admins_ws = None

def init_sheets():
    global users_ws, blacklist_ws, settings_ws, channels_ws, admins_ws
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
        client = gspread.authorize(creds)
        db = client.open_by_key(DB_TABLE_ID)
        users_ws = db.worksheet("Users")
        blacklist_ws = db.worksheet("Blacklist")
        settings_ws = db.worksheet("Settings")
        channels_ws = db.worksheet("Channels")
        admins_ws = db.worksheet("Admins")
        logging.info("✅ Google Sheets подключены.")
    except Exception as e:
        logging.error(f"❌ Ошибка Sheets: {e}")

init_sheets()

# Вспомогательная функция для асинхронной работы с Google Sheets (чтобы бот не зависал)
async def db_call(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

async def register_user(message: types.Message):
    """Записывает пользователя в таблицу, если его там нет."""
    try:
        uid = str(message.from_user.id)
        existing_ids = await db_call(users_ws.col_values, 1)
        if uid not in existing_ids:
            username = message.from_user.username or "no_username"
            name = message.from_user.full_name
            date = datetime.now().strftime("%d.%m.%Y %H:%M")
            await db_call(users_ws.append_row, [uid, username, name, date])
            logging.info(f"Новый пользователь зарегистрирован: {uid}")
    except Exception as e:
        logging.error(f"Ошибка при регистрации: {e}")

async def get_admins():
    try:
        col = await db_call(admins_ws.col_values, 1)
        return [int(i) for i in col if str(i).isdigit()] + [OWNER_ID]
    except:
        return [OWNER_ID]

async def is_banned(user_id):
    try:
        col = await db_call(blacklist_ws.col_values, 1)
        return str(user_id) in col
    except:
        return False

async def check_sub(user_id):
    try:
        # Проверяем, включена ли обязательная подписка (Ячейка B1 или строка 1 столбец 2)
        val_cell = await db_call(settings_ws.cell, 1, 2)
        if val_cell.value.lower() not in ["вкл", "on"]: 
            return True
        
        chans = await db_call(channels_ws.get_all_values)
        for ch in chans:
            if len(ch) < 2: continue
            try:
                # ch[0] - ID канала (должен начинаться с -100...)
                m = await bot.get_chat_member(ch[0], user_id)
                if m.status in ["left", "kicked"]: 
                    return False
            except Exception as e:
                logging.error(f"Ошибка проверки подписки на {ch[0]}: {e}")
                continue
        return True
    except Exception as e:
        logging.error(f"Ошибка в check_sub: {e}")
        return True

def cancel_kb():
    return ReplyKeyboardBuilder().add(KeyboardButton(text="❌ Отмена")).as_markup(resize_keyboard=True)

@dp.message(Command("admin"))
@dp.message(F.text == "❌ Отмена", StateFilter(AdminState))
async def admin_panel(message: types.Message, state: FSMContext = None):
    admins = await get_admins()
    if message.from_user.id not in admins: 
        return
    if state: 
        await state.clear()
    
    try:
        cell = await db_call(settings_ws.cell, 1, 2)
        sub_status = "ВКЛ" if cell.value.lower() in ["вкл", "on"] else "ВЫКЛ"
    except: 
        sub_status = "Ошибка"

    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="📊 Статистика"))
    kb.row(KeyboardButton(text="🚫 Забанить"), KeyboardButton(text="✅ Разбанить"))
    kb.row(KeyboardButton(text=f"🔄 Обяз. подписка: {sub_status}"))
    kb.row(KeyboardButton(text="➕ Назначить админа"), KeyboardButton(text="➖ Снять админа"))
    kb.row(KeyboardButton(text="➕ Добавить канал"), KeyboardButton(text="🗑 Удалить канал"))
    kb.row(KeyboardButton(text="📁 Список юзеров"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🛠 **Панель администратора**\nВыберите действие:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.startswith("🔄 Обяз. подписка:"))
async def toggle_sub_status(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    try:
        cell = await db_call(settings_ws.cell, 1, 2)
        new_val = "ВЫКЛ" if cell.value.lower() in ["вкл", "on"] else "ВКЛ"
        await db_call(settings_ws.update_cell, 1, 2, new_val)
        await message.answer(f"✅ Статус обязательной подписки изменен на: **{new_val}**")
        await admin_panel(message)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    try:
        all_users = len(await db_call(users_ws.col_values, 1)) - 1 # минус заголовок
        banned = len(await db_call(blacklist_ws.col_values, 1)) - 1
        await message.answer(f"📊 **Статистика**\n\nВсего пользователей: {max(0, all_users)}\nВ бане: {max(0, banned)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при получении статистики: {e}")

@dp.message(F.text == "📁 Список юзеров")
async def show_users(message: types.Message):
    if message.from_user.id not in await get_admins(): return
    count = len(await db_call(users_ws.col_values, 1)) - 1
    await message.answer(f"В базе {max(0, count)} юзеров. Таблицу можно посмотреть в Google Sheets по ссылке.")

# --- БАНЫ ---
@dp.message(F.text == "🚫 Забанить")
async def ban_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    await message.answer("Введите ID пользователя для бана:", reply_markup=cancel_kb())
    await state.set_state(AdminState.ban)

@dp.message(AdminState.ban)
async def ban_exec(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        await db_call(blacklist_ws.append_row, [message.text])
        await message.answer(f"✅ Пользователь {message.text} забанен.")
    else:
        await message.answer("ID должен состоять только из цифр.")
    await state.clear(); await admin_panel(message)

@dp.message(F.text == "✅ Разбанить")
async def unban_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    await message.answer("Введите ID пользователя для разбана:", reply_markup=cancel_kb())
    await state.set_state(AdminState.unban)

@dp.message(AdminState.unban)
async def unban_exec(message: types.Message, state: FSMContext):
    try:
        col = await db_call(blacklist_ws.col_values, 1)
        if message.text in col:
            idx = col.index(message.text) + 1
            await db_call(blacklist_ws.delete_rows, idx)
            await message.answer(f"✅ Пользователь {message.text} разбанен.")
        else:
            await message.answer("Пользователь не найден в бан-листе.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    await state.clear(); await admin_panel(message)

# --- АДМИНЫ ---
@dp.message(F.text == "➕ Назначить админа")
async def add_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: 
        return await message.answer("Только владелец может назначать админов.")
    await message.answer("Введите ID нового админа:", reply_markup=cancel_kb())
    await state.set_state(AdminState.new_admin)

@dp.message(AdminState.new_admin)
async def add_admin_exec(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        await db_call(admins_ws.append_row, [message.text])
        await message.answer(f"✅ Админ {message.text} добавлен.")
    else:
        await message.answer("ID должен состоять только из цифр.")
    await state.clear(); await admin_panel(message)

@dp.message(F.text == "➖ Снять админа")
async def del_admin_start(message: types.Message, state: FSMContext):
    if message.from_user.id != OWNER_ID: return
    await message.answer("Введите ID админа для снятия:", reply_markup=cancel_kb())
    await state.set_state(AdminState.del_admin)

@dp.message(AdminState.del_admin)
async def del_admin_exec(message: types.Message, state: FSMContext):
    try:
        col = await db_call(admins_ws.col_values, 1)
        if message.text in col:
            idx = col.index(message.text) + 1
            await db_call(admins_ws.delete_rows, idx)
            await message.answer(f"✅ Админ {message.text} удален.")
        else:
            await message.answer("Админ не найден.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
    await state.clear(); await admin_panel(message)

# --- КАНАЛЫ ---
@dp.message(F.text == "➕ Добавить канал")
async def add_ch_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    await message.answer("Отправьте данные канала в формате:\nID_КАНАЛА | ССЫЛКА | НАЗВАНИЕ\n\nПример:\n-1001234567 | https://t.me/join... | Мой Канал", reply_markup=cancel_kb())
    await state.set_state(AdminState.add_channel)

@dp.message(AdminState.add_channel)
async def add_ch_exec(message: types.Message, state: FSMContext):
    try:
        data = [x.strip() for x in message.text.split("|")]
        if len(data) == 3:
            await db_call(channels_ws.append_row, data)
            await message.answer("✅ Канал успешно добавлен!")
        else:
            await message.answer("❌ Неверный формат. Нужно 3 параметра через |")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear(); await admin_panel(message)

@dp.message(F.text == "🗑 Удалить канал")
async def del_ch_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    chans = await db_call(channels_ws.get_all_values)
    if not chans: 
        return await message.answer("Список пуст.")
    
    # Предполагается, что 1я строка - заголовки. Иначе нумерация может сбиться.
    msg = "Введите номер строки (цифру):\n" + "\n".join([f"{i+1}. {c[2]}" for i, c in enumerate(chans)])
    await message.answer(msg, reply_markup=cancel_kb())
    await state.set_state(AdminState.del_channel)

@dp.message(AdminState.del_channel)
async def del_ch_exec(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        try:
            await db_call(channels_ws.delete_rows, int(message.text))
            await message.answer("✅ Удалено.")
        except Exception as e: 
            await message.answer(f"❌ Ошибка: {e}")
    await state.clear(); await admin_panel(message)

# --- РАССЫЛКА ---
@dp.message(F.text == "📢 Рассылка")
async def broad_start(message: types.Message, state: FSMContext):
    if message.from_user.id not in await get_admins(): return
    await message.answer("Введите текст сообщения для рассылки всем пользователям:", reply_markup=cancel_kb())
    await state.set_state(AdminState.broadcast)

@dp.message(AdminState.broadcast)
async def broad_exec(message: types.Message, state: FSMContext):
    col = await db_call(users_ws.col_values, 1)
    uids = col[1:] # Пропускаем заголовок
    ok = 0
    m = await message.answer(f"🚀 Начинаю рассылку для {len(uids)} пользователей...")
    for uid in uids:
        try:
            await bot.send_message(uid, message.text)
            ok += 1
            await asyncio.sleep(0.05) # Защита от флудлимита Telegram
        except: 
            pass
    await m.edit_text(f"✅ Готово! Успешно доставлено: {ok}"); await state.clear(); await admin_panel(message)


@dp.message(Command("start"), StateFilter('*'))
@dp.message(F.text == "⬅️ Назад к курсам")
async def cmd_start(message: types.Message, state: FSMContext):
    if await is_banned(message.from_user.id): 
        return
    
    # Регистрация
    await register_user(message)
    
    # Проверка подписки
    if not await check_sub(message.from_user.id):
        kb = InlineKeyboardBuilder()
        chans = await db_call(channels_ws.get_all_values)
        for ch in chans: 
            if len(ch) >= 3:
                kb.row(InlineKeyboardButton(text=ch[2], url=ch[1]))
        kb.row(InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_sub"))
        return await message.answer("⚠️ Для использования бота, пожалуйста, подпишитесь на наши каналы:", reply_markup=kb.as_markup())

    await state.clear()
    kb = ReplyKeyboardBuilder()
    for c in GROUPS_BY_COURSE.keys(): kb.add(KeyboardButton(text=c))
    kb.row(KeyboardButton(text="👨‍🏫 Я преподаватель"))
    await message.answer("🎓 Выберите ваш курс:", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.callback_query(F.data == "check_sub")
async def sub_check_cb(call: types.CallbackQuery, state: FSMContext):
    if await check_sub(call.from_user.id):
        await call.answer("✅ Доступ открыт!")
        await cmd_start(call.message, state)
    else:
        await call.answer("❌ Вы не подписаны на все каналы!", show_alert=True)

@dp.message(F.text == "👨‍🏫 Я преподаватель")
async def teacher_mode(message: types.Message, state: FSMContext):
    await state.set_state(UserState.teacher)
    await message.answer("📝 Введите фамилию преподавателя:", reply_markup=cancel_kb())

@dp.message(UserState.teacher)
async def teacher_search(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await cmd_start(message, state)
    m = await message.answer("🔎 Ищу расписание в таблице...")
    res = await fetch_teacher_schedule(message.text)
    await m.edit_text(f"👨‍🏫 **{message.text}**\n{res}", parse_mode="Markdown")
    
    kb = ReplyKeyboardBuilder().add(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("Поиск завершен.", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.clear()

async def fetch_teacher_schedule(t_name):
    res_dict = {}; t_low = t_name.lower()
    async with aiohttp.ClientSession() as session:
        for course in GROUPS_BY_COURSE.keys():
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
            async with session.get(url) as resp:
                data = await resp.json()
                rows = data.get("values", [])
            if not rows: continue
            curr_day = ""
            for i in range(len(rows)):
                row = rows[i]
                if not row or not row[0:1]: continue
                d_c = str(row[0]).replace('\n', ' ').strip().upper()
                if any(d in d_c for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]): 
                    curr_day = d_c
                if not curr_day: continue
                
                for col in range(2, len(row)):
                    if t_low in str(row[col]).lower() and len(str(row[col])) > 2:
                        p = row[1] if len(row) > 1 else "?"
                        g = str(rows[1][col]).strip() if len(rows) > 1 and len(rows[1]) > col else "?"
                        rm = "?"
                        # Ищем кабинет в соседней ячейке (защита от Index Error)
                        try: 
                            if len(rows[i]) > col + 1:
                                rm = str(rows[i][col+1]).strip()
                        except: pass
                        
                        if curr_day not in res_dict: res_dict[curr_day] = []
                        entry = f"• {p} пара: {g} [каб. {rm}]"
                        if entry not in res_dict[curr_day]: res_dict[curr_day].append(entry)
                        
    if not res_dict: return "🔍 Ничего не найдено."
    out = ""
    for d, ls in res_dict.items(): out += f"\n📅 **{d}**\n" + "\n".join(ls) + "\n"
    return out

@dp.message(F.text.in_(GROUPS_BY_COURSE.keys()))
async def select_course(message: types.Message, state: FSMContext):
    await state.update_data(c=message.text)
    await state.set_state(UserState.group)
    kb = ReplyKeyboardBuilder()
    for g in GROUPS_BY_COURSE[message.text]: kb.add(KeyboardButton(text=g))
    kb.row(KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer(f"📍 Выберите группу ({message.text}):", reply_markup=kb.adjust(2).as_markup(resize_keyboard=True))

@dp.message(UserState.group)
async def select_group(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад к курсам": return await cmd_start(message, state)
    await state.update_data(g=message.text)
    await state.set_state(UserState.day)
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📅 Завтра"))
    kb.row(KeyboardButton(text="🗓 На неделю"), KeyboardButton(text="⬅️ Назад к курсам"))
    await message.answer("🕒 Выберите период расписания:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(UserState.day)
async def show_schedule(message: types.Message, state: FSMContext):
    if "Назад" in message.text: return await cmd_start(message, state)
    data = await state.get_data()
    
    # Защита на случай, если данные FSM стерлись после перезапуска
    if 'c' not in data or 'g' not in data:
        return await cmd_start(message, state)

    days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'ВОСКРЕСЕНЬЕ']
    
    target = None
    if "Сегодня" in message.text:
        target = days[datetime.now().weekday()]
    elif "Завтра" in message.text:
        target = days[(datetime.now()+timedelta(1)).weekday()]
    
    m = await message.answer("⏳ Загрузка расписания...")
    res = await fetch_student_sch(data['c'], data['g'], target)
    await m.edit_text(f"📋 Группа: **{data['g']}**\n{res}", parse_mode="Markdown")

async def fetch_student_sch(course, group, target_day):
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SCHEDULE_TABLE_ID}/values/{course}!A1:BG100?key={GOOGLE_API_KEY}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            rows = data.get("values", [])
            
    if not rows: return "Таблица пуста или недоступна."
    
    col_idx = -1
    # Ищем столбец с названием группы во 2-й строке (индекс 1)
    if len(rows) > 1:
        for i, cell in enumerate(rows[1]):
            if group.lower() in str(cell).lower(): 
                col_idx = i
                break
                
    if col_idx == -1: return f"Группа {group} не найдена в таблице."
    
    res, curr_day = {}, ""
    for i, row in enumerate(rows):
        if not row: continue
        d_c = str(row[0]).strip().upper()
        if any(d in d_c for d in ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]): 
            curr_day = d_c
            
        if not curr_day or (target_day and target_day.upper() not in curr_day): 
            continue
        
        p_n = row[1].strip() if len(row) > 1 else ""
        cont = str(row[col_idx]).strip() if len(row) > col_idx else ""
        
        if p_n.isdigit() and len(cont) > 2:
            rm = "?"
            try: 
                if len(row) > col_idx + 1:
                    rm = str(rows[i][col_idx+1]).strip()
            except: pass
            
            if curr_day not in res: res[curr_day] = []
            res[curr_day].append(f"• {p_n} пара: {cont} [каб. {rm}]")
            
    out = ""
    for d, ls in res.items(): 
        out += f"\n📅 **{d}**\n" + "\n".join(ls) + "\n"
    return out or "Занятий нет."

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
