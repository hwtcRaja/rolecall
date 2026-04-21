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
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS auto_log_hours BOOLEAN DEFAULT FALSE",
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

        # ── Donor & Sponsor Management ──
        """CREATE TABLE IF NOT EXISTS donor_tiers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            min_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            max_amount NUMERIC(10,2),
            color TEXT DEFAULT 'teal',
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS donor_tier_benefits (
            id TEXT PRIMARY KEY,
            tier_id TEXT NOT NULL REFERENCES donor_tiers(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            is_trackable BOOLEAN DEFAULT TRUE,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS donor_campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            goal_amount NUMERIC(10,2),
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS donors (
            id TEXT PRIMARY KEY,
            type TEXT DEFAULT 'individual',
            display_name TEXT NOT NULL,
            legal_name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            website TEXT,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE SET NULL,
            tier_id TEXT REFERENCES donor_tiers(id) ON DELETE SET NULL,
            tier_override BOOLEAN DEFAULT FALSE,
            is_anonymous BOOLEAN DEFAULT FALSE,
            recognition_name TEXT,
            notes TEXT,
            internal_rating TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'active',
            first_donation_date TEXT,
            last_donation_date TEXT,
            total_donated NUMERIC(10,2) DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            created_by TEXT)""",

        """CREATE TABLE IF NOT EXISTS donor_donations (
            id TEXT PRIMARY KEY,
            donor_id TEXT NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
            campaign_id TEXT REFERENCES donor_campaigns(id) ON DELETE SET NULL,
            amount NUMERIC(10,2) NOT NULL,
            donation_date TEXT NOT NULL,
            type TEXT DEFAULT 'cash',
            payment_status TEXT DEFAULT 'received',
            check_number TEXT,
            notes TEXT,
            thank_you_sent BOOLEAN DEFAULT FALSE,
            thank_you_sent_at TIMESTAMP,
            thank_you_sent_by TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            created_by TEXT)""",

        """CREATE TABLE IF NOT EXISTS donor_benefit_usage (
            id TEXT PRIMARY KEY,
            donor_id TEXT NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
            benefit_id TEXT NOT NULL REFERENCES donor_tier_benefits(id) ON DELETE CASCADE,
            used_at TIMESTAMP DEFAULT NOW(),
            notes TEXT,
            recorded_by TEXT)""",

        """CREATE TABLE IF NOT EXISTS donor_communications (
            id TEXT PRIMARY KEY,
            donor_id TEXT NOT NULL REFERENCES donors(id) ON DELETE CASCADE,
            type TEXT DEFAULT 'note',
            subject TEXT,
            body TEXT,
            sent_at TIMESTAMP DEFAULT NOW(),
            sent_by TEXT)""",
    ]:
        try:
            c.execute(col_sql)
            conn.commit()
        except Exception:
            conn.rollback()

    # Seed default HWTC donor tiers if none exist
    try:
        c.execute("SELECT COUNT(*) FROM donor_tiers")
        if c.fetchone()[0] == 0:
            default_tiers = [
                ('Theatregoer',              0,      100,    'gray',   8),
                ('Dramaturg',                101,    499,    'blue',   7),
                ('Playwright',               500,    1499,   'teal',   6),
                ('Director',                 1500,   2999,   'green',  5),
                ('Associate Producer',       3000,   4999,   'amber',  4),
                ('Producer',                 5000,   6999,   'orange', 3),
                ('Executive Producer',       7000,   9999,   'purple', 2),
                ('Production Sponsor',       10000,  49999,  'pink',   1),
                ('Season Production Sponsor',50000,  None,   'red',    0),
            ]
            import uuid as _uuid2
            for name, min_a, max_a, color, sort in default_tiers:
                c.execute(
                    "INSERT INTO donor_tiers (id,name,min_amount,max_amount,color,sort_order) VALUES (%s,%s,%s,%s,%s,%s)",
                    (str(_uuid2.uuid4()), name, min_a, max_a, color, sort)
                )
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
        (id,name,event_date,end_date,start_time,end_time,event_type_id,location,room,production_id,program_id,expected_volunteers,description,notes,status,requires_background_check,auto_log_hours)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)''',
        (eid, d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False),
         d.get('auto_log_hours', False)))
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
        event_type_id=%s,location=%s,room=%s,production_id=%s,program_id=%s,expected_volunteers=%s,description=%s,notes=%s,requires_background_check=%s,auto_log_hours=%s WHERE id=%s''',
        (d['name'], d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False),
         d.get('auto_log_hours', False), eid))
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
    users = fetchall(conn, 'SELECT id,name,email,role,role_permissions,COALESCE(active,TRUE) as active FROM users ORDER BY name')
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
#  DONOR & SPONSOR MANAGEMENT
# ─────────────────────────────────────────────

# ── Tiers ──
@app.route('/api/donor-tiers')
def get_donor_tiers():
    err = require_auth()
    if err: return err
    conn = get_db()
    tiers = fetchall(conn, '''
        SELECT t.*, COUNT(b.id) as benefit_count
        FROM donor_tiers t
        LEFT JOIN donor_tier_benefits b ON b.tier_id=t.id
        GROUP BY t.id ORDER BY t.min_amount DESC''')
    for tier in tiers:
        tier['benefits'] = fetchall(conn, 'SELECT * FROM donor_tier_benefits WHERE tier_id=%s ORDER BY sort_order,name', (tier['id'],))
    conn.close()
    return jsonify(tiers)

@app.route('/api/donor-tiers', methods=['POST'])
def create_donor_tier():
    err = require_auth()
    if err: return err
    d = request.json
    tid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_tiers (id,name,min_amount,max_amount,color,description,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (tid, d['name'], d.get('min_amount',0), d.get('max_amount') or None,
         d.get('color','teal'), d.get('description',''), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_tiers WHERE id=%s', (tid,))
    row['benefits'] = []
    conn.close()
    return jsonify(row)

@app.route('/api/donor-tiers/<tid>', methods=['PUT'])
def update_donor_tier(tid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE donor_tiers SET name=%s,min_amount=%s,max_amount=%s,color=%s,description=%s,sort_order=%s WHERE id=%s',
        (d['name'], d.get('min_amount',0), d.get('max_amount') or None,
         d.get('color','teal'), d.get('description',''), d.get('sort_order',0), tid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-tiers/<tid>', methods=['DELETE'])
def delete_donor_tier(tid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donor_tiers WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Benefits ──
@app.route('/api/donor-tiers/<tid>/benefits', methods=['POST'])
def add_tier_benefit(tid):
    err = require_auth()
    if err: return err
    d = request.json
    bid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_tier_benefits (id,tier_id,name,description,is_trackable,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (bid, tid, d['name'], d.get('description',''), d.get('is_trackable',True), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_tier_benefits WHERE id=%s', (bid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-benefits/<bid>', methods=['PUT'])
def update_tier_benefit(bid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE donor_tier_benefits SET name=%s,description=%s,is_trackable=%s,sort_order=%s WHERE id=%s',
        (d['name'], d.get('description',''), d.get('is_trackable',True), d.get('sort_order',0), bid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-benefits/<bid>', methods=['DELETE'])
def delete_tier_benefit(bid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donor_tier_benefits WHERE id=%s', (bid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Campaigns ──
@app.route('/api/donor-campaigns')
def get_donor_campaigns():
    err = require_auth()
    if err: return err
    conn = get_db()
    campaigns = fetchall(conn, '''
        SELECT c.*, COALESCE(SUM(d.amount),0) as raised
        FROM donor_campaigns c
        LEFT JOIN donor_donations d ON d.campaign_id=c.id AND d.payment_status='received'
        GROUP BY c.id ORDER BY c.created_at DESC''')
    conn.close()
    return jsonify(campaigns)

@app.route('/api/donor-campaigns', methods=['POST'])
def create_donor_campaign():
    err = require_auth()
    if err: return err
    d = request.json
    cid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_campaigns (id,name,description,goal_amount,start_date,end_date,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (cid, d['name'], d.get('description',''), d.get('goal_amount') or None,
         d.get('start_date') or None, d.get('end_date') or None, d.get('status','active')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_campaigns WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-campaigns/<cid>', methods=['PUT'])
def update_donor_campaign(cid):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE donor_campaigns SET name=%s,description=%s,goal_amount=%s,start_date=%s,end_date=%s,status=%s WHERE id=%s',
        (d['name'], d.get('description',''), d.get('goal_amount') or None,
         d.get('start_date') or None, d.get('end_date') or None, d.get('status','active'), cid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-campaigns/<cid>', methods=['DELETE'])
def delete_donor_campaign(cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donor_campaigns WHERE id=%s', (cid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Donors — static routes MUST come before <did> dynamic routes ──
@app.route('/api/donors')
def get_donors():
    err = require_auth()
    if err: return err
    conn = get_db()
    donors = fetchall(conn, '''
        SELECT dn.*, t.name as tier_name, t.color as tier_color,
               v.name as volunteer_name
        FROM donors dn
        LEFT JOIN donor_tiers t ON dn.tier_id=t.id
        LEFT JOIN volunteers v ON dn.volunteer_id=v.id
        ORDER BY dn.total_donated DESC, dn.display_name ASC''')
    conn.close()
    return jsonify(donors)

@app.route('/api/donors', methods=['POST'])
def create_donor():
    err = require_auth()
    if err: return err
    d = request.json
    did = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donors
        (id,type,display_name,legal_name,email,phone,address,website,
         volunteer_id,is_anonymous,recognition_name,notes,internal_rating,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)''',
        (did, d.get('type','individual'), d['display_name'], d.get('legal_name',''),
         d.get('email',''), d.get('phone',''), d.get('address',''), d.get('website',''),
         d.get('volunteer_id') or None, d.get('is_anonymous',False),
         d.get('recognition_name',''), d.get('notes',''),
         d.get('internal_rating','normal'), session.get('user_name','')))
    conn.commit()
    row = fetchone(conn, '''SELECT dn.*, t.name as tier_name, t.color as tier_color
        FROM donors dn LEFT JOIN donor_tiers t ON dn.tier_id=t.id WHERE dn.id=%s''', (did,))
    conn.close()
    return jsonify(row)

@app.route('/api/donors/summary')
def donor_summary():
    err = require_auth()
    if err: return err
    conn = get_db()
    from datetime import datetime
    year = datetime.now().year
    total_row = fetchone(conn, '''SELECT COALESCE(SUM(amount),0) as total
        FROM donor_donations WHERE payment_status='received'
        AND EXTRACT(YEAR FROM donation_date::date)=%s''', (year,))
    donor_count = fetchone(conn, "SELECT COUNT(*) as c FROM donors WHERE status='active'")
    new_this_year = fetchone(conn, '''SELECT COUNT(*) as c FROM donors
        WHERE EXTRACT(YEAR FROM created_at)=%s''', (year,))
    tier_breakdown = fetchall(conn, '''SELECT t.name, t.color, COUNT(dn.id) as count
        FROM donor_tiers t LEFT JOIN donors dn ON dn.tier_id=t.id AND dn.status='active'
        GROUP BY t.id,t.name,t.color ORDER BY t.min_amount DESC''')
    lapsed = fetchone(conn, '''SELECT COUNT(*) as c FROM donors
        WHERE status='active' AND last_donation_date IS NOT NULL
        AND last_donation_date::date < CURRENT_DATE - INTERVAL \'12 months\' ''')
    conn.close()
    return jsonify({
        'total_raised_this_year': float(total_row['total']),
        'active_donors': donor_count['c'],
        'new_this_year': new_this_year['c'],
        'lapsed_count': lapsed['c'] if lapsed else 0,
        'tier_breakdown': tier_breakdown
    })

@app.route('/api/donors/import', methods=['POST'])
def bulk_import_donors():
    err = require_auth()
    if err: return err
    rows = request.json.get('rows', [])
    if not rows:
        return jsonify({'error': 'No rows provided'}), 400
    conn = get_db()
    imported = 0
    skipped = 0
    errors = []
    for i, row in enumerate(rows):
        display_name = (row.get('display_name') or row.get('name') or '').strip()
        if not display_name:
            skipped += 1
            continue
        try:
            did = str(uuid.uuid4())
            execute(conn, '''INSERT INTO donors
                (id,type,display_name,legal_name,email,phone,address,
                 is_anonymous,recognition_name,notes,status,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)''',
                (did, row.get('type','individual'), display_name,
                 row.get('legal_name',''), row.get('email',''),
                 row.get('phone',''), row.get('address',''), False,
                 row.get('recognition_name',''), row.get('notes',''),
                 session.get('user_name','')))
            amount_str = str(row.get('total_donated') or row.get('amount') or '').replace('$','').replace(',','').strip()
            if amount_str:
                try:
                    amount = float(amount_str)
                    if amount > 0:
                        import datetime as _dt
                        date_str = row.get('last_donation_date') or row.get('donation_date') or _dt.date.today().isoformat()
                        pid = str(uuid.uuid4())
                        execute(conn, '''INSERT INTO donor_donations
                            (id,donor_id,amount,donation_date,type,payment_status,notes,created_by)
                            VALUES (%s,%s,%s,%s,'cash','received','Imported',%s)''',
                            (pid, did, amount, date_str, session.get('user_name','')))
                        recalc_donor_totals(conn, did)
                except (ValueError, TypeError):
                    pass
            conn.commit()
            imported += 1
        except Exception as e:
            conn.rollback()
            errors.append('Row {}: {}'.format(i+2, str(e)[:80]))
            skipped += 1
    conn.close()
    return jsonify({'ok': True, 'imported': imported, 'skipped': skipped, 'errors': errors[:10]})

# ── Dynamic donor routes ──
@app.route('/api/donors/<did>', methods=['PUT'])
def update_donor(did):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE donors SET type=%s,display_name=%s,legal_name=%s,email=%s,phone=%s,
        address=%s,website=%s,volunteer_id=%s,is_anonymous=%s,recognition_name=%s,
        notes=%s,internal_rating=%s,status=%s WHERE id=%s''',
        (d.get('type','individual'), d['display_name'], d.get('legal_name',''),
         d.get('email',''), d.get('phone',''), d.get('address',''), d.get('website',''),
         d.get('volunteer_id') or None, d.get('is_anonymous',False),
         d.get('recognition_name',''), d.get('notes',''),
         d.get('internal_rating','normal'), d.get('status','active'), did))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donors/<did>', methods=['DELETE'])
def delete_donor(did):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donors WHERE id=%s', (did,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donors/<primary_id>/merge', methods=['POST'])
def merge_donors(primary_id):
    """Merge one or more duplicate donors into a primary donor."""
    err = require_auth()
    if err: return err
    d = request.json
    merge_ids = d.get('merge_ids', [])
    if not merge_ids:
        return jsonify({'error': 'No donors to merge'}), 400
    conn = get_db()
    try:
        primary = fetchone(conn, 'SELECT * FROM donors WHERE id=%s', (primary_id,))
        if not primary:
            conn.close(); return jsonify({'error': 'Primary donor not found'}), 404
        moved_donations = 0
        for mid in merge_ids:
            if mid == primary_id:
                continue
            # Move all donations
            execute(conn, 'UPDATE donor_donations SET donor_id=%s WHERE donor_id=%s', (primary_id, mid))
            # Move benefit usage
            execute(conn, 'UPDATE donor_benefit_usage SET donor_id=%s WHERE donor_id=%s', (primary_id, mid))
            # Move communications
            execute(conn, 'UPDATE donor_communications SET donor_id=%s WHERE donor_id=%s', (primary_id, mid))
            # Count what we moved
            count = fetchone(conn, 'SELECT COUNT(*) as c FROM donor_donations WHERE donor_id=%s', (primary_id,))
            moved_donations = count['c'] if count else 0
            # Delete the duplicate
            execute(conn, 'DELETE FROM donors WHERE id=%s', (mid,))
        # Recalculate primary totals
        recalc_donor_totals(conn, primary_id)
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'moved_donations': moved_donations})
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/donors/<did>/detail')
def get_donor_detail(did):
    err = require_auth()
    if err: return err
    conn = get_db()
    donor = fetchone(conn, '''
        SELECT dn.*, t.name as tier_name, t.color as tier_color,
               v.name as volunteer_name
        FROM donors dn
        LEFT JOIN donor_tiers t ON dn.tier_id=t.id
        LEFT JOIN volunteers v ON dn.volunteer_id=v.id
        WHERE dn.id=%s''', (did,))
    if not donor:
        conn.close(); return jsonify({'error': 'Not found'}), 404
    donor['donations'] = fetchall(conn, '''
        SELECT dd.*, c.name as campaign_name
        FROM donor_donations dd
        LEFT JOIN donor_campaigns c ON dd.campaign_id=c.id
        WHERE dd.donor_id=%s ORDER BY dd.donation_date DESC''', (did,))
    donor['benefit_usage'] = fetchall(conn, '''
        SELECT bu.*, b.name as benefit_name, t.name as tier_name
        FROM donor_benefit_usage bu
        JOIN donor_tier_benefits b ON bu.benefit_id=b.id
        JOIN donor_tiers t ON b.tier_id=t.id
        WHERE bu.donor_id=%s ORDER BY bu.used_at DESC''', (did,))
    donor['communications'] = fetchall(conn, '''
        SELECT * FROM donor_communications WHERE donor_id=%s ORDER BY sent_at DESC''', (did,))
    conn.close()
    return jsonify(donor)

def recalc_donor_totals(conn, donor_id):
    total_row = fetchone(conn, '''
        SELECT COALESCE(SUM(amount),0) as total FROM donor_donations
        WHERE donor_id=%s AND payment_status='received' ''', (donor_id,))
    total = float(total_row['total']) if total_row else 0.0
    dates_row = fetchone(conn, '''
        SELECT MIN(donation_date) as first_date, MAX(donation_date) as last_date
        FROM donor_donations WHERE donor_id=%s AND payment_status='received' ''', (donor_id,))
    donor = fetchone(conn, 'SELECT tier_override FROM donors WHERE id=%s', (donor_id,))
    new_tier_id = None
    if not (donor and donor.get('tier_override')):
        tier_row = fetchone(conn, '''
            SELECT id FROM donor_tiers
            WHERE min_amount <= %s AND (max_amount IS NULL OR max_amount >= %s)
            ORDER BY min_amount DESC LIMIT 1''', (total, total))
        if tier_row: new_tier_id = tier_row['id']
    first_date = dates_row['first_date'] if dates_row else None
    last_date  = dates_row['last_date']  if dates_row else None
    if not (donor and donor.get('tier_override')):
        execute(conn, '''UPDATE donors SET total_donated=%s,
            first_donation_date=%s, last_donation_date=%s, tier_id=%s WHERE id=%s''',
            (total, first_date, last_date, new_tier_id, donor_id))
    else:
        execute(conn, '''UPDATE donors SET total_donated=%s,
            first_donation_date=%s, last_donation_date=%s WHERE id=%s''',
            (total, first_date, last_date, donor_id))

@app.route('/api/donors/<did>/donations', methods=['POST'])
def add_donation(did):
    err = require_auth()
    if err: return err
    d = request.json
    donation_id = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_donations
        (id,donor_id,campaign_id,amount,donation_date,type,payment_status,check_number,notes,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (donation_id, did, d.get('campaign_id') or None,
         d['amount'], d['donation_date'],
         d.get('type','cash'), d.get('payment_status','received'),
         d.get('check_number',''), d.get('notes',''),
         session.get('user_name','')))
    conn.commit()
    recalc_donor_totals(conn, did)
    conn.commit()
    row = fetchone(conn, '''SELECT dd.*, c.name as campaign_name
        FROM donor_donations dd LEFT JOIN donor_campaigns c ON dd.campaign_id=c.id
        WHERE dd.id=%s''', (donation_id,))
    conn.close()
    return jsonify(row)

@app.route('/api/donations/<donation_id>', methods=['PUT'])
def update_donation(donation_id):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, '''UPDATE donor_donations SET amount=%s,donation_date=%s,type=%s,
        payment_status=%s,campaign_id=%s,check_number=%s,notes=%s WHERE id=%s''',
        (d['amount'], d['donation_date'], d.get('type','cash'),
         d.get('payment_status','received'), d.get('campaign_id') or None,
         d.get('check_number',''), d.get('notes',''), donation_id))
    conn.commit()
    row = fetchone(conn, 'SELECT donor_id FROM donor_donations WHERE id=%s', (donation_id,))
    if row: recalc_donor_totals(conn, row['donor_id']); conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/donations/<donation_id>', methods=['DELETE'])
def delete_donation(donation_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    row = fetchone(conn, 'SELECT donor_id FROM donor_donations WHERE id=%s', (donation_id,))
    execute(conn, 'DELETE FROM donor_donations WHERE id=%s', (donation_id,))
    conn.commit()
    if row: recalc_donor_totals(conn, row['donor_id']); conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/donations/<donation_id>/send-thankyou', methods=['POST'])
def send_thank_you(donation_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    row = fetchone(conn, '''SELECT dd.*, dn.display_name, dn.recognition_name, dn.email,
        dn.is_anonymous, c.name as campaign_name
        FROM donor_donations dd
        JOIN donors dn ON dd.donor_id=dn.id
        LEFT JOIN donor_campaigns c ON dd.campaign_id=c.id
        WHERE dd.id=%s''', (donation_id,))
    if not row: conn.close(); return jsonify({'error': 'Not found'}), 404
    if not row.get('email'):
        conn.close(); return jsonify({'error': 'Donor has no email address on file'}), 400
    name = row.get('recognition_name') or row['display_name']
    amount = '${:,.2f}'.format(float(row['amount']))
    campaign_str = ' for ' + row['campaign_name'] if row.get('campaign_name') else ''
    html_body = '''<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">
        <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:32px;text-align:center;border-radius:12px 12px 0 0">
            <h1 style="color:#fff;font-size:24px;margin:16px 0 0">Thank You!</h1>
        </div>
        <div style="padding:32px;background:#fff;border-radius:0 0 12px 12px;border:1px solid #e0e0db;border-top:none">
            <p style="font-size:16px;color:#1a1a17">Dear {name},</p>
            <p style="font-size:15px;color:#5f5e5a;line-height:1.7;margin:16px 0">
                On behalf of Horizon West Theatre Company, we want to express our deepest gratitude
                for your generous contribution of <strong style="color:#0d3d4d">{amount}</strong>{campaign_str}.
            </p>
            <div style="background:#f0f8fa;border-left:4px solid #145466;padding:16px 20px;border-radius:0 8px 8px 0;margin:24px 0">
                <div style="font-size:13px;font-weight:600;color:#145466;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px">Donation Summary</div>
                <div style="font-size:15px;color:#0d3d4d;font-weight:700">{amount}</div>
                <div style="font-size:13px;color:#5f5e5a">Date: {date}{camp}</div>
            </div>
            <p style="font-size:15px;color:#5f5e5a;line-height:1.7">
                With gratitude,<br/><strong>Horizon West Theatre Company</strong>
            </p>
        </div>
        <p style="text-align:center;font-size:11px;color:#9b9b94;margin-top:16px">
            Horizon West Theatre Company is a 501(c)(3) non-profit organization.
        </p>
    </div>'''.format(
        name=name, amount=amount, campaign_str=campaign_str,
        date=row['donation_date'],
        camp=(' · ' + row['campaign_name']) if row.get('campaign_name') else ''
    )
    ok, err_msg = send_email([row['email']], 'Thank You for Your Generous Support — HWTC', html_body)
    if ok:
        execute(conn, '''UPDATE donor_donations SET thank_you_sent=TRUE,
            thank_you_sent_at=NOW(), thank_you_sent_by=%s WHERE id=%s''',
            (session.get('user_name',''), donation_id))
        cid = str(uuid.uuid4())
        execute(conn, '''INSERT INTO donor_communications (id,donor_id,type,subject,body,sent_by)
            VALUES (%s,%s,'email',%s,%s,%s)''',
            (cid, row['donor_id'], 'Thank you — {} donation'.format(amount),
             'Thank you sent for {}{}'.format(amount, campaign_str),
             session.get('user_name','')))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    conn.close()
    return jsonify({'error': err_msg or 'Failed to send email'}), 500

@app.route('/api/donors/<did>/benefits/use', methods=['POST'])
def record_benefit_use(did):
    err = require_auth()
    if err: return err
    d = request.json
    uid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_benefit_usage (id,donor_id,benefit_id,notes,recorded_by)
        VALUES (%s,%s,%s,%s,%s)''',
        (uid, did, d['benefit_id'], d.get('notes',''), session.get('user_name','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-benefit-usage/<uid>', methods=['DELETE'])
def delete_benefit_use(uid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donor_benefit_usage WHERE id=%s', (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donors/<did>/tier', methods=['PUT'])
def set_donor_tier(did):
    err = require_auth()
    if err: return err
    d = request.json
    conn = get_db()
    execute(conn, 'UPDATE donors SET tier_id=%s, tier_override=%s WHERE id=%s',
        (d.get('tier_id') or None, d.get('override', False), did))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────


init_db()

if __name__ == '__main__':
    print('\n🎭 RoleCall is running!')
    print('   Open http://localhost:5000 in your browser\n')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
