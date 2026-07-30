function currentNewsletterJsonPayload(){
      const visibleIds = new Set((state.items || []).map(item => item.id));
      const backups = (state.all_items || []).filter(item => !visibleIds.has(item.id));
      return {
        items: state.items || [],
        backup_news: backups,
        movies: state.movies || [],
        courses: state.courses || [],
        news_bank: state.news_bank || {},
        courses_bank: state.courses_bank || {},
        recommended_view: state.recommended_view || {},
        saved_views: state.saved_views || {},
        default_view: state.defaultView || {},
        selected_levels: state.selectedLevels || ['all'],
        news_display_count: newsViewCount(state),
        template: state.template || {},
        feature_mode: state.feature_mode || 'course',
        // Persist the selected display count so exported/saved newsletter JSON
        // knows whether the user was viewing 4 compact news cards or 6 cards.
        metadata: {
          ...(state.metadata || {}),
          source: 'ui_pdf_export',
          embedded_in_pdf: true,
          exported_at: new Date().toISOString(),
          display_count: (state.items || []).length,
          backup_count: backups.length,
          news_total_count: (state.items || []).length + backups.length
        }
      };
    }

    async function createPreviewPdfBlob(){
      let exportClone = null;
      try{
        if(document.fonts?.ready){
          try{ await document.fonts.ready; }catch{}
        }
        exportClone = await cloneCurrentPreviewForPdf();
        const {host, width, height} = exportClone;
        const previewWrapper = host.querySelector('.preview-window');
        if(!previewWrapper) throw new Error('Preview export wrapper was not found');
        const response = await fetch(`${API_BASE}/export-pdf`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            html: previewWrapper.outerHTML,
            width,
            height,
            direction: document.documentElement.dir || 'rtl',
            pdf_profile: 'whatsapp',
            source_html: location.pathname.split('/').pop() || 'News.html',
            newsletter_json: currentNewsletterJsonPayload()
          })
        });
        if(!response.ok){
          let message = 'PDF export failed';
          try{
            const errorData = await response.json();
            message = errorData.error || message;
          }catch{}
          throw new Error(message);
        }
        return response.blob();
      }finally{
        exportClone?.host?.remove();
      }
    }

    function safeDownloadStem(value='newsletter'){
      return String(value || 'newsletter').replace(/[\\/:*?"<>|\r\n]+/g, '_').replace(/^\.+|\.+$/g, '').trim() || 'newsletter';
    }

    async function downloadPreviewPdf(){
      const pdfBlob = await createPreviewPdfBlob();
      const url = URL.createObjectURL(pdfBlob);
      const link = document.createElement('a');
      link.href = url;
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      link.download = `${safeDownloadStem(state.versionTitle || `AINewsletter_v02_${stamp}`)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(()=>URL.revokeObjectURL(url), 1200);
      return pdfBlob;
    }

    async function blobToBase64(blob){
      return new Promise((resolve, reject)=>{
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    }

    async function convertCurrentVersionToPdf(){
      const versionId = currentEditingVersionId();
      if(!state.isAdmin || !versionId || !isPdfConversionRequest()) return false;
      showPlainToast('جاري تحويل النسخة إلى PDF...');
      const pdfBlob = await createPreviewPdfBlob();
      const pdf_base64 = await blobToBase64(pdfBlob);
      const response = await fetch(`${API_BASE}/versions/${encodeURIComponent(versionId)}/pdf`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          pdf_base64,
          filename: `${safeDownloadStem(state.versionTitle || `newsletter_version_${versionId}`)}.pdf`
        })
      });
      const data = await response.json().catch(()=>({}));
      if(!response.ok || !data.success){
        throw new Error(data.error || 'تعذر تحويل النسخة إلى PDF');
      }
      clearEditingVersion();
      showPlainToast('تم تحويل النسخة إلى PDF');
      setTimeout(()=>{ window.location.href = 'versions.html'; }, 700);
      return true;
    }

    function setDownloadLoading(active){
      document.body.classList.toggle('download-in-progress', Boolean(active));
      els.downloadLoadingOverlay?.classList.toggle('show', Boolean(active));
      els.downloadLoadingOverlay?.setAttribute('aria-busy', active ? 'true' : 'false');
    }

    async function exportCleanPdf(){
      try{
        setDownloadLoading(true);
        await downloadPreviewPdf();
      }catch(error){
        console.error(error);
        showToast('pdfError');
      }finally{
        setDownloadLoading(false);
      }
    }

    function persistUndoStack(){
      try{ localStorage.setItem('aiNewsletterUndoStack', JSON.stringify(state.undoStack.slice(-12))); }catch{}
    }
    function persistRedoStack(){
      try{ localStorage.setItem('aiNewsletterRedoStack', JSON.stringify(state.redoStack.slice(-12))); }catch{}
    }
    function loadUndoStack(){
      try{
        const saved = JSON.parse(localStorage.getItem('aiNewsletterUndoStack') || '[]');
        if(Array.isArray(saved)) state.undoStack = saved.slice(-12);
      }catch{}
      try{
        const savedRedo = JSON.parse(localStorage.getItem('aiNewsletterRedoStack') || '[]');
        if(Array.isArray(savedRedo)) state.redoStack = savedRedo.slice(-12);
      }catch{}
    }
    function snapshotPayload(){
      return {
        items: state.items,
        // Preserve the complete news pool so toolbar switching from 4 to 6 can
        // show real cards after undo/pin/restore flows, not just resize the page.
        all_items: state.all_items || state.items || [],
        courses: state.courses,
        movies: state.movies,
        news_bank: state.news_bank || {},
        courses_bank: state.courses_bank || {},
        recommended_view: state.recommended_view || {},
        saved_views: state.saved_views || {},
        default_view: state.defaultView || {},
        selected_levels: state.selectedLevels || ['all'],
        metadata: state.metadata || {},
        template: state.template || {},
        feature_mode: state.feature_mode,
        // Keep undo/pinned snapshots aligned with the toolbar news-count choice.
        newsDisplayCount: newsViewCount(state),
        feature_item: state.feature_item
      };
    }
    function hasPinnedState(){
      try{
        const saved = JSON.parse(localStorage.getItem(PINNED_STATE_KEY) || 'null');
        return Boolean(saved && (Array.isArray(saved.items) || Array.isArray(saved.courses) || Array.isArray(saved.movies)));
      }catch{
        return false;
      }
    }
    function readPinnedState(){
      try{
        const saved = JSON.parse(localStorage.getItem(PINNED_STATE_KEY) || 'null');
        if(saved && (Array.isArray(saved.items) || Array.isArray(saved.courses) || Array.isArray(saved.movies))) return saved;
      }catch{}
      return null;
    }
    function updatePinnedPageButton(){
      const button = document.querySelector('[data-action="pin-page"]');
      if(!button) return;
      const pinned = hasPinnedState();
      const label = pinned ? 'إلغاء التثبيت' : 'تثبيت مؤقت';
      button.classList.toggle('active', pinned);
      button.setAttribute('aria-label', label);
      button.removeAttribute('title');
      const text = button.querySelector('span');
      if(text) text.textContent = label;
    }
    function savePinnedState(){
      const payload = {
        ...snapshotPayload(),
        pinned_at: new Date().toISOString()
      };
      try{
        localStorage.setItem(PINNED_STATE_KEY, JSON.stringify(payload));
        updatePinnedPageButton();
        return true;
      }catch(error){
        console.error(error);
        return false;
      }
    }
    function clearPinnedState(){
      try{ localStorage.removeItem(PINNED_STATE_KEY); }catch{}
      updatePinnedPageButton();
    }
    function togglePinnedPage(){
      if(hasPinnedState()){
        clearPinnedState();
        showPlainToast('تم إلغاء التثبيت المؤقت');
        return;
      }
      if(!state.items.length && !state.courses.length && !state.movies.length){
        showPlainToast('افتح النشرة أولًا ثم ثبّت الصفحة');
        return;
      }
      if(savePinnedState()) showPlainToast('تم تثبيت الصفحة مؤقتًا لهذا المتصفح');
      else showPlainToast('تعذر حفظ النسخة المؤقتة');
    }
    function saveSnapshot(){
      state.undoStack.push(JSON.stringify(snapshotPayload()));
      if(state.undoStack.length>12) state.undoStack.shift();
      state.redoStack = [];
      persistUndoStack();
      persistRedoStack();
    }
    async function restoreSnapshot(raw, mode){
      const isRedo = mode === 'redo';
      const current = JSON.stringify(snapshotPayload());
      try{
        showToast(isRedo ? 'redoRunning' : 'undoRunning');
        const snapshot = JSON.parse(raw);
        const data = await request(`${API_BASE}/state`, {method:'PUT', body: JSON.stringify(snapshot)});
        if(isRedo){
          state.undoStack.push(current);
          if(state.undoStack.length>12) state.undoStack.shift();
          persistUndoStack();
        } else {
          state.redoStack.push(current);
          if(state.redoStack.length>12) state.redoStack.shift();
          persistRedoStack();
        }
        applyState(data, {restoreView:true});
        showToast(isRedo ? 'redoSaved' : 'undoSaved');
        const missing = fetchMissingSections(data);
        if(missing.length){
          showToast(sectionMessages[missing[0]] || 'fetchNewContent');
          await pollForCompletedContent();
        }
      }catch(error){
        console.error(error);
        showToast(isRedo ? 'redoFailed' : 'undoFailed');
      }
    }
    async function undoAction(){
      const raw = state.undoStack.pop();
      persistUndoStack();
      if(!raw){showToast('undoNone'); return;}
      await restoreSnapshot(raw, 'undo');
    }
    async function redoAction(){
      const raw = state.redoStack.pop();
      persistRedoStack();
      if(!raw){showToast('redoNone'); return;}
      await restoreSnapshot(raw, 'redo');
    }
    function openSettings(){
      if(els.settingsNewsletterTitle) els.settingsNewsletterTitle.value = state.template?.newsletter_title || '';
      if(els.settingsFooterPrefix) els.settingsFooterPrefix.value = state.template?.footer_prefix || 'تطوير : إدارة المرصد الثقافي';
      if(els.settingsMonthYear) els.settingsMonthYear.value = state.template?.month_year_override || '';
      if(els.settingsIssueNumber) els.settingsIssueNumber.value = state.template?.issue_number || '';
      els.settingsOverlay.classList.add('show');
    }
    async function saveSettings(event){
      event.preventDefault();
      const payload = {
        newsletter_title: (els.settingsNewsletterTitle?.value || '').trim(),
        footer_prefix: (els.settingsFooterPrefix?.value || '').trim(),
        month_year_override: (els.settingsMonthYear?.value || '').trim(),
        issue_number: Number(els.settingsIssueNumber?.value || state.template?.issue_number || 1)
      };
      const data = await request(`${API_BASE}/settings`, {method:'POST', body: JSON.stringify(payload)});
      state.template = normalizeFooterTemplate(data.template || {
        ...(state.template || {}),
        ...payload
      });
      updateNewsletterTitle();
      render();
      if(hasPinnedState()) savePinnedState();
      closeOverlay('settings');
      showToast('settingsSaved');
    }
    const minimumDisplayCounts = {items:4, movies:1, courses:2};
    const requiredCounts = minimumDisplayCounts;
    const sectionMessages = {
      items: 'fetchNewContent',
      movies: 'fetchNewContent',
      courses: 'fetchNewContent'
    };
    const landingProgress = {
      step:0,
      running:false,
      done:false,
      percent:0,
      steps:null,
      lastBackendProgress:null,
      stageStartedAt:{},
      stageElapsed:{},
      timer:null
    };
