// static/js/api.js

async function post(url, body) {
    const res = await fetch(url, {
        method: "POST",
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(body)
    });
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || err.answer || 'Server Error');
    }
    return res.json();
}

async function get(url) {
    const res = await fetch(url);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Server Error');
    }
    return res.json();
}

// --- Notes ---
export const getNotes = (pid) => get(`/general/${pid}`);
export const saveNotes = (pid, text) => post(`/general/${pid}`, { text });

// --- Rules ---
export const getRules = (pid) => get(`/rules/${pid}`);
export const addRule = (pid, data) => post(`/rules/${pid}/add`, data);
export const updateRule = (pid, data) => post(`/rules/${pid}/update`, data);
export const deleteRule = (pid, id) => post(`/rules/${pid}/delete`, { id });

// --- Chat & History ---
export const getChatHistory = (pid) => get(`/chat/${pid}`);
export const clearChatHistory = (pid) => post(`/chat/${pid}/clear`, {});
export const getPromptHistory = (pid) => get(`/history/${pid}`);
export const clearPromptHistory = (pid) => post(`/history/${pid}/clear`, {});
export const uploadTempFiles = (pid, formData) => fetch(`/upload_temp_files/${pid}`, { method: "POST", body: formData }).then(res => res.json());
export const askAI = (pid, body) => post(`/ask/${pid}`, body);

// --- Synopsis ---
export const getSynopsis = (pid) => get(`/project/${pid}/synopsis`);
export const saveSynopsis = (pid, text) => post(`/project/${pid}/synopsis`, { text });
export const getSynopsisHistory = (pid) => get(`/api/project/${pid}/synopsis_history`);
export const clearSynopsisHistory = (pid) => post(`/api/project/${pid}/synopsis_history/clear`, {});
export const parseSynopsis = (pid, text) => post(`/api/project/${pid}/parse_synopsis`, { text });
export const loadSynopsisDraft = (pid) => get(`/api/project/${pid}/load_draft`);
export const saveSynopsisDraft = (pid, draft_text, discussion_thread) => post(`/api/project/${pid}/save_draft`, { draft_text, discussion_thread });
export const summarizeChapter = (pid, body) => post(`/api/project/${pid}/summarize_chapter_discussion`, body);
export const updateSynopsisFromDiscussion = (pid, body) => post(`/api/project/${pid}/update_synopsis_from_discussion`, body);
export const updateDivisionFromDiscussion = (pid, body) => post(`/api/project/${pid}/update_division_from_discussion`, body);

// --- Outlines & Scenes ---
export const getOutlinesList = (pid) => get(`/api/project/${pid}/outlines/list`);
export const getOutline = (pid, chapter_title) => get(`/api/project/${pid}/outline?chapter_title=${encodeURIComponent(chapter_title)}`);
export const saveOutline = (pid, chapter_title, outline_text) => post(`/api/project/${pid}/outline`, { chapter_title, outline_text });
export const updateScene = (pid, body) => post(`/api/project/${pid}/update_scene_from_discussion`, body);
export const writeScene = (pid, scene_title, scene_description) => post(`/api/project/${pid}/write_scene`, { scene_title, scene_description });
export const updateDraft = (pid, body) => post(`/api/project/${pid}/update_draft_from_discussion`, body);

// --- Reviews ---
export const getReviews = (pid, kind) => get(`/reviews/${pid}?kind=${kind}`);
export const runReview = (pid, body) => post(`/review/${pid}/run`, body);
export const deleteReview = (pid, id) => post(`/reviews/${pid}/delete`, { id });
export const getReviewDiscussion = (pid, review_id) => get(`/review/${pid}/discussion/${review_id}`);
export const postReviewDiscussion = (pid, review_id, question) => post(`/review/${pid}/discuss`, { review_id, question });
export const updateReviewFromDiscussion = (pid, review_id) => post(`/review/${pid}/update_from_discussion`, { review_id });

// --- Illustrations & Objects ---
export const getObjects = (pid) => get(`/project/${pid}/objects/list`);
export const createObject = (pid, body) => post(`/project/${pid}/objects/create`, body);
export const deleteObject = (pid, object_id) => post(`/project/${pid}/objects/delete`, { object_id });
export const getImages = (pid) => get(`/images/${pid}`);
export const createImage = (pid, body) => post(`/image/${pid}`, body);
export const deleteImage = (pid, id) => post(`/images/${pid}/delete`, { id });

// --- Library ---
export const getLibraryFiles = () => get(`/api/library/list`);
export const uploadLibraryFiles = (formData) => fetch(`/api/library/upload`, { method: "POST", body: formData }).then(res => res.json());
export const deleteLibraryFile = (id) => post(`/api/library/delete`, { id });