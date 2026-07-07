from flask import Flask, request, jsonify, send_from_directory, session
from database import init_db, get_db
import os
from datetime import datetime, date
from calendar import monthrange

app = Flask(__name__, static_folder='.')
app.secret_key = 'gnt-hrms-fixed-secret-key-2024'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

APP_PASSWORD = 'gnt@2024'

init_db()

# Run migrations for existing databases
def migrate_db():
    db = get_db()
    migrations = [
        ("employees", "address", "TEXT", "''"),
        ("employees", "city", "TEXT", "''"),
        ("employees", "pin", "TEXT", "''"),
        ("ledger", "site", "TEXT", "''"),
        ("payroll", "paid_days", "REAL", "0"),
    ]
    for table, col, typ, default in migrations:
        try:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ} DEFAULT {default}")
            db.commit()
        except Exception:
            pass
    db.close()

migrate_db()

# ── helpers ───────────────────────────────────────────────────────────────────
def get_meta(key):
    db = get_db()
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    db.close()
    return row['value'] if row else None

def set_meta(key, value):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
    db.commit()
    db.close()

def sundays_in_month(yr, mo):
    _, days = monthrange(yr, mo)
    return sum(1 for d in range(1, days+1) if date(yr, mo, d).weekday() == 6)

def calc_pay(emp_id, month_key):
    yr, mo = int(month_key[:4]), int(month_key[5:])
    _, days_in_month = monthrange(yr, mo)
    sundays = sundays_in_month(yr, mo)
    weekdays = days_in_month - sundays
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        db.close()
        return None
    salary = emp['salary']
    daily_rate = salary / 30
    att_rows = db.execute("SELECT day, status FROM attendance WHERE emp_id=? AND month_key=?", (emp_id, month_key)).fetchall()
    att = {r['day']: r['status'] for r in att_rows}
    present = 0.0
    sunday_ot = 0
    for day in range(1, days_in_month + 1):
        wd = date(yr, mo, day).weekday()
        s = att.get(day, 'A')
        if wd == 6:
            if s == 'OT': sunday_ot += 1
        else:
            if s == 'P': present += 1
            elif s == 'H': present += 0.5
            elif s == 'L': present += 1
    ot_row = db.execute("SELECT ot_days FROM ot_days WHERE emp_id=? AND month_key=?", (emp_id, month_key)).fetchone()
    extra_ot = float(ot_row['ot_days']) if ot_row else 0.0
    total_ot = sunday_ot + extra_ot
    earned_pay = (present / weekdays) * salary if weekdays else 0
    ot_pay = total_ot * daily_rate
    deduct_rows = db.execute("SELECT SUM(amount) as total FROM ledger WHERE emp_id=? AND type='expense-recover' AND month_key=?", (emp_id, month_key)).fetchone()
    ledger_deduct = float(deduct_rows['total'] or 0)
    gross = earned_pay + ot_pay
    net = gross - ledger_deduct
    db.close()
    return dict(present=present, weekdays=weekdays, sundays=sundays,
                sunday_ot=sunday_ot, extra_ot=extra_ot, total_ot=total_ot,
                earned_pay=round(earned_pay,2), ot_pay=round(ot_pay,2),
                ledger_deduct=round(ledger_deduct,2),
                gross=round(gross,2), net=round(net,2), daily_rate=round(daily_rate,2))

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def fmt_inr(n):
    return f"₹{abs(round(n)):,}"

def fmt_date(d):
    try:
        dt = datetime.strptime(d, '%Y-%m-%d')
        return dt.strftime('%d %B %Y')
    except:
        return d or '___________'

# ── shared email HTML components ──────────────────────────────────────────────
LETTERHEAD = """
<div style="background:#1a1a18;color:#fff;padding:18px 36px;display:flex;justify-content:space-between;align-items:center;font-family:Arial,sans-serif">
  <div>
    <div style="font-size:20px;font-weight:700;letter-spacing:1px">GRAPHICS & TRENDS SOLUTIONS</div>
    <div style="font-size:10px;color:#ccc;margin-top:3px">Commercial Interior Fitout & Workspace Design</div>
  </div>
  <div style="text-align:right;font-size:10px;color:#ccc;line-height:1.7">
    C 269, Sector-10, Noida, Uttar Pradesh<br>
    +91-120-4322277 | +91-9560098148<br>
    graphicsandtrends@gmail.com<br>
    GST: 09AXBPA8060E1ZT
  </div>
</div>
<div style="height:4px;background:#d4a843"></div>
"""

STAMP_SVG = """
<svg viewBox="0 0 90 90" width="90" height="90" xmlns="http://www.w3.org/2000/svg" style="opacity:0.85;display:inline-block">
  <circle cx="45" cy="45" r="42" fill="none" stroke="#1a3a8a" stroke-width="1.8"/>
  <circle cx="45" cy="45" r="36" fill="none" stroke="#1a3a8a" stroke-width="0.8"/>
  <path id="topArc" d="M 9,45 A 36,36 0 0,1 81,45" fill="none"/>
  <path id="botArc" d="M 12,52 A 36,36 0 0,0 78,52" fill="none"/>
  <text font-family="serif" font-size="7.2" fill="#1a3a8a" font-weight="600" letter-spacing="1.2">
    <textPath href="#topArc" startOffset="50%" text-anchor="middle">GRAPHICS &amp; TRENDS SOLUTIONS</textPath>
  </text>
  <text font-family="serif" font-size="6.5" fill="#1a3a8a" letter-spacing="0.8">
    <textPath href="#botArc" startOffset="50%" text-anchor="middle">NOIDA · U.P. · INDIA</textPath>
  </text>
  <text x="45" y="40" font-family="serif" font-size="8" fill="#1a3a8a" font-weight="700" text-anchor="middle">GNT</text>
  <text x="45" y="51" font-family="serif" font-size="5.5" fill="#1a3a8a" text-anchor="middle">EST. 2010</text>
  <line x1="22" y1="56" x2="68" y2="56" stroke="#1a3a8a" stroke-width="0.7"/>
</svg>
<svg viewBox="0 0 90 90" width="90" height="90" xmlns="http://www.w3.org/2000/svg" style="position:absolute;top:0;left:0;opacity:0.75;display:inline-block">
  <path d="M 30 68 Q 32 58 36 62 Q 40 66 38 55 Q 37 50 42 52" stroke="#1a3a8a" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 42 52 Q 46 54 44 62 Q 43 66 48 64" stroke="#1a3a8a" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M 26 70 Q 52 72 58 68" stroke="#1a3a8a" stroke-width="1" fill="none" stroke-linecap="round" opacity="0.5"/>
</svg>
"""

def send_email(to_email, subject, html_body):
    if not resend.api_key:
        return False, "RESEND_API_KEY not set in Railway Variables."
    try:
        params = {
            "from": "GNT Solutions <onboarding@resend.dev>",
            "to": [to_email.strip()],
            "reply_to": "graphicsandtrends@gmail.com",
            "subject": subject,
            "html": html_body,
        }
        resend.Emails.send(params)
        return True, f"Email sent to {to_email}!"
    except Exception as e:
        return False, f"Email error: {str(e)}"

@app.route('/api/email/test', methods=['GET'])
@login_required
def test_email_config():
    if not resend.api_key:
        return jsonify({'ok': False, 'message': 'RESEND_API_KEY not set in Railway Variables'})
    return jsonify({'ok': True, 'message': 'Resend API key is configured', 'key_prefix': resend.api_key[:8]+'...'})

def build_offer_html(emp, joining_date, address, city, pin, ref):
    return f"""
<!DOCTYPE html><html><body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f5f5f0">
<div style="max-width:680px;margin:0 auto;background:#fff;border:1px solid #e0ddd5">
  {LETTERHEAD}
  <div style="padding:32px 40px;font-size:13px;color:#1a1a18;line-height:1.8">
    <table width="100%" style="margin-bottom:20px"><tr>
      <td><strong>Ref:</strong> {ref}</td>
      <td style="text-align:right"><strong>Date:</strong> {fmt_date(joining_date)}</td>
    </tr></table>
    <div style="margin-bottom:18px">
      To<br><strong>{emp['name']}</strong><br>
      {address}<br>{city}{' – '+pin if pin else ''}
    </div>
    <div style="margin-bottom:14px"><strong>Sub: Offer Letter</strong></div>
    <div style="margin-bottom:12px">Dear <strong>{emp['name']}</strong>,</div>
    <p style="margin-bottom:12px">We are pleased to offer you the post of <strong>{emp['desig']}</strong> based at <strong>Noida, Gautam Budh Nagar.</strong> Your joining salary will be <strong>Rs. {int(emp['salary']):,} per month</strong> inclusive all in hand. Appraisal for the same will be performance based.</p>
    <p style="margin-bottom:12px">Your employment with G&T Solutions will be subject to strict adherence to the policies and procedures of G&T Solutions. You will be on probation for one month. This offer is subject to background verification.</p>
    <p style="margin-bottom:12px">On acceptance of the terms and conditions as per this offer letter, you will be able to terminate your employment with G&T Solutions by giving one month notice to G&T Solutions and vice versa. You shall not be eligible to avail leave during the notice period.</p>
    <p style="margin-bottom:12px">We welcome you to join G&T Solutions and would be happy if you can sign the duplicate copy of this letter in token of your acceptance of the offer of employment with G&T Solutions.</p>
    <p style="margin-bottom:20px">You will be reporting to <strong>Mr. Aman Garg (+91-9560098148)</strong> on <strong>{fmt_date(joining_date)}</strong> at <strong>9:30 am at C 269, Ground Floor, Sector 10, Gautam Budh Nagar (U.P.)</strong></p>
    <p style="margin-bottom:24px">We wish you all the best and look forward to having you with us.</p>
    <div style="margin-top:32px">
      <div style="position:relative;display:inline-block;width:90px;height:90px">
        {STAMP_SVG}
      </div>
      <div style="margin-top:8px"><strong>Aman Garg</strong><br>Proprietor<br>Graphics & Trends Solutions</div>
    </div>
    <div style="margin-top:40px;padding-top:20px;border-top:1px solid #ddd;font-size:12px;color:#555">
      <p style="margin-bottom:8px">I accept the aforesaid terms & conditions and this offer of employment.</p>
      <p style="margin-bottom:8px">I will join on: _______________</p>
      <p style="margin-bottom:8px">Name: _______________</p>
      <p style="margin-bottom:8px">Signature: _______________</p>
      <p>Date: _______________</p>
    </div>
  </div>
</div>
</body></html>"""

def build_slip_html(emp, pr, month_label, recover_entries):
    daily_rate = emp['salary'] / 30
    deduction_rows = ''.join([
        f"<tr><td style='padding:4px 0;border-bottom:1px dashed #eee'>{x['label']}</td><td style='text-align:right;color:#e24b4a'>-{fmt_inr(x['amount'])}</td></tr>"
        for x in recover_entries
    ])
    sunday_ot_row = f"<tr><td style='padding:4px 0;border-bottom:1px dashed #eee'>Sunday OT ({pr['sunday_ot']} × {fmt_inr(daily_rate)})</td><td style='text-align:right'>{fmt_inr(pr['sunday_ot']*daily_rate)}</td></tr>" if pr['sunday_ot'] > 0 else ''
    extra_ot_row = f"<tr><td style='padding:4px 0;border-bottom:1px dashed #eee'>Extra OT ({pr['extra_ot']} × {fmt_inr(daily_rate)})</td><td style='text-align:right'>{fmt_inr(pr['extra_ot']*daily_rate)}</td></tr>" if pr['extra_ot'] > 0 else ''
    bank_block = ''
    if emp.get('bank') or emp.get('ifsc'):
        bank_block = f"""
        <div style="margin-top:12px;padding:10px;background:#faf9f5;border-radius:6px;font-size:12px">
          <strong>Bank Details</strong><br>
          {'A/C Holder: '+emp['acc_name']+'<br>' if emp.get('acc_name') else ''}
          {'Bank: '+emp['bank_name']+'<br>' if emp.get('bank_name') else ''}
          {'A/C No: '+emp['bank']+'<br>' if emp.get('bank') else ''}
          {'IFSC: '+emp['ifsc'] if emp.get('ifsc') else ''}
        </div>"""
    return f"""
<!DOCTYPE html><html><body style="margin:0;padding:0;font-family:Arial,sans-serif;background:#f5f5f0">
<div style="max-width:600px;margin:0 auto;background:#fff;border:1px solid #e0ddd5">
  {LETTERHEAD}
  <div style="padding:28px 32px;font-size:13px;color:#1a1a18">
    <div style="text-align:center;font-weight:700;font-size:15px;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #1a1a18">
      SALARY SLIP — {month_label.upper()}
    </div>
    <table width="100%" style="margin-bottom:16px;font-size:12px"><tr>
      <td style="vertical-align:top">
        <strong>{emp['name']}</strong><br>
        {emp['id']} | {emp['desig']}<br>
        {emp['dept']}<br>
        {'📞 '+emp['phone']+'<br>' if emp.get('phone') else ''}
        {'✉ '+emp['email'] if emp.get('email') else ''}
      </td>
      <td style="vertical-align:top;text-align:right;color:#555">
        Salary basis: 30 days<br>
        Working days: {pr['weekdays']} (excl. {pr['sundays']} Sundays)<br>
        Weekdays present: {pr['present']}/{pr['weekdays']}<br>
        Sunday OT: {pr['sunday_ot']} | Extra OT: {pr['extra_ot']}
      </td>
    </tr></table>
    <div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin:10px 0 5px">Earnings</div>
    <table width="100%" style="font-size:12px">
      <tr><td style='padding:4px 0;border-bottom:1px dashed #eee'>Base Salary (30-day basis)</td><td style='text-align:right'>{fmt_inr(emp['salary'])}</td></tr>
      <tr><td style='padding:4px 0;border-bottom:1px dashed #eee'>Earned Pay ({pr['present']}/{pr['weekdays']} days × {fmt_inr(emp['salary'])})</td><td style='text-align:right'>{fmt_inr(pr['earned_pay'])}</td></tr>
      {sunday_ot_row}{extra_ot_row}
      <tr><td style='padding:6px 0;border-bottom:1px dashed #eee;font-weight:600'>Gross Earnings</td><td style='text-align:right;font-weight:600'>{fmt_inr(pr['gross'])}</td></tr>
      {'<tr><td colspan=2><div style=font-size:10px;color:#888;text-transform:uppercase;letter-spacing:0.5px;margin:8px 0 4px>Deductions</div></td></tr>'+deduction_rows+'<tr><td style=padding:4px 0;border-bottom:1px dashed #eee;font-weight:500>Total Deductions</td><td style=text-align:right;color:#e24b4a>-'+fmt_inr(pr['ledger_deduct'])+'</td></tr>' if pr['ledger_deduct'] > 0 else ''}
      <tr style="border-top:2px solid #1a1a18"><td style='padding:8px 0;font-weight:700;font-size:14px'>NET PAYABLE</td><td style='text-align:right;font-weight:700;font-size:14px;color:#1d9e75'>{fmt_inr(pr['net'])}</td></tr>
    </table>
    {bank_block}
    <div style="margin-top:24px;padding-top:12px;border-top:1px dashed #ddd;display:flex;justify-content:space-between;align-items:flex-end">
      <span style="font-size:11px;color:#888">Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')}</span>
      <div style="text-align:center">
        <div style="position:relative;display:inline-block;width:86px;height:86px">
          {STAMP_SVG}
        </div>
        <div style="font-size:10px;color:#888;margin-top:4px">Authorised Signatory</div>
      </div>
    </div>
  </div>
</div>
</body></html>"""

# ── auth ──────────────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('password') == APP_PASSWORD:
        session.permanent = True
        session['logged_in'] = True
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Wrong password'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/check-auth')
def check_auth():
    return jsonify({'logged_in': bool(session.get('logged_in'))})

# ── employees ─────────────────────────────────────────────────────────────────
@app.route('/api/employees', methods=['GET'])
@login_required
def get_employees():
    db = get_db()
    rows = db.execute("SELECT * FROM employees ORDER BY rowid").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/employees', methods=['POST'])
@login_required
def add_employee():
    d = request.json
    num = int(get_meta('next_emp_num'))
    emp_id = f"GNT-{num:03d}"
    db = get_db()
    db.execute('''INSERT INTO employees(id,name,desig,dept,doj,salary,phone,email,address,city,pin,bank,bank_name,ifsc,acc_name,cl,sl,el,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (emp_id, d['name'], d['desig'], d.get('dept','General'), d.get('doj'),
         float(d.get('salary',0)), d.get('phone',''), d.get('email',''),
         d.get('address',''), d.get('city',''), d.get('pin',''),
         d.get('bank',''), d.get('bankName',''), d.get('ifsc',''),
         d.get('accName', d['name']),
         int(d.get('cl',12)), int(d.get('sl',6)), int(d.get('el',15)), 'Active'))
    db.commit()
    db.close()
    set_meta('next_emp_num', num + 1)
    return jsonify({'ok': True, 'id': emp_id})

@app.route('/api/employees/<emp_id>', methods=['PUT'])
@login_required
def update_employee(emp_id):
    d = request.json
    db = get_db()
    db.execute('''UPDATE employees SET name=?,desig=?,dept=?,doj=?,salary=?,phone=?,email=?,
        address=?,city=?,pin=?,bank=?,bank_name=?,ifsc=?,acc_name=?,cl=?,sl=?,el=? WHERE id=?''',
        (d['name'], d['desig'], d.get('dept','General'), d.get('doj'),
         float(d.get('salary',0)), d.get('phone',''), d.get('email',''),
         d.get('address',''), d.get('city',''), d.get('pin',''),
         d.get('bank',''), d.get('bankName',''), d.get('ifsc',''),
         d.get('accName', d['name']),
         int(d.get('cl',12)), int(d.get('sl',6)), int(d.get('el',15)), emp_id))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/employees/<emp_id>/status', methods=['POST'])
@login_required
def toggle_status(emp_id):
    db = get_db()
    emp = db.execute("SELECT status FROM employees WHERE id=?", (emp_id,)).fetchone()
    new_status = 'Inactive' if emp['status'] == 'Active' else 'Active'
    db.execute("UPDATE employees SET status=? WHERE id=?", (new_status, emp_id))
    db.commit()
    db.close()
    return jsonify({'ok': True, 'status': new_status})

@app.route('/api/employees/<emp_id>', methods=['DELETE'])
@login_required
def delete_employee(emp_id):
    db = get_db()
    for tbl in ['employees','attendance','ot_days','payroll','ledger','leaves']:
        col = 'id' if tbl == 'employees' else 'emp_id'
        db.execute(f"DELETE FROM {tbl} WHERE {col}=?", (emp_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── attendance ─────────────────────────────────────────────────────────────────
@app.route('/api/attendance/<month_key>', methods=['GET'])
@login_required
def get_attendance(month_key):
    db = get_db()
    rows = db.execute("SELECT emp_id, day, status FROM attendance WHERE month_key=?", (month_key,)).fetchall()
    ot_rows = db.execute("SELECT emp_id, ot_days FROM ot_days WHERE month_key=?", (month_key,)).fetchall()
    db.close()
    att = {f"{r['emp_id']}-{r['day']}": r['status'] for r in rows}
    ot = {r['emp_id']: r['ot_days'] for r in ot_rows}
    return jsonify({'attendance': att, 'ot': ot})

@app.route('/api/attendance', methods=['POST'])
@login_required
def save_attendance():
    d = request.json
    month_key = d['month_key']
    db = get_db()
    for key, status in d.get('attendance', {}).items():
        emp_id, day = key.rsplit('-', 1)
        db.execute('''INSERT INTO attendance(emp_id,month_key,day,status) VALUES(?,?,?,?)
            ON CONFLICT(emp_id,month_key,day) DO UPDATE SET status=excluded.status''',
            (emp_id, month_key, int(day), status))
    for emp_id, days in d.get('ot', {}).items():
        db.execute('''INSERT INTO ot_days(emp_id,month_key,ot_days) VALUES(?,?,?)
            ON CONFLICT(emp_id,month_key) DO UPDATE SET ot_days=excluded.ot_days''',
            (emp_id, month_key, float(days)))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── payroll ────────────────────────────────────────────────────────────────────
@app.route('/api/payroll/<month_key>', methods=['GET'])
@login_required
def get_payroll(month_key):
    db = get_db()
    rows = db.execute("SELECT * FROM payroll WHERE month_key=?", (month_key,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/payroll/calculate', methods=['POST'])
@login_required
def calculate_payroll():
    d = request.json
    month_key = d['month_key']
    db = get_db()
    emps = db.execute("SELECT * FROM employees WHERE status='Active'").fetchall()
    for emp in emps:
        calc = calc_pay(emp['id'], month_key)
        if not calc: continue
        existing = db.execute("SELECT paid,paid_date,posted_to_ledger FROM payroll WHERE emp_id=? AND month_key=?",
            (emp['id'], month_key)).fetchone()
        paid = existing['paid'] if existing else 'Unpaid'
        paid_date = existing['paid_date'] if existing else ''
        posted = existing['posted_to_ledger'] if existing else 0
        db.execute('''INSERT INTO payroll(emp_id,month_key,present,weekdays,sundays,sunday_ot,extra_ot,
            total_ot,earned_pay,ot_pay,ledger_deduct,gross,net,daily_rate,paid_days,paid,paid_date,posted_to_ledger)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(emp_id,month_key) DO UPDATE SET
            present=excluded.present,weekdays=excluded.weekdays,sundays=excluded.sundays,
            sunday_ot=excluded.sunday_ot,extra_ot=excluded.extra_ot,total_ot=excluded.total_ot,
            earned_pay=excluded.earned_pay,ot_pay=excluded.ot_pay,ledger_deduct=excluded.ledger_deduct,
            gross=excluded.gross,net=excluded.net,daily_rate=excluded.daily_rate,
            paid_days=excluded.paid_days''',
            (emp['id'], month_key, calc['present'], calc['weekdays'], calc['sundays'],
             calc['sunday_ot'], calc['extra_ot'], calc['total_ot'], calc['earned_pay'],
             calc['ot_pay'], calc['ledger_deduct'], calc['gross'], calc['net'],
             calc['daily_rate'], calc['paid_days'], paid, paid_date, posted))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/payroll/post-ledger', methods=['POST'])
@login_required
def post_to_ledger():
    d = request.json
    emp_id, month_key = d['emp_id'], d['month_key']
    db = get_db()
    pr = db.execute("SELECT * FROM payroll WHERE emp_id=? AND month_key=?", (emp_id, month_key)).fetchone()
    if not pr:
        db.close(); return jsonify({'error': 'Not calculated'}), 400
    if pr['posted_to_ledger']:
        db.close(); return jsonify({'error': 'Already posted'}), 400
    yr, mo = int(month_key[:4]), int(month_key[5:])
    label = f"Salary — {datetime(yr,mo,1).strftime('%B %Y')}"
    db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
        (emp_id, date.today().isoformat(), 'salary-credit', label, pr['net'], 'credit', month_key))
    db.execute("UPDATE payroll SET posted_to_ledger=1 WHERE emp_id=? AND month_key=?", (emp_id, month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/payroll/mark-paid', methods=['POST'])
@login_required
def mark_paid():
    d = request.json
    emp_id, month_key, status = d['emp_id'], d['month_key'], d['status']
    db = get_db()
    pr = db.execute("SELECT net FROM payroll WHERE emp_id=? AND month_key=?", (emp_id, month_key)).fetchone()
    today_str = date.today().strftime('%d/%m/%Y')
    db.execute("UPDATE payroll SET paid=?,paid_date=? WHERE emp_id=? AND month_key=?",
        (status, today_str, emp_id, month_key))
    if status == 'Paid' and pr:
        yr, mo = int(month_key[:4]), int(month_key[5:])
        label = f"Salary Paid — {datetime(yr,mo,1).strftime('%B %Y')}"
        db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
            (emp_id, date.today().isoformat(), 'salary-payment', label, pr['net'], 'debit', month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── ledger ─────────────────────────────────────────────────────────────────────
@app.route('/api/ledger/<emp_id>', methods=['GET'])
@login_required
def get_ledger(emp_id):
    db = get_db()
    rows = db.execute("SELECT * FROM ledger WHERE emp_id=? ORDER BY date,id", (emp_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/ledger/advance', methods=['POST'])
@login_required
def add_advance():
    d = request.json
    db = get_db()
    month_key = d['date'][:7]
    db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
        (d['emp_id'], d['date'], 'advance',
         f"{d.get('note','Advance salary')} ({d.get('mode','Cash')})",
         float(d['amount']), 'debit', month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/ledger/expenses', methods=['POST'])
@login_required
def add_expenses():
    d = request.json
    emp_id, dt, bill = d['emp_id'], d['date'], d.get('bill','')
    site = d.get('site','')
    month_key = dt[:7]
    db = get_db()
    for line in d.get('lines', []):
        desc = line.get('desc','')
        amt = float(line.get('amount', 0))
        exp_type = line.get('type','Other')
        effect_raw = line.get('effect','reimburse')
        entry_type = 'expense-reimburse' if effect_raw == 'reimburse' else 'expense-recover'
        effect = 'debit' if effect_raw == 'reimburse' else 'credit'
        site_tag = f" | {site}" if site else ''
        label = f"{desc}{' ['+bill+']' if bill else ''} ({exp_type}{site_tag})"
        db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
            (emp_id, dt, entry_type, label, amt, effect, month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/ledger/<int:entry_id>', methods=['DELETE'])
@login_required
def delete_ledger_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM ledger WHERE id=?", (entry_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/ledger/opening-balance', methods=['POST'])
@login_required
def add_opening_balance():
    d = request.json
    db = get_db()
    db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
        (d['emp_id'], d['date'], 'opening-balance',
         d.get('note','Opening Balance'), float(d['amount']), d['effect'], d['date'][:7]))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── leaves ─────────────────────────────────────────────────────────────────────
@app.route('/api/leaves', methods=['GET'])
@login_required
def get_leaves():
    db = get_db()
    rows = db.execute("SELECT * FROM leaves ORDER BY id DESC").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/leaves', methods=['POST'])
@login_required
def add_leave():
    d = request.json
    from_date, to_date = d['from_date'], d['to_date']
    days = (datetime.strptime(to_date,'%Y-%m-%d') - datetime.strptime(from_date,'%Y-%m-%d')).days + 1
    db = get_db()
    db.execute("INSERT INTO leaves(emp_id,from_date,to_date,leave_type,days,reason,status) VALUES(?,?,?,?,?,?,?)",
        (d['emp_id'], from_date, to_date, d.get('leave_type','Casual Leave'),
         days, d.get('reason',''), d.get('status','Pending')))
    if d.get('status') == 'Approved':
        lt = d.get('leave_type','')
        col = 'cl_used' if 'Casual' in lt else 'sl_used' if 'Sick' in lt else 'el_used' if 'Earned' in lt else None
        if col:
            db.execute(f"UPDATE employees SET {col}={col}+? WHERE id=?", (days, d['emp_id']))
    db.commit()
    db.close()
    return jsonify({'ok': True})

@app.route('/api/leaves/<int:leave_id>', methods=['DELETE'])
@login_required
def delete_leave(leave_id):
    db = get_db()
    db.execute("DELETE FROM leaves WHERE id=?", (leave_id,))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── email: offer letter ────────────────────────────────────────────────────────
@app.route('/api/email/offer-letter', methods=['POST'])
@login_required
def email_offer_letter():
    d = request.json
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id=?", (d['emp_id'],)).fetchone()
    db.close()
    if not emp:
        return jsonify({'ok': False, 'error': 'Employee not found'}), 404
    to_email = d.get('to_email') or emp['email']
    if not to_email:
        return jsonify({'ok': False, 'error': 'No email address for this employee'}), 400
    html = build_offer_html(
        dict(emp),
        d.get('joining_date',''),
        d.get('address',''),
        d.get('city',''),
        d.get('pin',''),
        d.get('ref', emp['id'])
    )
    ok, msg = send_email(
        to_email,
        f"Offer Letter — {emp['name']} | Graphics & Trends Solutions",
        html
    )
    return jsonify({'ok': ok, 'message': msg})

# ── email: salary slip ─────────────────────────────────────────────────────────
@app.route('/api/email/salary-slip', methods=['POST'])
@login_required
def email_salary_slip():
    d = request.json
    emp_id, month_key = d['emp_id'], d['month_key']
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    pr = db.execute("SELECT * FROM payroll WHERE emp_id=? AND month_key=?", (emp_id, month_key)).fetchone()
    recover_entries = db.execute(
        "SELECT * FROM ledger WHERE emp_id=? AND type='expense-recover' AND month_key=?",
        (emp_id, month_key)).fetchall()
    db.close()
    if not emp or not pr:
        return jsonify({'ok': False, 'error': 'Payroll not calculated for this month'}), 400
    to_email = d.get('to_email') or emp['email']
    if not to_email:
        return jsonify({'ok': False, 'error': 'No email address for this employee'}), 400
    yr, mo = int(month_key[:4]), int(month_key[5:])
    month_label = datetime(yr, mo, 1).strftime('%B %Y')
    html = build_slip_html(dict(emp), dict(pr), month_label, [dict(r) for r in recover_entries])
    ok, msg = send_email(
        to_email,
        f"Salary Slip — {month_label} | {emp['name']} | Graphics & Trends Solutions",
        html
    )
    return jsonify({'ok': ok, 'message': msg})

# ── serve ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
