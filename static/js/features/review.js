// static/js/features/review.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import * as api from '../api.js';

let currentReviewKind = 'general';
const discussionModal = document.getElementById('discussionModal');

async function loadReviewList(pid) {
    const reviewList = document.getElementById('reviewList');
    reviewList.innerHTML = `<div class='muted'>טוען...</div>`;
    try {
        const data = await api.getReviews(pid, currentReviewKind);
        reviewList.innerHTML = !data.items.length ? `<div class='muted'>אין ביקורות קודמות.</div>` :
            data.items.map(it => `
                <div class="li" data-id="${it.id}">
                    <div class="rowflex">
                        <h4 title="${new Date(it.created_at).toLocaleString('he-IL')}">${esc(it.title)}</h4>
                        <button class="linklike show">הצג</button>
                        <button class="linklike discuss">דיון</button>
                        <button class="linklike del">מחק</button>
                    </div>
                    <div class="box body" style="display:none; white-space:pre-wrap;">${esc(it.result || "")}</div>
                </div>`).join("");

        reviewList.querySelectorAll(".li").forEach(li => {
            const id = li.getAttribute("data-id");
            const title = li.querySelector("h4").textContent;
            li.querySelector(".show").addEventListener("click", () => {
                const body = li.querySelector(".body");
                body.style.display = (body.style.display === "none" ? "block" : "none");
            });
            li.querySelector(".del").addEventListener("click", async () => {
                if (confirm("למחוק?")) {
                    await api.deleteReview(pid, id);
                    await loadReviewList(pid);
                }
            });
            li.querySelector(".discuss").addEventListener("click", () => openDiscussionModal(pid, id, title));
        });
    } catch (e) {
        reviewList.innerHTML = `<div class='muted'>שגיאה בטעינה.</div>`;
        console.error(e);
    }
}

async function loadDiscussion(pid, rid) {
    const discussionThread = document.getElementById('discussionThread');
    discussionThread.innerHTML = `<div class='muted'>טוען...</div>`;
    try {
        const data = await api.getReviewDiscussion(pid, rid);
        discussionThread.innerHTML = !data.items.length ? `<div class='muted'>אין הודעות.</div>` :
            data.items.map(m => `
                <div class="li">
                    <div class="meta">${m.role === 'user' ? 'אתה' : 'סופר'} • ${new Date(m.created_at).toLocaleString('he-IL')}</div>
                    <div class="bubble">${esc(m.message)}</div>
                </div>`).join("");
        discussionThread.scrollTop = discussionThread.scrollHeight;
    } catch (e) {
        discussionThread.innerHTML = `<div class='muted'>שגיאה בטעינת הדיון.</div>`;
        console.error(e);
    }
}

function openDiscussionModal(pid, reviewId, reviewTitle) {
    discussionModal.setAttribute('data-review-id', reviewId);
    document.getElementById('discussionTitle').textContent = "דיון בביקורת: " + reviewTitle;
    loadDiscussion(pid, reviewId);
    openModal(discussionModal);
}

function setTab(pid, kind) {
    currentReviewKind = kind;
    document.getElementById('tabGeneral').classList.toggle('active', kind === 'general');
    document.getElementById('tabProof').classList.toggle('active', kind === 'proofread');
    document.getElementById('reviewOut').textContent = '';
    loadReviewList(pid);
}

export function initReview(pid) {
    // Custom event listener to load data only when tab is active
    document.addEventListener('load-reviews', () => loadReviewList(pid));

    safeAttach('tabGeneral', 'click', () => setTab(pid, 'general'));
    safeAttach('tabProof', 'click', () => setTab(pid, 'proofread'));

    safeAttach('closeDiscussionBtn', 'click', closeAllModals);

    safeAttach('askDiscussionBtn', 'click', async () => {
        const rid = discussionModal.getAttribute('data-review-id');
        const input = document.getElementById('discussionInput');
        const q = (input.value || "").trim();
        if (!rid || !q) return;
        
        const btn = document.getElementById('askDiscussionBtn');
        btn.disabled = true;
        try {
            await api.postReviewDiscussion(pid, rid, q);
            input.value = "";
            await loadDiscussion(pid, rid);
        } catch (e) {
            alert("שגיאה");
            console.error(e);
        } finally {
            btn.disabled = false;
            input.focus();
        }
    });

    safeAttach('updateReviewBtn', 'click', async () => {
        const rid = discussionModal.getAttribute('data-review-id');
        if (!rid || !confirm("האם לעדכן את דוח הביקורת המקורי על סמך הדיון?")) return;
        
        const btn = document.getElementById('updateReviewBtn');
        btn.disabled = true;
        btn.textContent = "מעדכן...";
        try {
            await api.updateReviewFromDiscussion(pid, rid);
            alert("דוח הביקורת עודכן!");
            closeAllModals();
            await loadReviewList(pid);
        } catch (e) {
            alert("שגיאה בעדכון הדוח: " + e.message);
            console.error(e);
        } finally {
            btn.disabled = false;
            btn.textContent = "עדכן דוח ביקורת";
        }
    });

    safeAttach('runReviewBtn', 'click', async () => {
        const rvStatus = document.getElementById('rvStatus');
        const reviewOut = document.getElementById('reviewOut');
        const btn = document.getElementById('runReviewBtn');
        rvStatus.innerHTML = "";
        reviewOut.textContent = "";
        
        try {
            let text = document.getElementById('reviewInput').value.trim();
            let source = "pasted";
            if (!text) {
                if (!document.getElementById('rvUseNotesWhenEmpty').checked) return;
                const g = await api.getNotes(pid);
                text = (g.text || "").trim();
                source = "notes";
                if (!text) {
                    alert("הקובץ הכללי ריק.");
                    return;
                }
            }
            rvStatus.innerHTML = `<div class='spinner'></div> <span>מריץ ביקורת... (זה עשוי לקחת זמן)</span>`;
            btn.disabled = true;
            
            const data = await api.runReview(pid, { kind: currentReviewKind, source, input_text: text });
            reviewOut.textContent = data.result || "—";
            await loadReviewList(pid);
            rvStatus.textContent = "הושלם!";
        } catch (e) {
            rvStatus.textContent = "שגיאה";
            alert("שגיאה: " + (e.message || e));
            console.error(e);
        } finally {
            btn.disabled = false;
        }
    });
}