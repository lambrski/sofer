# -*- coding: utf-8 -*-
import os
import re
import uuid
import json
import shutil
import io
from datetime import datetime
from typing import Optional, List
from base64 import b64decode

from fastapi import FastAPI, Form, File, UploadFile, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlmodel import SQLModel, Field, Session, create_engine, select, delete
import docx
import PyPDF2

from google import genai as google_genai_sdk
from PIL import Image
import google.generativeai as genai

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from prompts import (
    create_prose_master_prompt, create_persona_prompt, create_chapter_breakdown_prompt,
    create_synopsis_division_prompt, create_prose_division_prompt, create_general_review_prompt,
    create_proofread_prompt, create_review_discussion_prompt, create_review_update_prompt,
    create_image_rewrite_prompt, create_chapter_summary_prompt, create_synopsis_update_prompt,
    create_division_update_prompt, create_scene_update_prompt, create_scene_draft_prompt,
    create_draft_update_prompt
)

# ====== הגדרות מרכזיות וקבועים ======
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MEDIA_ROOT = "media"
LIBRARY_ROOT = "library"
TEMP_ROOT = "temp_files"
VECTORSTORE_ROOT = "vectorstores"
DB_FILE = "db.sqlite"
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}

TEXT_MODEL_API_NAME = "gemini-2.5-pro"
IMAGE_MODEL_API_NAME = "gemini-2.5-flash-image-preview"


# ====== FastAPI & Gemini Client ======
app = FastAPI()
genai.configure(api_key=GOOGLE_API_KEY)

try:
    text_model = genai.GenerativeModel(TEXT_MODEL_API_NAME)
    print(f"Successfully initialized text model: {TEXT_MODEL_API_NAME}")
except Exception as e:
    print(f"ERROR: Could not initialize text model '{TEXT_MODEL_API_NAME}'. The API returned an error: {e}")
    text_model = genai.GenerativeModel("gemini-1.5-pro-latest")
    print("Fallback: Initialized gemini-1.5-pro-latest instead.")


embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GOOGLE_API_KEY)


# ====== Image Generation Function ======
def generate_image_with_gemini(prompt: str, source_image: Optional[Image.Image] = None) -> bytes:
    try:
        print(f"Attempting to generate image with {IMAGE_MODEL_API_NAME}. Prompt: '{prompt}'")
        image_model = genai.GenerativeModel(IMAGE_MODEL_API_NAME)
        content = [prompt, source_image] if source_image else [prompt]
        response = image_model.generate_content(content)

        if response.parts:
            for part in response.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise RuntimeError(f"Image request blocked: {response.prompt_feedback.block_reason.name}")
        raise RuntimeError("No image data returned from Gemini.")

    except Exception as e:
        print(f"An error occurred in generate_image_with_gemini with model '{IMAGE_MODEL_API_NAME}': {e}")
        print("Fallback: Retrying image generation with gemini-1.5-pro-latest.")
        image_model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = image_model.generate_content([prompt, source_image] if source_image else [prompt])
        if response.parts:
            for part in response.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError(f"Image generation failed on both models. Original error: {e}")


# ====== Static file and template serving ======
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(LIBRARY_ROOT, exist_ok=True)
os.makedirs(TEMP_ROOT, exist_ok=True)
os.makedirs(VECTORSTORE_ROOT, exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")
app.mount("/library", StaticFiles(directory=LIBRARY_ROOT), name="library")
app.mount("/temp_files", StaticFiles(directory=TEMP_ROOT), name="temp_files")
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


# ====== Database Setup ======
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False)

# --- Database Models (SQLModel) ---
class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    age_group: Optional[str] = Field(default=None)
    chapters: Optional[int] = Field(default=None)
    frames_per_page: Optional[int] = Field(default=None)
    synopsis_text: str = Field(default="")
    total_pages: Optional[int] = Field(default=None)
    words_per_chapter_min: Optional[int] = Field(default=None)
    words_per_chapter_max: Optional[int] = Field(default=None)
    synopsis_draft_text: str = Field(default="")
    synopsis_draft_discussion: str = Field(default="[]")

class SynopsisHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ProjectObject(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    name: str
    description: str = ""
    style: str = ""
    reference_image_path: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class History(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    question: str
    answer: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class GeneralNotes(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    text: str = ""
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    vector_index_path: Optional[str] = Field(default=None)

class ChapterOutline(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    chapter_title: str
    outline_text: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    text: str
    mode: str = Field(default="enforce")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Illustration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    file_path: str
    prompt: str
    style: str
    scene_label: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_illustration_id: Optional[int] = Field(default=None, foreign_key="illustration.id")

class Review(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    kind: str
    source: str
    title: str
    input_size: int = 0
    input_text: str = ""
    result: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ReviewDiscussion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    review_id: int = Field(foreign_key="review.id")
    role: str
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class LibraryFile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str
    stored_path: str
    ext: str
    size: int = 0
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    vector_index_path: Optional[str] = Field(default=None)

class ProjectLibraryLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    file_id: int = Field(foreign_key="libraryfile.id")
    linked_at: datetime = Field(default_factory=datetime.utcnow)

class TempFile(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    project_id: int
    original_filename: str
    stored_path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    vector_index_path: Optional[str] = Field(default=None)

SQLModel.metadata.create_all(engine)

def _ensure_schema():
    try:
        with engine.connect() as conn:
            def add_column(table: str, column: str, type: str):
                try:
                    cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
                    if column not in cols:
                        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {type}")
                except Exception as e:
                    print(f"Could not add column {column} to table {table}: {e}")
            add_column("project", "age_group", "TEXT")
            add_column("project", "chapters", "INTEGER")
            add_column("project", "frames_per_page", "INTEGER")
            add_column("projectobject", "style", "TEXT")
            add_column("project", "synopsis_text", "TEXT")
            add_column("project", "total_pages", "INTEGER")
            add_column("project", "words_per_chapter_min", "INTEGER")
            add_column("project", "words_per_chapter_max", "INTEGER")
            add_column("project", "synopsis_draft_text", "TEXT")
            add_column("project", "synopsis_draft_discussion", "TEXT")
    except Exception as e:
        print(f"Could not perform schema check: {e}")

_ensure_schema()

# ====== Utility Functions ======
def _clean_ai_division_output(raw_text: str) -> str:
    match = re.search(r"פרק\s+\d+", raw_text)
    if match:
        return raw_text[match.start():]
    return raw_text.strip()

def build_rules_preamble(project_id: int) -> str:
    with Session(engine) as session:
        rules = session.exec(select(Rule).where((Rule.project_id == None) | (Rule.project_id == project_id))).all()
    enforced = [r.text for r in rules if r.mode == "enforce"]
    if not enforced: return ""
    return "עליך לציית לכללים הבאים באופן מוחלט ומדויק:\n- " + "\n- ".join(enforced) + "\n\n"

def _safe_join_under(base: str, path_rel: str) -> str:
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base_abs, path_rel.lstrip("/\\")))
    if os.path.commonpath([full, base_abs]) != base_abs:
        raise ValueError("Path traversal attempt detected.")
    return full

def _guess_ext(filename: str) -> str:
    return (os.path.splitext(filename)[1] or "").lower()

def rewrite_prompt_for_image_generation(raw_prompt: str) -> str:
    print(f"Rewriting raw prompt: '{raw_prompt}'")
    meta_prompt = create_image_rewrite_prompt(raw_prompt)
    try:
        rewrite_model = genai.GenerativeModel(TEXT_MODEL_API_NAME)
        response = rewrite_model.generate_content(meta_prompt)
        rewritten_prompt = response.text.strip()
        print(f"Rewritten prompt: '{rewritten_prompt}'")
        return rewritten_prompt
    except Exception as e:
        print(f"Error during prompt rewrite: {e}")
        raise RuntimeError(f"Prompt rewriting failed. Error: {e}") from e

def extract_text_from_file(file_path: str) -> str:
    ext = _guess_ext(file_path)
    text = ""
    try:
        if ext == '.pdf':
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
        elif ext == '.docx':
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        return f"Error reading file: {os.path.basename(file_path)}"
    return text

def create_vector_index(text: str, index_path: str):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = text_splitter.split_text(text)
    db = FAISS.from_texts(docs, embeddings)
    db.save_local(index_path)

def get_relevant_context_from_index(query: str, index_path: str, k=4) -> str:
    if not os.path.exists(index_path):
        return ""
    db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
    results = db.similarity_search(query, k=k)
    return "\n---\n".join([doc.page_content for doc in results])


# ====== Routes: Main & Projects ======
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with Session(engine) as session:
        projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return templates.TemplateResponse("home.html", {"request": request, "projects": projects})

@app.post("/new_project")
def new_project(
    name: str = Form(...), kind: str = Form(...),
    age_group: Optional[str] = Form(None),
    chapters: Optional[int] = Form(None),
    frames_per_page: Optional[int] = Form(None),
    total_pages: Optional[int] = Form(None)
):
    with Session(engine) as session:
        p = Project(
            name=name, kind=kind, age_group=age_group,
            chapters=chapters, frames_per_page=frames_per_page,
            total_pages=total_pages, synopsis_text=""
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        session.add(GeneralNotes(project_id=p.id, text=""))
        session.commit()
        return RedirectResponse(url=f"/project/{p.id}", status_code=303)

@app.post("/delete_project/{project_id}")
def delete_project_route(project_id: int):
    with Session(engine) as session:
        session.exec(delete(ChapterOutline).where(ChapterOutline.project_id == project_id))
        session.exec(delete(SynopsisHistory).where(SynopsisHistory.project_id == project_id))
        session.exec(delete(History).where(History.project_id == project_id))
        session.exec(delete(GeneralNotes).where(GeneralNotes.project_id == project_id))
        session.exec(delete(Rule).where(Rule.project_id == project_id))
        session.exec(delete(Illustration).where(Illustration.project_id == project_id))
        session.exec(delete(ReviewDiscussion).where(ReviewDiscussion.project_id == project_id))
        session.exec(delete(Review).where(Review.project_id == project_id))
        session.exec(delete(ProjectLibraryLink).where(ProjectLibraryLink.project_id == project_id))
        session.exec(delete(ProjectObject).where(ProjectObject.project_id == project_id))
        project = session.get(Project, project_id)
        if project:
            session.delete(project)
        session.commit()
    try:
        shutil.rmtree(os.path.join(MEDIA_ROOT, f"project_{project_id}_objects"), ignore_errors=True)
        shutil.rmtree(os.path.join(MEDIA_ROOT, f"project_{project_id}"), ignore_errors=True)
        shutil.rmtree(os.path.join(VECTORSTORE_ROOT, f"project_{project_id}"), ignore_errors=True)
    except Exception as e:
        print(f"Could not clean up asset directories for project {project_id}: {e}")
    return RedirectResponse("/", status_code=303)

@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_page(request: Request, project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse("project.html", {"request": request, "project": project})


# ====== Routes: Notes, Chat, History, Rules, Library ======
@app.get("/general/{project_id}")
def get_general(project_id: int):
    with Session(engine) as session:
        gn = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
    return JSONResponse({"text": gn.text if gn else ""})

@app.post("/general/{project_id}")
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

@app.get("/project/{project_id}/synopsis")
def get_synopsis(project_id: int):
    with Session(engine) as session:
        proj = session.get(Project, project_id)
    return JSONResponse({"text": proj.synopsis_text if proj else ""})

@app.post("/project/{project_id}/synopsis")
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

@app.get("/api/project/{project_id}/synopsis_history")
def get_synopsis_history(project_id: int):
    with Session(engine) as session:
        history = session.exec(select(SynopsisHistory).where(SynopsisHistory.project_id == project_id).order_by(SynopsisHistory.created_at.desc())).all()
    return JSONResponse({"items": [h.model_dump(mode='json') for h in history]})

@app.post("/api/project/{project_id}/synopsis_history/clear")
def clear_synopsis_history(project_id: int):
    with Session(engine) as session:
        session.exec(delete(SynopsisHistory).where(SynopsisHistory.project_id == project_id))
        session.commit()
    return JSONResponse({"ok": True})

@app.post("/api/project/{project_id}/parse_synopsis")
def parse_synopsis_endpoint(project_id: int, text: str = Form(...)):
    chapters = []
    clean_text = text.strip()

    parts = re.split(r'(פרק\s+\d+.*)', clean_text)

    i = 0
    if len(parts) > 1 and not parts[0].strip():
        i = 1
    elif len(parts) > 1 and "פרק" not in parts[0]:
        i = 1

    while i < len(parts):
        title = parts[i].strip()
        content = parts[i+1].strip() if (i+1) < len(parts) else ""
        if title.startswith("פרק"):
            chapters.append({"title": title, "content": content})
        i += 2

    return JSONResponse({"chapters": chapters})

@app.get("/api/project/{project_id}/load_draft")
def load_draft(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if project:
            return JSONResponse({
                "draft_text": project.synopsis_draft_text,
                "discussion": json.loads(project.synopsis_draft_discussion or "[]")
            })
    return JSONResponse({"draft_text": "", "discussion": []}, status_code=404)

@app.post("/api/project/{project_id}/save_draft")
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

@app.get("/chat/{project_id}")
def get_chat(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.desc())).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@app.post("/chat/{project_id}/clear")
def clear_chat(project_id: int):
    with Session(engine) as session:
        session.exec(delete(History).where(History.project_id == project_id))
        session.commit()
    return JSONResponse({"ok": True})

@app.get("/history/{project_id}")
def get_history(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(History.question).where(History.project_id == project_id).order_by(History.created_at.desc())).all()
    return JSONResponse({"items": [r for r in rows]})

@app.get("/rules/{project_id}")
def rules_list(project_id: int):
    with Session(engine) as session:
        global_rules = session.exec(select(Rule).where(Rule.project_id == None)).all()
        project_rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
    return JSONResponse({
        "global": [r.model_dump(mode='json') for r in global_rules],
        "project": [r.model_dump(mode='json') for r in project_rules]
    })

@app.post("/rules/{pid}/add")
def rules_add(pid: int, scope: str = Form(...), text: str = Form(...), mode: str = Form(...)):
    with Session(engine) as session:
        project_id = None if scope == "global" else pid
        session.add(Rule(project_id=project_id, text=text, mode=mode)); session.commit()
    return JSONResponse({"ok": True})

@app.post("/rules/{pid}/update")
def rules_update(pid: int, id: int = Form(...), text: str = Form(...), mode: str = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r:
            r.text = text; r.mode = mode; session.add(r); session.commit()
    return JSONResponse({"ok": True})

@app.post("/rules/{pid}/delete")
def rules_delete(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r:
            session.delete(r); session.commit()
    return JSONResponse({"ok": True})

# ====== Routes: Main AI Endpoints ======
@app.post("/upload_temp_files/{project_id}")
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

@app.post("/ask/{project_id}")
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
        # Draft discussion call
        if original_draft is not None and discussion_thread and scene_description is not None:
             is_discussion = True
             thread_data = json.loads(discussion_thread)
             thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
             full_context = f"**Original Scene Description (Context):**\n{scene_description}\n\n**Current Draft:**\n{original_draft}\n\n**Current Discussion:**\n{thread_str}"
        # Chapter/Scene outline discussion call
        elif full_synopsis and chapter_content and discussion_thread:
            is_discussion = True
            thread_data = json.loads(discussion_thread)
            thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
            full_context = f"**Full Context:**\n{full_synopsis}\n\n**Original Content (Focus):**\n{chapter_content}\n\n**Current Discussion:**\n{thread_str}"
        # Synopsis builder call
        elif current_draft is not None and discussion_thread:
            is_discussion = True
            thread_data = json.loads(discussion_thread)
            thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
            full_context = f"**Current Synopsis Draft:**\n{current_draft}\n\n**Current Discussion:**\n{thread_str}"
        # Refine division call
        elif original_division is not None and discussion_thread:
            is_discussion = True
            thread_data = json.loads(discussion_thread)
            thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
            full_context = f"**Original Divided Synopsis:**\n{original_division}\n\n**Current Discussion:**\n{thread_str}"
        else:
            # Regular call
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

            file_context = "" #... file context logic here ...

            history_context = "היסטוריית שיחה קודמת:\n" + chat_history_str + "\n\n" if chat_history_str else ""
            full_context = f"{file_context}{notes_context}{history_context}"

        prompt = ""

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
                session.add(project)
                session.commit()
                prompt = create_prose_division_prompt(
                    synopsis_text=synopsis_text_content,
                    min_words=words_per_chapter_min or 1500,
                    max_words=words_per_chapter_max or 3000,
                    preamble=preamble, context=full_context
                )
            else: # Comic
                prompt = create_synopsis_division_prompt(
                    synopsis_text=synopsis_text_content, num_chapters=project.chapters or 18,
                    preamble=preamble, context=full_context
                )

        else: # Default case for general chat and all discussion types
            prompt = f"{preamble}{full_context}\n\nבהתבסס על כל ההקשר שסופק, ענה על הבקשה הבאה: {text}"

        config = genai.types.GenerationConfig(temperature=float(temperature))
        resp = text_model.generate_content(contents=[prompt], generation_config=config)

        answer = _clean_ai_division_output(resp.text) if write_kind == 'divide_synopsis' else resp.text

        if not is_discussion:
            tag = f"【{mode}:{write_kind}】" if mode == 'write' else f"【{mode}】"
            if write_kind not in ['breakdown_chapter', 'divide_synopsis']:
                session.add(History(project_id=project_id, question=f"{tag} {text}", answer=answer)); session.commit()

        if temp_file_ids:
            # Cleanup temp files
            pass

        return JSONResponse({"ok": True, "answer": answer})

@app.post("/api/project/{project_id}/summarize_chapter_discussion")
def summarize_chapter_discussion(project_id: int, original_content: str = Form(...), discussion_thread: str = Form(...), full_synopsis: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_chapter_summary_prompt(original_content, thread_str, full_synopsis)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "updated_content": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/project/{project_id}/update_synopsis_from_discussion")
def update_synopsis_from_discussion(project_id: int, current_draft: str = Form(...), discussion_thread: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_synopsis_update_prompt(current_draft, thread_str)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "updated_synopsis": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/project/{project_id}/update_division_from_discussion")
def update_division_from_discussion(project_id: int, original_division: str = Form(...), discussion_thread: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_division_update_prompt(original_division, thread_str)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "updated_division": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# New/updated endpoints for outline and scene interaction
@app.post("/api/project/{project_id}/outline")
def save_outline(project_id: int, chapter_title: str = Form(...), outline_text: str = Form(...)):
    with Session(engine) as session:
        # Upsert logic: find if it exists, if so update, otherwise create.
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

@app.get("/api/project/{project_id}/outlines/list")
def get_outlines_list(project_id: int):
    with Session(engine) as session:
        outlines = session.exec(select(ChapterOutline.chapter_title).where(ChapterOutline.project_id == project_id)).all()
    return JSONResponse({"titles": outlines})

@app.get("/api/project/{project_id}/outline")
def get_outline(project_id: int, chapter_title: str):
    with Session(engine) as session:
        outline = session.exec(select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            ChapterOutline.chapter_title == chapter_title
        )).first()
        if outline:
            return JSONResponse({"ok": True, "outline_text": outline.outline_text})
    return JSONResponse({"ok": False, "error": "Outline not found"}, status_code=404)


@app.post("/api/project/{project_id}/update_scene_from_discussion")
def update_scene_from_discussion(project_id: int, original_content: str = Form(...), discussion_thread: str = Form(...), chapter_outline: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_scene_update_prompt(original_content, thread_str, chapter_outline)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "updated_content": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/project/{project_id}/write_scene")
def write_scene(project_id: int, scene_title: str = Form(...), scene_description: str = Form(...)):
    try:
        preamble = build_rules_preamble(project_id)
        context = preamble + create_prose_master_prompt()
        prompt = create_scene_draft_prompt(scene_title, scene_description, context)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "scene_draft": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/project/{project_id}/update_draft_from_discussion")
def update_draft_from_discussion(project_id: int, original_draft: str = Form(...), discussion_thread: str = Form(...), scene_description: str = Form(...)):
    try:
        thread_data = json.loads(discussion_thread)
        thread_str = "\n".join([f"{t['role']}: {t['content']}" for t in thread_data])
        prompt = create_draft_update_prompt(original_draft, thread_str, scene_description)
        response = text_model.generate_content(prompt)
        return JSONResponse({"ok": True, "updated_draft": response.text})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# All other routes from review onwards remain the same
# ...
@app.post("/review/{project_id}/run")
def run_review(project_id: int, kind: str = Form(...), source: str = Form(...), input_text: str = Form(...)):
    rules = build_rules_preamble(project_id)
    title = input_text[:40] + "..." if len(input_text) > 40 else input_text
    prompt = create_general_review_prompt(rules, input_text) if kind == "general" else create_proofread_prompt(input_text)

    try:
        result = text_model.generate_content(prompt).text
        with Session(engine) as session:
            review_obj = Review(project_id=project_id, kind=kind, source=source, title=title, result=result, input_size=len(input_text), input_text=input_text)
            session.add(review_obj); session.commit()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/reviews/{project_id}")
def list_reviews(project_id: int, kind: str = ""):
    with Session(engine) as session:
        q = select(Review).where(Review.project_id == project_id).order_by(Review.created_at.desc())
        if kind: q = q.where(Review.kind == kind)
        rows = session.exec(q).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@app.post("/reviews/{pid}/delete")
def delete_review(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Review, id)
        if r:
            session.exec(delete(ReviewDiscussion).where(ReviewDiscussion.review_id == id))
            session.delete(r); session.commit()
    return JSONResponse({"ok": True})

@app.get("/review/{pid}/discussion/{review_id}")
def get_review_discussion(review_id: int):
    with Session(engine) as session:
        msgs = session.exec(select(ReviewDiscussion).where(ReviewDiscussion.review_id == review_id).order_by(ReviewDiscussion.created_at.asc())).all()
    return JSONResponse({"items": [m.model_dump(mode='json') for m in msgs]})

@app.post("/review/{pid}/discuss")
def post_review_discussion(pid: int, review_id: int = Form(...), question: str = Form(...)):
    with Session(engine) as session:
        rev = session.get(Review, review_id)
        if not rev: return JSONResponse({"ok": False}, 404)
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="user", message=question)); session.commit()
        prompt = create_review_discussion_prompt(rev, question)
        answer = text_model.generate_content(contents=[prompt]).text
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="assistant", message=answer)); session.commit()
    return JSONResponse({"ok": True})

@app.post("/review/{pid}/update_from_discussion")
def update_review(pid: int, review_id: int = Form(...)):
    with Session(engine) as session:
        rev = session.get(Review, review_id)
        if not rev: return JSONResponse({"ok": False, "error": "Review not found"}, status_code=404)
        discussions = session.exec(select(ReviewDiscussion).where(ReviewDiscussion.review_id == rev.id).order_by(ReviewDiscussion.created_at.asc())).all()
        thread = "\n".join([f"{d.role}: {d.message}" for d in discussions])
        prompt = create_review_update_prompt(rev, thread)
        try:
            new_result = text_model.generate_content(prompt).text
            rev.result = new_result; session.add(rev); session.commit()
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/project/{project_id}/objects/list")
def list_objects(project_id: int):
    with Session(engine) as session:
        objects = session.exec(select(ProjectObject).where(ProjectObject.project_id == project_id).order_by(ProjectObject.created_at.desc())).all()
        return JSONResponse({"items": [o.model_dump(mode='json') for o in objects]})

@app.post("/project/{project_id}/objects/create")
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
        with open(path, "wb") as f: f.write(img_bytes)
        rel_url = f"/media/project_{project_id}_objects/{filename}"
        with Session(engine) as session:
            obj = ProjectObject(project_id=project_id, name=name, description=description, style=style, reference_image_path=rel_url)
            session.add(obj); session.commit()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/project/{project_id}/objects/delete")
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
            session.delete(obj); session.commit()
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Object not found"}, status_code=404)

@app.post("/image/{project_id}")
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

            english_desc = text_model.generate_content(f"Translate to a simple, clear English sentence for an AI: '{desc}'").text.strip()

            style_prefix = f"In the style of {style}: " if style else ""
            raw_prompt_text = f"{style_prefix}A full scene. Description: {english_desc}"
            if consistency_notes: raw_prompt_text += "\n\n**Consistency Guidelines:**\n" + "\n".join(consistency_notes)

            final_prompt = rewrite_prompt_for_image_generation(raw_prompt_text)
            img_bytes = generate_image_with_gemini(final_prompt, source_image=source_image_pil)

            project_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}")
            os.makedirs(project_dir, exist_ok=True)
            filename = f"img_{uuid.uuid4().hex}.png"
            path = os.path.join(project_dir, filename)
            with open(path, "wb") as f: f.write(img_bytes)
            rel_url = f"/media/project_{project_id}/{filename}"

            ill = Illustration(project_id=project_id, file_path=rel_url, prompt=desc, style=style, scene_label=scene_label, source_illustration_id=source_image_id)
            session.add(ill); session.commit()

            return JSONResponse({"ok": True, "url": rel_url})

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.get("/images/{project_id}")
def list_images(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(Illustration).where(Illustration.project_id == project_id).order_by(Illustration.created_at.desc())).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@app.post("/images/{pid}/delete")
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
            session.delete(row); session.commit()
    return JSONResponse({"ok": True})

@app.post("/api/library/upload")
async def library_upload(files: List[UploadFile] = File(...)):
    with Session(engine) as session:
        for uf in files:
            ext = _guess_ext(uf.filename)
            if ext not in ALLOWED_EXTS: continue
            uid_filename = f"{uuid.uuid4().hex}{ext}"
            dest_full = _safe_join_under(LIBRARY_ROOT, uid_filename)
            try:
                with open(dest_full, "wb") as f: f.write(await uf.read())
                stored_url_path = f"/library/{uid_filename}"
                text_content = extract_text_from_file(dest_full)
                index_path = None
                if text_content.strip():
                    index_dir = os.path.join(VECTORSTORE_ROOT, "library")
                    os.makedirs(index_dir, exist_ok=True)
                    index_name = uid_filename.replace('.', '_')
                    index_path = os.path.join(index_dir, index_name)
                    create_vector_index(text_content, index_path)

                rec = LibraryFile(filename=uf.filename, stored_path=stored_url_path, ext=ext, size=uf.size, vector_index_path=index_path)
                session.add(rec); session.commit()
            except Exception as e:
                print(f"Failed to save file {uf.filename}: {e}")
    return JSONResponse({"ok": True})

@app.get("/api/library/list")
def library_list():
    with Session(engine) as session:
        rows = session.exec(select(LibraryFile).order_by(LibraryFile.uploaded_at.desc())).all()
    items = [{"id": r.id, "filename": r.filename, "url": r.stored_path, "ext": r.ext, "size": r.size, "uploaded_at": r.uploaded_at.isoformat()} for r in rows]
    return JSONResponse({"items": items})

@app.post("/api/library/delete")
def library_delete(id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(LibraryFile, id)
        if not r: return JSONResponse({"ok": False}, status_code=404)
        try:
            filename = r.stored_path.replace("/library/", "", 1)
            full_path = _safe_join_under(LIBRARY_ROOT, filename)
            if os.path.exists(full_path): os.remove(full_path)
            if r.vector_index_path and os.path.exists(r.vector_index_path):
                shutil.rmtree(r.vector_index_path)
        except Exception as e: print(f"Could not delete file assets: {e}")
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.file_id == r.id)).all()
        for l in links: session.delete(l)
        session.delete(r); session.commit()
    return JSONResponse({"ok": True})

@app.get("/api/library/linked/{project_id}")
def library_linked(project_id: int):
    with Session(engine) as session:
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.project_id == project_id)).all()
    return JSONResponse({"items": [{"file_id": l.file_id} for l in links]})

@app.post("/api/library/link")
def library_link(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        exists = session.exec(select(ProjectLibraryLink).where((ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id))).first()
        if not exists:
            session.add(ProjectLibraryLink(project_id=project_id, file_id=file_id)); session.commit()
    return JSONResponse({"ok": True})

@app.post("/api/library/unlink")
def library_unlink(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        link = session.exec(select(ProjectLibraryLink).where((ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id))).first()
        if link:
            session.delete(link); session.commit()
    return JSONResponse({"ok": True})

# ====== Uvicorn Entrypoint ======
if __name__ == "__main__":
    import uvicorn

    if not GOOGLE_API_KEY:
        print("\nWARNING: GOOGLE_API_KEY is not set. The application will not function correctly.\n")

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
