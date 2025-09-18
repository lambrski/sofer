# -*- coding: utf-8 -*-
# FINAL, COMPLETE, AND CORRECTED FILE (app_fixed.py)

from fastapi import FastAPI, Form, UploadFile, File, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import SQLModel, Field, Session, create_engine, select
from jinja2 import Template
from google import genai
import os, re, uuid, json
from datetime import datetime
from base64 import b64decode
from typing import Optional, List
from sqlalchemy import delete  # <-- needed for proper DELETE operations

# ====== הגדרות מרכזיות וקבועים ======
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
MEDIA_ROOT = "media"
LIBRARY_ROOT = "library"
DB_FILE = "db.sqlite"
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
BRAIN_SRC_MAX = 16000
MAX_SINGLE_CHARS = 24000
CHUNK_SIZE = 12000
CHUNK_OVERLAP = 800

# ====== FastAPI & Gemini Client ======
app = FastAPI()
client = genai.Client(api_key=GOOGLE_API_KEY)

# ====== Static file serving ======
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(LIBRARY_ROOT, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")
app.mount("/library", StaticFiles(directory=LIBRARY_ROOT), name="library")

# ====== Database Setup ======
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False)

# --- מודלים של בסיס הנתונים (SQLModel) ---
class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str
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

class Rule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, foreign_key="project.id")
    text: str
    mode: str = Field(default="enforce")
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Character(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Illustration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    file_path: str
    prompt: str
    style: str
    scene_label: str = ""
    character_id: Optional[int] = Field(default=None, foreign_key="character.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

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

class ProjectLibraryLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    file_id: int = Field(foreign_key="libraryfile.id")
    linked_at: datetime = Field(default_factory=datetime.utcnow)

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
            add_column("review", "source", "TEXT")
            add_column("review", "title", "TEXT")
            add_column("review", "input_size", "INTEGER")
            add_column("review", "input_text", "TEXT")
            add_column("review", "created_at", "TEXT")
            add_column("illustration", "scene_label", "TEXT")
            add_column("illustration", "character_id", "INTEGER")
    except Exception as e:
        print(f"Could not perform schema check: {e}")

SQLModel.metadata.create_all(engine)
_ensure_schema()

# ====== Utility Functions ======
_WORD_SPLIT = re.compile(r"[^\w\u0590-\u05FF]+")

def _chunk_text(text: str, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = text or ""
    chunks = []
    n = len(text); i = 0
    while i < n:
        j = min(i + chunk_size, n)
        chunks.append(text[i:j])
        if j == n: break
        i = max(0, j - overlap)
    return chunks

def _score_chunk(chunk: str, query: str):
    q_tokens = [t for t in _WORD_SPLIT.split(query.lower()) if t]
    c_low = chunk.lower()
    return sum(2 for t in q_tokens if t in c_low) + (0.1 if chunk else 0)

def select_relevant_slices(notes_text: str, query: str, k=8):
    chunks = _chunk_text(notes_text or "", chunk_size=1200, overlap=200)
    scored = sorted(((c, _score_chunk(c, query)) for c in chunks), key=lambda x: x[1], reverse=True)
    top = [c for c, s in scored[:k] if s > 0]
    if not top and chunks:
        top = chunks[:min(k, len(chunks))]
    return top

def build_rules_preamble(project_id: int) -> str:
    with Session(engine) as session:
        rules = session.exec(select(Rule).where((Rule.project_id == None) | (Rule.project_id == project_id))).all()
    enforced = [r.text for r in rules if r.mode == "enforce"]
    if not enforced: return ""
    return "אכוף את הכללים הבאים:\n- " + "\n- ".join(enforced) + "\n\n"

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


# ====== HTML Templates ======
HOME_HTML = """
<html dir="rtl">
<head><meta charset="utf-8"><title>סתם סופר</title>
<style>
  body{font-family:Arial, sans-serif; max-width:980px; margin:24px auto;}
  h1{margin-bottom:4px}
  ul{line-height:1.9}
</style>
</head>
<body>
<h1>✍ סתם סופר</h1>
<h2>בחר או צור פרויקט</h2>
<form action="/new_project" method="post">
  שם פרויקט: <input type="text" name="name" required>
  סוג: <select name="kind"><option>פרוזה</option><option>קומיקס</option></select>
  <button type="submit">צור</button>
</form>
<hr>
<ul>
{% for p in projects %}
<li><a href="/project/{{p.id}}">{{p.name}} ({{p.kind}})</a></li>
{% endfor %}
</ul>
</body>
</html>
"""
PROJECT_HTML = """
<html dir="rtl">
<head>
  <meta charset="utf-8">
  <title>{{project.name}} - סתם סופר</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 980px; margin: 24px auto; }
    h1 { margin-bottom: 4px; } h2 { margin: 0 0 10px 0; color: #444; display:flex; gap:10px; align-items:center; flex-wrap:wrap;}
    textarea { width: 100%; font-size: 16px; box-sizing: border-box; } button { padding: 6px 14px; margin-top: 6px; cursor:pointer; }
    input {box-sizing: border-box;}
    .btnrow{display:flex; gap:8px; align-items:center; flex-wrap:wrap} #status { color: #666; font-size: 13px; margin-top: 4px; }
    #result { margin-top: 16px; padding: 12px; border: 1px solid #ddd; border-radius: 10px; min-height: 160px; max-height: 55vh; overflow:auto; background:#fff; }
    .turn { margin: 10px 0; } .meta{color:#888; font-size:12px; margin-bottom:4px}
    .bubble{border:1px solid #e6e6e6; border-radius:12px; padding:10px; white-space:pre-wrap}
    .q .bubble{background:#f9fbff} .a .bubble{background:#fafafa}
    .linklike { background:#f6f6f6; border:1px solid #ddd; border-radius:6px; padding:4px 8px; font-size:13px; }
    .muted { color:#777; } .hint { color:#777; font-size:12px; text-align:right }
    .modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.3); display:none; }
    .modal { position:fixed; top:6%; left:50%; transform:translateX(-50%); width:min(1000px, 96vw); background:#fff; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,.25); display:none; }
    .modal header { padding:10px 12px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; align-items:center;}
    .modal .content { max-height:66vh; overflow:auto; padding:10px 12px; }
    .modal footer { padding:10px 12px; border-top:1px solid #eee; display:flex; gap:8px; justify-content:flex-end;}
    #notesArea{width:100%; height:52vh; font-size:15px} .pill{font-size:12px; padding:2px 6px; border:1px solid #ddd; border-radius:999px}
    .field{margin:6px 0} .field input, .field textarea, .field select{width:100%}
    .grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px}
    .card{border:1px solid #eee; border-radius:8px; padding:6px} .card img{width:100%; height:180px; object-fit:cover; border-radius:6px; display:block}
    .small{font-size:12px; color:#666} .list{border:1px solid #eee; border-radius:8px; padding:8px; max-height:40vh; overflow:auto}
    .li{border-bottom:1px solid #f3f3f3; padding:6px 4px} .li:last-child{border-bottom:none} .li h4{margin:0 0 4px 0; font-size:14px}
    .rowflex{display:flex; gap:8px; align-items:center; flex-wrap:wrap} .two-col{display:grid; grid-template-columns:1fr 1fr; gap:10px}
    .box{border:1px solid #eee; border-radius:8px; padding:8px} .tabs{display:flex; gap:8px; margin-top:6px}
    .tabs .tabbtn{padding:6px 10px; border:1px solid #ddd; border-radius:999px; font-size:13px; cursor:pointer; background:#f6f6f6}
    .tabs .tabbtn.active{background:#e8f0ff; border-color:#c7dbff}
  </style>
</head>
<body data-project-id="{{project.id}}">
  <h1>✍ סתם סופר</h1>
  <h2>📘 פרויקט: {{project.name}} ({{project.kind}}) <button id="rulesBtn" class="linklike" type="button">כללים</button> <button id="notesBtn" class="linklike" type="button">קובץ כללי</button> <button id="libraryBtn" class="linklike" type="button">📚 ספרייה</button> <button id="exportBtn" class="linklike" type="button">ייצוא צ'אט</button> <button id="clearChatBtn" class="linklike" type="button">נקה שיחה</button> </h2>
  <div class="rowflex" style="margin-bottom:6px"> <label class="linklike"><input type="radio" name="mode" value="brainstorm" checked> סיעור מוחות</label> <label class="linklike"><input type="radio" name="mode" value="write"> כתיבה</label> <label class="linklike"><input type="radio" name="mode" value="review"> ביקורת</label> <label class="linklike"><input type="radio" name="mode" value="illustrate"> איור</label> <select id="writeKind" style="display:none"> <option value="outline">מתווה פרק</option> <option value="draft">טיוטת פרק</option> <option value="rewrite">שכתוב ושיפור</option> </select> </div>
  <div class="hint">(Ctrl+Enter = שליחה/הרצה,  Shift+Enter = שורה חדשה)</div>
  <div id="chatPanel"> <div class="btnrow" style="margin-bottom:6px"> <button id="historyBtn" class="linklike" type="button" title="שאלות אחרונות">היסטוריה</button> </div> <textarea id="prompt" rows="8" placeholder="כתוב כאן טקסט או שאלה..."></textarea> <div class="btnrow"> <button id="sendBtn" type="button">שלח</button> <button id="copyAnsBtn" class="linklike" type="button" title="העתק תשובה אחרונה">העתק תשובה</button> <label style="font-size:13px"><input type="checkbox" id="useNotes" checked> התבסס על 'קובץ כללי'</label> <div id="status"></div> </div> <div id="result"></div> </div>
  <div id="reviewPanel" style="display:none; margin-top:14px"> <div class="tabs"> <button class="tabbtn active" id="tabGeneral">ביקורת כללית</button> <button class="tabbtn" id="tabProof">הגהה</button> </div> <div class="row" style="margin-top:8px"> <div style="flex:2; min-width:300px"> <div class="field"> <label>טקסט לבדיקה (אם ריק — נבדוק את 'קובץ כללי'):</label> <textarea id="reviewInput" rows="10" placeholder="הדבק כאן טקסט מלא לבדיקה..."></textarea> </div> <div class="rowflex"> <label style="font-size:13px"><input type="checkbox" id="rvUseNotesWhenEmpty" checked> אם ריק — בדוק את 'קובץ כללי'</label> <label style="font-size:13px"><input type="checkbox" id="rvAllowChunk" checked> חלק אוטומטית אם צריך</label> </div> <div class="rowflex"> <button id="runReviewBtn" class="linklike" type="button">הרץ ביקורת</button> <progress id="rvProg" value="0" max="100" style="width:240px; display:none"></progress> <button id="rvCancelBtn" class="linklike" type="button" style="display:none">בטל</button> <span id="rvStatus" class="muted"></span> </div> <div class="box" style="margin-top:8px; white-space:pre-wrap"> <div style="font-weight:bold; margin-bottom:6px">דיון בביקורת</div> <div class="rowflex"> <select id="reviewPicker" style="min-width:220px"></select> <button id="refreshDiscussionBtn" class="linklike" type="button">רענן</button> </div> <div id="discussionThread" class="list" style="margin-top:6px; max-height:28vh; overflow:auto"></div> <div class="rowflex" style="margin-top:6px"> <input id="discussionInput" placeholder="שאלה/בקשה ביחס לממצאי הביקורת"> <button id="askDiscussionBtn" class="linklike" type="button">שלח</button> </div> <div class="small muted">Ctrl+Enter ישלח שאלה בדיון.</div> </div> <div id="reviewOut" class="box" style="margin-top:8px; white-space:pre-wrap"></div> </div> <div style="flex:1; min-width:260px"> <h4 style="margin:0 0 8px 0">ביקורות קודמות</h4> <div id="reviewList" class="list"></div> <div class="rowflex" style="margin-top:8px"> <button id="compareBtn" class="linklike" type="button">השווה נבחרים (עד 2)</button> </div> <div id="compareOut" class="two-col" style="margin-top:8px"></div> </div> </div> </div>
  <div id="illustratePanel" style="display:none; margin-top:14px"> <div class="row"> <div style="flex:1"> <div class="field"><label>תיאור האיור:</label><textarea id="imgDesc" rows="4"></textarea></div> <div class="field"><label>סגנון:</label><input id="imgStyle" placeholder="קומיקס / אקוורל / וכו'"></div> <div class="field"><label>סיטואציה (תווית):</label><input id="imgScene" placeholder="למשל: 'שמוליק בכניסה לבית הספר'"></div> <div class="field"> <label>דמות:</label> <div class="rowflex" style="gap:6px"> <select id="characterPicker" style="min-width:220px"></select> <input id="newCharacterName" placeholder="או צור דמות חדשה (שם)"> <button id="createCharacterBtn" class="linklike" type="button">צור דמות</button> </div> <textarea id="characterDesc" rows="3" placeholder="מאפייני עקביות לדמות (לבוש, גיל...)" style="margin-top:6px"></textarea> <div class="rowflex" style="gap:6px"> <button id="saveCharacterBtn" class="linklike" type="button">שמור פרופיל דמות</button> <span id="charStatus" class="muted"></span> </div> </div> <label style="font-size:13px"><input type="checkbox" id="imgUseNotes" checked> עקביות מול 'קובץ כללי'</label> <div class="rowflex" style="margin-top:6px"> <button id="genImageBtn" class="linklike" type="button">צור</button> <span id="imgStatus" class="muted"></span> </div> </div> </div> <hr> <div id="gallery" class="grid"></div> </div>
  <p><a href="/">⬅ חזרה לרשימת פרויקטים</a></p>
  <div id="backdrop" class="modal-backdrop"></div>
  <div id="notesModal" class="modal"> <header><strong>קובץ כללי — {{project.name}}</strong><button id="closeNotesBtn" class="linklike">סגור</button></header> <div class="content"><textarea id="notesArea"></textarea></div> <footer><button id="saveNotesBtn" class="linklike">שמור</button></footer> </div>
  <div id="histModal" class="modal"> <header><strong>היסטוריית שאלות</strong><div><button id="clearHistBtn" class="linklike">נקה</button><button id="closeHistBtn" class="linklike">סגור</button></div></header> <div id="histContent" class="content"></div> </div>
  <div id="rulesModal" class="modal"> <header><strong>כללים</strong><button id="closeRulesBtn" class="linklike">סגור</button></header> <div class="content" id="rulesContent"> <h3>כללי גג <span class="pill">חלים על כל הפרויקטים</span></h3> <div id="rulesGlobal"></div> <div class="rowflex"> <textarea id="newGlobalText" style="flex:1; height:56px"></textarea> <select id="newGlobalMode"><option value="enforce">אכיפה</option><option value="warn">אזהרה</option><option value="off">כבוי</option></select> <button id="addGlobalBtn" class="linklike">הוסף</button> </div> <hr> <h3>כללי פרויקט <span class="pill">רק לפרויקט הנוכחי</span></h3> <div id="rulesProject"></div> <div class="rowflex"> <textarea id="newProjectText" style="flex:1; height:56px"></textarea> <select id="newProjectMode"><option value="enforce">אכיפה</option><option value="warn">אזהרה</option><option value="off">כבוי</option></select> <button id="addProjectBtn" class="linklike">הוסף</button> </div> </div> </div>
  <div id="libraryModal" class="modal"> <header> <strong>ספרייה מרכזית</strong> <div class="rowflex"> <input type="text" id="libSearch" placeholder="חפש..." style="min-width:220px"> <label class="linklike" for="libUpload">העלה קבצים</label> <input type="file" id="libUpload" style="display:none" multiple accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,.webp"> <button id="closeLibraryBtn" class="linklike">סגור</button> </div> </header> <div class="content"> <div class="small muted">סוגי קבצים נתמכים: PDF, DOCX, TXT, PNG, JPG, JPEG, WEBP</div> <div id="libraryList" class="list"></div> </div> </div>
<script>
(function(){
  const pid = Number(document.body.getAttribute('data-project-id'));
  const MAX_SINGLE = 24000, CHUNK_SIZE = 12000, CHUNK_OVERLAP = 800, CONCURRENCY = 4, CHUNK_TIMEOUT_MS = 90000, CHUNK_MAX_RETRIES = 3, DRAFT_KEY = "draft_"+pid;
  function esc(s){return (s||"").replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
  function fmtTime(iso){ const d=new Date(iso); return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
  const sleep = (ms)=>new Promise(r=>setTimeout(r, ms));
  const backdrop = document.getElementById('backdrop');
  function openModal(el){ el.style.display="block"; backdrop.style.display="block"; }
  function closeAllModals(){ document.querySelectorAll('.modal').forEach(m=>m.style.display="none"); backdrop.style.display="none"; }
  backdrop.addEventListener("click", closeAllModals);
  const modeRadios = [...document.getElementsByName('mode')], writeKindEl = document.getElementById('writeKind'), chatPanel = document.getElementById('chatPanel'), reviewPanel = document.getElementById('reviewPanel'), illustratePanel = document.getElementById('illustratePanel');
  function currentMode(){ return modeRadios.find(r=>r.checked).value; }
  function currentWriteKind(){ return writeKindEl.value; }
  function applyModeUI(){ const m = currentMode(); writeKindEl.style.display = (m==='write') ? 'inline-block' : 'none'; chatPanel.style.display = (m==='review' || m==='illustrate') ? 'none' : 'block'; reviewPanel.style.display = (m==='review') ? 'block' : 'none'; illustratePanel.style.display = (m==='illustrate') ? 'block' : 'none'; document.getElementById('historyBtn').style.display = (m==='brainstorm') ? 'inline-block' : 'none'; if (m==='illustrate') { loadGallery(); loadCharacters(); } if (m==='review') { loadReviewList(); loadReviewPicker(); } }
  modeRadios.forEach(r=> r.addEventListener('change', applyModeUI));
  const promptEl = document.getElementById('prompt'), resultEl = document.getElementById('result'), statusEl = document.getElementById('status');
  const notesBtn = document.getElementById('notesBtn'), notesModal = document.getElementById('notesModal'), closeNotesBtn = document.getElementById('closeNotesBtn'), notesArea = document.getElementById('notesArea'), saveNotesBtn = document.getElementById('saveNotesBtn');
  notesBtn.addEventListener("click", async ()=>{ openModal(notesModal); notesArea.value = "טוען..."; const res = await fetch("/general/"+pid); const data = await res.json(); notesArea.value = data.text || ""; });
  closeNotesBtn.addEventListener("click", closeAllModals);
  saveNotesBtn.addEventListener("click", async ()=>{ try{ const res = await fetch("/general/"+pid, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ text: notesArea.value })}); if ((await res.json()).ok) { alert("נשמר"); closeAllModals(); } else { alert("שגיאה"); } }catch(e){ alert("שגיאה"); } });
  const historyBtn = document.getElementById('historyBtn'), histModal = document.getElementById('histModal'), closeHistBtn = document.getElementById('closeHistBtn'), clearHistBtn = document.getElementById('clearHistBtn'), histContent = document.getElementById('histContent');
  historyBtn.addEventListener("click", async ()=>{ openModal(histModal); histContent.innerHTML = "<div class='muted'>טוען...</div>"; const res = await fetch("/history/"+pid); const data = await res.json(); if (!data.items.length) { histContent.innerHTML = "<div class='muted'>אין היסטוריה.</div>"; return; } histContent.innerHTML = data.items.map(q => `<div class='li' title='לחץ להעתקה'>${esc(q)}</div>`).join(""); [...histContent.querySelectorAll('.li')].forEach(el=>{ el.addEventListener("click", ()=>{ promptEl.value = el.textContent; promptEl.focus(); closeAllModals(); }); }); });
  closeHistBtn.addEventListener("click", closeAllModals);
  clearHistBtn.addEventListener("click", async ()=>{ if (!confirm("למחוק היסטוריה?")) return; await fetch("/history/"+pid+"/clear", {method:"POST"}); histContent.innerHTML = "<div class='muted'>נמחק.</div>"; });
  const rulesBtn = document.getElementById('rulesBtn'), rulesModal = document.getElementById('rulesModal'), closeRulesBtn = document.getElementById('closeRulesBtn'), rulesGlobal = document.getElementById('rulesGlobal'), rulesProject = document.getElementById('rulesProject');
  function ruleRow(r){return `<div class="rowflex rule" data-id="${r.id}"><textarea style="flex:1; height:56px">${esc(r.text)}</textarea><select><option value="enforce" ${r.mode==="enforce"?"selected":""}>אכיפה</option><option value="warn"?"selected":""}>אזהרה</option><option value="off" ${r.mode==="off"?"selected":""}>כבוי</option></select><button class="linklike save">שמור</button><button class="linklike del">מחק</button></div>`;}
  async function loadRules(){ const res = await fetch("/rules/"+pid); const data = await res.json(); rulesGlobal.innerHTML = data.global.map(ruleRow).join("") || "<div class='muted'>אין.</div>"; rulesProject.innerHTML = data.project.map(ruleRow).join("") || "<div class='muted'>אין.</div>"; [...rulesModal.querySelectorAll(".rule")].forEach(row=>{ const id = row.getAttribute("data-id"); row.querySelector(".save").addEventListener("click", async ()=>{ const text = row.querySelector("textarea").value, mode = row.querySelector("select").value; await fetch(`/rules/${pid}/update`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id, text, mode })}); alert("נשמר"); }); row.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/rules/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadRules();} }); }); }
  rulesBtn.addEventListener("click", async ()=>{ openModal(rulesModal); await loadRules(); });
  closeRulesBtn.addEventListener("click", closeAllModals);
  document.getElementById('addGlobalBtn').addEventListener("click", async () => { const text = document.getElementById('newGlobalText').value, mode = document.getElementById('newGlobalMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'global', text, mode})}); await loadRules(); document.getElementById('newGlobalText').value = ""; });
  document.getElementById('addProjectBtn').addEventListener("click", async () => { const text = document.getElementById('newProjectText').value, mode = document.getElementById('newProjectMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'project', text, mode})}); await loadRules(); document.getElementById('newProjectText').value = ""; });
  const imgDesc = document.getElementById('imgDesc'), imgStyle = document.getElementById('imgStyle'), imgScene = document.getElementById('imgScene'), imgUseNotes = document.getElementById('imgUseNotes'), genImageBtn = document.getElementById('genImageBtn'), imgStatus = document.getElementById('imgStatus'), gallery = document.getElementById('gallery'), characterPicker = document.getElementById('characterPicker'), newCharacterName = document.getElementById('newCharacterName'), createCharacterBtn = document.getElementById('createCharacterBtn'), characterDesc = document.getElementById('characterDesc'), saveCharacterBtn = document.getElementById('saveCharacterBtn'), charStatus = document.getElementById('charStatus');
  async function loadCharacters(){ try{ const res = await fetch("/characters"); const data = await res.json(); const items = data.items || []; characterPicker.innerHTML = `<option value="">(ללא דמות)</option>` + items.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join(""); characterPicker.onchange = ()=>{ const id = characterPicker.value; const obj = items.find(x=>String(x.id)===String(id)); characterDesc.value = obj ? (obj.description||"") : ""; }; }catch(e){} }
  async function loadGallery(){ gallery.innerHTML = "<div class='muted'>טוען...</div>"; const res = await fetch("/images/"+pid); const data = await res.json(); if (!data.items.length){ gallery.innerHTML = "<div class='muted'>אין איורים.</div>"; return; } gallery.innerHTML = data.items.map(it => `<div class="card" data-id="${it.id}"><img src="${it.url}"><div class="small">${it.style?esc(it.style)+" • ":""}${it.scene_label?esc(it.scene_label)+" • ":""}${new Date(it.created_at).toLocaleString()}</div><div class="small" title="${esc(it.prompt)}">${esc((it.prompt||"").slice(0,80))}...</div><div class="rowflex"><a class="linklike" href="${it.url}" download>הורד</a><a class="linklike" href="${it.url}" target="_blank">פתח</a><button class="linklike delimg">מחק</button></div></div>`).join(""); [...gallery.querySelectorAll(".delimg")].forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".card").getAttribute("data-id"); if (!confirm("למחוק?")) return; await fetch(`/images/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadGallery(); }); }); }
  createCharacterBtn.addEventListener("click", async ()=>{ const name = (newCharacterName.value||"").trim(); if (!name) return; charStatus.textContent = "יוצר..."; const res = await fetch("/characters/create", { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ name, description: characterDesc.value||"" }) }); const data = await res.json(); if (!data.ok) { alert("שגיאה"); return; } newCharacterName.value = ""; await loadCharacters(); characterPicker.value = data.id; charStatus.textContent = "נוצר ✓"; setTimeout(()=> charStatus.textContent="", 1200); });
  saveCharacterBtn.addEventListener("click", async ()=>{ const id = characterPicker.value; if (!id) return; charStatus.textContent = "שומר..."; const res = await fetch("/characters/update", { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ id, description: characterDesc.value||"" }) }); if(!(await res.json()).ok){ alert("שגיאה"); return; } charStatus.textContent = "נשמר ✓"; setTimeout(()=> charStatus.textContent="", 1200); });
  const sendBtn = document.getElementById('sendBtn');  // <-- FIX: define the button
  function renderTurns(items){ resultEl.innerHTML = items.map(t => `<div class="turn q"><div class="meta">אתה • ${fmtTime(t.time)}</div><div class="bubble">${esc(t.q)}</div></div><div class="turn a"><div class="meta">סופר • ${fmtTime(t.time)}</div><div class="bubble">${esc(t.a || "")}</div></div>`).join(""); resultEl.scrollTop = resultEl.scrollHeight; }
  async function loadChat(){ try {const res = await fetch("/chat/"+pid); renderTurns((await res.json()).items); } catch(e) { console.error("Failed to load chat", e);}}
  document.getElementById('copyAnsBtn').addEventListener("click", async ()=>{ const bubbles = [...resultEl.querySelectorAll('.turn.a .bubble')]; if (!bubbles.length) return; const txt = bubbles[bubbles.length-1].textContent||""; await navigator.clipboard.writeText(txt); });
  async function sendText() { const m = currentMode(); if (m==='review' || m==='illustrate') return; const text = promptEl.value.trim(); if (!text) return; const writeKind = currentWriteKind(); sendBtn.disabled = True; statusEl.textContent = "שולח..."; try { const body = new URLSearchParams({ text, use_notes: document.getElementById('useNotes').checked ? "1" : "0", mode: m, write_kind: writeKind }); await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body }); await loadChat(); promptEl.value = ""; } catch(e) { alert("שגיאה"); await loadChat(); } finally { statusEl.textContent = ""; sendBtn.disabled = false; promptEl.focus(); } }
  document.getElementById('sendBtn').addEventListener("click", sendText);
  promptEl.addEventListener("keydown", (ev)=>{ if (ev.ctrlKey && ev.key === "Enter") { sendText(); ev.preventDefault(); } });
  document.getElementById('clearChatBtn').addEventListener("click", async ()=>{ if (confirm("למחוק שיחה?")) { await fetch("/chat/"+pid+"/clear", {method:"POST"}); renderTurns([]); } });
  document.getElementById('exportBtn').addEventListener("click", async ()=>{ const res = await fetch("/chat/"+pid); const items = (await res.json()).items; const lines = items.map(t => `שאלה: ${t.q}\nתשובה: ${t.a}\n---\n`).join(""); const blob = new Blob([lines], {type:"text/plain;charset=utf-8"}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `chat-${pid}.txt`; a.click(); URL.revokeObjectURL(url); });
  const tabGeneral = document.getElementById('tabGeneral'), tabProof = document.getElementById('tabProof'); let currentReviewKind = 'general';
  function setTab(kind){ currentReviewKind = kind; tabGeneral.classList.toggle('active', kind==='general'); tabProof.classList.toggle('active', kind==='proofread'); loadReviewList(); reviewOut.textContent = ''; }
  tabGeneral.addEventListener('click', ()=>setTab('general')); tabProof.addEventListener('click', ()=>setTab('proofread'));
  const reviewInput = document.getElementById('reviewInput'), rvUseNotesWhenEmpty = document.getElementById('rvUseNotesWhenEmpty'), rvAllowChunk = document.getElementById('rvAllowChunk'), runReviewBtn = document.getElementById('runReviewBtn'), rvProg = document.getElementById('rvProg'), rvCancelBtn = document.getElementById('rvCancelBtn'), rvStatus = document.getElementById('rvStatus'), reviewOut = document.getElementById('reviewOut'), reviewList = document.getElementById('reviewList'), compareBtn = document.getElementById('compareBtn'), compareOut = document.getElementById('compareOut');
  let selectedForCompare = new Set(), activeControllers = [], cancelRequested = false;
  const reviewPicker = document.getElementById('reviewPicker'), discussionThread = document.getElementById('discussionThread'), discussionInput = document.getElementById('discussionInput'), askDiscussionBtn = document.getElementById('askDiscussionBtn'), refreshDiscussionBtn = document.getElementById('refreshDiscussionBtn');
  async function loadReviewPicker(){ const res = await fetch(`/reviews/${pid}`); const items = (await res.json()).items||[]; reviewPicker.innerHTML = items.length ? items.map(it=>`<option value="${it.id}">${esc(it.title)} • ${new Date(it.created_at).toLocaleString()}</option>`).join("") : `<option value="">(אין)</option>`; if (items.length){ await loadDiscussion(items[0].id); } reviewPicker.onchange = async ()=>{ if (reviewPicker.value) await loadDiscussion(reviewPicker.value); else discussionThread.innerHTML=""; }; }
  async function loadDiscussion(rid){ discussionThread.innerHTML = "<div class='muted'>טוען...</div>"; const res = await fetch(`/review/${pid}/discussion/${rid}`); const items = (await res.json()).items || []; discussionThread.innerHTML = !items.length ? "<div class='muted'>אין הודעות.</div>" : items.map(m=>`<div class="li"><div class="meta">${m.role==='user'?'אתה':'סופר'} • ${new Date(m.created_at).toLocaleString()}</div><div class="bubble">${esc(m.message)}</div></div>`).join(""); discussionThread.scrollTop = discussionThread.scrollHeight; }
  async function sendDiscussion(){ const rid = reviewPicker.value, q = (discussionInput.value||"").trim(); if (!rid || !q) return; askDiscussionBtn.disabled = true; try{ await fetch(`/review/${pid}/discuss`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ review_id: rid, question: q })}); discussionInput.value = ""; await loadDiscussion(rid); } catch(e){alert("שגיאה");} finally{ askDiscussionBtn.disabled=false; } }
  askDiscussionBtn.addEventListener("click", sendDiscussion); discussionInput.addEventListener("keydown", (ev)=>{ if (ev.ctrlKey && ev.key === "Enter") { sendDiscussion(); ev.preventDefault(); } });
  refreshDiscussionBtn.addEventListener("click", async ()=>{ const rid = reviewPicker.value; if (rid) await loadDiscussion(rid); });
  function renderReviewList(items){ reviewList.innerHTML = items.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex"><input type="checkbox" class="pick"><h4 title="${new Date(it.created_at).toLocaleString()}">${esc(it.title)}</h4><button class="linklike show">הצג</button><button class="linklike del">מחק</button></div><div class="box body" style="display:none">${esc(it.result||"")}</div></div>`).join(""); [...reviewList.querySelectorAll(".li")].forEach(li=>{ const id = li.getAttribute("data-id"); li.querySelector(".show").addEventListener("click", ()=>{ const body = li.querySelector(".body"); body.style.display = (body.style.display==="none" ? "block" : "none"); }); li.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/reviews/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadReviewList();} }); li.querySelector(".pick").addEventListener("change", (e)=>{ if(e.target.checked){ if(selectedForCompare.size>=2){e.target.checked=false;return;} selectedForCompare.add(id); } else { selectedForCompare.delete(id); } }); }); }
  async function loadReviewList(){ selectedForCompare.clear(); compareOut.innerHTML = ""; const res = await fetch(`/reviews/${pid}?kind=${currentReviewKind}`); renderReviewList((await res.json()).items || []); }
  compareBtn.addEventListener("click", async ()=>{ if (selectedForCompare.size === 0) return; const ids = Array.from(selectedForCompare); const res = await fetch(`/reviews/${pid}/by_ids?ids=${ids.join(",")}`); const data = await res.json(); const a = data.items[0], b = data.items[1]; if(ids.length===1){ compareOut.innerHTML = `<div class="box">${esc(a?.result||"—")}</div>`; } else { compareOut.innerHTML = `<div class="box"><div class="small">${esc(a.title)}</div>${esc(a.result||"—")}</div><div class="box"><div class="small">${esc(b.title)}</div>${esc(b.result||"—")}</div>`; } });
  function resetProgress(){ rvProg.style.display="none"; rvProg.value=0; rvCancelBtn.style.display="none"; rvStatus.textContent=""; cancelRequested=false; activeControllers.forEach(c=>{try{c.abort()}catch(_){}}); activeControllers=[]; }
  rvCancelBtn.addEventListener("click", ()=>{ cancelRequested=true; activeControllers.forEach(c=>{try{c.abort()}catch(_){}}); activeControllers=[]; rvStatus.textContent = "בוטל."; rvCancelBtn.style.display="none"; });
  async function fetchChunkWithTimeoutRetry(kind, text, attempt=1){ const ctrl = new AbortController(); activeControllers.push(ctrl); const timer = setTimeout(()=>ctrl.abort(), CHUNK_TIMEOUT_MS); try{ const res = await fetch(`/review/${pid}/chunk`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind, text }), signal: ctrl.signal }); clearTimeout(timer); const data = await res.json(); if (!data.ok) throw new Error(data.error || "שגיאה"); return data.part || ""; }catch(e){ clearTimeout(timer); if (attempt < CHUNK_MAX_RETRIES && !cancelRequested){ await sleep(attempt*1200); return fetchChunkWithTimeoutRetry(kind, text, attempt+1); } throw e; } }
  async function runChunked(kind, fullText, source){ const chunks = _chunk_text(fullText); const N = chunks.length; const results = new Array(N); let done = 0; rvProg.style.display="inline-block"; rvProg.max = N; rvProg.value = 0; rvCancelBtn.style.display="inline-block"; rvStatus.textContent = `0 / ${N}`; let nextIdx = 0; async function worker(){ while(!cancelRequested && nextIdx < N){ const i = nextIdx++; try{ const part = await fetchChunkWithTimeoutRetry(kind, chunks[i], 1); results[i] = part; done++; rvProg.value = done; rvStatus.textContent = `${done}/${N}`; }catch(e){ if(cancelRequested) return; alert("שגיאה בחלק "+(i+1)); cancelRequested=true; return; } } } const workers = []; for(let k=0;k<CONCURRENCY;k++) workers.push(worker()); await Promise.all(workers); if(cancelRequested){ resetProgress(); return null; } const res = await fetch(`/review/${pid}/synthesize`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind, source, input_size: String(fullText.length), parts: JSON.stringify(results), input_text: fullText }) }); const data = await res.json(); if (!data.ok){ resetProgress(); alert(data.error||"שגיאת סינתזה"); return null; } rvStatus.textContent = `הושלם`; rvProg.style.display="none"; rvCancelBtn.style.display="none"; return data.result || ""; }
  document.addEventListener("keydown", (ev)=>{ if (reviewPanel.style.display==="block" && ev.ctrlKey && ev.key==="Enter"){ ev.preventDefault(); runReviewBtn.click(); } });
  runReviewBtn.addEventListener("click", async ()=>{ reviewOut.textContent = ""; resetProgress(); try{ let text = reviewInput.value.trim(); let source = text ? "pasted" : "notes"; if (!text){ if (!rvUseNotesWhenEmpty.checked) return; const g = await (await fetch("/general/"+pid)).json(); text = (g.text||"").trim(); if (!text) return; } const kind = currentReviewKind; if (!rvAllowChunk.checked && text.length > MAX_SINGLE){ alert(`הטקסט ארוך מדי (${text.length} תווים).`); return; } if (text.length <= MAX_SINGLE){ rvStatus.textContent = "מריץ..."; const one = await (await fetch(`/review/${pid}/chunk`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind, text })})).json(); if (!one.ok){ alert(one.error || "שגיאה"); return; } const fin = await (await fetch(`/review/${pid}/synthesize`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind, source, input_size: String(text.length), parts: JSON.stringify([one.part||""]), input_text: text })})).json(); if (!fin.ok){ alert(fin.error || "שגיאה"); return; } reviewOut.textContent = fin.result || "—"; await loadReviewList(); rvStatus.textContent = "הושלם"; return; } const finalReport = await runChunked(kind, text, source); if (finalReport!=null){ reviewOut.textContent = finalReport; await loadReviewList(); } }catch(e){ alert("שגיאה: "+(e.message||e)); }finally{ rvCancelBtn.style.display="none"; } });
  promptEl.value = localStorage.getItem(DRAFT_KEY) || "";
  promptEl.addEventListener("input", ()=> localStorage.setItem(DRAFT_KEY, promptEl.value));
  const libraryBtn = document.getElementById('libraryBtn'), libraryModal = document.getElementById('libraryModal'), closeLibraryBtn = document.getElementById('closeLibraryBtn'), libraryList = document.getElementById('libraryList'), libUpload = document.getElementById('libUpload'), libSearch = document.getElementById('libSearch');
  function renderLibrary(items, linked){ const q = (libSearch.value||"").trim().toLowerCase(); const rows = items.filter(it => !q || (it.filename||"").toLowerCase().includes(q)); if (!rows.length){ libraryList.innerHTML = "<div class='muted'>אין קבצים.</div>"; return; } const linkedSet = new Set(linked || []); libraryList.innerHTML = rows.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex" style="justify-content:space-between; gap:12px"><div><h4>${esc(it.filename)}</h4><div class="small">${esc(it.ext)} • ${(it.size/1024).toFixed(1)}KB • ${new Date(it.uploaded_at).toLocaleString()}</div><div class="rowflex"><a class="linklike" href="${it.url}" target="_blank">פתח</a><a class="linklike" href="${it.url}" download>הורד</a><button class="linklike del">מחק</button></div></div><label class="linklike"><input type="checkbox" class="linkchk" ${linkedSet.has(it.id)?'checked':''}> מקושר</label></div></div>`).join(""); [...libraryList.querySelectorAll(".del")].forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".li").getAttribute("data-id"); if(!confirm("למחוק?")) return; await fetch("/library/delete", { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ id })}); await loadLibrary(); }); }); [...libraryList.querySelectorAll(".linkchk")].forEach(chk=>{ chk.addEventListener("change", async ()=>{ const id = chk.closest(".li").getAttribute("data-id"); const url = chk.checked ? "/library/link" : "/library/unlink"; await fetch(url, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ project_id: String(pid), file_id: String(id) })}); }); }); }
  async function loadLibrary(){ libraryList.innerHTML = "<div class='muted'>טוען...</div>"; const [allRes, linkedRes] = await Promise.all([ fetch("/library/list"), fetch(`/library/linked/${pid}`) ]); const all = await allRes.json(); const linked = await linkedRes.json(); renderLibrary(all.items||[], (linked.items||[]).map(x=>x.file_id)); }
  libraryBtn.addEventListener("click", async ()=>{ openModal(libraryModal); await loadLibrary(); });
  closeLibraryBtn.addEventListener("click", closeAllModals);
  libSearch.addEventListener("input", ()=> loadLibrary());
  libUpload.addEventListener("change", async ()=>{ if (!libUpload.files.length) return; const fd = new FormData(); for (const f of libUpload.files) fd.append("files", f); await fetch("/library/upload", { method:"POST", body: fd }); await loadLibrary(); libUpload.value = ""; });
  applyModeUI(); loadChat();
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
def new_project(name: str = Form(...), kind: str = Form(...)):
    with Session(engine) as session:
        p = Project(name=name, kind=kind)
        session.add(p); session.commit(); session.refresh(p)
        session.add(GeneralNotes(project_id=p.id, text=""))
        session.commit()
    return RedirectResponse("/", status_code=303)

@app.get("/project/{project_id}", response_class=HTMLResponse)
def project_page(project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return RedirectResponse("/", status_code=303)
        if not session.exec(select(GeneralNotes).where(GeneralNotes.project_id == project_id)).first():
            session.add(GeneralNotes(project_id=project_id, text=""))
            session.commit()
    return render(PROJECT_HTML, project=project)

# ====== Routes: Library (File Upload) ======
@app.post("/library/upload")
async def library_upload(files: List[UploadFile] = File(...)):
    with Session(engine) as session:
        for uf in files:
            ext = _guess_ext(uf.filename)
            if ext not in ALLOWED_EXTS: 
                continue
            uid_filename = f"{uuid.uuid4().hex}{ext}"
            dest_full = _safe_join_under(LIBRARY_ROOT, uid_filename)
            try:
                data = await uf.read()
                with open(dest_full, "wb") as f:
                    f.write(data)
                stored_url_path = f"/library/{uid_filename}"
                rec = LibraryFile(filename=uf.filename, stored_path=stored_url_path, ext=ext, size=len(data))
                session.add(rec); session.commit()
            except Exception as e:
                print(f"Failed to save file {uf.filename}: {e}")
    return JSONResponse({"ok": True})

@app.get("/library/list")
def library_list():
    with Session(engine) as session:
        rows = session.exec(select(LibraryFile).order_by(LibraryFile.uploaded_at.desc())).all()
    items = [{"id": r.id, "filename": r.filename, "url": r.stored_path, "ext": r.ext, "size": r.size, "uploaded_at": r.uploaded_at.isoformat()} for r in rows]
    return JSONResponse({"items": items})

@app.post("/library/delete")
def library_delete(id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(LibraryFile, id)
        if not r: 
            return JSONResponse({"ok": False}, status_code=404)
        try:
            filename = r.stored_path.replace("/library/", "", 1)
            full_path = _safe_join_under(LIBRARY_ROOT, filename)
            if os.path.exists(full_path): os.remove(full_path)
        except Exception as e: 
            print(f"Could not delete file: {e}")
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.file_id == r.id)).all()
        for l in links: session.delete(l)
        session.delete(r); session.commit()
    return JSONResponse({"ok": True})

@app.get("/library/linked/{project_id}")
def library_linked(project_id: int):
    with Session(engine) as session:
        links = session.exec(select(ProjectLibraryLink).where(ProjectLibraryLink.project_id == project_id)).all()
    return JSONResponse({"items": [{"file_id": l.file_id} for l in links]})

@app.post("/library/link")
def library_link(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        exists = session.exec(select(ProjectLibraryLink).where((ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id))).first()
        if not exists:
            session.add(ProjectLibraryLink(project_id=project_id, file_id=file_id)); session.commit()
    return JSONResponse({"ok": True})

@app.post("/library/unlink")
def library_unlink(project_id: int = Form(...), file_id: int = Form(...)):
    with Session(engine) as session:
        link = session.exec(select(ProjectLibraryLink).where((ProjectLibraryLink.project_id == project_id) & (ProjectLibraryLink.file_id == file_id))).first()
        if link:
            session.delete(link); session.commit()
    return JSONResponse({"ok": True})

# ====== Routes: Notes, Chat, History ======
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
            gn = GeneralNotes(project_id=project_id, text=text)
            session.add(gn)
        else:
            gn.text = text
            gn.updated_at = datetime.utcnow()
        session.commit()
    return JSONResponse({"ok": True})

@app.get("/chat/{project_id}")
def get_chat(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.asc())).all()
    items = [{"q": r.question, "a": r.answer, "time": r.created_at.isoformat()} for r in rows]
    return JSONResponse({"items": items})

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
    # normalize to strings
    items = [r[0] if isinstance(r, tuple) else (r if isinstance(r, str) else getattr(r, "question", "")) for r in rows]
    return JSONResponse({"items": items})

@app.post("/history/{project_id}/clear")
def clear_history(project_id: int):
    return clear_chat(project_id)

# ====== Routes: Rules ======
@app.get("/rules/{project_id}")
def rules_list(project_id: int):
    with Session(engine) as session:
        global_rules = session.exec(select(Rule).where(Rule.project_id == None)).all()
        project_rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
    return JSONResponse({"global": [r.dict() for r in global_rules], "project": [r.dict() for r in project_rules]})

@app.post("/rules/{project_id}/add")
def rules_add(project_id: int, scope: str = Form(...), text: str = Form(...), mode: str = Form(...)):
    pid = None if scope == "global" else project_id
    with Session(engine) as session:
        session.add(Rule(project_id=pid, text=text, mode=mode)); session.commit()
    return JSONResponse({"ok": True})

@app.post("/rules/{pid}/update")
def rules_update(pid: int, id: int = Form(...), text: str = Form(...), mode: str = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r: 
            r.text = text
            r.mode = mode
            session.commit()
    return JSONResponse({"ok": True})

@app.post("/rules/{pid}/delete")
def rules_delete(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r: 
            session.delete(r); session.commit()
    return JSONResponse({"ok": True})

# ====== Routes: Main AI Endpoints (Ask, Review, Illustrate) ======
@app.post("/ask/{project_id}")
def ask_project(project_id: int, text: str = Form(...), use_notes: str = Form("1"), mode: str = Form(...), write_kind: str = Form(...)):
    with Session(engine) as session:
        notes_text = ""
        if use_notes == "1":
            gn = session.exec(select(GeneralNotes.text).where(GeneralNotes.project_id == project_id)).first()
            if gn: notes_text = gn
        turns = session.exec(select(History).where(History.project_id == project_id).order_by(History.created_at.desc()).limit(10)).all()
    slices = select_relevant_slices(notes_text, text) if notes_text else []
    context = "רקע מ'קובץ כללי':\n" + "\n---\n".join(slices) + "\n\n" if slices else ""
    prompt = f"{build_rules_preamble(project_id)}{context}המשך שיחה קודמת:\n{[t.question + ' -> ' + t.answer for t in reversed(turns)]}\n\nבקשה: {text}"
    resp = client.models.generate_content(model="gemini-1.5-flash", contents=[prompt])
    answer = resp.text
    with Session(engine) as session:
        tag = f"【{mode}:{write_kind}】" if mode == 'write' else f"【{mode}】"
        session.add(History(project_id=project_id, question=f"{tag} {text}", answer=answer)); session.commit()
    return JSONResponse({"answer": answer})

@app.post("/review/{project_id}/chunk")
def review_chunk(project_id: int, kind: str = Form(...), text: str = Form(...)):
    rules = build_rules_preamble(project_id)
    if kind == "general":
        p = f"{rules}בצע ביקורת כללית על הקטע: {text}"
    else:
        p = f"בצע הגהה על הקטע: {text}"
    part = client.models.generate_content(model="gemini-1.5-flash", contents=[p]).text
    return JSONResponse({"ok": True, "part": part})

@app.post("/review/{project_id}/synthesize")
def review_synthesize(project_id: int, kind: str = Form(...), parts: str = Form(...), source: str = Form(...), input_size: int = Form(0), input_text: str = Form(...)):
    parts_list = json.loads(parts)
    if len(parts_list) == 1:
        result = parts_list[0]
    else:
        joined = "\n\n---\n\n".join(parts_list)
        p = f"אחד את ממצאי הביקורת הבאים לדוח אחיד ({'כללי' if kind=='general' else 'הגהה'}):\n{joined}"
        result = client.models.generate_content(model="gemini-1.5-flash", contents=[p]).text
    with Session(engine) as session:
        session.add(Review(project_id=project_id, kind=kind, source=source, title=source, result=result, input_size=input_size, input_text=input_text)); session.commit()
    return JSONResponse({"ok": True, "result": result})

@app.get("/reviews/{project_id}")
def list_reviews(project_id: int, kind: str = ""):
    with Session(engine) as session:
        q = select(Review).where(Review.project_id == project_id).order_by(Review.created_at.desc())
        if kind: q = q.where(Review.kind == kind)
        rows = session.exec(q).all()
    return JSONResponse({"items": [r.dict() for r in rows]})

@app.post("/reviews/{pid}/delete")
def delete_review(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Review, id)
        if r: 
            session.delete(r); session.commit()
    return JSONResponse({"ok": True})
    
@app.get("/reviews/{pid}/by_ids")
def get_reviews_by_ids(pid: int, ids: str):
    id_list = [int(x) for x in ids.split(',') if x.isdigit()]
    with Session(engine) as session:
        rows = session.exec(select(Review).where(Review.id.in_(id_list))).all()
    return JSONResponse({"items": [r.dict() for r in rows]})
    
@app.get("/review/{pid}/discussion/{review_id}")
def get_review_discussion(pid: int, review_id: int):
    with Session(engine) as session:
        msgs = session.exec(select(ReviewDiscussion).where(ReviewDiscussion.review_id == review_id).order_by(ReviewDiscussion.created_at.asc())).all()
    return JSONResponse({"items": [m.dict() for m in msgs]})

@app.post("/review/{pid}/discuss")
def post_review_discussion(pid: int, review_id: int = Form(...), question: str = Form(...)):
    with Session(engine) as session:
        rev = session.get(Review, review_id)
        if not rev: return JSONResponse({"ok": False}, 404)
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="user", message=question)); session.commit()
        p = f"בהקשר לביקורת '{rev.result}', המשתמש שואל: {question}. ענה בקצרה."
        answer = client.models.generate_content(model="gemini-1.5-flash", contents=[p]).text
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="assistant", message=answer)); session.commit()
    return JSONResponse({"ok": True})
    
@app.get("/characters")
def list_characters():
    with Session(engine) as session:
        rows = session.exec(select(Character)).all()
    return JSONResponse({"items": [c.dict() for c in rows]})

@app.post("/characters/create")
def create_character(name: str = Form(...), description: str = Form("")):
    with Session(engine) as session:
        c = Character(name=name, description=description)
        session.add(c); session.commit(); session.refresh(c)
    return JSONResponse({"ok": True, "id": c.id})
    
@app.post("/characters/update")
def update_character(id: int = Form(...), description: str = Form(...)):
    with Session(engine) as session:
        c = session.get(Character, id)
        if c: c.description = description; session.commit()
    return JSONResponse({"ok": True})
    
@app.post("/image/{project_id}")
def create_image(project_id: int, desc: str = Form(...), style: str = Form(""), use_notes: str = Form("1"), character_id: Optional[int] = Form(None), scene_label: str = Form("")):
    # This is a simplified placeholder for the image prompt generation
    prompt = f"צור תמונה: {desc}, בסגנון {style}"
    resp = client.models.generate_content(model="gemini-1.5-flash", contents=[prompt, "צור תמונה לפי התיאור"])
    img_bytes = None
    # Try to extract inline image bytes (may not work with all SDK versions)
    if hasattr(resp, "candidates"):
        for cand in resp.candidates:
            if hasattr(cand, "content") and hasattr(cand.content, "parts"):
                for part in cand.content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        img_bytes = b64decode(part.inline_data.data); break
                if img_bytes: break
    if not img_bytes: 
        return JSONResponse({"ok": False, "error":"no_image_data"}, 500)
    
    project_dir = os.path.join(MEDIA_ROOT, f"project_{project_id}")
    os.makedirs(project_dir, exist_ok=True)
    filename = f"img_{uuid.uuid4().hex}.png"
    path = os.path.join(project_dir, filename)
    with open(path, "wb") as f: f.write(img_bytes)
    rel_url = f"/media/project_{project_id}/{filename}"
    with Session(engine) as session:
        ill = Illustration(project_id=project_id, file_path=rel_url, prompt=desc, style=style, scene_label=scene_label, character_id=character_id)
        session.add(ill); session.commit()
    return JSONResponse({"ok": True, "url": rel_url})

@app.get("/images/{project_id}")
def list_images(project_id: int):
    with Session(engine) as session:
        rows = session.exec(select(Illustration).where(Illustration.project_id == project_id)).all()
    items = []
    for r in rows:
        d = r.dict()
        d["url"] = r.file_path
        items.append(d)
    return JSONResponse({"items": items})
    
@app.post("/images/{pid}/delete")
def delete_image(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        row = session.get(Illustration, id)
        if row: 
            try:
                rel = row.file_path.replace("/media/", "", 1)
                full = _safe_join_under(MEDIA_ROOT, rel)
                if os.path.exists(full): os.remove(full)
            except Exception as e: 
                print("Failed to remove image file:", e)
            session.delete(row); session.commit()
    return JSONResponse({"ok": True})

# ====== Uvicorn Entrypoint ======
if __name__ == "__main__":
    import uvicorn
    if not GOOGLE_API_KEY:
        print("\nWARNING: GOOGLE_API_KEY is not set. The application will not function correctly.\n")
    uvicorn.run("app_fixed:app", host="0.0.0.0", port=8000, reload=True)
