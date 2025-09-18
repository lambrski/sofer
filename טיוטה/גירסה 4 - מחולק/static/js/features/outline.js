// static/js/features/outline.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import * as api from '../api.js';

let currentOutlineText = "";
let currentOutlineChapterTitle = "";
let currentSceneDiscussion = { cardId: null, title: "", originalContent: "", thread: [], fullOutline: "" };
let currentDraftDiscussion = { sceneDescription: "", originalDraft: "", thread: [] };

function parseAndRenderOutline(outlineText, chapterTitle) {
    const contentEl = document.getElementById('outlineManagerContent');
    contentEl.innerHTML = '';
    
    // Improved regex to better split scenes
    const sceneBlocks = outlineText.split(/\n(?=\s*(?:\*\*|##)\s*סצנה|\d+\.\s*\*)/).filter(Boolean);

    if (sceneBlocks.length === 0) {
        contentEl.innerHTML = `<div class='muted'>לא נמצאו סצנות תקינות במתווה. ודא שהפורמט הוא **סצנה X: כותרת**.</div>`;
    } else {
        contentEl.innerHTML = sceneBlocks.map((sceneText, index) => {
            const lines = sceneText.trim().split('\n');
            const sceneTitle = lines.shift() || `סצנה ${index + 1}`;
            const sceneContent = lines.join('\n').trim();
            const cardId = `scene-card-content-${index}`;

            return `
              <div class="outline-card">
                  <h5>${esc(sceneTitle.replace(/[\*#]/g, ''))}</h5>
                  <div class="small muted" style="white-space: pre-wrap;" id="${cardId}">${esc(sceneContent)}</div>
                  <div class="btnrow">
                    <button class="linklike discuss-scene-btn" data-card-id="${cardId}" data-scene-title="${esc(sceneTitle)}">💬 דיון</button>
                    <button class="linklike write-scene-btn" data-card-id="${cardId}" data-scene-title="${esc(sceneTitle)}">✍️ כתוב טיוטה לסצנה</button>
                  </div>
              </div>`;
        }).join('');
    }
}

function openOutlineManager(outlineText, chapterTitle) {
    currentOutlineText = outlineText;
    currentOutlineChapterTitle = chapterTitle;
    
    const modal = document.getElementById('outlineManagerModal');
    document.getElementById('outlineManagerTitle').textContent = `מתווה עבור: ${esc(chapterTitle)}`;
    parseAndRenderOutline(outlineText, chapterTitle);
    openModal(modal);
}

async function handleWriteChapterClick(pid, pkind, e) {
    const button = e.target;
    const chapterTitle = button.getAttribute('data-chapter-title');
    if (!confirm(`האם להפעיל את הפעולה על: "${chapterTitle}"?`)) return;
      
    button.disabled = true;
    button.innerHTML = `<div class='spinner' style="width:12px; height:12px;"></div>`;

    try {
        const body = { 
            text: chapterTitle, mode: 'write', write_kind: 'breakdown_chapter',
            use_notes: '1', use_history: '0'
        };
        const data = await api.askAI(pid, body);
        
        if (pkind === 'פרוזה') {
            openOutlineManager(data.answer, chapterTitle);
        } else { // Comic
            document.getElementById('chapterOutputTitle').textContent = `תוצר: ${chapterTitle}`;
            document.getElementById('chapterOutputContent').innerHTML = esc(data.answer).replace(/\n/g, '<br>');
            openModal(document.getElementById('chapterOutputModal'));
        }
    } catch (err) {
        alert("שגיאה: " + err.message);
    } finally {
        button.disabled = false;
        button.innerHTML = pkind === 'פרוזה' ? '📜 כתוב מתווה לפרק' : '✍️ כתוב את הפרק';
    }
}

async function handleViewOutlineClick(pid, e) {
    const btn = e.target;
    const chapterTitle = btn.getAttribute('data-chapter-title');
    btn.disabled = true;
    btn.textContent = "טוען...";
    try {
        const data = await api.getOutline(pid, chapterTitle);
        openOutlineManager(data.outline_text, chapterTitle);
    } catch (err) {
        alert("שגיאה בטעינת המתווה: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "👁️ הצג מתווה שמור";
    }
}

export function initOutline(pid, pkind) {
    // Event delegation for dynamically created buttons on synopsis cards
    document.body.addEventListener('click', (e) => {
        if (e.target.matches('.write-chapter-btn')) {
            handleWriteChapterClick(pid, pkind, e);
        }
        if (e.target.matches('.view-outline-btn')) {
            handleViewOutlineClick(pid, e);
        }
        if (e.target.matches('.discuss-scene-btn')) {
            // Open scene discussion logic
        }
        if (e.target.matches('.write-scene-btn')) {
            // Write scene draft logic
        }
    });

    safeAttach('saveOutlineBtn', 'click', async () => {
        const btn = document.getElementById('saveOutlineBtn');
        btn.disabled = true;
        btn.textContent = "שומר...";
        try {
            await api.saveOutline(pid, currentOutlineChapterTitle, currentOutlineText);
            alert("המתווה נשמר בהצלחה!");
            btn.textContent = "נשמר ✓";
            // Optionally, refresh synopsis cards if visible
            if (document.getElementById('synopsisCardView').style.display === 'block') {
                document.getElementById('synopsisToggleViewBtn').click(); // Toggle to editor
                document.getElementById('synopsisToggleViewBtn').click(); // And back to cards to refresh
            }
        } catch (err) {
            alert("שגיאה בשמירת המתווה: " + err.message);
            btn.textContent = "💾 שמור מתווה";
        } finally {
            btn.disabled = false;
        }
    });

    safeAttach('closeOutlineManagerBtn', 'click', closeAllModals);
    safeAttach('closeOutlineManagerBtnFooter', 'click', closeAllModals);

    // Other modals related to outline (scene discussion, draft) can be initialized here
}