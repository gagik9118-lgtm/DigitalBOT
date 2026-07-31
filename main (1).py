import telebot
from telebot import types
import sqlite3
import time
import threading
from datetime import datetime, timedelta
import random
import string
import os
import re
from functools import wraps

# ==================== КОНФИГ ====================
TOKEN = os.environ.get('BOT_TOKEN')
if not TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")
OWNER_ID = 8396445302
ADMIN_IDS = [8396445302]

bot = telebot.TeleBot(TOKEN)
user_data = {}
user_states = {}

# ==================== АЛГОРИТМ ЛУНА ====================
def luhn_check(card_number):
    """Проверка номера карты по алгоритму Луна"""
    # Удаляем пробелы и другие символы
    card_number = re.sub(r'\D', '', card_number)
    
    # Проверяем, что номер состоит только из цифр и имеет длину 16
    if not card_number.isdigit() or len(card_number) != 16:
        return False
    
    # Алгоритм Луна
    total = 0
    reverse_digits = card_number[::-1]
    
    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        if i % 2 == 1:  # Каждая вторая цифра (начиная с предпоследней)
            n *= 2
            if n > 9:
                n -= 9
        total += n
    
    return total % 10 == 0

# ==================== ВРЕМЯ ПО МСК ====================
def now_str():
    return (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")

def now_datetime():
    return datetime.utcnow() + timedelta(hours=3)

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'client',
            is_banned INTEGER DEFAULT 0,
            registered_at TIMESTAMP,
            privacy_accepted INTEGER DEFAULT 0,
            referred_by INTEGER DEFAULT NULL
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS partners (
            user_id INTEGER PRIMARY KEY,
            leads_this_week INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            total_paid REAL DEFAULT 0,
            last_week_reset TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            username TEXT,
            service TEXT,
            answers_text TEXT,
            app_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            referrer_id INTEGER DEFAULT NULL
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            bank TEXT,
            card_number TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS payout_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            created_at TIMESTAMP
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS admin_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            added_by INTEGER,
            added_at TIMESTAMP,
            removed_at TIMESTAMP DEFAULT NULL
        )''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS ban_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            banned_by INTEGER,
            ban_date TIMESTAMP,
            unban_date TIMESTAMP DEFAULT NULL
        )''')
        
        conn.commit()
        conn.close()
        print("✅ База данных готова")
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (OWNER_ID,))
        if not c.fetchone():
            c.execute("INSERT INTO users (user_id, username, full_name, status, registered_at, privacy_accepted) VALUES (?, ?, ?, ?, ?, ?)",
                      (OWNER_ID, "opps911", "Владелец", "owner", now_str(), 0))
            conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

def load_admin_ids():
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE status IN ('admin', 'owner')")
        db_admins = [row[0] for row in c.fetchall()]
        conn.close()
        for admin_id in db_admins:
            if admin_id not in ADMIN_IDS:
                ADMIN_IDS.append(admin_id)
    except Exception as e:
        print(f"❌ Ошибка загрузки админов: {e}")

def save_user(message):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        user_id = message.from_user.id
        username = message.from_user.username
        full_name = message.from_user.full_name or "Пользователь"
        
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if c.fetchone():
            conn.close()
            return
        
        status = 'owner' if user_id == OWNER_ID else 'admin' if user_id in ADMIN_IDS else 'client'
        
        c.execute("INSERT INTO users (user_id, username, full_name, status, registered_at, privacy_accepted) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, username, full_name, status, now_str(), 0))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")

def get_user(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r
    except:
        return None

def get_user_status(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT status FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else None
    except:
        return None

def is_banned(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r and r[0] == 1
    except:
        return False

def has_accepted_privacy(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT privacy_accepted FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r and r[0] == 1
    except:
        return False

def set_privacy_accepted(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE users SET privacy_accepted = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_partner(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT * FROM partners WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r
    except:
        return None

def create_partner(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO partners (user_id, leads_this_week, balance, total_paid, last_week_reset) VALUES (?, 0, 0, 0, ?)",
                  (user_id, now_str()))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_partner_percent(user_id):
    conn = sqlite3.connect('golden_house.db')
    c = conn.cursor()
    c.execute("SELECT leads_this_week FROM partners WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    leads = r[0] if r else 0
    
    if leads >= 15:
        return 30
    elif leads >= 11:
        return 20
    elif leads >= 6:
        return 15
    else:
        return 10

def get_partner_balance(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT balance FROM partners WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else 0
    except:
        return 0

def get_partner_leads(user_id):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT leads_this_week FROM partners WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        return r[0] if r else 0
    except:
        return 0

def reset_weekly_stats():
    while True:
        now = now_datetime()
        days = (6 - now.weekday()) % 7
        if days == 0 and now.hour == 0 and now.minute == 0:
            next_reset = now + timedelta(days=7)
        else:
            next_reset = now + timedelta(days=days)
            next_reset = next_reset.replace(hour=0, minute=0, second=0, microsecond=0)
        
        wait = (next_reset - now).total_seconds()
        if wait < 0:
            wait += 7 * 24 * 3600
        
        time.sleep(wait)
        
        try:
            conn = sqlite3.connect('golden_house.db')
            c = conn.cursor()
            c.execute("UPDATE partners SET leads_this_week = 0, last_week_reset = ?", (now_str(),))
            conn.commit()
            conn.close()
            print("🔄 Статистика сброшена")
        except Exception as e:
            print(f"❌ Ошибка сброса: {e}")

def reset_weekly_stats_thread():
    thread = threading.Thread(target=reset_weekly_stats, daemon=True)
    thread.start()

# ==================== ДЕКОРАТОРЫ ====================

def check_banned(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        
        if message.text and message.text.startswith('/start'):
            return func(message, *args, **kwargs)
        
        if is_banned(user_id):
            status = get_user_status(user_id)
            if status in ('admin', 'owner'):
                return func(message, *args, **kwargs)
            
            bot.send_message(message.chat.id, 
                           "🚫 Доступ ограничен. Вы заблокированы.",
                           reply_markup=banned_menu())
            return None
        
        return func(message, *args, **kwargs)
    return wrapper

def check_banned_callback(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        
        if is_banned(user_id):
            status = get_user_status(user_id)
            if status in ('admin', 'owner'):
                return func(call, *args, **kwargs)
            bot.answer_callback_query(call.id, "🚫 Вы заблокированы")
            return None
        
        return func(call, *args, **kwargs)
    return wrapper

def admin_only(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        status = get_user_status(user_id)
        if status in ('admin', 'owner'):
            return func(message, *args, **kwargs)
        return None
    return wrapper

def admin_only_callback(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        status = get_user_status(user_id)
        if status in ('admin', 'owner'):
            return func(call, *args, **kwargs)
        bot.answer_callback_query(call.id, "🚫 Нет доступа")
        return None
    return wrapper

def owner_only_callback(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        if call.from_user.id == OWNER_ID:
            return func(call, *args, **kwargs)
        bot.answer_callback_query(call.id, "🚫 Только владелец")
        return None
    return wrapper

def privacy_required(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        
        if message.text and message.text.startswith('/start'):
            return func(message, *args, **kwargs)
        
        if not has_accepted_privacy(user_id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📜 Политика конфиденциальности", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/")),
                types.InlineKeyboardButton("Я прочитал и согласен ✅", callback_data="accept_privacy")
            )
            bot.send_message(
                message.chat.id,
                "🔒 Для доступа к функциям бота необходимо принять Политику конфиденциальности.\n\n"
                "Пожалуйста, ознакомьтесь с документом и нажмите кнопку согласия.",
                reply_markup=markup
            )
            return None
        return func(message, *args, **kwargs)
    return wrapper

def privacy_required_callback(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        
        if call.data == "accept_privacy":
            return func(call, *args, **kwargs)
        
        if not has_accepted_privacy(user_id):
            bot.answer_callback_query(call.id, "🔒 Сначала примите политику конфиденциальности", show_alert=True)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📜 Политика конфиденциальности", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/")),
                types.InlineKeyboardButton("Я прочитал и согласен ✅", callback_data="accept_privacy")
            )
            bot.send_message(
                call.message.chat.id,
                "🔒 Для доступа к функциям бота необходимо принять Политику конфиденциальности.\n\n"
                "Пожалуйста, ознакомьтесь с документом и нажмите кнопку согласия.",
                reply_markup=markup
            )
            return None
        return func(call, *args, **kwargs)
    return wrapper

# ==================== МЕНЮ ====================

def banned_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("👤 Апелляция", url="https://t.me/opps911"),
        types.InlineKeyboardButton("📜 Регламент", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/ReglamentSiteGoldenHouee/"))
    )
    return markup

def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "💻 Web-разработка",
        "🤖 Разработка Telegram-бота",
        "🔗 Разработка реферальной системы",
        "📈 SEO-продвижение"
    ]
    markup.add(*[types.KeyboardButton(b) for b in buttons])
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("🔙 Назад"))
    return markup

# ==================== КОМАНДЫ ====================

@bot.message_handler(commands=['start'])
def start(message):
    try:
        save_user(message)
        
        if is_banned(message.from_user.id):
            bot.send_message(message.chat.id, "🚫 Доступ ограничен.", reply_markup=banned_menu())
            return
        
        text = """
<b>Добро пожаловать в Golden House!</b> 

Пока вы читаете этот текст, ваши менеджеры пропускают сообщения, а конкуренты забирают горячие лиды. <b>Мы решаем эту проблему раз и навсегда.</b> <b>Golden House — это автоматизация бизнес-процессов на высшем уровне.</b> Мы создаем умные экосистемы, которые работают на вас <b>24/7/365</b>.

<b>Что мы внедряем для вашего роста:</b>

🤖 Интеллектуальные TG-боты — моментальная обработка сотен заявок одновременно без потери качества.
<b>📊 Админ-панели и CRM</b> — полный контроль, аналитика и управление процессами в один клик.
<b>🔗 Реферальные системы</b> — запуск вирусного маркетинга, который заставит клиентов приводить к вам новых покупателей.

Вы платите за разработку системы один раз, а экономите миллионы на фонде оплаты труда каждый год. <b>Нажмите кнопку ниже, чтобы обсудить автоматизацию вашего проекта</b> 👇
        """
        
        # Проверка политики
        if not has_accepted_privacy(message.from_user.id):
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
                types.InlineKeyboardButton("📜 Политика конфиденциальности", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/")),
                types.InlineKeyboardButton("Я прочитал и согласен ✅", callback_data="accept_privacy")
            )
            bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
        else:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
                types.InlineKeyboardButton("📜 Политика конфиденциальности", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/"))
            )
            bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
        
        # ПОКАЗЫВАЕМ ReplyKeyboard с услугами (БЕЗ ТЕКСТА "Меню услуг:")
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        
    except Exception as e:
        print(f"❌ Ошибка start: {e}")

@bot.message_handler(commands=['partner'])
@check_banned
@privacy_required
def partner_command(message):
    user_id = message.from_user.id
    create_partner(user_id)
    show_partner_cabinet(message.chat.id, user_id)

@bot.message_handler(commands=['admin'])
@admin_only
def admin_panel(message):
    user_id = message.from_user.id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("🔨 Заблокировать", callback_data="admin_ban"),
        types.InlineKeyboardButton("🔓 Разблокировать", callback_data="admin_unban"),
        types.InlineKeyboardButton("👑 Назначить админа", callback_data="admin_make_admin"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("📋 Заявки", callback_data="admin_applications"),
        types.InlineKeyboardButton("💳 Выплаты", callback_data="admin_payments"),
        types.InlineKeyboardButton("➕ Обновить партнера", callback_data="admin_update_partner"),
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("💣 Массовая рассылка", callback_data="admin_mass_broadcast")
    ]
    
    if user_id == OWNER_ID:
        buttons.append(types.InlineKeyboardButton("❌ Разжаловать админа", callback_data="admin_remove_admin"))
    
    markup.add(*buttons)
    bot.send_message(message.chat.id, "🗃 Панель управления", reply_markup=markup)

# ==================== ЛИЧНЫЙ КАБИНЕТ ПАРТНЁРА ====================

def show_partner_cabinet(chat_id, user_id):
    create_partner(user_id)
    
    conn = sqlite3.connect('golden_house.db')
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    username = r[0] if r else "Нет"
    
    c.execute("SELECT leads_this_week, balance, total_paid FROM partners WHERE user_id = ?", (user_id,))
    r = c.fetchone()
    conn.close()
    
    leads, balance, total_paid = r if r else (0, 0, 0)
    percent = get_partner_percent(user_id)
    next_percent, leads_to_next = get_next_level_info(user_id)
    
    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    
    text = f"""
💼 Личный кабинет партнера | Golden House

👤 Аккаунт: @{username}
🆔 Ваш ID: <code>{user_id}</code>

📊 Статистика за текущую неделю:
Приведено покупателей: {leads} шт.
Текущая ставка: {percent}% от маржи
🔥 До следующего уровня ({next_percent}%) осталось привести: {leads_to_next} лид(ов).

💰 Финансовый баланс:
Доступно к выводу: {balance} ₽
Выплачено за всё время: {total_paid} ₽

🔗 Твоя реферальная ссылка:
<code>{ref_link}</code>
(Нажми на ссылку, чтобы скопировать. Направляй по ней клиентов!)
    """
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("💳 Вывести профит", callback_data="partner_withdraw"),
        types.InlineKeyboardButton("🔄 Обновить данные", callback_data="partner_refresh"),
        types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"),
        types.InlineKeyboardButton("🗂 Регламент", callback_data="partner_rules")
    )
    
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup)

def get_next_level_info(user_id):
    leads = get_partner_leads(user_id)
    if leads < 6:
        return 15, 6 - leads
    elif leads < 11:
        return 20, 11 - leads
    elif leads < 15:
        return 30, 15 - leads
    else:
        return 30, 0

# ==================== ОБРАБОТКА УСЛУГ ====================

@bot.message_handler(func=lambda m: True)
@check_banned
@privacy_required
def handle_services(message):
    user_id = message.from_user.id
    text = message.text
    
    if user_id in user_data and user_data[user_id].get('in_process'):
        return
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if text == "💻 Web-разработка":
        user_data[user_id] = {'service': 'web', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "Какой тип сайта Вас интересует? (Лендинг, визитка, интернет-магазин и т.д.)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
        return
    
    if text == "🤖 Разработка Telegram-бота":
        user_data[user_id] = {'service': 'bot', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "В какой сфере Ваш бизнес и какое направление планируете автоматизировать?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_bot)
        return
    
    if text == "🔗 Разработка реферальной системы":
        user_data[user_id] = {'service': 'ref', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "Для какого бизнеса или проекта нужна реферальная система? (Сайт, телеграм-бот, приложение)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_ref)
        return
    
    if text == "📈 SEO-продвижение":
        user_data[user_id] = {'service': 'seo', 'step': 0, 'in_process': True}
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("Тариф мини от 35 000₽/мес", callback_data="seo_mini"),
            types.InlineKeyboardButton("Тариф медиум от 50 000₽/мес", callback_data="seo_medium"),
            types.InlineKeyboardButton("Тариф PRO от 65 000₽/мес", callback_data="seo_pro")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Выберите тариф SEO-продвижения:", reply_markup=markup)

# ==================== ПРОЦЕССЫ УСЛУГ ====================

def process_web(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Ошибка. Начните заново.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 0:
        user_data[user_id]['site_type'] = text
        user_data[user_id]['step'] = 1
        msg = bot.send_message(message.chat.id, "Какой Ваш бюджет?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 1:
        user_data[user_id]['budget'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Какой нужен дедлайн?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 2:
        user_data[user_id]['deadline'] = text
        user_data[user_id]['step'] = 3
        msg = bot.send_message(message.chat.id, "Что у Вас за бизнес? (Например: недвижимость в Москве)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 3:
        user_data[user_id]['business'] = text
        user_data[user_id]['step'] = 4
        msg = bot.send_message(message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 4:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

def process_bot(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Ошибка. Начните заново.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 0:
        user_data[user_id]['business_area'] = text
        user_data[user_id]['step'] = 1
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("💰 Прием и квалификация заявок", callback_data="bot_func_1"),
            types.InlineKeyboardButton("⚙️ Интеграция с CRM / Кастомная админка", callback_data="bot_func_2"),
            types.InlineKeyboardButton("🔗 Реферальная система / Вирусный маркетинг", callback_data="bot_func_3"),
            types.InlineKeyboardButton("🧩 Другое (опишите текстом)", callback_data="bot_func_4")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Какой ключевой функционал должен быть в боте?", reply_markup=markup)
    elif step == 1:
        user_data[user_id]['function'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_bot)
    elif step == 2:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

def process_ref(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Ошибка. Начните заново.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 0:
        user_data[user_id]['business_type'] = text
        user_data[user_id]['step'] = 1
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("💰 Выплата процентов / Кэшбэк деньгами", callback_data="ref_reward_1"),
            types.InlineKeyboardButton("🎁 Бонусные баллы / Скидки на продукт", callback_data="ref_reward_2"),
            types.InlineKeyboardButton("🔑 Доступ к закрытому контенту / Функциям", callback_data="ref_reward_3"),
            types.InlineKeyboardButton("🧩 Сложная многоуровневая система", callback_data="ref_reward_4")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Какую механику вознаграждения планируете использовать?", reply_markup=markup)
    elif step == 1:
        user_data[user_id]['reward'] = text
        user_data[user_id]['step'] = 2
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Да", callback_data="ref_integration_yes"),
            types.InlineKeyboardButton("Нет", callback_data="ref_integration_no")
        )
        bot.send_message(message.chat.id, "Нужна ли интеграция с Вашей текущей CRM-системой или платежными сервисами для автоматических выплат?", reply_markup=markup)
    elif step == 2:
        user_data[user_id]['integration'] = text
        user_data[user_id]['step'] = 3
        msg = bot.send_message(message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_ref)
    elif step == 3:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

def finish_service(user_id):
    try:
        data = user_data[user_id]
        service_key = data['service']
        
        service_names = {
            'web': 'Web-разработка',
            'bot': 'Разработка Telegram-бота',
            'ref': 'Разработка реферальной системы',
            'seo': 'SEO-продвижение'
        }
        service = service_names.get(service_key, service_key)
        
        answers = [f"Услуга: {service}"]
        
        if service_key == 'web':
            answers.append(f"Тип сайта: {data.get('site_type', '')}")
            answers.append(f"Бюджет: {data.get('budget', '')}")
            answers.append(f"Дедлайн: {data.get('deadline', '')}")
            answers.append(f"Бизнес: {data.get('business', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        elif service_key == 'bot':
            answers.append(f"Сфера бизнеса: {data.get('business_area', '')}")
            answers.append(f"Функционал: {data.get('function', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        elif service_key == 'ref':
            answers.append(f"Тип бизнеса: {data.get('business_type', '')}")
            answers.append(f"Механика вознаграждения: {data.get('reward', '')}")
            answers.append(f"Интеграция: {data.get('integration', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        elif service_key == 'seo':
            answers.append(f"Тариф: {data.get('tariff', '')}")
            answers.append(f"Сайт и регионы: {data.get('site_info', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        
        answers_text = "\n".join(answers)
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else None
        
        c.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        referrer_id = r[0] if r else None
        
        c.execute("INSERT INTO applications (client_id, username, service, answers_text, created_at, referrer_id) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, username, service, answers_text, now_str(), referrer_id))
        app_id = c.lastrowid
        conn.commit()
        conn.close()
        
        admin_text = f"""
🔥 НОВАЯ ЗАЯВКА #{app_id}
👤 @{username or 'Нет'} [ID: <code>{user_id}</code>]
📅 {now_datetime().strftime("%d.%m.%Y %H:%M")}

{answers_text}

Источник трафика: {"⚠️ Приведен арбитражником" if referrer_id else "🌐 Органический трафик / Из поиска"}
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Закрыть", callback_data=f"close_app_{app_id}"),
            types.InlineKeyboardButton("🚫 Отказ", callback_data=f"reject_app_{app_id}")
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, admin_text, parse_mode='HTML', reply_markup=markup)
            except:
                pass
        
        bot.send_message(user_id, 
                        "✅ Данные приняты! Разбор Вашего проекта уже начался. Мы свяжемся с Вами в течение часа.\n\n🎁 На созвоне мы бесплатно покажем 3 главных места, где Ваш бизнес прямо сейчас теряет деньги и как закрыть эти дыры с помощью digital-инструментов.\n\nЕсли проект горит — пишите напрямую: @opps911 или позвоните +79950961675",
                        reply_markup=main_menu())
        
        if user_id in user_data:
            del user_data[user_id]
            
    except Exception as e:
        print(f"❌ Ошибка finish: {e}")
        bot.send_message(user_id, "Ошибка. Попробуйте позже.", reply_markup=main_menu())

# ==================== ОБРАБОТКА SEO ====================

def process_seo(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Ошибка. Начните заново.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 1:
        user_data[user_id]['site_info'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта? Напишите имя и номер телефона в одном сообщении!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_seo)
    elif step == 2:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda c: True)
@check_banned_callback
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    if data == "accept_privacy":
        if set_privacy_accepted(user_id):
            bot.answer_callback_query(call.id, "✅ Спасибо! Политика принята.")
            try:
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
                    types.InlineKeyboardButton("📜 Политика конфиденциальности", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/"))
                )
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except:
                pass
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка. Попробуйте позже.")
        return
    
    if not has_accepted_privacy(user_id):
        bot.answer_callback_query(call.id, "🔒 Сначала примите политику конфиденциальности", show_alert=True)
        return
    
    # ===== ПАРТНЁРСКАЯ ПРОГРАММА (НОВЫЙ ТЕКСТ) =====
    if data == "partner_program":
        create_partner(user_id)
        percent = get_partner_percent(user_id)
        leads = get_partner_leads(user_id)
        
        text = f"""
🔥 <b>Партнёрская программа Golden House: ревшара до 30% с маржи B2B-сделок</b>

Зарабатывайте на трафике для топового digital-агентства. Мы продаём веб-разработку, автоматизацию бизнеса (TG-боты) и SEO-продвижение. Вы получаете прогрессивный процент от чистой прибыли с каждого оплаченного чека.

<b>Недельная сетка тарифов (сброс каждый понедельник в 00:00 по МСК):</b>
1–5 оплат в неделю ➔ 10% с маржи
6–10 оплат в неделю ➔ 15% с маржи
11–14 оплат в неделю ➔ 20% с маржи
15+ оплат в неделю ➔ 30% с каждой сделки

Вся статистика, статусы лидов и баланс обновляются в реальном времени.

⚠️ <b>Важно:</b> Перед стартом обязательно изучите Регламент арбитража в личном кабинете. Там указаны разрешённые источники трафика, правила фиксации клиентов и условия выплат. Фрод и спам — бан без выплаты.

Ваша ставка: {percent}%
Приведено: {leads} чел.

Нажмите кнопку ниже, чтобы забрать реф-ссылку и открыть кабинет 👇
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 Личный кабинет", callback_data="partner_cabinet"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    if data == "partner_cabinet":
        create_partner(user_id)
        show_partner_cabinet(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id)
        return
    
    if data == "partner_refresh":
        create_partner(user_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_partner_cabinet(call.message.chat.id, user_id)
        bot.answer_callback_query(call.id, "Обновлено")
        return
    
    if data == "partner_withdraw":
        balance = get_partner_balance(user_id)
        
        if balance < 5000:
            msg = bot.send_message(call.message.chat.id, "❌ Минимальная сумма вывода 5000₽")
            threading.Thread(target=lambda: (time.sleep(15), bot.delete_message(msg.chat.id, msg.message_id))).start()
            bot.answer_callback_query(call.id)
            return
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, 
                              "Отправьте реквизиты для вывода средств:\n\n👤 ФИО получателя\n🪙 Банк\n💳 Номер карты/телефона\n💵 Сумма вывода\n\nОтправьте данные в одном сообщении!")
        bot.register_next_step_handler(msg, process_withdraw)
        bot.answer_callback_query(call.id)
        return
    
    if data == "partner_rules":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📜 Открыть", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/ReglamentArbitrazhDigital/")))
        bot.edit_message_text("📜 Регламент", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    if data == "back_to_main":
        if user_id in user_data:
            del user_data[user_id]
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith("bot_func_"):
        funcs = {
            "bot_func_1": "💰 Прием и квалификация заявок",
            "bot_func_2": "⚙️ Интеграция с CRM / Кастомная админка",
            "bot_func_3": "🔗 Реферальная система / Вирусный маркетинг",
            "bot_func_4": "🧩 Другое (опишите текстом)"
        }
        if user_id in user_data:
            user_data[user_id]['function'] = funcs.get(data, "Другое")
            user_data[user_id]['step'] = 2
            bot.delete_message(call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?", reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_bot)
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith("ref_reward_"):
        rewards = {
            "ref_reward_1": "💰 Выплата процентов / Кэшбэк деньгами",
            "ref_reward_2": "🎁 Бонусные баллы / Скидки на продукт",
            "ref_reward_3": "🔑 Доступ к закрытому контенту / Функциям",
            "ref_reward_4": "🧩 Сложная многоуровневая система"
        }
        if user_id in user_data:
            user_data[user_id]['reward'] = rewards.get(data, "Другое")
            user_data[user_id]['step'] = 2
            bot.delete_message(call.message.chat.id, call.message.message_id)
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Да", callback_data="ref_integration_yes"),
                types.InlineKeyboardButton("Нет", callback_data="ref_integration_no")
            )
            bot.send_message(call.message.chat.id, "Нужна ли интеграция с Вашей текущей CRM-системой или платежными сервисами для автоматических выплат?", reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    if data in ("ref_integration_yes", "ref_integration_no"):
        if user_id in user_data:
            user_data[user_id]['integration'] = "Да" if data == "ref_integration_yes" else "Нет"
            user_data[user_id]['step'] = 3
            bot.delete_message(call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?", reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_ref)
        bot.answer_callback_query(call.id)
        return
    
    if data.startswith("seo_"):
        tariffs = {
            "seo_mini": "Тариф мини от 35 000₽/мес",
            "seo_medium": "Тариф медиум от 50 000₽/мес",
            "seo_pro": "Тариф PRO от 65 000₽/мес"
        }
        if user_id in user_data:
            user_data[user_id]['tariff'] = tariffs.get(data, "Неизвестный")
            user_data[user_id]['step'] = 1
            bot.delete_message(call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, 
                                  "Укажите <b>ссылку</b> на Ваш сайт и <b>основные регионы</b>, в которых нужно поднять продажи. <b>Напишите текстом в одном сообщении.</b>",
                                  parse_mode='HTML', reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_seo)
        bot.answer_callback_query(call.id)
        return
    
    # ===== АДМИНСКИЕ КОЛЛБЭКИ =====
    if data.startswith("close_app_"):
        handle_close_app(call)
        return
    if data.startswith("reject_app_"):
        handle_reject_app(call)
        return
    if data == "admin_ban":
        handle_admin_ban(call)
        return
    if data == "admin_unban":
        handle_admin_unban(call)
        return
    if data == "admin_make_admin":
        handle_admin_make_admin(call)
        return
    if data == "admin_remove_admin":
        handle_admin_remove_admin(call)
        return
    if data == "admin_stats":
        handle_admin_stats(call)
        return
    if data == "admin_applications":
        handle_admin_applications(call)
        return
    if data == "admin_payments":
        handle_admin_payments(call)
        return
    if data == "admin_update_partner":
        handle_admin_update_partner(call)
        return
    if data == "admin_broadcast":
        handle_admin_broadcast(call)
        return
    if data == "admin_mass_broadcast":
        handle_admin_mass_broadcast(call)
        return
    if data.startswith("admin_unban_confirm_"):
        handle_admin_unban_confirm(call)
        return
    if data.startswith("admin_unban_cancel_"):
        handle_admin_unban_cancel(call)
        return
    if data.startswith("admin_remove_admin_confirm_"):
        handle_admin_remove_admin_confirm(call)
        return
    if data.startswith("admin_payment_confirm_"):
        handle_admin_payment_confirm(call)
        return
    if data.startswith("admin_payment_reject_"):
        handle_admin_payment_reject(call)
        return
    if data.startswith("admin_partner_stats_"):
        handle_admin_partner_stats(call)
        return
    if data.startswith("admin_partner_balance_"):
        handle_admin_partner_balance(call)
        return
    if data.startswith("admin_partner_stats_back_"):
        handle_admin_partner_stats_back(call)
        return
    if data == "admin_back":
        admin_panel_back(call)
        return
    
    bot.answer_callback_query(call.id, "Неизвестная команда")

# ==================== ВЫВОД СРЕДСТВ (С АЛГОРИТМОМ ЛУНА) ====================

def process_withdraw(message):
    user_id = message.from_user.id
    text = message.text
    
    try:
        lines = text.split('\n')
        if len(lines) < 4:
            bot.send_message(message.chat.id, "❌ Неправильный формат. Отправьте все данные с новой строки.")
            return
        
        full_name = lines[0].strip()
        bank = lines[1].strip()
        card = lines[2].strip()
        amount = float(re.search(r'[\d.]+', lines[3]).group()) if re.search(r'[\d.]+', lines[3]) else 0
        
        if amount < 5000:
            bot.send_message(message.chat.id, "❌ Минимальная сумма 5000₽")
            return
        
        # ===== ПРОВЕРКА КАРТЫ ПО АЛГОРИТМУ ЛУНА =====
        # Извлекаем только цифры из номера карты
        card_number = re.sub(r'\D', '', card)
        
        if not luhn_check(card_number):
            bot.send_message(
                message.chat.id,
                "❌ Введён неверный номер банковской карты. Пожалуйста, проверьте правильность введённых данных и попробуйте снова.\n\n"
                "Убедитесь, что номер карты состоит из 16 цифр и введён без ошибок."
            )
            return
        # ===========================================
        
        balance = get_partner_balance(user_id)
        if amount > balance:
            bot.send_message(message.chat.id, f"❌ Недостаточно средств. Доступно: {balance}₽")
            return
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else None
        
        c.execute("UPDATE partners SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                  (amount, user_id, amount))
        if c.rowcount == 0:
            conn.close()
            bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")
            return
        
        c.execute("INSERT INTO payment_requests (user_id, username, full_name, bank, card_number, amount, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (user_id, username, full_name, bank, card, amount, now_str()))
        req_id = c.lastrowid
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, "✅ Заявка принята! Выплата в течение 24 часов.", reply_markup=main_menu())
        
        admin_text = f"""
⚠️ ЗАЯВКА НА ВЫПЛАТУ #{req_id}
👤 @{username or 'Нет'} [ID: <code>{user_id}</code>]
💰 Сумма: {amount}₽
🏦 Банк: {bank}
💳 Карта: {card}
👤 ФИО: {full_name}
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Выплачено", callback_data=f"admin_payment_confirm_{req_id}"),
            types.InlineKeyboardButton("🚫 Отказ", callback_data=f"admin_payment_reject_{req_id}")
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, admin_text, parse_mode='HTML', reply_markup=markup)
            except:
                pass
                
    except Exception as e:
        print(f"❌ Ошибка вывода: {e}")
        bot.send_message(message.chat.id, "Ошибка. Попробуйте позже.", reply_markup=main_menu())

# ==================== АДМИНСКИЕ ФУНКЦИИ ====================

def handle_admin_ban(call):
    msg = bot.send_message(call.message.chat.id, "🔨 Введите ID пользователя:")
    bot.register_next_step_handler(msg, process_admin_ban)
    bot.answer_callback_query(call.id)

def process_admin_ban(message):
    try:
        user_id = int(message.text.strip())
        
        if user_id == OWNER_ID:
            bot.send_message(message.chat.id, "❌ Нельзя заблокировать владельца")
            return
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        
        if not r:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            conn.close()
            return
        
        c.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        c.execute("INSERT INTO ban_history (user_id, banned_by, ban_date) VALUES (?, ?, ?)",
                  (user_id, message.from_user.id, now_str()))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, f"✅ Пользователь {user_id} заблокирован")
        
        try:
            bot.send_message(user_id, "🚫 Вы заблокированы в Golden House.", reply_markup=banned_menu())
        except:
            pass
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_admin_unban(call):
    msg = bot.send_message(call.message.chat.id, "🔓 Введите ID пользователя:")
    bot.register_next_step_handler(msg, process_admin_unban)
    bot.answer_callback_query(call.id)

def process_admin_unban(message):
    try:
        user_id = int(message.text.strip())
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        
        if not r:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            conn.close()
            return
        
        if r[0] != 1:
            bot.send_message(message.chat.id, "❌ Пользователь не заблокирован")
            conn.close()
            return
        
        conn.close()
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Да ✅", callback_data=f"admin_unban_confirm_{user_id}"),
            types.InlineKeyboardButton("Нет 🚫", callback_data=f"admin_unban_cancel_{user_id}")
        )
        
        bot.send_message(message.chat.id, f"Подтвердите разблокировку {user_id}:", reply_markup=markup)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_admin_unban_confirm(call):
    try:
        user_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        c.execute("UPDATE ban_history SET unban_date = ? WHERE user_id = ? AND unban_date IS NULL",
                  (now_str(), user_id))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Пользователь {user_id} разблокирован", call.message.chat.id, call.message.message_id)
        
        try:
            bot.send_message(user_id, "✅ Ваш доступ восстановлен. Golden House", reply_markup=main_menu())
        except:
            pass
        
        bot.answer_callback_query(call.id, "Разблокирован")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_unban_cancel(call):
    bot.edit_message_text("❌ Разблокировка отменена", call.message.chat.id, call.message.message_id)
    admin_panel_back(call)
    bot.answer_callback_query(call.id)

def handle_admin_make_admin(call):
    msg = bot.send_message(call.message.chat.id, "👑 Введите ID пользователя:")
    bot.register_next_step_handler(msg, process_admin_make_admin)
    bot.answer_callback_query(call.id)

def process_admin_make_admin(message):
    try:
        user_id = int(message.text.strip())
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        
        if not r:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            conn.close()
            return
        
        c.execute("UPDATE users SET status = 'admin' WHERE user_id = ?", (user_id,))
        c.execute("INSERT INTO admin_history (user_id, added_by, added_at) VALUES (?, ?, ?)",
                  (user_id, message.from_user.id, now_str()))
        conn.commit()
        conn.close()
        
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
        
        bot.send_message(message.chat.id, f"✅ Администратор {user_id} добавлен")
        
        try:
            bot.send_message(user_id, "🎉 Добро пожаловать в админ-команду Golden House! Вас успешно назначили новым администратором этого бота. Права уже активны.\n\n🚀 Запустить панель администратора: /admin")
        except:
            pass
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

@owner_only_callback
def handle_admin_remove_admin(call):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("""SELECT u.user_id, u.username, ah.added_at 
                     FROM users u
                     JOIN admin_history ah ON u.user_id = ah.user_id
                     WHERE u.status = 'admin' AND u.user_id != ? AND ah.removed_at IS NULL""",
                  (OWNER_ID,))
        admins = c.fetchall()
        conn.close()
        
        if not admins:
            bot.edit_message_text("❌ Нет других администраторов", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        
        text = "👥 Управление администраторами:\n\n"
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for i, (admin_id, username, added_at) in enumerate(admins, 1):
            text += f"{i}. @{username or 'Нет'} [ID: <code>{admin_id}</code>] 📅 {added_at[:16]}\n"
            markup.add(types.InlineKeyboardButton(f"Разжаловать @{username or str(admin_id)}", 
                                                 callback_data=f"admin_remove_admin_confirm_{admin_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_remove_admin_confirm(call):
    try:
        user_id = int(call.data.split("_")[4])
        
        if user_id == OWNER_ID:
            bot.answer_callback_query(call.id, "❌ Нельзя разжаловать владельца")
            return
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else "Неизвестно"
        
        c.execute("UPDATE users SET status = 'client' WHERE user_id = ?", (user_id,))
        c.execute("UPDATE admin_history SET removed_at = ? WHERE user_id = ? AND removed_at IS NULL",
                  (now_str(), user_id))
        
        if user_id in ADMIN_IDS:
            ADMIN_IDS.remove(user_id)
        
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Администратор @{username} разжалован", call.message.chat.id, call.message.message_id)
        
        try:
            bot.send_message(user_id, "🚫 Ваш статус администратора аннулирован. Вы были удалены из списка администраторов бота Golden House.🔐 Доступ к админ-панели /admin и всем управляющим функциям для вашего аккаунта полностью закрыт.")
        except:
            pass
        
        bot.answer_callback_query(call.id, "Разжалован")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

# ===== СТАТИСТИКА (ТОЛЬКО КНОПКА "НАЗАД") =====
def handle_admin_stats(call):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM applications WHERE app_status = 'pending'")
        pending = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM applications WHERE app_status = 'closed'")
        closed = c.fetchone()[0] or 0
        
        conn.close()
        
        text = f"""
📈 Статистика агентства Golden House

👥 Пользователи:
Всего пользователей в боте: {total} чел.
Заблокированных пользователей: {banned}

💼 Заявки:
Необработанные заявки: {pending}
Завершённых сделок за всё время: {closed}
        """
        
        # ТОЛЬКО КНОПКА "НАЗАД"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_applications(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back"))
    
    msg = bot.edit_message_text("📋 Отправьте ID пользователя или дату в формате ДД.ММ.ГГГГ:\n\nНапример:\n• 31.07.2026 — все заявки за день\n• 8396445302 — все заявки пользователя\n• 31.07.2026 8396445302 — заявки пользователя за день", 
                               call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.register_next_step_handler(msg, process_search_apps)
    bot.answer_callback_query(call.id)

def process_search_apps(message):
    try:
        query = message.text.strip()
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        # ПАРСИМ ЗАПРОС
        parts = query.split()
        date_str = None
        client_id = None
        service_key = None
        
        for part in parts:
            # Проверяем формат даты ДД.ММ.ГГГГ
            if re.match(r'^\d{2}\.\d{2}\.\d{4}$', part):
                day, month, year = part.split('.')
                date_str = f"{year}-{month}-{day}"
            elif part.isdigit():
                client_id = int(part)
            elif part in ['web', 'bot', 'ref', 'seo']:
                service_key = part
        
        # Строим запрос
        query_sql = "SELECT * FROM applications WHERE 1=1"
        params = []
        
        if date_str:
            query_sql += " AND created_at LIKE ?"
            params.append(date_str + "%")
        if client_id:
            query_sql += " AND client_id = ?"
            params.append(client_id)
        if service_key:
            query_sql += " AND service = ?"
            params.append(service_key)
        
        query_sql += " ORDER BY created_at DESC LIMIT 20"
        
        c.execute(query_sql, params)
        apps = c.fetchall()
        conn.close()
        
        if not apps:
            bot.send_message(message.chat.id, "❌ Заявок не найдено")
            return
        
        for app in apps[:5]:
            app_id, client_id_db, username, service, answers, status, created_at, referrer = app
            status_emoji = "🆕" if status == 'pending' else "✅" if status == 'closed' else "🚫"
            
            text = f"""
{status_emoji} Заявка #{app_id}
👤 @{username or 'Нет'} [ID: <code>{client_id_db}</code>]
📋 {service}
📅 {created_at[:16]}

{answers[:200]}...
            """
            
            if status == 'pending':
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    types.InlineKeyboardButton("✅ Закрыть", callback_data=f"close_app_{app_id}"),
                    types.InlineKeyboardButton("🚫 Отказ", callback_data=f"reject_app_{app_id}")
                )
                bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
            else:
                bot.send_message(message.chat.id, text, parse_mode='HTML')
        
        if len(apps) > 5:
            bot.send_message(message.chat.id, f"📋 Показано 5 из {len(apps)} заявок")
            
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка поиска")

def handle_admin_payments(call):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT * FROM payment_requests WHERE status = 'pending' ORDER BY created_at DESC")
        payments = c.fetchall()
        conn.close()
        
        if not payments:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 назад", callback_data="admin_back"))
            bot.edit_message_text("🗂 нет активных заявок", call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)
            return
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        for p in payments[:5]:
            pay_id, user_id, username, full_name, bank, card, amount, status, created_at = p
            
            text = f"""
💳 Заявка #{pay_id}
👤 @{username or 'Нет'} [ID: <code>{user_id}</code>]
💰 {amount}₽
🏦 {bank}
💳 {card}
👤 {full_name}
📅 {created_at[:16]}
            """
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Выплачено", callback_data=f"admin_payment_confirm_{pay_id}"),
                types.InlineKeyboardButton("🚫 Отказ", callback_data=f"admin_payment_reject_{pay_id}")
            )
            
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_payment_confirm(call):
    try:
        pay_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount FROM payment_requests WHERE id = ?", (pay_id,))
        r = c.fetchone()
        
        if not r:
            bot.answer_callback_query(call.id, "Не найдено")
            conn.close()
            return
        
        user_id, amount = r
        
        c.execute("UPDATE payment_requests SET status = 'paid' WHERE id = ?", (pay_id,))
        c.execute("UPDATE partners SET total_paid = total_paid + ? WHERE user_id = ?",
                  (amount, user_id))
        c.execute("INSERT INTO payout_history (user_id, amount, created_at) VALUES (?, ?, ?)",
                  (user_id, amount, now_str()))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Выплата #{pay_id} подтверждена", call.message.chat.id, call.message.message_id)
        
        try:
            bot.send_message(user_id, 
                           "✅ Ваша заявка на выплату завершена! Администратор отправил денежные средства по указанным реквизитам. Если у Вас остались вопросы напишите нам @opps911, digitalofficialgoldenhouse@gmail.com")
        except:
            pass
        
        bot.answer_callback_query(call.id, "Готово")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_payment_reject(call):
    try:
        pay_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount FROM payment_requests WHERE id = ?", (pay_id,))
        r = c.fetchone()
        user_id, amount = r if r else (None, None)
        
        c.execute("UPDATE payment_requests SET status = 'rejected' WHERE id = ?", (pay_id,))
        if user_id is not None:
            c.execute("UPDATE partners SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"❌ Заявка #{pay_id} отклонена", call.message.chat.id, call.message.message_id)
        
        if user_id:
            try:
                bot.send_message(user_id, 
                               "❌ Ваша заявка на выплату отвергнута. Напишите нам для выяснения причин @opps911, digitalofficialgoldenhouse@gmail.com при отправке обращения указывайте свой ID, username, дату и время подачи заявки.")
            except:
                pass
        
        bot.answer_callback_query(call.id, "Отклонено")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_update_partner(call):
    msg = bot.send_message(call.message.chat.id, "📊 Введите ID пользователя:")
    bot.register_next_step_handler(msg, process_admin_update_partner)
    bot.answer_callback_query(call.id)

def process_admin_update_partner(message):
    try:
        user_id = int(message.text.strip())
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        
        if not r:
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            conn.close()
            return
        
        create_partner(user_id)
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Показать статистику", callback_data=f"admin_partner_stats_{user_id}"),
            types.InlineKeyboardButton("💰 Начислить баланс", callback_data=f"admin_partner_balance_{user_id}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        bot.send_message(message.chat.id, f"👤 @{r[0]} [ID: <code>{user_id}</code>]", parse_mode='HTML', reply_markup=markup)
        conn.close()
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_admin_partner_stats(call):
    try:
        user_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else "Нет"
        
        c.execute("SELECT leads_this_week, balance, total_paid FROM partners WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        conn.close()
        
        if not r:
            bot.answer_callback_query(call.id, "Нет данных")
            return
        
        leads, balance, total_paid = r
        percent = get_partner_percent(user_id)
        next_percent, leads_to_next = get_next_level_info(user_id)
        
        text = f"""
📊 Статистика партнера
👤 @{username} [ID: <code>{user_id}</code>]
📈 Текущая ставка: {percent}%
👥 Лидов за неделю: {leads}
💰 Баланс: {balance}₽
💵 Выплачено: {total_paid}₽
🔥 До следующего уровня ({next_percent}%) осталось: {leads_to_next} лид(ов)
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💰 Начислить баланс", callback_data=f"admin_partner_balance_{user_id}"),
            types.InlineKeyboardButton("🔙 назад", callback_data=f"admin_partner_stats_back_{user_id}")
        )
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_partner_stats_back(call):
    try:
        user_id = int(call.data.split("_")[3])
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Показать статистику", callback_data=f"admin_partner_stats_{user_id}"),
            types.InlineKeyboardButton("💰 Начислить баланс", callback_data=f"admin_partner_balance_{user_id}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        bot.edit_message_text(f"👤 Пользователь [ID: <code>{user_id}</code>]", 
                             call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_partner_balance(call):
    try:
        user_id = int(call.data.split("_")[3])
        
        user_states[call.from_user.id] = {'action': 'admin_partner_balance_amount', 'partner_id': user_id}
        
        msg = bot.send_message(call.message.chat.id, "💰 Введите сумму начисления:")
        bot.register_next_step_handler(msg, process_admin_partner_balance_amount)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def process_admin_partner_balance_amount(message):
    try:
        user_id = message.from_user.id
        state = user_states.get(user_id, {})
        partner_id = state.get('partner_id')
        
        if not partner_id:
            bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте заново.")
            return
        
        amount = float(message.text.strip().replace(',', '.'))
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Сумма должна быть > 0")
            return
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE partners SET balance = balance + ? WHERE user_id = ?",
                  (amount, partner_id))
        conn.commit()
        conn.close()
        
        leads = get_partner_leads(partner_id)
        percent = get_partner_percent(partner_id)
        balance = get_partner_balance(partner_id)
        next_percent, leads_to_next = get_next_level_info(partner_id)
        
        try:
            bot.send_message(partner_id, 
                           f"💰 Администрация Golden House:\n"
                           f"Ваш баланс: {balance}₽\n"
                           f"Начислено: {amount}₽\n"
                           f"Ваш текущий процент: {percent}%\n"
                           f"До повышения ставки осталось привести: {leads_to_next} лид(ов)\n"
                           f"Удачной охоты! 🎯")
        except:
            pass
        
        bot.send_message(message.chat.id, f"✅ Начислено {amount}₽ пользователю {partner_id}")
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("📊 Показать статистику", callback_data=f"admin_partner_stats_{partner_id}"),
            types.InlineKeyboardButton("💰 Начислить баланс", callback_data=f"admin_partner_balance_{partner_id}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        bot.send_message(message.chat.id, f"👤 Пользователь [ID: <code>{partner_id}</code>]", 
                        parse_mode='HTML', reply_markup=markup)
        
        if user_id in user_states:
            del user_states[user_id]
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите сумму числом (например: 5000)")
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_admin_broadcast(call):
    msg = bot.send_message(call.message.chat.id, "📢 Введите ID пользователя:")
    bot.register_next_step_handler(msg, process_broadcast_id)
    bot.answer_callback_query(call.id)

def process_broadcast_id(message):
    try:
        user_id = int(message.text.strip())
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if not c.fetchone():
            bot.send_message(message.chat.id, "❌ Пользователь не найден")
            conn.close()
            return
        conn.close()
        
        user_states[message.from_user.id] = {'action': 'admin_broadcast_msg', 'target_id': user_id}
        msg = bot.send_message(message.chat.id, "📝 Напишите сообщение:")
        bot.register_next_step_handler(msg, process_broadcast_msg)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def process_broadcast_msg(message):
    try:
        user_id = message.from_user.id
        state = user_states.get(user_id, {})
        target_id = state.get('target_id')
        
        if not target_id:
            bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте заново.")
            return
        
        bot.send_message(target_id, f"📨 Сообщение от администрации Golden House\n\n{message.text}")
        bot.send_message(message.chat.id, f"✅ Отправлено пользователю {target_id}")
        
        if user_id in user_states:
            del user_states[user_id]
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_admin_mass_broadcast(call):
    msg = bot.send_message(call.message.chat.id, "📢 Введите сообщение для всех:")
    bot.register_next_step_handler(msg, process_mass_broadcast)
    bot.answer_callback_query(call.id)

def process_mass_broadcast(message):
    try:
        text = message.text
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = c.fetchall()
        conn.close()
        
        success, failed = 0, 0
        status = bot.send_message(message.chat.id, "📨 Отправка...")
        
        for user in users:
            try:
                bot.send_message(user[0], f"📢 Рассылка Golden House:\n\n{text}")
                success += 1
                time.sleep(0.05)
            except:
                failed += 1
        
        bot.edit_message_text(f"✅ Готово!\nОтправлено: {success}\nНе доставлено: {failed}",
                            message.chat.id, status.message_id)
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def handle_close_app(call):
    try:
        app_id = int(call.data.split("_")[2])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE applications SET app_status = 'closed' WHERE id = ?", (app_id,))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Заявка #{app_id} закрыта", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Закрыто")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_reject_app(call):
    try:
        app_id = int(call.data.split("_")[2])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"🚫 Заявка #{app_id} отклонена и удалена", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Отклонено")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def admin_panel_back(call):
    user_id = call.from_user.id
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("🔨 Заблокировать", callback_data="admin_ban"),
        types.InlineKeyboardButton("🔓 Разблокировать", callback_data="admin_unban"),
        types.InlineKeyboardButton("👑 Назначить админа", callback_data="admin_make_admin"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("📋 Заявки", callback_data="admin_applications"),
        types.InlineKeyboardButton("💳 Выплаты", callback_data="admin_payments"),
        types.InlineKeyboardButton("➕ Обновить партнера", callback_data="admin_update_partner"),
        types.InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        types.InlineKeyboardButton("💣 Массовая рассылка", callback_data="admin_mass_broadcast")
    ]
    
    if user_id == OWNER_ID:
        buttons.append(types.InlineKeyboardButton("❌ Разжаловать админа", callback_data="admin_remove_admin"))
    
    markup.add(*buttons)
    
    try:
        bot.edit_message_text("🗃 Панель управления", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, "🗃 Панель управления", reply_markup=markup)
    
    bot.answer_callback_query(call.id)

# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 ЗАПУСК GOLDEN HOUSE БОТ")
    print("=" * 50)
    
    init_db()
    load_admin_ids()
    reset_weekly_stats_thread()
    
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"👥 Админы: {ADMIN_IDS}")
    print("=" * 50)
    
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            print("🔄 Перезапуск через 3 секунды...")
            time.sleep(3)