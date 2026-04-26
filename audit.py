#!/usr/bin/env python3
"""
RoleCall Local Audit — run before EVERY deploy.
Usage: python3 audit.py
Exits 1 if anything fails — DO NOT DEPLOY if it fails.
"""
import ast, re, collections, subprocess, tempfile, os, sys

errors=[]; warnings=[]; passed=0
def ok(m):   global passed; passed+=1; print(f"  \u2713 {m}")
def fail(m): errors.append(m);         print(f"  \u2717 {m}")
def warn(m): warnings.append(m);       print(f"  \u26a0 {m}")

src=open('app.py').read()
html=open('static/index.html').read()
kiosk=open('static/kiosk.html').read()
portal=open('static/portal.html').read()
pickup=open('static/pickup.html').read()

def fn_body(name):
    if f'def {name}' not in src: return ''
    return src.split(f'def {name}')[1].split('\ndef ')[0]

# ── 1. Python syntax ──────────────────────────────────────────────
print("\n── Python ──")
try:
    tree=ast.parse(src); ok("app.py syntax")
    funcs=[n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)]
    dups=[f for f,c in collections.Counter(funcs).items() if c>1]
    if dups: fail(f"Duplicate functions: {dups}")
    else: ok("No duplicate functions")
    ok(f"{len(re.findall(r'@app.route',src))} routes registered")
except SyntaxError as e:
    fail(f"SYNTAX ERROR: {e}"); sys.exit(1)

# ── 2. JS syntax ──────────────────────────────────────────────────
print("\n── JavaScript ──")
for fname in ['static/index.html','static/kiosk.html','static/portal.html','static/pickup.html']:
    content=open(fname).read()
    tag='<script>\n'
    start=content.rfind(tag,0,content.rfind('</body>')-3000 if '</body>' in content else len(content))
    end=content.find('\n</script>',start)
    if start<0: continue
    js=content[start+len(tag):end]
    with tempfile.NamedTemporaryFile(suffix='.mjs',mode='w',delete=False) as f2:
        f2.write(js); tmp=f2.name
    r=subprocess.run(['node','--check',tmp],capture_output=True,text=True)
    if r.returncode==0: ok(f"{fname}")
    else: fail(f"{fname}: {r.stderr.split(chr(10))[1] if chr(10) in r.stderr else r.stderr[:80]}")
    os.unlink(tmp)

# ── 3. Routes ─────────────────────────────────────────────────────
print("\n── Routes ──")
for label,pattern in [
    ("GET  /api/interest-types",          "@app.route('/api/interest-types')\ndef get_interest_types"),
    ("POST /api/interest-types",          "route('/api/interest-types', methods=['POST'])\ndef create_interest_type"),
    ("GET  /api/donor-tiers",             "@app.route('/api/donor-tiers')\ndef get_donor_tiers"),
    ("POST /api/donor-tiers",             "route('/api/donor-tiers', methods=['POST'])\ndef create_donor_tier"),
    ("GET  /api/donor-tiers benefits",    "route('/api/donor-tiers/<tid>/benefits'"),
    ("POST /api/donor-tiers benefits",    "route('/api/donor-tiers/<tid>/benefits', methods=['POST'])"),
    ("GET  /api/applications",            "@app.route('/api/applications')\ndef get_applications"),
    ("POST /api/applications approve",    "route('/api/applications/<aid>/approve'"),
    ("GET  /api/volunteers",              "@app.route('/api/volunteers')\ndef get_volunteers"),
    ("POST /api/volunteers",              "route('/api/volunteers', methods=['POST'])\ndef create_volunteer"),
    ("GET  /api/events",                  "@app.route('/api/events')\ndef get_events"),
    ("POST /api/events",                  "route('/api/events', methods=['POST'])\ndef create_event"),
    ("DELETE /api/events/<eid>",          "route('/api/events/<eid>', methods=['DELETE'])\ndef delete_event"),
    ("GET  /api/portal/login",            "route('/api/portal/login'"),
    ("GET  /api/portal/participant",      "route('/api/portal/participant/<yid>'"),
    ("GET  /api/pickup/queue",            "@app.route('/api/pickup/queue')\ndef pickup_queue"),
    ("POST /api/pickup/clear",            "route('/api/pickup/clear'"),
    ("GET  /api/carpools",                "@app.route('/api/carpools')\ndef get_carpools"),
    ("POST /api/carpools",                "route('/api/carpools', methods=['POST'])\ndef create_carpool"),
    ("GET  /api/youth-sign-ins",          "@app.route('/api/youth-sign-ins')\ndef get_youth_sign_ins"),
    ("POST /api/youth-sign-ins",          "route('/api/youth-sign-ins', methods=['POST'])\ndef create_youth_sign_in"),
    ("POST /api/youth-sign-ins signout",  "route('/api/youth-sign-ins/<sid>/sign-out'"),
    ("GET  /api/kiosk/waiver-check",      "route('/api/kiosk/waiver-check'"),
    ("POST /api/kiosk/session/begin",     "route('/api/kiosk/session/begin'"),
    ("POST /api/kiosk/session/stop",      "route('/api/kiosk/session/stop'"),
    ("GET  /api/kiosk/events",            "route('/api/kiosk/events')\ndef kiosk"),
    ("GET  /api/kiosk/youth",             "@app.route('/api/kiosk/youth')\ndef kiosk"),
    ("POST /api/kiosk/open-event",        "route('/api/kiosk/open-event-checklist'"),
    ("POST /api/kiosk/close-event",       "route('/api/kiosk/close-event'"),
    ("GET  /api/checklist-items",         "route('/api/checklist-items')\ndef get_checklist_items"),
    ("GET  /api/opening-checklist-items", "route('/api/opening-checklist-items')\ndef get_opening_checklist_items"),
    ("POST /api/pending-hours approve",   "route('/api/pending-hours/<hid>/approve'"),
    ("GET  /api/productions/<id>/team",   "route('/api/productions/<pid>/team')\ndef get_production_team"),
    ("POST /api/productions/<id>/team",   "route('/api/productions/<pid>/team', methods=['POST'])"),
    ("DEL  /api/productions/<id>/team",   "route('/api/productions/<pid>/team/<mid>', methods=['DELETE'])"),
    ("cumulative_benefits helper",        "def get_cumulative_benefits(conn, tier_id)"),
    ("cumulative in tiers",               "get_cumulative_benefits(conn, tier['id'])"),
    ("cumulative in email",               "get_cumulative_benefits(conn, donor"),
]:
    if pattern in src: ok(label)
    else: fail(f"MISSING: {label}")

# ── 4. Migrations ────────────────────────────────────────────────
print("\n── Migrations ──")
for label,pattern in [
    ("waiver required_for_volunteering",  "required_for_volunteering BOOLEAN"),
    ("waiver can_sign_online",            "can_sign_online BOOLEAN"),
    ("waiver required_all",               "required_all BOOLEAN DEFAULT FALSE"),
    ("production_team_bios",              "CREATE TABLE IF NOT EXISTS production_team_bios"),
    ("settings",                          "CREATE TABLE IF NOT EXISTS settings"),
    ("alerts",                            "CREATE TABLE IF NOT EXISTS alerts"),
    ("carpools",                          "CREATE TABLE IF NOT EXISTS carpools"),
    ("carpool_members",                   "CREATE TABLE IF NOT EXISTS carpool_members"),
    ("campaign_benefits",                 "CREATE TABLE IF NOT EXISTS campaign_benefits"),
    ("volunteers.linked_youth_id",        "volunteers ADD COLUMN IF NOT EXISTS linked_youth_id"),
    ("volunteers.pronouns",               "volunteers ADD COLUMN IF NOT EXISTS pronouns"),
    ("production_members.bio",            "production_members ADD COLUMN IF NOT EXISTS bio"),
    ("production_members.photo_url",      "production_members ADD COLUMN IF NOT EXISTS photo_url"),
    ("productions.general_content",       "productions ADD COLUMN IF NOT EXISTS general_content"),
]:
    if pattern in src: ok(label)
    else: fail(f"MISSING: {label}")

# ── 5. Business Logic ─────────────────────────────────────────────
print("\n── Business Logic ──")

# HOURS: approve must go to 'hours' not 'volunteer_hours'
b=fn_body('approve_pending_hours')
if 'INSERT INTO hours' in b: ok("approve_pending_hours inserts into 'hours'")
else: fail("approve_pending_hours does NOT insert into 'hours' — approved hours lost from reports!")

if 'INSERT INTO volunteer_hours' in src:
    fail("'volunteer_hours' table referenced — doesn't exist, use 'hours'!")
else: ok("No references to non-existent 'volunteer_hours'")

b=fn_body('kiosk_close_event')
if 'INSERT INTO hours' in b: ok("kiosk_close_event auto-approves into 'hours'")
else: fail("kiosk_close_event does NOT insert into 'hours' — event close won't log hours!")

# CHECKLIST: must be public (kiosk has no admin session)
b=fn_body('get_checklist_items')
if 'require_auth' in b[:300]: fail("get_checklist_items requires auth — kiosk CANNOT load closing checklist!")
else: ok("get_checklist_items is public (kiosk accessible)")

b=fn_body('get_opening_checklist_items')
if 'require_auth' in b[:300]: fail("get_opening_checklist_items requires auth — kiosk CANNOT load opening checklist!")
else: ok("get_opening_checklist_items is public (kiosk accessible)")

# YOUTH SIGN-IN: must return full record with name
b=fn_body('create_youth_sign_in')
if 'JOIN youth_participants' in b: ok("create_youth_sign_in returns full record (no '?? user')")
else: fail("create_youth_sign_in missing JOIN — kiosk shows '?? user'!")

b=fn_body('youth_sign_out')
if 'JOIN youth_participants' in b: ok("youth_sign_out returns full record")
else: fail("youth_sign_out missing JOIN — roster won't update on sign-out!")

# PICKUP: no TEXT/DATE comparison
b=fn_body('pickup_queue')
if 'event_date = CURRENT_DATE' in b or "event_date=CURRENT_DATE" in b:
    fail("pickup_queue uses event_date=CURRENT_DATE on TEXT column — will crash!")
else: ok("pickup_queue no TEXT/DATE comparison")

# EVENT DELETE: savepoints
b=fn_body('delete_event')
if 'SAVEPOINT' in b: ok("delete_event uses savepoints")
else: fail("delete_event missing savepoints — will fail with transaction abort!")

# APPROVE APPLICATION: no ON CONFLICT on non-unique email
b=fn_body('approve_application')
if 'ON CONFLICT' in b and 'email' in b:
    fail("approve_application uses ON CONFLICT(email) — volunteers.email has no UNIQUE constraint!")
else: ok("approve_application handles duplicate emails safely")

# CRON: total_seconds
if '.total_seconds()' in src: ok("Cron uses .total_seconds() (correct)")
else: fail("Cron uses .seconds (buggy) — scheduled reports unreliable!")

# REQUEST.JSON SAFETY
n=src.count('= request.json\n')
if n>0: warn(f"{n} route(s) use 'd = request.json' without 'or {{}}' — crashes if no body!")
else: ok("All routes use 'request.json or {}' safely")

# GLOBAL ERROR HANDLER
if '@app.errorhandler(Exception)' in src: ok("Global exception handler returns JSON")
else: fail("No global exception handler — 500s return HTML, frontend can't show error!")

# PORTAL: returns correct shape
b=fn_body('portal_auth')
if "'type'" in b or '"type"' in b or "type': " in b: ok("portal_auth returns {type,...} shape")
else: warn("portal_auth response shape — verify it includes 'type' field")

# PICKUP ANNOUNCEMENTS: tracking sign-outs not sign-ins
if 'prevSignedOutIds' in pickup and 'signed_out_at && !prevSignedOutIds' in pickup:
    ok("Pickup announcements track sign-outs (correct — won't fire on sign-in)")
else: fail("Pickup announcements — verify they track sign-outs not sign-ins!")

# ── 6. Frontend elements ─────────────────────────────────────────
print("\n── Frontend elements ──")
for label,check in [
    ("index: vol-interest-badge",         'id="vol-interest-badge"' in html),
    ("index: renderTiersPage",            'function renderTiersPage' in html),
    ("index: own_benefits in tiers",      'own_benefits' in html),
    ("index: campaign_benefits in donor", 'campaign_benefits' in html),
    ("index: addCampaignBenefit",         'function addCampaignBenefit' in html),
    ("index: saveCampaignPage only once", html.count('async function saveCampaignPage')==1),
    ("index: recordBenefitUse",           'function recordBenefitUse' in html),
    ("index: deleteEventFull shows error",'res?.error' in html),
    ("index: event date required",        "event date is required" in html.lower()),
    ("portal: loadPortalCarpools",        'function loadPortalCarpools' in portal),
    ("portal: renderPortalCarpoolList",   'function renderPortalCarpoolList' in portal),
    ("kiosk: setEysTab",                  'function setEysTab' in kiosk),
    ("kiosk: eysSignOutCarpool",          'function eysSignOutCarpool' in kiosk),
    ("kiosk: light bg youth screen",      '#screen-elic-youth-signin{background:var(--bg)}' in kiosk),
    ("kiosk: blocks non-open events",     "Not open yet" in kiosk),
    ("pickup: prevSignedOutIds null init",'prevSignedOutIds = null' in pickup),
    ("pickup: dismissAnnouncement",       'function dismissAnnouncement' in pickup),
    ("pickup: clearQueue",                'function clearQueue' in pickup),
    ("pickup: runCleanup",                'function runCleanup' in pickup),
]:
    if check: ok(label)
    else: fail(f"MISSING/BROKEN: {label}")

# ── Summary ───────────────────────────────────────────────────────
total=passed+len(errors)
print(f"\n{'='*55}")
print(f"  {passed}/{total} passed   {len(errors)} errors   {len(warnings)} warnings")
print(f"{'='*55}")
if errors:
    print(f"\n\U0001f6ab DO NOT DEPLOY — fix these first:")
    for e in errors: print(f"  \u2717 {e}")
if warnings:
    print(f"\n\u26a0 Warnings:")
    for w in warnings: print(f"  \u26a0 {w}")
if not errors:
    print("\n\u2705 All checks passed — safe to deploy")
sys.exit(1 if errors else 0)
