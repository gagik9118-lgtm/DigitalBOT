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
TOKEN = '8575046727:AAEMIIrHcHrfe5FN6yzaV7gJOYSIi_FMTHY'
OWNER_ID = 8396445302
ADMIN_IDS = [8396445302]

bot = telebot.TeleBot(TOKEN)
user_data = {}
user_states = {}

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        # Пользователи (добавлено поле privacy_accepted)
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'client',
            is_banned INTEGER DEFAULT 0,
            registered_at TIMESTAMP,
            privacy_accepted INTEGER DEFAULT 0
        )''')
        
        # Партнеры (арбитражники)
        c.execute('''CREATE TABLE IF NOT EXISTS partners (
            user_id INTEGER PRIMARY KEY,
            leads_this_week INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            total_paid REAL DEFAULT 0,
            last_week_reset TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )''')
        
        # Заявки на услуги
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
        
        # Заявки на выплаты
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
        
        # История выплат
        c.execute('''CREATE TABLE IF NOT EXISTS payout_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            created_at TIMESTAMP
        )''')
        
        # История админов
        c.execute('''CREATE TABLE IF NOT EXISTS admin_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            added_by INTEGER,
            added_at TIMESTAMP,
            removed_at TIMESTAMP DEFAULT NULL
        )''')
        
        # История банов
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
        
        # Добавляем владельца
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = ?", (OWNER_ID,))
        if not c.fetchone():
            c.execute("INSERT INTO users (user_id, username, full_name, status, registered_at, privacy_accepted) VALUES (?, ?, ?, ?, ?, ?)",
                      (OWNER_ID, "opps911", "Владелец", "owner", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 1))
            conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

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
                  (user_id, username, full_name, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка сохранения: {e}")

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
    """Проверяет, принял ли пользователь политику конфиденциальности"""
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
    """Отмечает, что пользователь принял политику"""
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
                  (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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

def reset_weekly_stats():
    while True:
        now = datetime.now()
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
            c.execute("UPDATE partners SET leads_this_week = 0, last_week_reset = ?", 
                      (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            conn.commit()
            conn.close()
            print("🔄 Статистика сброшена")
        except Exception as e:
            print(f"❌ Ошибка сброса: {e}")

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
    """Декоратор для проверки согласия с политикой конфиденциальности"""
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        user_id = message.from_user.id
        if not has_accepted_privacy(user_id):
            # Отправляем сообщение с просьбой принять политику
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📜 Политика конфиденциальности", url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/"),
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
    """Декоратор для callback-запросов"""
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = call.from_user.id
        if not has_accepted_privacy(user_id):
            bot.answer_callback_query(call.id, "🔒 Сначала примите политику конфиденциальности", show_alert=True)
            # Отправляем сообщение с просьбой принять политику
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("📜 Политика конфиденциальности", url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/"),
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
        
        # Проверяем, принята ли политика
        if not has_accepted_privacy(message.from_user.id):
            # Приветственное сообщение с политикой
            text = """
<b>Добро пожаловать в Golden House!</b> 

Пока вы читаете этот текст, ваши менеджеры пропускают сообщения, а конкуренты забирают горячие лиды. <b>Мы решаем эту проблему раз и навсегда.</b> <b>Golden House — это автоматизация бизнес-процессов на высшем уровне.</b> Мы создаем умные экосистемы, которые работают на вас <b>24/7/365</b>.

<b>Что мы внедряем для вашего роста:</b>

🤖 Интеллектуальные TG-боты — моментальная обработка сотен заявок одновременно без потери качества.
<b>📊 Админ-панели и CRM</b> — полный контроль, аналитика и управление процессами в один клик.
<b>🔗 Реферальные системы</b> — запуск вирусного маркетинга, который заставит клиентов приводить к вам новых покупателей.

Вы платите за разработку системы один раз, а экономите миллионы на фонде оплаты труда каждый год. <b>Нажмите кнопку ниже, чтобы обсудить автоматизацию вашего проекта</b> 👇
            """
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
                types.InlineKeyboardButton("📜 Политика конфиденциальности", url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/"),
                types.InlineKeyboardButton("Я прочитал и согласен ✅", callback_data="accept_privacy")
            )
            
            bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
            bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
            return
        
        # Если политика уже принята
        text = """
<b>Добро пожаловать в Golden House!</b> 

Пока вы читаете этот текст, ваши менеджеры пропускают сообщения, а конкуренты забирают горячие лиды. <b>Мы решаем эту проблему раз и навсегда.</b> <b>Golden House — это автоматизация бизнес-процессов на высшем уровне.</b> Мы создаем умные экосистемы, которые работают на вас <b>24/7/365</b>.

<b>Что мы внедряем для вашего роста:</b>

🤖 Интеллектуальные TG-боты — моментальная обработка сотен заявок одновременно без потери качества.
<b>📊 Админ-панели и CRM</b> — полный контроль, аналитика и управление процессами в один клик.
<b>🔗 Реферальные системы</b> — запуск вирусного маркетинга, который заставит клиентов приводить к вам новых покупателей.

Вы платите за разработку системы один раз, а экономите миллионы на фонде оплаты труда каждый год. <b>Нажмите кнопку ниже, чтобы обсудить автоматизацию вашего проекта</b> 👇
        """
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
            types.InlineKeyboardButton("📜 Политика конфиденциальности", url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/")
        )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        
    except Exception as e:
        print(f"❌ Ошибка start: {e}")

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
    
    # Web-разработка
    if text == "💻 Web-разработка":
        user_data[user_id] = {'service': 'Web-разработка', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "Какой тип сайта Вас интересует? (лендинг, визитка, интернет-магазин и т.д.)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
        return
    
    # Telegram-бот
    if text == "🤖 Разработка Telegram-бота":
        user_data[user_id] = {'service': 'Разработка Telegram-бота', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "В какой сфере бизнес и что планируете автоматизировать?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_bot)
        return
    
    # Реферальная система
    if text == "🔗 Разработка реферальной системы":
        user_data[user_id] = {'service': 'Разработка реферальной системы', 'step': 0, 'in_process': True}
        msg = bot.send_message(message.chat.id, "Для какого бизнеса нужна реферальная система?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_ref)
        return
    
    # SEO
    if text == "📈 SEO-продвижение":
        user_data[user_id] = {'service': 'SEO-продвижение', 'step': 0, 'in_process': True}
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("Тариф мини от 35 000₽/мес", callback_data="seo_mini"),
            types.InlineKeyboardButton("Тариф медиум от 50 000₽/мес", callback_data="seo_medium"),
            types.InlineKeyboardButton("Тариф PRO от 65 000₽/мес", callback_data="seo_pro")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Выберите тариф:", reply_markup=markup)

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
        msg = bot.send_message(message.chat.id, "Какой бюджет?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 1:
        user_data[user_id]['budget'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Какой дедлайн?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 2:
        user_data[user_id]['deadline'] = text
        user_data[user_id]['step'] = 3
        msg = bot.send_message(message.chat.id, "Какой бизнес? (например: недвижимость в Москве)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_web)
    elif step == 3:
        user_data[user_id]['business'] = text
        user_data[user_id]['step'] = 4
        msg = bot.send_message(message.chat.id, "Как Вас представить и контакт для связи?", reply_markup=back_menu())
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
        bot.send_message(message.chat.id, "Ошибка.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 0:
        user_data[user_id]['business_area'] = text
        user_data[user_id]['step'] = 1
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("💰 Прием заявок", callback_data="bot_func_1"),
            types.InlineKeyboardButton("⚙️ Интеграция с CRM", callback_data="bot_func_2"),
            types.InlineKeyboardButton("🔗 Реферальная система", callback_data="bot_func_3"),
            types.InlineKeyboardButton("🧩 Другое", callback_data="bot_func_4")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Какой функционал нужен?", reply_markup=markup)
    elif step == 1:
        user_data[user_id]['function'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Как Вас представить и контакт?", reply_markup=back_menu())
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
        bot.send_message(message.chat.id, "Ошибка.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 0:
        user_data[user_id]['business_type'] = text
        user_data[user_id]['step'] = 1
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        buttons = [
            types.InlineKeyboardButton("💰 Выплата процентов", callback_data="ref_reward_1"),
            types.InlineKeyboardButton("🎁 Бонусные баллы", callback_data="ref_reward_2"),
            types.InlineKeyboardButton("🔑 Доступ к контенту", callback_data="ref_reward_3"),
            types.InlineKeyboardButton("🧩 Многоуровневая", callback_data="ref_reward_4")
        ]
        markup.add(*buttons)
        bot.send_message(message.chat.id, "Какую механику вознаграждения?", reply_markup=markup)
    elif step == 1:
        user_data[user_id]['reward'] = text
        user_data[user_id]['step'] = 2
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Да", callback_data="ref_integration_yes"),
            types.InlineKeyboardButton("Нет", callback_data="ref_integration_no")
        )
        bot.send_message(message.chat.id, "Нужна интеграция с CRM?", reply_markup=markup)
    elif step == 2:
        user_data[user_id]['integration'] = text
        user_data[user_id]['step'] = 3
        msg = bot.send_message(message.chat.id, "Как Вас представить и контакт?", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_ref)
    elif step == 3:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

def finish_service(user_id):
    try:
        data = user_data[user_id]
        service = data['service']
        
        answers = [f"Услуга: {service}"]
        
        if service == 'Web-разработка':
            answers.append(f"Тип сайта: {data.get('site_type', '')}")
            answers.append(f"Бюджет: {data.get('budget', '')}")
            answers.append(f"Дедлайн: {data.get('deadline', '')}")
            answers.append(f"Бизнес: {data.get('business', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        elif service == 'Разработка Telegram-бота':
            answers.append(f"Сфера: {data.get('business_area', '')}")
            answers.append(f"Функционал: {data.get('function', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        elif service == 'Разработка реферальной системы':
            answers.append(f"Бизнес: {data.get('business_type', '')}")
            answers.append(f"Вознаграждение: {data.get('reward', '')}")
            answers.append(f"Интеграция: {data.get('integration', '')}")
            answers.append(f"Контакты: {data.get('contact', '')}")
        
        answers_text = "\n".join(answers)
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else None
        
        c.execute("INSERT INTO applications (client_id, username, service, answers_text, created_at) VALUES (?, ?, ?, ?, ?)",
                  (user_id, username, service, answers_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        app_id = c.lastrowid
        conn.commit()
        conn.close()
        
        # Админам
        admin_text = f"""
🔥 НОВАЯ ЗАЯВКА #{app_id}
👤 @{username or 'Нет'} [ID: {user_id}]
📅 {datetime.now().strftime("%d.%m.%Y %H:%M")}

{answers_text}
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Закрыть", callback_data=f"close_app_{app_id}"),
            types.InlineKeyboardButton("🚫 Отказ", callback_data=f"reject_app_{app_id}")
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, admin_text, reply_markup=markup)
            except:
                pass
        
        bot.send_message(user_id, 
                        "✅ Данные приняты! Разбор проекта уже начался. Мы свяжемся в течение часа.\n\n🎁 На созвоне покажем 3 места, где бизнес теряет деньги.\n\nЕсли проект горит — @opps911 или +79950961675",
                        reply_markup=main_menu())
        
        if user_id in user_data:
            del user_data[user_id]
            
    except Exception as e:
        print(f"❌ Ошибка finish: {e}")
        bot.send_message(user_id, "Ошибка. Попробуйте позже.", reply_markup=main_menu())

# ==================== КОЛЛБЭКИ ====================

@bot.callback_query_handler(func=lambda c: True)
@check_banned_callback
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    
    # ===== СОГЛАСИЕ С ПОЛИТИКОЙ =====
    if data == "accept_privacy":
        if set_privacy_accepted(user_id):
            bot.answer_callback_query(call.id, "✅ Спасибо! Политика принята.")
            # Обновляем сообщение, убираем кнопку согласия
            try:
                markup = types.InlineKeyboardMarkup(row_width=1)
                markup.add(
                    types.InlineKeyboardButton("🤝 Партнёрская программа", callback_data="partner_program"),
                    types.InlineKeyboardButton("📜 Политика конфиденциальности", url="https://gagik9118-lgtm.github.io/PolitikaPDnAgency/")
                )
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            except:
                pass
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка. Попробуйте позже.")
        return
    
    # Если политика не принята, блокируем все остальные функции
    if not has_accepted_privacy(user_id):
        bot.answer_callback_query(call.id, "🔒 Сначала примите политику конфиденциальности", show_alert=True)
        return
    
    # Партнерская программа
    if data == "partner_program":
        create_partner(user_id)
        percent = get_partner_percent(user_id)
        leads = get_partner_leads(user_id)
        
        text = f"""
💰 <b>Зарабатывайте с Golden House!</b>

Прогрессивная шкала:
1–5 покупателей/нед → 10%
6–10 → 15%
11–14 → 20%
15+ → 30%

Ваша ставка: {percent}%
Приведено: {leads} чел.
"""
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👤 Личный кабинет", callback_data="partner_cabinet"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    # Личный кабинет
    if data == "partner_cabinet":
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
        next_percent = 15 if leads < 6 else 20 if leads < 11 else 30 if leads < 15 else None
        leads_to_next = 6 - leads if leads < 6 else 11 - leads if leads < 11 else 15 - leads if leads < 15 else 0
        
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        text = f"""
💼 Личный кабинет

👤 @{username}
🆔 {user_id}

📊 Статистика:
Лидов за неделю: {leads}
Ставка: {percent}%
До следующего уровня: {leads_to_next} лид(ов)

💰 Баланс:
Доступно: {balance}₽
Выплачено: {total_paid}₽

🔗 Ссылка: {ref_link}
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("💳 Вывести", callback_data="partner_withdraw"),
            types.InlineKeyboardButton("🔄 Обновить", callback_data="partner_cabinet"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"),
            types.InlineKeyboardButton("🗂 Регламент", callback_data="partner_rules")
        )
        
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        except:
            bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)
        
        bot.answer_callback_query(call.id)
        return
    
    # Вывод средств
    if data == "partner_withdraw":
        balance = get_partner_balance(user_id)
        
        if balance < 5000:
            msg = bot.send_message(call.message.chat.id, "❌ Минимальная сумма вывода 5000₽")
            threading.Thread(target=lambda: (time.sleep(15), bot.delete_message(msg.chat.id, msg.message_id))).start()
            bot.answer_callback_query(call.id)
            return
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        msg = bot.send_message(call.message.chat.id, 
                              "Отправьте реквизиты:\n\n👤 ФИО\n🪙 Банк\n💳 Номер карты\n💵 Сумма")
        bot.register_next_step_handler(msg, process_withdraw)
        bot.answer_callback_query(call.id)
        return
    
    # Регламент
    if data == "partner_rules":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📜 Открыть", web_app=types.WebAppInfo(url="https://gagik9118-lgtm.github.io/ReglamentArbitrazhDigital/")))
        bot.edit_message_text("📜 Регламент", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    # Назад в главное
    if data == "back_to_main":
        if user_id in user_data:
            del user_data[user_id]
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_menu())
        bot.answer_callback_query(call.id)
        return
    
    # Функции для бота
    if data.startswith("bot_func_"):
        funcs = {
            "bot_func_1": "💰 Прием заявок",
            "bot_func_2": "⚙️ Интеграция с CRM",
            "bot_func_3": "🔗 Реферальная система",
            "bot_func_4": "🧩 Другое"
        }
        if user_id in user_data:
            user_data[user_id]['function'] = funcs.get(data, "Другое")
            user_data[user_id]['step'] = 2
            bot.delete_message(call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, "Как Вас представить и контакт?", reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_bot)
        bot.answer_callback_query(call.id)
        return
    
    # Вознаграждения для рефералки
    if data.startswith("ref_reward_"):
        rewards = {
            "ref_reward_1": "💰 Выплата процентов",
            "ref_reward_2": "🎁 Бонусные баллы",
            "ref_reward_3": "🔑 Доступ к контенту",
            "ref_reward_4": "🧩 Многоуровневая"
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
            bot.send_message(call.message.chat.id, "Нужна интеграция с CRM?", reply_markup=markup)
        bot.answer_callback_query(call.id)
        return
    
    # Интеграция для рефералки
    if data in ("ref_integration_yes", "ref_integration_no"):
        if user_id in user_data:
            user_data[user_id]['integration'] = "Да" if data == "ref_integration_yes" else "Нет"
            user_data[user_id]['step'] = 3
            bot.delete_message(call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, "Как Вас представить и контакт?", reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_ref)
        bot.answer_callback_query(call.id)
        return
    
    # SEO тарифы
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
                                  "Укажите <b>ссылку</b> на сайт и <b>регионы</b> для продвижения. <b>Напишите в одном сообщении.</b>",
                                  parse_mode='HTML', reply_markup=back_menu())
            bot.register_next_step_handler(msg, process_seo)
        bot.answer_callback_query(call.id)
        return
    
    # ===== АДМИНСКИЕ КОЛЛБЭКИ (ВСЕ ИСПРАВЛЕНЫ) =====
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
    if data == "admin_back":
        admin_panel_back(call)
        return
    
    # Если ничего не подошло
    bot.answer_callback_query(call.id, "Неизвестная команда")

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
        
        balance = get_partner_balance(user_id)
        if amount > balance:
            bot.send_message(message.chat.id, f"❌ Недостаточно средств. Доступно: {balance}₽")
            return
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        username = r[0] if r else None
        
        c.execute("INSERT INTO payment_requests (user_id, username, full_name, bank, card_number, amount, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (user_id, username, full_name, bank, card, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        req_id = c.lastrowid
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, "✅ Заявка принята! Выплата в течение 24 часов.", reply_markup=main_menu())
        
        # Админу
        admin_text = f"""
⚠️ ЗАЯВКА НА ВЫПЛАТУ #{req_id}
👤 @{username or 'Нет'} [ID: {user_id}]
💰 Сумма: {amount}₽
🏦 Банк: {bank}
💳 Карта: {card}
👤 ФИО: {full_name}
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Выплачено", callback_data=f"admin_payment_confirm_{req_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_payment_reject_{req_id}")
        )
        
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, admin_text, reply_markup=markup)
            except:
                pass
                
    except Exception as e:
        print(f"❌ Ошибка вывода: {e}")
        bot.send_message(message.chat.id, "Ошибка. Попробуйте позже.", reply_markup=main_menu())

def process_seo(message):
    user_id = message.from_user.id
    text = message.text
    
    if text == "🔙 Назад":
        if user_id in user_data:
            del user_data[user_id]
        bot.send_message(message.chat.id, "Выберите услугу:", reply_markup=main_menu())
        return
    
    if user_id not in user_data:
        bot.send_message(message.chat.id, "Ошибка.", reply_markup=main_menu())
        return
    
    step = user_data[user_id].get('step', 0)
    
    if step == 1:
        user_data[user_id]['site_info'] = text
        user_data[user_id]['step'] = 2
        msg = bot.send_message(message.chat.id, "Как Вас представить и контакт? (имя и телефон)", reply_markup=back_menu())
        bot.register_next_step_handler(msg, process_seo)
    elif step == 2:
        user_data[user_id]['contact'] = text
        finish_service(user_id)

# ==================== АДМИНСКИЕ ФУНКЦИИ (ИСПРАВЛЕНЫ) ====================

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
                  (user_id, message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
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
                  (user_id, message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        if user_id not in ADMIN_IDS:
            ADMIN_IDS.append(user_id)
        
        bot.send_message(message.chat.id, f"✅ Администратор {user_id} добавлен")
        
        try:
            bot.send_message(user_id, "🎉 Вас назначили администратором! /admin")
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
            text += f"{i}. @{username or 'Нет'} [ID: {admin_id}] 📅 {added_at[:16]}\n"
            markup.add(types.InlineKeyboardButton(f"Разжаловать @{username or str(admin_id)}", 
                                                 callback_data=f"admin_remove_admin_confirm_{admin_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
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
                  (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
        
        if user_id in ADMIN_IDS:
            ADMIN_IDS.remove(user_id)
        
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Администратор @{username} разжалован", call.message.chat.id, call.message.message_id)
        
        try:
            bot.send_message(user_id, "🚫 Ваш статус администратора аннулирован.")
        except:
            pass
        
        bot.answer_callback_query(call.id, "Разжалован")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_stats(call):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM users")
        total = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM applications WHERE app_status = 'pending'")
        active = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM applications WHERE app_status = 'closed'")
        closed = c.fetchone()[0] or 0
        
        c.execute("SELECT COALESCE(SUM(total_paid), 0) FROM partners")
        paid = c.fetchone()[0] or 0
        
        conn.close()
        
        text = f"""
📈 Статистика Golden House

👥 Пользователи: {total}
🔴 Заблокировано: {banned}
🟢 Активных: {total - banned}

💼 Заявки:
Активных: {active}
Закрыто: {closed}

💰 Выплачено: {paid}₽
        """
        
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
    
    msg = bot.edit_message_text("📋 Отправьте ID пользователя или дату (ДД.ММ.ГГГГ):", 
                               call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.register_next_step_handler(msg, process_search_apps)
    bot.answer_callback_query(call.id)

def process_search_apps(message):
    try:
        query = message.text.strip()
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        
        if query.isdigit():
            c.execute("SELECT id, client_id, username, service, answers_text, app_status, created_at FROM applications WHERE client_id = ? ORDER BY created_at DESC", (int(query),))
        else:
            c.execute("SELECT id, client_id, username, service, answers_text, app_status, created_at FROM applications WHERE created_at LIKE ? OR service LIKE ? ORDER BY created_at DESC",
                      (f"%{query}%", f"%{query}%"))
        
        apps = c.fetchall()
        conn.close()
        
        if not apps:
            bot.send_message(message.chat.id, "❌ Заявок не найдено")
            return
        
        for app in apps[:5]:
            app_id, client_id, username, service, answers, status, created_at = app
            status_emoji = "🆕" if status == 'pending' else "✅" if status == 'closed' else "🚫"
            
            text = f"""
{status_emoji} Заявка #{app_id}
👤 @{username or 'Нет'} [ID: {client_id}]
📋 {service}
📅 {created_at[:16]}

{answers[:150]}...
            """
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Закрыть", callback_data=f"close_app_{app_id}"),
                types.InlineKeyboardButton("🚫 Отказ", callback_data=f"reject_app_{app_id}")
            )
            
            bot.send_message(message.chat.id, text, reply_markup=markup)
        
        if len(apps) > 5:
            bot.send_message(message.chat.id, f"📋 Показано 5 из {len(apps)} заявок")
            
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка поиска")

def handle_admin_payments(call):
    try:
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT id, user_id, username, full_name, bank, card_number, amount, created_at FROM payment_requests WHERE status = 'pending' ORDER BY created_at DESC")
        payments = c.fetchall()
        conn.close()
        
        if not payments:
            bot.edit_message_text("💳 Нет активных заявок", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id)
            return
        
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        for p in payments[:5]:
            req_id, user_id, username, full_name, bank, card, amount, created_at = p
            
            text = f"""
💳 Заявка #{req_id}
👤 @{username or 'Нет'} [ID: {user_id}]
💰 {amount}₽
🏦 {bank}
💳 {card}
👤 {full_name}
📅 {created_at[:16]}
            """
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("✅ Выплачено", callback_data=f"admin_payment_confirm_{req_id}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_payment_reject_{req_id}")
            )
            
            bot.send_message(call.message.chat.id, text, reply_markup=markup)
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_payment_confirm(call):
    try:
        req_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id, amount FROM payment_requests WHERE id = ?", (req_id,))
        r = c.fetchone()
        
        if not r:
            bot.answer_callback_query(call.id, "Не найдено")
            conn.close()
            return
        
        user_id, amount = r
        
        c.execute("UPDATE payment_requests SET status = 'completed' WHERE id = ?", (req_id,))
        c.execute("UPDATE partners SET balance = balance - ?, total_paid = total_paid + ? WHERE user_id = ?",
                  (amount, amount, user_id))
        c.execute("INSERT INTO payout_history (user_id, amount, created_at) VALUES (?, ?, ?)",
                  (user_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"✅ Выплата #{req_id} подтверждена", call.message.chat.id, call.message.message_id)
        
        try:
            bot.send_message(user_id, f"✅ Выплата {amount}₽ отправлена!")
        except:
            pass
        
        bot.answer_callback_query(call.id, "Готово")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_payment_reject(call):
    try:
        req_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM payment_requests WHERE id = ?", (req_id,))
        r = c.fetchone()
        user_id = r[0] if r else None
        
        c.execute("UPDATE payment_requests SET status = 'rejected' WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"❌ Заявка #{req_id} отклонена", call.message.chat.id, call.message.message_id)
        
        if user_id:
            try:
                bot.send_message(user_id, "❌ Ваша заявка на выплату отклонена. Проверьте реквизиты.")
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
            types.InlineKeyboardButton("📊 Статистика", callback_data=f"admin_partner_stats_{user_id}"),
            types.InlineKeyboardButton("💰 Начислить", callback_data=f"admin_partner_balance_{user_id}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data="admin_back")
        )
        
        bot.send_message(message.chat.id, f"👤 @{r[0]} [ID: {user_id}]", reply_markup=markup)
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
        
        text = f"""
📊 Статистика партнера
👤 @{username} [ID: {user_id}]
📈 Ставка: {percent}%
👥 Лидов: {leads}
💰 Баланс: {balance}₽
💵 Выплачено: {total_paid}₽
        """
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"admin_partner_stats_back_{user_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_admin_partner_balance(call):
    try:
        user_id = int(call.data.split("_")[3])
        msg = bot.send_message(call.message.chat.id, "💰 Введите сумму сделки:")
        bot.register_next_step_handler(msg, process_admin_partner_balance, user_id)
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def process_admin_partner_balance(message, user_id):
    try:
        amount = float(message.text.strip().replace(',', '.'))
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Сумма должна быть > 0")
            return
        
        percent = get_partner_percent(user_id)
        profit = amount * percent / 100
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE partners SET balance = balance + ?, leads_this_week = leads_this_week + 1 WHERE user_id = ?",
                  (profit, user_id))
        conn.commit()
        conn.close()
        
        # Проверка достижения уровня
        leads = get_partner_leads(user_id)
        if leads >= 15:
            try:
                bot.send_message(user_id, f"🔥 Поздравляем! Вы достигли 30%! Приведено {leads} клиентов за неделю!")
            except:
                pass
        
        try:
            bot.send_message(user_id, f"🔥 Сделка завершена!\nСумма: {amount}₽\nВаш профит: {profit}₽ (ставка {percent}%)")
        except:
            pass
        
        bot.send_message(message.chat.id, f"✅ Начислено {profit}₽ пользователю {user_id}")
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите сумму")
    except Exception as e:
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
        
        msg = bot.send_message(message.chat.id, "📝 Напишите сообщение:")
        bot.register_next_step_handler(msg, process_broadcast_msg, user_id)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Введите ID (только цифры)")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def process_broadcast_msg(message, user_id):
    try:
        bot.send_message(user_id, f"📨 Сообщение от администрации:\n\n{message.text}")
        bot.send_message(message.chat.id, f"✅ Отправлено пользователю {user_id}")
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
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Подтверждаю ✅", callback_data=f"reject_app_confirm_{app_id}"),
            types.InlineKeyboardButton("Отменить 🚫", callback_data=f"reject_app_cancel_{app_id}")
        )
        
        bot.edit_message_text("Подтвердите отказ:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_reject_app_confirm(call):
    try:
        app_id = int(call.data.split("_")[3])
        
        conn = sqlite3.connect('golden_house.db')
        c = conn.cursor()
        c.execute("UPDATE applications SET app_status = 'rejected' WHERE id = ?", (app_id,))
        conn.commit()
        conn.close()
        
        bot.edit_message_text(f"🚫 Заявка #{app_id} отклонена", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Отклонено")
        
    except Exception as e:
        print(f"Ошибка: {e}")
        bot.answer_callback_query(call.id, "Ошибка")

def handle_reject_app_cancel(call):
    try:
        app_id = int(call.data.split("_")[3])
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Закрыть", callback_data=f"close_app_{app_id}"),
            types.InlineKeyboardButton("🚫 Отказ", callback_data=f"reject_app_{app_id}")
        )
        
        bot.edit_message_text(f"🔄 Отказ отменен для заявки #{app_id}", 
                            call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id, "Отменено")
        
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
    reset_weekly_stats_thread()
    
    print(f"👑 Владелец: {OWNER_ID}")
    print(f"👥 Админы: {ADMIN_IDS}")
    print("=" * 50)
    
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            print("🔄 Перезапуск через 3 секунды...")
            time.sleep(3)