// static/js/main.js
import { initChat } from './features/chat.js';
import { initSynopsis } from './features/synopsis.js';
import { initReview } from './features/review.js';
import { initGallery } from './features/gallery.js';
import { initLibrary } from './features/library.js';
import { initOutline } from './features/outline.js';
import { initRules } from './features/rules.js';
import { initNotes } from './features/notes.js';
import { initGeneralUI, applyModeUI } from './ui.js';

// Wait for the DOM to be fully loaded
document.addEventListener('DOMContentLoaded', () => {
    // Get project-specific data from the body tag
    const pid = Number(document.body.getAttribute('data-project-id'));
    const pkind = document.body.getAttribute('data-project-kind');

    // Initialize core UI elements and generic handlers
    initGeneralUI();

    // Initialize all feature modules
    initNotes(pid);
    initRules(pid);
    initChat(pid);
    initLibrary(pid);
    initSynopsis(pid, pkind);
    initReview(pid);
    initGallery(pid);
    initOutline(pid, pkind);

    // Set the initial UI state based on the selected mode
    applyModeUI();
});