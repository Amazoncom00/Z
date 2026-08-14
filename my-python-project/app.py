import os
import re
import urllib.parse
import asyncio
import time
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

# ---------------- DATABASE (CHANNEL) HELPERS ---------------- #
async def sync_user_to_channel(context: ContextTypes.DEFAULT_TYPE, user_id: int, status: str, trial: int, last_report: float = 0.0, refer_code: str = "None", refer_from: str = "None"):
    """Writes or edits the user's data in the Telegram Channel."""
    user_records = context.bot_data.setdefault("user_records", {})
    text = (f"Userid: {user_id}\nStatus: {status}\nTrial: {trial}\n"
            f"LastReport: {last_report}\nReferCode: {refer_code}\nReferFrom: {refer_from}")
    
    if user_id in user_records and "msg_id" in user_records[user_id]:
        msg_id = user_records[user_id]["msg_id"]
        try:
            await context.bot.edit_message_text(chat_id=DB_CHANNEL_ID, message_id=msg_id, text=text)
        except Exception:
            pass 
        user_records[user_id] = {"msg_id": msg_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from}
    else:
        try:
            msg = await context.bot.send_message(chat_id=DB_CHANNEL_ID, text=text)
            user_records[user_id] = {"msg_id": msg.message_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from}
        except Exception as e:
            print(f"Failed to post to DB Channel: {e}")

async def track_and_check_user(update: Update, context: ContextTypes.DEFAULT_TYPE, ref_code: str = None) -> bool:
    """Checks if a user is valid. Creates a DB entry for new users. Returns True if BLOCKED."""
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return False
        
    user_records = context.bot_data.setdefault("user_records", {})
    
    # If New User, add them to Database Channel
    if user_id not in user_records:
        start_trial = 0
        refer_from = "None"
        
        # Process Referral Code
        if ref_code:
            for uid, rec in user_records.items():
                if rec.get("refer_code") == ref_code and rec.get("refer_code") != "None":
                    start_trial = 2
                    refer_from = str(uid)
                    break
                    
        await sync_user_to_channel(context, user_id, "Active", start_trial, 0.0, "None", refer_from)
        return False
        
    # Check if Blocked
    if user_records[user_id].get("status", "Active").lower() == "blocked":
        return True
        
    return False

# ---------------- CHANNEL 2-WAY SYNC HANDLER ---------------- #
async def channel_db_sync_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listens for Admin manual edits inside the Database channel and media tags."""
    post = update.channel_post or update.edited_channel_post
    if not post or post.chat_id != DB_CHANNEL_ID:
        return

    # Cache Media based on tags and detect type dynamically
    caption = post.caption or post.text or ""
    tags = ["Logo", "TutorialVideo", "ProductLink", "AccountNumber"]
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

    # Sync User Edits: Extract format
    if post.text:
        match = re.search(r"Userid:\s*(\d+)\s*Status:\s*(\w+)\s*Trial:\s*(\d+)(?:\s*LastReport:\s*([\d\.]+))?(?:\s*ReferCode:\s*(\w+))?(?:\s*ReferFrom:\s*([\w]+))?", post.text, re.IGNORECASE)
        if match:
            user_id = int(match.group(1))
            status = match.group(2).capitalize()
            trial = int(match.group(3))
            last_report = float(match.group(4)) if match.group(4) else 0.0
            refer_code = match.group(5) if match.group(5) else "None"
            refer_from = match.group(6) if match.group(6) else "None"
            
            user_records = context.bot_data.setdefault("user_records", {})
            user_records[user_id] = {"msg_id": post.message_id, "status": status, "trial": trial, "last_report": last_report, "refer_code": refer_code, "refer_from": refer_from}

# ---------------- DYNAMIC MEDIA SENDER ---------------- #
async def send_dynamic_media(context, chat_id, tag, caption=None, reply_markup=None):
    file_id = context.bot_data.get(f"media_{tag}")
    file_type = context.bot_data.get(f"media_{tag}_type")
    
    if not file_id:
        if tag == "Logo":
            await context.bot.send_photo(chat_id=chat_id, photo=LOGO_URL_FALLBACK, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"[Attachment {tag} not set]\n{caption}", reply_markup=reply_markup, parse_mode="HTML")
        return

    if file_type == "photo":
        await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    elif file_type == "video":
        await context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    elif file_type == "document":
        await context.bot.send_document(chat_id=chat_id, document=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")

# ---------------- HELPERS ---------------- #
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
    args = context.args
    ref_code = args[0] if args else None
    
    if await track_and_check_user(update, context, ref_code): return
    
    user = update.effective_user
    context.user_data["state"] = None
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    welcome_text = f"Hello <b>{full_name}</b> 👋🏻\nWelcome To @XDiscount_bot"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("About us", callback_data="about_us"), InlineKeyboardButton("Terms", callback_data="terms")],
        [InlineKeyboardButton("🍁Start", callback_data="start_main")]
    ])
    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=keyboard)

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    try:
        target_id = int(context.args[0])
        user_records = context.bot_data.get("user_records", {})
        if target_id in user_records:
            rec = user_records[target_id]
            await sync_user_to_channel(context, target_id, "Active", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"))
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
    """Answers the PreCheckoutQuery for Telegram Stars"""
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles logic after user successfully pays via Telegram Stars"""
    user_id = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    user_records = context.bot_data.get("user_records", {})
    rec = user_records.get(user_id, {})
    
    trials = rec.get("trial", 0)
    status = rec.get("status", "Active")
    last_rep = rec.get("last_report", 0.0)
    refer_code = rec.get("refer_code", "None")
    refer_from = rec.get("refer_from", "None")

    reward_referrer = False

    if payload == "buy_1_discount":
        trials += 1
        await update.message.reply_text("🎉 Payment Successful! You have received 1 Discount Coupon.")
        reward_referrer = True
    elif payload == "buy_3_discounts":
        trials += 3
        await update.message.reply_text("🎉 Payment Successful! You have received 3 Discount Coupons.")
        reward_referrer = True
    elif payload == "buy_ref_code":
        refer_code = f"REF{user_id}"
        ref_link = f"https://t.me/{context.bot.username}?start={refer_code}"
        await update.message.reply_text(f"🎉 Payment Successful! Your Referral Link is ready:\n\n{ref_link}\n\nShare this with friends! If they use it and make a purchase, you get 1 Free Discount Coupon!")

    await sync_user_to_channel(context, user_id, status, trials, last_rep, refer_code, refer_from)

    # Reward the referrer if a pack was bought
    if reward_referrer and refer_from != "None":
        try:
            ref_id = int(refer_from)
            ref_rec = user_records.get(ref_id)
            if ref_rec:
                r_trials = ref_rec.get("trial", 0) + 1
                await sync_user_to_channel(context, ref_id, ref_rec.get("status", "Active"), r_trials, ref_rec.get("last_report", 0.0), ref_rec.get("refer_code", "None"), ref_rec.get("refer_from", "None"))
                await context.bot.send_message(chat_id=ref_id, text="🎁 <b>Bonus!</b>\nSomeone you referred just made a purchase! You have been rewarded with +1 Free Discount Coupon!", parse_mode="HTML")
        except Exception:
            pass

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
                await sync_user_to_channel(context, u_id, "Blocked", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"))
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
            [InlineKeyboardButton("🍁Start", callback_data="start_main")]
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
            "However, if a payment fails despite the user providing a valid and correct mobile number, X Discount Guarantees a full refund for the transaction amount."
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
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Notice: You can send 1 report in a week. Please continue carefully.", reply_markup=keyboard)

    elif data == "report_continue":
        last_rep = user_records.get(user.id, {}).get("last_report", 0.0)
        if time.time() - last_rep < 604800: # 7 days
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
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial"), InlineKeyboardButton("Direct Start", callback_data="direct_start")]])
            await context.bot.send_message(chat_id=chat_id, text=f"You have {trials_left} Free Discount Coupon(s) left.\nUse them carefully ⚠️", reply_markup=keyboard)
        else:
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase Discount", callback_data="purchase_menu")]])
            await context.bot.send_message(chat_id=chat_id, text="You have used all your free discounts.", reply_markup=keyboard)

    elif data == "purchase_menu":
        try: await query.message.delete()
        except: pass
        
        refer_code = user_records.get(user.id, {}).get("refer_code", "None")
        
        buttons = [
            [InlineKeyboardButton("1 Discount (500 ⭐️)", callback_data="buy_pack_1")],
            [InlineKeyboardButton("3 Discounts (1000 ⭐️)", callback_data="buy_pack_3")]
        ]
        
        if refer_code == "None":
            buttons.append([InlineKeyboardButton("Generate Referral Code (500 ⭐️)", callback_data="buy_ref")])
            
        buttons.append([InlineKeyboardButton("Back", callback_data="start_main")])
        
        text = "Purchase Discount Coupons using Telegram Stars!\n\n<i>Note: Generating a Referral Code allows you to invite friends. When they purchase a discount pack, you earn a free discount automatically!</i>"
        
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("buy_pack_") or data == "buy_ref":
        try: await query.message.delete()
        except: pass
        
        title = ""
        description = ""
        payload = ""
        price_amount = 0
        
        if data == "buy_pack_1":
            title = "1 Discount Coupon"
            description = "Get 1 Free Discount Trial"
            payload = "buy_1_discount"
            price_amount = 500
        elif data == "buy_pack_3":
            title = "3 Discount Coupons"
            description = "Get 3 Free Discount Trials"
            payload = "buy_3_discounts"
            price_amount = 1000
        elif data == "buy_ref":
            title = "Referral Code Generator"
            description = "Generate your unique Referral Code to earn bonuses!"
            payload = "buy_ref_code"
            price_amount = 500

        prices = [LabeledPrice(title, price_amount)]
        
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            provider_token="", # Empty for Telegram Stars
            currency="XTR",
            prices=prices
        )

    elif data == "tutorial":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Direct Start", callback_data="direct_start")]])
        try: await query.message.delete()
        except: pass
        await send_dynamic_media(context, chat_id, "TutorialVideo", reply_markup=kb)

    elif data == "direct_start":
        trials_left = user_records.get(user.id, {}).get("trial", 0)
        if trials_left <= 0:
            try: await query.message.delete()
            except: pass
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase Discount", callback_data="purchase_menu")]])
            await context.bot.send_message(chat_id=chat_id, text="❌ You have 0 Free Trials remaining.", reply_markup=kb)
            return

        context.user_data["state"] = "WAITING_FLIPKART_LINK"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial")]])
        text = "Send Your Product Link, Product Must be Electronic and without Discount, Price must be ₹50,000."
        try: await query.message.delete()
        except: pass
        await send_dynamic_media(context, chat_id, "ProductLink", text, kb)

    elif data == "edit_details":
        # Loop back to link state
        context.user_data["state"] = "WAITING_FLIPKART_LINK"
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text="Send Your Product Link again:")

    elif data == "continue_submit":
        trials_left = user_records.get(user.id, {}).get("trial", 0)
        rec = user_records.get(user.id, {})
        
        # Deduct Trial
        new_trial_count = max(0, trials_left - 1)
        await sync_user_to_channel(context, user.id, rec.get("status", "Active"), new_trial_count, rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"))

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
        await context.bot.send_message(chat_id=target_id, text="Your Link is not valid. You wasted your 1 discount coupon.")
        await query.message.edit_text(f"❌ Rejected User {target_id} (Invalid Link)")

    elif data.startswith("adm_sp_reject_"):
        target_id = int(data.split("adm_sp_reject_")[1])
        await context.bot.send_message(chat_id=target_id, text="You are late, the offer was grabbed by someone else.")
        await query.message.edit_text(f"❌ Special Offer Rejected for User {target_id}")

    elif data.startswith("adm_accept_"):
        target_id = int(data.split("adm_accept_")[1])
        admin_sessions[ADMIN_ID] = {"target_user_id": target_id, "step": "WAITING_HYPER_LINK", "data": {}}
        await query.message.edit_text(f"✅ Accepted User {target_id}.\nPlease send the Hyper Link:")

    # -- PURCHASE WORKFLOW STEPS --
    elif data.startswith("purchase_start_"):
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(chat_id=chat_id, text="1. Open Flipkart app.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_2")]]))
    elif data == "p_step_2":
        await query.message.edit_text(f"2. Select this product: {context.user_data.get('product_link', 'your saved link')}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_3")]]))
    elif data == "p_step_3":
        await query.message.edit_text("3. Tap on Buy Now", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_4")]]))
    elif data == "p_step_4":
        await query.message.edit_text(f"4. Apply {context.user_data.get('admin_discount', 'Discount')} Discount now", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_5")]]))
    elif data == "p_step_5":
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Apply Discount 🚨", url=context.user_data.get("admin_hyper_link", "https://flipkart.com"))]])
        await query.message.edit_text("5. Final Step: Click below to apply the discount directly!", reply_markup=keyboard)


# ---------------- TEXT & MEDIA HANDLER ---------------- #
async def media_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await track_and_check_user(update, context): return
    
    user_id = update.effective_user.id
    user_records = context.bot_data.get("user_records", {})
    state = context.user_data.get("state")
    
    # Handle Voice Report Submissions
    if state == "WAITING_VOICE_REPORT":
        if not update.message.voice:
            await update.message.reply_text("❌ Please send a Voice Note.")
            return
        if update.message.voice.duration > 35:
            await update.message.reply_text("❌ Voice note must be around 30 seconds or less. Try again.")
            return
            
        # Update Report timestamp in DB
        rec = user_records.get(user_id, {})
        await sync_user_to_channel(context, user_id, rec.get("status", "Active"), rec.get("trial", 0), time.time(), rec.get("refer_code", "None"), rec.get("refer_from", "None"))
        
        # Forward to admin
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ <b>New Issue Report from <code>{user_id}</code></b>", parse_mode="HTML")
        await update.message.copy(chat_id=ADMIN_ID)
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="terms")]])
        await update.message.reply_text("Within 24 hours, our team member will contact you.", reply_markup=kb)
        context.user_data["state"] = None
        return

    text = update.message.text.strip() if update.message.text else update.message.caption.strip() if update.message.caption else ""

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
                    await sync_user_to_channel(context, t_id, "Blocked", rec.get("trial", 0), rec.get("last_report", 0.0), rec.get("refer_code", "None"), rec.get("refer_from", "None"))
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
            if target_id not in context.application.user_data: context.application.user_data[target_id] = {}
            context.application.user_data[target_id]["admin_hyper_link"] = data["hyper_link"]
            context.application.user_data[target_id]["admin_discount"] = data["discount"]
            
            try:
                target_chat = await context.bot.get_chat(target_id)
                user_full = f"{target_chat.first_name} {target_chat.last_name or ''}".strip()
            except: user_full = "User"

            user_msg = f"Hi {user_full}\nYou got {data['discount']} on {data['product_name']}.\nYou can purchase {data['product_name']} for {text} from your Flipkart account."
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase", callback_data=f"purchase_start_{target_id}")]])

            await send_dynamic_media(context, target_id, "Logo", user_msg, keyboard)
            await update.message.reply_text(f"✅ Setup Completed! Notification sent to User {target_id}.")
            return

    # --- REGULAR USER WORKFLOWS ---
    if state == "WAITING_FLIPKART_LINK" and text:
        if is_valid_flipkart_link(text):
            context.user_data["product_link"] = text
            context.user_data["state"] = "WAITING_MOBILE_NUMBER"
            
            msg_text = ("Send your Flipkart Account Number +91 XXXXXXXXXX.\n\n"
                        "⚠️ We have an authentic server, so we do not require an OTP or Verification code.\n"
                        "⚠️ Do not share your OTP or Email with anybody.")
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Tutorial", callback_data="tutorial")]])
            
            await send_dynamic_media(context, update.message.chat_id, "AccountNumber", msg_text, kb)
        else:
            await update.message.reply_text("❌ Invalid Link. Please send a valid Flipkart link.")

    elif state == "WAITING_MOBILE_NUMBER" and text:
        # Expect 10 digit number with or without +91
        number_only = re.sub(r'\D', '', text)
        if len(number_only) >= 10:
            mobile_num = number_only[-10:] # get last 10 digits
            context.user_data["mobile_num"] = mobile_num
            context.user_data["state"] = None
            
            trials = user_records.get(user_id, {}).get("trial", 0)
            full_name = f"{update.effective_user.first_name} {update.effective_user.last_name or ''}".strip()
            conf_text = (
                f"{full_name}, you have {trials} discount coupon(s) left. "
                "If you continue, we will generate a discounted link, and 1 coupon will be deducted.\n\n"
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

    # Keep alive for Heroku/Render
    Thread(target=run_flask, daemon=True).start()

    persistence = PicklePersistence(filepath="bot_state.pkl")
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    # Core Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("Go", go_command))
    app.add_handler(CommandHandler("unblock", unblock_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Telegram Stars Handlers
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # Text, Photos, Videos, Voice
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, media_and_text_handler))
    
    # 2-WAY DB SYNC: Listens to the Database channel for manual Admin edits and Media Tags
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_db_sync_handler))

    print("Bot is running 24/7 with Channel Backend Database & Telegram Stars...")
    app.run_polling()


if __name__ == "__main__":
    main()
