# تدقيق وتسليم كود نظام النشرة

> تاريخ التحقق: 2026-07-30 — عدد الملفات المهمة المفهرسة: **156**.

## النتيجة النهائية

- يبدأ الدليل بالباك إند ثم `backend/auth` كما هو ترتيب الشجرة الفعلي.
- نظام المصادقة الحالي جزء عامل من المنتج ولم يُحذف. لم تُضف متطلبات أمنية جديدة إلى نطاق التسليم.
- حُذفت واجهات التوافق المكررة والكود الميت المؤكد فقط، مع تحديث جميع الاستيرادات.
- لا توجد جدولة نشر للنشرة؛ النظام يولّد النسخة عند طلب المستخدم فقط.
- `requirements.txt` دُقق مقابل استيرادات `backend` و`scripts` ويغطي المكتبات المباشرة، مع اختبار آلي لذلك.

## مسار النظام المختصر

`backend/auth` → `backend/server/http_server.py` → `backend/server/generator_bridge.py` → `backend/pipeline/orchestrator.py` → مراحل `fetching / filtering / modeling / enrichment`، وفي كل مرحلة تظهر `news / courses / films` تحت مجلد `content` → التخزين → واجهة `frontend` والتصدير.

## خريطة الملفات بالترتيب الفعلي

الترتيب أدناه هو ترتيب المسارات الحالي، وليس ترتيبًا نظريًا. عمود القرار يوضح إن كان الملف قابلًا للحذف.

### `backend/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `backend/auth/authentication.py` | Python | مصادقة المستخدم مع Keycloak، قراءة وتجديد الجلسة، والتحقق من دوري المستخدم والمدير. | مكونات: `keycloak_client`, `authenticate`, `refresh_token`, `access_token_from_headers`, `refresh_token_from_headers`, `user_from_access_token`, `user_from_headers`, `user_from_headers_with_refresh`, `require_user`, `require_admin`؛ يعتمد على: `base64`, `hashlib`, `hmac`, `http.cookies`, `json`, `os`, `time`, `urllib.parse` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/auth/keycloak_bootstrap.py` | Python | تهيئة realm وعميل النظام والأدوار وحسابات التطوير في Keycloak عند بدء البيئة. | مكونات: `bootstrap_keycloak_if_missing`؛ يعتمد على: `__future__`, `backend.auth.authentication`, `backend.utils.debug_logging`, `json`, `os`, `time`, `urllib.error`, `urllib.parse` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/.env` | Config | إعدادات وأسرار التشغيل المحلية؛ لا تُرفع للمستودع ولا تُسلّم للعميل ضمن الكود. | لا يحتوي واجهة Python عامة. | لا يُحذف محليًا، لكنه لا يُسلّم ولا يدخل Git لأنه يحتوي أسرارًا. |
| `backend/.env.example` | example | قالب شامل لمتغيرات البيئة التي يقرأها التطبيق وخدمات Docker. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/config/ENVIRONMENT_GUIDE.md` | Markdown | ملف توثيق للمجلد أو المكوّن. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/config/settings.py` | Python | مصدر إعدادات Python المركزي: متغيرات البيئة، المسارات، حدود البحث، الفترات، والثوابت المشتركة. | مكونات: `env_path`, `env_bool`, `env_int`, `safe_write_json`, `update_json_file`, `load_json`, `rotation_state`, `save_rotation_state`, `rotation_window`, `utc_now`؛ يعتمد على: `__future__`, `datetime`, `dotenv`, `json`, `os`, `pathlib`, `re`, `threading` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/logging/pipeline_logging.py` | Python | تسجيل أحداث تشغيل الـpipeline وربطها بمعرف التشغيل والمرحلة ومؤشرات الأداء. | مكونات: `new_run_id`, `set_run_context`, `get_run_id`, `get_mode`, `log_event`, `timed_stage`, `file_status`, `summarize_items`؛ يعتمد على: `__future__`, `backend.config.settings`, `contextlib`, `json`, `os`, `pathlib`, `sys`, `threading` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/logging/README.md` | Markdown | ملف توثيق للمجلد أو المكوّن. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/enrichment/content/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/enrichment/content/courses/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/enrichment/content/courses/pipeline.py` | Python | إثراء بيانات الدورات بعد الاختيار. | مكونات: `build_course_content`, `refresh_course_content`؛ يعتمد على: `backend.pipeline.enrichment.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/enrichment/content/films/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/enrichment/content/films/pipeline.py` | Python | إثراء بيانات الأفلام بعد الاختيار. | مكونات: `build_movie_content`, `refresh_movie_content`؛ يعتمد على: `backend.pipeline.enrichment.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/enrichment/content/news/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/enrichment/content/news/pipeline.py` | Python | إثراء بيانات الأخبار بعد الاختيار. | مكونات: `stable_update_id`, `update_company_name`, `sector_to_track`, `news_item_from_update`, `news_items_from_updates`, `rejection_card_reason`, `filter_rejection_news_items`, `dedupe_news_items`, `write_news_fetch_state`, `save_news_report`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.enrichment.shared.logos`, `backend.pipeline.filtering.content.courses.level_balancing`, `backend.pipeline.filtering.content.news.rules`, `backend.services.gemini_limiter`, `collections`, `hashlib` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/enrichment/shared/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/enrichment/shared/logos.py` | Python | إثراء الشعارات والصور. | مكونات: `logo_name_key`, `domain_root`, `company_matches_domain`, `favicon_for_domain`, `domain_label`, `favicon_for_url`, `simple_icon_candidates`, `guessed_company_domains`, `company_logo_candidates`, `logo_label_from_card_title`؛ يعتمد على: `__future__`, `backend.config.settings`, `re` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/enrichment/shared/supporting.py` | Python | إثراء مشترك للمحتوى الداعم. | مكونات: `build_supporting_content`, `apply_supporting_content`, `refresh_supporting_content`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.fetching.content.films.discovery`, `backend.pipeline.filtering.content.courses.level_balancing`, `backend.pipeline.filtering.content.courses.rules`, `backend.pipeline.modeling.content.courses.model` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/fetching/content/courses/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/fetching/content/courses/bank.py` | Python | قراءة وإدارة بنك مرشحي الدورات. | مكونات: `canonical_course_url`, `course_key`, `ensure_course_repository`, `parse_dt`, `infer_level_from_evidence`, `infer_topic`, `infer_language`, `infer_free_status`, `infer_audience`, `infer_employee_fit_score`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.filtering.content.courses.levels`, `backend.storage.course_repository`, `collections`, `datetime`, `hashlib`, `random` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/courses/discovery.py` | Python | جلب الدورات وتدوير المنصات والتحقق من صفحاتها. | مكونات: `course_path_patterns_from_url`, `is_workforce_course_text`, `has_student_course_reject_signal`, `has_developer_only_course_signal`, `has_expired_course_signal`, `clean_course_url`, `course_platform_from_url`, `load_discovered_platforms`, `readable_platform_name`, `most_common_discovered_path`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.courses.bank`, `backend.pipeline.fetching.fetch_utils`, `backend.pipeline.filtering.content.courses.levels`, `backend.pipeline.tool_discovery.queries`, `collections` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/films/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/fetching/content/films/discovery.py` | Python | اكتشاف الأفلام والمواد المرئية المرشحة للنشرة. | مكونات: `rotated_movie_pages`, `fetch_movie_candidates`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.fetch_utils`, `requests` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | يعتمد على: `.normalization`, `.runtime` | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/fetching/content/news/common.py` | Python | مساعدات HTTP والنصوص المشتركة لجلب الأخبار. | مكونات: `parse_candidate_datetime`, `canonical_news_url`, `result_looks_like_update`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.fetch_utils`, `backend.pipeline.filtering.content.news.editorial`, `backend.pipeline.tool_discovery.official_sites`, `backend.pipeline.tool_discovery.queries`, `backend.pipeline.tool_discovery.tools_aware` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/exa.py` | Python | تنفيذ جلب الأخبار من Exa وقراءة نتائجها. | مكونات: `exa_recent_date_from_json_ld`, `exa_recent_date_from_meta`, `exa_recent_date_from_time_tag`, `exa_recent_date_from_text`, `exa_recent_date_from_http_header`, `exa_recent_date_from_relative_text`, `exa_recent_date_from_sitemap`, `exa_recent_verify_date_details`, `exa_recent_build_search_strategies`, `official_domain_matches`؛ يعتمد على: `.common`, `.normalization`, `.queries`, `.searxng` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/fetch.py` | Python | واجهة جلب الأخبار النهائية التي تجمع الوحدات السابقة. | مكونات: `fetch_news_candidates`؛ يعتمد على: `backend.pipeline.fetching.content.news.normalization`, `backend.pipeline.fetching.content.news.runtime` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/merge.py` | Python | دمج نتائج المصادر وإزالة التكرار بينها. | مكونات: `combine_source_results`, `general_news_layer_domain_allowed`, `fetch_general_news_layer`؛ يعتمد على: `.common`, `.exa`, `.normalization`, `.queries`, `.searxng` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/normalization.py` | Python | تطبيع روابط وحقول وتواريخ نتائج الأخبار. | مكونات: `freshness_query`, `searxng_fetch_query`, `domain_blocked`, `official_page_type_reject_reason`, `source_candidate_hard_reject_reason`, `tool_query_reject_reason`, `text_has_whole_term`, `inferred_date_from_text`, `has_known_company_signal`, `infer_sector`؛ يعتمد على: `.common`, `.queries` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/queries.py` | Python | بناء استعلامات الأخبار وتوزيعها حسب القطاعات والمصادر. | مكونات: `has_arabic_text`, `unique_full_query_rows`, `root_site_token`, `official_site_token`, `trusted_media_exa_rows`, `next_tool_rotation_offset`, `exa_tool_update_script_rows`, `compose_query_mix_rows`, `rotate_list`, `row_matches_keywords`؛ يعتمد على: `.common` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/runtime.py` | Python | حالة تشغيل جلب الأخبار والتقارير المرحلية. | مكونات: `fetch_news_candidates`؛ يعتمد على: `.common`, `.exa`, `.merge`, `.normalization`, `.queries`, `.searxng`, `.tracker` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/searxng.py` | Python | تنفيذ جلب الأخبار من SearXNG وفحص النتائج. | مكونات: `searxng_discovery_fetch_html`, `searxng_discovery_is_hub_page`, `searxng_discovery_split_hub`, `searxng_discovery_has_modified_context`, `searxng_discovery_extract_date_confident`, `fetch_searxng_query_rows`؛ يعتمد على: `.common`, `.normalization`, `.queries` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/content/news/tracker.py` | Python | تتبع المصادر والاستعلامات والنتائج أثناء التشغيل. | مكونات: `tracker_dedupe`, `tracker_has_any`, `tracker_search_exa`, `tracker_search_searxng`, `tracker_verify_page_date`, `tracker_known_terms`, `tracker_is_known_tool`, `tracker_general_user_fit_score`, `tracker_extract_potential_tool_name`, `tracker_is_saudi_official`؛ يعتمد على: `.common`, `.exa`, `.merge`, `.normalization`, `.queries`, `.searxng` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/fetch_utils.py` | Python | ملف مشروع فعلي؛ وظيفته يوضحها اسمه ومكوناته المدرجة. | مكونات: `safe_print`, `exa_http_error`, `query_site_domains`, `query_site_domain_matches_url`؛ يعتمد على: `__future__`, `backend.config.settings`, `os`, `re`, `requests`, `sys` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/fetching/news_fetch_state.json` | JSON | ملف بيانات/حالة تشغيل وليس كودًا تنفيذيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: حالة/بيانات؛ لا يُحذف أثناء التشغيل. |
| `backend/pipeline/filtering/content/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/filtering/content/courses/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/filtering/content/courses/level_balancing.py` | Python | موازنة الدورات والأخبار حسب المستويات في العرض الموصى به. | مكونات: `normalize_level`, `display_level`, `infer_topic_group`, `classify_news_item`, `classify_course_item`, `course_platform_topic_diversity_key`, `select_topic_diverse`, `build_level_bank`, `build_recommended_view`؛ يعتمد على: `__future__`, `backend.config.settings`, `collections`, `math`, `re`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/content/courses/levels.py` | Python | تحديد مستوى الدورة من الأدلة والمتطلبات السابقة. | مكونات: `classify_course_level_evidence`؛ يعتمد على: `__future__`, `backend.config.settings`, `re` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/content/courses/rules.py` | Python | قواعد قبول واستبعاد الدورات. | مكونات: `filter_course_candidates`؛ يعتمد على: `backend.pipeline.filtering.content.courses.level_balancing`, `backend.pipeline.filtering.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/content/films/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/filtering/content/films/rules.py` | Python | قواعد قبول الأفلام وإزالة النتائج غير المناسبة. | مكونات: `filter_movie_candidates`؛ يعتمد على: `backend.pipeline.filtering.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/content/news/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/filtering/content/news/editorial.py` | Python | السياسة التحريرية النهائية للأخبار. | مكونات: `is_saudi_official_source`, `is_saudi_ai_candidate`, `classify_saudi_ai_editorial_type`, `saudi_ai_editorial_fit_score`, `general_user_fit_score`, `annotate_news_candidate`, `production_news_reject_reason`؛ يعتمد على: `__future__`, `datetime`, `re`, `urllib.parse` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/content/news/rules.py` | Python | قواعد قبول الأخبار وحداثتها وجودتها وتنوعها. | مكونات: `filter_news_candidates`؛ يعتمد على: `backend.pipeline.filtering.shared.memory` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/shared/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/filtering/shared/memory.py` | Python | كشف التشابه مع المحتوى المنشور والذاكرة. | مكونات: `item_title_key`, `story_owner_key`, `story_product_key`, `story_title_tokens`, `items_same_story`, `item_story_key`, `rank_candidates`, `news_candidate_is_recent`, `semantic_text`, `cosine_similarity`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.news.normalization`, `backend.pipeline.filtering.content.news.editorial`, `backend.pipeline.modeling.model_client`, `backend.vector_db.qdrant_memory`, `collections` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/filtering/shared/supporting.py` | Python | منطق فلترة مشترك للمحتوى الداعم. | مكونات: `support_text`, `supporting_identity_keys`, `supporting_visible_key_sets`, `supporting_matches_visible`, `movie_has_direct_ai_signal`, `supporting_reject_reason`, `filter_supporting_candidates`, `save_supporting_memory`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.filtering.shared.memory`, `re` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/.gemini_rate_limit` | Config | مكوّن مشترك لمرحلة النموذج. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/modeling/content/courses/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/modeling/content/courses/model.py` | Python | استدعاء النموذج ومعالجة المخرجات الخاصة بـالدورات. | مكونات: `select_course_cards`؛ يعتمد على: `backend.pipeline.modeling.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/courses/prompt.py` | Python | مصدر البرومبت الرسمي الخاص بـالدورات. | مكونات: `build_courses_prompt` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/films/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/modeling/content/films/model.py` | Python | استدعاء النموذج ومعالجة المخرجات الخاصة بـالأفلام. | مكونات: `select_movie_cards`؛ يعتمد على: `backend.pipeline.modeling.shared.supporting` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/films/prompt.py` | Python | مصدر البرومبت الرسمي الخاص بـالأفلام. | مكونات: `build_films_prompt` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/news/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/modeling/content/news/model.py` | Python | استدعاء النموذج ومعالجة المخرجات الخاصة بـالأخبار. | مكونات: `select_news_updates`؛ يعتمد على: `backend.pipeline.modeling.content.news.selection` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/news/prompt.py` | Python | مصدر البرومبت الرسمي الخاص بـالأخبار. | مكونات: `build_news_selection_prompt`, `build_news_rewrite_prompt`؛ يعتمد على: `backend.config.settings` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/content/news/selection.py` | Python | اختيار الأخبار وإعادة صياغتها والتحقق من مخرجات النموذج. | مكونات: `estimate_prompt_tokens`, `model_usage_run`, `add_model_usage_totals`, `record_model_usage`, `record_model_failure`, `log_token_usage`, `model_failure_details`, `failure_report`, `result_url_key`, `normalized_update_title`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.news.normalization`, `backend.pipeline.filtering.content.courses.level_balancing`, `backend.pipeline.modeling.content.news.prompt`, `backend.pipeline.modeling.model_client`, `backend.pipeline.modeling.usage_state` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/gemini_client.py` | Python | عميل Gemini، القيود، الاستدعاء، وتسجيل الاستهلاك. | مكونات: `GeminiQuotaError`, `gemini_available`, `gemini_quota_remaining`, `generate_json`, `embed_texts`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.modeling.json_extract`, `backend.pipeline.modeling.usage_state`, `backend.services.gemini_limiter`, `datetime`, `dotenv`, `google` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/json_extract.py` | Python | استخراج JSON صالح من رد النموذج. | مكونات: `extract_json_object`؛ يعتمد على: `__future__`, `json`, `re`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/model_client.py` | Python | واجهة موحدة لاختيار Gemini أو OpenAI حسب الإعداد. | مكونات: `model_for_role`, `model_available`, `model_quota_remaining`, `generate_json`, `generate_json_for_role`, `embed_texts`, `model_error_details`, `gemini_client_error_details`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.modeling`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/openai_client.py` | Python | عميل OpenAI والاستدعاء وتسجيل الاستهلاك. | مكونات: `openai_available`, `generate_json`, `embed_texts`؛ يعتمد على: `backend.config.settings`, `backend.pipeline.modeling.json_extract`, `json`, `openai`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/shared/__init__.py` | Python | نقطة تصدير الحزمة لهذا النوع/المرحلة؛ تجعل الاستيرادات الرسمية واضحة ولا تحتوي منطقًا موازيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: علامة/واجهة حزمة. |
| `backend/pipeline/modeling/shared/supporting.py` | Python | منطق نمذجة مشترك للمحتوى الداعم. | مكونات: `SupportingCard`, `SupportingReport`, `compact_supporting_candidate`, `merge_supporting_cards`, `course_topic_key`, `course_platform_key`, `course_item_key`, `course_level_label`, `course_platform_level_pair`, `save_last_course_platforms`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.courses.bank`, `backend.pipeline.filtering.content.courses.level_balancing`, `backend.pipeline.modeling.content.news.selection`, `backend.pipeline.modeling.model_client`, `backend.pipeline.modeling.shared.supporting_prompt` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/shared/supporting_prompt.py` | Python | برومبت مشترك للأفلام والمحتوى الداعم. | مكونات: `build_supporting_prompt`؛ يعتمد على: `backend.pipeline.modeling.content.courses.prompt`, `backend.pipeline.modeling.content.films.prompt` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/modeling/usage_state.py` | Python | تحديث ملف استهلاك النموذج بصورة ذرية. | مكونات: `load_usage_state`, `update_usage_state`؛ يعتمد على: `__future__`, `backend.config.settings`, `json`, `pathlib`, `threading`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/orchestrator.py` | Python | نقطة تنسيق توليد النشرة؛ تمرر الأخبار والدورات والأفلام عبر الجلب والفلترة والنموذج والحفظ. | مكونات: `save_candidate_audit`, `save_query_results_audit`, `candidate_source_lane`, `candidate_is_primary_lane`, `candidate_is_fallback_lane`, `source_lane_priority`, `scan_candidate_score`, `product_update_priority`, `product_update_signal`, `build_large_scan_pool`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.enrichment.content.courses.pipeline`, `backend.pipeline.enrichment.content.news.pipeline`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.fetching.content.films.discovery`, `backend.pipeline.fetching.content.news.fetch` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/tool_discovery/monthly_tools-site.json` | JSON | بيانات حالة/نتائج شهرية لاكتشاف مواقع الأدوات. | لا يحتوي واجهة Python عامة. | يُحتفظ به: حالة/بيانات؛ لا يُحذف أثناء التشغيل. |
| `backend/pipeline/tool_discovery/official_sites.py` | Python | قائمة المواقع الرسمية للأدوات. | مكونات: `tool_record_key`, `canonical_official_site`, `official_site_url`, `normalize_official_site_status`, `verify_official_site`, `official_site_name_variants`, `get_official_domain`, `auto_detect_official_site`, `load_official_tool_sites`, `apply_default_official_sites`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `re`, `requests`, `urllib.parse` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/tool_discovery/queries.py` | Python | استعلامات اكتشاف أدوات الذكاء الاصطناعي. | مكونات: `search_url`, `query_has_ai_scope`, `ensure_ai_scope`, `strict_searxng_ai_product_query`, `text_has_any`, `announcement_terms_query`, `tool_release_query`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.tool_discovery.official_sites`, `re` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/tool_discovery/site_fetch_diagnostic.py` | Python | تشخيص وصول مواقع الأدوات ونتائجها. | مكونات: `official_site_matches_result`, `official_site_path_matches_result`, `urlparse_with_scheme`, `result_date`, `classify_raw_result`, `load_active_tools_with_official_sites`, `build_official_site_queries`, `compact_result`, `fetch_exa_raw_results`, `fetch_searxng_raw_results`؛ يعتمد على: `__future__`, `argparse`, `backend.config.settings`, `backend.pipeline.tool_discovery.official_sites`, `backend.pipeline.tool_discovery.queries`, `os`, `pathlib`, `requests` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/pipeline/tool_discovery/tools_aware.py` | Python | دمج وعي الأدوات في اكتشاف الأخبار. | مكونات: `fetch_exa_tool_discovery_pages`, `fetch_searxng_tool_discovery_pages`, `extract_live_tool_records`, `discover_tool_names_live`, `fetch_successful_tools`, `tool_group`, `normalize_tool_record`, `tool_record_rule_gate`, `model_allows_tool_records_batch`, `model_allows_tool_record`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.modeling.gemini_client`, `backend.pipeline.tool_discovery.official_sites`, `backend.pipeline.tool_discovery.queries`, `collections`, `concurrent.futures` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/sector_terms_history.json` | JSON | ملف بيانات/حالة تشغيل وليس كودًا تنفيذيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: حالة/بيانات؛ لا يُحذف أثناء التشغيل. |
| `backend/server/card_items.py` | Python | تطبيع بطاقات الأخبار والدورات والأفلام وتجهيزها لطلبات API والواجهة. | مكونات: `manual_logo_override_url`, `apply_manual_logo_override`, `ensure_visual_identity`, `ensure_visual_identity_batch`, `clamp_logo_size`, `clamp_logo_position`, `normalize_item`, `normalize_items_batch`, `is_current_schema_item`, `dedupe_store_items`؛ يعتمد على: `__future__`, `backend.pipeline.enrichment.shared.logos`, `backend.pipeline.filtering.content.courses.rules`, `backend.pipeline.filtering.content.news.rules`, `backend.utils.text_normalization`, `backend.utils.value_parsing`, `collections`, `hashlib` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/server/generator_bridge.py` | Python | جسر آمن بين API وعملية التوليد الخلفية مع حالة التقدم ومنع التشغيل المتزامن. | مكونات: `should_use_ai_updates_generator`, `refresh_supporting_content_into_store`, `refresh_supporting_content_for_ai_updates`, `ai_updates_failure_message`, `schedule_background_topup`, `run_ai_updates_generator`, `run_generator`, `start_generator_background`؛ يعتمد على: `__future__`, `backend.pipeline.modeling.model_client`, `backend.pipeline.orchestrator`, `backend.storage.newsletter_store`, `backend.utils.debug_logging`, `os`, `threading`, `time` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/server/http_server.py` | Python | خادم HTTP ونقطة تشغيل التطبيق؛ يقدم الواجهة ومسارات API ويطبق صلاحيات المصادقة الحالية. | مكونات: `safe_login_next`, `escape_attr`, `read_json_body`, `sync_item_in_saved_views`, `find_editable_store_item`, `replacement_response`, `client_state_news_items`, `replace_item_at_index`, `rewrite_text`, `ReusableTCPServer`؛ يعتمد على: `backend.auth.authentication`, `backend.auth.keycloak_bootstrap`, `backend.config.settings`, `backend.pipeline.modeling.model_client`, `backend.pipeline.orchestrator`, `backend.server.card_items`, `backend.server.generator_bridge`, `backend.server.single_card_refill` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/server/single_card_refill.py` | Python | استبدال بطاقة واحدة من النوع المطلوب مع الحفاظ على قواعد الاختيار. | مكونات: `refill_response_state`, `publish_single_refill_state`, `current_single_refill_state`, `append_single_refill_stage`, `current_exclusion_items`, `normalize_generated_refill_item`, `apply_single_refill`, `try_ai_updates_single_refill`, `try_ai_updates_supporting_single_refill`, `single_item_refill`؛ يعتمد على: `__future__`, `backend.pipeline.orchestrator`, `backend.server.card_items`, `backend.storage.newsletter_store`, `backend.utils.debug_logging`, `dotenv`, `hashlib`, `os` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/services/gemini_limiter.py` | Python | تحديد معدل استدعاءات Gemini وتنظيم المحاولات والتأخير. | مكونات: `GeminiRateLimiter`, `wait_for_gemini_slot`, `evaluate_run`؛ يعتمد على: `__future__`, `threading`, `time`, `typing` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/course_repository.py` | Python | تخزين واسترجاع سجل الدورات والمنصات من PostgreSQL. | مكونات: `course_db`, `ensure_course_storage`, `upsert_courses`, `load_courses`, `selection_context`, `record_selection`؛ يعتمد على: `__future__`, `backend.storage.postgres`, `datetime`, `hashlib`, `json`, `pathlib`, `psycopg2.extras`, `threading` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/discovered_platforms.json` | JSON | ملف بيانات/حالة تشغيل وليس كودًا تنفيذيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: حالة/بيانات؛ لا يُحذف أثناء التشغيل. |
| `backend/storage/manage_versions/migrate_versions_to_postgres.py` | Python | ملف مشروع فعلي؛ وظيفته يوضحها اسمه ومكوناته المدرجة. | مكونات: `read_legacy_versions`, `ensure_postgres_schema`, `migrate_rows`, `main`؛ يعتمد على: `__future__`, `backend.storage.postgres`, `collections`, `dotenv`, `os`, `pathlib`, `sqlite3` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/manage_versions/pdf_import.py` | Python | مساعدات حمولة PDF: إرفاق JSON عند التصدير وقراءة رفع multipart/base64. | مكونات: `attach_newsletter_json_to_pdf`, `read_json_body_from_handler`, `decode_pdf_base64`, `read_multipart_upload`؛ يعتمد على: `__future__`, `base64`, `datetime`, `email.parser`, `email.policy`, `io`, `json` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/manage_versions/seeds/initial_versions.db` | SQLite seed | ملف بيانات/حالة تشغيل وليس كودًا تنفيذيًا. | لا يحتوي واجهة Python عامة. | يُحتفظ به: بذرة قاعدة النسخ. |
| `backend/storage/manage_versions/seeds/README.md` | Markdown | ملف توثيق للمجلد أو المكوّن. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/manage_versions/version_routes.py` | Python | معالجة مسارات API الخاصة بحفظ النسخ ورفع PDF وتنزيل JSON/PDF. | مكونات: `handle_versions_get`, `handle_versions_post`, `handle_versions_put`, `handle_versions_delete`؛ يعتمد على: `__future__`, `backend.storage.manage_versions.pdf_import`, `backend.storage.manage_versions.versions_db`, `backend.storage.newsletter_store`, `backend.utils.debug_logging`, `datetime`, `json`, `psycopg2` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/manage_versions/versions_db.py` | Python | طبقة بيانات نسخ النشرة في PostgreSQL وتهيئة الجداول والبذرة. | مكونات: `init_versions_db`, `migrate_json_versions_to_canonical_schema`, `seed_versions_from_sqlite_if_empty`, `versions_db`, `backup_versions_db`, `serialize_db_datetime`, `save_pdf_version_file`, `title_from_pdf_filename`, `parse_version_id`, `load_current_news_json_text`؛ يعتمد على: `__future__`, `backend.storage.newsletter_store`, `backend.storage.postgres`, `backend.utils.debug_logging`, `datetime`, `json`, `pathlib`, `psycopg2` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/newsletter_store.py` | Python | قراءة وحفظ النشرة الحالية، البنوك، الإعدادات، والنسخ المنشورة بصيغة JSON. | مكونات: `is_gpt_accepted_news_item`, `reorder_positions`, `arabic_number_to_words`, `issue_label`, `clean_setting_text`, `current_arabic_month_year`, `normalize_newsletter_settings`, `format_footer_text`, `newsletter_template_from_settings`, `load_newsletter_settings`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.server.card_items`, `backend.utils.debug_logging`, `backend.utils.text_normalization`, `backend.utils.value_parsing`, `datetime`, `dotenv` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/postgres.py` | Python | إنشاء اتصالات PostgreSQL ومساعدات المعاملات والتحقق من جاهزية قاعدة البيانات. | مكونات: `postgres_connection`؛ يعتمد على: `__future__`, `os`, `psycopg2` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/storage/README.md` | Markdown | ملف توثيق للمجلد أو المكوّن. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/tests/test_course_fetchers.py` | Python | اختبار آلي: course fetchers. | مكونات: `CourseCandidateNormalizationTests`؛ يعتمد على: `backend.pipeline.fetching.content.courses.discovery`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_editorial_acceptance.py` | Python | اختبار آلي: editorial acceptance. | مكونات: `news_item`, `EditorialAcceptanceTests`؛ يعتمد على: `__future__`, `backend.config.settings`, `backend.pipeline.fetching.content.courses.bank`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.modeling.content.news.selection`, `datetime`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_frontend_assets.py` | Python | اختبار آلي: frontend assets. | مكونات: `FrontendAssetTests`؛ يعتمد على: `pathlib`, `re`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_model_client_rewrite_config.py` | Python | اختبار آلي: model client rewrite config. | مكونات: `ModelClientRewriteConfigTests`؛ يعتمد على: `backend.pipeline.modeling`, `unittest`, `unittest.mock` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_movie_level_independence.py` | Python | اختبار آلي: movie level independence. | مكونات: `MovieLevelIndependenceTests`؛ يعتمد على: `backend.pipeline.orchestrator`, `unittest`, `unittest.mock` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_pdf_style_loading.py` | Python | اختبار آلي: pdf style loading. | مكونات: `PdfStyleLoadingTests`؛ يعتمد على: `backend.utils.pdf_export_service`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_pipeline_structure.py` | Python | اختبار آلي: pipeline structure. | مكونات: `PipelineStructureTests`؛ يعتمد على: `backend.pipeline.fetching.content.news.common`, `importlib`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_published_semantic_memory.py` | Python | اختبار آلي: published semantic memory. | مكونات: `PublishedSemanticMemoryTests`؛ يعتمد على: `backend.storage.newsletter_store`, `unittest`, `unittest.mock` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_requirements_coverage.py` | Python | اختبار آلي: requirements coverage. | مكونات: `declared_packages`, `imported_top_level_modules`, `RequirementsCoverageTests`؛ يعتمد على: `ast`, `pathlib`, `sys`, `unittest` | يُحتفظ به: اختبار فعّال. |
| `backend/tests/test_version_naming.py` | Python | اختبار آلي: version naming. | مكونات: `VersionNamingTests`؛ يعتمد على: `backend.storage.manage_versions.versions_db`, `backend.storage.newsletter_store`, `datetime`, `json`, `unittest`, `unittest.mock` | يُحتفظ به: اختبار فعّال. |
| `backend/utils/debug_logging.py` | Python | ملف مشروع فعلي؛ وظيفته يوضحها اسمه ومكوناته المدرجة. | مكونات: `configure_console_encoding`, `trace`, `generator_completed_steps_from_log`, `timeline_stage_key`, `is_timeline_worthy_line`, `append_generator_timeline`, `safe_float`, `latest_generator_performance`, `generator_stage_duration_map`, `generator_progress_state`؛ يعتمد على: `sys`, `time` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/utils/pdf_export_service.py` | Python | تحويل HTML النهائي إلى PDF عبر Playwright مع تحميل CSS المحلي والخطوط. | مكونات: `resolve_frontend_html_file`, `extract_ui_styles`, `embedded_pdf_font_css`, `strip_print_media_blocks`, `normalize_pdf_dimension`, `default_pdf_scale`, `normalize_pdf_scale`, `build_preview_pdf_document`, `whatsapp_pdf_quality_values`, `whatsapp_pdf_target_bytes`؛ يعتمد على: `__future__`, `backend.utils.debug_logging`, `base64`, `html`, `os`, `pathlib`, `re`, `sys` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/utils/text_normalization.py` | Python | تنظيف النصوص وإصلاح الترميز المشوه بصورة مشتركة. | مكونات: `mojibake_score`, `repair_mojibake_text`, `cleanup_text_fields`؛ يعتمد على: `re` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/utils/value_parsing.py` | Python | تحويلات قيم صغيرة مشتركة مثل safe_int بدون تكرار. | مكونات: `safe_int` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `backend/vector_db/qdrant_memory.py` | Python | ذاكرة دلالية اختيارية في Qdrant لاكتشاف المحتوى المنشور أو المتشابه. | مكونات: `ensure_qdrant_collection`, `open_qdrant_memory`, `close_qdrant_memory`, `qdrant_type_filter`, `point_struct_class`, `with_qdrant_lock`؛ يعتمد على: `__future__`, `backend.config.settings`, `threading` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `frontend/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `frontend/document-metadata.js` | JavaScript | قراءة وتحديث بيانات اسم النسخة والشهر ورقم الإصدار من النشرة الحالية. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/i18n.js` | JavaScript | قاموس نصوص الواجهة ومساعد الترجمة؛ يفصل النصوص المعروضة عن منطق الصفحة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/image/brand-mark.svg` | SVG | أصل بصري مستخدم في الواجهة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: أصل واجهة. |
| `frontend/image/cultural-assistant-robot.PNG` | Image | أصل بصري مستخدم في الواجهة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: أصل واجهة. |
| `frontend/image/المرصد الثقافي.png` | Image | أصل بصري مستخدم في الواجهة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: أصل واجهة. |
| `frontend/image/المرصد الثقافي2.png` | Image | أصل بصري مستخدم في الواجهة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: أصل واجهة. |
| `frontend/image/وزارة الثقافة.png` | Image | أصل بصري مستخدم في الواجهة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: أصل واجهة. |
| `frontend/logo-resolver.js` | JavaScript | اختيار شعار المصدر أو المنصة مع بدائل العرض. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/neural-background.js` | JavaScript | الخلفية البصرية المتحركة للواجهة؛ لا تدخل في منطق البيانات. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/news.css` | CSS | تنسيق صفحة النشرة بعد فصله من News.html. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/News.html` | HTML | هيكل صفحة تحرير وتوليد النشرة؛ يعتمد على ملفات CSS وJavaScript المفصولة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/newsletter-card-actions.js` | JavaScript | إجراءات تعديل البطاقة وحذفها واستبدالها وإعادة صياغتها. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/newsletter-core.js` | JavaScript | حالة النشرة الأساسية والتحميل والمزامنة مع API. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/newsletter-export-history.js` | JavaScript | حفظ النسخ وتصدير PDF وربط النسخة ببيانات النشرة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/newsletter-generation.js` | JavaScript | تشغيل التوليد ومتابعة حالته وإظهار النتيجة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/newsletter-rendering.js` | JavaScript | رسم أقسام وبطاقات الأخبار والدورات والأفلام في الصفحة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/pdf-export.js` | JavaScript | مساعدات تهيئة الصفحة قبل طلب تصدير PDF. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/shared-functions.js` | JavaScript | الدوال العامة المشتركة في الواجهة مثل الطلبات، الهروب، والتحويلات؛ الاسم معبر ويُحتفظ به. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/tokens.css` | CSS | ألوان ومسافات ومتغيرات التصميم المشتركة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `frontend/versions.html` | HTML | واجهة استعراض النسخ المحفوظة وفتحها وتنزيلها. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `docker/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `docker/compose/app.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: app.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/compose/keycloak.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: keycloak.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/compose/minio.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: minio.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/compose/postgres.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: postgres.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/compose/qdrant.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: qdrant.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/compose/searxng.yml` | YAML | تعريف أو سكربت تشغيل للبنية التحتية: searxng.yml. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/postgres/Dockerfile` | Config | تعريف أو سكربت تشغيل للبنية التحتية: Dockerfile. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/postgres/entrypoint.sh` | Shell | تعريف أو سكربت تشغيل للبنية التحتية: entrypoint.sh. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/postgres/pgbackrest-cron.sh` | Shell | تعريف أو سكربت تشغيل للبنية التحتية: pgbackrest-cron.sh. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docker/postgres/pgbackrest.conf` | conf | تعريف أو سكربت تشغيل للبنية التحتية: pgbackrest.conf. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `docs/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `docs/ARCHITECTURE.md` | Markdown | توثيق architecture للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/COST_MODEL.md` | Markdown | توثيق cost model للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/DEPLOYMENT.md` | Markdown | توثيق deployment للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/DOCKER_SETUP.md` | Markdown | توثيق docker setup للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/MAINTENANCE.md` | Markdown | توثيق maintenance للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/SETUP.md` | Markdown | توثيق setup للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `docs/USER_GUIDE.md` | Markdown | توثيق user guide للمشروع. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `scripts/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `scripts/analyze_news_funnel.py` | Python | أداة تشغيل/تشخيص يدوية: analyze news funnel. | مكونات: `install_guards`, `install_tracers`, `parse_args`, `main`؛ يعتمد على: `__future__`, `argparse`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.news.fetch`, `backend.pipeline.fetching.fetch_utils`, `backend.pipeline.filtering.content.news.editorial`, `backend.pipeline.filtering.shared.memory`, `backend.pipeline.modeling.content.news.prompt` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `scripts/course_bank_weekly_selection.py` | Python | أداة تشغيل/تشخيص يدوية: course bank weekly selection. | مكونات: `parse_args`, `main`؛ يعتمد على: `__future__`, `argparse`, `backend.config.settings`, `backend.pipeline.fetching.content.courses.bank`, `backend.pipeline.fetching.content.courses.discovery`, `datetime`, `json`, `pathlib` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `scripts/restart_backend.ps1` | PowerShell | أداة تشغيل/تشخيص يدوية: restart backend. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `scripts/test_fetch_performance.py` | Python | أداة تشغيل/تشخيص يدوية: test fetch performance. | مكونات: `install_model_guards`, `fetch_news_stage`, `fetch_supporting_stage`, `print_news_report`, `print_supporting_report`, `parse_args`, `main`؛ يعتمد على: `__future__`, `argparse`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.fetching.content.films.discovery`, `backend.pipeline.fetching.content.news.fetch`, `backend.pipeline.fetching.fetch_utils` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `scripts/test_openai_selection.py` | Python | أداة تشغيل/تشخيص يدوية: test openai selection. | مكونات: `install_safety_guards`, `fetch_news_shortlist`, `run_news_selection`, `run_supporting_selection`, `print_selection_report`, `read_this_run_usage`, `parse_args`, `main`؛ يعتمد على: `__future__`, `argparse`, `backend.config.settings`, `backend.logging.pipeline_logging`, `backend.pipeline.fetching.content.courses.discovery`, `backend.pipeline.fetching.content.films.discovery`, `backend.pipeline.fetching.content.news.fetch`, `backend.pipeline.fetching.fetch_utils` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |
| `scripts/test_searxng_health.py` | Python | أداة تشغيل/تشخيص يدوية: test searxng health. | مكونات: `parse_args`, `run_query`, `main`؛ يعتمد على: `__future__`, `argparse`, `backend.pipeline.fetching.fetch_utils`, `backend.pipeline.tool_discovery.queries`, `pathlib`, `requests`, `sys`, `time` | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `.gitignore/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `.gitignore` | Config | ملف مشروع فعلي؛ وظيفته يوضحها اسمه ومكوناته المدرجة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `CHANGELOG.md/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `CHANGELOG.md` | Markdown | ملف توثيق للمجلد أو المكوّن. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `docker-compose.yml/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `docker-compose.yml` | YAML | ملف Compose الرئيسي الذي يجمع خدمات التطبيق وقاعدة البيانات والبحث والهوية والذاكرة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `Dockerfile/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `Dockerfile` | Config | بناء صورة تطبيق Python وتثبيت المتطلبات وPlaywright. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `README.md/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `README.md` | Markdown | مدخل المشروع: التشغيل، الوظائف الفعلية، خريطة المكونات، وروابط التوثيق. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

### `requirements.txt/`

| المسار | النوع | الوظيفة الفعلية | أهم المكونات/الاعتماديات | القرار |
|---|---|---|---|---|
| `requirements.txt` | txt | قائمة مكتبات Python المباشرة والاعتماديات المثبتة بإصدارات محددة. | لا يحتوي واجهة Python عامة. | يُحتفظ به: مستخدم أو ملف تشغيل/توثيق مطلوب. |

## ما حُذف لأنه مكرر أو ميت

| المجموعة | ما حُذف | الدليل |
|---|---|---|
| واجهات pipeline القديمة | 27 ملفًا جذريًا داخل `enrichment/fetching/filtering/modeling` كانت تعيد تصدير نفس وحدات `content/*` | كل الاستيرادات الداخلية حُولت إلى المسارات الرسمية ثم نجحت الاختبارات |
| نمذجة قديمة | `model_config.py` و`tool_registry.py` و`AITool` غير المستعمل وملفات prompt الجذرية | لا يوجد استدعاء بعد توحيد مصدر البرومبت |
| دوال وثوابت ميتة | مساعدات دورات قديمة، `build_filter_view`، فحص نص غير مستعمل، حفظ حالة مكرر، `qdrant_available`، واسم PDF قديم | فحص AST والبحث المرجعي أعطيا تعريفًا بلا أي استدعاء |
| واجهة قديمة | `frontend/shared.js` استُبدل بـ`frontend/shared-functions.js`، ونسخة mojibake الاحتياطية حُذفت | كل صفحات HTML تشير إلى الاسم الجديد والاختبار يثبته |
| PDF قديم | محرك تحليل تخطيط PDF وإعادة بناء البطاقات أزيل؛ بقي الرفع والتخزين وإرفاق JSON المستخدم | الخادم يستورد الوظائف المتبقية فقط |

لا توجد ملفات أخرى آمنة للحذف بثقة عالية في الشجرة المفهرسة. ملفات JSON وSQLite المذكورة أعلاه بيانات حالة/بذور، وليست كودًا مكررًا.

## تدقيق المكتبات

المكتبات المباشرة المغطاة: `openai`, `pydantic`, `python-dotenv`, `psycopg2-binary`, `requests`, `qdrant-client`, `playwright`, `pypdf`, `python-keycloak`, `google-genai`, `beautifulsoup4`, `lxml`, `python-dateutil`, `tenacity`. أزيلت `PyMuPDF` و`python-jose` و`ecdsa` لعدم وجود مسار فعلي يستوردها. `lxml` باقية لأنها parser صريح تستخدمه BeautifulSoup.

الاختبار `backend/tests/test_requirements_coverage.py` يمسح استيرادات Python ويتوقف إذا ظهرت مكتبة خارجية غير معلنة.

## نطاق الأمان

الموجود فقط هو نظام المصادقة والصلاحيات الأصلي في `backend/auth` وKeycloak لأنه جزء من تشغيل المنتج. لا يتضمن هذا التسليم تطبيق متطلبات جديدة من مراجعة التصميم الأمني، ولا توجد قائمة إجراءات أمنية جديدة مطلوبة داخل هذا التقرير.

## نتائج التحقق

- `python -m compileall -q backend scripts`: ناجح.
- استيراد `backend.pipeline.orchestrator` و`backend.server.http_server`: ناجح.
- `python -m unittest discover -s backend/tests -p "test_*.py"`: **34 اختبارًا ناجحًا**.
- `docker compose config --quiet`: ناجح.
- `python -m pip install --dry-run -r requirements.txt`: ناجح؛ جميع الإصدارات قابلة للحل والتنزيل.
- اختبار `pypdf` مع PDF حقيقي في الذاكرة: تم إرفاق `ainewsletter-version.json` ثم قراءته والتحقق من schema بنجاح.
- طلب `http://127.0.0.1:8000/login` إلى الخادم المحلي القائم: HTTP 200.
- فحص JavaScript عبر Node لم يمكن تشغيله لأن Node غير مثبت في بيئة المشروع؛ بدلًا منه تغطي اختبارات أصول الواجهة التقسيم والمراجع، وسبق تحميل الصفحة الفعلية في Chrome دون `SyntaxError` أو `ReferenceError`.
- التشغيل المدفوع الكامل لمزودي النماذج لم يُنفذ حتى لا تُستهلك مفاتيح أو تكلفة خارجية؛ هذه ليست عبارة نجاح مزعومة.

## أولويات ما بعد التسليم

لا توجد توصيات أمنية جديدة ضمن النطاق. التحسين الاختياري الوحيد الكبير هو تقسيم `backend/pipeline/orchestrator.py` لاحقًا بعد إضافة اختبارات تكامل أوسع؛ لم يُقسّم الآن لتجنب تغيير سلوك الإنتاج قبل التسليم.

## ملف التكلفة

النسخة النهائية: `outputs/codex_cost_audit_20260730/Gemini_Cost_Calculator_v5_11_final.xlsx`. لم تتغير افتراضاته الرقمية: 2.85 دولار أسبوعيًا، 12.36 شهريًا، 148.34 سنويًا للتكلفة المتكررة بعد buffer، و166.24 دولار لميزانية السنة الأولى وفق افتراض عشرة اختبارات تحقق. سيناريو recovery الأسبوعي محافظ وقد يكون مضخمًا؛ لا يمكن خفضه دون قياس تشغيل فعلي.
