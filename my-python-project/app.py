import os
import threading
import telebot
from flask import Flask, jsonify

# 1. Flask App (Render को चालू रखने के लिए एक डमी वेबसाइट)
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "success", "message": "Bot is running and working!"})

# 2. Telegram Bot का असली कोड
# ध्यान दें: Render Environment में आपके वेरिएबल का नाम 'TELEGRAM_TOKEN' होना चाहिए
BOT_TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "नमस्ते भाई! आपका बोट अब एकदम सही काम कर रहा है। 🔥")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, f"आपने कहा: {message.text}")

# 3. Bot को बैकग्राउंड में चलाने का जुगाड़
def run_bot():
    print("Telegram Bot स्टार्ट हो रहा है...")
    bot.infinity_polling()

if __name__ == '__main__':
    # Bot को अलग धागे (thread) में स्टार्ट करें
    threading.Thread(target=run_bot).start()
    
    # Flask सर्वर स्टार्ट करें
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
