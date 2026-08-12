from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "success",
        "message": "Hello! Render par aapka Python app safaltapoorvak chal raha hai."
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # Render PORT environment variable deta hai
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
