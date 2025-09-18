# main.py
# The main entry point for the FastAPI application.
# Its only job is to initialize the app, create the database, and include the routers.

import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Import the routers from the 'routers' directory
from routers import project_api, writing_process_api, ai_api, assets_api, review_api
# Import the function to create the database tables
from database import create_db_and_tables

# Define constants
MEDIA_ROOT = "media"
LIBRARY_ROOT = "library"
TEMP_ROOT = "temp_files"
VECTORSTORE_ROOT = "vectorstores"

# Create necessary directories on startup
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(LIBRARY_ROOT, exist_ok=True)
os.makedirs(TEMP_ROOT, exist_ok=True)
os.makedirs(VECTORSTORE_ROOT, exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# Create the FastAPI app instance
app = FastAPI()

# Mount static files directories
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")
app.mount("/library", StaticFiles(directory=LIBRARY_ROOT), name="library")
app.mount("/temp_files", StaticFiles(directory=TEMP_ROOT), name="temp_files")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include all the modular routers
app.include_router(project_api.router)
app.include_router(writing_process_api.router)
app.include_router(ai_api.router)
app.include_router(assets_api.router) # Assuming you created this from the last step
app.include_router(review_api.router) # Assuming you created this from the last step


# Define what happens on application startup
@app.on_event("startup")
def on_startup():
    print("Creating database and tables...")
    create_db_and_tables()
    print("Database is ready.")

# Main entry point for running the app with Uvicorn
if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        print("\nWARNING: GOOGLE_API_KEY is not set. The application will not function correctly.\n")
    
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["."])
