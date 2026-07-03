from flask import Flask, request, jsonify, send_from_directory, session
from database import init_db, get_db
import os, math
from datetime import datetime, date
from calendar import monthrange

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'gnt-hrms-secret-2024')

APP_PASSWORD = 'gnt@2024'

init_db()

# ── helpers ──────────────────────────────────────────────────────────────────
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

    att_rows = db.execute(
        "SELECT day, status FROM attendance WHERE emp_id=? AND month_key=?",
        (emp_id, month_key)).fetchall()
    att = {r['day']: r['status'] for r in att_rows}

    present = 0.0
    sunday_ot = 0
    for day in range(1, days_in_month + 1):
        wd = date(yr, mo, day).weekday()
        s = att.get(day, 'A')
        if wd == 6:  # Sunday
            if s == 'OT':
                sunday_ot += 1
        else:
            if s == 'P':   present += 1
            elif s == 'H': present += 0.5
            elif s == 'L': present += 1

    ot_row = db.execute(
        "SELECT ot_days FROM ot_days WHERE emp_id=? AND month_key=?",
        (emp_id, month_key)).fetchone()
    extra_ot = float(ot_row['ot_days']) if ot_row else 0.0
    total_ot = sunday_ot + extra_ot

    earned_pay = (present / weekdays) * salary if weekdays else 0
    ot_pay = total_ot * daily_rate

    deduct_rows = db.execute(
        "SELECT SUM(amount) as total FROM ledger WHERE emp_id=? AND type='expense-recover' AND month_key=?",
        (emp_id, month_key)).fetchone()
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

# ── auth ─────────────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('password') == APP_PASSWORD:
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

# ── employees ────────────────────────────────────────────────────────────────
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
    db.execute('''INSERT INTO employees(id,name,desig,dept,doj,salary,phone,email,bank,bank_name,ifsc,acc_name,cl,sl,el,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (emp_id, d['name'], d['desig'], d.get('dept','General'), d.get('doj'),
         float(d.get('salary',0)), d.get('phone',''), d.get('email',''),
         d.get('bank',''), d.get('bankName',''), d.get('ifsc',''),
         d.get('accName', d['name']),
         int(d.get('cl',12)), int(d.get('sl',6)), int(d.get('el',15)), 'Active'))
    db.commit()
    db.close()
    set_meta('next_emp_num', num + 1)
    return jsonify({'ok': True, 'id': emp_id})

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

# ── attendance ───────────────────────────────────────────────────────────────
@app.route('/api/attendance/<month_key>', methods=['GET'])
@login_required
def get_attendance(month_key):
    db = get_db()
    rows = db.execute(
        "SELECT emp_id, day, status FROM attendance WHERE month_key=?", (month_key,)).fetchall()
    ot_rows = db.execute(
        "SELECT emp_id, ot_days FROM ot_days WHERE month_key=?", (month_key,)).fetchall()
    db.close()
    att = {}
    for r in rows:
        att[f"{r['emp_id']}-{r['day']}"] = r['status']
    ot = {r['emp_id']: r['ot_days'] for r in ot_rows}
    return jsonify({'attendance': att, 'ot': ot})

@app.route('/api/attendance', methods=['POST'])
@login_required
def save_attendance():
    d = request.json
    month_key = d['month_key']
    att = d.get('attendance', {})
    ot = d.get('ot', {})
    db = get_db()
    for key, status in att.items():
        emp_id, day = key.rsplit('-', 1)
        db.execute('''INSERT INTO attendance(emp_id,month_key,day,status)
            VALUES(?,?,?,?) ON CONFLICT(emp_id,month_key,day) DO UPDATE SET status=excluded.status''',
            (emp_id, month_key, int(day), status))
    for emp_id, days in ot.items():
        db.execute('''INSERT INTO ot_days(emp_id,month_key,ot_days)
            VALUES(?,?,?) ON CONFLICT(emp_id,month_key) DO UPDATE SET ot_days=excluded.ot_days''',
            (emp_id, month_key, float(days)))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── payroll ──────────────────────────────────────────────────────────────────
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
        if not calc:
            continue
        existing = db.execute("SELECT paid,paid_date,posted_to_ledger FROM payroll WHERE emp_id=? AND month_key=?",
            (emp['id'], month_key)).fetchone()
        paid = existing['paid'] if existing else 'Unpaid'
        paid_date = existing['paid_date'] if existing else ''
        posted = existing['posted_to_ledger'] if existing else 0
        db.execute('''INSERT INTO payroll(emp_id,month_key,present,weekdays,sundays,sunday_ot,extra_ot,
            total_ot,earned_pay,ot_pay,ledger_deduct,gross,net,daily_rate,paid,paid_date,posted_to_ledger)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(emp_id,month_key) DO UPDATE SET
            present=excluded.present,weekdays=excluded.weekdays,sundays=excluded.sundays,
            sunday_ot=excluded.sunday_ot,extra_ot=excluded.extra_ot,total_ot=excluded.total_ot,
            earned_pay=excluded.earned_pay,ot_pay=excluded.ot_pay,ledger_deduct=excluded.ledger_deduct,
            gross=excluded.gross,net=excluded.net,daily_rate=excluded.daily_rate''',
            (emp['id'], month_key, calc['present'], calc['weekdays'], calc['sundays'],
             calc['sunday_ot'], calc['extra_ot'], calc['total_ot'], calc['earned_pay'],
             calc['ot_pay'], calc['ledger_deduct'], calc['gross'], calc['net'],
             calc['daily_rate'], paid, paid_date, posted))
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
        db.close()
        return jsonify({'error': 'Not calculated'}), 400
    if pr['posted_to_ledger']:
        db.close()
        return jsonify({'error': 'Already posted'}), 400
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
    today = date.today().strftime('%d/%m/%Y')
    db.execute("UPDATE payroll SET paid=?,paid_date=? WHERE emp_id=? AND month_key=?",
        (status, today, emp_id, month_key))
    if status == 'Paid' and pr:
        yr, mo = int(month_key[:4]), int(month_key[5:])
        label = f"Salary Paid — {datetime(yr,mo,1).strftime('%B %Y')}"
        db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
            (emp_id, date.today().isoformat(), 'salary-payment', label, pr['net'], 'debit', month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── ledger ───────────────────────────────────────────────────────────────────
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
    lines = d.get('lines', [])
    month_key = dt[:7]
    db = get_db()
    for line in lines:
        desc = line.get('desc','')
        amt = float(line.get('amount', 0))
        exp_type = line.get('type','Other')
        effect_raw = line.get('effect','reimburse')
        entry_type = 'expense-reimburse' if effect_raw == 'reimburse' else 'expense-recover'
        effect = 'debit' if effect_raw == 'reimburse' else 'credit'
        label = f"{desc}{' ['+bill+']' if bill else ''} ({exp_type})"
        db.execute("INSERT INTO ledger(emp_id,date,type,label,amount,effect,month_key) VALUES(?,?,?,?,?,?,?)",
            (emp_id, dt, entry_type, label, amt, effect, month_key))
    db.commit()
    db.close()
    return jsonify({'ok': True})

# ── leaves ───────────────────────────────────────────────────────────────────
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
    from_date = d['from_date']
    to_date = d['to_date']
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

# ── serve frontend ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
