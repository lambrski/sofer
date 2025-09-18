# app/routes/illustrations.py
import os
import re
import uuid
from typing import Optional
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from PIL import Image

from app.database import engine
from app.models import ProjectObject, Illustration
from app.services import (rewrite_prompt_for_image_generation, generate_image_with_gemini, get_text_model)
from app.utils import _safe_join_under

router = APIRouter()
MEDIA_ROOT = "media"

@router.get("/project/{project_id}/objects/list")
def list_objects(project_id: int):
    with Session(engine) as session:
        objects = session.exec(select(ProjectObject).where(ProjectObject.project_id == project_id).order_by(ProjectObject.created_at.desc())).all()
        return JSONResponse({"items": [o.model_dump(mode='json') for o in objects]})

@router.post("/project/{project_id}/objects/create")
def create_object(project_id: int, name: str = Form(...), description: str = Form(...), style: str = Form("")):
    style_prefix = f"Style: {style}. " if style else ""
    raw_prompt = f"{style_prefix}A single character reference image named '{name}'. {description}. Centered, plain white background, full body shot."
    try:
        safe_prompt = rewrite_prompt_for_image_generation(raw_prompt)
        img_bytes = generate_image_with_gemini(safe_prompt)
        
        project_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}_objects")
        os.makedirs(project_dir, exist_ok=True)
        filename = f"obj_{uuid.uuid4().hex}.png"
        path = os.path.join(project_dir, filename)
        
        with open(path, "wb") as f:
            f.write(img_bytes)
            
        rel_url = f"/media/project_{project_id}_objects/{filename}"
        with Session(engine) as session:
            obj = ProjectObject(project_id=project_id, name=name, description=description, style=style, reference_image_path=rel_url)
            session.add(obj)
            session.commit()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.post("/project/{project_id}/objects/delete")
def delete_object(project_id: int, object_id: int = Form(...)):
    with Session(engine) as session:
        obj = session.get(ProjectObject, object_id)
        if obj and obj.project_id == project_id:
            if obj.reference_image_path:
                try:
                    full_path = _safe_join_under(MEDIA_ROOT, obj.reference_image_path.replace("/media/", ""))
                    if os.path.exists(full_path):
                        os.remove(full_path)
                except Exception as e:
                    print(f"Could not delete object file: {e}")
            session.delete(obj)
            session.commit()
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Object not found"}, status_code=404)

@router.post("/image/{project_id}")
def create_image(project_id: int, desc: str = Form(...), style: str = Form(""), scene_label: str = Form(""), source_image_id: Optional[int] = Form(None)):
    with Session(engine) as session:
        try:
            source_image_pil = None
            if source_image_id:
                source_ill = session.get(Illustration, source_image_id)
                if source_ill and source_ill.file_path:
                    full_path = _safe_join_under(MEDIA_ROOT, source_ill.file_path.replace("/media/", ""))
                    if os.path.exists(full_path):
                        source_image_pil = Image.open(full_path)

            all_objects = session.exec(select(ProjectObject).where(ProjectObject.project_id == project_id)).all()
            consistency_notes = [f"- '{obj.name}': {obj.description}" for obj in all_objects if re.search(r'\b' + re.escape(obj.name) + r'\b', desc, re.IGNORECASE)]

            text_model = get_text_model()
            english_desc = text_model.generate_content(f"Translate to a simple, clear English sentence for an AI: '{desc}'").text.strip()

            style_prefix = f"In the style of {style}: " if style else ""
            raw_prompt_text = f"{style_prefix}A full scene. Description: {english_desc}"
            if consistency_notes:
                raw_prompt_text += "\n\n**Consistency Guidelines:**\n" + "\n".join(consistency_notes)

            final_prompt = rewrite_prompt_for_image_generation(raw_prompt_text)
            img_bytes = generate_image_with_gemini(final_prompt, source_image=source_image_pil)

            project_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}")
            os.makedirs(project_dir, exist_ok=True)
            filename = f"img_{uuid.uuid4().hex}.png"
            path = os.path.join(project_dir, filename)
            with open(path, "wb") as f:
                f.write(img_bytes)
            rel_url = f"/media/project_{project_id}/{filename}"

            ill = Illustration(project_id=project_id, file_path=rel_url, prompt=desc, style=style, scene_label=scene_label, source_illustration_id=source_image_id)
            session.add(ill)
            session.commit()

            return JSONResponse({"ok": True, "url": rel_url})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/images/{project_id}")
def list_images(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(Illustration).where(Illustration.project_id == project_id).order_by(Illustration.created_at.desc())).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@router.post("/images/{pid}/delete")
def delete_image(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        row = session.get(Illustration, id)
        if row:
            try:
                full_path = _safe_join_under(MEDIA_ROOT, row.file_path.replace("/media/", ""))
                if os.path.exists(full_path):
                    os.remove(full_path)
            except Exception as e:
                print(f"Could not delete file {row.file_path}: {e}")
            session.delete(row)
            session.commit()
    return JSONResponse({"ok": True})
