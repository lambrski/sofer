// static/js/features/library.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import { getLibraryFiles, uploadLibraryFiles, deleteLibraryFile } from '../api.js';

let allLibraryFiles = []; // Cache library files to avoid refetching

async function loadLibrary() {
    const libraryList = document.getElementById('libraryList');
    libraryList.innerHTML = `<div class='muted'>טוען...</div>`;
    try {
        allLibraryFiles = await getLibraryFiles().then(data => data.items || []);
        renderLibrary();
    } catch (e) {
        libraryList.innerHTML = `<div class='muted'>שגיאה בטעינת הספרייה.</div>`;
        console.error(e);
    }
}

function renderLibrary() {
    const libraryList = document.getElementById('libraryList');
    const query = (document.getElementById('libSearch').value || "").trim().toLowerCase();
    const filteredFiles = allLibraryFiles.filter(it => !query || (it.filename || "").toLowerCase().includes(query));

    if (!filteredFiles.length) {
        libraryList.innerHTML = `<div class='muted'>אין קבצים${query ? ' תואמים לחיפוש' : ''}.</div>`;
        return;
    }

    libraryList.innerHTML = filteredFiles.map(it => `
        <div class="li" data-id="${it.id}">
            <div class="rowflex" style="justify-content:space-between; gap:12px">
                <div>
                    <h4>${esc(it.filename)}</h4>
                    <div class="small">${esc(it.ext)} • ${(it.size / 1024).toFixed(1)}KB • ${new Date(it.uploaded_at).toLocaleString('he-IL')}</div>
                    <div class="rowflex">
                        <a class="linklike" href="${it.url}" target="_blank">פתח</a>
                        <a class="linklike" href="${it.url}" download>הורד</a>
                        <button class="linklike del">מחק</button>
                    </div>
                </div>
            </div>
        </div>`).join("");

    libraryList.querySelectorAll(".del").forEach(btn => {
        btn.addEventListener("click", async (e) => {
            const id = e.target.closest(".li").getAttribute("data-id");
            if (!confirm("למחוק?")) return;
            await deleteLibraryFile(id);
            await loadLibrary(); // Reload and re-render
        });
    });
}

export function initLibrary(pid) {
    // Ensure global array for attached file IDs exists
    window.libraryFileIds = window.libraryFileIds || [];

    safeAttach('libraryBtn', 'click', () => {
        openModal(document.getElementById('libraryModal'));
        loadLibrary();
    });

    safeAttach('closeLibraryBtn', 'click', closeAllModals);
    safeAttach('libSearch', 'input', renderLibrary);
    
    safeAttach('libUpload', 'change', async (e) => {
        if (!e.target.files.length) return;
        const fd = new FormData();
        for (const f of e.target.files) {
            fd.append("files", f);
        }
        await uploadLibraryFiles(fd);
        await loadLibrary();
        e.target.value = "";
    });

    safeAttach('attachFromLibraryBtn', 'click', async () => {
        const modal = document.getElementById('libraryAttachModal');
        const listEl = document.getElementById('libraryAttachList');
        listEl.innerHTML = `<div class='muted'>טוען קבצים...</div>`;
        openModal(modal);

        try {
            if (!allLibraryFiles.length) {
                 allLibraryFiles = await getLibraryFiles().then(data => data.items || []);
            }
            if (!allLibraryFiles.length) {
                listEl.innerHTML = `<div class='muted'>הספרייה ריקה.</div>`;
                return;
            }
            listEl.innerHTML = allLibraryFiles.map(item => `
                <div class="li">
                    <label>
                        <input type="checkbox" value="${item.id}" data-filename="${esc(item.filename)}"> ${esc(item.filename)}
                    </label>
                </div>`).join('');
        } catch (e) {
            listEl.innerHTML = `<div class='muted'>שגיאה בטעינת הספרייה.</div>`;
            console.error(e);
        }
    });

    safeAttach('closeLibraryAttachBtn', 'click', closeAllModals);

    safeAttach('attachSelectedBtn', 'click', () => {
        const attachedFilesList = document.getElementById('attached-files-list');
        document.querySelectorAll('#libraryAttachList input:checked').forEach(checkbox => {
            const fileId = checkbox.value;
            const filename = checkbox.getAttribute('data-filename');
            if (!window.libraryFileIds.includes(fileId)) {
                window.libraryFileIds.push(fileId);
                attachedFilesList.innerHTML += `<span class="pill" data-type="library" data-id="${fileId}">${filename} <button class="remove-pill" data-id="${fileId}">x</button></span>`;
            }
        });

        // Add event listeners to remove pills
        attachedFilesList.querySelectorAll('.remove-pill').forEach(btn => {
            btn.onclick = (e) => {
                const idToRemove = e.target.getAttribute('data-id');
                window.libraryFileIds = window.libraryFileIds.filter(id => id !== idToRemove);
                e.target.parentElement.remove();
            };
        });
        closeAllModals();
    });
}