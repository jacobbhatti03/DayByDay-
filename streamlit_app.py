# app.py
"""
DayByDay — Full interactive Streamlit app
- Forced login/signup (Supabase email auth when configured)
- Sidebar navigation (Home, Planner, Chat, Feed)
- 8-day planner with cards, checkboxes, add/edit/remove tasks
- Per-task AI assistance (Ask DayBot)
- Chat that can modify plan or day
- Feed with AI next-step suggestions
- Persistent local JSON storage for session + projects (fallback)
- Gemini 2.5 Flash integration (if GEMINI_API_KEY present) with mock fallback
"""

import os
import json
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv

# ------------------------
# Streamlit page config (must be first)
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

# Optional AI import
try:
    import google.generativeai as genai
except Exception:
    genai = None

# Supabase client
try:
    from supabase import create_client
except Exception:
    create_client = None

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_KEY and create_client is not None)
REDIRECT_URI = "https://daybyday-1.streamlit.app/"
google_oauth_url = f"{SUPABASE_URL}/auth/v1/authorize?provider=google&redirect_to={REDIRECT_URI}"

supabase = None
if SUPABASE_CONFIGURED:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        SUPABASE_CONFIGURED = False
        supabase = None

# ------------------------
# Files (local persistence fallback)
# ------------------------
USERS_FILE = "users.json"
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"
FEED_FILE = "feed.json"
EXAMPLES_FILE = "ai_examples.json"

# ensure files exist (fallback)
def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

for path, default in [
    (USERS_FILE, {}), (PROJECTS_FILE, {}), (SESSION_FILE, {}), (FEED_FILE, []), (EXAMPLES_FILE, [])
]:
    ensure_file(path, default)

# ------------------------
# CSS
# ------------------------
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
body {{ background: linear-gradient(180deg,#070607,#0f0f10); color: var(--text); }}
.header {{ background: linear-gradient(90deg,var(--accent1),var(--accent2)); padding:16px; border-radius:12px; color:white; text-align:center; margin-bottom:14px; }}
.card {{ background: rgba(255,255,255,0.02); border-radius:12px; padding:12px; margin-bottom:12px; border:1px solid rgba(255,255,255,0.04); }}
.day-card {{ background: linear-gradient(135deg, rgba(123,44,191,0.06), rgba(255,110,199,0.03)); border-radius:12px; padding:12px; margin-bottom:12px; box-shadow: 0 8px 30px rgba(0,0,0,0.5); }}
.small {{ color: {MUTED}; font-size:13px; }}
button.stButton>button {{ background: linear-gradient(90deg,var(--accent2),var(--accent1)); color:white; border-radius:8px; }}
textarea, input, .stTextInput>div>input {{ background: rgba(255,255,255,0.02); color:var(--text); }}
</style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="header"><h1 style="margin:0">📅 {APP_NAME}</h1><div class="small">Your friendly AI project planner — DayBot helps every task.</div></div>', unsafe_allow_html=True)

# ------------------------
# JSON helpers
# ------------------------
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ------------------------
# Session state init
# ------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"
if "project" not in st.session_state:
    st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_ai_error" not in st.session_state:
    st.session_state.last_ai_error = None

# ------------------------
# Load / Save session
# ------------------------
def save_session():
    payload = {
        "active_tab": st.session_state.get("active_tab"),
        "user": st.session_state.get("user"),
        "project": st.session_state.get("project"),
        "chat_history": st.session_state.get("chat_history", [])
    }
    write_json(SESSION_FILE, payload)

def load_session():
    data = read_json(SESSION_FILE, {})
    for k in ["active_tab","user","project","chat_history"]:
        if k in data:
            st.session_state[k] = data[k]

load_session()

def save_project_to_history():
    if SUPABASE_CONFIGURED and st.session_state.get("user"):
        try:
            payload = {
                "user_email": st.session_state["user"],
                "project_json": json.dumps(st.session_state["project"]),
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("projects").insert(payload).execute()
            return True
        except Exception:
            pass
    projects = read_json(PROJECTS_FILE, {})
    user = st.session_state.user or "anonymous"
    user_projects = projects.get(user, [])
    user_projects.append(st.session_state.project.copy())
    projects[user] = user_projects
    write_json(PROJECTS_FILE, projects)
    return True

def load_last_project_for_user():
    user = st.session_state.get("user")
    if not user:
        return None
    if SUPABASE_CONFIGURED:
        try:
            res = supabase.table("projects").select("*").eq("user_email", user).order("created_at", {"ascending": False}).limit(1).execute()
            data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)
            if data and len(data) > 0:
                item = data[0]
                pj = item.get("project_json") or item.get("project_json")
                if isinstance(pj, str):
                    pj = json.loads(pj)
                return pj
        except Exception:
            pass
    projects = read_json(PROJECTS_FILE, {})
    user_projects = projects.get(user, [])
    if user_projects:
        return user_projects[-1]
    return None

def add_feed_post_supabase(user, text):
    entry = {"user": user, "text": text, "time": datetime.utcnow().isoformat()}
    ok, suggestions = ai_suggest_next_steps_from_post(text)
    if not ok:
        suggestions = ["Keep going — small steps build momentum.", "Review what worked.", "Plan one small win tomorrow."]
    entry["suggestions"] = suggestions
    if SUPABASE_CONFIGURED:
        try:
            payload = {
                "user_email": user,
                "text": text,
                "suggestions": json.dumps(suggestions),
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("feed").insert(payload).execute()
            return entry
        except Exception:
            pass
    feed = read_json(FEED_FILE, [])
    feed.insert(0, entry)
    write_json(FEED_FILE, feed)
    return entry

def read_feed_for_user():
    if SUPABASE_CONFIGURED:
        try:
            res = supabase.table("feed").select("*").order("created_at", {"ascending": False}).execute()
            data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)
            feed = []
            if data:
                for e in data:
                    suggs = e.get("suggestions") or e.get("suggestions")
                    if isinstance(suggs, str):
                        try:
                            suggs = json.loads(suggs)
                        except Exception:
                            suggs = [suggs]
                    feed.append({"user": e.get("user_email"), "text": e.get("text"), "time": e.get("created_at"), "suggestions": suggs})
            return feed
        except Exception:
            pass
    return read_json(FEED_FILE, [])

# ------------------------
# redirect helper
# ------------------------
def redirect_to(tab_name: str, save=True):
    st.session_state.active_tab = tab_name
    if save:
        save_session()

# ------------------------
# AI helpers (unchanged)
# ------------------------
SYSTEM_PROMPT = (
    f"You are {DAYBOT_NAME}, an encouraging, practical project assistant. "
    "Always reply with short actionable steps, task improvements, and time estimates when relevant. "
    "Do not reveal technical internals or model names."
)

def call_ai(prompt, max_tokens=600):
    if not GEMINI_API_KEY or genai is None:
        return False, "ERROR_NO_API_KEY"
    errors = []
    try:
        if hasattr(genai, "generate_text"):
            resp = genai.generate_text(model=MODEL_NAME, prompt=prompt, temperature=0.7, max_output_tokens=max_tokens)
            text = getattr(resp, "text", None) or str(resp)
            return True, text.strip()
    except Exception as e:
        errors.append(f"generate_text: {e}")
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or str(resp)
        return True, text.strip()
    except Exception as e:
        errors.append(f"GenerativeModel: {e}")
    return False, " | ".join(errors)

def mock_ai(prompt):
    return True, "✅ Mock response: pretend AI did it."

def ai_suggest_next_steps_from_post(post_text):
    prompt = f"Suggest 3 short next-step actions for this user post:\n{post_text}"
    ok, res = call_ai(prompt)
    if not ok:
        ok, res = mock_ai(prompt)
    lines = res.split("\n")
    lines = [l.strip("- ").strip() for l in lines if l.strip()]
    return True, lines[:3]

def plan_progress_percent(tasks_8days):
    total = sum(len(day) for day in tasks_8days)
    done = sum(1 for day in tasks_8days for t in day if t.get("done"))
    return int(done / max(total,1) * 100)

# ------------------------
# ------------------------
# Sidebar + Tabs + Sign out
# ------------------------
def render_app_ui():
    # Sidebar
    st.sidebar.markdown(f"### 📅 {APP_NAME}")
    st.sidebar.markdown(f"Hello, **{st.session_state.user}** 👋")
    selected_tab = st.sidebar.selectbox("Go to", ["Home", "Planner", "Chat", "Feed"], index=["Home","Planner","Chat","Feed"].index(st.session_state.active_tab))
    st.session_state.active_tab = selected_tab

    if st.sidebar.button("Sign Out"):
        if SUPABASE_CONFIGURED:
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
        st.session_state.user = None
        sess = read_json(SESSION_FILE, {})
        sess.pop("supabase_token", None)
        sess.pop("supabase_token_expires", None)
        write_json(SESSION_FILE, sess)
        save_session()
        st.success("Logged out.")
        return

    tab = st.session_state.active_tab

    if tab == "Home":
        st.markdown('<div class="card"><strong>Home</strong> — quick overview</div>', unsafe_allow_html=True)
        st.markdown(f"### Hello, **{st.session_state.user}** 👋")
        if st.session_state.project.get("title"):
            st.markdown(f"**Project:** {st.session_state.project.get('title')}")
            prog = plan_progress_percent(st.session_state.project.get("tasks", [[] for _ in range(8)]))
            st.markdown(f"Overall progress: **{prog}%**")
            st.progress(prog)
            if st.button("Open Planner", key="open_planner_btn"):
                redirect_to("Planner")
        else:
            st.info("You don't have an active project. Start planning to create one.")
            if st.button("Start Planning", key="start_planning_btn"):
                st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
                save_session()
                redirect_to("Planner")
        st.markdown("---")

    elif tab == "Planner":
        # Planner UI code here (all your existing 8-day planner UI, checkboxes, add/remove tasks)
        st.markdown('<div class="card"><strong>Planner</strong> — manage your 8-day plan</div>', unsafe_allow_html=True)
        for i, day_tasks in enumerate(st.session_state.project["tasks"]):
            st.markdown(f'<div class="day-card"><strong>Day {i+1}</strong></div>', unsafe_allow_html=True)
            for t_idx, task in enumerate(day_tasks):
                checked = st.checkbox(task.get("title","Unnamed Task"), value=task.get("done",False), key=f"day{i}_task{t_idx}")
                st.session_state.project["tasks"][i][t_idx]["done"] = checked
            new_task_title = st.text_input(f"Add task Day {i+1}", key=f"day{i}_newtask")
            if new_task_title:
                st.session_state.project["tasks"][i].append({"title": new_task_title, "done": False})
                st.session_state[f"day{i}_newtask"] = ""
        if st.button("Save Project"):
            save_project_to_history()
            st.success("Project saved!")

    elif tab == "Chat":
        st.markdown('<div class="card"><strong>Chat with DayBot</strong></div>', unsafe_allow_html=True)
        user_input = st.text_input("Your message:", key="input_box")
        if st.button("Send") and user_input:
            st.session_state.chat_history.append({"from":"user","msg":user_input})
            ok, ai_msg = call_ai(f"{SYSTEM_PROMPT}\nUser: {user_input}")
            if not ok:
                ok, ai_msg = mock_ai(user_input)
            st.session_state.chat_history.append({"from":"bot","msg":ai_msg})
            st.session_state.input_box = ""

        for msg in st.session_state.chat_history:
            if msg["from"]=="user":
                st.markdown(f"<div class='card'><strong>You:</strong> {msg['msg']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='card'><strong>{DAYBOT_NAME}:</strong> {msg['msg']}</div>", unsafe_allow_html=True)

    elif tab == "Feed":
        st.markdown('<div class="card"><strong>Feed</strong></div>', unsafe_allow_html=True)
        feed = read_feed_for_user()
        for f in feed:
            st.markdown(f"<div class='card'><strong>{f['user']}</strong> ({f['time']})<br>{f['text']}<br><em>Suggestions:</em> {', '.join(f.get('suggestions',[]))}</div>", unsafe_allow_html=True)

# ------------------------
# Supabase auth wrappers
# ------------------------
def supa_sign_up(email, password):
    if not SUPABASE_CONFIGURED:
        return False, "Supabase not configured - falling back to local signup."
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        return True, res
    except Exception as e:
        return False, str(e)

def supa_sign_in(email, password):
    if not SUPABASE_CONFIGURED:
        return False, "Supabase not configured - falling back to local login."
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        # If login succeeds, save session locally
        st.session_state.user = email
        save_session()
        return True, res
    except Exception as e:
        return False, str(e)
        
# ------------------------------
# Mock database stored in session (since Streamlit Cloud doesn't allow file writes)
# ------------------------------
if "users" not in st.session_state:
    st.session_state.users = {
        "admin": {"password": "admin123"}  # default admin user
    }nd st.session_state.logged_in:
    main_app()
else:
    login_page()
import streamlit as st

if "page" not in st.session_state:
    st.session_state.page = "login"
if "users" not in st.session_state:
    st.session_state.users = {"admin": {"password": "admin123"}}

def show_login():
    st.title("🔑 Login")
    username = st.text_input("Username", key="login_username")
    password = st.text_input("Password", type="password", key="login_password")
    if st.button("Login"):
        users = st.session_state.users
        if username in users and users[username]["password"] == password:
            st.session_state.current_user = username
            st.session_state.page = "main"
        else:
            st.error("Invalid credentials")

def show_signup():
    st.title("🆕 Sign Up")
    username = st.text_input("New username", key="signup_username")
    password = st.text_input("New password", type="password", key="signup_password")
    if st.button("Sign Up"):
        users = st.session_state.users
        if username in users:
            st.error("User already exists.")
        else:
            users[username] = {"password": password}
            st.session_state.users = users
            st.session_state.current_user = username
            st.session_state.page = "main"

def show_main():
    st.sidebar.write(f"👋 Welcome, {st.session_state.current_user}")
    if st.sidebar.button("Logout"):
        st.session_state.page = "login"
        st.session_state.current_user = None
    st.title("📅 DayByDay")
    st.write("Your friendly AI project planner — DayBot helps every task.")

# --------------------------
# Router
# --------------------------
if st.session_state.page == "login":
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    with tab1:
        show_login()
    with tab2:
        show_signup()
elif st.session_state.page == "main":
    show_main()
