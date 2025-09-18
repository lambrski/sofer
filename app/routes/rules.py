# app/routes/rules.py
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.database import engine
from app.models import Rule

router = APIRouter(prefix="/rules")

@router.get("/{project_id}")
def rules_list(project_id: int):
    with Session(engine) as session:
        global_rules = session.exec(select(Rule).where(Rule.project_id == None)).all()
        project_rules = session.exec(select(Rule).where(Rule.project_id == project_id)).all()
    return JSONResponse({
        "global": [r.model_dump(mode='json') for r in global_rules],
        "project": [r.model_dump(mode='json') for r in project_rules]
    })

@router.post("/{pid}/add")
def rules_add(pid: int, scope: str = Form(...), text: str = Form(...), mode: str = Form(...)):
    with Session(engine) as session:
        project_id = None if scope == "global" else pid
        session.add(Rule(project_id=project_id, text=text, mode=mode))
        session.commit()
    return JSONResponse({"ok": True})

@router.post("/{pid}/update")
def rules_update(pid: int, id: int = Form(...), text: str = Form(...), mode: str = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r:
            r.text = text
            r.mode = mode
            session.add(r)
            session.commit()
    return JSONResponse({"ok": True})

@router.post("/{pid}/delete")
def rules_delete(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Rule, id)
        if r:
            session.delete(r)
            session.commit()
    return JSONResponse({"ok": True})
