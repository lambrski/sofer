// static/js/features/notes.js
import { openModal, closeAllModals, safeAttach } from '../ui.js';
import { getNotes, saveNotes } from '../api.js';

export function initNotes(pid) {
    const notesArea = document.getElementById('notesArea');
    if (!notesArea) return;

    safeAttach('notesBtn', 'click', async () => {
        openModal(document.getElementById('notesModal'));
        notesArea.value = "טוען...";
        try {
            const data = await getNotes(pid);
            notesArea.value = data.text || "";
        } catch (e) {
            notesArea.value = "שגיאה בטעינת הקובץ.";
            console.error(e);
        }
    });

    safeAttach('closeNotesBtn', 'click', closeAllModals);

    safeAttach('saveNotesBtn', 'click', async () => {
        try {
            await saveNotes(pid, notesArea.value);
            alert("נשמר");
            closeAllModals();
        } catch (e) {
            alert("שגיאה: " + e.message);
            console.error(e);
        }
    });
}