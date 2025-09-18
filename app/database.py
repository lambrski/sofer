# app/database.py
from sqlmodel import create_engine, SQLModel

DB_FILE = "db.sqlite"
engine = create_engine(f"sqlite:///{DB_FILE}", echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
