# -*- coding: utf-8 -*-
"""
OLD SERIAL SHOP BOT  (Telegram, Python, python-telegram-bot v21+)

Features
  * User menu: Buy Old Serial, Add Balance, My Orders, My Balance, Refer & Earn,
    Watch Ad, Digital Time, Id, Help
  * Categories -> product list (Next/Back pages) -> product card (Buy Now / Next / Back)
  * PRODUCT STOCK SYSTEM: every product has its own stock (serials / accounts /
    codes). Buy Now takes one item from stock and delivers it instantly.
    Products can also be switched to "manual delivery" (unlimited, admin delivers).
  * Deposits: bKash / Nagad / Rocket / Binance -> amount -> TrxID -> admin approves
  * Admin panel (/admin) - everything can be changed from the panel
  * Colorful buttons (Telegram button styles: blue / green / red)

Run:
    pip install -U "python-telegram-bot[job-queue]"
    export BOT_TOKEN="123456:ABC..."
    export ADMIN_IDS="123456789"        # comma separated
    python bot.py
"""
import asyncio
import csv
import html
import io
import logging
import os
import sqlite3
import time
import datetime as dt
from zoneinfo import ZoneInfo

from telegram import (BotCommand, InlineKeyboardButton as IB, InlineKeyboardMarkup as IM,
                      KeyboardButton as KB, ReplyKeyboardMarkup as RM, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ----------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "9290718275:AAETrFImykSK8sfF5CzTlKyKYEFqpoFD0Zk")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "1686274364").replace(" ", "1686274364").split(",") if x.strip().lstrip("-").isdigit()]
DB_FILE = os.getenv("DB_FILE", "shop.db")
TZ = ZoneInfo("Asia/Dhaka")
NATIVE_COLORS = True      # Telegram button styles (needs an up-to-date Telegram app)

HTML = ParseMode.HTML
START_TS = time.time()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("shop")

METHODS = {"bkash": ("🅱️", "bKash"), "nagad": ("🟠", "Nagad"),
           "rocket": ("🚀", "Rocket"), "binance": ("🟡", "Binance")}

DEFAULTS = {
    "shop_name": "Old Serial Bot", "help_contact": "@your_support",
    "welcome_text": ("👋 <b>{shop}</b> এ আপনাকে স্বাগতম। কোন সমস্যা হলে যোগাযোগ করবেন : {contact}\n"
                     "—ধন্যবাদ\n\n"
                     "<b>যেভাবে ব্যালেন্স এড করবেন</b> 💳\n"
                     "└ 💰 Add Balance এ ক্লিক করুন\n"
                     "└ 🇧🇩 BDT / 💵 Crypto সিলেক্ট করুন\n"
                     "└ Amount দিন → Confirm Payment → TrxID দিন\n\n"
                     "<b>যেভাবে Serial নিবেন</b> 🎁\n"
                     "└ 🛒 Buy Old Serial এ ক্লিক করুন\n"
                     "└ Serial Name সিলেক্ট করুন\n"
                     "└ Buy Now এ ক্লিক করুন"),
    "welcome_bonus": "10", "refer_bonus": "2", "refer_percent": "10",
    "min_deposit": "50", "amounts": "50,60,70,80,100",
    "channel": "", "channel_on": "0", "log_channel": "", "log_on": "0",
    "refer_protect": "1", "phone_on": "0", "autopost": "0", "notify_new": "0",
    "product_note": "", "low_stock": "3", "per_page": "6",
    "pay_bkash_num": "", "pay_bkash_on": "1", "pay_nagad_num": "", "pay_nagad_on": "1",
    "pay_rocket_num": "", "pay_rocket_on": "1", "pay_binance_num": "", "pay_binance_on": "1",
    "ad_text": "", "ad_url": "", "ad_reward": "0.5", "ad_seconds": "10", "ad_daily": "5",
    "autofix_last": "Never run", "autofix_runs": "0",
}

MENU_LABELS = {"buy": "🛒 Buy Old Serial", "addbal": "💰 Add Balance", "orders": "📦 My Orders",
               "bal": "💳 My Balance", "refer": "👥 Refer & Earn", "ad": "📺 Watch Ad",
               "time": "🕐 Digital Time", "id": "🆔 Id", "help": "🆘 Help"}

# ----------------------------------------------------------------------------
# DATABASE
# ----------------------------------------------------------------------------
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, username TEXT, name TEXT,
  balance REAL DEFAULT 0, refer_balance REAL DEFAULT 0, ref_by INTEGER DEFAULT 0,
  refer_paid INTEGER DEFAULT 0, bonus_given INTEGER DEFAULT 0, total_spent REAL DEFAULT 0,
  total_orders INTEGER DEFAULT 0, banned INTEGER DEFAULT 0, ads_lock INTEGER DEFAULT 0,
  blocked_bot INTEGER DEFAULT 0, phone TEXT DEFAULT '', joined INTEGER, last_active INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS labels(key TEXT PRIMARY KEY, text TEXT);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, cat_id INTEGER, name TEXT,
  price REAL, image TEXT DEFAULT '', active INTEGER DEFAULT 1, track INTEGER DEFAULT 1, added INTEGER);
CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY AUTOINCREMENT, pid INTEGER, data TEXT,
  added INTEGER, sold INTEGER DEFAULT 0, order_id INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_stock ON stock(pid, sold);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, pid INTEGER,
  name TEXT, price REAL, status TEXT DEFAULT 'pending', details TEXT DEFAULT '',
  created INTEGER, delivered INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, method TEXT,
  amount REAL, trx TEXT DEFAULT '', status TEXT DEFAULT 'created', created INTEGER, decided INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS ad_views(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, ts INTEGER, reward REAL);
""")
db.commit()


def run(sql, args=()):
    cur = db.execute(sql, args)
    db.commit()
    return cur


def one(sql, args=()):
    return db.execute(sql, args).fetchone()


def all_(sql, args=()):
    return db.execute(sql, args).fetchall()


def cnt(sql, args=()):
    return one(sql, args)[0]


def S(k):
    r = one("SELECT value FROM settings WHERE key=?", (k,))
    return r["value"] if r else DEFAULTS.get(k, "")


def Sf(k):
    try:
        return float(S(k))
    except ValueError:
        return 0.0


def setS(k, v):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


def label(k):
    r = one("SELECT text FROM labels WHERE key=?", (k,))
    return r["text"] if r else MENU_LABELS[k]


def user(uid):
    return one("SELECT * FROM users WHERE uid=?", (uid,))


# ----------------------------------------------------------------------------
# SMALL HELPERS
# ----------------------------------------------------------------------------
def now():
    return int(time.time())


def per_page():
    try:
        return max(3, min(20, int(Sf("per_page"))))
    except ValueError:
        return 6


def esc(x):
    return html.escape(str(x if x is not None else ""))


def money(x):
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.2f}"


def dts(ts, fmt="%Y-%m-%d %H:%M"):
    return dt.datetime.fromtimestamp(ts, TZ).strftime(fmt) if ts else "-"


def chat_ref(x):
    x = str(x).strip()
    return int(x) if x.lstrip("-").isdigit() else x


def is_admin(uid):
    return uid in ADMIN_IDS


CYCLE = ["primary", "success", "danger"]   # blue, green, red


def ib(text, data=None, style=None, url=None):
    kw = {"style": style} if (NATIVE_COLORS and style) else None
    return IB(text, callback_data=data, url=url, api_kwargs=kw)


def kb(text, style=None, **kw):
    ak = {"style": style} if (NATIVE_COLORS and style) else None
    return KB(text, api_kwargs=ak, **kw)


def grid(items, cols=2, offset=0):
    rows, row = [], []
    for i, (t, d) in enumerate(items):
        row.append(ib(t, d, CYCLE[(i + offset) % 3]))
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def chunks(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)]


async def send(ctx, chat, text, markup=None, photo=None):
    try:
        if photo:
            try:
                return await ctx.bot.send_photo(chat, photo, caption=text[:1024], parse_mode=HTML, reply_markup=markup)
            except BadRequest as e:
                log.warning("photo failed: %s", e)
        return await ctx.bot.send_message(chat, text, parse_mode=HTML, reply_markup=markup)
    except BadRequest as e:
        log.warning("html failed (%s) - resending plain", e)
        return await ctx.bot.send_message(chat, text, reply_markup=markup)


async def say(update, ctx, text, markup=None):
    return await send(ctx, update.effective_chat.id, text, markup)


async def send_long(ctx, chat, text, markup=None):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    for i, p in enumerate(parts):
        await send(ctx, chat, p, markup if i == len(parts) - 1 else None)


async def show(update, ctx, text, markup=None, photo=None):
    """Edit the clicked message when possible, otherwise delete + send a new one."""
    q = update.callback_query
    chat = update.effective_chat.id
    if q:
        m = q.message
        if not photo and m and not getattr(m, "photo", None):
            try:
                await q.edit_message_text(text, parse_mode=HTML, reply_markup=markup)
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
        try:
            if m:
                await m.delete()
        except TelegramError:
            pass
    await send(ctx, chat, text, markup, photo)


async def alert(update, ctx, text):
    q = update.callback_query
    if q:
        try:
            await q.answer(text, show_alert=True)
        except TelegramError:
            pass
        ctx.user_data["_ans"] = True
    else:
        await say(update, ctx, text)


async def notify_user(ctx, uid, text, markup=None):
    try:
        await send(ctx, uid, text, markup)
        return True
    except Forbidden:
        run("UPDATE users SET blocked_bot=1 WHERE uid=?", (uid,))
    except TelegramError as e:
        log.warning("notify %s: %s", uid, e)
    return False


async def notify_admins(ctx, text, markup=None):
    for a in ADMIN_IDS:
        try:
            await send(ctx, a, text, markup)
        except TelegramError as e:
            log.warning("admin notify %s: %s", a, e)


async def tolog(ctx, kind, text):
    run("INSERT INTO logs(ts,kind,text) VALUES(?,?,?)", (now(), kind, text))
    if S("log_on") == "1" and S("log_channel"):
        try:
            await ctx.bot.send_message(chat_ref(S("log_channel")), f"📋 <b>{esc(kind.upper())}</b>\n{esc(text)}", parse_mode=HTML)
        except TelegramError as e:
            log.warning("log channel: %s", e)


# ----------------------------------------------------------------------------
# STOCK HELPERS
# ----------------------------------------------------------------------------
def stock_count(pid):
    return cnt("SELECT COUNT(*) FROM stock WHERE pid=? AND sold=0", (pid,))


def stock_line(p):
    if not p["track"]:
        return "♾ Available (manual delivery)"
    n = stock_count(p["id"])
    return f"✅ In stock: <b>{n}</b>" if n > 0 else "❌ <b>Out of stock</b>"


def add_stock(pid, text):
    """One item per line. If the text has a line '---' the items are split by it instead."""
    lines = text.replace("\r", "").split("\n")
    if any(l.strip() == "---" for l in lines):
        items, cur = [], []
        for l in lines:
            if l.strip() == "---":
                items.append("\n".join(cur).strip())
                cur = []
            else:
                cur.append(l)
        items.append("\n".join(cur).strip())
    else:
        items = [l.strip() for l in lines]
    items = [i for i in items if i]
    have = {r["data"] for r in all_("SELECT data FROM stock WHERE pid=? AND sold=0", (pid,))}
    added = dup = 0
    for it in items:
        if it in have:
            dup += 1
            continue
        have.add(it)
        db.execute("INSERT INTO stock(pid,data,added) VALUES(?,?,?)", (pid, it, now()))
        added += 1
    db.commit()
    return added, dup


# ----------------------------------------------------------------------------
# USER REGISTRATION / GUARD
# ----------------------------------------------------------------------------
async def reg(update, ctx):
    tu = update.effective_user
    u = user(tu.id)
    uname = tu.username or ""
    if not u:
        ref = 0
        args = getattr(ctx, "args", None)
        if args and args[0].startswith("ref") and args[0][3:].isdigit():
            ref = int(args[0][3:])
            if ref == tu.id or not user(ref):
                ref = 0
        run("INSERT INTO users(uid,username,name,joined,last_active,ref_by) VALUES(?,?,?,?,?,?)",
            (tu.id, uname, tu.full_name, now(), now(), ref))
        await tolog(ctx, "join", f"New user {tu.id} @{uname} ({tu.full_name}) ref={ref}")
        if S("refer_protect") != "1":
            await pay_refer(ctx, tu.id)
    else:
        run("UPDATE users SET username=?, name=?, last_active=?, blocked_bot=0 WHERE uid=?",
            (uname, tu.full_name, now(), tu.id))
    return user(tu.id)


async def pay_refer(ctx, uid):
    u = user(uid)
    if not u or not u["ref_by"] or u["refer_paid"]:
        return
    ref = user(u["ref_by"])
    if not ref:
        return
    if S("refer_protect") == "1" and u["phone"] and u["phone"] == ref["phone"]:
        return
    rb = Sf("refer_bonus")
    run("UPDATE users SET refer_paid=1 WHERE uid=?", (uid,))
    run("UPDATE users SET refer_balance=refer_balance+? WHERE uid=?", (rb, ref["uid"]))
    await notify_user(ctx, ref["uid"], f"🎉 New referral joined! +{money(rb)}৳ added to your refer balance.")
    await tolog(ctx, "refer", f"{ref['uid']} earned {money(rb)} from {uid}")


async def first_pass(ctx, u):
    if not u["bonus_given"]:
        wb = Sf("welcome_bonus")
        run("UPDATE users SET bonus_given=1, balance=balance+? WHERE uid=?", (wb, u["uid"]))
        if wb > 0:
            await notify_user(ctx, u["uid"], f"🎁 Welcome bonus <b>{money(wb)}৳</b> added to your balance!")
    if u["ref_by"] and not u["refer_paid"]:
        await pay_refer(ctx, u["uid"])


async def is_member(ctx, uid):
    try:
        m = await ctx.bot.get_chat_member(chat_ref(S("channel")), uid)
        return m.status in ("member", "administrator", "creator", "owner") or \
            (m.status == "restricted" and getattr(m, "is_member", False))
    except TelegramError as e:
        log.warning("member check failed: %s", e)
        return True      # misconfiguration must not lock everybody out (see Join Test)


async def guard(update, ctx):
    tu = update.effective_user
    if is_admin(tu.id):
        return True
    u = user(tu.id)
    if not u:
        u = await reg(update, ctx)
    if u["banned"]:
        await say(update, ctx, "🚫 You are banned from using this bot.")
        return False
    if S("channel_on") == "1" and S("channel"):
        if not await is_member(ctx, tu.id):
            ch = S("channel")
            link = f"https://t.me/{ch.lstrip('@')}" if ch.startswith("@") else "https://t.me/"
            await say(update, ctx, "⚠️ Please join our channel first, then tap <b>I Joined</b>.",
                      IM([[ib("📢 Join Channel", url=link, style="primary")], [ib("✅ I Joined", "chk", "success")]]))
            return False
    if S("phone_on") == "1" and not u["phone"]:
        await say(update, ctx, "📱 Please share your phone number to continue (one account per number).",
                  RM([[kb("📱 Share my number", "success", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True))
        return False
    await first_pass(ctx, u)
    return True


# ----------------------------------------------------------------------------
# KEYBOARDS
# ----------------------------------------------------------------------------
def main_menu():
    L = label
    return RM([[kb(L("buy"), "primary")],
               [kb(L("addbal"), "success"), kb(L("orders"), "primary")],
               [kb(L("bal"), "danger"), kb(L("refer"), "success")],
               [kb(L("ad"), "primary")],
               [kb(L("time"), "danger")],
               [kb(L("id"), "success"), kb(L("help"), "danger")]], resize_keyboard=True)


def welcome_text():
    return S("welcome_text").replace("{shop}", esc(S("shop_name"))).replace("{contact}", esc(S("help_contact")))


ADMIN_ROWS = [
    ["broadcast"], ["bcenter"], ["pending"],
    ["addprod", "editprod"], ["delprod", "cats"], ["stock", "lowstock"],
    ["total", "users"], ["sendprod", "delivered"], ["refertop", "reset"], ["paystats"],
    ["paymethod", "paytoggle"], ["comments"], ["channel", "jointest"], ["logch", "joinlogs"],
    ["referprot", "phoneprot"], ["pnotify", "notifyprod"], ["autopost", "shopname"],
    ["timechecks"], ["timelive"], ["autofix", "autofixstats"], ["adminads", "adsstatus"],
    ["active", "activedetail"], ["adslock", "unlock"], ["btnrename"],
    ["allprodcheck", "prodinfo"], ["allusers", "userinfo"], ["welcome", "id"], ["usermenu"],
]


def alabels():
    ch = S("channel") or "not set"
    return {
        "broadcast": "📢 Broadcast", "bcenter": "📥 Broadcast Center (সবাইকে + ব্লক তালিকা)",
        "pending": "📋 Pending", "addprod": "➕ Add Product", "editprod": "✏️ Edit Product",
        "delprod": "🗑 Del Product", "cats": "🗂 Categories", "stock": "📦 Stock Manager",
        "lowstock": "⚠️ Low Stock", "total": f"👥 Total Users ({cnt('SELECT COUNT(*) FROM users')})",
        "users": "👥 Users", "sendprod": "📦 Send Product", "delivered": "📬 Delivered",
        "refertop": "👥 Refer Top", "reset": "♻️ Reset Panel", "paystats": "⚡ Online Payment Stats",
        "paymethod": "💳 Payment Method", "paytoggle": "💳 Payment Toggle", "comments": "💬 Comments",
        "channel": f"📢 Channel: {ch}", "jointest": "🔍 Join Test", "logch": "📋 Log Channel",
        "joinlogs": "📋 Join Logs", "referprot": "🛡 Refer Protection", "phoneprot": "📱 Phone/IP Protect",
        "pnotify": "🔔 Product Notify", "notifyprod": "📢 Notify Product",
        "autopost": "📢 অটো পোস্ট (চ্যানেল)", "shopname": "🏷 Shop Name", "timechecks": "👥 Time Checks",
        "timelive": "🕐 Time LIVE", "autofix": "🛠 Auto-Fix", "autofixstats": "📊 Auto-Fix Stats",
        "adminads": "💰 Admin Ads", "adsstatus": "📊 Ads Status", "active": "👥 Active Users",
        "activedetail": "📄 Active Detail", "adslock": "🔐 Usr Ads Lock", "unlock": "🔓 Usr Unlock",
        "btnrename": "🔤 Button Rename", "allprodcheck": "📦 All Products Check",
        "prodinfo": "📊 Products Info", "allusers": "👥 All Users Info", "userinfo": "🔍 User Info",
        "welcome": "🎁 Welcome Bonus", "id": "🆔 Id", "usermenu": "👤 User Menu",
    }


def admin_kb():
    lab = alabels()
    rows, i = [], 0
    for r in ADMIN_ROWS:
        row = []
        for k in r:
            row.append(kb(lab[k], CYCLE[i % 3]))
            i += 1
        rows.append(row)
    return RM(rows, resize_keyboard=True)


def panel_text():
    users = cnt("SELECT COUNT(*) FROM users")
    pend = cnt("SELECT COUNT(*) FROM payments WHERE status='pending'") + cnt("SELECT COUNT(*) FROM orders WHERE status='pending'")
    deliv = cnt("SELECT COUNT(*) FROM orders WHERE status='delivered'")
    low = cnt("SELECT COUNT(*) FROM products WHERE track=1 AND active=1")  # products using stock
    oos = sum(1 for p in all_("SELECT id FROM products WHERE track=1 AND active=1") if stock_count(p["id"]) == 0)
    onoff = lambda k: "✅ ON" if S(k) == "1" else "❌ OFF"
    pays = "\n".join(f"• {n}: {esc(S('pay_' + k + '_num')) or '—'} {'✅' if S('pay_' + k + '_on') == '1' else '❌'}"
                     for k, (_, n) in METHODS.items())
    return (f"👑 <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━\n\n"
            f"👥 Users: {users} | ⏳ Pending: {pend} | 📦 Delivered: {deliv}\n"
            f"🗃 Stock products: {low} | ❌ Out of stock: {oos}\n"
            f"👥 Refer: {money(Sf('refer_bonus'))}৳/join | {money(Sf('refer_percent'))}% commission\n"
            f"⭐ Star Admin: {ADMIN_IDS[0] if ADMIN_IDS else '-'}\n"
            f"📢 Channel: {esc(S('channel')) or 'not set'} {onoff('channel_on')}\n"
            f"📋 Log Channel: {esc(S('log_channel')) or 'not set'} {onoff('log_on')}\n"
            f"🎁 Welcome Bonus: {money(Sf('welcome_bonus'))}৳ (/set_startbonus)\n\n"
            f"💳 <b>Payments:</b>\n{pays}\n\n"
            f"<b>Commands:</b>\n/addbal uid amt | /removebal uid amt\n"
            f"/sendproduct uid details | /delivered | /history | /pending\n"
            f"/addstock pid items... | /stock | /all_list")


# ----------------------------------------------------------------------------
# USER VIEWS : categories, products, buying
# ----------------------------------------------------------------------------
def plist(cat, term=""):
    w, a = "active=1", []
    if cat > 0:
        w += " AND cat_id=?"
        a.append(cat)
    if cat == -1 and term:
        w += " AND name LIKE ?"
        a.append(f"%{term}%")
    return w, a


async def view_cats(update, ctx, page=0):
    cs = all_("SELECT * FROM categories ORDER BY pos, id")
    per = 10
    pages = max(1, -(-len(cs) // per))
    page = max(0, min(page, pages - 1))
    rows = grid([(c["name"], f"cl:{c['id']}:0") for c in cs[page * per:(page + 1) * per]], 2)
    rows.append([ib("📋 All Products", "cl:0:0", "primary")])
    rows.append([ib("🔍 Search Old Serial Order Name", "sr", "success")])
    nav = []
    if page > 0:
        nav.append(ib("⬅️ Back", f"cs:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"cs:{page + 1}", "primary"))
    if nav:
        rows.append(nav)
    txt = (f"🛒 <b>{esc(S('shop_name'))}</b>\nSelect a category (Page {page + 1}/{pages}):"
           if cs else "😕 No categories yet. Please check back later.")
    await show(update, ctx, txt, IM(rows))


async def view_list(update, ctx, cat, page=0):
    term = ctx.user_data.get("sq", "")
    w, a = plist(cat, term)
    total = cnt(f"SELECT COUNT(*) FROM products WHERE {w}", a)
    pages = max(1, -(-total // per_page()))
    page = max(0, min(page, pages - 1))
    items = all_(f"SELECT * FROM products WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?", a + [per_page(), page * per_page()])
    if cat > 0:
        c = one("SELECT name FROM categories WHERE id=?", (cat,))
        title = c["name"] if c else "Products"
    elif cat == -1:
        title = f"🔍 {term}"
    else:
        title = "📋 All Products"
    rows = []
    for i, p in enumerate(items):
        oos = p["track"] and stock_count(p["id"]) == 0
        rows.append([ib(f"{p['name']}{' ( Stock Out )' if oos else ''} — {money(p['price'])}৳",
                        f"pv:{cat}:{page * per_page() + i}", "danger" if oos else CYCLE[i % 2])])
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"cl:{cat}:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"cl:{cat}:{page + 1}", "primary"))
    if nav:
        rows.append(nav)
    rows.append([ib("⬅️ All Products", "cs:0", "primary")])
    rows.append([ib("🔍 Search Old Serial Order Name", "sr", "success")])
    txt = f"<b>{esc(title)} — Old Serial Order</b> (Page {page + 1}/{pages}) — {total} items"
    if not total:
        txt += "\n\n😕 Nothing found."
    await show(update, ctx, txt, IM(rows))


async def view_prod(update, ctx, cat, pos):
    term = ctx.user_data.get("sq", "")
    w, a = plist(cat, term)
    total = cnt(f"SELECT COUNT(*) FROM products WHERE {w}", a)
    if total == 0:
        await alert(update, ctx, "😕 No products found.")
        return
    pos %= total
    p = one(f"SELECT * FROM products WHERE {w} ORDER BY id DESC LIMIT 1 OFFSET ?", a + [pos])
    u = user(update.effective_user.id)
    c = one("SELECT name FROM categories WHERE id=?", (p["cat_id"],))
    d = dt.datetime.fromtimestamp(p["added"], TZ)
    utc = dt.datetime.fromtimestamp(p["added"], dt.timezone.utc)
    oos = p["track"] and stock_count(p["id"]) == 0
    txt = (f"📦 <b>{esc(p['name'])}</b> ({pos + 1}/{total})\n\n"
           f"💰 Price: <b>{money(p['price'])}BDT</b>\n"
           f"💳 Your Balance: <b>{u['balance']:.2f}BDT</b>\n"
           f"🗃 Stock: {stock_line(p)}\n"
           f"📢 Channel: {esc(c['name']) if c else '-'}\n"
           f"🕐 <b>Added:</b> {d:%Y-%m-%d %H:%M:%S} ({d:%A}) Dhaka — 24h\n"
           f"🌍 UTC: {utc:%Y-%m-%d %H:%M:%S} / {utc:%I:%M:%S %p}\n")
    if S("product_note"):
        txt += f"\n💬 {esc(S('product_note'))[:200]}\n"
    txt += "\n" + ("❌ This item is out of stock right now." if oos else "✅ Click Buy Now to purchase instantly.")
    rows = [[ib("❌ Out of Stock", "noop", "danger")] if oos else [ib("✅ Buy Now", f"buy:{p['id']}", "success")],
            [ib("Next →", f"pv:{cat}:{pos + 1}", "primary")],
            [ib("⬅️ Back", f"cl:{cat}:{pos // per_page()}", "danger")]]
    await show(update, ctx, txt, IM(rows), photo=p["image"] or None)


async def open_product(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=? AND active=1", (pid,))
    if not p:
        await alert(update, ctx, "❌ Product not found.")
        return
    ctx.user_data["sq"] = ""
    await view_prod(update, ctx, 0, cnt("SELECT COUNT(*) FROM products WHERE active=1 AND id>?", (pid,)))


async def do_buy(update, ctx, pid):
    uid = update.effective_user.id
    p = one("SELECT * FROM products WHERE id=? AND active=1", (pid,))
    if not p:
        await alert(update, ctx, "❌ Product not found.")
        return
    u = user(uid)
    if p["track"] and stock_count(pid) <= 0:
        await alert(update, ctx, "❌ Out of stock! Please check back later.")
        return
    if u["balance"] + 1e-9 < p["price"]:
        await alert(update, ctx, f"❌ Insufficient balance. Price {money(p['price'])} TK, you have {u['balance']:.2f} TK.")
        await say(update, ctx, "💰 Please add balance first.", IM([[ib("💰 Add Balance", "dep", "success")]]))
        return
    item = None
    if p["track"]:
        item = one("SELECT * FROM stock WHERE pid=? AND sold=0 ORDER BY id LIMIT 1", (pid,))
        if not item:
            await alert(update, ctx, "❌ Out of stock!")
            return
    run("UPDATE users SET balance=balance-?, total_spent=total_spent+?, total_orders=total_orders+1 WHERE uid=?",
        (p["price"], p["price"], uid))
    oid = run("INSERT INTO orders(uid,pid,name,price,status,details,created,delivered) VALUES(?,?,?,?,?,?,?,?)",
              (uid, pid, p["name"], p["price"], "delivered" if item else "pending",
               item["data"] if item else "", now(), now() if item else 0)).lastrowid
    if item:
        run("UPDATE stock SET sold=1, order_id=? WHERE id=?", (oid, item["id"]))
    pc = Sf("refer_percent")
    if u["ref_by"] and pc > 0 and user(u["ref_by"]):
        com = p["price"] * pc / 100
        run("UPDATE users SET refer_balance=refer_balance+? WHERE uid=?", (com, u["ref_by"]))
        await notify_user(ctx, u["ref_by"], f"💸 Commission +{com:.2f}৳ from your referral's purchase.")
    await alert(update, ctx, "✅ Purchase successful!" if item else "✅ Order placed!")
    if item:
        await say(update, ctx, f"✅ <b>Order #{oid} delivered!</b>\n📦 {esc(p['name'])}\n💰 {money(p['price'])} TK\n\n"
                               f"🔑 <b>Your details:</b>\n<code>{esc(item['data'])}</code>")
        await tolog(ctx, "order", f"#{oid} {uid} bought '{p['name']}' {money(p['price'])}TK (auto from stock)")
        left = stock_count(pid)
        if left == 0 or left == int(Sf("low_stock")):
            await notify_admins(ctx, f"⚠️ <b>{'OUT OF STOCK' if left == 0 else 'Low stock'}</b>: {esc(p['name'])} (ID {pid}) — {left} left",
                                IM([[ib("➕ Add Stock", f"ska:{pid}", "success")]]))
    else:
        await say(update, ctx, f"✅ <b>Order #{oid} placed!</b>\n📦 {esc(p['name'])}\n💰 {money(p['price'])} TK\n\n⏳ Admin will deliver it soon.")
        await notify_admins(ctx, f"🆕 <b>New order #{oid}</b>\n👤 {uid} @{esc(u['username'])}\n📦 {esc(p['name'])} — {money(p['price'])} TK",
                            IM([[ib("📦 Deliver", f"dl:{oid}", "success")]]))
        await tolog(ctx, "order", f"#{oid} {uid} ordered '{p['name']}' {money(p['price'])}TK (manual)")


async def deliver_order(ctx, oid, details):
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    if not o:
        return False
    run("UPDATE orders SET status='delivered', details=?, delivered=? WHERE id=?", (details, now(), oid))
    await notify_user(ctx, o["uid"], f"✅ <b>Order #{oid} delivered!</b>\n📦 {esc(o['name'])}\n\n🔑 <b>Details:</b>\n<code>{esc(details)}</code>")
    await tolog(ctx, "delivered", f"#{oid} -> {o['uid']}")
    return True


async def view_orders(update, ctx, page=0):
    uid = update.effective_user.id
    per = 5
    total = cnt("SELECT COUNT(*) FROM orders WHERE uid=?", (uid,))
    if not total:
        await show(update, ctx, "📦 You have no orders yet.", IM([[ib("🛒 Buy Old Serial", "cs:0", "success")]]))
        return
    pages = -(-total // per)
    page = max(0, min(page, pages - 1))
    rows = all_("SELECT * FROM orders WHERE uid=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, per, page * per))
    txt = f"📦 <b>My Orders</b> (Page {page + 1}/{pages})\n"
    for o in rows:
        txt += f"\n{'✅' if o['status'] == 'delivered' else '⏳'} <b>#{o['id']}</b> {esc(o['name'])} — {money(o['price'])}TK\n🕐 {dts(o['created'])}\n"
        if o["details"]:
            txt += f"<code>{esc(o['details'][:300])}</code>\n"
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"mo:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"mo:{page + 1}", "primary"))
    await show(update, ctx, txt, IM([nav] if nav else []))


async def view_balance(update, ctx):
    u = user(update.effective_user.id)
    who = f"@{esc(u['username'])}" if u["username"] else esc(u["name"])
    txt = (f"💰 <b>YOUR BALANCE</b>\n━━━━━━━━━━━━━━\n👤 Username: {who}\n"
           f"💵 Available: {u['balance']:.2f} TK\n🚀 Total Orders amount : {u['total_spent']:.2f} TK\n"
           f"🚀 Total Orders : {u['total_orders']}\n🎁 Refer balance: {u['refer_balance']:.2f} TK\n━━━━━━━━━━━━━━")
    await show(update, ctx, txt, IM([[ib("💰 Add Balance", "dep", "success"), ib("🛒 Buy Old Serial", "cs:0", "primary")],
                                     [ib("📦 My Orders", "mo:0", "danger"), ib("👥 Refer & Earn", "rf", "success")],
                                     [ib("🔄 Refresh", "bl", "primary")]]))


async def view_refer(update, ctx):
    u = user(update.effective_user.id)
    un = (await ctx.bot.get_me()).username
    inv = cnt("SELECT COUNT(*) FROM users WHERE ref_by=?", (u["uid"],))
    paid = cnt("SELECT COUNT(*) FROM users WHERE ref_by=? AND refer_paid=1", (u["uid"],))
    txt = (f"👥 <b>Refer & Earn</b>\n━━━━━━━━━━━━━━\n🔗 Your link:\nhttps://t.me/{un}?start=ref{u['uid']}\n\n"
           f"🎁 Earn <b>{money(Sf('refer_bonus'))}৳</b> for every friend who joins\n"
           f"💸 + <b>{money(Sf('refer_percent'))}%</b> commission on their purchases\n\n"
           f"👤 Invited: {inv} (rewarded: {paid})\n💰 Refer balance: <b>{u['refer_balance']:.2f} TK</b>")
    await show(update, ctx, txt, IM([[ib("💱 Move to Balance", "rfmove", "success"), ib("🔄 Refresh", "rf", "primary")]]))


def time_text():
    d = dt.datetime.now(TZ)
    u = dt.datetime.now(dt.timezone.utc)
    return (f"🕐 <b>Digital Time</b>\n\n🇧🇩 Dhaka: <b>{d:%I:%M:%S %p}</b>\n📅 {d:%A, %d %B %Y}\n"
            f"🕰 24h: {d:%H:%M:%S}\n🌍 UTC: {u:%H:%M:%S}")


# ----------------------------------------------------------------------------
# DEPOSIT FLOW
# ----------------------------------------------------------------------------
async def view_portal(update, ctx):
    items = [(f"{e} {n}", f"dm:{k}") for k, (e, n) in METHODS.items() if S(f"pay_{k}_on") == "1" and S(f"pay_{k}_num")]
    rows = grid(items, 2)
    rows.append([ib("❌ Cancel", "dcancel", "danger")])
    txt = ("💲 <b>Deposit Portal</b>\n━━━━━━━━━━━━━━\n🏧 <b>Payment System</b>\n\n"
           "1) bKash / Nagad / Rocket / Binance → Enter amount (BDT) → Confirm\n"
           "2) Send the payment, then submit your TrxID → balance is added once an admin approves\n\n"
           "✅ Select a payment method to begin:" if items else "⚠️ No payment method is available right now.")
    await show(update, ctx, txt, IM(rows))


async def view_dep(update, ctx):
    d = ctx.user_data.get("dep")
    if not d:
        await view_portal(update, ctx)
        return
    n = METHODS[d["m"]][1]
    amounts = [float(x) for x in S("amounts").split(",") if x.strip()]
    btns = [ib(f"{money(a)} ✅" if a == d["amt"] else f"৳{money(a)}", f"da:{money(a)}", CYCLE[i % 3]) for i, a in enumerate(amounts)]
    rows = chunks(btns, 4)
    rows.append([ib("✍️ Enter Amount", "dcustom", "primary")])
    rows.append([ib("⬅️ Back", "dback", "primary"), ib("❌ Cancel", "dcancel", "danger")])
    rows.append([ib("✅ Confirm", "dconfirm", "success")])
    txt = (f"<b>{n} — Add Balance</b>\n━━━━━━━━━━━━━━\n\n💰 <b>Selected Amount:</b> ৳{money(d['amt'])}\n"
           f"⚠️ <b>Minimum Deposit:</b> ৳{money(Sf('min_deposit'))}\n\nHow much BDT would you like to deposit? 👇\n"
           f"Pick an amount below or tap <b>Enter Amount</b> to type your own.")
    await show(update, ctx, txt, IM(rows))


async def cancel_flow(update, ctx, notify=True):
    st = ctx.user_data.get("st", "")
    if st.startswith("trx:"):
        run("UPDATE payments SET status='cancelled' WHERE id=? AND status='created'", (int(st.split(":")[1]),))
    ctx.user_data.pop("st", None)
    ctx.user_data.pop("dep", None)
    if notify:
        await show(update, ctx, "❌ Cancelled.") if update.callback_query else await say(update, ctx, "❌ Cancelled.")


# ----------------------------------------------------------------------------
# CALLBACK REGISTRY
# ----------------------------------------------------------------------------
CB, ADMIN_CB = {}, set()


def cb(name, admin=False):
    def deco(f):
        CB[name] = f
        if admin:
            ADMIN_CB.add(name)
        return f
    return deco


async def on_cb(update, ctx):
    q = update.callback_query
    parts = q.data.split(":")
    name = parts[0]
    ctx.user_data["_ans"] = False
    await reg(update, ctx)
    uid = q.from_user.id
    try:
        if name in ADMIN_CB and not is_admin(uid):
            await q.answer("⛔ Admin only", show_alert=True)
            return
        if name not in ADMIN_CB and not await guard(update, ctx):
            await q.answer()
            return
        fn = CB.get(name)
        if fn:
            await fn(update, ctx, parts[1:])
    except Exception:
        log.exception("callback %s failed", q.data)
    if not ctx.user_data.get("_ans"):
        try:
            await q.answer()
        except TelegramError:
            pass


# ---- user callbacks --------------------------------------------------------
@cb("noop")
async def c_noop(update, ctx, a):
    await alert(update, ctx, "❌ Out of stock right now.")


@cb("chk")
async def c_chk(update, ctx, a):
    if await guard(update, ctx):
        await say(update, ctx, welcome_text(), main_menu())


@cb("cs")
async def c_cs(update, ctx, a):
    await view_cats(update, ctx, int(a[0]) if a else 0)


@cb("cl")
async def c_cl(update, ctx, a):
    await view_list(update, ctx, int(a[0]), int(a[1]))


@cb("pv")
async def c_pv(update, ctx, a):
    await view_prod(update, ctx, int(a[0]), int(a[1]))


@cb("pp")
async def c_pp(update, ctx, a):
    await open_product(update, ctx, int(a[0]))


@cb("sr")
async def c_sr(update, ctx, a):
    ctx.user_data["st"] = "search"
    await say(update, ctx, "🔍 Send the serial name you are looking for:\n(/cancel to stop)")


@cb("buy")
async def c_buy(update, ctx, a):
    await do_buy(update, ctx, int(a[0]))


@cb("mo")
async def c_mo(update, ctx, a):
    await view_orders(update, ctx, int(a[0]))


@cb("bl")
async def c_bl(update, ctx, a):
    await view_balance(update, ctx)


@cb("rf")
async def c_rf(update, ctx, a):
    await view_refer(update, ctx)


@cb("rfmove")
async def c_rfmove(update, ctx, a):
    u = user(update.effective_user.id)
    if u["refer_balance"] <= 0:
        await alert(update, ctx, "❌ Your refer balance is empty.")
        return
    amt = u["refer_balance"]
    run("UPDATE users SET balance=balance+?, refer_balance=0 WHERE uid=?", (amt, u["uid"]))
    await alert(update, ctx, f"✅ {amt:.2f} TK moved to your balance.")
    await view_refer(update, ctx)


@cb("tm")
async def c_tm(update, ctx, a):
    await show(update, ctx, time_text(), IM([[ib("🔄 Refresh", "tm", "primary")]]))


@cb("dep")
async def c_dep(update, ctx, a):
    await view_portal(update, ctx)


@cb("dm")
async def c_dm(update, ctx, a):
    m = a[0]
    amounts = [float(x) for x in S("amounts").split(",") if x.strip()]
    ctx.user_data["dep"] = {"m": m, "amt": max(Sf("min_deposit"), amounts[0] if amounts else Sf("min_deposit"))}
    await view_dep(update, ctx)


@cb("da")
async def c_da(update, ctx, a):
    d = ctx.user_data.get("dep")
    if d:
        d["amt"] = float(a[0])
    await view_dep(update, ctx)


@cb("dcustom")
async def c_dcustom(update, ctx, a):
    ctx.user_data["st"] = "dep_amt"
    await say(update, ctx, f"✍️ Send the amount in BDT (minimum ৳{money(Sf('min_deposit'))}):")


@cb("dback")
async def c_dback(update, ctx, a):
    ctx.user_data.pop("dep", None)
    await view_portal(update, ctx)


@cb("dcancel")
async def c_dcancel(update, ctx, a):
    await cancel_flow(update, ctx)


@cb("dconfirm")
async def c_dconfirm(update, ctx, a):
    d = ctx.user_data.get("dep")
    if not d:
        await view_portal(update, ctx)
        return
    if d["amt"] < Sf("min_deposit"):
        await alert(update, ctx, f"❌ Minimum deposit is ৳{money(Sf('min_deposit'))}")
        return
    num = S(f"pay_{d['m']}_num")
    if not num:
        await alert(update, ctx, "❌ This payment method is not configured.")
        return
    pid = run("INSERT INTO payments(uid,method,amount,created) VALUES(?,?,?,?)",
              (update.effective_user.id, d["m"], d["amt"], now())).lastrowid
    ctx.user_data["st"] = f"trx:{pid}"
    txt = (f"🧾 <b>Payment invoice created!</b>\n━━━━━━━━━━━━━━\nMethod: <b>{METHODS[d['m']][1]}</b>\n"
           f"Amount: <b>৳{money(d['amt'])}</b>\nSend to: <code>{esc(num)}</code>\n━━━━━━━━━━━━━━\n"
           f"After paying, send your <b>Transaction ID (TrxID)</b> here.\n(Cancel: /cancel)")
    await show(update, ctx, txt, IM([[ib("❌ Cancel", "dcancel", "danger")]]))


@cb("adc")
async def c_adc(update, ctx, a):
    t = ctx.user_data.get("ad_t")
    secs = int(Sf("ad_seconds"))
    if not t:
        await alert(update, ctx, "⚠️ Open the ad from the 📺 Watch Ad menu first.")
        return
    left = int(secs - (time.time() - t))
    if left > 0:
        await alert(update, ctx, f"⏳ Please wait {left}s more.")
        return
    ctx.user_data.pop("ad_t", None)
    r = Sf("ad_reward")
    run("UPDATE users SET balance=balance+? WHERE uid=?", (r, update.effective_user.id))
    run("INSERT INTO ad_views(uid,ts,reward) VALUES(?,?,?)", (update.effective_user.id, now(), r))
    await show(update, ctx, f"🎉 You earned <b>{money(r)}৳</b>!")


# ----------------------------------------------------------------------------
# MENU (reply keyboard) HANDLERS
# ----------------------------------------------------------------------------
async def m_ad(update, ctx):
    u = user(update.effective_user.id)
    if u["ads_lock"]:
        await say(update, ctx, "🔒 Ads are locked for your account.")
        return
    if not S("ad_text") and not S("ad_url"):
        await say(update, ctx, "📺 No ads available right now.")
        return
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    used = cnt("SELECT COUNT(*) FROM ad_views WHERE uid=? AND ts>?", (u["uid"], today))
    lim = int(Sf("ad_daily"))
    if used >= lim:
        await say(update, ctx, f"✅ Daily ad limit reached ({used}/{lim}). Come back tomorrow!")
        return
    ctx.user_data["ad_t"] = time.time()
    rows = []
    if S("ad_url"):
        rows.append([ib("🔗 Open Ad", url=S("ad_url"), style="primary")])
    rows.append([ib("✅ Claim Reward", "adc", "success")])
    await say(update, ctx, f"📺 <b>Sponsored</b>\n\n{esc(S('ad_text'))}\n\n⏳ Open the ad, wait {int(Sf('ad_seconds'))}s, "
                           f"then tap <b>Claim</b> to earn <b>{money(Sf('ad_reward'))}৳</b>.\nToday: {used}/{lim}", IM(rows))


async def m_id(update, ctx):
    tu = update.effective_user
    await say(update, ctx, f"🆔 Your ID: <code>{tu.id}</code>\n👤 {esc(tu.full_name)}" + (f"\n🔗 @{esc(tu.username)}" if tu.username else ""))


async def m_help(update, ctx):
    c = S("help_contact")
    rows = [[ib("💬 Contact Support", url=f"https://t.me/{c.lstrip('@')}", style="success")]] if c.startswith("@") else []
    await say(update, ctx, welcome_text(), IM(rows) if rows else None)


async def m_time(update, ctx):
    await say(update, ctx, time_text(), IM([[ib("🔄 Refresh", "tm", "primary")]]))


MENU = {"buy": lambda u, c: view_cats(u, c, 0), "addbal": lambda u, c: view_portal(u, c),
        "orders": lambda u, c: view_orders(u, c, 0), "bal": lambda u, c: view_balance(u, c),
        "refer": lambda u, c: view_refer(u, c), "ad": m_ad, "time": m_time, "id": m_id, "help": m_help}


# ----------------------------------------------------------------------------
# ADMIN : screens (pure builders -> (text, markup))
# ----------------------------------------------------------------------------
def onoff(k):
    return "✅ ON" if S(k) == "1" else "❌ OFF"


def tgl(key, screen, text):
    return ib(f"{text}: {onoff(key)}", f"tg:{key}:{screen}", "success" if S(key) == "1" else "danger")


def scr_channel():
    return (f"📢 <b>Channel</b>\n\nChannel: <code>{esc(S('channel')) or 'not set'}</code>\nForce-join: {onoff('channel_on')}\n\n"
            "The bot must be an admin of the channel for the join check to work.",
            IM([[ib("✏️ Set Channel", "set:channel", "primary")], [tgl("channel_on", "channel", "Force-join")],
                [ib("🔍 Join Test", "jt", "success")]]))


def scr_logch():
    return (f"📋 <b>Log Channel</b>\n\nChannel: <code>{esc(S('log_channel')) or 'not set'}</code>\nLogging: {onoff('log_on')}\n\n"
            "Orders, deposits, joins and deliveries are logged here.",
            IM([[ib("✏️ Set Log Channel", "set:log_channel", "primary")], [tgl("log_on", "logch", "Logging")]]))


def scr_refer():
    return (f"🛡 <b>Refer Protection</b>\n\nProtection: {onoff('refer_protect')}\n"
            "ON  = bonus is paid only after the new user passes the channel/phone checks (and phone ≠ referrer's phone).\n"
            "OFF = bonus is paid immediately on /start.\n\n"
            f"🎁 Bonus per join: <b>{money(Sf('refer_bonus'))}৳</b>\n💸 Commission: <b>{money(Sf('refer_percent'))}%</b>",
            IM([[tgl("refer_protect", "refer", "Protection")],
                [ib("🎁 Set Bonus", "set:refer_bonus", "success"), ib("💸 Set Commission %", "set:refer_percent", "primary")]]))


def scr_phone():
    return (f"📱 <b>Phone Protect</b>\n\nPhone verification: {onoff('phone_on')}\n"
            "Users must share their Telegram contact once; one account per number.\n"
            "(Telegram bots cannot see IP addresses, so only phone protection is possible.)",
            IM([[tgl("phone_on", "phone", "Phone verification")]]))


def scr_autopost():
    return (f"📢 <b>অটো পোস্ট (চ্যানেল)</b>\n\nAuto-post new products to {esc(S('channel')) or 'the channel (set it first)'}: {onoff('autopost')}",
            IM([[tgl("autopost", "autopost", "Auto-post")]]))


def scr_notify():
    return (f"🔔 <b>Product Notify</b>\n\nNotify ALL users when a new product is added: {onoff('notify_new')}",
            IM([[tgl("notify_new", "notify", "Notify users")]]))


def scr_paymethod():
    lines = "\n".join(f"{e} <b>{n}</b>: <code>{esc(S('pay_' + k + '_num')) or 'not set'}</code> {'✅' if S('pay_' + k + '_on') == '1' else '❌'}"
                      for k, (e, n) in METHODS.items())
    rows = grid([(f"✏️ {n}", f"set:pay_{k}_num") for k, (_, n) in METHODS.items()], 2)
    rows.append([ib(f"💵 Min Deposit ({money(Sf('min_deposit'))})", "set:min_deposit", "success"),
                 ib("🔢 Amount Buttons", "set:amounts", "primary")])
    return f"💳 <b>Payment Methods</b>\n\n{lines}\n\n🔢 Amounts: {esc(S('amounts'))}", IM(rows)


def scr_paytoggle():
    rows = [[tgl(f"pay_{k}_on", "paytoggle", f"{e} {n}")] for k, (e, n) in METHODS.items()]
    return "💳 <b>Payment Toggle</b>\nTurn payment methods on or off:", IM(rows)


def scr_shop():
    return (f"🏷 <b>Shop Settings</b>\n\n🏷 Name: <b>{esc(S('shop_name'))}</b>\n💬 Help contact: {esc(S('help_contact'))}\n"
            "📝 Welcome text: use {shop} and {contact} placeholders.",
            IM([[ib("🏷 Shop Name", "set:shop_name", "primary"), ib("💬 Help Contact", "set:help_contact", "success")],
                [ib("📝 Welcome Text", "set:welcome_text", "danger"), ib(f"📄 Per Page ({per_page()})", "set:per_page", "primary")]]))


def scr_comments():
    return (f"💬 <b>Comments</b>\n\nNote shown on every product card:\n<i>{esc(S('product_note')) or 'none'}</i>",
            IM([[ib("✏️ Set Note", "set:product_note", "primary"), ib("🗑 Clear", "clr:product_note:comments", "danger")]]))


def scr_ads():
    return (f"💰 <b>Admin Ads</b> (Watch Ad)\n\n📝 Text: {esc(S('ad_text')) or '—'}\n🔗 Link: {esc(S('ad_url')) or '—'}\n"
            f"💵 Reward: {money(Sf('ad_reward'))}৳\n⏳ Wait: {int(Sf('ad_seconds'))}s\n📅 Daily limit/user: {int(Sf('ad_daily'))}",
            IM([[ib("📝 Text", "set:ad_text", "primary"), ib("🔗 Link", "set:ad_url", "success")],
                [ib("💵 Reward", "set:ad_reward", "danger"), ib("⏳ Seconds", "set:ad_seconds", "primary")],
                [ib("📅 Daily Limit", "set:ad_daily", "success"), ib("🗑 Clear Ad", "clr:ad_text:ads", "danger")]]))


def scr_bcenter():
    tot = cnt("SELECT COUNT(*) FROM users")
    act = cnt("SELECT COUNT(*) FROM users WHERE last_active>?", (now() - 86400,))
    blk = cnt("SELECT COUNT(*) FROM users WHERE blocked_bot=1")
    return (f"📥 <b>Broadcast Center</b>\n\n👥 Total: {tot}\n🟢 Active (24h): {act}\n🚫 Blocked the bot: {blk}",
            IM([[ib("📢 Send to ALL", "bcs:all", "success"), ib("🟢 Send to Active", "bcs:active", "primary")],
                [ib("🚫 Blocked List", "bcs:blocked", "danger")]]))


def scr_btnrename():
    rows = grid([(label(k), f"brk:{k}") for k in MENU_LABELS], 2)
    rows.append([ib("♻️ Reset All Names", "brr", "danger")])
    return "🔤 <b>Button Rename</b>\nTap a button to give it a new name:", IM(rows)


def scr_cats():
    cs = all_("SELECT * FROM categories ORDER BY pos, id")
    rows = [[ib(f"{c['name']} ({cnt('SELECT COUNT(*) FROM products WHERE cat_id=?', (c['id'],))})", f"cmv:{c['id']}", CYCLE[i % 3])]
            for i, c in enumerate(cs)]
    rows.append([ib("➕ Add Category", "cma", "success")])
    return "🗂 <b>Categories</b>\nTap a category to rename / move / delete it:", IM(rows)


SCREENS = {"channel": scr_channel, "logch": scr_logch, "refer": scr_refer, "phone": scr_phone,
           "autopost": scr_autopost, "notify": scr_notify, "paymethod": scr_paymethod,
           "paytoggle": scr_paytoggle, "shop": scr_shop, "comments": scr_comments, "ads": scr_ads,
           "bcenter": scr_bcenter, "btnrename": scr_btnrename, "cats": scr_cats}


async def send_screen(update, ctx, name, edit=False):
    text, markup = SCREENS[name]()
    if edit:
        await show(update, ctx, text, markup)
    else:
        await say(update, ctx, text, markup)


@cb("sc", admin=True)
async def c_sc(update, ctx, a):
    await send_screen(update, ctx, a[0], edit=True)


@cb("tg", admin=True)
async def c_tg(update, ctx, a):
    setS(a[0], "0" if S(a[0]) == "1" else "1")
    await send_screen(update, ctx, a[1], edit=True)


@cb("clr", admin=True)
async def c_clr(update, ctx, a):
    setS(a[0], "")
    await send_screen(update, ctx, a[1], edit=True)


SET_INFO = {   # key: (prompt, type, screen to show afterwards)
    "welcome_bonus": ("🎁 Send the new <b>Welcome Bonus</b> amount (৳):", "f", None),
    "refer_bonus": ("🎁 Send the refer bonus per join (৳):", "f", "refer"),
    "refer_percent": ("💸 Send the refer commission percent (e.g. 10):", "f", "refer"),
    "min_deposit": ("💵 Send the minimum deposit (৳):", "f", "paymethod"),
    "amounts": ("🔢 Send amount buttons separated by commas, e.g. <code>50,60,70,80,100</code>", "amounts", "paymethod"),
    "channel": ("📢 Send the channel @username (or numeric id). Send <code>off</code> to clear:", "ch", "channel"),
    "log_channel": ("📋 Send the log channel id or @username. Send <code>off</code> to clear:", "ch", "logch"),
    "shop_name": ("🏷 Send the new shop name:", "s", "shop"),
    "help_contact": ("💬 Send the support @username:", "s", "shop"),
    "welcome_text": ("📝 Send the new welcome text (HTML allowed). Use {shop} and {contact}:", "s", "shop"),
    "product_note": ("💬 Send the note to show on product cards:", "s", "comments"),
    "ad_text": ("📝 Send the ad text:", "s", "ads"), "ad_url": ("🔗 Send the ad link (https://...):", "s", "ads"),
    "ad_reward": ("💵 Send the reward per ad (৳):", "f", "ads"), "ad_seconds": ("⏳ Send the wait time in seconds:", "i", "ads"),
    "ad_daily": ("📅 Send the daily ad limit per user:", "i", "ads"),
    "low_stock": ("⚠️ Send the low-stock alert level (number):", "i", None),
    "per_page": ("📄 How many products per page? (3-20, default 6):", "i", "shop"),
}
for _k in METHODS:
    SET_INFO[f"pay_{_k}_num"] = (f"✏️ Send the <b>{METHODS[_k][1]}</b> number / address users should pay to:", "s", "paymethod")


@cb("set", admin=True)
async def c_set(update, ctx, a):
    key = a[0]
    ctx.user_data["st"] = f"set:{key}"
    await say(update, ctx, SET_INFO[key][0] + f"\n\nCurrent: <code>{esc(S(key)) or '—'}</code>\n(/cancel to stop)")


@cb("jt", admin=True)
async def c_jt(update, ctx, a):
    await a_jointest(update, ctx)


# ----------------------------------------------------------------------------
# ADMIN : text-button handlers
# ----------------------------------------------------------------------------
A = {}


def akey(name):
    def deco(f):
        A[name] = f
        return f
    return deco


SCREEN_KEYS = {"channel": "channel", "logch": "logch", "referprot": "refer", "phoneprot": "phone",
               "autopost": "autopost", "pnotify": "notify", "paymethod": "paymethod", "paytoggle": "paytoggle",
               "shopname": "shop", "adminads": "ads", "comments": "comments", "bcenter": "bcenter",
               "btnrename": "btnrename", "cats": "cats"}
for _k, _s in SCREEN_KEYS.items():
    A[_k] = (lambda s: (lambda u, c: send_screen(u, c, s)))(_s)


@akey("broadcast")
async def a_broadcast(update, ctx):
    ctx.user_data["st"] = "bc:all"
    await say(update, ctx, "📢 <b>Broadcast</b>\nSend the message (text, photo + caption, video...) to deliver to ALL users.\n/cancel to abort.")


async def run_broadcast(ctx, admin_chat, targets, sender):
    ok = fail = 0
    for uid in targets:
        try:
            await sender(uid)
            ok += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await sender(uid)
                ok += 1
            except TelegramError:
                fail += 1
        except Forbidden:
            run("UPDATE users SET blocked_bot=1 WHERE uid=?", (uid,))
            fail += 1
        except TelegramError:
            fail += 1
        await asyncio.sleep(0.05)
    await send(ctx, admin_chat, f"✅ <b>Broadcast finished</b>\n📨 Sent: {ok}\n❌ Failed: {fail}")


def targets_for(kind):
    if kind == "active":
        return [r["uid"] for r in all_("SELECT uid FROM users WHERE banned=0 AND last_active>?", (now() - 86400,))]
    return [r["uid"] for r in all_("SELECT uid FROM users WHERE banned=0")]


@cb("bcs", admin=True)
async def c_bcs(update, ctx, a):
    if a[0] == "blocked":
        rows = all_("SELECT uid, username, name FROM users WHERE blocked_bot=1 ORDER BY last_active DESC LIMIT 100")
        txt = "🚫 <b>Blocked list</b>\n\n" + ("\n".join(f"• <code>{r['uid']}</code> {esc(r['name'])} {('@' + esc(r['username'])) if r['username'] else ''}" for r in rows) or "None 🎉")
        await send_long(ctx, update.effective_chat.id, txt)
        return
    ctx.user_data["st"] = f"bc:{a[0]}"
    await say(update, ctx, f"📢 Send the message to broadcast to <b>{'ALL' if a[0] == 'all' else 'ACTIVE (24h)'}</b> users.\n/cancel to abort.")


@akey("pending")
async def a_pending(update, ctx):
    chat = update.effective_chat.id
    pays = all_("SELECT * FROM payments WHERE status='pending' ORDER BY id LIMIT 20")
    ords = all_("SELECT * FROM orders WHERE status='pending' ORDER BY id LIMIT 20")
    if not pays and not ords:
        await say(update, ctx, "✅ Nothing pending.")
        return
    await say(update, ctx, f"📋 Pending payments: {len(pays)} | Pending orders: {len(ords)}")
    for p in pays:
        await send(ctx, chat, f"💳 <b>Payment #{p['id']}</b>\n👤 <code>{p['uid']}</code>\n{METHODS[p['method']][1]} — ৳{money(p['amount'])}\n🧾 TrxID: <code>{esc(p['trx'])}</code>\n🕐 {dts(p['created'])}",
                   IM([[ib("✅ Approve", f"pay:ok:{p['id']}", "success"), ib("❌ Reject", f"pay:no:{p['id']}", "danger")]]))
    for o in ords:
        await send(ctx, chat, f"📦 <b>Order #{o['id']}</b>\n👤 <code>{o['uid']}</code>\n{esc(o['name'])} — {money(o['price'])}TK\n🕐 {dts(o['created'])}",
                   IM([[ib("📦 Deliver", f"dl:{o['id']}", "success")]]))


@cb("pay", admin=True)
async def c_pay(update, ctx, a):
    ok, pid = a[0] == "ok", int(a[1])
    p = one("SELECT * FROM payments WHERE id=?", (pid,))
    if not p or p["status"] != "pending":
        await alert(update, ctx, "⚠️ Already processed.")
        return
    run("UPDATE payments SET status=?, decided=? WHERE id=?", ("approved" if ok else "rejected", now(), pid))
    if ok:
        run("UPDATE users SET balance=balance+? WHERE uid=?", (p["amount"], p["uid"]))
        await notify_user(ctx, p["uid"], f"✅ Your deposit of <b>৳{money(p['amount'])}</b> was approved. Balance updated!")
    else:
        await notify_user(ctx, p["uid"], f"❌ Your deposit of ৳{money(p['amount'])} (TrxID {esc(p['trx'])}) was rejected. Contact support if this is a mistake.")
    await tolog(ctx, "deposit", f"#{pid} {p['uid']} ৳{money(p['amount'])} {'APPROVED' if ok else 'REJECTED'}")
    try:
        await update.callback_query.edit_message_text(update.callback_query.message.text_html + f"\n\n{'✅ Approved' if ok else '❌ Rejected'}", parse_mode=HTML)
    except TelegramError:
        pass


@cb("dl", admin=True)
async def c_dl(update, ctx, a):
    o = one("SELECT * FROM orders WHERE id=?", (int(a[0]),))
    if not o or o["status"] != "pending":
        await alert(update, ctx, "⚠️ Order already delivered / not found.")
        return
    ctx.user_data["st"] = f"send:{o['id']}"
    await say(update, ctx, f"📦 Send the delivery details for <b>order #{o['id']}</b> ({esc(o['name'])}) — user <code>{o['uid']}</code>:\n(/cancel to stop)")


@akey("sendprod")
async def a_sendprod(update, ctx):
    ords = all_("SELECT * FROM orders WHERE status='pending' ORDER BY id LIMIT 20")
    if not ords:
        await say(update, ctx, "✅ No pending orders.\nManual send: <code>/sendproduct uid details</code>")
        return
    rows = [[ib(f"📦 #{o['id']} {o['name'][:25]} → {o['uid']}", f"dl:{o['id']}", CYCLE[i % 3])] for i, o in enumerate(ords)]
    await say(update, ctx, "📦 Pending orders — tap one to deliver:\n(or <code>/sendproduct uid details</code>)", IM(rows))


@akey("delivered")
async def a_delivered(update, ctx):
    rows = all_("SELECT * FROM orders WHERE status='delivered' ORDER BY id DESC LIMIT 25")
    txt = "📬 <b>Delivered (last 25)</b>\n\n" + ("\n".join(f"✅ #{o['id']} {esc(o['name'])} → <code>{o['uid']}</code> {money(o['price'])}TK ({dts(o['delivered'])})" for o in rows) or "None yet.")
    await send_long(ctx, update.effective_chat.id, txt)


def users_page(page):
    per = 15
    total = cnt("SELECT COUNT(*) FROM users")
    pages = max(1, -(-total // per))
    page = max(0, min(page, pages - 1))
    rows = all_("SELECT * FROM users ORDER BY joined DESC LIMIT ? OFFSET ?", (per, page * per))
    txt = f"👥 <b>Users</b> (Page {page + 1}/{pages}) — {total}\n\n" + "\n".join(
        f"<code>{r['uid']}</code> {esc(r['name'])[:18]} {('@' + esc(r['username'])) if r['username'] else ''} — {r['balance']:.2f}TK" for r in rows)
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"ul:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"ul:{page + 1}", "primary"))
    return txt, IM([nav] if nav else [])


@akey("users")
async def a_users(update, ctx):
    t, m = users_page(0)
    await say(update, ctx, t, m)


@cb("ul", admin=True)
async def c_ul(update, ctx, a):
    t, m = users_page(int(a[0]))
    await show(update, ctx, t, m)


@akey("total")
async def a_total(update, ctx):
    await say(update, ctx, f"👥 Total users: <b>{cnt('SELECT COUNT(*) FROM users')}</b>\n🟢 Active 24h: {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (now() - 86400,))}\n🚫 Banned: {cnt('SELECT COUNT(*) FROM users WHERE banned=1')}")


@akey("refertop")
async def a_refertop(update, ctx):
    rows = all_("SELECT ref_by, COUNT(*) c FROM users WHERE ref_by>0 AND refer_paid=1 GROUP BY ref_by ORDER BY c DESC LIMIT 10")
    lines = []
    for i, r in enumerate(rows, 1):
        u = user(r["ref_by"])
        lines.append(f"{i}. <code>{r['ref_by']}</code> {esc(u['name']) if u else ''} — {r['c']} refers | {u['refer_balance']:.2f}TK" if u else f"{i}. {r['ref_by']} — {r['c']}")
    await say(update, ctx, "👥 <b>Refer Top</b>\n\n" + ("\n".join(lines) or "No referrals yet."))


@akey("reset")
async def a_reset(update, ctx):
    ctx.user_data.clear()
    await say(update, ctx, panel_text(), admin_kb())


@akey("paystats")
async def a_paystats(update, ctx):
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    lines = []
    for k, (e, n) in METHODS.items():
        r = one("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM payments WHERE method=? AND status='approved'", (k,))
        lines.append(f"{e} {n}: {r['c']} deposits — ৳{money(r['s'])}")
    tt = one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE status='approved'")["s"]
    td = one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE status='approved' AND decided>?", (today,))["s"]
    await say(update, ctx, "⚡ <b>Online Payment Stats</b>\n\n" + "\n".join(lines) +
              f"\n\n💰 Total approved: ৳{money(tt)}\n📅 Today: ৳{money(td)}\n⏳ Pending: {cnt('SELECT COUNT(*) FROM payments WHERE status=?', ('pending',))}\n"
              f"❌ Rejected: {cnt('SELECT COUNT(*) FROM payments WHERE status=?', ('rejected',))}")


async def a_jointest(update, ctx):
    ch = S("channel")
    if not ch:
        await say(update, ctx, "⚠️ No channel is set. Use 📢 Channel first.")
        return
    out = [f"🔍 <b>Join Test</b> — {esc(ch)}"]
    try:
        c = await ctx.bot.get_chat(chat_ref(ch))
        out.append(f"✅ Channel found: {esc(c.title)}")
        me = await ctx.bot.get_chat_member(chat_ref(ch), ctx.bot.id)
        out.append(f"{'✅' if me.status in ('administrator', 'creator') else '⚠️'} Bot status: {me.status} (must be administrator)")
        m = await ctx.bot.get_chat_member(chat_ref(ch), update.effective_user.id)
        out.append(f"✅ Your status: {m.status}")
    except TelegramError as e:
        out.append(f"❌ Error: {esc(e)}")
    await say(update, ctx, "\n".join(out))


A["jointest"] = a_jointest


@akey("joinlogs")
async def a_joinlogs(update, ctx):
    rows = all_("SELECT * FROM logs WHERE kind='join' ORDER BY id DESC LIMIT 30")
    await send_long(ctx, update.effective_chat.id, "📋 <b>Join Logs</b>\n\n" + ("\n".join(f"{dts(r['ts'])} — {esc(r['text'])}" for r in rows) or "No joins logged yet."))


@akey("notifyprod")
async def a_notifyprod(update, ctx):
    ctx.user_data["st"] = "pfind:np"
    await say(update, ctx, "📢 Send the product <b>ID or name</b> to announce to all users:")


@akey("timechecks")
async def a_timechecks(update, ctx):
    d = dt.datetime.now(TZ)
    u = dt.datetime.now(dt.timezone.utc)
    up = int(time.time() - START_TS)
    await say(update, ctx, f"👥 <b>Time Checks</b>\n\n🇧🇩 Dhaka: {d:%Y-%m-%d %H:%M:%S}\n🌍 UTC: {u:%Y-%m-%d %H:%M:%S}\n⏱ Bot uptime: {up // 3600}h {up % 3600 // 60}m\n"
              f"🟢 Active now (5 min): {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (now() - 300,))}")


@akey("timelive")
async def a_timelive(update, ctx):
    m = await say(update, ctx, "⏳")

    async def loop():
        for _ in range(20):
            try:
                await m.edit_text(time_text() + "\n\n🔴 LIVE", parse_mode=HTML)
            except TelegramError:
                pass
            await asyncio.sleep(1)
    ctx.application.create_task(loop())


def autofix():
    rep = []
    n = run("UPDATE users SET balance=0 WHERE balance<0").rowcount
    rep.append(f"negative balances fixed: {n}")
    run("UPDATE users SET total_orders=(SELECT COUNT(*) FROM orders o WHERE o.uid=users.uid), "
        "total_spent=(SELECT COALESCE(SUM(price),0) FROM orders o WHERE o.uid=users.uid)")
    rep.append("user order totals recalculated")
    orphans = cnt("SELECT COUNT(*) FROM products WHERE cat_id NOT IN (SELECT id FROM categories)")
    if orphans:
        run("INSERT OR IGNORE INTO categories(name) VALUES('📦 Others')")
        oid = one("SELECT id FROM categories WHERE name='📦 Others'")["id"]
        run("UPDATE products SET cat_id=? WHERE cat_id NOT IN (SELECT id FROM categories)", (oid,))
    rep.append(f"orphan products moved: {orphans}")
    n = run("DELETE FROM stock WHERE sold=0 AND pid NOT IN (SELECT id FROM products)").rowcount
    rep.append(f"orphan stock removed: {n}")
    n = run("UPDATE payments SET status='cancelled' WHERE status='created' AND created<?", (now() - 86400,)).rowcount
    rep.append(f"stale invoices closed: {n}")
    n = run("UPDATE orders SET status='pending' WHERE status NOT IN ('pending','delivered')").rowcount
    rep.append(f"bad order states fixed: {n}")
    setS("autofix_last", f"{dts(now(), '%Y-%m-%d %H:%M')} — " + "; ".join(rep))
    setS("autofix_runs", int(Sf("autofix_runs")) + 1)
    return rep


@akey("autofix")
async def a_autofix(update, ctx):
    await say(update, ctx, "🛠 <b>Auto-Fix done</b>\n\n" + "\n".join("• " + r for r in autofix()))


@akey("autofixstats")
async def a_autofixstats(update, ctx):
    await say(update, ctx, f"📊 <b>Auto-Fix Stats</b>\n\nRuns: {int(Sf('autofix_runs'))}\nLast: {esc(S('autofix_last'))}\n(Runs automatically every 6 hours.)")


@akey("adsstatus")
async def a_adsstatus(update, ctx):
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = one("SELECT COUNT(*) c, COALESCE(SUM(reward),0) s FROM ad_views")
    t = one("SELECT COUNT(*) c, COALESCE(SUM(reward),0) s FROM ad_views WHERE ts>?", (today,))
    top = all_("SELECT uid, COUNT(*) c FROM ad_views GROUP BY uid ORDER BY c DESC LIMIT 5")
    await say(update, ctx, f"📊 <b>Ads Status</b>\n\nAd configured: {'✅' if (S('ad_text') or S('ad_url')) else '❌'}\nTotal views: {r['c']} (paid ৳{money(r['s'])})\n"
              f"Today: {t['c']} (৳{money(t['s'])})\n🔒 Locked users: {cnt('SELECT COUNT(*) FROM users WHERE ads_lock=1')}\n\n🏆 Top: " +
              (", ".join(f"{x['uid']}({x['c']})" for x in top) or "—"))


@akey("active")
async def a_active(update, ctx):
    n = now()
    await say(update, ctx, "👥 <b>Active Users</b>\n\n"
              f"🟢 Last 5 min: {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (n - 300,))}\n"
              f"🕐 Last hour: {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (n - 3600,))}\n"
              f"📅 Last 24h: {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (n - 86400,))}\n"
              f"🗓 Last 7 days: {cnt('SELECT COUNT(*) FROM users WHERE last_active>?', (n - 7 * 86400,))}")


@akey("activedetail")
async def a_activedetail(update, ctx):
    rows = all_("SELECT * FROM users WHERE last_active>? ORDER BY last_active DESC LIMIT 40", (now() - 86400,))
    await send_long(ctx, update.effective_chat.id, "📄 <b>Active (24h)</b>\n\n" + ("\n".join(
        f"<code>{r['uid']}</code> {esc(r['name'])[:16]} {('@' + esc(r['username'])) if r['username'] else ''} — {(now() - r['last_active']) // 60}m ago" for r in rows) or "None."))


@akey("adslock")
async def a_adslock(update, ctx):
    ctx.user_data["st"] = "adslock:1"
    await say(update, ctx, "🔐 Send the user ID (or @username) to <b>lock</b> from Watch Ad:")


@akey("unlock")
async def a_unlock(update, ctx):
    ctx.user_data["st"] = "adslock:0"
    await say(update, ctx, "🔓 Send the user ID (or @username) to <b>unlock</b> (ads + ban):")


@akey("allprodcheck")
async def a_allprodcheck(update, ctx):
    rows = all_("SELECT p.*, c.name cname FROM products p LEFT JOIN categories c ON c.id=p.cat_id ORDER BY p.id")
    names = {}
    for r in rows:
        names[r["name"].lower()] = names.get(r["name"].lower(), 0) + 1
    issues = []
    for r in rows:
        pr = []
        if not r["image"]:
            pr.append("no image")
        if r["price"] <= 0:
            pr.append("price ≤ 0")
        if names[r["name"].lower()] > 1:
            pr.append("duplicate name")
        if not r["cname"]:
            pr.append("no category")
        if r["track"] and stock_count(r["id"]) == 0:
            pr.append("out of stock")
        if pr:
            issues.append(f"⚠️ #{r['id']} {esc(r['name'])} — {', '.join(pr)}")
    await send_long(ctx, update.effective_chat.id, f"📦 <b>All Products Check</b>\nTotal: {len(rows)} | Problems: {len(issues)}\n\n" + ("\n".join(issues) or "✅ All good."))


@akey("prodinfo")
async def a_prodinfo(update, ctx):
    lines = [f"{esc(c['name'])}: {cnt('SELECT COUNT(*) FROM products WHERE cat_id=?', (c['id'],))} products" for c in all_("SELECT * FROM categories ORDER BY pos,id")]
    tot = cnt("SELECT COUNT(*) FROM products")
    st = cnt("SELECT COUNT(*) FROM stock WHERE sold=0")
    sold = cnt("SELECT COUNT(*) FROM stock WHERE sold=1")
    await say(update, ctx, f"📊 <b>Products Info</b>\n\nTotal: {tot} | Visible: {cnt('SELECT COUNT(*) FROM products WHERE active=1')}\n🗃 Stock items: {st} available / {sold} sold\n"
              f"💰 Orders: {cnt('SELECT COUNT(*) FROM orders')} — ৳{money(one('SELECT COALESCE(SUM(price),0) s FROM orders')['s'])}\n\n" + "\n".join(lines))


async def send_users_csv(ctx, chat):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["uid", "username", "name", "balance", "refer_balance", "orders", "spent", "ref_by", "banned", "joined", "last_active"])
    for r in all_("SELECT * FROM users ORDER BY joined"):
        w.writerow([r["uid"], r["username"], r["name"], r["balance"], r["refer_balance"], r["total_orders"], r["total_spent"], r["ref_by"], r["banned"], dts(r["joined"]), dts(r["last_active"])])
    f = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    f.name = "users.csv"
    await ctx.bot.send_document(chat, f, caption=f"👥 {cnt('SELECT COUNT(*) FROM users')} users")


@akey("allusers")
async def a_allusers(update, ctx):
    await send_users_csv(ctx, update.effective_chat.id)


@akey("userinfo")
async def a_userinfo(update, ctx):
    ctx.user_data["st"] = "uinfo"
    await say(update, ctx, "🔍 Send the user ID or @username:")


@akey("welcome")
async def a_welcome(update, ctx):
    await c_set(update, ctx, ["welcome_bonus"])


@akey("id")
async def a_id(update, ctx):
    await m_id(update, ctx)


@akey("usermenu")
async def a_usermenu(update, ctx):
    await say(update, ctx, "👤 User menu", main_menu())


def find_user(term):
    term = term.strip().lstrip("@")
    if term.lstrip("-").isdigit():
        return user(int(term))
    return one("SELECT * FROM users WHERE lower(username)=lower(?)", (term,))


def user_card(u):
    inv = cnt("SELECT COUNT(*) FROM users WHERE ref_by=?", (u["uid"],))
    txt = (f"👤 <b>User Info</b>\n━━━━━━━━━━━━━━\n🆔 <code>{u['uid']}</code>\n👤 {esc(u['name'])} {('@' + esc(u['username'])) if u['username'] else ''}\n"
           f"💵 Balance: {u['balance']:.2f} TK\n🎁 Refer balance: {u['refer_balance']:.2f} TK\n🚀 Orders: {u['total_orders']} ({u['total_spent']:.2f} TK)\n"
           f"👥 Invited: {inv} | Referred by: {u['ref_by'] or '-'}\n📱 Phone: {esc(u['phone']) or '-'}\n"
           f"🚫 Banned: {'Yes' if u['banned'] else 'No'} | 🔒 Ads lock: {'Yes' if u['ads_lock'] else 'No'}\n"
           f"🕐 Joined: {dts(u['joined'])}\n🟢 Last active: {dts(u['last_active'])}")
    i = u["uid"]
    return txt, IM([[ib("➕ Add Bal", f"bal:add:{i}", "success"), ib("➖ Remove Bal", f"bal:rem:{i}", "danger")],
                    [ib("✅ Unban" if u["banned"] else "🚫 Ban", f"ub:{i}", "primary"),
                     ib("🔓 Ads Unlock" if u["ads_lock"] else "🔒 Ads Lock", f"ua:{i}", "danger")],
                    [ib("📦 Orders", f"uo:{i}", "success")]])


@cb("ub", admin=True)
async def c_ub(update, ctx, a):
    u = user(int(a[0]))
    run("UPDATE users SET banned=? WHERE uid=?", (0 if u["banned"] else 1, u["uid"]))
    t, m = user_card(user(u["uid"]))
    await show(update, ctx, t, m)


@cb("ua", admin=True)
async def c_ua(update, ctx, a):
    u = user(int(a[0]))
    run("UPDATE users SET ads_lock=? WHERE uid=?", (0 if u["ads_lock"] else 1, u["uid"]))
    t, m = user_card(user(u["uid"]))
    await show(update, ctx, t, m)


@cb("bal", admin=True)
async def c_bal(update, ctx, a):
    ctx.user_data["st"] = f"bal:{a[0]}:{a[1]}"
    await say(update, ctx, f"💵 Send the amount to <b>{'add to' if a[0] == 'add' else 'remove from'}</b> user <code>{a[1]}</code>:")


@cb("uo", admin=True)
async def c_uo(update, ctx, a):
    rows = all_("SELECT * FROM orders WHERE uid=? ORDER BY id DESC LIMIT 15", (int(a[0]),))
    await send_long(ctx, update.effective_chat.id, f"📦 Orders of <code>{a[0]}</code>\n\n" + ("\n".join(f"{'✅' if o['status'] == 'delivered' else '⏳'} #{o['id']} {esc(o['name'])} {money(o['price'])}TK {dts(o['created'])}" for o in rows) or "None."))


async def bal_change(ctx, uid, amt):
    u = user(uid)
    if not u:
        return None
    run("UPDATE users SET balance=MAX(0, balance+?) WHERE uid=?", (amt, uid))
    await notify_user(ctx, uid, f"{'➕' if amt >= 0 else '➖'} Admin {'added' if amt >= 0 else 'removed'} <b>{money(abs(amt))}৳</b> {'to' if amt >= 0 else 'from'} your balance.")
    await tolog(ctx, "balance", f"{uid} {'+' if amt >= 0 else ''}{money(amt)}")
    return user(uid)["balance"]


# ---- button rename ---------------------------------------------------------
@cb("brk", admin=True)
async def c_brk(update, ctx, a):
    ctx.user_data["st"] = f"brn:{a[0]}"
    await say(update, ctx, f"🔤 Send the new name for <b>{esc(label(a[0]))}</b> (emoji allowed):")


@cb("brr", admin=True)
async def c_brr(update, ctx, a):
    run("DELETE FROM labels")
    await send_screen(update, ctx, "btnrename", edit=True)


# ---- categories ------------------------------------------------------------
@cb("cma", admin=True)
async def c_cma(update, ctx, a):
    ctx.user_data["st"] = "addcat"
    await say(update, ctx, "🗂 Send the new category name (emoji allowed), e.g. <code>⭐ Star Jalsha</code>:")


@cb("cmv", admin=True)
async def c_cmv(update, ctx, a):
    c = one("SELECT * FROM categories WHERE id=?", (int(a[0]),))
    if not c:
        return
    await show(update, ctx, f"🗂 <b>{esc(c['name'])}</b>\nProducts: {cnt('SELECT COUNT(*) FROM products WHERE cat_id=?', (c['id'],))}",
               IM([[ib("✏️ Rename", f"cmr:{c['id']}", "primary"), ib("⬆️ Move Up", f"cmu:{c['id']}", "success")],
                   [ib("🗑 Delete", f"cmd:{c['id']}", "danger"), ib("⬅️ Back", "sc:cats", "primary")]]))


@cb("cmr", admin=True)
async def c_cmr(update, ctx, a):
    ctx.user_data["st"] = f"rencat:{a[0]}"
    await say(update, ctx, "✏️ Send the new category name:")


@cb("cmu", admin=True)
async def c_cmu(update, ctx, a):
    cs = all_("SELECT * FROM categories ORDER BY pos, id")
    for i, c in enumerate(cs):
        run("UPDATE categories SET pos=? WHERE id=?", (i * 2, c["id"]))
    cid = int(a[0])
    run("UPDATE categories SET pos=pos-3 WHERE id=?", (cid,))
    await send_screen(update, ctx, "cats", edit=True)


@cb("cmd", admin=True)
async def c_cmd(update, ctx, a):
    await show(update, ctx, "🗑 Delete this category? Its products move to <b>📦 Others</b>.",
               IM([[ib("✅ Yes, delete", f"cmdy:{a[0]}", "danger"), ib("❌ No", "sc:cats", "success")]]))


@cb("cmdy", admin=True)
async def c_cmdy(update, ctx, a):
    cid = int(a[0])
    if cnt("SELECT COUNT(*) FROM products WHERE cat_id=?", (cid,)):
        run("INSERT OR IGNORE INTO categories(name) VALUES('📦 Others')")
        oid = one("SELECT id FROM categories WHERE name='📦 Others'")["id"]
        if oid != cid:
            run("UPDATE products SET cat_id=? WHERE cat_id=?", (oid, cid))
    run("DELETE FROM categories WHERE id=?", (cid,))
    await send_screen(update, ctx, "cats", edit=True)


# ---- products --------------------------------------------------------------
def parse_prod(s):
    s = s.strip()
    parts = [x.strip() for x in (s.split("|") if "|" in s else s.rsplit("_", 2))]
    if len(parts) < 2:
        return None
    try:
        price = float(parts[1].replace("৳", "").replace("TK", "").strip())
    except ValueError:
        return None
    return parts[0], price, (parts[2] if len(parts) > 2 else "")


def add_product(cat, name, price, img=""):
    return run("INSERT INTO products(cat_id,name,price,image,added) VALUES(?,?,?,?,?)", (cat, name, price, img, now())).lastrowid


def default_cat():
    run("INSERT OR IGNORE INTO categories(name) VALUES('📦 Others')")
    return one("SELECT id FROM categories WHERE name='📦 Others'")["id"]


async def finish_add(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    await say(update, ctx, f"✅ <b>Product added</b>\n#{pid} {esc(p['name'])} — {money(p['price'])}TK\n\nNow add its stock (serials / accounts / codes):",
              IM([[ib("➕ Add Stock", f"ska:{pid}", "success"), ib("✏️ Edit", f"ep:{pid}", "primary")]]))
    un = (await ctx.bot.get_me()).username
    text = f"📦 <b>{esc(p['name'])}</b>\n💰 {money(p['price'])} TK\n\n🛒 Buy now from @{un}"
    if S("autopost") == "1" and S("channel"):
        try:
            await send(ctx, chat_ref(S("channel")), text, IM([[ib("🛒 Buy Now", url=f"https://t.me/{un}?start=p{pid}", style="success")]]), p["image"] or None)
        except TelegramError as e:
            await say(update, ctx, f"⚠️ Auto-post failed: {esc(e)}")
    if S("notify_new") == "1":
        async def sender(uid):
            await send(ctx, uid, text, IM([[ib("🛒 Open", f"pp:{pid}", "success")]]), p["image"] or None)
        ctx.application.create_task(run_broadcast(ctx, update.effective_chat.id, targets_for("all"), sender))


@akey("addprod")
async def a_addprod(update, ctx):
    cs = all_("SELECT * FROM categories ORDER BY pos, id")
    if not cs:
        await say(update, ctx, "🗂 Create a category first.", IM([[ib("➕ Add Category", "cma", "success")]]))
        return
    await say(update, ctx, "➕ <b>Add Product</b>\nChoose the category:", IM(grid([(c["name"], f"ap:{c['id']}") for c in cs], 2)))


@cb("ap", admin=True)
async def c_ap(update, ctx, a):
    ctx.user_data["st"] = f"apn:{a[0]}"
    await say(update, ctx, "✍️ Send: <code>Serial Name | Price | Image link (optional)</code>\nExample: <code>Kothha ( Star Jalsha ) | 450</code>\n(/cancel to stop)")


def prod_card(p):
    c = one("SELECT name FROM categories WHERE id=?", (p["cat_id"],))
    txt = (f"✏️ <b>Product #{p['id']}</b>\n\n📛 {esc(p['name'])}\n💰 {money(p['price'])} TK\n🗂 {esc(c['name']) if c else '—'}\n"
           f"🖼 Image: {'yes' if p['image'] else 'no'}\n👁 Visible: {'yes' if p['active'] else 'no'}\n🗃 {stock_line(p)}")
    return txt, IM([[ib("✏️ Name", f"ef:name:{p['id']}", "primary"), ib("💰 Price", f"ef:price:{p['id']}", "success")],
                    [ib("🖼 Image", f"ef:image:{p['id']}", "danger"), ib("🗂 Category", f"efc:{p['id']}", "primary")],
                    [ib("📦 Stock", f"sk:{p['id']}", "success"), ib("🙈 Hide" if p["active"] else "👁 Show", f"et:{p['id']}", "danger")],
                    [ib("🗑 Delete", f"ed:{p['id']}", "danger")]])


def find_products(term):
    term = term.strip()
    if term.lstrip("#").isdigit():
        r = one("SELECT * FROM products WHERE id=?", (int(term.lstrip("#")),))
        return [r] if r else []
    return all_("SELECT * FROM products WHERE name LIKE ? ORDER BY id DESC LIMIT 10", (f"%{term}%",))


async def pick_product(update, ctx, purpose, term):
    res = find_products(term)
    if not res:
        await say(update, ctx, "😕 No product found. Try another ID/name (or /cancel).")
        ctx.user_data["st"] = f"pfind:{purpose}"
        return
    if len(res) == 1:
        await after_pick(update, ctx, purpose, res[0]["id"])
        return
    await say(update, ctx, "Choose a product:", IM([[ib(f"#{p['id']} {p['name'][:30]}", f"pk:{purpose}:{p['id']}", CYCLE[i % 3])] for i, p in enumerate(res)]))


async def after_pick(update, ctx, purpose, pid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    if purpose == "ep":
        t, m = prod_card(p)
        await say(update, ctx, t, m)
    elif purpose == "dp":
        await say(update, ctx, f"🗑 Delete <b>{esc(p['name'])}</b> (and its stock)?", IM([[ib("✅ Yes", f"edy:{pid}", "danger"), ib("❌ No", "noop2", "success")]]))
    elif purpose == "sk":
        await stock_card(update, ctx, pid)
    elif purpose == "np":
        await send_np(update, ctx, pid)


@cb("pk", admin=True)
async def c_pk(update, ctx, a):
    await after_pick(update, ctx, a[0], int(a[1]))


@cb("noop2", admin=True)
async def c_noop2(update, ctx, a):
    await show(update, ctx, "👍 Okay.")


async def send_np(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    text = f"📢 <b>{esc(p['name'])}</b>\n💰 {money(p['price'])} TK\n{stock_line(p)}"

    async def sender(uid):
        await send(ctx, uid, text, IM([[ib("🛒 Open", f"pp:{pid}", "success")]]), p["image"] or None)
    await say(update, ctx, "📢 Announcing to all users…")
    ctx.application.create_task(run_broadcast(ctx, update.effective_chat.id, targets_for("all"), sender))


@akey("editprod")
async def a_editprod(update, ctx):
    ctx.user_data["st"] = "pfind:ep"
    await say(update, ctx, "✏️ Send the product <b>ID or name</b>:")


@akey("delprod")
async def a_delprod(update, ctx):
    ctx.user_data["st"] = "pfind:dp"
    await say(update, ctx, "🗑 Send the product <b>ID or name</b> to delete:")


@cb("ep", admin=True)
async def c_ep(update, ctx, a):
    p = one("SELECT * FROM products WHERE id=?", (int(a[0]),))
    if p:
        t, m = prod_card(p)
        await show(update, ctx, t, m)


@cb("ef", admin=True)
async def c_ef(update, ctx, a):
    ctx.user_data["st"] = f"ef:{a[0]}:{a[1]}"
    hint = {"name": "new name", "price": "new price", "image": "an image link or send a photo"}[a[0]]
    await say(update, ctx, f"✍️ Send the {hint}:\n(/cancel to stop)")


@cb("efc", admin=True)
async def c_efc(update, ctx, a):
    cs = all_("SELECT * FROM categories ORDER BY pos, id")
    await show(update, ctx, "🗂 Choose the new category:", IM(grid([(c["name"], f"ec:{a[0]}:{c['id']}") for c in cs], 2)))


@cb("ec", admin=True)
async def c_ec(update, ctx, a):
    run("UPDATE products SET cat_id=? WHERE id=?", (int(a[1]), int(a[0])))
    t, m = prod_card(one("SELECT * FROM products WHERE id=?", (int(a[0]),)))
    await show(update, ctx, t, m)


@cb("et", admin=True)
async def c_et(update, ctx, a):
    p = one("SELECT * FROM products WHERE id=?", (int(a[0]),))
    run("UPDATE products SET active=? WHERE id=?", (0 if p["active"] else 1, p["id"]))
    t, m = prod_card(one("SELECT * FROM products WHERE id=?", (p["id"],)))
    await show(update, ctx, t, m)


@cb("ed", admin=True)
async def c_ed(update, ctx, a):
    await show(update, ctx, "🗑 Delete this product (and its stock)?", IM([[ib("✅ Yes", f"edy:{a[0]}", "danger"), ib("❌ No", f"ep:{a[0]}", "success")]]))


@cb("edy", admin=True)
async def c_edy(update, ctx, a):
    pid = int(a[0])
    run("DELETE FROM stock WHERE pid=? AND sold=0", (pid,))
    run("DELETE FROM products WHERE id=?", (pid,))
    await show(update, ctx, f"🗑 Product #{pid} deleted.")


# ---- stock manager ---------------------------------------------------------
async def stock_card(update, ctx, pid, edit=False):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        await say(update, ctx, "❌ Product not found.")
        return
    av = stock_count(pid)
    sold = cnt("SELECT COUNT(*) FROM stock WHERE pid=? AND sold=1", (pid,))
    txt = (f"📦 <b>Stock — {esc(p['name'])}</b> (ID {pid})\n\nMode: <b>{'Auto-delivery from stock' if p['track'] else 'Manual delivery (unlimited)'}</b>\n"
           f"✅ Available: <b>{av}</b>\n💸 Sold: {sold}")
    m = IM([[ib("➕ Add Stock", f"ska:{pid}", "success"), ib("📋 View", f"skv:{pid}", "primary")],
            [ib("🗑 Clear Unsold", f"skc:{pid}", "danger"), ib("🔁 Switch Mode", f"skm:{pid}", "primary")],
            [ib("⬅️ Stock List", "sm:0", "success")]])
    await (show if edit else say)(update, ctx, txt, m)


@akey("stock")
async def a_stock(update, ctx):
    t, m = stock_list(0)
    await say(update, ctx, t, m)


def stock_list(page):
    per = 8
    total = cnt("SELECT COUNT(*) FROM products")
    pages = max(1, -(-total // per))
    page = max(0, min(page, pages - 1))
    rows = all_("SELECT * FROM products ORDER BY id DESC LIMIT ? OFFSET ?", (per, page * per))
    btns = [[ib(f"{'♾' if not p['track'] else ('❌' if stock_count(p['id']) == 0 else '✅')} {p['name'][:26]} ({'∞' if not p['track'] else stock_count(p['id'])})",
                f"sk:{p['id']}", CYCLE[i % 3])] for i, p in enumerate(rows)]
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"sm:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"sm:{page + 1}", "primary"))
    if nav:
        btns.append(nav)
    btns.append([ib("🔎 Find product to add stock", "skfind", "success"), ib("⚠️ Low Stock", "slow", "danger")])
    return (f"📦 <b>Stock Manager</b> (Page {page + 1}/{pages})\nTotal stock items available: <b>{cnt('SELECT COUNT(*) FROM stock WHERE sold=0')}</b>\n"
            "✅ in stock  ❌ out of stock  ♾ manual", IM(btns))


@cb("sm", admin=True)
async def c_sm(update, ctx, a):
    t, m = stock_list(int(a[0]))
    await show(update, ctx, t, m)


@cb("sk", admin=True)
async def c_sk(update, ctx, a):
    await stock_card(update, ctx, int(a[0]), edit=True)


@cb("skfind", admin=True)
async def c_skfind(update, ctx, a):
    ctx.user_data["st"] = "pfind:sk"
    await say(update, ctx, "🔎 Send the product <b>ID or name</b>:")


@cb("ska", admin=True)
async def c_ska(update, ctx, a):
    ctx.user_data["st"] = f"stk:{a[0]}"
    await say(update, ctx, "➕ <b>Add stock</b>\nSend the items — <b>one per line</b> (serial / account / code / link).\n"
                           "For multi-line items separate them with a line containing <code>---</code>.\n"
                           "You can also upload a <b>.txt</b> file. Send /done when finished.")


@cb("skv", admin=True)
async def c_skv(update, ctx, a):
    rows = all_("SELECT * FROM stock WHERE pid=? AND sold=0 ORDER BY id LIMIT 10", (int(a[0]),))
    await say(update, ctx, f"📋 <b>Next {len(rows)} items to be sold</b> (of {stock_count(int(a[0]))})\n\n" + ("\n".join(f"{i}. <code>{esc(r['data'][:60])}</code>" for i, r in enumerate(rows, 1)) or "Empty."))


@cb("skc", admin=True)
async def c_skc(update, ctx, a):
    await show(update, ctx, f"🗑 Delete ALL {stock_count(int(a[0]))} unsold items of this product?", IM([[ib("✅ Yes, clear", f"skcy:{a[0]}", "danger"), ib("❌ No", f"sk:{a[0]}", "success")]]))


@cb("skcy", admin=True)
async def c_skcy(update, ctx, a):
    run("DELETE FROM stock WHERE pid=? AND sold=0", (int(a[0]),))
    await stock_card(update, ctx, int(a[0]), edit=True)


@cb("skm", admin=True)
async def c_skm(update, ctx, a):
    p = one("SELECT * FROM products WHERE id=?", (int(a[0]),))
    run("UPDATE products SET track=? WHERE id=?", (0 if p["track"] else 1, p["id"]))
    await stock_card(update, ctx, p["id"], edit=True)


async def low_stock_report(update, ctx):
    lvl = int(Sf("low_stock"))
    rows = [p for p in all_("SELECT * FROM products WHERE track=1 AND active=1 ORDER BY id") if stock_count(p["id"]) <= lvl]
    txt = f"⚠️ <b>Low / Out of stock</b> (≤ {lvl})\n\n" + ("\n".join(f"{'❌' if stock_count(p['id']) == 0 else '⚠️'} #{p['id']} {esc(p['name'])} — {stock_count(p['id'])} left" for p in rows) or "✅ All products have enough stock.")
    await send_long(ctx, update.effective_chat.id, txt, IM([[ib("⚙️ Set Alert Level", "set:low_stock", "primary")]]))


@akey("lowstock")
async def a_lowstock(update, ctx):
    await low_stock_report(update, ctx)


@cb("slow", admin=True)
async def c_slow(update, ctx, a):
    await low_stock_report(update, ctx)


# ----------------------------------------------------------------------------
# STATE MACHINE (text answers)
# ----------------------------------------------------------------------------
async def handle_state(update, ctx, st, text):
    uid = update.effective_user.id
    p = st.split(":")
    k = p[0]
    user_states = {"search", "dep_amt", "trx"}
    if k not in user_states and not is_admin(uid):
        ctx.user_data.pop("st", None)
        return

    # ----- user states
    if k == "search":
        ctx.user_data.pop("st", None)
        ctx.user_data["sq"] = text[:50]
        await view_list(update, ctx, -1, 0)
    elif k == "dep_amt":
        try:
            amt = float(text.replace(",", "").replace("৳", ""))
        except ValueError:
            await say(update, ctx, "❌ Please send a valid number.")
            return
        if amt < Sf("min_deposit"):
            await say(update, ctx, f"❌ Minimum deposit is ৳{money(Sf('min_deposit'))}.")
            return
        d = ctx.user_data.get("dep")
        ctx.user_data.pop("st", None)
        if d:
            d["amt"] = amt
        await view_dep(update, ctx)
    elif k == "trx":
        pay = one("SELECT * FROM payments WHERE id=?", (int(p[1]),))
        if not pay or pay["status"] != "created":
            ctx.user_data.pop("st", None)
            return
        trx = text.strip()
        if len(trx) < 6 or len(trx) > 64 or " " in trx:
            await say(update, ctx, "❌ That doesn't look like a valid TrxID. Send it again (or /cancel).")
            return
        if one("SELECT id FROM payments WHERE trx=? AND status IN ('pending','approved')", (trx,)):
            await say(update, ctx, "❌ This TrxID was already used.")
            return
        run("UPDATE payments SET trx=?, status='pending' WHERE id=?", (trx, pay["id"]))
        ctx.user_data.pop("st", None)
        ctx.user_data.pop("dep", None)
        await say(update, ctx, "✅ TrxID received! Your balance will be added once an admin approves.")
        u = user(uid)
        await notify_admins(ctx, f"💳 <b>New deposit #{pay['id']}</b>\n👤 <code>{uid}</code> @{esc(u['username'])}\n{METHODS[pay['method']][1]} — ৳{money(pay['amount'])}\n🧾 TrxID: <code>{esc(trx)}</code>",
                            IM([[ib("✅ Approve", f"pay:ok:{pay['id']}", "success"), ib("❌ Reject", f"pay:no:{pay['id']}", "danger")]]))
        await tolog(ctx, "deposit", f"#{pay['id']} {uid} {pay['method']} ৳{money(pay['amount'])} trx={trx} PENDING")

    # ----- admin states
    elif k == "set":
        key = p[1]
        prompt, typ, scr = SET_INFO[key]
        val = text.strip()
        try:
            if typ == "f":
                if float(val) < 0:
                    raise ValueError
            elif typ == "i":
                if int(val) < 0:
                    raise ValueError
            elif typ == "amounts":
                val = ",".join(money(float(x)) for x in val.replace(" ", "").split(",") if x)
                if not val:
                    raise ValueError
            elif typ == "ch":
                if val.lower() in ("off", "none", "clear"):
                    val = ""
                elif not (val.startswith("@") or val.lstrip("-").isdigit()):
                    raise ValueError
        except ValueError:
            await say(update, ctx, "❌ Invalid value. Try again (or /cancel).")
            return
        setS(key, val)
        ctx.user_data.pop("st", None)
        await say(update, ctx, "✅ Updated.")
        if scr:
            await send_screen(update, ctx, scr)
    elif k == "addcat":
        try:
            run("INSERT INTO categories(name,pos) VALUES(?,?)", (text.strip(), cnt("SELECT COUNT(*) FROM categories")))
        except sqlite3.IntegrityError:
            await say(update, ctx, "❌ That category already exists.")
            return
        ctx.user_data.pop("st", None)
        await send_screen(update, ctx, "cats")
    elif k == "rencat":
        try:
            run("UPDATE categories SET name=? WHERE id=?", (text.strip(), int(p[1])))
        except sqlite3.IntegrityError:
            await say(update, ctx, "❌ That name is already used.")
            return
        ctx.user_data.pop("st", None)
        await send_screen(update, ctx, "cats")
    elif k == "apn":
        r = parse_prod(text)
        if not r:
            await say(update, ctx, "❌ Format: <code>Name | Price | Image link(optional)</code>")
            return
        pid = add_product(int(p[1]), *r)
        if r[2]:
            ctx.user_data.pop("st", None)
            await finish_add(update, ctx, pid)
        else:
            ctx.user_data["st"] = f"api:{pid}"
            await say(update, ctx, "🖼 Now send the product <b>photo</b> or an image link — or /skip")
    elif k == "api":
        run("UPDATE products SET image=? WHERE id=?", (text.strip(), int(p[1])))
        ctx.user_data.pop("st", None)
        await finish_add(update, ctx, int(p[1]))
    elif k == "pfind":
        ctx.user_data.pop("st", None)
        await pick_product(update, ctx, p[1], text)
    elif k == "ef":
        field, pid = p[1], int(p[2])
        if field == "price":
            try:
                v = float(text)
            except ValueError:
                await say(update, ctx, "❌ Send a number.")
                return
            run("UPDATE products SET price=? WHERE id=?", (v, pid))
        else:
            run(f"UPDATE products SET {'name' if field == 'name' else 'image'}=? WHERE id=?", (text.strip(), pid))
        ctx.user_data.pop("st", None)
        t, m = prod_card(one("SELECT * FROM products WHERE id=?", (pid,)))
        await say(update, ctx, "✅ Updated.\n\n" + t, m)
    elif k == "stk":
        pid = int(p[1])
        added, dup = add_stock(pid, text)
        await say(update, ctx, f"✅ Added <b>{added}</b> items" + (f" (skipped {dup} duplicates)" if dup else "") +
                  f"\n📦 Available now: <b>{stock_count(pid)}</b>\nSend more, or /done.")
    elif k == "uinfo":
        u = find_user(text)
        if not u:
            await say(update, ctx, "😕 User not found. Send an ID or @username (or /cancel).")
            return
        ctx.user_data.pop("st", None)
        t, m = user_card(u)
        await say(update, ctx, t, m)
    elif k == "adslock":
        u = find_user(text)
        if not u:
            await say(update, ctx, "😕 User not found.")
            return
        lock = p[1] == "1"
        run("UPDATE users SET ads_lock=? WHERE uid=?", (1 if lock else 0, u["uid"]))
        if not lock:
            run("UPDATE users SET banned=0 WHERE uid=?", (u["uid"],))
        ctx.user_data.pop("st", None)
        await say(update, ctx, f"{'🔐 Locked' if lock else '🔓 Unlocked'} <code>{u['uid']}</code>.")
    elif k == "bal":
        try:
            amt = float(text)
        except ValueError:
            await say(update, ctx, "❌ Send a number.")
            return
        nb = await bal_change(ctx, int(p[2]), amt if p[1] == "add" else -amt)
        ctx.user_data.pop("st", None)
        await say(update, ctx, f"✅ Done. New balance: <b>{nb:.2f}</b> TK" if nb is not None else "❌ User not found.")
    elif k == "send":
        oid = int(p[1])
        ctx.user_data.pop("st", None)
        await say(update, ctx, f"✅ Order #{oid} delivered." if await deliver_order(ctx, oid, text) else "❌ Order not found.")
    elif k == "brn":
        new = text.strip()
        taken = {label(x) for x in MENU_LABELS if x != p[1]} | set(alabels().values())
        if not new or len(new) > 40 or new in taken:
            await say(update, ctx, "❌ Invalid or already used name. Try another.")
            return
        run("INSERT INTO labels(key,text) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text", (p[1], new))
        ctx.user_data.pop("st", None)
        await say(update, ctx, "✅ Renamed.", main_menu())
        await send_screen(update, ctx, "btnrename")
    elif k == "bc":
        await say(update, ctx, "⚠️ Please send the broadcast message itself (text/photo/video).")


async def on_text(update, ctx):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    await reg(update, ctx)
    if is_admin(uid):
        for key, lab in alabels().items():
            if lab == text:
                ctx.user_data.pop("st", None)
                await A[key](update, ctx)
                return
    for key in MENU_LABELS:
        if label(key) == text:
            ctx.user_data.pop("st", None)
            if await guard(update, ctx):
                await MENU[key](update, ctx)
            return
    st = ctx.user_data.get("st")
    if st:
        if st.startswith("bc:") and is_admin(uid):
            kind = st.split(":")[1]
            ctx.user_data.pop("st", None)
            await start_copy_broadcast(update, ctx, kind)
            return
        await handle_state(update, ctx, st, text)


async def start_copy_broadcast(update, ctx, kind):
    chat, mid = update.effective_chat.id, update.message.message_id
    ts = targets_for(kind)
    await say(update, ctx, f"📤 Sending to {len(ts)} users…")

    async def sender(uid):
        await ctx.bot.copy_message(uid, chat, mid)
    ctx.application.create_task(run_broadcast(ctx, chat, ts, sender))


async def on_media(update, ctx):
    uid = update.effective_user.id
    await reg(update, ctx)
    st = ctx.user_data.get("st", "")
    if not is_admin(uid) or not st:
        return
    m = update.message
    if st.startswith("bc:"):
        ctx.user_data.pop("st", None)
        await start_copy_broadcast(update, ctx, st.split(":")[1])
    elif st.startswith("api:") and m.photo:
        run("UPDATE products SET image=? WHERE id=?", (m.photo[-1].file_id, int(st.split(":")[1])))
        ctx.user_data.pop("st", None)
        await finish_add(update, ctx, int(st.split(":")[1]))
    elif st.startswith("ef:image:") and m.photo:
        pid = int(st.split(":")[2])
        run("UPDATE products SET image=? WHERE id=?", (m.photo[-1].file_id, pid))
        ctx.user_data.pop("st", None)
        t, mk = prod_card(one("SELECT * FROM products WHERE id=?", (pid,)))
        await say(update, ctx, "✅ Image updated.\n\n" + t, mk)
    elif st.startswith("stk:") and m.document:
        pid = int(st.split(":")[1])
        if m.document.file_size and m.document.file_size > 5_000_000:
            await say(update, ctx, "❌ File too large (max 5 MB).")
            return
        f = await m.document.get_file()
        data = bytes(await f.download_as_bytearray()).decode("utf-8", errors="ignore")
        added, dup = add_stock(pid, data)
        await say(update, ctx, f"✅ Added <b>{added}</b> items from file" + (f" (skipped {dup} duplicates)" if dup else "") +
                  f"\n📦 Available now: <b>{stock_count(pid)}</b>\nSend more, or /done.")


async def on_contact(update, ctx):
    c = update.message.contact
    tu = update.effective_user
    await reg(update, ctx)
    if c.user_id != tu.id:
        await say(update, ctx, "❌ Please share your OWN number using the button.")
        return
    phone = c.phone_number.lstrip("+")
    if one("SELECT uid FROM users WHERE phone=? AND uid!=?", (phone, tu.id)):
        await say(update, ctx, "❌ This phone number is already registered with another account.")
        return
    run("UPDATE users SET phone=? WHERE uid=?", (phone, tu.id))
    if await guard(update, ctx):
        await say(update, ctx, "✅ Verified!\n\n" + welcome_text(), main_menu())


# ----------------------------------------------------------------------------
# COMMANDS
# ----------------------------------------------------------------------------
def rest(update):
    parts = (update.message.text or "").split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def admin_only(f):
    async def w(update, ctx):
        if is_admin(update.effective_user.id):
            await f(update, ctx)
    return w


async def cmd_start(update, ctx):
    await reg(update, ctx)
    ctx.user_data.pop("st", None)
    if not await guard(update, ctx):
        return
    await say(update, ctx, welcome_text(), main_menu())
    arg = ctx.args[0] if ctx.args else ""
    if arg.startswith("p") and arg[1:].isdigit():
        await open_product(update, ctx, int(arg[1:]))


async def cmd_id(update, ctx):
    await m_id(update, ctx)


async def cmd_cancel(update, ctx):
    await cancel_flow(update, ctx, notify=False)
    await say(update, ctx, "❌ Cancelled.")


async def cmd_done(update, ctx):
    ctx.user_data.pop("st", None)
    await say(update, ctx, "✅ Done.")


async def cmd_skip(update, ctx):
    st = ctx.user_data.get("st", "")
    if st.startswith("api:"):
        ctx.user_data.pop("st", None)
        await finish_add(update, ctx, int(st.split(":")[1]))


@admin_only
async def cmd_admin(update, ctx):
    await say(update, ctx, panel_text(), admin_kb())


@admin_only
async def cmd_addbal(update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(ctx.args[1])
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: <code>/addbal uid amount</code>")
        return
    nb = await bal_change(ctx, uid, abs(amt))
    await say(update, ctx, f"✅ New balance: {nb:.2f} TK" if nb is not None else "❌ User not found.")


@admin_only
async def cmd_removebal(update, ctx):
    try:
        uid, amt = int(ctx.args[0]), float(ctx.args[1])
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: <code>/removebal uid amount</code>")
        return
    nb = await bal_change(ctx, uid, -abs(amt))
    await say(update, ctx, f"✅ New balance: {nb:.2f} TK" if nb is not None else "❌ User not found.")


@admin_only
async def cmd_sendproduct(update, ctx):
    r = rest(update).split(None, 1)
    if len(r) < 2 or not r[0].isdigit():
        await say(update, ctx, "Usage: <code>/sendproduct uid details</code>")
        return
    uid, details = int(r[0]), r[1]
    o = one("SELECT * FROM orders WHERE uid=? AND status='pending' ORDER BY id LIMIT 1", (uid,))
    if o:
        await deliver_order(ctx, o["id"], details)
        await say(update, ctx, f"✅ Order #{o['id']} delivered to {uid}.")
    elif await notify_user(ctx, uid, f"📦 <b>Delivery</b>\n\n<code>{esc(details)}</code>"):
        await say(update, ctx, "✅ Sent (no pending order found).")
    else:
        await say(update, ctx, "❌ Could not message that user.")


@admin_only
async def cmd_delivered(update, ctx):
    await a_delivered(update, ctx)


@admin_only
async def cmd_history(update, ctx):
    rows = all_("SELECT * FROM orders ORDER BY id DESC LIMIT 30")
    await send_long(ctx, update.effective_chat.id, "🧾 <b>Order history (last 30)</b>\n\n" + ("\n".join(
        f"{'✅' if o['status'] == 'delivered' else '⏳'} #{o['id']} {esc(o['name'])} — <code>{o['uid']}</code> {money(o['price'])}TK {dts(o['created'])}" for o in rows) or "No orders."))


@admin_only
async def cmd_pending(update, ctx):
    await a_pending(update, ctx)


@admin_only
async def cmd_userinfo(update, ctx):
    u = find_user(rest(update)) if rest(update) else None
    if not u:
        await say(update, ctx, "Usage: <code>/userinfo uid</code>")
        return
    t, m = user_card(u)
    await say(update, ctx, t, m)


@admin_only
async def cmd_all_usr_info(update, ctx):
    await send_users_csv(ctx, update.effective_chat.id)


@admin_only
async def cmd_all_list(update, ctx):
    rows = all_("SELECT p.*, c.name cname FROM products p LEFT JOIN categories c ON c.id=p.cat_id ORDER BY p.id")
    await send_long(ctx, update.effective_chat.id, f"📋 <b>All products ({len(rows)})</b>\n\n" + "\n".join(
        f"#{r['id']} [{esc(r['cname'])}] {esc(r['name'])} — {money(r['price'])}TK — {'∞' if not r['track'] else stock_count(r['id'])} in stock{'' if r['active'] else ' (hidden)'}" for r in rows))


@admin_only
async def cmd_broadcast(update, ctx):
    t = rest(update)
    if not t:
        await a_broadcast(update, ctx)
        return
    ts = targets_for("all")
    await say(update, ctx, f"📤 Sending to {len(ts)} users…")

    async def sender(uid):
        await send(ctx, uid, t)
    ctx.application.create_task(run_broadcast(ctx, update.effective_chat.id, ts, sender))


@admin_only
async def cmd_add_product(update, ctx):
    r = parse_prod(rest(update)) if rest(update) else None
    if not r:
        await say(update, ctx, "Usage: <code>/add_product Name_Price_Logo</code>\n(or use ➕ Add Product in the panel)")
        return
    pid = add_product(default_cat(), *r)
    await finish_add(update, ctx, pid)


@admin_only
async def cmd_del_product(update, ctx):
    t = rest(update).strip()
    res = find_products(t) if t else []
    if len(res) != 1:
        await say(update, ctx, "Usage: <code>/del_product id</code> (or exact name)")
        return
    await after_pick(update, ctx, "dp", res[0]["id"])


@admin_only
async def cmd_edit_product(update, ctx):
    parts = [x.strip() for x in rest(update).split("|")]
    if len(parts) < 3 or not parts[0].isdigit():
        await say(update, ctx, "Usage: <code>/edit_product ID| New Name | New Price</code>")
        return
    try:
        run("UPDATE products SET name=?, price=? WHERE id=?", (parts[1], float(parts[2]), int(parts[0])))
    except ValueError:
        await say(update, ctx, "❌ Price must be a number.")
        return
    await say(update, ctx, "✅ Updated.")


@admin_only
async def cmd_set_price(update, ctx):
    try:
        run("UPDATE products SET price=? WHERE id=?", (float(ctx.args[1]), int(ctx.args[0])))
        await say(update, ctx, "✅ Price updated.")
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: <code>/set_price id price</code>")


@admin_only
async def cmd_set_product_image(update, ctx):
    if len(ctx.args) < 2 or not ctx.args[0].isdigit():
        await say(update, ctx, "Usage: <code>/set_product_image id link</code>")
        return
    run("UPDATE products SET image=? WHERE id=?", (ctx.args[1], int(ctx.args[0])))
    await say(update, ctx, "✅ Image updated.")


@admin_only
async def cmd_set_startbonus(update, ctx):
    try:
        setS("welcome_bonus", float(ctx.args[0]))
        await say(update, ctx, f"✅ Welcome bonus = {ctx.args[0]}৳")
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: <code>/set_startbonus amount</code>")


@admin_only
async def cmd_addstock(update, ctx):
    r = (update.message.text or "").split(None, 1)
    body = r[1] if len(r) > 1 else ""
    first, _, items = body.replace("\r", "").partition("\n")
    bits = first.split(None, 1)
    if not bits or not bits[0].isdigit() or not one("SELECT id FROM products WHERE id=?", (int(bits[0]),)):
        await say(update, ctx, "Usage:\n<code>/addstock PRODUCT_ID\nitem1\nitem2\n...</code>")
        return
    pid = int(bits[0])
    if len(bits) > 1:
        items = bits[1] + "\n" + items
    if not items.strip():
        ctx.user_data["st"] = f"stk:{pid}"
        await say(update, ctx, "➕ Send the items (one per line, or a .txt file). /done when finished.")
        return
    added, dup = add_stock(pid, items)
    await say(update, ctx, f"✅ Added {added} items (duplicates skipped: {dup}). Available: <b>{stock_count(pid)}</b>")


@admin_only
async def cmd_stock(update, ctx):
    t, m = stock_list(0)
    await say(update, ctx, t, m)


async def job_autofix(ctx):
    autofix()


async def on_error(update, ctx):
    log.error("Unhandled error", exc_info=ctx.error)


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "welcome Old Serial Bot"), BotCommand("id", "anytime to get your ID"),
        BotCommand("admin", "only admin us"), BotCommand("add_product", "Serial Name _Price_Logo"),
        BotCommand("del_product", "delete Name id"), BotCommand("addbal", "UID Amount Add"),
        BotCommand("sendproduct", "product delivery UID"), BotCommand("edit_product", "ID| New Name | New Price"),
        BotCommand("set_price", "serial price change"), BotCommand("set_product_image", "1 image link"),
        BotCommand("addstock", "add stock to a product"), BotCommand("stock", "stock manager"),
        BotCommand("userinfo", "user information"), BotCommand("all_usr_info", "all user information"),
        BotCommand("all_list", "All product list"), BotCommand("broadcast", "All Usr product notification"),
        BotCommand("pending", "pending payment clear admin only"),
    ])


def main():
    if BOT_TOKEN.startswith("PUT_YOUR"):
        raise SystemExit("Set BOT_TOKEN first:  export BOT_TOKEN='123456:ABC...'")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    for name, fn in [("start", cmd_start), ("id", cmd_id), ("cancel", cmd_cancel), ("done", cmd_done), ("skip", cmd_skip),
                     ("admin", cmd_admin), ("addbal", cmd_addbal), ("removebal", cmd_removebal),
                     ("sendproduct", cmd_sendproduct), ("delivered", cmd_delivered), ("history", cmd_history),
                     ("pending", cmd_pending), ("userinfo", cmd_userinfo), ("all_usr_info", cmd_all_usr_info),
                     ("all_list", cmd_all_list), ("broadcast", cmd_broadcast), ("add_product", cmd_add_product),
                     ("del_product", cmd_del_product), ("edit_product", cmd_edit_product), ("set_price", cmd_set_price),
                     ("set_product_image", cmd_set_product_image), ("set_startbonus", cmd_set_startbonus),
                     ("addstock", cmd_addstock), ("stock", cmd_stock)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.ANIMATION, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    if app.job_queue:
        app.job_queue.run_repeating(job_autofix, interval=6 * 3600, first=120)
    log.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
