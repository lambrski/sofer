# app/routes/synopsis.py
import json
import re
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, delete

from app.database import engine
from app.models import Project, SynopsisHistory
from app.services import get_text_model
from prompts import create_synopsis_update_prompt, create_division_update_prompt, create_chapter_summary_prompt

router = APIRouter()

@router.get("/project/{project_id}/synopsis")
def get_synopsis(project_id: int):
    with Session(engine) as session:
        proj = session.get(Project, project_id)
    return JSONResponse({"text": proj.synopsis_text if proj else ""})

@router.post("/project/{project_id}/synopsis")
def save_synopsis(project_id: int, text: str = Form("")):
    with Session(engine) as session:
        proj = session.get(Project, project_id)
        if proj:
            if text.strip() and proj.synopsis_text != text and proj.synopsis_text:
                history_entry = SynopsisHistory(project_id=project_id, text=proj.synopsis_text)
                session.add(history_entry)

            proj.synopsis_text = text
            session.add(proj)
            session.commit()
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Project not found"}, status_code=404)

@router.get("/api/project/{project_id}/synopsis_history")
def get_synopsis_history(project_id: int):
    with Session(engine) as session:
        history = session.exec(select(SynopsisHistory).where(SynopsisHistory.project_id == project_id).order_by(SynopsisHistory.created_at.desc())).all()
    return JSONResponse({"items": [h.model_dump(mode='json') for h in history]})

@router.post("/api/project/{project_id}/synopsis_history/clear")
def clear_synopsis_history(project_id: int):
    with Session(engine) as session:
        session.exec(delete(SynopsisHistory).where(SynopsisHistory.project_id == project_id))
        session.commit()
    return JSONResponse({"ok": True})

@router.post("/api/project/{project_id}/parse_synopsis")
def parse_synopsis_endpoint(project_id: int, text: str = Form(...)):
    chapters = []
    clean_text = text.strip()
    parts = re.split(r'(פרק\s+\d+.*)', clean_text)
    i = 0
    if len(parts) > 1 and not parts[0].strip(): i = 1
    elif len(parts) > 1 and "פרק" not in parts[0]: i = 1
    while i < len(parts):
        title = parts[i].strip()
        content = parts[i+1].strip() if (i+1) < len(parts) else ""
        if title.startswith("פרק"):
            chapters.append({"title": title, "content": content})
        i += 2
    return JSONResponse({"chapters": chapters})

@router.get("/api/project/{project_id}/load_draft")
def load_draft(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project:
            return JSONResponse({
                "draft_text": project.synopsis_draft_text,
                "discussion": json.loads(project.synopsis_draft_discussion or "[]")
            })
    return JSONResponse({"draft_text": "", "discussion": []}, status_code=404)

@router.post("/api/project/{project_id}/save_draft")
def save_draft(project_id: int, draft_text: str = Form(""), discussion_thread: str = Form("[]")):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project:
            project.synopsis_draft_text = draft_text
            project.synopsis_draft_discussion = discussion_thread
            session.add(project)
            session.commit()
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False}, status_code=404)

@router.post("/api/project/{project_id}/summarize_chapter_discussion")
def summarize_chapter_discussion(project_id: int, original_content: str = Form(...), discussion_thread: str = Form(...), full_synopsis: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_chapter_summary_prompt(original_content, thread_str, full_synopsis)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "updated_content": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/api/project/{project_id}/update_synopsis_from_discussion")
def update_synopsis_from_discussion(project_id: int, current_draft: str = Form(...), discussion_thread: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_synopsis_update_prompt(current_draft, thread_str)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "updated_synopsis": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/api/project/{project_id}/update_division_from_discussion")
def update_division_from_discussion(project_id: int, original_division: str = Form(...), discussion_thread: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_division_update_prompt(original_division, thread_str)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "updated_division": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
