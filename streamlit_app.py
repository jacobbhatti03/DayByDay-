# app.py
"""
DayByDay v2 — Full App with Top Tabs (Home | Planner | Chat | Feed)
Features:
- Local username/password sign-up & login
- Gemini 2.5 Flash integration (if GEMINI_API_KEY present)
- Editable 8-day planner (cards), progress tracking
- Chat with DayBot (context-aware)
- Feed posts + AI next-steps suggestions
- Persistent local storage (JSON files) so refresh doesn't lose state
"""

import os
import json
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv

# Optional import of google.generativeai
try:
    import google.generativeai as genai
except Exception:
    genai = None

# -------------------------
# Config & ENV
# -------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # safe
MODEL_NAME = "gemini-2.5-flash"

APP_NAME = "DayByDay"
DAYBOT_NAME = "DayBot"

# Storage files
USERS_FILE = "users.json"
PROJECTS_FILE = "projects.json"
SESSION_FILE = "session.json"
EXAMPLES_FILE = "ai_examples.json"
FEED_FILE = "feed.json"

# Ensure files
def ensure_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

ensure_file(USERS_FILE, {})
ensure_file(PROJECTS_FILE, {})
ensure_file(SESSION_FILE, {})
ensure_file(EXAMPLES_FILE, [])
ensure_file(FEED_FILE, [])

# If key present, configure
if GEMINI_API_KEY and genai:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        # ignore; call_ai will handle fallback
        pass

# -------------------------
# Streamlit page config & CSS
# -------------------------
st.set_page_config(page_title=APP_NAME, page_icon="📅", layout="wide")

ACCENT1 = "#7b2cbf"
ACCENT2 = "#ff6ec7"
BG = "#0f0f10"
TEXT = "#e9e6ee"

CSS = """
<style>
:root { --bg: %s; --accent1: %s; --accent2: %s; --text: %s; }
body { background: linear-gradient(180deg, #070607, #0f0f10); color: var(--text); }
.header { background: linear-gradient(90deg, var(--accent1), var(--accent2)); padding:12px; border-radius:10px; color:white; text-align:center; margin-bottom:12px; }
.card { background: rgba(255,255,255,0.02); border-radius:10px; padding:12px; margin-bottom:12px; border:1px solid rgba(255,255,255,0.03); }
.small { font-size:13px; color:#cfc2e7; }
.day-card { background: linear-gradient(135deg, rgba(123,44,191,0.06), rgba(255,110,199,0.03)); border-radius:10px; padding:12px; margin-bottom:10px; box-shadow: 0 6px 18px rgba(0,0,0,0.5); }
button.stButton>button { background: linear-gradient(90deg, var(--accent2), var(--accent1)); color:white; border-radius:8px; }
textarea { background: rgba(255,255,255,0.02); color:var(--text); }
</style>
""" % (BG, ACCENT1, ACCENT2, TEXT)

st.markdown(CSS, unsafe_allow_html=True)
st.markdown(f'<div class="header"><h1 style="margin:6px 0">📅 {APP_NAME}</h1><div class="small">Your AI-powered 8-day project planner</div></div>', unsafe_allow_html=True)

# -------------------------
# Utility: JSON read/write
# -------------------------
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# -------------------------
# Session state setup & persistence
# -------------------------
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Home"  # Home, Planner, Chat, Feed
if "user" not in st.session_state:
    st.session_state.user = None
if "project" not in st.session_state:
    st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_ai_error" not in st.session_state:
    st.session_state.last_ai_error = None

def save_session():
    payload = {
        "active_tab": st.session_state.get("active_tab", "Home"),
        "user": st.session_state.get("user"),
        "project": st.session_state.get("project"),
        "chat_history": st.session_state.get("chat_history", [])
    }
    write_json(SESSION_FILE, payload)

def load_session():
    data = read_json(SESSION_FILE, {})
    if not data:
        return
    if "active_tab" in data:
        st.session_state.active_tab = data["active_tab"]
    if "user" in data:
        st.session_state.user = data["user"]
    if "project" in data and data["project"]:
        st.session_state.project = data["project"]
    if "chat_history" in data:
        st.session_state.chat_history = data["chat_history"]

# load persisted session at start
load_session()

# redirect helper
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

# -------------------------
# DayBot & AI helpers
# -------------------------
SYSTEM_PROMPT = (
    f"You are {DAYBOT_NAME}, a friendly, concise project assistant. Always reply with short actionable steps. "
    "Do NOT mention model names, vendor names, or technical internals. Keep tone motivating and practical."
)

def build_prompt_for_plan(title, constraints):
    few = read_json(EXAMPLES_FILE, [])[-3:]
    few_text = ""
    for ex in few:
        few_text += f"INPUT IDEA: {ex.get('input_idea','')}\nORIGINAL PLAN:\n{ex.get('original_plan','')}\nUSER MODIFIED PLAN:\n{ex.get('user_modified_plan','')}\n\n"
    prompt = f"{SYSTEM_PROMPT}\n\n{few_text}Generate an 8-day plan for the project below.\nTitle: {title}\nConstraints: {constraints}\nFormat:\nDay 1: <title>\n- Tasks:\n  1) ... - 1h\nKeep it concise."
    return prompt

def call_ai_model(prompt):
    """Robust call: try generate_text first, then GenerativeModel.generate_content; fallback to error."""
    if not GEMINI_API_KEY or genai is None:
        return False, "ERROR_NO_API_KEY"
    errors = []
    # Try generate_text if available
    try:
        if hasattr(genai, "generate_text"):
            resp = genai.generate_text(model=MODEL_NAME, prompt=prompt, temperature=0.7, max_output_tokens=900)
            text = getattr(resp, "text", None) or str(resp)
            return True, text.strip()
    except Exception as e:
        errors.append(f"generate_text: {e}")
    # Try GenerativeModel as fallback
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None) or str(resp)
        return True, text.strip()
    except Exception as e:
        errors.append(f"GenerativeModel: {e}")
    return False, " | ".join(errors)

def mock_plan(title="Project", constraints=""):
    base = ""
    for i in range(1,9):
        base += f"Day {i}: Focus {i}\n- Goal: Make measurable progress on part {i}\n- Tasks:\n  1) Setup / prepare - 1h\n  2) Implement core part - 2h\n  3) Test & refine - 1h\n\n"
    return base

def generate_plan(title, constraints):
    prompt = build_prompt_for_plan(title, constraints)
    ok, res = call_ai_model(prompt)
    if not ok:
        st.session_state.last_ai_error = res
        return mock_plan(title, constraints)
    return res

# -------------------------
# Plan parsing and utilities
# -------------------------
def parse_plan_to_tasks(plan_text):
    days = [""] * 8
    positions = []
    for i in range(1,9):
        token = f"Day {i}"
        idx = plan_text.find(token)
        if idx != -1:
            positions.append((i, idx))
    if positions:
        positions.sort(key=lambda x: x[1])
        for idx, (day_num, pos) in enumerate(positions):
            start = pos
            end = positions[idx+1][1] if idx+1 < len(positions) else len(plan_text)
            days[day_num-1] = plan_text[start:end].strip()
    else:
        lines = [l for l in plan_text.splitlines() if l.strip()]
        n = max(1, len(lines)//8)
        chunks = ["\n".join(lines[i:i+n]) for i in range(0, len(lines), n)]
        for i in range(min(8, len(chunks))):
            days[i] = chunks[i]
    parsed = []
    tid = 0
    for d in days:
        tasks = []
        if not d.strip():
            parsed.append(tasks)
            continue
        for line in d.splitlines():
            l = line.strip()
            if l.startswith("- ") or (len(l) > 1 and l[0].isdigit() and l[1] in ")."):
                cleaned = l.lstrip("- ").split(")",1)[-1] if ")" in l else l.lstrip("- ")
                if " - " in cleaned:
                    cleaned = cleaned.split(" - ")[0].strip()
                if cleaned:
                    tasks.append({"id": tid, "text": cleaned.strip(), "done": False})
                    tid += 1
        if not tasks:
            fragments = [s.strip() for s in d.split(",") if s.strip()]
            for f in fragments[:3]:
                tasks.append({"id": tid, "text": f[:120], "done": False})
                tid += 1
        parsed.append(tasks)
    while len(parsed) < 8:
        parsed.append([])
    return parsed[:8]

def plan_progress_percent(tasks_lists):
    total = 0; done = 0
    for day in tasks_lists:
        for t in day:
            total += 1
            if t.get("done"):
                done += 1
    return int(done*100/total) if total else 0

# -------------------------
# Auth & storage helpers
# -------------------------
def signup(username, password):
    users = read_json(USERS_FILE, {})
    if username in users:
        return False, "Username exists"
    users[username] = {"password": password, "created_at": datetime.utcnow().isoformat()}
    write_json(USERS_FILE, users)
    return True, "Account created"

def login(username, password):
    users = read_json(USERS_FILE, {})
    if username in users and users[username].get("password") == password:
        st.session_state.user = username
        save_session()
        return True, "Logged in"
    return False, "Invalid credentials"

# -------------------------
# Feed helpers
# -------------------------
def add_feed_post(user, text):
    feed = read_json(FEED_FILE, [])
    entry = {"user": user, "text": text, "time": datetime.utcnow().isoformat()}
    # AI suggests next steps
    # build prompt
    prompt = f"{SYSTEM_PROMPT}\nUser progress post: {text}\nGive 3 short next steps the user can do tomorrow related to this progress."
    ok, ai_reply = call_ai_model(prompt)
    if not ok:
        suggestions = ["Keep going — small steps matter.", "Review what worked.", "Focus on one small win tomorrow."]
    else:
        # keep first 3 short lines
        suggestions = [line.strip() for line in ai_reply.splitlines() if line.strip()][:3]
    entry["suggestions"] = suggestions
    feed.insert(0, entry)
    write_json(FEED_FILE, feed)
    return entry

# -------------------------
# UI: Top Tabs
# -------------------------
tabs = st.tabs(["Home", "Planner", "Chat", "Feed"])
# Sync tab selection with session_state.active_tab
# Determine tab index from state
tab_labels = ["Home", "Planner", "Chat", "Feed"]
try:
    active_index = tab_labels.index(st.session_state.active_tab)
except Exception:
    active_index = 0

# Render tabs and update session_state when user clicks a tab
for i, t in enumerate(tabs):
    if i == active_index:
        with t:
            st.session_state.active_tab = tab_labels[i]
            # do nothing (render later)
    else:
        with t:
            # show a small click handler to switch
            if st.button(f"Open {tab_labels[i]}", key=f"open_tab_{i}"):
                redirect_to(tab_labels[i])

# Now render content based on session_state.active_tab
st.write("")  # spacer

# -------------------------
# Page: Home
# -------------------------
if st.session_state.active_tab == "Home":
    st.markdown('<div class="card"><strong>Welcome</strong> — quick project overview</div>', unsafe_allow_html=True)
    if not st.session_state.user:
        st.info("Please sign in or create an account to continue.")
        col1, col2 = st.columns(2)
        with col1:
            uname = st.text_input("Username", key="login_uname")
            pwd = st.text_input("Password", type="password", key="login_pwd")
            if st.button("Login"):
                ok, msg = login(uname.strip(), pwd)
                if ok:
                    st.success(msg)
                    redirect_to("Planner")
                else:
                    st.error(msg)
        with col2:
            su = st.text_input("New username", key="signup_uname")
            sp = st.text_input("New password", type="password", key="signup_pwd")
            if st.button("Sign Up"):
                if not su.strip() or not sp.strip():
                    st.error("Enter username and password")
                else:
                    ok, m = signup(su.strip(), sp.strip())
                    if ok:
                        st.success(m)
                        st.session_state.user = su.strip()
                        save_session()
                        redirect_to("Planner")
                    else:
                        st.error(m)
    else:
        st.markdown(f"**Hello, {st.session_state.user}**")
        if st.session_state.project.get("title"):
            st.markdown(f"Current project: **{st.session_state.project.get('title')}**")
            progress = plan_progress_percent(st.session_state.project.get("tasks", []))
            st.markdown(f"Overall progress: **{progress}%**")
            st.progress(progress)
        else:
            st.info("No active project. Click Start Planning to create one.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Start Planning"):
                # prepare empty project and switch to Planner
                st.session_state.project = {"title":"", "constraints":"", "raw_plan":"", "tasks":[[] for _ in range(8)], "generated_at": None}
                save_session()
                redirect_to("Planner")
        with col2:
            if st.button("Load Last Project"):
                projects = read_json(PROJECTS_FILE, {}).get(st.session_state.user, [])
                if projects:
                    last = projects[-1]
                    st.session_state.project = last
                    save_session()
                    st.success("Loaded last project")
                else:
                    st.warning("No saved projects yet.")
        if st.button("Logout"):
            st.session_state.user = None
            save_session()
            st.success("Logged out")

# -------------------------
# Page: Planner
# -------------------------
elif st.session_state.active_tab == "Planner":
    st.markdown('<div class="card"><strong>AI Planner</strong> — create or edit your 8-day plan</div>', unsafe_allow_html=True)
    # Input / generate
    col1, col2 = st.columns([3,1])
    with col1:
        title = st.text_input("Project title", value=st.session_state.project.get("title",""), key="proj_title")
        constraints = st.text_area("Notes / constraints (optional)", value=st.session_state.project.get("constraints",""), height=80, key="proj_constraints")
    with col2:
        if st.button("Generate 8-day Plan (AI)"):
            if not title.strip():
                st.error("Enter a project title.")
            else:
                st.session_state.project["title"] = title.strip()
                st.session_state.project["constraints"] = constraints.strip()
                with st.spinner("Generating plan with DayBot..."):
                    plan_text = generate_plan(title.strip(), constraints.strip())
                    st.session_state.project["raw_plan"] = plan_text
                    st.session_state.project["generated_at"] = datetime.utcnow().isoformat()
                    st.session_state.project["tasks"] = parse_plan_to_tasks(plan_text)
                    # persist in projects file under user
                    projects = read_json(PROJECTS_FILE, {})
                    user_projects = projects.get(st.session_state.user, [])
                    user_projects.append(st.session_state.project)
                    projects[st.session_state.user] = user_projects
                    write_json(PROJECTS_FILE, projects)
                    save_session()
                st.success("Plan created and loaded into Planner cards.")
    st.markdown("---")
    # Show day cards (editable)
    tasks = st.session_state.project.get("tasks", [[] for _ in range(8)])
    for d in range(8):
        with st.container():
            st.markdown(f'<div class="day-card"><strong>Day {d+1}</strong></div>', unsafe_allow_html=True)
            day_tasks = tasks[d]
            if not day_tasks:
                st.info("Not done yet — empty.")
            else:
                for idx, t in enumerate(day_tasks):
                    cols = st.columns([0.05, 0.8, 0.15])
                    checked = cols[0].checkbox("", value=t.get("done", False), key=f"chk_{d}_{t['id']}")
                    if checked != t.get("done"):
                        t["done"] = checked
                        save_session()
                    new_text = cols[1].text_input("", value=t.get("text",""), key=f"txt_{d}_{t['id']}")
                    if new_text != t.get("text"):
                        t["text"] = new_text
                        save_session()
                    if cols[2].button("Remove", key=f"rm_{d}_{t['id']}"):
                        st.session_state.project["tasks"][d] = [tt for tt in st.session_state.project["tasks"][d] if tt["id"] != t["id"]]
                        save_session()
                        st.experimental_rerun()
            add_col1, add_col2 = st.columns([4,1])
            new_task = add_col1.text_input(f"Add task Day {d+1}", key=f"add_{d}")
            if add_col2.button("Add", key=f"add_btn_{d}"):
                if new_task.strip():
                    all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                    new_id = (max(all_ids)+1) if all_ids else 0
                    st.session_state.project["tasks"][d].append({"id": new_id, "text": new_task.strip(), "done": False})
                    save_session()
                    st.experimental_rerun()
            # day summary
            tot = len(st.session_state.project["tasks"][d])
            done = sum(1 for tt in st.session_state.project["tasks"][d] if tt.get("done"))
            st.markdown(f"**{done}/{tot} done**")
            st.markdown("---")
    # bottom controls
    colA, colB, colC = st.columns([1,1,1])
    with colA:
        if st.button("Save Plan (overwrite project)"):
            # persist in projects file (append)
            projects = read_json(PROJECTS_FILE, {})
            user_projects = projects.get(st.session_state.user, [])
            user_projects.append(st.session_state.project)
            projects[st.session_state.user] = user_projects
            write_json(PROJECTS_FILE, projects)
            st.success("Plan saved to your projects.")
    with colB:
        if st.button("Export Plan (TXT)"):
            txt = ""
            for i,day in enumerate(st.session_state.project["tasks"], start=1):
                txt += f"Day {i}:\n"
                for tt in day:
                    txt += f"- {tt['text']}\n"
                txt += "\n"
            st.download_button("Download TXT", txt, file_name="daybyday_plan.txt", mime="text/plain")
    with colC:
        if st.button("Go to Chat (ask DayBot)"):
            redirect_to("Chat")

# -------------------------
# Page: Chat
# -------------------------
elif st.session_state.active_tab == "Chat":
    st.markdown('<div class="card"><strong>Chat — DayBot</strong></div>', unsafe_allow_html=True)
    st.markdown("<div class='small'>Ask DayBot to refine the plan or give quick help about any day.</div>", unsafe_allow_html=True)
    # show chat history
    for msg in st.session_state.chat_history[-20:]:
        role = msg.get("role")
        text = msg.get("text")
        time = msg.get("time")
        if role == "user":
            st.markdown(f"**You ({time[:19]}):** {text}")
        else:
            st.markdown(f"**DayBot ({time[:19]}):** {text}")
    st.markdown("---")
    # context selector: whole plan or a day
    context_choice = st.selectbox("Context for DayBot:", ["Whole project"] + [f"Day {i+1}" for i in range(8)], key="chat_context")
    user_query = st.text_input("Your message to DayBot (e.g. 'Make Day 2 more detailed')", key="chat_input")
    if st.button("Send"):
        if not user_query.strip():
            st.warning("Type your message first.")
        else:
            st.session_state.chat_history.append({"role":"user", "text":user_query.strip(), "time": datetime.utcnow().isoformat()})
            # Build prompt with context
            if context_choice == "Whole project":
                context = st.session_state.project.get("raw_plan","") or ""
            else:
                day_idx = int(context_choice.split()[1]) - 1
                day_tasks = st.session_state.project.get("tasks", [[] for _ in range(8)])[day_idx]
                context = "\n".join([t.get("text","") for t in day_tasks]) or st.session_state.project.get("raw_plan","")
            prompt = f"{SYSTEM_PROMPT}\nContext:\n{context}\nUser request: {user_query}\nRespond concisely with an updated plan fragment or actionable changes."
            ok, resp = call_ai_model(prompt)
            if not ok:
                st.session_state.last_ai_error = resp
                reply = "DayBot is unavailable; try again later or edit manually."
            else:
                reply = resp
            st.session_state.chat_history.append({"role":"DayBot", "text": reply, "time": datetime.utcnow().isoformat()})
            save_session()
            # Optional: if reply looks like plan, user can choose to import — show import option
            if "Day" in reply and len(reply.splitlines()) > 2:
                if st.button("Import AI reply into project (append tasks)"):
                    # naive parse: add new tasks to day 1 as fallback
                    parsed = parse_plan_to_tasks(reply)
                    # merge parsed into current tasks: append non-empty tasks per day
                    for i in range(8):
                        for task in parsed[i]:
                            all_ids = [tt["id"] for dd in st.session_state.project["tasks"] for tt in dd]
                            nid = (max(all_ids)+1) if all_ids else 0
                            st.session_state.project["tasks"][i].append({"id": nid, "text": task["text"], "done": False})
                    save_session()
                    st.success("Imported AI edits into your project tasks.")
    st.markdown("---")
    if st.button("Back to Planner"):
        redirect_to("Planner")

# -------------------------
# Page: Feed
# -------------------------
elif st.session_state.active_tab == "Feed":
    st.markdown('<div class="card"><strong>Feed</strong> — share updates and see AI next steps</div>', unsafe_allow_html=True)
    if not st.session_state.user:
        st.info("Log in to post or view personalized feed.")
    else:
        post_text = st.text_area("Share progress (short):", height=80, key="feed_input")
        if st.button("Post update"):
            if not post_text.strip():
                st.warning("Write something first.")
            else:
                entry = add_feed_post(st.session_state.user, post_text.strip())
                st.success("Posted. AI suggested next steps added.")
                save_session()
        st.markdown("---")
        feed = read_json(FEED_FILE, [])
        if not feed:
            st.info("No feed posts yet.")
        else:
            for e in feed[:40]:
                st.markdown(f"**{e.get('user')}** • {e.get('time')[:19]}")
                st.markdown(e.get("text"))
                suggs = e.get("suggestions", [])
                if suggs:
                    st.markdown("**AI next steps:**")
                    for s in suggs:
                        st.markdown(f"- {s}")
                st.markdown("---")

# -------------------------
# Footer + debug
# -------------------------
st.markdown("<div class='small'>Tip: you can save project edits, post progress to Feed, and ask DayBot to update your plan.</div>", unsafe_allow_html=True)
if st.session_state.last_ai_error:
    st.markdown("**DayBot error (last):**")
    st.code(st.session_state.last_ai_error)
