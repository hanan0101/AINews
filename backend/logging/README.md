# Logging

This folder contains pipeline logging helpers.
يحتوي هذا المجلد على أدوات تسجيل مسار المعالجة.

## What Gets Logged

- Pipeline run ids and stage names.
- معرفات التشغيل وأسماء المراحل.
- Stage durations for source fetching, filtering, model selection, saving, and supporting content.
- مدد المراحل الخاصة بالجلب والفلترة واختيار النموذج والحفظ والمحتوى الداعم.
- Candidate summaries and model token estimates.
- ملخصات المرشحات وتقديرات رموز النموذج.
- Errors from external services such as Gemini, Exa, SearXNG, Qdrant, or PostgreSQL-adjacent flows.
- أخطاء الخدمات الخارجية مثل Gemini وExa وSearXNG وQdrant والمسارات المرتبطة بقاعدة البيانات.

## Where Logs Go

The active JSONL event stream is written under `backend/logs/ai_updates_run.jsonl` unless environment settings change it.
يكتب سجل الأحداث الحالي بصيغة JSONL داخل `backend/logs/ai_updates_run.jsonl` ما لم تغير الإعدادات ذلك.

## Why This Exists

The newsletter pipeline depends on external APIs, so every run needs enough trace data to explain why candidates were selected, rejected, delayed, or missing.
يعتمد مسار النشرة على واجهات خارجية، لذلك يحتاج كل تشغيل إلى بيانات تتبع كافية لتفسير سبب اختيار المرشحات أو رفضها أو تأخرها أو غيابها.

