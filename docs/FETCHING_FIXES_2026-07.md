# توثيق تقني: إصلاح نظام الفتشينق (Exa + SearXNG) — يوليو 2026

> **ملاحظة:** هذا الملف يغطي المرحلة الأولى فقط (تشخيص/إصلاح الفتشينق الأصلي، قبل الانتقال لـGemini). للتعديلات الأحدث (الانتقال لـGemini، إصلاح تكرار الدورات/الاستعلامات، حماية الحفظ من التراجع، آلية التنوع المرن) شوف [`UPDATES.md`](../UPDATES.md) بجذر المشروع.

هذا التوثيق يسجّل التشخيص والإصلاحات اللي طُبّقت على خط أنابيب جلب الأخبار/الأدوات/الدورات (`backend/pipeline/fetching/`, `backend/pipeline/tool_discovery/`, `backend/pipeline/orchestrator.py`). الهدف: مرجع تقني لمن يراجع الكود لاحقًا، ومسار قرار موثّق (وش كان الخلل، وش السبب الجذري، وش الحل، وش الدليل).

**حالة هذا التوثيق:** كل مسارات الكود (A, B1–B4, C, E, F) **مُطبّقة بالكامل**. A–B3 مُختبرة بتشغيل Pipeline كامل. F (الكورسات) وC (SearXNG) **مُختبرة بتشغيل حقيقي مباشر** لدوالهما (وأصلحنا خلل حقيقي بكل مسار أثناء الاختبار — تفاصيل بقسميهما). B4 **مُختبر جزئيًا/معزول** (طلبات API مباشرة) بس لم يمر بتشغيل Pipeline كامل بعد — الاختبارات لحد الآن تعمّدنا تجنّب استهلاك حصة Gemini المجانية (`GEMINI_DAILY_REQUEST_BUDGET`) قدر الإمكان، فما شغّلنا Pipeline كامل إلا مرة وحدة (لتحقق A-B3)؛ باقي الاختبارات كانت طلبات مباشرة لـExa/SearXNG بدون المرور بمرحلة GPT/Gemini.

---

## 1. التشخيص الأصلي (بداية المحادثة)

**الأعراض المُبلَّغة:** آخر 3 تشغيلات فعلية قبل أي إصلاح انهارت تدريجيًا:

| التشغيل (run_id) | selected_count | ملاحظة |
|---|---|---|
| `full-20260708T233207Z-e5c900bb` | 5 | تحت الحد الأدنى (12) |
| `full-20260709T001924Z-01328e83` | 1 | شبه فاشل |
| `full-20260709T002327Z-75cbf1ae` | 0 | فشل كامل، `saved_news: false`، ما كُتب `news.json` |

الدليل مصدره `backend/logs/ai_updates_run.jsonl` (تحليل مباشر لأحداث `source_fetch.summary`, `quality_filter.summary`, `gpt_news_selection.summary`, `pipeline.finished`).

### الأسباب الجذرية المكتشفة

1. **Exa بدون تدوير حقيقي** — `discovery_rows(source="exa")` كان يرجع مباشرة من `exa_tool_update_script_rows()` بدون المرور بآلية `next_news_query_rotation`/`rotate_list` (اللي SearXNG وحده كان يستخدمها). النتيجة: نفس أعلى 48 أداة بنفس الترتيب كل دورة (cycle) وكل تشغيل — أثبتنا هذا بمقارنة `raw_results`/`unique_results` بين cycle 1 وcycle 2 لنفس التشغيل (كانا متطابقين تمامًا: 877 = 877).
2. **قبول صفحات الفهرس (hub pages)** — قاعدة "soft official rule" بـ`fetch_exa_query_rows` كانت تقبل أي رابط على الدومين الرسمي يحتوي كلمة "blog"/"changelog" حتى لو ما قدرنا نتحقق من تاريخ نشر حقيقي (`date_confidence: "low"`). هذا خلّى صفحات فهرس عامة (`anthropic.com/news`, `ai.meta.com/blog/`) تُقبل كـ"خبر" بدل مقال محدد.
3. **قائمة الأدوات مجمّدة** — `AI_UPDATES_TOOL_DISCOVERY_ENABLED=0` بـ`.env` يطفي اكتشاف الأدوات الجديدة كليًا. وحتى لو فُعّل، فيه خلل بنيوي بـ`maintain_monthly_tool_files`: الدالة تعمل `return` مبكر لما القائمة الرئيسية "غير قديمة" (أقل من 30 يوم) **قبل** ما تفحص استحقاق الاكتشاف الأسبوعي (7 أيام) — يعني الاكتشاف الأسبوعي المفترض ما يشتغل فعليًا إلا كل 30 يوم.
4. **SearXNG يرجّع نتائج شبه صفرية** — تأكدنا حيًا (طلبات API مباشرة): محركات Brave/DuckDuckGo/Startpage معلّقة (CAPTCHA/rate-limit) على النسخة المستضافة محليًا. بيقى Google+Bing فقط شغالين وغير مستقرين تحت الضغط.
5. **طبقة الأخبار العامة/السعودية معطّلة** — `AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED=0` (المستخدم عطّلها يدويًا بسبب نتائج رديئة/"قاربج" — لا يوجد قيد جودة على الاستعلامات المفتوحة). وحتى لو فُعّلت، `fetch_general_news_layer` كانت تستدعي Exa فقط رغم استيرادها `GENERAL_NEWS_SEARXNG_ROWS` بدون استخدامها.
6. **فلترة السيمانتك معطّلة بالكامل** — `AI_UPDATES_SEMANTIC_MEMORY_ENABLED=0` ("Gemini-only mode" بالتعليق بـ.env) — تفسّر ليش القيمة دايمًا صفر بالسجلات، مو خلل بالكود نفسه.
7. **الدورات تُجلب من Exa فقط** — تأكيد بالكود: `courses.py` ما فيه أي استدعاء لـ`fetch_searxng_query_rows`/`search_url` رغم `import *` من `news_discovery.py`. `COURSES_PER_LEVEL=2` ثابت (بدل حساب ديناميكي زي الأخبار)، والتنويع داخل المستوى يعتمد على `topic_group` بس مو البلاتفورم.
8. **فحص نشاط الأدوات كان كود ميت فعليًا** — `mark_inactive_auto_tools` تعتمد على حقول `updates_last_60_days`/`last_update_seen` اللي ما فيه أي دالة بالكود تحسبها فعليًا — الشرط كان يتحقق نظريًا بس عمليًا يفشل دايمًا.

---

## 2. الإصلاحات المُطبّقة

### A. تحرير قائمة الأدوات + نظام سكور مستمر (مُختبر ✅)

**الملفات:** `backend/.env`, `backend/pipeline/tool_discovery/tools_aware.py`

- `AI_UPDATES_TOOL_DISCOVERY_ENABLED`: `0` → `1`.
- `maintain_monthly_tool_files` ([tools_aware.py:634](../backend/pipeline/tool_discovery/tools_aware.py#L634)): فصلنا فحص `auto_expansion_due` عن شرط `monthly_stale` — الاكتشاف الأسبوعي يفحص استحقاقه بشكل مستقل الآن.
- نظام سكور جديد بدل التصفير الثنائي: `activity_score` (0-100، يبدأ 60)، `+15` لكل فحص أسبوعي يلقى تحديث حقيقي، `-15` لو ما لقى. أقل من `40` = `status: "dormant"` (تُستبعد من دورة الاستعلامات لكن تبقى بالملف، وترجع تلقائيًا لو ارتفع سكورها).
- دالة جديدة `apply_tool_activity_signal(queried_tools, active_tools)` تحدّث السكور بناء على دليل حقيقي من كل تشغيل (مو فحص منفصل مكلف — تُعاد استخدام نتائج الفتشينق العادي).
- `load_monthly_tool_records`: يستبعد الأدوات `dormant` من مجموعة الاستعلام النشطة.

### B1. تدوير استعلامات Exa + ربط إشارة النشاط (مُختبر ✅)

**الملف:** `backend/pipeline/fetching/news_discovery.py`

- دالة جديدة `next_exa_tool_rotation_offset()` ([news_discovery.py:752](../backend/pipeline/fetching/news_discovery.py#L752)) — نفس نمط `next_news_query_rotation` الموجود لـSearXNG، تُطبَّق على قائمة الأدوات (يسحب حتى 160 أداة، يدور عليها بدل نفس أعلى 48 كل مرة).
- `fetch_exa_query_rows`: يسجّل `tool_activity_queried`/`tool_activity_seen` لكل دفعة استعلام.
- `orchestrator.py`: يجمع هذي الإشارة عبر الدورات (cycles) ويستدعي `apply_tool_activity_signal` بعد انتهاء كل تشغيل كامل.

### B2. كشف تاريخ أقوى + حل صفحات الفهرس (مُختبر ✅)

**الملف:** `backend/pipeline/fetching/news_discovery.py`

- 3 كواشف تاريخ جديدة أُضيفت لـ`exa_recent_verify_date_details`:
  - `exa_recent_date_from_http_header` — هيدر `Last-Modified`.
  - `exa_recent_date_from_relative_text` — أنماط رقمية بس ("N days/hours/weeks ago", "منذ N يوم/ساعة") — تعمّدنا استبعاد كلمات عامة زي "today"/"yesterday" لأنها تعطي نتائج إيجابية كاذبة (اختُبر: طابقت نص غير مرتبط بالمقال).
  - `exa_recent_date_from_sitemap` — يجرب `sitemap.xml`/`sitemap_index.xml`/`news-sitemap.xml` ويطابق `<loc>`/`<lastmod>`.
- فحص صفحة الفهرس (hub page) صار **أول خطوة** (مو آخر واحدة) — يعيد استخدام `searxng_discovery_is_hub_page`/`searxng_discovery_split_hub` الموجودة أصلاً لـSearXNG، ويحل الصفحة لأحدث رابط مقال فعلي فيها. تأكيد حي: `cursor.com/changelog` صار يرجّع `cursor.com/changelog/side-chat` (رابط محدد) بدل صفحة الفهرس نفسها.
- حذفنا قاعدة "قبول بثقة منخفضة لما ما نلقى تاريخ" ([السطر ~2622 سابقًا](../backend/pipeline/fetching/news_discovery.py)) — الآن **رفض** بدل قبول.

### B3. طبقة الأخبار العامة/السعودية (مُختبر ✅)

**الملفات:** `backend/.env`, `backend/pipeline/fetching/news_discovery.py`

- `AI_UPDATES_GENERAL_NEWS_LAYER_ENABLED`: `0` → `1`.
- دالة جديدة `general_news_layer_domain_allowed()` — قيد دومينات موثوقة: `SAUDI_OFFICIAL_DOMAINS`/`SAUDI_TRUSTED_MEDIA_DOMAINS` لحزمة `saudi_ai_news`، و`TRUSTED_MEDIA_SOURCES` لحزم `unlisted_ai_tool_updates`/`global_ai_events`. حزمة `aggregator` تمر بدون قيد (مقيّدة أصلاً بـ`site:` بمستوى الاستعلام).
- `fetch_general_news_layer`: صار يستدعي `fetch_searxng_query_rows(GENERAL_NEWS_SEARXNG_ROWS, ...)` بالتوازي مع Exa (كانت مستوردة وغير مستخدمة).

### B4. تفعيل `startPublishedDate` لاستعلامات الأدوات + توسيع تغطية السعودية (مُطبّق، غير مُختبر بتشغيل كامل بعد ⚠️)

**الملفات:** `backend/pipeline/fetching/news_discovery.py`, `backend/pipeline/tool_discovery/queries.py`

- اكتشاف مباشر عبر اختبار Exa API حي: استعلامات الأدوات الرئيسية (`exa_script_style=True`) كانت **لا** تطلب `startPublishedDate` من Exa إطلاقًا (تعتمد بالكامل على استخراج التاريخ من HTML بعدين). تجربة حية أثبتت إن إضافة `startPublishedDate` ترجّع نتائج حقيقية أحدث بتاريخ مؤكد من Exa نفسها (`publishedDate` صحيح)، بدل صفحات evergreen قديمة.
- `exa_request()`: الآن يجرب `startPublishedDate` أول محاولة لاستعلامات `script_style`، ولو رجعت صفر نتائج (أداة هادئة فعلاً هذا الأسبوع) يعيد المحاولة بدون فلتر تاريخ كـfallback — لا يفقد أدوات هادئة كليًا.
- تأكيد end-to-end: اختبار مباشر بأداة M-Files أعطى 6/6 نتائج بـ`acceptance_reason: official_domain_exa_date` (تاريخ من Exa مباشرة، بدون الحاجة نفتح الصفحة إطلاقًا).
- `SAUDI_TRUSTED_MEDIA_DOMAINS`: 5 → 15 دومين (أضفنا العربية Business، الشرق Business، Wamda، زاوية، عكاظ، الرياض، ليدرز، تك ورلد).
- استعلامات حزمة `saudi_ai_news`: Exa من 11 → 17 (أضفنا HUMAIN، NEOM، تمويل شركات ناشئة سعودية، أبحاث جامعية/KAUST)، SearXNG من 10 → 14 بنفس المواضيع.

### E (جزئي). تفعيل السيمانتك (مُختبر ✅ — يعمل، التسجيل المنظّم لسا ناقص)

**الملف:** `backend/.env`

- `AI_UPDATES_SEMANTIC_MEMORY_ENABLED`: `0` → `1` (العتبة بقيت `0.90` بدون تعديل، حسب طلب المستخدم — مراقبة بالتشغيلات الفعلية بدل اختبار يدوي مسبق).
- تأكيد حي: التشغيل التجريبي أظهر قرارات سيمانتك فعلية (`same-run dup title='Suno Blog' score=0.8969`، وقيم `top_score` بين 0.43–0.90 لعناصر مختلفة) — الطبقة تعمل فعليًا، مو مجرد كونفج.
- **ناقص:** إضافة `log_event` منظّم لقرارات السيمانتك (بدل الاعتماد على `print` فقط) — لسا ما طُبّق.

### C. SearXNG: حل جذري + اختبار صحّة (مُختبر بتشغيل حقيقي ✅)

**الملفات:** `searxng/settings.yml`, `backend/pipeline/fetching/news_discovery.py`, `backend/pipeline/tool_discovery/tools_aware.py`, `scripts/test_searxng_health.py` (جديد)

- `searxng/settings.yml`: `outgoing.request_timeout` من `3.0` → `8.0` ثانية، وأضفنا `max_request_timeout: 12.0` — كان الـtimeout الضيق يفشّل محركات أبطأ (Bing/Startpage) حتى لو كانت ستنجح بوقت أطول.
- ثابت جديد `SEARXNG_RELIABLE_ENGINES = "google,bing"` ([news_discovery.py:112](../backend/pipeline/fetching/news_discovery.py#L112)) — كل طلبات SearXNG بالكود (الاستعلامات الأساسية، FALLBACK 3 داخل Exa، اكتشاف الأدوات الأسبوعي بـ`tools_aware.py`) توقفت عن طلب Brave/Startpage/DuckDuckGo (مؤكد حيًا إنها معلّقة CAPTCHA/rate-limit) — تبقى مفعّلة بإعدادات SearXNG نفسها فتقدر ترجع تلقائيًا لو انحل الحظر، بس ما نضيع وقت ننتظرها.
- فعّلنا سلسلة fallback الموجودة أصلاً بـ`fetch_exa_query_rows` (كانت محصورة بشرط `not script_style` فتفشل دايمًا لاستعلامات الأدوات الرئيسية) — الآن تشتغل لكل أنواع الصفوف، فيها محاولة SearXNG بدون تقييد كملاذ أخير.
- سكربت اختبار جديد `scripts/test_searxng_health.py` — يشغّل دفعة استعلامات تمثيلية ويقيس نسبة النجاح/الكمون/المحركات المعطوبة، يُستخدم للتحقق بعد أي تعديل إعدادات مستقبلي بدل التخمين. **الاختبار ما يستهلك Exa/Gemini/OpenAI إطلاقًا — طلبات HTTP محلية مباشرة لـSearXNG بس.**

**دليل تشغيل حقيقي (بعد إعادة تشغيل حاوية `searxng`):**
- أعدنا تشغيل الحاوية (`docker restart ainewsletter_v0_1-searxng-1`) حتى يفعل تعديل `settings.yml`.
- شغّلنا `scripts/test_searxng_health.py`: **12/12 نجاح (100%)**، متوسط الكمون **0.59 ثانية** (كان 55+ ثانية لـ6 استعلامات بس قبل الإصلاح).
- **ملاحظة مهمة اكتشفناها بالاختبار:** محرك Google نفسه صار الآن *أيضًا* محظور CAPTCHA (تغيّر منذ الفحص الأول بالمحادثة لما كان يشتغل). حاليًا **Bing هو المحرك الوحيد اللي يرجّع نتائج فعليًا** — Brave وDuckDuckGo وStartpage وGoogle كلهم "Suspended/CAPTCHA". النتائج (10/10 لكل استعلام) حاليًا كلها من Bing. هذا وضع متغيّر (Google كان يشتغل قبل ساعات) — `SEARXNG_RELIABLE_ENGINES` تبقى `google,bing` عمدًا (فشل Google سريع بدون ما يبطّئ الطلب، وقد يرجع يشتغل)، لكن يستاهل تراقب هذا الملف بعد فترة للتأكد أي محرك فعليًا شغّال.

### F. الدورات: SearXNG + مستهدف ديناميكي + تنويع بلاتفورم+موضوع + وزن مجاني (مُختبر بتشغيل حقيقي ✅)

**الملفات:** `backend/pipeline/fetching/courses.py`, `backend/pipeline/filtering/level_balancing.py`, `backend/pipeline/enrichment/supporting.py`

- دالة جديدة `fetch_searxng_course_platform_raw()` وصلت بـ`fetch_course_platform_discovery` بجانب Exa (كانت Exa فقط رغم استيراد كل أدوات SearXNG عبر `import *`).
- **مقاومة أعطال Exa (طلب المستخدم "أضف منطق إكسا مع الكورسات")**: `fetch_exa_course_platform_raw()` كانت ترسل طلب واحد بدون أي إعادة محاولة — أي خطأ 429/500/502/503/504 عابر كان يُسقط النتيجة نهائيًا لذلك النطاق. أضفنا نفس منطق retry/backoff الموجود بمسار الأخبار (`exa_request_once`) — حتى `AI_UPDATES_EXA_RETRIES` محاولات مع تأخير تصاعدي.
- `COURSES_PER_LEVEL`: `2` ثابت → محسوب ديناميكيًا من `COURSES_TOTAL_TARGET = 18` (نفس نمط الأخبار) = `6` لكل مستوى.
- `build_level_bank`/`select_topic_diverse` بـ[level_balancing.py](../backend/pipeline/filtering/level_balancing.py) صارت تقبل `diversity_key_fn` قابل للتخصيص — للدورات نستخدم `course_platform_topic_diversity_key` (يرفض فقط لو **البلاتفورم والموضوع معًا** متطابقين مع عنصر سابق بنفس المستوى، تكرار بلاتفورم لحاله مسموح) بدل `topic_group` فقط (اللي بقيت كما هي للأخبار).
- دالة جديدة `is_free_course()` بـ`courses.py` تحدد الدورات المجانية (دومينات معروفة + مسارات `/free-*` + كلمة "free" بالنص)، وحقل `is_free` صار يُحفظ على كل عنصر دورة. `build_level_bank` صار يقبل `sort_key_fn` اختياري — الدورات تُرتّب لتفضيل المجاني عند التعادل (بدون ما يطيح دورة أقوى مدفوعة).

**🐛 خلل حقيقي اكتُشف وأُصلح أثناء الاختبار المباشر:** `score_course_platform_result()` كان فيها `page_status.startswith(...) and title and url and direct and has_course and has_ai` بدون `bool()` — بايثون تُرجع آخر قيمة truthy مو bool بالضرورة، فلو `title` كانت فاضية (سلسلة نصية فارغة، شائع بنتائج SearXNG) كانت النتيجة تتسرب كسلسلة نصية `""` بدل `False` لمتغير `page_blocked_but_exa_enough`، وبعدين `sum([..., "" ])` يطيح البايبلاين بالكامل (`TypeError`). هذا خلل قديم موجود قبل أي تعديل مني، بس ما كان ينكشف إلا لما SearXNG بدأ يغذّي نتائج حقيقية (بعضها بدون عنوان) لأول مرة. أُصلح بلف الشرط بـ`bool(...)`.

**دليل تشغيل حقيقي (بعد الإصلاح):**
- `fetch_course_candidates()`: 8-14 مرشح لكل تشغيل، **بدون أي كراش**.
- تنويع بلاتفورم فعلي بدون تكرار: Make Academy, Notion Academy, OpenAI Academy, Miro Academy, Academy Synthesia, Microsoft Learn, Tonex, DeepLearning.AI, LinkedIn Learning, Zapier Academy — حتى بعينة صغيرة (14 عنصر) ظهرت 6-10 بلاتفورمات مختلفة.
- `is_free`: يعمل بدقة ملحوظة (Make/Synthesia/OpenAI Academy = مجاني صح، Tonex = مدفوع صح).
- `build_level_bank` مع `course_platform_topic_diversity_key`/`sort_key_fn` اشتغلت بدون أي استثناء على بيانات حقيقية.
- SearXNG بالكورسات يشتغل بنيويًا (الاستعلامات تُرسل صح) لكن يرجّع صفر حاليًا لنفس سبب مسار C (الحاوية ما أعيد تشغيلها بعد بإعدادات timeout الجديدة).

### E. تفعيل السيمانتك + تسجيل منظّم (مُكتمل ✅، الجزء الجديد غير مُختبر بتشغيل كامل بعد ⚠️)

**الملف:** `backend/pipeline/filtering/memory.py`

- `semantic_duplicate()` و طبقة same-run semantic (خارج Qdrant) صارتا تسجّلان حدث `log_event("semantic_dedup.decision", ...)` منظّم لكل قرار (قبول/رفض + السكور + العتبة + العنوانين المتقارَنين) بدل `print` وحده — يسمح بمراجعة فعلية لدقة الفلترة من `ai_updates_run.jsonl` مباشرة.

### تبعيات

- `requirements.txt`: أُضيف `lxml==6.1.1` (مطلوب لتحليل XML بدالة `exa_recent_date_from_sitemap`).
- `scripts/test_searxng_health.py`: سكربت جديد لفحص صحّة SearXNG.

---

## 3. الدليل من تشغيل حقيقي (Workstream D — تحقق جزئي)

**run_id:** `full-20260711T145419Z-d7135715` (بعد تطبيق A + B1 + B2 + B3، **قبل** B4)

| المقياس | القيمة |
|---|---|
| `selected_count` | **15** (الهدف 18، الحد الأدنى 12) |
| `saved_news` | `true` |
| `tool_files.activity_signal_applied` | `updated: 41, raised: 33, lowered: 8` |
| Exa raw/unique (cycle 1) | 960 / 174 (كانت ~830/159 قبل) |
| General layer | 188 خام → 19 بعد فلتر الدومينات (`domain_allowlist_rejected: 88`) |
| SearXNG (أدوات) | 6 استعلامات → 55 ثانية → نتيجة واحدة بس (صفحة Google News الرئيسية — عمليًا صفر فائدة) |
| SearXNG (سعودية/عامة) | 15 استعلام → 0 نتيجة (يؤكد المشكلة، Workstream C لسا مطلوب) |

**مراجعة يدوية للمخرجات الفعلية** (`frontend/news.json`, ملف تجريبي منفصل عن ملف الإنتاج `data/news/news.json` اللي لم يُمس): 15 خبر متنوع ومحدد (Suno، Grok 4.5، Cursor Side Chat، LTX-2 مفتوح المصدر، Claude Reflect، Spotify Release Radar، Google Photos Video Remix، أصوات Grok، Luma Ray3.2، Kittl Agentic AI، إيقاف OpenAI Atlas، M-Files (مقالين مختلفين)، Perplexity Comet، Layla 7) — تغطية جيدة عبر المستويات الثلاثة والقطاعات.

**ملاحظتين بسيطتين من المراجعة:** عنصرين من 15 بحقل `published` فاضي (LTX-2, Perplexity) — النموذج اختارهم بناء على السياق رغم عدم تأكد التاريخ من طبقتنا. تستاهل مراقبة، مو حرجة.

**تجربة B4 (بعد هذا التشغيل):** اختُبرت المكوّنات بشكل منعزل (طلبات API مباشرة + دالة `fetch_exa_query_rows` على صف واحد) وأثبتت عملها الصحيح، لكن **لم يُشغَّل تشغيل كامل بعدها بعد** — هذا التحقق مؤجل حسب طلب المستخدم ("خلينا نعدل كل شي والتيست بعدين").

---

## 4. الباقي

كل مسارات الكود (A, B1–B4, C, E, F) **مُطبّقة الآن بالكامل**. المتبقي فعليًا هو التحقق فقط:

| المسار | الوصف | الحالة |
|---|---|---|
| **D — تحقق نهائي** | تشغيلات Pipeline كاملة (2-3) بعد كل التعديلات (خصوصًا B4 اللي لسا ما مرت بتشغيل كامل)، للتأكد من ثبات 12+/18 للأخبار — **مؤجّل عمدًا لتوفير حصة Gemini المجانية اليومية** حتى يتأكد المستخدم إن كل شي جاهز قبل أي تشغيل يستهلك حصة حقيقية | ⏳ مؤجّل بطلب المستخدم |
| **الملف الحقيقي** | كل التحقق لحد الآن على `frontend/news.json` (ملف تجريبي)، `data/news/news.json` (الإنتاج) لم يُمس | ⏳ قرار المستخدم |
| **إعادة تشغيل SearXNG** | تعديلات `searxng/settings.yml` (timeout) تحتاج إعادة تشغيل حاوية Docker `searxng` حتى تُطبَّق فعليًا | ⏳ عند التحقق |

## 5. أشياء تعمّدنا عدم لمسها (قرارات صريحة)

- **ما أضفنا محرك SearXNG بديل** (Mojeek/Yandex) — بطلب صريح من المستخدم، الهدف نصلح المحركات الموجودة مو نوسّعها.
- **ما غيّرنا `AI_UPDATES_LOOKBACK_DAYS` (نافذة 7 أيام)** — قرار تصميم متعمّد (حداثة مقابل تغطية)، بس وثّقناه كخيار مستقبلي لو احتاج المستخدم توسيع النافذة.
- **Gemini** (ميزانية الطلبات، `gemini_failed`) — مؤجل بالكامل لمهمة منفصلة بطلب المستخدم، لم يُلمس هنا.
- **نظام فحص نشاط الأدوات** — بدّلناه بالكامل لنظام سكور مستمر بدل إصلاح الحقول الميتة القديمة (`updates_last_60_days`).
