from flask import Flask, request, jsonify, session, send_from_directory, send_file
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import hashlib
import os
import uuid
import json
from datetime import datetime, date
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get('SECRET_KEY', 'rollcall-dev-key')
CORS(app, supports_credentials=True)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
# Railway uses postgres:// but psycopg2 requires postgresql://
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'board')''')

    c.execute('''CREATE TABLE IF NOT EXISTS interest_types (
        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, color TEXT DEFAULT 'gray',
        created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS volunteers (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
        phone TEXT, birthday TEXT, status TEXT NOT NULL DEFAULT 'active',
        interests TEXT DEFAULT '[]', created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, event_date TEXT,
        description TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS hours (
        id TEXT PRIMARY KEY, volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        event TEXT NOT NULL, event_id TEXT, date TEXT NOT NULL, hours REAL NOT NULL,
        role TEXT, notes TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY, volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        author TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS volunteer_history (
        id TEXT PRIMARY KEY, volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        event TEXT NOT NULL, role TEXT NOT NULL, date TEXT NOT NULL,
        notes TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS volunteer_files (
        id TEXT PRIMARY KEY, volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        name TEXT NOT NULL, size TEXT, type TEXT, date TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS waiver_types (
        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT,
        template_body TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS volunteer_waivers (
        id TEXT PRIMARY KEY, volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
        signed_date TEXT NOT NULL, expiry_date TEXT, filename TEXT, original_name TEXT,
        file_size TEXT, signed_name TEXT, signed_via TEXT DEFAULT 'upload',
        uploaded_by TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS email_templates (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL,
        body TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS youth_participants (
        id TEXT PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
        dob TEXT, program TEXT, status TEXT NOT NULL DEFAULT 'active',
        medical_notes TEXT, allergies TEXT, photo_consent INTEGER DEFAULT 0,
        medical_consent INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS youth_guardians (
        id TEXT PRIMARY KEY, youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        name TEXT NOT NULL, relationship TEXT NOT NULL, phone TEXT, email TEXT,
        is_primary INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS youth_emergency_contacts (
        id TEXT PRIMARY KEY, youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        name TEXT NOT NULL, relationship TEXT, phone TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW())''')

    c.execute('''CREATE TABLE IF NOT EXISTS youth_waivers (
        id TEXT PRIMARY KEY, youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
        signed_date TEXT NOT NULL, expiry_date TEXT, signed_by TEXT,
        filename TEXT, original_name TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    # youth_programs table
    c.execute('''CREATE TABLE IF NOT EXISTS youth_programs (
        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
        description TEXT, created_at TIMESTAMP DEFAULT NOW())''')

    # youth program enrollments (many-to-many)
    c.execute('''CREATE TABLE IF NOT EXISTS youth_program_enrollments (
        id TEXT PRIMARY KEY,
        youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        program_id TEXT NOT NULL REFERENCES youth_programs(id) ON DELETE CASCADE,
        enrolled_date TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(youth_id, program_id))''')

    # productions
    c.execute('''CREATE TABLE IF NOT EXISTS productions (
        id TEXT PRIMARY KEY, name TEXT NOT NULL,
        production_type TEXT DEFAULT 'show',
        start_date TEXT, end_date TEXT,
        description TEXT, status TEXT DEFAULT 'upcoming',
        created_at TIMESTAMP DEFAULT NOW())''')

    # production members (volunteers in a production)
    c.execute('''CREATE TABLE IF NOT EXISTS production_members (
        id TEXT PRIMARY KEY,
        production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        department TEXT,
        status TEXT DEFAULT 'confirmed',
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(production_id, volunteer_id))''')

    # add active column to users
    conn.commit()

    # pending hours (kiosk submissions awaiting approval)
    c.execute("""CREATE TABLE IF NOT EXISTS pending_hours (
        id TEXT PRIMARY KEY,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        event TEXT NOT NULL,
        event_id TEXT,
        date TEXT NOT NULL,
        hours REAL NOT NULL,
        role TEXT,
        notes TEXT,
        submitted_at TIMESTAMP DEFAULT NOW(),
        status TEXT DEFAULT 'pending')""")

    # event required waivers
    c.execute("""CREATE TABLE IF NOT EXISTS event_waivers (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
        UNIQUE(event_id, waiver_type_id))""")

    # production required waivers
    c.execute("""CREATE TABLE IF NOT EXISTS production_waivers (
        id TEXT PRIMARY KEY,
        production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
        waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
        UNIQUE(production_id, waiver_type_id))""")

    # volunteer emergency contacts
    c.execute("""CREATE TABLE IF NOT EXISTS volunteer_emergency_contacts (
        id TEXT PRIMARY KEY,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        relationship TEXT,
        phone TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW())""")

    # opening checklist template (separate from closing)
    c.execute("""CREATE TABLE IF NOT EXISTS opening_checklist_items (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        item_type TEXT NOT NULL DEFAULT 'checkbox',
        required BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        hint TEXT,
        created_at TIMESTAMP DEFAULT NOW())""")

    # seed default opening checklist items
    opening_items = [
        (str(__import__('uuid').uuid4()), 'Space is clean and ready', 'checkbox', True, 1, ''),
        (str(__import__('uuid').uuid4()), 'All equipment/props in place', 'checkbox', True, 2, ''),
        (str(__import__('uuid').uuid4()), 'Lights and sound checked', 'checkbox', True, 3, ''),
        (str(__import__('uuid').uuid4()), 'Bathrooms stocked and clean', 'checkbox', True, 4, ''),
        (str(__import__('uuid').uuid4()), 'Emergency exits clear', 'checkbox', True, 5, ''),
        (str(__import__('uuid').uuid4()), 'Headcount / expected attendance', 'text', False, 6, 'How many people are expected tonight?'),
        (str(__import__('uuid').uuid4()), 'Opening notes', 'text', False, 7, 'Anything staff should know before the event starts'),
    ]
    for item in opening_items:
        c.execute("INSERT INTO opening_checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", item)

    # youth authorized pickups
    c.execute("""CREATE TABLE IF NOT EXISTS youth_authorized_pickups (
        id TEXT PRIMARY KEY,
        youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        relationship TEXT,
        phone TEXT,
        priority INTEGER DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW())""")

    # production attendance (kiosk sign-in/out for cast & crew)
    c.execute("""CREATE TABLE IF NOT EXISTS prod_attendance (
        id TEXT PRIMARY KEY,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        signed_in_at TIMESTAMP DEFAULT NOW(),
        signed_out_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW())""")

    # youth parent sign-in/out
    c.execute("""CREATE TABLE IF NOT EXISTS youth_sign_ins (
        id TEXT PRIMARY KEY,
        youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        event_id TEXT REFERENCES events(id),
        program_id TEXT REFERENCES youth_programs(id),
        signed_in_at TIMESTAMP,
        signed_in_by TEXT,
        signed_out_at TIMESTAMP,
        signed_out_by TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW())""")

    # summer camps (programs with dates)
    # already covered by youth_programs — just add date columns via migration

    # event types (customizable)
    c.execute("""CREATE TABLE IF NOT EXISTS event_types (
        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
        color TEXT DEFAULT 'blue',
        created_at TIMESTAMP DEFAULT NOW())""")

    # seed default event types
    for et in [
        (str(__import__('uuid').uuid4()), 'Rehearsal', 'amber'),
        (str(__import__('uuid').uuid4()), 'Performance', 'teal'),
        (str(__import__('uuid').uuid4()), 'Meeting', 'blue'),
        (str(__import__('uuid').uuid4()), 'Build Day', 'pink'),
        (str(__import__('uuid').uuid4()), 'Strike', 'purple'),
        (str(__import__('uuid').uuid4()), 'Other', 'gray'),
    ]:
        c.execute("INSERT INTO event_types (id,name,color) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", et)

    # ELICs (approved event leads)
    c.execute("""CREATE TABLE IF NOT EXISTS elics (
        id TEXT PRIMARY KEY,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        pin TEXT NOT NULL,
        is_master BOOLEAN DEFAULT FALSE,
        active BOOLEAN DEFAULT TRUE,
        notes TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(volunteer_id))""")

    # event ELIC assignment
    c.execute("""CREATE TABLE IF NOT EXISTS event_elics (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        elic_id TEXT NOT NULL REFERENCES elics(id) ON DELETE CASCADE,
        UNIQUE(event_id, elic_id))""")

    # checklist template items
    c.execute("""CREATE TABLE IF NOT EXISTS checklist_items (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        item_type TEXT NOT NULL DEFAULT 'checkbox',
        required BOOLEAN DEFAULT TRUE,
        sort_order INTEGER DEFAULT 0,
        hint TEXT,
        created_at TIMESTAMP DEFAULT NOW())""")

    # event open/close log
    c.execute("""CREATE TABLE IF NOT EXISTS event_logs (
        id TEXT PRIMARY KEY,
        event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        elic_id TEXT NOT NULL REFERENCES elics(id),
        action TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT NOW(),
        notes TEXT)""")

    # closing checklist responses
    c.execute("""CREATE TABLE IF NOT EXISTS event_checklist_responses (
        id TEXT PRIMARY KEY,
        event_log_id TEXT NOT NULL REFERENCES event_logs(id) ON DELETE CASCADE,
        checklist_item_id TEXT,
        label TEXT NOT NULL,
        item_type TEXT NOT NULL,
        response TEXT,
        created_at TIMESTAMP DEFAULT NOW())""")

    # seed default checklist items
    default_items = [
        (str(__import__('uuid').uuid4()), 'Bathrooms cleaned and stocked', 'checkbox', True, 1, ''),
        (str(__import__('uuid').uuid4()), 'Thermostat set to away temperature', 'checkbox', True, 2, 'Set to 78°F cooling / 65°F heating'),
        (str(__import__('uuid').uuid4()), 'All trash emptied and taken out', 'checkbox', True, 3, ''),
        (str(__import__('uuid').uuid4()), 'Garage door and back door locked', 'checkbox', True, 4, 'Check both doors'),
        (str(__import__('uuid').uuid4()), 'All lights turned off', 'checkbox', True, 5, 'Include stage lights, lobby, bathrooms'),
        (str(__import__('uuid').uuid4()), 'Space swept and items put away', 'checkbox', True, 6, ''),
        (str(__import__('uuid').uuid4()), 'Any incidents to report?', 'text', False, 7, 'Describe any incidents, injuries, or issues that occurred'),
        (str(__import__('uuid').uuid4()), 'Additional notes', 'text', False, 8, 'Anything else the admin should know'),
    ]
    for item in default_items:
        c.execute("INSERT INTO checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", item)

    # pending profile updates (kiosk)
    c.execute("""CREATE TABLE IF NOT EXISTS pending_profile_updates (
        id TEXT PRIMARY KEY,
        volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT NOT NULL,
        submitted_at TIMESTAMP DEFAULT NOW(),
        status TEXT DEFAULT 'pending')""")

    # Run migrations in separate try blocks so failures don't roll back table creation
    for col_sql in [
        "ALTER TABLE waiver_types ADD COLUMN IF NOT EXISTS required_all BOOLEAN DEFAULT FALSE",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS start_time TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS end_time TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS end_date TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft'",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_type_id TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS location TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS room TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS production_id TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS expected_volunteers INTEGER",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS notes TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT 'mainstage'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS youth_program_id TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS requires_background_check BOOLEAN DEFAULT FALSE",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS background_check_date TEXT",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS background_check_status TEXT DEFAULT 'none'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role_permissions TEXT DEFAULT '{}'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS start_date TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS end_date TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_type TEXT DEFAULT 'class'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS instructor_id TEXT",
        "ALTER TABLE volunteer_waivers ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT",
        "ALTER TABLE volunteer_waivers ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT",
        "ALTER TABLE volunteer_waivers ADD COLUMN IF NOT EXISTS emergency_contact_relationship TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS programs TEXT DEFAULT '[]'",
    ]:
        try:
            c.execute(col_sql)
            conn.commit()
        except Exception:
            conn.rollback()

    conn.close()

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def require_auth():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    return None

def require_admin():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if session.get('role') != 'admin':
        return jsonify({'error': 'Admin required'}), 403
    return None

def serialize_row(r):
    out = {}
    for k, v in r.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out

def fetchall(conn, sql, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
        c.execute(sql, params)
        return [serialize_row(r) for r in c.fetchall()]

def fetchone(conn, sql, params=()):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
        c.execute(sql, params)
        r = c.fetchone()
        return serialize_row(r) if r else None

def execute(conn, sql, params=()):
    with conn.cursor() as c:
        c.execute(sql, params)

def get_waiver_summary(conn, vol_id):
    waivers = fetchall(conn,
        'SELECT vw.*, wt.name as type_name FROM volunteer_waivers vw JOIN waiver_types wt ON vw.waiver_type_id=wt.id WHERE vw.volunteer_id=%s ORDER BY vw.signed_date DESC',
        (vol_id,))
    today = date.today()
    worst = 'none'
    for w in waivers:
        if not w['expiry_date']:
            if worst == 'none': worst = 'valid'
            continue
        diff = (datetime.strptime(w['expiry_date'], '%Y-%m-%d').date() - today).days
        if diff < 0: worst = 'expired'; break
        elif diff < 30 and worst != 'expired': worst = 'expiring'
        elif worst == 'none': worst = 'valid'
    return worst, waivers

# ─────────────────────────────────────────────
#  SERVE FRONTEND
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')
@app.route('/api/debug')
def debug():
    try:
        conn = get_db()
        tables = fetchall(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        counts = {}
        for t in tables:
            name = t['table_name']
            try:
                row = fetchone(conn, f'SELECT COUNT(*) as c FROM "{name}"')
                counts[name] = row['c']
            except:
                counts[name] = 'error'
        conn.close()
        return jsonify({'status': 'ok', 'db_url_set': bool(DATABASE_URL), 'tables': counts})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'db_url_set': bool(DATABASE_URL)})



# ─────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json
    pw_hash = hashlib.sha256(d['password'].encode()).hexdigest()
    conn = get_db()
    user = fetchone(conn, 'SELECT * FROM users WHERE email=%s AND password_hash=%s', (d['email'], pw_hash))
    conn.close()
    if not user: return jsonify({'error': 'Invalid email or password'}), 401
    if not user.get('active', True): return jsonify({'error': 'Your account has been deactivated. Contact an administrator.'}), 403
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['role'] = user['role']
    return jsonify({'id': user['id'], 'name': user['name'], 'email': user['email'], 'role': user['role']})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me')
def me():
    if 'user_id' not in session: return jsonify({'user': None})
    return jsonify({'user': {'id': session['user_id'], 'name': session['user_name'], 'role': session['role']}})

# ─────────────────────────────────────────────
#  INTEREST TYPES
# ─────────────────────────────────────────────

@app.route('/api/interest-types')
def get_interest_types():
    err = require_auth()
    if err: return err
    conn = get_db()
    types = fetchall(conn, 'SELECT * FROM interest_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/interest-types', methods=['POST'])
def create_interest_type():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip(): return jsonify({'error': 'Name is required'}), 400
    tid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO interest_types (id,name,color) VALUES (%s,%s,%s)', (tid, d['name'].strip(), d.get('color','gray')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Interest type already exists'}), 400
    row = fetchone(conn, 'SELECT * FROM interest_types WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/interest-types/<tid>', methods=['DELETE'])
def delete_interest_type(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM interest_types WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────

@app.route('/api/events')
def get_events():
    err = require_auth()
    if err: return err
    conn = get_db()
    events = fetchall(conn, '''SELECT e.*,
        COALESCE(e.requires_background_check, FALSE) as requires_background_check,
        et.name as event_type_name, et.color as event_type_color,
        p.name as production_name
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id
        ORDER BY e.event_date DESC NULLS LAST, e.start_time ASC NULLS LAST''')
    for e in events:
        e['required_waivers'] = fetchall(conn,
            'SELECT ew.*, wt.name as waiver_name FROM event_waivers ew JOIN waiver_types wt ON ew.waiver_type_id=wt.id WHERE ew.event_id=%s', (e['id'],))
        e['elics'] = fetchall(conn, """SELECT ee.id as assignment_id, el.id as elic_id,
            el.is_master, v.name as volunteer_name
            FROM event_elics ee JOIN elics el ON ee.elic_id=el.id
            JOIN volunteers v ON el.volunteer_id=v.id
            WHERE ee.event_id=%s""", (e['id'],))
        e['status'] = e.get('status') or 'draft'
    conn.close()
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO events
        (id,name,event_date,end_date,start_time,end_time,event_type_id,location,room,production_id,expected_volunteers,description,notes,status,requires_background_check)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)''',
        (eid, d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False)))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*, et.name as event_type_name, et.color as event_type_color,
        p.name as production_name FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id WHERE e.id=%s''', (eid,))
    row['required_waivers'] = []; row['elics'] = []
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>', methods=['PUT'])
def update_event(eid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE events SET name=%s,event_date=%s,end_date=%s,start_time=%s,end_time=%s,
        event_type_id=%s,location=%s,room=%s,production_id=%s,expected_volunteers=%s,description=%s,notes=%s,requires_background_check=%s WHERE id=%s''',
        (d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False), eid))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*, et.name as event_type_name, et.color as event_type_color,
        p.name as production_name FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id WHERE e.id=%s''', (eid,))
    row['required_waivers'] = fetchall(conn,
        'SELECT ew.*, wt.name as waiver_name FROM event_waivers ew JOIN waiver_types wt ON ew.waiver_type_id=wt.id WHERE ew.event_id=%s', (eid,))
    row['elics'] = fetchall(conn, """SELECT ee.id as assignment_id, el.id as elic_id,
        el.is_master, v.name as volunteer_name FROM event_elics ee
        JOIN elics el ON ee.elic_id=el.id JOIN volunteers v ON el.volunteer_id=v.id
        WHERE ee.event_id=%s""", (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>', methods=['DELETE'])
def delete_event(eid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM events WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  VOLUNTEERS
# ─────────────────────────────────────────────

@app.route('/api/volunteers')
def get_volunteers():
    err = require_auth()
    if err: return err
    conn = get_db()
    vols = fetchall(conn, '''SELECT *, COALESCE(background_check_status,'none') as background_check_status FROM volunteers ORDER BY name''')
    for v in vols:
        v['total_hours'] = fetchone(conn, 'SELECT COALESCE(SUM(hours),0) as t FROM hours WHERE volunteer_id=%s', (v['id'],))['t']
        v['waiver_status'], v['waivers'] = get_waiver_summary(conn, v['id'])
    conn.close()
    return jsonify(vols)

@app.route('/api/volunteers/<vol_id>')
def get_volunteer(vol_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vol_id,))
    if not vol: conn.close(); return jsonify({'error': 'Not found'}), 404
    vol['hours']   = fetchall(conn, 'SELECT * FROM hours WHERE volunteer_id=%s ORDER BY date DESC', (vol_id,))
    vol['notes']   = fetchall(conn, 'SELECT * FROM notes WHERE volunteer_id=%s ORDER BY created_at DESC', (vol_id,))
    vol['history'] = fetchall(conn, 'SELECT * FROM volunteer_history WHERE volunteer_id=%s ORDER BY date DESC', (vol_id,))
    vol['files']   = fetchall(conn, 'SELECT * FROM volunteer_files WHERE volunteer_id=%s ORDER BY created_at DESC', (vol_id,))
    vol['emergency_contacts'] = fetchall(conn, 'SELECT * FROM volunteer_emergency_contacts WHERE volunteer_id=%s ORDER BY created_at DESC', (vol_id,))
    vol['productions'] = fetchall(conn, '''SELECT pm.*, p.name as production_name, p.production_type,
        p.start_date, p.end_date, p.status as production_status
        FROM production_members pm JOIN productions p ON pm.production_id=p.id
        WHERE pm.volunteer_id=%s ORDER BY p.start_date DESC NULLS LAST''', (vol_id,))
    vol['waiver_status'], vol['waivers'] = get_waiver_summary(conn, vol_id)
    vol['total_hours'] = fetchone(conn, 'SELECT COALESCE(SUM(hours),0) as t FROM hours WHERE volunteer_id=%s', (vol_id,))['t']
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers', methods=['POST'])
def create_volunteer():
    err = require_admin()
    if err: return err
    d = request.json
    vid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteers (id,name,email,phone,birthday,status,interests,background_check_status,background_check_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (vid, d['name'], d['email'], d.get('phone',''), d.get('birthday') or None, d.get('status','active'), json.dumps(d.get('interests',[])), d.get('background_check_status','none'), d.get('background_check_date') or None))
    conn.commit()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vid,))
    vol['total_hours'] = 0; vol['waiver_status'] = 'none'; vol['waivers'] = []
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['PUT'])
def update_volunteer(vol_id):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE volunteers SET name=%s,email=%s,phone=%s,birthday=%s,status=%s,interests=%s,background_check_status=%s,background_check_date=%s WHERE id=%s',
            (d['name'], d['email'], d.get('phone',''), d.get('birthday') or None, d.get('status','active'), json.dumps(d.get('interests',[])), d.get('background_check_status','none'), d.get('background_check_date') or None, vol_id))
    conn.commit()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vol_id,))
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['DELETE'])
def delete_volunteer(vol_id):
    err = require_admin()
    if err: return err
    conn = get_db()
    waivers = fetchall(conn, 'SELECT filename FROM volunteer_waivers WHERE volunteer_id=%s', (vol_id,))
    for w in waivers:
        if w['filename']:
            try: os.remove(os.path.join(UPLOAD_FOLDER, w['filename']))
            except: pass
    execute(conn, 'DELETE FROM volunteers WHERE id=%s', (vol_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  HOURS
# ─────────────────────────────────────────────

@app.route('/api/hours')
def get_hours():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn,
        'SELECT h.*, v.name as volunteer_name, v.email as volunteer_email FROM hours h JOIN volunteers v ON h.volunteer_id=v.id ORDER BY h.date DESC')
    conn.close()
    return jsonify(rows)

@app.route('/api/hours', methods=['POST'])
def create_hours():
    err = require_admin()
    if err: return err
    d = request.json
    hid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (hid, d['volunteer_id'], d['event'], d.get('event_id'), d['date'], d['hours'], d.get('role',''), d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT h.*, v.name as volunteer_name FROM hours h JOIN volunteers v ON h.volunteer_id=v.id WHERE h.id=%s', (hid,))
    conn.close()
    return jsonify(row)

@app.route('/api/hours/<hid>', methods=['DELETE'])
def delete_hours(hid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM hours WHERE id=%s', (hid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  NOTES
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/notes', methods=['POST'])
def create_note(vol_id):
    err = require_admin()
    if err: return err
    d = request.json
    nid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO notes (id,volunteer_id,author,content) VALUES (%s,%s,%s,%s)',
            (nid, vol_id, session['user_name'], d['content']))
    conn.commit()
    note = fetchone(conn, 'SELECT * FROM notes WHERE id=%s', (nid,))
    conn.close()
    return jsonify(note)

# ─────────────────────────────────────────────
#  HISTORY
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/history', methods=['POST'])
def create_history(vol_id):
    err = require_admin()
    if err: return err
    d = request.json
    hid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteer_history (id,volunteer_id,event,role,date,notes) VALUES (%s,%s,%s,%s,%s,%s)',
            (hid, vol_id, d['event'], d['role'], d['date'], d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM volunteer_history WHERE id=%s', (hid,))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  FILES
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/files', methods=['POST'])
def create_file(vol_id):
    err = require_admin()
    if err: return err
    d = request.json
    fid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteer_files (id,volunteer_id,name,size,type,date) VALUES (%s,%s,%s,%s,%s,%s)',
            (fid, vol_id, d['name'], d.get('size',''), d.get('type',''), date.today().isoformat()))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM volunteer_files WHERE id=%s', (fid,))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  WAIVER TYPES
# ─────────────────────────────────────────────

@app.route('/api/waiver-types')
def get_waiver_types():
    err = require_auth()
    if err: return err
    conn = get_db()
    types = fetchall(conn, 'SELECT * FROM waiver_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/waiver-types', methods=['POST'])
def create_waiver_type():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip(): return jsonify({'error': 'Name is required'}), 400
    tid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO waiver_types (id,name,description,template_body) VALUES (%s,%s,%s,%s)',
                (tid, d['name'].strip(), d.get('description',''), d.get('template_body','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Waiver type already exists'}), 400
    row = fetchone(conn, 'SELECT * FROM waiver_types WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/waiver-types/<tid>', methods=['PUT'])
def update_waiver_type(tid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE waiver_types SET name=%s,description=%s,template_body=%s WHERE id=%s',
            (d['name'], d.get('description',''), d.get('template_body',''), tid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM waiver_types WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/waiver-types/<tid>', methods=['DELETE'])
def delete_waiver_type(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM waiver_types WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/waiver-types/<tid>/public')
def get_waiver_type_public(tid):
    conn = get_db()
    row = fetchone(conn, 'SELECT id,name,description,template_body FROM waiver_types WHERE id=%s', (tid,))
    conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404
    return jsonify(row)

# ─────────────────────────────────────────────
#  VOLUNTEER WAIVERS
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/waivers', methods=['POST'])
def upload_waiver(vol_id):
    err = require_admin()
    if err: return err
    waiver_type_id = request.form.get('waiver_type_id')
    signed_date    = request.form.get('signed_date')
    expiry_date    = request.form.get('expiry_date') or None
    signed_name    = request.form.get('signed_name') or None
    signed_via     = request.form.get('signed_via', 'upload')
    ec_name        = request.form.get('emergency_contact_name') or None
    ec_phone       = request.form.get('emergency_contact_phone') or None
    ec_rel         = request.form.get('emergency_contact_relationship') or None
    if not waiver_type_id or not signed_date:
        return jsonify({'error': 'Waiver type and signed date are required'}), 400
    filename = original_name = file_size = None
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename:
            ext = os.path.splitext(secure_filename(f.filename))[1].lower()
            if ext not in ['.pdf','.jpg','.jpeg','.png','.doc','.docx']:
                return jsonify({'error': 'Invalid file type'}), 400
            filename = str(uuid.uuid4()) + ext
            original_name = f.filename
            f.save(os.path.join(UPLOAD_FOLDER, filename))
            size_bytes = os.path.getsize(os.path.join(UPLOAD_FOLDER, filename))
            file_size = f'{size_bytes//1024} KB' if size_bytes >= 1024 else f'{size_bytes} B'
    wid = str(uuid.uuid4())
    conn = get_db()
    execute(conn,
        'INSERT INTO volunteer_waivers (id,volunteer_id,waiver_type_id,signed_date,expiry_date,filename,original_name,file_size,signed_name,signed_via,uploaded_by,emergency_contact_name,emergency_contact_phone,emergency_contact_relationship) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (wid, vol_id, waiver_type_id, signed_date, expiry_date, filename, original_name, file_size, signed_name, signed_via, session['user_name'], ec_name, ec_phone, ec_rel))
    conn.commit()
    row = fetchone(conn,
        'SELECT vw.*, wt.name as type_name FROM volunteer_waivers vw JOIN waiver_types wt ON vw.waiver_type_id=wt.id WHERE vw.id=%s', (wid,))
    conn.close()
    return jsonify(row)

@app.route('/api/sign-waiver', methods=['POST'])
def sign_waiver_online():
    d = request.json
    vol_id         = d.get('volunteer_id')
    waiver_type_id = d.get('waiver_type_id')
    signed_name    = d.get('signed_name','').strip()
    if not vol_id or not waiver_type_id or not signed_name:
        return jsonify({'error': 'volunteer_id, waiver_type_id, and signed_name are required'}), 400
    today = date.today().isoformat()
    exp = date(date.today().year + 1, date.today().month, date.today().day).isoformat()
    wid = str(uuid.uuid4())
    conn = get_db()
    execute(conn,
        'INSERT INTO volunteer_waivers (id,volunteer_id,waiver_type_id,signed_date,expiry_date,signed_name,signed_via,uploaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        (wid, vol_id, waiver_type_id, today, exp, signed_name, 'online', 'Self-signed'))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/waivers/<wid>/download')
def download_waiver(wid):
    err = require_auth()
    if err: return err
    conn = get_db()
    w = fetchone(conn, 'SELECT * FROM volunteer_waivers WHERE id=%s', (wid,))
    conn.close()
    if not w or not w['filename']: return jsonify({'error': 'No file attached'}), 404
    filepath = os.path.join(UPLOAD_FOLDER, w['filename'])
    if not os.path.exists(filepath): return jsonify({'error': 'File not found on disk'}), 404
    return send_file(filepath, as_attachment=True, download_name=w['original_name'] or w['filename'])

@app.route('/api/waivers/<wid>', methods=['DELETE'])
def delete_waiver_record(wid):
    err = require_admin()
    if err: return err
    conn = get_db()
    w = fetchone(conn, 'SELECT * FROM volunteer_waivers WHERE id=%s', (wid,))
    if w and w['filename']:
        try: os.remove(os.path.join(UPLOAD_FOLDER, w['filename']))
        except: pass
    execute(conn, 'DELETE FROM volunteer_waivers WHERE id=%s', (wid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  YOUTH PROGRAMS
# ─────────────────────────────────────────────

@app.route('/api/youth-programs')
def get_youth_programs():
    err = require_auth()
    if err: return err
    conn = get_db()
    programs = fetchall(conn, 'SELECT * FROM youth_programs ORDER BY name')
    conn.close()
    return jsonify(programs)

@app.route('/api/youth-programs', methods=['POST'])
def create_youth_program():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip(): return jsonify({'error': 'Name is required'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO youth_programs (id,name,description) VALUES (%s,%s,%s)',
                (pid, d['name'].strip(), d.get('description','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Program already exists'}), 400
    row = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-programs/<pid>', methods=['DELETE'])
def delete_youth_program(pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_programs WHERE id=%s', (pid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  EMAIL TEMPLATES
# ─────────────────────────────────────────────

@app.route('/api/email-templates')
def get_email_templates():
    err = require_auth()
    if err: return err
    conn = get_db()
    templates = fetchall(conn, 'SELECT * FROM email_templates ORDER BY name')
    conn.close()
    return jsonify(templates)

@app.route('/api/email-templates', methods=['POST'])
def create_email_template():
    err = require_admin()
    if err: return err
    d = request.json
    tid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO email_templates (id,name,subject,body) VALUES (%s,%s,%s,%s)',
            (tid, d['name'], d['subject'], d['body']))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM email_templates WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/email-templates/<tid>', methods=['DELETE'])
def delete_email_template(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM email_templates WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  YOUTH
# ─────────────────────────────────────────────

@app.route('/api/youth')
def get_youth():
    err = require_auth()
    if err: return err
    conn = get_db()
    youth = fetchall(conn, 'SELECT * FROM youth_participants ORDER BY last_name,first_name')
    for y in youth:
        y['guardians'] = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s ORDER BY is_primary DESC', (y['id'],))
        y['emergency_contacts'] = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (y['id'],))
        y['authorized_pickups'] = fetchall(conn, 'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority', (y['id'],))
        y['waivers'] = fetchall(conn,
            'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=%s ORDER BY yw.signed_date DESC', (y['id'],))
        y['enrollments'] = fetchall(conn,
            'SELECT e.*, p.name as program_name FROM youth_program_enrollments e JOIN youth_programs p ON e.program_id=p.id WHERE e.youth_id=%s ORDER BY e.enrolled_date DESC', (y['id'],))
    conn.close()
    return jsonify(youth)

@app.route('/api/youth/<yid>')
def get_youth_participant(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    if not y: conn.close(); return jsonify({'error': 'Not found'}), 404
    y['guardians'] = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s ORDER BY is_primary DESC', (yid,))
    y['emergency_contacts'] = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (yid,))
    y['authorized_pickups'] = fetchall(conn, 'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority', (yid,))
    y['waivers'] = fetchall(conn,
        'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=%s ORDER BY yw.signed_date DESC', (yid,))
    y['enrollments'] = fetchall(conn,
        'SELECT e.*, p.name as program_name FROM youth_program_enrollments e JOIN youth_programs p ON e.program_id=p.id WHERE e.youth_id=%s ORDER BY e.enrolled_date DESC', (yid,))
    conn.close()
    return jsonify(y)

@app.route('/api/youth', methods=['POST'])
def create_youth():
    err = require_admin()
    if err: return err
    d = request.json
    yid = str(uuid.uuid4())
    conn = get_db()
    execute(conn,
        'INSERT INTO youth_participants (id,first_name,last_name,dob,program,status,medical_notes,allergies,photo_consent,medical_consent) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (yid, d['first_name'], d['last_name'], d.get('dob') or None, d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0))
    for g in d.get('guardians', []):
        execute(conn, 'INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), yid, g['name'], g.get('relationship',''), g.get('phone',''), g.get('email',''), 1 if g.get('is_primary') else 0))
    if d.get('emergency_name') and d.get('emergency_phone'):
        execute(conn, 'INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), yid, d['emergency_name'], d.get('emergency_relationship',''), d['emergency_phone']))
    conn.commit()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    y['guardians'] = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s', (yid,))
    y['emergency_contacts'] = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (yid,))
    y['waivers'] = []
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['PUT'])
def update_youth(yid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn,
        'UPDATE youth_participants SET first_name=%s,last_name=%s,dob=%s,program=%s,status=%s,medical_notes=%s,allergies=%s,photo_consent=%s,medical_consent=%s WHERE id=%s',
        (d['first_name'], d['last_name'], d.get('dob') or None, d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0, yid))
    conn.commit()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['DELETE'])
def delete_youth(yid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_participants WHERE id=%s', (yid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/guardians', methods=['POST'])
def add_guardian(yid):
    err = require_admin()
    if err: return err
    d = request.json
    gid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (gid, yid, d['name'], d.get('relationship',''), d.get('phone',''), d.get('email',''), 1 if d.get('is_primary') else 0))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_guardians WHERE id=%s', (gid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/guardians/<gid>', methods=['DELETE'])
def delete_guardian(gid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_guardians WHERE id=%s', (gid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/emergency-contacts', methods=['POST'])
def add_emergency_contact(yid):
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
            (eid, yid, d['name'], d.get('relationship',''), d['phone']))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_emergency_contacts WHERE id=%s', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/<yid>/waivers', methods=['POST'])
def add_youth_waiver(yid):
    err = require_admin()
    if err: return err
    waiver_type_id = request.form.get('waiver_type_id')
    signed_date    = request.form.get('signed_date')
    expiry_date    = request.form.get('expiry_date') or None
    signed_by      = request.form.get('signed_by') or None
    if not waiver_type_id or not signed_date:
        return jsonify({'error': 'Waiver type and signed date are required'}), 400
    filename = original_name = None
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename:
            ext = os.path.splitext(secure_filename(f.filename))[1].lower()
            filename = str(uuid.uuid4()) + ext
            original_name = f.filename
            f.save(os.path.join(UPLOAD_FOLDER, filename))
    wid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO youth_waivers (id,youth_id,waiver_type_id,signed_date,expiry_date,signed_by,filename,original_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (wid, yid, waiver_type_id, signed_date, expiry_date, signed_by, filename, original_name))
    conn.commit()
    row = fetchone(conn,
        'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.id=%s', (wid,))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  DASHBOARD
# ─────────────────────────────────────────────

@app.route('/api/dashboard')
def dashboard():
    err = require_auth()
    if err: return err
    conn = get_db()
    total_vols  = fetchone(conn, 'SELECT COUNT(*) as c FROM volunteers')['c']
    total_hours = fetchone(conn, 'SELECT COALESCE(SUM(hours),0) as s FROM hours')['s']
    total_youth = fetchone(conn, "SELECT COUNT(*) as c FROM youth_participants WHERE status='active'")['c']
    today = date.today()
    all_waivers = fetchall(conn,
        'SELECT vw.volunteer_id, vw.expiry_date, v.name FROM volunteer_waivers vw JOIN volunteers v ON vw.volunteer_id=v.id')
    vol_worst = {}; vol_names = {}
    for w in all_waivers:
        vid = w['volunteer_id']; vol_names[vid] = w['name']
        if not w['expiry_date']:
            if vid not in vol_worst: vol_worst[vid] = 'valid'
            continue
        diff = (datetime.strptime(w['expiry_date'], '%Y-%m-%d').date() - today).days
        prev = vol_worst.get(vid, 'none')
        if diff < 0: vol_worst[vid] = 'expired'
        elif diff < 30 and prev != 'expired': vol_worst[vid] = 'expiring'
        elif prev == 'none': vol_worst[vid] = 'valid'
    expiring = sum(1 for s in vol_worst.values() if s == 'expiring')
    expired  = sum(1 for s in vol_worst.values() if s == 'expired')
    alerts = []
    for vid, status in vol_worst.items():
        if status == 'expiring': alerts.append({'type':'warning','name':vol_names[vid],'msg':'waiver expiring soon','id':vid})
        if status == 'expired':  alerts.append({'type':'danger', 'name':vol_names[vid],'msg':'waiver has expired','id':vid})
    monthly = []
    for i in range(5, -1, -1):
        m = today.month - i; y = today.year + (m - 1) // 12; m = ((m - 1) % 12) + 1
        label = datetime(y, m, 1).strftime('%b')
        total = fetchone(conn,
            "SELECT COALESCE(SUM(hours),0) as s FROM hours WHERE TO_CHAR(TO_DATE(date,'YYYY-MM-DD'),'YYYY-MM')=%s",
            (f'{y:04d}-{m:02d}',))['s']
        monthly.append({'label': label, 'total': float(total)})
    top = fetchall(conn, '''
        SELECT v.id, v.name, COALESCE(SUM(h.hours),0) as total_hours, COUNT(DISTINCT h.event) as total_events
        FROM volunteers v LEFT JOIN hours h ON v.id=h.volunteer_id
        GROUP BY v.id, v.name ORDER BY total_hours DESC LIMIT 5
    ''')
    conn.close()
    return jsonify({'total_volunteers': total_vols, 'total_hours': float(total_hours), 'total_youth': total_youth,
                    'expiring_waivers': expiring, 'expired_waivers': expired,
                    'alerts': alerts, 'monthly_hours': monthly, 'top_volunteers': top})

# ─────────────────────────────────────────────
#  USERS
# ─────────────────────────────────────────────

@app.route('/api/users', methods=['POST'])
def create_user():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name') or not d.get('email') or not d.get('password'):
        return jsonify({'error': 'Name, email, and password are required'}), 400
    pw_hash = hashlib.sha256(d['password'].encode()).hexdigest()
    uid_ = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO users (id,name,email,password_hash,role) VALUES (%s,%s,%s,%s,%s)',
                (uid_, d['name'], d['email'], pw_hash, d.get('role','board')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Email already exists'}), 400
    conn.close()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────
#  PRODUCTIONS
# ─────────────────────────────────────────────

@app.route('/api/productions')
def get_productions():
    err = require_auth()
    if err: return err
    conn = get_db()
    prods = fetchall(conn, "SELECT *, COALESCE(stage,'mainstage') as stage FROM productions ORDER BY start_date DESC NULLS LAST")
    for p in prods:
        p['members'] = fetchall(conn, '''
            SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
            FROM production_members pm
            JOIN volunteers v ON pm.volunteer_id=v.id
            WHERE pm.production_id=%s ORDER BY pm.role''', (p['id'],))
        p['required_waivers'] = fetchall(conn,
            'SELECT pw.*, wt.name as waiver_name FROM production_waivers pw JOIN waiver_types wt ON pw.waiver_type_id=wt.id WHERE pw.production_id=%s', (p['id'],))
    conn.close()
    return jsonify(prods)

@app.route('/api/productions', methods=['POST'])
def create_production():
    err = require_admin()
    if err: return err
    d = request.json
    pid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO productions (id,name,production_type,stage,start_date,end_date,description,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (pid, d['name'], d.get('production_type','show'), d.get('stage','mainstage'),
             d.get('start_date') or None, d.get('end_date') or None,
             d.get('description',''), d.get('status','upcoming')))
    conn.commit()
    prod = fetchone(conn, 'SELECT * FROM productions WHERE id=%s', (pid,))
    prod['members'] = []
    conn.close()
    return jsonify(prod)

@app.route('/api/productions/<pid>', methods=['PUT'])
def update_production(pid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE productions SET name=%s,production_type=%s,stage=%s,start_date=%s,end_date=%s,description=%s,status=%s WHERE id=%s',
            (d['name'], d.get('production_type','show'), d.get('stage','mainstage'),
             d.get('start_date') or None, d.get('end_date') or None,
             d.get('description',''), d.get('status','upcoming'), pid))
    conn.commit()
    prod = fetchone(conn, 'SELECT * FROM productions WHERE id=%s', (pid,))
    prod['members'] = fetchall(conn, '''
        SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
        FROM production_members pm JOIN volunteers v ON pm.volunteer_id=v.id
        WHERE pm.production_id=%s ORDER BY pm.role''', (pid,))
    conn.close()
    return jsonify(prod)

@app.route('/api/productions/<pid>', methods=['DELETE'])
def delete_production(pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM productions WHERE id=%s', (pid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/members', methods=['POST'])
def add_production_member(pid):
    err = require_admin()
    if err: return err
    d = request.json
    mid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO production_members (id,production_id,volunteer_id,role,department,status,notes) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (mid, pid, d['volunteer_id'], d['role'], d.get('department',''), d.get('status','confirmed'), d.get('notes','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'This volunteer is already in this production'}), 400
    row = fetchone(conn, '''SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
        FROM production_members pm JOIN volunteers v ON pm.volunteer_id=v.id WHERE pm.id=%s''', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/members/<mid>', methods=['PUT'])
def update_production_member(mid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE production_members SET role=%s,department=%s,status=%s,notes=%s WHERE id=%s',
            (d['role'], d.get('department',''), d.get('status','confirmed'), d.get('notes',''), mid))
    conn.commit()
    row = fetchone(conn, '''SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
        FROM production_members pm JOIN volunteers v ON pm.volunteer_id=v.id WHERE pm.id=%s''', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/members/<mid>', methods=['DELETE'])
def remove_production_member(mid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_members WHERE id=%s', (mid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  YOUTH PROGRAM ENROLLMENTS
# ─────────────────────────────────────────────

@app.route('/api/youth/<yid>/enrollments', methods=['POST'])
def enroll_youth(yid):
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO youth_program_enrollments (id,youth_id,program_id,enrolled_date,notes) VALUES (%s,%s,%s,%s,%s)',
                (eid, yid, d['program_id'], d.get('enrolled_date') or date.today().isoformat(), d.get('notes','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Already enrolled in this program'}), 400
    row = fetchone(conn, '''SELECT e.*, p.name as program_name FROM youth_program_enrollments e
        JOIN youth_programs p ON e.program_id=p.id WHERE e.id=%s''', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/enrollments/<eid>', methods=['DELETE'])
def unenroll_youth(eid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_program_enrollments WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  USER MANAGEMENT
# ─────────────────────────────────────────────

@app.route('/api/users')
def get_users():
    err = require_admin()
    if err: return err
    conn = get_db()
    users = fetchall(conn, 'SELECT id,name,email,role,COALESCE(active,TRUE) as active FROM users ORDER BY name')
    conn.close()
    return jsonify(users)

@app.route('/api/users/<uid>/toggle', methods=['POST'])
def toggle_user(uid):
    err = require_admin()
    if err: return err
    if uid == session['user_id']:
        return jsonify({'error': 'Cannot deactivate your own account'}), 400
    conn = get_db()
    user = fetchone(conn, 'SELECT COALESCE(active,TRUE) as active FROM users WHERE id=%s', (uid,))
    if not user: conn.close(); return jsonify({'error': 'Not found'}), 404
    new_active = not user['active']
    execute(conn, 'UPDATE users SET active=%s WHERE id=%s', (new_active, uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'active': new_active})

# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────


init_db()

if __name__ == '__main__':
    print('\n🎭 RoleCall is running!')
    print('   Open http://localhost:5000 in your browser\n')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)

# ─────────────────────────────────────────────
#  KIOSK
# ─────────────────────────────────────────────

@app.route('/kiosk')
def kiosk_page():
    return send_from_directory('static', 'kiosk.html')




@app.route('/api/kiosk/youth')
def kiosk_youth():
    conn = get_db()
    youth = fetchall(conn,
        "SELECT id, first_name, last_name FROM youth_participants WHERE status='active' ORDER BY last_name, first_name")
    conn.close()
    return jsonify(youth)

@app.route('/api/kiosk/interest-types')
def kiosk_interest_types():
    conn = get_db()
    types = fetchall(conn, 'SELECT id, name FROM interest_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/kiosk/volunteer-profile/<vol_id>')
def kiosk_volunteer_profile(vol_id):
    """Minimal volunteer profile for kiosk — no auth needed."""
    conn = get_db()
    vol = fetchone(conn,
        "SELECT id, name, phone, interests, COALESCE(background_check_status,'none') as background_check_status FROM volunteers WHERE id=%s AND status='active'",
        (vol_id,))
    if not vol:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    ec = fetchone(conn,
        'SELECT name, relationship, phone FROM volunteer_emergency_contacts WHERE volunteer_id=%s ORDER BY created_at DESC LIMIT 1',
        (vol_id,))
    vol['emergency_contact'] = ec or {}
    conn.close()
    return jsonify(vol)

@app.route('/api/kiosk/volunteers')
def kiosk_volunteers():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    conn = get_db()
    vols = fetchall(conn,
        "SELECT id, name, email, phone FROM volunteers WHERE status='active' AND LOWER(name) LIKE %s ORDER BY name LIMIT 10",
        (f'%{q}%',))
    conn.close()
    return jsonify(vols)

@app.route('/api/kiosk/events')
def kiosk_events():
    # Only return events that have been opened by an ELIC
    conn = get_db()
    events = fetchall(conn, "SELECT * FROM events WHERE status='open' ORDER BY event_date DESC NULLS LAST")
    conn.close()
    return jsonify(events)

@app.route('/api/kiosk/submit', methods=['POST'])
def kiosk_submit():
    d = request.json
    if not d.get('volunteer_id') or not d.get('event') or not d.get('hours'):
        return jsonify({'error': 'Missing required fields'}), 400
    try:
        hours = float(d['hours'])
        if hours <= 0 or hours > 24:
            return jsonify({'error': 'Hours must be between 0.5 and 24'}), 400
    except Exception:
        return jsonify({'error': 'Invalid hours value'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    vol = fetchone(conn, "SELECT id, name FROM volunteers WHERE id=%s AND status='active'", (d['volunteer_id'],))
    if not vol:
        conn.close()
        return jsonify({'error': 'Volunteer not found'}), 404
    execute(conn,
        "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        (pid, d['volunteer_id'], d['event'], d.get('event_id'),
         date.today().isoformat(), hours, d.get('role',''), d.get('notes','')))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'volunteer_name': vol['name']})

# ─────────────────────────────────────────────
#  PENDING HOURS
# ─────────────────────────────────────────────

@app.route('/api/pending-hours')
def get_pending_hours():
    err = require_admin()
    if err: return err
    conn = get_db()
    rows = fetchall(conn,
        "SELECT ph.*, v.name as volunteer_name, v.email as volunteer_email FROM pending_hours ph JOIN volunteers v ON ph.volunteer_id=v.id WHERE ph.status='pending' ORDER BY ph.submitted_at DESC")
    conn.close()
    return jsonify(rows)

@app.route('/api/pending-hours/<pid>/approve', methods=['POST'])
def approve_hours(pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    ph = fetchone(conn, 'SELECT * FROM pending_hours WHERE id=%s', (pid,))
    if not ph:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    hid = str(uuid.uuid4())
    execute(conn,
        "INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (hid, ph['volunteer_id'], ph['event'], ph['event_id'], ph['date'], ph['hours'], ph['role'], ph['notes']))
    execute(conn, "UPDATE pending_hours SET status='approved' WHERE id=%s", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-hours/<pid>/reject', methods=['POST'])
def reject_hours(pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE pending_hours SET status='rejected' WHERE id=%s", (pid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-hours/count')
def pending_hours_count():
    err = require_auth()
    if err: return err
    conn = get_db()
    count = fetchone(conn, "SELECT COUNT(*) as c FROM pending_hours WHERE status='pending'")['c']
    conn.close()
    return jsonify({'count': count})

# ─────────────────────────────────────────────
#  WAIVER TYPE REQUIRED FLAG
# ─────────────────────────────────────────────

@app.route('/api/waiver-types/<tid>/toggle-required', methods=['POST'])
def toggle_waiver_required(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    wt = fetchone(conn, 'SELECT COALESCE(required_all,FALSE) as required_all FROM waiver_types WHERE id=%s', (tid,))
    if not wt: conn.close(); return jsonify({'error': 'Not found'}), 404
    new_val = not wt['required_all']
    execute(conn, 'UPDATE waiver_types SET required_all=%s WHERE id=%s', (new_val, tid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'required_all': new_val})

# ─────────────────────────────────────────────
#  EVENT / PRODUCTION REQUIRED WAIVERS
# ─────────────────────────────────────────────

@app.route('/api/events/<eid>/waivers', methods=['POST'])
def add_event_waiver(eid):
    err = require_admin()
    if err: return err
    d = request.json
    rid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO event_waivers (id,event_id,waiver_type_id) VALUES (%s,%s,%s)',
                (rid, eid, d['waiver_type_id']))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Already assigned'}), 400
    row = fetchone(conn, 'SELECT ew.*, wt.name as waiver_name FROM event_waivers ew JOIN waiver_types wt ON ew.waiver_type_id=wt.id WHERE ew.id=%s', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>/waivers/<wid>', methods=['DELETE'])
def remove_event_waiver(eid, wid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_waivers WHERE id=%s AND event_id=%s', (wid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/waivers', methods=['POST'])
def add_production_waiver(pid):
    err = require_admin()
    if err: return err
    d = request.json
    rid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO production_waivers (id,production_id,waiver_type_id) VALUES (%s,%s,%s)',
                (rid, pid, d['waiver_type_id']))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Already assigned'}), 400
    row = fetchone(conn, 'SELECT pw.*, wt.name as waiver_name FROM production_waivers pw JOIN waiver_types wt ON pw.waiver_type_id=wt.id WHERE pw.id=%s', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/waivers/<wid>', methods=['DELETE'])
def remove_production_waiver(pid, wid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_waivers WHERE id=%s AND production_id=%s', (wid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  KIOSK WAIVER CHECK
# ─────────────────────────────────────────────

@app.route('/api/kiosk/waiver-check')
def kiosk_waiver_check():
    vol_id   = request.args.get('volunteer_id')
    event_id = request.args.get('event_id')
    prod_id  = request.args.get('production_id')
    if not vol_id: return jsonify({'error': 'volunteer_id required'}), 400

    conn = get_db()
    today = date.today()

    # Get all volunteer's current valid waivers
    signed = fetchall(conn,
        'SELECT waiver_type_id, expiry_date, signed_date FROM volunteer_waivers WHERE volunteer_id=%s ORDER BY signed_date DESC',
        (vol_id,))
    # Build dict: waiver_type_id -> best status
    waiver_status = {}
    for w in signed:
        wid = w['waiver_type_id']
        if wid in waiver_status: continue  # already have a more recent one
        if not w['expiry_date']:
            waiver_status[wid] = 'valid'
        else:
            exp = datetime.strptime(w['expiry_date'], '%Y-%m-%d').date()
            diff = (exp - today).days
            if diff < 0: waiver_status[wid] = 'expired'
            elif diff < 30: waiver_status[wid] = 'expiring'
            else: waiver_status[wid] = 'valid'

    # Collect required waiver type IDs
    required_ids = set()

    # Level 1 — required for all
    all_required = fetchall(conn, "SELECT id FROM waiver_types WHERE COALESCE(required_all,FALSE)=TRUE")
    for r in all_required:
        required_ids.add(r['id'])

    # Level 2 — event specific
    if event_id:
        event_req = fetchall(conn, 'SELECT waiver_type_id FROM event_waivers WHERE event_id=%s', (event_id,))
        for r in event_req:
            required_ids.add(r['waiver_type_id'])

    # Level 2 — production specific
    if prod_id:
        prod_req = fetchall(conn, 'SELECT waiver_type_id FROM production_waivers WHERE production_id=%s', (prod_id,))
        for r in prod_req:
            required_ids.add(r['waiver_type_id'])

    # Build issues list
    issues = []
    for wt_id in required_ids:
        wt = fetchone(conn, 'SELECT * FROM waiver_types WHERE id=%s', (wt_id,))
        if not wt: continue
        status = waiver_status.get(wt_id, 'missing')
        if status in ('missing', 'expired', 'expiring'):
            issues.append({
                'waiver_type_id': wt_id,
                'name': wt['name'],
                'description': wt['description'],
                'template_body': wt['template_body'],
                'status': status,
                'can_sign_online': bool(wt['template_body'])
            })

    conn.close()
    return jsonify({'issues': issues, 'all_clear': len(issues) == 0})

# ─────────────────────────────────────────────
#  KIOSK WAIVER SIGN
# ─────────────────────────────────────────────

@app.route('/api/kiosk/sign-waiver', methods=['POST'])
def kiosk_sign_waiver():
    d = request.json
    vol_id         = d.get('volunteer_id')
    waiver_type_id = d.get('waiver_type_id')
    signed_name    = d.get('signed_name', '').strip()
    if not vol_id or not waiver_type_id or not signed_name:
        return jsonify({'error': 'Missing required fields'}), 400
    today = date.today().isoformat()
    exp   = date(date.today().year + 1, date.today().month, date.today().day).isoformat()
    wid   = str(uuid.uuid4())
    conn  = get_db()
    vol = fetchone(conn, "SELECT name FROM volunteers WHERE id=%s", (vol_id,))
    if not vol: conn.close(); return jsonify({'error': 'Volunteer not found'}), 404
    execute(conn,
        "INSERT INTO volunteer_waivers (id,volunteer_id,waiver_type_id,signed_date,expiry_date,signed_name,signed_via,uploaded_by) VALUES (%s,%s,%s,%s,%s,%s,'kiosk',%s)",
        (wid, vol_id, waiver_type_id, today, exp, signed_name, 'Kiosk self-sign'))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  PENDING PROFILE UPDATES
# ─────────────────────────────────────────────

@app.route('/api/kiosk/update-profile', methods=['POST'])
def kiosk_update_profile():
    d = request.json
    vol_id = d.get('volunteer_id')
    updates = d.get('updates', [])  # list of {field_name, old_value, new_value}
    if not vol_id or not updates:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    vol = fetchone(conn, "SELECT id FROM volunteers WHERE id=%s AND status='active'", (vol_id,))
    if not vol: conn.close(); return jsonify({'error': 'Volunteer not found'}), 404
    for u in updates:
        execute(conn,
            "INSERT INTO pending_profile_updates (id,volunteer_id,field_name,old_value,new_value) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), vol_id, u['field_name'], u.get('old_value',''), u['new_value']))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-profile-updates')
def get_pending_profile_updates():
    err = require_admin()
    if err: return err
    conn = get_db()
    rows = fetchall(conn,
        "SELECT pu.*, v.name as volunteer_name FROM pending_profile_updates pu JOIN volunteers v ON pu.volunteer_id=v.id WHERE pu.status='pending' ORDER BY pu.submitted_at DESC")
    conn.close()
    return jsonify(rows)

@app.route('/api/pending-profile-updates/<uid>/approve', methods=['POST'])
def approve_profile_update(uid):
    err = require_admin()
    if err: return err
    conn = get_db()
    pu = fetchone(conn, 'SELECT * FROM pending_profile_updates WHERE id=%s', (uid,))
    if not pu: conn.close(); return jsonify({'error': 'Not found'}), 404

    field = pu['field_name']
    new_val = pu['new_value']

    if field == 'phone':
        execute(conn, 'UPDATE volunteers SET phone=%s WHERE id=%s', (new_val, pu['volunteer_id']))
    elif field == 'interests':
        execute(conn, 'UPDATE volunteers SET interests=%s WHERE id=%s', (new_val, pu['volunteer_id']))
    elif field == 'emergency_contact':
        try:
            ec = json.loads(new_val)
            # Delete old and insert new
            execute(conn, 'DELETE FROM volunteer_emergency_contacts WHERE volunteer_id=%s', (pu['volunteer_id'],))
            execute(conn,
                'INSERT INTO volunteer_emergency_contacts (id,volunteer_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), pu['volunteer_id'], ec.get('name',''), ec.get('relationship',''), ec.get('phone','')))
        except Exception:
            pass

    execute(conn, "UPDATE pending_profile_updates SET status='approved' WHERE id=%s", (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-profile-updates/<uid>/reject', methods=['POST'])
def reject_profile_update(uid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE pending_profile_updates SET status='rejected' WHERE id=%s", (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-profile-updates/count')
def pending_profile_updates_count():
    err = require_auth()
    if err: return err
    conn = get_db()
    count = fetchone(conn, "SELECT COUNT(*) as c FROM pending_profile_updates WHERE status='pending'")['c']
    conn.close()
    return jsonify({'count': count})

# ─────────────────────────────────────────────
#  EVENT TYPES
# ─────────────────────────────────────────────

@app.route('/api/event-types')
def get_event_types():
    err = require_auth()
    if err: return err
    conn = get_db()
    types = fetchall(conn, 'SELECT * FROM event_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/event-types', methods=['POST'])
def create_event_type():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip(): return jsonify({'error': 'Name required'}), 400
    tid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO event_types (id,name,color) VALUES (%s,%s,%s)',
                (tid, d['name'].strip(), d.get('color','blue')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Event type already exists'}), 400
    row = fetchone(conn, 'SELECT * FROM event_types WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/event-types/<tid>', methods=['DELETE'])
def delete_event_type(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_types WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  ELICS
# ─────────────────────────────────────────────

@app.route('/api/elics')
def get_elics():
    err = require_auth()
    if err: return err
    conn = get_db()
    elics = fetchall(conn, '''SELECT e.*, v.name as volunteer_name, v.phone as volunteer_phone
        FROM elics e JOIN volunteers v ON e.volunteer_id=v.id ORDER BY v.name''')
    conn.close()
    return jsonify(elics)

@app.route('/api/elics', methods=['POST'])
def create_elic():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('volunteer_id') or not d.get('pin'):
        return jsonify({'error': 'Volunteer and PIN are required'}), 400
    if len(str(d['pin'])) != 4 or not str(d['pin']).isdigit():
        return jsonify({'error': 'PIN must be exactly 4 digits'}), 400
    eid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO elics (id,volunteer_id,pin,is_master,active,notes) VALUES (%s,%s,%s,%s,%s,%s)',
                (eid, d['volunteer_id'], d['pin'], d.get('is_master', False), True, d.get('notes','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'This volunteer is already an ELIC'}), 400
    row = fetchone(conn, '''SELECT e.*, v.name as volunteer_name FROM elics e
        JOIN volunteers v ON e.volunteer_id=v.id WHERE e.id=%s''', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/elics/<eid>', methods=['PUT'])
def update_elic(eid):
    err = require_admin()
    if err: return err
    d = request.json
    if d.get('pin') and (len(str(d['pin'])) != 4 or not str(d['pin']).isdigit()):
        return jsonify({'error': 'PIN must be exactly 4 digits'}), 400
    conn = get_db()
    execute(conn, 'UPDATE elics SET pin=%s,is_master=%s,active=%s,notes=%s WHERE id=%s',
            (d['pin'], d.get('is_master', False), d.get('active', True), d.get('notes',''), eid))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*, v.name as volunteer_name FROM elics e
        JOIN volunteers v ON e.volunteer_id=v.id WHERE e.id=%s''', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/elics/<eid>', methods=['DELETE'])
def delete_elic(eid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM elics WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  EVENT ELIC ASSIGNMENTS
# ─────────────────────────────────────────────

@app.route('/api/events/<evid>/elics', methods=['POST'])
def assign_event_elic(evid):
    err = require_admin()
    if err: return err
    d = request.json
    rid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO event_elics (id,event_id,elic_id) VALUES (%s,%s,%s)',
                (rid, evid, d['elic_id']))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Already assigned'}), 400
    row = fetchone(conn, '''SELECT ee.*, e.volunteer_id, v.name as volunteer_name
        FROM event_elics ee JOIN elics e ON ee.elic_id=e.id
        JOIN volunteers v ON e.volunteer_id=v.id WHERE ee.id=%s''', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/<evid>/elics/<rid>', methods=['DELETE'])
def remove_event_elic(evid, rid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_elics WHERE id=%s AND event_id=%s', (rid, evid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  CHECKLIST TEMPLATE
# ─────────────────────────────────────────────

@app.route('/api/checklist-items')
def get_checklist_items():
    err = require_auth()
    if err: return err
    conn = get_db()
    items = fetchall(conn, 'SELECT * FROM checklist_items ORDER BY sort_order, created_at')
    conn.close()
    return jsonify(items)

@app.route('/api/checklist-items', methods=['POST'])
def create_checklist_item():
    err = require_admin()
    if err: return err
    d = request.json
    cid = str(uuid.uuid4())
    conn = get_db()
    max_order = fetchone(conn, 'SELECT COALESCE(MAX(sort_order),0)+1 as n FROM checklist_items')['n']
    execute(conn, 'INSERT INTO checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s)',
            (cid, d['label'], d.get('item_type','checkbox'), d.get('required', True), max_order, d.get('hint','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM checklist_items WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/checklist-items/<cid>', methods=['PUT'])
def update_checklist_item(cid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE checklist_items SET label=%s,item_type=%s,required=%s,hint=%s WHERE id=%s',
            (d['label'], d.get('item_type','checkbox'), d.get('required',True), d.get('hint',''), cid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM checklist_items WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/checklist-items/<cid>', methods=['DELETE'])
def delete_checklist_item(cid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM checklist_items WHERE id=%s', (cid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  EVENT LOGS
# ─────────────────────────────────────────────

@app.route('/api/event-logs')
def get_event_logs():
    err = require_auth()
    if err: return err
    conn = get_db()
    logs = fetchall(conn, '''SELECT el.*, e.name as event_name, e.event_date,
        v.name as elic_name
        FROM event_logs el
        JOIN events e ON el.event_id=e.id
        JOIN elics ec ON el.elic_id=ec.id
        JOIN volunteers v ON ec.volunteer_id=v.id
        ORDER BY el.timestamp DESC LIMIT 100''')
    for log in logs:
        if log['action'] == 'close':
            log['checklist'] = fetchall(conn,
                'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY created_at', (log['id'],))
    conn.close()
    return jsonify(logs)

# ─────────────────────────────────────────────
#  KIOSK ELIC FLOW
# ─────────────────────────────────────────────

@app.route('/api/kiosk/elic-login', methods=['POST'])
def kiosk_elic_login():
    d = request.json
    pin = str(d.get('pin', '')).strip()
    if len(pin) != 4:
        return jsonify({'error': 'Invalid PIN'}), 401
    conn = get_db()
    elic = fetchone(conn, '''SELECT e.*, v.name as volunteer_name, v.phone as volunteer_phone
        FROM elics e JOIN volunteers v ON e.volunteer_id=v.id
        WHERE e.pin=%s AND e.active=TRUE''', (pin,))
    if not elic:
        conn.close()
        return jsonify({'error': 'Invalid PIN. Please try again or see an administrator.'}), 401
    # Get assigned events (or all if master)
    if elic['is_master']:
        events = fetchall(conn, '''SELECT e.*, el.id as log_id, el.action as current_status,
            COALESCE(p.stage,'mainstage') as stage, p.name as production_name
            FROM events e
            LEFT JOIN productions p ON e.production_id=p.id
            LEFT JOIN LATERAL (
                SELECT id, action FROM event_logs
                WHERE event_id=e.id ORDER BY timestamp DESC LIMIT 1
            ) el ON true
            ORDER BY e.event_date DESC NULLS LAST''')
    else:
        events = fetchall(conn, '''SELECT e.*, el2.id as log_id, el2.action as current_status,
            COALESCE(p.stage,'mainstage') as stage, p.name as production_name
            FROM event_elics ee
            JOIN events e ON ee.event_id=e.id
            JOIN elics ec ON ee.elic_id=ec.id
            LEFT JOIN productions p ON e.production_id=p.id
            LEFT JOIN LATERAL (
                SELECT id, action FROM event_logs
                WHERE event_id=e.id ORDER BY timestamp DESC LIMIT 1
            ) el2 ON true
            WHERE ec.id=%s
            ORDER BY e.event_date DESC NULLS LAST''', (elic['id'],))
    conn.close()
    return jsonify({'elic': elic, 'events': events})

@app.route('/api/kiosk/open-event', methods=['POST'])
def kiosk_open_event():
    d = request.json
    elic_id  = d.get('elic_id')
    event_id = d.get('event_id')
    if not elic_id or not event_id:
        return jsonify({'error': 'Missing fields'}), 400
    lid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, "INSERT INTO event_logs (id,event_id,elic_id,action) VALUES (%s,%s,%s,'open')",
            (lid, event_id, elic_id))
    execute(conn, "UPDATE events SET status='open' WHERE id=%s", (event_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'log_id': lid})

@app.route('/api/kiosk/close-event', methods=['POST'])
def kiosk_close_event():
    d = request.json
    elic_id   = d.get('elic_id')
    event_id  = d.get('event_id')
    responses = d.get('responses', [])
    if not elic_id or not event_id:
        return jsonify({'error': 'Missing fields'}), 400
    lid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, "INSERT INTO event_logs (id,event_id,elic_id,action) VALUES (%s,%s,%s,'close')",
            (lid, event_id, elic_id))
    execute(conn, "UPDATE events SET status='closed' WHERE id=%s", (event_id,))
    for r in responses:
        execute(conn,
            'INSERT INTO event_checklist_responses (id,event_log_id,checklist_item_id,label,item_type,response) VALUES (%s,%s,%s,%s,%s,%s)',
            (str(uuid.uuid4()), lid, r.get('item_id',''), r['label'], r['item_type'], r.get('response','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/event-status/<event_id>')
def kiosk_event_status(event_id):
    conn = get_db()
    evt = fetchone(conn, "SELECT status FROM events WHERE id=%s", (event_id,))
    conn.close()
    if not evt: return jsonify({'error': 'Not found'}), 404
    return jsonify({'status': evt['status'] or 'draft'})


# ─────────────────────────────────────────────
#  OPENING CHECKLIST TEMPLATE
# ─────────────────────────────────────────────

@app.route('/api/opening-checklist-items')
def get_opening_checklist_items():
    err = require_auth()
    if err: return err
    conn = get_db()
    items = fetchall(conn, 'SELECT * FROM opening_checklist_items ORDER BY sort_order, created_at')
    conn.close()
    return jsonify(items)

@app.route('/api/opening-checklist-items', methods=['POST'])
def create_opening_checklist_item():
    err = require_admin()
    if err: return err
    d = request.json
    cid = str(uuid.uuid4())
    conn = get_db()
    max_order = fetchone(conn, 'SELECT COALESCE(MAX(sort_order),0)+1 as n FROM opening_checklist_items')['n']
    execute(conn, 'INSERT INTO opening_checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s)',
            (cid, d['label'], d.get('item_type','checkbox'), d.get('required',True), max_order, d.get('hint','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM opening_checklist_items WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/opening-checklist-items/<cid>', methods=['PUT'])
def update_opening_checklist_item(cid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE opening_checklist_items SET label=%s,item_type=%s,required=%s,hint=%s WHERE id=%s',
            (d['label'], d.get('item_type','checkbox'), d.get('required',True), d.get('hint',''), cid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM opening_checklist_items WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/opening-checklist-items/<cid>', methods=['DELETE'])
def delete_opening_checklist_item(cid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM opening_checklist_items WHERE id=%s', (cid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  KIOSK OPEN EVENT WITH CHECKLIST
# ─────────────────────────────────────────────

@app.route('/api/kiosk/opening-checklist-items')
def kiosk_opening_checklist():
    items = []
    conn = get_db()
    items = fetchall(conn, 'SELECT * FROM opening_checklist_items ORDER BY sort_order')
    conn.close()
    return jsonify(items)

# Override open-event to support checklist responses
@app.route('/api/kiosk/open-event-checklist', methods=['POST'])
def kiosk_open_event_checklist():
    d = request.json
    elic_id   = d.get('elic_id')
    event_id  = d.get('event_id')
    responses = d.get('responses', [])
    if not elic_id or not event_id:
        return jsonify({'error': 'Missing fields'}), 400
    lid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, "INSERT INTO event_logs (id,event_id,elic_id,action) VALUES (%s,%s,%s,'open')",
            (lid, event_id, elic_id))
    execute(conn, "UPDATE events SET status='open' WHERE id=%s", (event_id,))
    for r in responses:
        execute(conn,
            'INSERT INTO event_checklist_responses (id,event_log_id,checklist_item_id,label,item_type,response) VALUES (%s,%s,%s,%s,%s,%s)',
            (str(uuid.uuid4()), lid, r.get('item_id',''), r['label'], r['item_type'], r.get('response','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'log_id': lid})

# ─────────────────────────────────────────────
#  YOUTH PARENT SIGN-IN/OUT
# ─────────────────────────────────────────────

@app.route('/api/youth-sign-ins')
def get_youth_sign_ins():
    err = require_auth()
    if err: return err
    event_id = request.args.get('event_id')
    program_id = request.args.get('program_id')
    conn = get_db()
    youth_id = request.args.get('youth_id')
    sql = '''SELECT ys.*, y.first_name, y.last_name
        FROM youth_sign_ins ys
        JOIN youth_participants y ON ys.youth_id=y.id
        WHERE 1=1'''
    params = []
    if event_id:
        sql += ' AND ys.event_id=%s'; params.append(event_id)
    if program_id:
        sql += ' AND ys.program_id=%s'; params.append(program_id)
    if youth_id:
        sql += ' AND ys.youth_id=%s'; params.append(youth_id)
    sql += ' ORDER BY ys.created_at DESC'
    rows = fetchall(conn, sql, params)
    conn.close()
    return jsonify(rows)

@app.route('/api/youth-sign-ins', methods=['POST'])
def create_youth_sign_in():
    err = require_auth()
    if err: return err
    d = request.json
    sid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO youth_sign_ins (id,youth_id,event_id,program_id,signed_in_at,signed_in_by)
        VALUES (%s,%s,%s,%s,NOW(),%s)''',
        (sid, d['youth_id'], d.get('event_id'), d.get('program_id'), d.get('signed_in_by','')))
    conn.commit()
    row = fetchone(conn, '''SELECT ys.*, y.first_name, y.last_name
        FROM youth_sign_ins ys JOIN youth_participants y ON ys.youth_id=y.id WHERE ys.id=%s''', (sid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-sign-ins/<sid>/sign-out', methods=['POST'])
def youth_sign_out(sid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by=%s WHERE id=%s',
            (d.get('signed_out_by',''), sid))
    conn.commit()
    row = fetchone(conn, '''SELECT ys.*, y.first_name, y.last_name
        FROM youth_sign_ins ys JOIN youth_participants y ON ys.youth_id=y.id WHERE ys.id=%s''', (sid,))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  USER ROLE MANAGEMENT
# ─────────────────────────────────────────────

@app.route('/api/users/<uid>/role', methods=['PUT'])
def update_user_role(uid):
    err = require_admin()
    if err: return err
    d = request.json
    valid_roles = ['admin', 'board', 'instructor', 'elic']
    if d.get('role') not in valid_roles:
        return jsonify({'error': f'Role must be one of: {", ".join(valid_roles)}'}), 400
    conn = get_db()
    execute(conn, 'UPDATE users SET role=%s WHERE id=%s', (d['role'], uid))
    conn.commit()
    user = fetchone(conn, 'SELECT id,name,email,role,COALESCE(active,TRUE) as active FROM users WHERE id=%s', (uid,))
    conn.close()
    return jsonify(user)


# ─────────────────────────────────────────────
#  KIOSK PRODUCTION SIGN-IN/OUT
# ─────────────────────────────────────────────

@app.route('/api/kiosk/production-roster/<event_id>')
def kiosk_production_roster(event_id):
    """Get the cast/crew roster for a production event, with their current sign-in status."""
    conn = get_db()
    evt = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (event_id,))
    if not evt or not evt.get('production_id'):
        conn.close()
        return jsonify({'error': 'Not a production event'}), 404
    prod_info = fetchone(conn, "SELECT id, name, COALESCE(stage,'mainstage') as stage FROM productions WHERE id=%s", (evt['production_id'],))

    members = fetchall(conn, '''
        SELECT pm.id as member_id, pm.volunteer_id, pm.role, pm.department, pm.status,
               v.name as volunteer_name, v.phone as volunteer_phone
        FROM production_members pm
        JOIN volunteers v ON pm.volunteer_id=v.id
        WHERE pm.production_id=%s AND pm.status != 'dropped'
        ORDER BY pm.department, v.name
    ''', (evt['production_id'],))

    # Check which are currently signed in (have pending_hours for this event with no end)
    # We use a simple attendance flag — signed_in_at in a prod_attendance table
    # For now use a simple lookup in our new prod_attendance table
    attendance = fetchall(conn,
        "SELECT * FROM prod_attendance WHERE event_id=%s",
        (event_id,))
    att_by_vol = {a['volunteer_id']: a for a in attendance}

    for m in members:
        att = att_by_vol.get(m['volunteer_id'])
        m['signed_in'] = att is not None and att.get('signed_out_at') is None
        m['attendance_id'] = att['id'] if att else None
        m['signed_in_at'] = att['signed_in_at'] if att else None

    conn.close()
    return jsonify({
        'event': evt,
        'production_name': prod_info['name'] if prod_info else '',
        'stage': prod_info['stage'] if prod_info else 'mainstage',
        'production_id': evt['production_id'],
        'members': members
    })

@app.route('/api/kiosk/production-signin', methods=['POST'])
def kiosk_production_signin():
    d = request.json
    volunteer_id = d.get('volunteer_id')
    event_id     = d.get('event_id')
    if not volunteer_id or not event_id:
        return jsonify({'error': 'Missing fields'}), 400
    conn = get_db()
    # Check not already signed in
    existing = fetchone(conn,
        "SELECT id FROM prod_attendance WHERE volunteer_id=%s AND event_id=%s AND signed_out_at IS NULL",
        (volunteer_id, event_id))
    if existing:
        conn.close()
        return jsonify({'error': 'Already signed in'}), 400
    aid = str(uuid.uuid4())
    execute(conn,
        "INSERT INTO prod_attendance (id,volunteer_id,event_id,signed_in_at) VALUES (%s,%s,%s,NOW())",
        (aid, volunteer_id, event_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'attendance_id': aid})

@app.route('/api/kiosk/production-signout', methods=['POST'])
def kiosk_production_signout():
    d = request.json
    attendance_id = d.get('attendance_id')
    volunteer_id  = d.get('volunteer_id')
    event_id      = d.get('event_id')
    if not attendance_id:
        return jsonify({'error': 'Missing attendance_id'}), 400
    conn = get_db()
    # Get sign-in time to calculate hours
    att = fetchone(conn, 'SELECT * FROM prod_attendance WHERE id=%s', (attendance_id,))
    if not att:
        conn.close()
        return jsonify({'error': 'Attendance record not found'}), 404

    execute(conn, 'UPDATE prod_attendance SET signed_out_at=NOW() WHERE id=%s', (attendance_id,))

    # Auto-submit hours to pending_hours
    evt = fetchone(conn, 'SELECT name FROM events WHERE id=%s', (event_id,))
    # Calculate hours from sign-in to now
    from datetime import timezone
    signed_in = att['signed_in_at']
    if hasattr(signed_in, 'replace'):
        now = datetime.now(timezone.utc) if signed_in.tzinfo else datetime.now()
        elapsed = (now - signed_in).total_seconds() / 3600
        hours = max(0.5, round(elapsed * 2) / 2)  # round to nearest 0.5
    else:
        hours = 1.0

    pid = str(uuid.uuid4())
    execute(conn,
        "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,'Kiosk production sign-in','pending')",
        (pid, volunteer_id, evt['name'] if evt else 'Production Event', event_id,
         date.today().isoformat(), hours, d.get('role','')))
    conn.commit()
    vol = fetchone(conn, 'SELECT name FROM volunteers WHERE id=%s', (volunteer_id,))
    conn.close()
    return jsonify({'ok': True, 'hours': hours, 'volunteer_name': vol['name'] if vol else ''})


# ─────────────────────────────────────────────
#  YOUTH AUTHORIZED PICKUPS
# ─────────────────────────────────────────────

@app.route('/api/youth/<yid>/authorized-pickups')
def get_authorized_pickups(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn,
        'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority, created_at',
        (yid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/youth/<yid>/authorized-pickups', methods=['POST'])
def add_authorized_pickup(yid):
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip():
        return jsonify({'error': 'Name is required'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    # Get next priority
    max_p = fetchone(conn, 'SELECT COALESCE(MAX(priority),0)+1 as n FROM youth_authorized_pickups WHERE youth_id=%s', (yid,))['n']
    execute(conn,
        'INSERT INTO youth_authorized_pickups (id,youth_id,name,relationship,phone,priority,notes) VALUES (%s,%s,%s,%s,%s,%s,%s)',
        (pid, yid, d['name'].strip(), d.get('relationship',''), d.get('phone',''), max_p, d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_authorized_pickups WHERE id=%s', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/<yid>/authorized-pickups/<pid>', methods=['DELETE'])
def delete_authorized_pickup(yid, pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_authorized_pickups WHERE id=%s AND youth_id=%s', (pid, yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/authorized-pickups/<yid>')
def kiosk_authorized_pickups(yid):
    """No auth needed — used by kiosk for sign-in/out."""
    conn = get_db()
    rows = fetchall(conn,
        'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority, created_at',
        (yid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/kiosk/unauthorized-pickup-notify', methods=['POST'])
def notify_unauthorized_pickup():
    """ELIC overrode authorized list — submit to pending updates for admin review."""
    d = request.json
    yid = d.get('youth_id')
    name = d.get('pickup_name','')
    action = d.get('action','pickup')  # 'dropoff' or 'pickup'
    conn = get_db()
    execute(conn,
        "INSERT INTO pending_profile_updates (id,volunteer_id,field_name,old_value,new_value,status) VALUES (%s,%s,%s,%s,%s,'pending')",
        (str(uuid.uuid4()), yid,
         f'youth_unauthorized_{action}',
         '',
         json.dumps({'youth_id': yid, 'name': name, 'action': action, 'note': 'Not on authorized list — consider adding'})))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

