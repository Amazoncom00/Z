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

# Configuration
ADMIN_ID = 8844584255
DB_CHANNEL_ID = -1003936910985
LOGO_URL_FALLBACK = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Global memory for admin workflows and debounce locks
admin_sessions = {}
click_locks = set()

# --- Dummy Flask Web Server to keep Cloud Hosting happy ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Rebrand Bot is Running 24/7 Successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ---------------- HELPERS, SCRAPERS & SHORTENER ---------------- #
async def edit_message_or_caption(query, text, reply_markup=None, parse_mode="HTML"):
    """Safely edits text message or photo/media caption without Telegram API errors."""
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
    """Formats 79812 into ₹79,812 perfectly."""
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
    """Extracts only the URL if it contains flipkart or fkrt, ignoring extra text."""
    urls = re.findall(r'(https?://[^\s]+)', text)
    for url in urls:
        if 'flipkart' in url.lower() or 'fkrt' in url.lower():
            return url
    return ""

def fetch_flipkart_metadata(url: str):
    """
    Follows redirects, extracts actual Product Title, exact numerical Price,
    and downloads product image bytes directly.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    final_url = url
    html = ""
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            final_url = response.geturl()
            html = response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Flipkart Page Request Error: {e}")

    # 1. Title Extraction
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
        extracted_title = re.sub(r'-\s*Flipkart.*$', '', extracted_title, flags=re.IGNORECASE)
        extracted_title = extracted_title.strip()

    if not extracted_title or "Flipkart" in extracted_title or len(extracted_title) < 4:
        slug_match = re.search(r'flipkart\.com/(?:dl/)?([^/?#]+)/p/', final_url, re.IGNORECASE)
        if slug_match:
            slug = slug_match.group(1)
            words = slug.split('-')
            extracted_title = " ".join([w.capitalize() for w in words if w])
    
    if not extracted_title:
        extracted_title = "Flipkart Product"

    # 2. Price Extraction (Robust multi-layer extraction)
    extracted_price = 0
    
    # Layer A: Schema JSON-LD
    json_ld_matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for j_text in json_ld_matches:
        try:
            data = json.loads(j_text.strip())
            if isinstance(data, dict):
                offers = data.get("offers")
                if isinstance(offers, dict) and "price" in offers:
                    extracted_price = int(float(offers["price"]))
                    break
                elif isinstance(offers, list) and len(offers) > 0 and "price" in offers[0]:
                    extracted_price = int(float(offers[0]["price"]))
                    break
        except Exception:
            pass

    # Layer B: Meta tags
    if not extracted_price:
        price_meta = re.search(r'<meta\s+(?:itemprop|property|name)=["\'](?:price|product:price:amount|og:price:amount)["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
        if price_meta:
            clean_p = re.sub(r'\D', '', price_meta.group(1))
            if clean_p:
                extracted_price = int(clean_p)

    # Layer C: Standard Flipkart dynamic classes
    if not extracted_price:
        price_cls = re.search(r'(?:Nx9bqj|CxhGGd|_30jeq3|_16Jk6d)[^>]*>₹?([\d,]+)<', html)
        if price_cls:
            clean_p = re.sub(r'\D', '', price_cls.group(1))
            if clean_p:
                extracted_price = int(clean_p)

    # 3. Image Extraction
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
            print(f"Error downloading image bytes: {img_err}")

    return extracted_title, extracted_price, image_bytes

def create_rebrandly_short_link(destination_url: str, user_mobile: str) -> tuple[bool, str]:
    """Creates a shortened link on Rebrandly with custom slashtag: Flipkart_UserMobile_RandomCode."""
    rebrand_key = (
        os.environ.get("Rebrand_Api")
        or os.environ.get("REBRAND_API")
        or os.environ.get("REBRAND_API_KEY")
        or os.environ.get("REBRANDLY_API_KEY")
    )
    if not rebrand_key:
        return False, "Rebrand_Api environment variable is missing!"

    random_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    slashtag = f"Flipkart_{user_mobile}_{random_code}"

    endpoint = "https://api.rebrandly.com/v1/links"
    headers = {
        "Content-Type": "application/json",
        "apikey": rebrand_key.strip()
    }
    
    dest = destination_url.strip()
    if not dest.startswith(('http://', 'https://')):
        dest = 'https://' + dest

    payload = {
        "destination": dest,
        "slashtag": slashtag,
        "title": f"Flipkart Order {user_mobile}"
    }

    try:
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            short_url = data.get("shortUrl")
            if short_url:
                final_short = f"https://{short_url}" if not short_url.startswith("http") else short_url
                return True, final_short
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        try:
            payload.pop("slashtag", None)
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                short_url = data.get("shortUrl")
                if short_url:
                    final_short = f"https://{short_url}" if not short_url.startswith("http") else short_url
                    return True, final_short
        except Exception:
            return False, f"Rebrandly API Error ({e.code}): {err_msg}"
    except Exception as ex:
        return False, f"Rebrandly Exception: {str(ex)}"

    return False, "Could not obtain short URL from Rebrandly response."

def generate_unique_referral_code(user_records):
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=7))
        if not any(r.get("refer_code") == code for r in user_records.values()):
            return code

async def sync_user_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, status: str, trial: int, last_report: float = 0.0, refer_code: str = "None", refer_from: str = "None", reward_given: str = "False"):
    user_records = context.bot_data.setdefault("user_records", {})
    text = (f"Userid: {user_id}\nStatus: {status}\nTrial: {trial}\n"
            f"LastReport: {last_report}\nReferCode: {refer_code}\n"
            f"ReferFrom: {refer_from}\nRewardGiven: {reward_given}")
    
    if user_id in user_records and "msg_id" in user_records[user_id]:
        msg_id = user_records[user_id]["msg_id"]
        try:
            await context.bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=msg_id, text=text)
            user_records[user_id] = {"msg_id": msg_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from, "reward_given": reward_given}
            return
        except Exception:
            pass 
            
    try:
        msg = await context.bot.send_message(chat_id=DB_CHANNEL_ID, text=text)
        user_records[user_id] = {"msg_id": msg.message_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from, "reward_given": reward_given}
    except Exception as e:
        print(f"Failed to post to DB Channel: {e}")

async def track_and_check_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return False
        
    user_records = context.bot_data.setdefault("user_records", {})
    if user_id not in user_records:
        await sync_user_to_channel(context, user_id, "Active", 0) 
        return False
        
    if str(user_records[user_id].get("status", "Active")).lower() == "blocked":
        return True
    return False

# ---------------- CHANNEL STARTUP RECOVERY & 2-WAY SYNC ---------------- #
async def parse_channel_post_content(context: ContextTypes.DEFAULT_TYPE, message):
    """Parses text and media of a channel message into bot_data cache."""
    if not message:
        return
    caption = message.caption or message.text or ""
    tags = ["Logo", "EnglishTutorial", "HindiTutorial", "ProductLink", "AccountNumber", "Ready"]
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

    if message.text:
        data_map = {}
        for line in message.text.split('\n'):
            if ':' in line:
                parts = line.split(':', 1)
                data_map[parts[0].strip().lower()] = parts[1].strip()

        if 'userid' in data_map:
            try:
                user_id = int(data_map['userid'])
                status = data_map.get('status', 'Active').capitalize()
                trial = int(data_map.get('trial', 0))
                last_report = float(data_map.get('lastreport', 0.0))
                refer_code = data_map.get('refercode', 'None')
                refer_from = data_map.get('referfrom', 'None')
                reward_given = data_map.get('rewardgiven', 'False').capitalize()
                
                user_records = context.bot_data.setdefault("user_records", {})
                user_records[user_id] = {
                    "msg_id": message.message_id, "status": status, "trial": trial, 
                    "last_report": last_report, "refer_code": refer_code, 
                    "refer_from": refer_from, "reward_given": reward_given
                }
            except Exception:
                pass

async def hydrate_channel_database_on_startup(app: Application):
    """Restores all users, balances, refer codes, and media attachments without creating duplicates."""
    print("⏳ Scanning Database Channel to hydrate in-memory database...")
    try:
        probe_msg = await app.bot.send_message(chat_id=DB_CHANNEL_ID, text="🔄 <i>Database Hydration Sync in Progress...</i>", parse_mode="HTML")
        latest_id = probe_msg.message_id
        await app.bot.delete_message(chat_id=DB_CHANNEL_ID, message_id=latest_id)

        start_id = max(1, latest_id - 600)
        found_users = 0

        for mid in range(latest_id - 1, start_id, -1):
            try:
                fwd = await app.bot.forward_message(chat_id=DB_CHANNEL_ID, from_chat_id=DB_CHANNEL_ID, message_id=mid)
                await parse_channel_post_content(app, fwd)
                await app.bot.delete_message(chat_id=DB_CHANNEL_ID, message_id=fwd.message_id)
                found_users += 1
                await asyncio.sleep(0.02)
            except Exception:
                continue

        print(f"✅ Startup Sync Complete! Synced {len(app.bot_data.get('user_records', {}))} users & media cache.")
    except Exception as e:
        print(f"⚠️ Startup Database Hydration note: {e}")

async def channel_db_sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or post.chat_id != DB_CHANNEL_ID:
        return
    await parse_channel_post_content(context, post)

# ---------------- 10-MINUTE DEAL EXPIRATION JOB ---------------- #
async def expire_deal_link_job(context: ContextTypes.DEFAULT_TYPE):
    """Triggered after 10 minutes (600s) to remove Buy button and show expiration message."""
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
        f"❌ <i>The 10-minute checkout window for this discount token has ended. Standard marketplace price has been restored.</i>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Go to Dashboard", callback_data="dashboard")]])

    try:
        if is_media:
            await context.bot.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=expired_text, parse_mode="HTML", reply_markup=kb)
        else:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=expired_text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:
        print(f"Deal expiry edit error: {e}")

# ---------------- DYNAMIC MEDIA SENDER ---------------- #
async def send_dynamic_media(context, chat_id, tag, caption=None, reply_markup=None):
    file_id = context.bot_data.get(f"media_{tag}")
    file_type = context.bot_data.get(f"media_{tag}_type")
    
    if not file_id:
        if tag == "Logo":
            await context.bot.send_photo(chat_id=chat_id, photo=LOGO_URL_FALLBACK, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"[Attachment {tag} not set by Admin]\n\n{caption}", reply_markup=reply_markup, parse_mode="HTML")
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

def parse_datetime(dt_str: str):
    dt_str = " ".join(dt_str.split()).upper()
    formats = ["%d/%m/%y %I%p", "%d/%m/%Y %I%p", "%d/%m/%y %I:%M%p", "%d/%m/%Y %I:%M%p"]
    for fmt in formats:
        try: return datetime.strptime(dt_str, fmt)
        except ValueError: continue
    return None

async def update_countdown_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    now = datetime.now()
    if now >= job.data["end_time"]:
        try: await context.bot.edit_message_text(chat_id=job.chat_id, message_id=job.data["msg_id"], text=f"🚨 <b>Countdown Finished!</b>\nSale '{job.data['name']}' has ended.", parse_mode="HTML")
        except: pass
        job.schedule_removal()
        return
    diff = job.data["end_time"] - now
    h, rem = divmod(diff.seconds, 3600)
    m, s = divmod(rem, 60)
    t_str = (f"{diff.days}d " if diff.days > 0 else "") + f"{h}h {m}m {s}s"
    text = f"⏳ <b>Live Countdown: {job.data['name']}</b>\n\nEnds in: <b>{t_str}</b>"
    try: await context.bot.edit_message_text(chat_id=job.chat_id, message_id=job.data["msg_id"], text=text, parse_mode="HTML")
    except: pass

# ---------------- COMMAND HANDLERS ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    user = update.effective_user
    context.user_data["state"] = None
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    welcome_text = f"Hello <b>{full_name}</b> 👋🏻\nWelcome To @Rebrandx_bot"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Let's Start", callback_data="lets_start")]])
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=kb)

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        user_records = context.bot_data.get("user_records", {})
        if target_id in user_records:
            rec = user_records[target_id]
            await sync_user_to_channel(context, target_id, "Active", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))
            await update.message.reply_text(f"✅ User {target_id} unblocked.")
        else:
            await update.message.reply_text("❌ User not found.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /unblock <userid>")

async def go_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = [
        [InlineKeyboardButton("Announcement", callback_data="adm_menu_announcement")],
        [InlineKeyboardButton("End Sale", callback_data="adm_menu_endsale")],
        [InlineKeyboardButton("Message User", callback_data="adm_menu_msg_user")],
        [InlineKeyboardButton("Special Offer", callback_data="adm_menu_spoffer")],
        [InlineKeyboardButton("End", callback_data="adm_menu_end")],
        [InlineKeyboardButton("Close", callback_data="adm_menu_close")]
    ]
    await update.message.reply_text("👑 <b>Admin Dashboard</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# ---------------- TELEGRAM STARS PAYMENT HANDLERS ---------------- #
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    user_records = context.bot_data.get("user_records", {})
    rec = user_records.get(user_id, {})
    
    trials = rec.get("trial", 0)
    refer_from = rec.get("refer_from", "None")
    reward_given = rec.get("reward_given", "False")
    refer_code = rec.get("refer_code", "None")

    added = 0
    if payload == "buy_pack_1": added = 1
    elif payload == "buy_pack_2": added = 2
    elif payload == "buy_pack_4": added = 4
    elif payload == "buy_pack_8": 
        added = 8
        if refer_code == "None":
            refer_code = generate_unique_referral_code(user_records)
            await context.bot.send_message(chat_id=user_id, text=f"🎁 <b>Bonus Unlocked!</b>\nYou now have a unique Referral Code: <code>{refer_code}</code>\n\nShare this to get free discounts when your friends make a purchase!", parse_mode="HTML")
        
    trials += added
    await update.message.reply_text(f"🎉 Payment Successful! You have received {added} Discount link(s).")
    
    if refer_from != "None" and reward_given == "False":
        reward_given = "True"
        try:
            ref_id = int(refer_from)
            ref_rec = user_records.get(ref_id)
            if ref_rec:
                r_trials = ref_rec.get("trial", 0) + 1
                await sync_user_to_channel(context, ref_id, ref_rec.get("status", "Active"), r_trials, ref_rec.get("last_report", 0.0), ref_rec.get("refer_code", "None"), ref_rec.get("refer_from", "None"), ref_rec.get("reward_given", "False"))
                await context.bot.send_message(chat_id=ref_id, text="🎁 <b>Bonus!</b>\nSomeone you referred just made their first purchase! You have been rewarded with +1 Free Discount link!", parse_mode="HTML")
        except Exception: pass

    await sync_user_to_channel(context, user_id, rec.get("status", "Active"), trials, rec.get("last_report", 0.0), refer_code, refer_from, reward_given)

# ---------------- CALLBACK QUERY HANDLER WITH DEBOUNCE LOCK ---------------- #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    query = update.callback_query
    user = update.effective_user
    chat_id = query.message.chat_id
    data = query.data
    user_records = context.bot_data.get("user_records", {})

    # Double-tap Lock Protection
    lock_key = f"{user.id}_{data}"
    if lock_key in click_locks:
        await query.answer("⏳ Processing, please wait...")
        return
        
    click_locks.add(lock_key)
    await query.answer()

    try:
        # -- ADMIN /GO MENU --
        if data == "adm_menu_announcement":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_ANNOUNCEMENT"}
            await edit_message_or_caption(query, "Write Announcement Message (You can attach image or video):")
        elif data == "adm_menu_endsale":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_SALE_DATE", "data": {}}
            await edit_message_or_caption(query, "Send date and time format: dd/mm/yy 1-12Am/Pm:")
        elif data == "adm_menu_msg_user":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_MSG_USER_ID"}
            await edit_message_or_caption(query, "Send User ID to message:")
        elif data == "adm_menu_spoffer":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_SPO_LINK", "data": {}}
            await edit_message_or_caption(query, "Send Flipkart Link:")
        elif data == "adm_menu_end":
            kb = [[InlineKeyboardButton("User", callback_data="adm_menu_end_user"), InlineKeyboardButton("All", callback_data="adm_menu_end_all")]]
            await edit_message_or_caption(query, "Block a specific User or All?", reply_markup=InlineKeyboardMarkup(kb))
        elif data == "adm_menu_end_user":
            admin_sessions[ADMIN_ID] = {"step": "WAITING_BLOCK_USER_ID"}
            await edit_message_or_caption(query, "Send User ID to block:")
        elif data == "adm_menu_end_all":
            kb = [[InlineKeyboardButton("Confirm Block All", callback_data="adm_menu_end_all_confirm")]]
            await edit_message_or_caption(query, "Are you sure?", reply_markup=InlineKeyboardMarkup(kb))
        elif data == "adm_menu_end_all_confirm":
            for u_id, rec in list(user_records.items()):
                if u_id != ADMIN_ID:
                    await sync_user_to_channel(context, u_id, "Blocked", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))
                    await asyncio.sleep(0.05)
            await edit_message_or_caption(query, "✅ All users blocked.")
        elif data == "adm_menu_close":
            try: await query.message.delete()
            except: pass

        # -- ADMIN ACCEPT WORKFLOW --
        elif data.startswith("adm_accept_"):
            target_id = int(data.split("adm_accept_")[1])
            admin_sessions[ADMIN_ID] = {"target_user_id": target_id, "step": "WAITING_ALL_DETAILS", "data": {}}
            prompt = (f"✅ <b>Accepted User <code>{target_id}</code></b>\n\n"
                      "<b>Send details in exactly 3 lines:</b>\n"
                      "Line 1: Discount (e.g. 50% or ₹15,000)\n"
                      "Line 2: Final Price (e.g. 45000)\n"
                      "Line 3: HyperLink (Long affiliate link to shorten)")
            await edit_message_or_caption(query, prompt, parse_mode="HTML")

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
            
            price_display = format_inr(p_price) if p_price > 0 else "Actual Price"
            admin_message = (
                f"1. <b><code>{target_id}</code></b>\n"
                f"2. {full_name}\n"
                f"3. <b>Product:</b> {p_name}\n"
                f"4. <b>Original Price:</b> {price_display}\n"
                f"5. <b>Link:</b> {p_link}\n"
                f"6. <b>Mobile:</b> {mob}"
            )
            await edit_message_or_caption(query, admin_message, reply_markup=kb, parse_mode="HTML")

        elif data.startswith("adm_rej_stock_"):
            target_id = int(data.split("adm_rej_stock_")[1])
            await context.bot.send_message(chat_id=target_id, text="Your provided Product is out of stock and you waste your 1 discount point")
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code>\n<b>Reason:</b> Out of Stock (No Refund)", parse_mode="HTML")

        elif data.startswith("adm_rej_nodisc_"):
            target_id = int(data.split("adm_rej_nodisc_")[1])
            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            p_name = req_data.get("product_name", "Flipkart Product")
            p_link = req_data.get("product_link", "https://flipkart.com")
            
            # Refund 1 point back
            rec = user_records.get(target_id, {})
            refunded_trials = rec.get("trial", 0) + 1
            await sync_user_to_channel(context, target_id, rec.get("status", "Active"), refunded_trials, rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))

            user_msg = f'Discount Not avalable on <a href="{p_link}">{p_name}</a> We gave you Your 1 discount point back'
            await context.bot.send_message(chat_id=target_id, text=user_msg, parse_mode="HTML", disable_web_page_preview=True)
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code>\n<b>Reason:</b> Discount Not Available\n✅ <b>1 Discount Point Refunded to User</b>", parse_mode="HTML")

        elif data.startswith("adm_rej_invalid_"):
            target_id = int(data.split("adm_rej_invalid_")[1])
            await context.bot.send_message(chat_id=target_id, text="Your provided link is Changed by other server")
            await edit_message_or_caption(query, f"❌ Rejected User <code>{target_id}</code>\n<b>Reason:</b> Invalid / Changed Link", parse_mode="HTML")

        # -- ADMIN VERIFICATION BEFORE SENDING --
        elif data == "verify_no":
            if ADMIN_ID in admin_sessions:
                admin_sessions[ADMIN_ID]["step"] = "WAITING_ALL_DETAILS"
                await edit_message_or_caption(query, "Let's rewrite.\nSend details in exactly 3 lines:\nLine 1: Discount\nLine 2: Final Price\nLine 3: HyperLink")
        
        elif data == "verify_yes":
            if ADMIN_ID not in admin_sessions: return
            session = admin_sessions[ADMIN_ID]
            target_id = session.get("target_user_id")
            data_dict = session.get("data", {})
            
            await edit_message_or_caption(query, "⏳ <b>Creating custom Rebrandly Short Link... Please wait.</b>", parse_mode="HTML")

            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            user_orig_link = req_data.get("product_link", "https://flipkart.com")
            user_mobile = req_data.get("mobile_num", "0000000000")
            prod_name = req_data.get("product_name", "Flipkart Product")
            prod_orig_price = req_data.get("product_price", 0)
            prod_img_bytes = req_data.get("product_image_bytes")

            original_hyperlink = data_dict["hyper_link"]
            success, short_or_err = await asyncio.to_thread(create_rebrandly_short_link, original_hyperlink, user_mobile)
            
            if not success:
                await edit_message_or_caption(
                    query,
                    f"❌ <b>Rebrandly Short Link Generation Failed!</b>\n\n"
                    f"<b>Reason:</b> {short_or_err}\n\n"
                    f"⚠️ <i>User was NOT notified because the short link could not be created. Please verify your Rebrand_Api key and try again.</i>",
                    parse_mode="HTML"
                )
                return

            final_price_fmt = format_inr(data_dict["final_price"])
            
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
            msg_text = "🎉 <b>Congratulations!</b>\nYour link is qualified for a discount."
            
            try:
                await send_dynamic_media(context, target_id, "Ready", msg_text, kb)
                await edit_message_or_caption(
                    query,
                    f"✅ <b>Setup Completed!</b>\n\n"
                    f"🔗 <b>Short Link:</b> <code>{short_or_err}</code>\n"
                    f"📦 <b>Product:</b> {prod_name}\n\n"
                    f"Message successfully sent to User <code>{target_id}</code>.",
                    parse_mode="HTML"
                )
            except Exception as e:
                await edit_message_or_caption(query, f"✅ Setup Completed in memory, but ❌ Failed to notify User <code>{target_id}</code>. Error: {e}", parse_mode="HTML")
                
            del admin_sessions[ADMIN_ID]

        # -- USER /START MENUS --
        elif data == "lets_start":
            text = "Hi I am Rebrand bot and I have a Tutorial Video. Which language do you want for that video?"
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
            caption = "⚠️ <b>Bina Video Dekhe Continue na kare</b>\n\nHere is the tutorial:"
            await send_dynamic_media(context, chat_id, tag, caption=caption, reply_markup=kb)

        elif data == "dashboard":
            trials_left = user_records.get(user.id, {}).get("trial", 0)
            buttons = [
                [InlineKeyboardButton("Report a Problem", callback_data="report_problem"), InlineKeyboardButton("Terms", callback_data="terms")],
                [InlineKeyboardButton("About us", callback_data="about_us"), InlineKeyboardButton("Shop", callback_data="purchase_menu")]
            ]
            
            if trials_left > 0:
                buttons.append([InlineKeyboardButton(f"🚀 Start x{trials_left}", callback_data="direct_start")])
            else:
                buttons.append([InlineKeyboardButton(f"🚀 Start x0", callback_data="no_trial_start")])

            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Welcome to Rebrand Dashboard!", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "no_trial_start":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Enter Referral Code", callback_data="enter_referral")],
                [InlineKeyboardButton("Shop", callback_data="purchase_menu")],
                [InlineKeyboardButton("Back", callback_data="dashboard")]
            ])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Enter Referral Code Here or Purchase Discounts", reply_markup=kb)

        elif data == "about_us":
            lang = context.user_data.get('lang', 'lang_en')
            if lang == "lang_hi":
                text = (
                    "Rebrand Kaise Kaam Karta Hai:\n"
                    "Jab Flipkart bade sales event host karta hai, tab high traffic ki wajah se server timeout aur session drop ho jate hain. Jisse valid price drops aur tokens fail ho jate hain.\n\n"
                    "Rebrand in unhandled session tokens ke liye ek fallback repository hai:\n"
                    "• Real-Time Capture: Humara system sale ke dauran expire hue tokens ko log karta hai.\n"
                    "• Sale khatam hone ke baad bhi aap in verified tokens se heavy discount pa sakte hain.\n"
                    "• Supported Sales: Big Billion Days, GOAT Sale, Big Diwali Sale, Flipkart Black Friday Sale."
                )
            else:
                text = (
                    "How Rebrand Works:\n"
                    "When major e-commerce platforms like Flipkart host flagship sales events, high traffic volumes frequently lead to server timeouts and session drops. Consequently, thousands of valid price drops, flash discounts, and promotional tokens are abandoned or fail at checkout.\n\n"
                    "Rebrand serves as a dedicated fallback repository for these unhandled session tokens:\n"
                    "• Real-Time Token Capture: Our system logs expired or dropped discount session tokens generated during high-load sale events.\n"
                    "• Automated Liquidation: We aggregate and validate these tokens so members can access heavy discounts even after flash sales end.\n"
                    "• Multi-Sale Integration: Fully synced across major shopping festivals:\n"
                    "Big Billion Days, GOAT Sale, Big Diwali Sale, Flipkart Black Friday Sale."
                )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await send_dynamic_media(context, chat_id, "Logo", text, kb)

        elif data == "terms":
            lang = context.user_data.get('lang', 'lang_en')
            if lang == "lang_hi":
                text = (
                    "Terms - Upyogkarta ki Zimmedari aur Refund Policy\n\n"
                    "Users ko apna sahi aur active Flipkart registered mobile number dena anivarya hai. Rebrand is number aur link ka istemal karke ek secure token banata hai jo automatically discount apply karke checkout page kholta hai.\n\n"
                    "Kripya dhyan dein ki order seedha aapke diye gaye number se linked account pe place hoga. Galat ya unauthorized number dene ki stithi mein kisi bhi nuksan ke liye Rebrand zimmedar nahi hoga aur koi refund/cancellation nahi hoga.\n\n"
                    "Lekin, agar valid mobile number hone ke bawajood payment fail hoti hai, toh Rebrand pure transaction amount ki refund ki guarantee deta hai."
                )
            else:
                text = (
                    "Terms - User Responsibility, Automation, and Refund Policy\n\n"
                    "Users must provide the correct and active mobile number linked to their Flipkart account. The Rebrand bot utilizes this mobile number and the provided product link to generate a secure session token specifically for the checkout process, directly opening a checkout page with the discount automatically applied.\n\n"
                    "Please be advised that the transaction will be processed and the order will be placed directly on the Flipkart account associated with the mobile number you provide. Rebrand is not responsible, and no refunds or cancellations will be issued, for any financial losses or incorrect orders resulting from the submission of an inaccurate, incorrect, or unauthorized mobile number by the user.\n\n"
                    "However, if a payment fails despite the user providing a valid and correct mobile number, Rebrand guarantees a full refund for the transaction amount."
                )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)

        elif data == "report_problem":
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data="report_continue"), InlineKeyboardButton("Back", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="⚠️ Notice: You can send 1 report per week. Please continue carefully.", reply_markup=kb)

        elif data == "report_continue":
            last_rep = user_records.get(user.id, {}).get("last_report", 0.0)
            if time.time() - last_rep < 604800:
                try: await query.message.delete()
                except: pass
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
                await context.bot.send_message(chat_id=chat_id, text="❌ You have already submitted a report this week. Try again later.", reply_markup=kb)
                return
                
            context.user_data["state"] = "WAITING_VOICE_REPORT"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Send a 30-Second Voice Note explaining your issue:", reply_markup=kb)

        elif data == "purchase_menu":
            try: await query.message.delete()
            except: pass
            buttons = [
                [InlineKeyboardButton("1 Discount (500 ⭐️)", callback_data="buy_pack_1")],
                [InlineKeyboardButton("2 Discounts (999 ⭐️)", callback_data="buy_pack_2")],
                [InlineKeyboardButton("4 Discounts (1400 ⭐️)", callback_data="buy_pack_4")],
                [InlineKeyboardButton("8 Discounts (3000 ⭐️)", callback_data="buy_pack_8")],
                [InlineKeyboardButton("Enter Referral Code", callback_data="enter_referral")],
                [InlineKeyboardButton("Back", callback_data="dashboard")]
            ]
            text = ("🛒 <b>Discount Store</b>\n\n"
                    "Purchase Discounts using Telegram Stars!\n\n"
                    "💡 <b>Referral Program:</b>\n"
                    "Buy the 8 Discounts pack to unlock your own Referral Code! When your friends use it, they get 1 free Discount, and when they buy a pack, you get 1 free Discount as a gift!")
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "enter_referral":
            context.user_data["state"] = "WAITING_REFERRAL_CODE"
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="purchase_menu")]])
            await context.bot.send_message(chat_id=chat_id, text="Please send the Referral Code you received:", reply_markup=kb)

        # --- ADMIN DIRECT BYPASS & STAR PAYMENTS ---
        elif data.startswith("buy_pack_"):
            try: await query.message.delete()
            except: pass

            if user.id == ADMIN_ID:
                added = 1 if data == "buy_pack_1" else 2 if data == "buy_pack_2" else 4 if data == "buy_pack_4" else 8
                current_rec = user_records.get(ADMIN_ID, {})
                new_trials = current_rec.get("trial", 0) + added
                await sync_user_to_channel(context, ADMIN_ID, "Active", new_trials, current_rec.get("last_report", 0.0), current_rec.get("refer_code", "None"), current_rec.get("refer_from", "None"), "False")
                
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back to Dashboard", callback_data="dashboard")]])
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"👑 <b>Admin Direct Bypass Activated!</b>\n\nAdded <b>+{added} Discounts</b> directly to your account for free.\nTotal Balance: <b>{new_trials}</b> Discounts.",
                    parse_mode="HTML",
                    reply_markup=kb
                )
                return

            title, description, payload, price_amount = "", "", "", 0
            if data == "buy_pack_1":
                title, description, payload, price_amount = "1 Discount", "Get 1 Free Discount", "buy_pack_1", 500
            elif data == "buy_pack_2":
                title, description, payload, price_amount = "2 Discounts", "Get 2 Free Discounts", "buy_pack_2", 999
            elif data == "buy_pack_4":
                title, description, payload, price_amount = "4 Discounts", "Get 4 Free Discounts", "buy_pack_4", 1400
            elif data == "buy_pack_8":
                title, description, payload, price_amount = "8 Discounts", "Get 8 Free Discounts + Unlocks Referral Code", "buy_pack_8", 3000
            prices = [LabeledPrice(title, price_amount)]
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Pay {price_amount} ⭐️", pay=True)],
                [InlineKeyboardButton("Cancel / Back", callback_data="purchase_menu")]
            ])
            await context.bot.send_invoice(chat_id=chat_id, title=title, description=description, payload=payload, provider_token="", currency="XTR", prices=prices, reply_markup=kb)

        elif data == "direct_start":
            context.bot_data.setdefault("user_flow_states", {})[user.id] = "NONE"
            context.user_data["state"] = "WAITING_FLIPKART_LINK"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
            text = "Send Your Product Link. The Product must be Electronic, and the price (without discount) must be at least ₹50,000."
            try: await query.message.delete()
            except: pass
            await send_dynamic_media(context, chat_id, "ProductLink", text, kb)

        elif data == "edit_details":
            context.user_data["state"] = "WAITING_FLIPKART_LINK"
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Send Your Product Link again:")

        elif data == "continue_submit":
            rec = user_records.get(user.id, {})
            trials_left = rec.get("trial", 0)
            new_trial_count = max(0, trials_left - 1)
            await sync_user_to_channel(context, user.id, rec.get("status", "Active"), new_trial_count, rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))

            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Turn on bot notification. We will send you the best discount within a few minutes.\nThank you for using Rebrand.")

            full_name = f"{user.first_name} {user.last_name or ''}".strip()
            p_name = context.user_data.get('product_name', 'Flipkart Product')
            p_price = context.user_data.get('product_price', 0)
            p_link = context.user_data.get('product_link', 'https://flipkart.com')
            mob = context.user_data.get('mobile_num', '')
            img_bytes = context.user_data.get('product_image_bytes')

            context.bot_data.setdefault("pending_requests", {})[user.id] = {
                "full_name": full_name,
                "product_name": p_name,
                "product_price": p_price,
                "product_link": p_link,
                "mobile_num": mob,
                "product_image_bytes": img_bytes
            }

            price_display = format_inr(p_price) if p_price > 0 else "Actual Extracted Price"
            admin_message = (
                f"1. <b><code>{user.id}</code></b>\n"
                f"2. {full_name}\n"
                f"3. <b>Product:</b> {p_name}\n"
                f"4. <b>Original Price:</b> {price_display}\n"
                f"5. <b>Link:</b> {p_link}\n"
                f"6. <b>Mobile:</b> {mob}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"),
                 InlineKeyboardButton("Reject", callback_data=f"adm_reject_menu_{user.id}")]
            ])
            
            if img_bytes:
                try:
                    await context.bot.send_photo(chat_id=ADMIN_ID, photo=io.BytesIO(img_bytes), caption=admin_message, parse_mode="HTML", reply_markup=keyboard)
                except Exception:
                    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)
            else:
                await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

        # -- SPECIAL OFFER BUTTON --
        elif data == "sp_offer_grab":
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(chat_id=chat_id, text="Turn on bot notification. We will send you the Discount Redirect.\nThank you for using Rebrand.")
            full_name = f"{user.first_name} {user.last_name or ''}".strip()
            admin_message = f"🎁 <b>[Special Offer]</b>\n1. <b><code>{user.id}</code></b>\n2. {full_name}"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"), InlineKeyboardButton("Reject", callback_data=f"adm_reject_menu_{user.id}")]])
            await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

        # -- POST-APPROVAL WORKFLOW FOR USER WITH 10-MINUTE TIMER & MIND-TRIGGERING LAYOUT --
        elif data == "resend_qualified_msg":
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="user_continue_ready"), InlineKeyboardButton("Tutorial", callback_data="tutorial_ready_chk")]
            ])
            msg_text = "🎉 <b>Congratulations!</b>\nYour link is qualified for a discount."
            await send_dynamic_media(context, chat_id, "Ready", msg_text, kb)
            
        elif data == "tutorial_ready_chk":
            lang = context.user_data.get('lang', 'lang_en')
            tag = "HindiTutorial" if lang == "lang_hi" else "EnglishTutorial"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="resend_qualified_msg")]])
            try: await query.message.delete()
            except: pass
            caption = "⚠️ <b>Bina Video Dekhe Continue na kare</b>\n\nHere is the tutorial:"
            await send_dynamic_media(context, chat_id, tag, caption=caption, reply_markup=kb)

        elif data == "user_continue_ready":
            try: await query.message.delete()
            except: pass
            
            d_data = context.bot_data.get("ready_links", {}).get(user.id, {})
            if not d_data:
                await context.bot.send_message(chat_id=chat_id, text="❌ Data fetch error. Please contact support.")
                return

            orig_link = d_data.get('orig_link', 'https://flipkart.com')
            if not orig_link.startswith(('http://', 'https://')):
                orig_link = 'https://' + orig_link
                
            orig_p_val = d_data.get('orig_price', 0)
            orig_p_str = format_inr(orig_p_val) if orig_p_val > 0 else "Market MRP"

            # Mind-Triggering Price Breakdown UI
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
                f"⚠️ <i>Click the button below to buy directly from Flipkart with the discount applied.</i>"
            )
            
            url = d_data.get('hyper_link', 'https://flipkart.com')
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔴 Buy Now 🔴", url=url)]])
            
            image_bytes = d_data.get('product_image_bytes')
            sent_msg = None
            is_media = False

            if image_bytes:
                try:
                    sent_msg = await context.bot.send_photo(chat_id=chat_id, photo=io.BytesIO(image_bytes), caption=text, parse_mode="HTML", reply_markup=kb)
                    is_media = True
                except Exception as e:
                    print(f"Error sending photo to user: {e}")
                    sent_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
                    is_media = False
            else:
                sent_msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
                is_media = False
            
            if user.id in context.bot_data.get("user_flow_states", {}):
                context.bot_data["user_flow_states"][user.id] = "DONE"

            # 10-Minute Real-Time Timer: Removes Buy Now button & shows Dashboard button
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

    finally:
        await asyncio.sleep(1.0)
        click_locks.discard(lock_key)


# ---------------- TEXT & MEDIA HANDLER ---------------- #
async def media_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    user_id = update.effective_user.id
    user_records = context.bot_data.get("user_records", {})
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else update.message.caption.strip() if update.message.caption else ""
    
    # -- REFERRAL PROMO CODES (NOW WITH START BUTTONS) --
    if state == "WAITING_REFERRAL_CODE":
        if text.startswith("/"):
            context.user_data["state"] = None
            return 

        code = text.upper()
        current_rec = user_records.get(user_id, {})
        
        start_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start Now", callback_data="direct_start")],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="dashboard")]
        ])

        if code == "ADMINREFFER009":
            new_trials = current_rec.get("trial", 0) + 9
            await sync_user_to_channel(context, user_id, current_rec.get("status", "Active"), new_trials, current_rec.get("last_report", 0.0), current_rec.get("refer_code", "None"), current_rec.get("refer_from", "None"), current_rec.get("reward_given", "False"))
            context.user_data["state"] = None
            await update.message.reply_text("✅ <b>Secret Promo Code Accepted!</b>\nYou have received <b>9 Free Discount links</b>.", parse_mode="HTML", reply_markup=start_kb)
            return

        referrer_uid = None
        for uid, rec in user_records.items():
            if rec.get("refer_code") == code and rec.get("refer_code") != "None":
                referrer_uid = uid
                break
                
        if not referrer_uid:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="purchase_menu")]])
            await update.message.reply_text("❌ Invalid Referral Code. Please check the code and try again.", reply_markup=kb)
            return
            
        if referrer_uid == user_id:
            context.user_data["state"] = None
            await update.message.reply_text("❌ You cannot use your own Referral Code!")
            return
            
        if current_rec.get("refer_from") != "None":
            context.user_data["state"] = None
            await update.message.reply_text("❌ You have already used a Referral Code before!")
            return
            
        new_trials = current_rec.get("trial", 0) + 1
        await sync_user_to_channel(context, user_id, current_rec.get("status", "Active"), new_trials, current_rec.get("last_report", 0.0), current_rec.get("refer_code", "None"), str(referrer_uid), "False")
        
        context.user_data["state"] = None
        await update.message.reply_text("✅ <b>Referral Code Accepted!</b>\nYou have received <b>1 Free Discount link</b>.", parse_mode="HTML", reply_markup=start_kb)
        return

    if state == "WAITING_VOICE_REPORT":
        if not update.message.voice:
            await update.message.reply_text("❌ Please send a Voice Note.")
            return
        if update.message.voice.duration > 35:
            await update.message.reply_text("❌ Voice note must be around 30 seconds or less. Try again.")
            return
            
        rec = user_records.get(user_id, {})
        await sync_user_to_channel(context, user_id, rec.get("status", "Active"), rec.get("trial", 0), time.time(), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))
        
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ <b>New Issue Report from <code>{user_id}</code></b>", parse_mode="HTML")
        await update.message.copy(chat_id=ADMIN_ID)
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="dashboard")]])
        await update.message.reply_text("Within 24 hours, our team member will contact you.", reply_markup=kb)
        context.user_data["state"] = None
        return

    # --- ADMIN WORKFLOW ENGINE ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_id = session.get("target_user_id")

        if step == "WAITING_ALL_DETAILS":
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if len(lines) < 3:
                await update.message.reply_text("❌ Please provide exactly 3 lines:\nLine 1: Discount\nLine 2: Final Price\nLine 3: HyperLink\n\nTry again:")
                return
            
            discount, final_price, hyperlink = lines[0], lines[1], lines[2]
            req_data = context.bot_data.get("pending_requests", {}).get(target_id, {})
            auto_prod_name = req_data.get("product_name", "Flipkart Product")
            orig_p = req_data.get("product_price", 0)

            session["data"] = {
                "discount": discount,
                "final_price": final_price,
                "hyper_link": hyperlink
            }
            
            price_dsp = format_inr(orig_p) if orig_p > 0 else "Actual Price"
            verify_text = (
                f"Please verify the details for User <code>{target_id}</code>:\n\n"
                f"📦 <b>Product Header:</b> {auto_prod_name}\n"
                f"🏷 <b>Original Price:</b> {price_dsp}\n"
                f"💸 <b>Discount:</b> {discount}\n"
                f"💰 <b>Final Price:</b> {format_inr(final_price)}\n"
                f"🔗 <b>Target HyperLink (To Shorten):</b> {hyperlink}\n\n"
                f"Are these correct? On confirmation, the link will be shortened via Rebrandly."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, Send to User", callback_data="verify_yes"),
                 InlineKeyboardButton("No, Let me rewrite", callback_data="verify_no")]
            ])
            session["step"] = "WAITING_VERIFICATION"
            await update.message.reply_text(verify_text, reply_markup=kb, disable_web_page_preview=True, parse_mode="HTML")
            return

        elif step == "WAITING_MSG_USER_ID":
            try:
                t_msg_id = int(text)
                session["target_user_id"] = t_msg_id
                session["step"] = "WAITING_MSG_PAYLOAD"
                await update.message.reply_text(f"Send the message/attachment for User {t_msg_id}:")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Must be a number.")
            return
            
        elif step == "WAITING_MSG_PAYLOAD":
            t_msg_id = session.get("target_user_id")
            try:
                await update.message.copy(chat_id=t_msg_id)
                await update.message.reply_text(f"✅ Message sent successfully to {t_msg_id}!")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to send: {e}")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_ANNOUNCEMENT":
            sent = 0
            for u_id, rec in user_records.items():
                if u_id == ADMIN_ID or rec.get("status", "Active").lower() == "blocked": continue
                try:
                    await update.message.copy(chat_id=u_id)
                    sent += 1
                    await asyncio.sleep(0.05)
                except: pass
            await update.message.reply_text(f"✅ Announcement Broadcasted to {sent} active users.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_SALE_DATE":
            parsed = parse_datetime(text)
            if not parsed or parsed <= datetime.now():
                await update.message.reply_text("❌ Invalid format or past time. Try again (e.g., '15/08/26 10AM'):")
                return
            session["data"]["end_time"] = parsed
            session["step"] = "WAITING_SALE_NAME"
            await update.message.reply_text("Send the End Sale Name:")
            return

        elif step == "WAITING_SALE_NAME":
            sale_name = text
            end_time = session["data"]["end_time"]
            del admin_sessions[user_id]
            
            msg = await update.message.reply_text(f"⏳ Starting countdown for '{sale_name}'...")
            context.job_queue.run_repeating(
                update_countdown_message, interval=10, first=1,
                data={"msg_id": msg.message_id, "end_time": end_time, "name": sale_name},
                chat_id=user_id, name=f"countdown_{msg.message_id}"
            )
            
            for u_id, rec in user_records.items():
                if u_id == ADMIN_ID or rec.get("status", "Active").lower() == "blocked": continue
                try:
                    await context.bot.send_message(chat_id=u_id, text=f"🚨 <b>{sale_name}</b> is ending soon!\nMark your calendars for {end_time.strftime('%d/%m/%Y %I:%M %p')}.", parse_mode="HTML")
                    await asyncio.sleep(0.05)
                except: pass
            return

        elif step == "WAITING_SPO_LINK":
            session["data"]["spo_link"] = text
            session["step"] = "WAITING_SPO_NAME"
            await update.message.reply_text("Send Product Name:")
            return
        elif step == "WAITING_SPO_NAME":
            session["data"]["spo_name"] = text
            session["step"] = "WAITING_SPO_CPRICE"
            await update.message.reply_text("Send Current Price:")
            return
        elif step == "WAITING_SPO_CPRICE":
            session["data"]["spo_cprice"] = text
            session["step"] = "WAITING_SPO_DISC"
            await update.message.reply_text("Send Discount (e.g. 50%):")
            return
        elif step == "WAITING_SPO_DISC":
            session["data"]["spo_disc"] = text
            session["step"] = "WAITING_SPO_OPRICE"
            await update.message.reply_text("Send Offer Price:")
            return
        elif step == "WAITING_SPO_OPRICE":
            oprice = text
            offer_text = f"{session['data']['spo_link']}\n<b>{session['data']['spo_name']}</b>\n<s>{session['data']['spo_cprice']}</s> - {session['data']['spo_disc']} = <b>{oprice}</b>"
            del admin_sessions[user_id]
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Get Offer Now", callback_data="sp_offer_grab")]])
            sent = 0
            for u_id, rec in user_records.items():
                if u_id == ADMIN_ID or rec.get("status", "Active").lower() == "blocked": continue
                try:
                    await context.bot.send_message(chat_id=u_id, text=offer_text, parse_mode="HTML", reply_markup=kb)
                    sent += 1
                    await asyncio.sleep(0.05)
                except: pass
            await update.message.reply_text(f"✅ Special offer broadcasted to {sent} active users.")
            return

        elif step == "WAITING_BLOCK_USER_ID":
            try:
                t_id = int(text)
                if t_id in user_records:
                    rec = user_records[t_id]
                    await sync_user_to_channel(context, t_id, "Blocked", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))
                    await update.message.reply_text(f"✅ User {t_id} has been blocked and database updated.")
                else:
                    await update.message.reply_text("❌ User not found in database.")
            except ValueError: await update.message.reply_text("❌ Invalid User ID. Must be a number.")
            del admin_sessions[user_id]
            return

    # --- REGULAR USER WORKFLOWS ---
    if state == "WAITING_FLIPKART_LINK" and text:
        clean_link = extract_flipkart_link(text)
        if clean_link:
            status_msg = await update.message.reply_text("🔍 Fetching product details from Flipkart...")
            
            p_title, p_price, p_image_bytes = await asyncio.to_thread(fetch_flipkart_metadata, clean_link)
            
            try:
                await status_msg.delete()
            except Exception:
                pass

            # Backend 50K Eligibility Verification
            if p_price > 0 and p_price < 50000:
                warn_text = (
                    f"❌ <b>Product Not Eligible!</b>\n\n"
                    f"📦 <b>Product:</b> {p_title}\n"
                    f"💰 <b>Detected Price:</b> {format_inr(p_price)}\n\n"
                    f"⚠️ <b>Requirement:</b> The product price must be at least <b>₹50,000</b> and the item must be an <b>Electronic</b> product.\n\n"
                    f"Please send a qualified product link."
                )
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back to Dashboard", callback_data="dashboard")]])
                await update.message.reply_text(warn_text, parse_mode="HTML", reply_markup=kb)
                return

            context.user_data["product_link"] = clean_link
            context.user_data["product_name"] = p_title
            context.user_data["product_price"] = p_price
            context.user_data["product_image_bytes"] = p_image_bytes
            context.user_data["state"] = "WAITING_MOBILE_NUMBER"

            price_dsp = format_inr(p_price) if p_price > 0 else "Actual Price"
            msg_text = (f"📦 <b>Detected Product:</b> {p_title}\n"
                        f"💰 <b>Price:</b> {price_dsp}\n\n"
                        "Send your Flipkart Account Number +91 XXXXXXXXXX.\n\n"
                        "⚠️ We have an authentic server, so we do not require an OTP or Verification code.\n"
                        "⚠️ Do not share your OTP or Email with anybody.")
            
            # Back button removed on mobile number demand
            await send_dynamic_media(context, update.message.chat_id, "AccountNumber", msg_text, reply_markup=None)
        else:
            await update.message.reply_text("❌ Invalid Link. Please send a valid Flipkart link.")

    elif state == "WAITING_MOBILE_NUMBER" and text:
        number_only = re.sub(r'\D', '', text)
        if len(number_only) >= 10:
            mobile_num = number_only[-10:]
            context.user_data["mobile_num"] = mobile_num
            context.user_data["state"] = None
            
            trials = user_records.get(user_id, {}).get("trial", 0)
            full_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()
            
            p_price = context.user_data.get('product_price', 0)
            price_display = format_inr(p_price) if p_price > 0 else "Actual Price"

            conf_text = (
                f"{full_name}, you have {trials} discount link(s) left. "
                "If you continue, we will generate a discounted link, and 1 link will be deducted.\n\n"
                f"📦 <b>Product:</b> {context.user_data.get('product_name')}\n"
                f"💰 <b>Price:</b> {price_display}\n"
                f"🔗 <b>Link:</b> {context.user_data['product_link']}\n"
                f"📱 <b>Number:</b> +91 {mobile_num}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Edit", callback_data="edit_details"), InlineKeyboardButton("Continue", callback_data="continue_submit")]])
            await update.message.reply_text(conf_text, reply_markup=kb, disable_web_page_preview=True, parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Please enter a valid 10-digit mobile number.")


# ---------------- APPLICATION STARTUP HOOK ---------------- #
async def post_init_setup(application: Application):
    """Triggered right after bot starts to hydrate channel history."""
    asyncio.create_task(hydrate_channel_database_on_startup(application))


# ---------------- MAIN APPLICATION ---------------- #
def main():
    if not BOT_TOKEN:
        print("WARNING: TELEGRAM_TOKEN environment variable is missing!")
        return

    Thread(target=run_flask, daemon=True).start()

    persistence = PicklePersistence(filepath="bot_state.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).post_init(post_init_setup).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("Go", go_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, media_and_text_handler))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_db_sync_handler))

    print("Bot is running 24/7 with 10-Min Timer, Actual Price Engine & Rebrandly integration...")
    app.run_polling()

if __name__ == "__main__":
    main()
