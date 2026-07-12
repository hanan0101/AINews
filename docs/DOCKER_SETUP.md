# هيكلة Docker — خريطة كاملة

جواب مباشر على "كل كونتينر مفروض له ملف؟" — **نعم، وهذا موجود فعلاً**. كل خدمة (كونتينر) لها ملف compose منفصل خاص بها تحت `docker/compose/`. هذا الملف خريطة توضّح وين كل شي.

## الخريطة: كونتينر ← ملف ← وظيفة

| الكونتينر | ملف الإعداد | يبني من | الوظيفة |
|---|---|---|---|
| `ainewsletter` (تطبيقنا) | `docker/compose/app.yml` | `Dockerfile` (جذر المشروع) | سيرفر HTTP + الواجهة + محرّك التشغيل (orchestrator) |
| `postgres` | `docker/compose/postgres.yml` | `docker/postgres/Dockerfile` | تخزين نسخ النشرة + نسخ احتياطية مجدولة تلقائيًا |
| `keycloak` | `docker/compose/keycloak.yml` | صورة جاهزة (image) | تسجيل الدخول والصلاحيات (admin/user) |
| `searxng` | `docker/compose/searxng.yml` | صورة جاهزة (image) | محرك البحث الذاتي الاستضافة |
| `qdrant` | `docker/compose/qdrant.yml` | صورة جاهزة (image) | قاعدة بيانات المتجهات (الذاكرة الدلالية) |

## ملفات الجذر (root) — وين تبدأ

| الملف | الوظيفة |
|---|---|
| `docker-compose.yml` | **نقطة البداية** — ما فيه إعدادات فعلية، بس يجمع الـ5 ملفات أعلاه عبر `include:`. شغّل `docker compose up -d` من هنا دايمًا. |
| `Dockerfile` | يبني صورة كونتينر `ainewsletter` بس (التطبيق الرئيسي) — يثبت المتطلبات وينسخ الكود. |

**ليه هذولا بالجذر مو داخل `docker/`؟** مقصود، مو ملفات ضايعة — هذا الموضع القياسي اللي أدوات Docker تتوقعه تلقائيًا: `docker compose up` بدون أي `-f` يبحث عن `docker-compose.yml` بالمجلد الحالي، ونفس الشي لـ`docker build .` مع `Dockerfile`. لو نقلناهم داخل `docker/` بنحتاج نكتب المسار يدويًا بكل أمر (`docker compose -f docker/docker-compose.yml ...`) — أعقد بلا داعي. البنية الحالية توازن بين المعيار (root) والتنظيم (التفاصيل الفعلية بـ`docker/compose/*.yml`).

## مجلد `docker/postgres/` — تفاصيل خدمة postgres فقط

| الملف | الوظيفة |
|---|---|
| `Dockerfile` | يبني صورة postgres مخصصة (فوق postgres الرسمي) تضيف سكربتات النسخ الاحتياطي |
| `entrypoint.sh` | يشتغل عند بدء الكونتينر — يبدأ postgres + يجدول النسخ الاحتياطي (cron) |
| `backup.sh` | سكربت النسخ الاحتياطي الفعلي — يشتغل تلقائيًا يوميًا (`POSTGRES_BACKUP_CRON`، افتراضي 2 صباحًا)، وممكن تشغّله يدويًا: `docker compose exec postgres /usr/local/bin/postgres-backup` |

## ليه بنية "include" بدل ملف واحد ضخم؟

كل خدمة مستقلة (تشتغل، تتوقف، تُعاد بناؤها) بدون التأثير على البقية. مثال حقيقي من اليوم: أعدنا تشغيل `searxng` بس (`docker compose restart searxng`) بعد تعديل إعداداته، بدون ما نلمس postgres أو keycloak أو التطبيق الرئيسي.

## أوامر أساسية (من جذر المشروع)

```bash
docker compose up -d --build     # يبني ويشغّل كل الخدمات (لازم بعد أي تعديل بـ.env أو Dockerfile)
docker compose restart searxng   # يعيد تشغيل خدمة وحدة بس (يكفي لتعديلات searxng/settings.yml)
docker compose ps                # يعرض حالة كل الحاويات
docker compose logs -f ainewsletter   # يتابع سجل التطبيق حي
```

**تنبيه مهم (اتكشف اليوم):** تعديل `backend/.env` يحتاج `docker compose up -d --build` (إعادة إنشاء الحاوية) — مو `docker restart` بس، لأن متغيرات البيئة تُخبز داخل الحاوية وقت الإنشاء فقط (`env_file:` بملف `app.yml`).
