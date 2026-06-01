import os
import json
import uuid
import hashlib
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
import anthropic

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mirsad-secret-2024')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///mirsad.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

# ─── Models ──────────────────────────────────────────────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Judgment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(500), nullable=False)
    court = db.Column(db.String(200))
    case_type = db.Column(db.String(200))
    case_number = db.Column(db.String(100))
    judgment_date = db.Column(db.String(50))
    subject = db.Column(db.String(500))
    full_text = db.Column(db.Text)
    facts = db.Column(db.Text)
    requests = db.Column(db.Text)
    defenses = db.Column(db.Text)
    reasons = db.Column(db.Text)
    verdict = db.Column(db.Text)
    principles = db.Column(db.Text)
    related_laws = db.Column(db.Text)
    summary = db.Column(db.Text)
    source_url = db.Column(db.String(500))
    source_name = db.Column(db.String(200))
    file_path = db.Column(db.String(500))
    status = db.Column(db.String(50), default='draft')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    tags = db.Column(db.Text, default='[]')

class Regulation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(500), nullable=False)
    category = db.Column(db.String(200))
    issuing_authority = db.Column(db.String(200))
    issue_date = db.Column(db.String(50))
    full_text = db.Column(db.Text)
    summary = db.Column(db.Text)
    source_url = db.Column(db.String(500))
    source_name = db.Column(db.String(200), default='هيئة الخبراء بمجلس الوزراء')
    status = db.Column(db.String(50), default='published')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Principle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    text = db.Column(db.Text, nullable=False)
    subject = db.Column(db.String(200))
    judgment_id = db.Column(db.Integer, db.ForeignKey('judgment.id'))
    source = db.Column(db.String(300))
    status = db.Column(db.String(50), default='published')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    action = db.Column(db.String(100))
    resource_type = db.Column(db.String(100))
    resource_id = db.Column(db.String(100))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Auth Helpers ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'غير مصرح'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'غير مصرح'}), 401
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            return jsonify({'error': 'صلاحية المدير مطلوبة'}), 403
        return f(*args, **kwargs)
    return decorated

def log_action(user_id, action, resource_type, resource_id, details=''):
    log = AuditLog(user_id=user_id, action=action, resource_type=resource_type,
                   resource_id=str(resource_id), details=details)
    db.session.add(log)
    db.session.commit()

# ─── AI Helper ───────────────────────────────────────────────────────────────

def ai_analyze(prompt, system_prompt=None):
    try:
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        messages = [{"role": "user", "content": prompt}]
        kwargs = {"model": "claude-opus-4-5", "max_tokens": 4096, "messages": messages}
        if system_prompt:
            kwargs["system"] = system_prompt
        response = client.messages.create(**kwargs)
        return response.content[0].text
    except Exception as e:
        return f"خطأ في الذكاء الاصطناعي: {str(e)}"

JUDICIAL_SYSTEM = """أنت مساعد قانوني متخصص في القضاء السعودي. مهمتك تحليل الأحكام القضائية السعودية واستخراج عناصرها.
يجب أن تكون إجاباتك دقيقة ومستندة فقط على النص المقدم. لا تختلق معلومات.
أجب دائماً بالعربية وبصيغة JSON منظمة عند الطلب."""

# ─── Routes: Auth ─────────────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get('username')).first()
    if user and bcrypt.check_password_hash(user.password_hash, data.get('password', '')):
        session['user_id'] = user.id
        session['is_admin'] = user.is_admin
        return jsonify({'success': True, 'is_admin': user.is_admin, 'username': user.username})
    return jsonify({'error': 'بيانات الدخول غير صحيحة'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth/me')
def me():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        return jsonify({'logged_in': True, 'is_admin': user.is_admin, 'username': user.username})
    return jsonify({'logged_in': False})

# ─── Routes: Search ───────────────────────────────────────────────────────────

@app.route('/api/search')
def search():
    q = request.args.get('q', '')
    court = request.args.get('court', '')
    case_type = request.args.get('type', '')
    resource = request.args.get('resource', 'all')
    page = int(request.args.get('page', 1))
    per_page = 12

    results = []

    if resource in ('all', 'judgments'):
        query = Judgment.query.filter(Judgment.status == 'published')
        if q:
            query = query.filter(
                db.or_(Judgment.title.contains(q), Judgment.full_text.contains(q),
                       Judgment.subject.contains(q), Judgment.verdict.contains(q),
                       Judgment.summary.contains(q))
            )
        if court:
            query = query.filter(Judgment.court.contains(court))
        if case_type:
            query = query.filter(Judgment.case_type.contains(case_type))
        for j in query.order_by(Judgment.created_at.desc()).limit(20).all():
            results.append({'type': 'judgment', 'id': j.uid, 'title': j.title,
                           'court': j.court, 'date': j.judgment_date, 'summary': j.summary,
                           'case_type': j.case_type})

    if resource in ('all', 'regulations'):
        query = Regulation.query.filter(Regulation.status == 'published')
        if q:
            query = query.filter(
                db.or_(Regulation.title.contains(q), Regulation.full_text.contains(q),
                       Regulation.summary.contains(q))
            )
        for r in query.order_by(Regulation.created_at.desc()).limit(20).all():
            results.append({'type': 'regulation', 'id': r.uid, 'title': r.title,
                           'category': r.category, 'date': r.issue_date, 'summary': r.summary})

    if resource in ('all', 'principles'):
        query = Principle.query.filter(Principle.status == 'published')
        if q:
            query = query.filter(db.or_(Principle.text.contains(q), Principle.subject.contains(q)))
        for p in query.order_by(Principle.created_at.desc()).limit(20).all():
            results.append({'type': 'principle', 'id': p.uid, 'text': p.text,
                           'subject': p.subject, 'source': p.source})

    return jsonify({'results': results, 'total': len(results)})

# ─── Routes: Judgments ────────────────────────────────────────────────────────

@app.route('/api/judgments')
def get_judgments():
    page = int(request.args.get('page', 1))
    per_page = 12
    query = Judgment.query.filter(Judgment.status == 'published')
    total = query.count()
    judgments = query.order_by(Judgment.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()
    return jsonify({
        'judgments': [{'id': j.uid, 'title': j.title, 'court': j.court,
                      'case_type': j.case_type, 'date': j.judgment_date,
                      'summary': j.summary} for j in judgments],
        'total': total, 'pages': (total + per_page - 1) // per_page
    })

@app.route('/api/judgments/<uid>')
def get_judgment(uid):
    j = Judgment.query.filter_by(uid=uid).first_or_404()
    principles = Principle.query.filter_by(judgment_id=j.id).all()
    return jsonify({
        'id': j.uid, 'title': j.title, 'court': j.court,
        'case_type': j.case_type, 'case_number': j.case_number,
        'date': j.judgment_date, 'subject': j.subject,
        'full_text': j.full_text, 'facts': j.facts,
        'requests': j.requests, 'defenses': j.defenses,
        'reasons': j.reasons, 'verdict': j.verdict,
        'summary': j.summary, 'principles': j.principles,
        'related_laws': j.related_laws, 'source_url': j.source_url,
        'source_name': j.source_name, 'status': j.status,
        'extracted_principles': [{'text': p.text, 'subject': p.subject} for p in principles],
        'tags': json.loads(j.tags or '[]')
    })

# ─── Routes: Regulations ──────────────────────────────────────────────────────

@app.route('/api/regulations')
def get_regulations():
    page = int(request.args.get('page', 1))
    per_page = 12
    query = Regulation.query.filter(Regulation.status == 'published')
    total = query.count()
    regs = query.order_by(Regulation.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()
    return jsonify({
        'regulations': [{'id': r.uid, 'title': r.title, 'category': r.category,
                        'date': r.issue_date, 'summary': r.summary,
                        'source_name': r.source_name} for r in regs],
        'total': total, 'pages': (total + per_page - 1) // per_page
    })

@app.route('/api/regulations/<uid>')
def get_regulation(uid):
    r = Regulation.query.filter_by(uid=uid).first_or_404()
    return jsonify({
        'id': r.uid, 'title': r.title, 'category': r.category,
        'issuing_authority': r.issuing_authority, 'date': r.issue_date,
        'full_text': r.full_text, 'summary': r.summary,
        'source_url': r.source_url, 'source_name': r.source_name
    })

# ─── Routes: Principles ───────────────────────────────────────────────────────

@app.route('/api/principles')
def get_principles():
    subject = request.args.get('subject', '')
    query = Principle.query.filter(Principle.status == 'published')
    if subject:
        query = query.filter(Principle.subject.contains(subject))
    principles = query.order_by(Principle.created_at.desc()).limit(50).all()
    return jsonify({
        'principles': [{'id': p.uid, 'text': p.text, 'subject': p.subject,
                       'source': p.source} for p in principles]
    })

# ─── Routes: AI Features ──────────────────────────────────────────────────────

@app.route('/api/ai/analyze-judgment', methods=['POST'])
@admin_required
def analyze_judgment():
    data = request.json
    text = data.get('text', '')
    if not text:
        return jsonify({'error': 'النص مطلوب'}), 400

    prompt = f"""حلل هذا الحكم القضائي السعودي واستخرج عناصره الأساسية.
أجب بصيغة JSON فقط بهذا الهيكل بالضبط:
{{
  "facts": "الوقائع",
  "requests": "طلبات الأطراف",
  "defenses": "الدفوع",
  "reasons": "الأسباب",
  "verdict": "المنطوق",
  "principles": "المبادئ القضائية المستخلصة",
  "related_laws": "النصوص النظامية المشار إليها",
  "summary": "ملخص مختصر للحكم"
}}

النص:
{text[:8000]}"""

    result = ai_analyze(prompt, JUDICIAL_SYSTEM)
    try:
        clean = result.strip()
        if clean.startswith('```'):
            clean = clean.split('```')[1]
            if clean.startswith('json'):
                clean = clean[4:]
        parsed = json.loads(clean)
        return jsonify({'success': True, 'data': parsed})
    except:
        return jsonify({'success': True, 'data': {'summary': result}})

@app.route('/api/ai/draft-memo', methods=['POST'])
def draft_memo():
    data = request.json
    facts = data.get('facts', '')
    memo_type = data.get('type', 'لائحة دعوى')
    legal_basis = data.get('legal_basis', '')

    prompt = f"""أنت محامٍ سعودي متخصص. اكتب {memo_type} قانونية احترافية وفق الإجراءات السعودية.

وقائع القضية:
{facts}

{'الأساس القانوني المقترح: ' + legal_basis if legal_basis else ''}

اكتب المذكرة بأسلوب قانوني رسمي وفق النظام السعودي. 
ابدأ بـ "بسم الله الرحمن الرحيم" ثم البيانات الرسمية.
ضع تنبيهاً في النهاية بأن هذه مسودة أولية تحتاج مراجعة متخصص قانوني."""

    result = ai_analyze(prompt, JUDICIAL_SYSTEM)
    return jsonify({'draft': result})

@app.route('/api/ai/qa', methods=['POST'])
def legal_qa():
    data = request.json
    question = data.get('question', '')

    judgments = Judgment.query.filter(
        db.or_(Judgment.title.contains(question[:50]),
               Judgment.summary.contains(question[:50])),
        Judgment.status == 'published'
    ).limit(3).all()

    regulations = Regulation.query.filter(
        db.or_(Regulation.title.contains(question[:50]),
               Regulation.summary.contains(question[:50])),
        Regulation.status == 'published'
    ).limit(3).all()

    context = ""
    sources = []
    for j in judgments:
        context += f"\nحكم قضائي: {j.title}\nالملخص: {j.summary}\n"
        sources.append({'type': 'judgment', 'title': j.title, 'id': j.uid})
    for r in regulations:
        context += f"\nنظام: {r.title}\nالملخص: {r.summary}\n"
        sources.append({'type': 'regulation', 'title': r.title, 'id': r.uid})

    prompt = f"""بناءً على المصادر التالية من قاعدة البيانات، أجب على السؤال القانوني.
إذا لم تجد إجابة في المصادر، قل ذلك صراحة ولا تختلق معلومات.

المصادر المتاحة:
{context if context else 'لا توجد مصادر مرتبطة في قاعدة البيانات حالياً.'}

السؤال: {question}"""

    answer = ai_analyze(prompt, JUDICIAL_SYSTEM)
    return jsonify({'answer': answer, 'sources': sources})

# ─── Routes: Admin ────────────────────────────────────────────────────────────

@app.route('/api/admin/judgments', methods=['POST'])
@admin_required
def create_judgment():
    data = request.json
    j = Judgment(
        title=data.get('title', ''),
        court=data.get('court', ''),
        case_type=data.get('case_type', ''),
        case_number=data.get('case_number', ''),
        judgment_date=data.get('judgment_date', ''),
        subject=data.get('subject', ''),
        full_text=data.get('full_text', ''),
        facts=data.get('facts', ''),
        requests=data.get('requests', ''),
        defenses=data.get('defenses', ''),
        reasons=data.get('reasons', ''),
        verdict=data.get('verdict', ''),
        principles=data.get('principles', ''),
        related_laws=data.get('related_laws', ''),
        summary=data.get('summary', ''),
        source_url=data.get('source_url', ''),
        source_name=data.get('source_name', ''),
        status=data.get('status', 'draft'),
        created_by=session['user_id'],
        tags=json.dumps(data.get('tags', []))
    )
    db.session.add(j)
    db.session.commit()
    log_action(session['user_id'], 'create', 'judgment', j.id, f'إضافة حكم: {j.title}')
    return jsonify({'success': True, 'id': j.uid})

@app.route('/api/admin/judgments/<uid>', methods=['PUT'])
@admin_required
def update_judgment(uid):
    j = Judgment.query.filter_by(uid=uid).first_or_404()
    data = request.json
    for field in ['title','court','case_type','case_number','judgment_date','subject',
                  'full_text','facts','requests','defenses','reasons','verdict',
                  'principles','related_laws','summary','source_url','source_name','status']:
        if field in data:
            setattr(j, field, data[field])
    if 'tags' in data:
        j.tags = json.dumps(data['tags'])
    j.updated_at = datetime.utcnow()
    db.session.commit()
    log_action(session['user_id'], 'update', 'judgment', j.id, f'تحديث حكم: {j.title}')
    return jsonify({'success': True})

@app.route('/api/admin/judgments/<uid>', methods=['DELETE'])
@admin_required
def delete_judgment(uid):
    j = Judgment.query.filter_by(uid=uid).first_or_404()
    log_action(session['user_id'], 'delete', 'judgment', j.id, f'حذف حكم: {j.title}')
    db.session.delete(j)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/admin/regulations', methods=['POST'])
@admin_required
def create_regulation():
    data = request.json
    r = Regulation(
        title=data.get('title', ''),
        category=data.get('category', ''),
        issuing_authority=data.get('issuing_authority', ''),
        issue_date=data.get('issue_date', ''),
        full_text=data.get('full_text', ''),
        summary=data.get('summary', ''),
        source_url=data.get('source_url', ''),
        source_name=data.get('source_name', 'هيئة الخبراء بمجلس الوزراء'),
        status=data.get('status', 'published'),
        created_by=session['user_id']
    )
    db.session.add(r)
    db.session.commit()
    log_action(session['user_id'], 'create', 'regulation', r.id, f'إضافة نظام: {r.title}')
    return jsonify({'success': True, 'id': r.uid})

@app.route('/api/admin/upload', methods=['POST'])
@admin_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'لا يوجد ملف'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'لم يتم اختيار ملف'}), 400
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ('pdf', 'doc', 'docx', 'txt'):
        return jsonify({'error': 'نوع الملف غير مدعوم'}), 400
    unique_name = f"{uuid.uuid4()}_{filename}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    file.save(file_path)

    text = extract_text(file_path, ext)
    log_action(session['user_id'], 'upload', 'file', unique_name, f'رفع ملف: {filename}')
    return jsonify({'success': True, 'file_path': unique_name, 'extracted_text': text[:5000]})

def extract_text(path, ext):
    try:
        if ext == 'txt':
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        elif ext == 'pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(path)
                return '\n'.join(p.extract_text() or '' for p in reader.pages)
            except:
                return 'تعذّر استخراج النص من PDF. يرجى نسخ النص يدوياً.'
        elif ext in ('doc', 'docx'):
            try:
                import docx
                doc = docx.Document(path)
                return '\n'.join(p.text for p in doc.paragraphs)
            except:
                return 'تعذّر استخراج النص من Word. يرجى نسخ النص يدوياً.'
    except Exception as e:
        return f'خطأ في الاستخراج: {str(e)}'
    return ''

@app.route('/api/admin/stats')
@admin_required
def admin_stats():
    total_j = Judgment.query.count()
    published_j = Judgment.query.filter_by(status='published').count()
    total_r = Regulation.query.count()
    total_p = Principle.query.count()
    total_u = User.query.count()
    recent_logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(20).all()

    courts = db.session.query(Judgment.court, db.func.count(Judgment.id)).group_by(Judgment.court).all()
    types = db.session.query(Judgment.case_type, db.func.count(Judgment.id)).group_by(Judgment.case_type).all()

    return jsonify({
        'totals': {'judgments': total_j, 'published_judgments': published_j,
                  'regulations': total_r, 'principles': total_p, 'users': total_u},
        'by_court': [{'court': c[0] or 'غير محدد', 'count': c[1]} for c in courts],
        'by_type': [{'type': t[0] or 'غير محدد', 'count': t[1]} for t in types],
        'recent_logs': [{'action': l.action, 'resource_type': l.resource_type,
                        'details': l.details, 'timestamp': l.timestamp.isoformat()} for l in recent_logs]
    })

@app.route('/api/admin/all-judgments')
@admin_required
def admin_all_judgments():
    page = int(request.args.get('page', 1))
    per_page = 15
    query = Judgment.query
    total = query.count()
    judgments = query.order_by(Judgment.created_at.desc()).offset((page-1)*per_page).limit(per_page).all()
    return jsonify({
        'judgments': [{'id': j.uid, 'title': j.title, 'court': j.court,
                      'case_type': j.case_type, 'status': j.status,
                      'created_at': j.created_at.isoformat()} for j in judgments],
        'total': total
    })

@app.route('/api/admin/principles', methods=['POST'])
@admin_required
def create_principle():
    data = request.json
    p = Principle(
        text=data.get('text', ''),
        subject=data.get('subject', ''),
        judgment_id=data.get('judgment_id'),
        source=data.get('source', ''),
        status=data.get('status', 'published'),
        created_by=session['user_id']
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({'success': True, 'id': p.uid})

# ─── Main Page ────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>المرصد القضائي السعودي الذكي</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800&family=Amiri:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --gold: #B8860B;
    --gold-light: #D4A017;
    --gold-pale: #FDF6E3;
    --gold-border: #E8D5A3;
    --navy: #0A1628;
    --navy-mid: #122040;
    --navy-light: #1E3A5F;
    --navy-soft: #2A5080;
    --cream: #FAFAF7;
    --cream-2: #F4F1E8;
    --text-main: #1A1A2E;
    --text-muted: #5A6070;
    --text-light: #8A9AB0;
    --border: #E2D9C8;
    --border-light: #EDE8DC;
    --success: #1A6B3C;
    --danger: #8B1A1A;
    --info: #1A4A6B;
    --radius: 10px;
    --radius-lg: 16px;
    --shadow: 0 2px 16px rgba(10,22,40,0.08);
    --shadow-lg: 0 8px 40px rgba(10,22,40,0.14);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Tajawal', sans-serif;
    background: var(--cream);
    color: var(--text-main);
    direction: rtl;
    min-height: 100vh;
  }

  /* ─── Header ─────────────────────────────── */
  .header {
    background: var(--navy);
    border-bottom: 2px solid var(--gold);
    padding: 0 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 64px;
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .header-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
  }

  .brand-icon {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, var(--gold), var(--gold-light));
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
  }

  .brand-text { color: white; }
  .brand-text h1 { font-size: 17px; font-weight: 700; line-height: 1.2; }
  .brand-text span { font-size: 11px; color: var(--gold-light); font-weight: 300; }

  .header-nav {
    display: flex;
    gap: 4px;
  }

  .nav-btn {
    background: none;
    border: none;
    color: #B0BDD0;
    padding: 6px 14px;
    border-radius: 6px;
    font-family: 'Tajawal', sans-serif;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
  }
  .nav-btn:hover, .nav-btn.active { background: rgba(184,134,11,0.15); color: var(--gold-light); }

  .header-actions { display: flex; gap: 8px; align-items: center; }

  .btn {
    padding: 7px 18px;
    border-radius: var(--radius);
    font-family: 'Tajawal', sans-serif;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    border: none;
    transition: all 0.2s;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .btn-gold { background: var(--gold); color: white; }
  .btn-gold:hover { background: var(--gold-light); }
  .btn-outline { background: transparent; color: #B0BDD0; border: 1px solid rgba(255,255,255,0.15); }
  .btn-outline:hover { border-color: var(--gold); color: var(--gold-light); }
  .btn-primary { background: var(--navy-light); color: white; border: 1px solid var(--navy-soft); }
  .btn-primary:hover { background: var(--navy-soft); }
  .btn-danger { background: #fee2e2; color: var(--danger); border: 1px solid #fecaca; }
  .btn-danger:hover { background: #fecaca; }
  .btn-success { background: #d1fae5; color: var(--success); border: 1px solid #a7f3d0; }
  .btn-sm { padding: 5px 12px; font-size: 13px; }

  /* ─── Layout ──────────────────────────────── */
  .main { display: flex; min-height: calc(100vh - 64px); }

  .sidebar {
    width: 220px;
    background: white;
    border-left: 1px solid var(--border);
    padding: 1.5rem 0;
    flex-shrink: 0;
    position: sticky;
    top: 64px;
    height: calc(100vh - 64px);
    overflow-y: auto;
  }

  .sidebar-section { margin-bottom: 0.5rem; }
  .sidebar-label {
    padding: 6px 20px;
    font-size: 11px;
    font-weight: 700;
    color: var(--text-light);
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }
  .sidebar-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 20px;
    color: var(--text-muted);
    cursor: pointer;
    font-size: 14px;
    border-right: 3px solid transparent;
    transition: all 0.15s;
  }
  .sidebar-item:hover { background: var(--cream-2); color: var(--navy); }
  .sidebar-item.active { background: var(--gold-pale); color: var(--gold); border-right-color: var(--gold); font-weight: 500; }
  .sidebar-icon { font-size: 16px; width: 20px; text-align: center; }

  .content { flex: 1; padding: 2rem; min-width: 0; }

  /* ─── Pages ───────────────────────────────── */
  .page { display: none; }
  .page.active { display: block; }

  /* ─── Hero ────────────────────────────────── */
  .hero {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-mid) 60%, var(--navy-light) 100%);
    border-radius: var(--radius-lg);
    padding: 3rem 2.5rem;
    color: white;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
  }
  .hero::before {
    content: '⚖';
    position: absolute;
    left: 2rem;
    top: 50%;
    transform: translateY(-50%);
    font-size: 100px;
    opacity: 0.05;
  }
  .hero h2 {
    font-family: 'Amiri', serif;
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--gold-light);
  }
  .hero p { font-size: 15px; color: #B0BDD0; max-width: 600px; line-height: 1.7; }

  .search-bar {
    display: flex;
    gap: 10px;
    margin-top: 1.5rem;
    max-width: 700px;
  }
  .search-input {
    flex: 1;
    padding: 12px 18px;
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: var(--radius);
    background: rgba(255,255,255,0.08);
    color: white;
    font-family: 'Tajawal', sans-serif;
    font-size: 15px;
    outline: none;
    backdrop-filter: blur(4px);
  }
  .search-input::placeholder { color: rgba(255,255,255,0.4); }
  .search-input:focus { border-color: var(--gold); background: rgba(255,255,255,0.12); }

  /* ─── Stats Row ───────────────────────────── */
  .stats-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
    margin-bottom: 2rem;
  }
  .stat-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    box-shadow: var(--shadow);
  }
  .stat-icon {
    width: 44px; height: 44px;
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px;
    flex-shrink: 0;
  }
  .stat-icon.gold { background: var(--gold-pale); }
  .stat-icon.blue { background: #EBF4FF; }
  .stat-icon.green { background: #EDFAF3; }
  .stat-icon.purple { background: #F3F0FF; }
  .stat-num { font-size: 26px; font-weight: 700; color: var(--navy); line-height: 1; }
  .stat-label { font-size: 12px; color: var(--text-muted); margin-top: 3px; }

  /* ─── Section Headers ─────────────────────── */
  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
  }
  .section-title {
    font-family: 'Amiri', serif;
    font-size: 20px;
    font-weight: 700;
    color: var(--navy);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-title::before {
    content: '';
    display: inline-block;
    width: 4px;
    height: 20px;
    background: var(--gold);
    border-radius: 2px;
  }

  /* ─── Cards Grid ──────────────────────────── */
  .cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 1rem;
  }

  .card {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    box-shadow: var(--shadow);
    transition: all 0.2s;
    cursor: pointer;
    position: relative;
  }
  .card:hover { box-shadow: var(--shadow-lg); transform: translateY(-2px); border-color: var(--gold-border); }
  .card-type {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    margin-bottom: 8px;
  }
  .type-judgment { background: #FEF3C7; color: #92400E; }
  .type-regulation { background: #DBEAFE; color: #1E40AF; }
  .type-principle { background: #D1FAE5; color: #065F46; }
  .card-title { font-size: 14px; font-weight: 600; color: var(--text-main); margin-bottom: 6px; line-height: 1.5; }
  .card-meta { font-size: 12px; color: var(--text-muted); display: flex; flex-wrap: wrap; gap: 8px; }
  .card-meta span { display: flex; align-items: center; gap: 3px; }
  .card-summary { font-size: 13px; color: var(--text-muted); margin-top: 8px; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

  /* ─── Detail Panel ────────────────────────── */
  .detail-panel {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow);
  }
  .detail-header {
    background: var(--navy);
    padding: 1.5rem 2rem;
    color: white;
  }
  .detail-header h2 {
    font-family: 'Amiri', serif;
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 8px;
    color: var(--gold-light);
  }
  .detail-meta { display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: #B0BDD0; }
  .detail-body { padding: 2rem; }

  .detail-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }
  .tab-btn {
    padding: 8px 16px;
    background: none;
    border: none;
    font-family: 'Tajawal', sans-serif;
    font-size: 13px;
    color: var(--text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: all 0.15s;
  }
  .tab-btn.active { color: var(--gold); border-bottom-color: var(--gold); font-weight: 500; }

  .tab-content { display: none; }
  .tab-content.active { display: block; }

  .detail-section { margin-bottom: 1.5rem; }
  .detail-section h3 {
    font-size: 14px;
    font-weight: 600;
    color: var(--navy);
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px dashed var(--border);
  }
  .detail-text { font-size: 14px; line-height: 1.8; color: var(--text-main); white-space: pre-wrap; }

  .principle-item {
    background: var(--gold-pale);
    border: 1px solid var(--gold-border);
    border-radius: var(--radius);
    padding: 1rem;
    margin-bottom: 0.75rem;
    font-size: 14px;
    line-height: 1.7;
  }
  .principle-item::before { content: '📌 '; }

  /* ─── Search Page ─────────────────────────── */
  .search-filters {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    margin-bottom: 1.5rem;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: flex-end;
  }
  .filter-group { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 150px; }
  .filter-group label { font-size: 12px; font-weight: 500; color: var(--text-muted); }
  .filter-group input, .filter-group select {
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: 'Tajawal', sans-serif;
    font-size: 13px;
    background: var(--cream);
    color: var(--text-main);
    outline: none;
  }
  .filter-group input:focus, .filter-group select:focus { border-color: var(--gold); }

  /* ─── Memo Page ───────────────────────────── */
  .memo-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
  .memo-form {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
  }
  .form-group { margin-bottom: 1rem; }
  .form-group label { display: block; font-size: 13px; font-weight: 500; color: var(--text-muted); margin-bottom: 5px; }
  .form-group textarea {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: 'Tajawal', sans-serif;
    font-size: 14px;
    resize: vertical;
    outline: none;
    background: var(--cream);
    line-height: 1.7;
  }
  .form-group textarea:focus { border-color: var(--gold); }
  .form-group select {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: 'Tajawal', sans-serif;
    font-size: 14px;
    background: var(--cream);
    outline: none;
  }
  .memo-output {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
  }
  .memo-text {
    flex: 1;
    font-size: 14px;
    line-height: 2;
    color: var(--text-main);
    font-family: 'Tajawal', sans-serif;
    white-space: pre-wrap;
    min-height: 400px;
    background: var(--cream);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem;
  }

  /* ─── Admin ───────────────────────────────── */
  .admin-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 2rem; }
  .admin-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    text-align: center;
    box-shadow: var(--shadow);
  }
  .admin-card .big-num { font-size: 36px; font-weight: 700; color: var(--navy); }
  .admin-card .label { font-size: 13px; color: var(--text-muted); margin-top: 4px; }

  .admin-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .admin-table th {
    background: var(--navy);
    color: white;
    padding: 10px 14px;
    text-align: right;
    font-weight: 500;
    font-size: 13px;
  }
  .admin-table td {
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-light);
    color: var(--text-main);
  }
  .admin-table tr:hover td { background: var(--cream-2); }

  .status-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
  }
  .status-published { background: #D1FAE5; color: #065F46; }
  .status-draft { background: #FEF3C7; color: #92400E; }
  .status-review { background: #DBEAFE; color: #1E40AF; }

  /* ─── QA Chat ─────────────────────────────── */
  .qa-container { max-width: 700px; }
  .chat-messages {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    min-height: 300px;
    max-height: 500px;
    overflow-y: auto;
    margin-bottom: 1rem;
  }
  .msg { margin-bottom: 1rem; }
  .msg-user { text-align: left; }
  .msg-user .bubble {
    background: var(--navy);
    color: white;
    display: inline-block;
    padding: 10px 16px;
    border-radius: 12px 12px 4px 12px;
    max-width: 80%;
    font-size: 14px;
    line-height: 1.6;
  }
  .msg-ai .bubble {
    background: var(--gold-pale);
    border: 1px solid var(--gold-border);
    display: inline-block;
    padding: 10px 16px;
    border-radius: 12px 12px 12px 4px;
    max-width: 90%;
    font-size: 14px;
    line-height: 1.8;
    white-space: pre-wrap;
  }
  .msg-sources { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px; }
  .source-chip {
    background: var(--cream-2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 11px;
    color: var(--text-muted);
    cursor: pointer;
  }
  .source-chip:hover { border-color: var(--gold); color: var(--gold); }

  /* ─── Map/Chart ───────────────────────────── */
  .chart-box {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
  }
  .chart-bars { display: flex; flex-direction: column; gap: 10px; margin-top: 1rem; }
  .bar-row { display: flex; align-items: center; gap: 10px; }
  .bar-label { width: 150px; font-size: 13px; color: var(--text-muted); text-align: right; flex-shrink: 0; }
  .bar-track { flex: 1; height: 24px; background: var(--cream-2); border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; background: linear-gradient(90deg, var(--navy-light), var(--gold)); border-radius: 4px; transition: width 0.6s ease; display: flex; align-items: center; padding-right: 8px; }
  .bar-num { font-size: 12px; color: white; font-weight: 600; }

  /* ─── Loading / Empty ─────────────────────── */
  .loading {
    text-align: center;
    padding: 3rem;
    color: var(--text-muted);
    font-size: 14px;
  }
  .loading .spinner {
    width: 32px; height: 32px;
    border: 3px solid var(--border);
    border-top-color: var(--gold);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    margin: 0 auto 1rem;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .empty-state {
    text-align: center;
    padding: 4rem 2rem;
    color: var(--text-muted);
  }
  .empty-state .icon { font-size: 48px; margin-bottom: 1rem; }
  .empty-state p { font-size: 15px; }

  /* ─── Modal ───────────────────────────────── */
  .modal-overlay {
    position: fixed; inset: 0;
    background: rgba(10,22,40,0.6);
    z-index: 200;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: white;
    border-radius: var(--radius-lg);
    width: 100%;
    max-width: 680px;
    max-height: 90vh;
    overflow-y: auto;
    box-shadow: var(--shadow-lg);
  }
  .modal-header {
    background: var(--navy);
    padding: 1.25rem 1.5rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    color: white;
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    position: sticky;
    top: 0;
    z-index: 1;
  }
  .modal-header h3 { font-size: 16px; font-weight: 600; color: var(--gold-light); }
  .modal-close {
    background: none; border: none; color: #B0BDD0;
    font-size: 20px; cursor: pointer; line-height: 1;
  }
  .modal-body { padding: 1.5rem; }
  .modal-footer {
    padding: 1rem 1.5rem;
    border-top: 1px solid var(--border);
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }

  /* ─── Login ───────────────────────────────── */
  .login-overlay {
    position: fixed; inset: 0;
    background: var(--navy);
    z-index: 300;
    display: none;
    align-items: center;
    justify-content: center;
  }
  .login-overlay.open { display: flex; }
  .login-box {
    background: white;
    border-radius: var(--radius-lg);
    padding: 2.5rem;
    width: 380px;
    text-align: center;
    box-shadow: var(--shadow-lg);
  }
  .login-logo { font-size: 40px; margin-bottom: 1rem; }
  .login-box h2 { font-family: 'Amiri', serif; font-size: 22px; color: var(--navy); margin-bottom: 6px; }
  .login-box p { font-size: 13px; color: var(--text-muted); margin-bottom: 1.5rem; }
  .login-input {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: 'Tajawal', sans-serif;
    font-size: 14px;
    margin-bottom: 10px;
    background: var(--cream);
    outline: none;
    text-align: right;
  }
  .login-input:focus { border-color: var(--gold); }
  .login-error { color: var(--danger); font-size: 13px; margin-bottom: 10px; }
  .toast {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    z-index: 500;
    display: none;
    padding: 12px 20px;
    border-radius: var(--radius);
    font-size: 14px;
    font-weight: 500;
    max-width: 300px;
    box-shadow: var(--shadow-lg);
  }
  .toast.success { background: #D1FAE5; color: var(--success); border: 1px solid #A7F3D0; }
  .toast.error { background: #FEE2E2; color: var(--danger); border: 1px solid #FECACA; }
  .toast.show { display: block; animation: slideIn 0.3s ease; }
  @keyframes slideIn { from { transform: translateX(20px); opacity: 0; } to { transform: none; opacity: 1; } }

  /* ─── Judicial Map ────────────────────────── */
  .jmap { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
  .jmap-card {
    background: white;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem;
    box-shadow: var(--shadow);
  }
  .jmap-card h3 { font-size: 15px; font-weight: 600; color: var(--navy); margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
  .jmap-card ul { list-style: none; }
  .jmap-card ul li {
    padding: 7px 0;
    border-bottom: 1px dashed var(--border-light);
    font-size: 13px;
    color: var(--text-muted);
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
  .jmap-card ul li::before { content: '←'; color: var(--gold); flex-shrink: 0; }
  .jmap-card ul li:last-child { border-bottom: none; }

  /* ─── Pagination ──────────────────────────── */
  .pagination { display: flex; gap: 6px; justify-content: center; margin-top: 1.5rem; flex-wrap: wrap; }
  .page-btn {
    padding: 6px 14px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: white;
    font-family: 'Tajawal', sans-serif;
    font-size: 13px;
    cursor: pointer;
    color: var(--text-muted);
  }
  .page-btn.active { background: var(--navy); color: white; border-color: var(--navy); }
  .page-btn:hover:not(.active) { border-color: var(--gold); color: var(--gold); }

  @media (max-width: 768px) {
    .sidebar { display: none; }
    .memo-layout { grid-template-columns: 1fr; }
    .stats-row { grid-template-columns: repeat(2, 1fr); }
    .admin-grid { grid-template-columns: repeat(2, 1fr); }
    .jmap { grid-template-columns: 1fr; }
    .header-nav { display: none; }
  }

  .upload-zone {
    border: 2px dashed var(--gold-border);
    border-radius: var(--radius);
    padding: 2rem;
    text-align: center;
    cursor: pointer;
    color: var(--text-muted);
    font-size: 14px;
    transition: all 0.2s;
    background: var(--cream);
  }
  .upload-zone:hover { border-color: var(--gold); background: var(--gold-pale); color: var(--navy); }

  .notice {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 13px;
    color: #92400E;
    margin-bottom: 1rem;
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
</style>
</head>
<body>

<!-- ─── Login Overlay ─── -->
<div class="login-overlay" id="loginOverlay">
  <div class="login-box">
    <div class="login-logo">⚖️</div>
    <h2>المرصد القضائي السعودي الذكي</h2>
    <p>منصة البحث القانوني والقضائي</p>
    <div id="loginError" class="login-error" style="display:none"></div>
    <input class="login-input" type="text" id="loginUser" placeholder="اسم المستخدم" />
    <input class="login-input" type="password" id="loginPass" placeholder="كلمة المرور" />
    <button class="btn btn-gold" style="width:100%;justify-content:center;padding:11px" onclick="doLogin()">دخول</button>
    <p style="margin-top:1rem;font-size:12px;color:var(--text-light)">للعرض التجريبي: admin / admin123</p>
  </div>
</div>

<!-- ─── Toast ─── -->
<div class="toast" id="toast"></div>

<!-- ─── Header ─── -->
<header class="header">
  <div class="header-brand" onclick="navigate('home')">
    <div class="brand-icon">⚖️</div>
    <div class="brand-text">
      <h1>المرصد القضائي الذكي</h1>
      <span>البحث القانوني السعودي</span>
    </div>
  </div>
  <nav class="header-nav">
    <button class="nav-btn active" onclick="navigate('home')">الرئيسية</button>
    <button class="nav-btn" onclick="navigate('search')">البحث</button>
    <button class="nav-btn" onclick="navigate('judgments')">الأحكام</button>
    <button class="nav-btn" onclick="navigate('regulations')">الأنظمة</button>
    <button class="nav-btn" onclick="navigate('principles')">المبادئ</button>
    <button class="nav-btn" onclick="navigate('memo')">مساعد المذكرات</button>
    <button class="nav-btn" onclick="navigate('map')">خريطة القضاء</button>
    <button class="nav-btn" onclick="navigate('qa')">الذكاء الاصطناعي</button>
  </nav>
  <div class="header-actions">
    <span id="userLabel" style="color:#B0BDD0;font-size:13px"></span>
    <button class="btn btn-outline btn-sm" id="adminBtn" onclick="navigate('admin')" style="display:none">لوحة التحكم</button>
    <button class="btn btn-outline btn-sm" onclick="doLogout()">خروج</button>
  </div>
</header>

<!-- ─── Main ─── -->
<div class="main">
  <aside class="sidebar">
    <div class="sidebar-section">
      <div class="sidebar-label">القسم الرئيسي</div>
      <div class="sidebar-item active" onclick="navigate('home')"><span class="sidebar-icon">🏛️</span> الرئيسية</div>
      <div class="sidebar-item" onclick="navigate('search')"><span class="sidebar-icon">🔍</span> البحث الذكي</div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-label">قواعد البيانات</div>
      <div class="sidebar-item" onclick="navigate('judgments')"><span class="sidebar-icon">📋</span> الأحكام القضائية</div>
      <div class="sidebar-item" onclick="navigate('regulations')"><span class="sidebar-icon">📜</span> الأنظمة واللوائح</div>
      <div class="sidebar-item" onclick="navigate('principles')"><span class="sidebar-icon">⚖️</span> المبادئ القضائية</div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-label">الأدوات</div>
      <div class="sidebar-item" onclick="navigate('memo')"><span class="sidebar-icon">✍️</span> مساعد المذكرات</div>
      <div class="sidebar-item" onclick="navigate('qa')"><span class="sidebar-icon">🤖</span> المساعد القانوني</div>
      <div class="sidebar-item" onclick="navigate('map')"><span class="sidebar-icon">🗺️</span> خريطة القضاء</div>
      <div class="sidebar-item" onclick="navigate('analytics')"><span class="sidebar-icon">📊</span> التحليلات</div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-label">الإدارة</div>
      <div class="sidebar-item" id="adminSideItem" onclick="navigate('admin')" style="display:none"><span class="sidebar-icon">⚙️</span> لوحة التحكم</div>
    </div>
  </aside>

  <main class="content">

    <!-- ═══ HOME ═══ -->
    <div class="page active" id="page-home">
      <div class="hero">
        <h2>المرصد القضائي السعودي الذكي</h2>
        <p>منصة متكاملة للبحث القانوني في الأحكام القضائية السعودية والأنظمة واللوائح والمبادئ القضائية، مدعومة بالذكاء الاصطناعي</p>
        <div class="search-bar">
          <input class="search-input" id="heroSearch" placeholder="ابحث في الأحكام والأنظمة والمبادئ..." onkeydown="if(event.key==='Enter')quickSearch()">
          <button class="btn btn-gold" onclick="quickSearch()">🔍 بحث</button>
        </div>
      </div>

      <div class="stats-row" id="homeStats">
        <div class="stat-card"><div class="stat-icon gold">📋</div><div><div class="stat-num" id="sJudgments">—</div><div class="stat-label">حكم قضائي</div></div></div>
        <div class="stat-card"><div class="stat-icon blue">📜</div><div><div class="stat-num" id="sRegs">—</div><div class="stat-label">نظام ولائحة</div></div></div>
        <div class="stat-card"><div class="stat-icon green">⚖️</div><div><div class="stat-num" id="sPrincs">—</div><div class="stat-label">مبدأ قضائي</div></div></div>
        <div class="stat-card"><div class="stat-icon purple">👥</div><div><div class="stat-num" id="sUsers">—</div><div class="stat-label">مستخدم مسجل</div></div></div>
      </div>

      <div class="notice">⚠️ <span>تنبيه قانوني: مخرجات هذه المنصة مساعدة أولية لا تغني عن الاستشارة القانونية المتخصصة. يجب التحقق من كل معلومة من مصدرها الرسمي.</span></div>

      <div class="section-header">
        <h2 class="section-title">آخر الأحكام المضافة</h2>
        <button class="btn btn-primary btn-sm" onclick="navigate('judgments')">عرض الكل</button>
      </div>
      <div class="cards-grid" id="homeJudgments"><div class="loading"><div class="spinner"></div>جارٍ التحميل...</div></div>
    </div>

    <!-- ═══ SEARCH ═══ -->
    <div class="page" id="page-search">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">البحث الذكي</h2>
      </div>
      <div class="search-filters">
        <div class="filter-group" style="flex:3;min-width:200px">
          <label>نص البحث</label>
          <input type="text" id="searchQ" placeholder="أدخل كلمات البحث...">
        </div>
        <div class="filter-group">
          <label>المصدر</label>
          <select id="searchResource">
            <option value="all">الكل</option>
            <option value="judgments">الأحكام</option>
            <option value="regulations">الأنظمة</option>
            <option value="principles">المبادئ</option>
          </select>
        </div>
        <div class="filter-group">
          <label>المحكمة</label>
          <input type="text" id="searchCourt" placeholder="اسم المحكمة">
        </div>
        <div class="filter-group">
          <label>نوع القضية</label>
          <input type="text" id="searchType" placeholder="نوع القضية">
        </div>
        <button class="btn btn-gold" onclick="doSearch()" style="align-self:flex-end">بحث</button>
      </div>
      <div id="searchResults"><div class="empty-state"><div class="icon">🔍</div><p>أدخل كلمات البحث للبدء</p></div></div>
    </div>

    <!-- ═══ JUDGMENTS ═══ -->
    <div class="page" id="page-judgments">
      <div class="section-header">
        <h2 class="section-title">الأحكام القضائية</h2>
      </div>
      <div id="judgmentDetail" style="display:none;margin-bottom:1.5rem">
        <button class="btn btn-outline btn-sm" onclick="closeDetail('judgmentDetail');loadJudgments()" style="color:var(--navy);border-color:var(--border);background:white;margin-bottom:1rem">← رجوع</button>
        <div class="detail-panel" id="judgmentDetailContent"></div>
      </div>
      <div id="judgmentsList">
        <div class="cards-grid" id="judgmentsGrid"><div class="loading"><div class="spinner"></div>جارٍ التحميل...</div></div>
        <div class="pagination" id="judgmentsPagination"></div>
      </div>
    </div>

    <!-- ═══ REGULATIONS ═══ -->
    <div class="page" id="page-regulations">
      <div class="section-header">
        <h2 class="section-title">الأنظمة واللوائح</h2>
      </div>
      <div id="regulationDetail" style="display:none;margin-bottom:1.5rem">
        <button class="btn btn-outline btn-sm" onclick="closeDetail('regulationDetail');loadRegulations()" style="color:var(--navy);border-color:var(--border);background:white;margin-bottom:1rem">← رجوع</button>
        <div class="detail-panel" id="regulationDetailContent"></div>
      </div>
      <div id="regulationsList">
        <div class="cards-grid" id="regulationsGrid"><div class="loading"><div class="spinner"></div>جارٍ التحميل...</div></div>
        <div class="pagination" id="regulationsPagination"></div>
      </div>
    </div>

    <!-- ═══ PRINCIPLES ═══ -->
    <div class="page" id="page-principles">
      <div class="section-header">
        <h2 class="section-title">المبادئ القضائية</h2>
        <div style="display:flex;gap:8px">
          <input type="text" id="principleSubject" placeholder="تصفية حسب الموضوع" style="padding:7px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal',sans-serif;font-size:13px;outline:none">
          <button class="btn btn-primary btn-sm" onclick="loadPrinciples()">تصفية</button>
        </div>
      </div>
      <div id="principlesGrid"><div class="loading"><div class="spinner"></div>جارٍ التحميل...</div></div>
    </div>

    <!-- ═══ MEMO ═══ -->
    <div class="page" id="page-memo">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">مساعد صياغة المذكرات القضائية</h2>
      </div>
      <div class="notice">⚠️ <span>هذا المساعد يولّد مسودات أولية فقط. يجب مراجعة كل مذكرة من قِبَل محامٍ متخصص قبل استخدامها.</span></div>
      <div class="memo-layout">
        <div class="memo-form">
          <div class="form-group">
            <label>نوع المذكرة</label>
            <select id="memoType">
              <option value="لائحة دعوى">لائحة دعوى</option>
              <option value="مذكرة جوابية">مذكرة جوابية</option>
              <option value="مذكرة اعتراض">مذكرة اعتراض</option>
              <option value="لائحة استئناف">لائحة استئناف</option>
              <option value="التماس إعادة نظر">التماس إعادة نظر</option>
              <option value="مذكرة قانونية مختصرة">مذكرة قانونية مختصرة</option>
            </select>
          </div>
          <div class="form-group">
            <label>وقائع القضية</label>
            <textarea id="memoFacts" rows="8" placeholder="اكتب وقائع القضية بالتفصيل: الأطراف، موضوع النزاع، التواريخ، المطالبات..."></textarea>
          </div>
          <div class="form-group">
            <label>الأساس القانوني (اختياري)</label>
            <textarea id="memoLegal" rows="3" placeholder="مثال: نظام التجارة، نظام العمل، نظام الأحوال الشخصية..."></textarea>
          </div>
          <button class="btn btn-gold" style="width:100%;justify-content:center" onclick="draftMemo()" id="memoBtn">✍️ توليد المذكرة</button>
        </div>
        <div class="memo-output">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">
            <strong style="font-size:14px;color:var(--navy)">المسودة</strong>
            <div style="display:flex;gap:8px">
              <button class="btn btn-primary btn-sm" onclick="copyMemo()">نسخ</button>
            </div>
          </div>
          <div class="memo-text" id="memoOutput">ستظهر المسودة هنا بعد الإنشاء...</div>
        </div>
      </div>
    </div>

    <!-- ═══ JUDICIAL MAP ═══ -->
    <div class="page" id="page-map">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">خريطة القضاء السعودي</h2>
      </div>
      <div class="jmap">
        <div class="jmap-card">
          <h3>🏛️ أنواع المحاكم</h3>
          <ul>
            <li>المحكمة العليا – أعلى سلطة قضائية</li>
            <li>محاكم الاستئناف – الدرجة الثانية</li>
            <li>المحاكم العامة – القضايا المدنية والجنائية</li>
            <li>المحاكم التجارية – النزاعات التجارية</li>
            <li>المحاكم العمالية – نزاعات العمل</li>
            <li>المحاكم الجزائية – القضايا الجنائية</li>
            <li>محاكم الأحوال الشخصية – شؤون الأسرة</li>
            <li>ديوان المظالم – القضاء الإداري</li>
          </ul>
        </div>
        <div class="jmap-card">
          <h3>📈 درجات التقاضي</h3>
          <ul>
            <li><strong>الدرجة الأولى:</strong> المحاكم الابتدائية – النظر الأول في القضية</li>
            <li><strong>الدرجة الثانية:</strong> محاكم الاستئناف – مراجعة أحكام الدرجة الأولى</li>
            <li><strong>الدرجة العليا:</strong> المحكمة العليا – مراقبة تطبيق الأنظمة</li>
            <li><strong>المراجعة الإدارية:</strong> ديوان المظالم للقرارات الحكومية</li>
          </ul>
        </div>
        <div class="jmap-card">
          <h3>⏱️ مدد الاعتراض</h3>
          <ul>
            <li>الاعتراض على الحكم الابتدائي: 30 يوماً من تاريخ التبليغ</li>
            <li>الطعن أمام محكمة الاستئناف: 30 يوماً من صدور الحكم</li>
            <li>الالتماس بإعادة النظر: 60 يوماً من اكتساب الحكم القطعية</li>
            <li>التظلم الإداري: 60 يوماً من تاريخ العلم بالقرار</li>
          </ul>
        </div>
        <div class="jmap-card">
          <h3>📋 الاختصاص النوعي</h3>
          <ul>
            <li>المحاكم التجارية: عقود تجارية، إفلاس، شركات</li>
            <li>المحاكم العمالية: عقود عمل، فصل تعسفي، مكافآت</li>
            <li>ديوان المظالم: طعون إدارية، عقود حكومية</li>
            <li>محاكم الأحوال: زواج، طلاق، نفقة، ولاية</li>
            <li>المحاكم الجزائية: جرائم وعقوبات تعزيرية</li>
          </ul>
        </div>
        <div class="jmap-card">
          <h3>📚 المصادر الرسمية</h3>
          <ul>
            <li><a href="https://www.moj.gov.sa" target="_blank" style="color:var(--gold)">وزارة العدل السعودية</a></li>
            <li><a href="https://najiz.sa" target="_blank" style="color:var(--gold)">منصة ناجز للخدمات العدلية</a></li>
            <li><a href="https://www.scj.gov.sa" target="_blank" style="color:var(--gold)">المجلس الأعلى للقضاء</a></li>
            <li><a href="https://laws.boe.gov.sa" target="_blank" style="color:var(--gold)">هيئة الخبراء – الأنظمة</a></li>
            <li><a href="https://uqn.gov.sa" target="_blank" style="color:var(--gold)">أم القرى – الجريدة الرسمية</a></li>
          </ul>
        </div>
        <div class="jmap-card">
          <h3>⚡ إجراءات التقاضي الأساسية</h3>
          <ul>
            <li>تقديم لائحة الدعوى عبر منصة ناجز</li>
            <li>تحديد موعد الجلسة وتبليغ الأطراف</li>
            <li>تبادل المذكرات والمستندات</li>
            <li>المرافعة وسماع الشهود</li>
            <li>إصدار الحكم والتبليغ به</li>
            <li>التنفيذ عبر المحكمة المختصة</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- ═══ QA ═══ -->
    <div class="page" id="page-qa">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">المساعد القانوني الذكي</h2>
      </div>
      <div class="qa-container">
        <div class="notice">🤖 <span>يجيب المساعد بناءً على قاعدة بيانات المنصة فقط. إذا لم تُضَف أحكام أو أنظمة، ستكون الإجابات محدودة.</span></div>
        <div class="chat-messages" id="chatMessages">
          <div class="msg msg-ai">
            <div class="bubble">مرحباً! أنا المساعد القانوني للمرصد القضائي السعودي. يمكنني الإجابة على أسئلتك القانونية بناءً على الأحكام والأنظمة المتاحة في قاعدة البيانات. كيف يمكنني مساعدتك؟</div>
          </div>
        </div>
        <div style="display:flex;gap:10px">
          <input type="text" id="qaInput" placeholder="اكتب سؤالك القانوني هنا..." style="flex:1;padding:11px 16px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal',sans-serif;font-size:14px;outline:none" onkeydown="if(event.key==='Enter')sendQA()">
          <button class="btn btn-gold" onclick="sendQA()" id="qaBtn">إرسال</button>
        </div>
      </div>
    </div>

    <!-- ═══ ANALYTICS ═══ -->
    <div class="page" id="page-analytics">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">التحليلات والإحصاءات</h2>
      </div>
      <div id="analyticsContent"><div class="loading"><div class="spinner"></div>جارٍ التحميل...</div></div>
    </div>

    <!-- ═══ ADMIN ═══ -->
    <div class="page" id="page-admin">
      <div class="section-header" style="margin-bottom:1.5rem">
        <h2 class="section-title">لوحة تحكم المدير</h2>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:1.5rem">
        <button class="btn btn-gold" onclick="openAddJudgment()">+ إضافة حكم</button>
        <button class="btn btn-primary" onclick="openAddRegulation()">+ إضافة نظام</button>
        <button class="btn btn-primary" onclick="openAddPrinciple()">+ إضافة مبدأ</button>
        <button class="btn btn-outline btn-sm" onclick="loadAdminData()" style="color:var(--navy);border-color:var(--border);background:white">↻ تحديث</button>
      </div>

      <div class="admin-grid" id="adminStats">
        <div class="admin-card"><div class="big-num">—</div><div class="label">إجمالي الأحكام</div></div>
        <div class="admin-card"><div class="big-num">—</div><div class="label">الأنظمة واللوائح</div></div>
        <div class="admin-card"><div class="big-num">—</div><div class="label">المبادئ القضائية</div></div>
      </div>

      <div class="section-header" style="margin-bottom:1rem">
        <h2 class="section-title" style="font-size:16px">جميع الأحكام</h2>
      </div>
      <div style="overflow-x:auto">
        <table class="admin-table" id="adminJudgmentsTable">
          <thead><tr><th>العنوان</th><th>المحكمة</th><th>نوع القضية</th><th>الحالة</th><th>التاريخ</th><th>إجراءات</th></tr></thead>
          <tbody id="adminJudgmentsBody"><tr><td colspan="6" class="loading" style="text-align:center">جارٍ التحميل...</td></tr></tbody>
        </table>
      </div>

      <div class="section-header" style="margin-bottom:1rem;margin-top:2rem">
        <h2 class="section-title" style="font-size:16px">سجل التدقيق</h2>
      </div>
      <div style="overflow-x:auto">
        <table class="admin-table" id="auditTable">
          <thead><tr><th>الإجراء</th><th>النوع</th><th>التفاصيل</th><th>الوقت</th></tr></thead>
          <tbody id="auditBody"></tbody>
        </table>
      </div>
    </div>

  </main>
</div>

<!-- ─── Modal: Add Judgment ─── -->
<div class="modal-overlay" id="modalJudgment">
  <div class="modal">
    <div class="modal-header">
      <h3>إضافة / تعديل حكم قضائي</h3>
      <button class="modal-close" onclick="closeModal('modalJudgment')">✕</button>
    </div>
    <div class="modal-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div class="form-group" style="grid-column:1/-1"><label>عنوان الحكم *</label><input type="text" id="jTitle" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="عنوان الحكم"></div>
        <div class="form-group"><label>المحكمة</label><input type="text" id="jCourt" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="اسم المحكمة"></div>
        <div class="form-group"><label>نوع القضية</label><select id="jType" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;background:var(--cream)"><option>تجارية</option><option>عمالية</option><option>مدنية</option><option>جزائية</option><option>إدارية</option><option>أحوال شخصية</option><option>أخرى</option></select></div>
        <div class="form-group"><label>رقم القضية</label><input type="text" id="jNumber" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="رقم القضية"></div>
        <div class="form-group"><label>تاريخ الحكم</label><input type="text" id="jDate" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="مثال: 1445/05/10هـ"></div>
        <div class="form-group" style="grid-column:1/-1">
          <label>رفع ملف (PDF / Word)</label>
          <div class="upload-zone" onclick="document.getElementById('jFile').click()">
            📎 اضغط لرفع الملف أو اسحبه هنا<br>
            <span style="font-size:12px;color:var(--text-light)" id="jFileName">PDF, DOC, DOCX</span>
          </div>
          <input type="file" id="jFile" style="display:none" accept=".pdf,.doc,.docx,.txt" onchange="handleFileUpload('jFile','jFileName','jFullText')">
        </div>
        <div class="form-group" style="grid-column:1/-1"><label>النص الكامل للحكم</label><textarea id="jFullText" rows="6" placeholder="أو أدخل النص مباشرة..." style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group" style="grid-column:1/-1;display:flex;justify-content:flex-end"><button class="btn btn-primary btn-sm" onclick="analyzeWithAI()" id="aiAnalyzeBtn">🤖 تحليل بالذكاء الاصطناعي</button></div>
        <div class="form-group" style="grid-column:1/-1"><label>الوقائع</label><textarea id="jFacts" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group"><label>المنطوق</label><textarea id="jVerdict" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group"><label>الملخص</label><textarea id="jSummary" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group"><label>المبادئ القضائية</label><textarea id="jPrinciples" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group"><label>النصوص النظامية المستند إليها</label><textarea id="jRelatedLaws" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
        <div class="form-group"><label>رابط المصدر الرسمي</label><input type="text" id="jSourceUrl" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="https://..."></div>
        <div class="form-group"><label>اسم المصدر</label><input type="text" id="jSourceName" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="مثال: وزارة العدل"></div>
        <div class="form-group"><label>الحالة</label><select id="jStatus" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;background:var(--cream)"><option value="draft">مسودة</option><option value="review">قيد المراجعة</option><option value="published">منشور</option></select></div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline btn-sm" onclick="closeModal('modalJudgment')" style="color:var(--text-muted);border-color:var(--border)">إلغاء</button>
      <button class="btn btn-gold" onclick="saveJudgment()">💾 حفظ الحكم</button>
    </div>
  </div>
</div>

<!-- ─── Modal: Add Regulation ─── -->
<div class="modal-overlay" id="modalRegulation">
  <div class="modal">
    <div class="modal-header">
      <h3>إضافة نظام أو لائحة</h3>
      <button class="modal-close" onclick="closeModal('modalRegulation')">✕</button>
    </div>
    <div class="modal-body">
      <div class="form-group"><label>عنوان النظام *</label><input type="text" id="rTitle" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="اسم النظام أو اللائحة"></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div class="form-group"><label>التصنيف</label><select id="rCategory" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;background:var(--cream)"><option>نظام</option><option>لائحة تنفيذية</option><option>قرار وزاري</option><option>مرسوم ملكي</option><option>تعميم</option></select></div>
        <div class="form-group"><label>جهة الإصدار</label><input type="text" id="rAuthority" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="مثال: هيئة الخبراء"></div>
        <div class="form-group"><label>تاريخ الإصدار</label><input type="text" id="rDate" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)"></div>
        <div class="form-group"><label>رابط المصدر الرسمي</label><input type="text" id="rSourceUrl" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="https://laws.boe.gov.sa/..."></div>
      </div>
      <div class="form-group"><label>ملخص النظام</label><textarea id="rSummary" rows="4" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
      <div class="form-group"><label>النص الكامل</label><textarea id="rFullText" rows="8" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:13px;resize:vertical;outline:none;background:var(--cream)"></textarea></div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline btn-sm" onclick="closeModal('modalRegulation')" style="color:var(--text-muted);border-color:var(--border)">إلغاء</button>
      <button class="btn btn-gold" onclick="saveRegulation()">💾 حفظ النظام</button>
    </div>
  </div>
</div>

<!-- ─── Modal: Add Principle ─── -->
<div class="modal-overlay" id="modalPrinciple">
  <div class="modal">
    <div class="modal-header">
      <h3>إضافة مبدأ قضائي</h3>
      <button class="modal-close" onclick="closeModal('modalPrinciple')">✕</button>
    </div>
    <div class="modal-body">
      <div class="form-group"><label>نص المبدأ *</label><textarea id="pText" rows="5" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;resize:vertical;outline:none;background:var(--cream)" placeholder="اكتب نص المبدأ القضائي..."></textarea></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">
        <div class="form-group"><label>الموضوع</label><input type="text" id="pSubject" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="مثال: العقود، التجارة..."></div>
        <div class="form-group"><label>المصدر</label><input type="text" id="pSource" style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius);font-family:'Tajawal';font-size:14px;outline:none;background:var(--cream)" placeholder="الحكم أو القرار المصدر"></div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-outline btn-sm" onclick="closeModal('modalPrinciple')" style="color:var(--text-muted);border-color:var(--border)">إلغاء</button>
      <button class="btn btn-gold" onclick="savePrinciple()">💾 حفظ المبدأ</button>
    </div>
  </div>
</div>

<script>
// ─── State ────────────────────────────────────────────────────────────────────
let currentUser = null;
let editingJudgmentId = null;
let jCurrentPage = 1, rCurrentPage = 1;

// ─── Init ─────────────────────────────────────────────────────────────────────
window.onload = async () => {
  const res = await api('/api/auth/me');
  if (!res.logged_in) {
    document.getElementById('loginOverlay').classList.add('open');
  } else {
    currentUser = res;
    onLoggedIn();
  }
};

function onLoggedIn() {
  document.getElementById('loginOverlay').classList.remove('open');
  document.getElementById('userLabel').textContent = currentUser.username;
  if (currentUser.is_admin) {
    document.getElementById('adminBtn').style.display = '';
    document.getElementById('adminSideItem').style.display = '';
  }
  loadHomeStats();
  loadHomeJudgments();
}

// ─── API Helper ───────────────────────────────────────────────────────────────
async function api(url, method='GET', body=null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  return r.json();
}

// ─── Auth ─────────────────────────────────────────────────────────────────────
async function doLogin() {
  const username = document.getElementById('loginUser').value;
  const password = document.getElementById('loginPass').value;
  const res = await api('/api/auth/login', 'POST', { username, password });
  if (res.success) {
    currentUser = res;
    onLoggedIn();
  } else {
    const el = document.getElementById('loginError');
    el.style.display = '';
    el.textContent = res.error || 'خطأ في الدخول';
  }
}

async function doLogout() {
  await api('/api/auth/logout', 'POST');
  location.reload();
}

// ─── Navigation ───────────────────────────────────────────────────────────────
function navigate(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.sidebar-item').forEach(b => b.classList.remove('active'));
  document.getElementById('page-' + page)?.classList.add('active');

  if (page === 'judgments') loadJudgments();
  if (page === 'regulations') loadRegulations();
  if (page === 'principles') loadPrinciples();
  if (page === 'admin') loadAdminData();
  if (page === 'analytics') loadAnalytics();
}

// ─── Home ─────────────────────────────────────────────────────────────────────
async function loadHomeStats() {
  const r = await api('/api/admin/stats');
  if (r.totals) {
    document.getElementById('sJudgments').textContent = r.totals.published_judgments || 0;
    document.getElementById('sRegs').textContent = r.totals.regulations || 0;
    document.getElementById('sPrincs').textContent = r.totals.principles || 0;
    document.getElementById('sUsers').textContent = r.totals.users || 0;
  }
}

async function loadHomeJudgments() {
  const r = await api('/api/judgments?page=1');
  const el = document.getElementById('homeJudgments');
  if (!r.judgments || !r.judgments.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>لا توجد أحكام منشورة بعد</p></div>';
    return;
  }
  el.innerHTML = r.judgments.slice(0, 6).map(j => renderJudgmentCard(j)).join('');
}

// ─── Quick Search ─────────────────────────────────────────────────────────────
function quickSearch() {
  const q = document.getElementById('heroSearch').value;
  document.getElementById('searchQ').value = q;
  navigate('search');
  doSearch();
}

// ─── Search ───────────────────────────────────────────────────────────────────
async function doSearch() {
  const q = document.getElementById('searchQ').value;
  const resource = document.getElementById('searchResource').value;
  const court = document.getElementById('searchCourt').value;
  const type = document.getElementById('searchType').value;
  const el = document.getElementById('searchResults');
  el.innerHTML = '<div class="loading"><div class="spinner"></div>جارٍ البحث...</div>';
  const r = await api(`/api/search?q=${encodeURIComponent(q)}&resource=${resource}&court=${encodeURIComponent(court)}&type=${encodeURIComponent(type)}`);
  if (!r.results || !r.results.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">🔍</div><p>لا توجد نتائج مطابقة</p></div>';
    return;
  }
  el.innerHTML = `<p style="font-size:13px;color:var(--text-muted);margin-bottom:1rem">وُجد ${r.results.length} نتيجة</p><div class="cards-grid">${r.results.map(item => {
    if (item.type === 'judgment') return renderJudgmentCard(item);
    if (item.type === 'regulation') return renderRegulationCard(item);
    if (item.type === 'principle') return renderPrincipleCard(item);
    return '';
  }).join('')}</div>`;
}

// ─── Judgments ────────────────────────────────────────────────────────────────
async function loadJudgments(page=1) {
  jCurrentPage = page;
  const r = await api(`/api/judgments?page=${page}`);
  const grid = document.getElementById('judgmentsGrid');
  if (!r.judgments || !r.judgments.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="icon">📋</div><p>لا توجد أحكام منشورة</p></div>';
  } else {
    grid.innerHTML = r.judgments.map(j => renderJudgmentCard(j)).join('');
  }
  renderPagination('judgmentsPagination', r.pages, page, loadJudgments);
}

function renderJudgmentCard(j) {
  return `<div class="card" onclick="openJudgment('${j.id}')">
    <span class="card-type type-judgment">حكم قضائي</span>
    <div class="card-title">${j.title || 'بدون عنوان'}</div>
    <div class="card-meta">
      ${j.court ? `<span>🏛️ ${j.court}</span>` : ''}
      ${j.case_type ? `<span>📁 ${j.case_type}</span>` : ''}
      ${j.date ? `<span>📅 ${j.date}</span>` : ''}
    </div>
    ${j.summary ? `<div class="card-summary">${j.summary}</div>` : ''}
  </div>`;
}

async function openJudgment(id) {
  document.getElementById('judgmentsList').style.display = 'none';
  document.getElementById('judgmentDetail').style.display = 'block';
  document.getElementById('judgmentDetailContent').innerHTML = '<div class="loading" style="padding:3rem"><div class="spinner"></div>جارٍ التحميل...</div>';
  const j = await api(`/api/judgments/${id}`);
  document.getElementById('judgmentDetailContent').innerHTML = `
    <div class="detail-header">
      <h2>${j.title || 'بدون عنوان'}</h2>
      <div class="detail-meta">
        ${j.court ? `<span>🏛️ ${j.court}</span>` : ''}
        ${j.case_type ? `<span>📁 ${j.case_type}</span>` : ''}
        ${j.case_number ? `<span>🔢 ${j.case_number}</span>` : ''}
        ${j.date ? `<span>📅 ${j.date}</span>` : ''}
        ${j.status === 'published' ? '<span style="color:#86efac">✓ منشور</span>' : ''}
      </div>
      ${j.source_name ? `<div style="font-size:12px;color:#B0BDD0;margin-top:8px">المصدر: ${j.source_name}${j.source_url ? ` • <a href="${j.source_url}" target="_blank" style="color:var(--gold-light)">رابط المصدر</a>` : ''}</div>` : ''}
    </div>
    <div class="detail-body">
      ${j.summary ? `<div class="detail-section"><h3>الملخص</h3><div class="detail-text">${j.summary}</div></div>` : ''}
      <div class="detail-tabs">
        <button class="tab-btn active" onclick="switchTab(this,'tab-facts')">الوقائع والطلبات</button>
        <button class="tab-btn" onclick="switchTab(this,'tab-verdict')">الأسباب والمنطوق</button>
        <button class="tab-btn" onclick="switchTab(this,'tab-principles')">المبادئ والأنظمة</button>
        ${j.full_text ? '<button class="tab-btn" onclick="switchTab(this,\'tab-full\')">النص الكامل</button>' : ''}
      </div>
      <div class="tab-content active" id="tab-facts">
        ${j.facts ? `<div class="detail-section"><h3>الوقائع</h3><div class="detail-text">${j.facts}</div></div>` : ''}
        ${j.requests ? `<div class="detail-section"><h3>طلبات الأطراف</h3><div class="detail-text">${j.requests}</div></div>` : ''}
        ${j.defenses ? `<div class="detail-section"><h3>الدفوع</h3><div class="detail-text">${j.defenses}</div></div>` : ''}
      </div>
      <div class="tab-content" id="tab-verdict">
        ${j.reasons ? `<div class="detail-section"><h3>الأسباب</h3><div class="detail-text">${j.reasons}</div></div>` : ''}
        ${j.verdict ? `<div class="detail-section"><h3>المنطوق</h3><div class="detail-text" style="font-weight:600">${j.verdict}</div></div>` : ''}
      </div>
      <div class="tab-content" id="tab-principles">
        ${j.principles ? `<div class="detail-section"><h3>المبادئ القضائية</h3>${j.principles.split('\n').filter(Boolean).map(p => `<div class="principle-item">${p}</div>`).join('')}</div>` : ''}
        ${j.related_laws ? `<div class="detail-section"><h3>النصوص النظامية المستند إليها</h3><div class="detail-text">${j.related_laws}</div></div>` : ''}
        ${j.extracted_principles?.length ? `<div class="detail-section"><h3>مبادئ مستخرجة بالذكاء الاصطناعي</h3>${j.extracted_principles.map(p => `<div class="principle-item">${p.text} <span style="font-size:11px;color:var(--text-light)">(${p.subject||''})</span></div>`).join('')}</div>` : ''}
      </div>
      ${j.full_text ? `<div class="tab-content" id="tab-full"><div class="detail-section"><h3>النص الكامل</h3><div class="detail-text" style="font-size:13px">${j.full_text}</div></div></div>` : ''}
    </div>`;
}

function closeDetail(id) {
  document.getElementById(id).style.display = 'none';
  document.getElementById('judgmentsList').style.display = '';
  document.getElementById('regulationsList').style.display = '';
}

function switchTab(btn, tabId) {
  const parent = btn.closest('.detail-body');
  parent.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  parent.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(tabId)?.classList.add('active');
}

// ─── Regulations ──────────────────────────────────────────────────────────────
async function loadRegulations(page=1) {
  rCurrentPage = page;
  const r = await api(`/api/regulations?page=${page}`);
  const grid = document.getElementById('regulationsGrid');
  if (!r.regulations || !r.regulations.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="icon">📜</div><p>لا توجد أنظمة مضافة</p></div>';
  } else {
    grid.innerHTML = r.regulations.map(reg => renderRegulationCard(reg)).join('');
  }
  renderPagination('regulationsPagination', r.pages, page, loadRegulations);
}

function renderRegulationCard(r) {
  return `<div class="card" onclick="openRegulation('${r.id}')">
    <span class="card-type type-regulation">${r.category || 'نظام'}</span>
    <div class="card-title">${r.title || 'بدون عنوان'}</div>
    <div class="card-meta">
      ${r.date ? `<span>📅 ${r.date}</span>` : ''}
      ${r.source_name ? `<span>📌 ${r.source_name}</span>` : ''}
    </div>
    ${r.summary ? `<div class="card-summary">${r.summary}</div>` : ''}
  </div>`;
}

async function openRegulation(id) {
  document.getElementById('regulationsList').style.display = 'none';
  document.getElementById('regulationDetail').style.display = 'block';
  document.getElementById('regulationDetailContent').innerHTML = '<div class="loading" style="padding:3rem"><div class="spinner"></div>جارٍ التحميل...</div>';
  const r = await api(`/api/regulations/${id}`);
  document.getElementById('regulationDetailContent').innerHTML = `
    <div class="detail-header">
      <h2>${r.title}</h2>
      <div class="detail-meta">
        ${r.category ? `<span>📁 ${r.category}</span>` : ''}
        ${r.date ? `<span>📅 ${r.date}</span>` : ''}
        ${r.issuing_authority ? `<span>🏛️ ${r.issuing_authority}</span>` : ''}
      </div>
      ${r.source_name ? `<div style="font-size:12px;color:#B0BDD0;margin-top:8px">المصدر: ${r.source_name}${r.source_url ? ` • <a href="${r.source_url}" target="_blank" style="color:var(--gold-light)">رابط المصدر</a>` : ''}</div>` : ''}
    </div>
    <div class="detail-body">
      ${r.summary ? `<div class="detail-section"><h3>الملخص</h3><div class="detail-text">${r.summary}</div></div>` : ''}
      ${r.full_text ? `<div class="detail-section"><h3>النص الكامل</h3><div class="detail-text" style="font-size:13px">${r.full_text}</div></div>` : ''}
    </div>`;
}

// ─── Principles ───────────────────────────────────────────────────────────────
async function loadPrinciples() {
  const subject = document.getElementById('principleSubject')?.value || '';
  const r = await api(`/api/principles?subject=${encodeURIComponent(subject)}`);
  const el = document.getElementById('principlesGrid');
  if (!r.principles || !r.principles.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">⚖️</div><p>لا توجد مبادئ مضافة</p></div>';
    return;
  }
  el.innerHTML = `<div style="display:flex;flex-direction:column;gap:0.75rem">${r.principles.map(p => renderPrincipleCard(p)).join('')}</div>`;
}

function renderPrincipleCard(p) {
  return `<div class="principle-item" style="cursor:default">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem">
      <div>${p.text || ''}</div>
      <div style="flex-shrink:0">
        ${p.subject ? `<span class="card-type type-principle" style="margin:0">${p.subject}</span>` : ''}
      </div>
    </div>
    ${p.source ? `<div style="font-size:12px;color:var(--text-light);margin-top:6px">المصدر: ${p.source}</div>` : ''}
  </div>`;
}

// ─── Pagination ───────────────────────────────────────────────────────────────
function renderPagination(containerId, pages, current, fn) {
  if (!pages || pages <= 1) { document.getElementById(containerId).innerHTML = ''; return; }
  let html = '';
  for (let i=1; i<=pages; i++) {
    html += `<button class="page-btn ${i===current?'active':''}" onclick="${fn.name}(${i})">${i}</button>`;
  }
  document.getElementById(containerId).innerHTML = html;
}

// ─── Memo ─────────────────────────────────────────────────────────────────────
async function draftMemo() {
  const btn = document.getElementById('memoBtn');
  btn.disabled = true; btn.textContent = '⏳ جارٍ الإنشاء...';
  const facts = document.getElementById('memoFacts').value;
  const type = document.getElementById('memoType').value;
  const legal = document.getElementById('memoLegal').value;
  if (!facts.trim()) { showToast('يرجى إدخال وقائع القضية', 'error'); btn.disabled=false; btn.textContent='✍️ توليد المذكرة'; return; }
  const r = await api('/api/ai/draft-memo', 'POST', { facts, type, legal_basis: legal });
  document.getElementById('memoOutput').textContent = r.draft || r.error || 'خطأ في الإنشاء';
  btn.disabled = false; btn.textContent = '✍️ توليد المذكرة';
}

function copyMemo() {
  const text = document.getElementById('memoOutput').textContent;
  navigator.clipboard.writeText(text).then(() => showToast('تم نسخ المذكرة', 'success'));
}

// ─── QA ───────────────────────────────────────────────────────────────────────
async function sendQA() {
  const input = document.getElementById('qaInput');
  const btn = document.getElementById('qaBtn');
  const q = input.value.trim();
  if (!q) return;
  const msgs = document.getElementById('chatMessages');
  msgs.innerHTML += `<div class="msg msg-user"><div class="bubble">${q}</div></div>`;
  input.value = '';
  btn.disabled = true;
  msgs.innerHTML += `<div class="msg msg-ai" id="aiThinking"><div class="bubble">⏳ جارٍ التحليل...</div></div>`;
  msgs.scrollTop = msgs.scrollHeight;
  const r = await api('/api/ai/qa', 'POST', { question: q });
  document.getElementById('aiThinking').outerHTML = `<div class="msg msg-ai">
    <div class="bubble">${r.answer || 'عذراً، حدث خطأ'}</div>
    ${r.sources?.length ? `<div class="msg-sources">${r.sources.map(s => `<span class="source-chip" onclick="openSource('${s.type}','${s.id}')">${s.title}</span>`).join('')}</div>` : ''}
  </div>`;
  btn.disabled = false;
  msgs.scrollTop = msgs.scrollHeight;
}

function openSource(type, id) {
  if (type === 'judgment') { navigate('judgments'); openJudgment(id); }
  if (type === 'regulation') { navigate('regulations'); openRegulation(id); }
}

// ─── Analytics ────────────────────────────────────────────────────────────────
async function loadAnalytics() {
  const r = await api('/api/admin/stats');
  const el = document.getElementById('analyticsContent');
  if (!r.totals) { el.innerHTML = '<div class="empty-state"><div class="icon">📊</div><p>لا توجد بيانات</p></div>'; return; }

  const maxC = Math.max(...r.by_court.map(c=>c.count), 1);
  const maxT = Math.max(...r.by_type.map(t=>t.count), 1);

  el.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem">
      <div class="chart-box">
        <div class="section-header" style="margin-bottom:0.5rem"><h2 class="section-title" style="font-size:15px">الأحكام حسب المحكمة</h2></div>
        <div class="chart-bars">
          ${r.by_court.map(c => `<div class="bar-row"><div class="bar-label">${c.court}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.round(c.count/maxC*100)}%"><span class="bar-num">${c.count}</span></div></div></div>`).join('') || '<p style="color:var(--text-light);font-size:13px;padding:1rem">لا توجد بيانات</p>'}
        </div>
      </div>
      <div class="chart-box">
        <div class="section-header" style="margin-bottom:0.5rem"><h2 class="section-title" style="font-size:15px">الأحكام حسب النوع</h2></div>
        <div class="chart-bars">
          ${r.by_type.map(t => `<div class="bar-row"><div class="bar-label">${t.type}</div><div class="bar-track"><div class="bar-fill" style="width:${Math.round(t.count/maxT*100)}%"><span class="bar-num">${t.count}</span></div></div></div>`).join('') || '<p style="color:var(--text-light);font-size:13px;padding:1rem">لا توجد بيانات</p>'}
        </div>
      </div>
    </div>`;
}

// ─── Admin ────────────────────────────────────────────────────────────────────
async function loadAdminData() {
  const stats = await api('/api/admin/stats');
  if (stats.totals) {
    const cells = document.querySelectorAll('#adminStats .big-num');
    if (cells[0]) cells[0].textContent = stats.totals.judgments;
    if (cells[1]) cells[1].textContent = stats.totals.regulations;
    if (cells[2]) cells[2].textContent = stats.totals.principles;
    const tbody = document.getElementById('auditBody');
    tbody.innerHTML = stats.recent_logs.map(l =>
      `<tr><td><span class="status-badge ${l.action==='delete'?'status-draft':l.action==='create'?'status-published':'status-review'}">${l.action}</span></td><td>${l.resource_type}</td><td>${l.details||''}</td><td style="direction:ltr;font-size:12px">${new Date(l.timestamp).toLocaleString('ar-SA')}</td></tr>`
    ).join('');
  }
  const jres = await api('/api/admin/all-judgments');
  if (jres.judgments) {
    document.getElementById('adminJudgmentsBody').innerHTML = jres.judgments.map(j =>
      `<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${j.title}</td><td>${j.court||'—'}</td><td>${j.case_type||'—'}</td><td><span class="status-badge status-${j.status}">${{draft:'مسودة',review:'مراجعة',published:'منشور'}[j.status]||j.status}</span></td><td style="font-size:12px">${new Date(j.created_at).toLocaleDateString('ar-SA')}</td><td><button class="btn btn-danger btn-sm" onclick="deleteJudgment('${j.id}')">حذف</button></td></tr>`
    ).join('');
  }
}

async function deleteJudgment(id) {
  if (!confirm('هل تريد حذف هذا الحكم؟')) return;
  const r = await api(`/api/admin/judgments/${id}`, 'DELETE');
  if (r.success) { showToast('تم حذف الحكم', 'success'); loadAdminData(); }
  else showToast('خطأ في الحذف', 'error');
}

// ─── Add Judgment ─────────────────────────────────────────────────────────────
function openAddJudgment() {
  editingJudgmentId = null;
  ['jTitle','jCourt','jNumber','jDate','jFullText','jFacts','jVerdict','jSummary','jPrinciples','jRelatedLaws','jSourceUrl','jSourceName'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('modalJudgment').classList.add('open');
}

async function handleFileUpload(fileInputId, fileNameId, textAreaId) {
  const file = document.getElementById(fileInputId).files[0];
  if (!file) return;
  document.getElementById(fileNameId).textContent = file.name + ' — جارٍ الرفع...';
  const formData = new FormData();
  formData.append('file', file);
  const r = await fetch('/api/admin/upload', { method: 'POST', body: formData });
  const res = await r.json();
  if (res.success) {
    document.getElementById(fileNameId).textContent = file.name + ' ✓';
    if (res.extracted_text) document.getElementById(textAreaId).value = res.extracted_text;
    showToast('تم رفع الملف بنجاح', 'success');
  } else {
    showToast(res.error || 'خطأ في الرفع', 'error');
  }
}

async function analyzeWithAI() {
  const text = document.getElementById('jFullText').value;
  if (!text) { showToast('يرجى إدخال النص أولاً', 'error'); return; }
  const btn = document.getElementById('aiAnalyzeBtn');
  btn.disabled = true; btn.textContent = '⏳ جارٍ التحليل...';
  const r = await api('/api/ai/analyze-judgment', 'POST', { text });
  if (r.success && r.data) {
    const d = r.data;
    if (d.facts) document.getElementById('jFacts').value = d.facts;
    if (d.verdict) document.getElementById('jVerdict').value = d.verdict;
    if (d.summary) document.getElementById('jSummary').value = d.summary;
    if (d.principles) document.getElementById('jPrinciples').value = d.principles;
    if (d.related_laws) document.getElementById('jRelatedLaws').value = d.related_laws;
    showToast('تم التحليل بنجاح', 'success');
  } else {
    showToast(r.error || 'خطأ في التحليل', 'error');
  }
  btn.disabled = false; btn.textContent = '🤖 تحليل بالذكاء الاصطناعي';
}

async function saveJudgment() {
  const data = {
    title: document.getElementById('jTitle').value,
    court: document.getElementById('jCourt').value,
    case_type: document.getElementById('jType').value,
    case_number: document.getElementById('jNumber').value,
    judgment_date: document.getElementById('jDate').value,
    full_text: document.getElementById('jFullText').value,
    facts: document.getElementById('jFacts').value,
    verdict: document.getElementById('jVerdict').value,
    summary: document.getElementById('jSummary').value,
    principles: document.getElementById('jPrinciples').value,
    related_laws: document.getElementById('jRelatedLaws').value,
    source_url: document.getElementById('jSourceUrl').value,
    source_name: document.getElementById('jSourceName').value,
    status: document.getElementById('jStatus').value,
  };
  if (!data.title) { showToast('عنوان الحكم مطلوب', 'error'); return; }
  const url = editingJudgmentId ? `/api/admin/judgments/${editingJudgmentId}` : '/api/admin/judgments';
  const method = editingJudgmentId ? 'PUT' : 'POST';
  const r = await api(url, method, data);
  if (r.success) {
    showToast('تم حفظ الحكم بنجاح', 'success');
    closeModal('modalJudgment');
    loadAdminData();
  } else {
    showToast(r.error || 'خطأ في الحفظ', 'error');
  }
}

// ─── Add Regulation ───────────────────────────────────────────────────────────
function openAddRegulation() {
  document.getElementById('modalRegulation').classList.add('open');
}

async function saveRegulation() {
  const data = {
    title: document.getElementById('rTitle').value,
    category: document.getElementById('rCategory').value,
    issuing_authority: document.getElementById('rAuthority').value,
    issue_date: document.getElementById('rDate').value,
    summary: document.getElementById('rSummary').value,
    full_text: document.getElementById('rFullText').value,
    source_url: document.getElementById('rSourceUrl').value,
    status: 'published',
  };
  if (!data.title) { showToast('عنوان النظام مطلوب', 'error'); return; }
  const r = await api('/api/admin/regulations', 'POST', data);
  if (r.success) { showToast('تم حفظ النظام بنجاح', 'success'); closeModal('modalRegulation'); loadAdminData(); }
  else showToast(r.error || 'خطأ', 'error');
}

// ─── Add Principle ────────────────────────────────────────────────────────────
function openAddPrinciple() {
  document.getElementById('modalPrinciple').classList.add('open');
}

async function savePrinciple() {
  const data = {
    text: document.getElementById('pText').value,
    subject: document.getElementById('pSubject').value,
    source: document.getElementById('pSource').value,
    status: 'published',
  };
  if (!data.text) { showToast('نص المبدأ مطلوب', 'error'); return; }
  const r = await api('/api/admin/principles', 'POST', data);
  if (r.success) { showToast('تم حفظ المبدأ بنجاح', 'success'); closeModal('modalPrinciple'); loadAdminData(); }
  else showToast(r.error || 'خطأ', 'error');
}

// ─── Modal helpers ────────────────────────────────────────────────────────────
function closeModal(id) { document.getElementById(id).classList.remove('open'); }

// ─── Toast ────────────────────────────────────────────────────────────────────
function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast ${type} show`;
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ─── Login Enter ──────────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && document.getElementById('loginOverlay').classList.contains('open')) doLogin();
});
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return HTML_PAGE

@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─── Init DB ──────────────────────────────────────────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=bcrypt.generate_password_hash('admin123').decode('utf-8'),
                is_admin=True
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ تم إنشاء حساب المدير: admin / admin123")

# يُشغَّل عند بدء التطبيق سواء عبر gunicorn أو مباشرة
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
