# -*- coding: utf-8 -*-
# FINAL, COMPLETE, AND CORRECTED CODE (V42 - All Fixes Implemented)

from fastapi import FastAPI, Form, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select, delete
from jinja2 import Template
import os, re, uuid, json
from datetime import datetime, timedelta
from base64 import b64decode
from typing import Optional, List, Union
import io
import docx
import PyPDF2
import shutil

# [NEW SDK] Import the new Google GenAI SDK and Pillow
from google import genai as google_genai_sdk
from PIL import Image

# Import legacy libraries for text generation
import google.generativeai as genai

# Import LangChain components
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# ====== הגדרות מרכזיות וקבועים ======
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MEDIA_ROOT = "media"
LIBRARY_ROOT = "library"
TEMP_ROOT = "temp_files"
VECTORSTORE_ROOT = "vectorstores"
DB_FILE = "db.sqlite"
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}

# ====== MODEL NAMES AS PER USER'S EXPLICIT INSTRUCTION ======
TEXT_MODEL_NAME  = os.environ.get("TEXT_MODEL_NAME",  "gemini-2.5-pro")
IMAGE_MODEL_NAME = os.environ.get("IMAGE_MODEL_NAME", "gemini-2.5-flash-image-preview")

# ====== FastAPI & Gemini Client ======
app = FastAPI()
genai.configure(api_key=GOOGLE_API_KEY)
try:
    text_model = genai.GenerativeModel(TEXT_MODEL_NAME)
    print(f"Successfully initialized text model: {TEXT_MODEL_NAME}")
except Exception as e:
    print(f"Could not initialize {TEXT_MODEL_NAME}. Falling back to gemini-1.5-pro-latest. Error: {e}")
    text_model = genai.GenerativeModel("gemini-1.5-pro-latest")

embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GOOGLE_API_KEY)

# ====== [FIX 1/4] STARTUP EVENT TO VERIFY INDEXES ======
@app.on_event("startup")
def verify_vector_indexes_on_startup():
    """
    Runs once when the application starts.
    Checks if the vector index files listed in the database actually exist on disk.
    If an index is missing, it rebuilds it from the text stored in the database.
    """
    print("--- Running startup verification for vector indexes ---")
    with Session(engine) as session:
        # Check all General Notes
        notes_with_indexes = session.exec(
            select(GeneralNotes).where(GeneralNotes.vector_index_path != None)
        ).all()
        
        for note in notes_with_indexes:
            if note.vector_index_path and not os.path.exists(note.vector_index_path):
                print(f"WARNING: Index for GeneralNotes (Project ID: {note.project_id}) is missing. Rebuilding...")
                try:
                    index_dir = os.path.dirname(note.vector_index_path)
                    os.makedirs(index_dir, exist_ok=True)
                    if note.text and note.text.strip():
                        create_vector_index(note.text, note.vector_index_path)
                        print(f"SUCCESS: Rebuilt index for GeneralNotes (Project ID: {note.project_id})")
                    else:
                        print(f"INFO: Skipping index rebuild for empty note (Project ID: {note.project_id})")
                except Exception as e:
                    print(f"ERROR: Failed to rebuild index for GeneralNotes (Project ID: {note.project_id}): {e}")
        
    print("--- Startup verification complete ---")

# ====== Image Generation Function ======
def generate_image_with_gemini(prompt: str, source_image: Optional[Image.Image] = None) -> bytes:
    """
    Creates an image with Gemini. If source_image is provided, it attempts an image-to-image edit.
    """
    try:
        print(f"Generating image with model {IMAGE_MODEL_NAME}. Prompt: '{prompt}'")
        image_model = genai.GenerativeModel(IMAGE_MODEL_NAME)
        
        content = [prompt]
        if source_image:
            print("Source image provided for editing.")
            content.append(source_image)
            
        response = image_model.generate_content(content)
        
        if response.parts:
            for part in response.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data

        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise RuntimeError(f"Image request blocked by safety filters: {response.prompt_feedback.block_reason.name}")

        print(f"DEBUG: Full Gemini response received: {response}")
        raise RuntimeError("No image data returned from Gemini.")

    except Exception as e:
        print(f"An error occurred in generate_image_with_gemini: {e}")
        raise e


# ====== Static file serving ======
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(LIBRARY_ROOT, exist_ok=True)
os.makedirs(TEMP_ROOT, exist_ok=True)
os.makedirs(VECTORSTORE_ROOT, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")
app.mount("/library", StaticFiles(directory=LIBRARY_ROOT), name="library")
app.mount("/temp_files", StaticFiles(directory=TEMP_ROOT), name="temp_files")


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
            add_column("libraryfile", "vector_index_path", "TEXT")
            add_column("tempfile", "vector_index_path", "TEXT")
            add_column("generalnotes", "vector_index_path", "TEXT")
            add_column("illustration", "source_illustration_id", "INTEGER")
    except Exception as e:
        print(f"Could not perform schema check: {e}")

_ensure_schema()

# ====== Utility Functions ======
def build_rules_preamble(project_id: int) -> str:
    with Session(engine) as session:
        rules = session.exec(select(Rule).where((Rule.project_id == None) | (Rule.project_id == project_id))).all()
    enforced = [r.text for r in rules if r.mode == "enforce"]
    if not enforced: return ""
    return "עליך לציית לכללים הבאים באופן מוחלט ומדויק. אל תפרש את 'רוח הדברים' או תסטה מהכתוב. בצע את הכללים כלשונם:\n- " + "\n- ".join(enforced) + "\n\n"

def _safe_join_under(base: str, path_rel: str) -> str:
    base_abs = os.path.abspath(base)
    full = os.path.abspath(os.path.join(base_abs, path_rel.lstrip("/\\")))
    if os.path.commonpath([full, base_abs]) != base_abs:
        raise ValueError("Path traversal attempt detected.")
    return full

def _guess_ext(filename: str) -> str:
    return (os.path.splitext(filename)[1] or "").lower()

def render(template_str, **kwargs):
    return Template(template_str).render(**kwargs)
    
# ====== [FIX 3/4] NEW HELPER FUNCTION FOR CHAPTER EXTRACTION ======
def extract_chapter_text(full_text: str, chapter_identifier: str) -> Optional[str]:
    """
    Extracts the full text of a specific chapter from a larger text.
    It looks for "פרק X" where X is the identifier.
    """
    # Create a regex pattern to find the start of the chapter
    # This looks for "פרק" followed by the identifier, allowing for flexible spacing and an optional colon.
    start_pattern = re.compile(r"פרק\s+" + re.escape(chapter_identifier) + r"[:\.\s\w\-]*\n?", re.IGNORECASE)
    
    start_match = start_pattern.search(full_text)
    
    if not start_match:
        return None
        
    # Find the start position of the content (after the title)
    content_start_pos = start_match.end()
    
    # Create a pattern to find the beginning of the *next* chapter
    # This looks for "פרק" followed by one or more digits or Hebrew letters.
    next_chapter_pattern = re.compile(r"פרק\s+[\dא-ת]+", re.IGNORECASE)
    
    # Search for the next chapter starting from where our chapter's content begins
    next_match = next_chapter_pattern.search(full_text, content_start_pos)
    
    if next_match:
        # If a next chapter is found, extract everything up to its start
        content_end_pos = next_match.start()
        return full_text[content_start_pos:content_end_pos].strip()
    else:
        # If no next chapter is found, extract everything to the end of the text
        return full_text[content_start_pos:].strip()


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

HOME_HTML = """
<html dir="rtl">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>סתם סופר</title>
<style>
  body{font-family:Arial, sans-serif; max-width:980px; margin:24px auto; padding: 0 15px;}
  h1{margin-bottom:4px}
  ul{line-height:1.9; padding-right: 20px;}
  li { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 10px;}
  .project-link { flex-grow: 1; }
  .delete-form button { background: #fdd; border: 1px solid #f99; color: #800; border-radius: 4px; cursor: pointer; padding: 2px 8px; }
  form { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;}
</style>
</head>
<body>
<h1>✍ סתם סופר</h1>
<h2>בחר או צור פרויקט</h2>
<form action="/new_project" method="post" id="newProjectForm">
  שם פרויקט: <input type="text" name="name" required>
  סוג: <select name="kind" id="projectKind">
    <option value="פרוזה">פרוזה</option>
    <option value="קומיקס">קומיקס</option>
  </select>
  
  <span id="proseOptions" style="display:inline;">
    קהל יעד: <select name="age_group">
      <option value="מבוגרים">מבוגרים (14+)</option>
      <option value="נוער">נוער (10-15)</option>
      <option value="ילדים">ילדים (8-12)</option>
    </select>
  </span>
  
  <span id="comicOptions" style="display:none;">
    מספר עמודים כללי: <input type="number" name="total_pages" value="54" style="width: 60px;">
    מספר פרקים: <input type="number" name="chapters" value="18" style="width: 60px;">
    פריימים לעמוד: <input type="number" name="frames_per_page" value="6" style="width: 60px;">
  </span>

  <button type="submit">צור</button>
</form>
<hr>
<ul>
{% for p in projects %}
<li>
  <a href="/project/{{p.id}}" class="project-link">{{p.name}} ({{p.kind}})</a>
  <form class="delete-form" action="/delete_project/{{p.id}}" method="post" onsubmit="return confirm('האם אתה בטוח שברצונך למחוק את הפרויקט? פעולה זו היא בלתי הפיכה.');">
    <button type="submit">מחק</button>
  </form>
</li>
{% endfor %}
</ul>

<script>
  const projectKind = document.getElementById('projectKind');
  const proseOptions = document.getElementById('proseOptions');
  const comicOptions = document.getElementById('comicOptions');
  
  projectKind.addEventListener('change', function() {
    if (this.value === 'פרוזה') {
      proseOptions.style.display = 'inline-block';
      comicOptions.style.display = 'none';
    } else {
      proseOptions.style.display = 'none';
      comicOptions.style.display = 'inline-block';
    }
  });
  projectKind.dispatchEvent(new Event('change'));
</script>

</body>
</html>
"""
PROJECT_HTML = """
<html dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{project.name}} - סתם סופר</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 980px; margin: 24px auto; padding: 0 15px;}
    h1 { margin-bottom: 4px; } h2 { margin: 0 0 10px 0; color: #444; display:flex; gap:10px; align-items:center; flex-wrap:wrap;}
    textarea { width: 100%; font-size: 16px; box-sizing: border-box; } button { padding: 6px 14px; margin-top: 6px; cursor:pointer; }
    input {box-sizing: border-box;}
    .btnrow{display:flex; gap:8px; align-items:center; flex-wrap:wrap} #status { color: #666; font-size: 13px; margin-top: 4px; }
    #result { margin-top: 16px; padding: 12px; border: 1px solid #ddd; border-radius: 10px; min-height: 160px; max-height: 55vh; overflow:auto; background:#fff; display: flex; flex-direction: column;}
    .turn { margin: 10px 0; } .meta{color:#888; font-size:12px; margin-bottom:4px; display: flex; justify-content: space-between; align-items: center;}
    .bubble{border:1px solid #e6e6e6; border-radius:12px; padding:10px; white-space:pre-wrap; flex-grow: 1; position: relative;}
    .q .bubble{background:#f9fbff} .a .bubble{background:#fafafa}
    /* ====== [FIX 4/4] CSS FIX FOR COPY BUTTON ====== */
    .copy-bubble { position: absolute; bottom: 5px; left: 5px; opacity: 0; transition: opacity 0.2s; cursor: pointer; font-size: 10px !important; padding: 2px 6px !important; margin:0 !important; z-index: 99;}
    .bubble:hover .copy-bubble { opacity: 1; }
    .linklike { background:#f6f6f6; border:1px solid #ddd; border-radius:6px; padding:4px 8px; font-size:13px; }
    .muted { color:#777; } .hint { color:#777; font-size:12px; text-align:right }
    .modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.3); display:none; z-index: 10; }
    .modal { position:fixed; top:6%; left:50%; transform:translateX(-50%); width:min(1000px, 96vw); background:#fff; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,.25); display:none; z-index: 11;}
    .modal header { padding:10px 12px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center;}
    .modal .content { max-height:75vh; overflow:auto; padding:10px 12px; }
    .modal footer { padding:10px 12px; border-top:1px solid #eee; display:flex; gap:8px; justify-content:flex-end;}
    #notesArea {width:100%; height:70vh; font-size:15px}
    #synopsisArea {width:100%; height:45vh; font-size:15px} 
    .pill{font-size:12px; padding:2px 6px; border:1px solid #ddd; border-radius:999px; display: inline-block; margin: 2px;}
    .field{margin:6px 0} .field input, .field textarea, .field select{width:100%}
    .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px}
    .card{border:1px solid #eee; border-radius:8px; padding:6px} .card img{width:100%; height:180px; object-fit:cover; border-radius:6px; display:block}
    .small{font-size:12px; color:#666} .list{border:1px solid #eee; border-radius:8px; padding:8px; max-height:40vh; overflow:auto}
    .li{border-bottom:1px solid #f3f3f3; padding:6px 4px} .li:last-child{border-bottom:none} .li h4{margin:0 0 4px 0; font-size:14px}
    .rowflex{display:flex; gap:8px; align-items:center; flex-wrap:wrap} .two-col{display:grid; grid-template-columns:1fr 1fr; gap:10px}
    .box{border:1px solid #eee; border-radius:8px; padding:8px} .tabs{display:flex; gap:8px; margin-top:6px}
    .tabs .tabbtn{padding:6px 10px; border:1px solid #ddd; border-radius:999px; font-size:13px; cursor:pointer; background:#f6f6f6}
    .tabs .tabbtn.active{background:#e8f0ff; border-color:#c7dbff}
    #object-gallery {display:grid; grid-template-columns:repeat(auto-fill,minmax(120px,1fr)); gap:10px;}
    .object-card {border:1px solid #eee; border-radius:8px; padding:4px; text-align:center;}
    .object-card img {width:100%; height:120px; object-fit:contain; border-radius:4px; background:#f8f8f8;}
    .object-card h5 {margin:4px 0; font-size:13px;}
    #editingIndicator {font-size: 13px; background: #fff8e1; border: 1px solid #ffecb3; padding: 4px 8px; border-radius: 6px; display: none; margin-bottom: 8px;}
    .chapter-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 8px; margin-bottom: 8px; }
    .chapter-card h5 { margin: 0 0 5px 0; }
    .spinner { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 20px; height: 20px; animation: spin 1s linear infinite; display: inline-block; }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    
    @media (max-width: 600px) {
        .two-col, .row { flex-direction: column; }
        h2 { font-size: 1.2em; }
    }
  </style>
</head>
<body data-project-id="{{project.id}}" data-project-kind="{{project.kind}}">
  <h1>✍ סתם סופר</h1>
  <a href="/" style="float:left; margin-left:10px;">⬅ חזרה לרשימת פרויקטים</a>
  <h2>📘 פרויקט: {{project.name}} ({{project.kind}})  
    <button id="rulesBtn" class="linklike" type="button">כללים</button>  
    <button id="notesBtn" class="linklike" type="button">קובץ כללי</button>  
    {% if project.kind == 'קומיקס' %}
    <button id="synopsisBtn" class="linklike" type="button">תקציר קומיקס</button>
    <button id="divideSynopsisBtn" class="linklike" type="button">חלק תקציר לפרקים</button>
    {% endif %}
    <button id="libraryBtn" class="linklike" type="button">📚 ספרייה</button>  
    <button id="clearChatBtn" class="linklike" type="button">נקה שיחה</button>  
  </h2>
  <div class="rowflex" style="margin-bottom:6px"> <label class="linklike"><input type="radio" name="mode" value="brainstorm" checked> סיעור מוחות</label> <label class="linklike"><input type="radio" name="mode" value="write"> כתיבה</label> <label class="linklike"><input type="radio" name="mode" value="review"> ביקורת</label> <label class="linklike"><input type="radio" name="mode" value="illustrate"> איור</label>  
    <select id="writeKind" style="display:none">  
      <option value="outline">מתווה</option>
      <option value="draft">טיוטה</option>  
      <option value="rewrite">שכתוב ושיפור</option>
      {% if project.kind == 'קומיקס' %}
      <option value="breakdown_chapter">כתוב פרק מתקציר</option>
      {% endif %}
    </select>
  </div>
  <div class="hint">(Ctrl+Enter = שליחה/הרצה,  Shift+Enter = שורה חדשה)</div>
  <div id="chatPanel">
    <div id="brainstormControls" class="rowflex" style="margin-bottom:6px">
        <label for="temperature">טמפרטורה (0.1=ממוקד, 1.0=יצירתי):</label>
        <input type="range" id="temperature" name="temperature" min="0.1" max="1.0" value="0.7" step="0.1" style="flex:1;">
        <span id="tempValue">0.7</span>
        <select id="personaSelector" class="linklike">
            <option value="partner">שותף יצירתי</option>
            <option value="assistant">עוזר ישיר</option>
        </select>
    </div>
    <textarea id="prompt" rows="8" placeholder="כתוב כאן טקסט או שאלה..."></textarea>
    <div class="btnrow" style="justify-content: space-between;">
        <div class="rowflex">
            <button id="sendBtn" type="button">שלח</button>  
            <label class="linklike" for="tempFileUpload">העלה קובץ לשיחה</label>
            <input type="file" id="tempFileUpload" multiple style="display:none;">
            <button id="attachFromLibraryBtn" class="linklike">צרף מהספרייה</button>
        </div>
        <div id="status" class="rowflex"></div>
    </div>
    <div class="btnrow" style="margin-top: 8px;">
        <label style="font-size:13px"><input type="checkbox" id="useNotes" checked> התבסס על 'קובץ כללי'</label>  
        <label style="font-size:13px"><input type="checkbox" id="useHistory" checked> השתמש בהיסטוריית השיחה</label>  
        <button id="historyBtn" class="linklike" type="button" title="שאלות אחרונות">היסטוריית שאלות</button>
    </div>
    <div id="attached-files-list" class="rowflex" style="font-size:12px; margin-top:4px;"></div>
    <div id="result"></div>
  </div>
  <div id="reviewPanel" style="display:none; margin-top:14px"> <div class="tabs"> <button class="tabbtn active" id="tabGeneral">ביקורת כללית</button> <button class="tabbtn" id="tabProof">הגהה</button> </div> <div class="row" style="margin-top:8px"> <div style="flex:2; min-width:300px"> <div class="field"> <label>טקסט לבדיקה (אם ריק — נבדוק את 'קובץ כללי'):</label> <textarea id="reviewInput" rows="10" placeholder="הדבק כאן טקסט מלא לבדיקה..."></textarea> </div> <div class="rowflex"> <label style="font-size:13px"><input type="checkbox" id="rvUseNotesWhenEmpty" checked> אם ריק — בדוק את 'קובץ כללי'</label> </div> <div class="rowflex"> <button id="runReviewBtn" class="linklike" type="button">הרץ ביקורת</button> <div id="rvStatus" class="rowflex" style="gap:8px;"></div></div> <div id="reviewOut" class="box" style="margin-top:8px; white-space:pre-wrap"></div> </div> <div style="flex:1; min-width:260px"> <h4 style="margin:0 0 8px 0">ביקורות קודמות</h4> <div id="reviewList" class="list"></div></div> </div> </div>
  <div id="illustratePanel" style="display:none; margin-top:14px">
    <div class="box">
        <div id="editingIndicator">🎨 מצב עריכת תמונה. שנה את התיאור ולחץ "צור איור" כדי לעדכן את התמונה. <button id="cancelEditBtn" class="linklike small">בטל עריכה</button></div>
        <div class="field"><label>תיאור הסצנה (המערכת תזהה אוטומטית שמות של אובייקטים מהמעבדה):</label><textarea id="imgDesc" rows="4" placeholder="למשל: שמוליק וצביקי בפתח מערת הרוחות"></textarea></div>
        <div class="rowflex">
            <div class="field" style="flex:1;"><label>סגנון:</label><input id="imgStyle" placeholder="קומיקס / אקוורל / וכו'"></div>
            <div class="field" style="flex:1;"><label>תווית (למיון):</label><input id="imgScene" placeholder="למשל: הכניסה למערה"></div>
        </div>
        <div class="rowflex">
            <button id="genImageBtn" class="linklike" type="button">צור איור</button>
            <button id="objectLabBtn" class="linklike" type="button">🔬 פתח את מעבדת האובייקטים</button>
            <div id="imgStatus" class="rowflex" style="gap:8px;"></div>
        </div>
    </div>
    <hr>
    <div id="gallery" class="grid"></div>
  </div>

  <div id="backdrop" class="modal-backdrop"></div>
  <div id="notesModal" class="modal"> <header><strong>קובץ כללי — {{project.name}}</strong><button id="closeNotesBtn" class="linklike">סגור</button></header> <div class="content"><textarea id="notesArea"></textarea></div> <footer><button id="saveNotesBtn" class="linklike">שמור</button></footer> </div>
  <div id="synopsisModal" class="modal"> 
    <header><strong>תקציר קומיקס — {{project.name}}</strong>
      <div>
        <button id="synopsisToggleViewBtn" class="linklike">הצג כרטיסיות פרקים</button>
        <button id="closeSynopsisBtn" class="linklike">סגור</button>
      </div>
    </header> 
    <div class="content">
      <div id="synopsisEditorView">
        <textarea id="synopsisArea"></textarea>
        <hr style="margin: 12px 0;">
        <h4 style="margin-top:0; margin-bottom:5px;">היסטוריית גרסאות</h4>
        <div id="synopsisHistory" class="list" style="max-height: 25vh; font-size: 13px; white-space: pre-wrap;"></div>
      </div>
      <div id="synopsisCardView" style="display:none;" class="list"></div>
    </div> 
    <footer style="justify-content: space-between;">
        <div class="rowflex">
            <button id="clearSynopsisHistoryBtn" class="linklike">נקה היסטוריית גרסאות</button>
        </div>
        <button id="saveSynopsisBtn" class="linklike">שמור תקציר</button>
    </footer> 
  </div>
  <div id="histModal" class="modal"> <header><strong>היסטוריית שאלות</strong><div><button id="clearHistBtn" class="linklike">נקה</button><button id="closeHistBtn" class="linklike">סגור</button></div></header> <div id="histContent" class="content"></div> </div>
  <div id="rulesModal" class="modal"> <header><strong>כללים</strong><button id="closeRulesBtn" class="linklike">סגור</button></header> <div class="content" id="rulesContent"> <h3>כללי גג <span class="pill">חלים על כל הפרויקטים</span></h3> <div id="rulesGlobal"></div> <div class="rowflex"> <textarea id="newGlobalText" style="flex:1; height:56px"></textarea> <select id="newGlobalMode"><option value="enforce">אכיפה</option><option value="warn">אזהרה</option><option value="off">כבוי</option></select> <button id="addGlobalBtn" class="linklike">הוסף</button> </div> <hr> <h3>כללי פרויקט <span class="pill">רק לפרויקט הנוכחי</span></h3> <div id="rulesProject"></div> <div class="rowflex"> <textarea id="newProjectText" style="flex:1; height:56px"></textarea> <select id="newProjectMode"><option value="enforce">אכיפה</option><option value="warn">אזהרה</option><option value="off">כבוי</option></select> <button id="addProjectBtn" class="linklike">הוסף</button> </div> </div> </div>
  <div id="libraryModal" class="modal"> <header> <strong>ספרייה מרכזית</strong> <div class="rowflex"> <input type="text" id="libSearch" placeholder="חפש..." style="min-width:220px"> <label class="linklike" for="libUpload">העלה קבצים</label> <input type="file" id="libUpload" style="display:none" multiple accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp"> <button id="closeLibraryBtn" class="linklike">סגור</button> </div> </header> <div class="content"> <div class="small muted">סוגי קבצים נתמכים: PDF, DOCX, TXT, PNG, JPG, JPEG, WEBP</div> <div id="libraryList" class="list"></div> </div> </div>
  <div id="libraryAttachModal" class="modal"> <header> <strong>צרף קבצים מהספרייה</strong> <button id="closeLibraryAttachBtn" class="linklike">סגור</button></header> <div id="libraryAttachList" class="content list"></div> <footer><button id="attachSelectedBtn" class="linklike">צרף נבחרים לשיחה</button></footer></div>
  <div id="discussionModal" class="modal"> <header><strong id="discussionTitle">דיון בביקורת</strong><button id="closeDiscussionBtn" class="linklike">סגור</button></header> <div id="discussionThread" class="content list" style="max-height: 50vh;"></div> <footer style="background:#f8f8f8; align-items:center;"><input id="discussionInput" placeholder="שאל שאלה על ממצאי הביקורת..." style="flex:1; padding: 8px;"><button id="updateReviewBtn" class="linklike">עדכן דוח ביקורת</button><button id="askDiscussionBtn" class="linklike">שלח</button></footer></div>
  <div id="objectLabModal" class="modal">
    <header><strong>🔬 מעבדת האובייקטים</strong><button id="closeObjectLabBtn" class="linklike">סגור</button></header>
    <div class="content two-col">
        <div class="box">
            <h4 style="margin-top:0;">יצירת אובייקט חדש</h4>
            <div class="field"><label>שם האובייקט (מילה אחת, לזיהוי אוטומטי):</label><input id="objName" placeholder="למשל: שמוליק"></div>
            <div class="field"><label>סגנון:</label><input id="objStyle" placeholder="ריאליסטי, קומיקס, שחור לבן..."></div>
            <div class="field"><label>תיאור ויזואלי (מאפייני עקביות):</label><textarea id="objDesc" rows="4" placeholder="ילד עם שיער ג'ינג'י, פנים מנומשות..."></textarea></div>
            <div class="rowflex"><button id="createObjectBtn" class="linklike">צור תמונת ייחוס</button><div id="objStatus" class="rowflex" style="gap:8px;"></div></div>
        </div>
        <div class="box">
            <h4 style="margin-top:0;">ספריית האובייקטים של הפרויקט</h4>
            <div id="object-gallery" class="list"></div>
        </div>
    </div>
  </div>

<script>
(function(){
  const pid = Number(document.body.getAttribute('data-project-id'));
  let tempFileIds = [], libraryFileIds = [];
  let editingImageId = null;
  
  function esc(s){return (s||"").replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
  function fmtTime(iso){ const d=new Date(iso); return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
  const backdrop = document.getElementById('backdrop');
  function openModal(el){ if(el) {el.style.display="block"; backdrop.style.display="block";} }
  function closeAllModals(){ document.querySelectorAll('.modal').forEach(m=>m.style.display="none"); backdrop.style.display="none"; }
  backdrop.addEventListener("click", closeAllModals);
  
  function safeAttach(id, event, handler) {
      const el = document.getElementById(id);
      if (el) { el.addEventListener(event, handler); }
  }

  // JAVASCRIPT SCOPE FIX: Function moved to global scope of the IIFE
  async function loadSynopsisHistory() {
      const historyEl = document.getElementById('synopsisHistory');
      historyEl.innerHTML = `<div class="muted">טוען היסטוריה...</div>`;
      try {
          const res = await fetch(`/api/project/${pid}/synopsis_history`);
          const data = await res.json();
          if (!data.items || data.items.length === 0) {
              historyEl.innerHTML = `<div class="muted">אין היסטוריית גרסאות.</div>`;
              return;
          }
          historyEl.innerHTML = data.items.map(item => `
              <div class="li">
                  <div class="rowflex" style="justify-content: space-between;">
                      <strong>גרסה מתאריך ${new Date(item.created_at).toLocaleString('he-IL')}</strong>
                      <button class="linklike restore-synopsis-btn">שחזר</button>
                  </div>
                  <div class="box" style="margin-top:4px;">${esc(item.text)}</div>
              </div>
          `).join('');
          historyEl.querySelectorAll('.restore-synopsis-btn').forEach(btn => {
              btn.addEventListener('click', (e) => {
                  const text = e.target.closest('.li').querySelector('.box').textContent;
                  document.getElementById('synopsisArea').value = text;
                  alert('הגרסה שוחזרה לעורך. לחץ "שמור תקציר" כדי לשמור את השינויים.');
              });
          });
      } catch (e) {
          historyEl.innerHTML = `<div class="muted">שגיאה בטעינת ההיסטוריה.</div>`;
      }
  }

  // --- Main UI Logic ---
  const modeRadios = [...document.getElementsByName('mode')], writeKindEl = document.getElementById('writeKind'), brainstormControls = document.getElementById('brainstormControls');
  function applyModeUI(){
      const mode = modeRadios.find(r=>r.checked).value;
      if (writeKindEl) writeKindEl.style.display = (mode==='write') ? 'inline-block' : 'none';
      if (document.getElementById('chatPanel')) document.getElementById('chatPanel').style.display = (mode==='review' || mode==='illustrate') ? 'none' : 'block';
      if (brainstormControls) brainstormControls.style.display = (mode ==='brainstorm' || mode ==='write') ? 'flex' : 'none';
      if (document.getElementById('reviewPanel')) document.getElementById('reviewPanel').style.display = (mode==='review') ? 'block' : 'none';
      if (document.getElementById('illustratePanel')) document.getElementById('illustratePanel').style.display = (mode==='illustrate') ? 'block' : 'none';
      if (mode==='illustrate') { loadGallery(); }
      if (mode==='review') { loadReviewList(); }
  }
  modeRadios.forEach(r=> r.addEventListener('change', applyModeUI));
  
  // --- Modals & General Buttons ---
  safeAttach('notesBtn', 'click', async () => { openModal(document.getElementById('notesModal')); const notesArea = document.getElementById('notesArea'); notesArea.value = "טוען..."; try { const res = await fetch("/general/"+pid); const data = await res.json(); notesArea.value = data.text || ""; } catch (e) { notesArea.value = "שגיאה בטעינת הקובץ."; } });
  safeAttach('closeNotesBtn', 'click', closeAllModals);
  safeAttach('saveNotesBtn', 'click', async () => { try{ const res = await fetch("/general/"+pid, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ text: document.getElementById('notesArea').value })}); if (!res.ok) throw new Error('שגיאת שרת'); alert("נשמר"); closeAllModals(); }catch(e){ alert("שגיאה: " + e.message); } });
  
  // --- Synopsis Modal Logic ---
  const synopsisBtn = document.getElementById('synopsisBtn');
  if(synopsisBtn) {
    synopsisBtn.addEventListener("click", async () => { 
        openModal(document.getElementById('synopsisModal')); 
        const synopsisArea = document.getElementById('synopsisArea'); 
        synopsisArea.value = "טוען..."; 
        try { 
            const res = await fetch("/project/"+pid+"/synopsis"); 
            const data = await res.json(); 
            synopsisArea.value = data.text || ""; 
            await loadSynopsisHistory();
        } catch(e) { 
            synopsisArea.value = "שגיאה בטעינת התקציר."; 
        } 
    });
    safeAttach('closeSynopsisBtn', 'click', closeAllModals);
    safeAttach('saveSynopsisBtn', 'click', async () => { 
        try{ 
            const res = await fetch("/project/"+pid+"/synopsis", {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ text: document.getElementById('synopsisArea').value })}); 
            if (!res.ok) throw new Error('שגיאת שרת'); 
            alert("נשמר"); 
            closeAllModals(); 
        } catch(e) { 
            alert("שגיאה: " + e.message); 
        } 
    });
    safeAttach('synopsisToggleViewBtn', 'click', (e) => {
        const editorView = document.getElementById('synopsisEditorView');
        const cardView = document.getElementById('synopsisCardView');
        if (editorView.style.display !== 'none') {
            editorView.style.display = 'none';
            cardView.style.display = 'block';
            e.target.textContent = 'הצג עורך טקסט';
            renderSynopsisCards(document.getElementById('synopsisArea').value);
        } else {
            editorView.style.display = 'block';
            cardView.style.display = 'none';
            e.target.textContent = 'הצג כרטיסיות פרקים';
        }
    });
    
    function renderSynopsisCards(synopsisText) {
        const cardView = document.getElementById('synopsisCardView');
        cardView.innerHTML = '<div class="spinner"></div>';
        fetch(`/api/project/${pid}/parse_synopsis`, {
            method: "POST",
            headers: {'Content-Type':'application/x-www-form-urlencoded'},
            body: new URLSearchParams({text: synopsisText})
        }).then(res => res.json()).then(data => {
            if (!data.chapters || data.chapters.length === 0) {
                cardView.innerHTML = `<div class="muted">לא נמצאו פרקים בתקציר. ודא שהכותרות בפורמט 'פרק X:'.</div>`;
                return;
            }
            cardView.innerHTML = data.chapters.map(chap => `
                <div class="chapter-card">
                    <h5>${esc(chap.title)}</h5>
                    <div class="small muted" style="white-space: pre-wrap;">${esc(chap.content)}</div>
                    <button class="linklike write-chapter-btn" data-content="${esc(chap.title)}">✍️ כתוב את הפרק</button>
                </div>
            `).join('');
            cardView.querySelectorAll('.write-chapter-btn').forEach(btn => {
                btn.addEventListener('click', writeChapterFromCard);
            });
        });
    }

    async function writeChapterFromCard(e) {
        const content = e.target.getAttribute('data-content');
        if (!confirm(`האם לכתוב את הפרק: "${content}"? התוצאה תתווסף לחלון השיחה הראשי.`)) return;
        closeAllModals();
        
        const status = document.getElementById('status');
        status.innerHTML = `<div class="spinner"></div> <span>כותב את הפרק...</span>`;
        try {
            const body = new URLSearchParams({ 
                text: content,
                mode: 'write', 
                write_kind: 'breakdown_chapter',
                use_notes: '1', use_history: '1' 
            });
            const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
            if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
            await loadChat();
        } catch (err) {
            alert("שגיאה בכתיבת הפרק: " + err.message);
        } finally {
            status.innerHTML = "";
            document.getElementById('chatPanel').scrollIntoView({behavior: 'smooth'});
        }
    }
  }

  safeAttach('divideSynopsisBtn', 'click', async () => {
    const synopsisArea = document.getElementById('synopsisArea');
    const currentSynopsis = synopsisArea.value;
    if (!currentSynopsis.trim()) { alert("לא ניתן לחלק תקציר ריק."); return; }
    if (!confirm("פעולה זו תשמור את הגרסה הנוכחית של התקציר בהיסטוריה, ולאחר מכן תשלח אותו למודל לחלוקה לפרקים. התוצאה תחליף את הטקסט הנוכחי בעורך. האם להמשיך?")) return;
    
    const status = document.getElementById('status');
    status.innerHTML = `<div class="spinner"></div> <span>מחלק את התקציר...</span>`;
    try {
        const body = new URLSearchParams({ 
            mode: 'write', 
            write_kind: 'divide_synopsis', 
            synopsis_text_content: currentSynopsis 
        });
        const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
        const data = await res.json();
        if (!res.ok) { throw new Error(data.answer || 'שגיאת שרת'); }
        synopsisArea.value = data.answer || "לא התקבלה תשובה מהמודל.";
        alert("התקציר חולק לפרקים. ניתן כעת לשמור אותו או לעבור לתצוגת כרטיסיות.");
        await loadSynopsisHistory(); // Refresh history to show the newly saved version
        openModal(document.getElementById('synopsisModal'));
    } catch(e) {
        alert("שגיאה בחלוקת התקציר: " + e.message);
    } finally {
        status.innerHTML = "";
    }
  });

  safeAttach('clearSynopsisHistoryBtn', 'click', async () => {
    if (!confirm("האם למחוק את כל היסטוריית הגרסאות של התקציר? פעולה זו היא בלתי הפיכה.")) return;
    try {
        const res = await fetch(`/api/project/${pid}/synopsis_history/clear`, { method: "POST" });
        if (!res.ok) throw new Error("Server error");
        await loadSynopsisHistory();
        alert("היסטוריית התקציר נמחקה.");
    } catch (e) {
        alert("שגיאה במחיקת ההיסטוריה.");
    }
  });

  safeAttach('historyBtn', 'click', async () => { const histContent = document.getElementById('histContent'); openModal(document.getElementById('histModal')); histContent.innerHTML = "<div class='muted'>טוען...</div>"; const res = await fetch("/history/"+pid); const data = await res.json(); if (!data.items.length) { histContent.innerHTML = "<div class='muted'>אין היסטוריה.</div>"; return; } histContent.innerHTML = data.items.map(q => `<div class='li' title='לחץ להעתקה'>${esc(q)}</div>`).join(""); [...histContent.querySelectorAll('.li')].forEach(el=>{ el.addEventListener("click", ()=>{ document.getElementById('prompt').value = el.textContent; document.getElementById('prompt').focus(); closeAllModals(); }); }); });
  safeAttach('closeHistBtn', 'click', closeAllModals);
  safeAttach('clearHistBtn', 'click', async ()=>{ if (!confirm("למחוק היסטוריה?")) return; await fetch("/history/"+pid+"/clear", {method:"POST"}); document.getElementById('histContent').innerHTML = "<div class='muted'>נמחק.</div>"; });
  
  safeAttach('rulesBtn', 'click', async ()=>{ openModal(document.getElementById('rulesModal')); await loadRules(); });
  safeAttach('closeRulesBtn', 'click', closeAllModals);
  async function loadRules(){
      try {
        const res = await fetch("/rules/"+pid); const data = await res.json();
        function ruleRow(r){return `<div class="rowflex rule" data-id="${r.id}"><textarea style="flex:1; height:56px">${esc(r.text)}</textarea><select><option value="enforce" ${r.mode==="enforce"?"selected":""}>אכיפה</option><option value="warn" ${r.mode==="warn"?"selected":""}>אזהרה</option><option value="off" ${r.mode==="off"?"selected":""}>כבוי</option></select><button class="linklike save">שמור</button><button class="linklike del">מחק</button></div>`;}
        document.getElementById('rulesGlobal').innerHTML = data.global.map(ruleRow).join("") || "<div class='muted'>אין.</div>";
        document.getElementById('rulesProject').innerHTML = data.project.map(ruleRow).join("") || "<div class='muted'>אין.</div>";
        [...document.querySelectorAll("#rulesModal .rule")].forEach(row=>{
            const id = row.getAttribute("data-id");
            row.querySelector(".save").addEventListener("click", async ()=>{ const text = row.querySelector("textarea").value, mode = row.querySelector("select").value; await fetch(`/rules/${pid}/update`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id, text, mode })}); alert("נשמר"); });
            row.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/rules/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadRules();} });
        });
      } catch (e) { document.getElementById('rulesContent').innerHTML = "שגיאה בטעינת הכללים."; }
  }
  safeAttach('addGlobalBtn', 'click', async () => { const text = document.getElementById('newGlobalText').value, mode = document.getElementById('newGlobalMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'global', text, mode})}); await loadRules(); document.getElementById('newGlobalText').value = ""; });
  safeAttach('addProjectBtn', 'click', async () => { const text = document.getElementById('newProjectText').value, mode = document.getElementById('newProjectMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'project', text, mode})}); await loadRules(); document.getElementById('newProjectText').value = ""; });
  
  // --- Chat Panel ---
  const promptEl = document.getElementById('prompt');
  const tempSlider = document.getElementById('temperature');
  const tempValue = document.getElementById('tempValue');
  if (tempSlider) tempSlider.addEventListener('input', () => { tempValue.textContent = tempSlider.value; });
  async function loadChat(){
      try {
          const res = await fetch("/chat/"+pid);
          const data = await res.json();
          const resultEl = document.getElementById('result');
          resultEl.innerHTML = !data.items.length ? "" : data.items.map(t =>  
              `<div class="turn a"><div class="meta"><span>סופר • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.answer)}<button title="העתק" class="linklike copy-bubble">📋</button></div></div>
               <div class="turn q"><div class="meta"><span>אתה • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.question)}</div></div>`
          ).join("");
          resultEl.querySelectorAll('.copy-bubble').forEach(btn => {
              btn.addEventListener('click', (e) => {
                  const bubble = e.target.closest('.bubble');
                  const textToCopy = bubble.textContent.replace(/📋$/, '').trim();
                  navigator.clipboard.writeText(textToCopy);
                  const originalText = e.target.textContent;
                  e.target.textContent = '✓';
                  setTimeout(() => { e.target.textContent = originalText; }, 1200);
              });
          });
          resultEl.scrollTop = 0;
      } catch(e) { console.error("Failed to load chat", e); }
  }
  safeAttach('tempFileUpload', 'change', async (e) => {
      const files = e.target.files;
      if (!files.length) return;
      const status = document.getElementById('status');
      status.innerHTML = `<div class="spinner"></div> <span>מעלה קבצים...</span>`;
      const fd = new FormData();
      for (const file of files) { fd.append("files", file); }
      try {
          const res = await fetch(`/upload_temp_files/${pid}`, { method: "POST", body: fd });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error);
          tempFileIds.push(...data.file_ids);
          const listEl = document.getElementById('attached-files-list');
          listEl.innerHTML += data.filenames.map(name => `<span class="pill" data-type="temp">${esc(name)}</span>`).join("");
      } catch(err) { alert("שגיאה בהעלאת קבצים: " + err.message); }
      finally { status.innerHTML = ""; e.target.value = ""; }
  });
  safeAttach('sendBtn', 'click', async () => {
    const text = promptEl.value.trim();
    if (!text && tempFileIds.length === 0 && libraryFileIds.length === 0) return;
    const btn = document.getElementById('sendBtn'), status = document.getElementById('status');
    btn.disabled = true;
    status.innerHTML = `<div class="spinner"></div> <span>חושב...</span>`;
    try {
        const body = new URLSearchParams({ text, temperature: tempSlider.value, persona: document.getElementById('personaSelector').value, use_notes: document.getElementById('useNotes').checked ? "1" : "0", mode: modeRadios.find(r=>r.checked).value, write_kind: writeKindEl.value, use_history: document.getElementById('useHistory').checked ? "1" : "0" });
        tempFileIds.forEach(id => body.append("temp_file_ids", id));
        libraryFileIds.forEach(id => body.append("library_file_ids", id));
        const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
        if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
        await loadChat();
        promptEl.value = "";
        tempFileIds = [];
        libraryFileIds = [];
        document.getElementById('attached-files-list').innerHTML = "";
    } catch(e) { alert("שגיאה: " + e.message); await loadChat(); }
    finally { status.innerHTML = ""; btn.disabled = false; promptEl.focus(); }
  });
  safeAttach('clearChatBtn', 'click', async ()=>{ if (confirm("למחוק שיחה?")) { await fetch("/chat/"+pid+"/clear", {method:"POST"}); loadChat(); } });

  // --- Review Panel Logic --
  safeAttach('tabGeneral', 'click', ()=>setTab('general'));
  safeAttach('tabProof', 'click', ()=>setTab('proofread'));
  let currentReviewKind = 'general';
  function setTab(kind){ currentReviewKind = kind; document.getElementById('tabGeneral').classList.toggle('active', kind==='general'); document.getElementById('tabProof').classList.toggle('active', kind==='proofread'); loadReviewList(); document.getElementById('reviewOut').textContent = ''; }
  const discussionModal = document.getElementById('discussionModal');
  safeAttach('closeDiscussionBtn', 'click', closeAllModals);
  async function openDiscussionModal(reviewId, reviewTitle) {
      discussionModal.setAttribute('data-review-id', reviewId);
      document.getElementById('discussionTitle').textContent = "דיון בביקורת: " + reviewTitle;
      await loadDiscussion(reviewId);
      openModal(discussionModal);
  }
  async function loadDiscussion(rid){
      const discussionThread = document.getElementById('discussionThread');
      discussionThread.innerHTML = "<div class='muted'>טוען...</div>";
      try {
          const res = await fetch(`/review/${pid}/discussion/${rid}`);
          const data = await res.json();
          discussionThread.innerHTML = !data.items.length ? "<div class='muted'>אין הודעות.</div>" : data.items.map(m=>`<div class="li"><div class="meta">${m.role==='user'?'אתה':'סופר'} • ${new Date(m.created_at).toLocaleString()}</div><div class="bubble">${esc(m.message)}</div></div>`).join("");
          discussionThread.scrollTop = discussionThread.scrollHeight;
      } catch(e) { discussionThread.innerHTML = "<div class='muted'>שגיאה בטעינת הדיון.</div>"; }
  }
  safeAttach('askDiscussionBtn', 'click', async () => {
      const rid = discussionModal.getAttribute('data-review-id'), input = document.getElementById('discussionInput'), q = (input.value||"").trim();
      if (!rid || !q) return;
      const btn = document.getElementById('askDiscussionBtn');
      btn.disabled = true;
      try{
          await fetch(`/review/${pid}/discuss`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ review_id: rid, question: q })});
          input.value = "";
          await loadDiscussion(rid);
      } catch(e){alert("שגיאה");} finally{ btn.disabled=false; input.focus(); }
  });
  safeAttach('updateReviewBtn', 'click', async () => {
      const rid = discussionModal.getAttribute('data-review-id');
      if (!rid || !confirm("האם לעדכן את דוח הביקורת המקורי על סמך הדיון?")) return;
      const btn = document.getElementById('updateReviewBtn');
      btn.disabled = true; btn.textContent = "מעדכן...";
      try {
          const res = await fetch(`/review/${pid}/update_from_discussion`, {method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({review_id: rid})});
          if (!res.ok) throw new Error("Failed to update review.");
          alert("דוח הביקורת עודכן!");
          closeAllModals();
          await loadReviewList();
      } catch (e) { alert("שגיאה בעדכון הדוח: " + e.message); }
      finally { btn.disabled = false; btn.textContent = "עדכן דוח ביקורת"; }
  });
  async function loadReviewList(){
      const reviewList = document.getElementById('reviewList');
      reviewList.innerHTML = `<div class="muted">טוען...</div>`;
      const res = await fetch(`/reviews/${pid}?kind=${currentReviewKind}`);
      const data = await res.json();
      reviewList.innerHTML = !data.items.length ? "<div class='muted'>אין ביקורות קודמות.</div>" : data.items.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex"><h4 title="${new Date(it.created_at).toLocaleString()}">${esc(it.title)}</h4><button class="linklike show">הצג</button><button class="linklike discuss">דיון</button><button class="linklike del">מחק</button></div><div class="box body" style="display:none; white-space:pre-wrap;">${esc(it.result||"")}</div></div>`).join("");
      [...reviewList.querySelectorAll(".li")].forEach(li=>{
          const id = li.getAttribute("data-id"), title = li.querySelector("h4").textContent;
          li.querySelector(".show").addEventListener("click", ()=>{ const body = li.querySelector(".body"); body.style.display = (body.style.display==="none" ? "block" : "none"); });
          li.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/reviews/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadReviewList();} });
          li.querySelector(".discuss").addEventListener("click", ()=> openDiscussionModal(id, title));
      });
  }
  safeAttach('runReviewBtn', 'click', async () => {
      const rvStatus = document.getElementById('rvStatus'), reviewOut = document.getElementById('reviewOut'), btn = document.getElementById('runReviewBtn');
      rvStatus.innerHTML = ""; reviewOut.textContent = "";
      try{
          let text = document.getElementById('reviewInput').value.trim();
          let source = "pasted";
          if (!text){
              if (!document.getElementById('rvUseNotesWhenEmpty').checked) return;
              const g = await (await fetch("/general/"+pid)).json();
              text = (g.text||"").trim();
              source = "notes";
              if (!text) { alert("הקובץ הכללי ריק."); return; }
          }
          rvStatus.innerHTML = `<div class="spinner"></div> <span>מריץ ביקורת... (זה עשוי לקחת זמן)</span>`;
          btn.disabled = true;
          const res = await fetch(`/review/${pid}/run`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind: currentReviewKind, source, input_text: text }) });
          const data = await res.json();
          if (!res.ok) { throw new Error(data.error || "שגיאה לא ידועה מהשרת"); }
          reviewOut.textContent = data.result || "—";
          await loadReviewList();
          rvStatus.textContent = "הושלם!";
      } catch(e) { rvStatus.textContent = "שגיאה"; alert("שגיאה: "+(e.message||e)); }
      finally { btn.disabled = false; }
  });

  // -- Illustration & Object Lab Logic --
  safeAttach('objectLabBtn', 'click', async () => { openModal(document.getElementById('objectLabModal')); await loadObjects(); });
  safeAttach('closeObjectLabBtn', 'click', closeAllModals);
  async function loadObjects() {
      const gallery = document.getElementById('object-gallery');
      gallery.innerHTML = `<div class="muted">טוען...</div>`;
      try {
          const res = await fetch(`/project/${pid}/objects/list`);
          if (!res.ok) throw new Error("Server responded with an error");
          const data = await res.json();
          gallery.innerHTML = !data.items.length ? "<div class='muted'>אין אובייקטים.</div>" : data.items.map(obj => `
              <div class="object-card" data-id="${obj.id}">
                  <a href="${obj.reference_image_path}" target="_blank" title="הצג בגודל מלא">
                    <img src="${obj.reference_image_path}" alt="${esc(obj.name)}">
                  </a>
                  <h5>${esc(obj.name)}</h5>
                  <div class="rowflex" style="justify-content:center;">
                    <button class="linklike small edit-obj" data-name="${esc(obj.name)}" data-style="${esc(obj.style)}" data-desc="${esc(obj.description)}">ערוך</button>
                    <button class="linklike small del-obj">מחק</button>
                  </div>
              </div>`).join("");
          
          gallery.querySelectorAll('.del-obj').forEach(btn => {
              btn.addEventListener("click", async (e) => {
                  e.stopPropagation();
                  const id = e.target.closest('.object-card').getAttribute('data-id');
                  if (confirm("למחוק את האובייקט?")) {
                      await fetch(`/project/${pid}/objects/delete`, {method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({object_id: id})});
                      await loadObjects();
                  }
              });
          });
          
          gallery.querySelectorAll('.edit-obj').forEach(btn => {
              btn.addEventListener("click", (e) => {
                  e.stopPropagation();
                  document.getElementById('objName').value = e.target.getAttribute('data-name');
                  document.getElementById('objStyle').value = e.target.getAttribute('data-style');
                  document.getElementById('objDesc').value = e.target.getAttribute('data-desc');
                  alert("פרטי האובייקט נטענו לטופס. שנה אותם ולחץ 'צור' כדי ליצור גרסה חדשה לצד המקור.");
                  document.getElementById('objName').focus();
              });
          });

      } catch (e) { 
          console.error("Error in loadObjects:", e);
          gallery.innerHTML = `<div class="muted">שגיאה בטעינת אובייקטים.</div>`; 
      }
  }
  safeAttach('createObjectBtn', 'click', async () => {
      const name = document.getElementById('objName').value.trim();
      const desc = document.getElementById('objDesc').value.trim();
      const style = document.getElementById('objStyle').value.trim();
      if (!name || !desc) { alert("חובה למלא שם ותיאור לאובייקט."); return; }
      const btn = document.getElementById('createObjectBtn'), status = document.getElementById('objStatus');
      btn.disabled = true;
      status.innerHTML = `<div class="spinner"></div> <span>מייצר תמונת ייחוס...</span>`;
      try {
          const res = await fetch(`/project/${pid}/objects/create`, { method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({name, description: desc, style}) });
          if (!res.ok) { const data = await res.json(); throw new Error(data.error || "שגיאת שרת"); }
          status.textContent = "נוצר!"; 
          document.getElementById('objName').value = '';
          document.getElementById('objDesc').value = '';
          document.getElementById('objStyle').value = '';
          await loadObjects();
      } catch (e) { 
          status.textContent = "שגיאה."; 
          alert("שגיאה ביצירת אובייקט: " + e.message); 
      } finally { 
          btn.disabled = false; 
      }
  });
  safeAttach('genImageBtn', 'click', async () => {
      const desc = document.getElementById('imgDesc').value.trim();
      if (!desc) return;
      const btn = document.getElementById('genImageBtn'), status = document.getElementById('imgStatus');
      btn.disabled = true;
      status.innerHTML = `<div class="spinner"></div> <span>מייצר סצנה...</span>`;
      try{
          const body = new URLSearchParams({ desc, style: document.getElementById('imgStyle').value || "", scene_label: document.getElementById('imgScene').value || "" });
          if (editingImageId) {
              body.append('source_image_id', editingImageId);
          }
          const res = await fetch(`/image/${pid}`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
          if (!res.ok) { const err = await res.json(); throw new Error(err.error || "שגיאה לא ידועה מהשרת"); }
          await loadGallery();
          status.innerHTML = "נוצר ✓";
          setTimeout(()=> status.innerHTML ="", 2000);
          cancelEditMode();
      } catch(e) { 
          alert("שגיאה: " + e.message); 
          status.innerHTML = "שגיאה."; 
      } finally { 
          btn.disabled = false; 
      }
  });
  function cancelEditMode() {
      editingImageId = null;
      document.getElementById('editingIndicator').style.display = 'none';
  }
  safeAttach('cancelEditBtn', 'click', cancelEditMode);

  async function loadGallery(){
      const gallery = document.getElementById('gallery');
      gallery.innerHTML = "<div class='muted'>טוען...</div>";
      try {
        const res = await fetch("/images/"+pid);
        if (!res.ok) throw new Error("Server responded with an error");
        const data = await res.json();
        if (!data.items.length){ gallery.innerHTML = "<div class='muted'>אין איורים.</div>"; return; }
        gallery.innerHTML = data.items.map(it => `<div class="card" data-id="${it.id}">
          <img src="${it.file_path}">
          <div class="small">${it.style?esc(it.style)+" • ":""}${it.scene_label?esc(it.scene_label)+" • ":""}${new Date(it.created_at).toLocaleString()}</div>
          <div class="small" title="${esc(it.prompt)}">${esc((it.prompt||"").slice(0,80))}...</div>
          <div class="rowflex">
              <a class="linklike" href="${it.file_path}" download>הורד</a>
              <a class="linklike" href="${it.file_path}" target="_blank">פתח</a>
              <button class="linklike edit-img" data-id="${it.id}" data-prompt="${esc(it.prompt)}">ערוך</button>
              <button class="linklike delimg">מחק</button>
          </div>
        </div>`).join("");

        gallery.querySelectorAll(".delimg").forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".card").getAttribute("data-id"); if (!confirm("למחוק?")) return; await fetch(`/images/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadGallery(); }); });
        gallery.querySelectorAll('.edit-img').forEach(btn => {
            btn.addEventListener('click', (e) => {
                editingImageId = e.target.getAttribute('data-id');
                const prompt = e.target.getAttribute('data-prompt');
                document.getElementById('imgDesc').value = prompt;
                document.getElementById('editingIndicator').style.display = 'block';
                document.getElementById('illustratePanel').scrollIntoView({ behavior: 'smooth' });
            });
        });
      } catch (e) {
          console.error("Error in loadGallery:", e);
          gallery.innerHTML = `<div class="muted">שגיאה בטעינת הגלריה.</div>`;
      }
  }

  // --- Library Modal & Attachment Logic ---
  safeAttach('libraryBtn', 'click', async ()=>{ openModal(document.getElementById('libraryModal')); await loadLibrary(); });
  safeAttach('closeLibraryBtn', 'click', closeAllModals);
  safeAttach('attachFromLibraryBtn', 'click', async () => {
      const modal = document.getElementById('libraryAttachModal');
      const listEl = document.getElementById('libraryAttachList');
      listEl.innerHTML = `<div class="muted">טוען קבצים מהספרייה...</div>`;
      openModal(modal);
      try {
        const res = await fetch('/api/library/list');
        const data = await res.json();
        if (!data.items.length) {
            listEl.innerHTML = `<div class="muted">הספרייה ריקה.</div>`;
            return;
        }
        listEl.innerHTML = data.items.map(item => `<div class="li"><label><input type="checkbox" value="${item.id}" data-filename="${esc(item.filename)}"> ${esc(item.filename)}</label></div>`).join('');
      } catch(e) { listEl.innerHTML = `<div class="muted">שגיאה בטעינת הספרייה.</div>`; }
  });
  safeAttach('closeLibraryAttachBtn', 'click', closeAllModals);
  safeAttach('attachSelectedBtn', 'click', () => {
      const attachedFilesList = document.getElementById('attached-files-list');
      document.querySelectorAll('#libraryAttachList input:checked').forEach(checkbox => {
          const fileId = checkbox.value;
          const filename = checkbox.getAttribute('data-filename');
          if (!libraryFileIds.includes(fileId)) {
              libraryFileIds.push(fileId);
              attachedFilesList.innerHTML += `<span class="pill" data-type="library" data-id="${fileId}">${filename}</span>`;
          }
      });
      closeAllModals();
  });
  async function loadLibrary(){
      const libraryList = document.getElementById('libraryList');
      libraryList.innerHTML = `<div class="muted">טוען...</div>`;
      try {
          function renderLibrary(items){
              const q = (document.getElementById('libSearch').value||"").trim().toLowerCase();
              const rows = items.filter(it => !q || (it.filename||"").toLowerCase().includes(q));
              if (!rows.length){ libraryList.innerHTML = "<div class='muted'>אין קבצים.</div>"; return; }
              libraryList.innerHTML = rows.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex" style="justify-content:space-between; gap:12px"><div><h4>${esc(it.filename)}</h4><div class="small">${esc(it.ext)} • ${(it.size/1024).toFixed(1)}KB • ${new Date(it.uploaded_at).toLocaleString()}</div><div class="rowflex"><a class="linklike" href="${it.url}" target="_blank">פתח</a><a class="linklike" href="${it.url}" download>הורד</a><button class="linklike del">מחק</button></div></div></div></div>`).join("");
              [...libraryList.querySelectorAll(".del")].forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".li").getAttribute("data-id"); if(!confirm("למחוק?")) return; await fetch("/api/library/delete", { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ id })}); await loadLibrary(); }); });
          }
          const res = await fetch("/api/library/list");
          if (!res.ok) throw new Error("Network response was not ok.");
          const data = await res.json();
          renderLibrary(data.items||[]);
          document.getElementById('libSearch').oninput = () => renderLibrary(data.items||[]);
          document.getElementById('libUpload').onchange = async (e)=>{ if (!e.target.files.length) return; const fd = new FormData(); for (const f of e.target.files) fd.append("files", f); await fetch("/api/library/upload", { method:"POST", body: fd }); await loadLibrary(); e.target.value = ""; };
      } catch (e) {
          libraryList.innerHTML = `<div class="muted">שגיאה בטעינת הספרייה.</div>`;
      }
  }

  // --- Universal Ctrl+Enter Handler ---
  document.addEventListener("keydown", (ev)=>{
    if (ev.ctrlKey && ev.key==="Enter"){
      const activeEl = document.activeElement;
      if (activeEl.id === 'prompt') { document.getElementById('sendBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'reviewInput') { document.getElementById('runReviewBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'discussionInput') { document.getElementById('askDiscussionBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'imgDesc') { document.getElementById('genImageBtn').click(); ev.preventDefault(); }
      if (['objName', 'objStyle', 'objDesc'].includes(activeEl.id)) {
          document.getElementById('createObjectBtn').click();
          ev.preventDefault();
      }
    }
  });
  
  applyModeUI();
  loadChat();
})();
</script>
</body>
</html>
"""

# ====== Routes: Main & Projects ======
@app.get("/", response_class=HTMLResponse)
def home():
    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
    return render(HOME_HTML, projects=projects)

@app.post("/new_project")
def new_project(name: str = Form(...), kind: str = Form(...), age_group: Optional[str] = Form(None), chapters: Optional[int] = Form(None), frames_per_page: Optional[int] = Form(None), total_pages: Optional[int] = Form(None)):
    with Session(engine) as session:
        p = Project(name=name, kind=kind, age_group=age_group, chapters=chapters, frames_per_page=frames_per_page, total_pages=total_pages, synopsis_text="")
        session.add(p)
        session.commit()
        session.refresh(p)
        session.add(GeneralNotes(project_id=p.id, text=""))
        session.commit()
        return RedirectResponse(url=f"/project/{p.id}", status_code=303)

@app.post("/delete_project/{project_id}")
def delete_project(project_id: int):
    with Session(engine) as session:
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
        obj_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}_objects")
        if os.path.exists(obj_dir): shutil.rmtree(obj_dir)
        img_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}")
        if os.path.exists(img_dir): shutil.rmtree(img_dir)
        vector_dir = os.path.join(VECTORSTORE_ROOT, f"project_{project_id}")
        if os.path.exists(vector_dir): shutil.rmtree(vector_dir)
    except Exception as e:
        print(f"Could not clean up asset directories for project {project_id}: {e}")
        
    return RedirectResponse("/", status_code=303)

@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return RedirectResponse("/", status_code=303)
        return render(PROJECT_HTML, project=project)

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
            session.commit()
            session.refresh(gn)

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
            if proj.synopsis_text and proj.synopsis_text.strip():
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
    pattern = re.compile(r"(פרק\s+\d+[:\.\s\w\-]+)\n?([\s\S]*?)(?=פרק\s+\d+[:\.]|\Z)")
    matches = pattern.finditer(text)
    for match in matches:
        title = match.group(1).strip().replace(":", "")
        content = match.group(2).strip()
        chapters.append({"title": title, "content": content})
    return JSONResponse({"chapters": chapters})

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
            r.text = text
            r.mode = mode
            session.add(r)
            session.commit()
    return JSONResponse({"ok": True})

@app.post("/rules/{pid}/delete")
def rules_delete(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r:
            session.delete(r)
            session.commit()
    return JSONResponse({"ok": True})
    
# ====== Routes: Main AI Endpoints ======
@app.post("/upload_temp_files/{project_id}")
async def upload_temp_files(project_id: int, files: List[UploadFile] = File(...)):
    with Session(engine) as session:
        file_ids = []
        filenames = []
        for uf in files:
            ext = _guess_ext(uf.filename)
            uid_filename = f"{uuid.uuid4().hex}{ext}"
            dest_full = _safe_join_under(TEMP_ROOT, uid_filename)
            with open(dest_full, "wb") as f:
                f.write(await uf.read())
            
            text_content = extract_text_from_file(dest_full)
            if text_content:
                index_dir = os.path.join(VECTORSTORE_ROOT, f"project_{project_id}", "temp")
                os.makedirs(index_dir, exist_ok=True)
                index_path = os.path.join(index_dir, uid_filename)
                create_vector_index(text_content, index_path)

                rec = TempFile(project_id=project_id, original_filename=uf.filename, stored_path=dest_full, vector_index_path=index_path)
                session.add(rec)
                session.commit()
                session.refresh(rec)
                file_ids.append(rec.id)
                filenames.append(uf.filename)
    return JSONResponse({"ok": True, "file_ids": file_ids, "filenames": filenames})

@app.post("/ask/{project_id}")
def ask_project(project_id: int, text: str = Form(""), use_notes: str = Form("1"), mode: str = Form(...), write_kind: str = Form(...), use_history: str = Form("1"), temperature: float = Form(0.7), persona: str = Form("partner"), temp_file_ids: List[str] = Form([]), library_file_ids: List[int] = Form([]), synopsis_text_content: Optional[str] = Form(None)):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return JSONResponse({"ok": False, "answer": "Project not found."}, status_code=404)
        
        preamble = build_rules_preamble(project_id)
        
        if project.kind == 'פרוזה':
            prose_master_prompt = """
תפקידך הוא לשמש כעוזר מקצועי לסופר, המתמחה בכתיבת רומני פרוזה. כל המחשבה והפלט שלך חייבים להיות בסגנון ספרותי.
הטקסט ב'קובץ כללי' מהווה את הבסיס וההקשר של עולם הסיפור. עליך להתייחס למידע הקיים בו כאמת המוחלטת של הסיפור עד כה. כל תוכן חדש שאתה יוצר חייב להיות עקבי והמשכי לבסיס זה.
מכיוון שזהו פרויקט פרוזה, עליך להתעלם ולהימנע לחלוטין מכל קונספט של מדיה ויזואלית. חל איסור מוחלט להשתמש במונחים כמו 'פריימים', 'פאנלים', 'תסריט למאייר', 'זוויות מצלמה' או דיאלוג בפורמט של תסריט.
"""
            preamble += prose_master_prompt + "\n\n"

        if mode == 'brainstorm' or mode == 'write':
            if persona == 'assistant':
                preamble += "הפרסונה שלך היא 'עוזר ישיר'. תפקידך להיות תמציתי...\n\n"
            else: 
                preamble += "הפרסונה שלך היא 'שותף יצירתי מקצועי'...\n\n"
        
        # ====== [FIX 3/4] CHAPTER RETRIEVAL LOGIC ======
        notes_context = ""
        # Look for a chapter reference in the user's query
        chapter_match = re.search(r'(?:פרק|עיין בפרק)\s+([א-ת\d]+)', text, re.IGNORECASE)
        
        if chapter_match and use_notes == "1":
            chapter_id = chapter_match.group(1)
            print(f"User requested specific chapter: {chapter_id}")
            gn_obj = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
            if gn_obj and gn_obj.text:
                chapter_content = extract_chapter_text(gn_obj.text, chapter_id)
                if chapter_content:
                    notes_context = f"המשתמש ביקש להתמקד בפרק {chapter_id}. להלן התוכן המלא של הפרק:\n---\n{chapter_content}\n---\n"
                else:
                    notes_context = f"ניסיתי למצוא את פרק {chapter_id} בקובץ הכללי אך לא מצאתי אותו.\n"
        elif use_notes == "1":
            # Standard semantic search if no chapter is specified
            gn_obj = session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first()
            if gn_obj and gn_obj.vector_index_path:
                notes_context = get_relevant_context_from_index(text, gn_obj.vector_index_path)
                if notes_context:
                    notes_context = "להלן קטעים רלוונטיים מתוך 'קובץ כללי' להתייחסותך:\n" + notes_context + "\n\n"
        
        chat_history_str = ""
        if use_history == "1":
            turns = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.desc()).limit(10)).all()
            chat_history_str = "\n".join([f"ש: {t.question}\nת: {t.answer}" for t in reversed(turns)])
        
        file_context = ""
        if temp_file_ids:
            file_context += "ההקשר הבא מבוסס על קבצים זמניים שהמשתמש העלה:\n"
            for file_id in temp_file_ids:
                temp_file = session.get(TempFile, file_id)
                if temp_file and temp_file.vector_index_path:
                    file_context += get_relevant_context_from_index(text, temp_file.vector_index_path)
            file_context += "\n"
        
        if library_file_ids:
            file_context += "ההקשר הבא מבוסס על קבצים מהספרייה:\n"
            lib_files = session.exec(select(LibraryFile).where(LibraryFile.id.in_(library_file_ids))).all()
            for lib_file in lib_files:
                if lib_file.vector_index_path:
                    file_context += get_relevant_context_from_index(text, lib_file.vector_index_path)
            file_context += "\n"

        history_context = "היסטוריית שיחה קודמת:\n" + chat_history_str + "\n\n" if chat_history_str else ""
        full_context = f"{file_context}{notes_context}{history_context}"

        prompt = ""
        if project.kind == 'קומיקס' and write_kind == 'breakdown_chapter':
            synopsis = project.synopsis_text
            extractor_prompt = f"From the following synopsis, extract only the text related to '{text}'. Return only that text, with no preamble.\n\nSYNOPSIS:\n{synopsis}"
            chapter_synopsis = text_model.generate_content(extractor_prompt).text
            pages_per_chapter = (project.total_pages or 54) / (project.chapters or 18)
            prompt = f"{preamble}{full_context}להלן תקציר של פרק בקומיקס:\n---\n{chapter_synopsis}\n---\nהמשימה שלך היא לכתוב את התסריט המפורט עבור הפרק..."
        elif project.kind == 'קומיקס' and write_kind == 'divide_synopsis':
            if not synopsis_text_content or not synopsis_text_content.strip():
                   return JSONResponse({"ok": False, "answer": "Synopsis is empty."}, status_code=400)
            
            history_entry = SynopsisHistory(project_id=project_id, text=synopsis_text_content)
            session.add(history_entry)
            session.commit()

            prompt = f"{preamble}{full_context}לפניך תקציר של סיפור קומיקס. עליך לחלק אותו באופן הגיוני ל-{project.chapters or 18} פרקים...\n\nהתקציר המלא:\n{synopsis_text_content}"
        else:
            prompt = f"{preamble}{full_context}בהתבסס על כל ההקשר שסופק, ענה על הבקשה הבאה: {text}"

        config = genai.types.GenerationConfig(temperature=float(temperature))
        resp = text_model.generate_content(contents=[prompt], generation_config=config)
        answer = resp.text
        tag = f"【{mode}:{write_kind}】" if mode == 'write' else f"【{mode}】"
        
        if write_kind != 'divide_synopsis':
            session.add(History(project_id=project_id, question=f"{tag} {text}", answer=answer)); session.commit()
        
        if temp_file_ids:
            for file_id in temp_file_ids:
                temp_file = session.get(TempFile, file_id)
                if temp_file:
                    if os.path.exists(temp_file.stored_path): os.remove(temp_file.stored_path)
                    if temp_file.vector_index_path and os.path.exists(temp_file.vector_index_path): shutil.rmtree(temp_file.vector_index_path)
                    session.delete(temp_file)
            session.commit()

        return JSONResponse({"ok": True, "answer": answer})

# ====== Routes: Review ======
@app.post("/review/{project_id}/run")
def run_review(project_id: int, kind: str = Form(...), source: str = Form(...), input_text: str = Form(...)):
    rules = build_rules_preamble(project_id)
    title = input_text[:40] + "..." if len(input_text) > 40 else input_text

    if kind == "general":
        prompt = f"{rules}המשימה שלך היא לבצע ביקורת ספרותית מקיפה על הסיפור המלא המצורף...הסיפור המלא לבדיקה:\n{input_text}"
    else:
        prompt = f"בצע הגהה על הטקסט המלא הבא ותקן שגיאות כתיב, דקדוק ופיסוק:\n\n{input_text}"
    
    try:
        result = text_model.generate_content(prompt).text
        with Session(engine) as session:
            review_obj = Review(project_id=project_id, kind=kind, source=source, title=title, result=result, input_size=len(input_text), input_text=input_text)
            session.add(review_obj)
            session.commit()
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
            session.delete(r)
            session.commit()
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
        prompt = f"""אתה מנהל דיון על דוח ביקורת שכתבת...הטקסט המקורי שנבדק:\n---\n{rev.input_text}\n---\nדוח הביקורת שכתבת:\n---\n{rev.result}\n---\nהשאלה החדשה של המשתמש: {question}"""
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
        prompt = f"""...הטקסט המקורי שנבדק:\n---\n{rev.input_text}\n---\nדוח הביקורת הישן והשגוי שכתבת:\n---\n{rev.result}\n---\nתמלול הדיון שבו התגלו הטעויות:\n---\n{thread}\n---\nאנא כתוב גרסה חדשה, מתוקנת ומשופרת של דוח הביקורת..."""
        try:
            new_result = text_model.generate_content(prompt).text
            rev.result = new_result
            session.add(rev)
            session.commit()
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ====== Routes: Illustration & Object Lab ======
@app.get("/project/{project_id}/objects/list")
def list_objects(project_id: int):
    with Session(engine) as session:
        objects = session.exec(select(ProjectObject).where(ProjectObject.project_id == project_id).order_by(ProjectObject.created_at.desc())).all()
        return JSONResponse({"items": [o.model_dump(mode='json') for o in objects]})

@app.post("/project/{project_id}/objects/create")
def create_object(project_id: int, name: str = Form(...), description: str = Form(...), style: str = Form("")):
    # ====== [FIX 2/4] REMOVED PROMPT REWRITING FOR OBJECTS ======
    raw_prompt = f"A single character reference image named '{name}'. {description}. Style: {style}. Centered on a plain white background, full body shot, no shadows or other elements."
    try:
        # Directly translate and use the prompt
        translation_prompt = f"Translate the following into a clear, descriptive English sentence for an image AI. Description: '{raw_prompt}'"
        final_prompt = text_model.generate_content(translation_prompt).text.strip()
        
        img_bytes = generate_image_with_gemini(final_prompt)

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
            session.delete(obj)
            session.commit()
            return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "Object not found"}, status_code=404)
    
@app.post("/image/{project_id}")
def create_image(project_id: int, desc: str = Form(...), style: str = Form(""), scene_label: str = Form(""), source_image_id: Optional[int] = Form(None)):
    with Session(engine) as session:
        try:
            source_image_pil = None
            if source_image_id:
                source_ill = session.get(Illustration, source_image_id)
                if source_ill:
                    full_path = _safe_join_under(MEDIA_ROOT, source_ill.file_path.replace("/media/", ""))
                    if os.path.exists(full_path):
                        source_image_pil = Image.open(full_path)

            all_objects = session.exec(select(ProjectObject).where(ProjectObject.project_id == project_id)).all()
            consistency_notes = []
            if all_objects:
                for obj in all_objects:
                    if re.search(r'\b' + re.escape(obj.name) + r'\b', desc, re.IGNORECASE):
                        consistency_notes.append(f"- For the character or object '{obj.name}', strictly adhere to this description: {obj.description}")

            translation_prompt = f"Translate the following image description into a simple, clear, and descriptive English sentence, suitable for an image generation AI. Do not add any extra text or explanations, just the translated sentence. Description: '{desc}'"
            english_desc = text_model.generate_content(translation_prompt).text.strip()
            
            # ====== [FIX 2/4] SIMPLIFIED PROMPT FOR ALL IMAGES (NEW & EDITED) ======
            final_prompt = f"A full scene image. Description: {english_desc}"
            if style: final_prompt += f", in the style of {style}"
            if consistency_notes: final_prompt += "\n\n**Important Consistency Guidelines:**\n" + "\n".join(consistency_notes)
            
            img_bytes = generate_image_with_gemini(final_prompt, source_image=source_image_pil)
            
            project_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}")
            os.makedirs(project_dir, exist_ok=True)
            filename = f"img_{uuid.uuid4().hex}.png"
            path = os.path.join(project_dir, filename)
            with open(path, "wb") as f: f.write(img_bytes)
            rel_url = f"/media/project_{project_id}/{filename}"
            
            ill = Illustration(project_id=project_id, file_path=rel_url, prompt=desc, style=style, scene_label=scene_label, source_illustration_id=source_image_id)
            session.add(ill)
            session.commit()
            
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

# ====== Library API Routes ======
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
                index_dir = os.path.join(VECTORSTORE_ROOT, f"library")
                os.makedirs(index_dir, exist_ok=True)
                index_path = os.path.join(index_dir, uid_filename)
                if text_content.strip():
                    create_vector_index(text_content, index_path)
                else:
                    index_path = None

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
    filename_without_ext = os.path.splitext(os.path.basename(__file__))[0]
    
    if not GOOGLE_API_KEY:
        print("\nWARNING: GOOGLE_API_KEY is not set. The application will not function correctly.\n")

    uvicorn.run(f"{filename_without_ext}:app", host="0.0.0.0", port=8000, reload=True)
