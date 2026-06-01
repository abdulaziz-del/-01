# ⚖️ المرصد القضائي السعودي الذكي
منصة بحث قانوني ذكية متخصصة في القضاء السعودي

---

## 🚀 تشغيل المشروع محلياً

### 1. المتطلبات
- Python 3.9+
- pip

### 2. تثبيت المكتبات
```bash
pip install -r requirements.txt
```

### 3. إعداد المتغيرات البيئية
أنشئ ملف `.env` أو عيّن المتغيرات:
```bash
export ANTHROPIC_API_KEY=your_key_here
export SECRET_KEY=your_secret_key
# للإنتاج:
export DATABASE_URL=postgresql://user:pass@host/db
```

### 4. تشغيل التطبيق
```bash
python app.py
```
افتح المتصفح: http://localhost:5000

**بيانات الدخول الافتراضية:** admin / admin123

---

## 🗂️ هيكل المشروع
```
mirsad/
├── app.py              # التطبيق الرئيسي (Flask)
├── requirements.txt    # المكتبات
├── Procfile            # إعداد Render/Heroku
├── templates/
│   └── index.html      # الواجهة الكاملة (RTL عربي)
├── uploads/            # الملفات المرفوعة
└── mirsad.db           # قاعدة البيانات (SQLite للتطوير)
```

---

## 🌐 النشر على Render (مجاني)

### الخطوات:
1. **ارفع المشروع على GitHub:**
```bash
git init
git add .
git commit -m "Initial commit - المرصد القضائي"
git remote add origin https://github.com/YOUR_USER/mirsad.git
git push -u origin main
```

2. **أنشئ مشروعاً على [render.com](https://render.com):**
   - New → Web Service
   - اربطه بـ GitHub repository
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Environment Variables:**
     - `ANTHROPIC_API_KEY` = مفتاح Claude API
     - `SECRET_KEY` = مفتاح سري عشوائي
     - `DATABASE_URL` = رابط PostgreSQL (أضف قاعدة بيانات Render مجانية)

3. **أضف قاعدة بيانات PostgreSQL:**
   - New → PostgreSQL (Free Tier)
   - انسخ الـ Internal Database URL وضعه في `DATABASE_URL`

---

## ✨ الوظائف المتاحة

| الوظيفة | الوصف |
|---------|-------|
| 🔍 البحث الذكي | بحث في الأحكام والأنظمة والمبادئ |
| 📋 الأحكام | عرض وتصفح الأحكام القضائية |
| 📜 الأنظمة | قاعدة بيانات الأنظمة واللوائح |
| ⚖️ المبادئ | موسوعة المبادئ القضائية |
| ✍️ مساعد المذكرات | توليد مسودات مذكرات قضائية بالذكاء الاصطناعي |
| 🤖 المساعد القانوني | إجابة أسئلة قانونية مستندة لقاعدة البيانات |
| 🗺️ خريطة القضاء | دليل تفاعلي لهيكل القضاء السعودي |
| 📊 التحليلات | إحصاءات وتحليلات مرئية |
| ⚙️ لوحة التحكم | إدارة كاملة للمحتوى والمستخدمين |

---

## 📡 API Endpoints

```
GET  /api/judgments          - قائمة الأحكام
GET  /api/judgments/<id>     - تفاصيل حكم
GET  /api/regulations        - قائمة الأنظمة
GET  /api/regulations/<id>   - تفاصيل نظام
GET  /api/principles         - المبادئ القضائية
GET  /api/search             - البحث الشامل
POST /api/ai/draft-memo      - توليد مذكرة
POST /api/ai/qa              - سؤال قانوني
POST /api/admin/upload       - رفع ملف (admin)
POST /api/admin/judgments    - إضافة حكم (admin)
```

---

## ⚠️ ملاحظات قانونية
- مخرجات الذكاء الاصطناعي مساعدة أولية فقط ولا تغني عن استشارة محامٍ متخصص
- يجب التحقق من كل معلومة من مصدرها الرسمي
- المنصة لا تعرض أحكاماً سرية أو غير منشورة رسمياً
