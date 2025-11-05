# app.py — DayByDay
"""
DayByDay — AI Project Planner
- Simple username/password login
- 8-day planner with cards, checkboxes, and AI task generator
- 'Generate Project' on Home → auto-opens Planner (no rerun)
- Persistent JSON storage for projects and sessions
- Gemini AI integration (optional, mock fallback)
"""

import os
import json
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv

# -------------------------------
# Config & Setup
# -------------------------------
APP_NAME = "DayByDay"
DAYBOT_NAME = "DayBot"

st.set_page_config(page_title=APP_NAME, page_icon="📅", layout="wide")

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Optional Gemini
try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
except Exception:
    genai = None

# -------------------------------
# Files & Storage Helpers
# -------------------------------
USERS_FILE = "users.json"
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"

def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)

for p, d in [(USERS_FILE, {}), (PROJECTS_FILE, {}), (SESSION_FILE, {})]:
    ensure_file(p, d)

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# -------------------------------
# AI Helper (Gemini or Mock)
# -------------------------------
def call_ai(prompt: str):
    if genai and GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            resp = model.generate_content(prompt)
            return True, resp.text
        except Exception:
            pass
    # fallback
    mock = "\n".join([f"Day {i+1}: Do research, build feature {i+1}, test it." for i in range(8)])
    return True, mock

# -------------------------------
# Auth Helpers
# -------------------------------
def load_users():
    return read_json(USERS_FILE, {})

def save_users(users):
    write_json(USERS_FILE, users)

def login(username, password):
    users = load_users()
    if username in users and users[username] == password:
        st.session_state.user = username
        return True
    return False

def signup(username, password):
    users = load_users()
    if username in users:
        return False, "Username already exists."
    users[username] = password
    save_users(users)
    st.session_state.user = username
    return True, "Account created successfully!"

# -------------------------------
# Styling
# -------------------------------
ACCENT1 = "#7b2cbf"
ACCENT2 = "#ff6ec7"
BG = "#0f0f10"
TEXT = "#e9e6ee"
MUTED = "#bdb7d9"

st.markdown(f"""
<style>
:root {{
  --bg: {BG}; --accent1: {ACCENT1}; --accent2: {ACCENT2}; --text: {TEXT};
}}
body {{
  background: linear-gradient(180deg,#070607,#0f0f10);
  color: var(--text);
}}
.header {{
  background: linear-gradient(90deg,var(--accent1),var(--accent2));
  padding:16px; border-radius:12px;
  color:white; text-align:center;
  margin-bottom:14px;
}}
.card {{
  background: rgba(255,255,255,0.02);
  border-radius:12px;
  padding:12px; margin-bottom:12px;
  border:1px solid rgba(255,255,255,0.04);
}}
.day-card {{
  background: linear-gradient(135deg, rgba(123,44,191,0.06), rgba(255,110,199,0.03));
  border-radius:12px; padding:12px; margin-bottom:12px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.5);
}}
.small {{ color: {MUTED}; font-size:13px; }}
button.stButton>button {{
  background: linear-gradient(90deg,var(--accent2),var(--accent1));
  color:white; border-radius:8px;
}}
textarea, input, .stTextInput>div>input {{
  background: rgba(255,255,255,0.02);
  color:var(--text);
}}
</style>
""", unsafe_allow_html=True)

st.markdown(
    f'<div class="header"><h1 style="margin:0">📅 {APP_NAME}</h1>'
    f'<div class="small">Your friendly AI project planner — {DAYBOT_NAME} helps every task.</div></div>',
    unsafe_allow_html=True,
)

# -------------------------------
# Initialize session
# -------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"
if "project" not in st.session_state:
    st.session_state.project = {"title": "", "constraints": "", "tasks": [[] for _ in range(8)]}

# -------------------------------
# UI Components
# -------------------------------
def login_screen():
    st.title("🔐 Sign In / Sign Up")

    tab1, tab2 = st.tabs(["Sign In", "Sign Up"])
    with tab1:
        user = st.text_input("Username", key="login_user")
        pwd = st.text_input("Password", type="password", key="login_pwd")
        if st.button("Login"):
            if login(user.strip(), pwd.strip()):
                st.success(f"Welcome back, {user}!")
            else:
                st.error("Invalid username or password.")

    with tab2:
        user = st.text_input("New Username", key="signup_user")
        pwd = st.text_input("New Password", type="password", key="signup_pwd")
        if st.button("Create Account"):
            ok, msg = signup(user.strip(), pwd.strip())
            if ok:
                st.success(msg)
            else:
                st.error(msg)

def render_home():
    st.subheader(f"Welcome, {st.session_state.user} 👋")
    st.write("Let's plan your next 8-day project!")

    proj = st.session_state.project
    title = st.text_input("📝 Project Title", value=proj["title"])
    constraints = st.text_area("📋 Constraints or Details", value=proj["constraints"])

    if st.button("🚀 Generate 8-Day Plan"):
        prompt = f"Create an 8-day step-by-step project plan for: {title}\nConstraints: {constraints}"
        ok, plan_text = call_ai(prompt)

        days = [[] for _ in range(8)]
        if ok and plan_text:
            lines = [l.strip("-• ") for l in plan_text.split("\n") if l.strip()]
            for i, line in enumerate(lines[:16]):  # two tasks per day
                days[i // 2].append({"title": line, "done": False})

        st.session_state.project = {
            "title": title,
            "constraints": constraints,
            "tasks": days,
            "generated_at": datetime.utcnow().isoformat(),
        }
        st.success("✅ Project generated! Opening your planner...")
        st.session_state.active_tab = "Planner"

    done = sum(t["done"] for d in proj["tasks"] for t in d)
    total = sum(len(d) for d in proj["tasks"])
    if total > 0:
        st.progress(int(done / total * 100))
    else:
        st.info("No project yet. Fill in details and click Generate.")

def render_planner():
    proj = st.session_state.project
    st.header(f"📅 {proj['title'] or 'Your 8-Day Plan'}")
    for i, day_tasks in enumerate(proj["tasks"]):
        with st.expander(f"Day {i+1}"):
            for task in day_tasks:
                checked = st.checkbox(task["title"], value=task["done"], key=f"{i}-{task['title']}")
                task["done"] = checked
    write_json(PROJECTS_FILE, {st.session_state.user: proj})

# -------------------------------
# Main app
# -------------------------------
if st.session_state.user is None:
    login_screen()
else:
    st.sidebar.title("📂 Navigation")
    tabs = ["Home", "Planner", "Logout"]
    choice = st.sidebar.radio("Go to", tabs, index=tabs.index(st.session_state.active_tab))

    if choice == "Logout":
        st.session_state.user = None
        st.session_state.active_tab = "Home"
    else:
        st.session_state.active_tab = choice

    if st.session_state.active_tab == "Home":
        render_home()
    elif st.session_state.active_tab == "Planner":
        render_planner()
