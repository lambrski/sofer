# app/services.py
import os
import google.generativeai as genai
from typing import Optional
from PIL import Image
from sqlmodel import Session, select

from app.database import engine
from app.models import Rule
from prompts import create_image_rewrite_prompt

# ====== Constants & SDK Init ======
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# Original, speculative model names restored as requested
TEXT_MODEL_API_NAME = "gemini-2.5-pro"
IMAGE_MODEL_API_NAME = "gemini-2.5-flash-image-preview"

genai.configure(api_key=GOOGLE_API_KEY)

# This block now includes a fallback to a stable model
try:
    text_model = genai.GenerativeModel(TEXT_MODEL_API_NAME)
    print(f"Successfully initialized speculative text model: {TEXT_MODEL_API_NAME}")
except Exception as e:
    print(f"ERROR: Could not initialize text model '{TEXT_MODEL_API_NAME}'. Error: {e}")
    print("Fallback: Initializing gemini-1.5-pro-latest instead.")
    try:
        text_model = genai.GenerativeModel("gemini-1.5-pro-latest")
    except Exception as fallback_e:
        print(f"FATAL: Could not initialize fallback model either. Error: {fallback_e}")
        text_model = None


# ====== Service Functions ======

def get_text_model():
    if not text_model:
        raise RuntimeError("Text model could not be initialized, not even the fallback.")
    return text_model

def build_rules_preamble(project_id: int) -> str:
    with Session(engine) as session:
        rules = session.exec(select(Rule).where((Rule.project_id == None) | (Rule.project_id == project_id))).all()
    enforced = [r.text for r in rules if r.mode == "enforce"]
    if not enforced: return ""
    return "עליך לציית לכללים הבאים באופן מוחלט ומדויק:\n- " + "\n- ".join(enforced) + "\n\n"

def rewrite_prompt_for_image_generation(raw_prompt: str) -> str:
    print(f"Rewriting raw prompt: '{raw_prompt}'")
    meta_prompt = create_image_rewrite_prompt(raw_prompt)
    try:
        rewrite_model = get_text_model()
        response = rewrite_model.generate_content(meta_prompt)
        rewritten_prompt = response.text.strip()
        print(f"Rewritten prompt: '{rewritten_prompt}'")
        return rewritten_prompt
    except Exception as e:
        print(f"Error during prompt rewrite: {e}")
        raise RuntimeError(f"Prompt rewriting failed. Error: {e}") from e

def generate_image_with_gemini(prompt: str, source_image: Optional[Image.Image] = None) -> bytes:
    try:
        print(f"Attempting to generate image with {IMAGE_MODEL_API_NAME}. Prompt: '{prompt}'")
        image_model = genai.GenerativeModel(IMAGE_MODEL_API_NAME)
        content = [prompt, source_image] if source_image else [prompt]
        response = image_model.generate_content(content)

        if response.parts:
            for part in response.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise RuntimeError(f"Image request blocked: {response.prompt_feedback.block_reason.name}")
        raise RuntimeError("No image data returned from Gemini.")

    except Exception as e:
        print(f"An error occurred in generate_image_with_gemini with model '{IMAGE_MODEL_API_NAME}': {e}")
        print("Fallback: Retrying image generation with gemini-1.5-pro-latest.")
        try:
            image_model = genai.GenerativeModel("gemini-1.5-pro-latest")
            response = image_model.generate_content([prompt, source_image] if source_image else [prompt])
            if response.parts:
                for part in response.parts:
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data
            raise RuntimeError(f"Image generation failed on both models. Original error: {e}")
        except Exception as fallback_e:
             raise RuntimeError(f"Image generation fallback also failed. Error: {fallback_e}")
