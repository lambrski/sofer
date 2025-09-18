# app/routes/chat.py
import os
import uuid
import json
from typing import List, Optional
from fastapi import APIRouter, Form, File, UploadFile
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, delete
import google.generativeai as genai

from app.database import engine
from app.models import Project, History, GeneralNotes, TempFile
from app.services import get_text_model, build_rules_preamble
from app.utils import (get_relevant_context_from_index, _clean_ai_division_output, _guess_ext,
                       _safe_join_under, extract_text_from_file, create_vector_index)
from prompts import (create_prose_master_prompt, create_persona_prompt, create_chapter_breakdown_prompt,
                     create_synopsis_division_prompt, create_prose_division_prompt)

router = APIRouter()
TEMP_ROOT = "temp_files"
VECTORSTORE_ROOT = "vectorstores"

@router.get("/chat/{project_id}")
def get_chat(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.desc())).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@router.post("/chat/{project_id}/clear")
def clear_chat(project_id: int):
    with Session(engine) as session:
        session.exec(delete(History).where(History.project_id == project_id))
        session.commit()
    return JSONResponse({"ok": True})

@router.get("/history/{project_id}")
def get_history(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(History.question).where(History.project_id == project_id).order_by(History.created_at.desc())).all()
    return JSONResponse({"items": [r for r in rows]})

@router.post("/upload_temp_files/{project_id}")
async def upload_temp_files(project_id: int, files: List[UploadFile] = File(...)):
    with Session(engine) as session:
        file_ids = []; filenames = []
        for uf in files:
            ext = _guess_ext(uf.filename)
            uid_filename = f"{uuid.uuid4().hex}{ext}"
            dest_full = _safe_join_under(TEMP_ROOT, uid_filename)
            with open(dest_full, "wb") as f: f.write(await uf.read())

            text_content = extract_text_from_file(dest_full)
            if text_content:
                index_dir = os.path.join(VECTORSTORE_ROOT, f"project_{project_id}", "temp")
                os.makedirs(index_dir, exist_ok=True)
                index_path = os.path.join(index_dir, uid_filename)
                create_vector_index(text_content, index_path)

                rec = TempFile(project_id=project_id, original_filename=uf.filename, stored_path=dest_full, vector_index_path=index_path)
                session.add(rec); session.commit(); session.refresh(rec)
                file_ids.append(rec.id); filenames.append(uf.filename)
    return JSONResponse({"ok": True, "file_ids": file_ids, "filenames": filenames})

@router.post("/ask/{project_id}")
def ask_project(
    project_id: int, text: str = Form(""), use_notes: str = Form("1"),
    mode: str = Form(...), write_kind: str = Form(...), use_history: str = Form("1"),
    temperature: float = Form(0.7), persona: str = Form("partner"),
    temp_file_ids: List[str] = Form([]), library_file_ids: List[int] = Form([]),
    synopsis_text_content: Optional[str] = Form(None),
    words_per_chapter_min: Optional[int] = Form(None),
    words_per_chapter_max: Optional[int] = Form(None),
    full_synopsis: Optional[str] = Form(None),
    chapter_content: Optional[str] = Form(None),
    discussion_thread: Optional[str] = Form(None),
    current_draft: Optional[str] = Form(None),
    original_division: Optional[str] = Form(None),
    original_draft: Optional[str] = Form(None),
    scene_description: Optional[str] = Form(None)
):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return JSONResponse({"ok": False, "answer": "Project not found."}, status_code=404)

        preamble = build_rules_preamble(project_id)

        if project.kind == 'פרוזה':
            preamble += create_prose_master_prompt() + "\n\n"

        if mode == 'brainstorm' or mode == 'write':
            preamble += create_persona_prompt(persona)

        full_context = ""
        is_discussion = False
        
        # Determine if it's a discussion-based call
        if any([discussion_thread]):
             is_discussion = True
             thread_data = json.loads(discussion_thread)
             thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
             # Contextualize based on discussion type
             if original_draft is not None and scene_description is not None:
                 full_context = f"**Original Scene Description (Context):**\n{scene_description}\n\n**Current Draft:**\n{original_draft}\n\n**Current Discussion:**\n{thread_str}"
             elif full_synopsis and chapter_content:
                 full_context = f"**Full Context:**\n{full_synopsis}\n\n**Original Content (Focus):**\n{chapter_content}\n\n**Current Discussion:**\n{thread_str}"
             elif current_draft is not None:
                 full_context = f"**Current Synopsis Draft:**\n{current_draft}\n\n**Current Discussion:**\n{thread_str}"
             elif original_division is not None:
                 full_context = f"**Original Divided Synopsis:**\n{original_division}\n\n**Current Discussion:**\n{thread_str}"
        else:
            # Regular call context building
            notes_context = ""
            if use_notes == "1" and text.strip():
                gn_obj = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
                if gn_obj and gn_obj.vector_index_path:
                    notes_context = get_relevant_context_from_index(text, gn_obj.vector_index_path)
                    if notes_context: notes_context = "להלן קטעים רלוונטיים מתוך 'קובץ כללי':\n" + notes_context + "\n\n"

            chat_history_str = ""
            if use_history == "1":
                turns = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.desc()).limit(10)).all()
                chat_history_str = "\n".join([f"ש: {t.question}\nת: {t.answer}" for t in reversed(turns)])

            file_context = "" # Placeholder for file context logic
            history_context = "היסטוריית שיחה קודמת:\n" + chat_history_str + "\n\n" if chat_history_str else ""
            full_context = f"{file_context}{notes_context}{history_context}"

        prompt = ""
        text_model = get_text_model()

        if write_kind == 'breakdown_chapter':
            extractor_prompt = f"From the full synopsis, extract only the text for the chapter titled '{text}'.\n\nSYNOPSIS:\n{project.synopsis_text}"
            chapter_synopsis = text_model.generate_content(extractor_prompt).text
            prompt = create_chapter_breakdown_prompt(preamble, full_context, chapter_synopsis, project)

        elif write_kind == 'divide_synopsis':
            if not synopsis_text_content or not synopsis_text_content.strip():
                return JSONResponse({"ok": False, "answer": "Synopsis is empty."}, status_code=400)
            if project.kind == 'פרוזה':
                project.words_per_chapter_min = words_per_chapter_min
                project.words_per_chapter_max = words_per_chapter_max
                session.add(project); session.commit()
                prompt = create_prose_division_prompt(synopsis_text=synopsis_text_content, min_words=words_per_chapter_min or 1500, max_words=words_per_chapter_max or 3000, preamble=preamble, context=full_context)
            else:
                prompt = create_synopsis_division_prompt(synopsis_text=synopsis_text_content, num_chapters=project.chapters or 18, preamble=preamble, context=full_context)
        else:
            prompt = f"{preamble}{full_context}\n\nבהתבסס על כל ההקשר שסופק, ענה על הבקשה הבאה: {text}"

        config = genai.types.GenerationConfig(temperature=float(temperature))
        resp = text_model.generate_content(contents=[prompt], generation_config=config)
        answer = _clean_ai_division_output(resp.text) if write_kind == 'divide_synopsis' else resp.text

        if not is_discussion and write_kind not in ['breakdown_chapter', 'divide_synopsis']:
            tag = f"【{mode}:{write_kind}】" if mode == 'write' else f"【{mode}】"
            session.add(History(project_id=project_id, question=f"{tag} {text}", answer=answer)); session.commit()

        # Cleanup temp files logic can be added here
        return JSONResponse({"ok": True, "answer": answer})
