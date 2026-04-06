from flask import Flask, request, jsonify, session, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
import hashlib
import os
import uuid
import json
from datetime import datetime, date
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.secret_key = 'rollcall-secret-key-change-in-production'
CORS(app, supports_credentials=True)

DB_PATH = 'rollcall.db'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'board'
        );

        CREATE TABLE IF NOT EXISTS interest_types (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            color TEXT DEFAULT 'gray',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS volunteers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            birthday TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            interests TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            event_date TEXT,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS hours (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            event TEXT NOT NULL,
            event_id TEXT,
            date TEXT NOT NULL,
            hours REAL NOT NULL,
            role TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS volunteer_history (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            event TEXT NOT NULL,
            role TEXT NOT NULL,
            date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS volunteer_files (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            name TEXT NOT NULL,
            size TEXT,
            type TEXT,
            date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS waiver_types (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            template_body TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS volunteer_waivers (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL,
            waiver_type_id TEXT NOT NULL,
            signed_date TEXT NOT NULL,
            expiry_date TEXT,
            filename TEXT,
            original_name TEXT,
            file_size TEXT,
            signed_name TEXT,
            signed_via TEXT DEFAULT 'upload',
            uploaded_by TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (volunteer_id) REFERENCES volunteers(id) ON DELETE CASCADE,
            FOREIGN KEY (waiver_type_id) REFERENCES waiver_types(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS email_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS youth_participants (
            id TEXT PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            dob TEXT,
            program TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            medical_notes TEXT,
            allergies TEXT,
            photo_consent INTEGER DEFAULT 0,
            medical_consent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS youth_guardians (
            id TEXT PRIMARY KEY,
            youth_id TEXT NOT NULL,
            name TEXT NOT NULL,
            relationship TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            is_primary INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (youth_id) REFERENCES youth_participants(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS youth_emergency_contacts (
            id TEXT PRIMARY KEY,
            youth_id TEXT NOT NULL,
            name TEXT NOT NULL,
            relationship TEXT,
            phone TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (youth_id) REFERENCES youth_participants(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS youth_waivers (
            id TEXT PRIMARY KEY,
            youth_id TEXT NOT NULL,
            waiver_type_id TEXT NOT NULL,
            signed_date TEXT NOT NULL,
            expiry_date TEXT,
            signed_by TEXT,
            filename TEXT,
            original_name TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (youth_id) REFERENCES youth_participants(id) ON DELETE CASCADE
        );
    ''')

    def hash_pw(pw):
        return hashlib.sha256(pw.encode()).hexdigest()

    # Seed users
    for u in [
        (str(uuid.uuid4()), 'Aria Montgomery', 'admin@horizonwest.org', hash_pw('admin123'), 'admin'),
        (str(uuid.uuid4()), 'Marcus Chen',     'board@horizonwest.org', hash_pw('board123'), 'board'),
    ]:
        c.execute('INSERT OR IGNORE INTO users (id,name,email,password_hash,role) VALUES (?,?,?,?,?)', u)

    # Seed interest types
    for it in [
        (str(uuid.uuid4()), 'Performance',    'teal'),
        (str(uuid.uuid4()), 'Painting',       'pink'),
        (str(uuid.uuid4()), 'Front of House', 'blue'),
        (str(uuid.uuid4()), 'Technical',      'amber'),
        (str(uuid.uuid4()), 'Other',          'gray'),
    ]:
        c.execute('INSERT OR IGNORE INTO interest_types (id,name,color) VALUES (?,?,?)', it)

    # Seed waiver types
    for wt in [
        (str(uuid.uuid4()), 'General Liability',     'Standard liability waiver for all volunteers',
         'By signing this waiver, I agree to hold harmless Horizon West Theater from any injury or damages that may occur during my volunteer service.'),
        (str(uuid.uuid4()), 'Minor Waiver',          'Required for volunteers under 18',
         'As parent or legal guardian, I hereby grant permission for the above named minor to participate in volunteer activities at Horizon West Theater.'),
        (str(uuid.uuid4()), 'Media Release',         'Permission to use photos and video',
         'I grant Horizon West Theater the right to use photographs and video footage taken of me during events for promotional and educational purposes.'),
        (str(uuid.uuid4()), 'COVID Health Screening','Health screening acknowledgment',
         'I confirm that I am not experiencing COVID-19 symptoms and agree to follow all health and safety protocols established by Horizon West Theater.'),
    ]:
        c.execute('INSERT OR IGNORE INTO waiver_types (id,name,description,template_body) VALUES (?,?,?,?)', wt)

    # Seed email templates
    for et in [
        (str(uuid.uuid4()), 'Event Reminder',    'Reminder: Upcoming Event',
         'Hi {name},\n\nThis is a reminder that you are signed up for our upcoming event. Please arrive 15 minutes early.\n\nThank you for volunteering!\nHorizon West Theater'),
        (str(uuid.uuid4()), 'Waiver Expiring',   'Action Required: Your Waiver is Expiring',
         'Hi {name},\n\nYour volunteer waiver will expire soon. Please stop by or contact us to renew it before your next event.\n\nThank you,\nHorizon West Theater'),
        (str(uuid.uuid4()), 'Thank You',         'Thank You for Volunteering!',
         'Hi {name},\n\nThank you so much for volunteering with us. Your time and dedication mean everything to our organization.\n\nWith gratitude,\nHorizon West Theater'),
    ]:
        c.execute('INSERT OR IGNORE INTO email_templates (id,name,subject,body) VALUES (?,?,?,?)', et)

    # Seed events
    for ev in [
        (str(uuid.uuid4()), 'Mamma Mia!',        '2025-03-01', 'Spring musical production'),
        (str(uuid.uuid4()), 'Holiday Gala 2024', '2024-12-15', 'Annual holiday fundraiser'),
        (str(uuid.uuid4()), 'Spring Showcase',   '2025-04-05', 'Student showcase performance'),
        (str(uuid.uuid4()), 'Rent',              '2025-02-14', 'Valentine weekend production'),
        (str(uuid.uuid4()), 'Set Build Weekend', '2025-01-20', 'Set construction for spring show'),
    ]:
        c.execute('INSERT OR IGNORE INTO events (id,name,event_date,description) VALUES (?,?,?,?)', ev)

    # Seed volunteers
    for v in [
        ('v1','Sophie Larkin',    'sophie@email.com', '(555)201-3344','1994-03-12','active',   '["Performance","Front of House"]'),
        ('v2','Darius Wells',     'darius@email.com', '(555)888-2211','1989-07-22','active',   '["Technical","Painting"]'),
        ('v3','Priya Nandakumar','priya@email.com',  '(555)334-9012','1997-11-05','active',   '["Performance","Technical"]'),
        ('v4','Tomasz Bryl',      'tomasz@email.com', '(555)774-0023','1985-05-30','active',   '["Painting","Other"]'),
        ('v5','Yuki Tanaka',      'yuki@email.com',   '(555)121-5566','2000-08-18','inactive', '["Front of House"]'),
        ('v6','Ramon Delgado',    'ramon@email.com',  '(555)902-3344','1991-12-03','active',   '["Performance","Front of House"]'),
    ]:
        c.execute('INSERT OR IGNORE INTO volunteers (id,name,email,phone,birthday,status,interests) VALUES (?,?,?,?,?,?,?)', v)

    # Seed hours
    for h in [
        ('hr1','v1','Mamma Mia!','2025-03-01',6,'Ensemble','Dress rehearsal + performance'),
        ('hr2','v1','Holiday Gala 2024','2024-12-15',4,'FOH Lead',''),
        ('hr3','v1','Spring Showcase','2025-04-05',4,'Performer',''),
        ('hr4','v2','Rent','2025-02-14',8,'Lighting Technician','Rig setup + show'),
        ('hr5','v2','Set Build Weekend','2025-01-20',7,'Scenic Painter',''),
        ('hr6','v3','Spring Showcase','2025-04-05',5,'Stage Manager',''),
        ('hr7','v3','Mamma Mia!','2025-03-01',6,'ASM',''),
        ('hr8','v4','Mamma Mia!','2025-03-01',12,'Set Design Lead','Multi-day build'),
        ('hr9','v6','Holiday Gala 2024','2024-12-15',3,'Box Office',''),
    ]:
        c.execute('INSERT OR IGNORE INTO hours (id,volunteer_id,event,date,hours,role,notes) VALUES (?,?,?,?,?,?,?)', h)

    # Seed notes
    for n in [
        ('n1','v1','Aria Montgomery','Excellent stage presence. Recommended for lead roles.'),
        ('n2','v2','Marcus Chen','Skilled with lighting rigs. Available most weekends.'),
        ('n3','v5','Aria Montgomery','Went on leave — check back in fall 2025.'),
    ]:
        c.execute('INSERT OR IGNORE INTO notes (id,volunteer_id,author,content) VALUES (?,?,?,?)', n)

    # Seed history
    for h in [
        ('h1','v1','Mamma Mia!','Ensemble','2025-03-01','Standout performance'),
        ('h2','v1','Holiday Gala 2024','FOH Lead','2024-12-15',''),
        ('h3','v2','Rent','Lighting Technician','2025-02-14',''),
        ('h4','v2','Set Build Weekend','Scenic Painter','2025-01-20','Built flats for Act 2'),
        ('h5','v3','Spring Showcase','Stage Manager','2025-04-05',''),
        ('h6','v4','Mamma Mia!','Set Design Lead','2025-03-01',''),
        ('h7','v6','Holiday Gala 2024','Greeter / Box Office','2024-12-15',''),
    ]:
        c.execute('INSERT OR IGNORE INTO volunteer_history (id,volunteer_id,event,role,date,notes) VALUES (?,?,?,?,?,?)', h)

    # Seed youth participants
    for y in [
        ('y1','Emma','Rodriguez','2012-05-14','Summer Theater Camp','active','None','Peanuts',1,1),
        ('y2','Liam','Park','2013-08-22','Youth Acting Class','active','Asthma - has inhaler','None',1,0),
        ('y3','Zoe','Williams','2011-11-03','Junior Crew','active','','Tree nuts',0,1),
    ]:
        c.execute('INSERT OR IGNORE INTO youth_participants (id,first_name,last_name,dob,program,status,medical_notes,allergies,photo_consent,medical_consent) VALUES (?,?,?,?,?,?,?,?,?,?)', y)

    for g in [
        ('g1','y1','Maria Rodriguez','Mother','(555)301-2222','maria@email.com',1),
        ('g2','y1','Carlos Rodriguez','Father','(555)301-3333','carlos@email.com',0),
        ('g3','y2','Jin Park','Parent','(555)402-1111','jin@email.com',1),
        ('g4','y3','Sarah Williams','Mother','(555)503-4444','sarah@email.com',1),
    ]:
        c.execute('INSERT OR IGNORE INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (?,?,?,?,?,?,?)', g)

    for e in [
        ('e1','y1','Grandma Rosa','Grandmother','(555)301-9999'),
        ('e2','y2','Uncle Tom','Uncle','(555)402-8888'),
        ('e3','y3','Aunt Lisa','Aunt','(555)503-7777'),
    ]:
        c.execute('INSERT OR IGNORE INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (?,?,?,?,?)', e)

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

def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]

def get_waiver_summary(conn, vol_id):
    waivers = rows_to_list(conn.execute(
        'SELECT vw.*, wt.name as type_name FROM volunteer_waivers vw JOIN waiver_types wt ON vw.waiver_type_id=wt.id WHERE vw.volunteer_id=? ORDER BY vw.signed_date DESC',
        (vol_id,)
    ).fetchall())
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
    user = row_to_dict(conn.execute('SELECT * FROM users WHERE email=? AND password_hash=?', (d['email'], pw_hash)).fetchone())
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
    types = rows_to_list(conn.execute('SELECT * FROM interest_types ORDER BY name').fetchall())
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
        conn.execute('INSERT INTO interest_types (id,name,color) VALUES (?,?,?)',
                     (tid, d['name'].strip(), d.get('color','gray')))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Interest type already exists'}), 400
    row = row_to_dict(conn.execute('SELECT * FROM interest_types WHERE id=?', (tid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/interest-types/<tid>', methods=['DELETE'])
def delete_interest_type(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM interest_types WHERE id=?', (tid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────

@app.route('/api/events')
def get_events():
    err = require_auth()
    if err: return err
    conn = get_db()
    events = rows_to_list(conn.execute('SELECT * FROM events ORDER BY event_date DESC').fetchall())
    conn.close()
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO events (id,name,event_date,description) VALUES (?,?,?,?)',
                 (eid, d['name'], d.get('event_date'), d.get('description','')))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM events WHERE id=?', (eid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>', methods=['DELETE'])
def delete_event(eid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM events WHERE id=?', (eid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  VOLUNTEERS
# ─────────────────────────────────────────────

@app.route('/api/volunteers')
def get_volunteers():
    err = require_auth()
    if err: return err
    conn = get_db()
    vols = rows_to_list(conn.execute('SELECT * FROM volunteers ORDER BY name').fetchall())
    for v in vols:
        v['total_hours'] = conn.execute('SELECT COALESCE(SUM(hours),0) as t FROM hours WHERE volunteer_id=?', (v['id'],)).fetchone()['t']
        v['waiver_status'], v['waivers'] = get_waiver_summary(conn, v['id'])
    conn.close()
    return jsonify(vols)

@app.route('/api/volunteers/<vol_id>')
def get_volunteer(vol_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    vol = row_to_dict(conn.execute('SELECT * FROM volunteers WHERE id=?', (vol_id,)).fetchone())
    if not vol: conn.close(); return jsonify({'error': 'Not found'}), 404
    vol['hours']   = rows_to_list(conn.execute('SELECT * FROM hours WHERE volunteer_id=? ORDER BY date DESC', (vol_id,)).fetchall())
    vol['notes']   = rows_to_list(conn.execute('SELECT * FROM notes WHERE volunteer_id=? ORDER BY created_at DESC', (vol_id,)).fetchall())
    vol['history'] = rows_to_list(conn.execute('SELECT * FROM volunteer_history WHERE volunteer_id=? ORDER BY date DESC', (vol_id,)).fetchall())
    vol['files']   = rows_to_list(conn.execute('SELECT * FROM volunteer_files WHERE volunteer_id=? ORDER BY created_at DESC', (vol_id,)).fetchall())
    vol['waiver_status'], vol['waivers'] = get_waiver_summary(conn, vol_id)
    vol['total_hours'] = conn.execute('SELECT COALESCE(SUM(hours),0) as t FROM hours WHERE volunteer_id=?', (vol_id,)).fetchone()['t']
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers', methods=['POST'])
def create_volunteer():
    err = require_admin()
    if err: return err
    d = request.json
    vid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO volunteers (id,name,email,phone,birthday,status,interests) VALUES (?,?,?,?,?,?,?)',
                 (vid, d['name'], d['email'], d.get('phone',''), d.get('birthday'), d.get('status','active'), json.dumps(d.get('interests',[]))))
    conn.commit()
    vol = row_to_dict(conn.execute('SELECT * FROM volunteers WHERE id=?', (vid,)).fetchone())
    vol['total_hours'] = 0; vol['waiver_status'] = 'none'; vol['waivers'] = []
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['PUT'])
def update_volunteer(vol_id):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    conn.execute('UPDATE volunteers SET name=?,email=?,phone=?,birthday=?,status=?,interests=? WHERE id=?',
                 (d['name'], d['email'], d.get('phone',''), d.get('birthday'), d.get('status','active'), json.dumps(d.get('interests',[])), vol_id))
    conn.commit()
    vol = row_to_dict(conn.execute('SELECT * FROM volunteers WHERE id=?', (vol_id,)).fetchone())
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['DELETE'])
def delete_volunteer(vol_id):
    err = require_admin()
    if err: return err
    conn = get_db()
    waivers = rows_to_list(conn.execute('SELECT filename FROM volunteer_waivers WHERE volunteer_id=?', (vol_id,)).fetchall())
    for w in waivers:
        if w['filename']:
            try: os.remove(os.path.join(UPLOAD_FOLDER, w['filename']))
            except: pass
    conn.execute('DELETE FROM volunteers WHERE id=?', (vol_id,))
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
    rows = rows_to_list(conn.execute(
        'SELECT h.*, v.name as volunteer_name, v.email as volunteer_email FROM hours h JOIN volunteers v ON h.volunteer_id=v.id ORDER BY h.date DESC'
    ).fetchall())
    conn.close()
    return jsonify(rows)

@app.route('/api/hours', methods=['POST'])
def create_hours():
    err = require_admin()
    if err: return err
    d = request.json
    hid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes) VALUES (?,?,?,?,?,?,?,?)',
                 (hid, d['volunteer_id'], d['event'], d.get('event_id'), d['date'], d['hours'], d.get('role',''), d.get('notes','')))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT h.*, v.name as volunteer_name FROM hours h JOIN volunteers v ON h.volunteer_id=v.id WHERE h.id=?', (hid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/hours/<hid>', methods=['DELETE'])
def delete_hours(hid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM hours WHERE id=?', (hid,))
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
    conn.execute('INSERT INTO notes (id,volunteer_id,author,content) VALUES (?,?,?,?)',
                 (nid, vol_id, session['user_name'], d['content']))
    conn.commit()
    note = row_to_dict(conn.execute('SELECT * FROM notes WHERE id=?', (nid,)).fetchone())
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
    conn.execute('INSERT INTO volunteer_history (id,volunteer_id,event,role,date,notes) VALUES (?,?,?,?,?,?)',
                 (hid, vol_id, d['event'], d['role'], d['date'], d.get('notes','')))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM volunteer_history WHERE id=?', (hid,)).fetchone())
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
    conn.execute('INSERT INTO volunteer_files (id,volunteer_id,name,size,type,date) VALUES (?,?,?,?,?,?)',
                 (fid, vol_id, d['name'], d.get('size',''), d.get('type',''), date.today().isoformat()))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM volunteer_files WHERE id=?', (fid,)).fetchone())
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
    types = rows_to_list(conn.execute('SELECT * FROM waiver_types ORDER BY name').fetchall())
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
        conn.execute('INSERT INTO waiver_types (id,name,description,template_body) VALUES (?,?,?,?)',
                     (tid, d['name'].strip(), d.get('description',''), d.get('template_body','')))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Waiver type already exists'}), 400
    row = row_to_dict(conn.execute('SELECT * FROM waiver_types WHERE id=?', (tid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/waiver-types/<tid>', methods=['PUT'])
def update_waiver_type(tid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    conn.execute('UPDATE waiver_types SET name=?,description=?,template_body=? WHERE id=?',
                 (d['name'], d.get('description',''), d.get('template_body',''), tid))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM waiver_types WHERE id=?', (tid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/waiver-types/<tid>', methods=['DELETE'])
def delete_waiver_type(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM waiver_types WHERE id=?', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# Public waiver signing page
@app.route('/api/waiver-types/<tid>/public')
def get_waiver_type_public(tid):
    conn = get_db()
    row = row_to_dict(conn.execute('SELECT id,name,description,template_body FROM waiver_types WHERE id=?', (tid,)).fetchone())
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
    conn.execute(
        'INSERT INTO volunteer_waivers (id,volunteer_id,waiver_type_id,signed_date,expiry_date,filename,original_name,file_size,signed_name,signed_via,uploaded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (wid, vol_id, waiver_type_id, signed_date, expiry_date, filename, original_name, file_size, signed_name, signed_via, session['user_name'])
    )
    conn.commit()
    row = row_to_dict(conn.execute(
        'SELECT vw.*, wt.name as type_name FROM volunteer_waivers vw JOIN waiver_types wt ON vw.waiver_type_id=wt.id WHERE vw.id=?', (wid,)
    ).fetchone())
    conn.close()
    return jsonify(row)

# Online waiver signing (public — no auth required)
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
    conn.execute(
        'INSERT INTO volunteer_waivers (id,volunteer_id,waiver_type_id,signed_date,expiry_date,signed_name,signed_via,uploaded_by) VALUES (?,?,?,?,?,?,?,?)',
        (wid, vol_id, waiver_type_id, today, exp, signed_name, 'online', 'Self-signed')
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'message': 'Waiver signed successfully'})

@app.route('/api/waivers/<wid>/download')
def download_waiver(wid):
    err = require_auth()
    if err: return err
    conn = get_db()
    w = row_to_dict(conn.execute('SELECT * FROM volunteer_waivers WHERE id=?', (wid,)).fetchone())
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
    w = row_to_dict(conn.execute('SELECT * FROM volunteer_waivers WHERE id=?', (wid,)).fetchone())
    if w and w['filename']:
        try: os.remove(os.path.join(UPLOAD_FOLDER, w['filename']))
        except: pass
    conn.execute('DELETE FROM volunteer_waivers WHERE id=?', (wid,))
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
    templates = rows_to_list(conn.execute('SELECT * FROM email_templates ORDER BY name').fetchall())
    conn.close()
    return jsonify(templates)

@app.route('/api/email-templates', methods=['POST'])
def create_email_template():
    err = require_admin()
    if err: return err
    d = request.json
    tid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO email_templates (id,name,subject,body) VALUES (?,?,?,?)',
                 (tid, d['name'], d['subject'], d['body']))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM email_templates WHERE id=?', (tid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/email-templates/<tid>', methods=['DELETE'])
def delete_email_template(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM email_templates WHERE id=?', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  YOUTH PARTICIPANTS
# ─────────────────────────────────────────────

@app.route('/api/youth')
def get_youth():
    err = require_auth()
    if err: return err
    conn = get_db()
    youth = rows_to_list(conn.execute('SELECT * FROM youth_participants ORDER BY last_name,first_name').fetchall())
    for y in youth:
        y['guardians'] = rows_to_list(conn.execute('SELECT * FROM youth_guardians WHERE youth_id=? ORDER BY is_primary DESC', (y['id'],)).fetchall())
        y['emergency_contacts'] = rows_to_list(conn.execute('SELECT * FROM youth_emergency_contacts WHERE youth_id=?', (y['id'],)).fetchall())
        y['waivers'] = rows_to_list(conn.execute(
            'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=? ORDER BY yw.signed_date DESC', (y['id'],)
        ).fetchall())
    conn.close()
    return jsonify(youth)

@app.route('/api/youth/<yid>')
def get_youth_participant(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    y = row_to_dict(conn.execute('SELECT * FROM youth_participants WHERE id=?', (yid,)).fetchone())
    if not y: conn.close(); return jsonify({'error': 'Not found'}), 404
    y['guardians'] = rows_to_list(conn.execute('SELECT * FROM youth_guardians WHERE youth_id=? ORDER BY is_primary DESC', (yid,)).fetchall())
    y['emergency_contacts'] = rows_to_list(conn.execute('SELECT * FROM youth_emergency_contacts WHERE youth_id=?', (yid,)).fetchall())
    y['waivers'] = rows_to_list(conn.execute(
        'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.youth_id=? ORDER BY yw.signed_date DESC', (yid,)
    ).fetchall())
    conn.close()
    return jsonify(y)

@app.route('/api/youth', methods=['POST'])
def create_youth():
    err = require_admin()
    if err: return err
    d = request.json
    yid = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        'INSERT INTO youth_participants (id,first_name,last_name,dob,program,status,medical_notes,allergies,photo_consent,medical_consent) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (yid, d['first_name'], d['last_name'], d.get('dob'), d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0)
    )
    # Add guardians
    for g in d.get('guardians', []):
        conn.execute('INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (?,?,?,?,?,?,?)',
                     (str(uuid.uuid4()), yid, g['name'], g.get('relationship',''), g.get('phone',''), g.get('email',''), 1 if g.get('is_primary') else 0))
    # Add emergency contact
    if d.get('emergency_name') and d.get('emergency_phone'):
        conn.execute('INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (?,?,?,?,?)',
                     (str(uuid.uuid4()), yid, d['emergency_name'], d.get('emergency_relationship',''), d['emergency_phone']))
    conn.commit()
    y = row_to_dict(conn.execute('SELECT * FROM youth_participants WHERE id=?', (yid,)).fetchone())
    y['guardians'] = rows_to_list(conn.execute('SELECT * FROM youth_guardians WHERE youth_id=?', (yid,)).fetchall())
    y['emergency_contacts'] = rows_to_list(conn.execute('SELECT * FROM youth_emergency_contacts WHERE youth_id=?', (yid,)).fetchall())
    y['waivers'] = []
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['PUT'])
def update_youth(yid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    conn.execute(
        'UPDATE youth_participants SET first_name=?,last_name=?,dob=?,program=?,status=?,medical_notes=?,allergies=?,photo_consent=?,medical_consent=? WHERE id=?',
        (d['first_name'], d['last_name'], d.get('dob'), d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0, yid)
    )
    conn.commit()
    y = row_to_dict(conn.execute('SELECT * FROM youth_participants WHERE id=?', (yid,)).fetchone())
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['DELETE'])
def delete_youth(yid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM youth_participants WHERE id=?', (yid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/guardians', methods=['POST'])
def add_guardian(yid):
    err = require_admin()
    if err: return err
    d = request.json
    gid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (?,?,?,?,?,?,?)',
                 (gid, yid, d['name'], d.get('relationship',''), d.get('phone',''), d.get('email',''), 1 if d.get('is_primary') else 0))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM youth_guardians WHERE id=?', (gid,)).fetchone())
    conn.close()
    return jsonify(row)

@app.route('/api/youth/guardians/<gid>', methods=['DELETE'])
def delete_guardian(gid):
    err = require_admin()
    if err: return err
    conn = get_db()
    conn.execute('DELETE FROM youth_guardians WHERE id=?', (gid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/emergency-contacts', methods=['POST'])
def add_emergency_contact(yid):
    err = require_admin()
    if err: return err
    d = request.json
    eid = str(uuid.uuid4())
    conn = get_db()
    conn.execute('INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (?,?,?,?,?)',
                 (eid, yid, d['name'], d.get('relationship',''), d['phone']))
    conn.commit()
    row = row_to_dict(conn.execute('SELECT * FROM youth_emergency_contacts WHERE id=?', (eid,)).fetchone())
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
    conn.execute('INSERT INTO youth_waivers (id,youth_id,waiver_type_id,signed_date,expiry_date,signed_by,filename,original_name) VALUES (?,?,?,?,?,?,?,?)',
                 (wid, yid, waiver_type_id, signed_date, expiry_date, signed_by, filename, original_name))
    conn.commit()
    row = row_to_dict(conn.execute(
        'SELECT yw.*, wt.name as type_name FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id WHERE yw.id=?', (wid,)
    ).fetchone())
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
    total_vols  = conn.execute('SELECT COUNT(*) as c FROM volunteers').fetchone()['c']
    total_hours = conn.execute('SELECT COALESCE(SUM(hours),0) as s FROM hours').fetchone()['s']
    total_youth = conn.execute('SELECT COUNT(*) as c FROM youth_participants WHERE status=\'active\'').fetchone()['c']
    today = date.today()
    all_waivers = rows_to_list(conn.execute(
        'SELECT vw.volunteer_id, vw.expiry_date, v.name FROM volunteer_waivers vw JOIN volunteers v ON vw.volunteer_id=v.id'
    ).fetchall())
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
        total = conn.execute("SELECT COALESCE(SUM(hours),0) as s FROM hours WHERE strftime('%Y-%m',date)=?", (f'{y:04d}-{m:02d}',)).fetchone()['s']
        monthly.append({'label': label, 'total': total})
    top = rows_to_list(conn.execute('''
        SELECT v.id, v.name, COALESCE(SUM(h.hours),0) as total_hours, COUNT(DISTINCT h.event) as total_events
        FROM volunteers v LEFT JOIN hours h ON v.id=h.volunteer_id
        GROUP BY v.id ORDER BY total_hours DESC LIMIT 5
    ''').fetchall())
    conn.close()
    return jsonify({'total_volunteers': total_vols, 'total_hours': total_hours, 'total_youth': total_youth,
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
        conn.execute('INSERT INTO users (id,name,email,password_hash,role) VALUES (?,?,?,?,?)',
                     (uid_, d['name'], d['email'], pw_hash, d.get('role','board')))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
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
    app.run(debug=True, port=5000)
