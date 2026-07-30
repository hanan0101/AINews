function formatStepElapsed(seconds){
      if(seconds === null || seconds === undefined || seconds === '') return '';
      const value = Number(seconds);
      if(!Number.isFinite(value) || value < 0) return '';
      if(value < 60) return `${Math.round(value)}s`;
      const mins = Math.floor(value / 60);
      const secs = Math.round(value % 60);
      return `${mins}m ${secs}s`;
    }
    function landingStageKey(step, index){
      return String(step?.key || step?.label_en || step?.label_ar || `step-${index}`);
    }
    function stageElapsedSeconds(step, index, status){
      const key = landingStageKey(step, index);
      const backendElapsed = Number(step?.elapsed_seconds);
      if(status === 'done'){
        if(Number.isFinite(backendElapsed)) landingProgress.stageElapsed[key] = backendElapsed;
        return Number.isFinite(landingProgress.stageElapsed[key]) ? landingProgress.stageElapsed[key] : backendElapsed;
      }
      if(status === 'active' && !landingProgress.done){
        if(!landingProgress.stageStartedAt[key]){
          const seed = Number.isFinite(backendElapsed) ? backendElapsed : 0;
          landingProgress.stageStartedAt[key] = Date.now() - (seed * 1000);
        }
        const liveElapsed = (Date.now() - landingProgress.stageStartedAt[key]) / 1000;
        return Math.max(Number.isFinite(backendElapsed) ? backendElapsed : 0, liveElapsed);
      }
      return Number.isFinite(backendElapsed) ? backendElapsed : null;
    }
    function ensureLandingProgressTimer(){
      if(landingProgress.timer || !landingProgress.running || landingProgress.done) return;
      landingProgress.timer = window.setInterval(()=>{
        if(!landingProgress.running || landingProgress.done){
          clearLandingProgressTimer();
          return;
        }
        setLandingProgressFromBackend(null);
        if(landingProgress.lastBackendProgress?.running){
          renderBackendTimeline(landingProgress.lastBackendProgress);
        }
      }, 1000);
    }
    function clearLandingProgressTimer(){
      if(landingProgress.timer){
        window.clearInterval(landingProgress.timer);
        landingProgress.timer = null;
      }
    }
    function supportingBackgroundNote(progressLike){
      const timeline = Array.isArray(progressLike?.timeline) ? progressLike.timeline : [];
      const hasBackgroundSupporting = timeline.some(entry => {
        const text = String(entry?.text || '').toLowerCase();
        return text.includes('background courses') || text.includes('background course') || text.includes('prefetch');
      });
      if(!hasBackgroundSupporting) return '';
      return state.language === 'ar'
        ? 'جاري تجهيز الكورسات والأفلام بالخلفية'
        : 'Preparing courses and films in the background';
    }
    function normalizeBackendProgress(progressLike, forceDone=false){
      const progress = progressLike?.progress || progressLike || {};
      const timeline = Array.isArray(progressLike?.timeline) ? progressLike.timeline : [];
      const fallbackSteps = currentLandingSteps().map(label => ({label_ar: label, label_en: label}));
      const steps = Array.isArray(progress?.steps) && progress.steps.length ? progress.steps : fallbackSteps;
      const total = Number(progress?.total_steps) || steps.length || 1;
      let completed = Number(progress?.completed_steps);
      if(!Number.isFinite(completed)) completed = 0;
      completed = Math.max(0, Math.min(completed, total));
      if(forceDone) completed = total;
      let active = Number(progress?.active_step);
      if(!Number.isFinite(active)) active = Math.min(completed, total - 1);
      active = Math.max(0, Math.min(active, total - 1));
      const explicitStatuses = steps.map(step => typeof step === 'object' ? String(step?.status || '') : '');
      const hasExplicitStatuses = explicitStatuses.some(Boolean);
      if(explicitStatuses.some(Boolean)){
        const activeFromStatus = explicitStatuses.findIndex(status => status === 'active');
        const doneFromStatus = explicitStatuses.filter(status => status === 'done').length;
        if(activeFromStatus >= 0) active = activeFromStatus;
        completed = doneFromStatus;
        if(forceDone) completed = total;
      }
      const latestTimelineStage = [...timeline].reverse().find(entry => Number.isFinite(Number(entry?.stage_index)) && Number(entry?.stage_index) >= 0);
      if(latestTimelineStage){
        const timelineActive = Math.max(0, Math.min(Number(latestTimelineStage.stage_index), total - 1));
        if(!hasExplicitStatuses){
          active = timelineActive;
          completed = Math.max(completed, Math.max(0, timelineActive - 1));
        }
        if(forceDone) completed = total;
      }
      const percent = forceDone ? 100 : Math.round((completed / total) * 100);
      return {steps, total, completed, active, percent};
    }
    function setLandingProgressFromBackend(progressLike=null, forceDone=false){
      if(progressLike) landingProgress.lastBackendProgress = progressLike;
      const normalized = normalizeBackendProgress(progressLike || landingProgress.lastBackendProgress, forceDone);
      landingProgress.steps = normalized.steps;
      landingProgress.step = normalized.active;
      landingProgress.percent = normalized.percent;
      landingProgress.done = Boolean(forceDone || normalized.completed >= normalized.total);
      if(landingProgress.running && !landingProgress.done) ensureLandingProgressTimer();
      if(landingProgress.done) clearLandingProgressTimer();
      refreshLandingStepLabels();
      els.splashSteps?.querySelectorAll('.splash-step').forEach((item, index)=>{
        const backendStep = normalized.steps[index] || {};
        const status = backendStep.status || (landingProgress.done ? 'done' : index < normalized.completed ? 'done' : index === normalized.active ? 'active' : 'idle');
        const isDone = status === 'done';
        const isActive = status === 'active' && !landingProgress.done;
        item.classList.toggle('done', isDone);
        item.classList.toggle('active', isActive);
        const dot = item.querySelector('.splash-step-dot');
        if(dot) dot.textContent = '';
        const timeEl = item.querySelector('.splash-step-time');
        if(timeEl) timeEl.textContent = formatStepElapsed(stageElapsedSeconds(backendStep, index, status));
      });
      const totalSteps = els.splashSteps?.querySelectorAll('.splash-step').length || 1;
      const doneCount = els.splashSteps?.querySelectorAll('.splash-step.done').length || 0;
      const fillPct = Math.round((doneCount / totalSteps) * 100);
      if(els.splashSteps){
        els.splashSteps.style.setProperty('--fill', `${fillPct}%`);
      }
      if(els.splashStatus){
        const steps = currentLandingSteps();
        const perf = progressLike?.performance || landingProgress.lastBackendProgress?.performance || {};
        const totalSeconds = Number(perf.total_seconds || perf.ai_updates_total_seconds || 0);
        if(landingProgress.done && totalSeconds){
          const elapsed = formatTimelineElapsed(totalSeconds);
          els.splashStatus.textContent = state.language === 'ar'
            ? `تم تجهيز الأخبار خلال ${elapsed}`
            : `News generated in ${elapsed}`;
        }else{
          let statusText = landingProgress.done ? t('doneOpening') : (steps[normalized.active] || t('loadingNewsletter'));
          const backgroundNote = !landingProgress.done ? supportingBackgroundNote(progressLike || landingProgress.lastBackendProgress) : '';
          if(backgroundNote) statusText = `${statusText} | ${backgroundNote}`;
          els.splashStatus.textContent = statusText;
        }
      }
    }
    function setLandingProgress(step, forceDone=false){
      const steps = currentLandingSteps();
      const total = steps.length || 1;
      const completed = forceDone ? total : Math.max(0, Math.min(step, total));
      setLandingProgressFromBackend({
        steps: landingProgress.steps || steps.map(label => ({label_ar: label, label_en: label})),
        total_steps: total,
        completed_steps: completed,
        active_step: Math.min(completed, total - 1),
      }, forceDone);
    }
    function startLandingProgress(progress=null){
      landingProgress.running = true;
      landingProgress.done = false;
      landingProgress.percent = 0;
      landingProgress.lastBackendProgress = progress || null;
      landingProgress.steps = progress?.steps || null;
      landingProgress.stageStartedAt = {};
      landingProgress.stageElapsed = {};
      setLandingProgressFromBackend(progress || {completed_steps:0, active_step:0, total_steps:currentLandingSteps().length});
      ensureLandingProgressTimer();
    }
    function stopLandingProgress(){
      landingProgress.running = false;
      clearLandingProgressTimer();
    }
    async function revealNewsletter(){
      const total = currentLandingSteps().length;
      if(total >= 6){
        setLandingProgressFromBackend({
          steps: landingProgress.steps || currentLandingSteps().map(label => ({label_ar: label, label_en: label})),
          total_steps: total,
          completed_steps: total - 2,
          active_step: total - 2,
        });
        await new Promise(resolve => setTimeout(resolve, 280));
        setLandingProgressFromBackend({
          steps: landingProgress.steps || currentLandingSteps().map(label => ({label_ar: label, label_en: label})),
          total_steps: total,
          completed_steps: total - 1,
          active_step: total - 1,
        });
        await new Promise(resolve => setTimeout(resolve, 280));
      }
      setLandingProgress(total - 1, true);
      await new Promise(resolve => setTimeout(resolve, 420));
      els.splash.classList.add('hide');
      document.documentElement.classList.remove('splash-visible');
      document.body.classList.remove('splash-visible');
      els.shell.classList.add('ready');
      setTimeout(()=>showTip('choose'),250);
    }
    function revealNewsletterImmediately(){
      stopLandingProgress();
      els.splash.classList.remove('loading','error');
      els.splash.classList.add('hide');
      document.documentElement.classList.remove('splash-visible');
      document.body.classList.remove('splash-visible');
      document.body.classList.remove('user-transition');
      els.shell.classList.add('ready');
      document.documentElement.classList.remove('restored-version');
    }
    async function revealNewsletterForUser(){
      stopLandingProgress();
      els.splash.classList.remove('error');
      els.splash.classList.add('loading');
      document.body.classList.add('user-transition');
      if(els.splashStatus) els.splashStatus.textContent = 'جاري فتح النشرة...';
      await new Promise(resolve => setTimeout(resolve, 900));
      revealNewsletterImmediately();
    }
    function revealPinnedNewsletter(){
      const pinned = readPinnedState();
      if(!pinned) return false;
      applyState({...pinned, generator:null});
      revealNewsletterImmediately();
      updatePinnedPageButton();
      setTimeout(()=>showPlainToast('تم فتح النسخة المثبتة بدون توليد جديد'), 350);
      return true;
    }
    function shouldRevealRestoredVersion(){
      try{
        if (new URLSearchParams(window.location.search).get('new') === '1') return false;
        if (new URLSearchParams(window.location.search).get('restoredVersion')) return true;
        const stored = sessionStorage.getItem(EDITING_VERSION_KEY) || '';
        return /^\d+$/.test(stored);
      }catch(_){
        return false;
      }
    }
    function restoredVersionIdFromUrl(){
      try{
        const value = new URLSearchParams(window.location.search).get('restoredVersion') || '';
        return /^\d+$/.test(value) ? value : '';
      }catch(_){
        return '';
      }
    }
    async function loadRestoredVersionForView(){
      // Keep the restored version across a browser refresh after its query
      // parameter has been removed from the address bar.
      const versionId = currentEditingVersionId();
      if(!versionId) return false;
      const record = await request(`${API_BASE}/versions/${versionId}`);
      const payload = record?.content;
      if(!payload || typeof payload !== 'object' || Array.isArray(payload)){
        showPlainToast('\u062a\u0639\u0630\u0631 \u0641\u062a\u062d \u0627\u0644\u0646\u0633\u062e\u0629');
        return false;
      }
      try{ sessionStorage.setItem(EDITING_VERSION_KEY, versionId); }catch(_){}
      state.versionTitle = String(record?.title || '').trim();
      applyState(payload);
      return true;
    }
    function currentEditingVersionId(){
      const fromUrl = restoredVersionIdFromUrl();
      if(fromUrl){
        try{ sessionStorage.setItem(EDITING_VERSION_KEY, fromUrl); }catch(_){}
        return fromUrl;
      }
      try{
        const stored = sessionStorage.getItem(EDITING_VERSION_KEY) || '';
        return /^\d+$/.test(stored) ? stored : '';
      }catch(_){
        return '';
      }
    }
    function clearEditingVersion(){
      try{ sessionStorage.removeItem(EDITING_VERSION_KEY); }catch(_){}
      state.versionTitle = '';
    }
    function isNewGenerationPage(){
      try{
        return new URLSearchParams(window.location.search).get('new') === '1';
      }catch(_){
        return false;
      }
    }
    function isPdfConversionRequest(){
      try{
        return new URLSearchParams(window.location.search).get('convertPdf') === '1';
      }catch(_){
        return false;
      }
    }
    function isLoginRedirect(){
      try{
        return new URLSearchParams(window.location.search).get('from') === 'login';
      }catch(_){
        return false;
      }
    }
    function isPageRefresh(){
      try{
        const navigation = performance.getEntriesByType?.('navigation')?.[0];
        if(navigation?.type) return navigation.type === 'reload';
        return performance.navigation?.type === 1;
      }catch(_){
        return false;
      }
    }
    function openGenerationPage(){
      clearEditingVersion();
      clearPinnedState();
      window.location.href = 'News.html?new=1';
    }
    async function startNewsletterGeneration(){
      if(landingProgress.running) return;
      clearPinnedState();
      clearEditingVersion();
      els.splash.classList.remove('error');
      els.splash.classList.add('loading');
      updateSplashStatusForLanguage();
      if(els.splashError) els.splashError.textContent = t('splashError');
      if(els.generateBtn) els.generateBtn.textContent = t('retryNewsletter');
      startLandingProgress();
      try{
        const refillData = await request(`${API_BASE}/refill`, {
          method:'POST',
          body: JSON.stringify({section:null, force:true})
        });
        setLandingProgressFromBackend(refillData.generator);
        const finalData = await pollForGeneratorDone({applyWhileRunning:false});
        const finalResult = finalData?.generator?.last_result;
        // New-generate safety: the backend intentionally restores the previous
        // newsletter when a run fails or does not save enough fresh news. Do not
        // reveal that restored old version as if it were the new Generate result.
        if(finalResult && finalResult.success === false){
          throw new Error(finalResult.message || 'Generate finished without saving a new newsletter');
        }
        await loadState(false);
        if(!hasEnoughContentToDisplay(state)){
          const hasAnyContent = state.items.length || state.courses.length || state.movies.length;
          if(!hasAnyContent){
            throw new Error(finalData?.generator?.last_result?.message || 'Newsletter content is incomplete');
          }
          showToast('incompleteContent');
        }
        stopLandingProgress();
        await revealNewsletter();
      }catch(error){
        console.error(error);
        stopLandingProgress();
        els.splash.classList.add('error');
        els.splash.classList.remove('loading');
        updateSplashStatusForLanguage();
        setLandingProgress(0);
        if(els.splashStatus) els.splashStatus.textContent = t('splashStatusError');
        if(els.splashError) els.splashError.textContent = t('splashErrorDetailed');
      }
    }
    function applyState(data, options={}){
      const incomingItems = dedupeClientItems(data.items || []);
      const allNewsSources = [];
      allNewsSources.push(...incomingItems);
      // Accept both backend and UI snapshot names for the full news pool.
      // all_items is used by pinned/undo state; all_news_items/backup_news can
      // come from backend payloads or exported newsletter JSON.
      ['all_items','all_news_items','news','backup_news','reserve_news'].forEach(key => {
        if(Array.isArray(data[key])) allNewsSources.push(...data[key]);
      });
      ['beginner','intermediate','advanced'].forEach(level => {
        if(Array.isArray(data.news_bank?.[level])) allNewsSources.push(...data.news_bank[level]);
      });
      const incomingAllItems = dedupeClientItems(allNewsSources.length ? allNewsSources : incomingItems);
      const nextSignature = clientContentSignature(incomingAllItems);
      const isFullReload = !data?.success && !data?.replacement_source && !data?.refill;
      if(isFullReload && state.contentSignature && nextSignature && nextSignature !== state.contentSignature){
        state.cardNav = {};
        state.card_refill_history = {};
      }
      state.contentSignature = nextSignature || state.contentSignature;
      state.items = incomingItems;
      state.all_items = incomingAllItems;
      state.courses = data.courses || [];
      state.movies = data.movies || [];
      state.news_bank = data.news_bank || {};
      state.courses_bank = data.courses_bank || {};
      state.recommended_view = data.recommended_view || {};
      state.saved_views = data.saved_views || {};
      state.defaultView = data.default_view || {};
      state.metadata = data.metadata || {};
      const shouldApplyIncomingView = Boolean(options.restoreView || !state.viewInitialized);
      // A fresh backend state should use the saved bank/order, not a temporary
      // drag-sort override from the previous render.
      clearContextViewOverrides();
      // Preserve the user's 4/6 toolbar choice across backend refreshes. Most
      // API responses do not include news_display_count, so resetting to 4 here
      // made the page jump back to four cards after the user selected six.
      if(shouldApplyIncomingView){
        const defaultNewsDisplayCount = isFullReload ? state.defaultView?.news_display_count : null;
        const incomingNewsDisplayCount = Number(defaultNewsDisplayCount ?? data.news_display_count ?? data.newsDisplayCount);
        state.newsDisplayCount = incomingNewsDisplayCount === 6 ? 6 : incomingNewsDisplayCount === 4 ? 4 : newsViewCount(state);
        const incomingSelectedLevels = (isFullReload ? state.defaultView?.selected_levels : null) ?? data.selected_levels ?? data.selectedLevels;
        if(Array.isArray(incomingSelectedLevels) && incomingSelectedLevels.length){
          state.selectedLevels = incomingSelectedLevels.map(normalizeLevelName).filter(Boolean);
          if(!state.selectedLevels.length) state.selectedLevels = ['all'];
        }
      }
      if(!Array.isArray(state.selectedLevels) || !state.selectedLevels.length){
        state.selectedLevels = ['all'];
      }
      // The API value is the current user choice (for example, immediately
      // after switching to movies). It must win over the last saved default;
      // otherwise loadState() visibly switches to movie and then jumps back
      // to courses as soon as the GET /news response is applied.
      state.feature_mode = data.feature_mode || (isFullReload ? state.defaultView?.feature_mode : null) || state.feature_mode || 'course';
      state.feature_item = data.feature_item || null;
      // Migrate the legacy footer in restored, pinned, and previously saved
      // newsletter payloads without changing their month or issue number.
      state.template = normalizeFooterTemplate(data.template || {});
      state.previous_counts = data.previous_counts || state.previous_counts || {};
      if(!(isFullReload && restoreSavedViewForContext())) applySelectedLevelView();
      renderBackendTimeline(data.generator);
      updateNewsletterTitle();
      render();
      applyRolePermissions();
      state.viewInitialized = true;
      if(hasPinnedState()) savePinnedState();
    }
    function missingClientSections(data){
      return Object.keys(requiredCounts).filter(section => ((data[section] || []).length < requiredCounts[section]));
    }
    function fetchMissingSections(data){
      return Array.isArray(data?.needs_fetch) ? data.needs_fetch : missingClientSections(data);
    }
    function hasEnoughContentToDisplay(data){
      return Object.keys(minimumDisplayCounts).every(section => ((data[section] || []).length >= minimumDisplayCounts[section]));
    }
    async function pollForCompletedContent(section=null){
      let lastFeedback = '';
      let lastCounts = null;
      let stalledAfterFinish = 0;
      for(let attempt=0; attempt<GENERATOR_POLL_MAX_ATTEMPTS; attempt++){
        await new Promise(resolve => setTimeout(resolve, 1500));
        const data = await request(`${API_BASE}/news?auto=0`);
        applyState(data);
        const missing = fetchMissingSections(data);
        const runningSections = data.generator?.sections || [];
        const feedback = data.feedback?.[0] || (data.generator?.running && runningSections.length ? `${t('generatorFetching')} ${runningSections.join(', ')}` : '');
        if(feedback && feedback !== lastFeedback){
          showToast(feedback);
          lastFeedback = feedback;
        }
        if(!section && missing.length===0) return data;
        if(section && !missing.includes(section)) return data;
        const counts = JSON.stringify({
          items: (data.items || []).length,
          movies: (data.movies || []).length,
          courses: (data.courses || []).length
        });
        if(!data.generator?.running){
          stalledAfterFinish = counts === lastCounts ? stalledAfterFinish + 1 : 0;
          if(stalledAfterFinish >= 2 || attempt > 4) return data;
        }
        lastCounts = counts;
      }
      showToast('incompleteContent');
      return null;
    }
    async function pollForAdditionalContent(section, previousCount){
      let lastFeedback = '';
      for(let attempt=0; attempt<GENERATOR_POLL_MAX_ATTEMPTS; attempt++){
        await new Promise(resolve => setTimeout(resolve, 1500));
        const data = await request(`${API_BASE}/news?auto=0`);
        applyState(data);
        const currentCount = (data[section] || []).length;
        const feedback = data.feedback?.[0] || (data.generator?.running ? `${t('extraFetchingSection')} ${section}...` : '');
        if(feedback && feedback !== lastFeedback){
          showToast(feedback);
          lastFeedback = feedback;
        }
        if(currentCount > previousCount) return data;
        if(!data.generator?.running && attempt > 2) return data;
      }
      showToast('additionalFailed');
      return null;
    }
    async function pollForGeneratorDone(options={}){
      const applyWhileRunning = options.applyWhileRunning !== false;
      for(let attempt=0; attempt<GENERATOR_POLL_MAX_ATTEMPTS; attempt++){
        await new Promise(resolve => setTimeout(resolve, 1500));
        const data = await request(`${API_BASE}/news?auto=0`);
        setLandingProgressFromBackend(data.generator);
        if(applyWhileRunning || !data.generator?.running){
          applyState(data);
        }else{
          renderBackendTimeline(data.generator);
        }
        if(!data.generator?.running) return data;
      }
      return null;
    }
    async function loadState(triggerFetch=true){
      let data = await request(`${API_BASE}/news?auto=0`);
      applyState(data);
      const missing = fetchMissingSections(data);
      if(missing.length && triggerFetch && state.isAdmin){
        const labels = {items:t('newsLabel'), movies:t('moviesLabel'), courses:t('coursesLabel')};
        showToast(`${t('lessThanRequired')} ${missing.map(section=>labels[section] || section).join(state.language === 'ar' ? '، ' : ', ')}`);
        for(const section of missing){
          const currentCount = (data[section] || []).length;
          const targetCount = minimumDisplayCounts[section] || requiredCounts[section] || currentCount;
          for(let index=currentCount; index<targetCount; index++){
            try{
              data = await request(`${API_BASE}/refill`, {
                method:'POST',
                body: JSON.stringify({section, pool_only:true, index, action:'replace'})
              });
              applyState(data);
            }catch(error){
              console.error(error);
              break;
            }
          }
        }
        const stillMissing = fetchMissingSections(data);
        if(stillMissing.length){
          await request(`${API_BASE}/refill`, {
            method:'POST',
            body: JSON.stringify({section: stillMissing.length === 1 ? stillMissing[0] : null, force:true})
          });
          await pollForCompletedContent();
        }
      }
      return data;
    }
    function initActions(){
      document.querySelector('[data-action="download"]')?.addEventListener('click', exportCleanPdf);
      document.querySelector('[data-action="preview"]')?.addEventListener('click', openPreview);
      document.querySelector('[data-action="undo"]')?.addEventListener('click', undoAction);
      document.querySelector('[data-action="redo"]')?.addEventListener('click', redoAction);
      document.querySelector('[data-action="settings"]')?.addEventListener('click', openSettings);
      document.querySelector('[data-action="pin-page"]')?.addEventListener('click', togglePinnedPage);
      document.querySelectorAll('[data-close]').forEach(btn=>btn.addEventListener('click', ()=>closeOverlay(btn.dataset.close)));
      document.querySelectorAll('[data-feature-mode]').forEach(btn=>btn.addEventListener('click', ()=>switchFeature(btn.dataset.featureMode)));
      els.alternativeFetchBtn?.addEventListener('click', async ()=>{
        const target = state.alternativeTarget;
        const resolve = state.alternativeResolve;
        state.alternativeResolve = null;
        closeOverlay('alternative');
        if(resolve){
          resolve(true);
          return;
        }
        if(!target) return;
        await fetchMoreAlternative(target.section, target.id, target.index, target.action || 'replace');
      });
      els.deleteConfirmBtn?.addEventListener('click', ()=>closeDeleteConfirm(true));
      els.editForm?.addEventListener('submit', saveEdit);
      els.editLogoSize?.addEventListener('input', ()=>{
        if(!state.editTarget) return updateLogoSizeValue(els.editLogoSize.value);
        applyLogoSizePreview(state.editTarget.section, state.editTarget.id, els.editLogoSize.value);
      });
      els.logoEditorSize?.addEventListener('input', ()=>updateLogoEditorSize(els.logoEditorSize.value));
      els.logoEditorSave?.addEventListener('click', saveLogoEditor);
      els.logoEditorCancel?.addEventListener('click', ()=>closeLogoEditor({restore:true}));
      els.logoEditorClose?.addEventListener('click', ()=>closeLogoEditor({restore:true}));
      els.logoEditorScrim?.addEventListener('click', ()=>closeLogoEditor({restore:true}));
      document.addEventListener('pointerdown', handleLogoPointerDown, {passive:false});
      document.addEventListener('wheel', handleLogoWheel, {passive:false});
      els.settingsForm?.addEventListener('submit', saveSettings);
      els.previewOverlay?.addEventListener('click', e=>{ if(e.target===els.previewOverlay) closeOverlay('preview');});
      els.contentTypeOverlay?.addEventListener('click', e=>{ if(e.target===els.contentTypeOverlay) closeOverlay('contentType');});
      els.editOverlay?.addEventListener('click', e=>{ if(e.target===els.editOverlay) closeOverlay('edit');});
      els.aiOverlay?.addEventListener('click', e=>{ if(e.target===els.aiOverlay) closeOverlay('ai');});
      els.alternativeOverlay?.addEventListener('click', e=>{ if(e.target===els.alternativeOverlay) closeOverlay('alternative');});
      els.deleteConfirmOverlay?.addEventListener('click', e=>{ if(e.target===els.deleteConfirmOverlay) closeOverlay('deleteConfirm');});
      els.settingsOverlay?.addEventListener('click', e=>{ if(e.target===els.settingsOverlay) closeOverlay('settings');});
      els.aiForm?.addEventListener('submit', saveAi);
    }
    async function boot(){
      await loadAuthState();
      initActions();
      loadUndoStack();
      applyLanguage();
      setLandingProgress(0);
      els.generateBtn?.addEventListener('click', startNewsletterGeneration);
      window.addEventListener('beforeunload', ()=>{
        if(hasPinnedState()) savePinnedState();
      });
      if(isPageRefresh()){
        const restored = shouldRevealRestoredVersion()
          ? await loadRestoredVersionForView()
          : false;
        if(!restored) await loadState(false);
        revealNewsletterImmediately();
        window.history.replaceState({}, document.title, 'News.html');
        return;
      }
      if(isLoginRedirect()){
        clearEditingVersion();
        await loadState(false);
        revealNewsletterImmediately();
        window.history.replaceState({}, document.title, 'News.html');
        return;
      }
      if(isNewGenerationPage()){
        clearEditingVersion();
        clearPinnedState();
        window.history.replaceState({}, document.title, 'News.html');
        return;
      }
      if(!state.isAdmin){
        const restored = await loadRestoredVersionForView();
        if(!restored){
          clearEditingVersion();
          await loadState(false);
        }
        if(restored){
          revealNewsletterImmediately();
        }else{
          await revealNewsletterForUser();
        }
        window.history.replaceState({}, document.title, 'News.html');
        return;
      }
      if(shouldRevealRestoredVersion()){
        const restored = await loadRestoredVersionForView();
        if(!restored) await loadState(false);
        revealNewsletterImmediately();
        if(restored && isPdfConversionRequest()){
          await convertCurrentVersionToPdf();
          return;
        }
        window.history.replaceState({}, document.title, 'News.html');
        setTimeout(()=>showPlainToast('تم فتح النسخة'), 250);
      }
    }
    boot().catch(error=>{
      console.error(error);
      els.splash.classList.add('error');
      if(els.splashStatus) els.splashStatus.textContent = t('pageError');
      if(els.splashError) els.splashError.textContent = error.message || t('pageErrorDetailed');
    });
