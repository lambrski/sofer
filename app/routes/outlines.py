# app/routes/outlines.py
import json
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.database import engine
from app.models import ChapterOutline, Project
from app.services import get_text_model, build_rules_preamble
from prompts import (create_scene_update_prompt, create_scene_draft_prompt, 
                     create_draft_update_prompt, create_prose_master_prompt)

router = APIRouter(prefix="/api/project/{project_id}")

@router.post("/outline")
def save_outline(project_id: int, chapter_title: str = Form(...), outline_text: str = Form(...)):
    with Session(engine) as session:
        existing = session.exec(select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            ChapterOutline.chapter_title == chapter_title
        )).first()
        if existing:
            existing.outline_text = outline_text
            session.add(existing)
        else:
            new_outline = ChapterOutline(
                project_id=project_id,
                chapter_title=chapter_title,
                outline_text=outline_text
            )
            session.add(new_outline)
        session.commit()
    return JSONResponse({"ok": True})

@router.get("/outlines/list")
def get_outlines_list(project_id: int):
    with Session(engine) as session:
        outlines = session.exec(select(ChapterOutline.chapter_title).where(ChapterOutline.project_id == project_id)).all()
    return JSONResponse({"titles": outlines})

@router.get("/outline")
def get_outline(project_id: int, chapter_title: str):
    with Session(engine) as session:
        outline = session.exec(select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            ChapterOutline.chapter_title == chapter_title
        )).first()
        if outline:
            return JSONResponse({"ok": True, "outline_text": outline.outline_text})
    return JSONResponse({"ok": False, "error": "Outline not found"}, status_code=404)

@router.post("/update_scene_from_discussion")
def update_scene_from_discussion(project_id: int, original_content: str = Form(...), discussion_thread: str = Form(...), chapter_outline: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_scene_update_prompt(original_content, thread_str, chapter_outline)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "updated_content": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/write_scene")
def write_scene(project_id: int, scene_title: str = Form(...), scene_description: str = Form(...)):
    try:
        preamble = build_rules_preamble(project_id)
        context = preamble + create_prose_master_prompt()
        prompt = create_scene_draft_prompt(scene_title, scene_description, context)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "scene_draft": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/update_draft_from_discussion")
def update_draft_from_discussion(project_id: int, original_draft: str = Form(...), discussion_thread: str = Form(...), scene_description: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_draft_update_prompt(original_draft, thread_str, scene_description)
        response = get_text_model().generate_content(prompt)
        return JSONResponse({"ok": True, "updated_draft": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
