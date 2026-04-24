#!/usr/bin/env python3
"""
RoleCall API Test Suite
Run against a live instance: python3 test_api.py https://your-app.railway.app

Tests every major route with realistic data and checks responses.
Requires an admin account — set ROLECALL_EMAIL and ROLECALL_PASSWORD env vars,
or pass them as args: python3 test_api.py <url> <email> <password>
"""

import sys, os, json, uuid
import urllib.request, urllib.error
from datetime import date, timedelta

# ── Config ──────────────────────────────────────────────────────────────
BASE_URL = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://localhost:5000'
EMAIL    = sys.argv[2] if len(sys.argv) > 2 else os.environ.get('ROLECALL_EMAIL', 'admin@test.com')
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else os.environ.get('ROLECALL_PASSWORD', 'password')

PASS = 0; FAIL = 0; SKIP = 0
_cookies = ''
_created = {}  # track IDs to clean up

def req(method, path, body=None, expect=200, label=None):
    global PASS, FAIL, _cookies
    url = BASE_URL + path
    data = json.dumps(body).encode() if body else None
    headers = {'Content-Type': 'application/json', 'Cookie': _cookies}
    try:
        r = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(r) as resp:
            # Capture cookies
            set_cookie = resp.headers.get('Set-Cookie', '')
            if set_cookie and 'session=' in set_cookie:
                _cookies = '; '.join(
                    p.split(';')[0] for p in set_cookie.split(',') if 'session=' in p
                ) or _cookies
            raw = resp.read()
            result = json.loads(raw) if raw else {}
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        result = json.loads(raw) if raw else {}
        status = e.code
    except Exception as e:
        print(f'  ✗ {label or path}: NETWORK ERROR — {e}')
        FAIL += 1
        return None

    ok = (status == expect) if isinstance(expect, int) else (status in expect)
    tag = '✓' if ok else '✗'
    lbl = label or f'{method} {path}'
    if ok:
        PASS += 1
        print(f'  {tag} {lbl} ({status})')
    else:
        FAIL += 1
        err = result.get('error', '') if isinstance(result, dict) else ''
        print(f'  {tag} {lbl} — expected {expect}, got {status}. {err}')
    return result if ok else None

def section(title):
    print(f'\n{"─"*55}')
    print(f'  {title}')
    print(f'{"─"*55}')

# ── Tests ────────────────────────────────────────────────────────────────

section('AUTH')
r = req('POST', '/api/auth/login', {'email': EMAIL, 'password': PASSWORD}, label='Login')
if not r or not r.get('user'):
    print(f'\n  ⚠ Login failed — remaining tests will fail. Check credentials.')
    sys.exit(1)
print(f'    Logged in as: {r["user"]["name"]} ({r["user"]["role"]})')

req('GET', '/api/auth/me', label='GET /api/auth/me')

section('VOLUNTEERS')
r = req('GET', '/api/volunteers', label='List volunteers')
vols = r if isinstance(r, list) else []

r = req('POST', '/api/volunteers', {
    'name': '_Test Volunteer',
    'email': f'test_{uuid.uuid4().hex[:6]}@test.com',
    'phone': '555-0000',
    'status': 'active'
}, label='Create volunteer')
if r and r.get('id'):
    _created['volunteer_id'] = r['id']
    req('GET', f'/api/volunteers/{r["id"]}', label='Get volunteer')
    req('PUT', f'/api/volunteers/{r["id"]}', {'name': '_Test Volunteer Updated', 'email': r.get('email',''), 'phone': '', 'status': 'active'}, label='Update volunteer')

section('EVENTS')
r = req('GET', '/api/events', label='List events')
events = r if isinstance(r, list) else []

r = req('POST', '/api/events', {
    'name': '_Test Event',
    'event_date': date.today().isoformat(),
    'start_time': '18:00',
    'end_time': '20:00',
    'status': 'draft'
}, label='Create event')
if r and r.get('id'):
    _created['event_id'] = r['id']
    req('PUT', f'/api/events/{r["id"]}', {
        'name': '_Test Event Updated',
        'event_date': date.today().isoformat(),
        'status': 'draft'
    }, label='Update event')

section('PRODUCTIONS')
r = req('GET', '/api/productions', label='List productions')
prods = r if isinstance(r, list) else []

r = req('POST', '/api/productions', {
    'name': '_Test Production',
    'production_type': 'show',
    'stage': 'rising_stars',
    'status': 'active'
}, label='Create production')
if r and r.get('id'):
    _created['production_id'] = r['id']
    pid = r['id']
    req('GET', f'/api/productions/{pid}/team', label='Get team')
    req('GET', f'/api/productions/{pid}/youth-members', label='Get youth members')
    req('GET', f'/api/productions/{pid}/conflicts', label='Get conflicts')
    req('GET', f'/api/productions/{pid}/general-content', label='Get general content')

    # Team bio CRUD
    r2 = req('POST', f'/api/productions/{pid}/team', {
        'name': '_Test Person',
        'role': 'Director',
        'bio': 'Test bio',
        'headshot_url': ''
    }, label='Add team member')
    if r2 and r2.get('id'):
        _created['team_bio_id'] = r2['id']
        req('PUT', f'/api/productions/{pid}/team/{r2["id"]}', {
            'name': '_Test Person Updated',
            'role': 'Producer',
            'bio': 'Updated bio',
            'headshot_url': ''
        }, label='Update team member')
        req('DELETE', f'/api/productions/{pid}/team/{r2["id"]}', label='Delete team member')
        _created.pop('team_bio_id', None)

section('YOUTH')
r = req('GET', '/api/youth', label='List youth')
req('GET', '/api/youth-programs', label='List programs')
req('GET', '/api/families', label='List families')

r = req('POST', '/api/youth', {
    'first_name': '_Test',
    'last_name': 'Youth',
    'dob': '2015-01-01',
    'status': 'active'
}, label='Create youth')
if r and r.get('id'):
    _created['youth_id'] = r['id']

section('KIOSK')
req('GET', '/api/kiosk/events', label='Kiosk events')
req('GET', '/api/kiosk/active-sessions', label='Active sessions')
req('GET', '/api/kiosk/youth', label='Kiosk youth list')

section('ELICS')
r = req('GET', '/api/elics', label='List ELICs')
elics = r if isinstance(r, list) else []
if vols:
    r = req('POST', '/api/elics', {
        'volunteer_id': vols[0]['id'],
        'pin': '9999',
        'is_master': False,
        'assigned_events': []
    }, label='Create ELIC')
    if r and r.get('id'):
        _created['elic_id'] = r['id']

section('DONORS')
req('GET', '/api/donors', label='List donors')
req('GET', '/api/donor-tiers', label='List tiers')
req('GET', '/api/donor-campaigns', label='List campaigns')
req('GET', '/api/donor-email-templates', label='List email templates')
req('GET', '/api/donations/all', label='All donations')
req('GET', '/api/donor-benefits', label='All benefits')

r = req('POST', '/api/donors', {
    'display_name': '_Test Donor',
    'email': f'donor_{uuid.uuid4().hex[:6]}@test.com',
    'is_anonymous': False
}, label='Create donor')
if r and r.get('id'):
    _created['donor_id'] = r['id']
    req('GET', f'/api/donors/{r["id"]}/detail', label='Donor detail')

section('PORTAL')
req('GET', '/api/portal/carpools', label='Portal carpools')
req('GET', '/api/portal/callout', label='Portal callout')
req('GET', '/api/portal/announcements', label='Portal announcements')

section('CARPOOLS')
req('GET', '/api/carpools', label='List carpools')
if _created.get('event_id'):
    r = req('POST', '/api/carpools', {
        'event_id': _created['event_id'],
        'name': '_Test Carpool',
        'driver_name': 'Test Driver',
        'driver_phone': '555-1234',
        'max_seats': 4
    }, label='Create carpool')
    if r and r.get('id'):
        _created['carpool_id'] = r['id']

section('SETTINGS & MISC')
req('GET', '/api/email-settings', label='Email settings')
req('GET', '/api/event-types', label='Event types')
req('GET', '/api/interest-types', label='Interest types')
req('GET', '/api/waiver-types', label='Waiver types')
req('GET', '/api/users', label='Users')
req('GET', '/api/notifications', label='Notifications')
req('GET', '/api/pending-hours', label='Pending hours')
req('GET', '/api/nav-icons', label='Nav icons')
req('GET', '/api/reports/run', [200, 405], label='Reports (method check)')

section('REPORTS')
req('POST', '/api/reports/run', {
    'report_type': 'monthly_recap',
    'params': {'year': date.today().year, 'month': date.today().month}
}, label='Run monthly recap')
req('POST', '/api/reports/run', {
    'report_type': 'top_volunteers',
    'params': {
        'start_date': (date.today() - timedelta(days=30)).isoformat(),
        'end_date': date.today().isoformat()
    }
}, label='Run top volunteers')
req('POST', '/api/reports/run', {
    'report_type': 'lapsed_volunteers',
    'params': {'days': 90}
}, label='Run lapsed volunteers')
req('GET', '/api/scheduled-reports', label='Scheduled reports')

section('CLEANUP')
if _created.get('carpool_id'):
    req('DELETE', f'/api/carpools/{_created["carpool_id"]}', label='Delete test carpool')
if _created.get('donor_id'):
    req('DELETE', f'/api/donors/{_created["donor_id"]}', label='Delete test donor')
if _created.get('elic_id'):
    req('DELETE', f'/api/elics/{_created["elic_id"]}', label='Delete test ELIC')
if _created.get('youth_id'):
    req('DELETE', f'/api/youth/{_created["youth_id"]}', label='Delete test youth')
if _created.get('production_id'):
    req('DELETE', f'/api/productions/{_created["production_id"]}', label='Delete test production')
if _created.get('event_id'):
    req('DELETE', f'/api/events/{_created["event_id"]}', label='Delete test event')
if _created.get('volunteer_id'):
    req('DELETE', f'/api/volunteers/{_created["volunteer_id"]}', label='Delete test volunteer')

req('POST', '/api/auth/logout', label='Logout')

# ── Summary ──────────────────────────────────────────────────────────────
total = PASS + FAIL + SKIP
print(f'\n{"═"*55}')
print(f'  RESULTS: {PASS}/{total} passed   {FAIL} failed   {SKIP} skipped')
print(f'{"═"*55}')
if FAIL > 0:
    sys.exit(1)
