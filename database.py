import sqlite3, os

DB_PATH = os.environ.get('DB_PATH', 'gnt_hrms.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS employees (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        desig TEXT NOT NULL,
        dept TEXT,
        doj TEXT,
        salary REAL,
        phone TEXT,
        email TEXT,
        bank TEXT,
        bank_name TEXT,
        ifsc TEXT,
        acc_name TEXT,
        cl INTEGER DEFAULT 12,
        sl INTEGER DEFAULT 6,
        el INTEGER DEFAULT 15,
        cl_used INTEGER DEFAULT 0,
        sl_used INTEGER DEFAULT 0,
        el_used INTEGER DEFAULT 0,
        status TEXT DEFAULT 'Active',
        next_emp_num INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        month_key TEXT NOT NULL,
        day INTEGER NOT NULL,
        status TEXT DEFAULT 'A',
        UNIQUE(emp_id, month_key, day)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ot_days (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        month_key TEXT NOT NULL,
        ot_days REAL DEFAULT 0,
        UNIQUE(emp_id, month_key)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payroll (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        month_key TEXT NOT NULL,
        present REAL DEFAULT 0,
        weekdays INTEGER DEFAULT 0,
        sundays INTEGER DEFAULT 0,
        sunday_ot REAL DEFAULT 0,
        extra_ot REAL DEFAULT 0,
        total_ot REAL DEFAULT 0,
        earned_pay REAL DEFAULT 0,
        ot_pay REAL DEFAULT 0,
        ledger_deduct REAL DEFAULT 0,
        gross REAL DEFAULT 0,
        net REAL DEFAULT 0,
        daily_rate REAL DEFAULT 0,
        paid TEXT DEFAULT 'Unpaid',
        paid_date TEXT DEFAULT '',
        posted_to_ledger INTEGER DEFAULT 0,
        UNIQUE(emp_id, month_key)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        date TEXT NOT NULL,
        type TEXT NOT NULL,
        label TEXT NOT NULL,
        amount REAL NOT NULL,
        effect TEXT NOT NULL,
        month_key TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS leaves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        from_date TEXT NOT NULL,
        to_date TEXT NOT NULL,
        leave_type TEXT,
        days INTEGER,
        reason TEXT,
        status TEXT DEFAULT 'Pending'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')

    # Init meta counters
    c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('next_emp_num','1')")
    c.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('next_entry_id','1')")

    conn.commit()
    conn.close()
