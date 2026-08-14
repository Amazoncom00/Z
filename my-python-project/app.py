import os
import re
import urllib.parse
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

# Global memory for admin workflows
admin_sessions = {}

# --- Dummy Flask Web Server to keep Cloud Hosting happy ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "X Discount Bot is Running 24/7 Successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ---------------- HELPERS & FORMATTERS ---------------- #
def format_inr(number_str: str) -> str:
    """Formats 79812 into ₹79,812 perfectly."""
    num = re.sub(r'\D', '', number_str)
    if not num: 
        return f"₹{number_str}"
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
        except Exception:
            pass 
        user_records[user_id] = {"msg_id": msg_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from, "reward_given": reward_given}
    else:
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
        
    if user_records[user_id].get("status", "Active").lower() == "blocked":
        return True
    return False

# ---------------- CHANNEL 2-WAY SYNC HANDLER ---------------- #
async def channel_db_sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post or post.chat_id != DB_CHANNEL_ID:
        return

    caption = post.caption or post.text or ""
    tags = ["Logo", "EnglishTutorial", "HindiTutorial", "ProductLink", "AccountNumber", "Ready"]
    for tag in tags:
        if tag in caption:
            if post.photo:
                context.bot_data[f"media_{tag}"] = post.photo[-1].file_id
                context.bot_data[f"media_{tag}_type"] = "photo"
            elif post.video:
                context.bot_data[f"media_{tag}"] = post.video.file_id
                context.bot_data[f"media_{tag}_type"] = "video"
            elif post.document:
                context.bot_data[f"media_{tag}"] = post.document.file_id
                context.bot_data[f"media_{tag}_type"] = "document"

    if post.text:
        match = re.search(r"Userid:\s*(\d+)\s*Status:\s*(\w+)\s*Trial:\s*(\d+)(?:\s*LastReport:\s*([\d\.]+))?(?:\s*ReferCode:\s*(\w+))?(?:\s*ReferFrom:\s*([\w]+))?(?:\s*RewardGiven:\s*(\w+))?", post.text, re.IGNORECASE)
        if match:
            user_id = int(match.group(1))
            status = match.group(2).capitalize()
            trial = int(match.group(3))
            last_report = float(match.group(4)) if match.group(4) else 0.0
            refer_code = match.group(5) if match.group(5) else "None"
            refer_from = match.group(6) if match.group(6) else "None"
            reward_given = match.group(7).capitalize() if match.group(7) else "False"
            
            user_records = context.bot_data.setdefault("user_records", {})
            user_records[user_id] = {"msg_id": post.message_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from, "reward_given": reward_given}

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
        # Failsafe if media is invalid or expired
        await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup, parse_mode="HTML")

def is_valid_flipkart_link(text: str) -> bool:
    return bool(re.search(r"flipkart", text, re.IGNORECASE))

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
    
    welcome_text = f"Hello <b>{full_name}</b> 👋🏻\nWelcome To @XDiscount_bot"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("About us", callback_data="about_us"), InlineKeyboardButton("Terms", callback_data="terms")],
        [InlineKeyboardButton("🍁 Start", callback_data="start_main")]
    ])
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=keyboard)

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
            await context.bot.send_message(chat_id=user_id, text=f"🎁 <b>Bonus Unlocked!</b>\nYou now have a unique Referral Code: <code>{refer_code}</code>\n\nShare this to get free discount links when your friends make a purchase!", parse_mode="HTML")
        
    trials += added
    await update.message.reply_text(f"🎉 Payment Successful! You have received {added} Discount link(s).")
    
    # Process First-Time Purchase Referral Reward
    if refer_from != "None" and reward_given == "False":
        reward_given = "True"
        try:
            ref_id = int(refer_from)
            ref_rec = user_records.get(ref_id)
            if ref_rec:
                r_trials = ref_rec.get("trial", 0) + 1
                await sync_user_to_channel(context, ref_id, ref_rec.get("status", "Active"), r_trials, ref_rec.get("last_report", 0.0), ref_rec.get("refer_code", "None"), ref_rec.get("refer_from", "None"), ref_rec.get("reward_given", "False"))
                await context.bot.send_message(chat_id=ref_id, text="🎁 <b>Bonus!</b>\nSomeone you referred just made their first purchase! You have been rewarded with +1 Free Discount link!", parse_mode="HTML")
        except Exception:
            pass

    await sync_user_to_channel(context, user_id, rec.get("status", "Active"), trials, rec.get("last_report", 0.0), refer_code, refer_from, reward_given)

# ---------------- CALLBACK QUERY HANDLER ---------------- #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user
    user_records = context.bot_data.get("user_records", {})
    chat_id = query.message.chat_id

    # -- ADMIN /GO MENU --
    if data == "adm_menu_announcement":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_ANNOUNCEMENT"}
        await query.message.edit_text("Write Announcement Message (You can attach image or video):")
    elif data == "adm_menu_endsale":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_SALE_DATE", "data": {}}
        await query.message.edit_text("Send date and time format: dd/mm/yy 1-12Am/Pm:")
    elif data == "adm_menu_spoffer":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_SPO_LINK", "data": {}}
        await query.message.edit_text("Send Flipkart Link:")
    elif data == "adm_menu_end":
        kb = [[InlineKeyboardButton("User", callback_data="adm_menu_end_user"), InlineKeyboardButton("All", callback_data="adm_menu_end_all")]]
        await query.message.edit_text("Block a specific User or All?", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "adm_menu_end_user":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_BLOCK_USER_ID"}
        await query.message.edit_text("Send User ID to block:")
    elif data == "adm_menu_end_all":
        kb = [[InlineKeyboardButton("Confirm Block All", callback_data="adm_menu_end_all_confirm")]]
        await query.message.edit_text("Are you sure?", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "adm_menu_end_all_confirm":
        for u_id, rec in list(user_records.items()):
            if u_id != ADMIN_ID:
                await sync_user_to_channel(context, u_id, "Blocked", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"), rec.get("reward_given", "False"))
                await asyncio.sleep(0.05)
        await query.message.edit_text("✅ All users blocked.")
    elif data == "adm_menu_close":
        try: await query.message.delete()
        except: pass

    # -- NEW USER /START MENUS --
    elif data == "main_menu":
        context.user_data["state"] = None
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        welcome_text = f"Hello <b>{full_name}</b> 👋🏻\nWelcome To @XDiscount_bot"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("About us", callback_data="about_us"), InlineKeyboardButton("Terms", callback_data="terms")],
            [InlineKeyboardButton("🍁 Start", callback_data="start_main")]
        ])
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text=welcome_text, parse_mode="HTML", reply_markup=keyboard)

    elif data in ["about_us", "hinglish_about"]:
        text = (
            "How X DISCOUNT Works:\n"
            "When major e-commerce platforms like Flipkart host flagship sales events, high traffic volumes frequently lead to server timeouts and session drops. Consequently, thousands of valid price drops, flash discounts, and promotional tokens are abandoned or fail at checkout.\n\n"
            "X DISCOUNT serves as a dedicated fallback repository for these unhandled session tokens:\n"
            "• Real-Time Token Capture: Our system logs expired or dropped discount session tokens generated during high-load sale events.\n"
            "• Automated Liquidation: We aggregate and validate these tokens so members can access heavy discounts even after flash sales end.\n"
            "• Multi-Sale Integration: Fully synced across major shopping festivals:\n"
            "Big Billion Days, GOAT Sale, Big Diwali Sale, Flipkart Black Friday Sale."
        )
        if data == "hinglish_about":
            text = (
                "X DISCOUNT Kaise Kaam Karta Hai:\n"
                "Jab Flipkart bade sales event host karta hai, tab high traffic ki wajah se server timeout aur session drop ho jate hain. Jisse valid price drops aur tokens fail ho jate hain.\n\n"
                "X DISCOUNT in unhandled session tokens ke liye ek fallback repository hai:\n"
                "• Real-Time Capture: Humara system sale ke dauran expire hue tokens ko log karta hai.\n"
                "• Sale khatam hone ke baad bhi aap in verified tokens se heavy discount pa sakte hain.\n"
                "• Supported Sales: Big Billion Days, GOAT Sale, Big Diwali Sale, Flipkart Black Friday Sale."
            )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Hinglish" if data=="about_us" else "English", callback_data="hinglish_about" if data=="about_us" else "about_us"), InlineKeyboardButton("Back", callback_data="main_menu")]
        ])
        try: await query.message.delete()
        except: pass
        await send_dynamic_media(context, chat_id, "Logo", text, keyboard)

    elif data in ["terms", "hinglish_terms"]:
        text = (
            "Terms - User Responsibility, Automation, and Refund Policy\n\n"
            "Users must provide the correct and active mobile number linked to their Flipkart account. The X Discount bot utilizes this mobile number and the provided product link to generate a secure session token specifically for the checkout process, directly opening a checkout page with the discount automatically applied.\n\n"
            "Please be advised that the transaction will be processed and the order will be placed directly on the Flipkart account associated with the mobile number you provide. X Discount is not responsible, and no refunds or cancellations will be issued, for any financial losses or incorrect orders resulting from the submission of an inaccurate, incorrect, or unauthorized mobile number by the user.\n\n"
            "However, if a payment fails despite the user providing a valid and correct mobile number, X Discount guarantees a full refund for the transaction amount."
        )
        if data == "hinglish_terms":
            text = (
                "Terms - Upyogkarta ki Zimmedari aur Refund Policy\n\n"
                "Users ko apna sahi aur active Flipkart registered mobile number dena anivarya hai. X Discount is number aur link ka istemal karke ek secure token banata hai jo automatically discount apply karke checkout page kholta hai.\n\n"
                "Kripya dhyan dein ki order seedha aapke diye gaye number se linked account pe place hoga. Galat ya unauthorized number dene ki stithi mein kisi bhi nuksan ke liye X Discount zimmedar nahi hoga aur koi refund/cancellation nahi hoga.\n\n"
                "Lekin, agar valid mobile number hone ke bawajood payment fail hoti hai, toh X Discount pure transaction amount ki refund ki guarantee deta hai."
            )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Hinglish" if data=="terms" else "English", callback_data="hinglish_terms" if data=="terms" else "terms"), InlineKeyboardButton("Back", callback_data="main_menu")],
            [InlineKeyboardButton("Report any Problem", callback_data="report_problem")]
        ])
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)

    elif data == "report_problem":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data="report_continue"), InlineKeyboardButton("Back", callback_data="terms")]])
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Notice: You can send 1 report per week. Please continue carefully.", reply_markup=keyboard)

    elif data == "report_continue":
        last_rep = user_records.get(user.id, {}).get("last_report", 0.0)
        if time.time() - last_rep < 604800:
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="terms")]])
            await context.bot.send_message(chat_id=chat_id, text="❌ You have already submitted a report this week. Try again later.", reply_markup=kb)
            return
            
        context.user_data["state"] = "WAITING_VOICE_REPORT"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="terms")]])
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text="Send a 30-Second Voice Note explaining your issue:", reply_markup=kb)

    elif data == "start_main":
        trials_left = user_records.get(user.id, {}).get("trial", 0)
        try: await query.message.delete()
        except: pass

        if trials_left > 0:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial_eng"), InlineKeyboardButton("Direct Start", callback_data="direct_start")]])
            await context.bot.send_message(chat_id=chat_id, text=f"You have {trials_left} Free Discount link(s) left.\nUse them carefully ⚠️", reply_markup=keyboard)
        else:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase Discount", callback_data="purchase_menu")]])
            await context.bot.send_message(chat_id=chat_id, text="You have used all your free discount links.", reply_markup=keyboard)

    elif data == "purchase_menu":
        try: await query.message.delete()
        except: pass
        
        buttons = [
            [InlineKeyboardButton("1 Discount link (500 ⭐️)", callback_data="buy_pack_1")],
            [InlineKeyboardButton("2 Discount links (999 ⭐️)", callback_data="buy_pack_2")],
            [InlineKeyboardButton("4 Discount links (1400 ⭐️)", callback_data="buy_pack_4")],
            [InlineKeyboardButton("8 Discount links (3000 ⭐️)", callback_data="buy_pack_8")],
            [InlineKeyboardButton("Enter Referral Code", callback_data="enter_referral")],
            [InlineKeyboardButton("Back", callback_data="start_main")]
        ]
        
        text = ("🛒 <b>Discount Store</b>\n\n"
                "Purchase Discount links using Telegram Stars!\n\n"
                "💡 <b>Referral Program:</b>\n"
                "Buy the 8 Discount links pack to unlock your own Referral Code! When your friends use it, they get 1 free link, and when they buy a pack, you get 1 free link as a gift!")
        
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "enter_referral":
        context.user_data["state"] = "WAITING_REFERRAL_CODE"
        try: await query.message.delete()
        except: pass
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="purchase_menu")]])
        await context.bot.send_message(chat_id=chat_id, text="Please send the Referral Code you received:", reply_markup=kb)

    elif data.startswith("buy_pack_"):
        try: await query.message.delete()
        except: pass
        title, description, payload, price_amount = "", "", "", 0
        if data == "buy_pack_1":
            title, description, payload, price_amount = "1 Discount link", "Get 1 Free Discount link", "buy_pack_1", 500
        elif data == "buy_pack_2":
            title, description, payload, price_amount = "2 Discount links", "Get 2 Free Discount links", "buy_pack_2", 999
        elif data == "buy_pack_4":
            title, description, payload, price_amount = "4 Discount links", "Get 4 Free Discount links", "buy_pack_4", 1400
        elif data == "buy_pack_8":
            title, description, payload, price_amount = "8 Discount links", "Get 8 Free Discount links + Unlocks Referral Code", "buy_pack_8", 3000
        prices = [LabeledPrice(title, price_amount)]
        await context.bot.send_invoice(chat_id=chat_id, title=title, description=description, payload=payload, provider_token="", currency="XTR", prices=prices)

    # -- TUTORIAL FLOW --
    elif data in ["tutorial_eng", "tutorial_hin"]:
        tag = "EnglishTutorial" if data == "tutorial_eng" else "HindiTutorial"
        other_btn = "Hindi Tutorial" if data == "tutorial_eng" else "English Tutorial"
        other_call = "tutorial_hin" if data == "tutorial_eng" else "tutorial_eng"
        
        # Decide back destination
        back_dest = "resend_qualified_msg" if context.user_data.get("is_in_ready_flow") else "direct_start"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(other_btn, callback_data=other_call)],
            [InlineKeyboardButton("Back", callback_data=back_dest)]
        ])
        try: await query.message.delete()
        except: pass
        await send_dynamic_media(context, chat_id, tag, caption="Here is the tutorial:", reply_markup=kb)

    elif data == "direct_start":
        context.user_data["is_in_ready_flow"] = False
        trials_left = user_records.get(user.id, {}).get("trial", 0)
        if trials_left <= 0:
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase Discount", callback_data="purchase_menu")]])
            await context.bot.send_message(chat_id=chat_id, text="❌ You have 0 Free Discount links remaining.", reply_markup=kb)
            return

        context.user_data["state"] = "WAITING_FLIPKART_LINK"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial_eng")]])
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
        await context.bot.send_message(chat_id=chat_id, text="Turn on bot notification. We will send you the best discount within a few minutes.\nThank you for using X DISCOUNT.")

        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        admin_message = (
            f"1. <b><code>{user.id}</code></b>\n"
            f"2. {full_name}\n"
            f"3. {context.user_data.get('product_link')}\n"
            f"4. Mobile: {context.user_data.get('mobile_num')}"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"), InlineKeyboardButton("Reject", callback_data=f"adm_reject_{user.id}")]])
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

    # -- SPECIAL OFFER BUTTON --
    elif data == "sp_offer_grab":
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text="Turn on bot notification. We will send you the Discount Redirect.\nThank you for using X DISCOUNT.")
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        admin_message = f"🎁 <b>[Special Offer]</b>\n1. <b><code>{user.id}</code></b>\n2. {full_name}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"), InlineKeyboardButton("Reject", callback_data=f"adm_sp_reject_{user.id}")]])
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

    # -- ADMIN REVIEW CALLS --
    elif data.startswith("adm_reject_"):
        target_id = int(data.split("adm_reject_")[1])
        await context.bot.send_message(chat_id=target_id, text="Your Link is not valid. You wasted your 1 discount link.")
        await query.message.edit_text(f"❌ Rejected User {target_id} (Invalid Link)")

    elif data.startswith("adm_sp_reject_"):
        target_id = int(data.split("adm_sp_reject_")[1])
        await context.bot.send_message(chat_id=target_id, text="You are late, the offer was grabbed by someone else.")
        await query.message.edit_text(f"❌ Special Offer Rejected for User {target_id}")

    elif data.startswith("adm_accept_"):
        target_id = int(data.split("adm_accept_")[1])
        # Start Session silently.
        admin_sessions[ADMIN_ID] = {"target_user_id": target_id, "step": "WAITING_HYPER_LINK", "data": {}}
        await query.message.edit_text(f"✅ Accepted User {target_id}.\nPlease send the Hyper Link:")

    # -- POST-APPROVAL WORKFLOW FOR USER --
    elif data == "resend_qualified_msg":
        try: await query.message.delete()
        except: pass
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Continue", callback_data="user_continue_ready"), InlineKeyboardButton("Tutorial", callback_data="tutorial_eng")]
        ])
        msg_text = "🎉 <b>Congratulations!</b>\nYour link is qualified for a discount."
        await send_dynamic_media(context, chat_id, "Ready", msg_text, kb)

    elif data == "user_continue_ready":
        try: await query.message.delete()
        except: pass
        d_data = context.user_data.get("final_discount_data", {})
        if not d_data:
            await context.bot.send_message(chat_id=chat_id, text="Data fetch error. Please contact support.")
            return

        text = (f"🎉 You got <b>{d_data.get('discount')}</b> on <b>{d_data.get('product_name')}</b>.\n"
                f"You can purchase this product for <b>{d_data.get('final_price')}</b>.")
        
        url = d_data.get('hyper_link', 'https://flipkart.com')
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔴 Buy Now 🔴", url=url)]])
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb)
        context.user_data["is_in_ready_flow"] = False


# ---------------- TEXT & MEDIA HANDLER ---------------- #
async def media_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    user_id = update.effective_user.id
    user_records = context.bot_data.get("user_records", {})
    state = context.user_data.get("state")
    text = update.message.text.strip() if update.message.text else update.message.caption.strip() if update.message.caption else ""
    
    if state == "WAITING_REFERRAL_CODE":
        if text.startswith("/"):
            context.user_data["state"] = None
            return 

        code = text.upper()
        current_rec = user_records.get(user_id, {})
        
        # Secret Promo Code
        if code == "ADMINREFFER009":
            new_trials = current_rec.get("trial", 0) + 9
            await sync_user_to_channel(context, user_id, current_rec.get("status", "Active"), new_trials, current_rec.get("last_report", 0.0), current_rec.get("refer_code", "None"), current_rec.get("refer_from", "None"), current_rec.get("reward_given", "False"))
            context.user_data["state"] = None
            await update.message.reply_text("✅ Secret Promo Code Accepted! You have received 9 Free Discount links.")
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
        await update.message.reply_text("✅ Referral Code accepted! You have received 1 Free Discount link.")
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
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="terms")]])
        await update.message.reply_text("Within 24 hours, our team member will contact you.", reply_markup=kb)
        context.user_data["state"] = None
        return

    # --- ADMIN WORKFLOW ENGINE ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_id = session.get("target_user_id")

        if step == "WAITING_ANNOUNCEMENT":
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

        if step == "WAITING_HYPER_LINK":
            session["data"]["hyper_link"] = text
            session["step"] = "WAITING_DISCOUNT"
            await update.message.reply_text("Send Discount amount/percentage (e.g. 50%):")
            return
        elif step == "WAITING_DISCOUNT":
            session["data"]["discount"] = text
            session["step"] = "WAITING_PROD_NAME"
            await update.message.reply_text("Send Product Name:")
            return
        elif step == "WAITING_PROD_NAME":
            session["data"]["product_name"] = text
            session["step"] = "WAITING_PRICE"
            await update.message.reply_text("Send Final Price:")
            return
        elif step == "WAITING_PRICE":
            data = session["data"]
            del admin_sessions[user_id]
            
            # Format price beautifully
            final_price_fmt = format_inr(text)
            
            # Save final securely in user data cache
            target_data = context.application.user_data.setdefault(target_id, {})
            target_data["final_discount_data"] = {
                "hyper_link": data["hyper_link"],
                "discount": data["discount"],
                "product_name": data["product_name"],
                "final_price": final_price_fmt
            }
            target_data["is_in_ready_flow"] = True
            
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("Continue", callback_data="user_continue_ready"), InlineKeyboardButton("Tutorial", callback_data="tutorial_eng")]
            ])
            msg_text = "🎉 <b>Congratulations!</b>\nYour link is qualified for a discount."
            
            try:
                # Send the "Ready" message to the user instantly
                await send_dynamic_media(context, target_id, "Ready", msg_text, kb)
                # Ensure the Admin is always replied to
                await update.message.reply_text(f"✅ Setup Completed! Qualified message successfully sent to User {target_id}.")
            except Exception as e:
                # Absolute safety net to ensure Admin never gets stuck
                await update.message.reply_text(f"✅ Setup Completed in memory, but ❌ Failed to notify User {target_id}. They might have blocked the bot or chat is missing. Error: {e}")
                
            return

    # --- REGULAR USER WORKFLOWS ---
    if state == "WAITING_FLIPKART_LINK" and text:
        if is_valid_flipkart_link(text):
            context.user_data["product_link"] = text
            context.user_data["state"] = "WAITING_MOBILE_NUMBER"
            
            msg_text = ("Send your Flipkart Account Number +91 XXXXXXXXXX.\n\n"
                        "⚠️ We have an authentic server, so we do not require an OTP or Verification code.\n"
                        "⚠️ Do not share your OTP or Email with anybody.")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial_eng")]])
            
            await send_dynamic_media(context, update.message.chat_id, "AccountNumber", msg_text, kb)
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
            conf_text = (
                f"{full_name}, you have {trials} discount link(s) left. "
                "If you continue, we will generate a discounted link, and 1 link will be deducted.\n\n"
                f"Link: {context.user_data['product_link']}\n"
                f"Number: +91 {mobile_num}"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Edit", callback_data="edit_details"), InlineKeyboardButton("Continue", callback_data="continue_submit")]])
            await update.message.reply_text(conf_text, reply_markup=kb, disable_web_page_preview=True)
        else:
            await update.message.reply_text("❌ Please enter a valid 10-digit mobile number.")


# ---------------- MAIN APPLICATION ---------------- #
def main():
    if not BOT_TOKEN:
        print("WARNING: TELEGRAM_TOKEN environment variable is missing!")
        return

    Thread(target=run_flask, daemon=True).start()

    persistence = PicklePersistence(filepath="bot_state.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("Go", go_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, media_and_text_handler))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_db_sync_handler))

    print("Bot is running 24/7 with Channel Backend Database & Telegram Stars...")
    app.run_polling()

if __name__ == "__main__":
    main()
