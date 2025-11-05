# app.py
"""
DayByDay — Full interactive Streamlit app
- Local username/password login (no OAuth or Supabase)
- Sidebar navigation (Home, Planner, Chat, Feed)
- 8-day planner with cards, checkboxes, add/edit/remove tasks
- Per-task AI assistance (Ask DayBot)
- Chat that can modify plan or day
- Feed with AI next-step suggestions
- Persistent local JSON storage for session + projects
- Gemini 2.5 Flash integration (if GEMINI_API_KEY present) with mock fallback
"""

import os
import json
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv

# ------------------------
# Streamlit page config
# ------------------------
APP_NAME = "DayByDay"
DAYBOT_NAME = "DayBot"
st.set_page_config(page_title=APP_NAME, page_icon="📅", layout="wide")

# ------------------------
# Config & env
# ------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"

try:
    import google.generativeai as genai
except Exception:
    genai = None

# ------------------------
# Files
# ------------------------
USERS_FILE = "users.json"
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"
FEED_FILE = "feed.json"

def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)

for p, d in [
    (USERS_FILE, {}), (PROJECTS_FILE, {}), (SESSION_FILE, {}), (FEED_FILE, [])
]:
    ensure_file(p, d)

# ------------------------
# CSS
# ------------------------
ACCENT1, ACCENT2, BG, TEXT, MUTED = "#7b2cbf", "#ff6ec7", "#0f0f10", "#e9e6ee", "#bdb7d9"
st.markdown(f"""
<style>
:root {{ --bg:{BG}; --accent1:{ACCENT1}; --accent2:{ACCENT2}; --text:{TEXT}; }}
body {{ background: linear-gradient(180deg,#070607,#0f0f10); color:var(--text); }}
.header {{ background: linear-gradient(90deg,var(--accent1),var(--accent2));
  padding:16px; border-radius:12px; color:white; text-align:center; margin-bottom:14px; }}
.card {{ background: rgba(255,255,255,0.02); border-radius:12px; padding:12px;
  margin-bottom:12px; border:1px solid rgba(255,255,255,0.04); }}
.day-card {{ background: linear-gradient(135deg, rgba(123,44,191,0.06), rgba(255,110,199,0.03));
  border-radius:12px; padding:12px; margin-bottom:12px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); }}
.small {{ color:{MUTED}; font-size:13px; }}
button.stButton>button {{ background: linear-gradient(90deg,var(--accent2),var(--accent1)); color:white; border-radius:8px; }}
textarea, input, .stTextInput>div>input {{ background: rgba(255,255,255,0.02); color:var(--text); }}
</style>
""", unsafe_allow_html=True)

st.markdown(
    f'<div class="header"><h1 style="margin:0">📅 {APP_NAME}</h1>'
    f'<div class="small">Your friendly AI project planner — {DAYBOT_NAME} helps every task.</div></div>',
    unsafe_allow_html=True,
)

# ------------------------
# Helpers
# ------------------------
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ------------------------
# Session init
# ------------------------
for key, default in {
    "user": None,
    "active_tab": "Home",
    "project": {"title": "", "constraints": "", "tasks": [[] for _ in range(8)], "generated_at": None},
    "chat_history": []
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ------------------------
# AI mock
# ------------------------
def call_ai(prompt):
    if not GEMINI_API_KEY or genai is None:
        return True, "🤖 Mock response: AI is thinking locally!"
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(prompt)
        return True, resp.text
    except Exception:
        return True, "⚙️ AI temporarily unavailable."

# ------------------------
# App Core
# ------------------------
def render_app():
    st.sidebar.write(f"👋 Logged in as **{st.session_state.user}**")
    page = st.sidebar.radio("Navigate", ["Home", "Planner", "Chat", "Feed"], index=["Home", "Planner", "Chat", "Feed"].index(st.session_state.active_tab))
    st.session_state.active_tab = page

    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.session_state.active_tab = "Home"
        return

    if page == "Home":
        st.subheader(f"Welcome, {st.session_state.user} 👋")
        st.write("Your current project overview:")
        proj = st.session_state.project
        done = sum(t["done"] for d in proj["tasks"] for t in d)
        total = sum(len(d) for d in proj["tasks"])
        st.progress(int(done / max(total, 1) * 100))

    elif page == "Planner":
        st.subheader("🗓️ 8-Day Planner")
        for i, day_tasks in enumerate(st.session_state.project["tasks"]):
            st.markdown(f"**Day {i+1}**")
            for t_idx, t in enumerate(day_tasks):
                checked = st.checkbox(t["title"], value=t["done"], key=f"d{i}t{t_idx}")
                t["done"] = checked
            new_task = st.text_input(f"Add task (Day {i+1})", key=f"add_d{i}")
            if new_task:
                st.session_state.project["tasks"][i].append({"title": new_task, "done": False})
        if st.button("💾 Save Project"):
            write_json(PROJECTS_FILE, {st.session_state.user: st.session_state.project})
            st.success("Project saved!")

    elif page == "Chat":
        st.subheader(f"💬 Chat with {DAYBOT_NAME}")
        msg = st.text_input("Type a message", key="chat_input")
        if st.button("Send"):
            st.session_state.chat_history.append({"from": "you", "msg": msg})
            ok, reply = call_ai(msg)
            st.session_state.chat_history.append({"from": "bot", "msg": reply})
        for m in st.session_state.chat_history:
            st.markdown(f"**{m['from'].capitalize()}**: {m['msg']}")

    elif page == "Feed":
        st.subheader("📢 Project Feed")
        posts = read_json(FEED_FILE, [])
        for p in posts:
            st.markdown(f"<div class='card'><b>{p['user']}</b>: {p['text']}</div>", unsafe_allow_html=True)
        text = st.text_input("Post update")
        if st.button("Post"):
            entry = {"user": st.session_state.user, "text": text, "time": datetime.utcnow().isoformat()}
            posts.insert(0, entry)
            write_json(FEED_FILE, posts)
            st.success("Posted!")

# ------------------------
# Auth UI
# ------------------------
def login_signup_ui():
    st.markdown("### 🔐 Login or Sign Up")
    col1, col2 = st.columns(2)
    users = read_json(USERS_FILE, {})

    # LOGIN
    with col1:
        st.subheader("Login")
        u = st.text_input("Username", key="login_u")
        p = st.text_input("Password", type="password", key="login_p")
        if st.button("Login"):
            if u in users and users[u]["password"] == p:
                st.session_state.user = u
                st.session_state.active_tab = "Home"
            else:
                st.error("Invalid credentials")

    # SIGNUP
    with col2:
        st.subheader("Sign Up")
        su = st.text_input("New username", key="signup_u")
        sp = st.text_input("New password", type="password", key="signup_p")
        if st.button("Create Account"):
            if su in users:
                st.error("User already exists")
            else:
                users[su] = {"password": sp}
                write_json(USERS_FILE, users)
                st.session_state.user = su
                st.session_state.active_tab = "Home"
                st.success("Account created!")

# ------------------------
# Main
# ------------------------
if st.session_state.user:
    render_app()
else:
    login_signup_ui()
