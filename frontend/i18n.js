// i18n: translation lookup, language switching, RTL/LTR mixed-title
// rendering, and a few splash/progress text helpers that are updated on
// every language switch alongside the rest of the UI text.
// Depends on `state`/`els` (defined in the main News.html script, which
// loads after this file - safe because none of this runs until a later
// user action, by which point the main script has already executed).
    function t(key){
      return LANGUAGES[state.language]?.[key] ?? LANGUAGES.ar[key] ?? key;
    }
    function currentLandingSteps(){
      if(Array.isArray(landingProgress?.steps) && landingProgress.steps.length){
        return landingProgress.steps.map(step => {
          if(typeof step === 'string') return step;
          return step.label_ar || step.label_en || step.key || '';
        });
      }
      return LANGUAGES[state.language]?.landingSteps || LANGUAGES.ar.landingSteps;
    }
    function setText(selector, value){
      const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
      if(el) el.textContent = value;
    }
    function formatTimelineElapsed(value){
      const seconds = Number(value || 0);
      if(!Number.isFinite(seconds) || seconds <= 0) return '';
      if(seconds < 60) return `${seconds.toFixed(1)}s`;
      const minutes = Math.floor(seconds / 60);
      const rest = Math.round(seconds % 60);
      return `${minutes}m ${rest}s`;
    }
    function renderBackendTimeline(generator){
      state.generator = generator || null;
    }
    function updateStaticLanguageText(){
      document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = t(el.dataset.i18n);
      });
      const toolbarLabels = {
        send: 'toolbarSend',
        settings: 'toolbarSettings',
        download: 'toolbarDownload',
        preview: 'toolbarPreview',
        undo: 'toolbarUndo',
        redo: 'toolbarRedo'
      };
      Object.entries(toolbarLabels).forEach(([action,key]) => {
        const button = document.querySelector(`[data-action="${action}"]`);
        if(button){
          button.setAttribute('aria-label', t(key));
          button.removeAttribute('title');
        }
      });
      updatePinnedPageButton();
      setText('[data-feature-mode="course"] span', t('courseSwitch'));
      setText('[data-feature-mode="movie"] span', t('filmSwitch'));
      updateNewsletterFooter();
      setText('#contentTypeOverlay .modal-head h4', t('modalContentChoice'));
      setText('#contentTypeOverlay [data-feature-mode="movie"] h5', t('modalMovieTitle'));
      setText('#contentTypeOverlay [data-feature-mode="movie"] p', t('modalMovieDesc'));
      setText('#contentTypeOverlay [data-feature-mode="course"] h5', t('modalCourseTitle'));
      setText('#contentTypeOverlay [data-feature-mode="course"] p', t('modalCourseDesc'));
      setText('#editOverlay label[for="editTitle"]', t('titleLabel'));
      setText('#editOverlay label[for="editText"]', t('descriptionLabel'));
      setText('#editOverlay label[for="editUrl"]', t('urlLabel'));
      setText('#editOverlay label[for="editSource"]', t('sourceLabel'));
      setText('#editOverlay label[for="editLogo"]', t('logoImageLabel') || 'Company logo URL');
      setText('#editOverlay label[for="editLogoSize"]', t('logoSizeLabel') || 'Logo size');
      setText('#editOverlay .modal-actions .primary', t('saveEdit'));
      setText('#editOverlay [data-close="edit"].btn', t('cancel'));
      setText(els.logoEditorTitle, t('logoSizeLabel') || 'Logo size');
      setText(els.logoEditorSave, t('saveEdit') || 'Save');
      setText(els.logoEditorCancel, t('cancel') || 'Cancel');
      setText('#aiOverlay label[for="aiInstruction"]', t('aiInstructionLabel'));
      if(els.aiInstruction) els.aiInstruction.placeholder = t('aiInstructionPlaceholder');
      setText('#aiOverlay .modal-actions .primary', t('run'));
      setText('#aiOverlay [data-close="ai"].btn', t('cancel'));
      setText('#alternativeModalTitle', t('alternativeTitle'));
      setText('#alternativeModalText', t('alternativeText'));
      setText('#alternativeFetchBtn', t('fetchMore'));
      setText('#alternativeOverlay [data-close="alternative"].btn', t('cancel'));
      setText('#deleteConfirmTitle', t('deleteConfirmTitle'));
      setText('#deleteConfirmText', t('deleteConfirmText'));
      setText('#deleteConfirmBtn', t('deleteConfirmAction'));
      setText('#deleteConfirmOverlay [data-close="deleteConfirm"].btn', t('cancel'));
      setText('#settingsOverlay .modal-head h4', t('settingsTitle'));
      setText('#settingsOverlay label[for="settingsNewsletterTitle"]', 'عنوان الصفحة');
      setText('#settingsOverlay label[for="settingsFooterPrefix"]', 'نص بداية الفوتر');
      setText('#settingsOverlay label[for="settingsMonthYear"]', 'الشهر والسنة');
      setText('#settingsOverlay label[for="settingsIssueNumber"]', 'رقم الإصدار');
      setText('#settingsOverlay .modal-actions .primary', t('saveSettings'));
      setText('#settingsOverlay [data-close="settings"].btn', t('cancel'));
      setText('#previewOverlay [data-close="preview"]', t('close'));
      setText('#tipChoose h4', t('tipChooseTitle'));
      setText('#tipChoose p', t('tipChooseText'));
      setText('#tipChoose .tip-btn', t('next'));
      setText('#tipEdit h4', t('tipEditTitle'));
      setText('#tipEdit p', t('tipEditText'));
      setText('#tipEdit .tip-btn', t('next'));
      setText('#tipReorder h4', t('tipReorderTitle'));
      setText('#tipReorder p', t('tipReorderText'));
      setText('#tipReorder .tip-btn', t('done'));
      if(els.editModalTitle && !els.editOverlay.classList.contains('show')) els.editModalTitle.textContent = t('editCardTitle');
      if(els.aiModalTitle && !els.aiOverlay.classList.contains('show')) els.aiModalTitle.textContent = t('aiModalTitle');
    }
    function updateNewsletterTitle(){
      if(!els.newsletterTitle) return;
      const templateTitle = state.template?.newsletter_title;
      const title = state.language === 'ar' && templateTitle ? templateTitle : t('newsletterTitle');
      const formattedTitle = String(title)
        .replace(/\\n/g, '\n')
        .replace(/[ \t]*\n[ \t]*/g, '\n')
        .trim();
      els.newsletterTitle.innerHTML = escapeHtml(formattedTitle).replace(/\n/g,'<br>');
      updateNewsletterFooter();
    }
    function formatFooterSeparators(text){
      return String(text || '').replace(/\s*\|\s*/g, '              |              ');
    }
    function normalizeFooterTemplate(template={}){
      const legacyPrefix = 'المرصد الثقافي';
      const previousPrefix = 'تطوير: إدارة المرصد الثقافي';
      const currentPrefix = 'تطوير : إدارة المرصد الثقافي';
      const legacyAgency = 'وكالة الإستراتيجيات والسياسات الثقافية';
      const agency = 'وكالة الاستراتيجيات والسياسات الثقافية';
      const normalized = {...(template || {})};
      const storedPrefix = String(normalized.footer_prefix || '').trim();
      const knownPrefixes = [legacyPrefix, previousPrefix, currentPrefix];
      if(knownPrefixes.includes(storedPrefix)) normalized.footer_prefix = currentPrefix;
      const footerParts = String(normalized.footer_text || '').split(/\s*\|\s*/);
      const firstPart = String(footerParts[0] || '').trim();
      if(knownPrefixes.includes(firstPart) || knownPrefixes.includes(storedPrefix)){
        const storedAgency = String(footerParts[1] || '').trim();
        const hasAgency = storedAgency === agency || storedAgency === legacyAgency;
        let monthYear = String(footerParts[hasAgency ? 2 : 1] || normalized.month_year || normalized.month_year_override || '').trim();
        if(monthYear && !monthYear.endsWith(' م')) monthYear += ' م';
        const rawIssue = String(footerParts[hasAgency ? 3 : 2] || normalized.issue_label || '').trim();
        const issueLabel = rawIssue.replace(/^الإصـ*دار\s*/, '').trim();
        normalized.footer_text = [
          currentPrefix,
          agency,
          monthYear,
          issueLabel ? `الإصدار ${issueLabel}` : ''
        ].filter(Boolean).join('\t\t|\t\t');
      }
      return normalized;
    }
    function updateNewsletterFooter(){
      const footer = document.querySelector('.page-footer');
      if(!footer) return;
      footer.textContent = formatFooterSeparators(state.template?.footer_text || t('footerText'));
    }
    function refreshLandingStepLabels(){
      const steps = currentLandingSteps();
      if(els.splashSteps){
        while(els.splashSteps.children.length < steps.length){
          const item = document.createElement('div');
          item.className = 'splash-step';
          item.dataset.step = String(els.splashSteps.children.length);
          const dot = document.createElement('span');
          dot.className = 'splash-step-dot';
          const copy = document.createElement('div');
          copy.className = 'splash-step-copy';
          const label = document.createElement('div');
          label.className = 'splash-step-label';
          const time = document.createElement('div');
          time.className = 'splash-step-time';
          copy.append(label, time);
          item.append(dot, copy);
          els.splashSteps.appendChild(item);
        }
        while(els.splashSteps.children.length > steps.length){
          els.splashSteps.lastElementChild?.remove();
        }
      }
      els.splashSteps?.querySelectorAll('.splash-step').forEach((item, index) => {
        item.dataset.step = String(index);
        const label = item.querySelector('.splash-step-label');
        if(label) label.textContent = steps[index] || '';
      });
    }
    function updateSplashStatusForLanguage(){
      if(els.splashError) els.splashError.textContent = els.splash?.classList.contains('error') ? t('splashErrorDetailed') : t('splashError');
      if(els.splashTitle){
        els.splashTitle.textContent = els.splash?.classList.contains('loading') ? t('loadingNewsletter') : t('splashTitle');
      }
      if(!els.splashStatus) return;
      if(els.splash?.classList.contains('error')){
        els.splashStatus.textContent = t('splashStatusError');
        return;
      }
      if(landingProgress?.done){
        els.splashStatus.textContent = t('doneOpening');
        return;
      }
      if(landingProgress?.running || els.splash?.classList.contains('loading')){
        els.splashStatus.textContent = currentLandingSteps()[landingProgress.step] || t('loadingNewsletter');
        setLandingProgressFromBackend(landingProgress.lastBackendProgress);
        return;
      }
      els.splashStatus.textContent = t('splashIntro');
    }
    function applyLanguage(){
      state.language = 'ar';
      localStorage.setItem(LANGUAGE_KEY, 'ar');
      document.documentElement.lang = state.language;
      document.documentElement.dir = 'rtl';
      document.title = t('splashTitle');
      document.body.classList.remove('lang-en');
      document.body.classList.add('lang-ar');
      updateStaticLanguageText();
      refreshLandingStepLabels();
      updateSplashStatusForLanguage();
      updateNewsletterTitle();
      if(state.items.length || state.courses.length || state.movies.length) render();
    }

    function bidiTitleHtml(v=''){
      const value = String(v || '');
      const latinParentheses = /\([^()\r\n]*[A-Za-z0-9][^()\r\n]*\)/g;
      let html = '';
      let cursor = 0;
      for(const match of value.matchAll(latinParentheses)){
        html += escapeHtml(value.slice(cursor, match.index));
        // Unicode LTR isolate/PDI keeps mixed Arabic/Latin parentheses ordered
        // without adding inline elements that can confuse Chrome line-clamp.
        html += `&#x2066;${escapeHtml(match[0])}&#x2069;`;
        cursor = match.index + match[0].length;
      }
      return html + escapeHtml(value.slice(cursor));
    }
    function mixedBidiTitleClass(v=''){
      const groups = String(v || '').match(/\([^()\r\n]*[A-Za-z0-9][^()\r\n]*\)/g) || [];
      return groups.length > 1 && String(v || '').length > 40 ? ' mixed-bidi-title' : '';
    }
