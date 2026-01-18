from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from datetime import datetime
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import os
from dotenv import load_dotenv

# ---------------- LOAD ENV ----------------
load_dotenv()

app = Flask(__name__)
app.secret_key = "secret123"

# ---------------- ENERGY & CO2 CONSTANTS ----------------
# Based on research + IEA methodology (estimation)
LLM_ENERGY_KWH_PER_QUERY = 0.00034   # 0.34 Wh per query
GRID_EMISSION_FACTOR = 0.7           # India avg kg CO2 / kWh

# ---------------- MYSQL CONFIG ----------------
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'finalyeardb'

mysql = MySQL(app)

# ---------------- API KEY ----------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']

        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[3], password):
            session['user'] = username
            return redirect(url_for('index'))
        else:
            return "Invalid login credentials"

    return render_template("login.html")

# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])

        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (username, email, password)
        )
        mysql.connection.commit()
        cur.close()

        session['user'] = username
        return redirect(url_for('index'))

    return render_template("signup.html")

# ---------------- INDEX ----------------
@app.route("/index")
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template("index.html")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# ---------------- AI QUERY ----------------
# ---------------- BCA KEYWORDS ----------------
BCA_KEYWORDS = [
    "bca", "computer application",
    "programming", "c", "c++", "java", "python",
    "data structure", "algorithm",
    "dbms", "database", "mysql", "sql",
    "operating system", "os",
    "computer network", "networking",
    "html", "css", "javascript", "php",
    "software engineering",
    "oop", "oops",
    "ai", "artificial intelligence",
    "machine learning",
    "cloud computing",
    "flask", "django"
]
def is_bca_related(query):
    query = query.lower()
    return any(keyword in query for keyword in BCA_KEYWORDS)

@app.route("/ask", methods=["POST"])
def ask_ai():
    if 'user' not in session:
        return jsonify({"response": "Please login first"})

    data = request.get_json()
    user_query = data.get("query")

    if not user_query:
        return jsonify({"response": "Please enter a valid query."})

    # ---------- BCA KEYWORD VALIDATION ----------
    if not is_bca_related(user_query):
        return jsonify({
            "response": "Query not matched. Kindly enter BCA related concepts."
        })

    # ---------- CALL OPENROUTER ----------
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [{"role": "user", "content": user_query}]
    }

    api_response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload
    )

    result = api_response.json()
    ai_response = result["choices"][0]["message"]["content"]

    # ---------- ENERGY & CO2 CALC ----------
    energy_kwh = LLM_ENERGY_KWH_PER_QUERY
    co2_kg = energy_kwh * GRID_EMISSION_FACTOR

    # ---------- STORE QUERY ----------
    cur = mysql.connection.cursor()
    cur.execute("""
        INSERT INTO query_logs
        (username, query_text, response_text, energy_kwh, co2_kg)
        VALUES (%s, %s, %s, %s, %s)
    """, (session['user'], user_query, ai_response, energy_kwh, co2_kg))
    mysql.connection.commit()

    # ---------- TODAY'S STATS ----------
    cur.execute("""
        SELECT COUNT(*), SUM(energy_kwh), SUM(co2_kg)
        FROM query_logs
        WHERE username=%s AND DATE(created_at)=CURDATE()
    """, (session['user'],))

    count, total_energy, total_co2 = cur.fetchone()
    cur.close()

    return jsonify({
        "response": ai_response,
        "engine": "GPT-3.5 Turbo (Estimated)",
        "stats": {
            "count": count or 0,
            "energy": round(total_energy or 0, 6),
            "co2": round(total_co2 or 0, 6)
        }
    })

# ---------------- ADMIN PANEL ----------------
@app.route("/admin")
def admin():
    cur = mysql.connection.cursor(dictionary=True)
    cur.execute("SELECT * FROM query_logs ORDER BY created_at DESC")
    logs = cur.fetchall()
    cur.close()

    return render_template("admin.html", logs=logs)

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)

