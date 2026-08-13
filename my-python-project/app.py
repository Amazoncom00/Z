import os
import re
import pytz
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Configuration
ADMIN_ID = 86919346
LOGO_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Global dict to track admin workflow targets and temporary inputs
admin_sessions = {}


def is_server_open() -> bool:
    """Check if current Kolkata (IST) time is between 4:00 PM and 8:00 PM."""
    kolkata_tz = pytz.timezone("Asia/Kolkata")
    now = datetime.now(kolkata_tz)
    return 16 <= now.hour < 20


def is_valid_flipkart_link(text: str) -> bool:
    """Validate if the string is a valid URL from Flipkart."""
    pattern = r"https?://(?:www\.)?(?:flipkart\.com|fkrt\.cc|flipkart\.page\.link)/\S+"
    return bool(re.search(pattern, text, re.IGNORECASE))


# ---------------- START COMMAND ---------------- #
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()  # Reset user state

    welcome_text = (
        f"Hello ! {user.first_name} {user.last_name or ''}\n"
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

    # 2. Get Discount (Time Check)
    elif data == "get_discount":
        if not is_server_open():
            await query.message.reply_text(
                "Server Shut Down We will Notify you When it Will avalable between 4pm-8pm"
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
                ]
            ]
        )

        await query.message.reply_text(text, reply_markup=keyboard)

    # 3. Free / Buy Discount selected
    elif data in ["free_discount", "buy_discount"]:
        context.user_data["state"] = "AWAITING_LINK"
        await query.message.reply_text("Send Your Flipcart Product Link")

    # 4. Payment Method Selected
    elif data.startswith("pay_"):
        method = data.split("pay_")[1].replace("_", " ").title()
        context.user_data["selected_method"] = method

        link = context.user_data.get("product_link", "N/A")
        confirm_text = (
            f"<b>Confirmation Details:</b>\n\n"
            f"<b>Product Link:</b> {link}\n"
            f"<b>Selected Method:</b> {method}"
        )

        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Confirm", callback_data="confirm_order")]]
        )

        await query.message.reply_text(
            confirm_text, parse_mode="HTML", reply_markup=keyboard
        )

    # 5. User Confirm Order
    elif data == "confirm_order":
        await query.message.reply_text(
            "Turn on bot notification we will send you the best discount under Few Minutes .\n"
            "Thanks to use X DISCOUNT."
        )

        # Send request details to Admin
        admin_message = (
            f"🔥 <b>NEW DISCOUNT REQUEST</b> 🔥\n\n"
            f"1. <b>User ID:</b> <code>{user.id}</code>\n"
            f"2. <b>Name:</b> {user.first_name} {user.last_name or ''}\n"
            f"3. <b>Product Link:</b> {context.user_data.get('product_link')}\n"
            f"4. <b>Payment Method:</b> {context.user_data.get('selected_method')}"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Accept", callback_data=f"adm_accept_{user.id}"),
                    InlineKeyboardButton("Reject", callback_data=f"adm_reject_{user.id}"),
                ]
            ]
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID, text=admin_message, parse_mode="HTML", reply_markup=keyboard
        )

    # 6. Admin Action: Reject
    elif data.startswith("adm_reject_"):
        target_user_id = int(data.split("adm_reject_")[1])
        await context.bot.send_message(
            chat_id=target_user_id,
            text="Free Service is Expired For You try bot on new telegram",
        )
        await query.edit_message_text(
            f"❌ Request for User <code>{target_user_id}</code> was Rejected.", parse_mode="HTML"
        )

    # 7. Admin Action: Accept -> Start step-by-step prompts
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

    # 8. Purchase Flow (Walkthrough steps)
    elif data.startswith("purchase_start_"):
        await query.edit_message_text(
            "1. Open Flipcart app.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Next", callback_data="p_step_2")]]
            ),
        )

    elif data == "p_step_2":
        user_link = context.user_data.get("product_link", "your saved link")
        await query.edit_message_text(
            f"2. Select this product: {user_link}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Next", callback_data="p_step_3")]]
            ),
        )

    elif data == "p_step_3":
        await query.edit_message_text(
            "3. Tap on Buy Now",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Next", callback_data="p_step_4")]]
            ),
        )

    elif data == "p_step_4":
        discount = context.user_data.get("admin_discount", "special")
        await query.edit_message_text(
            f"4. Apply {discount} Discount now",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Next", callback_data="p_step_5")]]
            ),
        )

    elif data == "p_step_5":
        hyper_link = context.user_data.get("admin_hyper_link", "https://flipkart.com")
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚨 Apply Discount 🚨", url=hyper_link)]]
        )
        await query.edit_message_text(
            "5. Final Step: Click below to apply discount directly!", reply_markup=keyboard
        )


# ---------------- MESSAGE HANDLER ---------------- #
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

            # Extract collected data
            data = session["data"]
            hyper_link = data["hyper_link"]
            discount = data["discount"]
            prod_name = data["product_name"]
            final_price = data["final_price"]

            # Clear admin session
            del admin_sessions[user_id]

            # Store in target user's context memory for workflow navigation
            target_user_data = context.application.user_data[target_user_id]
            target_user_data["admin_hyper_link"] = hyper_link
            target_user_data["admin_discount"] = discount

            # Retrieve target user details
            try:
                target_chat = await context.bot.get_chat(target_user_id)
                user_first = target_chat.first_name or "User"
                user_last = target_chat.last_name or ""
            except Exception:
                user_first, user_last = "User", ""

            # Send Notification with Photo to Target User
            user_msg = (
                f"Hi {user_first} {user_last}\n"
                f"You got {discount} on <b>{prod_name}</b>.\n"
                f"You can purchase <b>{prod_name}</b> in <b>{final_price}</b> From your Flipcart account."
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

            await update.message.reply_text(f"✅ Notification successfully sent to User <code>{target_user_id}</code>!", parse_mode="HTML")
            return

    # --- REGULAR USER LINK SUBMISSION ---
    if context.user_data.get("state") == "AWAITING_LINK":
        if is_valid_flipkart_link(text):
            context.user_data["product_link"] = text
            context.user_data["state"] = None  # Clear state

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Upi", callback_data="pay_upi"),
                        InlineKeyboardButton("Credit Card", callback_data="pay_credit_card"),
                        InlineKeyboardButton("Net Banking", callback_data="pay_net_banking"),
                    ]
                ]
            )

            await update.message.reply_text(
                "Which Payment method you use mainly on Flipcart and want discount on",
                reply_markup=keyboard,
            )
        else:
            await update.message.reply_text(
                "❌ Invalid Flipkart Link. Please send a valid link from flipkart.com."
            )


# ---------------- MAIN APPLICATION ---------------- #
def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_TOKEN environment variable is missing!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
