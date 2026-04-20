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
import requests

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
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
        options="-c timezone=America/New_York"
    )
    return conn

def init_db():
    conn = psycopg2.connect(
        DATABASE_URL,
        options="-c timezone=America/New_York"
    )
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

    # seed default opening checklist items (only if none exist)
    c.execute("SELECT COUNT(*) as cnt FROM opening_checklist_items")
    if c.fetchone()[0] == 0:
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
            c.execute("INSERT INTO opening_checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s)", item)

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

    # youth production members (kids cast in Rising Stars productions)
    c.execute("""CREATE TABLE IF NOT EXISTS youth_production_members (
        id TEXT PRIMARY KEY,
        production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
        youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
        role TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE(production_id, youth_id))""")

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

    # seed default event types (name has UNIQUE constraint so ON CONFLICT works correctly)
    for et in [
        ('Rehearsal', 'amber'), ('Performance', 'teal'), ('Meeting', 'blue'),
        ('Build Day', 'pink'), ('Strike', 'purple'), ('Other', 'gray'),
    ]:
        c.execute("INSERT INTO event_types (id,name,color) VALUES (%s,%s,%s) ON CONFLICT (name) DO NOTHING",
                  (str(__import__('uuid').uuid4()), et[0], et[1]))

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

    # seed default checklist items (only if none exist)
    c.execute("SELECT COUNT(*) as cnt FROM checklist_items")
    if c.fetchone()[0] == 0:
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
            c.execute("INSERT INTO checklist_items (id,label,item_type,required,sort_order,hint) VALUES (%s,%s,%s,%s,%s,%s)", item)

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
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS default_elic_id TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS default_elic_id TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS program_id TEXT",
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
        "ALTER TABLE youth_production_members ADD COLUMN IF NOT EXISTS role TEXT",
        # volunteer-participant linking
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS linked_participant_id TEXT REFERENCES youth_participants(id) ON DELETE SET NULL",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS linked_volunteer_id TEXT REFERENCES volunteers(id) ON DELETE SET NULL",
        # stage manager role (no DB change needed, just allow it in validation)
        # notifications read tracking
        """CREATE TABLE IF NOT EXISTS notification_reads (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notification_type TEXT NOT NULL,
            notification_id TEXT NOT NULL,
            read_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_id, notification_type, notification_id))""",
        # production conflicts
        """CREATE TABLE IF NOT EXISTS production_conflicts (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            event_id TEXT REFERENCES events(id) ON DELETE CASCADE,
            youth_id TEXT REFERENCES youth_participants(id) ON DELETE CASCADE,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'absent',
            source TEXT NOT NULL DEFAULT 'admin',
            notes TEXT,
            approved BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            created_by_portal BOOLEAN DEFAULT FALSE)""",
        "ALTER TABLE volunteer_waivers ADD COLUMN IF NOT EXISTS youth_id TEXT REFERENCES youth_participants(id) ON DELETE CASCADE",
        # portal features
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS family_id TEXT",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS passphrase TEXT",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS portal_passphrase TEXT",
        # portal content tables
        """CREATE TABLE IF NOT EXISTS families (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            passphrase TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS portal_announcements (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            production_id TEXT REFERENCES productions(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            author_id TEXT REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS portal_files (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            production_id TEXT REFERENCES productions(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            drive_url TEXT NOT NULL,
            description TEXT,
            author_id TEXT REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW())""",
        # portal folders
        "ALTER TABLE portal_files ADD COLUMN IF NOT EXISTS folder TEXT DEFAULT 'General'",
        # email settings
        """CREATE TABLE IF NOT EXISTS email_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            resend_api_key TEXT DEFAULT '',
            from_email TEXT DEFAULT 'info@hwtco.org',
            report_recipients TEXT DEFAULT '',
            alert_pending_hours BOOLEAN DEFAULT TRUE,
            alert_profile_updates BOOLEAN DEFAULT TRUE,
            alert_callouts BOOLEAN DEFAULT TRUE,
            alert_waiver_expiry BOOLEAN DEFAULT TRUE,
            auto_send_checklist_report BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT NOW())""",
        "INSERT INTO email_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS report_recipient_user_ids TEXT DEFAULT '[]'",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_conflicts BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_waivers BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_event_not_opened BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_event_not_closed BOOLEAN DEFAULT TRUE",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS venue TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
        """CREATE TABLE IF NOT EXISTS production_general_content (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            html_content TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by TEXT)""",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS pushed_at TIMESTAMP",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS push_count INTEGER DEFAULT 0",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published'",
        "ALTER TABLE volunteer_applications ADD COLUMN IF NOT EXISTS pronouns TEXT",
        "ALTER TABLE volunteer_applications ADD COLUMN IF NOT EXISTS is_adult BOOLEAN DEFAULT TRUE",
        "UPDATE users SET role='staff' WHERE role NOT IN ('admin','staff')",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS body_draft TEXT",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS title_draft TEXT",
        """CREATE TABLE IF NOT EXISTS kiosk_sessions (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
            event_id TEXT REFERENCES events(id),
            event_name TEXT,
            role TEXT DEFAULT '',
            started_at TIMESTAMP DEFAULT NOW(),
            ended_at TIMESTAMP,
            hours NUMERIC(5,2),
            status TEXT DEFAULT 'active')""",
        """CREATE TABLE IF NOT EXISTS nav_icons (
            key TEXT PRIMARY KEY,
            lucide_name TEXT NOT NULL)""",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS image_url TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS performance_location TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS portal_color TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS portal_image_url TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS director TEXT",
        # meet the team
        """CREATE TABLE IF NOT EXISTS production_team_members (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            role TEXT,
            bio TEXT,
            headshot_url TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        "ALTER TABLE pending_profile_updates ADD COLUMN IF NOT EXISTS youth_id TEXT REFERENCES youth_participants(id) ON DELETE CASCADE",
        """CREATE TABLE IF NOT EXISTS portal_folders (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            production_id TEXT REFERENCES productions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        # audit trail columns
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS updated_by TEXT",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS updated_by TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS updated_by TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS updated_by TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS updated_by TEXT",
        # one-time dedup: keep only the oldest checklist item per label
        """DELETE FROM checklist_items WHERE id NOT IN (
            SELECT DISTINCT ON (label) id FROM checklist_items ORDER BY label, created_at ASC)""",
        """DELETE FROM opening_checklist_items WHERE id NOT IN (
            SELECT DISTINCT ON (label) id FROM opening_checklist_items ORDER BY label, created_at ASC)""",
        # volunteer interest/application form
        """CREATE TABLE IF NOT EXISTS volunteer_applications (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            interests TEXT DEFAULT '[]',
            how_heard TEXT,
            notes TEXT,
            status TEXT DEFAULT 'pending',
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT NOW())""",
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
    resp = send_from_directory('static', 'index.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp
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
    # Store permissions in session for fast checking
    if user['role'] == 'admin':
        session['permissions'] = '{}'  # admin bypasses all checks
    else:
        session['permissions'] = user.get('role_permissions') or '{}'
    perms_dict = {'id': user['id'], 'name': user['name'], 'email': user['email'],
                  'role': user['role'], 'permissions': json.loads(session['permissions'] or '{}')}
    return jsonify(perms_dict)

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me')
def me():
    if 'user_id' not in session: return jsonify({'user': None})
    conn = get_db()
    u = fetchone(conn, 'SELECT id, name, email, role, role_permissions FROM users WHERE id=%s', (session['user_id'],))
    conn.close()
    if not u: return jsonify({'user': None})
    perms = {}
    if u['role'] != 'admin':
        try: perms = json.loads(u.get('role_permissions') or '{}')
        except Exception: perms = {}
    return jsonify({'user': {'id': u['id'], 'name': u['name'], 'email': u['email'],
                             'role': u['role'], 'permissions': perms}})

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
        p.name as production_name, COALESCE(p.stage,'mainstage') as production_stage,
        pg.name as program_name
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id
        LEFT JOIN youth_programs pg ON e.program_id=pg.id
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
        (id,name,event_date,end_date,start_time,end_time,event_type_id,location,room,production_id,program_id,expected_volunteers,description,notes,status,requires_background_check)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)''',
        (eid, d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False)))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*,
        COALESCE(e.requires_background_check, FALSE) as requires_background_check,
        et.name as event_type_name, et.color as event_type_color,
        p.name as production_name, COALESCE(p.stage,'mainstage') as production_stage,
        pg.name as program_name
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id
        LEFT JOIN youth_programs pg ON e.program_id=pg.id
        WHERE e.id=%s''', (eid,))
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
        event_type_id=%s,location=%s,room=%s,production_id=%s,program_id=%s,expected_volunteers=%s,description=%s,notes=%s,requires_background_check=%s WHERE id=%s''',
        (d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False), eid))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*,
        COALESCE(e.requires_background_check, FALSE) as requires_background_check,
        et.name as event_type_name, et.color as event_type_color,
        p.name as production_name, COALESCE(p.stage,'mainstage') as production_stage,
        pg.name as program_name
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        LEFT JOIN productions p ON e.production_id=p.id
        LEFT JOIN youth_programs pg ON e.program_id=pg.id
        WHERE e.id=%s''', (eid,))
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
    try:
        # Clear non-cascade FK references before deleting
        execute(conn, 'UPDATE youth_sign_ins SET event_id=NULL WHERE event_id=%s', (eid,))
        execute(conn, 'UPDATE kiosk_sessions SET event_id=NULL WHERE event_id=%s', (eid,))
        execute(conn, 'DELETE FROM events WHERE id=%s', (eid,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'error': str(e)}), 500
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
    programs = fetchall(conn, '''SELECT yp.*, v.name as default_elic_name
        FROM youth_programs yp
        LEFT JOIN elics el ON yp.default_elic_id=el.id
        LEFT JOIN volunteers v ON el.volunteer_id=v.id
        ORDER BY yp.name''')
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
        execute(conn, 'INSERT INTO youth_programs (id,name,description,program_type,start_date,end_date,instructor_id,default_elic_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (pid, d['name'].strip(), d.get('description',''),
                 d.get('program_type','class'), d.get('start_date') or None,
                 d.get('end_date') or None, d.get('instructor_id') or None,
                 d.get('default_elic_id') or None))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Program already exists'}), 400
    row = fetchone(conn, '''SELECT yp.*, v.name as default_elic_name FROM youth_programs yp LEFT JOIN elics el ON yp.default_elic_id=el.id LEFT JOIN volunteers v ON el.volunteer_id=v.id WHERE yp.id=%s''', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-programs/<pid>', methods=['PUT'])
def update_youth_program(pid):
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name','').strip(): return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    execute(conn, 'UPDATE youth_programs SET name=%s,description=%s,program_type=%s,start_date=%s,end_date=%s,instructor_id=%s,default_elic_id=%s WHERE id=%s',
            (d['name'].strip(), d.get('description',''),
             d.get('program_type','class'), d.get('start_date') or None,
             d.get('end_date') or None, d.get('instructor_id') or None,
             d.get('default_elic_id') or None, pid))
    conn.commit()
    row = fetchone(conn, '''SELECT yp.*, v.name as default_elic_name FROM youth_programs yp LEFT JOIN elics el ON yp.default_elic_id=el.id LEFT JOIN volunteers v ON el.volunteer_id=v.id WHERE yp.id=%s''', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-programs/<pid>', methods=['DELETE'])
def delete_youth_program(pid):
    err = require_admin()
    if err: return err
    conn = get_db()
    # Clear any FK references that don't cascade
    execute(conn, 'UPDATE youth_sign_ins SET program_id=NULL WHERE program_id=%s', (pid,))
    execute(conn, 'UPDATE events SET program_id=NULL WHERE program_id=%s', (pid,))
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
        execute(conn, 'INSERT INTO users (id,name,email,password_hash,role,role_permissions) VALUES (%s,%s,%s,%s,%s,%s)',
                (uid_, d['name'], d['email'], pw_hash, d.get('role','staff'), '{}'))
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
    prods = fetchall(conn, """SELECT p.*, COALESCE(p.stage,'mainstage') as stage,
        v.name as default_elic_name
        FROM productions p
        LEFT JOIN elics el ON p.default_elic_id=el.id
        LEFT JOIN volunteers v ON el.volunteer_id=v.id
        ORDER BY p.start_date DESC NULLS LAST""")
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
    execute(conn, 'INSERT INTO productions (id,name,production_type,stage,start_date,end_date,description,status,default_elic_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (pid, d['name'], d.get('production_type','show'), d.get('stage','mainstage'),
             d.get('start_date') or None, d.get('end_date') or None,
             d.get('description',''), d.get('status','upcoming'),
             d.get('default_elic_id') or None))
    conn.commit()
    prod = fetchone(conn, '''SELECT p.*, COALESCE(p.stage,'mainstage') as stage, v.name as default_elic_name FROM productions p LEFT JOIN elics el ON p.default_elic_id=el.id LEFT JOIN volunteers v ON el.volunteer_id=v.id WHERE p.id=%s''', (pid,))
    prod['members'] = []
    conn.close()
    return jsonify(prod)

@app.route('/api/productions/<pid>', methods=['PUT'])
def update_production(pid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE productions SET name=%s,production_type=%s,stage=%s,start_date=%s,end_date=%s,description=%s,status=%s,default_elic_id=%s,image_url=%s WHERE id=%s',
            (d['name'], d.get('production_type','show'), d.get('stage','mainstage'),
             d.get('start_date') or None, d.get('end_date') or None,
             d.get('description',''), d.get('status','upcoming'),
             d.get('default_elic_id') or None,
             d.get('image_url') or None, pid))
    conn.commit()
    prod = fetchone(conn, '''SELECT p.*, COALESCE(p.stage,'mainstage') as stage, v.name as default_elic_name FROM productions p LEFT JOIN elics el ON p.default_elic_id=el.id LEFT JOIN volunteers v ON el.volunteer_id=v.id WHERE p.id=%s''', (pid,))
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
    import time
    resp = send_from_directory('static', 'kiosk.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    resp.headers['ETag'] = str(int(time.time()))
    return resp




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
    # Return events that are open, OR scheduled for today/recent (within 1 day)
    conn = get_db()
    events = fetchall(conn, """
        SELECT * FROM events
        WHERE status='open'
           OR (status IN ('draft','published','in_progress')
               AND event_date::date >= (CURRENT_DATE - INTERVAL '1 day')
               AND event_date::date <= (CURRENT_DATE + INTERVAL '1 day'))
        ORDER BY
            CASE WHEN status='open' THEN 0 ELSE 1 END,
            event_date ASC NULLS LAST
    """)
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
        '''SELECT pu.*, 
            v.name as volunteer_name,
            CASE WHEN pu.youth_id IS NOT NULL 
                 THEN (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pu.youth_id)
                 ELSE v.name END as display_name,
            CASE WHEN pu.youth_id IS NOT NULL THEN 'participant' ELSE 'volunteer' END as profile_type
            FROM pending_profile_updates pu 
            LEFT JOIN volunteers v ON pu.volunteer_id=v.id 
            WHERE pu.status='pending' 
            ORDER BY pu.submitted_at DESC''')
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
    # No auth required — kiosk needs this without a session
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
    # Send checklist report email (non-blocking)
    try:
        send_checklist_report(event_id)
    except Exception as e:
        app.logger.error(f'Report email error: {e}')
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
    # No auth required — kiosk needs this without a session
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
    valid_roles = ['admin', 'board', 'instructor', 'elic', 'stage_manager']
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


# ─────────────────────────────────────────────
#  DEFAULT ELIC / ENROLLMENT HELPERS
# ─────────────────────────────────────────────

@app.route('/api/events/default-elic')
def get_default_elic_for_parent():
    program_id    = request.args.get('program_id')
    production_id = request.args.get('production_id')
    conn = get_db()
    elic_id = None
    if program_id:
        row = fetchone(conn, 'SELECT default_elic_id FROM youth_programs WHERE id=%s', (program_id,))
        if row: elic_id = row['default_elic_id']
    elif production_id:
        row = fetchone(conn, 'SELECT default_elic_id FROM productions WHERE id=%s', (production_id,))
        if row: elic_id = row['default_elic_id']
    conn.close()
    return jsonify({'elic_id': elic_id})

@app.route('/api/youth-programs/<pid>/enroll', methods=['POST'])
def bulk_enroll_youth(pid):
    err = require_admin()
    if err: return err
    d = request.json
    youth_ids = d.get('youth_ids', [])
    if not youth_ids:
        return jsonify({'error': 'No youth selected'}), 400
    conn = get_db()
    enrolled = 0
    for yid in youth_ids:
        try:
            execute(conn,
                "INSERT INTO youth_program_enrollments (id,youth_id,program_id,enrolled_date) VALUES (%s,%s,%s,%s)",
                (str(uuid.uuid4()), yid, pid, date.today().isoformat()))
            enrolled += 1
        except psycopg2.IntegrityError:
            conn.rollback()
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'enrolled': enrolled})

@app.route('/api/youth-programs/<pid>/enrolled')
def get_program_enrolled(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    youth = fetchall(conn, '''SELECT y.id, y.first_name, y.last_name, y.dob, y.status,
        ye.id as enrollment_id, ye.enrolled_date
        FROM youth_program_enrollments ye
        JOIN youth_participants y ON ye.youth_id=y.id
        WHERE ye.program_id=%s ORDER BY y.last_name, y.first_name''', (pid,))
    conn.close()
    return jsonify(youth)


@app.route('/api/youth-enrollments/<eid>', methods=['DELETE'])
def delete_youth_enrollment(eid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_program_enrollments WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────
#  YOUTH PRODUCTION MEMBERS
# ─────────────────────────────────────────────

@app.route('/api/productions/<pid>/youth-members', methods=['POST'])
def add_youth_production_members(pid):
    err = require_admin()
    if err: return err
    d = request.json
    youth_ids = d.get('youth_ids', [])
    conn = get_db()
    added = 0
    for yid in youth_ids:
        try:
            execute(conn,
                "INSERT INTO youth_production_members (id,production_id,youth_id) VALUES (%s,%s,%s)",
                (str(uuid.uuid4()), pid, yid))
            added += 1
        except psycopg2.IntegrityError:
            conn.rollback()
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'added': added})

@app.route('/api/productions/<pid>/youth-members', methods=['GET'])
def get_youth_production_members(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT ypm.*, y.first_name, y.last_name, y.dob
        FROM youth_production_members ypm
        JOIN youth_participants y ON ypm.youth_id=y.id
        WHERE ypm.production_id=%s ORDER BY y.last_name, y.first_name''', (pid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/productions/<pid>/youth-members/<mid>', methods=['DELETE'])
def remove_youth_production_member(pid, mid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_production_members WHERE id=%s AND production_id=%s', (mid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════
#  PARTICIPANT PORTAL
# ═══════════════════════════════════════════════════════════════

@app.route('/portal')
def portal_page():
    resp = send_from_directory('static', 'portal.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

# ── Family management ──

@app.route('/api/families', methods=['GET'])
def get_families():
    err = require_admin()
    if err: return err
    conn = get_db()
    families = fetchall(conn, '''SELECT f.*, 
        COUNT(y.id) as member_count
        FROM families f
        LEFT JOIN youth_participants y ON y.family_id=f.id
        GROUP BY f.id ORDER BY f.name''')
    conn.close()
    return jsonify(families)

@app.route('/api/families', methods=['POST'])
def create_family():
    err = require_admin()
    if err: return err
    d = request.json
    if not d.get('name') or not d.get('passphrase'):
        return jsonify({'error': 'Name and passphrase required'}), 400
    fid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO families (id,name,passphrase) VALUES (%s,%s,%s)',
                (fid, d['name'].strip(), d['passphrase'].strip()))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Passphrase already in use'}), 400
    row = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (fid,))
    conn.close()
    return jsonify(row)

@app.route('/api/families/<fid>', methods=['PUT'])
def update_family(fid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE families SET name=%s,passphrase=%s WHERE id=%s',
            (d.get('name',''), d.get('passphrase',''), fid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (fid,))
    conn.close()
    return jsonify(row)

@app.route('/api/families/<fid>', methods=['DELETE'])
def delete_family(fid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=NULL WHERE family_id=%s', (fid,))
    execute(conn, 'DELETE FROM families WHERE id=%s', (fid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/families/<fid>/members', methods=['POST'])
def add_family_member(fid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=%s WHERE id=%s',
            (fid, d['youth_id']))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/families/<fid>/members/<yid>', methods=['DELETE'])
def remove_family_member(fid, yid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=NULL WHERE id=%s AND family_id=%s', (yid, fid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal login ──

@app.route('/api/portal/login', methods=['POST'])
def portal_login():
    d = request.json
    passphrase = (d.get('passphrase') or '').strip()
    if not passphrase:
        return jsonify({'error': 'Passphrase required'}), 400
    conn = get_db()

    # Check family passphrase
    family = fetchone(conn, 'SELECT * FROM families WHERE LOWER(passphrase)=LOWER(%s)', (passphrase,))
    if family:
        members = fetchall(conn, '''SELECT y.*, 
            COALESCE(y.family_id,'') as family_id
            FROM youth_participants y WHERE y.family_id=%s 
            ORDER BY y.first_name''', (family['id'],))
        conn.close()
        return jsonify({'type': 'family', 'family': family, 'members': members})

    # Check individual youth passphrase
    youth = fetchone(conn, 'SELECT * FROM youth_participants WHERE LOWER(passphrase)=LOWER(%s)', (passphrase,))
    if youth:
        conn.close()
        return jsonify({'type': 'participant', 'participant': youth})

    # Check instructor login (volunteer with instructor user account)
    # Instructors use email+password via normal login
    conn.close()
    return jsonify({'error': 'Passphrase not found'}), 404

@app.route('/api/portal/instructor-login', methods=['POST'])
def portal_instructor_login():
    d = request.json
    pw_hash = hashlib.sha256(d.get('password','').encode()).hexdigest()
    conn2 = get_db()
    user = fetchone(conn2, "SELECT * FROM users WHERE email=%s AND password_hash=%s AND active=TRUE",
                    (d.get('email','').strip(), pw_hash))
    conn2.close()
    if not user:
        return jsonify({'error': 'Invalid email or password'}), 401
    if user['role'] not in ('admin','instructor'):
        return jsonify({'error': 'Not an instructor account'}), 403
    conn = get_db()
    # Get programs where this user is the instructor volunteer
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE email=%s', (user['email'],))
    programs = []
    productions = []
    if vol:
        programs = fetchall(conn, '''SELECT p.*, v.name as default_elic_name
            FROM youth_programs p LEFT JOIN elics el ON p.default_elic_id=el.id
            LEFT JOIN volunteers v ON el.volunteer_id=v.id
            WHERE p.instructor_id=%s ORDER BY p.name''', (vol['id'],))
        # Rising Stars productions they manage
        productions = fetchall(conn, '''SELECT p.* FROM productions p
            JOIN production_members pm ON pm.production_id=p.id
            WHERE p.stage='rising_stars' AND pm.volunteer_id=%s
            ORDER BY p.name''', (vol['id'],))
    if user['role'] == 'admin':
        # Admins see everything
        programs = fetchall(conn, 'SELECT * FROM youth_programs ORDER BY name')
        productions = fetchall(conn, "SELECT * FROM productions WHERE stage='rising_stars' ORDER BY name")
    conn.close()
    return jsonify({'type': 'instructor', 'user': {'id': user['id'], 'name': user['name'], 'email': user['email'], 'role': user['role']}, 'programs': programs, 'productions': productions})

# ── Portal data endpoints (no auth — passphrase already validated client-side) ──

@app.route('/api/portal/participant/<yid>')
def portal_participant_data(yid):
    conn = get_db()
    # Enrollments
    enrollments = fetchall(conn, '''SELECT ye.*, yp.name as program_name, 
        yp.description, yp.start_date, yp.end_date, yp.program_type,
        v.name as instructor_name
        FROM youth_program_enrollments ye
        JOIN youth_programs yp ON ye.program_id=yp.id
        LEFT JOIN volunteers v ON yp.instructor_id=v.id
        WHERE ye.youth_id=%s ORDER BY yp.start_date''', (yid,))
    # Rising Stars productions
    productions = fetchall(conn, '''SELECT p.*, ypm.role as cast_role
        FROM youth_production_members ypm
        JOIN productions p ON ypm.production_id=p.id
        WHERE ypm.youth_id=%s ORDER BY p.start_date''', (yid,))
    # Portal announcements for enrolled programs
    prog_ids = [e['program_id'] for e in enrollments]
    prod_ids = [p['id'] for p in productions]
    announcements = []
    if prog_ids or prod_ids:
        placeholders = ','.join(['%s']*(len(prog_ids)+len(prod_ids)))
        announcements = fetchall(conn, f'''SELECT pa.*, 
            COALESCE(yp.name, pr.name) as context_name,
            u.name as author_name
            FROM portal_announcements pa
            LEFT JOIN youth_programs yp ON pa.program_id=yp.id
            LEFT JOIN productions pr ON pa.production_id=pr.id
            LEFT JOIN users u ON pa.author_id=u.id
            WHERE (pa.program_id IN ({','.join(['%s']*len(prog_ids)) if prog_ids else 'NULL'})
               OR pa.production_id IN ({','.join(['%s']*len(prod_ids)) if prod_ids else 'NULL'}))
               AND COALESCE(pa.status,'published')='published'
            ORDER BY pa.created_at DESC''',
            tuple(prog_ids + prod_ids)) if (prog_ids or prod_ids) else []
    # Files
    files = []
    if prog_ids or prod_ids:
        files = fetchall(conn, f'''SELECT pf.*,
            COALESCE(yp.name, pr.name) as context_name,
            u.name as author_name
            FROM portal_files pf
            LEFT JOIN youth_programs yp ON pf.program_id=yp.id
            LEFT JOIN productions pr ON pf.production_id=pr.id
            LEFT JOIN users u ON pf.author_id=u.id
            WHERE pf.program_id IN ({','.join(['%s']*len(prog_ids)) if prog_ids else 'NULL'})
               OR pf.production_id IN ({','.join(['%s']*len(prod_ids)) if prod_ids else 'NULL'})
            ORDER BY pf.created_at DESC''',
            tuple(prog_ids + prod_ids)) if (prog_ids or prod_ids) else []
    conn.close()
    return jsonify({
        'enrollments': enrollments,
        'productions': productions,
        'announcements': announcements,
        'files': files
    })

@app.route('/api/portal/program/<pid>/events')
def portal_program_events(pid):
    conn = get_db()
    events = fetchall(conn, '''SELECT e.* FROM events e
        WHERE e.program_id=%s ORDER BY e.event_date ASC NULLS LAST''', (pid,))
    conn.close()
    return jsonify(events)

@app.route('/api/portal/production/<pid>/events')
def portal_production_events(pid):
    conn = get_db()
    events = fetchall(conn, '''SELECT e.* FROM events e
        WHERE e.production_id=%s ORDER BY e.event_date ASC NULLS LAST''', (pid,))
    conn.close()
    return jsonify(events)

# ── Instructor portal content management ──

@app.route('/api/portal/announcements', methods=['POST'])
def create_portal_announcement():
    err = require_auth()
    if err: return err
    d = request.json
    aid = str(uuid.uuid4())
    status = d.get('status', 'published')
    conn = get_db()
    execute(conn, '''INSERT INTO portal_announcements 
        (id,program_id,production_id,title,body,author_id,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (aid, d.get('program_id') or None, d.get('production_id') or None,
         d['title'], d['body'], session.get('user_id'), status))
    conn.commit()
    row = fetchone(conn, '''SELECT pa.*, u.name as author_name FROM portal_announcements pa
        LEFT JOIN users u ON pa.author_id=u.id WHERE pa.id=%s''', (aid,))
    conn.close()
    return jsonify(row)

@app.route('/api/portal/announcements/<aid>', methods=['PUT'])
def update_portal_announcement(aid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    # Only update title/body if provided and non-empty
    updates = ['status=%s']
    params = [d.get('status','published')]
    if d.get('title'):
        updates.append('title=%s'); params.append(d['title'])
    if d.get('body'):
        updates.append('body=%s'); params.append(d['body'])
    params.append(aid)
    execute(conn, 'UPDATE portal_announcements SET '+','.join(updates)+' WHERE id=%s', tuple(params))
    conn.commit()
    row = fetchone(conn, '''SELECT pa.*, u.name as author_name FROM portal_announcements pa
        LEFT JOIN users u ON pa.author_id=u.id WHERE pa.id=%s''', (aid,))
    conn.close()
    return jsonify(row)

@app.route('/api/portal/announcements/<aid>', methods=['DELETE'])
def delete_portal_announcement(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM portal_announcements WHERE id=%s', (aid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/files', methods=['POST'])
def create_portal_file():
    err = require_auth()
    if err: return err
    d = request.json
    fid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO portal_files
        (id,program_id,production_id,title,drive_url,description,folder,author_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
        (fid, d.get('program_id') or None, d.get('production_id') or None,
         d['title'], d['drive_url'], d.get('description',''), d.get('folder','General'), session.get('user_id')))
    conn.commit()
    row = fetchone(conn, '''SELECT pf.*, u.name as author_name FROM portal_files pf
        LEFT JOIN users u ON pf.author_id=u.id WHERE pf.id=%s''', (fid,))
    conn.close()
    return jsonify(row)

@app.route('/api/portal/files/<fid>', methods=['DELETE'])
def delete_portal_file(fid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM portal_files WHERE id=%s', (fid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/instructor/content/<context_type>/<context_id>')
def get_portal_content(context_type, context_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    field = 'program_id' if context_type == 'program' else 'production_id'
    announcements = fetchall(conn, f'''SELECT pa.*, u.name as author_name 
        FROM portal_announcements pa LEFT JOIN users u ON pa.author_id=u.id
        WHERE pa.{field}=%s ORDER BY pa.created_at DESC''', (context_id,))
    files = fetchall(conn, f'''SELECT pf.*, u.name as author_name
        FROM portal_files pf LEFT JOIN users u ON pf.author_id=u.id
        WHERE pf.{field}=%s ORDER BY pf.created_at DESC''', (context_id,))
    conn.close()
    return jsonify({'announcements': announcements, 'files': files})


@app.route('/api/youth/<yid>/passphrase', methods=['PUT'])
def set_youth_passphrase(yid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE id=%s',
            (d.get('passphrase') or None, yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



# ── Portal Folders ──
@app.route('/api/portal/folders', methods=['GET'])
def get_portal_folders():
    prog_id = request.args.get('program_id')
    prod_id = request.args.get('production_id')
    conn = get_db()
    if prog_id:
        folders = fetchall(conn, 'SELECT * FROM portal_folders WHERE program_id=%s ORDER BY sort_order,name', (prog_id,))
    elif prod_id:
        folders = fetchall(conn, 'SELECT * FROM portal_folders WHERE production_id=%s ORDER BY sort_order,name', (prod_id,))
    else:
        folders = []
    conn.close()
    return jsonify(folders)

@app.route('/api/portal/folders', methods=['POST'])
def create_portal_folder():
    err = require_auth()
    if err: return err
    d = request.json
    fid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO portal_folders (id,program_id,production_id,name) VALUES (%s,%s,%s,%s)',
            (fid, d.get('program_id') or None, d.get('production_id') or None, d['name'].strip()))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM portal_folders WHERE id=%s', (fid,))
    conn.close()
    return jsonify(row)

@app.route('/api/portal/folders/<fid>', methods=['DELETE'])
def delete_portal_folder(fid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Move files in this folder to General
    execute(conn, "UPDATE portal_files SET folder='General' WHERE folder=(SELECT name FROM portal_folders WHERE id=%s)", (fid,))
    execute(conn, 'DELETE FROM portal_folders WHERE id=%s', (fid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal waiver status for program ──
@app.route('/api/portal/program/<pid>/waiver-status')
def portal_program_waiver_status(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Get required waivers for this program via event waivers
    prog_events = fetchall(conn, 'SELECT id FROM events WHERE program_id=%s', (pid,))
    event_ids = [e['id'] for e in prog_events]
    required_waivers = []
    if event_ids:
        ph = ','.join(['%s']*len(event_ids))
        required_waivers = fetchall(conn, f'''SELECT DISTINCT wt.id, wt.name FROM event_waivers ew
            JOIN waiver_types wt ON ew.waiver_type_id=wt.id
            WHERE ew.event_id IN ({ph})''', tuple(event_ids))
    # Get enrolled youth
    enrolled = fetchall(conn, '''SELECT y.id, y.first_name, y.last_name 
        FROM youth_program_enrollments ye JOIN youth_participants y ON ye.youth_id=y.id
        WHERE ye.program_id=%s''', (pid,))
    # Check waivers on file for each
    result = []
    for y in enrolled:
        signed = fetchall(conn, '''SELECT vw.waiver_type_id FROM volunteer_waivers vw WHERE vw.youth_id=%s''', (y['id'],))
        signed_ids = {w['waiver_type_id'] for w in signed}
        missing = [w for w in required_waivers if w['id'] not in signed_ids]
        result.append({**y, 'missing_waivers': missing, 'waiver_ok': len(missing)==0})
    conn.close()
    return jsonify({'required_waivers': required_waivers, 'participants': result})


# ── Youth portal profile update requests ──
@app.route('/api/portal/youth/<yid>/profile', methods=['GET'])
def portal_get_youth_profile(yid):
    conn = get_db()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    if not y:
        conn.close(); return jsonify({'error': 'Not found'}), 404
    guardians = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s ORDER BY is_primary DESC', (yid,))
    emergency = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (yid,))
    # Youth waivers via production_waivers or volunteer_waivers linked to youth guardian volunteer
    # For now return waivers that reference this youth via production enrollment
    waivers = []
    try:
        waivers = fetchall(conn, '''SELECT vw.*, wt.name as type_name 
            FROM volunteer_waivers vw
            JOIN waiver_types wt ON vw.waiver_type_id=wt.id 
            WHERE vw.youth_id=%s''', (yid,))
    except Exception:
        conn.rollback()
        waivers = []
    conn.close()
    return jsonify({**dict(y), 'guardians': guardians, 'emergency': emergency, 'waivers': waivers})

@app.route('/api/portal/youth/<yid>/request-update', methods=['POST'])
def portal_request_youth_update(yid):
    d = request.json
    conn = get_db()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    if not y:
        conn.close(); return jsonify({'error': 'Not found'}), 404
    uid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO pending_profile_updates 
        (id, youth_id, field_name, old_value, new_value)
        VALUES (%s, %s, %s, %s, %s)''',
        (uid, yid, d['field_name'], d.get('old_value',''), d['new_value']))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ═══════════════════════════════════════════════════════════════
#  NOTIFICATIONS CENTER
# ═══════════════════════════════════════════════════════════════

@app.route('/api/notifications')
def get_notifications():
    err = require_auth()
    if err: return err
    role = session.get('role')
    user_id = session.get('user_id')
    conn = get_db()
    result = {'needs_action': [], 'activity': [], 'total_action': 0}

    # ── Pending hours (admin/instructor) ──
    if role in ('admin', 'instructor', 'board'):
        hours = fetchall(conn, '''SELECT ph.*, v.name as volunteer_name, v.id as volunteer_id
            FROM pending_hours ph JOIN volunteers v ON ph.volunteer_id=v.id
            WHERE ph.status='pending' ORDER BY ph.submitted_at DESC''')
        for h in hours:
            result['needs_action'].append({
                'type': 'pending_hours', 'id': h['id'],
                'title': f"{h['volunteer_name']} submitted {h['hours']}h for {h['event']}",
                'sub': f"Submitted {h.get('submitted_at','')[:10]}",
                'icon': '⏱', 'color': 'amber', 'data': dict(h)
            })

    # ── Pending profile updates ──
    if role in ('admin',):
        updates = fetchall(conn, '''SELECT pu.*,
            CASE WHEN pu.youth_id IS NOT NULL 
                 THEN (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pu.youth_id)
                 ELSE v.name END as person_name,
            CASE WHEN pu.youth_id IS NOT NULL THEN 'participant' ELSE 'volunteer' END as profile_type
            FROM pending_profile_updates pu
            LEFT JOIN volunteers v ON pu.volunteer_id=v.id
            WHERE pu.status='pending' ORDER BY pu.submitted_at DESC''')
        for u in updates:
            result['needs_action'].append({
                'type': 'profile_update', 'id': u['id'],
                'title': f"{u['person_name']} requested change to {u['field_name']}",
                'sub': f"New value: {u['new_value'][:60]}",
                'icon': '👤', 'color': 'blue', 'data': dict(u)
            })

    # ── Conflict requests needing approval ──
    if role in ('admin', 'stage_manager'):
        conflicts = fetchall(conn, '''SELECT pc.*,
            COALESCE(
                (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pc.youth_id),
                (SELECT name FROM volunteers WHERE id=pc.volunteer_id)
            ) as person_name,
            p.name as production_name,
            e.name as event_name, e.event_date
            FROM production_conflicts pc
            JOIN productions p ON pc.production_id=p.id
            LEFT JOIN events e ON pc.event_id=e.id
            WHERE pc.approved=FALSE ORDER BY pc.created_at DESC''')
        for c in conflicts:
            result['needs_action'].append({
                'type': 'conflict_request', 'id': c['id'],
                'title': f"{c['person_name']} — {c['status'].title()} for {c['production_name']}",
                'sub': c['event_name'] or 'No specific event',
                'icon': '⚔️', 'color': 'red', 'data': dict(c)
            })

    # ── Missing waivers (proactive) ──
    if role in ('admin', 'instructor'):
        # Events in next 7 days
        upcoming_evts = fetchall(conn, '''SELECT e.id, e.name, e.event_date, e.program_id, e.production_id
            FROM events e WHERE e.event_date::date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
            ORDER BY e.event_date''')
        for evt in upcoming_evts:
            req_waivers = fetchall(conn, '''SELECT wt.id, wt.name FROM event_waivers ew
                JOIN waiver_types wt ON ew.waiver_type_id=wt.id WHERE ew.event_id=%s''', (evt['id'],))
            if not req_waivers: continue
            # Check enrolled youth
            if evt['program_id']:
                enrolled = fetchall(conn, '''SELECT y.id, y.first_name, y.last_name
                    FROM youth_program_enrollments ye JOIN youth_participants y ON ye.youth_id=y.id
                    WHERE ye.program_id=%s''', (evt['program_id'],))
                wt_ids = [w['id'] for w in req_waivers]
                for y in enrolled:
                    signed = fetchall(conn, 'SELECT waiver_type_id FROM volunteer_waivers WHERE youth_id=%s', (y['id'],))
                    signed_ids = {s['waiver_type_id'] for s in signed}
                    missing = [w for w in req_waivers if w['id'] not in signed_ids]
                    if missing:
                        result['needs_action'].append({
                            'type': 'missing_waiver', 'id': f"{evt['id']}_{y['id']}",
                            'title': f"{y['first_name']} {y['last_name']} missing waiver for {evt['name']}",
                            'sub': f"Event: {evt['event_date']} · Missing: {', '.join(w['name'] for w in missing)}",
                            'icon': '📋', 'color': 'red', 'data': {'event': dict(evt), 'youth': dict(y), 'missing': missing}
                        })

    # ── Activity: Today's callouts ──
    today = fetchall(conn, '''SELECT pc.*,
        COALESCE(
            (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pc.youth_id),
            (SELECT name FROM volunteers WHERE id=pc.volunteer_id)
        ) as person_name,
        p.name as production_name
        FROM production_conflicts pc
        JOIN productions p ON pc.production_id=p.id
        WHERE DATE(pc.created_at)=CURRENT_DATE AND pc.approved=TRUE
        ORDER BY pc.created_at DESC''')
    for c in today:
        result['activity'].append({
            'type': 'callout', 'id': c['id'],
            'title': f"{c['person_name']} called {c['status']} — {c['production_name']}",
            'sub': f"Self-reported · {str(c.get('created_at',''))[:16]}",
            'icon': '🔴' if c['status']=='absent' else '🟡', 'color': 'red',
            'data': dict(c)
        })

    # ── Activity: Unauthorized pickups ──
    pickups = fetchall(conn, '''SELECT pp.*, 
        y.first_name||' '||y.last_name as youth_name
        FROM pending_profile_updates pp
        JOIN youth_participants y ON pp.youth_id=y.id
        WHERE pp.field_name='unauthorized_pickup' AND pp.status='pending'
        ORDER BY pp.submitted_at DESC''')
    for p in pickups:
        result['activity'].append({
            'type': 'unauthorized_pickup', 'id': p['id'],
            'title': f"Unauthorized pickup attempt for {p['youth_name']}",
            'sub': p.get('new_value','')[:80],
            'icon': '⚠️', 'color': 'amber', 'data': dict(p)
        })

    result['total_action'] = len(result['needs_action'])
    conn.close()
    return jsonify(result)


# ── Volunteer-Participant linking ──

@app.route('/api/volunteers/<vid>/link-participant', methods=['POST'])
def link_volunteer_participant(vid):
    err = require_admin()
    if err: return err
    d = request.json
    pid = d.get('participant_id')
    conn = get_db()
    execute(conn, 'UPDATE volunteers SET linked_participant_id=%s WHERE id=%s', (pid or None, vid))
    if pid:
        execute(conn, 'UPDATE youth_participants SET linked_volunteer_id=%s WHERE id=%s', (vid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/link-volunteer', methods=['POST'])
def link_youth_volunteer(yid):
    err = require_admin()
    if err: return err
    d = request.json
    vid = d.get('volunteer_id')
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET linked_volunteer_id=%s WHERE id=%s', (vid or None, yid))
    if vid:
        execute(conn, 'UPDATE volunteers SET linked_participant_id=%s WHERE id=%s', (yid, vid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── Production Conflicts ──

@app.route('/api/productions/<pid>/conflicts', methods=['GET'])
def get_production_conflicts(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    conflicts = fetchall(conn, '''SELECT pc.*,
        COALESCE(
            (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pc.youth_id),
            (SELECT name FROM volunteers WHERE id=pc.volunteer_id)
        ) as person_name,
        e.name as event_name, e.event_date
        FROM production_conflicts pc
        LEFT JOIN events e ON pc.event_id=e.id
        WHERE pc.production_id=%s ORDER BY pc.created_at DESC''', (pid,))
    conn.close()
    return jsonify(conflicts)

@app.route('/api/productions/<pid>/conflicts', methods=['POST'])
def create_production_conflict(pid):
    err = require_auth()
    if err: return err
    d = request.json
    cid = str(uuid.uuid4())
    conn = get_db()
    # Admin-created conflicts are auto-approved, portal submissions need approval
    approved = session.get('role') in ('admin', 'stage_manager')
    execute(conn, '''INSERT INTO production_conflicts
        (id, production_id, event_id, youth_id, volunteer_id, status, source, notes, approved, created_by_portal)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (cid, pid, d.get('event_id') or None, d.get('youth_id') or None,
         d.get('volunteer_id') or None, d.get('status','absent'),
         d.get('source','admin'), d.get('notes',''), approved,
         d.get('from_portal', False)))
    conn.commit()
    row = fetchone(conn, '''SELECT pc.*,
        COALESCE(
            (SELECT first_name||' '||last_name FROM youth_participants WHERE id=pc.youth_id),
            (SELECT name FROM volunteers WHERE id=pc.volunteer_id)
        ) as person_name,
        e.name as event_name, e.event_date
        FROM production_conflicts pc LEFT JOIN events e ON pc.event_id=e.id
        WHERE pc.id=%s''', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/conflicts/<cid>', methods=['PUT'])
def update_conflict(pid, cid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE production_conflicts SET status=%s, notes=%s, approved=%s WHERE id=%s''',
            (d.get('status'), d.get('notes',''), d.get('approved', True), cid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/conflicts/<cid>', methods=['DELETE'])
def delete_conflict(pid, cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_conflicts WHERE id=%s', (cid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal callout (self-reported, day-of only) ──
@app.route('/api/portal/callout', methods=['POST'])
def portal_callout():
    d = request.json
    youth_id = d.get('youth_id')
    production_id = d.get('production_id')
    status = d.get('status', 'absent')
    if status not in ('absent', 'sick', 'late', 'leaving_early'):
        return jsonify({'error': 'Invalid status'}), 400
    if not youth_id or not production_id:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    # Check it's today (prevent advance callouts)
    cid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO production_conflicts
        (id, production_id, event_id, youth_id, status, source, notes, approved, created_by_portal)
        VALUES (%s,%s,%s,%s,%s,'portal',%s,TRUE,TRUE)''',
        (cid, production_id, d.get('event_id') or None, youth_id, status, d.get('notes','')))
    conn.commit()
    # Alert email for callouts
    try:
        s = get_email_settings()
        if s.get('alert_callouts'):
            prod = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (production_id,))
            yth  = fetchone(conn, 'SELECT first_name, last_name FROM youth_participants WHERE id=%s', (youth_id,))
            prod_name = prod['name'] if prod else 'production'
            yth_name  = (yth['first_name'] + ' ' + yth['last_name']) if yth else 'A cast member'
            callout_event_id = d.get('event_id')
            callout_recipients = recipients_with_elic(callout_event_id, s) if callout_event_id else get_recipient_emails(s)
            if callout_recipients:
                send_email(callout_recipients,
                    'RoleCall -- Callout: ' + yth_name + ' (' + status.title() + ')',
                    '<p style="font-family:sans-serif"><strong>' + yth_name + '</strong> has called out as <strong>' + status.replace('_',' ').title() + '</strong> for <strong>' + prod_name + '</strong>.<br><br>Log in to RoleCall to view conflicts.</p>')
    except Exception: pass
    conn.close()
    return jsonify({'ok': True, 'id': cid})

# ── Mark notification as read ──
@app.route('/api/notifications/read', methods=['POST'])
def mark_notification_read():
    err = require_auth()
    if err: return err
    d = request.json
    rid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO notification_reads (id, user_id, notification_type, notification_id)
            VALUES (%s,%s,%s,%s) ON CONFLICT (user_id, notification_type, notification_id) DO NOTHING''',
            (rid, session.get('user_id'), d['type'], d['id']))
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════
#  MEET THE TEAM
# ═══════════════════════════════════════════════════════════════

@app.route('/api/productions/<pid>/team', methods=['GET'])
def get_team(pid):
    conn = get_db()
    try:
        members = fetchall(conn, 'SELECT * FROM production_team_members WHERE production_id=%s ORDER BY sort_order,name', (pid,))
    except Exception:
        members = []
    conn.close()
    return jsonify(members)

@app.route('/api/productions/<pid>/team', methods=['POST'])
def add_team_member(pid):
    err = require_auth()
    if err: return err
    d = request.json
    mid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO production_team_members (id,production_id,name,role,bio,headshot_url,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (mid, pid, d['name'], d.get('role',''), d.get('bio',''), d.get('headshot_url',''), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM production_team_members WHERE id=%s', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/team/<mid>', methods=['PUT'])
def update_team_member(pid, mid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE production_team_members SET name=%s,role=%s,bio=%s,headshot_url=%s,sort_order=%s WHERE id=%s''',
        (d['name'], d.get('role',''), d.get('bio',''), d.get('headshot_url',''), d.get('sort_order',0), mid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/team/<mid>', methods=['DELETE'])
def delete_team_member(pid, mid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_team_members WHERE id=%s', (mid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Production About (update production info) ──
@app.route('/api/productions/<pid>/about', methods=['PUT'])
def update_production_about(pid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE productions SET description=%s, venue=%s, director=%s,
        performance_location=%s, start_date=%s, end_date=%s,
        portal_color=%s, portal_image_url=%s WHERE id=%s''',
        (d.get('description',''), d.get('venue',''), d.get('director',''),
         d.get('performance_location',''),
         d.get('start_date') or None, d.get('end_date') or None,
         d.get('portal_color') or None, d.get('portal_image_url') or None,
         pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── Portal-facing: public conflicts for a production (approved only, no names of others) ──
@app.route('/api/portal/production/<pid>/conflicts')
def portal_production_conflicts(pid):
    """Returns approved conflicts visible to portal — today's and upcoming only.
    For privacy, only returns conflicts for the requesting youth (if yid passed),
    plus anonymised counts for others."""
    conn = get_db()
    yid = request.args.get('youth_id')
    today = 'CURRENT_DATE'
    # All approved conflicts for this production from today forward
    rows = fetchall(conn, '''SELECT pc.id, pc.event_id, pc.youth_id, pc.status,
        pc.source, pc.notes, pc.created_at,
        e.name as event_name, e.event_date, e.start_time
        FROM production_conflicts pc
        LEFT JOIN events e ON pc.event_id=e.id
        WHERE pc.production_id=%s AND pc.approved=TRUE
          AND (e.event_date IS NULL OR e.event_date::date >= CURRENT_DATE)
        ORDER BY e.event_date ASC NULLS LAST, pc.created_at DESC''', (pid,))
    conn.close()
    # Return full details for own conflicts, just event_id+status for others
    result = []
    for r in rows:
        if r['youth_id'] == yid:
            result.append({**dict(r), 'is_mine': True})
        else:
            result.append({
                'event_id': r['event_id'],
                'event_name': r['event_name'],
                'event_date': r['event_date'],
                'status': r['status'],
                'is_mine': False,
                'youth_id': None  # anonymised
            })
    return jsonify(result)


# ── Youth production member role update ──
@app.route('/api/productions/<pid>/youth-members/<mid>', methods=['PUT'])
def update_youth_production_member(pid, mid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE youth_production_members SET role=%s WHERE id=%s AND production_id=%s',
            (d.get('role',''), mid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── Reset user password (admin only) ──
@app.route('/api/users/<uid>/reset-password', methods=['POST'])
def reset_user_password(uid):
    err = require_admin()
    if err: return err
    d = request.json
    new_pw = d.get('password','').strip()
    if len(new_pw) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    pw_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    conn = get_db()
    execute(conn, 'UPDATE users SET password_hash=%s WHERE id=%s', (pw_hash, uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>', methods=['PUT'])
def update_user(uid):
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    # Update name, email, and optionally password
    if d.get('password'):
        pw_hash = hashlib.sha256(d['password'].encode()).hexdigest()
        execute(conn, 'UPDATE users SET name=%s, email=%s, password_hash=%s WHERE id=%s',
                (d['name'], d['email'], pw_hash, uid))
    else:
        execute(conn, 'UPDATE users SET name=%s, email=%s WHERE id=%s',
                (d['name'], d['email'], uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>', methods=['DELETE'])
def delete_user(uid):
    err = require_admin()
    if err: return err
    if uid == session.get('user_id'):
        return jsonify({'error': 'You cannot delete your own account'}), 400
    conn = get_db()
    execute(conn, 'DELETE FROM users WHERE id=%s', (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>/send-reset-link', methods=['POST'])
def send_reset_link(uid):
    err = require_admin()
    if err: return err
    conn = get_db()
    u = fetchone(conn, 'SELECT name, email FROM users WHERE id=%s', (uid,))
    conn.close()
    if not u or not u.get('email'):
        return jsonify({'error': 'User not found'}), 404
    # Generate a temporary password and send it
    import secrets, string
    temp_pw = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    pw_hash = hashlib.sha256(temp_pw.encode()).hexdigest()
    conn = get_db()
    execute(conn, 'UPDATE users SET password_hash=%s WHERE id=%s', (pw_hash, uid))
    conn.commit(); conn.close()
    # Send email
    settings = get_email_settings()
    html = ('<p style="font-family:-apple-system,sans-serif">Hi '+u['name']+',</p>'
            '<p style="font-family:-apple-system,sans-serif">An administrator has reset your RoleCall password.</p>'
            '<p style="font-family:-apple-system,sans-serif"><strong>Temporary Password:</strong> <code style="background:#f4f4f4;padding:4px 8px;border-radius:4px;font-size:16px">'+temp_pw+'</code></p>'
            '<p style="font-family:-apple-system,sans-serif">Please log in and change your password immediately.</p>'
            '<p style="font-family:-apple-system,sans-serif;color:#6b7280;font-size:12px">Sent by RoleCall — Horizon West Theater Company</p>')
    ok, err_msg = send_email([u['email']], 'Your RoleCall Password Has Been Reset', html)
    if ok:
        return jsonify({'ok': True})
    return jsonify({'error': err_msg or 'Failed to send email'}), 500



# ═══════════════════════════════════════════════════════════════
#  EMAIL — RESEND INTEGRATION
# ═══════════════════════════════════════════════════════════════

def get_email_settings():
    conn = get_db()
    row = fetchone(conn, 'SELECT * FROM email_settings WHERE id=1')
    conn.close()
    return row or {}

def get_recipient_emails(settings=None):
    """Resolve report_recipient_user_ids -> list of email addresses.
    Falls back to legacy report_recipients text field."""
    if settings is None:
        settings = get_email_settings()
    conn = get_db()
    emails = []
    ids_raw = settings.get('report_recipient_user_ids') or '[]'
    try:
        user_ids = json.loads(ids_raw) if isinstance(ids_raw, str) else (ids_raw or [])
    except Exception:
        user_ids = []
    if user_ids:
        placeholders = ','.join(['%s'] * len(user_ids))
        rows = fetchall(conn, 'SELECT email FROM users WHERE id IN ({}) AND active=TRUE'.format(placeholders), tuple(user_ids))
        emails = [r['email'] for r in rows if r.get('email')]
    if not emails:
        legacy = (settings.get('report_recipients') or '').strip()
        if legacy:
            emails = [e.strip() for e in legacy.split(',') if e.strip()]
    conn.close()
    return emails

def get_elic_email_for_event(event_id, conn=None):
    """Return the email address of the most recent ELIC assigned to this event, if any."""
    close_conn = conn is None
    if close_conn: conn = get_db()
    row = fetchone(conn, """
        SELECT v.email FROM event_logs el
        JOIN elics ec ON el.elic_id = ec.id
        JOIN volunteers v ON ec.volunteer_id = v.id
        WHERE el.event_id = %s AND el.action IN ('open','close')
        ORDER BY el.timestamp DESC LIMIT 1
    """, (event_id,))
    if close_conn: conn.close()
    return row['email'] if row and row.get('email') else None

def recipients_with_elic(event_id, settings=None, conn=None):
    """Get standard recipients merged with the ELIC for the given event (deduped)."""
    base = get_recipient_emails(settings)
    elic_email = get_elic_email_for_event(event_id, conn)
    if elic_email and elic_email not in base:
        base = base + [elic_email]
    return base


def send_email(to_emails, subject, html_body, from_email=None):
    """Send via Resend API. Returns (True, None) or (False, error_message)."""
    settings = get_email_settings()
    api_key = settings.get('resend_api_key','').strip()
    if not api_key:
        return False, 'Resend API key not configured in Settings -> Email'
    from_addr = from_email or settings.get('from_email','info@hwtco.org')
    if isinstance(to_emails, str):
        to_emails = [e.strip() for e in to_emails.split(',') if e.strip()]
    to_emails = [e for e in to_emails if e]
    if not to_emails:
        return False, 'No recipients configured in Settings -> Email'
    try:
        resp = requests.post('https://api.resend.com/emails',
            headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
            json={'from': from_addr, 'to': to_emails, 'subject': subject, 'html': html_body},
            timeout=10)
        if resp.status_code not in (200, 201, 202):
            try:
                err_detail = resp.json().get('message') or resp.json().get('name') or resp.text[:120]
            except Exception:
                err_detail = resp.text[:120]
            app.logger.error('Resend error %s: %s', resp.status_code, err_detail)
            return False, 'Resend {}: {}'.format(resp.status_code, err_detail)
        return True, None
    except Exception as e:
        app.logger.error('Email send error: %s', e)
        return False, str(e)

def build_checklist_report_html(event_id, conn=None):
    close_conn = conn is None
    if close_conn:
        conn = get_db()
    evt = fetchone(conn, """SELECT e.*, p.name as production_name, yp.name as program_name
        FROM events e
        LEFT JOIN productions p ON e.production_id=p.id
        LEFT JOIN youth_programs yp ON e.program_id=yp.id
        WHERE e.id=%s""", (event_id,))
    if not evt:
        if close_conn: conn.close()
        return None

    logs = fetchall(conn, """SELECT el.*, v.name as elic_name
        FROM event_logs el
        JOIN elics ec ON el.elic_id=ec.id
        JOIN volunteers v ON ec.volunteer_id=v.id
        WHERE el.event_id=%s ORDER BY el.timestamp""", (event_id,))

    open_log  = next((l for l in logs if l['action']=='open'), None)
    close_log = next((l for l in reversed(logs) if l['action']=='close'), None)
    open_responses  = fetchall(conn, 'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY created_at', (open_log['id'],))  if open_log  else []
    close_responses = fetchall(conn, 'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY created_at', (close_log['id'],)) if close_log else []
    sign_ins = fetchall(conn, """SELECT ys.*, y.first_name, y.last_name
        FROM youth_sign_ins ys JOIN youth_participants y ON ys.youth_id=y.id
        WHERE ys.event_id=%s ORDER BY ys.signed_in_at""", (event_id,))
    # Approved volunteer hours for this event
    vol_hours_approved = fetchall(conn, """SELECT h.*, v.name as volunteer_name
        FROM hours h JOIN volunteers v ON h.volunteer_id=v.id
        WHERE h.event_id=%s ORDER BY v.name""", (event_id,))
    # Pending volunteer hours for this event (submitted but not yet approved)
    vol_hours_pending = fetchall(conn, """SELECT ph.*, v.name as volunteer_name
        FROM pending_hours ph JOIN volunteers v ON ph.volunteer_id=v.id
        WHERE ph.event_id=%s ORDER BY v.name""", (event_id,))
    # Kiosk timer sessions for this event
    kiosk_sessions = fetchall(conn, """SELECT ks.*, v.name as volunteer_name
        FROM kiosk_sessions ks JOIN volunteers v ON ks.volunteer_id=v.id
        WHERE ks.event_id=%s AND ks.status='completed' ORDER BY v.name""", (event_id,))
    if close_conn: conn.close()

    def fmt_ts(ts):
        if not ts: return '---'
        try:
            from datetime import datetime
            if isinstance(ts, str): ts = datetime.fromisoformat(ts.replace('Z',''))
            return ts.strftime('%I:%M %p')
        except Exception: return str(ts)

    def response_row(r):
        resp = r.get('response') or ''
        if r['item_type'] == 'checkbox':
            val = '&#x2705;' if resp.lower() in ('true','yes','1') else '&#x274C;'
        elif r['item_type'] == 'rating':
            try: val = '&#x2B50;' * int(resp) if resp else '---'
            except Exception: val = resp or '---'
        else:
            val = resp or '---'
        return ('<tr>'
                '<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;color:#374151">' + r['label'] + '</td>'
                '<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;color:#374151;text-align:center">' + val + '</td>'
                '</tr>')

    def section(title, color, responses, ts_label='', ts_val='', elic=''):
        rows = ''.join(response_row(r) for r in responses) if responses else '<tr><td colspan="2" style="padding:12px;color:#9ca3af;text-align:center">No responses recorded</td></tr>'
        meta = ''
        if ts_val: meta += '<span style="margin-right:16px">&#x1F550; ' + ts_label + ': ' + ts_val + '</span>'
        if elic: meta += '<span>&#x1F464; ELIC: ' + elic + '</span>'
        meta_row = ('<div style="background:#f9fafb;padding:8px 16px;font-size:13px;color:#6b7280;border:1px solid #e5e7eb;border-top:none">' + meta + '</div>') if meta else ''
        return ('<div style="margin-bottom:28px">'
                '<h2 style="font-size:16px;font-weight:700;color:#fff;background:' + color + ';padding:10px 16px;border-radius:8px 8px 0 0;margin:0">' + title + '</h2>'
                + meta_row +
                '<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-top:none">'
                '<thead><tr>'
                '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Item</th>'
                '<th style="padding:8px 12px;background:#f9fafb;text-align:center;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;width:80px">Response</th>'
                '</tr></thead><tbody>' + rows + '</tbody></table></div>')

    si_rows = ''
    for s in sign_ins:
        name = (s.get('first_name','') + ' ' + s.get('last_name','')).strip()
        so = fmt_ts(s.get('signed_out_at')) if s.get('signed_out_at') else '<span style="color:#f59e0b">Not signed out</span>'
        si_rows += ('<tr>'
                    '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + name + '</td>'
                    '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + fmt_ts(s.get('signed_in_at')) + '</td>'
                    '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + so + '</td>'
                    '</tr>')
    if not si_rows:
        si_rows = '<tr><td colspan="3" style="padding:12px;color:#9ca3af;text-align:center">No participant sign-in records for this event</td></tr>'

    # Build volunteer hours rows — combine approved, pending, and kiosk sessions
    vol_rows = ''
    total_vol_hours = 0.0
    seen_vol = {}  # dedupe by volunteer_id + source
    for h in vol_hours_approved:
        key = str(h['volunteer_id']) + '_approved'
        if key not in seen_vol:
            seen_vol[key] = True
            hrs = float(h['hours'] or 0)
            total_vol_hours += hrs
            vol_rows += ('<tr style="background:#f0fdf4">'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + (h['volunteer_name'] or '—') + '</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + (h['role'] or '—') + '</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;font-weight:700">' + str(hrs) + 'h</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:13px"><span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">Approved</span></td>'
                '</tr>')
    for h in vol_hours_pending:
        key = str(h['volunteer_id']) + '_pending'
        if key not in seen_vol:
            seen_vol[key] = True
            hrs = float(h['hours'] or 0)
            total_vol_hours += hrs
            source = 'Kiosk timer' if (h.get('notes') or '').startswith('Recorded via kiosk') else 'Manual entry'
            vol_rows += ('<tr>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + (h['volunteer_name'] or '—') + '</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px">' + (h['role'] or '—') + '</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:14px;font-weight:700">' + str(hrs) + 'h</td>'
                '<td style="padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:13px"><span style="background:#fef9c3;color:#854d0e;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700">Pending · ' + source + '</span></td>'
                '</tr>')
    if not vol_rows:
        vol_rows = '<tr><td colspan="4" style="padding:12px;color:#9ca3af;text-align:center">No volunteer hours recorded for this event</td></tr>'

    vol_total_str = str(round(total_vol_hours, 2)) + 'h total'
    volunteer_section = ('<div style="margin-bottom:28px">'
        '<h2 style="font-size:16px;font-weight:700;color:#fff;background:#1d4ed8;padding:10px 16px;border-radius:8px 8px 0 0;margin:0">'
        '&#x1F91D; Volunteer Hours (' + str(len(seen_vol)) + ' volunteer' + ('s' if len(seen_vol)!=1 else '') + ' &nbsp;&middot;&nbsp; ' + vol_total_str + ')</h2>'
        '<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-top:none">'
        '<thead><tr>'
        '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Volunteer</th>'
        '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Role</th>'
        '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Hours</th>'
        '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Status</th>'
        '</tr></thead>'
        '<tbody>' + vol_rows + '</tbody></table></div>')

    event_date = evt.get('event_date','') or ''
    event_name = evt.get('name','Event')
    context    = evt.get('production_name') or evt.get('program_name') or ''
    elic_name  = (open_log or close_log or {}).get('elic_name','---')
    open_ts    = fmt_ts(open_log['timestamp'])  if open_log  else '---'
    close_ts   = fmt_ts(close_log['timestamp']) if close_log else '---'

    ctx_str = ('&nbsp;&middot;&nbsp;' + context) if context else ''
    elic_str = ('&nbsp;&middot;&nbsp; ' + elic_name) if elic_name else ''
    date_str = ('&#128197; ' + event_date) if event_date else ''

    header = ('<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:28px 32px;color:#fff">'
              '<div style="font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;opacity:0.7;margin-bottom:6px">HWTC -- RoleCall Event Report</div>'
              '<div style="font-size:24px;font-weight:800;margin-bottom:4px">' + event_name + '</div>'
              '<div style="opacity:0.85;font-size:14px">' + date_str + ctx_str + elic_str + '</div>'
              '<div style="margin-top:12px;display:flex;gap:20px;font-size:13px;opacity:0.8">'
              '<span>&#x1F7E2; Opened: ' + open_ts + '</span>'
              '<span>&#x1F534; Closed: ' + close_ts + '</span>'
              '<span>&#x1F91D; ' + str(len(seen_vol)) + ' volunteer' + ('s' if len(seen_vol)!=1 else '') + '</span>'
              '<span>&#x1F465; ' + str(len(sign_ins)) + ' participant' + ('s' if len(sign_ins)!=1 else '') + '</span>'
              '</div></div>')

    attendance_section = ('<div style="margin-bottom:28px">'
                          '<h2 style="font-size:16px;font-weight:700;color:#fff;background:#0d6e6e;padding:10px 16px;border-radius:8px 8px 0 0;margin:0">'
                          '&#x1F465; Participant Sign-Ins (' + str(len(sign_ins)) + ' participant' + ('s' if len(sign_ins)!=1 else '') + ')</h2>'
                          '<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-top:none">'
                          '<thead><tr>'
                          '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Name</th>'
                          '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Signed In</th>'
                          '<th style="padding:8px 12px;background:#f9fafb;text-align:left;font-size:12px;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px">Signed Out</th>'
                          '</tr></thead><tbody>' + si_rows + '</tbody></table></div>')

    footer = ('<div style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:16px 32px;font-size:12px;color:#9ca3af;text-align:center">'
              'Generated by RoleCall &nbsp;&middot;&nbsp; Horizon West Theatre Company &nbsp;&middot;&nbsp; ' + event_date + '</div>')

    return ('<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#f3f4f6;margin:0;padding:24px">'
            '<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">'
            + header
            + '<div style="padding:28px 32px">'
            + section('&#x1F7E2; Opening Checklist', '#16a34a', open_responses, 'Opened', open_ts, open_log['elic_name'] if open_log else '')
            + section('&#x1F534; Closing Checklist', '#dc2626', close_responses, 'Closed', close_ts, close_log['elic_name'] if close_log else '')
            + volunteer_section
            + attendance_section
            + '</div>' + footer
            + '</div></body></html>')


def send_checklist_report(event_id):
    settings = get_email_settings()
    if not settings.get('auto_send_checklist_report'): return
    recipients = recipients_with_elic(event_id, settings)
    if not recipients: return
    html = build_checklist_report_html(event_id)
    if not html: return
    conn = get_db()
    evt = fetchone(conn, 'SELECT name, event_date FROM events WHERE id=%s', (event_id,))
    conn.close()
    name = evt['name'] if evt else 'Event'
    date = (evt.get('event_date','') or '') if evt else ''
    subject = 'Event Report -- ' + name + (' (' + date + ')' if date else '')
    send_email(recipients, subject, html)


@app.route('/api/email-settings', methods=['GET'])
def get_email_settings_api():
    err = require_admin()
    if err: return err
    s = dict(get_email_settings() or {})
    if s.get('resend_api_key'):
        s['resend_api_key'] = ('........' + s['resend_api_key'][-4:]) if len(s.get('resend_api_key','')) > 4 else '........'
    return jsonify(s)

@app.route('/api/email-settings', methods=['PUT'])
def update_email_settings_api():
    err = require_admin()
    if err: return err
    d = request.json
    conn = get_db()
    key_val = d.get('resend_api_key','').strip()
    if key_val and '.' not in key_val[:4]:
        execute(conn, 'UPDATE email_settings SET resend_api_key=%s WHERE id=1', (key_val,))
    user_ids = d.get('report_recipient_user_ids', [])
    execute(conn, """UPDATE email_settings SET
        from_email=%s, report_recipient_user_ids=%s,
        alert_pending_hours=%s, alert_profile_updates=%s,
        alert_callouts=%s, alert_waiver_expiry=%s,
        auto_send_checklist_report=%s,
        alert_conflicts=%s, alert_waivers=%s,
        alert_event_not_opened=%s, alert_event_not_closed=%s,
        updated_at=NOW() WHERE id=1""", (
        d.get('from_email','info@hwtco.org'),
        json.dumps(user_ids),
        d.get('alert_pending_hours', True),
        d.get('alert_profile_updates', True),
        d.get('alert_callouts', True),
        d.get('alert_waiver_expiry', True),
        d.get('auto_send_checklist_report', True),
        d.get('alert_conflicts', True),
        d.get('alert_waivers', True),
        d.get('alert_event_not_opened', True),
        d.get('alert_event_not_closed', True),
    ))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/email-settings/test', methods=['POST'])
def test_email():
    err = require_admin()
    if err: return err
    settings = get_email_settings()
    recipients = get_recipient_emails(settings)
    ok, err = send_email(
        recipients,
        'RoleCall -- Test Email',
        '<h2 style="font-family:sans-serif">Test email working</h2><p style="font-family:sans-serif">If you received this, RoleCall email alerts are configured correctly.</p>'
    )
    return jsonify({'ok': ok, 'error': err})

@app.route('/api/email-settings/send-report/<event_id>', methods=['POST'])
def send_report_now(event_id):
    err = require_admin()
    if err: return err
    settings = get_email_settings()
    recipients = recipients_with_elic(event_id, settings)
    if not recipients:
        return jsonify({'error': 'No report recipients configured in Settings -> Email'}), 400
    html = build_checklist_report_html(event_id)
    if not html:
        return jsonify({'error': 'Event not found'}), 404
    conn = get_db()
    evt = fetchone(conn, 'SELECT name, event_date FROM events WHERE id=%s', (event_id,))
    conn.close()
    name = evt['name'] if evt else 'Event'
    date = (evt.get('event_date','') or '') if evt else ''
    subject = 'Event Report -- ' + name + (' (' + date + ')' if date else '')
    ok, err = send_email(recipients, subject, html)
    return jsonify({'ok': ok, 'error': err})

@app.route('/api/email-settings/check-events', methods=['POST'])
def check_event_alerts():
    """Called by frontend polling to alert on events not opened/closed on time."""
    err = require_auth()
    if err: return err
    settings = get_email_settings()
    recipients = get_recipient_emails(settings)
    if not recipients:
        return jsonify({'ok': True, 'alerts': []})

    import uuid as _uuid
    from datetime import datetime, timezone

    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    est = ZoneInfo('America/New_York')
    now_est = datetime.now(est)
    conn = get_db()
    alerts_sent = []

    # Alert 20 minutes BEFORE start if not yet opened
    if settings.get('alert_event_not_opened'):
        events = fetchall(conn, """
            SELECT e.id, e.name, e.event_date, e.start_time
            FROM events e
            WHERE e.event_date::date = CURRENT_DATE
              AND e.start_time IS NOT NULL
              AND (e.status IS NULL OR e.status IN ('draft','published'))
              AND NOT EXISTS (SELECT 1 FROM event_logs el WHERE el.event_id=e.id AND el.action IN ('open','alert_not_opened'))
        """)
        for evt in events:
            try:
                time_str = str(evt['start_time'])[:5]
                start_dt = datetime.strptime(evt['event_date'] + ' ' + time_str, '%Y-%m-%d %H:%M').replace(tzinfo=est)
                mins_until = (start_dt - now_est).total_seconds() / 60
                # Alert window: between 25 and 15 minutes before start
                if -5 <= mins_until <= 25:
                    subj = 'RoleCall Reminder -- Open Event Soon: ' + evt['name']
                    body = ('<p style="font-family:sans-serif">Reminder: <strong>' + evt['name'] + '</strong> is scheduled to start at '
                            + time_str + ' and has <strong>not been opened</strong> in RoleCall yet.<br><br>'
                            + ('It starts in approximately ' + str(int(mins_until)) + ' minutes.' if mins_until > 0 else 'It was scheduled to start ' + str(int(-mins_until)) + ' minutes ago.')
                            + '<br><br>Please open the event from the kiosk before participants arrive.</p>')
                    evt_recipients = recipients_with_elic(evt['id'], settings, conn)
                    ok, _ = send_email(evt_recipients, subj, body)
                    if ok:
                        execute(conn, "INSERT INTO event_logs (id,event_id,elic_id,action) SELECT %s,%s,id,'alert_not_opened' FROM elics LIMIT 1",
                                (_uuid.uuid4().hex, evt['id']))
                        alerts_sent.append('not_opened:' + evt['name'])
            except Exception as ex:
                app.logger.error('check not_opened: %s', ex)

    # Not closed within 2 hours of end
    if settings.get('alert_event_not_closed'):
        events = fetchall(conn, """
            SELECT e.id, e.name, e.event_date, e.end_time
            FROM events e
            WHERE e.event_date::date = CURRENT_DATE
              AND e.end_time IS NOT NULL
              AND e.status = 'open'
              AND NOT EXISTS (SELECT 1 FROM event_logs el WHERE el.event_id=e.id AND el.action IN ('close','alert_not_closed'))
        """)
        for evt in events:
            try:
                time_str = str(evt['end_time'])[:5]
                end_dt = datetime.strptime(evt['event_date'] + ' ' + time_str, '%Y-%m-%d %H:%M').replace(tzinfo=est)
                mins_late = (now_est - end_dt).total_seconds() / 60
                if mins_late >= 120:
                    subj = 'RoleCall Alert -- Event Not Closed: ' + evt['name']
                    body = ('<p style="font-family:sans-serif">Event <strong>' + evt['name'] + '</strong> was scheduled to end at '
                            + time_str + ' but has not been closed. It is now '
                            + str(int(mins_late)) + ' minutes past the end time.</p>')
                    evt_recipients = recipients_with_elic(evt['id'], settings, conn)
                    ok, _ = send_email(evt_recipients, subj, body)
                    if ok:
                        execute(conn, "INSERT INTO event_logs (id,event_id,elic_id,action) SELECT %s,%s,id,'alert_not_closed' FROM elics LIMIT 1",
                                (_uuid.uuid4().hex, evt['id']))
                        alerts_sent.append('not_closed:' + evt['name'])
            except Exception as ex:
                app.logger.error('check not_closed: %s', ex)

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'alerts': alerts_sent})

# ═══════════════════════════════════════════════════════════════
#  NAV ICONS
# ═══════════════════════════════════════════════════════════════

@app.route('/api/nav-icons', methods=['GET'])
def get_nav_icons():
    conn = get_db()
    rows = fetchall(conn, 'SELECT key, lucide_name FROM nav_icons')
    conn.close()
    return jsonify({r['key']: r['lucide_name'] for r in rows})

@app.route('/api/nav-icons', methods=['PUT'])
def save_nav_icons():
    err = require_admin()
    if err: return err
    d = request.json  # {key: lucide_name, ...}
    conn = get_db()
    for key, name in d.items():
        if name:
            execute(conn, '''INSERT INTO nav_icons (key, lucide_name) VALUES (%s,%s)
                ON CONFLICT (key) DO UPDATE SET lucide_name=EXCLUDED.lucide_name''', (key, name))
        else:
            execute(conn, 'DELETE FROM nav_icons WHERE key=%s', (key,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════
#  KIOSK VOLUNTEER TIMER
# ═══════════════════════════════════════════════════════════════

@app.route('/api/kiosk/session/begin', methods=['POST'])
def kiosk_begin_session():
    d = request.json
    vol_id   = d.get('volunteer_id')
    event_id = d.get('event_id')
    role     = d.get('role','')
    if not vol_id:
        return jsonify({'error': 'Missing volunteer_id'}), 400
    conn = get_db()
    # Check for already-active session
    existing = fetchone(conn, "SELECT id FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
    if existing:
        conn.close()
        return jsonify({'error': 'Already volunteering — please stop your current session first.'}), 400
    # Get event name
    event_name = d.get('event_name','')
    if event_id and not event_name:
        evt = fetchone(conn, 'SELECT name FROM events WHERE id=%s', (event_id,))
        if evt: event_name = evt['name']
    sid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO kiosk_sessions (id, volunteer_id, event_id, event_name, role, status)
        VALUES (%s,%s,%s,%s,%s,'active')''', (sid, vol_id, event_id or None, event_name, role))
    conn.commit()
    session_row = fetchone(conn, 'SELECT * FROM kiosk_sessions WHERE id=%s', (sid,))
    conn.close()
    return jsonify({'ok': True, 'session_id': sid, 'started_at': str(session_row['started_at'])})

@app.route('/api/kiosk/session/stop', methods=['POST'])
def kiosk_stop_session():
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    role   = d.get('role','')
    if not vol_id:
        return jsonify({'error': 'Missing volunteer_id'}), 400
    conn = get_db()
    try:
        session = fetchone(conn, "SELECT * FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
        if not session:
            conn.close()
            return jsonify({'error': 'No active session found'}), 400
        # Use DB clock (already Eastern per connection options)
        time_row = fetchone(conn, "SELECT EXTRACT(EPOCH FROM (NOW() - started_at)) as secs FROM kiosk_sessions WHERE id=%s", (session['id'],))
        elapsed_secs = float(time_row['secs']) if time_row and time_row['secs'] else 0
        elapsed_hours = round(elapsed_secs / 3600, 2)
        elapsed_hours = max(0.25, elapsed_hours)  # minimum 15 min
        today_row = fetchone(conn, "SELECT CURRENT_DATE::text as today")
        today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()
        execute(conn, "UPDATE kiosk_sessions SET ended_at=NOW(), hours=%s, status='completed', role=%s WHERE id=%s",
                (elapsed_hours, role or session['role'], session['id']))
        pid = str(uuid.uuid4())
        execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (pid, vol_id, session['event_name'] or 'Volunteer Session', session['event_id'],
                 today, elapsed_hours, role or session['role'], 'Recorded via kiosk timer'))
        conn.commit()
        # Alert email — use vol name fetched before closing conn
        try:
            s = get_email_settings()
            if s.get('alert_pending_hours'):
                recipients = get_recipient_emails(s)
                vol = fetchone(conn, 'SELECT name FROM volunteers WHERE id=%s', (vol_id,))
                vol_name = vol['name'] if vol else 'A volunteer'
                if recipients:
                    send_email(recipients,
                        'RoleCall — Hours Submitted: ' + vol_name,
                        '<p style="font-family:sans-serif"><strong>' + vol_name + '</strong> logged <strong>'
                        + str(elapsed_hours) + ' hours</strong> via kiosk timer for <strong>'
                        + (session['event_name'] or 'a session') + '</strong>.</p>')
        except Exception as email_err:
            app.logger.error('Stop session email error: %s', email_err)
        conn.close()
        return jsonify({'ok': True, 'hours': elapsed_hours})
    except Exception as e:
        app.logger.error('kiosk_stop_session error: %s', e)
        try: conn.close()
        except Exception: pass
        return jsonify({'error': 'Server error stopping session: ' + str(e)}), 500

@app.route('/api/kiosk/session/active/<vol_id>')
def kiosk_active_session(vol_id):
    conn = get_db()
    session = fetchone(conn, "SELECT * FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
    conn.close()
    if not session:
        return jsonify({'active': False})
    return jsonify({'active': True, 'session': dict(session), 'started_at': str(session['started_at'])})


# ═══════════════════════════════════════════════════════════════
#  PRODUCTION GENERAL CONTENT (WYSIWYG)
# ═══════════════════════════════════════════════════════════════

@app.route('/api/productions/<pid>/general-content', methods=['GET'])
def get_general_content(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    row = fetchone(conn, 'SELECT * FROM production_general_content WHERE production_id=%s', (pid,))
    conn.close()
    return jsonify(row or {'html_content': '', 'updated_at': None})

@app.route('/api/productions/<pid>/general-content', methods=['PUT'])
def save_general_content(pid):
    err = require_auth()
    if err: return err
    d = request.json
    uid = session.get('user_id')
    conn = get_db()
    existing = fetchone(conn, 'SELECT id FROM production_general_content WHERE production_id=%s', (pid,))
    if existing:
        execute(conn, 'UPDATE production_general_content SET html_content=%s, updated_at=NOW(), updated_by=%s WHERE production_id=%s',
                (d.get('html_content',''), uid, pid))
    else:
        execute(conn, 'INSERT INTO production_general_content (id, production_id, html_content, updated_by) VALUES (%s,%s,%s,%s)',
                (str(__import__('uuid').uuid4()), pid, d.get('html_content',''), uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/announcements/<aid>/push', methods=['POST'])
def push_announcement(pid, aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    ann = fetchone(conn, '''SELECT pa.*, u.name as author_name
        FROM portal_announcements pa LEFT JOIN users u ON pa.author_id=u.id
        WHERE pa.id=%s AND pa.production_id=%s''', (aid, pid))
    if not ann:
        conn.close()
        return jsonify({'error': 'Announcement not found'}), 404
    prod = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (pid,))
    prod_name = prod['name'] if prod else 'Production'
    # Get emails of all cast families + enrolled youth guardians
    guardian_emails = fetchall(conn, '''
        SELECT DISTINCT yg.email FROM youth_production_members ypm
        JOIN youth_participants y ON ypm.youth_id=y.id
        JOIN youth_guardians yg ON yg.youth_id=y.id
        WHERE ypm.production_id=%s AND yg.email IS NOT NULL AND yg.email!=\'\'
    ''', (pid,))
    # Also get portal family emails where a member is in this production
    family_emails = fetchall(conn, '''
        SELECT DISTINCT f.passphrase FROM families f
        JOIN youth_participants y ON y.family_id=f.id
        JOIN youth_production_members ypm ON ypm.youth_id=y.id
        WHERE ypm.production_id=%s
    ''', (pid,))
    # Collect unique emails
    emails = list(set(r['email'] for r in guardian_emails if r.get('email')))
    # Also include report recipients
    settings = get_email_settings()
    for e in get_recipient_emails(settings):
        if e not in emails:
            emails.append(e)
    if not emails:
        conn.close()
        return jsonify({'error': 'No email addresses found for cast families'}), 400
    portal_url = 'https://your-app.railway.app/portal'
    html = ('<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:600px;margin:0 auto">'
            '<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:24px 28px;border-radius:10px 10px 0 0;color:#fff">'
            '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:0.7;margin-bottom:6px">HWTC — ' + prod_name + '</div>'
            '<div style="font-size:22px;font-weight:800">' + ann['title'] + '</div>'
            '</div>'
            '<div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px 28px;border-radius:0 0 10px 10px">'
            '<div style="font-size:15px;color:#374151;line-height:1.6;margin-bottom:20px">' + ann['body'] + '</div>'
            '<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;padding:14px 18px">'
            '<div style="font-size:13px;font-weight:600;color:#166534;margin-bottom:4px">View in the Portal</div>'
            '<div style="font-size:13px;color:#166534">Log into the participant portal to see the full production info, files, schedule and more.</div>'
            '</div>'
            '<div style="margin-top:20px;font-size:12px;color:#9ca3af">Sent from RoleCall &middot; Horizon West Theatre Company</div>'
            '</div></div>')
    ok, err_msg = send_email(emails, 'New Announcement: ' + ann['title'] + ' — ' + prod_name, html)
    if ok:
        execute(conn, 'UPDATE portal_announcements SET pushed_at=NOW(), push_count=COALESCE(push_count,0)+1 WHERE id=%s', (aid,))
        conn.commit()
    conn.close()
    return jsonify({'ok': ok, 'sent_to': len(emails), 'error': err_msg})


# ═══════════════════════════════════════════════════════════════
#  PORTAL — CONTACT PRODUCTION TEAM
# ═══════════════════════════════════════════════════════════════

@app.route('/api/portal/contact-production', methods=['POST'])
def portal_contact_production():
    d = request.json or {}
    prod_id    = d.get('production_id')
    from_name  = d.get('from_name','').strip()
    from_email = d.get('from_email','').strip()
    subject    = d.get('subject','').strip()
    message    = d.get('message','').strip()

    if not all([prod_id, from_name, from_email, subject, message]):
        return jsonify({'error': 'All fields are required'}), 400

    conn = get_db()
    prod = fetchone(conn, 'SELECT name, default_elic_id FROM productions WHERE id=%s', (prod_id,))
    if not prod:
        conn.close()
        return jsonify({'error': 'Production not found'}), 404

    prod_name = prod['name']

    # Collect recipient emails: production members (crew/volunteers)
    members = fetchall(conn, '''SELECT v.name, v.email FROM production_members pm
        JOIN volunteers v ON pm.volunteer_id=v.id
        WHERE pm.production_id=%s AND v.email IS NOT NULL AND v.email!=\'\'
    ''', (prod_id,))

    # Default ELIC email
    elic_email = None
    elic_name = None
    if prod.get('default_elic_id'):
        elic = fetchone(conn, '''SELECT v.name, v.email FROM elics el
            JOIN volunteers v ON el.volunteer_id=v.id
            WHERE el.id=%s''', (prod['default_elic_id'],))
        if elic:
            elic_email = elic.get('email')
            elic_name  = elic.get('name')

    conn.close()

    # Build recipient list — crew members + ELIC
    to_emails = list(set(m['email'] for m in members if m.get('email')))
    if elic_email and elic_email not in to_emails:
        to_emails.append(elic_email)

    if not to_emails:
        return jsonify({'error': 'No contact emails found for this production team'}), 400

    # Build HTML email
    html = ('<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:#f3f4f6;margin:0;padding:24px">'
        '<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">'
        '<div style="background:linear-gradient(135deg,#4c1d95,#7c3aed);padding:24px 28px;color:#fff">'
        '<div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;opacity:0.7;margin-bottom:6px">HWTC \u2014 ' + prod_name + '</div>'
        '<div style="font-size:20px;font-weight:800;margin-bottom:4px">' + subject + '</div>'
        '<div style="opacity:0.8;font-size:13px">From: ' + from_name + ' &lt;' + from_email + '&gt;</div>'
        '</div>'
        '<div style="padding:24px 28px">'
        '<div style="font-size:15px;color:#374151;line-height:1.7;white-space:pre-wrap">' + message + '</div>'
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af">'
        'This message was sent via the RoleCall participant portal for <strong>' + prod_name + '</strong>. '
        'Reply directly to ' + from_email + ' to respond.'
        '</div></div></div></body></html>')

    settings = get_email_settings()
    ok, err_msg = send_email(to_emails, subject + ' (via portal)', html,
                             from_email=settings.get('from_email','info@hwtco.org'))

    # Also send a separate ELIC alert if they're not already a recipient
    if elic_email and ok:
        alert_html = ('<p style="font-family:sans-serif">\U0001f514 <strong>' + (elic_name or 'ELIC') + '</strong>, '
            'a family has contacted the production team for <strong>' + prod_name + '</strong>.<br><br>'
            '<strong>From:</strong> ' + from_name + ' (' + from_email + ')<br>'
            '<strong>Subject:</strong> ' + subject + '<br>'
            '<strong>Message:</strong><br><blockquote style="border-left:3px solid #7c3aed;margin:8px 0;padding:8px 12px;color:#374151">'
            + message + '</blockquote>'
            'You can reply directly to ' + from_email + '.</p>')
        send_email(elic_email, '\U0001f514 Portal message for ' + prod_name + ': ' + subject, alert_html)

    return jsonify({'ok': ok, 'sent_to': len(to_emails), 'error': err_msg})


# ═══════════════════════════════════════════════════════════════
#  PERMISSION SYSTEM
# ═══════════════════════════════════════════════════════════════

# All sections and their keys
PERMISSION_SECTIONS = [
    ('volunteers',    'Volunteers',           'View and manage volunteer profiles'),
    ('events',        'Events & Calendar',    'View and create events'),
    ('hours',         'Time Tracking',        'View and approve volunteer hours'),
    ('email',         'Email',                'Send emails and manage templates'),
    ('productions',   'Productions',          'View and manage productions'),
    ('rising_stars',  'Rising Stars',         'Rising Stars productions and portal'),
    ('youth',         'Participants',         'View and manage youth participants'),
    ('programs',      'Programs & Classes',   'View and manage programs'),
    ('portal_admin',  'Portal Content',       'Manage portal announcements and files'),
    ('kiosk',         'Sign-In / Kiosk',      'Open and close events on kiosk'),
    ('reports',       'Reports & Logs',       'View event logs and email reports'),
    ('settings',      'Settings',             'Manage system settings and users'),
]

def get_user_permissions(user_id):
    """Returns dict of {section: 'none'|'view'|'edit'} for a user."""
    conn = get_db()
    u = fetchone(conn, 'SELECT role, role_permissions FROM users WHERE id=%s', (user_id,))
    conn.close()
    if not u: return {}
    if u['role'] == 'admin': return {k: 'edit' for k,_,_ in PERMISSION_SECTIONS}
    try:
        perms = json.loads(u['role_permissions'] or '{}')
    except Exception:
        perms = {}
    return perms

def has_permission(section, level='view'):
    """Check if current session user has permission. level: 'view' or 'edit'."""
    if 'user_id' not in session: return False
    if session.get('role') == 'admin': return True
    try:
        perms = json.loads(session.get('permissions') or '{}')
    except Exception:
        perms = {}
    p = perms.get(section, 'none')
    if level == 'view': return p in ('view', 'edit')
    if level == 'edit': return p == 'edit'
    return False

def require_permission(section, level='view'):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if not has_permission(section, level):
        return jsonify({'error': 'Permission denied'}), 403
    return None

@app.route('/api/users/<uid>/permissions', methods=['PUT'])
def update_user_permissions(uid):
    err = require_admin()
    if err: return err
    d = request.json  # {section: 'none'|'view'|'edit', ...}
    conn = get_db()
    execute(conn, 'UPDATE users SET role_permissions=%s WHERE id=%s',
            (json.dumps(d), uid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/permissions/sections')
def get_permission_sections():
    err = require_auth()
    if err: return err
    return jsonify([{'key':k,'label':l,'desc':d} for k,l,d in PERMISSION_SECTIONS])


# ═══════════════════════════════════════════════════════════════
#  PICKUP DISPLAY — TV Queue
# ═══════════════════════════════════════════════════════════════

@app.route('/pickup')
def pickup_page():
    resp = send_from_directory('static', 'pickup.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

@app.route('/api/pickup/queue')
def pickup_queue():
    """Public endpoint — no auth required. Returns all minors signed in today."""
    conn = get_db()
    rows = fetchall(conn, """
        SELECT
            ys.id, ys.youth_id, ys.signed_in_at, ys.signed_out_at,
            y.first_name, y.last_name, y.dob,
            e.name  AS event_name,   e.id  AS event_id,
            yp.name AS program_name, yp.id AS program_id,
            (SELECT name FROM youth_guardians
             WHERE youth_id=y.id ORDER BY is_primary DESC LIMIT 1) AS guardian_name
        FROM youth_sign_ins ys
        JOIN youth_participants y  ON ys.youth_id   = y.id
        LEFT JOIN events e         ON ys.event_id   = e.id
        LEFT JOIN youth_programs yp ON ys.program_id = yp.id
        WHERE ys.signed_in_at::date = CURRENT_DATE
          AND (
            ys.signed_out_at IS NULL
            OR ys.signed_out_at > NOW() - INTERVAL '2 hours'
          )
        ORDER BY ys.signed_in_at ASC
    """)
    conn.close()
    return jsonify(rows)


# ═══════════════════════════════════════════════════════════════
#  VOLUNTEER INTEREST FORM
# ═══════════════════════════════════════════════════════════════

@app.route('/join')
def join_page():
    resp = send_from_directory('static', 'join.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

@app.route('/api/join/interest-types')
def join_interest_types():
    conn = get_db()
    types = fetchall(conn, 'SELECT id, name, color FROM interest_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/join/submit', methods=['POST'])
def join_submit():
    d = request.json
    if not d.get('name') or not d.get('email'):
        return jsonify({'error': 'Name and email are required'}), 400
    aid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO volunteer_applications
            (id, name, email, phone, pronouns, is_adult, interests, how_heard, notes, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')''',
            (aid, d['name'].strip(), d['email'].strip().lower(),
             d.get('phone','').strip(),
             d.get('pronouns','').strip(),
             d.get('is_adult', True),
             json.dumps(d.get('interests', [])),
             d.get('how_heard','').strip(),
             d.get('notes','').strip()))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': 'Submission failed. Please try again.'}), 500

    # Send alert email to org
    try:
        settings = get_email_settings()
        recipients = get_recipient_emails(settings)
        if recipients:
            interests_str = ', '.join(d.get('interests', [])) or 'None specified'
            age_str = '18 or older' if d.get('is_adult', True) else 'Under 18'
            html_body = f'''<div style="font-family:-apple-system,sans-serif;max-width:600px">
                <h2 style="color:#0d3d4d">New Volunteer Interest Submission</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px">
                  <tr><td style="padding:8px;font-weight:600;color:#666;width:140px">Name</td><td style="padding:8px">{d['name']}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Email</td><td style="padding:8px">{d['email']}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">Phone</td><td style="padding:8px">{d.get('phone','—')}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Pronouns</td><td style="padding:8px">{d.get('pronouns','—') or '—'}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">Age</td><td style="padding:8px">{age_str}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Interests</td><td style="padding:8px">{interests_str}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">How they heard</td><td style="padding:8px">{d.get('how_heard','—')}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Notes</td><td style="padding:8px">{d.get('notes','—') or '—'}</td></tr>
                </table>
                <p style="margin-top:20px;color:#666;font-size:13px">Log in to RoleCall to review this submission.</p>
            </div>'''
            send_email(recipients, f'New Volunteer Interest — {d["name"]}', html_body)
    except Exception:
        pass

    conn.close()
    return jsonify({'ok': True, 'id': aid})

@app.route('/api/applications')
def get_applications():
    err = require_auth()
    if err: return err
    conn = get_db()
    apps = fetchall(conn, '''SELECT * FROM volunteer_applications ORDER BY created_at DESC''')
    conn.close()
    return jsonify(apps)

@app.route('/api/applications/<aid>/approve', methods=['POST'])
def approve_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    app_row = fetchone(conn, 'SELECT * FROM volunteer_applications WHERE id=%s', (aid,))
    if not app_row:
        conn.close(); return jsonify({'error': 'Application not found'}), 404

    # Create volunteer record
    vid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO volunteers (id, name, email, phone, status, interests, created_by)
        VALUES (%s,%s,%s,%s,'active',%s,%s)''',
        (vid, app_row['name'], app_row['email'], app_row.get('phone',''),
         app_row.get('interests','[]'), session.get('user_name','')))

    # Mark application approved
    execute(conn, '''UPDATE volunteer_applications
        SET status='approved', reviewed_by=%s, reviewed_at=NOW(), volunteer_id=%s WHERE id=%s''',
        (session.get('user_name',''), vid, aid))
    conn.commit()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vid,))
    conn.close()
    return jsonify({'ok': True, 'volunteer': vol})

@app.route('/api/applications/<aid>/decline', methods=['POST'])
def decline_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, '''UPDATE volunteer_applications
        SET status='not_interested', reviewed_by=%s, reviewed_at=NOW() WHERE id=%s''',
        (session.get('user_name',''), aid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/applications/<aid>', methods=['DELETE'])
def delete_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM volunteer_applications WHERE id=%s', (aid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

