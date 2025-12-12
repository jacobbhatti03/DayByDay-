# app.py

import os
import json
import copy
from datetime import datetime
from pathlib import Path
import google.Generativeai as genai
import streamlit as st
from dotenv import load_dotenv

# --------------------------------------------------
# ENV & STORAGE
# --------------------------------------------------
load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "daybyday_data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

PROJECTS_FILE = DATA_DIR / "projects.json"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

def read_json(path: Path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def write_json(path: Path, obj):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    tmp.replace(path)

if not PROJECTS_FILE.exists():
    write_json(PROJECTS_FILE, {})

def load_projects():
    return read_json(PROJECTS_FILE, {})

def save_project(project):
    projects = load_projects()
    projects[project["title"]] = copy.deepcopy(project)
    write_json(PROJECTS_FILE, projects)

def delete_project(title):
    projects = load_projects()
    if title in projects:
        del projects[title]
        write_json(PROJECTS_FILE, projects)

# --------------------------------------------------
# ✅ PROPER GEMINI CALL (Google Gen AI Python SDK)
# --------------------------------------------------
# Uses the officially documented approach:
# client.models.generate_content(model="gemini-2.5-flash", contents="...") :contentReference[oaicite:2]{index=2}
try:
    from google import genai  # <- package: google-genai (new SDK)
    _HAS_GOOGLE_GENAI = True
except Exception:
    genai = None
    _HAS_GOOGLE_GENAI = False

def call_gemini_text(prompt: str, max_output_tokens: int = 700):
    if not GEMINI_API_KEY:
        return False, "GEMINI_API_KEY not found in .env."
    if not _HAS_GOOGLE_GENAI:
        return False, "Missing dependency: install with `pip install -U google-genai`."

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        # ✅ You asked for 2.5 Flash:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "max_output_tokens": max_output_tokens,
                "temperature": 0.7,
                "top_p": 0.95,
            },
        )

        # New SDK returns structured output; `.text` is the simplest accessor
        text = getattr(resp, "text", None)
        if text:
            return True, str(text).strip()

        return False, "Gemini returned empty output."

    except Exception as e:
        msg = str(e)
        if "reported as leaked" in msg:
            return False, (
                "Your Gemini API key was revoked (reported as leaked). "
                "Generate a new key and replace it in .env."
            )
        return False, f"Gemini error: {e}"

# --------------------------------------------------
# UI PAGES
# --------------------------------------------------
def page_home():
    st.header("📅 DayByDay — AI 8-Day Planner")

    projects = load_projects()

    if projects:
        for title, proj in projects.items():
            with st.expander(title):
                if st.button("Open Plan", key=f"open_{title}"):
                    st.session_state.project = proj
                    st.session_state.page = "planner"
                    st.rerun()
                if st.button("Delete Plan", key=f"del_{title}"):
                    delete_project(title)
                    st.rerun()
    else:
        st.info("No plans yet. Create one!")

    if st.button("➕ Create New AI Plan"):
        st.session_state.page = "create"
        st.rerun()

def page_create_project():
    st.header("🤖 Create AI-Generated 8-Day Plan")

    title = st.text_input("Project Name")
    prompt = st.text_area(
        "What do you want DayByDay to plan?",
        placeholder="e.g. Create an 8-day study plan to learn Python basics"
    )

    if st.button("Generate Plan"):
        if not title.strip():
            st.error("Project name is required")
            return
        if not prompt.strip():
            st.error("Please describe your plan")
            return

        with st.spinner("Generating your 8-day plan..."):
            ok, ai_text = call_gemini_text(
                f"""
Create an 8-day plan.
STRICT FORMAT:

Day 1:
- task
- task

Day 2:
- task

Continue until Day 8.
NO extra explanation.

PLAN REQUEST:
{prompt}
"""
            )

        if not ok:
            st.error(ai_text)
            return

        # Parse AI response into tasks[8]
        tasks = [[] for _ in range(8)]
        current_day = -1

        for line in ai_text.splitlines():
            line = line.strip()
            if line.lower().startswith("day"):
                try:
                    current_day = int(line.split()[1].replace(":", "")) - 1
                except Exception:
                    current_day = -1
            elif line.startswith("-") and 0 <= current_day < 8:
                tasks[current_day].append(line.lstrip("- ").strip())

        project = {
            "title": title.strip(),
            "description": prompt.strip(),
            "tasks": tasks,
            "generated_at": datetime.utcnow().isoformat()
        }

        save_project(project)

        st.session_state.project = project
        st.session_state.page = "planner"
        st.rerun()

def page_planner():
    proj = st.session_state.project

    st.header(f"🗓️ {proj['title']}")
    st.write(proj["description"])

    for i, day_tasks in enumerate(proj["tasks"]):
        st.subheader(f"Day {i + 1}")
        if day_tasks:
            for task in day_tasks:
                st.write(f"- {task}")
        else:
            st.write("_No tasks_")

    if st.button("⬅ Back"):
        st.session_state.page = "home"
        st.rerun()

# --------------------------------------------------
# MAIN
# --------------------------------------------------
def main():
    if "page" not in st.session_state:
        st.session_state.page = "home"

    if st.session_state.page == "home":
        page_home()
    elif st.session_state.page == "create":
        page_create_project()
    elif st.session_state.page == "planner":
        page_planner()
    else:
        page_home()

if __name__ == "__main__":
    main()
