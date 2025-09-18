# app/routes/projects.py
import shutil
import os
from typing import Optional
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, delete

from app.database import engine
from app.models import (Project, ChapterOutline, SynopsisHistory, History, GeneralNotes, Rule, 
                        Illustration, ReviewDiscussion, Review, ProjectLibraryLink, ProjectObject)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
MEDIA_ROOT = "media"
VECTORSTORE_ROOT = "vectorstores"

@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home_page(request: Request):
    with Session(engine) as session:
        projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return templates.TemplateResponse("home.html", {"request": request, "projects": projects})

@router.post("/new_project")
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

@router.get("/project/{project_id}", response_class=HTMLResponse, include_in_schema=False)
def project_page(request: Request, project_id: int):
    with Session(engine) as session:
        project = session.get(Project, project_id)
        if not project:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse("project.html", {"request": request, "project": project})

@router.post("/delete_project/{project_id}")
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
