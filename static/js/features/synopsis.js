// static/js/features/synopsis.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import * as api from '../api.js';

let currentChapterDiscussion = { title: "", originalContent: "", thread: [] };
let currentSynopsisBuilder = { thread: [] };
let currentDivisionRefinement = { originalDivision: "", thread: [] };

async function loadSynopsisHistory(pid) {
    const historyEl = document.getElementById('synopsisHistory');
    if (!historyEl) return;
    historyEl.innerHTML = `<div class='muted'>טוען היסטוריה...</div>`;
    try {
        const data = await api.getSynopsisHistory(pid);
        if (!data.items || data.items.length === 0) {
            historyEl.innerHTML = `<div class='muted'>אין היסטוריית גרסאות.</div>`;
            return;
        }
        historyEl.innerHTML = data.items.map(item => `
            <div class="li">
                <div class="rowflex" style="justify-content: space-between;">
                    <strong>גרסה מתאריך ${new Date(item.created_at).toLocaleString('he-IL')}</strong>
                    <button class="linklike restore-synopsis-btn">שחזר</button>
                </div>
                <div class="box" style="margin-top:4px;">${esc(item.text)}</div>
            </div>`).join('');
        
        historyEl.querySelectorAll('.restore-synopsis-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const text = e.target.closest('.li').querySelector('.box').textContent;
                document.getElementById('synopsisArea').value = text;
                alert('הגרסה שוחזרה לעורך. לחץ "שמור תקציר" כדי לשמור את השינויים.');
            });
        });
    } catch (e) {
        historyEl.innerHTML = `<div class='muted'>שגיאה בטעינת ההיסטוריה.</div>`;
        console.error(e);
    }
}

export async function renderSynopsisCards(pid, pkind) {
    const cardView = document.getElementById('synopsisCardView');
    cardView.innerHTML = `<div class='spinner'></div>`;
    
    try {
        const [outlinesData, chaptersData] = await Promise.all([
            api.getOutlinesList(pid),
            api.parseSynopsis(pid, document.getElementById('synopsisArea').value)
        ]);

        const savedOutlines = outlinesData.titles || [];

        if (!chaptersData.chapters || chaptersData.chapters.length === 0) {
            cardView.innerHTML = `<div class='muted'>לא נמצאו פרקים בתקציר. ודא שהכותרות בפורמט 'פרק X:'.</div>`;
            return;
        }
        const buttonText = pkind === 'פרוזה' ? '📜 כתוב מתווה לפרק' : '✍️ כתוב את הפרק';
        cardView.innerHTML = chaptersData.chapters.map(chap => {
            const hasOutline = savedOutlines.includes(chap.title);
            const outlineButton = hasOutline
                ? `<button class="linklike view-outline-btn" data-chapter-title="${esc(chap.title)}">👁️ הצג מתווה שמור</button>`
                : '';

            return `
              <div class="chapter-card">
                  <h5>${esc(chap.title)}</h5>
                  <div class="small muted" style="white-space: pre-wrap;">${esc(chap.content)}</div>
                  <div class="btnrow">
                    <button class="linklike write-chapter-btn" data-content="${esc(chap.content)}" data-chapter-title="${esc(chap.title)}">${buttonText}</button>
                    <button class="linklike discuss-chapter-btn" data-content="${esc(chap.content)}" data-chapter-title="${esc(chap.title)}">💬 דיון</button>
                    ${outlineButton}
                  </div>
              </div>
            `;
        }).join('');
    } catch (e) {
        cardView.innerHTML = `<div class='muted'>שגיאה בעיבוד הפרקים.</div>`;
        console.error(e);
    }
}

function openChapterDiscussion(e) {
    const button = e.target;
    currentChapterDiscussion.title = button.getAttribute('data-chapter-title');
    currentChapterDiscussion.originalContent = button.getAttribute('data-content');
    currentChapterDiscussion.thread = []; // Reset thread

    document.getElementById('chapterDiscussionTitle').textContent = `דיון על: ${currentChapterDiscussion.title}`;
    document.getElementById('chapterDiscussionThread').innerHTML = '<div class="muted">הדיון ריק. שאל שאלה כדי להתחיל.</div>';
    document.getElementById('chapterDiscussionInput').value = "";
    
    openModal(document.getElementById('chapterDiscussionModal'));
}

export function initSynopsis(pid, pkind) {
    safeAttach('synopsisBtn', 'click', async () => {
        openModal(document.getElementById('synopsisModal'));
        const synopsisArea = document.getElementById('synopsisArea');
        synopsisArea.value = "טוען...";
        try {
            const data = await api.getSynopsis(pid);
            synopsisArea.value = data.text || "";
            await loadSynopsisHistory(pid);
        } catch (e) {
            synopsisArea.value = "שגיאה בטעינת התקציר.";
            console.error(e);
        }
    });

    safeAttach('closeSynopsisBtn', 'click', closeAllModals);

    safeAttach('saveSynopsisBtn', 'click', async () => {
        try {
            await api.saveSynopsis(pid, document.getElementById('synopsisArea').value);
            alert("נשמר");
            await loadSynopsisHistory(pid);
        } catch (e) {
            alert("שגיאה: " + e.message);
            console.error(e);
        }
    });

    safeAttach('synopsisToggleViewBtn', 'click', (e) => {
        const editorView = document.getElementById('synopsisEditorView');
        const cardView = document.getElementById('synopsisCardView');
        const isEditorVisible = editorView.style.display !== 'none';
        
        editorView.style.display = isEditorVisible ? 'none' : 'block';
        cardView.style.display = isEditorVisible ? 'block' : 'none';
        document.getElementById('divideSynopsisBtn').style.display = isEditorVisible ? 'none' : 'inline-block';
        
        e.target.textContent = isEditorVisible ? 'הצג עורך טקסט' : 'הצג כרטיסיות פרקים';
        if (isEditorVisible) {
            renderSynopsisCards(pid, pkind);
        }
    });

    // Division Logic
    safeAttach('divideSynopsisBtn', 'click', async (e) => {
        const btn = e.target;
        const synopsisText = document.getElementById('synopsisArea').value;
        if (!synopsisText.trim()) { alert("התקציר ריק."); return; }
        
        btn.disabled = true;
        btn.innerHTML = `<div class='spinner'></div>`;
        try {
            const body = { 
                mode: 'write', 
                write_kind: 'divide_synopsis', 
                synopsis_text_content: synopsisText 
            };
            if (pkind === 'פרוזה') {
                body.words_per_chapter_min = document.getElementById('prose_min_words').value;
                body.words_per_chapter_max = document.getElementById('prose_max_words').value;
            }
            const data = await api.askAI(pid, body);
            document.getElementById('divisionResultArea').value = data.answer || "לא התקבלה תשובה מהמודל.";
            openModal(document.getElementById('divisionModal'));
        } catch (err) {
            alert(`שגיאה בחלוקת התקציר: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.textContent = "חלק תקציר לפרקים";
        }
    });

    safeAttach('acceptDivisionBtn', 'click', () => {
        document.getElementById('synopsisArea').value = document.getElementById('divisionResultArea').value;
        closeAllModals();
        alert("החלוקה הועתקה לעורך. לחץ 'שמור תקציר' כדי לשמור.");
    });
    safeAttach('closeDivisionModalBtn', 'click', closeAllModals);
    
    // Synopsis Builder Logic
    safeAttach('synopsisBuilderBtn', 'click', async () => {
        const builderArea = document.getElementById('synopsisBuilderArea');
        const builderThread = document.getElementById('synopsisBuilderThread');
        try {
            const data = await api.loadSynopsisDraft(pid);
            builderArea.value = data.draft_text || document.getElementById('synopsisArea').value;
            currentSynopsisBuilder.thread = data.discussion || [];
            
            if (currentSynopsisBuilder.thread.length > 0) {
                builderThread.innerHTML = currentSynopsisBuilder.thread.map(t => 
                    `<div class="turn ${t.role === 'user' ? 'q' : 'a'}"><div class="bubble">${esc(t.content)}</div></div>`
                ).join('');
            } else {
                builderThread.innerHTML = '<div class="muted">התחל שיחה לבניית התקציר...</div>';
            }
        } catch (e) {
            builderArea.value = document.getElementById('synopsisArea').value;
            currentSynopsisBuilder.thread = [];
            builderThread.innerHTML = '<div class="muted">שגיאה בטעינת טיוטה. מתחילים מחדש.</div>';
            console.error(e);
        }
        document.getElementById('synopsisBuilderInput').value = "";
        openModal(document.getElementById('synopsisBuilderModal'));
    });
    
    safeAttach('closeSynopsisBuilderBtn', 'click', closeAllModals);
    safeAttach('saveSynopsisDraftBtn', 'click', async () => {
        const btn = document.getElementById('saveSynopsisDraftBtn');
        btn.disabled = true;
        btn.innerHTML = `<div class='spinner'></div>`;
        try {
            await api.saveSynopsisDraft(pid, document.getElementById('synopsisBuilderArea').value, JSON.stringify(currentSynopsisBuilder.thread));
            alert("טיוטה נשמרה!");
        } catch (err) {
            alert("שגיאה בשמירת הטיוטה: " + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = "💾 שמור טיוטה";
        }
    });

    safeAttach('transferSynopsisBtn', 'click', () => {
        if (confirm("האם להעביר טיוטה זו לעורך הראשי? התוכן הקיים יוחלף.")) {
            document.getElementById('synopsisArea').value = document.getElementById('synopsisBuilderArea').value;
            alert("הטיוטה הועברה. יש לשמור שינויים בעורך הראשי.");
            closeAllModals();
            openModal(document.getElementById('synopsisModal'));
        }
    });

    // Attach listener for dynamically created buttons
    document.body.addEventListener('click', (e) => {
        if (e.target.classList.contains('discuss-chapter-btn')) {
            openChapterDiscussion(e);
        }
    });
}