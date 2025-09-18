(function(){
  const pid = Number(document.body.getAttribute('data-project-id'));
  const pkind = document.body.getAttribute('data-project-kind');
  let tempFileIds = [], libraryFileIds = [];
  let editingImageId = null;
  let currentChapterDiscussion = { title: "", originalContent: "", thread: [] };
  let currentSynopsisBuilder = { thread: [] };
  let currentDivisionRefinement = { originalDivision: "", thread: [] };
  
  function esc(s){return (s||"").replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
  function fmtTime(iso){ const d=new Date(iso); return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}); }
  const backdrop = document.getElementById('backdrop');
  function openModal(el){ if(el) {el.style.display="block"; backdrop.style.display="block";} }
  function closeAllModals(){ document.querySelectorAll('.modal').forEach(m=>m.style.display="none"); backdrop.style.display="none"; }
  backdrop.addEventListener("click", closeAllModals);
  
  function safeAttach(id, event, handler) {
      const el = document.getElementById(id);
      if (el) { el.addEventListener(event, handler); }
  }

  // --- Main UI Logic ---
  const modeRadios = [...document.getElementsByName('mode')], writeKindEl = document.getElementById('writeKind'), brainstormControls = document.getElementById('brainstormControls');
  function applyModeUI(){
      const mode = modeRadios.find(r=>r.checked).value;
      if (writeKindEl) writeKindEl.style.display = (mode==='write') ? 'inline-block' : 'none';
      if (document.getElementById('chatPanel')) document.getElementById('chatPanel').style.display = (mode==='review' || mode==='illustrate') ? 'none' : 'block';
      if (brainstormControls) brainstormControls.style.display = (mode ==='brainstorm' || mode ==='write') ? 'flex' : 'none';
      if (document.getElementById('reviewPanel')) document.getElementById('reviewPanel').style.display = (mode==='review') ? 'block' : 'none';
      if (document.getElementById('illustratePanel')) document.getElementById('illustratePanel').style.display = (mode==='illustrate') ? 'block' : 'none';
      if (mode==='illustrate') { loadGallery(); }
      if (mode==='review') { loadReviewList(); }
  }
  modeRadios.forEach(r=> r.addEventListener('change', applyModeUI));
  
  // --- Modals & General Buttons ---
  safeAttach('notesBtn', 'click', async () => { openModal(document.getElementById('notesModal')); const notesArea = document.getElementById('notesArea'); notesArea.value = "טוען..."; try { const res = await fetch("/general/"+pid); const data = await res.json(); notesArea.value = data.text || ""; } catch (e) { notesArea.value = "שגיאה בטעינת הקובץ."; } });
  safeAttach('closeNotesBtn', 'click', closeAllModals);
  safeAttach('saveNotesBtn', 'click', async () => { try{ const res = await fetch("/general/"+pid, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ text: document.getElementById('notesArea').value }) }); if (!res.ok) throw new Error('שגיאת שרת'); alert("נשמר"); closeAllModals(); }catch(e){ alert("שגיאה: " + e.message); } });
  
  // --- Synopsis Modal Logic ---
  async function loadSynopsisHistory() {
      const historyEl = document.getElementById('synopsisHistory');
      if (!historyEl) return;
      historyEl.innerHTML = `<div class="muted">טוען היסטוריה...</div>`;
      try {
          const res = await fetch(`/api/project/${pid}/synopsis_history`);
          const data = await res.json();
          if (!data.items || data.items.length === 0) {
              historyEl.innerHTML = `<div class="muted">אין היסטוריית גרסאות.</div>`;
              return;
          }
          historyEl.innerHTML = data.items.map(item => `
              <div class="li">
                  <div class="rowflex" style="justify-content: space-between;">
                      <strong>גרסה מתאריך ${new Date(item.created_at).toLocaleString('he-IL')}</strong>
                      <button class="linklike restore-synopsis-btn">שחזר</button>
                  </div>
                  <div class="box" style="margin-top:4px;">${esc(item.text)}</div>
              </div>
          `).join('');
          historyEl.querySelectorAll('.restore-synopsis-btn').forEach(btn => {
              btn.addEventListener('click', (e) => {
                  const text = e.target.closest('.li').querySelector('.box').textContent;
                  document.getElementById('synopsisArea').value = text;
                  alert('הגרסה שוחזרה לעורך. לחץ "שמור תקציר" כדי לשמור את השינויים.');
              });
          });
      } catch (e) {
          historyEl.innerHTML = `<div class="muted">שגיאה בטעינת ההיסטוריה.</div>`;
      }
  }

  function renderSynopsisCards(synopsisText) {
      const cardView = document.getElementById('synopsisCardView');
      cardView.innerHTML = '<div class="spinner"></div>';
      fetch(`/api/project/${pid}/parse_synopsis`, {
          method: "POST",
          headers: {'Content-Type':'application/x-www-form-urlencoded'},
          body: new URLSearchParams({text: synopsisText})
      }).then(res => res.json()).then(data => {
          if (!data.chapters || data.chapters.length === 0) {
              cardView.innerHTML = `<div class="muted">לא נמצאו פרקים בתקציר. ודא שהכותרות בפורמט 'פרק X:'.</div>`;
              return;
          }
          cardView.innerHTML = data.chapters.map(chap => `
              <div class="chapter-card">
                  <h5>${esc(chap.title)}</h5>
                  <div class="small muted" style="white-space: pre-wrap;">${esc(chap.content)}</div>
                  <div class="btnrow">
                    <button class="linklike write-chapter-btn" data-content="${esc(chap.content)}" data-chapter-title="${esc(chap.title)}">✍️ כתוב את הפרק</button>
                    <button class="linklike discuss-chapter-btn" data-content="${esc(chap.content)}" data-chapter-title="${esc(chap.title)}">💬 דיון</button>
                  </div>
              </div>
          `).join('');
          cardView.querySelectorAll('.write-chapter-btn').forEach(btn => btn.addEventListener('click', writeChapterFromCard));
          cardView.querySelectorAll('.discuss-chapter-btn').forEach(btn => btn.addEventListener('click', openChapterDiscussion));
      });
  }

  function cleanAIResponse(text) { return text.trim(); }

  async function writeChapterFromCard(e) {
      const button = e.target;
      const originalButtonText = button.innerHTML;
      
      const chapterContent = button.getAttribute('data-content');
      const chapterTitle = button.getAttribute('data-chapter-title');
      
      if (!confirm(`האם לכתוב את הפרק: "${chapterTitle}"?`)) return;
      
      button.disabled = true;
      button.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px; display:inline-block; margin-left:4px;"></div> <span>כותב...</span>`;

      try {
          const body = new URLSearchParams({ 
              text: chapterTitle,
              mode: 'write', 
              write_kind: 'breakdown_chapter',
              use_notes: '1', 
              use_history: '0'
          });
          const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
          if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
          const data = await res.json();
          
          const chapterModal = document.getElementById('chapterOutputModal');
          document.getElementById('chapterOutputTitle').textContent = `תוצר: ${chapterTitle}`;
          document.getElementById('chapterOutputContent').innerHTML = esc(data.answer).replace(/\n/g, '<br>');
          openModal(chapterModal);
      } catch (err) {
          alert("שגיאה בכתיבת הפרק: " + err.message);
      } finally {
          button.disabled = false;
          button.innerHTML = originalButtonText;
      }
  }

  const synopsisBtn = document.getElementById('synopsisBtn');
  if(synopsisBtn) {
    synopsisBtn.addEventListener("click", async () => { 
      openModal(document.getElementById('synopsisModal')); 
      const synopsisArea = document.getElementById('synopsisArea'); 
      synopsisArea.value = "טוען..."; 
      try { 
        const res = await fetch("/project/"+pid+"/synopsis"); 
        const data = await res.json(); 
        synopsisArea.value = data.text || ""; 
        await loadSynopsisHistory();
      } catch(e) { 
        synopsisArea.value = "שגיאה בטעינת התקציר."; 
      } 
    });
    safeAttach('closeSynopsisBtn', 'click', closeAllModals);
    safeAttach('saveSynopsisBtn', 'click', async () => { 
      try{ 
        const res = await fetch("/project/"+pid+"/synopsis", {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ text: document.getElementById('synopsisArea').value }) }); 
        if (!res.ok) throw new Error('שגיאת שרת'); 
        alert("נשמר");
        await loadSynopsisHistory();
      } catch(e) { 
        alert("שגיאה: " + e.message); 
      } 
    });
    safeAttach('synopsisToggleViewBtn', 'click', (e) => {
      const editorView = document.getElementById('synopsisEditorView');
      const cardView = document.getElementById('synopsisCardView');
      const divideBtn = document.getElementById('divideSynopsisBtn');
      const clearHistoryBtn = document.getElementById('clearSynopsisHistoryBtn');

      if (editorView.style.display !== 'none') {
        editorView.style.display = 'none';
        cardView.style.display = 'block';
        divideBtn.style.display = 'none';
        clearHistoryBtn.style.display = 'none';
        e.target.textContent = 'הצג עורך טקסט';
        renderSynopsisCards(document.getElementById('synopsisArea').value);
      } else {
        editorView.style.display = 'block';
        cardView.style.display = 'none';
        divideBtn.style.display = 'inline-block';
        clearHistoryBtn.style.display = 'inline-block';
        e.target.textContent = 'הצג כרטיסיות פרקים';
      }
    });
  }

  // --- Division Modal Logic ---
  safeAttach('divideSynopsisBtn', 'click', async () => {
    const synopsisArea = document.getElementById('synopsisArea');
    const currentSynopsis = synopsisArea.value;
    if (!currentSynopsis.trim()) { alert("לא ניתן לחלק תקציר ריק."); return; }
    
    const btn = document.getElementById('divideSynopsisBtn');
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner"></div>`;

    try {
        const body = new URLSearchParams({ 
            mode: 'write', 
            write_kind: 'divide_synopsis', 
            synopsis_text_content: currentSynopsis 
        });

        if (pkind === 'פרוזה') {
            body.append('words_per_chapter_min', document.getElementById('prose_min_words').value);
            body.append('words_per_chapter_max', document.getElementById('prose_max_words').value);
        }

        const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
        const data = await res.json();
        if (!res.ok) { throw new Error(data.answer || 'שגיאת שרת'); }
        
        document.getElementById('divisionResultArea').value = data.answer || "לא התקבלה תשובה מהמודל.";
        openModal(document.getElementById('divisionModal'));
        
    } catch(e) {
        alert(`אירעה שגיאה בחלוקת התקציר: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = "חלק תקציר לפרקים";
    }
  });

  safeAttach('acceptDivisionBtn', 'click', () => {
      const newSynopsis = document.getElementById('divisionResultArea').value;
      document.getElementById('synopsisArea').value = newSynopsis;
      document.getElementById('divisionModal').style.display = 'none';
      alert("החלוקה אושרה והועתקה לעורך. כעת עליך ללחוץ על 'שמור תקציר' כדי לשמור את השינויים.");
  });
  
  safeAttach('closeDivisionModalBtn', 'click', closeAllModals);

  safeAttach('clearSynopsisHistoryBtn', 'click', async () => {
    if (!confirm("האם למחוק את כל היסטוריית הגרסאות?")) return;
    try {
        const res = await fetch(`/api/project/${pid}/synopsis_history/clear`, { method: "POST" });
        if (!res.ok) throw new Error("Server error");
        await loadSynopsisHistory();
        alert("היסטוריית התקציר נמחקה.");
    } catch (e) {
        alert("שגיאה במחיקת ההיסטוריה.");
    }
  });
  
  safeAttach('closeChapterOutputBtn', 'click', () => {
      document.getElementById('chapterOutputModal').style.display = 'none';
  });
  
  safeAttach('editChapterBtn', 'click', (e) => {
    const contentDiv = document.getElementById('chapterOutputContent');
    const saveBtn = document.getElementById('saveChapterEditsBtn');
    const editor = document.createElement('textarea');
    editor.style.width = '100%';
    editor.style.minHeight = '50vh';
    editor.style.fontSize = '15px';
    editor.value = contentDiv.innerHTML.replace(/<br\s*[\/]?>/gi, "\n");
    contentDiv.innerHTML = '';
    contentDiv.appendChild(editor);
    editor.focus();
    e.target.style.display = 'none';
    saveBtn.style.display = 'inline-block';
  });
  
  safeAttach('saveChapterEditsBtn', 'click', (e) => {
    const contentDiv = document.getElementById('chapterOutputContent');
    const editBtn = document.getElementById('editChapterBtn');
    const editor = contentDiv.querySelector('textarea');
    contentDiv.innerHTML = esc(editor.value).replace(/\n/g, '<br>');
    e.target.style.display = 'none';
    editBtn.style.display = 'inline-block';
  });

  safeAttach('appendChapterBtn', 'click', async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = 'מוסיף...';
    try {
      const contentDiv = document.getElementById('chapterOutputContent');
      const editor = contentDiv.querySelector('textarea');
      const chapterText = editor ? editor.value : contentDiv.innerHTML.replace(/<br\s*[\/]?>/gi, "\n");
      
      const res = await fetch("/general/"+pid);
      if (!res.ok) throw new Error('Failed to fetch general notes.');
      const data = await res.json();
      const newNotes = (data.text || "") + "\n\n---\n\n" + chapterText;
      
      const saveRes = await fetch("/general/"+pid, {
        method:"POST", 
        headers:{'Content-Type':'application/x-www-form-urlencoded'}, 
        body: new URLSearchParams({ text: newNotes })
      });
      if (!saveRes.ok) throw new Error('Failed to save updated notes.');
      alert("הפרק נוסף בהצלחה לקובץ הכללי!");
      document.getElementById('chapterOutputModal').style.display = 'none';
    } catch (err) {
      alert("שגיאה: " + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'הוסף לקובץ כללי Append ➡️';
    }
  });

  safeAttach('historyBtn', 'click', async () => { const histContent = document.getElementById('histContent'); openModal(document.getElementById('histModal')); histContent.innerHTML = "<div class='muted'>טוען...</div>"; const res = await fetch("/history/"+pid); const data = await res.json(); if (!data.items.length) { histContent.innerHTML = "<div class='muted'>אין היסטוריה.</div>"; return; } histContent.innerHTML = data.items.map(q => `<div class='li' title='לחץ להעתקה'>${esc(q)}</div>`).join(""); [...histContent.querySelectorAll('.li')].forEach(el=>{ el.addEventListener("click", ()=>{ document.getElementById('prompt').value = el.textContent; document.getElementById('prompt').focus(); closeAllModals(); }); }); });
  safeAttach('closeHistBtn', 'click', closeAllModals);
  safeAttach('clearHistBtn', 'click', async ()=>{ if (!confirm("למחוק היסטוריה?")) return; await fetch("/history/"+pid+"/clear", {method:"POST"}); document.getElementById('histContent').innerHTML = "<div class='muted'>נמחק.</div>"; });
  
  safeAttach('rulesBtn', 'click', async ()=>{ openModal(document.getElementById('rulesModal')); await loadRules(); });
  safeAttach('closeRulesBtn', 'click', closeAllModals);
  async function loadRules(){
      try {
        const res = await fetch("/rules/"+pid); const data = await res.json();
        function ruleRow(r){return `<div class="rowflex rule" data-id="${r.id}"><textarea style="flex:1; height:56px">${esc(r.text)}</textarea><select><option value="enforce" ${r.mode==="enforce"?"selected":""}>אכיפה</option><option value="warn" ${r.mode==="warn"?"selected":""}>אזהרה</option><option value="off" ${r.mode==="off"?"selected":""}>כבוי</option></select><button class="linklike save">שמור</button><button class="linklike del">מחק</button></div>`;}
        document.getElementById('rulesGlobal').innerHTML = data.global.map(ruleRow).join("") || "<div class='muted'>אין.</div>";
        document.getElementById('rulesProject').innerHTML = data.project.map(ruleRow).join("") || "<div class='muted'>אין.</div>";
        [...document.querySelectorAll("#rulesModal .rule")].forEach(row=>{
            const id = row.getAttribute("data-id");
            row.querySelector(".save").addEventListener("click", async ()=>{ const text = row.querySelector("textarea").value, mode = row.querySelector("select").value; await fetch(`/rules/${pid}/update`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id, text, mode })}); alert("נשמר"); });
            row.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/rules/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadRules();} });
        });
      } catch (e) { document.getElementById('rulesContent').innerHTML = "שגיאה בטעינת הכללים."; }
  }
  safeAttach('addGlobalBtn', 'click', async () => { const text = document.getElementById('newGlobalText').value, mode = document.getElementById('newGlobalMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'global', text, mode})}); await loadRules(); document.getElementById('newGlobalText').value = ""; });
  safeAttach('addProjectBtn', 'click', async () => { const text = document.getElementById('newProjectText').value, mode = document.getElementById('newProjectMode').value; if(!text.trim()) return; await fetch(`/rules/${pid}/add`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({scope:'project', text, mode})}); await loadRules(); document.getElementById('newProjectText').value = ""; });
  
  // --- Chat Panel ---
  const promptEl = document.getElementById('prompt');
  const tempSlider = document.getElementById('temperature');
  const tempValue = document.getElementById('tempValue');
  if (tempSlider) tempSlider.addEventListener('input', () => { tempValue.textContent = tempSlider.value; });
  async function loadChat(){
      try {
          const res = await fetch("/chat/"+pid);
          const data = await res.json();
          const resultEl = document.getElementById('result');
          resultEl.innerHTML = !data.items.length ? "" : data.items.map(t =>  
              `<div class="turn q"><div class="meta"><span>אתה • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.question)}</div></div>
               <div class="turn a"><div class="meta"><span>סופר • ${fmtTime(t.created_at)}</span></div><div class="bubble">${esc(t.answer)}<button title="העתק" class="linklike copy-bubble">📋</button></div></div>`
          ).join("");
          resultEl.querySelectorAll('.copy-bubble').forEach(btn => {
              btn.addEventListener('click', (e) => {
                  const bubble = e.target.closest('.bubble');
                  const tempDiv = document.createElement('div');
                  tempDiv.innerHTML = bubble.innerHTML;
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
            resultEl.children[resultEl.children.length-1].scrollIntoView();
          }
      } catch(e) { console.error("Failed to load chat", e); }
  }
  safeAttach('tempFileUpload', 'change', async (e) => {
      const files = e.target.files;
      if (!files.length) return;
      const status = document.getElementById('status');
      status.innerHTML = `<div class="spinner"></div> <span>מעלה קבצים...</span>`;
      const fd = new FormData();
      for (const file of files) { fd.append("files", file); }
      try {
          const res = await fetch(`/upload_temp_files/${pid}`, { method: "POST", body: fd });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error);
          tempFileIds.push(...data.file_ids);
          const listEl = document.getElementById('attached-files-list');
          listEl.innerHTML += data.filenames.map(name => `<span class="pill" data-type="temp">${esc(name)}</span>`).join("");
      } catch(err) { alert("שגיאה בהעלאת קבצים: " + err.message); }
      finally { status.innerHTML = ""; e.target.value = ""; }
  });
  safeAttach('sendBtn', 'click', async () => {
    const text = promptEl.value.trim();
    if (!text && tempFileIds.length === 0 && libraryFileIds.length === 0) return;
    const btn = document.getElementById('sendBtn'), status = document.getElementById('status');
    btn.disabled = true;
    status.innerHTML = `<div class="spinner"></div> <span>חושב...</span>`;
    try {
        const body = new URLSearchParams({ text: text, temperature: tempSlider.value, persona: document.getElementById('personaSelector').value, use_notes: document.getElementById('useNotes').checked ? "1" : "0", mode: modeRadios.find(r=>r.checked).value, write_kind: writeKindEl.value, use_history: document.getElementById('useHistory').checked ? "1" : "0" });
        tempFileIds.forEach(id => body.append("temp_file_ids", id));
        libraryFileIds.forEach(id => body.append("library_file_ids", id));
        const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
        if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
        await loadChat();
        promptEl.value = "";
        tempFileIds = [];
        libraryFileIds = [];
        document.getElementById('attached-files-list').innerHTML = "";
    } catch(e) { alert("שגיאה: " + e.message); await loadChat(); }
    finally { status.innerHTML = ""; btn.disabled = false; promptEl.focus(); }
  });
  safeAttach('clearChatBtn', 'click', async ()=>{ if (confirm("למחוק שיחה?")) { await fetch("/chat/"+pid+"/clear", {method:"POST"}); loadChat(); } });

  // --- Review Panel Logic --
  safeAttach('tabGeneral', 'click', ()=>setTab('general'));
  safeAttach('tabProof', 'click', ()=>setTab('proofread'));
  let currentReviewKind = 'general';
  function setTab(kind){ currentReviewKind = kind; document.getElementById('tabGeneral').classList.toggle('active', kind==='general'); document.getElementById('tabProof').classList.toggle('active', kind==='proofread'); loadReviewList(); document.getElementById('reviewOut').textContent = ''; }
  const discussionModal = document.getElementById('discussionModal');
  safeAttach('closeDiscussionBtn', 'click', closeAllModals);
  async function openDiscussionModal(reviewId, reviewTitle) {
      discussionModal.setAttribute('data-review-id', reviewId);
      document.getElementById('discussionTitle').textContent = "דיון בביקורת: " + reviewTitle;
      await loadDiscussion(reviewId);
      openModal(discussionModal);
  }
  async function loadDiscussion(rid){
      const discussionThread = document.getElementById('discussionThread');
      discussionThread.innerHTML = `<div class="muted">טוען...</div>`;
      try {
          const res = await fetch(`/review/${pid}/discussion/${rid}`);
          const data = await res.json();
          discussionThread.innerHTML = !data.items.length ? "<div class='muted'>אין הודעות.</div>" : data.items.map(m=>`<div class="li"><div class="meta">${m.role==='user'?'אתה':'סופר'} • ${new Date(m.created_at).toLocaleString()}</div><div class="bubble">${esc(m.message)}</div></div>`).join("");
          discussionThread.scrollTop = discussionThread.scrollHeight;
      } catch(e) { discussionThread.innerHTML = "<div class='muted'>שגיאה בטעינת הדיון.</div>"; }
  }
  safeAttach('askDiscussionBtn', 'click', async () => {
      const rid = discussionModal.getAttribute('data-review-id'), input = document.getElementById('discussionInput'), q = (input.value||"").trim();
      if (!rid || !q) return;
      const btn = document.getElementById('askDiscussionBtn');
      btn.disabled = true;
      try{
          await fetch(`/review/${pid}/discuss`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({ review_id: rid, question: q })});
          input.value = "";
          await loadDiscussion(rid);
      } catch(e){alert("שגיאה");} finally{ btn.disabled=false; input.focus(); }
  });
  safeAttach('updateReviewBtn', 'click', async () => {
      const rid = discussionModal.getAttribute('data-review-id');
      if (!rid || !confirm("האם לעדכן את דוח הביקורת המקורי על סמך הדיון?")) return;
      const btn = document.getElementById('updateReviewBtn');
      btn.disabled = true; btn.textContent = "מעדכן...";
      try {
          const res = await fetch(`/review/${pid}/update_from_discussion`, {method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({review_id: rid})});
          if (!res.ok) throw new Error("Failed to update review.");
          alert("דוח הביקורת עודכן!");
          closeAllModals();
          await loadReviewList();
      } catch (e) { alert("שגיאה בעדכון הדוח: " + e.message); }
      finally { btn.disabled = false; btn.textContent = "עדכן דוח ביקורת"; }
  });
  async function loadReviewList(){
      const reviewList = document.getElementById('reviewList');
      reviewList.innerHTML = `<div class="muted">טוען...</div>`;
      const res = await fetch(`/reviews/${pid}?kind=${currentReviewKind}`);
      const data = await res.json();
      reviewList.innerHTML = !data.items.length ? "<div class='muted'>אין ביקורות קודמות.</div>" : data.items.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex"><h4 title="${new Date(it.created_at).toLocaleString()}">${esc(it.title)}</h4><button class="linklike show">הצג</button><button class="linklike discuss">דיון</button><button class="linklike del">מחק</button></div><div class="box body" style="display:none; white-space:pre-wrap;">${esc(it.result||"")}</div></div>`).join("");
      [...reviewList.querySelectorAll(".li")].forEach(li=>{
          const id = li.getAttribute("data-id"), title = li.querySelector("h4").textContent;
          li.querySelector(".show").addEventListener("click", ()=>{ const body = li.querySelector(".body"); body.style.display = (body.style.display==="none" ? "block" : "none"); });
          li.querySelector(".del").addEventListener("click", async ()=>{ if(confirm("למחוק?")){ await fetch(`/reviews/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadReviewList();} });
          li.querySelector(".discuss").addEventListener("click", ()=> openDiscussionModal(id, title));
      });
  }
  safeAttach('runReviewBtn', 'click', async () => {
      const rvStatus = document.getElementById('rvStatus'), reviewOut = document.getElementById('reviewOut'), btn = document.getElementById('runReviewBtn');
      rvStatus.innerHTML = ""; reviewOut.textContent = "";
      try{
          let text = document.getElementById('reviewInput').value.trim();
          let source = "pasted";
          if (!text){
              if (!document.getElementById('rvUseNotesWhenEmpty').checked) return;
              const g = await (await fetch("/general/"+pid)).json();
              text = (g.text||"").trim();
              source = "notes";
              if (!text) { alert("הקובץ הכללי ריק."); return; }
          }
          rvStatus.innerHTML = `<div class="spinner"></div> <span>מריץ ביקורת... (זה עשוי לקחת זמן)</span>`;
          btn.disabled = true;
          const res = await fetch(`/review/${pid}/run`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ kind: currentReviewKind, source, input_text: text }) });
          const data = await res.json();
          if (!res.ok) { throw new Error(data.error || "שגיאה לא ידועה מהשרת"); }
          reviewOut.textContent = data.result || "—";
          await loadReviewList();
          rvStatus.textContent = "הושלם!";
      } catch(e) { rvStatus.textContent = "שגיאה"; alert("שגיאה: "+(e.message||e)); }
      finally { btn.disabled = false; }
  });

  // -- Illustration & Object Lab Logic --
  safeAttach('objectLabBtn', 'click', async () => { openModal(document.getElementById('objectLabModal')); await loadObjects(); });
  safeAttach('closeObjectLabBtn', 'click', closeAllModals);
  async function loadObjects() {
      const gallery = document.getElementById('object-gallery');
      gallery.innerHTML = `<div class="muted">טוען...</div>`;
      try {
          const res = await fetch(`/project/${pid}/objects/list`);
          if (!res.ok) throw new Error("Server responded with an error");
          const data = await res.json();
          gallery.innerHTML = !data.items.length ? "<div class='muted'>אין אובייקטים.</div>" : data.items.map(obj => `
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
                      await fetch(`/project/${pid}/objects/delete`, {method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({object_id: id})});
                      await loadObjects();
                  }
              });
          });
      } catch (e) { 
          console.error("Error in loadObjects:", e);
          gallery.innerHTML = `<div class="muted">שגיאה בטעינת אובייקטים.</div>`; 
      }
  }
  safeAttach('createObjectBtn', 'click', async () => {
      const name = document.getElementById('objName').value.trim();
      const desc = document.getElementById('objDesc').value.trim();
      const style = document.getElementById('objStyle').value.trim();
      if (!name || !desc) { alert("חובה למלא שם ותיאור לאובייקט."); return; }
      const btn = document.getElementById('createObjectBtn'), status = document.getElementById('objStatus');
      btn.disabled = true;
      status.innerHTML = `<div class="spinner"></div> <span>מייצר תמונת ייחוס...</span>`;
      try {
          const res = await fetch(`/project/${pid}/objects/create`, { method: "POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({name, description: desc, style}) });
          if (!res.ok) { const data = await res.json(); throw new Error(data.error || "שגיאת שרת"); }
          status.textContent = "נוצר!";
          await loadObjects();
      } catch (e) { 
          status.textContent = "שגיאה."; 
          alert("שגיאה ביצירת אובייקט: " + e.message); 
      } finally { 
          btn.disabled = false; 
      }
  });
  safeAttach('genImageBtn', 'click', async () => {
      const desc = document.getElementById('imgDesc').value.trim();
      if (!desc) return;
      const btn = document.getElementById('genImageBtn'), status = document.getElementById('imgStatus');
      btn.disabled = true;
      status.innerHTML = `<div class="spinner"></div> <span>מייצר סצנה...</span>`;
      try{
          const body = new URLSearchParams({ desc, style: document.getElementById('imgStyle').value || "", scene_label: document.getElementById('imgScene').value || "" });
          if (editingImageId) {
              body.append('source_image_id', editingImageId);
          }
          const res = await fetch(`/image/${pid}`, { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
          if (!res.ok) { const err = await res.json(); throw new Error(err.error || "שגיאה לא ידועה מהשרת"); }
          await loadGallery();
          status.innerHTML = "נוצר ✓";
          setTimeout(()=> status.innerHTML ="", 2000);
          cancelEditMode();
      } catch(e) { 
          alert("שגיאה: " + e.message); 
          status.innerHTML = "שגיאה."; 
      } finally { 
          btn.disabled = false; 
      }
  });
  function cancelEditMode() {
      editingImageId = null;
      document.getElementById('editingIndicator').style.display = 'none';
  }
  safeAttach('cancelEditBtn', 'click', cancelEditMode);

  async function loadGallery(){
      const gallery = document.getElementById('gallery');
      gallery.innerHTML = "<div class='muted'>טוען...</div>";
      try {
        const res = await fetch("/images/"+pid);
        if (!res.ok) throw new Error("Server responded with an error");
        const data = await res.json();
        if (!data.items.length){ gallery.innerHTML = "<div class='muted'>אין איורים.</div>"; return; }
        gallery.innerHTML = data.items.map(it => `<div class="card" data-id="${it.id}">
          <img src="${it.file_path}">
          <div class="small">${it.style?esc(it.style)+" • ":""}${it.scene_label?esc(it.scene_label)+" • ":""}${new Date(it.created_at).toLocaleString()}</div>
          <div class="small" title="${esc(it.prompt)}">${esc((it.prompt||"").slice(0,80))}...</div>
          <div class="rowflex">
              <a class="linklike" href="${it.file_path}" download>הורד</a>
              <a class="linklike" href="${it.file_path}" target="_blank">פתח</a>
              <button class="linklike edit-img" data-id="${it.id}" data-prompt="${esc(it.prompt)}">ערוך</button>
              <button class="linklike delimg">מחק</button>
          </div>
        </div>`).join("");

        gallery.querySelectorAll(".delimg").forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".card").getAttribute("data-id"); if (!confirm("למחוק?")) return; await fetch(`/images/${pid}/delete`, {method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({id})}); await loadGallery(); }); });
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
          console.error("Error in loadGallery:", e);
          gallery.innerHTML = `<div class="muted">שגיאה בטעינת הגלריה.</div>`;
      }
  }

  // --- Library Modal & Attachment Logic ---
  safeAttach('libraryBtn', 'click', async ()=>{ openModal(document.getElementById('libraryModal')); await loadLibrary(); });
  safeAttach('closeLibraryBtn', 'click', closeAllModals);
  safeAttach('attachFromLibraryBtn', 'click', async () => {
      const modal = document.getElementById('libraryAttachModal');
      const listEl = document.getElementById('libraryAttachList');
      listEl.innerHTML = `<div class="muted">טוען קבצים מהספרייה...</div>`;
      openModal(modal);
      try {
        const res = await fetch('/api/library/list');
        const data = await res.json();
        if (!data.items.length) {
            listEl.innerHTML = `<div class="muted">הספרייה ריקה.</div>`;
            return;
        }
        listEl.innerHTML = data.items.map(item => `<div class="li"><label><input type="checkbox" value="${item.id}" data-filename="${esc(item.filename)}"> ${esc(item.filename)}</label></div>`).join('');
      } catch(e) { listEl.innerHTML = `<div class="muted">שגיאה בטעינת הספרייה.</div>`; }
  });
  safeAttach('closeLibraryAttachBtn', 'click', closeAllModals);
  safeAttach('attachSelectedBtn', 'click', () => {
      const attachedFilesList = document.getElementById('attached-files-list');
      document.querySelectorAll('#libraryAttachList input:checked').forEach(checkbox => {
          const fileId = checkbox.value;
          const filename = checkbox.getAttribute('data-filename');
          if (!libraryFileIds.includes(fileId)) {
              libraryFileIds.push(fileId);
              attachedFilesList.innerHTML += `<span class="pill" data-type="library" data-id="${fileId}">${filename}</span>`;
          }
      });
      closeAllModals();
  });
  async function loadLibrary(){
      const libraryList = document.getElementById('libraryList');
      libraryList.innerHTML = `<div class="muted">טוען...</div>`;
      try {
          function renderLibrary(items){
              const q = (document.getElementById('libSearch').value||"").trim().toLowerCase();
              const rows = items.filter(it => !q || (it.filename||"").toLowerCase().includes(q));
              if (!rows.length){ libraryList.innerHTML = "<div class='muted'>אין קבצים.</div>"; return; }
              libraryList.innerHTML = rows.map(it => `<div class="li" data-id="${it.id}"><div class="rowflex" style="justify-content:space-between; gap:12px"><div><h4>${esc(it.filename)}</h4><div class="small">${esc(it.ext)} • ${(it.size/1024).toFixed(1)}KB • ${new Date(it.uploaded_at).toLocaleString()}</div><div class="rowflex"><a class="linklike" href="${it.url}" target="_blank">פתח</a><a class="linklike" href="${it.url}" download>הורד</a><button class="linklike del">מחק</button></div></div></div></div>`).join("");
              [...libraryList.querySelectorAll(".del")].forEach(btn=>{ btn.addEventListener("click", async ()=>{ const id = btn.closest(".li").getAttribute("data-id"); if(!confirm("למחוק?")) return; await fetch("/api/library/delete", { method:"POST", headers:{'Content-Type':'application/x-www-form-urlencoded'}, body: new URLSearchParams({ id })}); await loadLibrary(); }); });
          }
          const res = await fetch("/api/library/list");
          if (!res.ok) throw new Error("Network response was not ok.");
          const data = await res.json();
          renderLibrary(data.items||[]);
          document.getElementById('libSearch').oninput = () => renderLibrary(data.items||[]);
          document.getElementById('libUpload').onchange = async (e)=>{ if (!e.target.files.length) return; const fd = new FormData(); for (const f of e.target.files) fd.append("files", f); await fetch("/api/library/upload", { method:"POST", body: fd }); await loadLibrary(); e.target.value = ""; };
      } catch (e) {
          libraryList.innerHTML = `<div class="muted">שגיאה בטעינת הספרייה.</div>`;
      }
  }

  // --- New Chapter Discussion Logic ---
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

  safeAttach('closeChapterDiscussionBtn', 'click', () => {
      document.getElementById('chapterDiscussionModal').style.display = 'none';
  });

  safeAttach('discussTemp', 'input', (e) => {
    document.getElementById('discussTempValue').textContent = e.target.value;
  });

  safeAttach('sendChapterDiscussionBtn', 'click', async () => {
    const input = document.getElementById('chapterDiscussionInput');
    const question = input.value.trim();
    if (!question) return;

    const btn = document.getElementById('sendChapterDiscussionBtn');
    const tempSlider = document.getElementById('discussTemp');
    const personaSelector = document.getElementById('discussPersona');
    const threadEl = document.getElementById('chapterDiscussionThread');
    const originalText = btn.textContent;

    if(currentChapterDiscussion.thread.length === 0) { threadEl.innerHTML = ""; }
    threadEl.innerHTML += `<div class="turn q"><div class="bubble">${esc(question)}</div></div>`;
    threadEl.scrollTop = threadEl.scrollHeight;
    currentChapterDiscussion.thread.push({role: 'user', content: question});
    input.value = "";
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;

    try {
        const body = new URLSearchParams({ 
            text: question,
            full_synopsis: document.getElementById('synopsisArea').value,
            chapter_content: currentChapterDiscussion.originalContent,
            discussion_thread: JSON.stringify(currentChapterDiscussion.thread),
            temperature: tempSlider.value,
            persona: personaSelector.value,
            mode: 'brainstorm',
            write_kind: 'chat',
            use_notes: '0',
            use_history: '0'
        });

        const res = await fetch("/ask/"+pid, { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
        if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
        const data = await res.json();
        
        threadEl.innerHTML += `<div class="turn a"><div class="bubble">${esc(data.answer)}</div></div>`;
        currentChapterDiscussion.thread.push({role: 'assistant', content: data.answer});
        threadEl.scrollTop = threadEl.scrollHeight;

    } catch (err) {
        threadEl.innerHTML += `<div class="turn a"><div class="bubble" style="color:red;">שגיאה: ${esc(err.message)}</div></div>`;
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
  });

  safeAttach('summarizeChapterBtn', 'click', async () => {
    if(currentChapterDiscussion.thread.length === 0) {
        alert("לא ניתן לסכם דיון ריק.");
        return;
    }
    const btn = document.getElementById('summarizeChapterBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;

    try {
        const body = new URLSearchParams({
            original_content: currentChapterDiscussion.originalContent,
            discussion_thread: JSON.stringify(currentChapterDiscussion.thread),
            full_synopsis: document.getElementById('synopsisArea').value
        });

        const res = await fetch(`/api/project/${pid}/summarize_chapter_discussion`, { method: "POST", body });
        const data = await res.json();
        if(!res.ok) throw new Error(data.error || "שגיאת שרת");

        const newContent = data.updated_content;
        if (confirm(`המודל מציע את העדכון הבא לפרק. האם להעתיק אותו לעורך הראשי?\n\n---\n${newContent}`)) {
            const mainSynopsis = document.getElementById('synopsisArea');
            mainSynopsis.value = mainSynopsis.value.replace(currentChapterDiscussion.originalContent, newContent);
            
            renderSynopsisCards(mainSynopsis.value);
            document.getElementById('synopsisEditorView').style.display = 'none';
            document.getElementById('synopsisCardView').style.display = 'block';
            document.getElementById('synopsisToggleViewBtn').textContent = 'הצג עורך טקסט';

            document.getElementById('chapterDiscussionModal').style.display = 'none';
            alert("כרטיסיית הפרק עודכנה, והשינוי הועתק לעורך הראשי. לחץ 'שמור תקציר' כדי לשמור את השינויים.");
        }

    } catch(err) {
        alert("שגיאה בסיכום: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
  });
  
  // --- New Synopsis Builder Logic ---
  safeAttach('synopsisBuilderBtn', 'click', async () => {
    const builderArea = document.getElementById('synopsisBuilderArea');
    const builderThread = document.getElementById('synopsisBuilderThread');
    
    try {
        const res = await fetch(`/api/project/${pid}/load_draft`);
        const data = await res.json();
        if (!res.ok) throw new Error("Could not load draft.");
        
        builderArea.value = data.draft_text || document.getElementById('synopsisArea').value;
        currentSynopsisBuilder.thread = data.discussion || [];
        
        if (currentSynopsisBuilder.thread.length > 0) {
            builderThread.innerHTML = currentSynopsisBuilder.thread.map(t => 
                `<div class="turn ${t.role === 'user' ? 'q' : 'a'}"><div class="bubble">${esc(t.content)}</div></div>`
            ).join('');
        } else {
            builderThread.innerHTML = '<div class="muted">התחל שיחה כדי לבנות את התקציר...</div>';
        }

    } catch(e) {
        console.error("Could not load draft, starting fresh.", e);
        builderArea.value = document.getElementById('synopsisArea').value;
        currentSynopsisBuilder.thread = [];
        builderThread.innerHTML = '<div class="muted">התחל שיחה כדי לבנות את התקציר...</div>';
    }
    
    document.getElementById('synopsisBuilderInput').value = "";
    openModal(document.getElementById('synopsisBuilderModal'));
  });

  safeAttach('closeSynopsisBuilderBtn', 'click', closeAllModals);
  
  safeAttach('builderTemp', 'input', (e) => {
    document.getElementById('builderTempValue').textContent = e.target.value;
  });
  
  safeAttach('sendSynopsisBuilderBtn', 'click', async () => {
      const input = document.getElementById('synopsisBuilderInput');
      const question = input.value.trim();
      if (!question) return;

      const btn = document.getElementById('sendSynopsisBuilderBtn');
      const tempSlider = document.getElementById('builderTemp');
      const personaSelector = document.getElementById('builderPersona');
      const threadEl = document.getElementById('synopsisBuilderThread');
      const originalText = btn.textContent;

      if(currentSynopsisBuilder.thread.length === 0) { threadEl.innerHTML = ""; }
      threadEl.innerHTML += `<div class="turn q"><div class="bubble">${esc(question)}</div></div>`;
      threadEl.scrollTop = threadEl.scrollHeight;
      currentSynopsisBuilder.thread.push({role: 'user', content: question});
      input.value = "";
      btn.disabled = true;
      btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;

      try {
        const body = new URLSearchParams({ 
            text: question,
            current_draft: document.getElementById('synopsisBuilderArea').value,
            discussion_thread: JSON.stringify(currentSynopsisBuilder.thread),
            temperature: tempSlider.value,
            persona: personaSelector.value,
            mode: 'brainstorm',
            write_kind: 'chat',
            use_notes: '1',
            use_history: '0'
        });
        const res = await fetch("/ask/"+pid, { method:'POST', body });
        if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
        const data = await res.json();
        
        threadEl.innerHTML += `<div class="turn a"><div class="bubble">${esc(data.answer)}</div></div>`;
        currentSynopsisBuilder.thread.push({role: 'assistant', content: data.answer});
        threadEl.scrollTop = threadEl.scrollHeight;
      } catch (err) {
          threadEl.innerHTML += `<div class="turn a"><div class="bubble" style="color:red;">שגיאה: ${esc(err.message)}</div></div>`;
      } finally {
          btn.disabled = false;
          btn.innerHTML = originalText;
      }
  });

  safeAttach('updateSynopsisFromDiscussionBtn', 'click', async () => {
    if(currentSynopsisBuilder.thread.length === 0) {
        alert("לא ניתן לעדכן מטיוטה ריקה.");
        return;
    }
    const btn = document.getElementById('updateSynopsisFromDiscussionBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;
    
    try {
        const body = new URLSearchParams({
            current_draft: document.getElementById('synopsisBuilderArea').value,
            discussion_thread: JSON.stringify(currentSynopsisBuilder.thread)
        });
        const res = await fetch(`/api/project/${pid}/update_synopsis_from_discussion`, { method: "POST", body });
        const data = await res.json();
        if(!res.ok) throw new Error(data.error || "שגיאת שרת");
        
        document.getElementById('synopsisBuilderArea').value = data.updated_synopsis;
        alert("טיוטת התקציר עודכנה.");

    } catch (err) {
        alert("שגיאה בעדכון הטיוטה: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
  });
  
  safeAttach('saveSynopsisDraftBtn', 'click', async () => {
      const btn = document.getElementById('saveSynopsisDraftBtn');
      const originalText = btn.textContent;
      btn.disabled = true;
      btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;
      
      try {
          const body = new URLSearchParams({
              draft_text: document.getElementById('synopsisBuilderArea').value,
              discussion_thread: JSON.stringify(currentSynopsisBuilder.thread)
          });
          const res = await fetch(`/api/project/${pid}/save_draft`, { method: "POST", body });
          if(!res.ok) throw new Error("שגיאת שרת");
          alert("טיוטה נשמרה!");
      } catch (err) {
          alert("שגיאה בשמירת הטיוטה: " + err.message);
      } finally {
          btn.disabled = false;
          btn.innerHTML = originalText;
      }
  });

  safeAttach('transferSynopsisBtn', 'click', () => {
    const newSynopsis = document.getElementById('synopsisBuilderArea').value;
    if (confirm("האם להעביר את הטיוטה לעורך הראשי? פעולה זו תחליף את התוכן הקיים בעורך.")) {
        document.getElementById('synopsisArea').value = newSynopsis;
        alert("הטיוטה הועברה בהצלחה. לחץ 'שמור תקציר' בעורך הראשי כדי לשמור את השינויים.");
        closeAllModals();
        openModal(document.getElementById('synopsisModal'));
    }
  });

  // --- New Refine Division Logic ---
  safeAttach('openRefineChatBtn', 'click', () => {
    currentDivisionRefinement.originalDivision = document.getElementById('divisionResultArea').value;
    currentDivisionRefinement.thread = [];
    document.getElementById('refineDivisionChatThread').innerHTML = '<div class="muted">התחל דיון לשיפור החלוקה...</div>';
    document.getElementById('refineDivisionChatInput').value = "";
    openModal(document.getElementById('refineDivisionChatModal'));
  });

  safeAttach('closeRefineDivisionChatBtn', 'click', () => {
      document.getElementById('refineDivisionChatModal').style.display = 'none';
  });

  safeAttach('refineTemp', 'input', (e) => {
    document.getElementById('refineTempValue').textContent = e.target.value;
  });

  safeAttach('sendRefineChatBtn', 'click', async () => {
      const input = document.getElementById('refineDivisionChatInput');
      const question = input.value.trim();
      if (!question) return;

      const btn = document.getElementById('sendRefineChatBtn');
      const tempSlider = document.getElementById('refineTemp');
      const personaSelector = document.getElementById('refinePersona');
      const threadEl = document.getElementById('refineDivisionChatThread');
      const originalText = btn.textContent;

      if(currentDivisionRefinement.thread.length === 0) { threadEl.innerHTML = ""; }
      threadEl.innerHTML += `<div class="turn q"><div class="bubble">${esc(question)}</div></div>`;
      threadEl.scrollTop = threadEl.scrollHeight;
      currentDivisionRefinement.thread.push({role: 'user', content: question});
      input.value = "";
      btn.disabled = true;
      btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;
      
      try {
        const body = new URLSearchParams({
            text: question,
            original_division: currentDivisionRefinement.originalDivision,
            discussion_thread: JSON.stringify(currentDivisionRefinement.thread),
            temperature: tempSlider.value,
            persona: personaSelector.value,
            mode: 'brainstorm',
            write_kind: 'chat',
            use_notes: '0',
            use_history: '0'
        });
        const res = await fetch("/ask/"+pid, { method:'POST', body });
        if (!res.ok) { const err = await res.json(); throw new Error(err.answer || 'שגיאת שרת'); }
        const data = await res.json();
        
        threadEl.innerHTML += `<div class="turn a"><div class="bubble">${esc(data.answer)}</div></div>`;
        currentDivisionRefinement.thread.push({role: 'assistant', content: data.answer});
        threadEl.scrollTop = threadEl.scrollHeight;
      } catch (err) {
          threadEl.innerHTML += `<div class="turn a"><div class="bubble" style="color:red;">שגיאה: ${esc(err.message)}</div></div>`;
      } finally {
          btn.disabled = false;
          btn.innerHTML = originalText;
      }
  });

  safeAttach('updateDivisionFromChatBtn', 'click', async () => {
    if(currentDivisionRefinement.thread.length === 0) {
        alert("לא ניתן לעדכן מחלוקה ריקה.");
        return;
    }
    const btn = document.getElementById('updateDivisionFromChatBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner" style="width:12px; height:12px; border-width:2px;"></div>`;
    
    try {
        const body = new URLSearchParams({
            original_division: currentDivisionRefinement.originalDivision,
            discussion_thread: JSON.stringify(currentDivisionRefinement.thread)
        });
        const res = await fetch(`/api/project/${pid}/update_division_from_discussion`, { method: "POST", body });
        const data = await res.json();
        if(!res.ok) throw new Error(data.error || "שגיאת שרת");
        
        document.getElementById('divisionResultArea').value = data.updated_division;
        document.getElementById('refineDivisionChatModal').style.display = 'none';
        alert("החלוקה עודכנה. ניתן לאשר ולהעביר לעורך.");

    } catch (err) {
        alert("שגיאה בעדכון החלוקה: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
  });


  // --- Universal Ctrl+Enter Handler ---
  document.addEventListener("keydown", (ev)=>{
    if (ev.ctrlKey && ev.key==="Enter"){
      const activeEl = document.activeElement;
      if (activeEl.id === 'prompt') { document.getElementById('sendBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'reviewInput') { document.getElementById('runReviewBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'discussionInput') { document.getElementById('askDiscussionBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'chapterDiscussionInput') { document.getElementById('sendChapterDiscussionBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'synopsisBuilderInput') { document.getElementById('sendSynopsisBuilderBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'refineDivisionChatInput') { document.getElementById('sendRefineChatBtn').click(); ev.preventDefault(); }
      if (activeEl.id === 'imgDesc') { document.getElementById('genImageBtn').click(); ev.preventDefault(); }
      if (['objName', 'objStyle', 'objDesc'].includes(activeEl.id)) {
          document.getElementById('createObjectBtn').click();
          ev.preventDefault();
      }
    }
  });
  
  applyModeUI();
  loadChat();
})();