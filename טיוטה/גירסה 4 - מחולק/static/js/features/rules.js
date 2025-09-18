// static/js/features/rules.js
import { openModal, closeAllModals, safeAttach, esc } from '../ui.js';
import { getRules, addRule, updateRule, deleteRule } from '../api.js';

async function loadRules(pid) {
    try {
        const data = await getRules(pid);
        
        function ruleRow(r) {
            return `
            <div class="rowflex rule" data-id="${r.id}">
                <textarea style="flex:1; height:56px">${esc(r.text)}</textarea>
                <select>
                    <option value="enforce" ${r.mode === "enforce" ? "selected" : ""}>אכיפה</option>
                    <option value="warn" ${r.mode === "warn" ? "selected" : ""}>אזהרה</option>
                    <option value="off" ${r.mode === "off" ? "selected" : ""}>כבוי</option>
                </select>
                <button class="linklike save">שמור</button>
                <button class="linklike del">מחק</button>
            </div>`;
        }
        
        document.getElementById('rulesGlobal').innerHTML = data.global.map(ruleRow).join("") || "<div class='muted'>אין.</div>";
        document.getElementById('rulesProject').innerHTML = data.project.map(ruleRow).join("") || "<div class='muted'>אין.</div>";

        document.querySelectorAll("#rulesModal .rule").forEach(row => {
            const id = row.getAttribute("data-id");
            row.querySelector(".save").addEventListener("click", async () => {
                const text = row.querySelector("textarea").value;
                const mode = row.querySelector("select").value;
                await updateRule(pid, { id, text, mode });
                alert("נשמר");
            });
            row.querySelector(".del").addEventListener("click", async () => {
                if (confirm("למחוק?")) {
                    await deleteRule(pid, id);
                    await loadRules(pid);
                }
            });
        });
    } catch (e) {
        document.getElementById('rulesContent').innerHTML = "שגיאה בטעינת הכללים.";
        console.error(e);
    }
}

export function initRules(pid) {
    safeAttach('rulesBtn', 'click', () => {
        openModal(document.getElementById('rulesModal'));
        loadRules(pid);
    });

    safeAttach('closeRulesBtn', 'click', closeAllModals);

    safeAttach('addGlobalBtn', 'click', async () => {
        const text = document.getElementById('newGlobalText').value.trim();
        const mode = document.getElementById('newGlobalMode').value;
        if (!text) return;
        await addRule(pid, { scope: 'global', text, mode });
        await loadRules(pid);
        document.getElementById('newGlobalText').value = "";
    });

    safeAttach('addProjectBtn', 'click', async () => {
        const text = document.getElementById('newProjectText').value.trim();
        const mode = document.getElementById('newProjectMode').value;
        if (!text) return;
        await addRule(pid, { scope: 'project', text, mode });
        await loadRules(pid);
        document.getElementById('newProjectText').value = "";
    });
}