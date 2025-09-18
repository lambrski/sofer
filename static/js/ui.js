// static/js/ui.js

const backdrop = document.getElementById('backdrop');

export function esc(s) {
    return (s || "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

export function fmtTime(iso) {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function openModal(el) {
    if (el) {
        el.style.display = "block";
        backdrop.style.display = "block";
    }
}

export function closeAllModals() {
    document.querySelectorAll('.modal').forEach(m => m.style.display = "none");
    backdrop.style.display = "none";
}

export function safeAttach(id, event, handler) {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener(event, handler);
    }
}

export function applyModeUI() {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const writeKindEl = document.getElementById('writeKind');
    const brainstormControls = document.getElementById('brainstormControls');
    
    if (writeKindEl) writeKindEl.style.display = (mode === 'write') ? 'inline-block' : 'none';
    if (document.getElementById('chatPanel')) document.getElementById('chatPanel').style.display = (mode === 'review' || mode === 'illustrate') ? 'none' : 'block';
    if (brainstormControls) brainstormControls.style.display = (mode === 'brainstorm' || mode === 'write') ? 'flex' : 'none';
    if (document.getElementById('reviewPanel')) document.getElementById('reviewPanel').style.display = (mode === 'review') ? 'block' : 'none';
    if (document.getElementById('illustratePanel')) document.getElementById('illustratePanel').style.display = (mode === 'illustrate') ? 'block' : 'none';
    
    // Trigger data loading when a tab is shown
    if (mode === 'illustrate') {
        // This will be handled by the gallery initializer
        document.dispatchEvent(new CustomEvent('load-gallery'));
    }
    if (mode === 'review') {
        // This will be handled by the review initializer
        document.dispatchEvent(new CustomEvent('load-reviews'));
    }
}

export function initGeneralUI() {
    backdrop.addEventListener("click", closeAllModals);
    document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', applyModeUI));
    
    // Universal Ctrl+Enter Handler
    document.addEventListener("keydown", (ev) => {
        if (ev.ctrlKey && ev.key === "Enter") {
            const activeEl = document.activeElement;
            const activeId = activeEl.id;
            const buttonToClick = {
                'prompt': 'sendBtn',
                'reviewInput': 'runReviewBtn',
                'discussionInput': 'askDiscussionBtn',
                'chapterDiscussionInput': 'sendChapterDiscussionBtn',
                'synopsisBuilderInput': 'sendSynopsisBuilderBtn',
                'refineDivisionChatInput': 'sendRefineChatBtn',
                'sceneDiscussionInput': 'sendSceneDiscussionBtn',
                'draftDiscussionInput': 'sendDraftDiscussionBtn',
                'imgDesc': 'genImageBtn',
                'objName': 'createObjectBtn',
                'objStyle': 'createObjectBtn',
                'objDesc': 'createObjectBtn',
            }[activeId];
            
            if (buttonToClick) {
                document.getElementById(buttonToClick)?.click();
                ev.preventDefault();
            }
        }
    });
}