# prompts.py
# This file centralizes all complex prompts for the AI models.

def create_prose_master_prompt() -> str:
    return """
תפקידך הוא לשמש כעוזר מקצועי לסופר, המתמחה בכתיבת רומני פרוזה. כל המחשבה והפלט שלך חייבים להיות בסגנון ספרותי.
הטקסט ב'קובץ כללי' מהווה את הבסיס וההקשר של עולם הסיפור. עליך להתייחס למידע הקיים בו כאמת המוחלטת של הסיפור עד כה. כל תוכן חדש שאתה יוצר חייב להיות עקבי והמשכי לבסיס זה.
מכיוון שזהו פרויקט פרוזה, עליך להתעלם ולהימנע לחלוטין מכל קונספט של מדיה ויזואלית. חל איסור מוחלט להשתמש במונחים כמו 'פריימים', 'פאנלים', 'תסריט למאייר', 'זוויות מצלמה' או דיאלוג בפורמט של תסריט.
"""

def create_persona_prompt(persona: str) -> str:
    if persona == 'assistant':
        return "הפרסונה שלך היא 'עוזר ישיר'. תפקידך להיות תמציתי ומדויק.\n\n"
    return "הפרסונה שלך היא 'שותף יצירתי מקצועי'. חשוב ברמה גבוהה והצע רעיונות מקוריים.\n\n"

def create_chapter_breakdown_prompt(preamble: str, context: str, chapter_synopsis: str, project) -> str:
    # This function needs logic to differentiate between prose and comic
    if project.kind == 'קומיקס':
        num_chapters = project.chapters or 18
        total_pages = project.total_pages or 54
        frames_per_page = project.frames_per_page or 6
        pages_per_chapter = total_pages // num_chapters if num_chapters > 0 else 1
        
        return f"""{preamble}{context}להלן תקציר של פרק בקומיקס:
---
{chapter_synopsis}
---
המשימה שלך היא לכתוב את התסריט המפורט עבור הפרק. עליך לפרק את התקציר לעמודים ופריימים, לפי מבנה של {pages_per_chapter} עמודים, ו-{frames_per_page} פריימים לעמוד.

**כלל ברזל: בכל פריים חייב להופיע טקסט כלשהו, בין אם הרהור או דיאלוג. אין ליצור פריימים ללא טקסט.**

הקפד על הפורמט: מספר פריים, אחריו טקסט (אם יש הרהור, ציין 'הרהור:'), ובשורה נפרדת תיאור ויזואלי בסוגריים מרובעים.
דוגמה (אם מתחילים מפריים 19): 19.
הרהור: עוד הפרעה...
[קצין במדים יושב במשרד מפואר ומביט בטלפון המצלצל].

החזר אך ורק את התסריט המעוצב, ללא כל משפט פתיחה או סיכום."""
    else: # Prose
        return f"""{preamble}{context}בהתבסס על תקציר הפרק הבא, כתוב טיוטה ראשונית של הפרק המלא.
התמקד בהרחבת הנקודות המרכזיות, פיתוח הדיאלוגים, תיאור הסביבה והעמקת רגשות הדמויות.
החזר רק את הטקסט של הפרק, ללא כל הקדמה או סיכום.

**תקציר הפרק:**
---
{chapter_synopsis}
---
"""


def create_synopsis_division_prompt(synopsis_text: str, num_chapters: int, preamble: str, context: str) -> str:
    return f"""{preamble}{context}Your task is to act as a literary editor and divide the following synopsis into exactly {num_chapters} chapters. You must do this by ONLY inserting chapter headings (e.g., 'פרק 1:') into the original text.

**CRITICAL INSTRUCTIONS TO FOLLOW EXACTLY:**

1.  **PRESERVE ALL CONTENT:** You are strictly forbidden from summarizing, editing, rewriting, shortening, or altering the original content in any way. Your final output MUST contain 100% of the original text.
2.  **NARRATIVE LOGIC:** The division must be based on narrative logic. A chapter is a dramatic unit, not a measure of length.
3.  **STRUCTURAL HINT:** The original text may be divided into sections with letters (א, ב, ג). Use these as strong hints for logical breaks.
4.  **FINAL VERIFICATION:** Before you output the text, double-check that the last sentence of your output is identical to the last sentence of the original input text.
5.  **NO PREAMBLE:** Do not add any conversational text or preamble to your response. The response must begin directly with "פרק 1...".

**The full text to be divided is below:**
---
{synopsis_text}
"""

def create_prose_division_prompt(synopsis_text: str, min_words: int, max_words: int, preamble: str, context: str) -> str:
    return f"""{preamble}{context}Your task is to act as a professional literary editor and divide the following prose synopsis into logical chapters.

**CRITICAL INSTRUCTIONS TO FOLLOW EXACTLY:**

1.  **PRIMARY GOAL: NARRATIVE COHESION.** Your main goal is to find the most natural breaking points in the story. A chapter should represent a complete scene, a significant shift in time or location, or a point of high tension. The narrative flow is the most important factor.

2.  **SECONDARY GOAL: WORD COUNT GUIDELINE.** As a strong guideline, you should aim to create chapters that, when fully written, would likely be between {min_words} and {max_words} words long. This is an estimation. You must use your literary judgment to balance this guideline with the narrative needs. It is better to have a slightly shorter or longer chapter that ends at a logical point, than a chapter of perfect length that stops awkwardly.

3.  **EXECUTION:** You must perform this task by ONLY inserting chapter headings (e.g., 'פרק 1:', 'פרק 2: שם הפרק') into the original text. You are strictly forbidden from summarizing, editing, or altering the original content in any way.

4.  **NO PREAMBLE:** Do not add any conversational text or preamble. Your response must begin directly with the first word of the divided synopsis (e.g., it must start with "פרק 1...").

**The full text to be divided is below:**
---
{synopsis_text}
"""


def create_general_review_prompt(rules: str, text: str) -> str:
    return f"{rules}המשימה שלך היא לבצע ביקורת ספרותית מקיפה על הסיפור המלא המצורף...\nהסיפור המלא לבדיקה:\n{text}"

def create_proofread_prompt(text: str) -> str:
    return f"בצע הגהה על הטקסט המלא הבא ותקן שגיאות כתיב, דקדוק ופיסוק:\n\n{text}"

def create_review_discussion_prompt(review, question: str) -> str:
    return f"""אתה מנהל דיון על דוח ביקורת שכתבת...הטקסט המקורי שנבדק:
---
{review.input_text}
---
דוח הביקורת שכתבת:
---
{review.result}
---
השאלה החדשה של המשתמש: {question}"""

def create_review_update_prompt(review, discussion_thread: str) -> str:
    return f"""...הטקסט המקורי שנבדק:
---
{review.input_text}
---
דוח הביקורת הישן והשגוי שכתבת:
---
{review.result}
---
תמלול הדיון שבו התגלו הטעויות:
---
{discussion_thread}
---
אנא כתוב גרסה חדשה, מתוקנת ומשופרת של דוח הביקורת..."""

def create_image_rewrite_prompt(raw_prompt: str) -> str:
    return f"""
You are a "prompt engineer". You will receive an image description from a user. Your task is to rewrite it into a detailed, visual, and safe prompt for an image generation model.
Focus on visual characteristics: appearance, clothing, environment, lighting, and style.
Instead of using potentially sensitive words directly, describe the subject's apparent age and features.
The goal is to honor the user's intent while ensuring the prompt is safe for generation.
Return ONLY the rewritten prompt, without any preamble.

The user's original description is: '{raw_prompt}'
"""

def create_chapter_summary_prompt(original_content: str, discussion_thread: str, full_synopsis: str) -> str:
    return f"""
Your role is an expert editor. You will be given the full synopsis of a story, the original text of a specific chapter's synopsis, and a transcript of a discussion about that chapter.
Your task is to rewrite the specific chapter's synopsis based on the conclusions of the discussion, while maintaining consistency with the full synopsis.

Follow these steps precisely:
1.  Read the **Full Synopsis** to understand the overall story context.
2.  Read the **Original Chapter Synopsis** to understand its starting point.
3.  Read the **Discussion Transcript** to understand the key decisions, additions, or changes that were agreed upon for this specific chapter.
4.  Synthesize the conclusions from the discussion.
5.  Rewrite the original chapter synopsis to integrate these conclusions seamlessly. Preserve the original tone and style. Do not add any new ideas that were not mentioned in the discussion.
6.  Return ONLY the final, rewritten chapter synopsis. Do not add any conversational preamble, explanations, or summaries. The output must be only the complete, updated text of the chapter's synopsis.

**Full Story Synopsis (for context):**
---
{full_synopsis}
---

**Original Chapter Synopsis (the text to be updated):**
---
{original_content}
---

**Discussion Transcript (the source of changes):**
---
{discussion_thread}
---

**Rewritten Chapter Synopsis:**
"""

def create_synopsis_update_prompt(current_draft: str, discussion_thread: str) -> str:
    return f"""
You are a senior editor helping a writer develop a synopsis. You will be given the current draft of the synopsis and a transcript of a brainstorming discussion.

Your task is to intelligently rewrite and improve the current draft based on the ideas and conclusions from the discussion.

Follow these steps:
1.  Read the **Current Synopsis Draft** to understand the story so far.
2.  Read the **Discussion Transcript** to identify the new ideas, changes, plot points, and character developments that were decided upon.
3.  Integrate these new elements into the synopsis. You may need to restructure, add, remove, or rewrite sections to make the story flow logically.
4.  Ensure the final output is a single, cohesive, and complete synopsis.
5.  Return ONLY the new, rewritten synopsis. Do not include any conversational text, explanations, or preamble. Your response should be the full text of the improved synopsis.

**Current Synopsis Draft:**
---
{current_draft}
---

**Discussion Transcript:**
---
{discussion_thread}
---

**New, Rewritten Synopsis:**
"""

def create_division_update_prompt(original_division: str, discussion_thread: str) -> str:
    return f"""
You are an expert editor. You will be given a synopsis that has already been divided into chapters, and a transcript of a discussion about how to improve that division.

Your task is to re-divide the original text based on the instructions from the discussion.

Follow these steps precisely:
1.  Read the **Original Divided Synopsis** to understand the starting point.
2.  Read the **Discussion Transcript** to understand the requested changes (e.g., "merge chapters 2 and 3," "split chapter 5 into two parts").
3.  Apply these changes to the original text. **Crucially, you must not alter, summarize, or rewrite the content of the synopsis itself.** Your only job is to move, add, or remove the chapter headings (e.g., "פרק 1:"). The final word count must be identical to the original.
4.  Return ONLY the final, re-divided synopsis. Do not add any conversational preamble or explanations. Your response must begin directly with "פרק 1...".

**Original Divided Synopsis:**
---
{original_division}
---

**Discussion Transcript:**
---
{discussion_thread}
---

**New, Re-divided Synopsis:**
"""
