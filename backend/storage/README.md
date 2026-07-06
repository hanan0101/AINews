# Storage

This folder documents storage ownership. Runtime storage still lives in the mounted paths used by the application and Docker.
يوثق هذا المجلد ملكية التخزين. يبقى التخزين التشغيلي في المسارات المركبة التي يستخدمها التطبيق وDocker.

## Active Storage Locations

- `data/`: Docker-mounted generated newsletter data and exports.
- `data/`: بيانات النشرة والتصديرات التي تولدها حاويات Docker.
- `backend/news_fetch_state.json`: query rotation and fetch-state memory.
- `backend/news_fetch_state.json`: ذاكرة تدوير الاستعلامات وحالة الجلب.
- `backend/sector_terms_history.json`: learned sector terms for future query quality.
- `backend/sector_terms_history.json`: مصطلحات القطاعات المتعلمة لتحسين الاستعلامات لاحقا.
- `backend/monthly_tools-site.json`: tool registry and official-site seed data.
- `backend/monthly_tools-site.json`: سجل الأدوات وبيانات المواقع الرسمية الأولية.
- `backend/qdrant_db/`: embedded Qdrant semantic-memory files for duplicate detection.
- `backend/qdrant_db/`: ملفات ذاكرة Qdrant الدلالية لاكتشاف التكرار.
- `postgres_data`: Docker volume for saved newsletter versions.
- `postgres_data`: مجلد Docker لحفظ إصدارات النشرة.
- `postgres_backups`: Docker volume for PostgreSQL SQL backups.
- `postgres_backups`: مجلد Docker لنسخ PostgreSQL الاحتياطية.

## Storage Reasoning

Generated state is separated from source code when Docker runs by mounting `/app/data` and named database volumes.
تفصل حالة التشغيل عن كود المصدر عند تشغيل Docker عبر تركيب `/app/data` ومجلدات قاعدة البيانات المسماة.

Small JSON state files remain under `backend/` because the current pipeline reads them directly during local development and Docker bind mounts.
تبقى ملفات JSON الصغيرة داخل `backend/` لأن المسار الحالي يقرأها مباشرة أثناء التطوير المحلي وتركيبات Docker.

