import os
import re
import urllib.parse
import pytz
from datetime import datetime
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

# Dynamically generate QR code image URL
QR_CODE_API_URL = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(TRUST_WALLET_LINK)}"

# Global memory for admin current active workflow
admin_sessions = {}


def is_server_open() -> bool:
    """Check if current Kolkata (IST) time is between 4:00 PM and 8:00 PM."""
    kolkata_tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(kolkata_tz)
    return 16 <= now.hour < 20


def is_valid_flipkart_link(text: str) -> bool:
    """Extract and validate Flipkart URL from message text."""
    pattern = r"https?://(?:www\.)?(?:flipkart\.com|fkrt\.cc|flipkart\.page\.link)/\S+"
    return bool(re.search(pattern, text, re.IGNORECASE))


# ---------------- TIMER CALLBACK (30-MIN EXPIRY) ---------------- #
async def expire_offer_callback(context: ContextTypes.DEFAULT_TYPE):
    """Triggered automatically after 30 minutes if user hasn't completed purchase."""
    job = context.job
    user_id = job.data["user_id"]
    
    if user_id in context.application.user_data:
        context.application.user_data[user_id]["offer_active"] = False

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ <b>Offer Expired!</b>\n\nYour 30-minute discount window has ended. Please start a new request during server hours (4PM - 8PM).",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ---------------- START COMMAND ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data["state"] = None
    
    # Save user ID locally for Broadcast feature
    if "user_list" not in context.bot_data:
        context.bot_data["user_list"] = set()
    context.bot_data["user_list"].add(user.id)

    welcome_text = (
        f"Hello ! {user.first_name} {user.last_name or ''}\n"
        f"This is X DISCOUNT ⚔️"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Who are we", callback_data="who_are_we")]]
    )

    await update.message.reply_text(welcome_text, reply_markup=keyboard)


# ---------------- ADMIN BROADCAST ---------------- #
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /broadcast Your message here"""
    if update.effective_user.id != ADMIN_ID:
        return

    broadcast_msg = " ".join(context.args)
    if not broadcast_msg:
        await update.message.reply_text("❌ Please specify a message!\nUsage: <code>/broadcast Hello users!</code>", parse_mode="HTML")
        return

    users = context.bot_data.get("user_list", set())
    sent_count = 0

    for u_id in list(users):
        try:
            await context.bot.send_message(chat_id=u_id, text=broadcast_msg)
            sent_count += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ Broadcast successfully delivered to <b>{sent_count}</b> users.", parse_mode="HTML")


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
            "4. <b><i>FLIPCART BLACK FRIDAY SALE</i></b>.\n\n"
            "so when the sale is live there is too much load on server that's why "
            "the discount failed and discount session tokens comes to our server.\n"
            "Our Server Avalable on 4pm-8pm only"
        )

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Get Discount", callback_data="get_discount")]]
        )

        await query.message.chat.send_photo(
            photo=LOGO_URL,
            caption=about_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

    # 2. Get Discount (Time Check & Free/Buy Menu)
    elif data in ["get_discount", "back_to_discount_type"]:
        if not is_server_open():
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Contact Support", url="https://t.me/telegram")]
            ])
            await query.message.reply_text(
                "Server Shut Down We will Notify you When it Will avalable between 4pm-8pm",
                reply_markup=keyboard
            )
            return

        text = (
            "This service is not free the service charge $50/DISCOUNT.\n"
            "Free Trial Avalable 2 per telegram accouunt."
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Free discount", callback_data="free_discount"),
                    InlineKeyboardButton("Buy Discount", callback_data="buy_discount"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ]
        )

        if query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(text, reply_markup=keyboard)
        else:
            await query.edit_message_text(text, reply_markup=keyboard)

    # 3. Main Menu Button
    elif data == "main_menu":
        context.user_data["state"] = None
        welcome_text = (
            f"Hello ! {user.first_name} {user.last_name or ''}\n"
            f"This is X DISCOUNT ⚔️"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Who are we", callback_data="who_are_we")]])
        
        if query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(welcome_text, reply_markup=keyboard)
        else:
            await query.edit_message_text(welcome_text, reply_markup=keyboard)

    # 4. Free Discount Flow
    elif data == "free_discount":
        context.user_data["state"] = "AWAITING_LINK"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        await query.message.reply_text("Send Your Flipcart Product Link", reply_markup=keyboard)

    # 5. Buy Discount Flow (Generate Payment QR Code + Back Navigation)
    elif data == "buy_discount":
        payment_caption = (
            "💰 <b>BUY DISCOUNT - PAYMENT DETAILS</b>\n\n"
            f"<b>My Public Address to Receive BTC:</b>\n<code>{BTC_ADDRESS}</code>\n\n"
            f"<b>Pay me via Trust Wallet:</b>\n{TRUST_WALLET_LINK}\n\n"
            "<i>Scan the QR code above or use the details to complete your payment ($50).</i>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ I Have Paid / Continue", callback_data="buy_continue")],
            [
                InlineKeyboardButton("⬅️ Back", callback_data="back_to_discount_type"),
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")
            ]
        ])

        try:
            await query.message.delete()
        except Exception:
            pass

        await query.message.chat.send_photo(
            photo=QR_CODE_API_URL,
            caption=payment_caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    # 6. Buy Continue (NO BACK BUTTONS AFTER THIS POINT)
    elif data == "buy_continue":
        context.user_data["state"] = "AWAITING_LINK"
        
        # Simple message without back buttons as requested
        try:
            await query.message.delete()
        except Exception:
            pass

        await query.message.chat.send_message("Send Your Flipcart Product Link")

    # 7. Payment Method Selected
    elif data.startswith("pay_"):
        method = data.split("pay_")[1].replace("_", " ").title()
        context.user_data["selected_method"] = method

        link = context.user_data.get("product_link", "N/A")
        confirm_text = (
            f"<b>Confirmation Details:</b>\n\n"
            f"<b>Product Link:</b> {link}\n"
            f"<b>Selected Method:</b> {method}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Confirm", callback_data="confirm_order")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ])

        await query.message.reply_text(confirm_text, parse_mode="HTML", reply_markup=keyboard)

    # 8. Confirm Order
    elif data == "confirm_order":
        await query.message.reply_text(
            "Turn on bot notification we will send you the best discount under Few Minutes .\n"
            "Thanks to use X DISCOUNT."
        )

        admin_message = (
            f"🔥 <b>NEW DISCOUNT REQUEST</b> 🔥\n\n"
            f"1. <b>User ID:</b> <code>{user.id}</code>\n"
            f"2. <b>Name:</b> {user.first_name} {user.last_name or ''}\n"
            f"3. <b>Product Link:</b> {context.user_data.get('product_link')}\n"
            f"4. <b>Payment Method:</b> {context.user_data.get('selected_method')}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"),
                InlineKeyboardButton("Reject", callback_data=f"adm_reject_{user.id}"),
            ]
        ])

        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard)

    # 9. Admin Reject
    elif data.startswith("adm_reject_"):
        target_user_id = int(data.split("adm_reject_")[1])
        await context.bot.send_message(
            chat_id=target_user_id,
            text="Free Service is Expired For You try bot on new telegram",
        )
        await query.edit_message_text(f"❌ Request for User <code>{target_user_id}</code> Rejected.", parse_mode="HTML")

    # 10. Admin Accept
    elif data.startswith("adm_accept_"):
        target_user_id = int(data.split("adm_accept_")[1])
        admin_sessions[ADMIN_ID] = {
            "target_user_id": target_user_id,
            "step": "WAITING_HYPER_LINK",
            "data": {},
        }
        await query.message.reply_text(
            f"✅ Accepting request for User <code>{target_user_id}</code>.\n\n"
            f"<b>Step 1:</b> Please send the Hyper Link (Discount URL):",
            parse_mode="HTML",
        )

    # 11. Purchase Walkthrough
    elif data.startswith("purchase_start_"):
        if context.user_data.get("offer_active") is False:
            await query.answer("⚠️ This offer has expired after 30 minutes!", show_alert=True)
            return

        await query.edit_message_text(
            "1. Open Flipcart app.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_2")]]),
        )

    elif data == "p_step_2":
        user_link = context.user_data.get("product_link", "your saved link")
        await query.edit_message_text(
            f"2. Select this product: {user_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_3")]]),
        )

    elif data == "p_step_3":
        await query.edit_message_text(
            "3. Tap on Buy Now",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_4")]]),
        )

    elif data == "p_step_4":
        discount = context.user_data.get("admin_discount", "special")
        await query.edit_message_text(
            f"4. Apply {discount} Discount now",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Next", callback_data="p_step_5")]]),
        )

    elif data == "p_step_5":
        hyper_link = context.user_data.get("admin_hyper_link", "https://flipkart.com")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🚨 Apply Discount 🚨", url=hyper_link)]])
        await query.edit_message_text("5. Final Step: Click below to apply discount directly!", reply_markup=keyboard)


# ---------------- TEXT HANDLER ---------------- #
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "user_list" not in context.bot_data:
        context.bot_data["user_list"] = set()
    context.bot_data["user_list"].add(user_id)

    # --- ADMIN WORKFLOW ENGINE ---
    if user_id == ADMIN_ID and user_id in admin_sessions:
        session = admin_sessions[user_id]
        step = session["step"]
        target_user_id = session["target_user_id"]

        if step == "WAITING_HYPER_LINK":
            session["data"]["hyper_link"] = text
            session["step"] = "WAITING_DISCOUNT"
            await update.message.reply_text("<b>Step 2:</b> Send Discount amount/percentage (e.g., 50%):", parse_mode="HTML")
            return

        elif step == "WAITING_DISCOUNT":
            session["data"]["discount"] = text
            session["step"] = "WAITING_PROD_NAME"
            await update.message.reply_text("<b>Step 3:</b> Send Product Name:", parse_mode="HTML")
            return

        elif step == "WAITING_PROD_NAME":
            session["data"]["product_name"] = text
            session["step"] = "WAITING_PRICE"
            await update.message.reply_text("<b>Step 4:</b> Send Final Price:", parse_mode="HTML")
            return

        elif step == "WAITING_PRICE":
            session["data"]["final_price"] = text

            data = session["data"]
            hyper_link = data["hyper_link"]
            discount = data["discount"]
            prod_name = data["product_name"]
            final_price = data["final_price"]

            del admin_sessions[user_id]

            target_user_data = context.application.user_data[target_user_id]
            target_user_data["admin_hyper_link"] = hyper_link
            target_user_data["admin_discount"] = discount
            target_user_data["offer_active"] = True

            # 30-minute expiry timer
            context.job_queue.run_once(
                expire_offer_callback,
                when=1800,
                data={"user_id": target_user_id},
                name=f"expire_{target_user_id}"
            )

            try:
                target_chat = await context.bot.get_chat(target_user_id)
                user_first = target_chat.first_name or "User"
                user_last = target_chat.last_name or ""
            except Exception:
                user_first, user_last = "User", ""

            user_msg = (
                f"Hi {user_first} {user_last}\n"
                f"You got {discount} on <b>{prod_name}</b>.\n"
                f"You can purchase <b>{prod_name}</b> in <b>{final_price}</b> From your Flipcart account.\n\n"
                f"⏰ <i>Note: This offer is valid for <b>30 Minutes</b> only!</i>"
            )

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Purchase", callback_data=f"purchase_start_{target_user_id}")]]
            )

            await context.bot.send_photo(
                chat_id=target_user_id,
                photo=LOGO_URL,
                caption=user_msg,
                parse_mode="HTML",
                reply_markup=keyboard,
            )

            await update.message.reply_text(
                f"✅ Notification & 30-min timer sent to User <code>{target_user_id}</code>!", 
                parse_mode="HTML"
            )
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
                    InlineKeyboardButton("Upi", callback_data="pay_upi"),
                    InlineKeyboardButton("Credit Card", callback_data="pay_credit_card"),
                    InlineKeyboardButton("Net Banking", callback_data="pay_net_banking"),
                ],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])

            await update.message.reply_text(
                "Which Payment method you use mainly on Flipcart and want discount on",
                reply_markup=keyboard,
            )
        else:
            # Feature #4: Try Again button on invalid link
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="free_discount")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
            await update.message.reply_text(
                "❌ Invalid Flipkart Link. Please send a valid link from flipkart.com.",
                reply_markup=keyboard
            )


# ---------------- MAIN APPLICATION ---------------- #
def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is missing!")

    persistence = PicklePersistence(filepath="bot_state.pkl")

    app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
