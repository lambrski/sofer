// static/js/features/chat.js
import { openModal, closeAllModals, safeAttach, esc, fmtTime } from '../ui.js';
import { getChatHistory, clearChatHistory, getPromptHistory, clearPromptHistory, uploadTempFiles, askAI } from '../api.js';

let tempFileIds = [], libraryFileIds = []; // Module-level state

function renderAttachedFiles() {
    const listEl = document.getElementById('attached-files-list');
    // This function will need to be enhanced to track filenames along with IDs
    // For now, it's a placeholder for more complex logic if needed.
    // The current implementation in library.js directly manipulates this element.
}

async function loadChat(pid) {
    try {
        const data = await getChatHistory(pid);
        const resultEl = document.getElementById('result');
        resultEl.innerHTML = !data.items.length ? "" : data.items.map(t =>
            `<div class="turn q"><div class="meta"><span>אתה • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.question)}</div></div>
             <div class="turn a"><div class="meta"><span>סופר • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.answer)}<button title="העתק" class="linklike copy-bubble">📋</button></div></div>`
        ).join("");
        
        resultEl.querySelectorAll('.copy-bubble').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const bubble = e.target.closest('.bubble');
                // Clone the node to avoid modifying the original
                const tempDiv = bubble.cloneNode(true);
                // Remove the button from the cloned node before getting text
                const copyBtn = tempDiv.querySelector('.copy-bubble');
                if (copyBtn) copyBtn.remove();
                
                const textToCopy = tempDiv.textContent.trim();
                navigator.clipboard.writeText(textToCopy);
                
                const originalText = e.target.textContent;
                e.target.textContent = '✓';
                setTimeout(() => { e.target.textContent = originalText; }, 1200);
            });
        });

        if (resultEl.children.length > 0) {
            resultEl.scrollTop = resultEl.scrollHeight;
        }
    } catch (e) {
        console.error("Failed to load chat", e);
    }
}

export function initChat(pid) {
    loadChat(pid); // Initial load

    safeAttach('tempFileUpload', 'change', async (e) => {
        const files = e.target.files;
        if (!files.length) return;
        
        const status = document.getElementById('status');
        status.innerHTML = `<div class='spinner'></div> <span>מעלה קבצים...</span>`;
        
        const fd = new FormData();
        for (const file of files) {
            fd.append("files", file);
        }
        
        try {
            const data = await uploadTempFiles(pid, fd);
            tempFileIds.push(...data.file_ids);
            const listEl = document.getElementById('attached-files-list');
            listEl.innerHTML += data.filenames.map(name => `<span class="pill" data-type="temp">${esc(name)}</span>`).join("");
        } catch (err) {
            alert("שגיאה בהעלאת קבצים: " + err.message);
        } finally {
            status.innerHTML = "";
            e.target.value = ""; // Clear file input
        }
    });

    safeAttach('sendBtn', 'click', async () => {
        const promptEl = document.getElementById('prompt');
        const text = promptEl.value.trim();
        // Get libraryFileIds from the global scope (managed by library.js)
        const currentLibraryFileIds = window.libraryFileIds || [];

        if (!text && tempFileIds.length === 0 && currentLibraryFileIds.length === 0) return;
        
        const btn = document.getElementById('sendBtn');
        const status = document.getElementById('status');
        btn.disabled = true;
        status.innerHTML = `<div class='spinner'></div> <span>חושב...</span>`;
        
        try {
            const body = {
                text: text,
                temperature: document.getElementById('temperature').value,
                persona: document.getElementById('personaSelector').value,
                use_notes: document.getElementById('useNotes').checked ? "1" : "0",
                mode: document.querySelector('input[name="mode"]:checked').value,
                write_kind: document.getElementById('writeKind').value,
                use_history: document.getElementById('useHistory').checked ? "1" : "0",
                temp_file_ids: tempFileIds,
                library_file_ids: currentLibraryFileIds
            };
            
            await askAI(pid, body);
            
            await loadChat(pid);
            promptEl.value = "";
            tempFileIds = [];
            window.libraryFileIds = []; // Clear global library file IDs
            document.getElementById('attached-files-list').innerHTML = "";
        } catch (e) {
            alert("שגיאה: " + e.message);
            await loadChat(pid);
        } finally {
            status.innerHTML = "";
            btn.disabled = false;
            promptEl.focus();
        }
    });

    safeAttach('clearChatBtn', 'click', async () => {
        if (confirm("למחוק שיחה?")) {
            await clearChatHistory(pid);
            loadChat(pid);
        }
    });

    safeAttach('historyBtn', 'click', async () => {
        const histContent = document.getElementById('histContent');
        openModal(document.getElementById('histModal'));
        histContent.innerHTML = "<div class='muted'>טוען...</div>";
        const data = await getPromptHistory(pid);
        if (!data.items.length) {
            histContent.innerHTML = "<div class='muted'>אין היסטוריה.</div>";
            return;
        }
        histContent.innerHTML = data.items.map(q => `<div class='li' title='לחץ להעתקה'>${esc(q)}</div>`).join("");
        histContent.querySelectorAll('.li').forEach(el => {
            el.addEventListener("click", () => {
                document.getElementById('prompt').value = el.textContent;
                document.getElementById('prompt').focus();
                closeAllModals();
            });
        });
    });

    safeAttach('closeHistBtn', 'click', closeAllModals);

    safeAttach('clearHistBtn', 'click', async () => {
        if (!confirm("למחוק היסטוריה?")) return;
        await clearPromptHistory(pid);
        document.getElementById('histContent').innerHTML = "<div class='muted'>נמחק.</div>";
    });

    // Share libraryFileIds globally for chat to access
    window.libraryFileIds = window.libraryFileIds || [];
}