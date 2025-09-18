# app/routes/library.py
import os
import uuid
import shutil
from typing import List
from fastapi import APIRouter, Form, File, UploadFile
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.database import engine
from app.models import LibraryFile, ProjectLibraryLink
from app.utils import _guess_ext, _safe_join_under, extract_text_from_file, create_vector_index

router = APIRouter(prefix="/api/library")
LIBRARY_ROOT = "library"
VECTORSTORE_ROOT = "vectorstores"
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}

@router.post("/upload")
async def library_upload(files: List[UploadFile] = File(...)):
    with Session(engine) as session:
        for uf in files:
            ext = _guess_ext(uf.filename)
            if ext not in ALLOWED_EXTS: continue
            
            uid_filename = f"{uuid.uuid4().hex}{ext}"
            dest_full = _safe_join_under(LIBRARY_ROOT, uid_filename)
            
            try:
                with open(dest_full, "wb") as f:
                    f.write(await uf.read())
                
                stored_url_path = f"/library/{uid_filename}"
                text_content = extract_text_from_file(dest_full)
                index_path = None
                
                if text_content.strip():
                    index_dir = os.path.join(VECTORSTORE_ROOT, "library")
                    os.makedirs(index_dir, exist_ok=True)
                    index_name = uid_filename.replace('.', '_')
                    index_path = os.path.join(index_dir, index_name)
                    create_vector_index(text_content, index_path)

                rec = LibraryFile(
                    filename=uf.filename, 
                    stored_path=stored_url_path, 
                    ext=ext, 
                    size=uf.size, 
                    vector_index_path=index_path
                )
                session.add(rec)
                session.commit()
            except Exception as e:
                print(f"Failed to save file {uf.filename}: {e}")
    return JSONResponse({"ok": True})

@router.get("/list")
def library_list():
    with Session(engine) as session:
        rows = session.exec(select(LibraryFile).order_by(LibraryFile.uploaded_at.desc())).all()
    items = [{
        "id": r.id, 
        "filename": r.filename, 
        "url": r.stored_path, 
        "ext": r.ext, 
        "size": r.size, 
        "uploaded_at": r.uploaded_at.isoformat()
    } for r in rows]
    return JSONResponse({"items": items})

@router.post("/delete")
def library_delete(id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(LibraryFile, id)
        if not r: 
            return JSONResponse({"ok": False}, status_code=404)
        
        try:
            filename = r.stored_path.replace("/library/", "", 1)
            full_path = _safe_join_under(LIBRARY_ROOT, filename)
            if os.path.exists(full_path): 
                os.remove(full_path)
            if r.vector_index_path and os.path.exists(r.vector_index_path):
                shutil.rmtree(r.vector_index_path)
        except Exception as e:
            print(f"Could not delete file assets: {e}")
            
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.file_id == r.id)).all()
        for l in links: 
            session.delete(l)
            
        session.delete(r)
        session.commit()
    return JSONResponse({"ok": True})

@router.get("/linked/{project_id}")
def library_linked(project_id: int):
    with Session(engine) as session:
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.project_id == project_id)).all()
    return JSONResponse({"items": [{"file_id": l.file_id} for l in links]})

@router.post("/link")
def library_link(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        exists = session.exec(select(ProjectLibraryLink).where(
            (ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id)
        )).first()
        if not exists:
            session.add(ProjectLibraryLink(project_id=project_id, file_id=file_id))
            session.commit()
    return JSONResponse({"ok": True})

@router.post("/unlink")
def library_unlink(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        link = session.exec(select(ProjectLibraryLink).where(
            (ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id)
        )).first()
        if link:
            session.delete(link)
            session.commit()
    return JSONResponse({"ok": True})
