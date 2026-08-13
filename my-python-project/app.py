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
ADMIN_ID = 8844584255
LOGO_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Crypto Payment Details
BTC_ADDRESS = "bc1qyllk67nznsds8rhwe0qkc7msleu72g3pfdwa7c"
TRUST_WALLET_LINK = f"https://link.trustwallet.com/send?coin=0&address={BTC_ADDRESS}&amount=0.00095"

# Dynamically generate QR code image URL
QR_CODE_API_URL = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(TRUST_WALLET_LINK)}"

# Global memory for admin current active workflow
admin_sessions = {}

# --- Dummy Flask Web Server to keep Cloud Hosting happy with Web Port Requirements ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "X Discount Bot is Running Successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)

# -------------------------------------------------------------------------------------

def is_server_open() -> bool:
    """Check if current Kolkata (IST) time is between 1:00 AM and 12:00 AM."""
    kolkata_tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(kolkata_tz)
    return 1 <= now.hour < 24


def is_valid_flipkart_link(text: str) -> bool:
    """Extract and validate Flipkart URL from message text."""
    pattern = r"https?://(?:www\.)?(?:flipkart\.com|fkrt\.cc|flipkart\.page\.link)/\S+"
    return bool(re.search(pattern, text, re.IGNORECASE))


# ---------------- START COMMAND ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["state"] = None
    
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    welcome_text = (
        f"Hello ! {full_name}\n"
        f"This is X DISCOUNT ⚔️"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Who are we", callback_data="who_are_we")]]
    )

    await update.message.reply_text(welcome_text, reply_markup=keyboard)


# ---------------- CALLBACK QUERY HANDLER ---------------- #
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # 1. Who Are We
    if data == "who_are_we":
        try:
            await query.message.delete()
        except Exception:
            pass

        about_text = (
            "X DISCOUNT is a Dumping server of failed discounts from big sales like\n"
            "1. <b><i>BIG BILLION DAY</i></b>\n"
            "2. <b><i>GOAT SALE</i></b>\n"
            "3. <b><i>BIG DIWALI SALE</i></b>\n"
            "4. <b><i>FLIPCART BLACK FRIDAY SALE</i></b>.\n"
            "so when the sale is live there is too much load on server that's why "
            "the discount failed and discount session tokens comes to our server.\n"
            "Our Server Avalable on 4pm-8pm only"
        )

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Get Discount", callback_data="get_discount")]]
        )

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=LOGO_URL,
            caption=about_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    # 2. Get Discount (Time Check & Free/Buy Menu)
    elif data == "get_discount":
        if not is_server_open():
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Server Shut Down We will Notify you When it Will avalable between 4pm-8pm"
            )
            return

        text = (
            "This service is not free the service charge $50/DISCOUNT.\n"
            "Free Trial Avalable 2 per telegram accouunt."
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Free discount", callback_data="free_discount"),
                InlineKeyboardButton("Buy Discount", callback_data="buy_discount"),
            ]
        ])

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=text,
            reply_markup=keyboard
        )

    # 3. Free Discount Flow
    elif data == "free_discount":
        context.user_data["state"] = "AWAITING_LINK"
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Send Your Flipcart Product Link"
        )

    # 4. Buy Discount Flow (Retained if you want them to pay BTC in future)
    elif data == "buy_discount":
        payment_caption = (
            "💰 <b>BUY DISCOUNT - PAYMENT DETAILS</b>\n\n"
            f"<b>My Public Address to Receive BTC:</b>\n<code>{BTC_ADDRESS}</code>\n\n"
            f"<b>Pay me via Trust Wallet:</b>\n{TRUST_WALLET_LINK}\n\n"
            "<i>Scan the QR code above or use the details to complete your payment ($50).</i>"
        )

        try:
            await query.message.delete()
        except Exception:
            pass

        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=QR_CODE_API_URL,
            caption=payment_caption,
            parse_mode="HTML"
        )

    # 5. Payment Method Selected
    elif data.startswith("pay_"):
        method = data.replace("pay_", "")
        context.user_data["selected_method"] = method

        link = context.user_data.get("product_link", "N/A")
        confirm_text = (
            f"Link: {link}\n"
            f"Selected Method: {method}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm", callback_data="confirm_order")]
        ])
        
        try:
            await query.message.delete()
        except Exception:
            pass
            
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=confirm_text,
            reply_markup=keyboard
        )

    # 6. Confirm Order (Notify user + send data to Admin)
    elif data == "confirm_order":
        try:
            await query.message.delete()
        except Exception:
            pass
            
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "Turn on bot notification we will send you the best discount under Few Minutes .\n"
                "Thanks to use X DISCOUNT."
            )
        )

        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        
        # Sent to Admin using your requested format (User ID gets big highlighted as Code block)
        admin_message = (
            f"1. <b><code>{user.id}</code></b>\n"
            f"2. {full_name}\n"
            f"3. {context.user_data.get('product_link')} | {context.user_data.get('selected_method')}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"),
                InlineKeyboardButton("Reject", callback_data=f"adm_reject_{user.id}"),
            ]
        ])

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    # 7. Admin Reject
    elif data.startswith("adm_reject_"):
        target_user_id = int(data.split("adm_reject_")[1])
        await context.bot.send_message(
            chat_id=target_user_id,
            text="Free Service is Expired For You try bot on new telegram"
        )
        await query.message.edit_text(f"❌ Rejected User {target_user_id}")

    # 8. Admin Accept
    elif data.startswith("adm_accept_"):
        target_user_id = int(data.split("adm_accept_")[1])
        admin_sessions[ADMIN_ID] = {
            "target_user_id": target_user_id,
            "step": "WAITING_HYPER_LINK",
            "data": {},
        }
        await query.message.edit_text(
            f"✅ Accepted User {target_user_id}.\nPlease send the Hyper Link:"
        )

    # 9. Purchase Walkthrough Steps
    elif data.startswith("purchase_start_"):
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="1. Open Flipcart app.",
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
            "3. Tap on Buy Now",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_4")]])
        )

    elif data == "p_step_4":
        discount = context.user_data.get("admin_discount", "Discount")
        await query.message.edit_text(
            f"4. Apply {discount} Discount now",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_5")]])
        )

    elif data == "p_step_5":
        hyper_link = context.user_data.get("admin_hyper_link", "https://flipkart.com")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Apply Discount 🚨", url=hyper_link)]])
        await query.message.edit_text(
            "5. Final Step: Click below to apply discount directly!", 
            reply_markup=keyboard
        )


# ---------------- TEXT HANDLER ---------------- #
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # --- ADMIN WORKFLOW ENGINE ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_user_id = session["target_user_id"]

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

            # Save data to User cache so they can use it during their Walkthrough Steps
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

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Purchase", callback_data=f"purchase_start_{target_user_id}")]]
            )

            await context.bot.send_photo(
                chat_id=target_user_id,
                photo=LOGO_URL,
                caption=user_msg,
                reply_markup=keyboard,
            )

            await update.message.reply_text(f"✅ Setup Completed! Notification sent to User {target_user_id}.")
            return

    # --- REGULAR USER LINK SUBMISSION ---
    if context.user_data.get("state") == "AWAITING_LINK":
        if is_valid_flipkart_link(text):
            match = re.search(r"https?://\S+", text)
            clean_link = match.group(0) if match else text

            context.user_data["product_link"] = clean_link
            context.user_data["state"] = None

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Upi", callback_data="pay_Upi"),
                    InlineKeyboardButton("Credit Card", callback_data="pay_Credit Card"),
                    InlineKeyboardButton("Net Banking", callback_data="pay_Net Banking"),
                ]
            ])

            await update.message.reply_text(
                "Which Payment method you use mainly on Flipcart and want discount on",
                reply_markup=keyboard,
            )
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

    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
