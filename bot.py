# -*- coding: utf-8 -*-
"""
OLD SERIAL SHOP BOT  -  Telegram bot, 100% Python
Library : python-telegram-bot v22+   (pip install "python-telegram-bot[job-queue]")
Run     : set BOT_TOKEN and ADMIN_IDS, then  python bot.py

Everything (prices, products, categories, payment numbers, bonuses, button names,
channels, ads ...) is editable from the Telegram admin panel: send /admin.
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

# ============================== CONFIG ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").replace(" ", "").split(",") if x]
DB_FILE = os.getenv("DB_FILE", "shop.db")
TZ = ZoneInfo("Asia/Dhaka")
PER_PAGE = 6            # products per page
NATIVE_COLORS = True    # Telegram coloured buttons (Bot API 9.4+). Set False to disable.
# ====================================================================

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
log = logging.getLogger("shop")
HTML = ParseMode.HTML
START_TS = time.time()
CYCLE = ["primary", "success", "danger"]          # blue, green, red


# ============================== DATABASE ==============================
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
CREATE TABLE IF NOT EXISTS users(uid INTEGER PRIMARY KEY, username TEXT, name TEXT, balance REAL DEFAULT 0,
  refer_balance REAL DEFAULT 0, ref_by INTEGER DEFAULT 0, refer_paid INTEGER DEFAULT 0, bonus_given INTEGER DEFAULT 0,
  total_spent REAL DEFAULT 0, total_orders INTEGER DEFAULT 0, banned INTEGER DEFAULT 0, ads_lock INTEGER DEFAULT 0,
  blocked_bot INTEGER DEFAULT 0, phone TEXT DEFAULT '', joined INTEGER, last_active INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS labels(key TEXT PRIMARY KEY, text TEXT);
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, pos INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, cat_id INTEGER, name TEXT, price REAL,
  image TEXT DEFAULT '', active INTEGER DEFAULT 1, added INTEGER);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, pid INTEGER, name TEXT, price REAL,
  status TEXT DEFAULT 'pending', details TEXT DEFAULT '', created INTEGER, delivered INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, method TEXT, amount REAL,
  trx TEXT DEFAULT '', status TEXT DEFAULT 'created', created INTEGER, decided INTEGER DEFAULT 0);
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


def rows_(sql, args=()):
    return db.execute(sql, args).fetchall()


def count(sql, args=()):
    return one(sql, args)[0]


METHODS = {"bkash": ("🅱️", "bKash"), "nagad": ("🟠", "Nagad"),
           "rocket": ("🚀", "Rocket"), "binance": ("🟡", "Binance")}

DEFAULTS = {
    "shop_name": "Old Serial Bot", "help_contact": "@your_support",
    "welcome_text": ("👋 <b>{shop}</b> এ আপনাকে স্বাগতম। কোন সমস্যা হলে যোগাযোগ করবেন : {contact}\n—ধন্যবাদ\n\n"
                     "<b>যেভাবে ব্যালেন্স এড করবেন</b> 💳\n└ 💰 Add Balance এ ক্লিক করুন\n"
                     "└ 🇧🇩 BDT / 💵 Crypto সিলেক্ট করুন\n└ Amount দিন → Confirm Payment → TrxID দিন\n\n"
                     "<b>যেভাবে Serial নিবেন</b> 🎁\n└ 🛒 Buy Old Serial এ ক্লিক করুন\n"
                     "└ Serial Name সিলেক্ট করুন\n└ Buy Now এ ক্লিক করুন"),
    "welcome_bonus": "10", "refer_bonus": "2", "refer_percent": "10",
    "min_deposit": "50", "amounts": "50,60,70,80,100",
    "channel": "", "channel_on": "0", "log_channel": "", "log_on": "0",
    "refer_protect": "1", "phone_on": "0", "autopost": "0", "notify_new": "0", "product_note": "",
    "pay_bkash_num": "", "pay_bkash_on": "1", "pay_nagad_num": "", "pay_nagad_on": "1",
    "pay_rocket_num": "", "pay_rocket_on": "1", "pay_binance_num": "", "pay_binance_on": "1",
    "ad_text": "", "ad_url": "", "ad_reward": "0.5", "ad_seconds": "10", "ad_daily": "5",
    "autofix_last": "Never run", "autofix_runs": "0",
}


def S(key):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return r[0] if r else DEFAULTS.get(key, "")


def Sf(key):
    try:
        return float(S(key))
    except ValueError:
        return 0.0


def setS(key, val):
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(val)))


# ----- editable main-menu button names -----
LABELS = {"buy": "🛒 Buy Old Serial", "addbal": "💰 Add Balance", "orders": "📦 My Orders",
          "bal": "💳 My Balance", "refer": "👥 Refer & Earn", "ad": "📺 Watch Ad",
          "time": "🕐 Digital Time", "id": "🆔 Id", "help": "🆘 Help"}


def label(k):
    r = one("SELECT text FROM labels WHERE key=?", (k,))
    return r[0] if r else LABELS[k]


# ============================== SMALL HELPERS ==============================
def esc(s):
    return html.escape(str(s if s is not None else ""))


def money(x):
    return f"{float(x):g}"


def now():
    return int(time.time())


def fmt_short(ts):
    return dt.datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M") if ts else "-"


def fmt_dual(ts):
    d = dt.datetime.fromtimestamp(ts, TZ)
    u = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    return (f"{d:%Y-%m-%d %H:%M:%S} ({d:%A}) Dhaka — 24h", f"{u:%Y-%m-%d %H:%M:%S} / {u:%I:%M:%S %p}")


def chat_ref(x):
    x = str(x).strip()
    return int(x) if x.lstrip("-").isdigit() else x


def ib(text, data=None, style=None, url=None):
    ak = {"style": style} if (NATIVE_COLORS and style) else None
    return IB(text, callback_data=data, url=url, api_kwargs=ak)


def kb(text, style=None, **kw):
    ak = {"style": style} if (NATIVE_COLORS and style) else None
    return KB(text, api_kwargs=ak, **kw)


def grid(items, cols=2, offset=0):
    """items = [(text, callback)] -> colourful inline rows."""
    out, row = [], []
    for i, (t, d) in enumerate(items):
        row.append(ib(t, d, CYCLE[(i + offset) % 3]))
        if len(row) == cols:
            out.append(row)
            row = []
    if row:
        out.append(row)
    return out


def on_off(k):
    return "✅ ON" if S(k) == "1" else "❌ OFF"


def user(uid):
    return one("SELECT * FROM users WHERE uid=?", (uid,))


def add_bal(uid, amt):
    run("UPDATE users SET balance=balance+? WHERE uid=?", (amt, uid))


def bot_link(uname, arg=""):
    return f"https://t.me/{uname}" + (f"?start={arg}" if arg else "")


# ============================== SENDING ==============================
async def send(ctx, chat, text, markup=None, photo=None):
    try:
        if photo:
            try:
                return await ctx.bot.send_photo(chat, photo, caption=text[:1024], parse_mode=HTML, reply_markup=markup)
            except BadRequest as e:
                log.warning("photo failed (%s) -> sending text", e)
        return await ctx.bot.send_message(chat, text, parse_mode=HTML, reply_markup=markup)
    except BadRequest as e:
        if "parse" in str(e).lower():
            return await ctx.bot.send_message(chat, text, reply_markup=markup)
        raise


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
    if q and q.message:
        m = q.message
        if not photo and not getattr(m, "photo", None):
            try:
                await q.edit_message_text(text, parse_mode=HTML, reply_markup=markup)
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
        try:
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
        log.warning("notify %s failed: %s", uid, e)
    return False


async def notify_admins(ctx, text, markup=None):
    for a in ADMIN_IDS:
        await notify_user(ctx, a, text, markup)


async def tolog(ctx, kind, text):
    run("INSERT INTO logs(ts,kind,text) VALUES(?,?,?)", (now(), kind, text))
    if S("log_on") == "1" and S("log_channel"):
        try:
            await ctx.bot.send_message(chat_ref(S("log_channel")), f"📋 <b>{esc(kind.upper())}</b>\n{esc(text)}",
                                       parse_mode=HTML)
        except TelegramError as e:
            log.warning("log channel error: %s", e)


async def broadcast(ctx, targets, sender):
    ok = fail = 0
    for uid in targets:
        for attempt in (1, 2):
            try:
                await sender(uid)
                ok += 1
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Forbidden:
                run("UPDATE users SET blocked_bot=1 WHERE uid=?", (uid,))
                fail += 1
                break
            except TelegramError:
                fail += 1
                break
        await asyncio.sleep(0.05)
    return ok, fail


# ============================== USERS / GATES ==============================
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
        await tolog(ctx, "join", f"New user {tu.id} @{uname} ({tu.full_name}) ref={ref or '-'}")
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
    await notify_user(ctx, ref["uid"], f"🎉 A new user joined with your link! +{money(rb)}৳ added to your refer balance.")
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
        log.warning("membership check failed (is the bot admin in the channel?): %s", e)
        return True


async def guard(update, ctx):
    tu = update.effective_user
    if tu.id in ADMIN_IDS:
        return True
    u = user(tu.id)
    if u["banned"]:
        await say(update, ctx, "🚫 You are banned from using this bot.")
        return False
    if S("channel_on") == "1" and S("channel") and not await is_member(ctx, tu.id):
        link = "https://t.me/" + S("channel").lstrip("@") if S("channel").startswith("@") else None
        rows = ([[ib("📢 Join Channel", url=link, style="primary")]] if link else [])
        rows.append([ib("✅ I Joined", "chk", "success")])
        await say(update, ctx, "⚠️ Please join our channel first, then tap <b>I Joined</b>.", IM(rows))
        return False
    if S("phone_on") == "1" and not u["phone"]:
        await say(update, ctx, "📱 Please share your phone number to continue.",
                  RM([[kb("📱 Share my number", "success", request_contact=True)]], resize_keyboard=True,
                     one_time_keyboard=True))
        return False
    await first_pass(ctx, u)
    return True


# ============================== MENUS ==============================
def main_menu():
    L = label
    return RM([[kb(L("buy"), "primary")],
               [kb(L("addbal"), "success"), kb(L("orders"), "primary")],
               [kb(L("bal"), "danger"), kb(L("refer"), "success")],
               [kb(L("ad"), "primary")],
               [kb(L("time"), "danger")],
               [kb(L("id"), "success"), kb(L("help"), "danger")]], resize_keyboard=True)


def welcome_text():
    return (S("welcome_text").replace("{shop}", esc(S("shop_name"))).replace("{contact}", esc(S("help_contact"))))


# ---- admin keyboard (same layout as the screenshots + management rows) ----
ADMIN_ROWS = [
    ["broadcast"], ["bcenter"], ["pending"],
    ["addprod", "editprod"], ["delprod", "cats"],
    ["total", "users"], ["sendprod", "delivered"], ["refertop", "reset"],
    ["paystats"], ["paymethod", "paytoggle"], ["comments"],
    ["channel", "jointest"], ["logch", "joinlogs"], ["referprot", "phoneprot"],
    ["pnotify", "notifyprod"], ["autopost", "shopname"], ["timechecks"], ["timelive"],
    ["autofix", "autofixstats"], ["adminads", "adsstatus"], ["active", "activedetail"],
    ["adslock", "unlock"], ["btnrename"], ["allprodcheck", "prodinfo"],
    ["allusers", "userinfo"], ["welcome", "id"], ["usermenu"],
]


def alabels():
    return {
        "broadcast": "📢 Broadcast", "bcenter": "📥 Broadcast Center (সবাইকে + ব্লক তালিকা)", "pending": "📋 Pending",
        "addprod": "➕ Add Product", "editprod": "✏️ Edit Product", "delprod": "🗑 Del Product", "cats": "🗂 Categories",
        "total": f"👥 Total Users ({count('SELECT COUNT(*) FROM users')})", "users": "👥 Users",
        "sendprod": "📦 Send Product", "delivered": "📬 Delivered", "refertop": "👥 Refer Top", "reset": "♻️ Reset Panel",
        "paystats": "⚡ Online Payment Stats", "paymethod": "💳 Payment Method", "paytoggle": "💳 Payment Toggle",
        "comments": "💬 Comments", "channel": f"📢 Channel: {S('channel') or 'not set'}", "jointest": "🔍 Join Test",
        "logch": "📋 Log Channel", "joinlogs": "📋 Join Logs", "referprot": "🛡 Refer Protection",
        "phoneprot": "📱 Phone/IP Protect", "pnotify": "🔔 Product Notify", "notifyprod": "📢 Notify Product",
        "autopost": "📢 অটো পোস্ট (চ্যানেল)", "shopname": "🏷 Shop Name", "timechecks": "👥 Time Checks",
        "timelive": "🕐 Time LIVE", "autofix": "🛠 Auto-Fix", "autofixstats": "📊 Auto-Fix Stats",
        "adminads": "💰 Admin Ads", "adsstatus": "📊 Ads Status", "active": "👥 Active Users",
        "activedetail": "📄 Active Detail", "adslock": "🔐 Usr Ads Lock", "unlock": "🔓 Usr Unlock",
        "btnrename": "🔤 Button Rename", "allprodcheck": "📦 All Products Check", "prodinfo": "📊 Products Info",
        "allusers": "👥 All Users Info", "userinfo": "🔍 User Info", "welcome": "🎁 Welcome Bonus", "id": "🆔 Id",
        "usermenu": "👤 User Menu",
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
    users = count("SELECT COUNT(*) FROM users")
    pend = count("SELECT COUNT(*) FROM payments WHERE status='pending'") + \
        count("SELECT COUNT(*) FROM orders WHERE status='pending'")
    deliv = count("SELECT COUNT(*) FROM orders WHERE status='delivered'")
    pay = "\n".join(f"• {n}: {esc(S(f'pay_{k}_num')) or '—'} {'✅' if S(f'pay_{k}_on') == '1' else '❌'}"
                    for k, (e, n) in METHODS.items())
    return (f"👑 <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━\n\n"
            f"👥 Users: {users} | ⏳ Pending: {pend} | 📦 Delivered: {deliv}\n"
            f"👥 Refer: {S('refer_bonus')}৳/join | {S('refer_percent')}% commission\n"
            f"⭐ Star Admin: <code>{ADMIN_IDS[0]}</code>\n"
            f"📢 Channel: {esc(S('channel') or 'not set')} {on_off('channel_on')}\n"
            f"📋 Log Channel: {esc(S('log_channel') or 'not set')} {on_off('log_on')}\n"
            f"🎁 Welcome Bonus: {S('welcome_bonus')}৳ (/set_startbonus)\n\n"
            f"💳 <b>Payments:</b>\n{pay}\n\n"
            f"<b>Commands:</b>\n/addbal uid amt | /removebal uid amt\n"
            f"/sendproduct uid details | /delivered | /history | /pending")


# ============================== PRODUCT BROWSING ==============================
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
    cs = rows_("SELECT * FROM categories ORDER BY pos, id")
    per = 10
    pages = max(1, -(-len(cs) // per))
    page = max(0, min(page, pages - 1))
    rows = grid([(c["name"], f"cl:{c['id']}:0") for c in cs[page * per:(page + 1) * per]], 2)
    rows.append([ib("📋 All Products", "cl:0:0", "primary")])
    rows.append([ib("🔍 Search Old Serial Order Name", "sr", "success")])
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"cs:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"cs:{page + 1}", "success"))
    if nav:
        rows.append(nav)
    await show(update, ctx, f"🛒 <b>Select a category</b> (Page {page + 1}/{pages})", IM(rows))


async def view_list(update, ctx, cat, page=0):
    term = ctx.user_data.get("sq", "")
    w, a = plist(cat, term)
    total = count(f"SELECT COUNT(*) FROM products WHERE {w}", a)
    pages = max(1, -(-total // PER_PAGE))
    page = max(0, min(page, pages - 1))
    items = rows_(f"SELECT * FROM products WHERE {w} ORDER BY id DESC LIMIT ? OFFSET ?", a + [PER_PAGE, page * PER_PAGE])
    if cat > 0:
        c = one("SELECT name FROM categories WHERE id=?", (cat,))
        title = c["name"] if c else "Products"
    elif cat == -1:
        title = f"🔍 Search: {term}"
    else:
        title = "📋 All Products"
    rows = [[ib(f"🎞 {p['name']} {money(p['price'])}TK", f"pv:{cat}:{page * PER_PAGE + i}", CYCLE[i % 3])]
            for i, p in enumerate(items)]
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"cl:{cat}:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"cl:{cat}:{page + 1}", "success"))
    if nav:
        rows.append(nav)
    rows.append([ib("⬅️ All Products", "cs:0", "primary")])
    rows.append([ib("🔍 Search Old Serial Order Name", "sr", "success")])
    head = f"⭐ <b>{esc(title)} — Old Serial Order</b> (Page {page + 1}/{pages}) — {total} items"
    if not items:
        head += "\n\nNothing found."
    await show(update, ctx, head, IM(rows))


async def view_prod(update, ctx, cat, pos):
    term = ctx.user_data.get("sq", "")
    w, a = plist(cat, term)
    total = count(f"SELECT COUNT(*) FROM products WHERE {w}", a)
    if total == 0:
        await alert(update, ctx, "No products here.")
        return
    pos %= total
    p = one(f"SELECT * FROM products WHERE {w} ORDER BY id DESC LIMIT 1 OFFSET ?", a + [pos])
    u = user(update.effective_user.id)
    c = one("SELECT name FROM categories WHERE id=?", (p["cat_id"],))
    d1, d2 = fmt_dual(p["added"])
    text = (f"📦 <b>{esc(p['name'])}</b> ({pos + 1}/{total})\n\n"
            f"💰 Price: <b>{money(p['price'])}BDT</b>\n💳 Your Balance:\n<b>{u['balance']:.2f}BDT</b>\n"
            f"📢 <b>Channel:</b> {esc(c['name'] if c else '-')}\n🕐 <b>Added:</b> {d1}\n🌍 UTC: {d2}\n\n"
            f"✅ Click Buy Now to purchase instantly.")
    if S("product_note"):
        text += f"\n\n💬 {esc(S('product_note'))[:200]}"
    rows = [[ib("✅ Buy Now", f"buy:{p['id']}", "success")],
            [ib("Next →", f"pv:{cat}:{pos + 1}", "primary")],
            [ib("⬅️ Back", f"cl:{cat}:{pos // PER_PAGE}", "danger")]]
    await show(update, ctx, text, IM(rows), photo=p["image"] or None)


async def open_product(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=? AND active=1", (pid,))
    if not p:
        await say(update, ctx, "❌ Product not found.")
        return
    ctx.user_data["sq"] = ""
    await view_prod(update, ctx, 0, count("SELECT COUNT(*) FROM products WHERE active=1 AND id>?", (pid,)))


async def do_buy(update, ctx, pid):
    uid = update.effective_user.id
    p = one("SELECT * FROM products WHERE id=? AND active=1", (pid,))
    if not p:
        await alert(update, ctx, "❌ Product not available.")
        return
    u = user(uid)
    if u["balance"] + 1e-9 < p["price"]:
        await alert(update, ctx, f"❌ Not enough balance. You need {money(p['price'])} BDT, you have {u['balance']:.2f}.")
        await say(update, ctx, "💰 Please add balance first.", IM([[ib("💰 Add Balance", "dep", "success")]]))
        return
    run("UPDATE users SET balance=balance-?, total_spent=total_spent+?, total_orders=total_orders+1 WHERE uid=?",
        (p["price"], p["price"], uid))
    oid = run("INSERT INTO orders(uid,pid,name,price,created) VALUES(?,?,?,?,?)",
              (uid, pid, p["name"], p["price"], now())).lastrowid
    pct = Sf("refer_percent")
    if u["ref_by"] and pct > 0 and user(u["ref_by"]):
        com = p["price"] * pct / 100
        run("UPDATE users SET refer_balance=refer_balance+? WHERE uid=?", (com, u["ref_by"]))
        await notify_user(ctx, u["ref_by"], f"💸 Commission +{com:.2f}৳ from your referral's purchase.")
    await alert(update, ctx, "✅ Order placed!")
    await say(update, ctx, f"✅ <b>Order #{oid} placed</b>\n📦 {esc(p['name'])}\n💰 {money(p['price'])} BDT\n\n"
                           f"Your serial will be delivered soon. Check <b>{esc(label('orders'))}</b>.")
    await notify_admins(ctx, f"🛒 <b>New order #{oid}</b>\n👤 <code>{uid}</code> @{esc(u['username'])}\n"
                             f"📦 {esc(p['name'])} — {money(p['price'])}৳",
                        IM([[ib("📦 Deliver", f"dl:{oid}", "success")]]))
    await tolog(ctx, "order", f"#{oid} {uid} bought {p['name']} for {money(p['price'])}")


async def view_orders(update, ctx, page=0):
    uid = update.effective_user.id
    per = 5
    total = count("SELECT COUNT(*) FROM orders WHERE uid=?", (uid,))
    if not total:
        await show(update, ctx, "📦 You have no orders yet.", IM([[ib(label("buy"), "cs:0", "success")]]))
        return
    pages = -(-total // per)
    page = max(0, min(page, pages - 1))
    lines = []
    for o in rows_("SELECT * FROM orders WHERE uid=? ORDER BY id DESC LIMIT ? OFFSET ?", (uid, per, page * per)):
        ic = "✅" if o["status"] == "delivered" else "⏳"
        line = f"{ic} <b>#{o['id']}</b> {esc(o['name'])} — {money(o['price'])}TK\n    🕐 {fmt_short(o['created'])}"
        if o["details"]:
            line += f"\n    <code>{esc(o['details'][:300])}</code>"
        lines.append(line)
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"mo:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"mo:{page + 1}", "success"))
    await show(update, ctx, f"📦 <b>My Orders</b> (Page {page + 1}/{pages})\n\n" + "\n\n".join(lines),
               IM([nav] if nav else []))


# ============================== BALANCE / DEPOSIT ==============================
async def view_balance(update, ctx):
    u = user(update.effective_user.id)
    uname = f"@{esc(u['username'])}" if u["username"] else esc(u["name"])
    text = (f"💰 <b>YOUR BALANCE</b>\n━━━━━━━━━━━━━━\n👤 Username: {uname}\n💵 Available: {u['balance']:.2f} TK\n"
            f"🚀 Total Orders amount : {u['total_spent']:.2f} TK\n🚀 Total Orders : {u['total_orders']}\n"
            f"🎁 Refer balance: {u['refer_balance']:.2f} TK\n━━━━━━━━━━━━━━")
    rows = [[ib("💰 Add Balance", "dep", "success"), ib("🛒 Buy Old Serial", "cs:0", "primary")],
            [ib("📦 My Orders", "mo:0", "danger"), ib("👥 Refer & Earn", "rf", "success")],
            [ib("🔄 Refresh", "bl", "primary")]]
    await show(update, ctx, text, IM(rows))


async def view_portal(update, ctx):
    enabled = [(f"{e} {n}", f"dm:{k}") for k, (e, n) in METHODS.items() if S(f"pay_{k}_on") == "1"]
    if not enabled:
        await show(update, ctx, "⚠️ No payment method is available right now.")
        return
    rows = grid(enabled, 2)
    rows.append([ib("❌ Cancel", "dcancel", "danger")])
    await show(update, ctx, "💲 <b>Deposit Portal</b>\n━━━━━━━━━━━━━━\n\n🏧 <b>Payment System</b>\n\n"
                            "1) bKash / Nagad / Rocket / Binance → Enter amount (BDT) → Confirm\n"
                            "2) Send the payment, then submit your TrxID → balance is added once an admin approves\n\n"
                            "✅ Select a payment method to begin:", IM(rows))


def amounts():
    out = []
    for x in S("amounts").split(","):
        try:
            out.append(float(x))
        except ValueError:
            pass
    return out or [50.0, 100.0]


async def view_dep(update, ctx):
    d = ctx.user_data.get("dep")
    if not d:
        await view_portal(update, ctx)
        return
    _, name = METHODS[d["m"]]
    btns = [(f"{money(a)} ✅" if a == d["amt"] else f"৳{money(a)}", f"da:{money(a)}") for a in amounts()]
    rows = []
    for i in range(0, len(btns), 4):
        rows.append([ib(t, c, CYCLE[(i + j) % 3]) for j, (t, c) in enumerate(btns[i:i + 4])])
    rows.append([ib("✍️ Enter Amount", "dcustom", "primary")])
    rows.append([ib("⬅️ Back", "dback", "primary"), ib("❌ Cancel", "dcancel", "danger")])
    rows.append([ib("✅ Confirm", "dconfirm", "success")])
    await show(update, ctx, f"<b>{name} — Add Balance</b>\n━━━━━━━━━━━━━━\n\n💰 <b>Selected Amount:</b> ৳{money(d['amt'])}\n"
                            f"⚠️ <b>Minimum Deposit:</b> ৳{money(Sf('min_deposit'))}\n\n"
                            f"How much BDT would you like to deposit? 👇\nPick an amount below or tap <b>Enter Amount</b> to type your own.",
               IM(rows))


async def view_refer(update, ctx):
    uid = update.effective_user.id
    u = user(uid)
    me = (await ctx.bot.get_me()).username
    inv = count("SELECT COUNT(*) FROM users WHERE ref_by=?", (uid,))
    paid = count("SELECT COUNT(*) FROM users WHERE ref_by=? AND refer_paid=1", (uid,))
    text = (f"👥 <b>Refer & Earn</b>\n━━━━━━━━━━━━━━\n🔗 Your link:\n{bot_link(me, f'ref{uid}')}\n\n"
            f"🎁 Earn <b>{S('refer_bonus')}৳</b> for every user who joins\n"
            f"💸 Plus <b>{S('refer_percent')}%</b> commission on their purchases\n\n"
            f"👤 Invited: {inv} (counted: {paid})\n💰 Refer balance: <b>{u['refer_balance']:.2f} TK</b>")
    await show(update, ctx, text, IM([[ib("💱 Move to Balance", "rfmove", "success"), ib("🔄 Refresh", "rf", "primary")]]))


def time_text():
    d = dt.datetime.now(TZ)
    u = dt.datetime.now(dt.timezone.utc)
    return (f"🕐 <b>Digital Time</b>\n\n🇧🇩 Dhaka: <b>{d:%I:%M:%S %p}</b>\n📅 {d:%A, %d %B %Y}\n"
            f"🕰 24h: {d:%H:%M:%S}\n🌍 UTC: {u:%H:%M:%S}")


# ============================== USER MENU HANDLERS ==============================
async def m_buy(update, ctx):
    await view_cats(update, ctx, 0)


async def m_addbal(update, ctx):
    await view_portal(update, ctx)


async def m_orders(update, ctx):
    await view_orders(update, ctx, 0)


async def m_bal(update, ctx):
    await view_balance(update, ctx)


async def m_refer(update, ctx):
    await view_refer(update, ctx)


async def m_time(update, ctx):
    await say(update, ctx, time_text(), IM([[ib("🔄 Refresh", "tm", "success")]]))


async def m_id(update, ctx):
    tu = update.effective_user
    await say(update, ctx, f"🆔 <b>Your ID:</b> <code>{tu.id}</code>\n👤 {esc(tu.full_name)}"
                           + (f" (@{esc(tu.username)})" if tu.username else ""))


async def m_help(update, ctx):
    c = S("help_contact")
    rows = [[ib("💬 Contact Support", url=f"https://t.me/{c.lstrip('@')}", style="primary")]] if c.startswith("@") else []
    await say(update, ctx, welcome_text(), IM(rows) if rows else None)


async def m_ad(update, ctx):
    uid = update.effective_user.id
    u = user(uid)
    if u["ads_lock"]:
        await say(update, ctx, "🔒 Ads are locked for your account.")
        return
    if not S("ad_text") and not S("ad_url"):
        await say(update, ctx, "📺 No ads available right now. Please check back later.")
        return
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    used = count("SELECT COUNT(*) FROM ad_views WHERE uid=? AND ts>=?", (uid, int(today)))
    lim = int(Sf("ad_daily"))
    if used >= lim:
        await say(update, ctx, f"⏳ Daily ad limit reached ({used}/{lim}). Come back tomorrow!")
        return
    ctx.user_data["ad_t"] = time.time()
    rows = []
    if S("ad_url"):
        rows.append([ib("🔗 Open Ad", url=S("ad_url"), style="primary")])
    rows.append([ib("✅ Claim Reward", "adc", "success")])
    await say(update, ctx, f"📺 <b>Sponsored</b>\n\n{esc(S('ad_text'))}\n\n⏳ Open the ad, wait {int(Sf('ad_seconds'))}s, "
                           f"then tap <b>Claim</b> to earn <b>{S('ad_reward')}৳</b>.\nToday: {used}/{lim}", IM(rows))


MENU = {"buy": m_buy, "addbal": m_addbal, "orders": m_orders, "bal": m_bal, "refer": m_refer,
        "ad": m_ad, "time": m_time, "id": m_id, "help": m_help}


# ============================== CALLBACK REGISTRY ==============================
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
    parts = (q.data or "").split(":")
    name, a = parts[0], parts[1:]
    ctx.user_data["_ans"] = False
    await reg(update, ctx)
    uid = q.from_user.id
    if name in ADMIN_CB and uid not in ADMIN_IDS:
        await q.answer("⛔ Admin only", show_alert=True)
        return
    if name not in ADMIN_CB and not await guard(update, ctx):
        await q.answer()
        return
    fn = CB.get(name)
    try:
        if fn:
            await fn(update, ctx, a)
    except Exception:
        log.exception("callback %s failed", q.data)
    if not ctx.user_data.get("_ans"):
        try:
            await q.answer()
        except TelegramError:
            pass


# ---------------- user callbacks ----------------
@cb("chk")
async def c_chk(update, ctx, a):
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
    await say(update, ctx, "🔍 Type the serial name to search (or /cancel):")


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
    amt = u["refer_balance"]
    if amt <= 0:
        await alert(update, ctx, "You have no refer balance.")
        return
    run("UPDATE users SET balance=balance+?, refer_balance=0 WHERE uid=?", (amt, u["uid"]))
    await alert(update, ctx, f"✅ {amt:.2f}৳ moved to your balance.")
    await view_refer(update, ctx)


@cb("tm")
async def c_tm(update, ctx, a):
    await show(update, ctx, time_text(), IM([[ib("🔄 Refresh", "tm", "success")]]))


@cb("adc")
async def c_adc(update, ctx, a):
    uid = update.effective_user.id
    t = ctx.user_data.get("ad_t")
    if not t:
        await alert(update, ctx, "Open the Watch Ad menu again.")
        return
    wait = Sf("ad_seconds") - (time.time() - t)
    if wait > 0:
        await alert(update, ctx, f"⏳ Please wait {int(wait) + 1} more seconds.")
        return
    ctx.user_data.pop("ad_t", None)
    rw = Sf("ad_reward")
    run("INSERT INTO ad_views(uid,ts,reward) VALUES(?,?,?)", (uid, now(), rw))
    add_bal(uid, rw)
    await show(update, ctx, f"🎉 You earned <b>{money(rw)}৳</b>!")


# ---------------- deposit callbacks ----------------
@cb("dep")
async def c_dep(update, ctx, a):
    await view_portal(update, ctx)


@cb("dm")
async def c_dm(update, ctx, a):
    m = a[0]
    if m not in METHODS or S(f"pay_{m}_on") != "1":
        await alert(update, ctx, "Method unavailable.")
        return
    first = amounts()[0]
    ctx.user_data["dep"] = {"m": m, "amt": max(first, Sf("min_deposit"))}
    await view_dep(update, ctx)


@cb("da")
async def c_da(update, ctx, a):
    d = ctx.user_data.get("dep")
    if not d:
        await view_portal(update, ctx)
        return
    amt = float(a[0])
    if amt < Sf("min_deposit"):
        await alert(update, ctx, f"Minimum deposit is {money(Sf('min_deposit'))}.")
        return
    d["amt"] = amt
    await view_dep(update, ctx)


@cb("dcustom")
async def c_dcustom(update, ctx, a):
    ctx.user_data["st"] = "dep_amt"
    await say(update, ctx, f"✍️ Send the amount in BDT (minimum {money(Sf('min_deposit'))}):")


@cb("dback")
async def c_dback(update, ctx, a):
    ctx.user_data.pop("dep", None)
    await view_portal(update, ctx)


@cb("dcancel")
async def c_dcancel(update, ctx, a):
    await cancel_flow(ctx, update.effective_user.id)
    await show(update, ctx, "❌ Cancelled.")


@cb("dconfirm")
async def c_dconfirm(update, ctx, a):
    d = ctx.user_data.get("dep")
    if not d:
        await view_portal(update, ctx)
        return
    m, amt = d["m"], d["amt"]
    num = S(f"pay_{m}_num")
    if not num:
        await alert(update, ctx, "This payment method is not configured yet. Contact admin.")
        return
    pid = run("INSERT INTO payments(uid,method,amount,created) VALUES(?,?,?,?)",
              (update.effective_user.id, m, amt, now())).lastrowid
    ctx.user_data["st"] = f"trx:{pid}"
    await show(update, ctx, f"🧾 <b>Payment invoice created!</b>\n━━━━━━━━━━━━━━\nMethod: <b>{METHODS[m][1]}</b>\n"
                            f"Amount: <b>৳{money(amt)}</b>\nSend to: <code>{esc(num)}</code>\n━━━━━━━━━━━━━━\n"
                            f"After paying, send your <b>Transaction ID (TrxID)</b> here.\n(Cancel: /cancel)",
               IM([[ib("❌ Cancel", "dcancel", "danger")]]))


async def cancel_flow(ctx, uid):
    st = ctx.user_data.pop("st", None) or ""
    ctx.user_data.pop("dep", None)
    if st.startswith("trx:"):
        run("UPDATE payments SET status='cancelled' WHERE id=? AND status='created'", (int(st.split(":")[1]),))


# ============================== ADMIN SCREENS (pure builders) ==============================
def scr_channel():
    t = (f"📢 <b>Required Channel</b>\n\nChannel: <b>{esc(S('channel') or 'not set')}</b>\nForce-join: {on_off('channel_on')}\n\n"
         f"Make the bot an <b>admin</b> of the channel so it can check members.")
    return t, IM([[ib("✏️ Set Channel", "set:channel", "primary"), ib("🔁 Toggle ON/OFF", "tg:channel_on:channel", "success")],
                  [ib("🔍 Join Test", "jt", "danger")]])


def scr_logch():
    t = f"📋 <b>Log Channel</b>\n\nChannel: <b>{esc(S('log_channel') or 'not set')}</b>\nLogging: {on_off('log_on')}"
    return t, IM([[ib("✏️ Set Log Channel", "set:log_channel", "primary"), ib("🔁 Toggle ON/OFF", "tg:log_on:logch", "success")]])


def scr_refer():
    t = (f"🛡 <b>Refer Protection</b>: {on_off('refer_protect')}\n\nON = referral bonus is paid only after the new user passes "
         f"the channel/phone checks (and not with the same phone as the referrer).\n\n"
         f"🎁 Bonus per join: <b>{S('refer_bonus')}৳</b>\n💸 Commission on purchases: <b>{S('refer_percent')}%</b>")
    return t, IM([[ib("🔁 Toggle Protection", "tg:refer_protect:refer", "success")],
                  [ib("🎁 Set Bonus", "set:refer_bonus", "primary"), ib("💸 Set Commission %", "set:refer_percent", "danger")]])


def scr_phone():
    t = (f"📱 <b>Phone Protect</b>: {on_off('phone_on')}\n\nON = users must share their Telegram phone number once; one phone = one account.\n"
         f"(Telegram does not give bots a user's IP address, so only the phone check is possible.)")
    return t, IM([[ib("🔁 Toggle ON/OFF", "tg:phone_on:phone", "success")]])


def scr_autopost():
    t = f"📢 <b>Auto Post to Channel</b>: {on_off('autopost')}\n\nNew products are posted to the channel ({esc(S('channel') or 'not set')})."
    return t, IM([[ib("🔁 Toggle ON/OFF", "tg:autopost:autopost", "success")]])


def scr_notify():
    t = f"🔔 <b>Product Notify</b>: {on_off('notify_new')}\n\nON = every new product is sent to all users automatically."
    return t, IM([[ib("🔁 Toggle ON/OFF", "tg:notify_new:notify", "success")]])


def scr_paymethod():
    lines = [f"{e} <b>{n}</b>: <code>{esc(S(f'pay_{k}_num')) or '—'}</code> {on_off(f'pay_{k}_on')}" for k, (e, n) in METHODS.items()]
    t = ("💳 <b>Payment Methods</b>\n\n" + "\n".join(lines) +
         f"\n\n⚠️ Min deposit: <b>{money(Sf('min_deposit'))}</b>\n💰 Amount buttons: <b>{esc(S('amounts'))}</b>")
    rows = grid([(f"✏️ {n} number", f"set:pay_{k}_num") for k, (e, n) in METHODS.items()], 2)
    rows.append([ib("⚠️ Min Deposit", "set:min_deposit", "primary"), ib("💰 Amount Buttons", "set:amounts", "success")])
    return t, IM(rows)


def scr_paytoggle():
    rows = grid([(f"{e} {n}: {'ON ✅' if S(f'pay_{k}_on') == '1' else 'OFF ❌'}", f"tg:pay_{k}_on:paytoggle")
                 for k, (e, n) in METHODS.items()], 2)
    return "💳 <b>Payment Toggle</b>\nTap a method to switch it ON/OFF:", IM(rows)


def scr_shop():
    t = (f"🏷 <b>Shop Settings</b>\n\nShop name: <b>{esc(S('shop_name'))}</b>\nHelp contact: <b>{esc(S('help_contact'))}</b>\n\n"
         f"Welcome text (use {{shop}} and {{contact}}):\n<code>{esc(S('welcome_text')[:500])}</code>")
    return t, IM([[ib("🏷 Shop Name", "set:shop_name", "primary"), ib("🆘 Help Contact", "set:help_contact", "success")],
                  [ib("👋 Welcome Text", "set:welcome_text", "danger")]])


def scr_comments():
    t = f"💬 <b>Product Comment</b>\n\nA note shown under every product.\nCurrent: {esc(S('product_note')) or '— none —'}"
    return t, IM([[ib("✏️ Set Comment", "set:product_note", "primary"), ib("🗑 Clear", "clr:product_note:comments", "danger")]])


def scr_ads():
    t = (f"💰 <b>Admin Ads</b> (Watch Ad)\n\n📝 Text: {esc(S('ad_text')) or '—'}\n🔗 Link: {esc(S('ad_url')) or '—'}\n"
         f"🎁 Reward: {S('ad_reward')}৳\n⏳ Wait: {S('ad_seconds')}s\n📅 Daily limit/user: {S('ad_daily')}")
    rows = grid([("📝 Text", "set:ad_text"), ("🔗 Link", "set:ad_url"), ("🎁 Reward", "set:ad_reward"),
                 ("⏳ Seconds", "set:ad_seconds"), ("📅 Daily Limit", "set:ad_daily")], 2)
    rows.append([ib("🗑 Remove Ad", "clr:ad_text:ads", "danger")])
    return t, IM(rows)


def scr_bcenter():
    tot = count("SELECT COUNT(*) FROM users")
    act = count("SELECT COUNT(*) FROM users WHERE last_active>?", (now() - 86400,))
    blk = count("SELECT COUNT(*) FROM users WHERE blocked_bot=1")
    ban = count("SELECT COUNT(*) FROM users WHERE banned=1")
    t = (f"📥 <b>Broadcast Center</b>\n\n👥 All users: {tot}\n🟢 Active (24h): {act}\n🚫 Blocked the bot: {blk}\n⛔ Banned: {ban}")
    return t, IM([[ib("📢 Send to ALL", "bc:all", "success"), ib("🟢 Send to Active", "bc:active", "primary")],
                  [ib("🚫 Blocked List", "bc:blocked", "danger")]])


def scr_btnrename():
    rows = grid([(label(k), f"brk:{k}") for k in LABELS], 2)
    rows.append([ib("♻️ Reset All Names", "brr", "danger")])
    return "🔤 <b>Button Rename</b>\nTap a button to give it a new name:", IM(rows)


def scr_cats():
    cs = rows_("SELECT * FROM categories ORDER BY pos, id")
    rows = [[ib(f"{c['name']} ({count('SELECT COUNT(*) FROM products WHERE cat_id=?', (c['id'],))})", f"cmv:{c['id']}", CYCLE[i % 3])]
            for i, c in enumerate(cs)]
    rows.append([ib("➕ Add Category", "cmadd", "success")])
    return f"🗂 <b>Categories</b> ({len(cs)})\nTap one to rename / move / delete:", IM(rows)


SCREENS = {"channel": scr_channel, "logch": scr_logch, "refer": scr_refer, "phone": scr_phone, "autopost": scr_autopost,
           "notify": scr_notify, "paymethod": scr_paymethod, "paytoggle": scr_paytoggle, "shop": scr_shop,
           "comments": scr_comments, "ads": scr_ads, "bcenter": scr_bcenter, "btnrename": scr_btnrename, "cats": scr_cats}


async def send_screen(update, ctx, name):
    t, m = SCREENS[name]()
    await say(update, ctx, t, m)


@cb("sc", admin=True)
async def c_sc(update, ctx, a):
    t, m = SCREENS[a[0]]()
    await show(update, ctx, t, m)


@cb("tg", admin=True)
async def c_tg(update, ctx, a):
    setS(a[0], "0" if S(a[0]) == "1" else "1")
    t, m = SCREENS[a[1]]()
    await show(update, ctx, t, m)


@cb("clr", admin=True)
async def c_clr(update, ctx, a):
    setS(a[0], "")
    t, m = SCREENS[a[1]]()
    await show(update, ctx, t, m)


# ---- generic "set a setting" flow ----
SET_INFO = {
    "welcome_bonus": ("🎁 Send the new <b>Welcome Bonus</b> amount (৳):", "f", None),
    "refer_bonus": ("🎁 Send bonus (৳) paid per referred user:", "f", "refer"),
    "refer_percent": ("💸 Send commission % on referred users' purchases:", "f", "refer"),
    "min_deposit": ("⚠️ Send the minimum deposit (৳):", "f", "paymethod"),
    "amounts": ("💰 Send amount buttons separated by commas, e.g. <code>50,60,70,80,100</code>", "amounts", "paymethod"),
    "channel": ("📢 Send channel <code>@username</code> (or <code>-100…</code> id). Send <code>none</code> to clear.", "ch", "channel"),
    "log_channel": ("📋 Send log channel <code>@username</code> or <code>-100…</code> id. <code>none</code> clears.", "ch", "logch"),
    "shop_name": ("🏷 Send the new shop name:", "s", "shop"),
    "help_contact": ("🆘 Send the support contact (e.g. <code>@yoursupport</code>):", "s", "shop"),
    "welcome_text": ("👋 Send the new welcome text. Use {shop} and {contact}. HTML like &lt;b&gt; is allowed:", "s", "shop"),
    "product_note": ("💬 Send the comment shown under each product:", "s", "comments"),
    "ad_text": ("📝 Send the ad text:", "s", "ads"),
    "ad_url": ("🔗 Send the ad link (https://…):", "s", "ads"),
    "ad_reward": ("🎁 Send the reward per ad (৳):", "f", "ads"),
    "ad_seconds": ("⏳ Send seconds users must wait before claiming:", "i", "ads"),
    "ad_daily": ("📅 Send daily ad limit per user:", "i", "ads"),
}
for _k, (_e, _n) in METHODS.items():
    SET_INFO[f"pay_{_k}_num"] = (f"{_e} Send the <b>{_n}</b> number / address users should pay to:", "s", "paymethod")


@cb("set", admin=True)
async def c_set(update, ctx, a):
    ctx.user_data["st"] = f"set:{a[0]}"
    await say(update, ctx, SET_INFO[a[0]][0] + "\n\n/cancel to abort.")


# ============================== ADMIN CALLBACKS ==============================
@cb("pay", admin=True)
async def c_pay(update, ctx, a):
    ok, pid = a[0] == "ok", int(a[1])
    p = one("SELECT * FROM payments WHERE id=?", (pid,))
    q = update.callback_query
    if not p or p["status"] != "pending":
        await alert(update, ctx, "Already processed.")
        return
    run("UPDATE payments SET status=?, decided=? WHERE id=?", ("approved" if ok else "rejected", now(), pid))
    if ok:
        add_bal(p["uid"], p["amount"])
        await notify_user(ctx, p["uid"], f"✅ <b>Deposit approved!</b>\n৳{money(p['amount'])} added to your balance.")
    else:
        await notify_user(ctx, p["uid"], f"❌ Your deposit of ৳{money(p['amount'])} (TrxID <code>{esc(p['trx'])}</code>) was rejected. Contact support.")
    await tolog(ctx, "deposit", f"#{pid} {p['uid']} {p['method']} {money(p['amount'])} -> {'approved' if ok else 'rejected'}")
    try:
        await q.edit_message_text(q.message.text_html + f"\n\n{'✅ Approved' if ok else '❌ Rejected'}", parse_mode=HTML)
    except TelegramError:
        pass


@cb("dl", admin=True)
async def c_dl(update, ctx, a):
    o = one("SELECT * FROM orders WHERE id=?", (int(a[0]),))
    if not o or o["status"] != "pending":
        await alert(update, ctx, "Order already delivered / not found.")
        return
    ctx.user_data["st"] = f"send:{o['id']}"
    await say(update, ctx, f"📦 Send the delivery details for order <b>#{o['id']}</b> ({esc(o['name'])}) to user <code>{o['uid']}</code>.\n/cancel to abort.")


async def deliver_order(ctx, oid, details):
    o = one("SELECT * FROM orders WHERE id=?", (oid,))
    run("UPDATE orders SET status='delivered', details=?, delivered=? WHERE id=?", (details, now(), oid))
    await notify_user(ctx, o["uid"], f"📦 <b>Order #{oid} delivered!</b>\n{esc(o['name'])}\n\n{esc(details)}")
    await tolog(ctx, "delivered", f"#{oid} -> {o['uid']}")


@cb("bc", admin=True)
async def c_bc(update, ctx, a):
    if a[0] == "blocked":
        r = rows_("SELECT uid,username,name FROM users WHERE blocked_bot=1 OR banned=1 LIMIT 200")
        txt = "🚫 <b>Blocked / banned users</b>\n" + ("\n".join(f"<code>{x['uid']}</code> @{esc(x['username'])} {esc(x['name'])}" for x in r) or "None")
        await send_long(ctx, update.effective_chat.id, txt)
        return
    ctx.user_data["st"] = f"bc:{a[0]}"
    await say(update, ctx, f"📢 Send the message to broadcast to <b>{'ALL' if a[0] == 'all' else 'ACTIVE (24h)'}</b> users "
                           f"(text, photo + caption, video…). /cancel to abort.")


def targets(kind):
    if kind == "active":
        return [r[0] for r in rows_("SELECT uid FROM users WHERE banned=0 AND last_active>?", (now() - 86400,))]
    return [r[0] for r in rows_("SELECT uid FROM users WHERE banned=0")]


async def start_broadcast(update, ctx, kind, sender):
    chat = update.effective_chat.id
    ids = targets(kind)
    await say(update, ctx, f"🚀 Sending to {len(ids)} users…")

    async def job():
        ok, fail = await broadcast(ctx, ids, sender)
        await send(ctx, chat, f"✅ Broadcast finished.\nSent: {ok}\nFailed/blocked: {fail}")
        await tolog(ctx, "broadcast", f"sent {ok}, failed {fail}")
    ctx.application.create_task(job())


def users_page(page):
    per = 15
    total = count("SELECT COUNT(*) FROM users")
    pages = max(1, -(-total // per))
    page = max(0, min(page, pages - 1))
    r = rows_("SELECT * FROM users ORDER BY joined DESC LIMIT ? OFFSET ?", (per, page * per))
    t = f"👥 <b>Users</b> ({total}) — Page {page + 1}/{pages}\n\n" + "\n".join(
        f"<code>{u['uid']}</code> @{esc(u['username'])} — {u['balance']:.0f}৳ — {u['total_orders']} orders" for u in r)
    nav = []
    if page > 0:
        nav.append(ib("← Prev", f"ul:{page - 1}", "danger"))
    if page < pages - 1:
        nav.append(ib("Next →", f"ul:{page + 1}", "success"))
    return t, IM([nav] if nav else [])


@cb("ul", admin=True)
async def c_ul(update, ctx, a):
    t, m = users_page(int(a[0]))
    await show(update, ctx, t, m)


def user_card(u):
    inv = count("SELECT COUNT(*) FROM users WHERE ref_by=?", (u["uid"],))
    t = (f"👤 <b>User Info</b>\n━━━━━━━━━━━━━━\n🆔 <code>{u['uid']}</code>\n👤 {esc(u['name'])} "
         f"{('@' + esc(u['username'])) if u['username'] else ''}\n💵 Balance: {u['balance']:.2f} TK\n"
         f"🎁 Refer balance: {u['refer_balance']:.2f} TK\n🚀 Orders: {u['total_orders']} ({u['total_spent']:.2f} TK)\n"
         f"👥 Invited: {inv} | Referred by: {u['ref_by'] or '-'}\n📱 Phone: {esc(u['phone']) or '-'}\n"
         f"⛔ Banned: {'Yes' if u['banned'] else 'No'} | 🔒 Ads lock: {'Yes' if u['ads_lock'] else 'No'}\n"
         f"🕐 Joined: {fmt_short(u['joined'])}\n🟢 Last active: {fmt_short(u['last_active'])}")
    uid = u["uid"]
    m = IM([[ib("➕ Add Balance", f"bal:add:{uid}", "success"), ib("➖ Remove Balance", f"bal:rem:{uid}", "danger")],
            [ib("✅ Unban" if u["banned"] else "⛔ Ban", f"ub:{uid}", "danger"),
             ib("🔓 Ads Unlock" if u["ads_lock"] else "🔐 Ads Lock", f"ua:{uid}", "primary")],
            [ib("📦 Orders", f"uo:{uid}", "success")]])
    return t, m


def find_user(term):
    term = term.strip().lstrip("@")
    if term.isdigit():
        return user(int(term))
    return one("SELECT * FROM users WHERE username=? COLLATE NOCASE", (term,))


@cb("bal", admin=True)
async def c_bal(update, ctx, a):
    ctx.user_data["st"] = f"bal:{a[0]}:{a[1]}"
    await say(update, ctx, f"{'➕ Add' if a[0] == 'add' else '➖ Remove'} balance for <code>{a[1]}</code> — send the amount:")


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


@cb("uo", admin=True)
async def c_uo(update, ctx, a):
    r = rows_("SELECT * FROM orders WHERE uid=? ORDER BY id DESC LIMIT 20", (int(a[0]),))
    await send_long(ctx, update.effective_chat.id, "📦 <b>Orders</b>\n" + (
        "\n".join(f"{'✅' if o['status'] == 'delivered' else '⏳'} #{o['id']} {esc(o['name'])} {money(o['price'])}TK {fmt_short(o['created'])}" for o in r) or "None"))


@cb("jt", admin=True)
async def c_jt(update, ctx, a):
    await a_jointest(update, ctx)


# ---- categories ----
@cb("cmadd", admin=True)
async def c_cmadd(update, ctx, a):
    ctx.user_data["st"] = "addcat"
    await say(update, ctx, "🗂 Send the new category name (emoji allowed, e.g. <code>⭐ Star Jalsha</code>):")


@cb("cmv", admin=True)
async def c_cmv(update, ctx, a):
    c = one("SELECT * FROM categories WHERE id=?", (int(a[0]),))
    if not c:
        return
    n = count("SELECT COUNT(*) FROM products WHERE cat_id=?", (c["id"],))
    await show(update, ctx, f"🗂 <b>{esc(c['name'])}</b>\nProducts: {n}",
               IM([[ib("✏️ Rename", f"cmren:{c['id']}", "primary"), ib("⬆️ Move Up", f"cmup:{c['id']}", "success")],
                   [ib("🗑 Delete", f"cmdel:{c['id']}", "danger")], [ib("⬅️ Back", "sc:cats", "primary")]]))


@cb("cmren", admin=True)
async def c_cmren(update, ctx, a):
    ctx.user_data["st"] = f"rencat:{a[0]}"
    await say(update, ctx, "✏️ Send the new category name:")


@cb("cmup", admin=True)
async def c_cmup(update, ctx, a):
    cs = rows_("SELECT id FROM categories ORDER BY pos, id")
    ids = [c[0] for c in cs]
    i = ids.index(int(a[0]))
    if i > 0:
        ids[i - 1], ids[i] = ids[i], ids[i - 1]
    for n, cid in enumerate(ids):
        run("UPDATE categories SET pos=? WHERE id=?", (n, cid))
    t, m = scr_cats()
    await show(update, ctx, t, m)


@cb("cmdel", admin=True)
async def c_cmdel(update, ctx, a):
    cid = int(a[0])
    if len(a) == 1:
        n = count("SELECT COUNT(*) FROM products WHERE cat_id=?", (cid,))
        await show(update, ctx, f"⚠️ Delete this category? Its {n} product(s) move to <b>📦 Others</b>.",
                   IM([[ib("✅ Yes, delete", f"cmdel:{cid}:y", "danger"), ib("↩️ No", "sc:cats", "primary")]]))
        return
    if count("SELECT COUNT(*) FROM products WHERE cat_id=?", (cid,)):
        run("UPDATE products SET cat_id=? WHERE cat_id=?", (ensure_cat("📦 Others"), cid))
    run("DELETE FROM categories WHERE id=?", (cid,))
    t, m = scr_cats()
    await show(update, ctx, t, m)


def ensure_cat(name):
    r = one("SELECT id FROM categories WHERE name=?", (name,))
    if r:
        return r[0]
    cid = run("INSERT INTO categories(name,pos) VALUES(?,?)", (name, count("SELECT COUNT(*) FROM categories"))).lastrowid
    return cid


# ---- button rename ----
@cb("brk", admin=True)
async def c_brk(update, ctx, a):
    ctx.user_data["st"] = f"brn:{a[0]}"
    await say(update, ctx, f"🔤 Current: <b>{esc(label(a[0]))}</b>\nSend the new button name (emoji allowed):")


@cb("brr", admin=True)
async def c_brr(update, ctx, a):
    run("DELETE FROM labels")
    t, m = scr_btnrename()
    await show(update, ctx, "♻️ All button names reset.\n\n" + t, m)


# ---- product management ----
def product_card(p):
    c = one("SELECT name FROM categories WHERE id=?", (p["cat_id"],))
    t = (f"📦 <b>#{p['id']} {esc(p['name'])}</b>\n💰 {money(p['price'])} TK\n🗂 {esc(c['name'] if c else '-')}\n"
         f"🖼 Image: {'yes' if p['image'] else 'no'}\n👁 Visible: {'yes' if p['active'] else 'no'}\n🕐 {fmt_short(p['added'])}")
    i = p["id"]
    m = IM([[ib("✏️ Name", f"ef:name:{i}", "primary"), ib("💰 Price", f"ef:price:{i}", "success")],
            [ib("🖼 Image", f"ef:image:{i}", "danger"), ib("🗂 Category", f"ef:cat:{i}", "primary")],
            [ib("👁 Hide/Show", f"et:{i}", "success"), ib("🗑 Delete", f"ed:{i}", "danger")]])
    return t, m


@cb("ep", admin=True)
async def c_ep(update, ctx, a):
    p = one("SELECT * FROM products WHERE id=?", (int(a[0]),))
    if p:
        t, m = product_card(p)
        await show(update, ctx, t, m)


@cb("ef", admin=True)
async def c_ef(update, ctx, a):
    field, pid = a[0], int(a[1])
    if field == "cat":
        rows = grid([(c["name"], f"ec:{pid}:{c['id']}") for c in rows_("SELECT * FROM categories ORDER BY pos,id")], 2)
        await show(update, ctx, "🗂 Choose the new category:", IM(rows))
        return
    ctx.user_data["st"] = f"ef:{field}:{pid}"
    hint = {"name": "the new name", "price": "the new price", "image": "a photo or an image link"}[field]
    await say(update, ctx, f"Send {hint}:")


@cb("ec", admin=True)
async def c_ec(update, ctx, a):
    run("UPDATE products SET cat_id=? WHERE id=?", (int(a[1]), int(a[0])))
    t, m = product_card(one("SELECT * FROM products WHERE id=?", (int(a[0]),)))
    await show(update, ctx, t, m)


@cb("et", admin=True)
async def c_et(update, ctx, a):
    p = one("SELECT * FROM products WHERE id=?", (int(a[0]),))
    run("UPDATE products SET active=? WHERE id=?", (0 if p["active"] else 1, p["id"]))
    t, m = product_card(one("SELECT * FROM products WHERE id=?", (p["id"],)))
    await show(update, ctx, t, m)


@cb("ed", admin=True)
async def c_ed(update, ctx, a):
    pid = int(a[0])
    if len(a) == 1:
        await show(update, ctx, f"⚠️ Delete product #{pid} permanently?",
                   IM([[ib("✅ Yes, delete", f"ed:{pid}:y", "danger"), ib("↩️ No", f"ep:{pid}", "primary")]]))
        return
    run("DELETE FROM products WHERE id=?", (pid,))
    await show(update, ctx, f"🗑 Product #{pid} deleted.")


@cb("ap", admin=True)
async def c_ap(update, ctx, a):
    ctx.user_data["st"] = f"apn:{a[0]}"
    await say(update, ctx, "➕ Send: <code>Name | Price</code>\nOptional image link: <code>Name | Price | https://…</code>\n"
                           "Example: <code>Kothha ( Star Jalsha ) | 450</code>")


@cb("np", admin=True)
async def c_np(update, ctx, a):
    await notify_product(update, ctx, int(a[0]))


def parse_prod(s):
    parts = [x.strip() for x in (s.split("|") if "|" in s else s.rsplit("_", 2))]
    if len(parts) < 2 or not parts[0]:
        return None
    try:
        price = float(parts[1])
    except ValueError:
        return None
    return parts[0], price, (parts[2] if len(parts) > 2 else "")


def add_product(cat, name, price, img=""):
    return run("INSERT INTO products(cat_id,name,price,image,added) VALUES(?,?,?,?,?)", (cat, name, price, img, now())).lastrowid


def product_msg(p):
    c = one("SELECT name FROM categories WHERE id=?", (p["cat_id"],))
    return f"🆕 <b>{esc(p['name'])}</b>\n📢 {esc(c['name'] if c else '')}\n💰 {money(p['price'])} TK"


async def after_add(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    await say(update, ctx, f"✅ Product added!\n\n{product_msg(p)}\nID: <code>{pid}</code>")
    await tolog(ctx, "product", f"added #{pid} {p['name']} {money(p['price'])}")
    me = (await ctx.bot.get_me()).username
    if S("autopost") == "1" and S("channel"):
        try:
            await send(ctx, chat_ref(S("channel")), product_msg(p),
                       IM([[ib("🛒 Buy Now", url=bot_link(me, f"p{pid}"), style="success")]]), p["image"] or None)
        except TelegramError as e:
            await say(update, ctx, f"⚠️ Auto-post failed: {esc(e)}")
    if S("notify_new") == "1":
        await notify_product(update, ctx, pid)


async def notify_product(update, ctx, pid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    if not p:
        return
    markup = IM([[ib("🛒 Open", f"pp:{pid}", "success")]])

    async def sender(uid):
        await send(ctx, uid, product_msg(p), markup, p["image"] or None)
    await start_broadcast(update, ctx, "all", sender)


# ============================== ADMIN KEYBOARD HANDLERS ==============================
async def a_broadcast(update, ctx):
    ctx.user_data["st"] = "bc:all"
    await say(update, ctx, "📢 <b>Broadcast</b>\nSend the message for ALL users (text, photo + caption, video…).\n/cancel to abort.")


async def a_pending(update, ctx):
    chat = update.effective_chat.id
    pays = rows_("SELECT * FROM payments WHERE status='pending' ORDER BY id LIMIT 20")
    ords = rows_("SELECT * FROM orders WHERE status='pending' ORDER BY id LIMIT 20")
    if not pays and not ords:
        await say(update, ctx, "✅ Nothing pending.")
        return
    for p in pays:
        await send(ctx, chat, f"💳 <b>Deposit #{p['id']}</b>\n👤 <code>{p['uid']}</code>\n{METHODS[p['method']][1]} — ৳{money(p['amount'])}\n"
                              f"TrxID: <code>{esc(p['trx'])}</code>\n🕐 {fmt_short(p['created'])}",
                   IM([[ib("✅ Approve", f"pay:ok:{p['id']}", "success"), ib("❌ Reject", f"pay:no:{p['id']}", "danger")]]))
    for o in ords:
        await send(ctx, chat, f"📦 <b>Order #{o['id']}</b>\n👤 <code>{o['uid']}</code>\n{esc(o['name'])} — {money(o['price'])}৳\n🕐 {fmt_short(o['created'])}",
                   IM([[ib("📦 Deliver", f"dl:{o['id']}", "success")]]))


async def a_total(update, ctx):
    await say(update, ctx, f"👥 Total users: <b>{count('SELECT COUNT(*) FROM users')}</b>")


async def a_users(update, ctx):
    t, m = users_page(0)
    await say(update, ctx, t, m)


async def a_sendprod(update, ctx):
    ords = rows_("SELECT * FROM orders WHERE status='pending' ORDER BY id LIMIT 20")
    if not ords:
        await say(update, ctx, "✅ No pending orders.\nManual send: <code>/sendproduct uid details</code>")
        return
    rows = [[ib(f"📦 #{o['id']} {o['name'][:25]} → {o['uid']}", f"dl:{o['id']}", CYCLE[i % 3])] for i, o in enumerate(ords)]
    await say(update, ctx, "📦 <b>Pending orders</b> — tap one to deliver:\n(or <code>/sendproduct uid details</code>)", IM(rows))


async def a_delivered(update, ctx):
    r = rows_("SELECT * FROM orders WHERE status='delivered' ORDER BY delivered DESC LIMIT 25")
    await send_long(ctx, update.effective_chat.id, "📬 <b>Delivered (last 25)</b>\n" + (
        "\n".join(f"✅ #{o['id']} {esc(o['name'])} → <code>{o['uid']}</code> {fmt_short(o['delivered'])}" for o in r) or "None"))


async def a_refertop(update, ctx):
    r = rows_("SELECT ref_by, COUNT(*) n FROM users WHERE ref_by>0 AND refer_paid=1 GROUP BY ref_by ORDER BY n DESC LIMIT 10")
    lines = []
    for i, x in enumerate(r, 1):
        u = user(x["ref_by"])
        lines.append(f"{i}. <code>{x['ref_by']}</code> @{esc(u['username']) if u else ''} — {x['n']} refs — {u['refer_balance']:.2f}৳" if u else f"{i}. {x['ref_by']} — {x['n']}")
    await say(update, ctx, "👥 <b>Refer Top</b>\n" + ("\n".join(lines) or "No referrals yet."))


async def a_reset(update, ctx):
    ctx.user_data.clear()
    await say(update, ctx, panel_text(), admin_kb())


async def a_paystats(update, ctx):
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    lines = []
    for k, (e, n) in METHODS.items():
        r = one("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE method=? AND status='approved'", (k,))
        lines.append(f"{e} {n}: {r[0]} deposits — ৳{r[1]:.2f}")
    td = one("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM payments WHERE status='approved' AND decided>=?", (int(today),))
    await say(update, ctx, "⚡ <b>Online Payment Stats</b>\n\n" + "\n".join(lines) +
              f"\n\n📅 Today: {td[0]} deposits — ৳{td[1]:.2f}\n⏳ Pending: {count('SELECT COUNT(*) FROM payments WHERE status=?', ('pending',))}\n"
              f"💰 Total approved: ৳{one('SELECT COALESCE(SUM(amount),0) FROM payments WHERE status=?', ('approved',))[0]:.2f}")


async def a_jointest(update, ctx):
    ch = S("channel")
    if not ch:
        await say(update, ctx, "⚠️ No channel is set.")
        return
    try:
        chat = await ctx.bot.get_chat(chat_ref(ch))
        me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
        m = await ctx.bot.get_chat_member(chat.id, update.effective_user.id)
        await say(update, ctx, f"🔍 <b>Join Test</b>\nChannel: {esc(chat.title)}\nBot status: <b>{me.status}</b> "
                               f"{'✅' if me.status == 'administrator' else '⚠️ make the bot admin'}\nYour status: <b>{m.status}</b>")
    except TelegramError as e:
        await say(update, ctx, f"❌ Join test failed: {esc(e)}\nAdd the bot as admin to the channel.")


async def a_joinlogs(update, ctx):
    r = rows_("SELECT * FROM logs WHERE kind='join' ORDER BY id DESC LIMIT 30")
    await send_long(ctx, update.effective_chat.id, "📋 <b>Join Logs</b>\n" + ("\n".join(f"{fmt_short(x['ts'])} — {esc(x['text'])}" for x in r) or "None"))


async def a_timechecks(update, ctx):
    d = dt.datetime.now(TZ)
    u = dt.datetime.now(dt.timezone.utc)
    up = int(time.time() - START_TS)
    await say(update, ctx, f"👥 <b>Time Checks</b>\n\n🇧🇩 Dhaka: {d:%Y-%m-%d %H:%M:%S}\n🌍 UTC: {u:%Y-%m-%d %H:%M:%S}\n"
                           f"⏱ Bot uptime: {up // 3600}h {up % 3600 // 60}m {up % 60}s")


async def a_timelive(update, ctx):
    m = await say(update, ctx, time_text())

    async def job():
        for _ in range(25):
            await asyncio.sleep(1.2)
            try:
                await m.edit_text(time_text() + "\n\n🔴 LIVE", parse_mode=HTML)
            except TelegramError:
                break
    ctx.application.create_task(job())


def autofix():
    rep = []
    n = run("UPDATE users SET balance=0 WHERE balance<0").rowcount
    rep.append(f"negative balances fixed: {n}")
    run("UPDATE users SET total_orders=(SELECT COUNT(*) FROM orders o WHERE o.uid=users.uid), "
        "total_spent=(SELECT COALESCE(SUM(price),0) FROM orders o WHERE o.uid=users.uid)")
    rep.append("user order totals recalculated")
    n = run("UPDATE orders SET status='pending' WHERE status NOT IN ('pending','delivered')").rowcount
    rep.append(f"odd order statuses fixed: {n}")
    orphan = count("SELECT COUNT(*) FROM products WHERE cat_id NOT IN (SELECT id FROM categories)")
    if orphan:
        run("UPDATE products SET cat_id=? WHERE cat_id NOT IN (SELECT id FROM categories)", (ensure_cat("📦 Others"),))
    rep.append(f"orphan products moved: {orphan}")
    n = run("UPDATE payments SET status='cancelled' WHERE status='created' AND created<?", (now() - 86400,)).rowcount
    rep.append(f"stale invoices cancelled: {n}")
    n = run("UPDATE products SET price=0 WHERE price<0").rowcount
    rep.append(f"negative prices fixed: {n}")
    setS("autofix_last", f"{fmt_short(now())}\n" + "\n".join(rep))
    setS("autofix_runs", int(Sf("autofix_runs")) + 1)
    return rep


async def a_autofix(update, ctx):
    rep = autofix()
    await say(update, ctx, "🛠 <b>Auto-Fix done</b>\n" + "\n".join(f"• {x}" for x in rep))


async def a_autofixstats(update, ctx):
    await say(update, ctx, f"📊 <b>Auto-Fix Stats</b>\nRuns: {int(Sf('autofix_runs'))}\n\nLast run:\n{esc(S('autofix_last'))}")


async def a_adsstatus(update, ctx):
    tot = one("SELECT COUNT(*), COALESCE(SUM(reward),0) FROM ad_views")
    today = dt.datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    td = one("SELECT COUNT(*), COALESCE(SUM(reward),0) FROM ad_views WHERE ts>=?", (int(today),))
    top = rows_("SELECT uid, COUNT(*) n FROM ad_views GROUP BY uid ORDER BY n DESC LIMIT 5")
    await say(update, ctx, f"📊 <b>Ads Status</b>\nAd set: {'✅' if (S('ad_text') or S('ad_url')) else '❌'}\n"
                           f"Total views: {tot[0]} (paid ৳{tot[1]:.2f})\nToday: {td[0]} (৳{td[1]:.2f})\nLocked users: {count('SELECT COUNT(*) FROM users WHERE ads_lock=1')}\n\n"
                           f"Top viewers:\n" + ("\n".join(f"<code>{x['uid']}</code> — {x['n']}" for x in top) or "—"))


async def a_active(update, ctx):
    n = now()
    c = lambda s: count("SELECT COUNT(*) FROM users WHERE last_active>?", (n - s,))
    await say(update, ctx, f"👥 <b>Active Users</b>\n🟢 Last hour: {c(3600)}\n🟢 Last 24h: {c(86400)}\n🟢 Last 7 days: {c(604800)}\n"
                           f"👥 Total: {count('SELECT COUNT(*) FROM users')}")


async def a_activedetail(update, ctx):
    r = rows_("SELECT * FROM users WHERE last_active>? ORDER BY last_active DESC LIMIT 40", (now() - 86400,))
    await send_long(ctx, update.effective_chat.id, "📄 <b>Active (24h)</b>\n" + (
        "\n".join(f"<code>{u['uid']}</code> @{esc(u['username'])} — {(now() - u['last_active']) // 60} min ago" for u in r) or "None"))


async def a_adslock(update, ctx):
    ctx.user_data["st"] = "adslock:1"
    await say(update, ctx, "🔐 Send the user ID or @username to <b>lock ads</b> for:")


async def a_unlock(update, ctx):
    ctx.user_data["st"] = "adslock:0"
    await say(update, ctx, "🔓 Send the user ID or @username to <b>unlock</b>:")


async def a_allprodcheck(update, ctx):
    r = rows_("SELECT p.*, c.name cname FROM products p LEFT JOIN categories c ON c.id=p.cat_id ORDER BY p.id DESC")
    names = {}
    for p in r:
        names.setdefault(p["name"].lower(), []).append(p["id"])
    probs = []
    for p in r:
        issues = []
        if not p["image"]:
            issues.append("no image")
        if p["price"] <= 0:
            issues.append("price 0")
        if len(names[p["name"].lower()]) > 1:
            issues.append("duplicate name")
        if not p["active"]:
            issues.append("hidden")
        if issues:
            probs.append(f"#{p['id']} {esc(p['name'])} — {', '.join(issues)}")
    await send_long(ctx, update.effective_chat.id, f"📦 <b>All Products Check</b>\nTotal: {len(r)}\nWith issues: {len(probs)}\n\n" + "\n".join(probs[:150]))


async def a_prodinfo(update, ctx):
    r = rows_("SELECT c.name, COUNT(p.id) n FROM categories c LEFT JOIN products p ON p.cat_id=c.id AND p.active=1 GROUP BY c.id ORDER BY c.pos, c.id")
    tot = one("SELECT COUNT(*), COALESCE(AVG(price),0) FROM products WHERE active=1")
    await send_long(ctx, update.effective_chat.id, f"📊 <b>Products Info</b>\nActive products: {tot[0]} | Avg price: {tot[1]:.0f}TK\n"
                                                    f"Hidden: {count('SELECT COUNT(*) FROM products WHERE active=0')}\n\n" +
                    "\n".join(f"{esc(x['name'])}: {x['n']}" for x in r))


async def send_users_csv(ctx, chat):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["uid", "username", "name", "balance", "refer_balance", "orders", "spent", "ref_by", "banned", "phone", "joined", "last_active"])
    for u in rows_("SELECT * FROM users ORDER BY joined"):
        w.writerow([u["uid"], u["username"], u["name"], u["balance"], u["refer_balance"], u["total_orders"], u["total_spent"],
                    u["ref_by"], u["banned"], u["phone"], fmt_short(u["joined"]), fmt_short(u["last_active"])])
    data = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    data.name = "users.csv"
    await ctx.bot.send_document(chat, data, caption=f"👥 {count('SELECT COUNT(*) FROM users')} users")


async def a_allusers(update, ctx):
    await send_users_csv(ctx, update.effective_chat.id)


async def a_userinfo(update, ctx):
    ctx.user_data["st"] = "uinfo"
    await say(update, ctx, "🔍 Send the user ID or @username:")


async def a_welcome(update, ctx):
    ctx.user_data["st"] = "set:welcome_bonus"
    await say(update, ctx, f"🎁 Current welcome bonus: <b>{S('welcome_bonus')}৳</b>\n" + SET_INFO["welcome_bonus"][0])


async def a_id(update, ctx):
    await m_id(update, ctx)


async def a_usermenu(update, ctx):
    await say(update, ctx, "👤 User menu", main_menu())


async def a_addprod(update, ctx):
    cs = rows_("SELECT * FROM categories ORDER BY pos, id")
    if not cs:
        await say(update, ctx, "🗂 Create a category first (tap <b>🗂 Categories</b> → ➕ Add Category).")
        return
    await say(update, ctx, "➕ <b>Add Product</b> — choose the category:", IM(grid([(c["name"], f"ap:{c['id']}") for c in cs], 2)))


async def a_editprod(update, ctx):
    ctx.user_data["st"] = "epfind"
    await say(update, ctx, "✏️ Send the product <b>ID</b> or part of its <b>name</b>:")


async def a_delprod(update, ctx):
    ctx.user_data["st"] = "dpfind"
    await say(update, ctx, "🗑 Send the product <b>ID</b> or part of its <b>name</b> to delete:")


async def a_notifyprod(update, ctx):
    ctx.user_data["st"] = "npfind"
    await say(update, ctx, "📢 Send the product <b>ID</b> or <b>name</b> to announce to all users:")


ADMIN = {"broadcast": a_broadcast, "pending": a_pending, "total": a_total, "users": a_users, "sendprod": a_sendprod,
         "delivered": a_delivered, "refertop": a_refertop, "reset": a_reset, "paystats": a_paystats, "jointest": a_jointest,
         "joinlogs": a_joinlogs, "timechecks": a_timechecks, "timelive": a_timelive, "autofix": a_autofix,
         "autofixstats": a_autofixstats, "adsstatus": a_adsstatus, "active": a_active, "activedetail": a_activedetail,
         "adslock": a_adslock, "unlock": a_unlock, "allprodcheck": a_allprodcheck, "prodinfo": a_prodinfo,
         "allusers": a_allusers, "userinfo": a_userinfo, "welcome": a_welcome, "id": a_id, "usermenu": a_usermenu,
         "addprod": a_addprod, "editprod": a_editprod, "delprod": a_delprod, "notifyprod": a_notifyprod}
SCREEN_KEYS = {"bcenter": "bcenter", "channel": "channel", "logch": "logch", "referprot": "refer", "phoneprot": "phone",
               "pnotify": "notify", "autopost": "autopost", "paymethod": "paymethod", "paytoggle": "paytoggle",
               "shopname": "shop", "comments": "comments", "adminads": "ads", "btnrename": "btnrename", "cats": "cats"}


async def run_admin_key(update, ctx, key):
    if key in SCREEN_KEYS:
        await send_screen(update, ctx, SCREEN_KEYS[key])
    else:
        await ADMIN[key](update, ctx)


# ============================== MESSAGE HANDLERS ==============================
async def on_text(update, ctx):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    await reg(update, ctx)
    st = ctx.user_data.get("st")
    if uid in ADMIN_IDS:
        for k, v in alabels().items():
            if v == text:
                ctx.user_data.pop("st", None)
                await run_admin_key(update, ctx, k)
                return
    for k in LABELS:
        if label(k) == text:
            ctx.user_data.pop("st", None)
            if await guard(update, ctx):
                await MENU[k](update, ctx)
            return
    if st:
        await handle_state(update, ctx, st, text)


USER_STATES = {"search", "dep_amt", "trx"}


async def handle_state(update, ctx, st, text):
    uid = update.effective_user.id
    p = st.split(":")
    k = p[0]
    if k not in USER_STATES and uid not in ADMIN_IDS:
        ctx.user_data.pop("st", None)
        return
    if not await guard(update, ctx):
        return
    pop = lambda: ctx.user_data.pop("st", None)

    if k == "search":
        pop()
        ctx.user_data["sq"] = text[:50]
        await view_list(update, ctx, -1, 0)

    elif k == "dep_amt":
        try:
            amt = float(text.replace(",", ""))
        except ValueError:
            await say(update, ctx, "❌ Send a valid number.")
            return
        if amt < Sf("min_deposit"):
            await say(update, ctx, f"❌ Minimum deposit is {money(Sf('min_deposit'))}.")
            return
        if not ctx.user_data.get("dep"):
            pop()
            return
        ctx.user_data["dep"]["amt"] = amt
        pop()
        await view_dep(update, ctx)

    elif k == "trx":
        pay = one("SELECT * FROM payments WHERE id=?", (int(p[1]),))
        if not pay or pay["status"] != "created":
            pop()
            return
        if len(text) < 6 or len(text) > 64 or " " in text:
            await say(update, ctx, "❌ That does not look like a TrxID. Send it again (or /cancel).")
            return
        if one("SELECT id FROM payments WHERE trx=? AND status IN ('pending','approved')", (text,)):
            await say(update, ctx, "❌ This TrxID was already used.")
            return
        run("UPDATE payments SET trx=?, status='pending' WHERE id=?", (text, pay["id"]))
        pop()
        ctx.user_data.pop("dep", None)
        await say(update, ctx, "✅ TrxID received! Your balance is added as soon as an admin approves it.")
        u = user(uid)
        await notify_admins(ctx, f"💳 <b>New deposit #{pay['id']}</b>\n👤 <code>{uid}</code> @{esc(u['username'])}\n"
                                 f"{METHODS[pay['method']][1]} — ৳{money(pay['amount'])}\nTrxID: <code>{esc(text)}</code>",
                            IM([[ib("✅ Approve", f"pay:ok:{pay['id']}", "success"), ib("❌ Reject", f"pay:no:{pay['id']}", "danger")]]))

    elif k == "set":
        key = p[1]
        prompt, typ, back = SET_INFO[key]
        val = text
        try:
            if typ == "f":
                val = str(float(text))
                if float(val) < 0:
                    raise ValueError
            elif typ == "i":
                val = str(int(text))
            elif typ == "amounts":
                val = ",".join(money(float(x)) for x in text.replace(" ", "").split(",") if x)
                if not val:
                    raise ValueError
            elif typ == "ch":
                if text.lower() in ("none", "off", "-"):
                    val = ""
                elif not (text.startswith("@") or text.lstrip("-").isdigit()):
                    raise ValueError
        except ValueError:
            await say(update, ctx, "❌ Invalid value, try again (or /cancel).")
            return
        setS(key, val)
        pop()
        await say(update, ctx, "✅ Saved.")
        if back:
            await send_screen(update, ctx, back)

    elif k == "addcat":
        pop()
        try:
            ensure_cat(text[:40])
        except sqlite3.Error:
            pass
        await send_screen(update, ctx, "cats")

    elif k == "rencat":
        pop()
        try:
            run("UPDATE categories SET name=? WHERE id=?", (text[:40], int(p[1])))
        except sqlite3.IntegrityError:
            await say(update, ctx, "❌ That name already exists.")
        await send_screen(update, ctx, "cats")

    elif k == "apn":
        parsed = parse_prod(text)
        if not parsed:
            await say(update, ctx, "❌ Format: <code>Name | Price</code> (or <code>Name | Price | image link</code>)")
            return
        pid = add_product(int(p[1]), *parsed)
        if parsed[2]:
            pop()
            await after_add(update, ctx, pid)
        else:
            ctx.user_data["st"] = f"api:{pid}"
            await say(update, ctx, "🖼 Now send the product <b>photo</b> or an image link.\nOr /skip to add without an image.")

    elif k == "api":
        pop()
        run("UPDATE products SET image=? WHERE id=?", (text, int(p[1])))
        await after_add(update, ctx, int(p[1]))

    elif k in ("epfind", "dpfind", "npfind"):
        pop()
        r = [one("SELECT * FROM products WHERE id=?", (int(text),))] if text.isdigit() else \
            rows_("SELECT * FROM products WHERE name LIKE ? ORDER BY id DESC LIMIT 10", (f"%{text}%",))
        r = [x for x in r if x]
        if not r:
            await say(update, ctx, "❌ Nothing found.")
            return
        pre = {"epfind": "ep", "dpfind": "ed", "npfind": "np"}[k]
        rows = [[ib(f"#{x['id']} {x['name'][:30]} {money(x['price'])}TK", f"{pre}:{x['id']}", CYCLE[i % 3])] for i, x in enumerate(r)]
        await say(update, ctx, "Select a product:", IM(rows))

    elif k == "ef":
        field, pid = p[1], int(p[2])
        if field == "name":
            run("UPDATE products SET name=? WHERE id=?", (text, pid))
        elif field == "price":
            try:
                run("UPDATE products SET price=? WHERE id=?", (float(text), pid))
            except ValueError:
                await say(update, ctx, "❌ Send a number.")
                return
        else:
            run("UPDATE products SET image=? WHERE id=?", (text, pid))
        pop()
        t, m = product_card(one("SELECT * FROM products WHERE id=?", (pid,)))
        await say(update, ctx, "✅ Updated.\n\n" + t, m)

    elif k == "uinfo":
        pop()
        u = find_user(text)
        if not u:
            await say(update, ctx, "❌ User not found.")
            return
        t, m = user_card(u)
        await say(update, ctx, t, m)

    elif k == "adslock":
        pop()
        u = find_user(text)
        if not u:
            await say(update, ctx, "❌ User not found.")
            return
        run("UPDATE users SET ads_lock=? WHERE uid=?", (int(p[1]), u["uid"]))
        await say(update, ctx, f"{'🔐 Ads locked' if p[1] == '1' else '🔓 Ads unlocked'} for <code>{u['uid']}</code>.")

    elif k == "bal":
        try:
            amt = float(text)
        except ValueError:
            await say(update, ctx, "❌ Send a number.")
            return
        pop()
        await change_balance(update, ctx, int(p[2]), amt if p[1] == "add" else -amt)

    elif k == "send":
        pop()
        oid = int(p[1])
        o = one("SELECT * FROM orders WHERE id=?", (oid,))
        if not o or o["status"] != "pending":
            await say(update, ctx, "Order not pending anymore.")
            return
        await deliver_order(ctx, oid, text)
        await say(update, ctx, f"✅ Order #{oid} delivered to <code>{o['uid']}</code>.")

    elif k == "brn":
        pop()
        taken = {label(x) for x in LABELS if x != p[1]} | set(alabels().values())
        if text in taken:
            await say(update, ctx, "❌ That name is already used by another button.")
            return
        run("INSERT INTO labels(key,text) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET text=excluded.text", (p[1], text[:40]))
        await say(update, ctx, "✅ Renamed. Users get the new keyboard on their next /start.", main_menu())
        await send_screen(update, ctx, "btnrename")

    elif k == "bc":
        pop()   # text broadcast (non-text goes through on_media)
        await run_bc(update, ctx, p[1])


async def run_bc(update, ctx, kind):
    m = update.message

    async def sender(uid):
        await ctx.bot.copy_message(uid, m.chat_id, m.message_id)
    await start_broadcast(update, ctx, kind, sender)


async def change_balance(update, ctx, uid, delta):
    u = user(uid)
    if not u:
        await say(update, ctx, "❌ User not found.")
        return
    add_bal(uid, delta)
    await say(update, ctx, f"✅ {'Added' if delta >= 0 else 'Removed'} {abs(delta):g}৳ — new balance {user(uid)['balance']:.2f}৳")
    await notify_user(ctx, uid, f"{'💰' if delta >= 0 else '➖'} Admin {'added' if delta >= 0 else 'removed'} <b>{abs(delta):g}৳</b> "
                                f"{'to' if delta >= 0 else 'from'} your balance.")
    await tolog(ctx, "balance", f"{uid} {delta:+g}")


async def on_media(update, ctx):
    uid = update.effective_user.id
    st = ctx.user_data.get("st", "")
    if uid not in ADMIN_IDS or not st:
        return
    p = st.split(":")
    if p[0] == "bc":
        ctx.user_data.pop("st")
        await run_bc(update, ctx, p[1])
    elif p[0] in ("api", "ef") and update.message.photo:
        pid = int(p[1] if p[0] == "api" else p[2])
        if p[0] == "ef" and p[1] != "image":
            return
        run("UPDATE products SET image=? WHERE id=?", (update.message.photo[-1].file_id, pid))
        ctx.user_data.pop("st")
        if p[0] == "api":
            await after_add(update, ctx, pid)
        else:
            t, m = product_card(one("SELECT * FROM products WHERE id=?", (pid,)))
            await say(update, ctx, "✅ Image updated.\n\n" + t, m)


async def on_contact(update, ctx):
    uid = update.effective_user.id
    c = update.message.contact
    if c.user_id != uid:
        await say(update, ctx, "❌ Please share your own number.")
        return
    phone = c.phone_number.lstrip("+")
    if one("SELECT uid FROM users WHERE phone=? AND uid!=?", (phone, uid)):
        await say(update, ctx, "❌ This phone number is already used by another account.")
        return
    run("UPDATE users SET phone=? WHERE uid=?", (phone, uid))
    await say(update, ctx, "✅ Verified!", main_menu())
    await first_pass(ctx, user(uid))


# ============================== COMMANDS ==============================
def admin_only(f):
    async def w(update, ctx):
        if update.effective_user.id in ADMIN_IDS:
            await reg(update, ctx)
            await f(update, ctx)
    return w


def rest(update):
    parts = (update.message.text or "").split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


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
    await reg(update, ctx)
    await m_id(update, ctx)


async def cmd_cancel(update, ctx):
    await cancel_flow(ctx, update.effective_user.id)
    await say(update, ctx, "❌ Cancelled.")


async def cmd_skip(update, ctx):
    st = ctx.user_data.get("st", "")
    if st.startswith("api:") and update.effective_user.id in ADMIN_IDS:
        ctx.user_data.pop("st")
        await after_add(update, ctx, int(st.split(":")[1]))


@admin_only
async def cmd_admin(update, ctx):
    await say(update, ctx, panel_text(), admin_kb())


@admin_only
async def cmd_addbal(update, ctx):
    try:
        await change_balance(update, ctx, int(ctx.args[0]), float(ctx.args[1]))
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /addbal uid amount")


@admin_only
async def cmd_removebal(update, ctx):
    try:
        await change_balance(update, ctx, int(ctx.args[0]), -float(ctx.args[1]))
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /removebal uid amount")


@admin_only
async def cmd_sendproduct(update, ctx):
    try:
        uid = int(ctx.args[0])
        details = rest(update).split(None, 1)[1]
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /sendproduct uid details")
        return
    o = one("SELECT * FROM orders WHERE uid=? AND status='pending' ORDER BY id LIMIT 1", (uid,))
    if o:
        await deliver_order(ctx, o["id"], details)
        await say(update, ctx, f"✅ Order #{o['id']} delivered to {uid}.")
    elif await notify_user(ctx, uid, f"📦 <b>Delivery</b>\n\n{esc(details)}"):
        await say(update, ctx, f"✅ Sent to {uid} (no pending order found).")
    else:
        await say(update, ctx, "❌ Could not send (user blocked the bot?).")


@admin_only
async def cmd_history(update, ctx):
    r = rows_("SELECT * FROM orders ORDER BY id DESC LIMIT 30")
    await send_long(ctx, update.effective_chat.id, "🧾 <b>Order history (last 30)</b>\n" + (
        "\n".join(f"{'✅' if o['status'] == 'delivered' else '⏳'} #{o['id']} {esc(o['name'])} {money(o['price'])}TK → <code>{o['uid']}</code>" for o in r) or "None"))


@admin_only
async def cmd_userinfo(update, ctx):
    u = find_user(ctx.args[0]) if ctx.args else None
    if not u:
        await say(update, ctx, "Usage: /userinfo uid|@username")
        return
    t, m = user_card(u)
    await say(update, ctx, t, m)


@admin_only
async def cmd_all_usr_info(update, ctx):
    await send_users_csv(ctx, update.effective_chat.id)


@admin_only
async def cmd_all_list(update, ctx):
    r = rows_("SELECT p.*, c.name cname FROM products p LEFT JOIN categories c ON c.id=p.cat_id ORDER BY p.id DESC")
    await send_long(ctx, update.effective_chat.id, f"📋 <b>All products ({len(r)})</b>\n" + "\n".join(
        f"#{p['id']} [{esc(p['cname'])}] {esc(p['name'])} — {money(p['price'])}TK{' 🖼' if p['image'] else ''}" for p in r))


@admin_only
async def cmd_broadcast(update, ctx):
    txt = rest(update)
    if not txt:
        await a_broadcast(update, ctx)
        return

    async def sender(uid):
        await send(ctx, uid, txt)
    await start_broadcast(update, ctx, "all", sender)


@admin_only
async def cmd_pending(update, ctx):
    await a_pending(update, ctx)


@admin_only
async def cmd_delivered(update, ctx):
    await a_delivered(update, ctx)


@admin_only
async def cmd_add_product(update, ctx):
    parsed = parse_prod(rest(update))
    if not parsed:
        await say(update, ctx, "Usage: /add_product Name_Price_Logo   or   /add_product Name | Price | Logo")
        return
    pid = add_product(ensure_cat("📦 Others"), *parsed)
    await after_add(update, ctx, pid)


@admin_only
async def cmd_del_product(update, ctx):
    t = rest(update)
    p = one("SELECT * FROM products WHERE id=?", (int(t),)) if t.isdigit() else one("SELECT * FROM products WHERE name=? COLLATE NOCASE", (t,))
    if not p:
        await say(update, ctx, "Usage: /del_product name_or_id")
        return
    run("DELETE FROM products WHERE id=?", (p["id"],))
    await say(update, ctx, f"🗑 Deleted #{p['id']} {esc(p['name'])}")


@admin_only
async def cmd_edit_product(update, ctx):
    parts = [x.strip() for x in rest(update).split("|")]
    try:
        pid, name, price = int(parts[0]), parts[1], float(parts[2])
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /edit_product ID| New Name | New Price")
        return
    run("UPDATE products SET name=?, price=? WHERE id=?", (name, price, pid))
    await say(update, ctx, "✅ Updated.")


@admin_only
async def cmd_set_price(update, ctx):
    try:
        run("UPDATE products SET price=? WHERE id=?", (float(ctx.args[1]), int(ctx.args[0])))
        await say(update, ctx, "✅ Price updated.")
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /set_price product_id new_price")


@admin_only
async def cmd_set_product_image(update, ctx):
    try:
        run("UPDATE products SET image=? WHERE id=?", (ctx.args[1], int(ctx.args[0])))
        await say(update, ctx, "✅ Image updated.")
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /set_product_image product_id image_link")


@admin_only
async def cmd_set_startbonus(update, ctx):
    try:
        setS("welcome_bonus", float(ctx.args[0]))
        await say(update, ctx, f"✅ Welcome bonus = {ctx.args[0]}৳")
    except (IndexError, ValueError):
        await say(update, ctx, "Usage: /set_startbonus amount")


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
        BotCommand("userinfo", "user information"), BotCommand("all_usr_info", "all user information"),
        BotCommand("all_list", "All product list"), BotCommand("broadcast", "All Usr product notification"),
        BotCommand("pending", "pending payment clear admin only")])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    cmds = {"start": cmd_start, "id": cmd_id, "cancel": cmd_cancel, "skip": cmd_skip, "admin": cmd_admin,
            "addbal": cmd_addbal, "removebal": cmd_removebal, "sendproduct": cmd_sendproduct, "history": cmd_history,
            "userinfo": cmd_userinfo, "all_usr_info": cmd_all_usr_info, "all_list": cmd_all_list,
            "broadcast": cmd_broadcast, "pending": cmd_pending, "delivered": cmd_delivered,
            "add_product": cmd_add_product, "del_product": cmd_del_product, "edit_product": cmd_edit_product,
            "set_price": cmd_set_price, "set_product_image": cmd_set_product_image, "set_startbonus": cmd_set_startbonus}
    for name, fn in cmds.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.ANIMATION, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    if app.job_queue:
        app.job_queue.run_repeating(job_autofix, interval=6 * 3600, first=120)
    log.info("Bot started. Admins: %s", ADMIN_IDS)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
