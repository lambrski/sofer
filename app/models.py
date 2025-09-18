# app/models.py
import uuid
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field

# (כל הקלאסים של SQLModel שהיו ב-main.py הועברו לכאן)
# Project, SynopsisHistory, ProjectObject, History, GeneralNotes,
# ChapterOutline, Rule, Illustration, Review, ReviewDiscussion,
# LibraryFile, ProjectLibraryLink, TempFile

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
