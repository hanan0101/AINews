// Logo/favicon resolution: builds the ordered list of candidate logo URLs
// for a card (official domain favicon, brand icon services, generated
// initials fallback, etc.) and the <img onerror> chain-advance handler that
// walks that list in the browser. Depends on `t()` from i18n.js and
// `escapeHtml` from shared-functions.js (both load before this file).
    function isNewsItem(item={}){
      return String(item.type || '').toLowerCase() === 'news';
    }
    function isPublisherLogoUrl(url=''){
      const normalized = String(url || '').toLowerCase();
      return NEWS_PUBLISHER_LOGO_URL_PARTS.some(part => normalized.includes(part));
    }
    function brandTokenMatch(text='', key=''){
      const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return new RegExp(`(^|[^a-z0-9])${escaped}([^a-z0-9]|$)`, 'i').test(text);
    }
    function transparentLogoUrl(item={}){
      const text = [
        item.logo_company,
        item.main_company,
        item.company,
        item.provider,
        item.platform,
        item.title
      ].filter(Boolean).join(' ').toLowerCase();
      if(!text) return '';
      for(const [alias,key] of TRANSPARENT_LOGO_ALIASES){
        if(text.includes(alias) && TRANSPARENT_LOGOS[key]) return TRANSPARENT_LOGOS[key];
      }
      for(const [key,url] of Object.entries(TRANSPARENT_LOGOS)){
        if(brandTokenMatch(text, key)) return url;
      }
      return '';
    }
    function isLikelyBackgroundIconUrl(url=''){
      const normalized = String(url || '').toLowerCase();
      if(normalized.startsWith('data:image/svg+xml')) return false;
      return normalized.includes('google.com/s2/favicons') ||
        normalized.includes('logo.clearbit.com') ||
        normalized.includes('icons.duckduckgo.com') ||
        normalized.includes('favicon') ||
        normalized.endsWith('.ico');
    }
    function isGeneratedFallbackLogoUrl(url=''){
      return String(url || '').trim().toLowerCase().startsWith('data:image/svg');
    }
    function companyFaviconUrl(item={}){
      const companyGroups = [
        item.logo_company,
        item.main_company,
        item.company,
        item.update_owner,
        item.provider_name,
        item.source_or_platform_company
      ].filter(Boolean).map(value=>String(value).toLowerCase());
      const secondaryGroups = [
        item.tool_name,
        item.product_name,
        item.title
      ].filter(Boolean).map(value=>String(value).toLowerCase());
      const textGroups = [...companyGroups, ...secondaryGroups];
      for(const text of textGroups){
      for(const [key,domain] of Object.entries(COMPANY_FAVICON_DOMAINS)){
        if(isNewsItem(item) && NEWS_PUBLISHER_LOGO_KEYS.has(key)) continue;
        if(brandTokenMatch(text, key)) return TRANSPARENT_LOGOS[key] || '';
      }
      }
      if(isNewsItem(item)) return '';
      const url = String(item.url || item.source_url || '');
      try{
        const parsed = new URL(url);
        if(parsed.hostname) return '';
      }catch{}
      return '';
    }
    function sourceFaviconUrl(item={}){
      if(isNewsItem(item)) return '';
      const urls = [item.source_url, item.url].filter(Boolean);
      for(const rawUrl of urls){
        try{
          const parsed = new URL(String(rawUrl));
          if(parsed.hostname) return `https://www.google.com/s2/favicons?sz=128&domain=${parsed.hostname}`;
        }catch{}
      }
      return '';
    }
    function faviconUrlForDomain(domain=''){
      const clean = String(domain || '').trim().replace(/^https?:\/\//i, '').replace(/^www\./i, '').split('/')[0];
      return '';
    }
    function fallbackDomainsForBrandKey(key=''){
      const normalized = String(key || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
      const readable = String(key || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
      const domains = [
        SIMPLE_ICON_FALLBACK_DOMAINS[normalized],
        COMPANY_FAVICON_DOMAINS[normalized],
        COMPANY_FAVICON_DOMAINS[readable]
      ].filter(Boolean);
      return [...new Set(domains)];
    }
    function simpleIconFallbackUrls(url=''){
      const normalized = String(url || '').trim().toLowerCase();
      const match = normalized.match(/cdn\.simpleicons\.org\/([^/?#]+)/);
      if(!match) return [];
      const slug = decodeURIComponent(match[1]).replace(/[^a-z0-9-]/g, '');
      const compactSlug = slug.replace(/-/g, '');
      const urls = [];
      const add = value => {
        const clean = String(value || '').trim();
        if(clean && !urls.includes(clean)) urls.push(clean);
      };
      fallbackDomainsForBrandKey(slug).forEach(domain => {
        add(`https://icons.duckduckgo.com/ip3/${domain}.ico`);
        add(`https://www.google.com/s2/favicons?sz=128&domain=${domain}`);
      });
      fallbackDomainsForBrandKey(compactSlug).forEach(domain => {
        add(`https://icons.duckduckgo.com/ip3/${domain}.ico`);
        add(`https://www.google.com/s2/favicons?sz=128&domain=${domain}`);
      });
      return urls;
    }
    function logoBrandFallbackUrls(item={}){
      const labels = [
        item.logo_company,
        item.main_company,
        item.company,
        item.update_owner,
        item.provider_name,
        item.provider,
        item.platform,
        item.product_name,
        item.tool_name
      ].filter(Boolean);
      const urls = [];
      labels.forEach(label => {
        const text = String(label || '').toLowerCase();
        Object.entries(COMPANY_FAVICON_DOMAINS).forEach(([key, domain]) => {
          if(brandTokenMatch(text, key)){
            const url = TRANSPARENT_LOGOS[key] || '';
            if(url && !urls.includes(url)) urls.push(url);
          }
        });
      });
      return urls;
    }
    function clearbitBrandFallbackUrls(item={}){
      const labels = [
        item.logo_company,
        item.main_company,
        item.company,
        item.update_owner,
        item.provider_name,
        item.provider,
        item.platform,
        item.product_name,
        item.tool_name
      ].filter(Boolean);
      const urls = [];
      labels.forEach(label => {
        const text = String(label || '').toLowerCase();
        Object.entries(COMPANY_FAVICON_DOMAINS).forEach(([key, domain]) => {
          if(isNewsItem(item) && NEWS_PUBLISHER_LOGO_KEYS.has(key)) return;
          if(brandTokenMatch(text, key)){
            const url = `https://logo.clearbit.com/${domain}`;
            if(url && !urls.includes(url)) urls.push(url);
          }
        });
      });
      return urls;
    }
    function guessedBrandFallbackUrls(item={}){
      const labels = [
        item.logo_company,
        item.main_company,
        item.company,
        item.update_owner,
        item.provider_name,
        item.provider,
        item.platform,
        item.product_name,
        item.tool_name
      ].filter(Boolean);
      const urls = [];
      labels.forEach(label => {
        const normalized = String(label || '').toLowerCase()
          .replace(/\b(inc|llc|ltd|corp|corporation|company|co)\b/g, ' ')
          .replace(/[^a-z0-9]+/g, ' ')
          .trim();
        const compact = normalized.replace(/\s+/g, '');
        const dashed = normalized.replace(/\s+/g, '-');
        [compact, dashed].forEach(stem => {
          if(stem.length < 3) return;
          [`https://cdn.simpleicons.org/${stem}`].forEach(url => {
            if(url && !urls.includes(url)) urls.push(url);
          });
        });
      });
      return urls;
    }
    function logoFallbackLabel(item={}){
      const labels = [
        item.logo_company,
        item.main_company,
        item.company,
        item.update_owner,
        item.provider_name,
        item.provider,
        item.platform,
        item.product_name,
        item.tool_name,
        item.title
      ].filter(Boolean);
      const raw = String(labels[0] || 'AI').replace(/\([^)]*\)/g, ' ').replace(/[^A-Za-z0-9\u0600-\u06FF]+/g, ' ').trim();
      const words = raw.split(/\s+/).filter(Boolean);
      if(words.length >= 2) return words.slice(0, 2).map(word => word[0]).join('').toUpperCase();
      return (words[0] || 'AI').slice(0, 3).toUpperCase();
    }
    function generatedLogoDataUrl(label='AI'){
      const clean = String(label || 'AI').slice(0, 3).toUpperCase();
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96" rx="22" fill="#fff8ef"/><rect x="3" y="3" width="90" height="90" rx="19" fill="none" stroke="#8e4640" stroke-opacity=".35" stroke-width="6"/><text x="48" y="58" text-anchor="middle" font-family="Arial, sans-serif" font-size="30" font-weight="700" fill="#8e4640">${clean.replace(/[&<>]/g, '')}</text></svg>`;
      return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
    }
    function logoUrlWithVersion(url='', version=''){
      const clean = String(url || '').trim();
      const stamp = String(version || '').trim();
      if(!clean || !stamp || clean.startsWith('data:image')) return clean;
      try{
        const parsed = new URL(clean, window.location.href);
        parsed.searchParams.set('v', stamp);
        return parsed.href;
      }catch{
        return clean.includes('?') ? `${clean}&v=${encodeURIComponent(stamp)}` : `${clean}?v=${encodeURIComponent(stamp)}`;
      }
    }
    function logoFallbackChain(item={}){
      const chain = [];
      const isNews = isNewsItem(item);
      const modelCompanyOnly = isNews && !!item.simple_gpt_selected;
      const add = url => {
        const clean = String(url || '').trim();
        if(!clean) return;
        if(isNews && !modelCompanyOnly && isLikelyBackgroundIconUrl(clean)) return;
        if(!chain.includes(clean)) chain.push(clean);
      };
      const addCompanyFallback = url => {
        const clean = String(url || '').trim();
        if(!clean) return;
        if(isNews && isPublisherLogoUrl(clean)) return;
        if(!chain.includes(clean)) chain.push(clean);
      };
      const existingLogo = String(item.logo || '');
      const manualLogo = String(item.logo_override_url || item.manual_logo_url || '').trim();
      const manualDisplayLogo = logoUrlWithVersion(manualLogo, item.logo_updated_at || item.logoUpdatedAt || '');
      if(manualLogo){
        add(manualDisplayLogo || manualLogo);
        add(generatedLogoDataUrl(logoFallbackLabel(item)));
        return chain;
      }
      if(modelCompanyOnly){
        const transparentPreferred = [];
        const delayed = [];
        const collect = url => {
          const clean = String(url || '').trim();
          if(!clean) return;
          if(isLikelyBackgroundIconUrl(clean)){
            delayed.push(clean);
          }else{
            transparentPreferred.push(clean);
          }
          simpleIconFallbackUrls(clean).forEach(fallbackUrl => {
            if(!delayed.includes(fallbackUrl)) delayed.push(fallbackUrl);
          });
        };
        collect(transparentLogoUrl(item));
        collect(existingLogo);
        (Array.isArray(item.logo_candidates) ? item.logo_candidates : []).forEach(collect);
        transparentPreferred.forEach(add);
        delayed.forEach(add);
        add(generatedLogoDataUrl(logoFallbackLabel(item)));
        return chain;
      }
      const generatedDataLogo = existingLogo.startsWith('data:image');
      const sourceText = String(item.source || '').toLowerCase();
      const sourceOnlyLogo = sourceText.includes('google news') && existingLogo.includes('google.com/s2/favicons');
      const backgroundRiskLogo = isLikelyBackgroundIconUrl(existingLogo);
      const officialFallbackLogo = String(item.company_detection_reason || '').includes('official_domain_favicon') ||
        String(item.company_detection_reason || '').includes('guessed_official_favicon') ||
        String(item.company_detection_reason || '').includes('transparent_known');
      const transparentLogo = transparentLogoUrl({
        logo_company:item.logo_company,
        main_company:item.main_company,
        company:item.company,
        title:''
      });
      if(!(isNews && isPublisherLogoUrl(transparentLogo))){
        add(transparentLogo);
        simpleIconFallbackUrls(transparentLogo).forEach(add);
      }
      if(!generatedDataLogo && !sourceOnlyLogo && !(backgroundRiskLogo && !officialFallbackLogo) && !(isNews && isPublisherLogoUrl(existingLogo))){
        add(existingLogo);
        simpleIconFallbackUrls(existingLogo).forEach(add);
      }
      (Array.isArray(item.logo_candidates) ? item.logo_candidates : []).forEach(url => {
        if(isNews && isGeneratedFallbackLogoUrl(url)) return;
        if(!(isNews && isPublisherLogoUrl(url))){
          add(url);
          simpleIconFallbackUrls(url).forEach(add);
        }
      });
      add(companyFaviconUrl(item));
      logoBrandFallbackUrls(item).forEach(add);
      clearbitBrandFallbackUrls(item).forEach(addCompanyFallback);
      const secondaryTransparentLogo = transparentLogoUrl(item);
      if(!(isNews && isPublisherLogoUrl(secondaryTransparentLogo))){
        add(secondaryTransparentLogo);
        simpleIconFallbackUrls(secondaryTransparentLogo).forEach(add);
      }
      add(sourceFaviconUrl(item));
      guessedBrandFallbackUrls(item).forEach(add);
      add(generatedLogoDataUrl(logoFallbackLabel(item)));
      return chain;
    }
    function sameLogoUrl(a='', b=''){
      try{
        return new URL(a, window.location.href).href === new URL(b, window.location.href).href;
      }catch{
        return String(a || '') === String(b || '');
      }
    }
    function hideFailedLogo(img){
      if(!img) return false;
      const fallback = String(img.dataset.logoFallback || '').trim();
      const currentSrc = img.currentSrc || img.src || img.getAttribute('src') || '';
      if(fallback && !sameLogoUrl(currentSrc, fallback)){
        img.dataset.logoIndex = '-1';
        img.classList.remove('logo-failed');
        const logoBox = img.closest('.card-logo');
        if(logoBox) logoBox.classList.remove('logo-empty');
        img.src = fallback;
        return true;
      }
      img.classList.add('logo-failed');
      const logoBox = img.closest('.card-logo');
      if(logoBox) logoBox.classList.add('logo-empty');
      return false;
    }
    function advanceLogoImage(img){
      if(!img) return false;
      let chain = [];
      try{
        chain = JSON.parse(img.dataset.logoChain || '[]');
      }catch{
        chain = [];
      }
      let index = Number(img.dataset.logoIndex || 0) + 1;
      const currentSrc = img.currentSrc || img.src || img.getAttribute('src') || '';
      while(chain[index] && sameLogoUrl(currentSrc, chain[index])) index++;
      if(chain[index]){
        img.dataset.logoIndex = String(index);
        img.classList.remove('logo-failed');
        const logoBox = img.closest('.card-logo');
        if(logoBox) logoBox.classList.remove('logo-empty');
        img.src = chain[index];
        return true;
      }
      return hideFailedLogo(img);
    }
    function clampLogoSize(value){
      const parsed = Number.parseInt(value, 10);
      if(!Number.isFinite(parsed)) return 30;
      return Math.max(18, Math.min(78, parsed));
    }
    function clampLogoPosition(value){
      const parsed = Number.parseFloat(value);
      if(!Number.isFinite(parsed)) return 0;
      return Math.max(-90, Math.min(190, Math.round(parsed)));
    }
    function hasLogoPositionValue(value){
      return value !== undefined && value !== null && value !== '';
    }
    function hasCustomLogoPosition(item={}){
      const logoX = hasLogoPositionValue(item.logo_x) ? item.logo_x : item.logoX;
      const logoY = hasLogoPositionValue(item.logo_y) ? item.logo_y : item.logoY;
      if(!hasLogoPositionValue(logoX) && !hasLogoPositionValue(logoY)) return false;
      const x = Number.parseFloat(logoX);
      const y = Number.parseFloat(logoY);
      return !(Number.isFinite(x) && Number.isFinite(y) && x === 0 && y === 0);
    }
    function logoSizeStyle(item={}){
      const styles = [`--logo-size:${clampLogoSize(item.logo_size || item.logoSize || 30)}px`];
      const logoX = hasLogoPositionValue(item.logo_x) ? item.logo_x : item.logoX;
      const logoY = hasLogoPositionValue(item.logo_y) ? item.logo_y : item.logoY;
      if(hasCustomLogoPosition(item) && hasLogoPositionValue(logoX)) styles.push(`--logo-x:${clampLogoPosition(logoX)}px`);
      if(hasCustomLogoPosition(item) && hasLogoPositionValue(logoY)) styles.push(`--logo-y:${clampLogoPosition(logoY)}px`);
      return styles.join(';');
    }
    function logoMarkup(item, section='', id=''){
      const chain = logoFallbackChain(item);
      const logoUrl = chain[0] || '';
      const chainAttr = escapeHtml(JSON.stringify(chain));
      const fallbackLogo = generatedLogoDataUrl(logoFallbackLabel(item));
      const actionAttrs = section && id
        ? ` data-card-action="edit-logo" data-target-section="${escapeHtml(section)}" data-target-id="${escapeHtml(id)}" role="button" tabindex="0" aria-label="${escapeHtml(t('logoSizeLabel') || 'Logo size')}" title="${escapeHtml(t('logoSizeLabel') || 'Logo size')}"`
        : '';
      return `<div class="card-logo" style="${logoSizeStyle(item)}"${actionAttrs}><img src="${escapeHtml(logoUrl || fallbackLogo)}" data-logo-chain="${chainAttr}" data-logo-index="0" data-logo-fallback="${escapeHtml(fallbackLogo)}" alt="" loading="lazy" decoding="async" fetchpriority="low" referrerpolicy="no-referrer" onerror="advanceLogoImage(this)"></div>`;
    }
