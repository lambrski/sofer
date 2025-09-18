# app/main.py
import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.database import create_db_and_tables
from app.routes import projects, chat, notes, synopsis, illustrations, review, library, rules, outlines

# Create all database tables on startup
create_db_and_tables()

app = FastAPI()

# Mount static files
os.makedirs("static", exist_ok=True)
os.makedirs("media", exist_ok=True)
os.makedirs("library", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/media", StaticFiles(directory="media"), name="media")
app.mount("/library", StaticFiles(directory="library"), name="library")

templates = Jinja2Templates(directory="templates")

# Include all the different API routers
app.include_router(projects.router)
app.include_router(chat.router)
app.include_router(notes.router)
app.include_router(synopsis.router)
app.include_router(illustrations.router)
app.include_router(review.router)
app.include_router(library.router)
app.include_router(rules.router)
app.include_router(outlines.router)

# The main home page route remains here
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return projects.home_page(request) # Logic moved to projects router

# Uvicorn entrypoint
if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        print("\nWARNING: GOOGLE_API_KEY is not set. The application will not function correctly.\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
