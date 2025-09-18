# app/routes/notes.py
import os
import shutil
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.database import engine
from app.models import GeneralNotes
from app.utils import create_vector_index

router = APIRouter()
VECTORSTORE_ROOT = "vectorstores"

@router.get("/general/{project_id}")
def get_general(project_id: int):
    with Session(engine) as session:
        gn = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
    return JSONResponse({"text": gn.text if gn else ""})

@router.post("/general/{project_id}")
def save_general(project_id: int, text: str = Form("")):
    with Session(engine) as session:
        gn = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
        if not gn:
            gn = GeneralNotes(project_id=project_id)
            session.add(gn)
        
        gn.text = text
        index_dir = os.path.join(VECTORSTORE_ROOT, f"project_{project_id}")
        os.makedirs(index_dir, exist_ok=True)
        index_path = os.path.join(index_dir, "general_notes_index")

        if os.path.exists(index_path):
            shutil.rmtree(index_path)

        if text.strip():
            create_vector_index(text, index_path)
            gn.vector_index_path = index_path
        else:
            gn.vector_index_path = None
        
        session.add(gn)
        session.commit()
    return JSONResponse({"ok": True})
