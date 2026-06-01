"""
import_judgments.py — استيراد الأحكام من ملفات PDF إلى قاعدة البيانات
الاستخدام:
  1. ارفع ملفات PDF في نفس مجلد هذا الملف
  2. شغّل: python3 import_judgments.py
"""
import json, re, os, sys

# ── استخراج النصوص ──────────────────────────────────────────────────────────
def clean(t):
    t = re.sub(r'\u0640+', '', t)
    t = re.sub(r'\s+', ' ', t)
    return t.strip()

def extract_judgments_from_pdf(pdf_path, pdf_num):
    try:
        import pypdf
    except ImportError:
        print("pypdf غير مثبت. شغّل: pip install pypdf")
        return []

    reader = pypdf.PdfReader(pdf_path)
    total = len(reader.pages)
    judgments = []
    i = 0

    while i < total:
        raw = reader.pages[i].extract_text() or ''
        page = clean(raw)

        is_header = bool(
            re.search(r'\d{5,12}\s*ر[َ]?ق[ْ]?م[ُ]?\s*الص[َّ]?ك', page) or
            re.search(r'\d{5,12}\s*رقم\s*الصك', page) or
            ('رقم الدعوى' in page and re.search(r'\d{4,12}\s*رقم', page) and i > 20)
        )

        if is_header:
            all_text = page
            i += 1
            for _ in range(20):
                if i >= total: break
                np = clean(reader.pages[i].extract_text() or '')
                if re.search(r'\d{5,12}\s*ر[َ]?ق[ْ]?م[ُ]?\s*الص[َّ]?ك', np) and 'رقم الدعوى' in np:
                    break
                all_text += '\n' + np
                i += 1

            m = re.search(r'(\d{5,12})', page)
            case_num = m.group(1) if m else ''
            dm = re.search(r'(\d{4}/\d{1,2}/\d{1,2})', page)
            date = dm.group(1) + 'هـ' if dm else ''
            sub_lines = [l for l in page.split('\n') if ' - ' in l and len(l) > 20]
            subject = ' | '.join(sub_lines[:2])[:300] if sub_lines else ''
            if not subject:
                for l in page.split('\n')[3:7]:
                    if len(l) > 30 and not l[0].isdigit():
                        subject = l[:200]; break

            vm = re.search(r'(لذلك حكمت|لذا حكم|فلهذا حكم|وبناءً على ما تقدم حكمت)(.*?)(?:وصلى|حرر|وبالله)', all_text, re.DOTALL)
            verdict = vm.group(0)[:500].strip() if vm else ''
            pm = re.search(r'مبادئ وقواعد.*?\n(.*?)(?:ادعى|الحمد لله)', all_text, re.DOTALL)
            principles = pm.group(1)[:400].strip() if pm else ''

            ct = 'مدنية'
            for kw, v in [('بيع','تجارية'),('شركة','تجارية'),('إيجار','تجارية'),
                           ('عمل','عمالية'),('طلاق','أحوال شخصية'),
                           ('جريمة','جزائية'),('عقار','عقارية')]:
                if kw in all_text[:600]: ct = v; break

            if len(all_text) > 200:
                judgments.append({
                    'title': (subject or f'حكم رقم {case_num}')[:150],
                    'case_number': case_num,
                    'judgment_date': date,
                    'court': 'المحكمة العامة',
                    'case_type': ct,
                    'subject': subject[:300],
                    'full_text': all_text[:10000],
                    'verdict': verdict,
                    'principles': principles,
                    'source_name': 'مجموعة الأحكام القضائية - وزارة العدل السعودية',
                    'source_url': 'https://www.moj.gov.sa',
                    'status': 'published',
                    'tags': json.dumps([f'مجلد{pdf_num}', 'وزارة العدل'])
                })
        else:
            i += 1

    return judgments

# ── إدخال قاعدة البيانات ────────────────────────────────────────────────────
def import_to_db(judgments):
    from app import app, db, Judgment, User

    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        added = skipped = 0

        for j in judgments:
            if Judgment.query.filter_by(title=j['title']).first():
                skipped += 1
                continue
            db.session.add(Judgment(created_by=admin.id, **j))
            added += 1
            if added % 50 == 0:
                db.session.commit()
                print(f"  تم إضافة {added} حكم...")

        db.session.commit()
        print(f"✅ مُضاف: {added} | متكرر: {skipped} | الإجمالي: {Judgment.query.count()}")

if __name__ == '__main__':
    all_j = []
    # ابحث عن ملفات PDF في المجلد الحالي
    pdf_files = sorted([f for f in os.listdir('.') if f.endswith('.pdf')])
    
    if not pdf_files:
        print("لا توجد ملفات PDF في هذا المجلد")
        sys.exit(1)

    for idx, fname in enumerate(pdf_files, 1):
        jj = extract_judgments_from_pdf(fname, idx)
        print(f"{fname}: {len(jj)} حكم")
        all_j.extend(jj)

    print(f"\nالإجمالي المستخرج: {len(all_j)} حكم")
    if all_j:
        import_to_db(all_j)
