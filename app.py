import os
import json
import uuid
import hashlib
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
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

@app.route('/')
def index():
    return render_template('index.html')

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

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
