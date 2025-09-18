@echo off
cd C:\sofer
start "" http://localhost:8000
uvicorn app.main:app --reload
pause