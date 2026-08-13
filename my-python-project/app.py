import os
import re
import urllib.parse
import pytz
from datetime import datetime
from threading import Thread
from flask import Flask

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

# Configuration
ADMIN_ID = 86919346
LOGO_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Crypto Payment Details
BTC_ADDRESS = "bc1qyllk67nznsds8rhwe0qkc7msleu72g3pfdwa7c"
TRUST_WALLET_LINK = f"https://link.trustwallet.com/send?coin=0&address={BTC_ADDRESS}&amount=0.00095"

QR_CODE_API_URL = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(TRUST_WALLET_LINK)}"

# Global memory for admin current active workflow
admin_sessions = {}

# --- Dummy Flask Web Server to keep Cloud Hosting happy ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "X Discount Bot is Running Successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# ---------------- HELPER FUNCTIONS ---------------- #
def is_server_open() -> bool:
    """Check if current Kolkata (IST) time is between 4:00 PM and 8:00 PM."""
    kolkata_tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(kolkata_tz)
    return 16 <= now.hour < 20

def is_valid_flipkart_link(text: str) -> bool:
    pattern = r"https?://(?:www\.)?(?:flipkart\.com|fkrt\.cc|flipkart\.page\.link)/\S+"
    return bool(re.search(pattern, text, re.IGNORECASE))

def parse_datetime(dt_str: str):
    """Parse custom date strings like '15/08/26 10AM' or '15/08/2026 5:30PM'"""
    dt_str = " ".join(dt_str.split()).upper()
    formats = [
        "%d/%m/%y %I%p", "%d/%m/%Y %I%p", 
        "%d/%m/%y %I:%M%p", "%d/%m/%Y %I:%M%p"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None

def track_and_check_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Tracks users globally. Returns True if user is BLOCKED, False otherwise."""
    user_id = update.effective_user.id
    
    if "all_users" not in context.bot_data:
        context.bot_data["all_users"] = set()
    context.bot_data["all_users"].add(user_id)
    
    if user_id in context.bot_data.get("blocked_users", set()) and user_id != ADMIN_ID:
        return True
    return False


# ---------------- LIVE COUNTDOWN JOB ---------------- #
async def update_countdown_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    end_time = job.data["end_time"]
    sale_name = job.data["name"]
    msg_id = job.data["msg_id"]
    chat_id = job.chat_id
    
    now = datetime.now()
    if now >= end_time:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=f"🚨 <b>Countdown Finished!</b>\nSale '{sale_name}' has ended.", parse_mode="HTML"
            )
        except Exception:
            pass
        job.schedule_removal()
        return
        
    diff = end_time - now
    hours, rem = divmod(diff.seconds, 3600)
    mins, secs = divmod(rem, 60)
    time_str = (f"{diff.days}d " if diff.days > 0 else "") + f"{hours}h {mins}m {secs}s"
    
    text = f"⏳ <b>Live Countdown: {sale_name}</b>\n\nEnds in: <b>{time_str}</b>"
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="HTML")
    except Exception:
        pass


# ---------------- COMMAND HANDLERS ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if track_and_check_user(update, context): return
    
    user = update.effective_user
    context.user_data["state"] = None
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    welcome_text = f"Hello ! {full_name}\nThis is X DISCOUNT ⚔️"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Who are we", callback_data="who_are_we")]])
    await update.message.reply_text(welcome_text, reply_markup=keyboard)


async def go_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    kb = [
        [InlineKeyboardButton("Announcement", callback_data="adm_menu_announcement")],
        [InlineKeyboardButton("End Sale", callback_data="adm_menu_endsale")],
        [InlineKeyboardButton("Special Offer", callback_data="adm_menu_spoffer")],
        [InlineKeyboardButton("End", callback_data="adm_menu_end")],
        [InlineKeyboardButton("Close", callback_data="adm_menu_close")]
    ]
    await update.message.reply_text("👑 <b>Admin Dashboard</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))


# ---------------- CALLBACK QUERY HANDLER ---------------- #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if track_and_check_user(update, context): return
    
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # -- ADMIN /GO MENU --
    if data == "adm_menu_announcement":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_ANNOUNCEMENT"}
        await query.message.edit_text("Write Announcement Message (You can attach image or video):")
        
    elif data == "adm_menu_endsale":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_SALE_DATE", "data": {}}
        await query.message.edit_text("Send date and time in this format: dd/mm/yy 1-12Am/Pm\nExample: <code>15/08/26 5PM</code>", parse_mode="HTML")
        
    elif data == "adm_menu_spoffer":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_SPO_LINK", "data": {}}
        await query.message.edit_text("Send Flipkart Link:")
        
    elif data == "adm_menu_end":
        kb = [[InlineKeyboardButton("User", callback_data="adm_menu_end_user"), InlineKeyboardButton("All", callback_data="adm_menu_end_all")]]
        await query.message.edit_text("Block a specific User or All Users?", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data == "adm_menu_end_user":
        admin_sessions[ADMIN_ID] = {"step": "WAITING_BLOCK_USER_ID"}
        await query.message.edit_text("Send User ID to block:")
        
    elif data == "adm_menu_end_all":
        kb = [[InlineKeyboardButton("Confirm Block All", callback_data="adm_menu_end_all_confirm")]]
        await query.message.edit_text("Are you sure you want to block ALL users?", reply_markup=InlineKeyboardMarkup(kb))
        
    elif data == "adm_menu_end_all_confirm":
        context.bot_data["blocked_users"] = set(context.bot_data.get("all_users", set()))
        if ADMIN_ID in context.bot_data["blocked_users"]:
            context.bot_data["blocked_users"].remove(ADMIN_ID)
        await query.message.edit_text("✅ All users have been permanently blocked.")
        
    elif data == "adm_menu_close":
        try: await query.message.delete()
        except Exception: pass

    # -- REGULAR FLOWS --
    elif data == "who_are_we":
        try: await query.message.delete()
        except Exception: pass

        about_text = (
            "X DISCOUNT is a Dumping server of failed discounts from big sales like\n"
            "1. <b><i>BIG BILLION DAY</i></b>\n2. <b><i>GOAT SALE</i></b>\n"
            "3. <b><i>BIG DIWALI SALE</i></b>\n4. <b><i>FLIPCART BLACK FRIDAY SALE</i></b>.\n"
            "so when the sale is live there is too much load on server that's why "
            "the discount failed and discount session tokens comes to our server.\n"
            "Our Server Avalable on 4pm-8pm only"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Get Discount", callback_data="get_discount")]])
        await context.bot.send_photo(chat_id=query.message.chat_id, photo=LOGO_URL, caption=about_text, parse_mode="HTML", reply_markup=keyboard)

    elif data == "get_discount":
        if not is_server_open():
            await context.bot.send_message(chat_id=query.message.chat_id, text="Server Shut Down We will Notify you When it Will avalable between 4pm-8pm")
            return

        text = "This service is not free the service charge $50/DISCOUNT.\nFree Trial Avalable 2 per telegram accouunt."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Free discount", callback_data="free_discount"), InlineKeyboardButton("Buy Discount", callback_data="buy_discount")]
        ])
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_message(chat_id=query.message.chat_id, text=text, reply_markup=keyboard)

    elif data == "free_discount":
        context.user_data["state"] = "AWAITING_LINK"
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_message(chat_id=query.message.chat_id, text="Send Your Flipcart Product Link")

    elif data == "buy_discount":
        # Keep Crypto wallet just in case
        payment_caption = (
            "💰 <b>BUY DISCOUNT - PAYMENT DETAILS</b>\n\n"
            f"<b>My Public Address to Receive BTC:</b>\n<code>{BTC_ADDRESS}</code>\n\n"
            f"<b>Pay me via Trust Wallet:</b>\n{TRUST_WALLET_LINK}\n\n"
            "<i>Scan the QR code above or use the details to complete your payment ($50).</i>"
        )
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_photo(chat_id=query.message.chat_id, photo=QR_CODE_API_URL, caption=payment_caption, parse_mode="HTML")

    elif data.startswith("pay_"):
        method = data.replace("pay_", "")
        context.user_data["selected_method"] = method
        link = context.user_data.get("product_link", "N/A")
        
        confirm_text = f"Link: {link}\nSelected Method: {method}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Confirm", callback_data="confirm_order")]])
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_message(chat_id=query.message.chat_id, text=confirm_text, reply_markup=keyboard)

    elif data == "confirm_order":
        try: await query.message.delete()
        except Exception: pass
            
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Turn on bot notification we will send you the best discount under Few Minutes .\nThanks to use X DISCOUNT."
        )

        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        admin_message = (
            f"1. <b><code>{user.id}</code></b>\n"
            f"2. {full_name}\n"
            f"3. {context.user_data.get('product_link')} | {context.user_data.get('selected_method')}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"), InlineKeyboardButton("Reject", callback_data=f"adm_reject_{user.id}")]
        ])
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

    # -- SPECIAL OFFER BUTTON --
    elif data == "sp_offer_grab":
        try: await query.message.delete()
        except Exception: pass
            
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Turn on bot notification we will send you the Discount Redirect\nThanks to use X DISCOUNT."
        )

        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        admin_message = (
            f"🎁 <b>[Special Offer]</b>\n"
            f"1. <b><code>{user.id}</code></b>\n"
            f"2. {full_name}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"), InlineKeyboardButton("Reject", callback_data=f"adm_sp_reject_{user.id}")]
        ])
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

    # -- ADMIN REVIEW CALLS --
    elif data.startswith("adm_reject_"):
        target_user_id = int(data.split("adm_reject_")[1])
        await context.bot.send_message(chat_id=target_user_id, text="Free Service is Expired For You try bot on new telegram")
        await query.message.edit_text(f"❌ Rejected User {target_user_id}")

    elif data.startswith("adm_sp_reject_"):
        target_user_id = int(data.split("adm_sp_reject_")[1])
        await context.bot.send_message(chat_id=target_user_id, text="You are so late the offer grabed by someone")
        await query.message.edit_text(f"❌ Special Offer Rejected for User {target_user_id}")

    elif data.startswith("adm_accept_"):
        target_user_id = int(data.split("adm_accept_")[1])
        admin_sessions[ADMIN_ID] = {"target_user_id": target_user_id, "step": "WAITING_HYPER_LINK", "data": {}}
        await query.message.edit_text(f"✅ Accepted User {target_user_id}.\nPlease send the Hyper Link:")

    # -- PURCHASE WORKFLOW STEPS --
    elif data.startswith("purchase_start_"):
        try: await query.message.delete()
        except Exception: pass
        await context.bot.send_message(
            chat_id=query.message.chat_id, text="1. Open Flipcart app.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_2")]])
        )
    elif data == "p_step_2":
        user_link = context.user_data.get("product_link", "your saved link")
        await query.message.edit_text(
            f"2. Select this product: {user_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_3")]])
        )
    elif data == "p_step_3":
        await query.message.edit_text(
            "3. Tap on Buy Now", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_4")]])
        )
    elif data == "p_step_4":
        discount = context.user_data.get("admin_discount", "Discount")
        await query.message.edit_text(
            f"4. Apply {discount} Discount now", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_5")]])
        )
    elif data == "p_step_5":
        hyper_link = context.user_data.get("admin_hyper_link", "https://flipkart.com")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Apply Discount 🚨", url=hyper_link)]])
        await query.message.edit_text("5. Final Step: Click below to apply discount directly!", reply_markup=keyboard)


# ---------------- TEXT & MEDIA HANDLER ---------------- #
async def media_and_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if track_and_check_user(update, context): return
    
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else update.message.caption.strip() if update.message.caption else ""

    # --- ADMIN WORKFLOW ENGINE ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_user_id = session.get("target_user_id")

        if step == "WAITING_ANNOUNCEMENT":
            users = context.bot_data.get("all_users", set())
            sent = 0
            for uid in users:
                if uid == ADMIN_ID: continue
                try:
                    await update.message.copy(chat_id=uid)
                    sent += 1
                except Exception:
                    pass
            await update.message.reply_text(f"✅ Announcement Broadcasted to {sent} users.")
            del admin_sessions[user_id]
            return

        elif step == "WAITING_SALE_DATE":
            parsed = parse_datetime(text)
            if not parsed:
                await update.message.reply_text("❌ Invalid format. Please use format like '15/08/26 10AM' or '15/08/26 5:30PM'. Try again:")
                return
            if parsed <= datetime.now():
                await update.message.reply_text("❌ That time is in the past! Please enter a future date/time:")
                return
            session["data"]["end_time"] = parsed
            session["step"] = "WAITING_SALE_NAME"
            await update.message.reply_text("Send the End Sale Name:")
            return

        elif step == "WAITING_SALE_NAME":
            sale_name = text
            end_time = session["data"]["end_time"]
            del admin_sessions[user_id]
            
            # Start UI countdown msg for Admin
            msg = await update.message.reply_text(f"⏳ Starting countdown for '{sale_name}'...")
            context.job_queue.run_repeating(
                update_countdown_message, interval=10, first=1,
                data={"msg_id": msg.message_id, "end_time": end_time, "name": sale_name},
                chat_id=user_id, name=f"countdown_{msg.message_id}"
            )
            
            # Broadcast general awareness to all users
            users = context.bot_data.get("all_users", set())
            for uid in users:
                if uid == ADMIN_ID: continue
                try:
                    await context.bot.send_message(
                        chat_id=uid, text=f"🚨 <b>{sale_name}</b> is ending soon!\nMark your calendars for {end_time.strftime('%d/%m/%Y %I:%M %p')}.", parse_mode="HTML"
                    )
                except Exception: pass
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
            link = session["data"]["spo_link"]
            name = session["data"]["spo_name"]
            cprice = session["data"]["spo_cprice"]
            disc = session["data"]["spo_disc"]
            del admin_sessions[user_id]
            
            offer_text = f"{link}\n<b>{name}</b>\n<s>{cprice}</s> - {disc} = <b>{oprice}</b>"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Get Offer Now", callback_data="sp_offer_grab")]])
            
            users = context.bot_data.get("all_users", set())
            sent = 0
            for uid in users:
                if uid == ADMIN_ID: continue
                try:
                    await context.bot.send_message(chat_id=uid, text=offer_text, parse_mode="HTML", reply_markup=kb)
                    sent += 1
                except Exception: pass
            await update.message.reply_text(f"✅ Special offer broadcasted to {sent} users.")
            return

        elif step == "WAITING_BLOCK_USER_ID":
            try:
                target_id = int(text)
                if "blocked_users" not in context.bot_data:
                    context.bot_data["blocked_users"] = set()
                context.bot_data["blocked_users"].add(target_id)
                await update.message.reply_text(f"✅ User {target_id} has been blocked.\n*(Note: Telegram API does not allow bots to delete chat history on user devices, but they are now permanently banned from interacting)*.")
            except ValueError:
                await update.message.reply_text("❌ Invalid User ID. Must be a number.")
            del admin_sessions[user_id]
            return

        # ADMIN ACCEPT FLOW
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
            session["data"]["final_price"] = text

            data = session["data"]
            hyper_link = data["hyper_link"]
            discount = data["discount"]
            prod_name = data["product_name"]
            final_price = data["final_price"]
            del admin_sessions[user_id]

            if target_user_id not in context.application.user_data:
                context.application.user_data[target_user_id] = {}
            target_user_data = context.application.user_data[target_user_id]
            target_user_data["admin_hyper_link"] = hyper_link
            target_user_data["admin_discount"] = discount
            
            try:
                target_chat = await context.bot.get_chat(target_user_id)
                user_full = f"{target_chat.first_name} {target_chat.last_name or ''}".strip()
            except Exception:
                user_full = "User"

            user_msg = (
                f"Hi {user_full}\n"
                f"You got {discount} on {prod_name}.\n"
                f"You can purchase {prod_name} in {final_price} From your Flipcart account."
            )
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Purchase", callback_data=f"purchase_start_{target_user_id}")]])

            await context.bot.send_photo(chat_id=target_user_id, photo=LOGO_URL, caption=user_msg, reply_markup=keyboard)
            await update.message.reply_text(f"✅ Setup Completed! Notification sent to User {target_user_id}.")
            return

    # --- REGULAR USER LINK SUBMISSION ---
    if context.user_data.get("state") == "AWAITING_LINK" and text:
        if is_valid_flipkart_link(text):
            match = re.search(r"https?://\S+", text)
            clean_link = match.group(0) if match else text
            context.user_data["product_link"] = clean_link
            context.user_data["state"] = None

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Upi", callback_data="pay_Upi"), InlineKeyboardButton("Credit Card", callback_data="pay_Credit Card"), InlineKeyboardButton("Net Banking", callback_data="pay_Net Banking")]
            ])
            await update.message.reply_text("Which Payment method you use mainly on Flipcart and want discount on", reply_markup=keyboard)
        else:
            await update.message.reply_text("please send correct link")


# ---------------- MAIN APPLICATION ---------------- #
def main():
    if not BOT_TOKEN:
        print("WARNING: TELEGRAM_TOKEN environment variable is missing!")
        return

    # Start Flask Webserver in separate background thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    persistence = PicklePersistence(filepath="bot_state.pkl")

    # job_queue needs to be explicitly enabled in newer versions
    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("Go", go_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Listen to both text and media (Photos, videos) for broadcasts
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, media_and_text_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
