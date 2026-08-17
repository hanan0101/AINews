const API_BASE = "/api";
    // Raised from 150 (225s) 2026-07-12: a real full pipeline run measured
    // 650-800+ seconds end to end (source fetch + 2 news-selection cycles +
    // courses/movies), so the old window gave up mid-run and showed
    // "incompleteContent" even when the backend was still working correctly
    // and later finished successfully. 1000 attempts * 1.5s = 1500s (25 min)
    // gives real margin above the worst observed run plus Gemini retry
    // backoff.
    const GENERATOR_POLL_MAX_ATTEMPTS = 1000;
    const LANGUAGE_KEY = "aiNewsletterLanguage";
    const PINNED_STATE_KEY = "aiNewsletterPinnedState";
    const EDITING_VERSION_KEY = "aiNewsletterEditingVersionId";
    const LANGUAGES = {
      ar: {
        splashTitle: "نشرة أخبار الذكاء الاصطناعي",
        newsletterTitle: "نشرة أخبار\nالذكاء الاصطناعي",
        splashIntro: "ابدأ تجهيز النشرة للحصول على أحدث الأخبار والدورات والأفلام المقترحة في تجربة جاهزة للمراجعة والتصدير.",
        createNewsletter: "إنشاء النشرة",
        retryNewsletter: "إعادة المحاولة",
        loadingNewsletter: "جاري تحميل النشرة",
        newsletterReady: "النشرة جاهزة للمراجعة",
        doneOpening: "النشرة جاهزة للمراجعة. يتم فتح صفحة المراجعة الآن...",
        loadingProgress: "تقدم التحميل",
        splashError: "تعذر تحميل المحتوى. يرجى المحاولة مرة أخرى.",
        splashStatusError: "لم نتمكن من تجهيز النشرة الآن.",
        splashErrorDetailed: "تعذر تحميل المحتوى أو إنشاء النشرة. تحقق من الاتصال ومفاتيح Gemini/OpenAI أو حدود الاستخدام ثم حاول مرة أخرى.",
        pageError: "حدث خطأ أثناء تجهيز الصفحة.",
        pageErrorDetailed: "تعذر تشغيل الصفحة. يرجى المحاولة مرة أخرى.",
        toolbarSend: "إرسال",
        toolbarSettings: "الإعدادات",
        toolbarDownload: "تنزيل",
        toolbarPreview: "معاينة",
        toolbarUndo: "تراجع",
        toolbarRedo: "إعادة",
        courseSection: "الدورات التدريبية المقترحة",
        filmSection: "الفيلم المقترح",
        courseSwitch: "دورة تدريبية",
        filmSwitch: "فيلم",
        source: "المصدر",
        courseOpen: "الدخول للدورة",
        level: "المستوى",
        beginner: "مبتدئ",
        intermediate: "متوسط",
        advanced: "متقدم",
        edit: "تعديل",
        aiPrompt: "وجهه AI",
        replace: "استبدال",
        delete: "حذف",
        editNews: "تعديل الخبر",
        editSuggested: "تعديل المحتوى المقترح",
        aiNews: "وجهه الذكاء الاصطناعي للخبر",
        aiContent: "وجهه الذكاء الاصطناعي للمحتوى",
        aiDefaultInstruction: "اجعل الصياغة أوضح وأكثر سلاسة.",
        switchMovieDone: "تم اختيار الفيلم",
        switchCourseDone: "تم اختيار الدورة",
        noAlternative: "لا يوجد بديل متاح",
        replacingItem: "جاري جلب عنصر جديد...",
        confirmFetchNew: "لا يوجد بديل متاح. هل تريد جلب عنصر جديد؟",
        alternativeTitle: "لا يوجد بديل متاح",
        alternativeText: "لا يوجد بديل متاح. هل تريد جلب عنصر جديد؟",
        fetchMore: "جلب عنصر جديد",
        cardBack: "السابق",
        cardForward: "التالي",
        fetchedApplyingReplacement: "تم جلب محتوى جديد. جاري تطبيق الاستبدال...",
        fetchedReplacementDone: "تم استبدال العنصر بعد جلب محتوى جديد",
        fetchedContentDone: "تم جلب المحتوى الجديد",
        fetchedButNoApply: "تم جلب المحتوى الجديد، لكن تعذر تطبيق الاستبدال تلقائيًا",
        generatorFetching: "جاري جلب:",
        extraFetchingSection: "جاري جلب محتوى إضافي لقسم",
        noSuitableReplacement: "لم يتم العثور على بديل مناسب. حاول مرة أخرى.",
        progressReplacing: "جاري تجهيز البديل",
        progressDeleting: "جاري التعويض بعد الحذف",
        progressLoadingMore: "جاري جلب عنصر جديد",
        progressSteps: [
          "البحث عن بديل مناسب",
          "فحص الجودة",
          "فحص التكرار",
          "تجهيز المحتوى",
          "تحديث البطاقة"
        ],
        itemReplaced: "تم استبدال العنصر",
        contentReplaced: "تم استبدال العنصر المقترح",
        fetchNewContent: "جاري جلب عنصر جديد...",
        fetchDone: "انتهى طلب الجلب",
        fetchFailed: "تعذر بدء الجلب",
        undoNone: "لا يوجد تراجع متاح",
        undoRunning: "جاري التراجع...",
        undoSaved: "تم التراجع وحفظه في الملف",
        undoFailed: "تعذر التراجع",
        redoNone: "لا يوجد إعادة متاحة",
        redoRunning: "جاري الإعادة...",
        redoSaved: "تمت الإعادة وحفظها في الملف",
        redoFailed: "تعذرت الإعادة",
        settingsSaved: "تم حفظ إعدادات النشرة",
        pdfOpening: "جاري فتح نافذة حفظ PDF...",
        pdfChoose: "اختر Save as PDF لحفظ النشرة بنفس شكل المعاينة",
        pdfError: "حدث خطأ أثناء تحميل PDF",
        saveEditRunning: "جاري حفظ التعديل...",
        saveEditDone: "تم حفظ التعديل وتحديث الملف",
        saveEditFailed: "تعذر حفظ التعديل",
        deleteConfirmTitle: "تأكيد الحذف",
        deleteConfirm: "هل تريد حذف هذا العنصر؟",
        deleteConfirmText: "هل تريد حذف هذا العنصر؟ سيتم استبداله ببديل مناسب إذا كان متاحًا.",
        deleteConfirmAction: "حذف",
        deleteRunning: "جاري حذف العنصر من الملف...",
        deleteNewsDone: "تم حذف الخبر من الملف",
        deleteItemDone: "تم حذف العنصر من الملف",
        deleteFailed: "تعذر حذف العنصر",
        aiRunning: "جاري تنفيذ توجيه الذكاء الاصطناعي...",
        aiNewsDone: "تم تنفيذ التوجيه وتحديث الخبر",
        aiLocalDone: "تم التنفيذ محليًا وتحديث الخبر",
        aiContentDone: "تم تنفيذ التوجيه وتحديث المحتوى",
        aiFailed: "تعذر تنفيذ توجيه الذكاء الاصطناعي",
        reorderSaved: "تم تحديث الترتيب",
        reorderLocal: "تم الترتيب محليًا فقط",
        incompleteContent: "تعذر إكمال المحتوى الآن، وسيبقى آخر محتوى محفوظ ظاهرًا.",
        additionalFailed: "تعذر جلب محتوى إضافي الآن.",
        lessThanRequired: "المحتوى أقل من المطلوب. جاري جلب:",
        newsLabel: "الأخبار",
        moviesLabel: "الأفلام",
        coursesLabel: "الدورات",
        modalContentChoice: "ما الذي تريد عرضه في القسم السفلي؟",
        modalMovieTitle: "فيلم",
        modalMovieDesc: "اختر فيلمًا أو وثائقيًا",
        modalCourseTitle: "دورة تدريبية",
        modalCourseDesc: "اختر دورة تدريبية مناسبة",
        editCardTitle: "تعديل البطاقة",
        titleLabel: "العنوان",
        descriptionLabel: "الوصف",
        urlLabel: "الرابط",
        sourceLabel: "المصدر",
        logoImageLabel: "شعار الشركة",
        logoSizeLabel: "حجم الشعار",
        saveEdit: "حفظ التعديل",
        cancel: "إلغاء",
        aiModalTitle: "وجهه الذكاء الاصطناعي",
        aiInstructionLabel: "اكتب التوجيه",
        aiInstructionPlaceholder: "مثال: اجعل الصياغة أكثر مهنية واختصارًا",
        run: "تنفيذ",
        settingsTitle: "إعدادات النشرة",
        saveSettings: "حفظ الإعدادات",
        downloadPdf: "تنزيل PDF",
        downloadPptx: "PowerPoint (.pptx)",
        downloadPdfHelp: "نسخة عالية الجودة للطباعة والمشاركة",
        downloadPptxHelp: "شرائح عالية الجودة قابلة للتعديل",
        pptxError: "حدث خطأ أثناء تحميل PowerPoint",
        close: "إغلاق",
        footerText: "تطوير : إدارة المرصد الثقافي\t\t|\t\tوكالة الاستراتيجيات والسياسات الثقافية\t\t|\t\tمايو 2026 م\t\t|\t\tالإصدار السابع",
        tipChooseTitle: "يمكنك اختيار ما سيظهر في القسم السفلي",
        tipChooseText: "اختر بين عرض دورة تدريبية أو فيلم.",
        tipEditTitle: "يمكنك تحرير النشرة",
        tipEditText: "يمكن تعديل كل بطاقة بشكل منفصل: العنوان، الوصف، الصورة، والمصدر.",
        tipReorderTitle: "يمكنك ترتيب المحتوى",
        tipReorderText: "اسحب بطاقات الأخبار وأفلتها لإعادة ترتيبها.",
        next: "التالي",
        done: "تم",
        landingSteps: [
          "جمع ترشيحات الدورات",
          "جمع ترشيحات الأفلام",
          "التحقق وتنقية المحتوى",
          "إزالة التكرار وفحص التشابه",
          "معالجة المحتوى بالنموذج",
          "صياغة الملخصات والتوصيات",
          "حفظ النشرة النهائية",
          "تجهيز المعاينة"
        ]
      },
      en: {
        splashTitle: "AI News Newsletter",
        newsletterTitle: "AI News\nNewsletter",
        splashIntro: "Create the newsletter to prepare the latest AI news, course picks, and film recommendations for review and export.",
        createNewsletter: "Create Newsletter",
        retryNewsletter: "Try Again",
        loadingNewsletter: "Loading Newsletter",
        newsletterReady: "Newsletter Ready for Review",
        doneOpening: "Newsletter ready for review. Opening the review page now...",
        loadingProgress: "Loading Progress",
        splashError: "Could not load the content. Please try again.",
        splashStatusError: "We could not prepare the newsletter right now.",
        splashErrorDetailed: "Could not load or create the newsletter. Check the connection, Gemini/OpenAI keys, or quota limits, then try again.",
        pageError: "An error occurred while preparing the page.",
        pageErrorDetailed: "Could not start the page. Please try again.",
        toolbarSend: "Send",
        toolbarSettings: "Settings",
        toolbarDownload: "Download",
        toolbarPreview: "Preview",
        toolbarUndo: "Undo",
        toolbarRedo: "Redo",
        courseSection: "Course Recommendations",
        filmSection: "Film Recommendation",
        courseSwitch: "Course",
        filmSwitch: "Film",
        source: "Source",
        courseOpen: "Open Course",
        level: "Level",
        beginner: "Beginner",
        intermediate: "Intermediate",
        advanced: "Advanced",
        edit: "Edit",
        aiPrompt: "AI Prompt",
        replace: "Replace",
        delete: "Delete",
        editNews: "Edit News Item",
        editSuggested: "Edit Suggested Content",
        aiNews: "Prompt AI for News Item",
        aiContent: "Prompt AI for Content",
        aiDefaultInstruction: "Make the wording clearer and smoother.",
        switchMovieDone: "Film selected",
        switchCourseDone: "Course selected",
        noAlternative: "No replacement is available",
        replacingItem: "Fetching a new item...",
        confirmFetchNew: "No replacement is available. Do you want to fetch a new item?",
        alternativeTitle: "No replacement is available",
        alternativeText: "No replacement is available. Do you want to fetch a new item?",
        fetchMore: "Fetch new item",
        cardBack: "Back",
        cardForward: "Forward",
        fetchedApplyingReplacement: "New content fetched. Applying the replacement...",
        fetchedReplacementDone: "Item replaced after fetching new content",
        fetchedContentDone: "New content fetched",
        fetchedButNoApply: "New content was fetched, but automatic replacement could not be applied.",
        generatorFetching: "Fetching:",
        extraFetchingSection: "Fetching additional content for",
        noSuitableReplacement: "No suitable replacement found. Try again.",
        progressReplacing: "Preparing replacement",
        progressDeleting: "Replacing deleted card",
        progressLoadingMore: "Fetching a new item",
        progressSteps: [
          "Searching for replacement",
          "Checking quality",
          "Checking duplicates",
          "Preparing content",
          "Updating card"
        ],
        itemReplaced: "Item replaced",
        contentReplaced: "Suggested item replaced",
        fetchNewContent: "Fetching a new item...",
        fetchDone: "Fetch request finished",
        fetchFailed: "Could not start fetching",
        undoNone: "No undo is available",
        undoRunning: "Undoing...",
        undoSaved: "Undo saved to the file",
        undoFailed: "Could not undo",
        redoNone: "No redo is available",
        redoRunning: "Redoing...",
        redoSaved: "Redo saved to the file",
        redoFailed: "Could not redo",
        settingsSaved: "Delivery email saved",
        pdfOpening: "Opening the PDF save window...",
        pdfChoose: "Choose Save as PDF to preserve the preview layout",
        pdfError: "An error occurred while loading the PDF",
        saveEditRunning: "Saving the edit...",
        saveEditDone: "Edit saved and file updated",
        saveEditFailed: "Could not save the edit",
        deleteConfirmTitle: "Confirm deletion",
        deleteConfirm: "Do you want to delete this item?",
        deleteConfirmText: "Do you want to delete this item? It will be replaced with a suitable alternative if available.",
        deleteConfirmAction: "Delete",
        deleteRunning: "Deleting the item from the file...",
        deleteNewsDone: "News item deleted from the file",
        deleteItemDone: "Item deleted from the file",
        deleteFailed: "Could not delete the item",
        aiRunning: "Running the AI prompt...",
        aiNewsDone: "Prompt applied and news item updated",
        aiLocalDone: "Applied locally and updated the news item",
        aiContentDone: "Prompt applied and content updated",
        aiFailed: "Could not run the AI prompt",
        reorderSaved: "Order updated",
        reorderLocal: "Order changed locally only",
        incompleteContent: "Could not complete the content now, so the last saved content will remain visible.",
        additionalFailed: "Could not fetch additional content now.",
        lessThanRequired: "Content is below the required amount. Fetching:",
        newsLabel: "news",
        moviesLabel: "films",
        coursesLabel: "courses",
        modalContentChoice: "What should appear in the lower section?",
        modalMovieTitle: "Film",
        modalMovieDesc: "Choose a film or documentary",
        modalCourseTitle: "Course",
        modalCourseDesc: "Choose a suitable course",
        editCardTitle: "Edit Card",
        titleLabel: "Title",
        descriptionLabel: "Description",
        urlLabel: "URL",
        sourceLabel: "Source",
        logoImageLabel: "Company logo URL",
        logoSizeLabel: "Logo size",
        saveEdit: "Save Edit",
        cancel: "Cancel",
        aiModalTitle: "Prompt AI",
        aiInstructionLabel: "Write the prompt",
        aiInstructionPlaceholder: "Example: make the wording more professional and concise",
        run: "Run",
        settingsTitle: "Newsletter Settings",
        saveSettings: "Save Settings",
        downloadPdf: "Download PDF",
        downloadPptx: "PowerPoint (.pptx)",
        downloadPdfHelp: "High-quality copy for printing and sharing",
        downloadPptxHelp: "High-quality, editable slides",
        pptxError: "An error occurred while downloading PowerPoint",
        close: "Close",
        footerText: "Cultural Observatory\t|\tMay\t|\tSixteenth Edition",
        tipChooseTitle: "Choose what appears in the lower section",
        tipChooseText: "Switch between a course recommendation and a film.",
        tipEditTitle: "Edit the newsletter",
        tipEditText: "Each card can be edited separately: title, description, image, and source.",
        tipReorderTitle: "Reorder the content",
        tipReorderText: "Drag and drop news cards to change their order.",
        next: "Next",
        done: "Done",
        landingSteps: [
          "Fetch Course Recommendations",
          "Fetch Film Recommendations",
          "Validate and Filter Content",
          "Remove Duplicates and Check Similarity",
          "Process Content with AI Model",
          "Generate Summaries and Recommendations",
          "Save Final Newsletter",
          "Prepare Preview"
        ]
      }
    };
    const savedLanguage = "ar";
    LANGUAGES.ar.landingSteps = [
      "جلب وتنقية أخبار الذكاء الاصطناعي",
      "جلب ومعالجة ترشيحات الدورات",
      "جلب ومعالجة ترشيحات الأفلام",
      "حفظ النشرة النهائية",
      "تجهيز المعاينة",
      "النشرة جاهزة للمراجعة"
    ];
    LANGUAGES.en.landingSteps = [
      "Fetch and Filter AI News",
      "Fetch and Process Courses",
      "Fetch and Process Films",
      "Save Final Newsletter",
      "Prepare Preview",
      "Newsletter Ready for Review"
    ];
    const state = {items:[], all_items:[], movies:[], courses:[], news_bank:{}, courses_bank:{}, recommended_view:{}, saved_views:{}, defaultView:{}, selectedLevels:['all'], newsDisplayCount:4, viewInitialized:false, newsViewOverride:null, coursesViewOverride:null, movieViewOverride:null, levelFilterOpen:false, newsCountFilterOpen:false, toolbarFilterOutsideBound:false, feature_mode:"course", feature_item:null, selected:null, undoStack:[], redoStack:[], reorderSupported:true, editTarget:null, logoEditTarget:null, logoDrag:null, logoSaveTimer:null, suppressLogoClickUntil:0, aiTarget:null, alternativeTarget:null, alternativeResolve:null, deleteConfirmResolve:null, cardNav:{}, cardNavPending:{}, card_refill_history:{}, contentSignature:'', onboarding:null, language:"ar", cardProgress:{}, cardProgressTimers:{}, cardProgressAbort:{}, tips:{choose:false,edit:false,reorder:false}, tipTimers:{}, generator:null, timeline:[], previous_counts:{}, isAdmin:false, versionTitle:'', generationCancelRequested:false};
    // Native browser title bubbles cannot be styled; the toolbar uses the
    // accessible aria-label with the custom tooltip defined above instead.
    document.querySelectorAll('.topbar [title]').forEach(element => element.removeAttribute('title'));
    const els = {
      splash: document.getElementById('splashScreen'),
      shell: document.getElementById('appShell'),
      generateBtn: document.getElementById('generateNewsletterBtn'),
      cancelGenerationBtn: document.getElementById('cancelGenerationBtn'),
      splashTitle: document.querySelector('.splash-title'),
      splashStatus: document.getElementById('splashStatus'),
      splashError: document.getElementById('splashError'),
      splashSteps: document.getElementById('splashSteps'),
      splashProgress: document.getElementById('splashProgress'),
      splashProgressLabel: document.getElementById('splashProgressLabel'),
      newsGrid: document.getElementById('newsGrid'),
      levelFilter: document.getElementById('levelFilter'),
      newsCountFilter: document.getElementById('newsCountFilter'),
      downloadExport: document.getElementById('downloadExport'),
      downloadButton: document.querySelector('[data-action="download"]'),
      featureTitle: document.getElementById('featureSectionTitle'),
      featureList: document.getElementById('featureList'),
      page: document.getElementById('newsletterPage'),
      newsletterTitle: document.getElementById('newsletterTitle'),
      contentTypeOverlay: document.getElementById('contentTypeOverlay'),
      editOverlay: document.getElementById('editOverlay'),
      previewOverlay: document.getElementById('previewOverlay'),
      previewMount: document.getElementById('previewMount'),
      downloadLoadingOverlay: document.getElementById('downloadLoadingOverlay'),
      aiOverlay: document.getElementById('aiOverlay'),
      alternativeOverlay: document.getElementById('alternativeOverlay'),
      alternativeFetchBtn: document.getElementById('alternativeFetchBtn'),
      alternativeModalTitle: document.getElementById('alternativeModalTitle'),
      alternativeModalText: document.getElementById('alternativeModalText'),
      deleteConfirmOverlay: document.getElementById('deleteConfirmOverlay'),
      deleteConfirmBtn: document.getElementById('deleteConfirmBtn'),
      deleteConfirmTitle: document.getElementById('deleteConfirmTitle'),
      deleteConfirmText: document.getElementById('deleteConfirmText'),
      settingsOverlay: document.getElementById('settingsOverlay'),
      toast: document.getElementById('toast'),
      floatingProgressHost: document.getElementById('floatingProgressHost'),
      editForm: document.getElementById('editForm'),
      aiForm: document.getElementById('aiForm'),
      settingsForm: document.getElementById('settingsForm'),
      aiInstruction: document.getElementById('aiInstruction'),
      aiModalTitle: document.getElementById('aiModalTitle'),
      settingsNewsletterTitle: document.getElementById('settingsNewsletterTitle'),
      settingsFooterPrefix: document.getElementById('settingsFooterPrefix'),
      settingsMonthYear: document.getElementById('settingsMonthYear'),
      settingsIssueNumber: document.getElementById('settingsIssueNumber'),
      editTitle: document.getElementById('editTitle'),
      editText: document.getElementById('editText'),
      editUrl: document.getElementById('editUrl'),
      editSource: document.getElementById('editSource'),
      editLevelField: document.getElementById('editLevelField'),
      editLevel: document.getElementById('editLevel'),
      editLevelFilter: document.getElementById('editLevelFilter'),
      editLevelToggle: document.getElementById('editLevelToggle'),
      editLevelText: document.getElementById('editLevelText'),
      editLogo: document.getElementById('editLogo'),
      editLogoSize: document.getElementById('editLogoSize'),
      editLogoSizeValue: document.getElementById('editLogoSizeValue'),
      editModalTitle: document.getElementById('editModalTitle'),
      logoEditorOverlay: document.getElementById('logoEditorOverlay'),
      logoEditorScrim: document.getElementById('logoEditorScrim'),
      logoEditorClose: document.getElementById('logoEditorClose'),
      logoEditorPreview: document.getElementById('logoEditorPreview'),
      logoEditorTitle: document.getElementById('logoEditorTitle'),
      logoEditorSize: document.getElementById('logoEditorSize'),
      logoEditorSizeValue: document.getElementById('logoEditorSizeValue'),
      logoEditorSave: document.getElementById('logoEditorSave'),
      logoEditorCancel: document.getElementById('logoEditorCancel'),
      tipChoose: document.getElementById('tipChoose'),
      tipEdit: document.getElementById('tipEdit'),
      tipReorder: document.getElementById('tipReorder'),
    };

    function viewerCanRequest(url, options={}){
      if(state.isAdmin) return true;
      const method = String(options.method || 'GET').toUpperCase();
      const target = String(url || '');
      if(method === 'GET') return true;
      if(method === 'POST' && (target.includes('/api/export-pdf') || target.includes('/api/export-pptx') || target.includes('/auth/logout'))) return true;
      return false;
    }
    async function request(url, options={}){
      if(!viewerCanRequest(url, options)){
        throw new Error('Read-only user cannot perform this action');
      }
      const response = await fetch(url,{cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
      const data = await response.json().catch(()=>({}));
      if(!response.ok){
        const error = new Error(data.message || data.error || 'Request failed');
        error.data = data;
        throw error;
      }
      return data;
    }
    async function loadAuthState(){
      try{
        const auth = await request(`${API_BASE}/auth/me`);
        document.body.classList.toggle('is-admin', !!auth.is_admin);
        document.body.classList.toggle('is-user', !!auth.is_user);
        state.isAdmin = !!auth.is_admin;
        document.body.classList.toggle('viewer-mode', !state.isAdmin);
        updateRoleAwareLabels();
        applyRolePermissions();
        removeStrayLogoutButtons();
        return auth;
      }catch(error){
        if(error?.data?.error) window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
        throw error;
      }
    }
    function updateRoleAwareLabels(){
      const versionsButton = document.querySelector('[data-action="versions"]');
      if(versionsButton && !state.isAdmin){
        const label = versionsButton.querySelector('span');
        if(label) label.textContent = 'النسخ السابقة';
        versionsButton.removeAttribute('title');
        versionsButton.setAttribute('aria-label', 'النسخ السابقة');
      }
    }
    function applyRolePermissions(){
      if(state.isAdmin) return;
      const adminSelectors = [
        '[data-admin-only]',
        '[data-action="new-newsletter"]',
        '[data-action="save-version"]',
        '[data-action="settings"]',
        '[data-action="preview"]',
        '[data-action="undo"]',
        '[data-action="redo"]',
        '[data-action="pin-page"]',
        '.splash-versions-link',
        '.card-popover',
        '.news-count-filter',
        '#contentTypeOverlay',
        '#editOverlay',
        '#aiOverlay',
        '#settingsOverlay',
        '#alternativeOverlay',
        '#deleteConfirmOverlay',
        '#logoEditorOverlay',
        '.tip-pop',
        '.floating-progress-host'
      ];
      hideAdminOnlySelectors(adminSelectors);
      document.querySelectorAll('.card-logo').forEach(element=>{
        element.style.pointerEvents = 'none';
        element.style.cursor = 'default';
      });
    }
    function removeStrayLogoutButtons(){
      document.querySelectorAll('[data-action="logout"]').forEach(button=>button.remove());
    }
    async function saveVersion() {
      try {
        // Commit only the currently selected Mode + Level/general view. Other
        // contexts stay untouched and retain their own last saved ordering.
        markCurrentViewAsDefault();
        commitCurrentViewToSavedViews();
        const persisted = await request(`${API_BASE}/state`, {
          method:'PUT',
          body:JSON.stringify(snapshotPayload())
        });
        applyState(persisted);
        restoreSavedViewForContext();
        render();
        const editingId = currentEditingVersionId();
        const res = await fetch(editingId ? `/api/versions/${editingId}` : '/api/versions', {
          method: editingId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: editingId ? JSON.stringify({ save_current: true }) : undefined
        });
        const savedRecord = await res.json().catch(()=>({}));
        if (res.ok) {
          if(savedRecord?.title) state.versionTitle = String(savedRecord.title).trim();
          if (editingId) {
            showPlainToast('تم تحديث النسخة');
            return;
          }
          showPlainToast('تم حفظ النسخة');
        } else if(savedRecord?.code === 'duplicate_version_title' || res.status === 409) {
          showPlainToast('\u064a\u0648\u062c\u062f \u0645\u0644\u0641 \u0645\u062d\u0641\u0648\u0638 \u0628\u0646\u0641\u0633 \u0627\u0644\u0627\u0633\u0645\u060c \u0627\u062e\u062a\u0631 \u0627\u0633\u0645\u064b\u0627 \u0645\u062e\u062a\u0644\u0641\u064b\u0627');
        } else {
          showPlainToast('لا يوجد محتوى للحفظ');
        }
      } catch (e) {
        showPlainToast('تعذر حفظ النسخة');
      }
    }
    function showToast(msg){ flashToastElement(els.toast, t(msg)); }
    function showPlainToast(message){ flashToastElement(els.toast, message); }
    function bindTips(){
      document.querySelectorAll('[data-tip-next]').forEach(btn=>{
        btn.addEventListener('click', ()=>{
          const step = btn.dataset.tipNext;
          if(step==='choose'){
            state.tips.choose = true;
            hideTip('choose');
            return;
          }
          if(step==='edit'){ state.tips.edit = true; hideTip('edit'); return; }
          if(step==='reorder'){ state.tips.reorder = true; hideTip('reorder'); return; }
        });
      });
    }
    function hideTip(step){
      if(state.tipTimers?.[step]){
        clearTimeout(state.tipTimers[step]);
        delete state.tipTimers[step];
      }
      if(step==='choose') els.tipChoose.classList.remove('show');
      if(step==='edit') els.tipEdit.classList.remove('show');
      if(step==='reorder') els.tipReorder.classList.remove('show');
    }
    function scheduleTipAutoHide(step){
      if(!step) return;
      if(state.tipTimers?.[step]) clearTimeout(state.tipTimers[step]);
      state.tipTimers[step] = setTimeout(()=>{
        state.tips[step] = true;
        hideTip(step);
      }, 10000);
    }
    function showTip(step){
      if(!step) return [els.tipChoose, els.tipEdit, els.tipReorder].forEach(el=>el && el.classList.remove('show'));
      if(step==='choose' && !state.tips.choose){ els.tipChoose.classList.add('show'); scheduleTipAutoHide('choose'); }
      if(step==='edit' && !state.tips.edit){ els.tipEdit.classList.add('show'); scheduleTipAutoHide('edit'); }
      if(step==='reorder' && !state.tips.reorder){ els.tipReorder.classList.add('show'); scheduleTipAutoHide('reorder'); }
    }
    function showTips(steps=[]){
      [els.tipChoose, els.tipEdit, els.tipReorder].forEach(el=>el && el.classList.remove('show'));
      steps.forEach(showTip);
    }
    function markGuide(step){ showTip(step); }
    const TRANSPARENT_LOGOS = {
      openai:'https://cdn.simpleicons.org/openai',
      chatgpt:'https://cdn.simpleicons.org/openai',
      google:'https://cdn.simpleicons.org/google',
      gemini:'https://cdn.simpleicons.org/googlegemini',
      deepmind:'https://cdn.simpleicons.org/googledeepmind',
      microsoft:'https://cdn.simpleicons.org/microsoft',
      'مايكروسوفت':'https://cdn.simpleicons.org/microsoft',
      azure:'https://cdn.simpleicons.org/microsoftazure',
      copilot:'https://cdn.simpleicons.org/githubcopilot',
      github:'https://cdn.simpleicons.org/github',
      anthropic:'https://cdn.simpleicons.org/anthropic',
      claude:'https://cdn.simpleicons.org/claude',
      meta:'https://cdn.simpleicons.org/meta',
      xai:'https://cdn.simpleicons.org/x',
      nvidia:'https://cdn.simpleicons.org/nvidia',
      adobe:'https://cdn.simpleicons.org/adobe',
      amazon:'https://cdn.simpleicons.org/amazon',
      alexa:'https://cdn.simpleicons.org/amazon',
      'أمازون':'https://cdn.simpleicons.org/amazon',
      aws:'https://cdn.simpleicons.org/amazonaws',
      apple:'https://cdn.simpleicons.org/apple',
      ibm:'https://cdn.simpleicons.org/ibm',
      cisco:'https://cdn.simpleicons.org/cisco',
      deel:'https://cdn.simpleicons.org/deel',
      rivian:'https://cdn.simpleicons.org/rivian',
      uber:'https://cdn.simpleicons.org/uber',
      kayak:'https://cdn.simpleicons.org/kayak',
      ixigo:'https://cdn.simpleicons.org/ixigo',
      autodesk:'https://cdn.simpleicons.org/autodesk',
      revit:'https://cdn.simpleicons.org/autodesk',
      sensetime:'https://cdn.simpleicons.org/sensetime',
      gauth:'https://cdn.simpleicons.org/gauth',
      oracle:'https://cdn.simpleicons.org/oracle',
      canva:'https://cdn.simpleicons.org/canva',
      coursera:'https://cdn.simpleicons.org/coursera',
      edx:'https://cdn.simpleicons.org/edx',
      udacity:'https://cdn.simpleicons.org/udacity',
      udemy:'https://cdn.simpleicons.org/udemy',
      kaggle:'https://cdn.simpleicons.org/kaggle',
      linkedin:'https://cdn.simpleicons.org/linkedin',
      pluralsight:'https://cdn.simpleicons.org/pluralsight',
      techcrunch:'https://cdn.simpleicons.org/techcrunch',
      'the verge':'https://cdn.simpleicons.org/theverge',
      verge:'https://cdn.simpleicons.org/theverge',
      wired:'https://cdn.simpleicons.org/wired',
      bloomberg:'https://cdn.simpleicons.org/bloomberg',
      venturebeat:'https://cdn.simpleicons.org/venturebeat',
      huggingface:'https://cdn.simpleicons.org/huggingface',
      'hugging face':'https://cdn.simpleicons.org/huggingface',
      mistral:'https://cdn.simpleicons.org/mistralai',
      'mistral ai':'https://cdn.simpleicons.org/mistralai',
      perplexity:'https://cdn.simpleicons.org/perplexity',
      cohere:'https://cdn.simpleicons.org/cohere',
      midjourney:'https://cdn.simpleicons.org/midjourney',
      runway:'https://cdn.simpleicons.org/runway',
      elevenlabs:'https://cdn.simpleicons.org/elevenlabs',
      notion:'https://cdn.simpleicons.org/notion',
      'notion ai':'https://cdn.simpleicons.org/notion',
      n8n:'https://cdn.simpleicons.org/n8n',
      shopify:'https://cdn.simpleicons.org/shopify',
      sap:'https://cdn.simpleicons.org/sap',
      servicenow:'https://cdn.simpleicons.org/servicenow',
      ringcentral:'https://cdn.simpleicons.org/ringcentral',
      calendly:'https://cdn.simpleicons.org/calendly',
      tableau:'https://cdn.simpleicons.org/tableau',
      storyteq:'https://cdn.simpleicons.org/storyteq',
      anysphere:'https://cdn.simpleicons.org/cursor',
      cursor:'https://cdn.simpleicons.org/cursor',
      reallusion:'https://www.reallusion.com/about/includes/image/press_resource_product/rl/reallusion-logo-horizontal-lightbg_2000x443.png'
    };
    const TRANSPARENT_LOGO_ALIASES = [
      ['google deepmind','deepmind'],
      ['google gemini','gemini'],
      ['google ai','google'],
      ['microsoft learn','microsoft'],
      ['linkedin learning','linkedin'],
      ['مايكروسوفت','microsoft'],
      ['أوبر','uber'],
      ['اوبر','uber'],
      ['x.ai','xai'],
      ['xai','xai'],
      ['grok','xai'],
      ['anysphere','cursor'],
      ['cursor','cursor'],
      ['reallusion','reallusion']
    ];
    const COMPANY_FAVICON_DOMAINS = {
      openai:'openai.com',
      chatgpt:'chatgpt.com',
      google:'google.com',
      gemini:'gemini.google.com',
      'google translate':'translate.google.com',
      microsoft:'microsoft.com',
      'مايكروسوفت':'microsoft.com',
      anthropic:'anthropic.com',
      claude:'claude.ai',
      meta:'meta.com',
      xai:'x.ai',
      grok:'x.ai',
      nvidia:'nvidia.com',
      adobe:'adobe.com',
      cisco:'cisco.com',
      deel:'deel.com',
      rivian:'rivian.com',
      amazon:'amazon.com',
      alexa:'amazon.com',
      'أمازون':'amazon.com',
      aws:'aws.amazon.com',
      apple:'apple.com',
      ibm:'ibm.com',
      oracle:'oracle.com',
      uber:'uber.com',
      kayak:'kayak.com',
      ixigo:'ixigo.com',
      ai2:'allenai.org',
      molmo:'allenai.org',
      gauth:'gauthmath.com',
      canva:'canva.com',
      coursera:'coursera.org',
      edx:'edx.org',
      udacity:'udacity.com',
      udemy:'udemy.com',
      kaggle:'kaggle.com',
      linkedin:'linkedin.com',
      pluralsight:'pluralsight.com',
      jstor:'jstor.org',
      notion:'notion.so',
      figma:'figma.com',
      deepl:'deepl.com',
      stripe:'stripe.com',
      storyteq:'storyteq.com',
      autodesk:'autodesk.com',
      n8n:'n8n.io',
      shopify:'shopify.com',
      sap:'sap.com',
      servicenow:'servicenow.com',
      ringcentral:'ringcentral.com',
      calendly:'calendly.com',
      perplexity:'perplexity.ai',
      cohere:'cohere.com',
      midjourney:'midjourney.com',
      runway:'runwayml.com',
      elevenlabs:'elevenlabs.io',
      tableau:'tableau.com',
      techcrunch:'techcrunch.com',
      'the verge':'theverge.com',
      verge:'theverge.com',
      wired:'wired.com',
      bloomberg:'bloomberg.com',
      venturebeat:'venturebeat.com',
      huggingface:'huggingface.co',
      'hugging face':'huggingface.co',
      mistral:'mistral.ai',
      'mistral ai':'mistral.ai',
      anysphere:'anysphere.inc',
      cursor:'cursor.com',
      reallusion:'reallusion.com'
    };
    const SIMPLE_ICON_FALLBACK_DOMAINS = {
      adobephotoshop:'adobe.com',
      amazonaws:'aws.amazon.com',
      githubcopilot:'github.com',
      googledeepmind:'deepmind.google',
      googlegemini:'gemini.google.com',
      huggingface:'huggingface.co',
      mistralai:'mistral.ai',
      microsoftazure:'azure.microsoft.com',
      oracle:'oracle.com',
      jstor:'jstor.org',
      theverge:'theverge.com',
      anysphere:'anysphere.inc',
      cursor:'cursor.com',
      reallusion:'reallusion.com',
      x:'x.ai'
    };
    const NEWS_PUBLISHER_LOGO_KEYS = new Set([
      'techcrunch','the verge','verge','reuters','venturebeat','zdnet','bbc',
      'wired','bloomberg','the decoder','theguardian','guardian','wsj',
      'arstechnica','technologyreview'
    ]);
    const NEWS_PUBLISHER_LOGO_URL_PARTS = [
      'simpleicons.org/techcrunch','simpleicons.org/theverge','simpleicons.org/reuters',
      'simpleicons.org/venturebeat','simpleicons.org/zdnet','simpleicons.org/bbc',
      'simpleicons.org/wired','simpleicons.org/bloomberg',
      'domain=techcrunch.com','domain=theverge.com','domain=reuters.com',
      'domain=venturebeat.com','domain=zdnet.com','domain=bbc.com',
      'domain=bbc.co.uk','domain=wired.com','domain=bloomberg.com',
      'domain=the-decoder.com','domain=theguardian.com','domain=wsj.com',
      'domain=arstechnica.com','domain=technologyreview.com'
    ];
