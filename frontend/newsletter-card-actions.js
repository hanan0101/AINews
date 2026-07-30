function findVisibleIndex(section, id){
      const list = getSectionList(section);
      return list.findIndex(item => item.id === id);
    }
    function showCardProgress(section, index, titleKey='progressReplacing'){
      if(index < 0) return;
      const key = progressKey(section, index);
      if(state.cardProgressTimers[key]) clearInterval(state.cardProgressTimers[key]);
      state.cardProgress[key] = {step:0, completed:0, titleKey, failed:false, startedAt:Date.now(), lastAdvanceAt:Date.now(), stepStartedAt:{0:Date.now()}, stepElapsed:{}};
      const useServerProgress = titleKey === 'progressReplacing';
      if(useServerProgress) pollSingleRefillProgress(section, index, titleKey);
      state.cardProgressTimers[key] = setInterval(async ()=>{
        const current = state.cardProgress[key];
        if(!current || current.failed){
          clearInterval(state.cardProgressTimers[key]);
          delete state.cardProgressTimers[key];
          if(current?.failed){
            window.setTimeout(()=>hideCardProgress(section, index), 1400);
          }
          return;
        }
        if(useServerProgress){
          const lastStage = await pollSingleRefillProgress(section, index, titleKey);
          render();
          const updated = state.cardProgress[key];
          if(updated?.startedAt && Date.now() - Number(updated.startedAt) > 70000){
            clearInterval(state.cardProgressTimers[key]);
            delete state.cardProgressTimers[key];
            showReplacementFailedState(section, index);
            window.setTimeout(()=>hideCardProgress(section, index), 2200);
            return;
          }
          if(lastStage === 'completed' || updated?.finished){
            clearInterval(state.cardProgressTimers[key]);
            delete state.cardProgressTimers[key];
            window.setTimeout(()=>hideCardProgress(section, index), 650);
            return;
          }
          if(lastStage === 'failed' || updated?.failed){
            clearInterval(state.cardProgressTimers[key]);
            delete state.cardProgressTimers[key];
            window.setTimeout(()=>hideCardProgress(section, index), 1800);
            return;
          }
          return;
        }
        if(Date.now() - Number(current.lastAdvanceAt || current.startedAt || 0) < 2600){
          render();
          return;
        }
        const total = t('progressSteps').length;
        const nextCompleted = Math.min((current.completed || 0) + 1, Math.max(1, total - 1));
        state.cardProgress[key] = {
          ...current,
          lastAdvanceAt: Date.now(),
          completed: nextCompleted,
          step: Math.min(nextCompleted, total - 1),
        };
        render();
      }, 1000);
      render();
    }
    function hideCardProgress(section, index){
      const key = progressKey(section, index);
      if(state.cardProgressTimers[key]){
        clearInterval(state.cardProgressTimers[key]);
        delete state.cardProgressTimers[key];
      }
      state.cardProgressAbort[key]?.abort();
      delete state.cardProgressAbort[key];
      delete state.cardProgress[key];
      render();
    }
    async function cancelCardProgress(section, index){
      const key = progressKey(section, index);
      try{
        await request(`${API_BASE}/generation/cancel`, {method:'POST', body:'{}'});
      }catch(error){
        console.error(error);
      }
      state.cardProgressAbort[key]?.abort();
      delete state.cardProgressAbort[key];
      hideCardProgress(section, index);
    }
    function showReplacementFailedState(section, index){
      const key = progressKey(section, index);
      if(state.cardProgressTimers[key]){
        clearInterval(state.cardProgressTimers[key]);
        delete state.cardProgressTimers[key];
      }
      const existing = state.cardProgress[key] || {};
      state.cardProgress[key] = {...existing, step:t('progressSteps').length - 1, failed:true};
      render();
    }
    function updateCardAtIndex(section, index, newItem){
      if(index < 0 || !newItem) return;
      if(section === 'items'){
        // 4/6 news-count fix: update the visible news list first because card
        // replacement may target cards that came from all_items/news_bank.
        const visible = [...visibleNewsList()];
        const previous = visible[index];
        if(state.selected?.section === section && state.selected?.id === previous?.id){
          state.selected = {section, id:newItem.id};
        }
        if(index < visible.length) visible[index] = newItem;
        else visible.splice(index, 0, newItem);
        state.newsViewOverride = visible;
        state.items = visible.slice(0, newsViewCount(state));
        const replaceInPool = pool => {
          if(!Array.isArray(pool)) return pool;
          const previousId = previous?.id;
          const previousUrl = String(previous?.url || '').trim();
          const newId = newItem?.id;
          const newUrl = String(newItem?.url || '').trim();
          const nextPool = [...pool];
          const previousPoolIndex = nextPool.findIndex(item =>
            (previousId && item?.id === previousId)
            || (previousUrl && String(item?.url || '').trim() === previousUrl)
          );
          const existingNewIndex = nextPool.findIndex((item, poolIndex) =>
            poolIndex !== previousPoolIndex && (
              (newId && item?.id === newId)
              || (newUrl && String(item?.url || '').trim() === newUrl)
            )
          );
          if(previousPoolIndex >= 0){
            // A prepared alternative already belongs to the full pool. Swap it
            // with the visible card instead of deduping it away, so card 7+
            // remains available after success, failure, undo, and further edits.
            nextPool[previousPoolIndex] = newItem;
            if(existingNewIndex >= 0 && previous) nextPool[existingNewIndex] = previous;
          }else if(existingNewIndex < 0){
            nextPool.splice(Math.min(index, nextPool.length), 0, newItem);
          }
          return dedupeClientItems(nextPool);
        };
        state.all_items = replaceInPool(state.all_items || []);
        return;
      }
      if(section === 'courses'){
        const visible = [...getSectionList('courses')];
        const previous = visible[index];
        if(state.selected?.section === section && state.selected?.id === previous?.id){
          state.selected = {section, id:newItem.id};
        }
        if(index < visible.length) visible[index] = newItem;
        else visible.splice(index, 0, newItem);
        state.coursesViewOverride = dedupeClientItems(visible).slice(0,2);
        state.courses = dedupeClientItems([...visible, ...(state.courses || []), previous]);
        return;
      }
      if(section === 'movies'){
        const previous = getSectionList('movies')[0];
        if(state.selected?.section === section && state.selected?.id === previous?.id){
          state.selected = {section, id:newItem.id};
        }
        state.movieViewOverride = newItem;
        state.feature_item = newItem;
        state.movies = dedupeClientItems([newItem, ...(state.movies || []).filter(item=>item?.id !== newItem?.id)]);
        if(previous && previous.id !== newItem.id && !state.movies.some(item=>item.id === previous.id)) state.movies.push(previous);
      }
    }
    function restoreVisibleSectionAfterReload(section, visibleItems, index, persistedItem){
      const intended = (Array.isArray(visibleItems) ? visibleItems : []).filter(Boolean).slice();
      if(persistedItem){
        if(index < intended.length) intended[index] = persistedItem;
        else intended.splice(index, 0, persistedItem);
      }
      if(section === 'movies'){
        if(intended[0]) updateCardAtIndex(section, 0, intended[0]);
        return;
      }
      intended.forEach((entry, visibleIndex)=>updateCardAtIndex(section, visibleIndex, entry));
    }
    function captureVisibleEditorView(){
      return {
        items:[...getSectionList('items')],
        courses:[...getSectionList('courses')],
        movies:state.feature_mode === 'movie' ? [...getSectionList('movies')] : []
      };
    }
    function updateCapturedEditorItem(snapshot, section, itemId, updatedItem){
      if(!snapshot || !updatedItem) return;
      const list = Array.isArray(snapshot[section]) ? snapshot[section] : [];
      const index = list.findIndex(entry=>entry?.id === itemId || entry?.id === updatedItem?.id);
      if(index >= 0) list[index] = updatedItem;
    }
    function restoreCapturedEditorView(snapshot){
      if(!snapshot) return;
      restoreVisibleSectionAfterReload('items', snapshot.items || [], -1, null);
      restoreVisibleSectionAfterReload('courses', snapshot.courses || [], -1, null);
      if(state.feature_mode === 'movie' && snapshot.movies?.length){
        restoreVisibleSectionAfterReload('movies', snapshot.movies, -1, null);
      }
      render();
    }
    function isVisibleDuplicate(section, index, item){
      const url = String(item?.url || '').trim().toLowerCase();
      const title = String(item?.title || '').trim().toLowerCase();
      return getSectionList(section).some((entry, entryIndex) => {
        if(entryIndex === index) return false;
        if(item?.id && entry.id === item.id) return true;
        if(url && String(entry.url || '').trim().toLowerCase() === url) return true;
        if(title && String(entry.title || '').trim().toLowerCase() === title) return true;
        return false;
      });
    }
    function replacementToken(value){
      return String(value || '').trim().toLowerCase();
    }
    function addReplacementTokens(tokens, item={}){
      if(!tokens || !item) return;
      ['id','url','original_url','source_url','source_id','story_key'].forEach(key=>{
        const value = replacementToken(item[key]);
        if(value) tokens.add(`${key}:${value}`);
      });
      ['title','original_title'].forEach(key=>{
        const value = replacementToken(item[key]);
        if(value) tokens.add(`title:${value}`);
      });
    }
    function clientItemIdentity(item={}){
      const url = replacementToken(item.url || item.original_url || item.source_url);
      if(url) return `url:${url.replace(/\/+$/, '')}`;
      const story = replacementToken(item.story_key || item.story_signature || item.source_id);
      if(story) return `story:${story}`;
      const title = replacementToken(item.title || item.original_title);
      return title ? `title:${title}` : '';
    }
    function dedupeClientItems(items=[]){
      const seen = new Set();
      const unique = [];
      (Array.isArray(items) ? items : []).forEach(item => {
        if(!item || typeof item !== 'object') return;
        const key = clientItemIdentity(item);
        if(key && seen.has(key)) return;
        if(key) seen.add(key);
        unique.push(item);
      });
      return unique;
    }
    function clientContentSignature(items=[]){
      return dedupeClientItems(items)
        .map(item => clientItemIdentity(item) || replacementToken(item.id || item.title || item.url))
        .filter(Boolean)
        .sort()
        .join('|');
    }
    function itemMatchesReplacementTokens(item={}, tokens=new Set()){
      const own = new Set();
      addReplacementTokens(own, item);
      for(const token of own){
        if(tokens.has(token)) return true;
      }
      return false;
    }
    function replacementSeenTokens(section, index){
      const tokens = new Set();
      // Only cards currently visible in another slot are globally blocked.
      // A story/course previously visited in a different card remains valid;
      // each card owns its own navigation and refill history.
      getSectionList(section).forEach((item, itemIndex)=>{
        if(itemIndex !== index) addReplacementTokens(tokens, item);
      });
      const history = state.card_refill_history?.[replacementContextKey(section, index)];
      if(history){
        (history?.tried_items || []).forEach(item=>addReplacementTokens(tokens, item));
        (history?.tried_urls || []).forEach(url=>url && tokens.add(`url:${replacementToken(url)}`));
        (history?.tried_titles || []).forEach(title=>title && tokens.add(`title:${replacementToken(title)}`));
        (history?.tried_source_ids || []).forEach(sourceId=>sourceId && tokens.add(`source_id:${replacementToken(sourceId)}`));
      }
      const currentKey = replacementContextKey(section, index);
      const currentNav = state.cardNav?.[currentKey];
      ['prev','rejected'].forEach(name =>
        (currentNav?.[name] || []).forEach(item=>addReplacementTokens(tokens, item))
      );
      return tokens;
    }
    function levelBankItems(bank={}){
      return dedupeClientItems([
        ...bankList(bank, 'beginner'),
        ...bankList(bank, 'intermediate'),
        ...bankList(bank, 'advanced')
      ]);
    }
    function storedSectionPool(section){
      if(section === 'items'){
        const allItems = Array.isArray(state.all_items) && state.all_items.length ? state.all_items : [];
        return dedupeClientItems([
          ...levelBankItems(state.news_bank),
          ...allItems,
          ...(Array.isArray(state.items) ? state.items : [])
        ]);
      }
      if(section === 'courses'){
        return dedupeClientItems([
          ...levelBankItems(state.courses_bank),
          ...(Array.isArray(state.courses) ? state.courses : [])
        ]);
      }
      if(section === 'movies'){
        return dedupeClientItems(Array.isArray(state.movies) ? state.movies : []);
      }
      return [];
    }
    function visiblePageItems(){
      const visible = [
        ...visibleNewsList(),
        ...(state.feature_mode === 'course' ? (displayItemsForRender(state).courses || []) : []),
        ...(state.feature_mode === 'movie' ? getSectionList('movies') : [])
      ];
      return dedupeClientItems(visible);
    }
    function isVisibleAnywhere(item={}, section='', index=-1){
      const target = getSectionList(section)[index];
      const targetKey = clientItemIdentity(target);
      const candidateKey = clientItemIdentity(item);
      return visiblePageItems().some(entry => {
        const entryKey = clientItemIdentity(entry);
        if(targetKey && entryKey === targetKey) return false;
        return Boolean(candidateKey && entryKey === candidateKey);
      });
    }
    function findPreparedAlternative(section, index){
      const current = getSectionList(section)[index];
      const tokens = replacementSeenTokens(section, index);
      addReplacementTokens(tokens, current);
      const pool = storedSectionPool(section);
      for(const candidate of pool){
        if(!candidate || typeof candidate !== 'object') continue;
        if(!candidate.id && !candidate.title && !candidate.url) continue;
        if(section !== 'movies' && !itemMatchesReplacementLevel(candidate)) continue;
        if(itemMatchesReplacementTokens(candidate, tokens)) continue;
        if(isVisibleDuplicate(section, index, candidate) || isVisibleAnywhere(candidate, section, index)) continue;
        return candidate;
      }
      return null;
    }
    async function persistCardAtIndex(section, index, item, targetId='', visibleBefore=null){
      return request(`${API_BASE}/card/${section}/${index}`, {
        method:'POST',
        body: JSON.stringify({
          item,
          target_id:targetId,
          // Optimistic rendering has already put `item` in the target slot.
          // Send the view captured before that change; otherwise the server
          // sees the candidate itself and rejects every flip as a duplicate.
          visible_items:(Array.isArray(visibleBefore) ? visibleBefore : getSectionList(section)).map(compactHistoryItem)
        })
      });
    }
    async function applyNavigationItem(section, index, item, options={}){
      if(isVisibleDuplicate(section, index, item)){
        showToast('noSuitableReplacement');
        return false;
      }
      const previous = getSectionList(section)[index];
      const visibleBefore = [...getSectionList(section)];
      const completeViewBeforeNavigation = captureVisibleEditorView();
      updateCapturedEditorItem(completeViewBeforeNavigation, section, previous?.id || item?.id, item);
      if(options.optimistic){
        updateCardAtIndex(section, index, item);
        render();
      }
      try{
        const data = await persistCardAtIndex(section, index, item, previous?.id || '', visibleBefore);
        if(data.item) updateCardAtIndex(section, data.index ?? index, data.item);
        updateCapturedEditorItem(completeViewBeforeNavigation, section, item?.id || previous?.id, data.item || item);
        applyState(data);
        // Restore news and supporting cards together. A course replacement
        // must not reset earlier news choices, and vice versa.
        restoreCapturedEditorView(completeViewBeforeNavigation);
        return true;
      }catch(error){
        if(options.optimistic && previous){
          updateCardAtIndex(section, index, previous);
          render();
        }
        throw error;
      }
    }
    async function restorePreviousCard(section, index){
      if(!hasPreviousCard(section, index)){
        showPlainToast('لا توجد نسخة سابقة لهذا الكارد');
        return;
      }
      try{
        showPlainToast('جاري استرجاع الكارد السابق...');
        const data = await request(`${API_BASE}/restore-previous-card`, {
          method:'POST',
          body: JSON.stringify({section, index})
        });
        applyState(data);
        showPlainToast('تم استرجاع الكارد من النسخة السابقة');
      }catch(error){
        console.error(error);
        showPlainToast(error.data?.message || error.data?.error || 'تعذر استرجاع الكارد السابق');
      }
    }
    function openAlternativeDialog(section, id, index, action='replace'){
      state.alternativeTarget = {section, id, index, action};
      const title = t('alternativeTitle');
      const text = t('alternativeText');
      setText(els.alternativeModalTitle, title);
      setText(els.alternativeModalText, text);
      setText(els.alternativeFetchBtn, t('fetchMore'));
      if(!els.alternativeOverlay || !els.alternativeFetchBtn){
        return window.confirm(text);
      }
      els.alternativeOverlay.classList.add('show');
      return null;
    }
    function openAlternativeConfirm(section, id, index, action='replace'){
      const fallbackConfirmed = openAlternativeDialog(section, id, index, action);
      if(typeof fallbackConfirmed === 'boolean') return Promise.resolve(fallbackConfirmed);
      return new Promise(resolve => {
        state.alternativeResolve = resolve;
      });
    }
    function closeDeleteConfirm(confirmed=false){
      els.deleteConfirmOverlay?.classList.remove('show');
      const resolve = state.deleteConfirmResolve;
      state.deleteConfirmResolve = null;
      if(resolve) resolve(Boolean(confirmed));
    }
    function openDeleteConfirm(section='items'){
      closeDeleteConfirm(false);
      const isArabic = state.language === 'ar';
      const names = {
        items: isArabic ? 'الخبر' : 'news item',
        courses: isArabic ? 'الدورة' : 'course',
        movies: isArabic ? 'الفيلم' : 'film',
      };
      const itemName = names[section] || (isArabic ? 'العنصر' : 'item');
      setText(
        els.deleteConfirmTitle,
        isArabic ? 'تأكيد الحذف' : 'Confirm deletion'
      );
      setText(
        els.deleteConfirmText,
        isArabic ? `هل تريد حذف ${itemName}؟ لا يمكن التراجع عن الحذف بعد تأكيده.`
          : `Do you want to delete this ${itemName}? This action cannot be undone after confirmation.`
      );
      setText(
        els.deleteConfirmBtn,
        isArabic ? 'نعم، احذف' : 'Yes, delete'
      );
      if(!els.deleteConfirmOverlay || !els.deleteConfirmBtn){
        const message = els.deleteConfirmText?.textContent || 'Confirm delete?';
        return Promise.resolve(window.confirm(message));
      }
      els.deleteConfirmOverlay.classList.add('show');
      return new Promise(resolve => {
        state.deleteConfirmResolve = resolve;
      });
    }
    async function deleteCard(section,id){
      if(!state.isAdmin || !id) return;
      const confirmed = await openDeleteConfirm(section);
      if(!confirmed) return;
      try{
        saveSnapshot();
        showToast('deleteRunning');
        await request(cardUpdateRoute(section,id), {method:'DELETE'});
        if(state.selected?.section === section && state.selected?.id === id) state.selected = null;
        await loadState(false);
        showToast(section === 'items' ? 'deleteNewsDone' : 'deleteItemDone');
      }catch(error){
        console.error(error);
        showToast(error.data?.error || error.message || t('deleteFailed'));
      }
    }
    function replacementExcludeItems(section, index){
      const nav = cardNavState(section, index);
      const history = refillHistoryState(section, index);
      return [...(nav.prev || []), ...(nav.next || []), ...(nav.rejected || [])]
        .concat(history.tried_items || [])
        .filter(item => item && typeof item === 'object')
        .map(compactHistoryItem);
    }
    function visibleReplacementItems(section){
      return visiblePageItems()
        .filter(item => item && typeof item === 'object')
        .map(compactHistoryItem);
    }
    async function fetchMoreAlternative(section, id, index, action='replace'){
      action = 'replace';
      const completeViewBeforeFetch = captureVisibleEditorView();
      showCardProgress(section, index, 'progressReplacing');
      const key = progressKey(section, index);
      const controller = new AbortController();
      state.cardProgressAbort[key]?.abort();
      state.cardProgressAbort[key] = controller;
      try{
        const data = await request(`${API_BASE}/refill`, {
          method:'POST',
          signal: controller.signal,
        body: JSON.stringify({
          section,
          force:true,
          pool_only:true,
          allow_fetch:true,
          live_fetch:true,
          item_id:id,
          index,
          action:'replace',
          level:section === 'movies' ? '' : requestedReplacementLevel(),
          levels:section === 'movies' ? [] : (replacementLevels() ? [...replacementLevels()] : []),
          replacement_context:replacementContextKey(section, index),
          visible_items:visibleReplacementItems(section),
          exclude_items:replacementExcludeItems(section, index),
          card_refill_history:refillHistoryState(section, index)
        })
        });
        applyRefillProgress(section, data.index ?? index, data, 'progressReplacing');
        if(data?.success && data?.item){
          const nav = cardNavState(section, index);
          const current = getSectionList(section)[index];
          rememberTriedReplacement(section, index, current);
          rememberTriedReplacement(section, data.index ?? index, data.item);
          if(action !== 'delete' && current) nav.prev.push(current);
          updateCardAtIndex(section, data.index ?? index, data.item);
          updateCapturedEditorItem(completeViewBeforeFetch, section, current?.id || id, data.item);
          applyState(data);
          restoreCapturedEditorView(completeViewBeforeFetch);
          await wait(450);
          delete state.cardProgressAbort[key];
          hideCardProgress(section, data.index ?? index);
          showToast('itemReplaced');
          return true;
        }
        throw new Error(data?.message || t('noSuitableReplacement'));
      }catch(error){
        if(error.name === 'AbortError'){
          hideCardProgress(section, index);
          return false;
        }
        console.error(error);
        delete state.cardProgressAbort[key];
        applyRefillProgress(section, error.data?.index ?? index, error.data, 'progressReplacing');
        showReplacementFailedState(section, error.data?.index ?? index);
        showToast(error.data?.message || error.data?.error || error.message || t('noSuitableReplacement'));
        return false;
      }
    }
    async function navigateCard(section, id, index, direction){
      const pendingKey = replacementContextKey(section, index);
      if(state.cardNavPending[pendingKey]) return;
      state.cardNavPending[pendingKey] = true;
      render();
      try{
        const nav = cardNavState(section, index);
        const current = getSectionList(section)[index];
        if(!current) return;
      if(direction < 0){
        const previous = nav.prev.pop();
        if(!previous){
          showPlainToast(state.language === 'ar' ? '\u0644\u0627 \u064a\u0648\u062c\u062f \u062e\u0628\u0631 \u0633\u0627\u0628\u0642 \u0644\u0647\u0630\u0627 \u0627\u0644\u0643\u0627\u0631\u062f' : 'No previous story for this card');
          render();
          return;
        }
        if(isVisibleDuplicate(section, index, previous)){
          nav.rejected.push(previous);
          showToast('noSuitableReplacement');
          render();
          return;
        }
        nav.next.unshift(current);
        saveSnapshot();
        try{
          await applyNavigationItem(section, index, previous, {optimistic:true});
          showToast('itemReplaced');
        }catch(error){
          nav.next.shift();
          nav.prev.push(previous);
          console.error(error);
          showToast(error.data?.message || error.data?.error || error.message || t('noSuitableReplacement'));
        }
        return;
      }
      let next = nav.next.shift();
      while(next && isVisibleDuplicate(section, index, next)){
        nav.rejected.push(next);
        next = nav.next.shift();
      }
      if(next){
        nav.prev.push(current);
        saveSnapshot();
        try{
          await applyNavigationItem(section, index, next, {optimistic:true});
          showToast('itemReplaced');
        }catch(error){
          nav.prev.pop();
          nav.next.unshift(next);
          console.error(error);
          showToast(error.data?.message || error.data?.error || error.message || t('noSuitableReplacement'));
        }
        return;
      }
      const prepared = findPreparedAlternative(section, index);
      if(prepared){
        nav.prev.push(current);
        rememberTriedReplacement(section, index, current);
        rememberTriedReplacement(section, index, prepared);
        saveSnapshot();
        try{
          await applyNavigationItem(section, index, prepared, {optimistic:true});
          showToast('itemReplaced');
        }catch(error){
          nav.prev.pop();
          nav.rejected.push(prepared);
          console.error(error);
          showToast(error.data?.message || error.data?.error || error.message || t('noSuitableReplacement'));
        }
        return;
      }
      // No prepared alternative remains for this card. Ask before any network
      // fetch in both the general view and a specific Level. If confirmed,
      // fetchMoreAlternative still sends the selected Level to the backend;
      // cancelling leaves the current card unchanged.
      const confirmed = await openAlternativeConfirm(section, current.id || id, index, 'replace');
      if(confirmed){
        saveSnapshot();
        await fetchMoreAlternative(section, current.id || id, index, 'replace');
      }
      }finally{
        delete state.cardNavPending[pendingKey];
        render();
      }
    }
    async function retryReplacementAfterFastFetch(section, id, index, action='replace'){
      await pollForGeneratorDone();
      const route = section==='items' ? `${API_BASE}/replace/${id}` : `${API_BASE}/replace/${section}/${id}`;
      return request(route,{method:'POST', body: JSON.stringify({})});
    }
    async function confirmAndFetchReplacement(section, id, index, action='replace'){
      const confirmed = await openAlternativeConfirm(section, id, index, action);
      if(!confirmed){
        hideCardProgress(section, index);
        return null;
      }
      showToast('fetchNewContent');
      return fetchMoreAlternative(section, id, index, action);
    }
    function handleOutsideCardClick(e){
      if(e.target.closest('[data-id]') || e.target.closest('.modal') || e.target.closest('.tip-pop') || e.target.closest('.card-nav') || e.target.closest('.floating-progress-host')) return;
      if(state.selected){ state.selected = null; render(); }
    }
    function bindDragAndDrop(){
      let dragId = null;
      document.querySelectorAll('.news-card').forEach(card=>{
        card.addEventListener('dragstart', ()=>{dragId=card.dataset.id; card.classList.add('dragging'); showTip('reorder');});
        card.addEventListener('dragend', ()=>{card.classList.remove('dragging'); document.querySelectorAll('.news-card').forEach(c=>c.classList.remove('drag-over'));});
        card.addEventListener('dragover', e=>{e.preventDefault(); card.classList.add('drag-over');});
        card.addEventListener('dragleave', ()=>card.classList.remove('drag-over'));
        card.addEventListener('drop', async e=>{
          e.preventDefault(); card.classList.remove('drag-over');
          const targetId = card.dataset.id; if(!dragId || dragId===targetId) return;
          const currentView = displayItemsForRender(state).news || state.items || [];
          const from = currentView.findIndex(item=>item.id===dragId); const to = currentView.findIndex(item=>item.id===targetId); if(from<0||to<0) return;
          saveSnapshot();
          // Level/count UI fix: news_bank can rebuild the visible order on every
          // render, so drag sorting must store the reordered visible list.
          const reordered = [...currentView];
          const [moved] = reordered.splice(from,1);
          reordered.splice(to,0,moved);
          state.items = reordered;
          state.newsViewOverride = reordered;
          render();
          try { await request(`${API_BASE}/reorder/items`, {method:'PUT', body: JSON.stringify({ids: state.items.map(item=>item.id)})}); showToast('reorderSaved'); }
          catch{ showToast('reorderLocal'); }
        });
      });
      let courseDragId = null;
      document.querySelectorAll('.feature-card.draggable-course').forEach(card=>{
        card.addEventListener('dragstart', ()=>{courseDragId=card.dataset.id; card.classList.add('dragging'); showTip('reorder');});
        card.addEventListener('dragend', ()=>{card.classList.remove('dragging'); document.querySelectorAll('.feature-card.draggable-course').forEach(c=>c.classList.remove('drag-over'));});
        card.addEventListener('dragover', e=>{e.preventDefault(); card.classList.add('drag-over');});
        card.addEventListener('dragleave', ()=>card.classList.remove('drag-over'));
        card.addEventListener('drop', async e=>{
          e.preventDefault();
          card.classList.remove('drag-over');
          const targetId = card.dataset.id;
          if(!courseDragId || courseDragId===targetId) return;
          const currentView = [...(displayItemsForRender(state).courses || [])];
          const from = currentView.findIndex(item=>item.id===courseDragId);
          const to = currentView.findIndex(item=>item.id===targetId);
          if(from<0 || to<0) return;
          saveSnapshot();
          const [moved] = currentView.splice(from,1);
          currentView.splice(to,0,moved);
          const visibleIds = new Set(currentView.map(item=>item.id));
          state.coursesViewOverride = currentView;
          state.courses = [...currentView, ...(state.courses || []).filter(item=>!visibleIds.has(item.id))];
          render();
          try{
            await request(`${API_BASE}/reorder/courses`, {method:'PUT', body:JSON.stringify({ids:state.courses.map(item=>item.id)})});
            showToast('reorderSaved');
          }catch{
            showToast('reorderLocal');
          }
        });
      });
    }
    function openContentType(){ state.tips.choose = true; hideTip('choose'); }
    function closeOverlay(type){
      if(type==='contentType') els.contentTypeOverlay?.classList.remove('show');
      if(type==='edit') els.editOverlay.classList.remove('show');
      if(type==='preview') els.previewOverlay.classList.remove('show');
      if(type==='ai') els.aiOverlay.classList.remove('show');
      if(type==='alternative'){
        els.alternativeOverlay.classList.remove('show');
        const resolve = state.alternativeResolve;
        state.alternativeResolve = null;
        state.alternativeTarget=null;
        if(resolve) resolve(false);
      }
      if(type==='deleteConfirm') closeDeleteConfirm(false);
      if(type==='settings') els.settingsOverlay.classList.remove('show');
    }
    function updateLogoSizeValue(value){
      const size = clampLogoSize(value);
      if(els.editLogoSize) els.editLogoSize.value = String(size);
      if(els.editLogoSizeValue) els.editLogoSizeValue.textContent = `${size}px`;
      return size;
    }
    function cssEscapeValue(value=''){
      if(window.CSS && typeof CSS.escape === 'function') return CSS.escape(String(value));
      return String(value).replace(/["\\]/g, '\\$&');
    }
    function applyLogoSizePreview(section, id, value){
      const size = updateLogoSizeValue(value);
      const card = document.querySelector(`[data-section="${cssEscapeValue(section)}"][data-id="${cssEscapeValue(id)}"]`);
      const logo = card?.querySelector?.('.card-logo');
      if(logo) logo.style.setProperty('--logo-size', `${size}px`);
    }
    function cardUpdateRoute(section, id){
      return section === 'items' ? `${API_BASE}/news/${id}` : `${API_BASE}/content/${section}/${id}`;
    }
    function logoEditorItem(section, id){
      return getSectionList(section).find(entry => entry.id === id);
    }
    function markLogoEditTarget(section, id){
      document.querySelectorAll('.logo-edit-target').forEach(card => card.classList.remove('logo-edit-target'));
      const card = document.querySelector(`[data-section="${cssEscapeValue(section)}"][data-id="${cssEscapeValue(id)}"]`);
      if(card) card.classList.add('logo-edit-target');
    }
    function directLogoCard(section, id){
      return document.querySelector(`[data-section="${cssEscapeValue(section)}"][data-id="${cssEscapeValue(id)}"]`);
    }
    function directLogoBox(section, id){
      return directLogoCard(section, id)?.querySelector?.('.card-logo') || null;
    }
    function readLogoMetrics(section, id){
      const item = logoEditorItem(section, id) || {};
      const logo = directLogoBox(section, id);
      const styles = logo ? getComputedStyle(logo) : null;
      const logoX = hasLogoPositionValue(item.logo_x) ? item.logo_x : item.logoX;
      const logoY = hasLogoPositionValue(item.logo_y) ? item.logo_y : item.logoY;
      const defaultX = section === 'movies' || section === 'courses' ? 16 : 14;
      const defaultY = section === 'movies' || section === 'courses' ? -14 : -12;
      const useStoredPosition = hasCustomLogoPosition(item);
      return {
        size: clampLogoSize(item.logo_size || item.logoSize || (styles ? parseFloat(styles.width) : 30)),
        x: clampLogoPosition(useStoredPosition && hasLogoPositionValue(logoX) ? logoX : (styles ? parseFloat(styles.left) : defaultX)),
        y: clampLogoPosition(useStoredPosition && hasLogoPositionValue(logoY) ? logoY : (styles ? parseFloat(styles.top) : defaultY)),
      };
    }
    function applyLogoDirectMetrics(section, id, metrics={}){
      const item = logoEditorItem(section, id);
      const logo = directLogoBox(section, id);
      const defaultX = section === 'movies' || section === 'courses' ? 16 : 14;
      const defaultY = section === 'movies' || section === 'courses' ? -14 : -12;
      const size = clampLogoSize(metrics.size ?? item?.logo_size ?? 30);
      const x = clampLogoPosition(metrics.x ?? item?.logo_x ?? defaultX);
      const y = clampLogoPosition(metrics.y ?? item?.logo_y ?? defaultY);
      if(logo){
        logo.style.setProperty('--logo-size', `${size}px`);
        logo.style.setProperty('--logo-x', `${x}px`);
        logo.style.setProperty('--logo-y', `${y}px`);
      }
      if(item){
        item.logo_size = size;
        item.logo_x = x;
        item.logo_y = y;
      }
      return {size,x,y};
    }
    function startLogoDirectEdit(section, id){
      const item = logoEditorItem(section,id);
      if(!item) return null;
      const metrics = readLogoMetrics(section, id);
      state.logoEditTarget = {section,id,...metrics};
      state.selected = {section,id};
      markLogoEditTarget(section,id);
      document.body.classList.add('logo-editing');
      return state.logoEditTarget;
    }
    async function persistLogoDirectEdit(section, id){
      const item = logoEditorItem(section,id);
      if(!item) return;
      const metrics = readLogoMetrics(section, id);
      try{
        await request(cardUpdateRoute(section,id), {
          method:'PUT',
          body: JSON.stringify({logo_size:metrics.size, logo_x:metrics.x, logo_y:metrics.y})
        });
      }catch(error){
        console.error(error);
        showToast(error.data?.error || error.message || t('saveEditFailed'));
      }
    }
    function closeLogoDirectEdit(){
      state.logoEditTarget = null;
      document.body.classList.remove('logo-editing');
      document.querySelectorAll('.logo-edit-target').forEach(card => card.classList.remove('logo-edit-target'));
    }
    function scheduleLogoDirectSave(section, id){
      if(state.logoSaveTimer) clearTimeout(state.logoSaveTimer);
      state.logoSaveTimer = setTimeout(async ()=>{
        await persistLogoDirectEdit(section, id);
        closeLogoDirectEdit();
        showToast('saveEditDone');
      }, 650);
    }
    function logoResizeHit(logo, event){
      const rect = logo.getBoundingClientRect();
      return event.shiftKey || (event.clientX >= rect.right - 16 && event.clientY >= rect.bottom - 16);
    }
    function handleLogoPointerDown(event){
      const logo = event.target.closest?.('.card-logo[data-card-action="edit-logo"]');
      if(!logo) return;
      event.preventDefault();
      event.stopPropagation();
      const section = logo.dataset.targetSection;
      const id = logo.dataset.targetId;
      const target = startLogoDirectEdit(section, id);
      if(!target) return;
      saveSnapshot();
      const start = readLogoMetrics(section, id);
      state.logoDrag = {
        section,
        id,
        mode: logoResizeHit(logo, event) ? 'resize' : 'move',
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        ...start,
      };
      state.suppressLogoClickUntil = Date.now() + 500;
      logo.setPointerCapture?.(event.pointerId);
      window.addEventListener('pointermove', handleLogoPointerMove, {passive:false});
      window.addEventListener('pointerup', handleLogoPointerUp, {once:true});
    }
    function handleLogoPointerMove(event){
      const drag = state.logoDrag;
      if(!drag) return;
      event.preventDefault();
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if(drag.mode === 'resize'){
        const delta = Math.abs(dx) > Math.abs(dy) ? dx : dy;
        applyLogoDirectMetrics(drag.section, drag.id, {size:drag.size + delta, x:drag.x, y:drag.y});
      }else{
        applyLogoDirectMetrics(drag.section, drag.id, {size:drag.size, x:drag.x + dx, y:drag.y + dy});
      }
    }
    async function handleLogoPointerUp(){
      const drag = state.logoDrag;
      state.logoDrag = null;
      window.removeEventListener('pointermove', handleLogoPointerMove);
      if(!drag) return;
      await persistLogoDirectEdit(drag.section, drag.id);
      closeLogoDirectEdit();
      showToast('saveEditDone');
    }
    function handleLogoWheel(event){
      const logo = event.target.closest?.('.card-logo[data-card-action="edit-logo"]');
      if(!logo) return;
      event.preventDefault();
      event.stopPropagation();
      const section = logo.dataset.targetSection;
      const id = logo.dataset.targetId;
      if(!state.logoEditTarget || state.logoEditTarget.section !== section || state.logoEditTarget.id !== id){
        saveSnapshot();
        startLogoDirectEdit(section, id);
      }
      const metrics = readLogoMetrics(section, id);
      const nextSize = metrics.size + (event.deltaY < 0 ? 2 : -2);
      applyLogoDirectMetrics(section, id, {...metrics, size:nextSize});
      state.suppressLogoClickUntil = Date.now() + 500;
      scheduleLogoDirectSave(section, id);
    }
    function updateLogoEditorSize(value){
      const size = clampLogoSize(value);
      if(els.logoEditorSize) els.logoEditorSize.value = String(size);
      if(els.logoEditorSizeValue) els.logoEditorSizeValue.textContent = `${size}px`;
      if(state.logoEditTarget) applyLogoSizePreview(state.logoEditTarget.section, state.logoEditTarget.id, size);
      return size;
    }
    function setLogoEditorPreview(item){
      if(!els.logoEditorPreview) return;
      const chain = logoFallbackChain(item || {});
      const src = chain[0] || item?.logo || item?.provider_logo || item?.source_logo || item?.poster || item?.image || '';
      els.logoEditorPreview.innerHTML = src
        ? `<img src="${escapeHtml(src)}" alt="" referrerpolicy="no-referrer">`
        : '<span class="fallback">Logo</span>';
    }
    function openLogoEditor(section,id){
      startLogoDirectEdit(section,id);
    }
    function closeLogoEditor({restore=false}={}){
      const target = state.logoEditTarget;
      if(restore && target) applyLogoSizePreview(target.section, target.id, target.originalSize);
      state.logoEditTarget = null;
      document.body.classList.remove('logo-editing');
      document.querySelectorAll('.logo-edit-target').forEach(card => card.classList.remove('logo-edit-target'));
      els.logoEditorOverlay?.classList.remove('show');
      els.logoEditorOverlay?.setAttribute('aria-hidden','true');
    }
    async function saveLogoEditor(){
      if(!state.logoEditTarget) return;
      const {section,id} = state.logoEditTarget;
      const size = clampLogoSize(els.logoEditorSize?.value || 30);
      const item = logoEditorItem(section,id);
      try{
        saveSnapshot();
        await request(cardUpdateRoute(section,id), {method:'PUT', body: JSON.stringify({logo_size:size})});
        if(item) item.logo_size = size;
        closeLogoEditor();
        render();
        showToast('saveEditDone');
      }catch(error){
        console.error(error);
        showToast(error.data?.error || error.message || t('saveEditFailed'));
      }
    }
    function openEdit(section,id){
      // Load the current card values, including the active source/logo override fields.
      const pool = getSectionList(section);
      const item = pool.find(entry=>entry.id===id);
      if(!item) return;
      state.editTarget={section,id,original:JSON.parse(JSON.stringify(item))};
      els.editModalTitle.textContent = section==='items' ? t('editNews') : t('editSuggested');
      els.editTitle.value=item.title||'';
      els.editText.value=item.text||'';
      els.editUrl.value=item.url||'';
      if(els.editSource){
        els.editSource.value = item.source || item.original_source || item.provider || item.platform || item.company || '';
      }
      if(els.editLogo){
        els.editLogo.value = section === 'movies'
          ? (item.logo_override_url || item.manual_logo_url || item.poster || item.image || item.logo || '')
          : (item.logo_override_url || item.manual_logo_url || item.logo || item.provider_logo || item.source_logo || '');
      }
      if(els.editLevelField){
        const showLevel = section === 'courses' || section === 'items';
        els.editLevelField.style.display = showLevel ? '' : 'none';
        if(showLevel && els.editLevel){
          const key = normalizeLevelName(item.level || item.course_level || item.difficulty || '') || 'beginner';
          els.editLevel.value = key.charAt(0).toUpperCase() + key.slice(1);
        }
      }
      updateLogoSizeValue(item.logo_size || item.logoSize || 30);
      els.editOverlay.classList.add('show');
    }
    function openAi(section,id){ const pool = getSectionList(section); const item = pool.find(entry=>entry.id===id); if(!item) return; state.aiTarget={section,id}; els.aiModalTitle.textContent = section==='items' ? t('aiNews') : t('aiContent'); els.aiInstruction.value=t('aiDefaultInstruction'); els.aiOverlay.classList.add('show'); }
    async function saveAi(event){
      event.preventDefault();
      if(!state.aiTarget) return;
      const instruction=(els.aiInstruction.value||'').trim();
      const {section,id}=state.aiTarget;
      const visibleViewBeforeAi = captureVisibleEditorView();
      try{
        saveSnapshot();
        showToast('aiRunning');
        if(section==='items'){
          const data = await request(`${API_BASE}/rewrite/${id}`,{method:'POST', body: JSON.stringify({instruction})});
          updateCapturedEditorItem(visibleViewBeforeAi, section, id, data?.item);
          closeOverlay('ai');
          await loadState(false);
          restoreCapturedEditorView(visibleViewBeforeAi);
          showToast(data.rewrite_mode==='ai' ? 'aiNewsDone' : 'aiLocalDone');
          state.onboarding='edit';
          showTip('edit');
          return;
        }
        const pool = getSectionList(section);
        const item = pool.find(entry=>entry.id===id);
        if(!item) return;
        const data = await request(`${API_BASE}/ai-edit`,{method:'POST', body: JSON.stringify({title:item.title,text:item.text,instruction})});
        const route = `${API_BASE}/content/${section}/${id}`;
        const savedEdit = await request(route,{method:'PUT', body: JSON.stringify({title:data.title||item.title,text:data.text||item.text})});
        updateCapturedEditorItem(visibleViewBeforeAi, section, id, savedEdit?.item || {...item,title:data.title||item.title,text:data.text||item.text});
        closeOverlay('ai');
        await loadState(false);
        restoreCapturedEditorView(visibleViewBeforeAi);
        showToast('aiContentDone');
        state.onboarding='edit';
        showTip('edit');
      }catch(error){
        console.error(error);
        showToast(error.data?.error || error.message || t('aiFailed'));
      }
    }
    async function replaceFeatureItem(section,id){ const pool = section==='courses' ? [...state.courses] : [...state.movies]; if(pool.length < 2){ showToast('noAlternative'); return; } const idx = pool.findIndex(entry=>entry.id===id); if(idx < 0) return; const next = pool[(idx+1) % pool.length]; if(next.id===id && pool.length===1) return; if(section==='courses'){ const list = state.courses.filter(entry=>entry.id!==next.id); state.courses=[next,...list]; } else { state.movies=[next,...state.movies.filter(entry=>entry.id!==next.id)]; state.feature_item=next; } await request(`${API_BASE}/feature/${section==='movies'?'movie':'course'}`,{method:'PUT', body: JSON.stringify({})}); render(); showToast('contentReplaced'); }
    async function saveEdit(event){
      // Save a manual override through the API without changing the card schema.
      event.preventDefault();
      if(!state.editTarget) return;
      const {section,id,original={}}=state.editTarget;
      const logoValue = (els.editLogo?.value || '').trim();
      const logoSize = clampLogoSize(els.editLogoSize?.value || 30);
      const sourceValue = (els.editSource?.value || '').trim();
      const payload={};
      const nextTitle = els.editTitle.value.trim();
      const nextText = els.editText.value.trim();
      const nextUrl = els.editUrl.value.trim();
      if(nextTitle !== String(original.title || '').trim()) payload.title = nextTitle;
      if(nextText !== String(original.text || '').trim()) payload.text = nextText;
      if(nextUrl !== String(original.url || '').trim()) payload.url = nextUrl;
      const originalSource = String(original.source || original.original_source || original.provider || original.platform || original.company || '').trim();
      if(sourceValue !== originalSource){
        payload.source = sourceValue;
        if(section === 'items') payload.original_source = sourceValue;
      }
      if(logoSize !== clampLogoSize(original.logo_size || original.logoSize || 30)) payload.logo_size = logoSize;
      if((section === 'courses' || section === 'items') && els.editLevel){
        const nextLevel = els.editLevel.value;
        const originalLevelKey = normalizeLevelName(original.level || original.course_level || original.difficulty || '') || 'beginner';
        const originalLevel = originalLevelKey.charAt(0).toUpperCase() + originalLevelKey.slice(1);
        if(nextLevel !== originalLevel) payload.level = nextLevel;
      }
      const originalLogo = section === 'movies'
        ? String(original.logo_override_url || original.manual_logo_url || original.poster || original.image || original.logo || '').trim()
        : String(original.logo_override_url || original.manual_logo_url || original.logo || original.provider_logo || original.source_logo || '').trim();
      if(logoValue !== originalLogo && section === 'movies'){
        payload.logo_override_url = logoValue;
        payload.manual_logo_url = logoValue;
        payload.logo_manual_override = Boolean(logoValue);
      }else if(logoValue !== originalLogo && section !== 'movies'){
        payload.logo_override_url = logoValue;
        payload.manual_logo_url = logoValue;
        payload.logo_manual_override = Boolean(logoValue);
        payload.logo_unresolved = !logoValue;
      }
      const route=section==='items' ? `${API_BASE}/news/${id}` : `${API_BASE}/content/${section}/${id}`;
      const visibleViewBeforeEdit = captureVisibleEditorView();
      try{
        saveSnapshot();
        showToast('saveEditRunning');
        const editResult = await request(route,{method:'PUT', body: JSON.stringify(payload)});
        updateCapturedEditorItem(
          visibleViewBeforeEdit,
          section,
          id,
          editResult?.item || {...original, ...payload}
        );
        closeOverlay('edit');
        await loadState(false);
        restoreCapturedEditorView(visibleViewBeforeEdit);
        showToast('saveEditDone');
        state.onboarding='edit';
        setTimeout(()=>showTip('edit'),250);
      }catch(error){
        console.error(error);
        if(error.status === 404 || error.data?.error === 'News item not found' || error.data?.error === 'Content item not found'){
          closeOverlay('edit');
          await loadState(false);
          showToast(state.language === 'ar' ? 'تم تحديث النشرة. البطاقة التي كنت تعدلها لم تعد موجودة.' : 'Newsletter refreshed. The card you were editing no longer exists.');
          return;
        }
        showToast(error.data?.error || error.message || t('saveEditFailed'));
      }
    }
    async function replaceItem(id,section='items'){
      const index = findVisibleIndex(section, id);
      if(index < 0) return;
      await navigateCard(section, id, index, 1);
    }
    async function refillNews(){
      const progressTargets = [['items', Math.min(state.items.length, 9)]];
      if(state.feature_mode === 'course') progressTargets.push(['courses', Math.min(state.courses.length, 1)]);
      if(state.feature_mode === 'movie') progressTargets.push(['movies', 0]);
      progressTargets.forEach(([section,index])=>showCardProgress(section, index, 'progressLoadingMore'));
      try{
        showToast('fetchNewContent');
        await request(`${API_BASE}/refill`, {method:'POST', body: JSON.stringify({section:null, force:true})});
        await pollForGeneratorDone({applyWhileRunning:false});
        await loadState(false);
        progressTargets.forEach(([section,index])=>hideCardProgress(section, index));
        showToast('fetchDone');
      }catch(error){
        console.error(error);
        progressTargets.forEach(([section,index])=>showReplacementFailedState(section, index));
        showToast(error.data?.message || error.data?.error || error.message || t('fetchFailed'));
      }
    }
    async function switchFeature(mode){
      if(!['course','movie'].includes(mode)) return;
      // Immediate UI switch fix: update local state first, then sync with the
      // backend. This prevents the button from feeling broken while loadState()
      // refreshes the newsletter JSON.
      state.feature_mode = mode;
      if(!restoreSavedViewForContext() && mode === 'movie') state.feature_item = (state.movies || [])[0] || state.feature_item || null;
      render();
      if(!state.isAdmin){
        closeOverlay('contentType');
        showToast(mode==='movie' ? 'switchMovieDone' : 'switchCourseDone');
        return;
      }
      const data = await request(`${API_BASE}/feature/${mode}`, {method:'PUT', body: JSON.stringify({})});
      if(data.feature_mode) state.feature_mode = data.feature_mode;
      if(data.feature_item) state.feature_item = data.feature_item;
      state.tips.choose = true;
      hideTip('choose');
      closeOverlay('contentType');
      await loadState(false);
      restoreSavedViewForContext();
      render();
      showToast(mode==='movie' ? 'switchMovieDone' : 'switchCourseDone');
      const hasMovie = mode !== 'movie' || Boolean(
        (state.movies || []).some(item => item && (item.id || item.title)) ||
        (state.feature_item && (state.feature_item.id || state.feature_item.title))
      );
      if(mode === 'movie' && !hasMovie){
        const confirmed = await openAlternativeConfirm('movies', '', 0, 'replace');
        if(confirmed) await fetchMoreAlternative('movies', '', 0, 'replace');
      }
      setTimeout(()=>showTips(['edit','reorder']),250);
    }
    const exportCleanSelectors = [
      '.feature-switch',
      '.card-popover',
      '.tip-pop',
      '.overlay',
      '.preview-overlay',
      '.toast'
    ].join(',');


    // The backend rasterizes this preview into a WhatsApp-friendly PDF.
