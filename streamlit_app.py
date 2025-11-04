# app.py
"""
DayByDay — Full interactive Streamlit app
- Forced login/signup
- Top tabs (Home, Planner, Chat, Feed)
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

# Optional AI import
try:
    import google.generativeai as genai
except Exception:
    genai = None

# ------------------------
# Config & env
# ------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"

APP_NAME = "DayByDay"
DAYBOT_NAME = "DayBot"

# Files (local persistence)
USERS_FILE = "users.json"
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"
FEED_FILE = "feed.json"
EXAMPLES_FILE = "ai_examples.json"

# ensure files exist
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
st.set_page_config(page_title=APP_NAME, page_icon="📅", layout="wide")

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
# Session state initialization (must run before UI)
# ------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"  # controlled only after login
if "project" not in st.session_state:
    st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_ai_error" not in st.session_state:
    st.session_state.last_ai_error = None

# ------------------------
# Persistence helpers: session & projects
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
    for k in ["active_tab", "user", "project", "chat_history"]:
        if k in data:
            st.session_state[k] = data[k]

# load persisted session on start
load_session()

def save_project_to_history():
    projects = read_json(PROJECTS_FILE, {})
    user = st.session_state.user
    if not user:
        return
    user_projects = projects.get(user, [])
    user_projects.append(st.session_state.project.copy())
    projects[user] = user_projects
    write_json(PROJECTS_FILE, projects)

# ------------------------
# redirect helper (defined before use)
# ------------------------
def redirect_to(tab_name: str, save=True, rerun=True):
    st.session_state.active_tab = tab_name
    if save:
        save_session()
    if rerun:
        try:
            st.experimental_rerun()
        except Exception:
            try:
                st.rerun()
            except Exception:
                pass

# ------------------------
# AI helpers
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
# Plan parsing utilities
# ------------------------
def parse_plan_to_tasks(plan_text):
    # simple heuristic: split by "Day 1", "Day 2", ...
    days = [""] * 8
    for i in range(1, 9):
        token = f"Day {i}"
        idx = plan_text.find(token)
        if idx != -1:
            # find end
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
                # skip headers
                if l.startswith("- "):
                    t = l[2:].strip()
                elif l[0].isdigit() and (l[1] in ")."):
                    # "1) Do X"
                    t = l.split(")", 1)[1].strip() if ")" in l else l
                else:
                    t = l
                if t:
                    tasks.append({"id": tid, "text": t, "done": False})
                    tid += 1
        parsed.append(tasks)
    # ensure length 8
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
# Auth helpers
# ------------------------
def signup_user(username, password):
    users = read_json(USERS_FILE, {})
    if username in users:
        return False, "Username already exists."
    users[username] = {"password": password, "created_at": datetime.utcnow().isoformat()}
    write_json(USERS_FILE, users)
    return True, "Account created."

def login_user(username, password):
    users = read_json(USERS_FILE, {})
    if username in users and users[username].get("password") == password:
        st.session_state.user = username
        save_session()
        return True, "Logged in."
    return False, "Invalid credentials."

# ------------------------
# Feed helper
# ------------------------
def add_feed_post(user, text):
    feed = read_json(FEED_FILE, [])
    ok, suggestions = ai_suggest_next_steps_from_post(text)
    if not ok:
        suggestions = ["Keep going — small steps build momentum.", "Review what worked.", "Plan one small win tomorrow."]
    entry = {"user": user, "text": text, "time": datetime.utcnow().isoformat(), "suggestions": suggestions}
    feed.insert(0, entry)
    write_json(FEED_FILE, feed)
    return entry

# ------------------------
# UI: Login enforced landing
# ------------------------
def login_screen():
    st.markdown('<div class="card"><strong>Welcome — Log in to start DayByDay</strong></div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        uname = st.text_input("Username", key="login_input")
        pwd = st.text_input("Password", type="password", key="password_input")
        if st.button("Login", key="login_btn"):
            ok, msg = login_user(uname.strip(), pwd)
            if ok:
                st.success(msg)
                redirect_to("Home")
            else:
                st.error(msg)
    with col2:
        new_u = st.text_input("New username", key="signup_user_input")
        new_p = st.text_input("New password", type="password", key="signup_pass_input")
        if st.button("Sign Up", key="signup_btn"):
            if not new_u.strip() or not new_p.strip():
                st.error("Enter username & password.")
            else:
                ok, m = signup_user(new_u.strip(), new_p)
                if ok:
                    st.success(m)
                    st.session_state.user = new_u.strip()
                    save_session()
                    redirect_to("Home")
                else:
                    st.error(m)
    st.markdown("<div class='small'>Your credentials are stored locally for this demo. For production use secure server-side auth.</div>", unsafe_allow_html=True)

# ------------------------
# UI: Top tabs and pages (only after login)
# ------------------------
def render_app_ui():
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
            st.session_state.user = None
            save_session()
            st.success("Logged out.")
            st.experimental_rerun()

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
                        if cols[2].button("Ask DayBot", key=f"ask_{d}_{t['id']}"):
                            # Ask DayBot to improve this task
                            ok, reply = ask_daybot_for_task_improvement(d, t.get("text",""), st.session_state.project.get("title","(no title)"))
                            if not ok:
                                st.warning(reply)
                            else:
                                # Show suggestions and let user pick to replace
                                st.info("DayBot suggestions:")
                                for idx, line in enumerate(reply.splitlines(), start=1):
                                    st.write(f"{idx}. {line}")
                                # allow quick replace
                                if cols[3].button("Apply top suggestion", key=f"apply_{d}_{t['id']}"):
                                    first_line = reply.splitlines()[0] if reply.splitlines() else t.get("text")
                                    t["text"] = first_line
                                    save_session()
                                    st.success("Applied top suggestion.")
                                    st.experimental_rerun()
                        if cols[3].button("Remove", key=f"rm_{d}_{t['id']}"):
                            st.session_state.project["tasks"][d] = [tt for tt in st.session_state.project["tasks"][d] if tt["id"] != t["id"]]
                            save_session()
                            st.experimental_rerun()
                add_col1, add_col2 = st.columns([4,1])
                new_task = add_col1.text_input(f"Add task Day {d+1}", key=f"add_{d}_input")
                if add_col2.button("Add", key=f"add_btn_{d}"):
                    if new_task.strip():
                        # generate unique id
                        all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                        new_id = (max(all_ids) + 1) if all_ids else 0
                        st.session_state.project["tasks"][d].append({"id": new_id, "text": new_task.strip(), "done": False})
                        save_session()
                        st.experimental_rerun()
                # Day controls
                tot = len(st.session_state.project["tasks"][d])
                done = sum(1 for tt in st.session_state.project["tasks"][d] if tt.get("done"))
                st.markdown(f"**{done}/{tot} done**")
                if st.button("Regenerate Day with DayBot", key=f"regen_day_{d}"):
                    # Ask DayBot to rewrite this day using current tasks as context
                    context = [tt.get("text","") for tt in st.session_state.project["tasks"][d]]
                    ok, resp = ask_daybot_for_day_update(d, context, st.session_state.project.get("title",""), "Rewrite and optimize tasks for clarity and time estimates.")
                    if ok:
                        # parse resp into lines and replace tasks
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
                        st.experimental_rerun()
                if st.button("Clear Day", key=f"clear_day_{d}"):
                    st.session_state.project["tasks"][d] = []
                    save_session()
                    st.experimental_rerun()
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
        # show last 30 messages
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
                # build prompt depending on context
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
                st.experimental_rerun()
        # option to import last DayBot reply into plan
        if st.session_state.chat_history:
            last = st.session_state.chat_history[-1]
            if last.get("role") == "DayBot" and "Day" in last.get("text", "") and st.button("Import last DayBot reply into tasks", key="import_chat_reply_btn"):
                parsed = parse_plan_to_tasks(last["text"])
                for i in range(8):
                    # append parsed tasks
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
                    st.experimental_rerun()
        st.markdown("---")
        feed = read_json(FEED_FILE, [])
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
if not st.session_state.user:
    # show only login/signup
    login_screen()
else:
    render_app_ui()

# ------------------------
# Footer: last AI error debug (hidden unless error)
# ------------------------
if st.session_state.last_ai_error:
    st.markdown("---")
    st.markdown("**DayBot error (last):**")
    st.code(st.session_state.last_ai_error)
