# app/routes/review.py
from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, delete

from app.database import engine
from app.models import Review, ReviewDiscussion
from app.services import get_text_model, build_rules_preamble
from prompts import (create_general_review_prompt, create_proofread_prompt, 
                     create_review_discussion_prompt, create_review_update_prompt)

router = APIRouter()

@router.post("/review/{project_id}/run")
def run_review(project_id: int, kind: str = Form(...), source: str = Form(...), input_text: str = Form(...)):
    rules = build_rules_preamble(project_id)
    title = input_text[:40] + "..." if len(input_text) > 40 else input_text
    prompt = create_general_review_prompt(rules, input_text) if kind == "general" else create_proofread_prompt(input_text)
    
    try:
        text_model = get_text_model()
        result = text_model.generate_content(prompt).text
        with Session(engine) as session:
            review_obj = Review(
                project_id=project_id, 
                kind=kind, 
                source=source, 
                title=title, 
                result=result, 
                input_size=len(input_text), 
                input_text=input_text
            )
            session.add(review_obj)
            session.commit()
        return JSONResponse({"ok": True, "result": result})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@router.get("/reviews/{project_id}")
def list_reviews(project_id: int, kind: str = ""):
    with Session(engine) as session:
        q = select(Review).where(Review.project_id == project_id).order_by(Review.created_at.desc())
        if kind: 
            q = q.where(Review.kind == kind)
        rows = session.exec(q).all()
    return JSONResponse({"items": [r.model_dump(mode='json') for r in rows]})

@router.post("/reviews/{pid}/delete")
def delete_review(pid: int, id: int = Form(...)):
    with Session(engine) as session:
        r = session.get(Review, id)
        if r:
            session.exec(delete(ReviewDiscussion).where(ReviewDiscussion.review_id == id))
            session.delete(r)
            session.commit()
    return JSONResponse({"ok": True})

@router.get("/review/{pid}/discussion/{review_id}")
def get_review_discussion(review_id: int):
    with Session(engine) as session:
        msgs = session.exec(select(ReviewDiscussion).where(ReviewDiscussion.review_id == review_id).order_by(ReviewDiscussion.created_at.asc())).all()
    return JSONResponse({"items": [m.model_dump(mode='json') for m in msgs]})

@router.post("/review/{pid}/discuss")
def post_review_discussion(pid: int, review_id: int = Form(...), question: str = Form(...)):
    with Session(engine) as session:
        rev = session.get(Review, review_id)
        if not rev: 
            return JSONResponse({"ok": False}, 404)
        
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="user", message=question))
        session.commit()
        
        prompt = create_review_discussion_prompt(rev, question)
        text_model = get_text_model()
        answer = text_model.generate_content(contents=[prompt]).text
        
        session.add(ReviewDiscussion(project_id=pid, review_id=rev.id, role="assistant", message=answer))
        session.commit()
    return JSONResponse({"ok": True})

@router.post("/review/{pid}/update_from_discussion")
def update_review(pid: int, review_id: int = Form(...)):
    with Session(engine) as session:
        rev = session.get(Review, review_id)
        if not rev: 
            return JSONResponse({"ok": False, "error": "Review not found"}, status_code=404)
        
        discussions = session.exec(select(ReviewDiscussion).where(ReviewDiscussion.review_id == rev.id).order_by(ReviewDiscussion.created_at.asc())).all()
        thread = "\n".join([f"{d.role}: {d.message}" for d in discussions])
        prompt = create_review_update_prompt(rev, thread)
        
        try:
            text_model = get_text_model()
            new_result = text_model.generate_content(prompt).text
            rev.result = new_result
            session.add(rev)
            session.commit()
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
