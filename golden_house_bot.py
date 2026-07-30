import sqlite3
import threading
import time
import re
from datetime import datetime, timedelta

import telebot
from telebot import types

# =========================================================
#                       НАСТРОЙКИ
# =========================================================

TOKEN = "8575046727:AAEMIIrHcHrfe5FN6yzaV7gJOYSIi_FMTHY"

OWNER_ID = 8396445302          # главный владелец, только он может разжаловать админов
OWNER_USERNAME = "opps911"

REGLAMENT_BAN_URL = "https://gagik9118-lgtm.github.io/ReglamentSiteGoldenHouee/"
REGLAMENT_PARTNER_URL = "https://gagik9118-lgtm.github.io/ReglamentArbitrazhDigital/"

MIN_WITHDRAW = 5000  # минимальная сумма вывода для партнёра

DB_PATH = "golden_house.db"

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
BOT_USERNAME = None  # заполнится в main()

# =========================================================
#                    БАЗА ДАННЫХ (SQLite)
# =========================================================

db_lock = threading.RLock()


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'client',      -- client / admin / owner
            is_banned INTEGER DEFAULT 0,
            banned_by INTEGER,
            registered_at TEXT,
            referred_by INTEGER,               -- ID арбитражника, если пришёл по ссылке
            admin_added_by INTEGER,
            admin_added_at TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS partners (
            user_id INTEGER PRIMARY KEY,
            leads_this_week INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            total_paid REAL DEFAULT 0
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            service TEXT,
            answers_text TEXT,
            app_status TEXT DEFAULT 'pending',   -- pending / closed / rejected
            referred_by INTEGER,
            created_at TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            full_name TEXT,
            bank TEXT,
            card TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',   -- pending / paid / rejected
            created_at TEXT
        )""")
        # Bankovskie_platezhi - сырые реквизиты, которые прислал пользователь
        cur.execute("""
        CREATE TABLE IF NOT EXISTS Bankovskie_platezhi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            raw_data TEXT,
            created_at TEXT
        )""")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        conn.commit()
        conn.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def msk_now():
    return datetime.utcnow() + timedelta(hours=3)


# --------------------- USERS ---------------------

def get_user(user_id):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row


def ensure_user(user_id, username, full_name, referred_by=None):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            status = "owner" if user_id == OWNER_ID else "client"
            conn.execute(
                "INSERT INTO users (user_id, username, full_name, status, is_banned, registered_at, referred_by) "
                "VALUES (?,?,?,?,0,?,?)",
                (user_id, username, full_name, status, now_str(), referred_by)
            )
            conn.commit()
            conn.close()
            return True  # новый пользователь
        else:
            conn.execute(
                "UPDATE users SET username=?, full_name=? WHERE user_id=?",
                (username, full_name, user_id)
            )
            conn.commit()
            conn.close()
            return False


def set_ban(user_id, banned, by_id=None):
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE users SET is_banned=?, banned_by=? WHERE user_id=?",
                     (1 if banned else 0, by_id, user_id))
        conn.commit()
        conn.close()


def is_banned(user_id):
    row = get_user(user_id)
    return bool(row and row["is_banned"] == 1)


def is_admin_or_owner(user_id):
    if user_id == OWNER_ID:
        return True
    row = get_user(user_id)
    return bool(row and row["status"] in ("admin", "owner"))


def is_owner(user_id):
    return user_id == OWNER_ID


def make_admin(user_id, added_by):
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE users SET status='admin', admin_added_by=?, admin_added_at=? WHERE user_id=?",
                     (added_by, now_str(), user_id))
        conn.commit()
        conn.close()


def remove_admin(user_id):
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE users SET status='client', admin_added_by=NULL, admin_added_at=NULL WHERE user_id=?",
                     (user_id,))
        conn.commit()
        conn.close()


def list_admins():
    with db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM users WHERE status='admin' ORDER BY admin_added_at").fetchall()
        conn.close()
        return rows


def all_active_users():
    with db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()
        conn.close()
        return [r["user_id"] for r in rows]


def all_admin_ids():
    with db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT user_id FROM users WHERE status IN ('admin','owner') AND is_banned=0").fetchall()
        conn.close()
        ids = set(r["user_id"] for r in rows)
        ids.add(OWNER_ID)
        return list(ids)


def display_name(row):
    if row is None:
        return "неизвестен"
    if row["username"]:
        return "@" + row["username"]
    return row["full_name"] or str(row["user_id"])


# --------------------- PARTNERS ---------------------

def get_partner(user_id):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM partners WHERE user_id=?", (user_id,)).fetchone()
        conn.close()
        return row


def ensure_partner(user_id):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM partners WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO partners (user_id, leads_this_week, balance, total_paid) VALUES (?,0,0,0)",
                         (user_id,))
            conn.commit()
        conn.close()


def get_percent(leads):
    if leads >= 15:
        return 30
    elif leads >= 11:
        return 20
    elif leads >= 6:
        return 15
    else:
        return 10


def next_level_info(leads):
    if leads < 6:
        return 15, 6 - leads, 6
    elif leads < 11:
        return 20, 11 - leads, 11
    elif leads < 15:
        return 30, 15 - leads, 15
    else:
        return 30, 0, 15


def accrue_deal(partner_id, amount):
    """Начисляет партнёру профит от сделки, возвращает (percent, profit, leads_this_week)"""
    ensure_partner(partner_id)
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM partners WHERE user_id=?", (partner_id,)).fetchone()
        leads = row["leads_this_week"] + 1
        percent = get_percent(leads)
        profit = round(amount * percent / 100, 2)
        new_balance = row["balance"] + profit
        conn.execute("UPDATE partners SET leads_this_week=?, balance=? WHERE user_id=?",
                     (leads, new_balance, partner_id))
        conn.commit()
        conn.close()
    return percent, profit, leads


def withdraw_balance(partner_id, amount):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM partners WHERE user_id=?", (partner_id,)).fetchone()
        new_balance = max(0, row["balance"] - amount)
        new_total = row["total_paid"] + amount
        conn.execute("UPDATE partners SET balance=?, total_paid=? WHERE user_id=?",
                     (new_balance, new_total, partner_id))
        conn.commit()
        conn.close()


def reset_all_weeks():
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE partners SET leads_this_week=0")
        conn.commit()
        conn.close()


def get_setting(key, default=None):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else default


def set_setting(key, value):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        conn.commit()
        conn.close()


# --------------------- APPLICATIONS ---------------------

def add_application(client_id, service, answers_text, referred_by):
    with db_lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO applications (client_id, service, answers_text, app_status, referred_by, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (client_id, service, answers_text, "pending", referred_by, now_str())
        )
        conn.commit()
        app_id = cur.lastrowid
        conn.close()
        return app_id


def get_application(app_id):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        conn.close()
        return row


def set_application_status(app_id, status):
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE applications SET app_status=? WHERE id=?", (status, app_id))
        conn.commit()
        conn.close()


def search_applications(date_str=None, service_key=None, client_id=None):
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    if date_str:
        query += " AND created_at LIKE ?"
        params.append(date_str + "%")
    if service_key:
        query += " AND service=?"
        params.append(service_key)
    if client_id:
        query += " AND client_id=?"
        params.append(client_id)
    query += " ORDER BY created_at DESC LIMIT 20"
    with db_lock:
        conn = get_conn()
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return rows


# --------------------- PAYMENTS ---------------------

def add_payment_request(user_id, full_name, bank, card, amount):
    with db_lock:
        conn = get_conn()
        cur = conn.execute(
            "INSERT INTO payments (user_id, full_name, bank, card, amount, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, full_name, bank, card, amount, "pending", now_str())
        )
        conn.commit()
        pay_id = cur.lastrowid
        conn.close()
        return pay_id


def get_payment(pay_id):
    with db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
        conn.close()
        return row


def set_payment_status(pay_id, status):
    with db_lock:
        conn = get_conn()
        conn.execute("UPDATE payments SET status=? WHERE id=?", (status, pay_id))
        conn.commit()
        conn.close()


def add_bank_data(user_id, raw_text):
    with db_lock:
        conn = get_conn()
        conn.execute("INSERT INTO Bankovskie_platezhi (user_id, raw_data, created_at) VALUES (?,?,?)",
                     (user_id, raw_text, now_str()))
        conn.commit()
        conn.close()


# =========================================================
#                 СЕРВИСНЫЕ ВОРОНКИ (БРИФЫ)
# =========================================================

SERVICES = {
    "web": {
        "title": "Web-разработка",
        "steps": [
            {"key": "type", "type": "text",
             "text": "Какой тип сайта Вас интересует? Например: лендинг, визитка, интернет магазин и тд.."},
            {"key": "budget", "type": "text", "text": "Отлично! Какой Ваш бюджет?"},
            {"key": "deadline", "type": "text", "text": "Какой нужен дедлайн?"},
            {"key": "business", "type": "text",
             "text": "Что у Вас за бизнес? Например: недвижимость в Москве"},
            {"key": "contact", "type": "text",
             "text": "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?"},
        ],
    },
    "bot": {
        "title": "Разработка Telegram-бота",
        "steps": [
            {"key": "sphere", "type": "text",
             "text": "В какой сфере у Вас бизнес и какое направление планируете автоматизировать?"},
            {"key": "functional", "type": "buttons",
             "text": "Какой ключевой функционал должен быть в боте?",
             "options": [
                 "💰 Прием и квалификация заявок",
                 "⚙️ Интеграция с CRM / Кастомная админка",
                 "🔗 Реферальная система / Вирусный маркетинг",
                 "🧩 Другое (опишите текстом)",
             ]},
            {"key": "contact", "type": "text",
             "text": "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?"},
        ],
    },
    "ref": {
        "title": "Разработка реферальной системы",
        "steps": [
            {"key": "business", "type": "text",
             "text": "Для какого бизнеса или проекта нужна реферальная система (сайт, телеграм-бот, приложение)?"},
            {"key": "mechanic", "type": "buttons",
             "text": "Какую механику вознаграждения планируете использовать?",
             "options": [
                 "💰 Выплата процентов / Кэшбэк деньгами",
                 "🎁 Бонусные баллы / Скидки на продукт",
                 "🔑 Доступ к закрытому контенту / Функциям",
                 "🧩 Сложная многоуровневая система",
             ]},
            {"key": "crm", "type": "buttons",
             "text": "Нужна ли интеграция с вашей текущей CRM-системой или платежными сервисами для автоматических выплат?",
             "options": ["Да", "Нет"]},
            {"key": "contact", "type": "text",
             "text": "Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта?"},
        ],
    },
    "seo": {
        "title": "SEO-продвижение",
        "steps": [
            {"key": "tariff", "type": "buttons",
             "text": "Выберите тариф SEO-продвижения",
             "options": [
                 "Тариф мини от 35 000₽/мес",
                 "Тариф медиум от 50 000₽/мес",
                 "Тариф PRO от 65 000₽/мес",
             ]},
            {"key": "site_regions", "type": "text",
             "text": "Укажите адрес вашего сайта <b>(ссылку)</b> <b>и основные регионы, в которых нужно поднять продажи.</b> "
                     "<b>Напишите текстом в одном сообщении.</b>"},
            {"key": "contact", "type": "text",
             "text": "Отлично, Как Вас представить отделу продаж и по какому контакту связаться для обсуждения проекта? "
                     "Напишите имя и номер телефона в одном сообщение!"},
        ],
    },
}

SUCCESS_TEXT = (
    "✅ Данные приняты! Разбор вашего проекта уже начался. Мы свяжемся с Вами в течение часа.\n\n"
    "🎁 на созвоне мы бесплатно покажем 3 главных места, где Ваш бизнес прямо сейчас теряет деньги "
    "и как закрыть эти дыры с помощью digital-инструментов. Если проект горит — пишите напрямую: "
    f"@{OWNER_USERNAME} или позвоните +79950961675"
)

SERVICE_BUTTONS = ["Web-разработка", "Разработка Telegram-бота", "Разработка реферальной системы", "SEO-продвижение"]
SERVICE_KEY_BY_LABEL = {
    "Web-разработка": "web",
    "Разработка Telegram-бота": "bot",
    "Разработка реферальной системы": "ref",
    "SEO-продвижение": "seo",
}

WELCOME_TEXT = (
    "❤<b>Добро пожаловать в Golden House!</b>\n\n"
    "Пока вы читаете этот текст, ваши менеджеры пропускают сообщения, а конкуренты забирают горячие лиды. "
    "<b>Мы решаем эту проблему раз и навсегда.</b> <b>Golden House — это автоматизация бизнес-процессов на высшем уровне.</b> "
    "Мы создаем умные экосистемы, которые работают на вас <b>24/7/365</b>.\n\n"
    "Что мы внедряем для вашего роста:\n"
    "🤖 Интеллектуальные TG-боты — моментальная обработка сотен заявок одновременно без потери качества.\n"
    "📊 <b>Админ-панели и CRM</b> — полный контроль, аналитика и управление процессами в один клик.\n"
    "🔗 <b>Реферальные системы</b> — запуск вирусного маркетинга, который заставит клиентов приводить к вам новых покупателей.\n\n"
    "Вы платите за разработку системы один раз, а экономите миллионы на фонде оплаты труда каждый год. "
    "<b>Нажмите кнопку ниже, чтобы обсудить автоматизацию вашего проекта</b> 👇"
)

PARTNER_INTRO_TEXT = (
    "💰 Зарабатывайте на digital-услугах вместе с Golden House!\n\n"
    "Мы платим честный процент от маржи за каждого приведенного клиента на разработку сайтов, ботов, "
    "рефералок или SEO. Без вложений с Вашей стороны — только Ваш целевой трафик.\n\n"
    "Прогрессивная шкала выплат:\n"
    "1–5 покупателей в неделю ➔ 10% с каждого лида.\n"
    "6–10 покупателей в неделю ➔ 15% с каждого лида.\n"
    "11–14 покупателей в неделю ➔ 20% с каждого лида.\n"
    "15+ покупателей в неделю ➔ 30% с каждого лида ЗА ВСЮ НЕДЕЛЮ.\n\n"
    "Нажмите кнопку ниже, чтобы получить свою уникальную ссылку"
)

BAN_TEXT = (
    "🚫 Доступ к системе автоматизации Golden House ограничен. Ваш аккаунт заблокирован за нарушение "
    "внутренних регламентов платформы или отправку некорректных данных. Если вы считаете, что блокировка "
    "произошла по ошибке, Вы можете подать официальную апелляцию руководителю агентства.\n\n"
    "👇 Используйте меню ниже для решения вопроса:"
)

UNBAN_TEXT = (
    "Ваш доступ к платформе Golden House восстановлен✅\n\n"
    "По итогам ручной проверки администрация подтвердила, что блокировка была вызвана технической ошибкой. "
    "Все функции экосистемы доступны вам в полном объёме.\n\n"
    "Рекомендуем ознакомиться с регламентом платформы, чтобы избежать повторных ограничений доступа в дальнейшем.\n\n"
    "Благодарим за обращение и понимание.\n\n"
    "Golden House\nСистема контроля доступа"
)

# =========================================================
#                СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ (FSM)
# =========================================================
# user_states[user_id] = {"action": "...", ...любые доп. поля...}
user_states = {}


def clear_state(uid):
    user_states.pop(uid, None)


# =========================================================
#                    КЛАВИАТУРЫ
# =========================================================

def main_reply_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(SERVICE_BUTTONS[0]))
    kb.add(types.KeyboardButton(SERVICE_BUTTONS[1]))
    kb.add(types.KeyboardButton(SERVICE_BUTTONS[2]))
    kb.add(types.KeyboardButton(SERVICE_BUTTONS[3]))
    return kb


def partner_intro_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🤝Партнёрская программа", callback_data="partner:intro"))
    return kb


def get_link_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("👤личный кабинет", callback_data="partner:cabinet"))
    return kb


def partner_cabinet_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 Вывести профит", callback_data="partner:withdraw"))
    kb.add(types.InlineKeyboardButton("🔄 Обновить данные", callback_data="partner:refresh"))
    kb.add(types.InlineKeyboardButton("🗂 Регламент", web_app=types.WebAppInfo(REGLAMENT_PARTNER_URL)))
    kb.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="partner:menu"))
    return kb


def back_only_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="back:main"))
    return kb


def step_kb(service_key, step_index, options=None):
    kb = types.InlineKeyboardMarkup()
    if options:
        for i, opt in enumerate(options):
            kb.add(types.InlineKeyboardButton(opt, callback_data=f"ans:{service_key}:{step_index}:{i}"))
    if step_index == 0:
        kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="back:main"))
    return kb if kb.keyboard else None


def ban_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("👤 Апелляция / Поддержка", url=f"https://t.me/{OWNER_USERNAME}"))
    kb.add(types.InlineKeyboardButton("📜 Регламент агентства", web_app=types.WebAppInfo(REGLAMENT_BAN_URL)))
    return kb


def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🚫 заблокировать", callback_data="adm:block"),
        types.InlineKeyboardButton("✅ разблокировать", callback_data="adm:unblock"),
    )
    kb.add(
        types.InlineKeyboardButton("👑 админа", callback_data="adm:addadmin"),
        types.InlineKeyboardButton("🗑 разжаловать администратора", callback_data="adm:rmadmin_list"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 Общая статистика", callback_data="adm:stats"),
        types.InlineKeyboardButton("➕ обновить статистику арбитражнику", callback_data="adm:updpartner"),
    )
    kb.add(
        types.InlineKeyboardButton("💳 заявки на выплаты", callback_data="adm:payouts"),
        types.InlineKeyboardButton("📋 заявки услуг", callback_data="adm:appssearch"),
    )
    kb.add(
        types.InlineKeyboardButton("📢 Рассылка", callback_data="adm:broadcast"),
        types.InlineKeyboardButton("💣 массовая рассылка", callback_data="adm:massbroadcast"),
    )
    return kb


def back_admin_kb(text="🔙 назад", cb="adm:menu"):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text, callback_data=cb))
    return kb


# =========================================================
#               ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОТПРАВКИ
# =========================================================

def send_admin_panel(chat_id, message_id=None):
    text = "🗃 панель управления Golden house\nВыберите действие:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=admin_menu_kb())
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=admin_menu_kb())


def send_main_menu(chat_id):
    bot.send_message(chat_id, WELCOME_TEXT, reply_markup=main_reply_kb())
    bot.send_message(chat_id, "🤝 Хотите зарабатывать вместе с нами? Подключайтесь к партнёрской программе:",
                      reply_markup=partner_intro_kb())


def notify_ban(user_id):
    try:
        bot.send_message(user_id, BAN_TEXT, reply_markup=ban_kb())
    except Exception:
        pass


def notify_unban(user_id):
    try:
        bot.send_message(user_id, UNBAN_TEXT, reply_markup=types.ReplyKeyboardRemove())
        send_main_menu(user_id)
    except Exception:
        pass


def service_title(key):
    return SERVICES.get(key, {}).get("title", key)


# =========================================================
#                          /start
# =========================================================

@bot.message_handler(commands=["start"])
def handle_start(message):
    uid = message.from_user.id
    if is_banned(uid):
        return  # игнорируем спам забаненных

    payload = message.text.split(maxsplit=1)
    referred_by = None
    if len(payload) > 1 and payload[1].startswith("ref_"):
        try:
            ref_id = int(payload[1].replace("ref_", ""))
            if ref_id != uid:
                referred_by = ref_id
        except ValueError:
            pass

    ensure_user(uid, message.from_user.username, message.from_user.full_name, referred_by)
    clear_state(uid)
    send_main_menu(message.chat.id)


# =========================================================
#             ВЫБОР УСЛУГИ (reply-клавиатура)
# =========================================================

@bot.message_handler(func=lambda m: m.text in SERVICE_BUTTONS)
def handle_service_choice(message):
    uid = message.from_user.id
    if is_banned(uid):
        return
    service_key = SERVICE_KEY_BY_LABEL[message.text]
    start_service_flow(message.chat.id, uid, service_key)


def start_service_flow(chat_id, uid, service_key):
    user_states[uid] = {"action": "svc", "service": service_key, "step": 0, "answers": {}}
    bot.send_message(chat_id, "⏳ Загружаю бриф...", reply_markup=types.ReplyKeyboardRemove())
    send_step(chat_id, uid)


def send_step(chat_id, uid):
    st = user_states.get(uid)
    if not st or st["action"] != "svc":
        return
    service = SERVICES[st["service"]]
    step = service["steps"][st["step"]]
    kb = step_kb(st["service"], st["step"], step.get("options"))
    bot.send_message(chat_id, step["text"], reply_markup=kb)


def advance_step(chat_id, uid):
    st = user_states.get(uid)
    if not st:
        return
    st["step"] += 1
    service = SERVICES[st["service"]]
    if st["step"] >= len(service["steps"]):
        finish_service_flow(chat_id, uid)
    else:
        send_step(chat_id, uid)


def finish_service_flow(chat_id, uid):
    st = user_states.get(uid)
    if not st:
        return
    service_key = st["service"]
    answers = st["answers"]
    service = SERVICES[service_key]
    lines = [f"{service['steps'][i]['text'].split('<')[0].strip()}: {answers.get(service['steps'][i]['key'], '-')}"
             for i in range(len(service["steps"]))]
    answers_text = "\n".join(lines)

    urow = get_user(uid)
    referred_by = urow["referred_by"] if urow else None
    app_id = add_application(uid, service_key, answers_text, referred_by)

    clear_state(uid)
    bot.send_message(chat_id, SUCCESS_TEXT, reply_markup=main_reply_kb())
    bot.send_message(chat_id, "🤝 Хотите зарабатывать вместе с нами? Подключайтесь к партнёрской программе:",
                      reply_markup=partner_intro_kb())

    notify_new_application(app_id)


def notify_new_application(app_id):
    app = get_application(app_id)
    if not app:
        return
    client = get_user(app["client_id"])
    client_name = display_name(client)
    dt = app["created_at"][:16]

    if app["referred_by"]:
        ref_user = get_user(app["referred_by"])
        source = f"⚠️ Приведен арбитражником: {display_name(ref_user)} [ID: {app['referred_by']}]"
    else:
        source = "🌐 Органический трафик / Из поиска"

    text = (
        f"🔥 НОВАЯ ЗАЯВКА НА УСЛУГУ | GOLDEN HOUSE [{dt}]\n\n"
        f"Клиент: {client_name} [ID: {app['client_id']}]\n\n"
        f"📝 Ответы на вопросы брифа:\n"
        f"Какая услуга: {service_title(app['service'])}\n{app['answers_text']}\n\n"
        f"Источник трафика:\n{source}\n\n"
        f"👇 Действия с заявкой:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Закрыть сделку", callback_data=f"app:close:{app_id}"))
    kb.add(types.InlineKeyboardButton("🚫 Отказ/спам", callback_data=f"app:reject:{app_id}"))
    kb.add(types.InlineKeyboardButton("🔙 В меню", callback_data="app:tomenu"))

    for admin_id in all_admin_ids():
        try:
            bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            pass


# =========================================================
#         CALLBACK: "назад" на первом шаге брифа
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "back:main")
def cb_back_main(call):
    uid = call.from_user.id
    clear_state(uid)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, "Возвращаемся в главное меню 👇", reply_markup=main_reply_kb())
    bot.answer_callback_query(call.id)


# =========================================================
#           CALLBACK: ответ кнопкой на шаге брифа
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("ans:"))
def cb_answer_button(call):
    uid = call.from_user.id
    if is_banned(uid):
        bot.answer_callback_query(call.id)
        return
    _, service_key, step_idx, opt_idx = call.data.split(":")
    step_idx = int(step_idx)
    opt_idx = int(opt_idx)

    st = user_states.get(uid)
    if not st or st["action"] != "svc" or st["service"] != service_key or st["step"] != step_idx:
        bot.answer_callback_query(call.id, "Этот шаг уже неактуален")
        return

    step = SERVICES[service_key]["steps"][step_idx]
    chosen = step["options"][opt_idx]
    st["answers"][step["key"]] = chosen

    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.answer_callback_query(call.id, f"Выбрано: {chosen}")
    advance_step(call.message.chat.id, uid)


# =========================================================
#         ПАРТНЁРСКАЯ ПРОГРАММА
# =========================================================

@bot.callback_query_handler(func=lambda c: c.data == "partner:intro")
def cb_partner_intro(call):
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, PARTNER_INTRO_TEXT, reply_markup=get_link_kb())


def build_cabinet_text(uid):
    urow = get_user(uid)
    ensure_partner(uid)
    prow = get_partner(uid)
    leads = prow["leads_this_week"]
    percent = get_percent(leads)
    next_percent, left, _ = next_level_info(leads)
    global BOT_USERNAME
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"

    text = (
        "💼 Личный кабинет партнера | Golden House\n"
        f"👤 Аккаунт: {display_name(urow)}\n"
        f"🆔 Ваш ID: {uid}\n\n"
        f"📊 Статистика за текущую неделю:\n"
        f"Приведено покупателей: {leads} шт.\n"
        f"Текущая ставка: {percent}% от маржи\n\n"
        f"🔥📈 До следующего уровня ({next_percent}%) осталось привести: {left} лид(ов).\n\n"
        f"💰 Финансовый баланс:\n"
        f"Доступно к выводу: {prow['balance']} ₽\n"
        f"Выплачено за всё время: {prow['total_paid']} ₽\n\n"
        f"🔗 Твоя реферальная ссылка:\n{link}\n"
        f"(Нажми на ссылку, чтобы скопировать. Направляй по ней клиентов!)"
    )
    return text


@bot.callback_query_handler(func=lambda c: c.data == "partner:cabinet")
def cb_partner_cabinet(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    ensure_partner(uid)
    bot.send_message(call.message.chat.id, build_cabinet_text(uid), reply_markup=partner_cabinet_kb())


@bot.callback_query_handler(func=lambda c: c.data == "partner:refresh")
def cb_partner_refresh(call):
    uid = call.from_user.id
    try:
        bot.edit_message_text(build_cabinet_text(uid), call.message.chat.id, call.message.message_id,
                               reply_markup=partner_cabinet_kb())
    except Exception:
        pass
    bot.answer_callback_query(call.id, "Обновлено")


@bot.callback_query_handler(func=lambda c: c.data == "partner:menu")
def cb_partner_to_menu(call):
    uid = call.from_user.id
    bot.answer_callback_query(call.id)
    clear_state(uid)
    bot.send_message(call.message.chat.id, "Главное меню 👇", reply_markup=main_reply_kb())


@bot.callback_query_handler(func=lambda c: c.data == "partner:withdraw")
def cb_partner_withdraw(call):
    uid = call.from_user.id
    ensure_partner(uid)
    prow = get_partner(uid)
    bot.answer_callback_query(call.id)
    if prow["balance"] < MIN_WITHDRAW:
        msg = bot.send_message(call.message.chat.id,
                                f"У Вас недостаточно средств для вывода! Минимальная сумма вывода {MIN_WITHDRAW}₽")
        threading.Thread(target=delete_later, args=(call.message.chat.id, msg.message_id, 15), daemon=True).start()
        return
    user_states[uid] = {"action": "partner_withdraw"}
    bot.send_message(call.message.chat.id,
                      "Отправьте реквизиты для вывода средств:\n"
                      "👤 ФИО получателя\n🪙 Банк\n💳 Номер карты/телефона\n💵 Сумма вывода\n\n"
                      "Отправьте данные в одном сообщение!")


def delete_later(chat_id, message_id, seconds):
    time.sleep(seconds)
    try:
        bot.delete_message(chat_id, message_id)
    except Exception:
        pass


# =========================================================
#         ОБЩИЙ ОБРАБОТЧИК ТЕКСТА (диспетчер по состояниям)
# =========================================================

@bot.message_handler(content_types=["text"])
def handle_text(message):
    uid = message.from_user.id
    if is_banned(uid):
        return  # полный игнор

    st = user_states.get(uid)
    if not st:
        return  # нет активного диалога - ничего не делаем

    action = st["action"]

    # ---------- Бриф услуги (текстовый шаг) ----------
    if action == "svc":
        service = SERVICES[st["service"]]
        step = service["steps"][st["step"]]
        if step["type"] != "text":
            return
        st["answers"][step["key"]] = message.text
        advance_step(message.chat.id, uid)
        return

    # ---------- Вывод профита партнёра ----------
    if action == "partner_withdraw":
        ensure_partner(uid)
        prow = get_partner(uid)
        add_bank_data(uid, message.text)
        pay_id = add_payment_request(uid, get_user(uid)["full_name"] or "", "", "", prow["balance"])
        with db_lock:
            conn = get_conn()
            conn.execute("UPDATE payments SET bank=?, card=?, full_name=? WHERE id=?",
                         (message.text, message.text, message.text, pay_id))
            conn.commit()
            conn.close()
        clear_state(uid)
        bot.send_message(message.chat.id,
                          "✅ Заявка успешно принята и отправлена на обработку! Наш финансовый отдел проверит "
                          "данные и произведет выплату в течение 24 часов. Вы получите уведомление от бота, "
                          "как только средства будут отправлены. Спасибо за работу с Golden House!",
                          reply_markup=main_reply_kb())
        notify_payout_request(pay_id)
        return

    # ---------- АДМИНСКИЕ СОСТОЯНИЯ ----------
    if action.startswith("admin_") and is_admin_or_owner(uid):
        handle_admin_text(message, st)
        return


def notify_payout_request(pay_id):
    pay = get_payment(pay_id)
    urow = get_user(pay["user_id"])
    prow = get_partner(pay["user_id"])
    text = (
        "⚠️ НОВАЯ ЗАЯВКА НА ВЫПЛАТУ | GOLDEN HOUSE\n\n"
        f"👤 Арбитражник: {display_name(urow)}, ID пользователя: {pay['user_id']}\n"
        f"💰 Текущий баланс в базе: {prow['balance']} ₽\n\n"
        f"📝 Реквизиты получателя (текст от пользователя):\n{pay['card']}\n\n"
        f"Сумма к выводу (весь доступный баланс на момент заявки): {pay['amount']} ₽\n\n"
        f"👇 Управление заявкой:"
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("✅ Выплачено (Списать баланс)", callback_data=f"pay:paid:{pay_id}"))
    kb.add(types.InlineKeyboardButton("❌ Отклонить заявку", callback_data=f"pay:reject:{pay_id}"))
    for admin_id in all_admin_ids():
        try:
            bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            pass


# =========================================================
#                      /admin
# =========================================================

@bot.message_handler(commands=["admin"])
def handle_admin_cmd(message):
    uid = message.from_user.id
    if is_banned(uid):
        return
    if not is_admin_or_owner(uid):
        return  # полный игнор для не-админов
    clear_state(uid)
    send_admin_panel(message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data == "adm:menu")
def cb_admin_menu(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    clear_state(uid)
    bot.answer_callback_query(call.id)
    send_admin_panel(call.message.chat.id, call.message.message_id)


# --------------------- Блокировка ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:block")
def cb_admin_block(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_block"}
    try:
        bot.edit_message_text("Отправьте ID", call.message.chat.id, call.message.message_id,
                               reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "Отправьте ID", reply_markup=back_admin_kb())


# --------------------- Разблокировка ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:unblock")
def cb_admin_unblock(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_unblock"}
    try:
        bot.edit_message_text("Отправьте ID", call.message.chat.id, call.message.message_id,
                               reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "Отправьте ID", reply_markup=back_admin_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:unblock_yes:"))
def cb_unblock_yes(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    target_id = int(call.data.split(":")[2])
    set_ban(target_id, False)
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("Пользователь разблокирован✅", call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    notify_unban(target_id)
    send_admin_panel(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:unblock_no:"))
def cb_unblock_no(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    clear_state(uid)
    send_admin_panel(call.message.chat.id, call.message.message_id)


# --------------------- Назначение админа ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:addadmin")
def cb_admin_addadmin(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_addadmin"}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="adm:menu"))
    try:
        bot.edit_message_text("Отправьте ID", call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, "Отправьте ID", reply_markup=kb)


# --------------------- Разжалование ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:rmadmin_list")
def cb_admin_rmadmin_list(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    if not is_owner(uid):
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "🚫 У вас недостаточно прав на использование данной функции")
        return
    bot.answer_callback_query(call.id)
    admins = list_admins()
    if not admins:
        try:
            bot.edit_message_text("Список администраторов пуст.", call.message.chat.id, call.message.message_id,
                                   reply_markup=back_admin_kb())
        except Exception:
            pass
        return
    lines = ["👥 Управление администраторами Golden House. Ниже приведен список действующих администраторов бота. "
             "Нажмите на кнопку с именем пользователя, чтобы лишить его прав администратора.\n"]
    kb = types.InlineKeyboardMarkup()
    for i, a in enumerate(admins, 1):
        lines.append(f"{i}. {display_name(a)} {a['user_id']} 📅 Добавлен: {a['admin_added_at']}")
        kb.add(types.InlineKeyboardButton(f"Разжаловать {display_name(a)}", callback_data=f"adm:rmadmin:{a['user_id']}"))
    lines.append("\n👇 Выберите администратора для разжалования:")
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="adm:menu"))
    text = "\n".join(lines)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:rmadmin:"))
def cb_admin_rmadmin(call):
    uid = call.from_user.id
    if not is_owner(uid):
        bot.answer_callback_query(call.id)
        bot.send_message(uid, "🚫 У вас недостаточно прав на использование данной функции")
        return
    target_id = int(call.data.split(":")[2])
    target = get_user(target_id)
    remove_admin(target_id)
    bot.answer_callback_query(call.id)
    text = (
        "✅ Администратор успешно разжалован. Пользователь удален из базы данных и больше не имеет доступа "
        "к админ-панели.\n\n"
        f"👤 Пользователь: {display_name(target)} {target_id}\n"
        f"📄 Статус: Права отозваны"
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=back_admin_kb())
    try:
        bot.send_message(target_id,
                          "🚫 Ваш статус администратора аннулирован Вы были удалены из списка администраторов "
                          "бота Golden House.🔐 Доступ к админ-панели /admin и всем управляющим функциям для "
                          "вашего аккаунта полностью закрыт.")
    except Exception:
        pass


# --------------------- Общая статистика ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:stats")
def cb_admin_stats(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    with db_lock:
        conn = get_conn()
        total_users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) c FROM users WHERE is_banned=1").fetchone()["c"]
        active_apps = conn.execute("SELECT COUNT(*) c FROM applications WHERE app_status='pending'").fetchone()["c"]
        closed_apps = conn.execute("SELECT COUNT(*) c FROM applications WHERE app_status='closed'").fetchone()["c"]
        total_paid = conn.execute("SELECT COALESCE(SUM(total_paid),0) s FROM partners").fetchone()["s"]
        conn.close()
    text = (
        "📈 Статистика агентства Golden House\n"
        "👥 Пользователи:\n"
        f"Всего пользователей в боте: {total_users} чел.\n\n"
        "💼 Сделки и Продажи:\n"
        f"Активных заявок в работе: {active_apps}\n"
        f"Успешно закрытых сделок: {closed_apps}\n"
        f"Заблокированных пользователей: {banned}\n"
        f"Выплачено арбитражникам: {total_paid} ₽\n\n"
        "🔄 Данные актуальны на текущую секунду."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 в меню", callback_data="adm:menu"))
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb)


# --------------------- Обновить статистику арбитражнику ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:updpartner")
def cb_admin_updpartner(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_updpartner_id"}
    try:
        bot.edit_message_text("Отправьте ID пользователя", call.message.chat.id, call.message.message_id,
                               reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "Отправьте ID пользователя", reply_markup=back_admin_kb())


def partner_action_kb(pid):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📊 Показать статистику", callback_data=f"adm:pshow:{pid}"))
    kb.add(types.InlineKeyboardButton("Начислить баланс", callback_data=f"adm:paccrue:{pid}"))
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="adm:menu"))
    return kb


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:pshow:"))
def cb_admin_pshow(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    pid = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    ensure_partner(pid)
    text = build_cabinet_text(pid)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data=f"adm:pback:{pid}"))
    bot.send_message(call.message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:pback:"))
def cb_admin_pback(call):
    uid = call.from_user.id
    pid = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("Выберите действие", call.message.chat.id, call.message.message_id,
                               reply_markup=partner_action_kb(pid))
    except Exception:
        bot.send_message(call.message.chat.id, "Выберите действие", reply_markup=partner_action_kb(pid))


@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:paccrue:"))
def cb_admin_paccrue(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    pid = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_paccrue_amount", "partner_id": pid}
    bot.send_message(call.message.chat.id, "Введите сумму сделки без ₽")


# --------------------- Заявки на выплаты ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:payouts")
def cb_admin_payouts(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    with db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM payments WHERE status='pending' ORDER BY created_at DESC").fetchall()
        conn.close()
    if not rows:
        bot.send_message(call.message.chat.id, "Заявок на выплату пока нет.", reply_markup=back_admin_kb())
        return
    for pay in rows:
        urow = get_user(pay["user_id"])
        prow = get_partner(pay["user_id"])
        text = (
            "⚠️ НОВАЯ ЗАЯВКА НА ВЫПЛАТУ | GOLDEN HOUSE\n\n"
            f"👤 Арбитражник: {display_name(urow)}, ID пользователя: {pay['user_id']}\n"
            f"💰 Текущий баланс в базе: {prow['balance'] if prow else 0} ₽\n\n"
            f"📝 Реквизиты получателя:\n{pay['card']}\n\n"
            f"Сумма к выводу: {pay['amount']}₽\n\n"
            f"👇 Управление заявкой:"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Выплачено (Списать баланс)", callback_data=f"pay:paid:{pay['id']}"))
        kb.add(types.InlineKeyboardButton("❌ Отклонить заявку", callback_data=f"pay:reject:{pay['id']}"))
        bot.send_message(call.message.chat.id, text, reply_markup=kb)
    bot.send_message(call.message.chat.id, "Это все актуальные заявки.", reply_markup=back_admin_kb())


@bot.callback_query_handler(func=lambda c: c.data.startswith("pay:paid:"))
def cb_pay_paid(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    pay_id = int(call.data.split(":")[2])
    pay = get_payment(pay_id)
    if not pay or pay["status"] != "pending":
        bot.answer_callback_query(call.id, "Заявка уже обработана")
        return
    withdraw_balance(pay["user_id"], pay["amount"])
    set_payment_status(pay_id, "paid")
    bot.answer_callback_query(call.id, "Выплата подтверждена")
    try:
        bot.edit_message_text(call.message.text + "\n\n✅ ВЫПЛАЧЕНО", call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    try:
        bot.send_message(pay["user_id"], f"✅ Ваша выплата {pay['amount']}₽ произведена. Спасибо за работу с Golden House!")
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("pay:reject:"))
def cb_pay_reject(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    pay_id = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_pay_reject_reason", "pay_id": pay_id}
    bot.send_message(call.message.chat.id, "Укажите причину отклонения заявки (например, неверные реквизиты):")


# --------------------- Рассылки ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:broadcast")
def cb_admin_broadcast(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_broadcast_id"}
    try:
        bot.edit_message_text("Введите ID", call.message.chat.id, call.message.message_id, reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "Введите ID", reply_markup=back_admin_kb())


@bot.callback_query_handler(func=lambda c: c.data == "adm:massbroadcast")
def cb_admin_massbroadcast(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_massbroadcast"}
    try:
        bot.edit_message_text("Введите сообщение для массовой рассылки", call.message.chat.id, call.message.message_id,
                               reply_markup=back_admin_kb())
    except Exception:
        bot.send_message(call.message.chat.id, "Введите сообщение для массовой рассылки", reply_markup=back_admin_kb())


# --------------------- Заявки услуг (поиск) ---------------------

@bot.callback_query_handler(func=lambda c: c.data == "adm:appssearch")
def cb_admin_appssearch(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    bot.answer_callback_query(call.id)
    user_states[uid] = {"action": "admin_appssearch"}
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 назад", callback_data="adm:menu"))
    text = ("Выберите дату и услугу или можете отправить ID заказчика и я найду заявку с его ID\n\n"
            "Форматы сообщения:\n"
            "• ГГГГ-ММ-ДД — все заявки за дату\n"
            "• ID — все заявки клиента\n"
            "• ГГГГ-ММ-ДД услуга ID — комбинированный поиск (услуга: web/bot/ref/seo)")
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "app:tomenu")
def cb_app_tomenu(call):
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("app:close:"))
def cb_app_close(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    app_id = int(call.data.split(":")[2])
    set_application_status(app_id, "closed")
    bot.answer_callback_query(call.id, "Сделка закрыта")
    send_admin_panel(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("app:reject:"))
def cb_app_reject(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    app_id = int(call.data.split(":")[2])
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Подтверждаю ✅", callback_data=f"app:rejyes:{app_id}"))
    kb.add(types.InlineKeyboardButton("Отменить отказ 🚫", callback_data=f"app:rejno:{app_id}"))
    bot.send_message(call.message.chat.id, "Подтвердите отказ заявки", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("app:rejyes:"))
def cb_app_rejyes(call):
    uid = call.from_user.id
    if not is_admin_or_owner(uid):
        bot.answer_callback_query(call.id)
        return
    app_id = int(call.data.split(":")[2])
    set_application_status(app_id, "rejected")
    bot.answer_callback_query(call.id)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔙 в меню", callback_data="adm:menu"))
    try:
        bot.edit_message_text("Отказ принят", call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(call.message.chat.id, "Отказ принят", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("app:rejno:"))
def cb_app_rejno(call):
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


# =========================================================
#          ТЕКСТОВЫЙ ДИСПЕТЧЕР ДЛЯ АДМИНСКИХ ДЕЙСТВИЙ
# =========================================================

def handle_admin_text(message, st):
    uid = message.from_user.id
    action = st["action"]
    text = message.text.strip()

    # ---------- Блокировка ----------
    if action == "admin_block":
        if not text.isdigit():
            bot.send_message(message.chat.id, "ID должен быть числом. Попробуйте ещё раз.")
            return
        target_id = int(text)
        set_ban(target_id, True, by_id=uid)
        clear_state(uid)
        bot.send_message(message.chat.id, f"Пользователь [{target_id}] заблокирован в данном боте",
                          reply_markup=back_admin_kb())
        notify_ban(target_id)
        return

    # ---------- Разблокировка ----------
    if action == "admin_unblock":
        if not text.isdigit():
            bot.send_message(message.chat.id, "ID должен быть числом. Попробуйте ещё раз.")
            return
        target_id = int(text)
        row = get_user(target_id)
        clear_state(uid)
        if not row or row["is_banned"] != 1:
            bot.send_message(message.chat.id, "Этот пользователь не найден в списке заблокированных.",
                              reply_markup=back_admin_kb())
            return
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("Да", callback_data=f"adm:unblock_yes:{target_id}"))
        kb.add(types.InlineKeyboardButton("нет", callback_data=f"adm:unblock_no:{target_id}"))
        by = row["banned_by"] or "неизвестен"
        bot.send_message(message.chat.id,
                          f"Данный пользователь был заблокирован администратором [{by}]\n"
                          f"Вы подтверждаете разблокировку пользователя [{target_id}]?",
                          reply_markup=kb)
        return

    # ---------- Назначение админа ----------
    if action == "admin_addadmin":
        if not text.isdigit():
            bot.send_message(message.chat.id, "ID должен быть числом. Попробуйте ещё раз.")
            return
        target_id = int(text)
        row = get_user(target_id)
        clear_state(uid)
        if not row:
            bot.send_message(message.chat.id, "Я не нашёл данного пользователя в базе данных",
                              reply_markup=back_admin_kb())
            return
        make_admin(target_id, uid)
        bot.send_message(message.chat.id, f"Новый администратор [{target_id}] добавлен администратором [{uid}]",
                          reply_markup=back_admin_kb())
        try:
            bot.send_message(target_id,
                              "🎉 Добро пожаловать в админ-команду Golden House! Вас успешно назначили новым "
                              "администратором этого бота. Права уже активны.\n\n🚀 Запустить панель "
                              "администратора: /admin")
        except Exception:
            pass
        return

    # ---------- Обновление статистики арбитражнику: ввод ID ----------
    if action == "admin_updpartner_id":
        if not text.isdigit():
            bot.send_message(message.chat.id, "ID должен быть числом. Попробуйте ещё раз.")
            return
        pid = int(text)
        row = get_user(pid)
        clear_state(uid)
        if not row:
            bot.send_message(message.chat.id, "Я не нашёл данного пользователя в базе данных",
                              reply_markup=back_admin_kb())
            return
        ensure_partner(pid)
        bot.send_message(message.chat.id, "Выберите действие", reply_markup=partner_action_kb(pid))
        return

    # ---------- Начисление баланса: сумма сделки ----------
    if action == "admin_paccrue_amount":
        pid = st["partner_id"]
        try:
            amount = float(text.replace(",", ".").replace(" ", ""))
        except ValueError:
            bot.send_message(message.chat.id, "Введите сумму числом, например 20000")
            return
        percent, profit, leads = accrue_deal(pid, amount)
        clear_state(uid)
        bot.send_message(message.chat.id,
                          f"Начислено. Ставка {percent}%, профит {profit}₽, лидов на неделе: {leads}",
                          reply_markup=back_admin_kb())
        try:
            bot.send_message(pid,
                              f"🔥 Сделка с лидом завершена! Сумма сделки {amount}₽. Ваш профит {profit}₽!")
        except Exception:
            pass
        if leads == 15:
            try:
                bot.send_message(pid,
                                  f"Поздравляем🔥 Вы достигли максимального уровня лидов за НЕДЕЛЮ! "
                                  f"Вы привели за неделю {leads} лид(ов). Ваша текущая ставка за лида 30% "
                                  f"держите её дальше чтобы не потерять профит!")
            except Exception:
                pass
        return

    # ---------- Отклонение заявки на выплату: причина ----------
    if action == "admin_pay_reject_reason":
        pay_id = st["pay_id"]
        pay = get_payment(pay_id)
        clear_state(uid)
        if pay and pay["status"] == "pending":
            set_payment_status(pay_id, "rejected")
            bot.send_message(message.chat.id, "Заявка отклонена.", reply_markup=back_admin_kb())
            try:
                bot.send_message(pay["user_id"], f"❌ Ваша заявка на выплату отклонена.\nПричина: {text}")
            except Exception:
                pass
        else:
            bot.send_message(message.chat.id, "Заявка уже обработана.", reply_markup=back_admin_kb())
        return

    # ---------- Рассылка одному ----------
    if action == "admin_broadcast_id":
        if not text.isdigit():
            bot.send_message(message.chat.id, "ID должен быть числом. Попробуйте ещё раз.")
            return
        target_id = int(text)
        row = get_user(target_id)
        if not row:
            clear_state(uid)
            bot.send_message(message.chat.id, "Я не нашёл данного пользователя в базе данных",
                              reply_markup=back_admin_kb())
            return
        user_states[uid] = {"action": "admin_broadcast_msg", "target_id": target_id}
        bot.send_message(message.chat.id, "Напишите сообщение")
        return

    if action == "admin_broadcast_msg":
        target_id = st["target_id"]
        clear_state(uid)
        try:
            bot.send_message(target_id, f"📨 Вам отправлено сообщение от администрации Golden House\n\n{text}")
            bot.send_message(message.chat.id, "Сообщение отправлено.", reply_markup=back_admin_kb())
        except Exception:
            bot.send_message(message.chat.id, "Не удалось отправить сообщение этому пользователю.",
                              reply_markup=back_admin_kb())
        return

    # ---------- Массовая рассылка ----------
    if action == "admin_massbroadcast":
        clear_state(uid)
        ids = all_active_users()
        sent = 0
        for user_id in ids:
            try:
                bot.send_message(user_id, text)
                sent += 1
            except Exception:
                pass
        bot.send_message(message.chat.id, f"Массовая рассылка завершена. Отправлено: {sent}/{len(ids)}",
                          reply_markup=back_admin_kb())
        return

    # ---------- Поиск заявок услуг ----------
    if action == "admin_appssearch":
        parts = text.split()
        date_str = None
        service_key = None
        client_id = None
        for p in parts:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", p):
                date_str = p
            elif p in SERVICES:
                service_key = p
            elif p.isdigit():
                client_id = int(p)

        results = search_applications(date_str, service_key, client_id)
        if not results:
            bot.send_message(message.chat.id, "Заявок по вашему запросу не найдено.", reply_markup=back_admin_kb())
            return
        for app in results:
            client = get_user(app["client_id"])
            text_out = (
                f"Заявка #{app['id']} от {app['created_at']}\n"
                f"Клиент: {display_name(client)} [{app['client_id']}]\n"
                f"Услуга: {service_title(app['service'])}\n"
                f"Статус: {app['app_status']}\n\n"
                f"{app['answers_text']}"
            )
            bot.send_message(message.chat.id, text_out)
        bot.send_message(message.chat.id, "Это все найденные заявки.", reply_markup=back_admin_kb())
        clear_state(uid)
        return


# =========================================================
#            ФОНОВЫЙ ПОТОК: ЕЖЕНЕДЕЛЬНЫЙ СБРОС СТАВОК
# =========================================================
# Сброс происходит каждый понедельник в 00:00 по МСК

def weekly_reset_worker():
    while True:
        try:
            now = msk_now()
            today_str = now.strftime("%Y-%m-%d")
            last_reset = get_setting("last_reset_date")
            if now.weekday() == 0 and last_reset != today_str:  # Monday
                reset_all_weeks()
                set_setting("last_reset_date", today_str)
        except Exception:
            pass
        time.sleep(60)


# =========================================================
#                          MAIN
# =========================================================

def main():
    global BOT_USERNAME
    init_db()
    me = bot.get_me()
    BOT_USERNAME = me.username
    threading.Thread(target=weekly_reset_worker, daemon=True).start()
    print("Golden House bot запущен как @%s" % BOT_USERNAME)
    bot.infinity_polling(skip_pending=True, timeout=60)


if __name__ == "__main__":
    main()
