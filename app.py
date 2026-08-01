from flask import Flask, request, jsonify
from flask_cors import CORS

# Apni API Bridge aur Database Core ko import karna
from api_bridge import APIBridge
import db_core

app = Flask(__name__)
# CORS enable karna bohot zaroori hai taaki HTML bina security error ke isse connect kar sake
CORS(app)

# Bridge initialize karna
bridge = APIBridge()

# ==========================================
# 1. DATABASE INITIALIZATION ROUTE
# ==========================================
@app.route('/api/init', methods=['GET'])
def setup_db():
    try:
        db_core.init_db() 
        return jsonify({"success": True, "message": "Cloud Database (Supabase) 100% Initialized!"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ==========================================
# 2. UNIVERSAL DYNAMIC ROUTER (PRO TRICK!)
# ==========================================
# Yeh ek akela route tumhare JS ke har ek function ko automatically process kar lega!
# Humein ab 50 alag-alag route likhne ki zaroorat nahi hai.
@app.route('/api/<method_name>', methods=['POST'])
def dynamic_api(method_name):
    # Check karna ki kya APIBridge mein yeh function (method) exist karta hai
    if not hasattr(bridge, method_name):
        return jsonify({"success": False, "error": f"Method {method_name} not found"})

    try:
        func = getattr(bridge, method_name)
        # JS Frontend hamesha arguments ki ek list (array) bhejega
        args = request.json or []

        # *args Python ki trick hai list ko variables mein kholne ki
        if isinstance(args, list):
            result = func(*args) 
        elif isinstance(args, dict):
            result = func(**args)
        else:
            result = func()

        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ==========================================
# SERVER STARTUP
# ==========================================
if __name__ == '__main__':
    print("🚀 Billing Software Backend Server Started!")
    print("👉 Frontend ke liye APIs http://127.0.0.1:5000/api/ par available hain.")
    # Debug=True ke sath host='0.0.0.0' lagana zaroori hai Wi-Fi connection ke liye
    app.run(host='192.168.1.9', debug=True, port=5000)