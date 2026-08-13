import io
import os
import re
import threading
import telebot
from flask import Flask, jsonify
from telebot import types
import requests
from pymongo import MongoClient

# 1. Flask App Setup (Render को चालू रखने के लिए)
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "success", "message": "X Discount Bot is running smoothly with MongoDB!"})

# 2. Variables & Setup
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# अपने MongoDB Atlas का कनेक्शन यूआरआई यहाँ डालें (या Render Environment Variables में सेट करें)
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://devsagaraaaaa_db_user:hsUgTzN7Gd3aJ5E7@cluster0.yhnaz0g.mongodb.net/?appName=Cluster0")

IMAGE_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
ADMIN_ID = 8844584255

# यूजर के अस्थायी इनपुट स्टोर करने के लिए
user_data = {}

# --- MongoDB Setup ---
try:
    client = MongoClient(MONGO_URI)
    db = client["x_discount_db"]
    users_collection = db["users"]
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

# --- Helper Functions for MongoDB ---
def get_user_from_db(user_id):
    try:
        user = users_collection.find_one({"user_id": str(user_id)})
        return user
    except Exception as e:
        print(f"Error fetching user from DB: {e}")
        return None

def save_user_to_db(user_id, first_name, free_trial=2):
    try:
        user_doc = {
            "user_id": str(user_id),
            "first_name": first_name,
            "freeTrial": free_trial,
            "link": "",
            "number": ""
        }
        users_collection.update_one(
            {"user_id": str(user_id)},
            {"$setOnInsert": user_doc},
            upsert=True
        )
    except Exception as e:
        print(f"Error saving user to DB: {e}")

def update_user_details_in_db(user_id, free_trial, link, number):
    try:
        users_collection.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "freeTrial": free_trial,
                    "link": link,
                    "number": number
                }
            }
        )
    except Exception as e:
        print(f"Error updating user in DB: {e}")

# --- Telegram Bot Handlers ---

# 1. /Start Command
import io
import os
import re
import threading
import telebot
from flask import Flask, jsonify
from telebot import types
import requests
from pymongo import MongoClient

# 1. Flask App Setup (For Render)
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "success", "message": "X Discount Bot is running smoothly with MongoDB!"})

# 2. Variables & Setup
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

# MongoDB Connection URI
MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://devsagaraaaaa_db_user:hsUgTzN7Gd3aJ5E7@cluster0.yhnaz0g.mongodb.net/?appName=Cluster0")

IMAGE_URL = "https://ik.imagekit.io/Rajmalik99/1786595036231.png"
ADMIN_ID = 8844584255

# Temporary data storage
user_data = {}

# --- MongoDB Setup ---
try:
    client = MongoClient(MONGO_URI)
    db = client["x_discount_db"]
    users_collection = db["users"]
    print("MongoDB Connected Successfully!")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")

# --- Helper Functions ---
def get_full_name(user):
    """Combines first and last name safely"""
    first = user.first_name or ""
    last = user.last_name or ""
    return f"{first} {last}".strip() or "User"

def get_user_from_db(user_id):
    try:
        return users_collection.find_one({"user_id": str(user_id)})
    except Exception as e:
        print(f"Error fetching user from DB: {e}")
        return None

def save_user_to_db(user_id, full_name, free_trial=2):
    try:
        user_doc = {
            "user_id": str(user_id),
            "full_name": full_name,
            "freeTrial": free_trial,
            "link": "",
            "number": ""
        }
        users_collection.update_one(
            {"user_id": str(user_id)},
            {"$setOnInsert": user_doc},
            upsert=True
        )
    except Exception as e:
        print(f"Error saving user to DB: {e}")

def update_user_details_in_db(user_id, free_trial, link, number):
    try:
        users_collection.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "freeTrial": free_trial,
                    "link": link,
                    "number": number
                }
            }
        )
    except Exception as e:
        print(f"Error updating user in DB: {e}")

# --- Telegram Bot Handlers ---

# 1. /Start Command
@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = str(message.from_user.id)
    full_name = get_full_name(message.from_user)

    user_doc = get_user_from_db(user_id)
    if not user_doc:
        save_user_to_db(user_id, full_name, free_trial=2)

    welcome_text = f"Hello {full_name}!\nThis is X DISCOUNT ⚔️"

    markup = types.InlineKeyboardMarkup()
    btn_who = types.InlineKeyboardButton("Who are we", callback_data="who_are_we")
    markup.add(btn_who)

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# 2. Callback Handlers
@bot.callback_query_handler(func=lambda call: True)
def callback_listener(call):
    user_id = str(call.from_user.id)
    full_name = get_full_name(call.from_user)

    if call.data == "who_are_we":
        caption_text = (
            "X DISCOUNT is a Dumping server of failed discounts from big sales like "
            "<i><b>BIG BILLION DAY</b></i> , <i><b>GOAT SALE</b></i> , "
            "<i><b>BIG DIWALI SALE</b></i> , <i><b>FLIPCART BLACK FRIDAY SALE</b></i>.\n\n"
            "so when the sale is live there is too much load on server that's why the discount failed "
            "and discount session tokens comes to our server."
        )

        markup = types.InlineKeyboardMarkup()
        btn_get_discount = types.InlineKeyboardButton("Get Discount", callback_data="get_discount")
        markup.add(btn_get_discount)

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

        # FIX 1: Send Image directly via URL (Super Fast!)
        try:
            bot.send_photo(
                call.message.chat.id,
                IMAGE_URL,
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception as e:
            print(f"Failed to send photo: {e}")
            bot.send_message(call.message.chat.id, caption_text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "get_discount":
        user_doc = get_user_from_db(user_id)
        
        # FIX 3: Default to 2 if user isn't found or 'freeTrial' is missing
        if not user_doc:
            save_user_to_db(user_id, full_name, free_trial=2)
            trials_left = 2
        else:
            trials_left = user_doc.get("freeTrial", 2)

        msg_text = "This service is not free the service charge $50/DISCOUNT."
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_free = types.InlineKeyboardButton(f"Free {trials_left} discount left", callback_data="use_free_trial")
        btn_buy = types.InlineKeyboardButton("Buy Discount", callback_data="buy_discount")
        markup.add(btn_free, btn_buy)

        bot.send_message(call.message.chat.id, msg_text, reply_markup=markup)

    elif call.data == "use_free_trial":
        user_doc = get_user_from_db(user_id)
        trials_left = int(user_doc.get("freeTrial", 2) if user_doc else 2)

        if trials_left <= 0:
            bot.answer_callback_query(call.id, "Your free trial limit is over!", show_alert=True)
            return

        bot.send_message(call.message.chat.id, "Send Your Flipkart Product Link")
        bot.register_next_step_handler(call.message, process_flipkart_link)

    elif call.data == "confirm_details":
        if user_id in user_data:
            link = user_data[user_id].get("link")
            number = user_data[user_id].get("number")

            user_doc = get_user_from_db(user_id)
            current_trials = int(user_doc.get("freeTrial", 2) if user_doc else 2)
            new_trials = max(0, current_trials - 1)

            update_user_details_in_db(user_id, new_trials, link, number)

            admin_msg = f"🚨 *New Discount Request* 🚨\n\n*User ID:* `{user_id}`\n*Name:* {full_name}\n*Link:* {link}\n*Number:* `{number}`"
            try:
                bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send message to admin: {e}")

            final_msg = "Turn on bot notification we will send you the best discount under 24hr .\nThanks to use X DISCOUNT."
            bot.send_message(call.message.chat.id, final_msg)

            del user_data[user_id]

# 3. Next Step Handlers
def process_flipkart_link(message):
    user_id = str(message.from_user.id)
    text = message.text.strip()

    if "flipkart.com" in text or "fkrt.it" in text:
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]["link"] = text

        msg = "Send Your Flipkart Mobile Number ⚠️ We didn't call/sms for otp do not share any other details than account number."
        bot.send_message(message.chat.id, msg)
        bot.register_next_step_handler(message, process_mobile_number)
    else:
        bot.send_message(message.chat.id, "Invalid link! Please send a valid Flipkart product link.")
        bot.register_next_step_handler(message, process_flipkart_link)

def process_mobile_number(message):
    user_id = str(message.from_user.id)
    number_text = message.text.strip()

    if re.match(r"^\d{10}$", number_text):
        if user_id in user_data:
            user_data[user_id]["number"] = number_text
            link = user_data[user_id]["link"]

            confirm_text = f"Please confirm your details:\n\n<b>Link:</b> {link}\n<b>Number:</b> {number_text}"
            markup = types.InlineKeyboardMarkup()
            btn_confirm = types.InlineKeyboardButton("Confirm", callback_data="confirm_details")
            markup.add(btn_confirm)

            bot.send_message(message.chat.id, confirm_text, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Invalid number! Please send a valid 10-digit mobile number.")
        bot.register_next_step_handler(message, process_mobile_number)

# 4. Threading & Execution
def run_bot():
    print("Telegram Bot starting with polling...")
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True, timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
@bot.message_handler(commands=["start"])
def send_welcome(message):
    user_id = str(message.from_user.id)
    first_name = message.from_user.first_name or "User"

    user_doc = get_user_from_db(user_id)

    if not user_doc:
        save_user_to_db(user_id, first_name, free_trial=2)

    # यहाँ यूजर का नाम सही से दिखेगा
    welcome_text = f"Hello {first_name} !\nThis is X DISCOUNT ⚔️"

    markup = types.InlineKeyboardMarkup()
    btn_who = types.InlineKeyboardButton("Who are we", callback_data="who_are_we")
    markup.add(btn_who)

    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

# 2. Callback Handlers
@bot.callback_query_handler(func=lambda call: True)
def callback_listener(call):
    user_id = str(call.from_user.id)
    first_name = call.from_user.first_name or "User"

    if call.data == "who_are_we":
        caption_text = (
            "X DISCOUNT is a Dumping server of failed discounts from big sales like "
            "<i><b>BIG BILLION DAY</b></i> , <i><b>GOAT SALE</b></i> , "
            "<i><b>BIG DIWALI SALE</b></i> , <i><b>FLIPCART BLACK FRIDAY SALE</b></i>.\n\n"
            "so when the sale is live there is too much load on server that's why the discount failed "
            "and discount session tokens comes to our server."
        )

        markup = types.InlineKeyboardMarkup()
        btn_get_discount = types.InlineKeyboardButton("Get Discount", callback_data="get_discount")
        markup.add(btn_get_discount)

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass

        try:
            response = requests.get(IMAGE_URL, timeout=10)
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
                bot.send_message(call.message.chat.id, caption_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            bot.send_message(call.message.chat.id, caption_text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "get_discount":
        user_doc = get_user_from_db(user_id)
        trials_left = user_doc.get("freeTrial", 0) if user_doc else 0

        msg_text = "This service is not free the service charge $50/DISCOUNT."
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_free = types.InlineKeyboardButton(f"Free {trials_left} discount left", callback_data="use_free_trial")
        btn_buy = types.InlineKeyboardButton("Buy Discount", callback_data="buy_discount")
        markup.add(btn_free, btn_buy)

        bot.send_message(call.message.chat.id, msg_text, reply_markup=markup)

    elif call.data == "use_free_trial":
        user_doc = get_user_from_db(user_id)
        trials_left = int(user_doc.get("freeTrial", 0) if user_doc else 0)

        if trials_left <= 0:
            bot.answer_callback_query(call.id, "आपकी फ्री ट्रायल सीमा समाप्त हो चुकी है!", show_alert=True)
            return

        bot.send_message(call.message.chat.id, "Send Your Flipcart Product Link")
        bot.register_next_step_handler(call.message, process_flipkart_link)

    elif call.data == "confirm_details":
        if user_id in user_data:
            link = user_data[user_id].get("link")
            number = user_data[user_id].get("number")

            user_doc = get_user_from_db(user_id)
            current_trials = int(user_doc.get("freeTrial", 2) if user_doc else 2)
            new_trials = max(0, current_trials - 1)

            update_user_details_in_db(user_id, new_trials, link, number)

            admin_msg = f"🚨 *New Discount Request* 🚨\n\n*User ID:* `{user_id}`\n*Name:* {first_name}\n*Link:* {link}\n*Number:* `{number}`"
            try:
                bot.send_message(ADMIN_ID, admin_msg, parse_mode="Markdown")
            except Exception as e:
                print(f"Failed to send message to admin: {e}")

            final_msg = "Turn on bot notification we will send you the best discount under 24hr .\nThanks to use X DISCOUNT."
            bot.send_message(call.message.chat.id, final_msg)

            del user_data[user_id]

# 3. Next Step Handlers
def process_flipkart_link(message):
    user_id = str(message.from_user.id)
    text = message.text.strip()

    if "flipkart.com" in text or "fkrt.it" in text:
        if user_id not in user_data:
            user_data[user_id] = {}
        user_data[user_id]["link"] = text

        msg = "Send Your Flipcart Mobile Number ⚠️ We did'nt call/sms for otp do not share any other details then account number."
        bot.send_message(message.chat.id, msg)
        bot.register_next_step_handler(message, process_mobile_number)
    else:
        bot.send_message(message.chat.id, "Invalid link! Please send a valid Flipkart product link.")
        bot.register_next_step_handler(message, process_flipkart_link)

def process_mobile_number(message):
    user_id = str(message.from_user.id)
    number_text = message.text.strip()

    if re.match(r"^\d{10}$", number_text):
        if user_id in user_data:
            user_data[user_id]["number"] = number_text
            link = user_data[user_id]["link"]

            confirm_text = f"Please confirm your details:\n\n<b>Link:</b> {link}\n<b>Number:</b> {number_text}"
            markup = types.InlineKeyboardMarkup()
            btn_confirm = types.InlineKeyboardButton("Confirm", callback_data="confirm_details")
            markup.add(btn_confirm)

            bot.send_message(message.chat.id, confirm_text, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Invalid number! Please send a valid 10-digit mobile number.")
        bot.register_next_step_handler(message, process_mobile_number)

# 4. Threading & Execution
def run_bot():
    print("Telegram Bot starting with polling...")
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True, timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
