function levelMarkup(level=''){
      const normalized = String(level||'').trim().toLowerCase();
      let active=1,label=t('beginner');
      if(normalized.includes('متوسط')||normalized.includes('intermediate')){active=2;label=t('intermediate');}
      if(normalized.includes('متقدم')||normalized.includes('advanced')){active=3;label=t('advanced');}
      return {label,dots:`<span class="level-dots">${[1,2,3].map(i=>`<span class="${i<=active?'active':''}"></span>`).join('')}</span>`};
    }
    function activeLevelContext(data=state){
      const selected = (data.selectedLevels || ['all']).map(normalizeLevelName).filter(Boolean);
      const levels = selected.filter(level=>level !== 'all').sort();
      return selected.includes('all') || !levels.length || levels.length >= 3 ? 'all' : levels.join('+');
    }
    function replacementContextKey(section, index, data=state){
      return `mode-${newsViewCount(data)}:${data.feature_mode || 'course'}:level-${activeLevelContext(data)}:${section}:${index}`;
    }
    function compactHistoryItem(item={}){
      return {
        id: item.id || '',
        title: item.title || '',
        url: item.url || '',
        source: item.source || '',
        source_id: item.source_id || ''
      };
    }
    function refillHistoryState(section, index){
      const key = replacementContextKey(section, index);
      if(!state.card_refill_history[key]){
        state.card_refill_history[key] = {
          attempts: 0,
          tried_urls: [],
          tried_titles: [],
          tried_source_ids: [],
          tried_items: [],
          used_queries: []
        };
      }
      return state.card_refill_history[key];
    }
    function rememberTriedReplacement(section, index, item){
      if(!item) return;
      const history = refillHistoryState(section, index);
      history.attempts = Number(history.attempts || 0) + 1;
      if(item.url && !history.tried_urls.includes(item.url)) history.tried_urls.push(item.url);
      if(item.title && !history.tried_titles.includes(item.title)) history.tried_titles.push(item.title);
      if(item.source_id && !history.tried_source_ids.includes(item.source_id)) history.tried_source_ids.push(item.source_id);
      const compact = compactHistoryItem(item);
      const key = `${compact.id}|${compact.url}|${compact.title}`;
      const hasItem = history.tried_items.some(entry => `${entry.id}|${entry.url}|${entry.title}` === key);
      if(!hasItem) history.tried_items.push(compact);
      history.tried_items = history.tried_items.slice(-40);
      history.tried_urls = history.tried_urls.slice(-40);
      history.tried_titles = history.tried_titles.slice(-40);
      history.tried_source_ids = history.tried_source_ids.slice(-40);
    }
    function visibleNewsList(){
      // In 4/6 mode the rendered news can come from news_bank/all_items rather
      // than state.items, so replacement/navigation must read the same visible
      // list the user is looking at.
      return displayItemsForRender(state).news || state.items || [];
    }
    function getSectionList(section){
      if(section === 'items') return visibleNewsList();
      if(section === 'courses') return displayItemsForRender(state).courses || state.courses || [];
      if(section === 'movies'){
        const featureMovie = state.feature_mode === 'movie' && state.feature_item?.type === 'movie'
          ? state.feature_item
          : null;
        const current = state.movieViewOverride || featureMovie || (state.movies || [])[0];
        return current ? [current] : [];
      }
      return [];
    }
    function cardNavState(section, index){
      const key = replacementContextKey(section, index);
      if(!state.cardNav[key]) state.cardNav[key] = {prev:[], next:[], rejected:[]};
      return state.cardNav[key];
    }
    function cardNavButtons(section, id, index){
      const nav = cardNavState(section, index);
      const pending = Boolean(state.cardNavPending?.[replacementContextKey(section, index)]);
      const safeSection = escapeHtml(section);
      const safeId = escapeHtml(id || '');
      const disabledBack = (!nav.prev.length || pending) ? ' disabled' : '';
      const disabledForward = pending ? ' disabled' : '';
      return `<div class="card-nav">
        <button class="card-nav-btn" type="button" data-card-action="nav-back" data-target-section="${safeSection}" data-target-id="${safeId}" data-target-index="${index}" aria-label="${escapeHtml(t('cardBack'))}"${disabledBack}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M9 18l6-6-6-6"/></svg></button>
        <button class="card-nav-btn" type="button" data-card-action="nav-forward" data-target-section="${safeSection}" data-target-id="${safeId}" data-target-index="${index}" aria-label="${escapeHtml(t('cardForward'))}"${disabledForward}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M15 18l-6-6 6-6"/></svg></button>
      </div>`;
    }
    function hasPreviousCard(section, index=0){
      return Number(state.previous_counts?.[section] || 0) > Number(index || 0);
    }
    function cardActionButtons(section, id, index=0){
      const safeSection = escapeHtml(section);
      const safeId = escapeHtml(id || '');
      return `<button type="button" data-card-action="ai" data-target-section="${safeSection}" data-target-id="${safeId}" aria-label="${escapeHtml(t('aiPrompt'))}"><span class="card-tool-ai">AI</span></button>
          <button type="button" data-card-action="edit" data-target-section="${safeSection}" data-target-id="${safeId}" aria-label="${escapeHtml(t('edit'))}"><span class="card-tool-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg></span></button>
          <button type="button" data-card-action="delete" data-target-section="${safeSection}" data-target-id="${safeId}" data-target-index="${index}" aria-label="${escapeHtml(t('delete'))}"><span class="card-tool-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M7 7l1 13h8l1-13"/><path d="M10 11v5M14 11v5"/></svg></span></button>`;
    }
    function newsCardMarkup(item, index=0){
      return `<article class="news-card ${state.selected?.id===item.id && state.selected?.section==='items'?'selected':''}" data-id="${escapeHtml(item.id)}" data-section="items" data-url="${escapeHtml(item.url||'#')}" draggable="true">
        ${logoMarkup(item, 'items', item.id)}
        <div class="card-head"><h3 class="card-title${mixedBidiTitleClass(item.title)}" dir="rtl">${bidiTitleHtml(item.title)}</h3><div class="card-title-line"></div></div>
        <p class="card-text">${escapeHtml(item.text)}</p>
        <a class="card-source" href="${escapeHtml(item.url||'#')}" target="_blank" rel="noopener noreferrer"><span>${t('source')}</span><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7"/><path d="M7 7h10v10"/></svg></a>
        <div class="card-popover">
          ${cardNavButtons('items', item.id, index)}
          ${cardActionButtons('items', item.id, index)}
        </div>
      </article>`;
    }
    function featureCardMarkup(item, section, index=0){
      const level = levelMarkup(item.level);
      return `<article class="feature-card ${section==='courses'?'draggable-course ':''}${state.selected?.id===item.id && state.selected?.section===section?'selected':''}" data-id="${escapeHtml(item.id)}" data-section="${section}" data-url="${escapeHtml(item.url||'#')}"${section==='courses'?' draggable="true"':''}>
        ${logoMarkup(item, section, item.id)}
        <div class="feature-header"><h3 class="card-title" dir="rtl">${bidiTitleHtml(item.title)}</h3><div class="card-title-line"></div><p class="card-text">${escapeHtml(item.text)}</p></div>
        <div class="feature-meta">
          <a class="feature-link" href="${escapeHtml(item.url||'#')}" target="_blank" rel="noopener noreferrer">${t('courseOpen')} <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17L17 7"/><path d="M7 7h10v10"/></svg></a>
          <span>${t('level')}: ${level.label || t('beginner')}</span>${level.dots}
        </div>
        <div class="card-popover">
          ${cardNavButtons(section, item.id, index)}
          ${cardActionButtons(section, item.id, index)}
        </div>
      </article>`;
    }
    function movieCardMarkup(item, index=0){
      const title = escapeHtml(item.title || 'Ex Machina');
      const text = escapeHtml(item.text || 'A film about artificial intelligence and its relationship with people.');
      const posterSrc = item.logo_override_url || item.manual_logo_url || item.poster || item.image || '';
      const poster = posterSrc ? `<img src="${escapeHtml(posterSrc)}" alt="">` : '<div style="width:100%;height:100%;background:linear-gradient(135deg,#6c4a37,#161616);"></div>';
      const sprockets = Array.from({length:5}).map(()=>'<span></span>').join('');
      return `<article class="feature-card movie-card ${state.selected?.id===(item.id||'feature-movie') && state.selected?.section==='movies'?'selected':''}" data-id="${escapeHtml(item.id||'feature-movie')}" data-section="movies" data-url="${escapeHtml(item.url||'#')}">
        <div class="movie-shell">
          <div class="movie-side">${sprockets}</div>
          <div class="movie-info">
            <h3 class="movie-title">${title}</h3>
            <p class="movie-text">${text}</p>
          </div>
          <div class="movie-poster-wrap"><div class="movie-poster">${poster}</div></div>
          <div class="movie-side">${sprockets}</div>
        </div>
        <div class="card-popover">
          ${cardNavButtons('movies', item.id || 'feature-movie', index)}
          ${cardActionButtons('movies', item.id || 'feature-movie', index)}
        </div>
      </article>`;
    }
    function progressKey(section, index){ return `${section}:${index}`; }
    function cardProgressMarkup(section, index){
      return `<article class="card-progress" data-progress-section="${escapeHtml(section)}" data-progress-index="${index}" aria-busy="true">
        <div class="card-loading-dots" aria-label="${escapeHtml(t('progressReplacing'))}"><span></span><span></span><span></span></div>
      </article>`;
    }
    function cardProgressDetailMarkup(section, index){
      const progress = state.cardProgress[progressKey(section, index)] || {};
      const steps = t('progressSteps');
      const active = Math.max(0, Math.min(progress.step || 0, steps.length - 1));
      const completed = Math.max(0, Math.min(progress.completed || 0, steps.length));
      const percent = progress.failed ? 100 : Math.round((completed / steps.length) * 100);
      const title = progress.failed ? t('noSuitableReplacement') : t(progress.titleKey || 'progressReplacing');
      const elapsed = progress.startedAt ? Math.max(0, (Date.now() - progress.startedAt) / 1000) : 0;
      const elapsedText = elapsed ? `${elapsed.toFixed(1)}s` : '';
      const serverStages = Array.isArray(progress.serverStages) ? progress.serverStages.slice(-5) : [];
      const progressStepElapsed = (stepIndex)=>{
        const frozen = Number(progress.stepElapsed?.[stepIndex]);
        if(Number.isFinite(frozen)) return frozen;
        const started = Number(progress.stepStartedAt?.[stepIndex]);
        if(stepIndex === active && Number.isFinite(started)) return Math.max(0, (Date.now() - started) / 1000);
        return null;
      };
      const serverMarkup = serverStages.length ? `<div class="card-progress-server">
        ${serverStages.map(stage=>{
          const label = refillStageLabel(stage.stage);
          const meta = stage.elapsed_seconds ? `${Number(stage.elapsed_seconds).toFixed(1)}s` : '';
          return `<div class="card-progress-server-row"><span class="card-progress-server-stage">${escapeHtml(label)}</span><span class="card-progress-server-meta">${escapeHtml(meta)}</span></div>`;
        }).join('')}
      </div>` : '';
      const className = `card-progress-detail ${progress.failed ? 'failed' : ''}`;
      const retryAction = progress.failed ? `<button class="tip-btn" type="button" data-card-action="retry-progress" data-target-section="${escapeHtml(section)}" data-target-index="${index}">${escapeHtml(state.language === 'ar' ? 'إعادة المحاولة' : 'Retry')}</button>` : '';
      const actions = `<div class="card-progress-actions">
        ${retryAction}
        <button class="tip-btn secondary" type="button" data-card-action="cancel-progress" data-target-section="${escapeHtml(section)}" data-target-index="${index}">${escapeHtml(t('cancel'))}</button>
      </div>`;
      return `<aside class="${className}" data-progress-detail-section="${escapeHtml(section)}" data-progress-detail-index="${index}">
        <div class="card-progress-head">
          <h3 class="card-progress-title">${escapeHtml(title)}</h3>
          <span class="card-progress-time">${escapeHtml(elapsedText)}</span>
        </div>
        <div class="card-progress-steps">
          ${steps.map((label, stepIndex)=>{
            const stepTime = progressStepElapsed(stepIndex);
            const stepStatus = stepIndex < completed ? 'done' : stepIndex === active ? 'active' : '';
            return `<div class="card-progress-step ${stepStatus}"><span class="card-progress-dot"></span><span class="card-progress-step-label">${escapeHtml(label)}</span><span class="card-progress-step-time">${escapeHtml(formatStepElapsed(stepTime))}</span></div>`;
          }).join('')}
        </div>
        ${serverMarkup}
        <div class="card-progress-bar"><div class="card-progress-fill" style="width:${percent}%"></div></div>
        ${actions}
      </aside>`;
    }
    function refillStageLabel(stage){
      const labelsAr = {
        searching:'فحص البدائل الجاهزة',
        source_fetch:'جلب أخبار جديدة',
        quality_check:'استلام نتيجة البحث',
        duplicate_check:'فحص التكرار',
        preparing_content:'تجهيز البديل',
        updating_card:'تحديث البطاقة',
        plan_b_recovery:'تجربة بديل آخر',
        completed:'تم التحديث',
        failed:'لم يتم العثور على بديل'
      };
      const labelsEn = {
        searching:'Checking saved alternatives',
        source_fetch:'Fetching new stories',
        quality_check:'Reading search result',
        duplicate_check:'Duplicate check',
        preparing_content:'Preparing replacement',
        updating_card:'Updating card',
        plan_b_recovery:'Trying another option',
        completed:'Updated',
        failed:'No replacement found'
      };
      return (state.language === 'ar' ? labelsAr : labelsEn)[stage] || stage || '';
    }
    function progressStepForRefillStage(stage){
      if(stage === 'searching') return 0;
      if(stage === 'quality_check') return 1;
      if(['duplicate_check','plan_b_recovery'].includes(stage)) return 2;
      if(stage === 'preparing_content') return 3;
      if(['updating_card','completed','failed'].includes(stage)) return 4;
      return 0;
    }
    function applyRefillProgress(section, index, data, titleKey='progressReplacing'){
      const key = progressKey(section, index);
      const stages = Array.isArray(data?.refill_stages) ? data.refill_stages : data?.refill ? [data.refill] : [];
      if(!stages.length) return;
      const last = stages[stages.length - 1] || {};
      const step = Math.min(progressStepForRefillStage(last.stage), t('progressSteps').length - 1);
      const existing = state.cardProgress[key] || {startedAt:Date.now(), titleKey, stepStartedAt:{0:Date.now()}, stepElapsed:{}};
      const now = Date.now();
      const stepStartedAt = {...(existing.stepStartedAt || {})};
      const stepElapsed = {...(existing.stepElapsed || {})};
      const previousStep = Number.isFinite(Number(existing.step)) ? Number(existing.step) : 0;
      if(!Number.isFinite(Number(stepStartedAt[previousStep]))) stepStartedAt[previousStep] = existing.startedAt || now;
      if(step !== previousStep && !Number.isFinite(Number(stepElapsed[previousStep]))){
        stepElapsed[previousStep] = Math.max(0, (now - Number(stepStartedAt[previousStep])) / 1000);
      }
      if(!Number.isFinite(Number(stepStartedAt[step]))) stepStartedAt[step] = now;
      if(last.stage === 'completed' || last.stage === 'failed'){
        stepElapsed[step] = Math.max(0, (now - Number(stepStartedAt[step])) / 1000);
      }
      state.cardProgress[key] = {
        ...existing,
        titleKey: existing.titleKey || titleKey,
        step,
        stepStartedAt,
        stepElapsed,
        completed: Math.max(existing.completed || 0, Math.min(step + (last.stage === 'completed' ? 1 : 0), t('progressSteps').length)),
        elapsedSeconds: Number(last.elapsed_seconds),
        serverStages: stages,
        finished: last.stage === 'completed',
        failed: last.stage === 'failed' || Boolean(data?.success === false && !data?.item),
      };
      render();
      return last.stage || '';
    }
    async function pollSingleRefillProgress(section, index, titleKey='progressReplacing'){
      try{
        const data = await request(`${API_BASE}/refill/progress`);
        if(!data || data.section !== section || Number(data.index) !== Number(index)) return '';
        const key = progressKey(section, index);
        const localStartedAt = Number(state.cardProgress[key]?.startedAt || 0) / 1000;
        if(Number(data.started_at || 0) + 1 < localStartedAt) return '';
        return applyRefillProgress(section, index, data, titleKey) || '';
      }catch(error){
        console.warn('single refill progress polling failed', error);
        return '';
      }
    }
    function wait(ms){ return new Promise(resolve=>setTimeout(resolve, ms)); }
    function visibleListWithProgress(section, items, limit, markup){
      const output = [];
      for(let index = 0; index < limit; index++){
        if(items[index]){
          output.push(markup(items[index], index));
        }
      }
      return output.join('');
    }
    function normalizeLevelName(level){
      const text = String(level || '').toLowerCase().trim();
      if(['beginner','intermediate','advanced','all'].includes(text)) return text;
      if(text.includes('مبتدئ')) return 'beginner';
      if(text.includes('متوسط')) return 'intermediate';
      if(text.includes('متقدم')) return 'advanced';
      if(text.includes('عام') || text.includes('الكل')) return 'all';
      return '';
    }
    function replacementLevels(data=state){
      const context = activeLevelContext(data);
      return context === 'all' ? null : new Set(context.split('+').filter(Boolean));
    }
    function itemMatchesReplacementLevel(item={}, data=state){
      const allowed = replacementLevels(data);
      if(!allowed) return true;
      const level = normalizeLevelName(item.level || item.course_level || item.difficulty || '');
      return Boolean(level && allowed.has(level));
    }
    function requestedReplacementLevel(data=state){
      const allowed = replacementLevels(data);
      return allowed && allowed.size === 1 ? [...allowed][0] : '';
    }
    function bankList(bank, level){
      return Array.isArray(bank?.[level]) ? bank[level] : [];
    }
    function newsViewCount(data=state){
      return Number(data.newsDisplayCount) === 6 ? 6 : 4;
    }
    function cloneViewData(value){
      try{return JSON.parse(JSON.stringify(value));}catch{return value;}
    }
    function savedViewModeKey(data=state){
      return `mode-${newsViewCount(data)}-${data.feature_mode || 'course'}`;
    }
    function savedViewLevelKey(data=state){ return activeLevelContext(data); }
    function savedViewForContext(data=state){
      return data.saved_views?.[savedViewModeKey(data)]?.[savedViewLevelKey(data)] || null;
    }
    function captureCurrentSavedView(){
      const view = displayItemsForRender(state);
      const featureItem = state.feature_mode === 'movie'
        ? (state.movieViewOverride || (state.movies || [])[0] || null)
        : ((view.courses || [])[0] || null);
      return cloneViewData({
        items:(view.news || []).slice(0, newsViewCount(state)),
        courses:(view.courses || []).slice(0,2),
        movies:state.feature_mode === 'movie' && featureItem ? [featureItem] : [],
        feature_item:featureItem,
        feature_mode:state.feature_mode || 'course',
        saved_at:new Date().toISOString()
      });
    }
    function commitCurrentViewToSavedViews(){
      const modeKey = savedViewModeKey(state);
      const levelKey = savedViewLevelKey(state);
      const saved = cloneViewData(state.saved_views || {});
      if(!saved[modeKey] || typeof saved[modeKey] !== 'object') saved[modeKey] = {};
      saved[modeKey][levelKey] = captureCurrentSavedView();
      state.saved_views = saved;
      return saved[modeKey][levelKey];
    }
    function markCurrentViewAsDefault(){
      state.defaultView = {
        news_display_count:newsViewCount(state),
        selected_levels:[...(state.selectedLevels || ['all'])],
        feature_mode:state.feature_mode || 'course',
        mode_key:savedViewModeKey(state),
        level_key:savedViewLevelKey(state),
        saved_at:new Date().toISOString()
      };
      return state.defaultView;
    }
    function clearContextViewOverrides(){
      state.newsViewOverride = null;
      state.coursesViewOverride = null;
      state.movieViewOverride = null;
    }
    function restoreSavedViewForContext(){
      clearContextViewOverrides();
      const saved = savedViewForContext(state);
      if(!saved) return false;
      if(Array.isArray(saved.items) && saved.items.length){
        state.newsViewOverride = cloneViewData(saved.items);
      }
      if(Array.isArray(saved.courses) && saved.courses.length){
        state.coursesViewOverride = cloneViewData(saved.courses);
      }
      // Films are global across levels. Level changes may restore news/course
      // layouts, but they must not replace the currently selected film.
      if(state.feature_mode === 'movie'){
        const movie = (state.movies || [])[0] || null;
        if(movie){
          state.movieViewOverride = cloneViewData(movie);
          state.feature_item = cloneViewData(movie);
        }
      }else{
        const course = (saved.courses || [])[0] || saved.feature_item || null;
        if(course) state.feature_item = cloneViewData(course);
      }
      return true;
    }
    function uniqueById(items=[]){
      const seen = new Set();
      const output = [];
      (Array.isArray(items) ? items : []).forEach(item=>{
        const key = String(item?.id || item?.url || item?.title || '');
        if(key && seen.has(key)) return;
        if(key) seen.add(key);
        output.push(item);
      });
      return output;
    }
    function fillNewsToCount(primary=[], data=state, count=4){
      // Level-balanced view fix: if one level is short (for example only one
      // Advanced item), fill the 4/6 visible cards from the remaining saved
      // news bank instead of rendering fewer cards on the page.
      const fallback = uniqueById([
        ...bankList(data.news_bank, 'beginner'),
        ...bankList(data.news_bank, 'intermediate'),
        ...bankList(data.news_bank, 'advanced'),
        ...(Array.isArray(data.all_items) ? data.all_items : []),
        ...(Array.isArray(data.items) ? data.items : [])
      ]);
      return uniqueById([...(primary || []), ...fallback]).slice(0,count);
    }
    function recommendedBankView(data=state){
      const recommended = data.recommended_view || {};
      const count = newsViewCount(data);
      const allBalancedNews = uniqueById([
        ...bankList(data.news_bank, 'beginner').slice(0, count === 6 ? 2 : 2),
        ...bankList(data.news_bank, 'intermediate').slice(0, count === 6 ? 2 : 1),
        ...bankList(data.news_bank, 'advanced').slice(0, count === 6 ? 2 : 1)
      ]);
      return {
        news: count === 4 && Array.isArray(recommended.news) && recommended.news.length
          ? fillNewsToCount(recommended.news.slice(0,4), data, 4)
          : fillNewsToCount(allBalancedNews, data, count),
        courses: Array.isArray(recommended.courses) && recommended.courses.length ? recommended.courses : [
          ...bankList(data.courses_bank, 'beginner').slice(0,1),
          ...bankList(data.courses_bank, 'intermediate').slice(0,1)
        ]
      };
    }
    function filteredBankView(data=state){
      // Level filtering changes only the visible view from the already saved bank.
      // It never calls Generate or refetches news/courses.
      const selected = (data.selectedLevels || ['all']).map(normalizeLevelName).filter(Boolean);
      const active = selected.includes('all') || !selected.length ? ['all'] : selected.filter(level=>level !== 'all');
      if(active.includes('all') || active.length >= 3) return recommendedBankView(data);
      const count = newsViewCount(data);
      if(active.length === 1){
        const level = active[0];
        const pool = uniqueById([
          ...bankList(data.news_bank, level),
          ...bankList(data.news_bank, 'beginner'),
          ...bankList(data.news_bank, 'intermediate'),
          ...bankList(data.news_bank, 'advanced')
        ]);
        return {
          news: fillNewsToCount(pool, data, count),
          courses: bankList(data.courses_bank, level).slice(0,2)
        };
      }
      const news = [];
      const courses = [];
      active.slice(0,2).forEach(level=>{
        news.push(...bankList(data.news_bank, level).slice(0, count === 6 ? 3 : 2));
        courses.push(...bankList(data.courses_bank, level).slice(0,1));
      });
      return {news: fillNewsToCount(news, data, count), courses: courses.slice(0,2)};
    }
    function displayItemsForRender(data=state){
      const view = filteredBankView(data);
      const count = newsViewCount(data);
      // Use all_items as the fallback source because state.items may already be
      // trimmed to the current toolbar count. This lets switching from 4 to 6
      // restore real extra cards instead of only increasing the page height.
      const fallbackNews = Array.isArray(data.all_items) && data.all_items.length ? data.all_items : (data.items || []);
      // Manual reorder fix: when the user drags cards, keep rendering that
      // reordered visible view instead of letting news_bank rebuild the old order.
      const manualNews = data === state && Array.isArray(state.newsViewOverride) ? state.newsViewOverride : null;
      const manualCourses = data === state && Array.isArray(state.coursesViewOverride) ? state.coursesViewOverride : null;
      return {
        news: manualNews && manualNews.length ? fillNewsToCount(manualNews, data, count) : (view.news && view.news.length ? view.news.slice(0,count) : fallbackNews.slice(0,count)),
        courses: manualCourses && manualCourses.length ? manualCourses.slice(0,2) : (view.courses && view.courses.length ? view.courses : (data.courses || []).slice(0,2))
      };
    }
    function applySelectedLevelView(){
      // Keep edit/replace/reorder actions aligned with the currently displayed
      // filtered view while preserving the full banks separately.
      const view = displayItemsForRender(state);
      if(view.news?.length) state.items = view.news;
      if(view.courses?.length) state.courses = view.courses;
    }
    function levelFilterLabel(){
      const selected = state.selectedLevels || ['all'];
      if(selected.includes('all') || !selected.length) return 'المستوى';
      const labels = {beginner:'مبتدئ', intermediate:'متوسط', advanced:'متقدم'};
      return selected.map(level=>labels[level] || level).join(' + ');
    }
    function renderFloatingProgress(){
      if(!els.floatingProgressHost) return;
      const key = Object.keys(state.cardProgress)[0];
      if(!key){
        els.floatingProgressHost.innerHTML = '';
        return;
      }
      const [section, indexText] = key.split(':');
      els.floatingProgressHost.innerHTML = cardProgressDetailMarkup(section, Number(indexText || 0));
    }
    function renderNewsletter(data=state, options={}){
      const page = options.page || els.page;
      if(!page) return;
      const newsGrid = page.querySelector('.news-grid');
      const featureTitle = page.querySelector('.section-divider h2');
      const featureList = page.querySelector('.feature-list');
      const featureSwitches = page.querySelectorAll('.switch-btn');
      const featureMode = data.feature_mode || 'course';
      const visibleBankView = displayItemsForRender(data);
      const count = newsViewCount(data);
      page.classList.toggle('news-count-6', count === 6);
      page.classList.toggle('news-count-4', count !== 6);
      if(newsGrid) newsGrid.innerHTML = visibleListWithProgress('items', visibleBankView.news || [], count, (item,index)=>newsCardMarkup(item,index));
      if(featureTitle) featureTitle.textContent = featureMode === 'movie' ? t('filmSection') : t('courseSection');
      featureSwitches.forEach(btn=>btn.classList.toggle('active', btn.dataset.featureMode === featureMode));
      if(featureMode === 'movie'){
        const featureMovie = data.feature_item?.type === 'movie' ? data.feature_item : null;
        const movie = (data === state ? state.movieViewOverride : null) || featureMovie || (data.movies || [])[0] || {};
        if(featureList) featureList.innerHTML = movieCardMarkup(movie, 0);
        featureList?.classList.add('movie-mode');
        featureList?.classList.remove('course-mode');
        page.classList.add('movie-layout');
        page.classList.remove('course-layout');
      } else {
        if(featureList) featureList.innerHTML = visibleListWithProgress('courses', visibleBankView.courses || [], 2, (item,index)=>featureCardMarkup(item,'courses',index));
        featureList?.classList.remove('movie-mode');
        featureList?.classList.add('course-mode');
        page.classList.add('course-layout');
        page.classList.remove('movie-layout');
      }
      return page;
    }
    function render(){
      renderNewsletter(state, {page: els.page});
      renderFloatingProgress();
      bindSelection();
      if(state.isAdmin) bindDragAndDrop();
      bindLevelFilter();
      bindNewsCountFilter();
      if(state.isAdmin) bindTips();
      applyRolePermissions();
      if(state.onboarding) showTip(state.onboarding);
    }
    function bindLevelFilter(){
      if(!els.levelFilter) return;
      const active = new Set(state.selectedLevels || ['all']);
      els.levelFilter.classList.toggle('open', Boolean(state.levelFilterOpen));
      const toggle = els.levelFilter.querySelector('#levelFilterToggle');
      if(toggle){
        toggle.setAttribute('aria-expanded', state.levelFilterOpen ? 'true' : 'false');
        const label = toggle.querySelector('span');
        if(label) label.textContent = levelFilterLabel();
        toggle.onclick = event => {
          event.stopPropagation();
          state.levelFilterOpen = !state.levelFilterOpen;
          state.newsCountFilterOpen = false;
          if(state.levelFilterOpen) showTip(null);
          render();
        };
      }
      els.levelFilter.querySelectorAll('.level-filter-option[data-level-filter]').forEach(button=>{
        const level = button.dataset.levelFilter;
        button.classList.toggle('active', active.has(level));
        const check = button.querySelector('.level-filter-check');
        if(check) check.textContent = active.has(level) ? '✓' : '';
        button.onclick = () => {
          // The filter only swaps visible cards from news_bank/courses_bank.
          // It intentionally does not call the backend or regenerate content.
          if(level === 'all'){
            state.selectedLevels = ['all'];
          }else{
            const next = new Set((state.selectedLevels || []).filter(value=>value !== 'all'));
            next.has(level) ? next.delete(level) : next.add(level);
            const values = [...next].filter(value=>['beginner','intermediate','advanced'].includes(value));
            state.selectedLevels = values.length ? values : ['all'];
            if(state.selectedLevels.length >= 3) state.selectedLevels = ['all'];
          }
          if(!restoreSavedViewForContext()) applySelectedLevelView();
          state.levelFilterOpen = false;
          render();
        };
      });
      bindToolbarFilterOutsideClose();
    }
    function bindNewsCountFilter(){
      if(!els.newsCountFilter) return;
      const activeCount = newsViewCount(state);
      els.newsCountFilter.classList.toggle('open', Boolean(state.newsCountFilterOpen));
      const toggle = els.newsCountFilter.querySelector('#newsCountFilterToggle');
      if(toggle){
        toggle.setAttribute('aria-expanded', state.newsCountFilterOpen ? 'true' : 'false');
        const label = toggle.querySelector('span');
        if(label) label.textContent = `${activeCount} أخبار`;
        toggle.onclick = event => {
          event.stopPropagation();
          state.newsCountFilterOpen = !state.newsCountFilterOpen;
          state.levelFilterOpen = false;
          if(state.newsCountFilterOpen) showTip(null);
          render();
        };
      }
      els.newsCountFilter.querySelectorAll('[data-news-count]').forEach(button=>{
        const count = Number(button.dataset.newsCount) === 6 ? 6 : 4;
        const active = activeCount === count;
        button.classList.toggle('active', active);
        const check = button.querySelector('.level-filter-check');
        if(check) check.textContent = active ? '✓' : '';
        button.onclick = () => {
          // News count only changes the visible card count and page height.
          // It does not generate, fetch, or edit the saved content bank.
          state.newsDisplayCount = count;
          if(!restoreSavedViewForContext()) applySelectedLevelView();
          state.newsCountFilterOpen = false;
          render();
        };
      });
      bindToolbarFilterOutsideClose();
    }
    function bindToolbarFilterOutsideClose(){
      if(!state.toolbarFilterOutsideBound){
        document.addEventListener('click', event => {
          const insideLevel = els.levelFilter && els.levelFilter.contains(event.target);
          const insideCount = els.newsCountFilter && els.newsCountFilter.contains(event.target);
          if(insideLevel || insideCount) return;
          if(state.levelFilterOpen || state.newsCountFilterOpen){
            state.levelFilterOpen = false;
            state.newsCountFilterOpen = false;
            render();
          }
        });
        state.toolbarFilterOutsideBound = true;
      }
    }
    function bindSelection(){
      document.querySelectorAll('[data-section][data-id]').forEach(card=>{
        card.addEventListener('click', e=>{
          if(e.target.closest('a')||e.target.closest('button')) return;
          state.selected = {section: card.dataset.section, id: card.dataset.id};
          state.onboarding = 'edit'; render();
        });
      });
      document.querySelectorAll('[data-card-action]').forEach(button=>{
        button.addEventListener('keydown', e=>{
          if(e.key !== 'Enter' && e.key !== ' ') return;
          e.preventDefault();
          button.click();
        });
        button.addEventListener('click', async e=>{
          e.stopPropagation();
          const card = button.closest('[data-section][data-id]');
          const action = button.dataset.cardAction;
          const section = button.dataset.targetSection || card?.dataset.section;
          const id = button.dataset.targetId || card?.dataset.id;
          if(!section) return;
          if(id) state.selected = {section, id};
          if(action==='edit') openEdit(section,id);
          if(action==='edit-logo'){
            if(Date.now() < Number(state.suppressLogoClickUntil || 0)) return;
            openLogoEditor(section,id);
          }
          if(action==='ai') openAi(section,id);
          if(action==='delete' && id) await deleteCard(section,id);
          if(action==='restore-previous') await restorePreviousCard(section, Number(button.dataset.targetIndex || 0));
          if(action==='nav-back') await navigateCard(section, id, Number(button.dataset.targetIndex || 0), -1);
          if(action==='nav-forward') await navigateCard(section, id, Number(button.dataset.targetIndex || 0), 1);
          if(action==='replace' && id) await replaceItem(id, section);
          if(action==='retry-progress'){
            const index = Number(button.dataset.targetIndex || 0);
            const list = getSectionList(section);
            await fetchMoreAlternative(section, list[index]?.id || id, index);
          }
          if(action==='cancel-progress') cancelCardProgress(section, Number(button.dataset.targetIndex || 0));
        });
      });
      document.removeEventListener('click', handleOutsideCardClick);
      document.addEventListener('click', handleOutsideCardClick);
    }
