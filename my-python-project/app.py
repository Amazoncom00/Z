import os
import re
import io
import json
import urllib.parse
import urllib.request
import asyncio
import time
import random
import string
from datetime import datetime
from threading import Thread
from flask import Flask

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, LabeledPrice
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    PicklePersistence,
    filters,
)

# ---------------- CONFIGURATION ---------------- #
ADMIN_ID = 8844584255
DB_CHANNEL_ID = -1003936910985
LOGO_URL_FALLBACK = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_WEBAPP_URL = os.environ.get(
    "GOOGLE_WEBAPP_URL",
    "https://script.google.com/macros/s/AKfycbzocUCl18JtTH8gGsFESRIR0rqWCG-WlYFjYa3yIdxakSRPP6jkWpxOsxepF46syzXB/exec"
)

# Global State Memory
admin_sessions = {}
click_locks = set()
active_live_chats = {}  # {user_id: True} when admin is chatting with user

# --- Dummy Flask Web Server for Cloud Hosting (Render/Koyeb/Heroku) ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Rebrand Bot with Google Sheets & Lejumo is Running 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ---------------- GOOGLE SHEETS WEB APP ENGINE ---------------- #
def gsheet_request(payload: dict) -> dict:
    """Sends JSON POST request to Google Apps Script Web App URL."""
    try:
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            GOOGLE_WEBAPP_URL,
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            res_text = response.read().decode('utf-8')
            return json.loads(res_text)
    except Exception as e:
        print(f"Google Sheet API Request Error: {e}")
        return {"status": "error", "message": str(e)}

def gsheet_get_all_users() -> dict:
    """Fetches all users from Google Sheet on startup."""
    try:
        url = f"{GOOGLE_WEBAPP_URL}?action=get_all_users"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            res_text = response.read().decode('utf-8')
            data = json.loads(res_text)
            if data.get("status") == "success":
                return data.get("users", {})
    except Exception as e:
        print(f"Error fetching all users from Google Sheet: {e}")
    return {}

async def sync_user_to_db(context: ContextTypes.DEFAULT_TYPE, user_id: int, discountpoint: int, refer_code: str = "None", refer_from: str = "None", status: str = "Active", admin_refer: str = "No", order_history: list = None):
    """Syncs user record in bot_data memory and Google Sheets in background."""
    user_records = context.bot_data.setdefault("user_records", {})
    existing = user_records.get(user_id, {})
    
    if order_history is None:
        order_history = existing.get("order_history", [])

    user_records[user_id] = {
        "userid": str(user_id),
        "discountpoint": discountpoint,
        "refer_code": refer_code,
        "refer_from": refer_from,
        "status": status,
        "admin_refer": admin_refer,
        "order_history": order_history,
        "last_report": existing.get("last_report", 0.0)
    }

    payload = {
        "action": "sync_user",
        "userid": str(user_id),
        "discountpoint": discountpoint,
        "refer_code": refer_code,
        "refer_from": refer_from,
        "status": status,
        "admin_refer": admin_refer,
        "order_history": order_history
    }
    await asyncio.to_thread(gsheet_request, payload)


# ---------------- HELPERS, SCRAPERS & SHORTENER ---------------- #
async def edit_message_or_caption(query, text, reply_markup=None, parse_mode="HTML"):
    try:
        if query.message.photo or query.message.video or query.message.document:
            await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await query.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception:
            pass

def format_inr(number_val) -> str:
    num = re.sub(r'\D', '', str(number_val))
    if not num: 
        return f"₹{number_val}"
    if len(num) <= 3: 
        return f"₹{num}"
    last_three = num[-3:]
    rest = num[:-3]
    chunks = []
    while rest:
        chunks.append(rest[-2:])
        rest = rest[:-2]
    chunks.reverse()
    return f"₹{','.join(chunks)},{last_three}"

def extract_flipkart_link(text: str) -> str:
    urls = re.findall(r'(https?://[^\s]+)', text)
    for url in urls:
        if 'flipkart' in url.lower() or 'fkrt' in url.lower():
            return url
    return ""

def fetch_flipkart_metadata(url: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-US,en;q=0.9,hi;q=0.8"
    }
    final_url = url
    html = ""
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            final_url = response.geturl()
            html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Flipkart Scrape Error: {e}")

    extracted_title = ""
    og_title = re.search(r'<meta\s+(?:property|name)=["\'](?:og:title|twitter:title)["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if og_title:
        extracted_title = og_title.group(1).strip()
    if not extracted_title:
        title_tag = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
        if title_tag:
            extracted_title = title_tag.group(1).strip()

    if extracted_title:
        extracted_title = re.sub(r':\s*Buy.*$', '', extracted_title, flags=re.IGNORECASE)
        extracted_title = re.sub(r'\|\s*Flipkart.*$', '', extracted_title, flags=re.IGNORECASE)
        extracted_title = re.sub(r'-\s*Flipkart.*$', '', extracted_title, flags=re.IGNORECASE).strip()

    if not extracted_title or "Flipkart" in extracted_title or len(extracted_title) < 4:
        slug_match = re.search(r'flipkart\.com/(?:dl/)?([^/?#]+)/p/', final_url, re.IGNORECASE)
        if slug_match:
            words = slug_match.group(1).split('-')
            extracted_title = " ".join([w.capitalize() for w in words if w])
    if not extracted_title:
        extracted_title = "Flipkart Product"

    extracted_price = 0
    selling_price_match = re.search(r'class=["\'][^"\']*(?:Nx9bqj|_30jeq3)[^"\']*["\'][^>]*>₹?\s*([\d,]+)', html)
    if selling_price_match:
        clean_p = re.sub(r'\D', '', selling_price_match.group(1))
        if clean_p and int(clean_p) > 0:
            extracted_price = int(clean_p)

    if not extracted_price:
        fsp_patterns = [
            r'"(?:FSP|SPECIAL_PRICE|finalPrice|discountedPrice|specialPrice)"[^}]*?"(?:value|decimalValue|amount)"\s*:\s*"?(\d+)',
            r'"(?:fsp|specialPrice|offerPrice)"\s*:\s*(\d+)',
            r'"prices"\s*:\s*\[\s*\{\s*"type"\s*:\s*"FSP"\s*,\s*"value"\s*:\s*(\d+)'
        ]
        for pat in fsp_patterns:
            f_match = re.search(pat, html, re.IGNORECASE)
            if f_match:
                val = next((x for x in f_match.groups() if x), None)
                if val and int(val) > 0:
                    extracted_price = int(val)
                    break

    image_url = None
    og_image = re.search(r'<meta\s+(?:property|name)=["\'](?:og:image|twitter:image)["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if og_image:
        image_url = og_image.group(1).strip()
    if not image_url:
        ruk_match = re.search(r'(https?://rukminim\d*\.flixcart\.com/image/[^\s"\'>]+)', html)
        if ruk_match:
            image_url = ruk_match.group(1).strip()

    image_bytes = None
    if image_url:
        try:
            img_req = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(img_req, timeout=10) as img_resp:
                image_bytes = img_resp.read()
        except Exception as img_err:
            print(f"Error downloading image: {img_err}")

    return extracted_title, extracted_price, image_bytes

def create_lejumo_short_link(destination_url: str) -> tuple[bool, str]:
    lejumo_key = os.environ.get("Lejumo_Api") or os.environ.get("LEJUMO_API") or os.environ.get("LEJUMO_API_KEY")
    if not lejumo_key:
        return False, "Lejumo_Api environment variable is missing!"

    endpoint = "https://www.lejumo.com/api/shorten"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {lejumo_key.strip()}",
        "User-Agent": "Mozilla/5.0"
    }
    dest = destination_url.strip()
    if not dest.startswith(('http://', 'https://')):
        dest = 'https://' + dest

    payload = {"url": dest}
    try:
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            short_url = data.get("short") or data.get("shortUrl")
            if short_url:
                final_short = f"https://{short_url}" if not short_url.startswith("http") else short_url
                return True, final_short
    except urllib.error.HTTPError as e:
        return False, f"Lejumo API Error ({e.code}): {e.read().decode('utf-8', errors='ignore')}"
    except Exception as ex:
        return False, f"Lejumo Exception: {str(ex)}"

    return False, "Could not obtain short link from Lejumo."

def generate_unique_referral_code(user_records):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
        if not any(str(r.get("refer_code", "")).strip().upper() == code for r in user_records.values()):
            return code

async def track_and_check_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return False
        
    user_records = context.bot_data.setdefault("user_records", {})
    if user_id not in user_records:
        await sync_user_to_db(context, user_id, 0)
        return False
        
    if str(user_records[user_id].get("status", "Active")).lower() == "blocked":
        return True
    return False


# ---------------- CHANNEL MEDIA SYNC ---------------- #
async def parse_channel_post_content(context: ContextTypes.DEFAULT_TYPE, message):
    if not message: return
    caption = message.caption or message.text or ""
    tags = ["Logo", "EnglishTutorial", "HindiTutorial", "ProductLink", "AccountNumber", "Ready", "NotAvalable"]
    for tag in tags:
        if tag in caption:
            if message.photo:
                context.bot_data[f"media_{tag}"] = message.photo[-1].file_id
                context.bot_data[f"media_{tag}_type"] = "photo"
            elif message.video:
                context.bot_data[f"media_{tag}"] = message.video.file_id
                context.bot_data[f"media_{tag}_type"] = "video"
            elif message.document:
                context.bot_data[f"media_{tag}"] = message.document.file_id
                context.bot_data[f"media_{tag}_type"] = "document"

async def channel_db_sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or post.chat_id != DB_CHANNEL_ID: return
    await parse_channel_post_content(context, post)

async def send_dynamic_media(context, chat_id, tag, caption=None, reply_markup=None):
    file_id = context.bot_data.get(f"media_{tag}")
    file_type = context.bot_data.get(f"media_{tag}_type")
    
    if not file_id:
        if tag == "Logo":
            await context.bot.send_photo(chat_id=chat_id, photo=LOGO_URL_FALLBACK, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode="HTML")
        return

    try:
        if file_type == "photo":
            await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        elif file_type == "video":
            await context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        elif file_type == "document":
            await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode="HTML")


# ---------------- BACKGROUND TIMERS (JOBS) ---------------- #
async def expire_deal_link_job(context: ContextTypes.DEFAULT_TYPE):
    """Triggered after 10 mins (600s) to expire checkout link."""
    job = context.job
    chat_id = job.data["chat_id"]
    msg_id = job.data["msg_id"]
    p_name = job.data["product_name"]
    orig_link = job.data["orig_link"]
    final_price = job.data["final_price"]
    is_media = job.data.get("is_media", False)

    expired_text = (
        f"⌛ <b>DISCOUNT DEAL EXPIRED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Product:</b> <a href='{orig_link}'>{p_name}</a>\n"
        f"<s>Deal Price: {final_price}</s>\n\n"
        f"❌ <i>Is discount token ki 10-minute validity khatam ho chuki hai. Standard Flipkart MRP wapas restore ho gayi hai.</i>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Go to Dashboard", callback_data="dashboard")]])
    try:
        if is_media:
            await context.bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=expired_text, parse_mode="HTML", reply_markup=kb)
        else:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=expired_text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        print(f"Deal expiry error: {e}")

async def admin_timeout_refund_job(context: ContextTypes.DEFAULT_TYPE):
    """Triggered if Admin doesn't accept/reject user link within 10 minutes (600s)."""
    job = context.job
    target_id = job.data["target_id"]
    
    pending = context.bot_data.get("pending_requests", {})
    if target_id not in pending:
        return  # Already accepted/rejected

    req_data = pending.pop(target_id, None)
    user_records = context.bot_data.get("user_records", {})
    rec = user_records.get(target_id, {})
    
    # Refund 1 Point back
    new_points = rec.get("discountpoint", 0) + 1
    await sync_user_to_db(context, target_id, new_points, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), rec.get("order_history", []))

    msg_text = (
        "⚠️ <b>High Server Traffic!</b>\n\n"
        "Abhi bohot saare users ek sath service use kar rahe hain, isliye aapki request process nahi ho payi.\n\n"
        "✅ <b>Aapka 1 Discount Point safely aapke account me wapas refund kar diya gaya hai.</b>\n"
        "Kripya thodi der baad dobara koshish karein."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Dashboard", callback_data="dashboard")]])
    try:
        await send_dynamic_media(context, target_id, "NotAvalable", caption=msg_text, reply_markup=kb)
    except Exception as e:
        print(f"Timeout notify error: {e}")

    # Remove or update admin pending card
    admin_msg_id = req_data.get("admin_msg_id")
    if admin_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_ID,
                message_id=admin_msg_id,
                text=f"⌛ <b>[10-Min Timeout - Auto Refunded]</b>\nUser <code>{target_id}</code> request timed out and point was refunded.",
                parse_mode="HTML"
            )
        except Exception:
            pass

async def post_deal_followup_job(context: ContextTypes.DEFAULT_TYPE):
    """Triggered 15 mins (900s) after user receives discount deal link."""
    job = context.job
    chat_id = job.data["chat_id"]
    p_name = job.data["product_name"]
    discount = job.data["discount"]
    savings = job.data["savings"]
    ref_used = job.data["ref_used"]
    img_bytes = job.data.get("img_bytes")

    upsell_text = (
        f"🎉 <b>Happy with our service?</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Product:</b> {p_name}\n"
        f"💸 <b>Discount Applied:</b> {discount}\n"
        f"💰 <b>Total Money Saved:</b> {savings} !\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 <b>Referral Code Used:</b> <code>{ref_used}</code>\n\n"
        f"✨ <b>Earn Unlimited Free Discount Points:</b>\n"
        f"Shop se <b>8 Discount Points</b> pack lijiye aur apna khud ka unique Referral Code unlock kijiye! Friends ko invite karne par unhe 1 Free Point milega aur aapko har purchase par +1 Free Gift Point milega!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Shop Discount Points", callback_data="purchase_menu")],
        [InlineKeyboardButton("⚠️ Report a Problem", callback_data="report_problem")]
    ])

    try:
        if img_bytes:
            await context.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(img_bytes), caption=upsell_text, parse_mode="HTML", reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=chat_id, text=upsell_text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        print(f"Follow-up job error: {e}")


# ---------------- COMMAND HANDLERS ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    user = update.effective_user
    context.user_data["state"] = None
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    welcome_text = f"Hello <b>{full_name}</b> 👋🏻\nWelcome to @Rebrandx_bot"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Let's Start", callback_data="lets_start")]])
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=kb)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terminates active live chat session (Admin only)."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    target_id = context.bot_data.get("active_chat_user")
    if target_id:
        context.bot_data["active_chat_user"] = None
        active_live_chats.pop(target_id, None)
        try:
            await context.bot.send_message(chat_id=target_id, text="⏹ <b>Admin has ended the live chat session.</b>", parse_mode="HTML")
        except Exception: pass
        await update.message.reply_text(f"✅ Live chat with User <code>{target_id}</code> terminated.", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ No active live chat session.")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        user_records = context.bot_data.get("user_records", {})
        rec = user_records.get(target_id, {})
        await sync_user_to_db(context, target_id, rec.get("discountpoint", 0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), "Active", rec.get("admin_refer", "No"), rec.get("order_history", []))
        await update.message.reply_text(f"✅ User {target_id} unblocked.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /unblock <userid>")

async def go_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = [
        [InlineKeyboardButton("🔍 User Profile & Inspect", callback_data="adm_menu_inspect"), InlineKeyboardButton("➕ Gift Points", callback_data="adm_menu_addpoints")],
        [InlineKeyboardButton("💬 Live Chat with User", callback_data="adm_menu_msg_user"), InlineKeyboardButton("📢 Announcement", callback_data="adm_menu_announcement")],
        [InlineKeyboardButton("⏳ End Sale Countdown", callback_data="adm_menu_endsale"), InlineKeyboardButton("🎁 Special Offer", callback_data="adm_menu_spoffer")],
        [InlineKeyboardButton("🚫 Block User / All", callback_data="adm_menu_end"), InlineKeyboardButton("❌ Close Panel", callback_data="adm_menu_close")]
    ]
    await update.message.reply_text("👑 <b>Admin Master Control Panel</b>\nChoose an action below:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


# ---------------- TELEGRAM STARS PAYMENT HANDLERS ---------------- #
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    user_records = context.bot_data.get("user_records", {})
    rec = user_records.get(user_id, {})
    
    points = rec.get("discountpoint", 0)
    refer_from = str(rec.get("refer_from", "None"))
    refer_code = str(rec.get("refer_code", "None"))
    admin_refer = str(rec.get("admin_refer", "No"))
    order_history = rec.get("order_history", [])

    added = 0
    if payload == "buy_pack_1": added = 1
    elif payload == "buy_pack_2": added = 2
    elif payload == "buy_pack_4": added = 4
    elif payload == "buy_pack_8": 
        added = 8
        if refer_code == "None" or not refer_code:
            refer_code = generate_unique_referral_code(user_records)
        
    points += added
    await update.message.reply_text(f"🎉 <b>Payment Successful!</b>\nAapke account me <b>+{added} Discount Point(s)</b> add kar diye gaye hain.", parse_mode="HTML")
    
    if refer_code != "None" and refer_code:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"🎁 <b>Aapka Referral Code:</b> <code>{refer_code}</code>\n\n"
                "Ise apne dosto ke saath share karein! Jab wo ise enter karenge toh unhe 1 Free Point milega, aur jab wo koi pack purchase karenge toh aapko +1 Free Discount Point gift milega!"
            ),
            parse_mode="HTML"
        )
    
    if refer_from != "None" and admin_refer == "No":
        for u_uid, u_rec in user_records.items():
            if str(u_rec.get("refer_code", "")).upper() == refer_from.upper():
                ref_id = int(u_uid)
                r_pts = u_rec.get("discountpoint", 0) + 1
                await sync_user_to_db(context, ref_id, r_pts, u_rec.get("refer_code", "None"), u_rec.get("refer_from", "None"), u_rec.get("status", "Active"), u_rec.get("admin_refer", "No"), u_rec.get("order_history", []))
                try:
                    await context.bot.send_message(chat_id=ref_id, text="🎁 <b>Referral Bonus!</b>\nAapke referred friend ne first purchase ki hai! Aapko reward ke roop me <b>+1 Free Discount Point</b> mil gaya hai!", parse_mode="HTML")
                except Exception: pass
                break

    await sync_user_to_db(context, user_id, points, refer_code, refer_from, rec.get("status", "Active"), admin_refer, order_history)


# ---------------- CALLBACK QUERY HANDLER ---------------- #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    data = query.data
    user_records = context.bot_data.get("user_records", {})

    lock_key = f"{user.id}_{data}"
    if lock_key in click_locks:
        await query.answer("⏳ Processing...")
        return
        
    click_locks.add(lock_key)
    await query.answer()

    try:
        # -- ADMIN /GO WORKFLOWS --
        if data == "adm_menu_close":
            try: await query.message.delete()
            except: pass
            return

        elif data == "adm_back_main":
            admin_sessions.pop(ADMIN_ID, None)
            kb = [
                [InlineKeyboardButton("🔍 User Profile & Inspect", callback_data="adm_menu_inspect"), InlineKeyboardButton("➕ Gift Points", callback_data="adm_menu_addpoints")],
                [InlineKeyboardButton("💬 Live Chat with User", callback_data="adm_menu_msg_user"), InlineKeyboardButton("📢 Announcement", callback_data="adm_menu_announcement")],
                [InlineKeyboardButton("⏳ End Sale Countdown", callback_data="adm_menu_endsale"), InlineKeyboardButton("🎁 Special Offer", callback_data="adm_menu_spoffer")],
                [InlineKeyboardButton("🚫 Block User / All", callback_data="adm_menu_end"), InlineKeyboardButton("❌ Close Panel", callback_data="adm_menu_close")]
            ]
            await edit_message_or_caption(query, "👑 <b>Admin Master Control Panel</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            return

        elif data == "adm_menu_inspect":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_INSPECT_USER_ID"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "🔍 <b>Send User ID to inspect profile:</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_menu_addpoints":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_GIFT_USER_ID"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "➕ <b>Send User ID to gift discount points:</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_menu_msg_user":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_CHAT_USER_ID"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "💬 <b>Send User ID to start 2-Way Live Chat:</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_end_chat_session":
            target_id = context.bot_data.get("active_chat_user")
            if target_id:
                context.bot_data["active_chat_user"] = None
                active_live_chats.pop(target_id, None)
                try:
                    await context.bot.send_message(chat_id=target_id, text="⏹ <b>Admin has ended the live chat session.</b>", parse_mode="HTML")
                except Exception: pass
            await edit_message_or_caption(query, "✅ <b>Live chat session ended.</b>", parse_mode="HTML")

        elif data == "adm_menu_announcement":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_ANNOUNCEMENT"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "📢 <b>Write Announcement Message (Text, Photo or Video):</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_menu_endsale":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_SALE_DATE", "data": {}}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "⏳ <b>Send date & time (format: dd/mm/yy 1-12Am/Pm):</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_menu_spoffer":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_SPO_LINK", "data": {}}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "🎁 <b>Send Flipkart Link for Special Offer:</b>", reply_markup=kb, parse_mode="HTML")

        elif data == "adm_menu_end":
            kb = [
                [InlineKeyboardButton("🚫 Block User", callback_data="adm_menu_end_user"), InlineKeyboardButton("💥 Block ALL Users", callback_data="adm_menu_end_all")],
                [InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]
            ]
            await edit_message_or_caption(query, "Select blocking mode:", reply_markup=InlineKeyboardMarkup(kb))

        elif data == "adm_menu_end_user":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_BLOCK_USER_ID"}
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm_back_main")]])
            await edit_message_or_caption(query, "Send User ID to block:", reply_markup=kb)

        elif data == "adm_menu_end_all":
            kb = [
                [InlineKeyboardButton("⚠️ Confirm Block ALL Users", callback_data="adm_menu_end_all_confirm")],
                [InlineKeyboardButton("🔙 Cancel / Back", callback_data="adm_back_main")]
            ]
            await edit_message_or_caption(query, "Are you absolutely sure you want to block all users?", reply_markup=InlineKeyboardMarkup(kb))

        elif data == "adm_menu_end_all_confirm":
            for u_id, rec in list(user_records.items()):
                if int(u_id) != ADMIN_ID:
                    await sync_user_to_db(context, int(u_id), rec.get("discountpoint", 0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), "Blocked", rec.get("admin_refer", "No"), rec.get("order_history", []))
                    await asyncio.sleep(0.02)
            await edit_message_or_caption(query, "✅ All users have been blocked.")

        # -- ADMIN ACCEPT WORKFLOW (2 LINES WITH CONTEXT SUMMARY) --
        elif data.startswith("adm_accept_"):
            target_id = int(data.split("adm_accept_")[1])
            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            
            p_name = req_data.get("product_name", "Flipkart Product")
            p_price = req_data.get("product_price", 0)
            p_link = req_data.get("product_link", "https://flipkart.com")
            mob = req_data.get("mobile_num", "N/A")
            full_name = req_data.get("full_name", f"User {target_id}")

            admin_sessions[ADMIN_ID] = {"target_user_id": target_id, "step": "WAITING_ALL_DETAILS", "data": {}}
            
            prompt = (
                f"✅ <b>Accepting Request for User <code>{target_id}</code></b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Name:</b> {full_name}\n"
                f"📱 <b>Mobile:</b> +91 {mob}\n"
                f"📦 <b>Product:</b> {p_name}\n"
                f"🏷 <b>Original Price:</b> {format_inr(p_price)}\n"
                f"🔗 <b>Link:</b> {p_link}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>Send details in exactly 2 lines:</b>\n"
                f"Line 1: Final Price (e.g. 45000)\n"
                f"Line 2: HyperLink (Long affiliate link to shorten)\n\n"
                f"<i>Note: Discount will be auto-calculated against original price.</i>"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel / Back", callback_data=f"adm_rej_cancel_{target_id}")]])
            await edit_message_or_caption(query, prompt, reply_markup=kb, parse_mode="HTML")

        # -- ADMIN REJECT MENU --
        elif data.startswith("adm_reject_menu_"):
            target_id = int(data.split("adm_reject_menu_")[1])
            kb = [
                [InlineKeyboardButton("🔴 Out of Stock", callback_data=f"adm_rej_stock_{target_id}")],
                [InlineKeyboardButton("🟡 Discount Not Available (Refund)", callback_data=f"adm_rej_nodisc_{target_id}")],
                [InlineKeyboardButton("⚪ Invalid Link", callback_data=f"adm_rej_invalid_{target_id}")],
                [InlineKeyboardButton("🔙 Cancel", callback_data=f"adm_rej_cancel_{target_id}")]
            ]
            await edit_message_or_caption(query, f"Select Rejection Reason for User <code>{target_id}</code>:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data.startswith("adm_rej_cancel_"):
            target_id = int(data.split("adm_rej_cancel_")[1])
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"adm_accept_{target_id}"), InlineKeyboardButton("Reject", callback_data=f"adm_reject_menu_{target_id}")]])
            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            full_name = req_data.get("full_name", f"User {target_id}")
            p_name = req_data.get("product_name", "Flipkart Product")
            p_price = req_data.get("product_price", 0)
            p_link = req_data.get("product_link", "https://flipkart.com")
            mob = req_data.get("mobile_num", "")
            
            admin_message = (
                f"1. <b><code>{target_id}</code></b>\n"
                f"2. {full_name}\n"
                f"3. <b>Product:</b> {p_name}\n"
                f"4. <b>Original Price:</b> {format_inr(p_price)}\n"
                f"5. <b>Link:</b> {p_link}\n"
                f"6. <b>Mobile:</b> {mob}"
            )
            await edit_message_or_caption(query, admin_message, reply_markup=kb, parse_mode="HTML")

        elif data.startswith("adm_rej_stock_"):
            target_id = int(data.split("adm_rej_stock_")[1])
            context.bot_data.get("pending_requests", {}).pop(target_id, None)
            try:
                await context.bot.send_message(chat_id=target_id, text="Aapka provided product out of stock ho chuka hai aur 1 discount point expire ho gaya hai.")
            except Exception: pass
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code> (Out of Stock).", parse_mode="HTML")

        elif data.startswith("adm_rej_nodisc_"):
            target_id = int(data.split("adm_rej_nodisc_")[1])
            req_data = context.bot_data.get("pending_requests", {}).pop(target_id, None)
            p_name = req_data.get("product_name", "Flipkart Product") if req_data else "Product"
            p_link = req_data.get("product_link", "https://flipkart.com") if req_data else "https://flipkart.com"
            
            rec = user_records.get(target_id, {})
            ref_points = rec.get("discountpoint", 0) + 1
            await sync_user_to_db(context, target_id, ref_points, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), rec.get("order_history", []))

            user_msg = f'Discount not available on <a href="{p_link}">{p_name}</a>. Humne aapka 1 discount point wapas refund kar diya hai.'
            try:
                await context.bot.send_message(chat_id=target_id, text=user_msg, parse_mode="HTML", disable_web_page_preview=True)
            except Exception: pass
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code> (No Discount)\n✅ <b>1 Point Refunded</b>", parse_mode="HTML")

        elif data.startswith("adm_rej_invalid_"):
            target_id = int(data.split("adm_rej_invalid_")[1])
            context.bot_data.get("pending_requests", {}).pop(target_id, None)
            try:
                await context.bot.send_message(chat_id=target_id, text="Aapka provided link server dwara accept nahi ho paya. Kripya valid product link bhejein.")
            except Exception: pass
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code> (Invalid Link).", parse_mode="HTML")

        # -- ADMIN VERIFICATION & LEJUMO SHORTENING --
        elif data == "verify_no":
            if ADMIN_ID in admin_sessions:
                admin_sessions[ADMIN_ID]["step"] = "WAITING_ALL_DETAILS"
                await edit_message_or_caption(query, "Send details in exactly 2 lines:\nLine 1: Final Price\nLine 2: HyperLink")

        elif data == "verify_yes":
            if ADMIN_ID not in admin_sessions: return
            session = admin_sessions[ADMIN_ID]
            target_id = session.get("target_user_id")
            data_dict = session.get("data", {})
            
            await edit_message_or_caption(query, "⏳ <b>Creating Lejumo Short Link... Please wait.</b>", parse_mode="HTML")

            req_data = context.bot_data.get("pending_requests", {}).pop(target_id, {})
            user_orig_link = req_data.get("product_link", "https://flipkart.com")
            prod_name = req_data.get("product_name", "Flipkart Product")
            prod_orig_price = req_data.get("product_price", 0)
            prod_img_bytes = req_data.get("product_image_bytes")

            original_hyperlink = data_dict["hyper_link"]
            success, short_or_err = await asyncio.to_thread(create_lejumo_short_link, original_hyperlink)
            
            rec = user_records.get(target_id, {})

            # Auto-refund if shortening fails
            if not success:
                refunded_pts = rec.get("discountpoint", 0) + 1
                await sync_user_to_db(context, target_id, refunded_pts, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), rec.get("order_history", []))
                try:
                    await context.bot.send_message(chat_id=target_id, text="⚠️ <b>Link Generation Error!</b>\nServer issue ki wajah se link create nahi ho paya. Humne aapka <b>1 Discount Point refund</b> kar diya hai.", parse_mode="HTML")
                except Exception: pass
                await edit_message_or_caption(query, f"❌ <b>Lejumo API Failed:</b> {short_or_err}\n\n✅ <b>User ko 1 Point Refund kar diya gaya.</b>", parse_mode="HTML")
                del admin_sessions[ADMIN_ID]
                return

            final_price_fmt = format_inr(data_dict["final_price"])
            
            # Record in user order history
            history_list = rec.get("order_history", [])
            history_list.append({
                "date": datetime.now().strftime("%d/%m/%Y %I:%M%p"),
                "product": prod_name,
                "orig_price": prod_orig_price,
                "final_price": data_dict["final_price"],
                "discount": data_dict["discount"],
                "status": "Completed"
            })
            await sync_user_to_db(context, target_id, rec.get("discountpoint", 0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), history_list)

            context.bot_data.setdefault("ready_links", {})[target_id] = {
                "hyper_link": short_or_err,
                "discount": data_dict["discount"],
                "product_name": prod_name,
                "orig_price": prod_orig_price,
                "product_image_bytes": prod_img_bytes,
                "final_price": final_price_fmt,
                "orig_link": user_orig_link
            }
            context.bot_data.setdefault("user_flow_states", {})[target_id] = "READY"
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="user_continue_ready"), InlineKeyboardButton("Tutorial", callback_data="tutorial_ready_chk")]
            ])
            msg_text = "🎉 <b>Congratulations!</b>\nAapka link discount ke liye qualify ho chuka hai."
            
            try:
                await send_dynamic_media(context, target_id, "Ready", msg_text, kb)
                await edit_message_or_caption(
                    query,
                    f"✅ <b>Setup Completed & Sent!</b>\n\n"
                    f"🔗 <b>Short Link:</b> <code>{short_or_err}</code>\n"
                    f"📦 <b>Product:</b> {prod_name}\n"
                    f"💸 <b>Discount:</b> {data_dict['discount']}\n"
                    f"💰 <b>Deal Price:</b> {final_price_fmt}\n\n"
                    f"Message successfully delivered to User <code>{target_id}</code>.",
                    parse_mode="HTML"
                )
            except Exception as e:
                # Auto-refund if message delivery fails
                refunded_pts = rec.get("discountpoint", 0) + 1
                await sync_user_to_db(context, target_id, refunded_pts, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), history_list)
                await edit_message_or_caption(query, f"❌ Failed to deliver to User: {e}\n✅ <b>1 Point Refunded.</b>", parse_mode="HTML")
                
            del admin_sessions[ADMIN_ID]

        # -- USER NAVIGATION & MENUS --
        elif data == "lets_start":
            text = "Hi! Mai Rebrand Bot hoon. Aap video tutorial kis language me dekhna chahte hain?"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Hindi", callback_data="lang_hi"), InlineKeyboardButton("English", callback_data="lang_en")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

        elif data in ["lang_hi", "lang_en"]:
            context.user_data['lang'] = data
            tag = "HindiTutorial" if data == "lang_hi" else "EnglishTutorial"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Lets Get Discount", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            caption = "⚠️ <b>Important:</b> Pehle short video tutorial dekh lein, phir aage continue karein:"
            await send_dynamic_media(context, chat_id, tag, caption=caption, reply_markup=kb)

        elif data == "dashboard":
            rec = user_records.get(user.id, {})
            points_left = rec.get("discountpoint", 0)
            buttons = [
                [InlineKeyboardButton("⚠️ Report a Problem", callback_data="report_problem"), InlineKeyboardButton("📜 Terms", callback_data="terms")],
                [InlineKeyboardButton("ℹ️ About us", callback_data="about_us"), InlineKeyboardButton("🛒 Shop", callback_data="purchase_menu")],
                [InlineKeyboardButton("👤 My Profile", callback_data="user_profile")]
            ]
            if points_left > 0:
                buttons.append([InlineKeyboardButton(f"🚀 Start x{points_left}", callback_data="direct_start")])
            else:
                buttons.append([InlineKeyboardButton(f"🚀 Start x0", callback_data="no_trial_start")])

            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="🏠 <b>Welcome to Rebrand Dashboard!</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "user_profile":
            rec = user_records.get(user.id, {})
            pts = rec.get("discountpoint", 0)
            r_code = rec.get("refer_code", "None")
            r_from = rec.get("refer_from", "None")
            history = rec.get("order_history", [])
            
            my_ref_display = f"<code>{r_code}</code>" if r_code != "None" else "<i>Buy 8-Pack to Unlock</i>"
            ref_used_display = f"<code>{r_from}</code>" if r_from != "None" else "None"
            
            history_text = ""
            if history:
                for h in history[-3:]:
                    history_text += f"\n• <b>{h.get('product', 'Item')}</b>: {h.get('discount', '')} (Deal: ₹{h.get('final_price', 0):,})"
            else:
                history_text = "\n<i>Koi previous order nahi mila.</i>"

            profile_card = (
                f"👤 <b>USER PROFILE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏷 <b>Name:</b> {user.first_name} {user.last_name or ''}\n"
                f"🆔 <b>User ID:</b> <code>{user.id}</code>\n"
                f"🎟 <b>Discount Points:</b> <b>{pts} Points</b>\n"
                f"🎁 <b>Referral Code Used:</b> {ref_used_display}\n"
                f"🔗 <b>Your Referral Code:</b> {my_ref_display}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Recent Orders History:</b>{history_text}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text=profile_card, parse_mode="HTML", reply_markup=kb)

        elif data == "no_trial_start":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Enter Referral Code", callback_data="enter_referral")],
                [InlineKeyboardButton("🛒 Shop Points", callback_data="purchase_menu")],
                [InlineKeyboardButton("🔙 Back", callback_data="dashboard")]
            ])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Aapke paas 0 Points hain. Referral code enter karein ya Shop se Discount Points purchase karein.", reply_markup=kb)

        elif data == "about_us":
            text = (
                "<b>How Rebrand Works:</b>\n\n"
                "Jab Flipkart bade sales event (Big Billion Days, GOAT Sale, Diwali Sale) host karta hai, tab heavy traffic ki wajah se bohot saare valid price drops aur checkout tokens drop ho jate hain.\n\n"
                "Rebrand in unhandled session tokens ko capture aur validate karta hai taaki aap sale khatam hone ke baad bhi heavy discounts pa sakein."
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await send_dynamic_media(context, chat_id, "Logo", text, kb)

        elif data == "terms":
            text = (
                "<b>Terms & Refund Policy:</b>\n\n"
                "1. Users ko apna wahi active mobile number dena anivarya hai jo unke Flipkart account se linked hai.\n"
                "2. Order seedha aapke diye gaye number wale account par place hoga.\n"
                "3. Galat ya kisi aur ka number enter karne par hone wale nuksan ke liye Rebrand zimmedar nahi hoga.\n"
                "4. Agar valid mobile number ke bawajood discount apply nahi hota ya link fail hota hai, toh aapka point 100% refund kiya jayega."
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb)

        elif data == "report_problem":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="report_continue")],
                [InlineKeyboardButton("🔙 Back", callback_data="dashboard")]
            ])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="⚠️ <b>Notice:</b> Aap week me 1 report submit kar sakte hain.", parse_mode="HTML", reply_markup=kb)

        elif data == "report_continue":
            last_rep = user_records.get(user.id, {}).get("last_report", 0.0)
            if time.time() - last_rep < 604800:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]])
                try: await query.message.delete()
                except: pass
                await context.bot.send_message(chat_id=chat_id, text="❌ Aap is week pehle hi report submit kar chuke hain. Kripya baad me try karein.", reply_markup=kb)
                return
                
            context.user_data["state"] = "WAITING_VOICE_REPORT"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Apni problem explain karte hue ek 30-Second ka Voice Note send karein:", reply_markup=kb)

        elif data == "purchase_menu":
            buttons = [
                [InlineKeyboardButton("1 Discount Point (500 ⭐️)", callback_data="buy_pack_1")],
                [InlineKeyboardButton("2 Discount Points (999 ⭐️)", callback_data="buy_pack_2")],
                [InlineKeyboardButton("4 Discount Points (1400 ⭐️)", callback_data="buy_pack_4")],
                [InlineKeyboardButton("8 Discount Points (3000 ⭐️)", callback_data="buy_pack_8")],
                [InlineKeyboardButton("🎁 Enter Referral Code", callback_data="enter_referral")],
                [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="dashboard")]
            ]
            text = (
                "🛒 <b>Discount Points Store</b>\n\n"
                "Telegram Stars ka use karke Discount Points khareedein!\n\n"
                "💡 <b>Referral Program:</b>\n"
                "8 Points pack purchase karne par aapka personal Referral Code unlock ho jayega!"
            )
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "enter_referral":
            context.user_data["state"] = "WAITING_REFERRAL_CODE"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="purchase_menu")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Apna Referral Code enter karein:", reply_markup=kb)

        # --- ADMIN DIRECT BYPASS & STAR PAYMENTS ---
        elif data.startswith("buy_pack_"):
            try: await query.message.delete()
            except: pass

            if user.id == ADMIN_ID:
                added = 1 if data == "buy_pack_1" else 2 if data == "buy_pack_2" else 4 if data == "buy_pack_4" else 8
                current_rec = user_records.get(ADMIN_ID, {})
                new_points = current_rec.get("discountpoint", 0) + added
                ref_code = str(current_rec.get("refer_code", "None"))

                if data == "buy_pack_8" and (ref_code == "None" or not ref_code):
                    ref_code = generate_unique_referral_code(user_records)
                
                await sync_user_to_db(context, ADMIN_ID, new_points, ref_code, current_rec.get("refer_from", "None"), "Active", current_rec.get("admin_refer", "No"), current_rec.get("order_history", []))
                
                admin_msg = f"👑 <b>Admin Bypass:</b> +{added} Points added. Total: <b>{new_points}</b> Points."
                if ref_code != "None" and ref_code:
                    admin_msg += f"\n🎁 <b>Your Referral Code:</b> <code>{ref_code}</code>"
                await context.bot.send_message(chat_id=chat_id, text=admin_msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Dashboard", callback_data="dashboard")]]))
                return

            title, description, payload, price_amount = "", "", "", 0
            if data == "buy_pack_1": title, description, payload, price_amount = "1 Discount Point", "Get 1 Free Discount Point", "buy_pack_1", 500
            elif data == "buy_pack_2": title, description, payload, price_amount = "2 Discount Points", "Get 2 Free Discount Points", "buy_pack_2", 999
            elif data == "buy_pack_4": title, description, payload, price_amount = "4 Discount Points", "Get 4 Free Discount Points", "buy_pack_4", 1400
            elif data == "buy_pack_8": title, description, payload, price_amount = "8 Discount Points", "Get 8 Free Discount Points + Unlocks Referral Code", "buy_pack_8", 3000
            
            prices = [LabeledPrice(title, price_amount)]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Pay {price_amount} ⭐️", pay=True)],
                [InlineKeyboardButton("🔙 Cancel", callback_data="purchase_menu")]
            ])
            await context.bot.send_invoice(chat_id=chat_id, title=title, description=description, payload=payload, provider_token="", currency="XTR", prices=prices, reply_markup=kb)

        elif data == "direct_start":
            context.bot_data.setdefault("user_flow_states", {})[user.id] = "NONE"
            context.user_data["state"] = "WAITING_FLIPKART_LINK"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]])
            text = "Apna Product Link send karein. Product Electronic hona chahiye aur price kam se kam ₹50,000 honi chahiye."
            try: await query.message.delete()
            except: pass
            await send_dynamic_media(context, chat_id, "ProductLink", text, kb)

        elif data == "edit_details":
            context.user_data["state"] = "WAITING_FLIPKART_LINK"
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Apna Product Link dobara send karein:")

        elif data == "continue_submit":
            rec = user_records.get(user.id, {})
            points_left = rec.get("discountpoint", 0)
            new_points = max(0, points_left - 1)
            
            await sync_user_to_db(context, user.id, new_points, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), rec.get("order_history", []))

            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="🔔 <b>Bot notification on rakhein.</b> Hum agle kuch minutes me aapko best discount provide karenge.")

            full_name = f"{user.first_name} {user.last_name or ''}".strip()
            p_name = context.user_data.get('product_name', 'Flipkart Product')
            p_price = context.user_data.get('product_price', 0)
            p_link = context.user_data.get('product_link', 'https://flipkart.com')
            mob = context.user_data.get('mobile_num', '')
            img_bytes = context.user_data.get('product_image_bytes')

            admin_message = (
                f"1. <b><code>{user.id}</code></b>\n"
                f"2. {full_name}\n"
                f"3. <b>Product:</b> {p_name}\n"
                f"4. <b>Original Price:</b> {format_inr(p_price)}\n"
                f"5. <b>Link:</b> {p_link}\n"
                f"6. <b>Mobile:</b> {mob}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"),
                 InlineKeyboardButton("Reject", callback_data=f"adm_reject_menu_{user.id}")]
            ])
            
            sent_admin_msg = None
            if img_bytes:
                try:
                    sent_admin_msg = await context.bot.send_photo(chat_id=ADMIN_ID, photo=io.BytesIO(img_bytes), caption=admin_message, parse_mode="HTML", reply_markup=keyboard)
                except Exception:
                    sent_admin_msg = await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)
            else:
                sent_admin_msg = await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

            context.bot_data.setdefault("pending_requests", {})[user.id] = {
                "full_name": full_name,
                "product_name": p_name,
                "product_price": p_price,
                "product_link": p_link,
                "mobile_num": mob,
                "product_image_bytes": img_bytes,
                "admin_msg_id": sent_admin_msg.message_id if sent_admin_msg else None
            }

            # 10-Minute Admin Auto-Timeout Timer (Refunds user if admin is unresponsive)
            context.job_queue.run_once(
                admin_timeout_refund_job,
                600,
                data={"target_id": user.id},
                name=f"timeout_user_{user.id}"
            )

        # -- POST-APPROVAL USER WORKFLOW --
        elif data == "resend_qualified_msg":
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="user_continue_ready"), InlineKeyboardButton("Tutorial", callback_data="tutorial_ready_chk")]
            ])
            await send_dynamic_media(context, chat_id, "Ready", "🎉 <b>Congratulations!</b>\nAapka link discount ke liye qualify ho chuka hai.", kb)
            
        elif data == "tutorial_ready_chk":
            lang = context.user_data.get('lang', 'lang_en')
            tag = "HindiTutorial" if lang == "lang_hi" else "EnglishTutorial"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="resend_qualified_msg")]])
            try: await query.message.delete()
            except: pass
            caption = "⚠️ <b>Important:</b> Pehle short video tutorial dekh lein:"
            await send_dynamic_media(context, chat_id, tag, caption=caption, reply_markup=kb)

        elif data == "user_continue_ready":
            try: await query.message.delete()
            except: pass
            
            d_data = context.bot_data.get("ready_links", {}).get(user.id, {})
            if not d_data:
                await context.bot.send_message(chat_id=chat_id, text="❌ Data fetch error. Support se contact karein.")
                return

            orig_link = d_data.get('orig_link', 'https://flipkart.com')
            orig_p_val = d_data.get('orig_price', 0)
            orig_p_str = format_inr(orig_p_val) if orig_p_val > 0 else "Market MRP"

            text = (
                f"🎉 <b>CONGRATULATIONS! DISCOUNT UNLOCKED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Product:</b> <a href='{orig_link}'>{d_data.get('product_name')}</a>\n\n"
                f"📊 <b>PRICE BREAKDOWN:</b>\n"
                f"├ 🏷 <b>Original Price:</b> <s>{orig_p_str}</s>\n"
                f"├ 💸 <b>Discount Applied:</b> <b>{d_data.get('discount')}</b>\n"
                f"└ 💰 <b>Deal Price:</b> <b>{d_data.get('final_price')}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <b>Instant Checkout Token Active</b>\n"
                f"⏳ <b>Link Expires in:</b> <b>10:00 Minutes</b>\n\n"
                f"⚠️ <i>Niche diye gaye button par click karke directly discount ke saath order place karein.</i>"
            )
            
            url = d_data.get('hyper_link', 'https://flipkart.com')
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔴 Buy Now 🔴", url=url)]])
            
            image_bytes = d_data.get('product_image_bytes')
            sent_msg = None
            is_media = False

            if image_bytes:
                try:
                    sent_msg = await context.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(image_bytes), caption=text, parse_mode="HTML", reply_markup=kb)
                    is_media = True
                except Exception:
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            else:
                sent_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            
            # Schedule 10-Min Deal Expiry Job
            if sent_msg:
                context.job_queue.run_once(
                    expire_deal_link_job,
                    600,
                    data={
                        "chat_id": chat_id,
                        "msg_id": sent_msg.message_id,
                        "product_name": d_data.get('product_name', 'Flipkart Product'),
                        "orig_link": orig_link,
                        "final_price": d_data.get('final_price', ''),
                        "is_media": is_media
                    },
                    name=f"deal_expire_{user.id}_{sent_msg.message_id}"
                )

            # Schedule 15-Min Post-Deal Follow-up & Upsell Job
            rec = user_records.get(user.id, {})
            savings_val = "Special Savings"
            try:
                final_val = int(re.sub(r'\D', '', str(d_data.get('final_price', '0'))))
                if orig_p_val > final_val:
                    savings_val = format_inr(orig_p_val - final_val)
            except Exception: pass

            context.job_queue.run_once(
                post_deal_followup_job,
                900,
                data={
                    "chat_id": chat_id,
                    "product_name": d_data.get('product_name', 'Flipkart Product'),
                    "discount": d_data.get('discount', 'Huge Discount'),
                    "savings": savings_val,
                    "ref_used": rec.get("refer_from", "None"),
                    "img_bytes": image_bytes
                },
                name=f"followup_{user.id}"
            )

    finally:
        await asyncio.sleep(0.5)
        click_locks.discard(lock_key)


# ---------------- TEXT & MEDIA MESSAGE HANDLER ---------------- #
async def media_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    user_id = update.effective_user.id
    user_records = context.bot_data.get("user_records", {})
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else update.message.caption.strip() if update.message.caption else ""

    # -- 2-WAY LIVE CHAT MODE ROUTING --
    active_chat_target = context.bot_data.get("active_chat_user")
    
    if user_id == ADMIN_ID and active_chat_target:
        try:
            await update.message.copy(chat_id=active_chat_target)
            await update.message.reply_text(f"📤 <i>Sent to User {active_chat_target}</i>", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to deliver: {e}")
        return

    if active_chat_target == user_id:
        try:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"💬 <b>From User <code>{user_id}</code>:</b>", parse_mode="HTML")
            await update.message.copy(chat_id=ADMIN_ID)
        except Exception: pass
        return

    # -- REFERRAL PROMO CODES --
    if state == "WAITING_REFERRAL_CODE":
        if text.startswith("/"):
            context.user_data["state"] = None
            return 

        code = text.strip().upper()
        current_rec = user_records.get(user_id, {})
        start_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Start Now", callback_data="direct_start")], [InlineKeyboardButton("🏠 Dashboard", callback_data="dashboard")]])

        if code == "VASH9K019S":
            if str(current_rec.get("refer_from", "None")) != "None":
                context.user_data["state"] = None
                await update.message.reply_text("❌ Aap pehle hi ek Referral Code use kar chuke hain!")
                return
                
            new_pts = current_rec.get("discountpoint", 0) + 1
            await sync_user_to_db(context, user_id, new_pts, current_rec.get("refer_code", "None"), "VASH9K019S", current_rec.get("status", "Active"), "Yes", current_rec.get("order_history", []))
            context.user_data["state"] = None
            await update.message.reply_text("✅ <b>Secret Promo Code Accepted!</b>\nAapko <b>+1 Free Discount Point</b> mil gaya hai.", parse_mode="HTML", reply_markup=start_kb)
            return

        referrer_uid = None
        for uid, rec in user_records.items():
            if str(rec.get("refer_code", "")).strip().upper() == code:
                referrer_uid = uid
                break
                
        if not referrer_uid:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="purchase_menu")]])
            await update.message.reply_text("❌ Invalid Referral Code. Kripya check karke dobara enter karein.", reply_markup=kb)
            return
            
        if int(referrer_uid) == user_id:
            context.user_data["state"] = None
            await update.message.reply_text("❌ Aap apna khud ka referral code use nahi kar sakte!")
            return
            
        if str(current_rec.get("refer_from", "None")) != "None":
            context.user_data["state"] = None
            await update.message.reply_text("❌ Aap pehle hi ek Referral Code use kar chuke hain!")
            return
            
        new_pts = current_rec.get("discountpoint", 0) + 1
        await sync_user_to_db(context, user_id, new_pts, current_rec.get("refer_code", "None"), code, current_rec.get("status", "Active"), "No", current_rec.get("order_history", []))
        context.user_data["state"] = None
        await update.message.reply_text("✅ <b>Referral Code Accepted!</b>\nAapko <b>+1 Free Discount Point</b> mil gaya hai.", parse_mode="HTML", reply_markup=start_kb)
        return

    # -- VOICE REPORT HANDLER --
    if state == "WAITING_VOICE_REPORT":
        if not update.message.voice:
            await update.message.reply_text("❌ Kripya ek Voice Note send karein.")
            return
        if update.message.voice.duration > 35:
            await update.message.reply_text("❌ Voice note 30 seconds se kam ka hona chahiye.")
            return
            
        rec = user_records.get(user_id, {})
        rec["last_report"] = time.time()
        
        # Log to Google Sheets
        payload = {
            "action": "add_report",
            "userid": str(user_id),
            "full_name": f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip(),
            "status": "Open",
            "notes": f"Voice Note ({update.message.voice.duration}s)"
        }
        asyncio.create_task(asyncio.to_thread(gsheet_request, payload))

        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ <b>New Issue Report from <code>{user_id}</code></b>", parse_mode="HTML")
        await update.message.copy(chat_id=ADMIN_ID)
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Dashboard", callback_data="dashboard")]])
        await update.message.reply_text("✅ Aapki report submit ho gayi hai. 24 hours ke andar team aapse contact karegi.", reply_markup=kb)
        context.user_data["state"] = None
        return

    # --- ADMIN WORKFLOW CONTROLLER ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_id = session.get("target_user_id")

        if step == "WAITING_ALL_DETAILS":
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if len(lines) < 2:
                await update.message.reply_text("❌ Please provide exactly 2 lines:\nLine 1: Final Price (e.g. 45000)\nLine 2: HyperLink\n\nTry again:")
                return
            
            final_price_raw, hyperlink = lines[0], lines[1]
            final_price_num = int(re.sub(r'\D', '', final_price_raw)) if re.sub(r'\D', '', final_price_raw) else 0

            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            auto_prod_name = req_data.get("product_name", "Flipkart Product")
            orig_p = req_data.get("product_price", 0)

            if orig_p > 0 and final_price_num > 0 and orig_p > final_price_num:
                diff = orig_p - final_price_num
                pct = round((diff / orig_p) * 100)
                discount_calc = f"{format_inr(diff)} ({pct}% OFF)"
            else:
                discount_calc = "Special Discount"

            session["data"] = {"discount": discount_calc, "final_price": final_price_num, "hyper_link": hyperlink}
            
            verify_text = (
                f"Please verify the details for User <code>{target_id}</code>:\n\n"
                f"📦 <b>Product:</b> {auto_prod_name}\n"
                f"🏷 <b>Original Price:</b> {format_inr(orig_p)}\n"
                f"💸 <b>Auto-Discount:</b> {discount_calc}\n"
                f"💰 <b>Final Price:</b> {format_inr(final_price_num)}\n"
                f"🔗 <b>Target HyperLink:</b> {hyperlink}\n\n"
                f"Are these correct? Link will be shortened via Lejumo."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, Send to User", callback_data="verify_yes"),
                 InlineKeyboardButton("No, Let me rewrite", callback_data="verify_no")]
            ])
            session["step"] = "WAITING_VERIFICATION"
            await update.message.reply_text(verify_text, reply_markup=kb, disable_web_page_preview=True, parse_mode="HTML")
            return

        elif step == "WAITING_INSPECT_USER_ID":
            try:
                t_id = int(text)
                rec = user_records.get(t_id, {})
                if rec:
                    history = rec.get("order_history", [])
                    h_text = "".join([f"\n• {h.get('product')} - {h.get('discount')} (₹{h.get('final_price')})" for h in history[-3:]]) or "\nNone"
                    card = (
                        f"🔍 <b>USER INSPECTOR: <code>{t_id}</code></b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎟 <b>Discount Points:</b> {rec.get('discountpoint', 0)}\n"
                        f"🎁 <b>Referral Used:</b> {rec.get('refer_from', 'None')}\n"
                        f"🔗 <b>User Refer Code:</b> {rec.get('refer_code', 'None')}\n"
                        f"📊 <b>Account Status:</b> {rec.get('status', 'Active')}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📦 <b>Recent Orders:</b>{h_text}"
                    )
                    kb = [
                        [InlineKeyboardButton("💬 Chat with User", callback_data=f"adm_start_chat_{t_id}")],
                        [InlineKeyboardButton("🔙 Back to Master Panel", callback_data="adm_back_main")]
                    ]
                    await update.message.reply_text(card, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
                else:
                    await update.message.reply_text(f"❌ User <code>{t_id}</code> not found in database.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Must be numeric.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_GIFT_USER_ID":
            try:
                session["gift_target"] = int(text)
                session["step"] = "WAITING_GIFT_AMOUNT"
                await update.message.reply_text(f"How many Discount Points to gift User {text}?")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID.")
            return

        elif step == "WAITING_GIFT_AMOUNT":
            try:
                amt = int(text)
                t_id = session.get("gift_target")
                rec = user_records.get(t_id, {})
                new_pts = rec.get("discountpoint", 0) + amt
                await sync_user_to_db(context, t_id, new_pts, rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("status", "Active"), rec.get("admin_refer", "No"), rec.get("order_history", []))
                
                try:
                    await context.bot.send_message(chat_id=t_id, text=f"🎁 <b>Surprise Gift!</b>\nAdmin has gifted you <b>+{amt} Discount Points</b>!", parse_mode="HTML")
                except Exception: pass
                
                await update.message.reply_text(f"✅ Gifted +{amt} Points to User <code>{t_id}</code>. New Balance: {new_pts}", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ Points must be a number.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_CHAT_USER_ID":
            try:
                t_id = int(text)
                context.bot_data["active_chat_user"] = t_id
                active_live_chats[t_id] = True
                
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏹ End Live Chat", callback_data="adm_end_chat_session")]])
                await update.message.reply_text(
                    f"🟢 <b>2-Way Live Chat Started with User <code>{t_id}</code></b>\n\n"
                    f"Aap jo bhi message bhejenge seedha user ko deliver hoga, aur user ka reply yahan aayega.\n\n"
                    f"Chat terminate karne ke liye <b>/stop</b> command bhejein ya niche button dabayein.",
                    parse_mode="HTML",
                    reply_markup=kb
                )
                try:
                    await context.bot.send_message(chat_id=t_id, text="💬 <b>Our Support Admin has joined the chat. You can reply directly here!</b>", parse_mode="HTML")
                except Exception: pass
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_ANNOUNCEMENT":
            sent = 0
            for u_id, rec in user_records.items():
                if int(u_id) == ADMIN_ID or str(rec.get("status", "Active")).lower() == "blocked": continue
                try:
                    await update.message.copy(chat_id=int(u_id))
                    sent += 1
                    await asyncio.sleep(0.04)
                except: pass
            await update.message.reply_text(f"✅ Announcement sent to {sent} active users.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_BLOCK_USER_ID":
            try:
                t_id = int(text)
                rec = user_records.get(t_id, {})
                await sync_user_to_db(context, t_id, rec.get("discountpoint", 0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), "Blocked", rec.get("admin_refer", "No"), rec.get("order_history", []))
                await update.message.reply_text(f"✅ User <code>{t_id}</code> has been blocked.", parse_mode="HTML")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID.")
            del admin_sessions[user_id]
            return

    # --- REGULAR USER WORKFLOWS ---
    if state == "WAITING_FLIPKART_LINK" and text:
        clean_link = extract_flipkart_link(text)
        if clean_link:
            status_msg = await update.message.reply_text("🔍 Flipkart se product details fetch ki ja rahi hain...")
            p_title, p_price, p_image_bytes = await asyncio.to_thread(fetch_flipkart_metadata, clean_link)
            
            try: await status_msg.delete()
            except Exception: pass

            if p_price > 0 and p_price < 50000:
                warn_text = (
                    f"❌ <b>Product Eligible Nahi Hai!</b>\n\n"
                    f"📦 <b>Product:</b> {p_title}\n"
                    f"💰 <b>Price:</b> {format_inr(p_price)}\n\n"
                    f"⚠️ <b>Requirement:</b> Product Electronic hona chahiye aur price kam se kam <b>₹50,000</b> honi chahiye."
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Go to Dashboard", callback_data="dashboard")]])
                await update.message.reply_text(warn_text, parse_mode="HTML", reply_markup=kb)
                return

            context.user_data["product_link"] = clean_link
            context.user_data["product_name"] = p_title
            context.user_data["product_price"] = p_price
            context.user_data["product_image_bytes"] = p_image_bytes
            context.user_data["state"] = "WAITING_MOBILE_NUMBER"

            msg_text = (
                f"📦 <b>Detected Product:</b> {p_title}\n"
                f"💰 <b>Price:</b> {format_inr(p_price)}\n\n"
                "Apna Flipkart Account Mobile Number (+91 XXXXXXXXXX) send karein.\n\n"
                "⚠️ Humara secure server hai, isliye OTP ya Password ki zaroorat nahi hoti.\n"
                "⚠️ Apna OTP ya Login details kisi ke saath share na karein."
            )
            await send_dynamic_media(context, update.message.chat_id, "AccountNumber", msg_text)
        else:
            await update.message.reply_text("❌ Invalid Link. Kripya ek valid Flipkart link bhejein.")

    elif state == "WAITING_MOBILE_NUMBER" and text:
        number_only = re.sub(r'\D', '', text)
        if len(number_only) >= 10:
            mobile_num = number_only[-10:]
            context.user_data["mobile_num"] = mobile_num
            context.user_data["state"] = None
            
            trials = user_records.get(user_id, {}).get("discountpoint", 0)
            full_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()
            p_price = context.user_data.get('product_price', 0)

            conf_text = (
                f"{full_name}, aapke paas <b>{trials} Discount Point(s)</b> bache hain.\n"
                "Aage badhne par 1 point deduct hoga aur discounted deal create hogi:\n\n"
                f"📦 <b>Product:</b> {context.user_data.get('product_name')}\n"
                f"💰 <b>Price:</b> {format_inr(p_price)}\n"
                f"🔗 <b>Link:</b> {context.user_data['product_link']}\n"
                f"📱 <b>Mobile:</b> +91 {mobile_num}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Edit Details", callback_data="edit_details"), InlineKeyboardButton("Continue", callback_data="continue_submit")]
            ])
            await update.message.reply_text(conf_text, reply_markup=kb, disable_web_page_preview=True, parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Kripya valid 10-digit mobile number enter karein.")


# ---------------- APPLICATION STARTUP HOOK ---------------- #
async def post_init_setup(application: Application):
    """Hydrates all users and settings from Google Sheets and Channel Media."""
    print("⏳ Syncing in-memory database with Google Sheets Web App...")
    users = await asyncio.to_thread(gsheet_get_all_users)
    if users:
        application.bot_data["user_records"] = users
        print(f"✅ Successfully hydrated {len(users)} users from Google Sheets!")
    else:
        print("ℹ️ Google Sheet is clean or starting fresh.")


# ---------------- MAIN APPLICATION ENTRY POINT ---------------- #
def main():
    if not BOT_TOKEN:
        print("CRITICAL: TELEGRAM_TOKEN environment variable is missing!")
        return

    Thread(target=run_flask, daemon=True).start()

    persistence = PicklePersistence(filepath="bot_state.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).post_init(post_init_setup).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("Go", go_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    
    # Callback Handlers
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Telegram Stars Payments
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Messages & Channel Attachments
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, media_and_text_handler))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_db_sync_handler))

    print("Bot is successfully running 24/7 with Google Sheets, Live Chat, Auto-Refund & Lejumo Engine...")
    app.run_polling()

if __name__ == "__main__":
    main()
