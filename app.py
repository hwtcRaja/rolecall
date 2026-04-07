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

DATABASE_URL = os.environ.get('DATABASE_URL')
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

    # Add emergency contact fields to volunteer_waivers
    try:
        c.execute('ALTER TABLE volunteer_waivers ADD COLUMN emergency_contact_name TEXT')
        c.execute('ALTER TABLE volunteer_waivers ADD COLUMN emergency_contact_phone TEXT')
        c.execute('ALTER TABLE volunteer_waivers ADD COLUMN emergency_contact_relationship TEXT')
        conn.commit()
    except Exception:
        conn.rollback()


    conn.commit()
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
    events = fetchall(conn, 'SELECT * FROM events ORDER BY event_date DESC NULLS LAST')
    conn.close()
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO events (id,name,event_date,description) VALUES (%s,%s,%s,%s)',
            (eid, d['name'], d.get('event_date') or None, d.get('description','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (eid,))
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
    vols = fetchall(conn, 'SELECT * FROM volunteers ORDER BY name')
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
    execute(conn, 'INSERT INTO volunteers (id,name,email,phone,birthday,status,interests) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (vid, d['name'], d['email'], d.get('phone',''), d.get('birthday') or None, d.get('status','active'), json.dumps(d.get('interests',[]))))
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
    execute(conn, 'UPDATE volunteers SET name=%s,email=%s,phone=%s,birthday=%s,status=%s,interests=%s WHERE id=%s',
            (d['name'], d['email'], d.get('phone',''), d.get('birthday') or None, d.get('status','active'), json.dumps(d.get('interests',[])), vol_id))
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
        y['waivers'] = fetchall(conn,
            'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=%s ORDER BY yw.signed_date DESC', (y['id'],))
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
    y['waivers'] = fetchall(conn,
        'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=%s ORDER BY yw.signed_date DESC', (yid,))
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
#  RUN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print('\n🎭 RollCall is running!')
    print('   Open http://localhost:5000 in your browser\n')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
