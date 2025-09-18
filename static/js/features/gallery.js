// static/js/features/gallery.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import * as api from '../api.js';

let editingImageId = null;

async function loadObjects(pid) {
    const gallery = document.getElementById('object-gallery');
    gallery.innerHTML = `<div class='muted'>טוען...</div>`;
    try {
        const data = await api.getObjects(pid);
        gallery.innerHTML = !data.items.length ? `<div class='muted'>אין אובייקטים.</div>` : 
            data.items.map(obj => `
                <div class="object-card" data-id="${obj.id}">
                    <a href="${obj.reference_image_path}" target="_blank" title="הצג בגודל מלא">
                        <img src="${obj.reference_image_path}" alt="${esc(obj.name)}">
                    </a>
                    <h5>${esc(obj.name)}</h5>
                    <button class="linklike small del-obj">מחק</button>
                </div>`).join("");
        
        gallery.querySelectorAll('.del-obj').forEach(btn => {
            btn.addEventListener("click", async (e) => {
                e.stopPropagation();
                const id = e.target.closest('.object-card').getAttribute('data-id');
                if (confirm("למחוק את האובייקט?")) {
                    await api.deleteObject(pid, id);
                    await loadObjects(pid);
                }
            });
        });
    } catch (e) {
        gallery.innerHTML = `<div class='muted'>שגיאה בטעינת אובייקטים.</div>`;
        console.error(e);
    }
}

async function loadGallery(pid) {
    const gallery = document.getElementById('gallery');
    gallery.innerHTML = "<div class='muted'>טוען...</div>";
    try {
        const data = await api.getImages(pid);
        if (!data.items.length) {
            gallery.innerHTML = "<div class='muted'>אין איורים.</div>";
            return;
        }
        gallery.innerHTML = data.items.map(it => `
            <div class="card" data-id="${it.id}">
                <img src="${it.file_path}">
                <div class="small">${it.style ? esc(it.style) + " • " : ""}${it.scene_label ? esc(it.scene_label) + " • " : ""}${new Date(it.created_at).toLocaleString('he-IL')}</div>
                <div class="small" title="${esc(it.prompt)}">${esc((it.prompt || "").slice(0, 80))}...</div>
                <div class="rowflex">
                    <a class="linklike" href="${it.file_path}" download>הורד</a>
                    <a class="linklike" href="${it.file_path}" target="_blank">פתח</a>
                    <button class="linklike edit-img" data-id="${it.id}" data-prompt="${esc(it.prompt)}">ערוך</button>
                    <button class="linklike delimg">מחק</button>
                </div>
            </div>`).join("");

        gallery.querySelectorAll(".delimg").forEach(btn => {
            btn.addEventListener("click", async () => {
                const id = btn.closest(".card").getAttribute("data-id");
                if (!confirm("למחוק?")) return;
                await api.deleteImage(pid, id);
                await loadGallery(pid);
            });
        });
        
        gallery.querySelectorAll('.edit-img').forEach(btn => {
            btn.addEventListener('click', (e) => {
                editingImageId = e.target.getAttribute('data-id');
                const prompt = e.target.getAttribute('data-prompt');
                document.getElementById('imgDesc').value = prompt;
                document.getElementById('editingIndicator').style.display = 'block';
                document.getElementById('illustratePanel').scrollIntoView({ behavior: 'smooth' });
            });
        });
    } catch (e) {
        gallery.innerHTML = `<div class='muted'>שגיאה בטעינת הגלריה.</div>`;
        console.error(e);
    }
}

function cancelEditMode() {
    editingImageId = null;
    document.getElementById('editingIndicator').style.display = 'none';
}

export function initGallery(pid) {
    // Custom event listener to load data only when tab is active
    document.addEventListener('load-gallery', () => loadGallery(pid));
    
    safeAttach('objectLabBtn', 'click', () => {
        openModal(document.getElementById('objectLabModal'));
        loadObjects(pid);
    });
    
    safeAttach('closeObjectLabBtn', 'click', closeAllModals);

    safeAttach('createObjectBtn', 'click', async () => {
        const name = document.getElementById('objName').value.trim();
        const description = document.getElementById('objDesc').value.trim();
        const style = document.getElementById('objStyle').value.trim();
        if (!name || !description) {
            alert("חובה למלא שם ותיאור לאובייקט.");
            return;
        }
        
        const btn = document.getElementById('createObjectBtn');
        const status = document.getElementById('objStatus');
        btn.disabled = true;
        status.innerHTML = `<div class='spinner'></div> <span>מייצר תמונת ייחוס...</span>`;
        
        try {
            await api.createObject(pid, { name, description, style });
            status.textContent = "נוצר!";
            await loadObjects(pid);
        } catch (e) {
            status.textContent = "שגיאה.";
            alert("שגיאה ביצירת אובייקט: " + e.message);
            console.error(e);
        } finally {
            btn.disabled = false;
        }
    });

    safeAttach('genImageBtn', 'click', async () => {
        const desc = document.getElementById('imgDesc').value.trim();
        if (!desc) return;
        
        const btn = document.getElementById('genImageBtn');
        const status = document.getElementById('imgStatus');
        btn.disabled = true;
        status.innerHTML = `<div class='spinner'></div> <span>מייצר סצנה...</span>`;
        
        try {
            const body = {
                desc: desc,
                style: document.getElementById('imgStyle').value || "",
                scene_label: document.getElementById('imgScene').value || ""
            };
            if (editingImageId) {
                body.source_image_id = editingImageId;
            }
            await api.createImage(pid, body);
            await loadGallery(pid);
            status.innerHTML = "נוצר ✓";
            setTimeout(() => status.innerHTML = "", 2000);
            cancelEditMode();
        } catch (e) {
            alert("שגיאה: " + e.message);
            status.innerHTML = "שגיאה.";
            console.error(e);
        } finally {
            btn.disabled = false;
        }
    });

    safeAttach('cancelEditBtn', 'click', cancelEditMode);
}