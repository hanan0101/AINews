// PDF/preview export: sizes and captures the newsletter preview, inlines
// same-origin images for html2canvas, and hand-draws each card into the
// exported PDF with jsPDF. Depends on logoFallbackChain/hideFailedLogo
// (logo-resolver.js), t() (i18n.js), and state/els/renderNewsletter (the
// main News.html script, which loads after this file - safe because
// nothing here runs until the user opens the export preview).
    function measuredExportHeight(page, classSource=page){
      if(!page) return 1340;
      const pageRect = page.getBoundingClientRect();
      const footer = page.querySelector('.page-footer');
      const footerHeight = Math.ceil(footer?.getBoundingClientRect?.().height || 0);
      const exportTrim = classSource?.classList?.contains('course-layout') || classSource?.classList?.contains('movie-layout');
      if(!exportTrim) return Math.round(pageRect.height || page.scrollHeight || 1340);
      const selectors = ['.page-head', '.news-grid', '.section-divider', '.feature-list', '.cultural-assistant-strip'];
      const contentBottom = selectors.reduce((bottom, selector)=>{
        const el = page.querySelector(selector);
        if(!el) return bottom;
        const rect = el.getBoundingClientRect();
        return Math.max(bottom, rect.bottom - pageRect.top);
      }, 0);
      const paddingBottom = Number.parseFloat(getComputedStyle(page).paddingBottom) || 0;
      return Math.ceil(contentBottom + footerHeight + paddingBottom);
    }

    function newsletterPageSize(page=null){
      const sourcePage = document.getElementById('newsletterPage');
      const targetPage = page?.isConnected ? page : sourcePage;
      const bounds = sourcePage?.getBoundingClientRect();
      return {
        pageWidth: Math.round(bounds?.width || 1000),
        pageHeight: measuredExportHeight(targetPage, page || sourcePage)
      };
    }

    function applyNewsletterExportSize(page, {margin = '0 auto', shadow = ''} = {}){
      const {pageWidth, pageHeight} = newsletterPageSize(page);
      Object.assign(page.style, {
        width: `${pageWidth}px`,
        maxWidth: `${pageWidth}px`,
        minWidth: `${pageWidth}px`,
        height: `${pageHeight}px`,
        minHeight: `${pageHeight}px`,
        margin,
        transform: 'none',
        scale: '1',
        overflow: 'hidden'
      });
      if(shadow !== '') page.style.boxShadow = shadow;
      return {pageWidth, pageHeight};
    }

    function buildPreviewPage(){
      const pageClone = document.getElementById('newsletterPage').cloneNode(true);
      renderNewsletter(state, {page: pageClone});

      pageClone
        .querySelectorAll(exportCleanSelectors)
        .forEach(el => el.remove());

      pageClone
        .querySelectorAll('.selected')
        .forEach(el => el.classList.remove('selected'));

      pageClone.classList.add('print-clean', 'newsletter-page');

      if(state.feature_mode === 'movie'){
        pageClone.classList.add('movie-layout');
        pageClone.classList.remove('course-layout');
      } else {
        pageClone.classList.add('course-layout');
        pageClone.classList.remove('movie-layout');
      }

      /*
        هذه هي مقاسات المعاينة المعتمدة.
        PDF سيأخذ من نفس عنصر المعاينة، وليس من Layout آخر.
      */
      applyNewsletterExportSize(pageClone, {margin: '0 auto'});

      return pageClone;
    }

    function openPreview(){
      /*
        المعاينة هي مصدر الحقيقة.
        أي شيء يظهر هنا هو نفسه الذي سيتم تصديره PDF.
      */
      els.previewMount.innerHTML = '';
      els.previewMount.appendChild(buildPreviewPage());
      els.previewOverlay.classList.add('show');
    }

    async function waitForAssets(container){
      /*
        انتظار الخطوط قبل التصوير.
      */
      if(document.fonts?.ready){
        try{
          await document.fonts.ready;
        }catch{}
      }

      /*
        انتظار الصور واللوقوهات.
      */
      const images = Array.from(container.querySelectorAll('img'));

      await Promise.all(images.map(async img => {
        const timeoutMs = img.closest('.card-logo') ? 800 : 4000;
        const withTimeout = promise => Promise.race([
          promise,
          new Promise(resolve => setTimeout(resolve, timeoutMs))
        ]);
        try{
          if(img.decode){
            await withTimeout(img.decode());
            return;
          }

          if(img.complete) return;

          await withTimeout(new Promise(resolve => {
            img.onload = resolve;
            img.onerror = resolve;
          }));
        }catch{
          return;
        }
      }));

      /*
        انتظار تثبيت الـ layout بعد تحميل الخطوط والصور.
      */
      await new Promise(resolve => requestAnimationFrame(resolve));
      await new Promise(resolve => requestAnimationFrame(resolve));
      await new Promise(resolve => setTimeout(resolve, 250));
    }

    function blobToDataUrl(blob){
      return new Promise((resolve, reject)=>{
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    }

    async function fetchImageAsDataUrl(rawSrc){
      if(!rawSrc) return '';
      if(String(rawSrc).startsWith('data:')) return String(rawSrc);
      let url;
      try{
        url = new URL(rawSrc, window.location.href);
      }catch{
        return '';
      }
      const fetchUrl = url.origin === window.location.origin
        ? url.href
        : `${API_BASE}/image-proxy?url=${encodeURIComponent(url.href)}`;
      const response = await fetch(fetchUrl, {cache:'force-cache'});
      if(!response.ok) return '';
      const blob = await response.blob();
      if(!String(blob.type || '').startsWith('image/')) return '';
      return blobToDataUrl(blob);
    }

    async function inlineSameOriginImagesForCapture(container){
      const restores = [];
      const images = Array.from(container.querySelectorAll('img'));
      await Promise.all(images.map(async img => {
        const rawSrc = img.currentSrc || img.src || img.getAttribute('src') || '';
        if(!rawSrc || rawSrc.startsWith('data:')) return;
        try{
          const dataUrl = await fetchImageAsDataUrl(rawSrc);
          if(!dataUrl) return;
          const originalSrc = img.getAttribute('src');
          const originalSrcset = img.getAttribute('srcset');
          const originalSizes = img.getAttribute('sizes');
          const originalCrossOrigin = img.getAttribute('crossorigin');
          restores.push(()=> {
            if(originalSrc === null) img.removeAttribute('src');
            else img.setAttribute('src', originalSrc);
            if(originalSrcset === null) img.removeAttribute('srcset');
            else img.setAttribute('srcset', originalSrcset);
            if(originalSizes === null) img.removeAttribute('sizes');
            else img.setAttribute('sizes', originalSizes);
            if(originalCrossOrigin === null) img.removeAttribute('crossorigin');
            else img.setAttribute('crossorigin', originalCrossOrigin);
          });
          img.removeAttribute('srcset');
          img.removeAttribute('sizes');
          img.setAttribute('crossorigin', 'anonymous');
          img.setAttribute('src', dataUrl);
        }catch{
          return;
        }
      }));
      await waitForAssets(container);
      return () => restores.reverse().forEach(restore => restore());
    }

    function copyComputedCssVariables(source, target){
      const computed = getComputedStyle(source);
      for(let index = 0; index < computed.length; index++){
        const name = computed[index];
        if(name.startsWith('--')){
          target.style.setProperty(name, computed.getPropertyValue(name));
        }
      }
      const rootComputed = getComputedStyle(document.documentElement);
      for(let index = 0; index < rootComputed.length; index++){
        const name = rootComputed[index];
        if(name.startsWith('--') && !target.style.getPropertyValue(name)){
          target.style.setProperty(name, rootComputed.getPropertyValue(name));
        }
      }
    }

    async function prepareImagesForExport(container){
      async function inlineLogoFallbackForExport(img){
        let chain = [];
        try{
          chain = JSON.parse(img.dataset.logoChain || '[]');
        }catch{
          chain = [];
        }
        const startIndex = Math.max(0, Number(img.dataset.logoIndex || 0) + 1);
        for(let index = startIndex; index < chain.length; index++){
          const candidate = chain[index];
          if(!candidate) continue;
          try{
            const dataUrl = await fetchImageAsDataUrl(candidate);
            if(dataUrl){
              img.removeAttribute('srcset');
              img.removeAttribute('sizes');
              img.setAttribute('crossorigin', 'anonymous');
              img.dataset.logoIndex = String(index);
              img.classList.remove('logo-failed');
              const logoBox = img.closest('.card-logo');
              if(logoBox) logoBox.classList.remove('logo-empty');
              img.setAttribute('src', dataUrl);
              return true;
            }
          }catch{}
        }
        return false;
      }
      const images = Array.from(container.querySelectorAll('img'));
      await Promise.all(images.map(async img => {
        const rawSrc = img.currentSrc || img.src || img.getAttribute('src') || '';
        if(!rawSrc) return;
        if(rawSrc.startsWith('data:')) return;
        try{
          const dataUrl = await fetchImageAsDataUrl(rawSrc);
          if(dataUrl){
            img.removeAttribute('srcset');
            img.removeAttribute('sizes');
            img.setAttribute('crossorigin', 'anonymous');
            img.setAttribute('src', dataUrl);
            return;
          }
        }catch{}
        const logoBox = img.closest('.card-logo');
        if(logoBox){
          const recovered = await inlineLogoFallbackForExport(img);
          if(!recovered) hideFailedLogo(img);
        }
      }));
    }

    // PDF export uses the rendered preview DOM as the source of truth.
    async function getActualPreviewPageForExport(){
      const visiblePreview = els.previewMount?.querySelector('.page');
      if(visiblePreview && els.previewOverlay?.classList.contains('show')) return visiblePreview;
      // Build the same preview off-screen. Download must never open or flash
      // the visible preview window.
      const sourceHost = document.createElement('div');
      sourceHost.className = 'pdf-export-host pdf-source-host';
      const wrapper = document.createElement('div');
      wrapper.className = 'preview-window';
      const page = buildPreviewPage();
      wrapper.appendChild(page);
      sourceHost.appendChild(wrapper);
      document.body.appendChild(sourceHost);
      await new Promise(resolve => requestAnimationFrame(resolve));
      await new Promise(resolve => requestAnimationFrame(resolve));
      await new Promise(resolve => setTimeout(resolve, 150));
      if(!page){
        sourceHost.remove();
        throw new Error('Preview page was not found. PDF export must use the preview DOM.');
      }
      return page;
    }

    async function cloneCurrentPreviewForPdf(){
      const source = await getActualPreviewPageForExport();
      await waitForAssets(source);
      const temporarySourceHost = source.closest('.pdf-source-host');
      const rect = source.getBoundingClientRect();
      const width = Math.round(rect.width);
      const height = measuredExportHeight(source);
      if(!width || !height){
        throw new Error('Preview page has invalid size. Make sure preview is visible before export.');
      }
      const clone = source.cloneNode(true);
      clone.classList.add('exporting-pdf');
      clone.querySelectorAll(exportCleanSelectors).forEach(el => el.remove());
      clone.querySelectorAll('.floating-progress-host, button').forEach(el => el.remove());
      clone.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
      copyComputedCssVariables(source, clone);
      temporarySourceHost?.remove();
      Object.assign(clone.style, {
        width: `${width}px`,
        maxWidth: `${width}px`,
        minWidth: `${width}px`,
        height: `${height}px`,
        minHeight: `${height}px`,
        margin: '0',
        transform: 'none',
        scale: '1',
        boxSizing: 'border-box'
      });
      const host = document.createElement('div');
      host.className = 'pdf-export-host';
      const previewWrapper = document.createElement('div');
      previewWrapper.className = 'preview-window pdf-preview-clone-wrapper';
      previewWrapper.appendChild(clone);
      host.appendChild(previewWrapper);
      document.body.appendChild(host);
      if(document.fonts?.ready){
        try{ await document.fonts.ready; }catch{}
      }
      await prepareImagesForExport(clone);
      await waitForAssets(clone);
      await new Promise(resolve => requestAnimationFrame(resolve));
      await new Promise(resolve => requestAnimationFrame(resolve));
      return {host, clone, width, height};
    }

    function arrayBufferToBase64(buffer){
      let binary = '';
      const bytes = new Uint8Array(buffer);
      const chunkSize = 0x8000;
      for(let i=0;i<bytes.length;i+=chunkSize){
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      }
      return btoa(binary);
    }

    async function installPdfFonts(pdf){
      if(installPdfFonts.done) return installPdfFonts.done;
      installPdfFonts.done = (async ()=>{
        try{
          const regular = await fetch('fonts/Effra_Rg.ttf').then(response=>response.arrayBuffer());
          const medium = await fetch('fonts/Effra_Md.ttf').then(response=>response.arrayBuffer());
          pdf.addFileToVFS('Effra_Rg.ttf', arrayBufferToBase64(regular));
          pdf.addFont('Effra_Rg.ttf', 'Effra', 'normal');
          pdf.addFileToVFS('Effra_Md.ttf', arrayBufferToBase64(medium));
          pdf.addFont('Effra_Md.ttf', 'Effra', 'medium');
        }catch(error){
          console.warn('PDF font load failed, falling back to Helvetica', error);
        }
      })();
      return installPdfFonts.done;
    }

    function pdfShapeText(pdf, value=''){
      const text = String(value || '').replace(/\r/g, '');
      if(/[\u0600-\u06FF]/.test(text) && typeof pdf.processArabic === 'function'){
        try{return pdf.processArabic(text);}
        catch{return text;}
      }
      return text;
    }

    function pdfSetFont(pdf, weight='normal', size=14, color='#2e241d'){
      const style = weight === 'medium' || weight === 500 || weight === '500' ? 'medium' : 'normal';
      try{pdf.setFont('Effra', style);}
      catch{pdf.setFont('helvetica', style === 'medium' ? 'normal' : style);}
      pdf.setFontSize(size);
      pdf.setTextColor(color);
    }

    function pdfTextWidth(pdf, text){
      return pdf.getTextWidth(pdfShapeText(pdf, text));
    }

    function pdfWrapText(pdf, text, maxWidth, maxLines=99){
      const paragraphs = String(text || '').replace(/\r/g, '').split('\n');
      const lines = [];
      for(const paragraph of paragraphs){
        const words = paragraph.trim().split(/\s+/).filter(Boolean);
        if(!words.length){
          if(lines.length < maxLines) lines.push('');
          continue;
        }
        let line = '';
        for(const word of words){
          const test = line ? `${line} ${word}` : word;
          if(pdfTextWidth(pdf, test) <= maxWidth || !line){
            line = test;
          }else{
            lines.push(line);
            line = word;
            if(lines.length >= maxLines) break;
          }
        }
        if(lines.length >= maxLines) break;
        if(line) lines.push(line);
        if(lines.length >= maxLines) break;
      }
      return lines.slice(0, maxLines);
    }

    function pdfDrawText(pdf, text, x, y, options={}){
      pdf.text(pdfShapeText(pdf, text), x, y, {
        align: options.align || 'right',
        baseline: options.baseline || 'alphabetic'
      });
    }

    function pdfDrawWrappedText(pdf, text, x, y, width, lineHeight, maxLines, options={}){
      const lines = pdfWrapText(pdf, text, width, maxLines);
      lines.forEach((line, index)=>pdfDrawText(pdf, line, x, y + (index * lineHeight), options));
      return lines.length;
    }

    function pdfInitials(item={}){
      return '';
    }

    async function imageDataForPdf(rawSrc){
      const dataUrl = await fetchImageAsDataUrl(rawSrc);
      if(!dataUrl) return null;
      return new Promise(resolve=>{
        const image = new Image();
        image.onload = ()=>{
          try{
            const canvas = document.createElement('canvas');
            canvas.width = Math.max(1, image.naturalWidth || image.width || 96);
            canvas.height = Math.max(1, image.naturalHeight || image.height || 96);
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0,0,canvas.width,canvas.height);
            ctx.drawImage(image,0,0,canvas.width,canvas.height);
            resolve({dataUrl:canvas.toDataURL('image/png'), width:canvas.width, height:canvas.height, format:'PNG'});
          }catch{
            resolve({dataUrl, width:image.naturalWidth || image.width || 96, height:image.naturalHeight || image.height || 96, format:dataUrl.includes('image/jpeg') ? 'JPEG' : 'PNG'});
          }
        };
        image.onerror = ()=>resolve(null);
        image.src = dataUrl;
      });
    }

    async function pdfDrawContainedImage(pdf, rawSrc, x, y, boxW, boxH, fallbackLabel='', options={}){
      const image = rawSrc ? await imageDataForPdf(rawSrc) : null;
      const padding = Number(options.padding ?? 0);
      const innerX = x + padding;
      const innerY = y + padding;
      const innerW = Math.max(1, Math.min(boxW - padding * 2, Number(options.maxWidth || boxW)));
      const innerH = Math.max(1, Math.min(boxH - padding * 2, Number(options.maxHeight || boxH)));
      if(image?.dataUrl && image.width && image.height){
        const aspect = image.width / image.height;
        if(options.fallbackOnExtremeAspect && (aspect > Number(options.maxAspect || 2.8) || aspect < Number(options.minAspect || 0.36))){
          return pdfDrawContainedImage(pdf, '', x, y, boxW, boxH, fallbackLabel, {...options, fallbackOnExtremeAspect:false});
        }
        const ratio = Math.min(innerW / image.width, innerH / image.height);
        const w = image.width * ratio;
        const h = image.height * ratio;
        pdf.addImage(image.dataUrl, image.format || 'PNG', innerX + (innerW - w) / 2, innerY + (innerH - h) / 2, w, h);
        return true;
      }
      if(fallbackLabel){
        pdf.setDrawColor('#C73D39');
        pdf.setFillColor('#fffaf4');
        const fallbackW = Number(options.fallbackSize || Math.min(innerW, innerH));
        const fallbackX = x + (boxW - fallbackW) / 2;
        const fallbackY = y + (boxH - fallbackW) / 2;
        pdf.roundedRect(fallbackX, fallbackY, fallbackW, fallbackW, 7, 7, 'FD');
        pdfSetFont(pdf, 'medium', Math.min(12, fallbackW * .34), '#8e4640');
        pdf.text(String(fallbackLabel).slice(0,3).toUpperCase(), x + boxW / 2, y + boxH / 2 + 4, {align:'center'});
      }
      return false;
    }

    function pdfCardLogoUrl(item){
      return logoFallbackChain(item)[0] || item.logo || item.provider_logo || item.source_logo || '';
    }

    function pdfRectFromPage(page, element){
      const pageRect = page.getBoundingClientRect();
      const rect = element.getBoundingClientRect();
      return {
        x: rect.left - pageRect.left,
        y: rect.top - pageRect.top,
        w: rect.width,
        h: rect.height
      };
    }

    function pdfCssNumber(value, fallback=0){
      const parsed = Number.parseFloat(String(value || '').replace('px',''));
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function pdfCssColor(value, fallback='#2e241d'){
      const text = String(value || '').trim();
      const match = text.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
      if(match){
        return '#' + [match[1], match[2], match[3]].map(part => Number(part).toString(16).padStart(2,'0')).join('');
      }
      return text.startsWith('#') ? text : fallback;
    }

    function pdfElementText(element){
      return String(element?.textContent || '').replace(/\s+/g, ' ').trim();
    }

    function pdfElementImageSrc(element){
      const img = element?.querySelector?.('img');
      return img ? (img.currentSrc || img.src || img.getAttribute('src') || '') : '';
    }

    function pdfDrawCssLine(pdf, x1, y1, x2, y2, color='#C73D39', width=.7){
      pdf.setDrawColor(color);
      pdf.setLineWidth(width);
      pdf.line(x1, y1, x2, y2);
    }

    function pdfDrawDividerElement(pdf, page, divider){
      const c = pdfColors();
      if(!divider) return;
      const rect = pdfRectFromPage(page, divider);
      const y = rect.y + rect.h / 2;
      const centerX = rect.x + rect.w / 2;
      pdfDrawCssLine(pdf, rect.x, y, centerX - 16, y, c.line, .7);
      pdfDrawCssLine(pdf, centerX + 16, y, rect.x + rect.w, y, c.line, .7);
      pdf.setFillColor(c.line);
      pdf.rect(centerX - 5, y - 5, 10, 10, 'F');
    }

    function pdfDrawCardChrome(pdf, page, card, radius=20){
      const c = pdfColors();
      const rect = pdfRectFromPage(page, card);
      pdf.setFillColor(c.card);
      pdf.setDrawColor(c.border);
      pdf.setLineWidth(1);
      pdf.roundedRect(rect.x, rect.y, rect.w, rect.h, radius, radius, 'FD');
      return rect;
    }

    async function pdfDrawDomLogo(pdf, page, logoBox, fallbackLabel, options={}){
      if(!logoBox) return false;
      const rect = pdfRectFromPage(page, logoBox);
      const rawSrc = pdfElementImageSrc(logoBox);
      return pdfDrawContainedImage(pdf, rawSrc, rect.x, rect.y, rect.w, rect.h, fallbackLabel, {
        padding: Number(options.padding ?? 0),
        maxWidth: Number(options.maxWidth || rect.w),
        maxHeight: Number(options.maxHeight || rect.h),
        fallbackSize: Number(options.fallbackSize || Math.min(rect.w, rect.h)),
        fallbackOnExtremeAspect: Boolean(options.fallbackOnExtremeAspect),
        maxAspect: Number(options.maxAspect || 3.6),
        minAspect: Number(options.minAspect || .28)
      });
    }

    function pdfDrawTextElement(pdf, page, element, options={}){
      if(!element) return 0;
      const rect = pdfRectFromPage(page, element);
      const style = getComputedStyle(element);
      const fontSize = Number(options.fontSize || pdfCssNumber(style.fontSize, 14));
      const lineHeight = Number(options.lineHeight || pdfCssNumber(style.lineHeight, fontSize * 1.45));
      const fontWeight = Number.parseInt(style.fontWeight, 10) >= 700 ? 'bold' : 'normal';
      const color = options.color || pdfCssColor(style.color, '#2e241d');
      const maxLines = Number(options.maxLines || 99);
      pdfSetFont(pdf, options.weight || fontWeight, fontSize, color);
      return pdfDrawWrappedText(
        pdf,
        pdfElementText(element),
        rect.x + rect.w,
        rect.y + fontSize,
        rect.w,
        lineHeight,
        maxLines,
        {align:'right'}
      );
    }

    function pdfColors(){
      return {
        paper:'#F5EDDF',
        card:'#FBF6ED',
        footer:'#F0DECC',
        text:'#2e241d',
        muted:'#78675d',
        line:'#C73D39',
        border:'#eaded4'
      };
    }

    function pdfDrawPageFrame(pdf, width, height){
      const c = pdfColors();
      pdf.setFillColor(c.paper);
      pdf.rect(0,0,width,height,'F');
      pdf.setDrawColor(c.line);
      pdf.setLineWidth(1);
      pdf.rect(.5,.5,width-1,height-1,'S');
      pdf.rect(6,6,width-12,height-12,'S');
      pdf.setLineDashPattern([4,4],0);
      pdf.setDrawColor('#d7bba9');
      pdf.rect(14,14,width-28,height-28,'S');
      pdf.setLineDashPattern([],0);
    }

    async function pdfDrawHeader(pdf, width){
      const c = pdfColors();
      await pdfDrawContainedImage(pdf, 'image/المرصد الثقافي.png', 34, 20, 110, 70, '', {padding:2, maxWidth:110, maxHeight:70});
      await pdfDrawContainedImage(pdf, 'image/وزارة الثقافة.png', width - 244, 0, 210, 104, '', {padding:0, maxWidth:210, maxHeight:104});
      const title = String(state.template?.newsletter_title || t('newsletterTitle')).replace(/\\n/g, '\n').trim();
      pdfSetFont(pdf, 'medium', 32, c.text);
      const lines = title.split('\n').filter(Boolean);
      const startY = 68 - ((lines.length - 1) * 18);
      lines.forEach((line, index)=>pdf.text(pdfShapeText(pdf, line), width / 2, startY + index * 40, {align:'center'}));
      pdf.setDrawColor(c.line);
      pdf.setLineWidth(.8);
      pdf.line(width / 2 - 180, 128, width / 2 - 18, 128);
      pdf.line(width / 2 + 18, 128, width / 2 + 180, 128);
      pdf.setFillColor(c.line);
      pdf.rect(width / 2 - 5, 123, 10, 10, 'F');
    }

    async function pdfDrawNewsCard(pdf, item, x, y, w, h){
      const c = pdfColors();
      pdf.setFillColor(c.card);
      pdf.setDrawColor(c.border);
      pdf.roundedRect(x, y, w, h, 20, 20, 'FD');
      await pdfDrawContainedImage(pdf, pdfCardLogoUrl(item), x + 14, y - 12, 30, 30, '', {
        padding:4,
        maxWidth:22,
        maxHeight:22,
        fallbackSize:22,
        fallbackOnExtremeAspect:true
      });
      pdfSetFont(pdf, 'medium', 20, c.text);
      pdfDrawWrappedText(pdf, item.title || '', x + w - 18, y + 42, w - 70, 29, 2, {align:'right'});
      pdf.setDrawColor(c.line);
      pdf.setLineWidth(.6);
      pdf.line(x + w - 106, y + 88, x + w - 18, y + 88);
      pdfSetFont(pdf, 'normal', 15, c.muted);
      pdfDrawWrappedText(pdf, item.text || item.summary || '', x + w - 18, y + 122, w - 36, 26, 4, {align:'right'});
      pdfSetFont(pdf, 'normal', 15, '#201915');
      pdfDrawText(pdf, 'المصدر ↗', x + 90, y + h - 18, {align:'left'});
    }

    function pdfLevelLabel(level=''){
      const lower = String(level || '').toLowerCase();
      if(lower.includes('intermediate') || lower.includes('متوسط')) return 'متوسط';
      if(lower.includes('advanced') || lower.includes('متقدم')) return 'متقدم';
      return 'مبتدئ';
    }

    async function pdfDrawCourseCard(pdf, item, x, y, w, h){
      const c = pdfColors();
      pdf.setFillColor(c.card);
      pdf.setDrawColor(c.border);
      pdf.roundedRect(x, y, w, h, 20, 20, 'FD');
      await pdfDrawContainedImage(pdf, pdfCardLogoUrl(item), x + 18, y - 14, 30, 30, '', {
        padding:4,
        maxWidth:22,
        maxHeight:22,
        fallbackSize:22,
        fallbackOnExtremeAspect:true
      });
      pdfSetFont(pdf, 'medium', 18.5, c.text);
      pdfDrawWrappedText(pdf, item.title || '', x + w - 22, y + 56, w - 76, 27, 2, {align:'right'});
      pdf.setDrawColor(c.line);
      pdf.line(x + w - 142, y + 98, x + w - 22, y + 98);
      pdfSetFont(pdf, 'normal', 14.5, c.muted);
      pdfDrawWrappedText(pdf, item.text || item.summary || '', x + w - 22, y + 134, w - 44, 27, 3, {align:'right'});
      pdf.setDrawColor('#eaded4');
      pdf.line(x + 22, y + h - 46, x + w - 22, y + h - 46);
      pdfSetFont(pdf, 'normal', 14, '#201915');
      pdfDrawText(pdf, 'الدخول للدورة ↗', x + 34, y + h - 18, {align:'left'});
      pdfSetFont(pdf, 'normal', 13, '#58483f');
      pdfDrawText(pdf, `المستوى: ${pdfLevelLabel(item.level)}`, x + w - 84, y + h - 18, {align:'right'});
      pdf.setFillColor(c.line);
      pdf.circle(x + w - 70, y + h - 22, 5, 'F');
      pdf.setDrawColor(c.line);
      pdf.circle(x + w - 52, y + h - 22, 5, 'S');
      pdf.circle(x + w - 34, y + h - 22, 5, 'S');
    }

    async function pdfDrawMovieCard(pdf, item, x, y, w, h){
      const c = pdfColors();
      pdf.setFillColor(c.card);
      pdf.setDrawColor(c.border);
      pdf.roundedRect(x, y, w, h, 18, 18, 'FD');
      await pdfDrawContainedImage(pdf, item.poster || item.image || '', x + w - 150, y + 22, 112, 160, '');
      pdfSetFont(pdf, 'medium', 22, c.text);
      pdfDrawWrappedText(pdf, item.title || '', x + w - 180, y + 52, w - 230, 27, 2, {align:'right'});
      pdfSetFont(pdf, 'normal', 17, c.muted);
      pdfDrawWrappedText(pdf, item.text || item.summary || '', x + w - 180, y + 112, w - 230, 31, 2, {align:'right'});
    }
