import streamlit as st
st.set_page_config(page_title="DayByDay", page_icon="📅", layout="wide")
# app.py
"""
DayByDay — Full interactive Streamlit app
"""
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv


# ✅ Must come before ANY Streamlit element
APP_NAME = "DayByDay"

# ✅ Everything else comes after this
load_dotenv()

# Example safe code below
st.markdown(f"## Welcome to {APP_NAME}")

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

# ------------------------
# Config & env
# ------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"

# Supabase config from env (or you can hardcode)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")  # e.g. https://xxxx.supabase.co
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # anon key
SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_KEY and create_client is not None)

supabase = None
if SUPABASE_CONFIGURED:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        supabase = None
        SUPABASE_CONFIGURED = False

APP_NAME = "DayByDay"
DAYBOT_NAME = "DayBot"

# Files (local persistence fallback)
USERS_FILE = "users.json"        # now maps email -> {username, created_at, password? (for local fallback)}
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"
FEED_FILE = "feed.json"
EXAMPLES_FILE = "ai_examples.json"

# ensure files exist (fallback)
def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

for p, d in [
    (USERS_FILE, {}), (PROJECTS_FILE, {}), (SESSION_FILE, {}), (FEED_FILE, []), (EXAMPLES_FILE, [])
]:
    ensure_file(p, d)

# configure AI if key present
if GEMINI_API_KEY and genai:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        # will fallback at call time
        pass

# ------------------------
# Streamlit page config and CSS
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
.sidebar-buttons > div {{ margin-bottom:8px; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="header"><h1 style="margin:0">📅 {APP_NAME}</h1><div class="small">Your friendly AI project planner — DayBot helps every task.</div></div>', unsafe_allow_html=True)

# ------------------------
# JSON helpers (fallback)
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
# Session state initialization (must run before UI)
# ------------------------
if "user" not in st.session_state:
    st.session_state.user = None  # app identity: either username (preferred) or email fallback
if "user_email" not in st.session_state:
    st.session_state.user_email = None  # the logged-in email (for Supabase)
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"  # controlled only after login
if "project" not in st.session_state:
    st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_ai_error" not in st.session_state:
    st.session_state.last_ai_error = None
if "chat_pref" not in st.session_state:
    st.session_state.chat_pref = None  # used when Ask DayBot clicked; structure: {"day":int, "task_text":str}
if "chat_pref_processed" not in st.session_state:
    st.session_state.chat_pref_processed = False

# ------------------------
# Persistence helpers: session & projects (Supabase when available)
# ------------------------
def save_session():
    # session.json kept for local state; store login_expires if present
    payload = {
        "active_tab": st.session_state.get("active_tab"),
        "user": st.session_state.get("user"),
        "user_email": st.session_state.get("user_email"),
        "project": st.session_state.get("project"),
        "chat_history": st.session_state.get("chat_history", []),
        "login_expires": st.session_state.get("login_expires")
    }
    write_json(SESSION_FILE, payload)

def load_session():
    data = read_json(SESSION_FILE, {})
    # expire check: if login_expires present and in the past, clear user
    login_expires = data.get("login_expires")
    if login_expires:
        try:
            exp = datetime.fromisoformat(login_expires)
            if exp < datetime.utcnow():
                # expired -> do not restore user
                data.pop("user", None)
                data.pop("user_email", None)
                data.pop("login_expires", None)
            # else keep
        except Exception:
            pass
    for k in ["active_tab", "user", "user_email", "project", "chat_history", "login_expires"]:
        if k in data:
            st.session_state[k] = data[k]

# load persisted session on start (local fallback). We'll validate Supabase session below if available.
load_session()

import streamlit as st
import json
import os

# ========== Simple user storage ==========
USER_FILE = "users.json"

# Create empty file if not exists
if not os.path.exists(USER_FILE):
    with open(USER_FILE, "w") as f:
        json.dump({}, f)

def load_users():
    with open(USER_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USER_FILE, "w") as f:
        json.dump(users, f, indent=4)

# ========== Auth functions ==========
def signup(username, password):
    users = load_users()
    if username in users:
        return False, "Username already exists!"
    users[username] = {"password": password}
    save_users(users)
    return True, "Sign-up successful!"

def login(username, password):
    users = load_users()
    if username not in users:
        return False, "User not found!"
    if users[username]["password"] != password:
        return False, "Incorrect password!"
    return True, "Login successful!"

# ========== Navigation Helper ==========
def redirect_to(page):
    st.session_state.active_tab = page

# ========== App Setup ==========
st.set_page_config(page_title="DayByDay", layout="wide")

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Login"
if "username" not in st.session_state:
    st.session_state.username = None

# ========== Sidebar ==========
def sidebar():
    with st.sidebar:
        st.markdown("### ☰ Navigation")
        tabs = ["Home", "Planner", "Chat", "Feed"]
        choice = st.radio("Go to", tabs, label_visibility="collapsed")

        if st.button("Logout", key="logout", help="Log out and return to login"):
            st.session_state.username = None
            redirect_to("Login")

        return choice

# ========== Pages ==========
def show_login():
    st.title("🔐 Login to DayByDay")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, msg = login(username, password)
        if ok:
            st.session_state.username = username
            redirect_to("Home")
        else:
            st.error(msg)

    st.markdown("Don't have an account?")
    if st.button("Sign Up"):
        redirect_to("Signup")

def show_signup():
    st.title("📝 Create your DayByDay Account")
    username = st.text_input("Choose a Username")
    password = st.text_input("Choose a Password", type="password")

    if st.button("Sign Up"):
        ok, msg = signup(username, password)
        if ok:
            st.success(msg)
            redirect_to("Login")
        else:
            st.error(msg)

    if st.button("Back to Login"):
        redirect_to("Login")

def show_home():
    st.title(f"👋 Welcome, {st.session_state.username}!")
    st.write("This is your Home Page.")
    if st.button("Generate Project"):
        redirect_to("Planner")

def show_planner():
    st.title("🗓️ Planner")
    st.write("Here you can plan your day and manage tasks.")

def show_chat():
    st.title("💬 Chat")
    st.write("Chat with your AI assistant here.")

def show_feed():
    st.title("📢 Feed")
    st.write("View updates and posts here.")

# ========== Router ==========
if st.session_state.active_tab == "Login":
    show_login()
elif st.session_state.active_tab == "Signup":
    show_signup()
else:
    current_tab = sidebar()

    if current_tab == "Home":
        show_home()
    elif current_tab == "Planner":
        show_planner()
    elif current_tab == "Chat":
        show_chat()
    elif current_tab == "Feed":
        show_feed()

def supa_get_user_from_token():
    """Try to read stored token in SESSION_FILE and validate with Supabase; return user email or None."""
    if not SUPABASE_CONFIGURED:
        return None
    sess = read_json(SESSION_FILE, {})
    token = sess.get("supabase_token")
    if not token:
        return None
    try:
        # newer client has get_user or get_user_by_cookie; try generic API
        if hasattr(supabase.auth, "get_user"):
            user_info = supabase.auth.get_user(token)
            if isinstance(user_info, dict) and user_info.get("data") and user_info["data"].get("user"):
                return user_info["data"]["user"].get("email")
            if hasattr(user_info, "user"):
                return getattr(user_info, "user").get("email")
        return None
    except Exception:
        return None

# ------------------------
# Save / load projects & feed (Supabase when available)
# ------------------------
def save_project_to_history():
    """Persist current project: to Supabase if configured, otherwise to local JSON (projects.json)."""
    if SUPABASE_CONFIGURED and st.session_state.get("user_email"):
        try:
            payload = {
                "user_email": st.session_state["user_email"],
                "project_json": json.dumps(st.session_state["project"]),
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("projects").insert(payload).execute()
            return True
        except Exception:
            # fallback to local
            pass
    # local fallback - keyed by email if available else username
    projects = read_json(PROJECTS_FILE, {})
    user_key = st.session_state.user_email or st.session_state.user or "anonymous"
    user_projects = projects.get(user_key, [])
    user_projects.append(st.session_state.project.copy())
    projects[user_key] = user_projects
    write_json(PROJECTS_FILE, projects)
    return True

def load_last_project_for_user():
    """Return last saved project for the current user or None."""
    user_email = st.session_state.get("user_email")
    user = st.session_state.get("user")
    if SUPABASE_CONFIGURED and user_email:
        try:
            res = supabase.table("projects").select("*").eq("user_email", user_email).order("created_at", {"ascending": False}).limit(1).execute()
            data = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)
            if data and len(data) > 0:
                item = data[0]
                pj = item.get("project_json") or item.get("project_json")
                if isinstance(pj, str):
                    pj = json.loads(pj)
                return pj
        except Exception:
            pass
    # fallback local: check by email first, then username
    projects = read_json(PROJECTS_FILE, {})
    if user_email and projects.get(user_email):
        return projects.get(user_email)[-1]
    if user and projects.get(user):
        return projects.get(user)[-1]
    return None

def add_feed_post_supabase(user, text):
    """Save feed post to Supabase or fallback local."""
    entry = {"user": user, "text": text, "time": datetime.utcnow().isoformat()}
    ok, suggestions = ai_suggest_next_steps_from_post(text)
    if not ok:
        suggestions = ["Keep going — small steps build momentum.", "Review what worked.", "Plan one small win tomorrow."]
    entry["suggestions"] = suggestions
    if SUPABASE_CONFIGURED and st.session_state.get("user_email"):
        try:
            payload = {
                "user_email": st.session_state["user_email"],
                "text": text,
                "suggestions": json.dumps(suggestions),
                "created_at": datetime.utcnow().isoformat()
            }
            supabase.table("feed").insert(payload).execute()
            return entry
        except Exception:
            pass
    # fallback local
    feed = read_json(FEED_FILE, [])
    feed.insert(0, entry)
    write_json(FEED_FILE, feed)
    return entry

def read_feed_for_user():
    """Read feed (global) — Supabase if configured, else local."""
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
# redirect helper (no rerun) - kept simple & fast
# ------------------------
def redirect_to(tab_name: str, save=True):
    st.session_state.active_tab = tab_name
    if save:
        save_session()
    # do not call experimental rerun: rely on natural rerun from widgets

# ------------------------
# AI helpers (unchanged)
# ------------------------
SYSTEM_PROMPT = (
    f"You are {DAYBOT_NAME}, an encouraging, practical project assistant. "
    "Always reply with short actionable steps, task improvements, and time estimates when relevant. "
    "Do not reveal technical internals or model names."
)

def call_ai(prompt, max_tokens=600):
    """Try generate_text then GenerativeModel; return (ok, text)."""
    if not GEMINI_API_KEY or genai is None:
        return False, "ERROR_NO_API_KEY"
    errors = []
    # try generate_text if available
    try:
        if hasattr(genai, "generate_text"):
            resp = genai.generate_text(model=MODEL_NAME, prompt=prompt, temperature=0.7, max_output_tokens=max_tokens)
            text = getattr(resp, "text", None) or str(resp)
            return True, text.strip()
    except Exception as e:
        errors.append(f"generate_text: {e}")
    # try GenerativeModel
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or str(resp)
        return True, text.strip()
    except Exception as e:
        errors.append(f"GenerativeModel: {e}")
    return False, " | ".join(errors)

def mock_generate_plan(title, constraints):
    base = ""
    for i in range(1,9):
        base += f"Day {i}: Focus on part {i}\n- Tasks:\n  1) Do step A - 1h\n  2) Do step B - 2h\n\n"
    return base

def generate_8day_plan(title, constraints):
    prompt = SYSTEM_PROMPT + "\n\nGenerate an 8-day plan for the project below. Use simple Day N headers and 2-4 short tasks per day.\n"
    prompt += f"Project title: {title}\nConstraints: {constraints}\n\nFormat:\nDay 1: <title>\n- Tasks:\n  1) ... - 1h\n"
    ok, text = call_ai(prompt)
    if not ok:
        st.session_state.last_ai_error = text
        return mock_generate_plan(title, constraints)
    return text

def ask_daybot_for_task_improvement(day_index, task_text, project_title):
    prompt = SYSTEM_PROMPT + f"\n\nProject: {project_title}\nContext: Day {day_index+1}\nTask: {task_text}\n\nGive 1-2 concise improved versions of this task and a short reason why (1 line each). Number them."
    ok, resp = call_ai(prompt, max_tokens=200)
    if not ok:
        return False, "DayBot unavailable. Try again later."
    return True, resp

def ask_daybot_for_day_update(day_index, day_tasks, project_title, user_request):
    # day_tasks is list of texts
    context = "\n".join(f"- {t}" for t in day_tasks)
    prompt = SYSTEM_PROMPT + f"\n\nProject: {project_title}\nContext: Day {day_index+1} tasks:\n{context}\nUser request: {user_request}\nRespond with updated tasks list (short bullets) and 1-line summary."
    ok, resp = call_ai(prompt, max_tokens=400)
    if not ok:
        return False, "DayBot unavailable. Try again later."
    return True, resp

def ai_suggest_next_steps_from_post(post_text):
    prompt = SYSTEM_PROMPT + f"\n\nUser posted progress: {post_text}\nProvide 3 concise next-step suggestions the user can do tomorrow (one line each)."
    ok, resp = call_ai(prompt, max_tokens=200)
    if not ok:
        return False, ["Keep going — small steps build momentum.", "Review what worked today.", "Prioritize one small win tomorrow."]
    lines = [l.strip("- ").strip() for l in resp.splitlines() if l.strip()]
    # take up to 3
    return True, lines[:3] if lines else ["Keep going — small steps build momentum."]

# ------------------------
# Plan parsing utilities (unchanged)
# ------------------------
def parse_plan_to_tasks(plan_text):
    days = [""] * 8
    for i in range(1, 9):
        token = f"Day {i}"
        idx = plan_text.find(token)
        if idx != -1:
            next_token = f"Day {i+1}"
            end = plan_text.find(next_token, idx+1)
            days[i-1] = plan_text[idx:end].strip() if end != -1 else plan_text[idx:].strip()
    parsed = []
    tid = 0
    for d in days:
        tasks = []
        if not d:
            parsed.append(tasks)
            continue
        for line in d.splitlines():
            l = line.strip()
            if l and not l.lower().startswith("day") and not l.lower().startswith("- goal"):
                if l.startswith("- "):
                    t = l[2:].strip()
                elif l[0].isdigit() and (l[1] in ")."):
                    t = l.split(")", 1)[1].strip() if ")" in l else l
                else:
                    t = l
                if t:
                    tasks.append({"id": tid, "text": t, "done": False})
                    tid += 1
        parsed.append(tasks)
    while len(parsed) < 8:
        parsed.append([])
    return parsed[:8]

def plan_progress_percent(tasks_lists):
    total = 0
    done = 0
    for day in tasks_lists:
        for t in day:
            total += 1
            if t.get("done"):
                done += 1
    return int(done*100/total) if total else 0

# ------------------------
# Local auth helpers (fallback) - left intact but not used when Supabase is configured
# ------------------------
def signup_user(username, password, email=None):
    users = read_json(USERS_FILE, {})
    key = email if email else username
    if key in users:
        return False, "Username/email already exists."
    users[key] = {"username": username, "password": password, "created_at": datetime.utcnow().isoformat(), "email": email}
    write_json(USERS_FILE, users)
    return True, "Account created."

def login_user(username_or_email, password):
    users = read_json(USERS_FILE, {})
    # try find by email first then by username
    for key, val in users.items():
        if (val.get("email") == username_or_email or key == username_or_email or val.get("username") == username_or_email) and val.get("password") == password:
            st.session_state.user = val.get("username") or key
            st.session_state.user_email = val.get("email") or key
            st.session_state.login_expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
            save_session()
            return True, "Logged in."
    return False, "Invalid credentials."

# ------------------------
# Feed helper (wrapped)
# ------------------------
def add_feed_post(user, text):
    return add_feed_post_supabase(user, text)

# ------------------------
# UI: Login enforced landing (now uses Supabase when available)
# ------------------------
def login_screen():
    st.markdown('<div class="card"><strong>Welcome — Log in to start DayByDay</strong></div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        # left column: Email login (Supabase) or local fallback
        email = st.text_input("Email", key="login_input")
        pwd = st.text_input("Password", type="password", key="password_input")
        if st.button("Login", key="login_btn"):
            if SUPABASE_CONFIGURED:
                ok, res = supa_sign_in(email.strip(), pwd)
                if ok:
                    st.success("Logged in (Supabase).")
                    # user & user_email set inside supa_sign_in
                    redirect_to("Home")
                else:
                    st.error(f"Login failed: {res}")
            else:
                ok, msg = login_user(email.strip(), pwd)
                if ok:
                    st.success(msg)
                    redirect_to("Home")
                else:
                    st.error(msg)
    with col2:
        # right column: Email sign up (Supabase) or local fallback
        new_username = st.text_input("Your name (username)", key="signup_name_input")
        new_email = st.text_input("New email", key="signup_user_input")
        new_pwd = st.text_input("New password", type="password", key="signup_pass_input")
        if st.button("Sign Up", key="signup_btn"):
            if not new_email.strip() or not new_pwd.strip() or not new_username.strip():
                st.error("Enter name, email & password.")
            else:
                if SUPABASE_CONFIGURED:
                    ok, res = supa_sign_up(new_email.strip(), new_pwd, username=new_username.strip())
                    if ok:
                        # store mapping locally so app shows username for this email
                        users = read_json(USERS_FILE, {})
                        users[new_email.strip()] = {"username": new_username.strip(), "created_at": datetime.utcnow().isoformat()}
                        write_json(USERS_FILE, users)
                        st.success("Sign-up initiated. Check your email for confirmation if required.")
                        # do not auto login to avoid verification issues
                    else:
                        st.error(f"Sign-up failed: {res}")
                else:
                    ok, m = signup_user(new_username.strip(), new_pwd, email=new_email.strip())
                    if ok:
                        st.success(m)
                        st.session_state.user = new_username.strip()
                        st.session_state.user_email = new_email.strip()
                        st.session_state.login_expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
                        save_session()
                        redirect_to("Home")
                    else:
                        st.error(m)
    st.markdown("<div class='small'>If Supabase is configured, we use secure email auth. Otherwise this demo stores credentials locally. Your 'name' is the app display name.</div>", unsafe_allow_html=True)

# ------------------------
# Sidebar (3-line vertical) - navigation & logout
# ------------------------
def render_sidebar():
    # Sidebar header
    st.sidebar.markdown(f"### {APP_NAME}")
    st.sidebar.markdown(f"Welcome, **{st.session_state.user}** 👋")

    # Navigation
    tabs = ["Home", "Planner", "Chat", "Feed"]
    selected_tab = st.sidebar.radio("Navigate", tabs, index=tabs.index(st.session_state.active_tab))
    st.session_state.active_tab = selected_tab
    save_session()

    # Spacer to push logout to bottom
    st.sidebar.markdown("<div style='flex:1; height:250px;'></div>", unsafe_allow_html=True)

    # Logout section (bottom fixed)
    st.sidebar.markdown("---")
    logout = st.sidebar.button("Logout")
    if logout:
        # Clear user session (no rerun)
        if SUPABASE_CONFIGURED:
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
        st.session_state.user = None
        st.session_state.active_tab = "Home"
        save_session()
        st.sidebar.success("You’ve been logged out.")

    st.sidebar.markdown(
        "<p style='text-align:center; color:gray; font-size:12px;'>DayByDay © 2025</p>",
        unsafe_allow_html=True
    )

# ------------------------
# UI: Top tabs and pages (only after login)
# ------------------------
def render_app_ui():
    # render sidebar first
    render_sidebar()

    tabs = st.tabs(["Home", "Planner", "Chat", "Feed"])
    # Home tab
    with tabs[0]:
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
                # clear current project
                st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
                save_session()
                redirect_to("Planner")
        st.markdown("---")
        if st.button("Logout", key="logout_btn"):
            # Logout: clear local session and try to sign out Supabase client
            if SUPABASE_CONFIGURED:
                try:
                    supabase.auth.sign_out()
                except Exception:
                    pass
            st.session_state.user = None
            st.session_state.user_email = None
            sess = read_json(SESSION_FILE, {})
            sess.pop("supabase_token", None)
            sess.pop("supabase_token_expires", None)
            sess.pop("login_expires", None)
            write_json(SESSION_FILE, sess)
            save_session()
            st.success("Logged out.")
            st.stop()

    # Planner tab
    with tabs[1]:
        st.markdown('<div class="card"><strong>Planner</strong> — AI-powered 8-day cards</div>', unsafe_allow_html=True)
        col1, col2 = st.columns([3,1])
        with col1:
            title = st.text_input("Project title", value=st.session_state.project.get("title",""), key="proj_title_input")
            constraints = st.text_area("Notes / constraints (optional)", value=st.session_state.project.get("constraints",""), height=80, key="proj_constraints_input")
        with col2:
            if st.button("Generate 8-day Plan (DayBot)", key="generate_plan_btn"):
                if not title.strip():
                    st.error("Enter a project title first.")
                else:
                    st.session_state.project["title"] = title.strip()
                    st.session_state.project["constraints"] = constraints.strip()
                    with st.spinner("DayBot is creating your plan..."):
                        plan_text = generate_8day_plan(title.strip(), constraints.strip())
                        st.session_state.project["raw_plan"] = plan_text
                        st.session_state.project["generated_at"] = datetime.utcnow().isoformat()
                        st.session_state.project["tasks"] = parse_plan_to_tasks(plan_text)
                        save_project_to_history()
                        save_session()
                    st.success("Plan generated and loaded into cards.")
        st.markdown("---")
        # Show day cards with interactive tasks
        tasks = st.session_state.project.get("tasks", [[] for _ in range(8)])
        for d in range(8):
            with st.container():
                st.markdown(f'<div class="day-card"><strong>Day {d+1}</strong></div>', unsafe_allow_html=True)
                day_tasks = tasks[d]
                if not day_tasks:
                    st.info("Not done yet — empty.")
                else:
                    for t in day_tasks:
                        cols = st.columns([0.05, 0.7, 0.15, 0.1])
                        checked = cols[0].checkbox("", value=t.get("done", False), key=f"chk_{d}_{t['id']}")
                        if checked != t.get("done"):
                            t["done"] = checked
                            save_session()
                        new_text = cols[1].text_input("", value=t.get("text",""), key=f"txt_{d}_{t['id']}") 
                        if new_text != t.get("text"):
                            t["text"] = new_text
                            save_session()
                        # --- Ask DayBot button now opens Chat with prefilled context and auto-asks AI ---
                        if cols[2].button("Ask DayBot", key=f"ask_{d}_{t['id']}"):
                            # set chat_pref and switch to Chat
                            st.session_state.chat_pref = {"day": d, "task_text": t.get("text",""), "project_title": st.session_state.project.get("title","")}
                            st.session_state.chat_pref_processed = False
                            save_session()
                            redirect_to("Chat")
                        if cols[3].button("Remove", key=f"rm_{d}_{t['id']}"):
                            st.session_state.project["tasks"][d] = [tt for tt in st.session_state.project["tasks"][d] if tt["id"] != t["id"]]
                            save_session()
                add_col1, add_col2 = st.columns([4,1])
                new_task = add_col1.text_input(f"Add task Day {d+1}", key=f"add_{d}_input")
                if add_col2.button("Add", key=f"add_btn_{d}"):
                    if new_task.strip():
                        all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                        new_id = (max(all_ids) + 1) if all_ids else 0
                        st.session_state.project["tasks"][d].append({"id": new_id, "text": new_task.strip(), "done": False})
                        save_session()
                # Day controls
                tot = len(st.session_state.project["tasks"][d])
                done = sum(1 for tt in st.session_state.project["tasks"][d] if tt.get("done"))
                st.markdown(f"**{done}/{tot} done**")
                if st.button("Regenerate Day with DayBot", key=f"regen_day_{d}"):
                    context = [tt.get("text","") for tt in st.session_state.project["tasks"][d]]
                    ok, resp = ask_daybot_for_day_update(d, context, st.session_state.project.get("title",""), "Rewrite and optimize tasks for clarity and time estimates.")
                    if ok:
                        lines = [l.strip("- ").strip() for l in resp.splitlines() if l.strip()]
                        new_tasks = []
                        all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                        nid = (max(all_ids) + 1) if all_ids else 0
                        for ln in lines[:6]:
                            new_tasks.append({"id": nid, "text": ln, "done": False})
                            nid += 1
                        st.session_state.project["tasks"][d] = new_tasks
                        save_session()
                        st.success("Day regenerated by DayBot.")
                if st.button("Clear Day", key=f"clear_day_{d}"):
                    st.session_state.project["tasks"][d] = []
                    save_session()
                st.markdown("---")
        # bottom controls
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            if st.button("Save Project", key="save_project_btn"):
                save_project_to_history()
                st.success("Project saved to history.")
        with c2:
            if st.button("Export TXT", key="export_txt_btn"):
                txt = ""
                for i,day in enumerate(st.session_state.project["tasks"], start=1):
                    txt += f"Day {i}:\n"
                    for tt in day:
                        txt += f"- {tt['text']}\n"
                    txt += "\n"
                st.download_button("Download TXT", txt, file_name="daybyday_plan.txt", mime="text/plain", key="download_txt")
        with c3:
            if st.button("Open Chat (DayBot)", key="open_chat_btn"):
                redirect_to("Chat")

    # Chat tab
    with tabs[2]:
        st.markdown('<div class="card"><strong>Chat — DayBot</strong></div>', unsafe_allow_html=True)
        st.markdown("<div class='small'>Ask DayBot to edit the plan, expand tasks, or give coaching.</div>", unsafe_allow_html=True)

        # if Ask DayBot from Planner created a chat_pref and not yet processed, auto-call AI
        if st.session_state.get("chat_pref") and not st.session_state.get("chat_pref_processed"):
            pref = st.session_state.chat_pref
            day_idx = pref.get("day")
            task_text = pref.get("task_text")
            project_title = pref.get("project_title", "")
            # Build prompt and call AI automatically to improve this task
            prompt = SYSTEM_PROMPT + f"\n\nProject: {project_title}\nContext: Day {day_idx+1}\nTask: {task_text}\n\nUser asked: Improve this task and give 2 alternatives and a quick reason each."
            ok, reply = call_ai(prompt, max_tokens=300)
            if not ok:
                st.session_state.chat_history.append({"role":"DayBot", "text": "DayBot unavailable — try again later.", "time": datetime.utcnow().isoformat()})
                st.session_state.last_ai_error = reply
            else:
                st.session_state.chat_history.append({"role":"user", "text": f"Improve task: {task_text}", "time": datetime.utcnow().isoformat()})
                st.session_state.chat_history.append({"role":"DayBot", "text": reply, "time": datetime.utcnow().isoformat()})
            st.session_state.chat_pref_processed = True
            save_session()

        for msg in st.session_state.chat_history[-30:]:
            role = msg.get("role")
            text = msg.get("text")
            time = msg.get("time", "")[:19]
            if role == "user":
                st.markdown(f"**You ({time}):** {text}")
            else:
                st.markdown(f"**DayBot ({time}):** {text}")
        st.markdown("---")
        context_choice = st.selectbox("Context:", ["Whole project"] + [f"Day {i+1}" for i in range(8)], key="chat_context_select")
        user_msg = st.text_input("Your message to DayBot", key="chat_input_box")
        if st.button("Send", key="chat_send_btn"):
            if not user_msg.strip():
                st.warning("Type a message first.")
            else:
                st.session_state.chat_history.append({"role":"user", "text":user_msg.strip(), "time": datetime.utcnow().isoformat()})
                if context_choice == "Whole project":
                    context = st.session_state.project.get("raw_plan", "") or "\n".join([t["text"] for d in st.session_state.project["tasks"] for t in d])
                else:
                    idx = int(context_choice.split()[1]) - 1
                    context = "\n".join([t.get("text","") for t in st.session_state.project["tasks"][idx]])
                prompt = SYSTEM_PROMPT + f"\n\nContext:\n{context}\n\nUser request: {user_msg.strip()}\nRespond concisely; if you return updated tasks, format as bullet lines."
                ok, reply = call_ai(prompt, max_tokens=600)
                if not ok:
                    st.session_state.chat_history.append({"role":"DayBot", "text": "DayBot is unavailable — try again later.", "time": datetime.utcnow().isoformat()})
                    st.session_state.last_ai_error = reply
                else:
                    st.session_state.chat_history.append({"role":"DayBot", "text": reply, "time": datetime.utcnow().isoformat()})
                save_session()
        # option to import last DayBot reply into plan
        if st.session_state.chat_history:
            last = st.session_state.chat_history[-1]
            if last.get("role") == "DayBot" and "Day" in last.get("text", "") and st.button("Import last DayBot reply into tasks", key="import_chat_reply_btn"):
                parsed = parse_plan_to_tasks(last["text"])
                for i in range(8):
                    for t in parsed[i]:
                        all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                        nid = (max(all_ids) + 1) if all_ids else 0
                        st.session_state.project["tasks"][i].append({"id": nid, "text": t["text"], "done": False})
                save_session()
                st.success("Imported AI reply into project tasks.")

    # Feed tab
    with tabs[3]:
        st.markdown('<div class="card"><strong>Feed</strong></div>', unsafe_allow_html=True)
        st.markdown("Share quick progress updates and get AI next-step suggestions.")
        if st.session_state.user:
            post_text = st.text_area("What's your progress? (short)", height=80, key="feed_input_box")
            if st.button("Post update", key="feed_post_btn"):
                if not post_text.strip():
                    st.warning("Write something first.")
                else:
                    entry = add_feed_post(st.session_state.user, post_text.strip())
                    save_session()
                    st.success("Posted. AI suggested next steps.")
        st.markdown("---")
        feed = read_feed_for_user()
        if not feed:
            st.info("No posts yet.")
        else:
            for e in feed[:50]:
                st.markdown(f"**{e.get('user','unknown')}** • {e.get('time','')[:19]}")
                st.markdown(e.get('text',''))
                suggs = e.get("suggestions", [])
                if suggs:
                    st.markdown("**AI next steps:**")
                    for s in suggs:
                        st.markdown(f"- {s}")
                st.markdown("---")

# ------------------------
# Main routing: enforce login
# ------------------------
# Try to auto-validate stored Supabase token (if any)
if SUPABASE_CONFIGURED and not st.session_state.user:
    try:
        validated_email = supa_get_user_from_token()
        if validated_email:
            st.session_state.user_email = validated_email
            # set username if local mapping exists
            users_map = read_json(USERS_FILE, {})
            mapped = users_map.get(validated_email, {})
            st.session_state.user = mapped.get("username") or validated_email
            # set login_expires from session file if exists (already loaded in load_session)
    except Exception:
        pass

if not st.session_state.user:
    # show only login/signup
    login_screen()
else:
    # If user has no project loaded, attempt to load last project from Supabase/local
    if not st.session_state.project.get("title"):
        last_proj = load_last_project_for_user()
        if last_proj:
            st.session_state.project = last_proj
    render_app_ui()

# ------------------------
# Footer: last AI error debug (hidden unless error)
# ------------------------
if st.session_state.last_ai_error:
    st.markdown("---")
    st.markdown("**DayBot error (last):**")
    st.code(st.session_state.last_ai_error)
