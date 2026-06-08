# دليل تشغيل AINewsletter_v0.1

هذا الدليل مخصص للمستخدم الذي يريد تشغيل البرنامج محليًا. يمكنك تشغيله بطريقتين:

- باستخدام Docker، وهي الطريقة الأسهل إذا كان Docker مثبتًا.
- بدون Docker باستخدام Python وبيئة افتراضية.

بعد التشغيل افتح الواجهة من المتصفح:

```text
http://127.0.0.1:8000/UI.html
```

## المتطلبات

قبل البدء تأكد من توفر التالي:

- Docker Desktop، إذا أردت التشغيل عبر Docker.
- أو Python 3.11 أو أحدث، إذا أردت التشغيل بدون Docker.
- مفاتيح API التالية داخل ملف البيئة:
  - `OPENAI_API_KEY`
  - `EXA_API_KEY`
  - `TMDB_API_KEY`

ملف البيئة الأساسي هو:

```text
backend/.env
```

إذا لم يكن الملف موجودًا، انسخه من المثال:

```powershell
copy backend\.env.example backend\.env
```

ثم افتحه وأضف المفاتيح:

```powershell
notepad backend\.env
```

## التشغيل باستخدام Docker

هذه الطريقة تشغل التطبيق مع خدمة SearXNG المساعدة.

1. افتح PowerShell داخل مجلد المشروع:

```powershell
cd C:\AINewsletter_v0.1
```

2. تأكد أن ملف البيئة موجود:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

إذا كان `backend\.env` موجودًا مسبقًا، لا تحتاج إلى نسخه مرة أخرى. فقط تأكد أن المفاتيح موجودة داخله.

3. شغل الخدمات:

```powershell
docker compose up --build
```

4. افتح الواجهة:

```text
http://127.0.0.1:8000/UI.html
```

5. لإيقاف التشغيل اضغط `Ctrl + C` في نافذة PowerShell.

أو أوقف الخدمات من نافذة أخرى:

```powershell
docker compose down
```

### تشغيل Docker في الخلفية

إذا أردت تشغيله بدون إبقاء نافذة السجلات مفتوحة:

```powershell
docker compose up --build -d
```

لمشاهدة السجلات:

```powershell
docker compose logs -f ainewsletter
```

لإيقافه:

```powershell
docker compose down
```

## التشغيل بدون Docker

استخدم هذه الطريقة إذا كنت تريد تشغيل البرنامج مباشرة على جهازك.

1. افتح PowerShell داخل مجلد المشروع:

```powershell
cd C:\AINewsletter_v0.1
```

2. أنشئ البيئة الافتراضية:

```powershell
python -m venv venv
```

3. فعّل البيئة:

```powershell
venv\Scripts\activate
```

4. ثبّت المكتبات:

```powershell
pip install -r requirements.txt
```

5. ثبّت متصفح Playwright المطلوب لتصدير PDF:

```powershell
python -m playwright install chromium
```

6. جهّز ملف البيئة:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

7. شغل السيرفر:

```powershell
python backend\server.py
```

8. افتح الواجهة:

```text
http://127.0.0.1:8000/UI.html
```

## تشغيل سريع على ويندوز

يوجد سكربت جاهز لإعادة تشغيل الباكند:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

إذا أردت رؤية السجلات مباشرة:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -Foreground
```

لإيقاف الباكند فقط:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\restart_backend.ps1 -NoStart
```

## طريقة الاستخدام من الواجهة

1. افتح:

```text
http://127.0.0.1:8000/UI.html
```

2. اضغط زر Generate لتوليد النشرة.
3. انتظر حتى يكتمل الجلب والاختيار.
4. يمكنك تعديل البطاقات يدويًا من الواجهة.
5. يمكنك تصدير النشرة PDF من الواجهة.

الملفات التي يتم تحديثها بعد التوليد:

- `frontend/news.json`
- `frontend/ai_updates_run_report.json`
- `backend/news_fetch_state.json`
- `backend/qdrant_db/`

## مشاكل شائعة

### المنفذ 8000 مشغول

إذا ظهر خطأ أن المنفذ مستخدم، أوقف السيرفر القديم:

```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

استبدل `<PID>` بالرقم الذي يظهر من الأمر الأول.

### Docker لا يقرأ مفاتيح API

تأكد أن الملف موجود هنا:

```text
backend/.env
```

وتأكد أن الأسماء مكتوبة بنفس الشكل:

```text
OPENAI_API_KEY=...
EXA_API_KEY=...
TMDB_API_KEY=...
```

ثم أعد التشغيل:

```powershell
docker compose down
docker compose up --build
```

### التوليد لا يجلب أخبارًا كافية

تأكد من:

- صحة مفاتيح API.
- اتصال الإنترنت.
- أن خدمة SearXNG تعمل عند استخدام Docker.
- عدم تفعيل وضع `NEWS_JSON_ONLY_MODE=1` داخل `backend/.env`.

### تصدير PDF لا يعمل بدون Docker

نفذ:

```powershell
python -m playwright install chromium
```

ثم أعد تشغيل السيرفر.

## ملاحظات مهمة

- لا تشارك ملف `backend/.env` لأنه يحتوي مفاتيح API.
- عند استخدام Docker، يتم ربط مجلدي `backend` و `frontend` مع الحاوية، لذلك أي ملفات ناتجة ستظهر في المشروع مباشرة.
- رابط الواجهة المحلي هو `http://127.0.0.1:8000/UI.html`.
- رابط SearXNG عند التشغيل عبر Docker هو `http://127.0.0.1:8080`.
