# -*- coding: utf-8 -*-
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

def seed_system_email_templates(conn=None):
    _own_conn = conn is None
    if _own_conn: conn = get_db()
    """Seed default system email templates if they don't already exist."""
    templates = [
        ('join_notification', 'New Volunteer Interest  -  {{name}}', 'new_volunteer_join',
         'Sent to admins when someone submits the join/interest form.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">New Volunteer Interest</h2>
  <p><strong>{{name}}</strong> has submitted an interest form.</p>
  <table style="width:100%;border-collapse:collapse;margin:16px 0">
    <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666;width:140px">Name</td><td style="padding:8px">{{name}}</td></tr>
    <tr><td style="padding:8px;font-weight:600;color:#666">Email</td><td style="padding:8px">{{email}}</td></tr>
    <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Phone</td><td style="padding:8px">{{phone}}</td></tr>
    <tr><td style="padding:8px;font-weight:600;color:#666">Interests</td><td style="padding:8px">{{interests}}</td></tr>
    <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Employer Program</td><td style="padding:8px">{{employer_program}}</td></tr>
    <tr><td style="padding:8px;font-weight:600;color:#666">How They Heard</td><td style="padding:8px">{{how_heard}}</td></tr>
    <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Notes</td><td style="padding:8px">{{notes}}</td></tr>
  </table>
  <p><a href="{{review_link}}" style="background:#145466;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600">Review Application</a></p>
</div>'''),

        ('hours_submitted', 'RoleCall  -  Hours Submitted: {{volunteer_name}}', 'hours_submitted',
         'Sent to admins when a volunteer submits hours for approval.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">Hours Submitted for Approval</h2>
  <p><strong>{{volunteer_name}}</strong> has submitted <strong>{{hours}}h</strong> for <strong>{{event_name}}</strong>.</p>
  <p style="color:#666">Date: {{date}}</p>
  <p><a href="{{review_link}}" style="background:#145466;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600">Review Hours</a></p>
</div>'''),

        ('event_closed', 'Event Closed: {{event_name}}', 'event_closed',
         'Sent to admins/recipients when an ELIC closes an event via the kiosk.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:24px;border-radius:10px 10px 0 0;color:#fff">
    <h2 style="margin:0">🔒 Event Closed: {{event_name}}</h2>
    <p style="opacity:0.8;margin:6px 0 0">Closed by {{elic_name}} on {{date}}</p>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 10px 10px">
    <p><strong>{{volunteer_count}}</strong> volunteers logged <strong>{{total_hours}}h</strong> total.</p>
    {{checklist_html}}
    {{hours_html}}
  </div>
</div>'''),

        ('event_signup', 'New Sign-up: {{event_name}}', 'event_signup',
         'Sent to admins when someone signs up for an event via the portal.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">New Event Sign-up</h2>
  <p><strong>{{volunteer_name}}</strong> has signed up for <strong>{{event_name}}</strong>.</p>
  <p style="color:#666">Role: {{role}}<br>Date: {{event_date}}</p>
</div>'''),

        ('role_filled', 'Role Filled: {{role_name}}  -  {{event_name}}', 'role_filled',
         'Sent to admins when a role on an event reaches full capacity.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">Role Now Full</h2>
  <p>The role <strong>{{role_name}}</strong> on <strong>{{event_name}}</strong> has been filled.</p>
  <p style="color:#666">Date: {{event_date}}</p>
</div>'''),

        ('volunteer_opportunity', 'Volunteer Opportunity: {{event_name}}', 'volunteer_opportunity',
         'Sent to volunteers when they are invited to sign up for an event.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:24px;border-radius:10px 10px 0 0;color:#fff">
    <h2 style="margin:0">🎭 Volunteer Opportunity</h2>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 10px 10px">
    <p>Hi {{volunteer_name}},</p>
    <p>You're invited to volunteer for <strong>{{event_name}}</strong>!</p>
    <p style="color:#666">Date: {{event_date}}<br>Location: {{location}}</p>
    <p>{{message}}</p>
    <p><a href="{{signup_link}}" style="background:#145466;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:600">View &amp; Sign Up</a></p>
  </div>
</div>'''),

        ('board_availability', 'Board Meeting Availability  -  {{month}} {{year}}', 'board_availability',
         'Sent to board members requesting their availability for a month.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">Board Meeting Availability  -  {{month}} {{year}}</h2>
  <p>Hi {{name}},</p>
  <p>We\'re scheduling the board meeting for <strong>{{month}} {{year}}</strong> and need to know your availability. Please click below and mark any dates you <strong>cannot</strong> attend.</p>
  <div style="text-align:center;margin:28px 0">
    <a href="{{link}}" style="background:#145466;color:#fff;text-decoration:none;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:700;display:inline-block">📅 Submit My Availability</a>
  </div>
  <p style="font-size:13px;color:#888">This link is unique to you. You can update your availability at any time by clicking it again.</p>
</div>'''),

        ('disney_reminder', '🐭 Reminder: Submit Your Volunteer Hours  -  Disney VoluntEARS', 'disney_reminder',
         'Sent to Disney Cast Members who have logged hours, reminding them to submit to VoluntEARS.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center">
    <div style="font-size:48px;margin-bottom:8px">🐭</div>
    <h2 style="color:#fff;margin:0;font-size:22px">Your Volunteer Hours Make a Difference!</h2>
  </div>
  <div style="background:#fff;padding:28px 32px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px">
    <p>Hi {{name}},</p>
    <p>We noticed you\'ve been volunteering with <strong>Horizon West Theatre Company</strong> recently  -  thank you!</p>
    <p>As a <strong>Disney Cast Member</strong>, you may be eligible to submit your volunteer hours through <strong>Disney VoluntEARS</strong>, which can result in a donation to our organization at no cost to you!</p>
    <div style="background:#f0f8fa;border-radius:10px;padding:20px 24px;margin:24px 0;border-left:4px solid #145466">
      <strong>To submit your hours:</strong><br/>
      Visit <a href="https://disneyvoluntears.com" style="color:#145466;font-weight:600">Disney VoluntEARS</a> and log your hours for Horizon West Theatre Company.
    </div>
    <p>If you have any questions or need help, please don\'t hesitate to reach out!</p>
    <p>With gratitude,<br><strong>Horizon West Theatre Company</strong></p>
  </div>
</div>'''),

        ('universal_reminder', 'Reminder: Submit Your Volunteer Hours - Universal Giving', 'universal_reminder',
         'Sent to Universal Team Members who have logged hours, reminding them to submit to Universal Giving.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">
  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center">
    <h2 style="color:#fff;margin:0;font-size:22px">Your Volunteer Hours Make a Difference!</h2>
    <p style="color:rgba(255,255,255,0.8);margin:8px 0 0;font-size:14px">Universal Team Member Giving Guide</p>
  </div>
  <div style="background:#fff;padding:28px 32px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px">
    <p>Hi {{name}},</p>
    <p>Thank you so much for volunteering with <strong>Horizon West Theatre Company</strong>! As a Universal Team Member, you can submit your hours through <strong>Universal Giving</strong> and potentially qualify for grant funding on our behalf.</p>
    <p style="font-size:14px;color:#6b7280">Here is a step-by-step guide to logging your hours:</p>

    <div style="margin:20px 0">

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">1</div>
          <strong>Go to the Team Universal site</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step1.png" alt="Team Universal home page" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">2</div>
          <strong>Scroll down and click &ldquo;Access myImpact&rdquo; on the home page</strong>
        </div>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">3</div>
          <strong>Select the company you work for &amp; log in with your SSO</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step2.png" alt="Select company and login" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">4</div>
          <strong>Go to the &ldquo;Log Your Hours&rdquo; page</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step3.png" alt="myImpact home - Log Your Hours" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">5</div>
          <strong>Click the &ldquo;Log Individual Hours&rdquo; button</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step4.png" alt="Log Individual Hours button" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">6</div>
          <strong>Search for &ldquo;Horizon West Theater Company&rdquo;</strong>
        </div>
        <span style="color:#6b7280;font-size:13px">Enter the organization name and search, or select it if it already appears from a previous entry.</span>
        <img src="https://rolecall.hwtco.org/static/images/universal_step5.png" alt="Search for organization" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">7</div>
          <strong>Enter your date range and hours, then click &ldquo;Save and Proceed&rdquo;</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step6.png" alt="Enter hours" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">8</div>
          <strong>Review your submission and click &ldquo;Submit&rdquo;</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step7.png" alt="Review and submit" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">9</div>
          <strong>A confirmation page will appear &mdash; you&#x2019;re all set!</strong>
        </div>
        <img src="https://rolecall.hwtco.org/static/images/universal_step8.png" alt="Confirmation" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>
      </div>

    </div>

    <div style="background:#f0f8fa;border-radius:10px;padding:20px 24px;margin:24px 0;border-left:4px solid #145466">
      <strong style="color:#145466">Did you know?</strong>
      <p style="margin:8px 0 0;font-size:14px;color:#374151">Once you complete <strong>52 hours</strong> of volunteering you qualify for <strong>Club 52</strong>. After <strong>104 hours</strong> you reach <strong>Club 52 Elite</strong> status. Both levels qualify for the Universal Orlando Foundation grant &mdash; where you can choose a non-profit to receive grant money. <strong>Horizon West Theater Company qualifies</strong> and hopes you will consider donating your grant to our cause!</p>
    </div>

    {{hours_section}}

    <p>If you have any questions or need help logging your hours, please reach out to us at <a href="mailto:info@hwtco.org" style="color:#145466">info@hwtco.org</a>.</p>
    <p>With gratitude,<br/><strong>Horizon West Theatre Company</strong></p>
  </div>
</div>''')

        ('temp_password', 'Your RoleCall Temporary Password', 'temp_password',
         'Sent to users when an admin generates a temporary password for them.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#145466">Your Temporary Password</h2>
  <p>Hi {{name}},</p>
  <p>A temporary password has been created for your RoleCall account.</p>
  <div style="background:#f0f8fa;border-radius:8px;padding:16px 24px;margin:16px 0;text-align:center">
    <div style="font-size:24px;font-weight:700;font-family:monospace;color:#145466;letter-spacing:2px">{{temp_password}}</div>
  </div>
  <p style="color:#666;font-size:13px">Please log in and change your password immediately.</p>
</div>'''),

        ('unauthorized_pickup', 'ALERT: Unauthorized Pickup Attempt', 'unauthorized_pickup',
         'Sent to admins/guardians when an unauthorized pickup attempt is detected at the kiosk.',
         '''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;border:2px solid #dc2626;border-radius:10px;overflow:hidden">
  <div style="background:#dc2626;padding:16px 24px;color:#fff">
    <h2 style="margin:0">⚠️ Unauthorized Pickup Attempt</h2>
  </div>
  <div style="padding:24px">
    <p>An unauthorized pickup attempt was detected for <strong>{{participant_name}}</strong>.</p>
    <p style="color:#666">Person attempting pickup: <strong>{{pickup_name}}</strong><br>Time: {{timestamp}}<br>Event: {{event_name}}</p>
    <p>Please review immediately.</p>
  </div>
</div>'''),
        ('welcome_email',
         'Welcome to {{program_name}}  -  HWTC RoleCall',
         'welcome_email',
         'Sent to families when they are enrolled in a program. Includes their portal passphrase. Supports {{program_name}}, {{passphrase}}, {{family_greeting}} merge tags.',
         '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8"/>\n<meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n<title>Welcome to {{program_name}}  -  HWTC RoleCall</title>\n<style>\n  * { box-sizing: border-box; margin: 0; padding: 0; }\n  body { font-family: Georgia, \'Times New Roman\', serif; background: #f5f4f0; color: #1a1a18; }\n  .wrapper { max-width: 640px; margin: 32px auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 16px rgba(0,0,0,0.08); }\n\n  /* Header */\n  .header { background: #0d4a38; padding: 40px 40px 32px; text-align: center; }\n  .header-logo { font-size: 11px; font-weight: 600; letter-spacing: 0.15em; text-transform: uppercase; color: rgba(255,255,255,0.6); margin-bottom: 10px; }\n  .header h1 { font-size: 28px; font-weight: 400; color: #fff; line-height: 1.3; margin-bottom: 6px; }\n  .header-sub { font-size: 14px; color: rgba(255,255,255,0.65); }\n  .header-rule { width: 40px; height: 2px; background: #1D9E75; margin: 16px auto 0; }\n\n  /* Body */\n  .body { padding: 36px 40px; }\n  p { font-size: 15px; line-height: 1.75; margin-bottom: 1rem; color: #2c2c2a; }\n  strong { font-weight: 600; }\n  a { color: #0F6E56; }\n\n  /* Callout */\n  .callout { background: #E1F5EE; border-left: 3px solid #1D9E75; border-radius: 0 8px 8px 0; padding: 14px 18px; margin: 1.5rem 0; }\n  .callout p { font-size: 14px; margin: 0; color: #085041; }\n  .callout strong { color: #04342C; }\n\n  /* Steps */\n  .steps { margin: 2rem 0; display: flex; flex-direction: column; gap: 2.5rem; }\n  .step-header { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 1rem; }\n  .step-num { width: 34px; height: 34px; border-radius: 50%; background: #1D9E75; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 15px; font-weight: 600; flex-shrink: 0; margin-top: 2px; font-family: -apple-system, sans-serif; }\n  .step-title { font-size: 16px; font-weight: 600; color: #0d4a38; margin-bottom: 4px; font-family: -apple-system, sans-serif; }\n  .step-desc { font-size: 14px; color: #5f5e5a; line-height: 1.65; }\n  code { background: #f1efe8; border: 1px solid #d3d1c7; border-radius: 4px; padding: 1px 6px; font-family: \'Courier New\', monospace; font-size: 13px; color: #0d4a38; }\n\n  /* Screenshot frame */\n  .screen { background: #f5f4f0; border: 1px solid #d3d1c7; border-radius: 10px; padding: 20px; margin-top: 0; }\n  .screen-label { font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: #888780; margin-bottom: 12px; font-family: -apple-system, sans-serif; }\n\n  /* Login mockup */\n  .login-card { max-width: 280px; margin: 0 auto; background: #fff; border: 1px solid #d3d1c7; border-radius: 10px; padding: 24px 20px; }\n  .login-logo-wrap { width: 44px; height: 44px; background: #0d4a38; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin: 0 auto 10px; }\n  .login-logo-icon { color: #fff; font-size: 20px; }\n  .login-app-name { font-size: 14px; font-weight: 600; text-align: center; color: #1a1a18; margin-bottom: 18px; font-family: -apple-system, sans-serif; }\n  .login-label { font-size: 11px; color: #888780; margin-bottom: 4px; font-family: -apple-system, sans-serif; }\n  .login-input { background: #f5f4f0; border: 1px solid #d3d1c7; border-radius: 6px; padding: 8px 10px; font-size: 13px; color: #888780; margin-bottom: 10px; font-family: monospace; letter-spacing: 2px; }\n  .login-btn { background: #1D9E75; color: #fff; border-radius: 6px; padding: 9px; text-align: center; font-size: 13px; font-weight: 600; font-family: -apple-system, sans-serif; }\n\n  /* Passphrase mockup */\n  .pp-card { max-width: 340px; margin: 0 auto; background: #fff; border: 1px solid #d3d1c7; border-radius: 10px; overflow: hidden; }\n  .pp-tabs { display: flex; border-bottom: 1px solid #d3d1c7; background: #f5f4f0; }\n  .pp-tab { padding: 8px 14px; font-size: 12px; color: #888780; font-family: -apple-system, sans-serif; }\n  .pp-tab.active { color: #0F6E56; border-bottom: 2px solid #1D9E75; font-weight: 600; background: #fff; }\n  .pp-body { padding: 16px 18px; }\n  .pp-section-title { font-size: 13px; font-weight: 600; color: #1a1a18; margin-bottom: 12px; font-family: -apple-system, sans-serif; }\n  .pp-field-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #888780; margin-bottom: 3px; font-family: -apple-system, sans-serif; }\n  .pp-field { background: #f5f4f0; border: 1px solid #d3d1c7; border-radius: 5px; padding: 7px 9px; font-size: 12px; color: #888780; margin-bottom: 8px; font-family: monospace; letter-spacing: 1px; }\n  .pp-save-btn { background: #1D9E75; color: #fff; border-radius: 5px; padding: 7px 14px; font-size: 12px; font-weight: 600; display: inline-block; font-family: -apple-system, sans-serif; }\n\n  /* Sections grid */\n  .sections-grid { display: flex; flex-direction: column; gap: 8px; }\n  .section-card { background: #fff; border: 1px solid #d3d1c7; border-radius: 8px; padding: 11px 13px; display: flex; align-items: flex-start; gap: 11px; }\n  .section-icon { width: 34px; height: 34px; background: #E1F5EE; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 16px; }\n  .section-name { font-size: 13px; font-weight: 600; color: #0d4a38; font-family: -apple-system, sans-serif; margin-bottom: 2px; }\n  .section-desc { font-size: 12px; color: #888780; line-height: 1.5; font-family: -apple-system, sans-serif; }\n\n  /* Announcements mockup */\n  .ann-card { max-width: 380px; margin: 0 auto; background: #fff; border: 1px solid #d3d1c7; border-radius: 10px; overflow: hidden; }\n  .ann-tabs { display: flex; border-bottom: 1px solid #d3d1c7; background: #f5f4f0; }\n  .ann-tab { padding: 7px 12px; font-size: 12px; color: #888780; font-family: -apple-system, sans-serif; }\n  .ann-tab.active { color: #0F6E56; border-bottom: 2px solid #1D9E75; font-weight: 600; background: #fff; }\n  .ann-badge { background: #E1F5EE; color: #0F6E56; border-radius: 10px; padding: 1px 6px; font-size: 10px; margin-left: 3px; }\n  .ann-body { padding: 10px 14px; display: flex; flex-direction: column; gap: 8px; }\n  .ann-item { border: 1px solid #d3d1c7; border-radius: 7px; padding: 10px 12px; }\n  .ann-item-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }\n  .ann-chip { background: #E1F5EE; color: #0F6E56; font-size: 9px; font-weight: 700; letter-spacing: 0.08em; padding: 2px 7px; border-radius: 10px; text-transform: uppercase; font-family: -apple-system, sans-serif; }\n  .ann-item-title { font-size: 12px; font-weight: 600; color: #1a1a18; font-family: -apple-system, sans-serif; }\n  .ann-item-body { font-size: 12px; color: #5f5e5a; line-height: 1.5; font-family: -apple-system, sans-serif; }\n  .ann-item-date { font-size: 10px; color: #b4b2a9; margin-top: 5px; font-family: -apple-system, sans-serif; }\n\n  /* Divider */\n  .rule { border: none; border-top: 1px solid #e8e6e0; margin: 2rem 0; }\n\n  /* CTA */\n  .cta { text-align: center; padding: 2rem 0 0.5rem; }\n  .cta-btn { display: inline-block; background: #1D9E75; color: #fff; text-decoration: none; padding: 12px 32px; border-radius: 8px; font-size: 14px; font-weight: 600; font-family: -apple-system, sans-serif; }\n  .cta-url { font-size: 12px; color: #888780; margin-top: 10px; font-family: -apple-system, sans-serif; }\n\n  /* Footer */\n  .footer { background: #f5f4f0; border-top: 1px solid #e8e6e0; padding: 20px 40px; text-align: center; }\n  .footer p { font-size: 12px; color: #888780; font-family: -apple-system, sans-serif; margin-bottom: 4px; }\n</style>\n</head>\n<body>\n<div class="wrapper">\n\n  <!-- Header -->\n  <div class="header">\n    <div class="header-logo">Horizon West Theater Company</div>\n    <h1>Welcome to {{program_name}}!</h1>\n    <div class="header-sub">Introducing RoleCall  -  your family portal</div>\n    <div class="header-rule"></div>\n  </div>\n\n  <!-- Body -->\n  <div class="body">\n\n    <p>Dear {{family_greeting}},</p>\n\n    <p>Summer camp is still a few weeks away, and we are so excited to have your family with us! Before the fun begins, we want to introduce you to <strong>RoleCall</strong>  -  our new family portal for Horizon West Theater Company.</p>\n\n    <p>Through RoleCall you can read announcements from your child\'s instructor, download program resources, sign required waivers, set up family carpools, and reach the theater company  -  all in one place. Moving forward, <strong>RoleCall will be our primary channel for all {{program_name}} communication.</strong></p>\n\n    <div class="callout">\n      <p><strong>Important  -  your passphrase is your child\'s pick-up password.</strong> Once you set it, our staff will ask for this word every afternoon before releasing your camper. Choose something only you and approved pick-up adults know.</p>\n    </div>\n\n    <hr class="rule"/>\n    <h2 style="font-size:18px;font-weight:600;color:#0d4a38;margin-bottom:1.5rem;font-family:-apple-system,sans-serif;">Getting started  -  three steps</h2>\n\n    <div class="steps">\n\n      <!-- Step 1 -->\n      <div>\n        <div class="step-header">\n          <div class="step-num">1</div>\n          <div>\n            <div class="step-title">Visit the portal</div>\n            <div class="step-desc">Open your browser and go to <a href="https://rolecall.hwtco.org/portal">rolecall.hwtco.org/portal</a></div>\n          </div>\n        </div>\n        <div class="screen">\n          <div class="screen-label">Portal login screen</div>\n          <div class="login-card">\n            <div class="login-logo-wrap">\n              <svg class="login-logo-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="22" height="22"><path d="M2 20h20M5 20V8l7-5 7 5v12"/><path d="M9 20v-5h6v5"/></svg>\n            </div>\n            <div class="login-app-name">HWTC Family Portal</div>\n            <div class="login-label">Your passphrase</div>\n            <div class="login-input">· · · · · · · · · · · ·</div>\n            <div class="login-btn">Sign In</div>\n          </div>\n        </div>\n      </div>\n\n      <!-- Step 2 -->\n      <div>\n        <div class="step-header">\n          <div class="step-num">2</div>\n          <div>\n            <div class="step-title">Sign in and set your passphrase</div>\n            <div class="step-desc">Use your temporary passphrase: <code style="background:#f1efe8;border:1px solid #d3d1c7;border-radius:4px;padding:1px 6px;font-family:\'Courier New\',monospace;font-size:13px;color:#0d4a38">{{passphrase}}</code>. Once inside, go to <strong>My Profile</strong> and change it to a word your family will remember. This same word is used at afternoon pick-up every day.</div>\n          </div>\n        </div>\n        <div class="screen">\n          <div class="screen-label">My Profile  -  changing your passphrase</div>\n          <div class="pp-card">\n            <div class="pp-tabs">\n              <div class="pp-tab">Programs</div>\n              <div class="pp-tab">Carpools</div>\n              <div class="pp-tab active">My Profile</div>\n            </div>\n            <div class="pp-body">\n              <div class="pp-section-title">🔑 Change Passphrase</div>\n              <div class="pp-field-label">Current passphrase</div>\n              <div class="pp-field">· · · · · · · · · ·</div>\n              <div class="pp-field-label">New passphrase</div>\n              <div class="pp-field" style="background:#fff;border-color:#1D9E75;">&nbsp;</div>\n              <div class="pp-field-label">Confirm new passphrase</div>\n              <div class="pp-field" style="background:#fff;">&nbsp;</div>\n              <div class="pp-save-btn">Update Passphrase</div>\n            </div>\n          </div>\n        </div>\n      </div>\n\n      <!-- Step 3 -->\n      <div>\n        <div class="step-header">\n          <div class="step-num">3</div>\n          <div>\n            <div class="step-title">Explore the portal</div>\n            <div class="step-desc">Take a few minutes to look around. The three main areas cover everything you\'ll need during camp.</div>\n          </div>\n        </div>\n        <div class="screen">\n          <div class="screen-label">Portal sections at a glance</div>\n          <div class="sections-grid">\n            <div class="section-card">\n              <div class="section-icon">📢</div>\n              <div>\n                <div class="section-name">Programs</div>\n                <div class="section-desc">Announcements from your instructor, downloadable files, rehearsal schedules, and program information</div>\n              </div>\n            </div>\n            <div class="section-card">\n              <div class="section-icon">🚗</div>\n              <div>\n                <div class="section-name">Carpools</div>\n                <div class="section-desc">Coordinate rides with other families  -  create a carpool or join an existing one for any scheduled day</div>\n              </div>\n            </div>\n            <div class="section-card">\n              <div class="section-icon">👤</div>\n              <div>\n                <div class="section-name">My Profile</div>\n                <div class="section-desc">Review and sign required waivers, update contact details, and manage your passphrase</div>\n              </div>\n            </div>\n          </div>\n        </div>\n      </div>\n\n    </div><!-- end steps -->\n\n    <hr class="rule"/>\n\n    <h2 style="font-size:18px;font-weight:600;color:#0d4a38;margin-bottom:1rem;font-family:-apple-system,sans-serif;">A note about auditions</h2>\n\n    <p>During {{program_name}}, every camper performs in a complete 30-minute show at the end of the week. To make the most of every rehearsal hour for choreography, songs, and blocking, auditions are held <em>before</em> the first day of camp. This year we are offering both <strong>virtual</strong> and <strong>in-person</strong> audition options.</p>\n\n    <p>All audition details  -  dates, materials, and sign-up links  -  will be posted in the <strong>Announcements</strong> section of your program inside RoleCall. Check there first!</p>\n\n    <div class="screen" style="margin-top:1.25rem;">\n      <div class="screen-label">Announcements  -  inside your program</div>\n      <div class="ann-card">\n        <div class="ann-tabs">\n          <div class="ann-tab">Overview</div>\n          <div class="ann-tab active">Announcements <span class="ann-badge">2</span></div>\n          <div class="ann-tab">Files</div>\n        </div>\n        <div class="ann-body">\n          <div class="ann-item">\n            <div class="ann-item-head">\n              <span class="ann-chip">Published</span>\n              <span class="ann-item-title">Audition information  -  Seussical Kids</span>\n            </div>\n            <div class="ann-item-body">Auditions are scheduled for Saturday, June 21. A virtual option is available  -  see the attached song sheet and sides.</div>\n            <div class="ann-item-date">June 10, 2026</div>\n          </div>\n          <div class="ann-item">\n            <div class="ann-item-head">\n              <span class="ann-chip">Published</span>\n              <span class="ann-item-title">Welcome to {{program_name}}!</span>\n            </div>\n            <div class="ann-item-body">We are thrilled to have you joining us for camp. Please review the supply list and dress code before the first day.</div>\n            <div class="ann-item-date">June 5, 2026</div>\n          </div>\n        </div>\n      </div>\n    </div>\n\n    <hr class="rule"/>\n\n    <p>We cannot wait to see what your camper creates this summer. Please reach out through the portal or email us directly if you have any questions at all.</p>\n\n    <p style="margin-bottom:4px;">With excitement,</p>\n    <p style="font-weight:600;margin-bottom:2px;">The HWTC Team</p>\n    <p style="font-size:13px;color:#888780;font-family:-apple-system,sans-serif;">Horizon West Theater Company</p>\n\n    <div class="cta">\n      <a class="cta-btn" href="https://rolecall.hwtco.org/portal">Sign In to RoleCall</a>\n      <div class="cta-url">rolecall.hwtco.org/portal</div>\n    </div>\n\n  </div><!-- end body -->\n\n  <div class="footer">\n    <p>Horizon West Theater Company</p>\n    <p>Questions? Contact us through the portal or reply to this email.</p>\n  </div>\n\n</div>\n</body>\n</html>\n'),

    ]


    for key, subject, _, description, body in templates:
        existing = fetchone(conn, 'SELECT id FROM email_templates WHERE template_key=%s', (key,))
        if existing:
            # Update system templates so content changes deploy automatically
            try:
                execute(conn, 'UPDATE email_templates SET subject=%s, body=%s, description=%s WHERE template_key=%s AND is_system=TRUE',
                    (subject, body, description, key))
                conn.commit()
            except Exception as e:
                import traceback; traceback.print_exc()
        if not existing:
            try:
                execute(conn, '''INSERT INTO email_templates (id, name, subject, body, template_key, is_system, description)
                    VALUES (%s,%s,%s,%s,%s,TRUE,%s)''',
                    (str(uuid.uuid4()), key.replace('_',' ').title(), subject, body, key, description))
            except Exception as e:
                app.logger.warning(f'Failed to seed template {key}: {e}')

def get_system_template(conn, key):
    """Get a system email template by key, returns None if not found."""
    return fetchone(conn, 'SELECT * FROM email_templates WHERE template_key=%s', (key,))

def log_volunteer_comm(conn, volunteer_id, subject, email_type='', sent_by='system', recipient_email=''):
    """Log an email sent to a volunteer."""
    try:
        execute(conn, '''INSERT INTO volunteer_communications
            (id, volunteer_id, subject, email_type, sent_by, recipient_email)
            VALUES (%s,%s,%s,%s,%s,%s)''',
            (str(uuid.uuid4()), volunteer_id, subject, email_type, sent_by, recipient_email))
    except Exception as e:
        app.logger.warning(f'log_volunteer_comm failed: {e}')

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
    # already covered by youth_programs  -  just add date columns via migration

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
        "ALTER TABLE waiver_types ADD COLUMN IF NOT EXISTS required_for_volunteering BOOLEAN DEFAULT FALSE",
        "ALTER TABLE waiver_types ADD COLUMN IF NOT EXISTS can_sign_online BOOLEAN DEFAULT FALSE",
        "ALTER TABLE waiver_types ADD COLUMN IF NOT EXISTS expires_days INTEGER",
        "ALTER TABLE interest_types ADD COLUMN IF NOT EXISTS sub_options TEXT DEFAULT '[]'",
        "ALTER TABLE interest_types ADD COLUMN IF NOT EXISTS sub_options_label TEXT DEFAULT ''",
        "UPDATE interest_types SET sub_options='[]' WHERE sub_options IS NULL",
        "UPDATE interest_types SET sub_options_label='' WHERE sub_options_label IS NULL",
        "ALTER TABLE volunteer_applications ADD COLUMN IF NOT EXISTS sub_selections TEXT DEFAULT '{}'",
        "UPDATE volunteer_applications SET sub_selections='{}' WHERE sub_selections IS NULL",
        # Sync required_all from required_for_volunteering  -  they should be the same column
        "UPDATE waiver_types SET required_all=required_for_volunteering WHERE required_for_volunteering=TRUE AND (required_all IS NULL OR required_all=FALSE)",
        "UPDATE waiver_types SET required_for_volunteering=required_all WHERE required_all=TRUE AND (required_for_volunteering IS NULL OR required_for_volunteering=FALSE)",
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
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS portal_last_login TIMESTAMP",
        "ALTER TABLE families ADD COLUMN IF NOT EXISTS email TEXT DEFAULT ''",
        "ALTER TABLE families ADD COLUMN IF NOT EXISTS phone TEXT DEFAULT ''",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS portal_passphrase TEXT",
        # portal content tables
        """CREATE TABLE IF NOT EXISTS families (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            passphrase TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS youth_notes (
            id TEXT PRIMARY KEY,
            youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
            author TEXT NOT NULL,
            author_id TEXT REFERENCES users(id),
            content TEXT NOT NULL,
            note_type TEXT DEFAULT 'general',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS youth_incidents (
            id TEXT PRIMARY KEY,
            youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
            incident_date TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            severity TEXT DEFAULT 'minor',
            reported_by TEXT,
            reported_by_id TEXT REFERENCES users(id),
            follow_up TEXT DEFAULT '',
            resolved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS portal_announcements (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            production_id TEXT REFERENCES productions(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT DEFAULT 'published',
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
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_new_rsvp BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS alert_role_filled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS sender_identities TEXT DEFAULT '[]'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS venue TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
        """CREATE TABLE IF NOT EXISTS production_general_content (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            html_content TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by TEXT)""",
        "ALTER TABLE board_members ADD COLUMN IF NOT EXISTS volunteer_id TEXT REFERENCES volunteers(id) ON DELETE SET NULL",
        "ALTER TABLE board_meeting_attendance ADD COLUMN IF NOT EXISTS attendance_type TEXT DEFAULT 'absent'",
        """CREATE TABLE IF NOT EXISTS audition_settings (
            id TEXT PRIMARY KEY,
            context_type TEXT NOT NULL,
            context_id TEXT NOT NULL,
            is_open BOOLEAN DEFAULT FALSE,
            title TEXT, description TEXT,
            audition_date TEXT, audition_time TEXT, location TEXT,
            roles TEXT DEFAULT '[]', instructions TEXT,
            email_submissions TEXT,
            allow_video_link BOOLEAN DEFAULT TRUE,
            allow_resume_link BOOLEAN DEFAULT TRUE,
            allow_headshot_link BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS audition_submissions (
            id TEXT PRIMARY KEY,
            context_type TEXT NOT NULL,
            context_id TEXT NOT NULL,
            family_id TEXT, participant_id TEXT,
            submitter_name TEXT NOT NULL, submitter_email TEXT,
            role_requested TEXT, video_url TEXT,
            resume_url TEXT, headshot_url TEXT, notes TEXT,
            status TEXT DEFAULT 'pending', admin_notes TEXT,
            submitted_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        "ALTER TABLE audition_settings ADD COLUMN IF NOT EXISTS context_type TEXT",
        "ALTER TABLE audition_settings DROP CONSTRAINT IF EXISTS audition_settings_context_id_key",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS roles_requested TEXT DEFAULT '[]'",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS cast_role TEXT",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS submitter_passphrase TEXT",
        """CREATE TABLE IF NOT EXISTS volunteer_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS volunteer_group_members (
            group_id TEXT NOT NULL REFERENCES volunteer_groups(id) ON DELETE CASCADE,
            volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
            PRIMARY KEY (group_id, volunteer_id))""",
        """CREATE TABLE IF NOT EXISTS director_interest_submissions (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            hwtc_experience TEXT,
            previous_experience TEXT,
            years_experience TEXT,
            experience_areas TEXT DEFAULT '[]',
            shows_refuse TEXT,
            role_description TEXT,
            most_rewarding TEXT,
            challenges TEXT,
            three_qualities TEXT,
            budget_management TEXT,
            dream_shows TEXT,
            admin_notes TEXT,
            status TEXT DEFAULT 'new',
            imported BOOLEAN DEFAULT FALSE,
            submitted_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        "ALTER TABLE audition_settings ADD COLUMN IF NOT EXISTS cast_list_published BOOLEAN DEFAULT FALSE",
        "ALTER TABLE audition_settings ADD COLUMN IF NOT EXISTS cast_list TEXT DEFAULT '[]'",
        """CREATE TABLE IF NOT EXISTS portal_message_threads (
            id TEXT PRIMARY KEY,
            family_id TEXT,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE SET NULL,
            production_id TEXT REFERENCES productions(id) ON DELETE SET NULL,
            subject TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            unread_admin INTEGER DEFAULT 0,
            unread_family INTEGER DEFAULT 0,
            family_passphrase TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS portal_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES portal_message_threads(id) ON DELETE CASCADE,
            sender_side TEXT NOT NULL,
            sender_name TEXT,
            body TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW())""",
        "UPDATE board_meeting_attendance SET attendance_type='in_person' WHERE attended=TRUE AND (attendance_type IS NULL OR attendance_type='absent')",
        "UPDATE board_meeting_attendance SET attendance_type='absent' WHERE attended=FALSE AND (attendance_type IS NULL OR attendance_type='in_person')",
        "ALTER TABLE youth_waivers ADD COLUMN IF NOT EXISTS signed_name TEXT",
        "ALTER TABLE youth_waivers ADD COLUMN IF NOT EXISTS signed_via TEXT DEFAULT 'upload'",
        "ALTER TABLE youth_participants ADD COLUMN IF NOT EXISTS shirt_size TEXT DEFAULT ''",
        "ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS last_invited_at TIMESTAMP",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS carpools_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS push_count INTEGER DEFAULT 0",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published'",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS program_id TEXT",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS production_id TEXT",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS author_id TEXT",
        "ALTER TABLE portal_announcements ADD COLUMN IF NOT EXISTS created_by TEXT",
        "ALTER TABLE portal_files ADD COLUMN IF NOT EXISTS context_type TEXT DEFAULT 'production'",
        "ALTER TABLE portal_files ADD COLUMN IF NOT EXISTS context_id TEXT",
        "ALTER TABLE volunteer_applications ADD COLUMN IF NOT EXISTS pronouns TEXT",
        "ALTER TABLE volunteer_applications ADD COLUMN IF NOT EXISTS is_adult BOOLEAN DEFAULT TRUE",
        "ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS template_key TEXT UNIQUE",
        "ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS is_system BOOLEAN DEFAULT FALSE",
        "ALTER TABLE email_templates ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
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
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS employer_program TEXT DEFAULT ''",
        """CREATE TABLE IF NOT EXISTS employer_reminder_log (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
            program_type TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT NOW(),
            sent_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS volunteer_communications (
            id TEXT PRIMARY KEY,
            volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
            subject TEXT NOT NULL,
            email_type TEXT DEFAULT '',
            sent_at TIMESTAMP DEFAULT NOW(),
            sent_by TEXT DEFAULT 'system',
            recipient_email TEXT DEFAULT '')""",
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
        # Registration system
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS registration_status TEXT DEFAULT 'draft'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS capacity INTEGER",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS price INTEGER DEFAULT 0",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS registration_open_date TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS registration_close_date TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS slug TEXT UNIQUE",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS square_catalog_item_id TEXT",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS interest_list_fields TEXT DEFAULT '[]'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS waitlist_auto_charge BOOLEAN DEFAULT TRUE",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS custom_fields TEXT DEFAULT '[]'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_info TEXT DEFAULT ''",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_images TEXT DEFAULT '[]'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS registration_form_type TEXT DEFAULT 'youth'",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS deposit_amount INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS discount_codes (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            description TEXT DEFAULT '',
            square_discount_id TEXT,
            discount_type TEXT NOT NULL DEFAULT 'percent',
            discount_value INTEGER NOT NULL DEFAULT 0,
            min_spend INTEGER DEFAULT 0,
            is_sibling_discount BOOLEAN DEFAULT FALSE,
            max_uses INTEGER,
            uses INTEGER DEFAULT 0,
            expires_at TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(program_id, code))""",
        """ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''""",
        """ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS min_spend INTEGER DEFAULT 0""",
        """ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS is_sibling_discount BOOLEAN DEFAULT FALSE""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS discount_code TEXT""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS discount_amount INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS payment_type TEXT DEFAULT 'full'""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS balance_due INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS balance_payment_link TEXT""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_enabled BOOLEAN DEFAULT FALSE""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_type TEXT DEFAULT 'percent'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_value INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS sibling_discount_amount INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS participant_count INTEGER DEFAULT 1""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS custom_field_values TEXT DEFAULT '{}'""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS siblings_data TEXT DEFAULT '[]'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS price INTEGER DEFAULT 0""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS deposit_amount INTEGER DEFAULT 0""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS waitlist_auto_charge BOOLEAN DEFAULT TRUE""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_info TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_images TEXT DEFAULT '[]'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS custom_fields TEXT DEFAULT '[]'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS square_catalog_item_id TEXT""",
        """CREATE TABLE IF NOT EXISTS program_registrations (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES youth_programs(id) ON DELETE CASCADE,
            registration_type TEXT NOT NULL DEFAULT 'registration',
            status TEXT NOT NULL DEFAULT 'pending',
            child_first_name TEXT, child_last_name TEXT, child_dob TEXT,
            guardian_name TEXT, guardian_email TEXT NOT NULL, guardian_phone TEXT,
            emergency_contact_name TEXT, emergency_contact_phone TEXT,
            shirt_size TEXT,
            notes TEXT,
            square_payment_id TEXT,
            square_order_id TEXT,
            square_checkout_id TEXT,
            amount_paid INTEGER DEFAULT 0,
            youth_id TEXT REFERENCES youth_participants(id) ON DELETE SET NULL,
            family_id TEXT REFERENCES families(id) ON DELETE SET NULL,
            waitlist_position INTEGER,
            waitlist_notified_at TIMESTAMP,
            waitlist_payment_link TEXT,
            waitlist_payment_expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS interest_list_entries (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES youth_programs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            child_name TEXT,
            child_age TEXT,
            notes TEXT,
            notified_at TIMESTAMP,
            converted_to_registration_id TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(program_id, email))""",
        # missing columns found in audit
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS general_content TEXT DEFAULT ''",
        "ALTER TABLE elics ADD COLUMN IF NOT EXISTS assigned_events TEXT DEFAULT '[]'",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS linked_youth_id TEXT",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS pronouns TEXT DEFAULT ''",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS bio TEXT DEFAULT ''",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS photo_url TEXT DEFAULT ''",
        "UPDATE volunteers SET pronouns='' WHERE pronouns IS NULL",
        # Backfill pronouns from approved applications for existing volunteers
        """UPDATE volunteers v SET pronouns=a.pronouns
           FROM volunteer_applications a
           WHERE a.volunteer_id=v.id
           AND (a.pronouns IS NOT NULL AND a.pronouns != '')
           AND (v.pronouns IS NULL OR v.pronouns='')""",
        "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS sub_selections TEXT DEFAULT '{}'",
        "UPDATE volunteers SET sub_selections='{}' WHERE sub_selections IS NULL",
        """CREATE TABLE IF NOT EXISTS event_rsvps (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE CASCADE,
            volunteer_name TEXT,
            volunteer_email TEXT,
            token TEXT UNIQUE,
            role_id TEXT,
            role_name TEXT DEFAULT '',
            status TEXT DEFAULT 'interested',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS event_roles (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            slots INTEGER NOT NULL DEFAULT 1,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        "ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS role_id TEXT",
        "ALTER TABLE event_rsvps ADD COLUMN IF NOT EXISTS role_name TEXT DEFAULT ''",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS rsvp_enabled BOOLEAN DEFAULT FALSE",
        # Board management
        """CREATE TABLE IF NOT EXISTS board_members (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            role TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            join_date TEXT,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS board_nominations (
            id TEXT PRIMARY KEY,
            member_id TEXT NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
            nomination_date TEXT NOT NULL,
            nomination_type TEXT DEFAULT 'election',
            term_years INTEGER DEFAULT 3,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS board_meetings (
            id TEXT PRIMARY KEY,
            meeting_date TEXT NOT NULL,
            meeting_time TEXT,
            location TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS board_meeting_attendance (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL REFERENCES board_meetings(id) ON DELETE CASCADE,
            member_id TEXT NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
            attended BOOLEAN DEFAULT TRUE,
            notes TEXT DEFAULT '',
            UNIQUE(meeting_id, member_id))""",
        """CREATE TABLE IF NOT EXISTS board_availability (
            id TEXT PRIMARY KEY,
            member_id TEXT NOT NULL REFERENCES board_members(id) ON DELETE CASCADE,
            month INTEGER NOT NULL,
            year INTEGER NOT NULL,
            blocked_dates TEXT DEFAULT '[]',
            token TEXT UNIQUE NOT NULL,
            submitted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(member_id, month, year))""",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS rsvp_message TEXT DEFAULT ''",
        """CREATE TABLE IF NOT EXISTS event_staff (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            volunteer_id TEXT NOT NULL REFERENCES volunteers(id) ON DELETE CASCADE,
            role TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(event_id, volunteer_id))""",
        "ALTER TABLE production_members ADD COLUMN IF NOT EXISTS bio TEXT DEFAULT ''",
        "ALTER TABLE production_members ADD COLUMN IF NOT EXISTS photo_url TEXT DEFAULT ''",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_date TEXT",
        # missing tables
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT)""",
        """CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            type TEXT DEFAULT 'info',
            message TEXT NOT NULL,
            source TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS production_required_waivers (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
            UNIQUE(production_id, waiver_type_id))""",
        """CREATE TABLE IF NOT EXISTS program_required_waivers (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES youth_programs(id) ON DELETE CASCADE,
            waiver_type_id TEXT NOT NULL REFERENCES waiver_types(id) ON DELETE CASCADE,
            UNIQUE(program_id, waiver_type_id))""",
        # meet the team  -  standalone public-facing entries (no volunteer required)
        """CREATE TABLE IF NOT EXISTS production_team_bios (
            id TEXT PRIMARY KEY,
            production_id TEXT NOT NULL REFERENCES productions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            headshot_url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
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

        """CREATE TABLE IF NOT EXISTS campaign_benefits (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL REFERENCES donor_campaigns(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            min_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
            is_trackable BOOLEAN DEFAULT FALSE,
            sort_order INTEGER DEFAULT 0,
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

        """CREATE TABLE IF NOT EXISTS donor_email_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            from_email TEXT DEFAULT '',
            from_name TEXT DEFAULT '',
            template_type TEXT DEFAULT 'thankyou',
            is_default BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS scheduled_reports (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            report_type TEXT NOT NULL,
            cadence TEXT DEFAULT 'monthly',
            send_day INTEGER DEFAULT 1,
            recipient_user_ids TEXT DEFAULT '[]',
            recipient_emails TEXT DEFAULT '',
            params TEXT DEFAULT '{}',
            is_active BOOLEAN DEFAULT TRUE,
            last_sent_at TIMESTAMP,
            next_send_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW())""",

        # Missing tables that get referenced
        """CREATE TABLE IF NOT EXISTS schedule_conflicts (
            id TEXT PRIMARY KEY,
            production_id TEXT REFERENCES productions(id) ON DELETE CASCADE,
            event_id TEXT REFERENCES events(id) ON DELETE SET NULL,
            volunteer_id TEXT REFERENCES volunteers(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'absent',
            event_date TEXT,
            notes TEXT,
            approved BOOLEAN DEFAULT FALSE,
            source TEXT DEFAULT 'staff',
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS carpools (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            driver_name TEXT NOT NULL,
            driver_phone TEXT DEFAULT '',
            code TEXT NOT NULL UNIQUE,
            max_seats INTEGER DEFAULT 6,
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT NOW())""",

        """CREATE TABLE IF NOT EXISTS carpool_members (
            id TEXT PRIMARY KEY,
            carpool_id TEXT NOT NULL REFERENCES carpools(id) ON DELETE CASCADE,
            youth_id TEXT NOT NULL REFERENCES youth_participants(id) ON DELETE CASCADE,
            added_by TEXT DEFAULT '',
            added_via TEXT DEFAULT 'admin',
            UNIQUE(carpool_id, youth_id))""",
    ]:
        try:
            c.execute(col_sql)
            conn.commit()
        except Exception:
            conn.rollback()

    # Seed board meeting event type if not exists
    try:
        existing = fetchone(conn, "SELECT id FROM event_types WHERE LOWER(name)='board meeting'")
        if not existing:
            execute(conn, "INSERT INTO event_types (id,name,color) VALUES (%s,'Board Meeting','#145466')", (str(uuid.uuid4()),))
            conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
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

    # One-time backfill: copy application notes to volunteer profile notes
    try:
        conn2 = get_db()
        c2 = conn2.cursor()
        c2.execute("""
            INSERT INTO notes (id, volunteer_id, author, content)
            SELECT gen_random_uuid()::text, a.volunteer_id, 'Join Form', a.notes
            FROM volunteer_applications a
            WHERE a.status = 'approved'
              AND a.volunteer_id IS NOT NULL
              AND (a.notes IS NOT NULL AND a.notes != '')
              AND NOT EXISTS (
                SELECT 1 FROM notes n
                WHERE n.volunteer_id = a.volunteer_id
                  AND n.author = 'Join Form'
                  AND n.content = a.notes
              )
        """)
        conn2.commit()
        conn2.close()
    except Exception:
        try: conn2.rollback(); conn2.close()
        except Exception: pass

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

def require_permission(section, level='edit'):
    """Allow admin OR a user with edit/view permission for the given section."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    if session.get('role') == 'admin':
        return None
    # Always read fresh from DB for non-admin users to pick up permission changes
    try:
        conn = get_db()
        u = fetchone(conn, 'SELECT role, role_permissions FROM users WHERE id=%s', (session['user_id'],))
        conn.close()
        if not u:
            return jsonify({'error': 'Unauthorized'}), 401
        if u.get('role') == 'admin':
            session['role'] = 'admin'
            return None
        perms = json.loads(u.get('role_permissions') or '{}')
        # Update session so future checks are faster
        session['permissions'] = u.get('role_permissions') or '{}'
    except Exception:
        perms = {}
    user_level = perms.get(section, 'none')
    if level == 'view' and user_level in ('view', 'edit'):
        return None
    if level == 'edit' and user_level == 'edit':
        return None
    return jsonify({'error': f'Permission denied: need {level} access for {section}. Contact an admin to update your permissions.'}), 403

# ─────────────────────────────────────────────
#  EMAIL HELPERS
# ─────────────────────────────────────────────

def get_email_settings():
    try:
        conn = get_db()
        row = fetchone(conn, 'SELECT * FROM email_settings WHERE id=1')
        conn.close()
        return row or {}
    except Exception:
        return {}

def get_recipient_emails(settings=None):
    if settings is None:
        settings = get_email_settings()
    emails = []
    try:
        conn = get_db()
        ids_raw = settings.get('report_recipient_user_ids') or '[]'
        user_ids = json.loads(ids_raw) if isinstance(ids_raw, str) else (ids_raw or [])
        if user_ids:
            placeholders = ','.join(['%s'] * len(user_ids))
            users = fetchall(conn, f'SELECT email FROM users WHERE id IN ({placeholders})', tuple(user_ids))
            emails = [u['email'] for u in users if u.get('email')]
        if not emails:
            raw = settings.get('report_recipients','')
            if raw:
                emails = [e.strip() for e in raw.split(',') if e.strip()]
        conn.close()
    except Exception:
        pass
    return emails

def send_email(to_emails, subject, html_body, from_email=None, from_name=None):
    """Send via Resend API. from_email/from_name override settings default."""
    settings = get_email_settings()
    api_key = settings.get('resend_api_key','').strip()
    if not api_key:
        app.logger.warning('Resend API key not configured  -  email not sent')
        return False, 'Resend API key not configured'
    # Build from address
    if from_email:
        base_email = from_email
        base_name  = from_name or ''
    else:
        # Use first sender identity as default, fall back to from_email setting
        try:
            identities = json.loads(settings.get('sender_identities') or '[]')
        except Exception:
            identities = []
        if identities:
            base_email = identities[0].get('email', settings.get('from_email','info@hwtco.org'))
            base_name  = identities[0].get('name', '')
        else:
            base_email = settings.get('from_email','info@hwtco.org')
            base_name  = ''
    from_addr = f'{base_name} <{base_email}>' if base_name else base_email
    if isinstance(to_emails, str):
        to_emails = [e.strip() for e in to_emails.split(',') if e.strip()]
    if not to_emails:
        return False, 'No recipients'
    try:
        import requests as _req
        resp = _req.post('https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'from': from_addr, 'to': to_emails, 'subject': subject, 'html': html_body},
            timeout=10)
        if resp.status_code not in (200, 201, 202):
            app.logger.error(f'Resend error: {resp.status_code} {resp.text}')
            return False, f'Resend error {resp.status_code}: {resp.text[:200]}'
        return True, None
    except Exception as e:
        app.logger.error(f'Email send error: {e}')
        return False, str(e)

def link_director_submission(conn, volunteer_id, email):
    """Link a director interest submission to a volunteer if not already linked."""
    try:
        execute(conn, 'UPDATE director_interest_submissions SET volunteer_id=%s WHERE LOWER(email)=%s AND volunteer_id IS NULL',
            (volunteer_id, email.strip().lower()))
    except Exception:
        pass


def serialize_row(r):
    out = {}
    for k, v in r.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out

def parse_db_datetime(val):
    """Safely parse a datetime value that may be a string (from serialize_row) or datetime object.
    Always returns a naive UTC datetime, or None if unparseable."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    if isinstance(val, str):
        s = val.strip()
        # Strip timezone offset if present (handles Python < 3.11)
        import re as _re
        s = _re.sub(r'[+-]\d{2}:\d{2}$', '', s).replace('Z', '')
        try:
            return datetime.fromisoformat(s)
        except Exception:
            pass
        # Try common formats
        for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
    return None

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
    from datetime import date as _date, datetime as _datetime
    waivers = fetchall(conn,
        'SELECT vw.*, wt.name as type_name FROM volunteer_waivers vw JOIN waiver_types wt ON vw.waiver_type_id=wt.id WHERE vw.volunteer_id=%s ORDER BY vw.signed_date DESC',
        (vol_id,))
    today = _date.today()
    # Check required waivers first
    required = fetchall(conn, 'SELECT id FROM waiver_types WHERE required_for_volunteering=TRUE OR required_all=TRUE')
    signed_type_ids = set(w['waiver_type_id'] for w in waivers)
    has_missing_required = any(r['id'] not in signed_type_ids for r in required)

    worst = 'none'
    for w in waivers:
        if not w['expiry_date']:
            if worst == 'none': worst = 'valid'
            continue
        try:
            diff = (_datetime.strptime(str(w['expiry_date'])[:10], '%Y-%m-%d').date() - today).days
        except Exception:
            if worst == 'none': worst = 'valid'
            continue
        if diff < 0: worst = 'expired'; break
        elif diff < 30 and worst != 'expired': worst = 'expiring'
        elif worst == 'none': worst = 'valid'

    # If missing a required waiver, downgrade to expired (worst)
    if has_missing_required and worst not in ('expired',):
        worst = 'expired'
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
    d = request.json or {}
    pw_hash = hashlib.sha256(d.get('password','').encode()).hexdigest()
    conn = get_db()
    user = fetchone(conn, 'SELECT * FROM users WHERE email=%s AND password_hash=%s', (d.get('email',''), pw_hash))
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

@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    """Self-service password change  -  any logged-in user."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    d = request.json or {}
    current_pw  = d.get('current_password','')
    new_pw      = d.get('new_password','')
    if not current_pw or not new_pw:
        return jsonify({'error': 'Both current and new password are required'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400
    conn = get_db()
    # Verify current password
    current_hash = hashlib.sha256(current_pw.encode()).hexdigest()
    user = fetchone(conn, 'SELECT id FROM users WHERE id=%s AND password_hash=%s',
                    (session['user_id'], current_hash))
    if not user:
        conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 400
    new_hash = hashlib.sha256(new_pw.encode()).hexdigest()
    execute(conn, 'UPDATE users SET password_hash=%s WHERE id=%s', (new_hash, session['user_id']))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

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
    d = request.json or {}
    if not (d.get('name') or '').strip(): return jsonify({'error': 'Name is required'}), 400
    tid = str(uuid.uuid4())
    conn = get_db()
    try:
        sub_opts = json.dumps(d.get('sub_options') or [])
        sub_label = (d.get('sub_options_label') or '').strip()
        execute(conn, 'INSERT INTO interest_types (id,name,color,sub_options,sub_options_label) VALUES (%s,%s,%s,%s,%s)',
            (tid, (d.get('name') or '').strip(), d.get('color','gray'), sub_opts, sub_label))
        conn.commit()
        row = fetchone(conn, 'SELECT * FROM interest_types WHERE id=%s', (tid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.rollback(); conn.close()
        app.logger.error(f'create_interest_type: {e}')
        if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
            return jsonify({'error': 'An interest type with that name already exists'}), 400
        return jsonify({'error': str(e)}), 500

@app.route('/api/interest-types/<tid>', methods=['PUT'])
def update_interest_type(tid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    try:
        sub_opts = json.dumps(d.get('sub_options') or [])
        sub_label = (d.get('sub_options_label') or '').strip()
        execute(conn, '''UPDATE interest_types SET name=%s, color=%s, sub_options=%s, sub_options_label=%s
            WHERE id=%s''',
            ((d.get('name') or '').strip(), d.get('color','gray'), sub_opts, sub_label, tid))
        conn.commit()
        row = fetchone(conn, 'SELECT * FROM interest_types WHERE id=%s', (tid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500

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
            el.is_master, v.name as volunteer_name, v.id as volunteer_id,
            COALESCE(v.background_check_status,'none') as background_check_status
            FROM event_elics ee JOIN elics el ON ee.elic_id=el.id
            JOIN volunteers v ON el.volunteer_id=v.id
            WHERE ee.event_id=%s""", (e['id'],))
        e['staff'] = []
        try:
            e['staff'] = fetchall(conn, """SELECT es.*, v.name as volunteer_name,
                v.background_check_status, v.email
                FROM event_staff es JOIN volunteers v ON es.volunteer_id=v.id
                WHERE es.event_id=%s ORDER BY es.role, v.name""", (e['id'],))
        except Exception:
            pass
        e['status'] = e.get('status') or 'draft'
    conn.close()
    return jsonify(events)

@app.route('/api/events', methods=['POST'])
def create_event():
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    if not (d.get('name') or '').strip():
        return jsonify({'error': 'Event name is required'}), 400
    if not (d.get('event_date') or '').strip():
        return jsonify({'error': 'Event date is required'}), 400
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO events
        (id,name,event_date,end_date,start_time,end_time,event_type_id,location,room,production_id,program_id,expected_volunteers,description,notes,status,requires_background_check,auto_log_hours)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)''',
        (eid, d.get('name',''), d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False),
         d.get('auto_log_hours', False)))
    conn.commit()
    # Auto-assign program instructor/default ELIC when event belongs to a program
    program_id = d.get('program_id') or None
    if program_id:
        try:
            prog = fetchone(conn, 'SELECT default_elic_id, instructor_id FROM youth_programs WHERE id=%s', (program_id,))
            if prog:
                elic_vol_id = prog.get('default_elic_id') or prog.get('instructor_id')
                if elic_vol_id:
                    elic = fetchone(conn, 'SELECT id FROM elics WHERE volunteer_id=%s', (elic_vol_id,))
                    if elic:
                        existing = fetchone(conn, 'SELECT id FROM event_elics WHERE event_id=%s AND elic_id=%s', (eid, elic['id']))
                        if not existing:
                            execute(conn, 'INSERT INTO event_elics (id,event_id,elic_id) VALUES (%s,%s,%s)',
                                (str(uuid.uuid4()), eid, elic['id']))
                            conn.commit()
        except Exception as e:
            app.logger.warning(f'Auto-ELIC assignment failed: {e}')
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

@app.route('/api/events/<eid>/status', methods=['POST'])
def set_event_status(eid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    status = d.get('status','').strip()
    if status not in ('draft','open','closed','cancelled'):
        return jsonify({'error': f'Invalid status: {status}'}), 400
    conn = get_db()
    execute(conn, 'UPDATE events SET status=%s WHERE id=%s', (status, eid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (eid,))
    conn.close()
    return jsonify({'ok': True, 'status': row['status'], 'id': eid})

@app.route('/api/events/<eid>', methods=['PUT'])
def update_event(eid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE events SET name=%s,event_date=%s,end_date=%s,start_time=%s,end_time=%s,
        event_type_id=%s,location=%s,room=%s,production_id=%s,program_id=%s,expected_volunteers=%s,
        description=%s,notes=%s,requires_background_check=%s,auto_log_hours=%s,
        rsvp_enabled=%s,rsvp_message=%s,status=%s,carpools_enabled=%s WHERE id=%s''',
        (d.get('name',''), d.get('event_date') or None, d.get('end_date') or None,
         d.get('start_time') or None, d.get('end_time') or None,
         d.get('event_type_id') or None, d.get('location',''), d.get('room',''),
         d.get('production_id') or None, d.get('program_id') or None,
         d.get('expected_volunteers') or None,
         d.get('description',''), d.get('notes',''), d.get('requires_background_check',False),
         d.get('auto_log_hours', False), d.get('rsvp_enabled', False),
         d.get('rsvp_message',''), d.get('status','draft'),
         d.get('carpools_enabled', False), eid))
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
        el.is_master, v.name as volunteer_name, v.id as volunteer_id,
        COALESCE(v.background_check_status,'none') as background_check_status
        FROM event_elics ee JOIN elics el ON ee.elic_id=el.id
        JOIN volunteers v ON el.volunteer_id=v.id
        WHERE ee.event_id=%s""", (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>', methods=['DELETE'])
def delete_event(eid):
    err = require_permission('events')
    if err: return err
    conn = get_db()
    cur = conn.cursor()
    try:
        def try_sql(sql, params=()):
            try:
                cur.execute('SAVEPOINT sp')
                cur.execute(sql, params)
                cur.execute('RELEASE SAVEPOINT sp')
            except Exception as e:
                cur.execute('ROLLBACK TO SAVEPOINT sp')
                app.logger.warning(f'delete_event skip: {e}')

        try_sql('UPDATE youth_sign_ins SET event_id=NULL WHERE event_id=%s', (eid,))
        try_sql('UPDATE kiosk_sessions SET event_id=NULL WHERE event_id=%s', (eid,))
        try_sql('DELETE FROM event_waivers WHERE event_id=%s', (eid,))
        try_sql('DELETE FROM event_elics WHERE event_id=%s', (eid,))
        try_sql('DELETE FROM event_checklist_responses WHERE event_id=%s', (eid,))
        try_sql('DELETE FROM hours WHERE event_id=%s', (eid,))

        # Carpools
        try:
            cur.execute('SAVEPOINT sp_carpools')
            cur.execute('SELECT id FROM carpools WHERE event_id=%s', (eid,))
            carpool_ids = [r[0] for r in cur.fetchall()]
            for cid in carpool_ids:
                cur.execute('DELETE FROM carpool_members WHERE carpool_id=%s', (cid,))
            if carpool_ids:
                cur.execute('DELETE FROM carpools WHERE event_id=%s', (eid,))
            cur.execute('RELEASE SAVEPOINT sp_carpools')
        except Exception as e:
            cur.execute('ROLLBACK TO SAVEPOINT sp_carpools')
            app.logger.warning(f'delete_event carpools: {e}')

        # The main delete  -  if this fails we want the real error
        cur.execute('DELETE FROM events WHERE id=%s', (eid,))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})

    except Exception as e:
        try: conn.rollback()
        except: pass
        try: cur.close()
        except: pass
        conn.close()
        app.logger.error(f'delete_event {eid}: {e}')
        return jsonify({'error': str(e)}), 500

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

@app.route('/api/volunteers/<vol_id>/communications')
def get_volunteer_communications(vol_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT * FROM volunteer_communications
        WHERE volunteer_id=%s ORDER BY sent_at DESC''', (vol_id,))
    conn.close()
    return jsonify(rows)

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
    # Board membership
    vol['board_member'] = fetchone(conn, '''SELECT bm.*, 
        (SELECT COUNT(*) FROM board_meeting_attendance WHERE member_id=bm.id AND attendance_type IN ('in_person','virtual')) as meetings_attended,
        (SELECT COUNT(*) FROM board_meeting_attendance WHERE member_id=bm.id) as meetings_total
        FROM board_members bm WHERE bm.volunteer_id=%s''', (vol_id,))
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers', methods=['POST'])
def create_volunteer():
    err = require_permission('volunteers')
    if err: return err
    d = request.json or {}
    vid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteers (id,name,email,phone,birthday,status,interests,background_check_status,background_check_date,bio,photo_url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (vid, d.get('name',''), d.get('email',''), d.get('phone',''), d.get('birthday') or None, d.get('status','active'), json.dumps(d.get('interests',[])), d.get('background_check_status','none'), d.get('background_check_date') or None, d.get('bio','') or '', d.get('photo_url','') or ''))
    conn.commit()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vid,))
    vol['total_hours'] = 0; vol['waiver_status'] = 'none'; vol['waivers'] = []
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['PUT'])
def update_volunteer(vol_id):
    err = require_permission('volunteers')
    if err: return err
    d = request.json or {}
    conn = get_db()
    # Ensure employer_program column exists (safe migration)
    try:
        execute(conn, "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS employer_program TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        try: conn.rollback()
        except Exception: pass
    sub_selections = json.dumps(d.get('sub_selections') or {})
    # Ensure bio/photo columns exist
    try:
        execute(conn, "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS bio TEXT DEFAULT ''")
        execute(conn, "ALTER TABLE volunteers ADD COLUMN IF NOT EXISTS photo_url TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        try: conn.rollback()
        except: pass
    execute(conn, '''UPDATE volunteers SET name=%s,email=%s,phone=%s,pronouns=%s,birthday=%s,status=%s,
        interests=%s,sub_selections=%s,background_check_status=%s,background_check_date=%s,employer_program=%s,
        bio=%s,photo_url=%s
        WHERE id=%s''',
        (d.get('name',''), d.get('email',''), d.get('phone',''), d.get('pronouns',''),
         d.get('birthday') or None, d.get('status','active'),
         json.dumps(d.get('interests',[])), sub_selections,
         d.get('background_check_status','none'), d.get('background_check_date') or None,
         d.get('employer_program','') or '',
         d.get('bio','') or '', d.get('photo_url','') or '',
         vol_id))
    conn.commit()
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vol_id,))
    conn.close()
    return jsonify(vol)

@app.route('/api/volunteers/<vol_id>', methods=['DELETE'])
def delete_volunteer(vol_id):
    err = require_permission('volunteers')
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
    err = require_permission('hours')
    if err: return err
    d = request.json or {}
    hid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (hid, d.get('volunteer_id'), d.get('event',''), d.get('event_id'), d.get('date',''), d.get('hours',0), d.get('role',''), d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT h.*, v.name as volunteer_name FROM hours h JOIN volunteers v ON h.volunteer_id=v.id WHERE h.id=%s', (hid,))
    conn.close()
    return jsonify(row)

@app.route('/api/hours/<hid>', methods=['DELETE'])
def delete_hours(hid):
    err = require_permission('hours')
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
    err = require_permission('volunteers')
    if err: return err
    d = request.json or {}
    nid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO notes (id,volunteer_id,author,content) VALUES (%s,%s,%s,%s)',
            (nid, vol_id, session['user_name'], d.get('content','')))
    conn.commit()
    note = fetchone(conn, 'SELECT * FROM notes WHERE id=%s', (nid,))
    conn.close()
    return jsonify(note)

# ─────────────────────────────────────────────
#  HISTORY
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/history', methods=['POST'])
def create_history(vol_id):
    err = require_permission('volunteers')
    if err: return err
    d = request.json or {}
    hid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteer_history (id,volunteer_id,event,role,date,notes) VALUES (%s,%s,%s,%s,%s,%s)',
            (hid, vol_id, d.get('event',''), d.get('role',''), d.get('date',''), d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM volunteer_history WHERE id=%s', (hid,))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  FILES
# ─────────────────────────────────────────────

@app.route('/api/volunteers/<vol_id>/files', methods=['POST'])
def create_file(vol_id):
    err = require_permission('volunteers')
    if err: return err
    d = request.json or {}
    fid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO volunteer_files (id,volunteer_id,name,size,type,date) VALUES (%s,%s,%s,%s,%s,%s)',
            (fid, vol_id, d.get('name',''), d.get('size',''), d.get('type',''), date.today().isoformat()))
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
    d = request.json or {}
    if not (d.get('name') or '').strip(): return jsonify({'error': 'Name is required'}), 400
    tid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO waiver_types (id,name,description,template_body,can_sign_online)
            VALUES (%s,%s,%s,%s,%s)''',
            (tid, (d.get('name') or '').strip(), d.get('description',''),
             d.get('template_body',''), bool(d.get('can_sign_online',False))))
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
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE waiver_types SET name=%s, description=%s, template_body=%s,
        can_sign_online=%s WHERE id=%s''',
        (d.get('name',''), d.get('description',''), d.get('template_body',''),
         bool(d.get('can_sign_online',False)), tid))
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
    err = require_permission('volunteers')
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
    d = request.json or {}
    vol_id         = d.get('volunteer_id')
    waiver_type_id = d.get('waiver_type_id')
    signed_name    = (d.get('signed_name') or '').strip()
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
    err = require_permission('volunteers')
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

@app.route('/api/youth-participants/check-duplicates', methods=['POST'])
def check_youth_duplicates():
    err = require_auth()
    if err: return err
    d = request.json or {}
    rows = d.get('rows', [])
    conn = get_db()
    results = []
    for row in rows:
        first = (row.get('first_name') or '').strip().lower()
        last  = (row.get('last_name') or '').strip().lower()
        dob   = (row.get('dob') or '').strip()
        if dob:
            match = fetchone(conn, 'SELECT id,first_name,last_name,dob FROM youth_participants WHERE LOWER(first_name)=%s AND LOWER(last_name)=%s AND dob=%s', (first, last, dob))
        else:
            match = fetchone(conn, 'SELECT id,first_name,last_name,dob FROM youth_participants WHERE LOWER(first_name)=%s AND LOWER(last_name)=%s', (first, last))
        results.append({'existing': match})
    conn.close()
    return jsonify(results)

@app.route('/api/youth-participants/bulk-import', methods=['POST'])
def bulk_import_youth():
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    rows = d.get('rows', [])
    program_id = d.get('program_id') or None
    enrolled_date = d.get('enrolled_date') or None
    if not rows:
        return jsonify({'error': 'No rows provided'}), 400
    conn = get_db()
    results = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}
    for i, row in enumerate(rows):
        try:
            first = (row.get('first_name') or '').strip()
            last  = (row.get('last_name') or '').strip()
            if not first or not last:
                results['errors'].append(f'Row {i+1}: first_name and last_name required')
                continue
            action      = row.get('action', 'create')
            existing_id = row.get('existing_id')
            if action == 'skip':
                results['skipped'] += 1
                continue
            dob             = (row.get('dob') or '').strip() or None
            status          = (row.get('status') or 'active').strip()
            medical_notes   = (row.get('medical_notes') or '').strip()
            allergies       = (row.get('allergies') or '').strip()
            photo_consent   = 1 if str(row.get('photo_consent','')).lower() in ('1','yes','true','y') else 0
            medical_consent = 1 if str(row.get('medical_consent','')).lower() in ('1','yes','true','y') else 0
            if action == 'update' and existing_id:
                execute(conn, 'UPDATE youth_participants SET first_name=%s,last_name=%s,dob=%s,status=%s,medical_notes=%s,allergies=%s,photo_consent=%s,medical_consent=%s WHERE id=%s',
                    (first, last, dob, status, medical_notes, allergies, photo_consent, medical_consent, existing_id))
                yid = existing_id
                results['updated'] += 1
            else:
                yid = str(uuid.uuid4())
                pp = default_passphrase(first, last)
                execute(conn, 'INSERT INTO youth_participants (id,first_name,last_name,dob,status,medical_notes,allergies,photo_consent,medical_consent,passphrase) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (yid, first, last, dob, status, medical_notes, allergies, photo_consent, medical_consent, pp))
                results['created'] += 1
            # Guardian
            gname = (row.get('guardian_name') or '').strip()
            if gname:
                existing_g = fetchone(conn, 'SELECT id FROM youth_guardians WHERE youth_id=%s AND is_primary=1', (yid,))
                if existing_g:
                    execute(conn, 'UPDATE youth_guardians SET name=%s,relationship=%s,phone=%s,email=%s WHERE id=%s',
                        (gname, (row.get('guardian_relationship') or '').strip(), (row.get('guardian_phone') or '').strip(), (row.get('guardian_email') or '').strip(), existing_g['id']))
                else:
                    execute(conn, 'INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (%s,%s,%s,%s,%s,%s,1)',
                        (str(uuid.uuid4()), yid, gname, (row.get('guardian_relationship') or '').strip(), (row.get('guardian_phone') or '').strip(), (row.get('guardian_email') or '').strip()))
            # Emergency contact
            ecname = (row.get('emergency_name') or '').strip()
            if ecname and (row.get('emergency_phone') or '').strip():
                try:
                    execute(conn, 'INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                        (str(uuid.uuid4()), yid, ecname, (row.get('emergency_relationship') or '').strip(), (row.get('emergency_phone') or '').strip()))
                except Exception:
                    pass
            # Authorized pickups
            for priority, prefix in enumerate(['pickup1','pickup2'], 1):
                puname = (row.get(prefix+'_name') or '').strip()
                if puname:
                    try:
                        execute(conn, 'INSERT INTO youth_authorized_pickups (id,youth_id,name,relationship,phone,priority) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                            (str(uuid.uuid4()), yid, puname, (row.get(prefix+'_relationship') or '').strip(), (row.get(prefix+'_phone') or '').strip(), priority))
                    except Exception:
                        pass
            # Program enrollment
            if program_id:
                try:
                    execute(conn, 'INSERT INTO youth_program_enrollments (id,youth_id,program_id,enrolled_date) VALUES (%s,%s,%s,%s) ON CONFLICT (youth_id,program_id) DO NOTHING',
                        (str(uuid.uuid4()), yid, program_id, enrolled_date))
                except Exception:
                    pass
            conn.commit()
        except Exception as e:
            results['errors'].append(f'Row {i+1} ({row.get("first_name","")} {row.get("last_name","")}): {str(e)}')
            try: conn.rollback()
            except Exception: pass
    conn.close()
    return jsonify(results)

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
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    if not (d.get('name') or '').strip(): return jsonify({'error': 'Name is required'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO youth_programs (id,name,description,program_type,start_date,end_date,instructor_id,default_elic_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                (pid, (d.get('name') or '').strip(), d.get('description',''),
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
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    if not (d.get('name') or '').strip(): return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    execute(conn, 'UPDATE youth_programs SET name=%s,description=%s,program_type=%s,start_date=%s,end_date=%s,instructor_id=%s,default_elic_id=%s WHERE id=%s',
            ((d.get('name') or '').strip(), d.get('description',''),
             d.get('program_type','class'), d.get('start_date') or None,
             d.get('end_date') or None, d.get('instructor_id') or None,
             d.get('default_elic_id') or None, pid))
    conn.commit()
    row = fetchone(conn, '''SELECT yp.*, v.name as default_elic_name FROM youth_programs yp LEFT JOIN elics el ON yp.default_elic_id=el.id LEFT JOIN volunteers v ON el.volunteer_id=v.id WHERE yp.id=%s''', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-programs/<pid>/announcements/<aid>/push', methods=['POST'])
def push_program_announcement(pid, aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Mark as published
    execute(conn, '''UPDATE portal_announcements
        SET status='published', pushed_at=NOW(), push_count=COALESCE(push_count,0)+1
        WHERE id=%s AND program_id=%s''', (aid, pid))
    conn.commit()
    ann = fetchone(conn, 'SELECT * FROM portal_announcements WHERE id=%s', (aid,))
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not ann or not prog:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    # Gather recipient emails
    recipients = set()
    enrolled = fetchall(conn, '''SELECT y.id FROM youth_participants y
        JOIN youth_program_enrollments ype ON ype.youth_id=y.id
        WHERE ype.program_id=%s AND y.status='active' ''', (pid,))
    for y in enrolled:
        guardians = fetchall(conn, "SELECT email FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email!=''", (y['id'],))
        for g in guardians:
            if g['email']: recipients.add(g['email'].strip().lower())
    # Instructor
    if prog.get('instructor_id'):
        vol = fetchone(conn, 'SELECT email FROM volunteers WHERE id=%s', (prog['instructor_id'],))
        if vol and vol.get('email'): recipients.add(vol['email'].strip().lower())
    conn.close()
    if not recipients:
        return jsonify({'ok': True, 'sent_to': 0, 'warning': 'No email addresses on file'})
    prog_name = prog.get('name','Program')
    html_body = f'''<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#0d9488;padding:24px;border-radius:8px 8px 0 0">
        <div style="color:rgba(255,255,255,0.8);font-size:13px;margin-bottom:4px">New Announcement</div>
        <h2 style="color:white;margin:0;font-size:22px">{prog_name}</h2>
      </div>
      <div style="background:#f8fafc;padding:28px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;border-top:none">
        <h3 style="color:#1e293b;margin:0 0 12px 0;font-size:18px">{ann['title']}</h3>
        <div style="white-space:pre-wrap;font-size:15px;line-height:1.8;color:#334155">{ann['body']}</div>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0"/>
        <p style="font-size:12px;color:#94a3b8;margin:0">
          Posted by Horizon West Theater Company for <strong>{prog_name}</strong>.
          Log in to the family portal to view and respond to announcements.
        </p>
      </div>
    </div>'''
    try:
        fi = (request.json or {}).get('from_identity') or {}
        send_email(list(recipients), f'{prog_name}: {ann["title"]}', html_body, fi.get('email') or None, fi.get('name') or None)
        return jsonify({'ok': True, 'sent_to': len(recipients)})
    except Exception as e:
        app.logger.error(f'push_program_announcement email error: {e}')
        return jsonify({'ok': True, 'sent_to': 0, 'warning': str(e)})

@app.route('/api/youth-programs/<pid>/announcements/<aid>/unpublish', methods=['POST'])
def unpublish_program_announcement(pid, aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE portal_announcements SET status='draft' WHERE id=%s AND program_id=%s", (aid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth-programs/<pid>', methods=['DELETE'])
def delete_youth_program(pid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    # Clear any FK references that don't cascade
    execute(conn, 'UPDATE youth_sign_ins SET program_id=NULL WHERE program_id=%s', (pid,))
    execute(conn, 'UPDATE events SET program_id=NULL WHERE program_id=%s', (pid,))
    execute(conn, 'DELETE FROM youth_programs WHERE id=%s', (pid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth-programs/<pid>/send-email', methods=['POST'])
def send_program_email(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    subject = d.get('subject', '').strip()
    body = d.get('body', '').strip()
    include_guardians = d.get('include_guardians', True)
    include_instructors = d.get('include_instructors', True)
    if not subject or not body:
        return jsonify({'error': 'Subject and body are required'}), 400
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404

    recipients = set()

    # Guardian emails for all enrolled youth
    if include_guardians:
        enrolled = fetchall(conn, '''SELECT y.id FROM youth_participants y
            JOIN youth_program_enrollments ype ON ype.youth_id=y.id
            WHERE ype.program_id=%s AND y.status='active' ''', (pid,))
        for y in enrolled:
            guardians = fetchall(conn, 'SELECT email FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email != \'\'', (y['id'],))
            for g in guardians:
                if g['email']:
                    recipients.add(g['email'].strip().lower())

    # Instructor email
    if include_instructors and prog.get('instructor_id'):
        vol = fetchone(conn, 'SELECT email FROM volunteers WHERE id=%s', (prog['instructor_id'],))
        if vol and vol.get('email'):
            recipients.add(vol['email'].strip().lower())

    conn.close()

    if not recipients:
        return jsonify({'error': 'No email addresses found for this program'}), 400

    prog_name = prog.get('name', 'Program')
    html_body = f'''<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#0d9488;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="color:white;margin:0">📚 {prog_name}</h2>
      </div>
      <div style="background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0">
        <div style="white-space:pre-wrap;font-size:15px;line-height:1.7;color:#1e293b">{body}</div>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0"/>
        <p style="font-size:12px;color:#94a3b8">This message was sent by Horizon West Theater Company regarding the <strong>{prog_name}</strong> program.</p>
      </div>
    </div>'''

    try:
        send_email(list(recipients), subject, html_body)
        return jsonify({'ok': True, 'sent_to': len(recipients), 'recipients': list(recipients)})
    except Exception as e:
        app.logger.error(f'send_program_email error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/youth-programs/<pid>/send-welcome', methods=['POST'])
def send_program_welcome(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    # mode: 'all' | 'family' | 'participant'
    mode       = d.get('mode', 'all')
    family_id  = d.get('family_id')
    youth_id   = d.get('youth_id')
    subject_override = d.get('subject', '').strip()

    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404

    prog_name = prog.get('name', 'Program')

    # Load template
    tmpl = get_system_template(conn, 'welcome_email')
    if not tmpl:
        conn.close()
        return jsonify({'error': 'Welcome email template not found  -  check Email Templates in Settings'}), 404
    body_tmpl    = tmpl['body']
    subject_tmpl = tmpl['subject']

    # Build recipient list: list of dicts {email, passphrase, family_greeting}
    recipients = []

    if mode == 'participant' and youth_id:
        y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (youth_id,))
        if y:
            guardians = fetchall(conn, "SELECT email, name FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email != ''", (youth_id,))
            pp = y.get('passphrase') or f"{y['first_name'].lower()}_{y['last_name'].lower()}_hwtc"
            greeting = f"{y['first_name']} {y['last_name']}"
            for g in guardians:
                if g['email']:
                    recipients.append({'email': g['email'].strip(), 'passphrase': pp, 'family_greeting': greeting, 'name': g.get('name','')})
            # Also check family passphrase
            if y.get('family_id'):
                fam = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (y['family_id'],))
                if fam and fam.get('passphrase'):
                    for r in recipients:
                        r['passphrase'] = fam['passphrase']

    elif mode == 'family' and family_id:
        fam = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (family_id,))
        if fam:
            members = fetchall(conn, "SELECT * FROM youth_participants WHERE family_id=%s AND status='active'", (family_id,))
            pp = fam.get('passphrase', '')
            greeting = fam.get('name', 'HWTC Family')
            # Family email first
            if fam.get('email'):
                recipients.append({'email': fam['email'].strip(), 'passphrase': pp, 'family_greeting': greeting})
            # Guardian emails
            for m in members:
                guardians = fetchall(conn, "SELECT email, name FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email != ''", (m['id'],))
                for g in guardians:
                    if g['email']:
                        recipients.append({'email': g['email'].strip(), 'passphrase': pp, 'family_greeting': greeting})

    else:  # all enrolled in program
        enrolled = fetchall(conn, """
            SELECT y.* FROM youth_participants y
            JOIN youth_program_enrollments ype ON ype.youth_id=y.id
            WHERE ype.program_id=%s AND y.status='active'""", (pid,))
        for y in enrolled:
            pp = y.get('passphrase') or f"{y['first_name'].lower()}_{y['last_name'].lower()}_hwtc"
            greeting = f"{y['first_name']} {y['last_name']}"
            # Prefer family passphrase if set
            if y.get('family_id'):
                fam = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (y['family_id'],))
                if fam and fam.get('passphrase'):
                    pp = fam['passphrase']
                    greeting = fam.get('name', greeting)
            guardians = fetchall(conn, "SELECT email, name FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email != ''", (y['id'],))
            for g in guardians:
                if g['email']:
                    recipients.append({'email': g['email'].strip(), 'passphrase': pp, 'family_greeting': greeting})

    conn.close()

    # Deduplicate by email (keep first passphrase seen per address)
    seen = {}
    deduped = []
    for r in recipients:
        e = r['email'].lower()
        if e not in seen:
            seen[e] = True
            deduped.append(r)

    if not deduped:
        return jsonify({'error': 'No email addresses found for the selected recipients'}), 400

    subject_base = subject_override or subject_tmpl.replace('{{program_name}}', prog_name)

    sent = 0
    errors = []
    fi = d.get('from_identity') or {}
    for r in deduped:
        html_body = (body_tmpl
            .replace('{{program_name}}', prog_name)
            .replace('{{passphrase}}', r.get('passphrase', ''))
            .replace('{{family_greeting}}', r.get('family_greeting', 'HWTC Family')))
        subject = subject_base.replace('{{program_name}}', prog_name)
        ok, err_msg = send_email([r['email']], subject, html_body, fi.get('email') or None, fi.get('name') or None)
        if ok:
            sent += 1
        else:
            errors.append({'email': r['email'], 'error': err_msg})

    return jsonify({
        'ok': True,
        'sent': sent,
        'total': len(deduped),
        'errors': errors,
        'recipients': [r['email'] for r in deduped],
    })


@app.route('/api/youth-programs/<pid>/welcome-recipients', methods=['GET'])
def get_welcome_recipients(pid):
    """Preview who would receive the welcome email for a program."""
    err = require_auth()
    if err: return err
    conn = get_db()
    enrolled = fetchall(conn, """
        SELECT y.id, y.first_name, y.last_name, y.passphrase, y.family_id,
               y.status
        FROM youth_participants y
        JOIN youth_program_enrollments ype ON ype.youth_id=y.id
        WHERE ype.program_id=%s AND y.status='active'
        ORDER BY y.last_name, y.first_name""", (pid,))

    result = []
    for y in enrolled:
        pp = y.get('passphrase') or f"{y['first_name'].lower()}_{y['last_name'].lower()}_hwtc"
        family_name = None
        family_id   = y.get('family_id')
        if family_id:
            fam = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (family_id,))
            if fam:
                if fam.get('passphrase'):
                    pp = fam['passphrase']
                family_name = fam.get('name')
        guardians = fetchall(conn, "SELECT name, email FROM youth_guardians WHERE youth_id=%s AND email IS NOT NULL AND email != ''", (y['id'],))
        result.append({
            'youth_id':     y['id'],
            'name':         f"{y['first_name']} {y['last_name']}",
            'family_id':    family_id,
            'family_name':  family_name,
            'passphrase':   pp,
            'guardians':    guardians,
        })

    conn.close()
    return jsonify(result)


# ─────────────────────────────────────────────────────────────
#  PORTAL MESSAGING THREADS
# ─────────────────────────────────────────────────────────────

@app.route('/api/portal/messages/start', methods=['POST'])
def portal_start_message_thread():
    d = request.json or {}
    passphrase   = d.get('passphrase','').strip()
    subject      = (d.get('subject') or '').strip()
    body         = (d.get('body') or '').strip()
    program_id   = d.get('program_id') or None
    production_id = d.get('production_id') or None
    if not subject or not body:
        return jsonify({'error': 'Subject and message are required'}), 400
    conn = get_db()
    family = fetchone(conn, 'SELECT * FROM families WHERE passphrase=%s', (passphrase,)) if passphrase else None
    sender_name = d.get('sender_name','').strip() or (family.get('name') if family else 'Family')
    family_id   = family['id'] if family else None
    tid = str(uuid.uuid4())
    execute(conn, """INSERT INTO portal_message_threads
        (id, family_id, program_id, production_id, subject, status, unread_admin, unread_family, family_passphrase)
        VALUES (%s,%s,%s,%s,%s,'open',1,0,%s)""",
        (tid, family_id, program_id, production_id, subject, passphrase or None))
    execute(conn, "INSERT INTO portal_messages (id,thread_id,sender_side,sender_name,body) VALUES (%s,%s,'family',%s,%s)",
        (str(uuid.uuid4()), tid, sender_name, body))
    conn.commit()
    # Email notify  -  configured recipients + all admins + anyone with youth permission
    s = get_email_settings()
    recipients = list(get_recipient_emails(s))
    try:
        staff_with_perm = fetchall(conn, """SELECT email FROM users
            WHERE email IS NOT NULL AND email!='' AND active=TRUE
            AND (role='admin' OR role_permissions::text LIKE '%"youth"%')""")
        for u in staff_with_perm:
            if u['email'] and u['email'] not in recipients:
                recipients.append(u['email'])
    except Exception as e:
        app.logger.warning(f'portal message staff lookup failed: {e}')
    # Always fall back to all admin users if list is still empty
    if not recipients:
        try:
            admins = fetchall(conn, "SELECT email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''")
            recipients = [u['email'] for u in admins if u.get('email')]
        except Exception: pass
    # Also notify the program instructor if one is set
    try:
        if program_id:
            prog_row = fetchone(conn, 'SELECT name, instructor_id FROM youth_programs WHERE id=%s', (program_id,))
            if prog_row and prog_row.get('instructor_id'):
                vol = fetchone(conn, 'SELECT email FROM volunteers WHERE id=%s', (prog_row['instructor_id'],))
                if vol and vol.get('email') and vol['email'] not in recipients:
                    recipients.append(vol['email'])
        elif production_id:
            prod_row = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (production_id,))
    except Exception: pass

    if recipients:
        ctx = ''
        if program_id:
            p = fetchone(conn, 'SELECT name FROM youth_programs WHERE id=%s', (program_id,))
            if p: ctx = f' - {p["name"]}'
        elif production_id:
            p = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (production_id,))
            if p: ctx = f' - {p["name"]}'
        html = f'<div style="font-family:-apple-system,sans-serif;max-width:600px"><h2 style="color:#145466">New Portal Message{ctx}</h2><p><strong>From:</strong> {sender_name}<br/><strong>Subject:</strong> {subject}</p><div style="background:#f5f9fa;padding:14px;border-radius:8px;margin:12px 0">{body}</div><p style="color:#9ca3af;font-size:12px">Reply via Programs or Productions - Portal Content - Messages tab in RoleCall admin.</p></div>'
        send_email(recipients, f'Portal Message: {subject}', html)
    conn.close()
    return jsonify({'ok': True, 'thread_id': tid})


@app.route('/api/portal/messages/thread/<tid>')
def portal_get_thread(tid):
    passphrase = request.args.get('passphrase','')
    conn = get_db()
    thread = fetchone(conn, 'SELECT * FROM portal_message_threads WHERE id=%s', (tid,))
    if not thread:
        conn.close(); return jsonify({'error': 'Not found'}), 404
    is_admin  = session.get('user_id') is not None
    is_family = passphrase and thread.get('family_passphrase') == passphrase
    if not is_admin and not is_family:
        conn.close(); return jsonify({'error': 'Unauthorized'}), 403
    messages = fetchall(conn, 'SELECT * FROM portal_messages WHERE thread_id=%s ORDER BY sent_at', (tid,))
    if is_admin:
        execute(conn, 'UPDATE portal_message_threads SET unread_admin=0 WHERE id=%s', (tid,))
    if is_family:
        execute(conn, 'UPDATE portal_message_threads SET unread_family=0 WHERE id=%s', (tid,))
    conn.commit()
    prog = fetchone(conn, 'SELECT name FROM youth_programs WHERE id=%s', (thread.get('program_id'),)) if thread.get('program_id') else None
    prod = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (thread.get('production_id'),)) if thread.get('production_id') else None
    conn.close()
    return jsonify({**dict(thread), 'messages': messages,
        'program_name': prog['name'] if prog else None,
        'production_name': prod['name'] if prod else None,
        'from_name': messages[0]['sender_name'] if messages else 'Family'})


@app.route('/api/portal/messages/thread/<tid>/reply', methods=['POST'])
def portal_reply_thread(tid):
    d = request.json or {}
    body = (d.get('body') or '').strip()
    if not body: return jsonify({'error': 'Message body required'}), 400
    conn = get_db()
    thread = fetchone(conn, 'SELECT * FROM portal_message_threads WHERE id=%s', (tid,))
    if not thread:
        conn.close(); return jsonify({'error': 'Not found'}), 404
    is_admin  = session.get('user_id') is not None
    passphrase = d.get('passphrase','')
    is_family  = passphrase and thread.get('family_passphrase') == passphrase
    if not is_admin and not is_family:
        conn.close(); return jsonify({'error': 'Unauthorized'}), 403
    side = 'admin' if is_admin else 'family'
    sender_name = session.get('user_name','Staff') if is_admin else (d.get('sender_name') or 'Family')
    execute(conn, 'INSERT INTO portal_messages (id,thread_id,sender_side,sender_name,body) VALUES (%s,%s,%s,%s,%s)',
        (str(uuid.uuid4()), tid, side, sender_name, body))
    if is_admin:
        execute(conn, 'UPDATE portal_message_threads SET unread_family=unread_family+1, updated_at=NOW() WHERE id=%s', (tid,))
    else:
        execute(conn, 'UPDATE portal_message_threads SET unread_admin=unread_admin+1, updated_at=NOW() WHERE id=%s', (tid,))
    conn.commit()
    s = get_email_settings()
    if is_admin and thread.get('family_passphrase'):
        try:
            family = fetchone(conn, 'SELECT email FROM families WHERE passphrase=%s', (thread['family_passphrase'],))
            if family and family.get('email'):
                html = f'<div style="font-family:-apple-system,sans-serif;max-width:600px"><h2 style="color:#145466">New reply: {thread["subject"]}</h2><div style="background:#f5f9fa;padding:14px;border-radius:8px;margin:12px 0">{body}</div><p><a href="https://rolecall.hwtco.org/portal.html" style="background:#145466;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:700">View in Portal</a></p></div>'
                send_email([family['email']], f'Re: {thread["subject"]}', html)
        except Exception: pass
    elif is_family:
        recipients = list(get_recipient_emails(s))
        try:
            staff = fetchall(conn, """SELECT email FROM users WHERE email IS NOT NULL AND email!='' AND active=TRUE
                AND (role='admin' OR role_permissions::text LIKE '%"youth"%')""")
            for u in staff:
                if u['email'] and u['email'] not in recipients: recipients.append(u['email'])
        except Exception as e:
            app.logger.warning(f'portal reply staff lookup failed: {e}')
        if not recipients:
            try:
                admins = fetchall(conn, "SELECT email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''")
                recipients = [u['email'] for u in admins if u.get('email')]
            except Exception: pass
        # Also notify the program instructor
        try:
            if thread.get('program_id'):
                prog_row = fetchone(conn, 'SELECT instructor_id FROM youth_programs WHERE id=%s', (thread['program_id'],))
                if prog_row and prog_row.get('instructor_id'):
                    vol = fetchone(conn, 'SELECT email FROM volunteers WHERE id=%s', (prog_row['instructor_id'],))
                    if vol and vol.get('email') and vol['email'] not in recipients:
                        recipients.append(vol['email'])
        except Exception: pass
        if recipients:
            html = f'<div style="font-family:-apple-system,sans-serif;max-width:600px"><h2 style="color:#145466">Family replied: {thread["subject"]}</h2><div style="background:#f5f9fa;padding:14px;border-radius:8px;margin:12px 0">{body}</div></div>'
            send_email(recipients, f'Portal Reply: {thread["subject"]}', html)
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/portal/messages/threads')
def portal_list_threads():
    err = require_auth()
    if err: return err
    program_id    = request.args.get('program_id')
    production_id = request.args.get('production_id')
    conn = get_db()
    where, vals = [], []
    if program_id:    where.append('t.program_id=%s');    vals.append(program_id)
    if production_id: where.append('t.production_id=%s'); vals.append(production_id)
    clause = ('WHERE ' + ' AND '.join(where)) if where else ''
    threads = fetchall(conn, f"""
        SELECT t.*,
            (SELECT COUNT(*) FROM portal_messages WHERE thread_id=t.id) as message_count,
            (SELECT body FROM portal_messages WHERE thread_id=t.id ORDER BY sent_at DESC LIMIT 1) as last_body,
            (SELECT sent_at FROM portal_messages WHERE thread_id=t.id ORDER BY sent_at DESC LIMIT 1) as last_at,
            (SELECT sender_name FROM portal_messages WHERE thread_id=t.id ORDER BY sent_at ASC LIMIT 1) as from_name,
            yp.name as program_name, p.name as production_name
        FROM portal_message_threads t
        LEFT JOIN youth_programs yp ON yp.id=t.program_id
        LEFT JOIN productions p ON p.id=t.production_id
        {clause}
        ORDER BY t.updated_at DESC""", vals)
    conn.close()
    return jsonify(threads)


@app.route('/api/portal/messages/thread/<tid>/close', methods=['POST'])
def portal_close_thread(tid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE portal_message_threads SET status='closed' WHERE id=%s", (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/portal/messages/family')
def portal_family_threads():
    passphrase = request.args.get('passphrase','').strip()
    if not passphrase: return jsonify([])
    conn = get_db()
    threads = fetchall(conn, """
        SELECT t.*,
            (SELECT COUNT(*) FROM portal_messages WHERE thread_id=t.id) as message_count,
            (SELECT body FROM portal_messages WHERE thread_id=t.id ORDER BY sent_at DESC LIMIT 1) as last_body,
            (SELECT sent_at FROM portal_messages WHERE thread_id=t.id ORDER BY sent_at DESC LIMIT 1) as last_at,
            yp.name as program_name, p.name as production_name
        FROM portal_message_threads t
        LEFT JOIN youth_programs yp ON yp.id=t.program_id
        LEFT JOIN productions p ON p.id=t.production_id
        WHERE t.family_passphrase=%s
        ORDER BY t.updated_at DESC""", (passphrase,))
    conn.close()
    return jsonify(threads)



# ─────────────────────────────────────────────────────────────
#  AUDITIONS
# ─────────────────────────────────────────────────────────────

@app.route('/api/auditions/settings/<context_type>/<context_id>', methods=['GET'])
def get_audition_settings(context_type, context_id):
    conn = get_db()
    row = fetchone(conn, 'SELECT * FROM audition_settings WHERE context_id=%s AND context_type=%s',
        (context_id, context_type))
    conn.close()
    if not row:
        resp = jsonify({'context_type': context_type, 'context_id': context_id,
            'is_open': False, 'roles': [], 'allow_video_link': True,
            'allow_resume_link': True, 'allow_headshot_link': True})
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    try: row['roles'] = json.loads(row.get('roles') or '[]')
    except Exception: row['roles'] = []
    resp = jsonify(row)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/api/auditions/settings/<context_type>/<context_id>', methods=['PUT'])
def save_audition_settings(context_type, context_id):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    existing = fetchone(conn, 'SELECT id FROM audition_settings WHERE context_id=%s AND context_type=%s',
        (context_id, context_type))
    roles_json = json.dumps(d.get('roles') or [])
    is_open  = bool(d.get('is_open', False))
    title    = (d.get('title') or '').strip() or None
    desc     = (d.get('description') or '').strip() or None
    aud_date = d.get('audition_date') or None
    aud_time = d.get('audition_time') or None
    location = (d.get('location') or '').strip() or None
    instructions = (d.get('instructions') or '').strip() or None
    email_sub    = (d.get('email_submissions') or '').strip() or None
    allow_video  = bool(d.get('allow_video_link', True))
    allow_resume = bool(d.get('allow_resume_link', True))
    allow_head   = bool(d.get('allow_headshot_link', True))
    if existing:
        execute(conn, """UPDATE audition_settings SET is_open=%s,title=%s,description=%s,
            audition_date=%s,audition_time=%s,location=%s,roles=%s,instructions=%s,
            email_submissions=%s,allow_video_link=%s,allow_resume_link=%s,allow_headshot_link=%s,
            updated_at=NOW() WHERE context_id=%s AND context_type=%s""",
            (is_open,title,desc,aud_date,aud_time,location,roles_json,instructions,
             email_sub,allow_video,allow_resume,allow_head,context_id,context_type))
    else:
        sid = str(uuid.uuid4())
        execute(conn, """INSERT INTO audition_settings
            (id,context_type,context_id,is_open,title,description,audition_date,audition_time,
             location,roles,instructions,email_submissions,allow_video_link,allow_resume_link,allow_headshot_link)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (sid,context_type,context_id,is_open,title,desc,aud_date,aud_time,
             location,roles_json,instructions,email_sub,allow_video,allow_resume,allow_head))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/list/<context_type>/<context_id>', methods=['GET'])
def get_audition_submissions(context_type, context_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        rows = fetchall(conn, """SELECT id, context_type, context_id, family_id,
            participant_id, submitter_name, submitter_email, role_requested,
            video_url, resume_url, headshot_url, notes, status, admin_notes,
            submitted_at, updated_at,
            COALESCE(roles_requested, '[]') as roles_requested,
            COALESCE(cast_role, '') as cast_role
            FROM audition_submissions
            WHERE context_type=%s AND context_id=%s ORDER BY submitted_at DESC""",
            (context_type, context_id))
    except Exception as e:
        app.logger.error(f'get_audition_submissions error: {e}')
        # Fallback without new columns if migration hasn't run yet
        try:
            rows = fetchall(conn, """SELECT * FROM audition_submissions
                WHERE context_type=%s AND context_id=%s ORDER BY submitted_at DESC""",
                (context_type, context_id))
            for r in rows:
                if 'roles_requested' not in r: r['roles_requested'] = '[]'
                if 'cast_role' not in r: r['cast_role'] = ''
        except Exception as e2:
            conn.close()
            app.logger.error(f'get_audition_submissions fallback error: {e2}')
            return jsonify([])
    conn.close()
    return jsonify(rows)


@app.route('/api/auditions/submit', methods=['POST'])
def submit_audition():
    d = request.json or {}
    context_type = d.get('context_type')
    context_id   = d.get('context_id')
    name = (d.get('submitter_name') or '').strip()
    if not context_type or not context_id or not name:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    settings = fetchone(conn, 'SELECT * FROM audition_settings WHERE context_id=%s AND context_type=%s',
        (context_id, context_type))
    if not settings or not settings.get('is_open'):
        conn.close()
        return jsonify({'error': 'Auditions are not currently open'}), 400
    passphrase  = (d.get('passphrase') or '').strip()
    family      = fetchone(conn, 'SELECT * FROM families WHERE passphrase=%s', (passphrase,)) if passphrase else None
    family_id   = family['id'] if family else None
    sid = str(uuid.uuid4())
    execute(conn, """INSERT INTO audition_submissions
        (id,context_type,context_id,family_id,participant_id,submitter_name,
         submitter_email,role_requested,video_url,resume_url,headshot_url,notes,submitter_passphrase)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
        sid, context_type, context_id, family_id,
        d.get('participant_id') or None, name,
        (d.get('submitter_email') or '').strip() or None,
        json.dumps(d.get('roles_requested') or ([d.get('role_requested')] if d.get('role_requested') else [])) ,
        (d.get('video_url') or '').strip() or None,
        (d.get('resume_url') or '').strip() or None,
        (d.get('headshot_url') or '').strip() or None,
        (d.get('notes') or '').strip() or None,
        passphrase or None,
    ))
    conn.commit()
    # Get context name
    ctx_name = ''
    instructor_id = None
    if context_type == 'production':
        p = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (context_id,))
        if p: ctx_name = p['name']
    elif context_type == 'program':
        p = fetchone(conn, 'SELECT name, instructor_id FROM youth_programs WHERE id=%s', (context_id,))
        if p:
            ctx_name = p['name']
            instructor_id = p.get('instructor_id')
    # Notify  -  instructor + info@ + audition email_submissions only (not all admins)
    try:
        recipients = []
        # 1. Program/production instructor
        if instructor_id:
            try:
                vol = fetchone(conn, 'SELECT email FROM volunteers WHERE id=%s', (instructor_id,))
                if vol and vol.get('email'): recipients.append(vol['email'])
            except Exception: pass
        # 2. info@ default fallback
        info_email = 'info@hwtco.org'
        if info_email not in recipients: recipients.append(info_email)
        # 3. Additional emails configured in audition settings
        if settings.get('email_submissions'):
            for e in settings['email_submissions'].split(','):
                e = e.strip()
                if e and e not in recipients: recipients.append(e)
        if recipients:
            links = []
            if d.get('video_url'):    links.append('<a href="' + d['video_url'] + '">Video</a>')
            if d.get('resume_url'):   links.append('<a href="' + d['resume_url'] + '">Resume</a>')
            if d.get('headshot_url'): links.append('<a href="' + d['headshot_url'] + '">Headshot</a>')
            html = (
                '<div style="font-family:-apple-system,sans-serif;max-width:600px">'
                '<h2 style="color:#145466">New Audition: ' + ctx_name + '</h2>'
                '<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">'
                '<tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466;width:140px">Name</td><td style="padding:8px 12px">' + name + '</td></tr>'
                (lambda roles: '<tr><td style="padding:8px 12px;font-weight:700;color:#145466">Role(s)</td><td style="padding:8px 12px">' + (', '.join(roles) if roles else 'Not specified') + '</td></tr>')(
                    (lambda r: r if r else ([d.get('role_requested')] if d.get('role_requested') else []))(
                        __import__('json').loads(d.get('roles_requested') or '[]') if isinstance(d.get('roles_requested'), str) else (d.get('roles_requested') or [])
                    )
                )
                + ('<tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466">Email</td><td style="padding:8px 12px">' + d.get('submitter_email','') + '</td></tr>' if d.get('submitter_email') else '')
                + ('<tr><td style="padding:8px 12px;font-weight:700;color:#145466">Notes</td><td style="padding:8px 12px">' + d.get('notes','') + '</td></tr>' if d.get('notes') else '')
                + '</table>'
                + ('<p>' + ' &nbsp; '.join(links) + '</p>' if links else '')
                + '<p style="color:#9ca3af;font-size:12px">Manage submissions in RoleCall under the Auditions tab.</p>'
                + '</div>'
            )
            send_email(recipients, 'New Audition: ' + name + ' for ' + ctx_name, html)
    except Exception as e:
        app.logger.warning(f'Audition notification failed: {e}')
    # Confirmation to submitter
    try:
        sub_email = (d.get('submitter_email') or '').strip()
        if sub_email:
            conf = (
                '<div style="font-family:-apple-system,sans-serif;max-width:600px">'
                '<h2 style="color:#145466">Audition Received: ' + ctx_name + '</h2>'
                '<p>Hi ' + name + ', we received your audition for <strong>' + ctx_name + '</strong>.</p>'
                '<p><strong>Role requested:</strong> ' + (d.get('role_requested') or 'Not specified') + '</p>'
                '<p>We will be in touch soon.</p>'
                '<p style="color:#9ca3af;font-size:13px">Horizon West Theatre Company</p></div>'
            )
            send_email([sub_email], 'Audition Received: ' + ctx_name, conf)
    except Exception: pass
    conn.close()
    return jsonify({'ok': True, 'submission_id': sid})


@app.route('/api/auditions/submissions/<sid>/status', methods=['PUT'])
def update_audition_status(sid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE audition_submissions SET status=%s,admin_notes=%s,updated_at=NOW() WHERE id=%s',
        (d.get('status','pending'), d.get('admin_notes',''), sid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/submissions/<sid>', methods=['DELETE'])
def delete_audition_submission(sid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Hard delete the submission
    execute(conn, 'DELETE FROM audition_submissions WHERE id=%s', (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/submissions/<sid>/decline', methods=['POST'])
def decline_audition_submission(sid):
    """Soft-delete — marks as declined so portal shows the form again."""
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE audition_submissions SET status='declined', updated_at=NOW() WHERE id=%s", (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



@app.route('/api/auditions/my-submission', methods=['GET'])
def get_my_audition_submission():
    """Check if a family/participant already submitted for a context."""
    passphrase   = request.args.get('passphrase','').strip()
    context_type = request.args.get('context_type','')
    context_id   = request.args.get('context_id','')
    if not passphrase or not context_type or not context_id:
        return jsonify(None)
    conn = get_db()
    sub = None
    # Try by family record first
    family = fetchone(conn, 'SELECT id FROM families WHERE passphrase=%s', (passphrase,))
    if family:
        sub = fetchone(conn, """SELECT * FROM audition_submissions
            WHERE family_id=%s AND context_type=%s AND context_id=%s
            AND status NOT IN ('declined') ORDER BY submitted_at DESC LIMIT 1""",
            (family['id'], context_type, context_id))
    # Fallback: check by submitter passphrase stored on the submission
    if not sub:
        sub = fetchone(conn, """SELECT * FROM audition_submissions
            WHERE submitter_passphrase=%s AND context_type=%s AND context_id=%s
            AND status NOT IN ('declined') ORDER BY submitted_at DESC LIMIT 1""",
            (passphrase, context_type, context_id))
    conn.close()
    if not sub: 
        resp = jsonify(None)
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    try: sub['roles_requested'] = json.loads(sub.get('roles_requested') or '[]')
    except Exception: sub['roles_requested'] = []
    if not sub.get('cast_role'): sub['cast_role'] = ''
    resp = jsonify(sub)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/api/auditions/submissions/<sid>/cast-role', methods=['PUT'])
def update_submission_cast_role(sid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE audition_submissions SET cast_role=%s, status=%s, updated_at=NOW() WHERE id=%s',
        (d.get('cast_role','').strip() or None, 'cast', sid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/settings/<context_type>/<context_id>/publish-cast', methods=['POST'])
def publish_cast_list(context_type, context_id):
    err = require_auth()
    if err: return err
    d = request.json or {}
    publish = bool(d.get('publish', True))
    conn = get_db()
    if publish:
        # Build cast list from all 'cast' submissions that have a cast_role
        cast = fetchall(conn, """SELECT submitter_name, cast_role, submitter_email
            FROM audition_submissions
            WHERE context_type=%s AND context_id=%s AND status='cast'
            ORDER BY cast_role, submitter_name""", (context_type, context_id))
        cast_json = json.dumps([dict(c) for c in cast])
        execute(conn, """UPDATE audition_settings
            SET cast_list_published=TRUE, cast_list=%s, updated_at=NOW()
            WHERE context_type=%s AND context_id=%s""",
            (cast_json, context_type, context_id))
    else:
        execute(conn, """UPDATE audition_settings
            SET cast_list_published=FALSE, updated_at=NOW()
            WHERE context_type=%s AND context_id=%s""",
            (context_type, context_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/cast-list/<context_type>/<context_id>', methods=['GET'])
def get_cast_list(context_type, context_id):
    """Public endpoint - returns cast list if published."""
    conn = get_db()
    row = fetchone(conn, """SELECT cast_list, cast_list_published, title
        FROM audition_settings WHERE context_type=%s AND context_id=%s""",
        (context_type, context_id))
    if not row or not row.get('cast_list_published'):
        conn.close()
        resp = jsonify({'published': False, 'cast': []})
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    # Get the actual production/program name
    ctx_name = ''
    if context_type == 'production':
        p = fetchone(conn, 'SELECT name FROM productions WHERE id=%s', (context_id,))
        if p: ctx_name = p['name']
    elif context_type == 'program':
        p = fetchone(conn, 'SELECT name FROM youth_programs WHERE id=%s', (context_id,))
        if p: ctx_name = p['name']
    conn.close()
    try:
        cast = json.loads(row.get('cast_list') or '[]')
    except Exception:
        cast = []
    title = row.get('title') or ctx_name
    resp = jsonify({'published': True, 'cast': cast, 'title': title, 'context_name': ctx_name})
    resp.headers['Cache-Control'] = 'no-store'
    return resp



# ─────────────────────────────────────────────────────────────
#  DIRECTOR INTEREST
# ─────────────────────────────────────────────────────────────

@app.route('/director-interest')
def director_interest_page():
    return send_from_directory('static', 'director-interest.html')


@app.route('/api/director-interest/submit', methods=['POST'])
def submit_director_interest():
    d = request.json or {}
    name  = (d.get('name') or '').strip()
    email = (d.get('email') or '').strip().lower()
    if not name or not email:
        return jsonify({'error': 'Name and email are required'}), 400
    conn = get_db()
    # Check for existing submission
    existing = fetchone(conn, 'SELECT id FROM director_interest_submissions WHERE email=%s', (email,))
    if existing:
        conn.close()
        return jsonify({'already_submitted': True})
    # Link to volunteer if exists
    vol = fetchone(conn, 'SELECT id FROM volunteers WHERE LOWER(email)=%s', (email,))
    vol_id = vol['id'] if vol else None
    sid = str(uuid.uuid4())
    execute(conn, """INSERT INTO director_interest_submissions
        (id, volunteer_id, name, email, phone, hwtc_experience, previous_experience,
         years_experience, experience_areas, shows_refuse, role_description,
         most_rewarding, challenges, three_qualities, budget_management, dream_shows)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
        sid, vol_id, name, email,
        (d.get('phone') or '').strip() or None,
        (d.get('hwtc_experience') or '').strip() or None,
        (d.get('previous_experience') or '').strip() or None,
        (d.get('years_experience') or '').strip() or None,
        json.dumps(d.get('experience_areas') or []),
        (d.get('shows_refuse') or '').strip() or None,
        (d.get('role_description') or '').strip() or None,
        (d.get('most_rewarding') or '').strip() or None,
        (d.get('challenges') or '').strip() or None,
        (d.get('three_qualities') or '').strip() or None,
        (d.get('budget_management') or '').strip() or None,
        (d.get('dream_shows') or '').strip() or None,
    ))
    conn.commit()
    # Notify admin
    try:
        s = get_email_settings()
        recipients = list(get_recipient_emails(s))
        if not recipients:
            admins = fetchall(conn, "SELECT email FROM users WHERE role='admin' AND email IS NOT NULL AND email!='' AND active=TRUE")
            recipients = [u['email'] for u in admins if u.get('email')]
        if not recipients:
            # Final fallback
            admins = fetchall(conn, "SELECT email FROM users WHERE role='admin' AND email IS NOT NULL AND email!=''")
            recipients = [u['email'] for u in admins if u.get('email')]
        app.logger.info(f'Director interest notification to: {recipients}')
        if recipients:
            areas = ', '.join(d.get('experience_areas') or []) or 'Not specified'
            html = (
                '<div style="font-family:-apple-system,sans-serif;max-width:600px">'
                '<h2 style="color:#145466">New Director Interest Submission</h2>'
                '<table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">'
                f'<tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466;width:180px">Name</td><td style="padding:8px 12px">{name}</td></tr>'
                f'<tr><td style="padding:8px 12px;font-weight:700;color:#145466">Email</td><td style="padding:8px 12px">{email}</td></tr>'
                f'<tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466">Years Experience</td><td style="padding:8px 12px">{d.get("years_experience") or "Not specified"}</td></tr>'
                f'<tr><td style="padding:8px 12px;font-weight:700;color:#145466">Experience Areas</td><td style="padding:8px 12px">{areas}</td></tr>'
                f'<tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466">Dream Shows</td><td style="padding:8px 12px">{(d.get("dream_shows") or "Not specified")[:200]}</td></tr>'
                '</table>'
                '<p style="color:#9ca3af;font-size:12px">View full response in RoleCall under Directors.</p>'
                '</div>'
            )
            send_email(recipients, 'Director Interest: ' + name, html)
    except Exception as e:
        app.logger.error(f'Director interest notify failed: {e}')
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/director-interest/submissions', methods=['GET'])
def get_director_submissions():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, """SELECT d.*, v.name as volunteer_name, v.id as matched_volunteer_id
        FROM director_interest_submissions d
        LEFT JOIN volunteers v ON LOWER(v.email)=d.email
        ORDER BY d.submitted_at DESC""")
    conn.close()
    for r in rows:
        try: r['experience_areas'] = json.loads(r.get('experience_areas') or '[]')
        except Exception: r['experience_areas'] = []
    return jsonify(rows)


@app.route('/api/director-interest/submissions/<sid>', methods=['PUT'])
def update_director_submission(sid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    # If full=true, update all response fields too
    if d.get('full'):
        execute(conn, """UPDATE director_interest_submissions
            SET status=%s, admin_notes=%s,
                hwtc_experience=%s, previous_experience=%s, years_experience=%s,
                experience_areas=%s, shows_refuse=%s, role_description=%s,
                most_rewarding=%s, challenges=%s, three_qualities=%s,
                budget_management=%s, dream_shows=%s,
                name=%s, phone=%s,
                updated_at=NOW()
            WHERE id=%s""",
            (d.get('status','new'), d.get('admin_notes','') or '',
             d.get('hwtc_experience') or None, d.get('previous_experience') or None,
             d.get('years_experience') or None,
             json.dumps(d.get('experience_areas') or []),
             d.get('shows_refuse') or None, d.get('role_description') or None,
             d.get('most_rewarding') or None, d.get('challenges') or None,
             d.get('three_qualities') or None, d.get('budget_management') or None,
             d.get('dream_shows') or None,
             d.get('name',''), d.get('phone','') or None,
             sid))
    else:
        execute(conn, """UPDATE director_interest_submissions
            SET status=%s, admin_notes=%s, updated_at=NOW() WHERE id=%s""",
            (d.get('status', 'new'), d.get('admin_notes', '') or '', sid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/director-interest/import', methods=['POST'])
def import_director_submissions():
    """One-time import of existing director interest data."""
    err = require_auth()
    if err: return err
    d = request.json or {}
    submissions = d.get('submissions', [])
    conn = get_db()
    imported = 0
    skipped = 0
    for s in submissions:
        email = (s.get('email') or '').strip().lower()
        if not email: continue
        existing = fetchone(conn, 'SELECT id FROM director_interest_submissions WHERE email=%s', (email,))
        if existing: skipped += 1; continue
        vol = fetchone(conn, 'SELECT id FROM volunteers WHERE LOWER(email)=%s', (email,))
        vol_id = vol['id'] if vol else None
        sid = str(uuid.uuid4())
        execute(conn, """INSERT INTO director_interest_submissions
            (id, volunteer_id, name, email, phone, hwtc_experience, previous_experience,
             years_experience, experience_areas, shows_refuse, role_description,
             most_rewarding, challenges, three_qualities, budget_management, dream_shows,
             admin_notes, status, imported)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)""", (
            sid, vol_id,
            (s.get('name') or '').strip(),
            email,
            (s.get('phone') or '').strip() or None,
            s.get('hwtc_experience') or None,
            s.get('previous_experience') or None,
            s.get('years_experience') or None,
            json.dumps(s.get('experience_areas') or []),
            s.get('shows_refuse') or None,
            s.get('role_description') or None,
            s.get('most_rewarding') or None,
            s.get('challenges') or None,
            s.get('three_qualities') or None,
            s.get('budget_management') or None,
            s.get('dream_shows') or None,
            s.get('admin_notes') or None,
            s.get('status') or 'new',
        ))
        imported += 1
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'imported': imported, 'skipped': skipped})



@app.route('/api/director-interest/pending-volunteers', methods=['GET'])
def get_pending_director_volunteers():
    """Volunteers with Director interest who have not submitted the director form."""
    err = require_auth()
    if err: return err
    conn = get_db()
    # Get all emails that have submitted the director form
    submitted = fetchall(conn, 'SELECT LOWER(email) as email FROM director_interest_submissions')
    submitted_emails = {r['email'] for r in submitted}
    # Get volunteers with Director in their interests
    vols = fetchall(conn, """SELECT id, name, email, phone, interests, created_at
        FROM volunteers WHERE status='active' AND interests IS NOT NULL AND interests != '[]'
        ORDER BY name""")
    pending = []
    for v in vols:
        try:
            interests = json.loads(v.get('interests') or '[]')
        except Exception:
            interests = []
        has_director = any('director' in str(i).lower() for i in interests)
        if has_director and v.get('email','').lower() not in submitted_emails:
            v['interests_parsed'] = interests
            pending.append(v)
    conn.close()
    return jsonify(pending)



@app.route('/api/director-interest/send-form-email', methods=['POST'])
def send_director_form_email():
    err = require_auth()
    if err: return err
    d = request.json or {}
    name  = (d.get('name') or '').strip()
    email = (d.get('email') or '').strip()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    form_url = f'https://rolecall.hwtco.org/director-interest?email={email}&name={name}'
    html = (
        '<div style="font-family:-apple-system,sans-serif;max-width:600px">'
        '<h2 style="color:#145466">Thank you for your interest in directing with HWTC</h2>'
        f'<p>Hi {name},</p>'
        '<p>Thank you for your volunteer interest and indicating that you would like to direct with Horizon West Theatre Company. We are excited to learn more about you!</p>'
        '<p>Because directing is a significant responsibility, we would love to know more about your specific directing intentions, experience, and vision. Please take a few minutes to complete our Director Interest Form:</p>'
        f'<p style="margin:24px 0"><a href="{form_url}" style="background:#145466;color:#fff;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">Complete Director Interest Form</a></p>'
        '<p style="color:#6b7280;font-size:13px">This form helps us understand your goals and find the right fit for you and our productions. It should take about 10 minutes to complete.</p>'
        '<p style="color:#6b7280;font-size:13px">If you have any questions, please reach out at info@hwtco.org.</p>'
        '<p style="color:#9ca3af;font-size:12px;margin-top:24px">Horizon West Theatre Company</p>'
        '</div>'
    )
    ok, msg = send_email([email], 'HWTC Director Interest Form', html)
    if not ok:
        return jsonify({'error': msg or 'Failed to send email'}), 500
    return jsonify({'ok': True})



@app.route('/api/youth-programs/<pid>/roster-export', methods=['GET'])
def export_program_roster(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    prog = fetchone(conn, 'SELECT name FROM youth_programs WHERE id=%s', (pid,))
    prog_name = prog['name'] if prog else 'Program'
    rows = fetchall(conn, '''SELECT
        y.first_name, y.last_name, y.dob, y.shirt_size,
        ype.enrolled_date, ype.notes as enrollment_notes,
        f.name as family_name, f.passphrase,
        y.portal_last_login,
        g.first_name as g1_first, g.last_name as g1_last,
        g.email as g1_email, g.phone as g1_phone, g.relationship as g1_rel,
        g2.first_name as g2_first, g2.last_name as g2_last,
        g2.email as g2_email, g2.phone as g2_phone, g2.relationship as g2_rel
        FROM youth_program_enrollments ype
        JOIN youth_participants y ON ype.youth_id=y.id
        LEFT JOIN youth_family_links yfl ON yfl.youth_id=y.id
        LEFT JOIN families f ON f.id=yfl.family_id
        LEFT JOIN youth_guardians g ON g.youth_id=y.id AND g.is_primary=TRUE
        LEFT JOIN youth_guardians g2 ON g2.youth_id=y.id AND g2.is_primary=FALSE
        WHERE ype.program_id=%s
        ORDER BY y.last_name, y.first_name''', (pid,))
    conn.close()
    import io, csv
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow([
        'Last Name','First Name','Date of Birth','Age','T-Shirt Size',
        'Enrolled Date','Portal Passphrase','Last Portal Login',
        'Family Name',
        'Guardian 1 Name','Guardian 1 Relationship','Guardian 1 Email','Guardian 1 Phone',
        'Guardian 2 Name','Guardian 2 Relationship','Guardian 2 Email','Guardian 2 Phone',
        'Enrollment Notes'
    ])
    from datetime import date as _date
    today = _date.today()
    for r in rows:
        dob = r.get('dob','')
        age = ''
        if dob:
            try:
                bd = _date.fromisoformat(dob)
                age = str(today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day)))
            except Exception: pass
        last_login = ''
        if r.get('portal_last_login'):
            try: last_login = str(r['portal_last_login'])[:16]
            except Exception: pass
        g1_name = f"{r.get('g1_first','')} {r.get('g1_last','')}".strip()
        g2_name = f"{r.get('g2_first','')} {r.get('g2_last','')}".strip()
        w.writerow([
            r.get('last_name',''), r.get('first_name',''), dob, age,
            r.get('shirt_size','') or '',
            r.get('enrolled_date','') or '',
            r.get('passphrase','') or '',
            last_login,
            r.get('family_name','') or '',
            g1_name, r.get('g1_rel','') or '', r.get('g1_email','') or '', r.get('g1_phone','') or '',
            g2_name, r.get('g2_rel','') or '', r.get('g2_email','') or '', r.get('g2_phone','') or '',
            r.get('enrollment_notes','') or '',
        ])
    csv_data = output.getvalue()
    safe_name = prog_name.replace(' ','_')
    from flask import Response
    return Response(csv_data, mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=roster_{safe_name}.csv'})



# ─────────────────────────────────────────────────────────────
#  VOLUNTEER GROUPS
# ─────────────────────────────────────────────────────────────

@app.route('/api/volunteer-groups', methods=['GET'])
def get_volunteer_groups():
    err = require_auth()
    if err: return err
    conn = get_db()
    groups = fetchall(conn, '''SELECT g.*, COUNT(m.volunteer_id) as member_count
        FROM volunteer_groups g
        LEFT JOIN volunteer_group_members m ON m.group_id=g.id
        GROUP BY g.id ORDER BY g.name''')
    conn.close()
    return jsonify(groups)


@app.route('/api/volunteer-groups', methods=['POST'])
def create_volunteer_group():
    err = require_auth()
    if err: return err
    d = request.json or {}
    name = (d.get('name') or '').strip()
    if not name: return jsonify({'error': 'Name required'}), 400
    gid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO volunteer_groups (id, name, description)
            VALUES (%s, %s, %s)''', (gid, name, d.get('description','').strip() or None))
        # Add initial members if provided
        for vid in (d.get('member_ids') or []):
            try:
                execute(conn, 'INSERT INTO volunteer_group_members (group_id, volunteer_id) VALUES (%s,%s)',
                    (gid, vid))
            except Exception: pass
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 400
    row = fetchone(conn, 'SELECT * FROM volunteer_groups WHERE id=%s', (gid,))
    conn.close()
    return jsonify(row)


@app.route('/api/volunteer-groups/<gid>', methods=['PUT'])
def update_volunteer_group(gid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE volunteer_groups SET name=%s, description=%s, updated_at=NOW()
        WHERE id=%s''', (d.get('name','').strip(), d.get('description','').strip() or None, gid))
    # Replace members if provided
    if 'member_ids' in d:
        execute(conn, 'DELETE FROM volunteer_group_members WHERE group_id=%s', (gid,))
        for vid in (d.get('member_ids') or []):
            try:
                execute(conn, 'INSERT INTO volunteer_group_members (group_id, volunteer_id) VALUES (%s,%s)',
                    (gid, vid))
            except Exception: pass
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/volunteer-groups/<gid>', methods=['DELETE'])
def delete_volunteer_group(gid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM volunteer_groups WHERE id=%s', (gid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/volunteer-groups/<gid>/members', methods=['GET'])
def get_group_members(gid):
    err = require_auth()
    if err: return err
    conn = get_db()
    members = fetchall(conn, '''SELECT v.id, v.name, v.email, v.status
        FROM volunteer_group_members m
        JOIN volunteers v ON v.id=m.volunteer_id
        WHERE m.group_id=%s ORDER BY v.name''', (gid,))
    conn.close()
    return jsonify(members)



@app.route('/api/square/catalog-items', methods=['GET'])
def get_square_catalog_items():
    """List Square catalog items for linking to programs."""
    err = require_auth()
    if err: return err
    if not SQUARE_ACCESS_TOKEN:
        return jsonify({'error': 'Square not configured'}), 400
    try:
        r = requests.get(
            f'{SQUARE_API_BASE}/v2/catalog/list?types=ITEM',
            headers=square_headers(), timeout=10)
        data = r.json()
        if r.status_code != 200:
            return jsonify({'error': data.get('errors', [{}])[0].get('detail','Square error')}), 400
        items = []
        for obj in (data.get('objects') or []):
            item_data = obj.get('item_data', {})
            # Get the first variation's price
            variations = item_data.get('variations', [])
            price = None
            variation_id = None
            if variations:
                v = variations[0]
                variation_id = v.get('id')
                price_money = v.get('item_variation_data', {}).get('price_money', {})
                price = price_money.get('amount')
            items.append({
                'id': obj.get('id'),
                'variation_id': variation_id,
                'name': item_data.get('name',''),
                'description': item_data.get('description',''),
                'price': price,
            })
        items.sort(key=lambda x: x['name'])
        return jsonify(items)
    except Exception as e:
        app.logger.error(f'Square catalog error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/square/catalog-items', methods=['POST'])
def create_square_catalog_item():
    """Create a new Square catalog item for a program."""
    err = require_auth()
    if err: return err
    d = request.json or {}
    name = (d.get('name') or '').strip()
    price_cents = int(d.get('price_cents') or 0)
    description = (d.get('description') or '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    import uuid as _uuid
    item_id = '#item_' + str(_uuid.uuid4()).replace('-','')[:16]
    var_id  = '#var_'  + str(_uuid.uuid4()).replace('-','')[:16]
    payload = {
        'idempotency_key': str(_uuid.uuid4()),
        'object': {
            'type': 'ITEM',
            'id': item_id,
            'item_data': {
                'name': name,
                'description': description or None,
                'variations': [{
                    'type': 'ITEM_VARIATION',
                    'id': var_id,
                    'item_variation_data': {
                        'name': 'Regular',
                        'pricing_type': 'FIXED_PRICING' if price_cents else 'VARIABLE_PRICING',
                        'price_money': {'amount': price_cents, 'currency': 'USD'} if price_cents else None,
                    }
                }]
            }
        }
    }
    try:
        r = requests.post(f'{SQUARE_API_BASE}/v2/catalog/object',
            json=payload, headers=square_headers(), timeout=10)
        data = r.json()
        if r.status_code != 200:
            return jsonify({'error': data.get('errors',[{}])[0].get('detail','Square error')}), 400
        obj = data.get('catalog_object', {})
        var = (obj.get('item_data',{}).get('variations') or [{}])[0]
        return jsonify({'id': obj.get('id'), 'variation_id': var.get('id'), 'name': name, 'price': price_cents})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/programs/<pid>/link-catalog-item', methods=['POST'])
def link_catalog_item(pid):
    """Link a Square catalog item (variation ID) to a program."""
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_programs SET square_catalog_item_id=%s WHERE id=%s',
        (d.get('catalog_item_id') or None, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



@app.route('/api/programs/<pid>/registration-settings', methods=['PUT'])
def save_registration_settings(pid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    import json as _json
    conn = get_db()
    images = d.get('program_images') or []
    custom_fields = d.get('custom_fields') or []
    execute(conn, '''UPDATE youth_programs SET
        registration_status=%s,
        registration_form_type=%s,
        slug=%s,
        capacity=%s,
        price=%s,
        deposit_amount=%s,
        sibling_discount_enabled=%s,
        sibling_discount_type=%s,
        sibling_discount_value=%s,
        registration_open_date=%s,
        registration_close_date=%s,
        waitlist_auto_charge=%s,
        program_info=%s,
        program_images=%s,
        custom_fields=%s,
        square_catalog_item_id=%s
        WHERE id=%s''',
        (d.get('registration_status') or 'draft',
         d.get('registration_form_type') or 'youth',
         (d.get('slug') or '').strip().lower().replace(' ', '-') or None,
         d.get('capacity') or None,
         int(d.get('price_cents') or 0),
         int(d.get('deposit_amount') or 0),
         bool(d.get('sibling_discount_enabled')),
         d.get('sibling_discount_type') or 'percent',
         int(d.get('sibling_discount_value') or 0),
         d.get('registration_open_date') or None,
         d.get('registration_close_date') or None,
         bool(d.get('waitlist_auto_charge', True)),
         (d.get('program_info') or '').strip(),
         _json.dumps(images),
         _json.dumps(custom_fields),
         d.get('square_catalog_item_id') or None,
         pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── Also need these columns on youth_programs if not already there ──
# (handled in migrations above via ALTER TABLE ... ADD COLUMN IF NOT EXISTS)


# ═══════════════════════════════════════════════════════════════
#  PUBLIC REGISTRATION ROUTES
# ═══════════════════════════════════════════════════════════════

@app.route('/register/<slug>')
@app.route('/register/<slug>/<path:rest>')
def register_page(slug, rest=None):
    return send_from_directory('static', 'register.html')


@app.route('/api/public/program/<slug>')
def public_program_info(slug):
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    reg_count = (fetchone(conn, 'SELECT COUNT(*) AS c FROM program_registrations WHERE program_id=%s AND status NOT IN (\'waitlisted\',\'cancelled\')', (prog['id'],)) or {}).get('c', 0)
    spots_remaining = None
    if prog.get('capacity'):
        spots_remaining = max(0, prog['capacity'] - reg_count)
    # Instructor info
    instr_name = None
    instr_bio = None
    instr_photo = None
    if prog.get('instructor_id'):
        instr = fetchone(conn, 'SELECT name, bio, photo_url FROM volunteers WHERE id=%s', (prog['instructor_id'],))
        if instr:
            instr_name = instr['name']
            instr_bio = instr.get('bio')
            instr_photo = instr.get('photo_url')
    conn.close()
    import json as _json
    images = []
    try:
        images = _json.loads(prog.get('program_images') or '[]')
    except Exception:
        pass
    custom_fields = []
    try:
        custom_fields = _json.loads(prog.get('custom_fields') or '[]')
    except Exception:
        pass
    return jsonify({
        'id': prog['id'],
        'name': prog['name'],
        'description': prog.get('description') or '',
        'slug': prog.get('slug') or '',
        'registration_status': prog.get('registration_status') or 'draft',
        'registration_form_type': prog.get('registration_form_type') or 'youth',
        'capacity': prog.get('capacity'),
        'registration_count': reg_count,
        'spots_remaining': spots_remaining,
        'price': prog.get('price') or 0,
        'deposit_amount': prog.get('deposit_amount') or 0,
        'start_date': prog.get('start_date'),
        'end_date': prog.get('end_date'),
        'program_info': prog.get('program_info') or '',
        'program_images': images,
        'custom_fields': custom_fields,
        'instructor_name': instr_name,
        'instructor_bio': instr_bio,
        'instructor_photo': instr_photo,
        'sibling_discount_enabled': bool(prog.get('sibling_discount_enabled')),
        'sibling_discount_type': prog.get('sibling_discount_type') or 'percent',
        'sibling_discount_value': prog.get('sibling_discount_value') or 0,
    })


@app.route('/api/public/program/<slug>/registration/<rid>')
def public_registration_status(slug, rid):
    conn = get_db()
    prog = fetchone(conn, 'SELECT id FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    reg = fetchone(conn, 'SELECT id, status, child_first_name, child_last_name, guardian_email FROM program_registrations WHERE id=%s AND program_id=%s', (rid, prog['id']))
    conn.close()
    if not reg:
        return jsonify({'error': 'Registration not found'}), 404
    return jsonify(dict(reg))


@app.route('/api/public/program/<slug>/register', methods=['POST'])
def public_register(slug):
    import json as _json, uuid as _uuid
    d = request.json or {}
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404

    reg_type = d.get('type', 'registration')

    # ── Interest list ──────────────────────────────────────────
    if reg_type == 'interest':
        name = (d.get('name') or '').strip()
        email = (d.get('email') or '').strip().lower()
        if not name or not email:
            conn.close()
            return jsonify({'error': 'Name and email required'}), 400
        existing = fetchone(conn, 'SELECT id FROM interest_list_entries WHERE program_id=%s AND email=%s', (prog['id'], email))
        if existing:
            conn.close()
            return jsonify({'ok': True, 'message': 'Already on interest list'})
        execute(conn, 'INSERT INTO interest_list_entries (id,program_id,name,email,phone,child_name,child_age) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (str(_uuid.uuid4()), prog['id'], name, email,
             (d.get('phone') or '').strip(),
             (d.get('child_name') or '').strip(),
             (d.get('child_age') or '').strip()))
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'type': 'interest'})

    # ── Waitlist ───────────────────────────────────────────────
    if reg_type == 'waitlist':
        guardian_email = (d.get('guardian_email') or '').strip().lower()
        if not guardian_email:
            conn.close()
            return jsonify({'error': 'Email required'}), 400
        pos_row = fetchone(conn, 'SELECT COALESCE(MAX(waitlist_position),0)+1 AS pos FROM program_registrations WHERE program_id=%s AND registration_type=\'waitlist\'', (prog['id'],))
        position = (pos_row or {}).get('pos', 1)
        rid = str(_uuid.uuid4())
        execute(conn, '''INSERT INTO program_registrations
            (id, program_id, registration_type, status, child_first_name, child_last_name,
             guardian_name, guardian_email, guardian_phone, notes, waitlist_position)
            VALUES (%s,%s,\'waitlist\',\'waitlisted\',%s,%s,%s,%s,%s,%s,%s)''',
            (rid, prog['id'],
             (d.get('child_first_name') or '').strip(),
             (d.get('child_last_name') or '').strip(),
             (d.get('guardian_name') or '').strip(),
             guardian_email,
             (d.get('guardian_phone') or '').strip(),
             (d.get('notes') or '').strip(),
             position))
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'type': 'waitlisted', 'position': position})

    # ── Full Registration ──────────────────────────────────────
    guardian_email = (d.get('guardian_email') or '').strip().lower()
    child_first = (d.get('child_first_name') or '').strip()
    if not guardian_email:
        conn.close()
        return jsonify({'error': 'Email required'}), 400

    # Check capacity again
    reg_count = (fetchone(conn, 'SELECT COUNT(*) AS c FROM program_registrations WHERE program_id=%s AND status NOT IN (\'waitlisted\',\'cancelled\')', (prog['id'],)) or {}).get('c', 0)
    if prog.get('capacity') and reg_count >= prog['capacity']:
        conn.close()
        return jsonify({'error': 'Program is now full. Please refresh and join the waitlist.'})

    # Discount / pricing ────────────────────────────────────────
    price = prog.get('price') or 0
    siblings = d.get('siblings') or []
    if not isinstance(siblings, list):
        siblings = []
    participant_count = 1 + len(siblings)
    basket = price * participant_count

    # Promo code
    discount_code_used = (d.get('discount_code') or '').strip().upper()
    discount_amount = 0
    sibling_discount_amount = 0
    square_discount_id = None
    if discount_code_used and price > 0:
        dc = fetchone(conn, 'SELECT * FROM discount_codes WHERE program_id=%s AND code=%s AND active=TRUE', (prog['id'], discount_code_used))
        if dc:
            if not (dc.get('max_uses') and (dc.get('uses') or 0) >= dc['max_uses']):
                min_spend = dc.get('min_spend') or 0
                if not (min_spend > 0 and basket < min_spend):
                    is_sib = bool(dc.get('is_sibling_discount'))
                    if is_sib and participant_count >= 2:
                        disc_per = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
                        discount_amount = disc_per * (participant_count - 1)
                    elif not is_sib:
                        discount_amount = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
                    square_discount_id = dc.get('square_discount_id')
                    # Increment uses
                    execute(conn, 'UPDATE discount_codes SET uses=COALESCE(uses,0)+1 WHERE id=%s', (dc['id'],))

    # Program-level sibling discount (auto, no code needed)
    if prog.get('sibling_discount_enabled') and participant_count >= 2 and price > 0:
        sib_type = prog.get('sibling_discount_type') or 'percent'
        sib_val = prog.get('sibling_discount_value') or 0
        if sib_type == 'percent':
            per_sib = int(price * sib_val / 100)
        else:
            per_sib = min(sib_val, price)
        sibling_discount_amount = per_sib * (participant_count - 1)

    total_discount = discount_amount + sibling_discount_amount
    final_price = max(0, basket - total_discount)

    # Payment type
    payment_type = d.get('payment_type') or 'full'
    deposit = prog.get('deposit_amount') or 0
    use_deposit = (payment_type == 'deposit' and deposit > 0 and deposit < final_price)
    amount_due_now = deposit if use_deposit else final_price
    balance_due = final_price - deposit if use_deposit else 0

    rid = str(_uuid.uuid4())
    custom_field_values = d.get('custom_field_values') or {}
    execute(conn, '''INSERT INTO program_registrations
        (id, program_id, registration_type, status,
         child_first_name, child_last_name, child_dob, shirt_size,
         guardian_name, guardian_email, guardian_phone,
         emergency_contact_name, emergency_contact_phone,
         notes, discount_code, discount_amount, sibling_discount_amount,
         payment_type, balance_due, participant_count,
         custom_field_values, siblings_data, amount_paid)
        VALUES (%s,%s,\'registration\',%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s)''',
        (rid, prog['id'],
         'pending_payment' if (price > 0 and amount_due_now > 0) else 'confirmed',
         child_first,
         (d.get('child_last_name') or '').strip(),
         (d.get('child_dob') or '').strip(),
         (d.get('shirt_size') or '').strip(),
         (d.get('guardian_name') or '').strip(),
         guardian_email,
         (d.get('guardian_phone') or '').strip(),
         (d.get('emergency_contact_name') or '').strip(),
         (d.get('emergency_contact_phone') or '').strip(),
         (d.get('notes') or '').strip(),
         discount_code_used or None,
         discount_amount,
         sibling_discount_amount,
         payment_type,
         balance_due,
         participant_count,
         _json.dumps(custom_field_values),
         _json.dumps(siblings),
         0))
    conn.commit()

    if price == 0 or amount_due_now == 0:
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed', 'registration_id': rid})

    # Create Square payment link
    try:
        pay_url, link_id, order_id = square_create_payment_link(
            prog, amount_due_now, rid, guardian_email,
            participant_count=participant_count,
            discount_amount=total_discount,
            square_discount_id=square_discount_id,
            use_deposit=use_deposit)
        execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s',
            (link_id, order_id, rid))
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'type': 'payment_required', 'payment_url': pay_url,
                        'registration_id': rid, 'use_deposit': use_deposit})
    except Exception as e:
        app.logger.error(f'Square payment link error during registration: {e}')
        conn.close()
        return jsonify({'error': f'Registration saved but payment link failed: {str(e)}'}), 500


def square_create_payment_link(prog, amount_cents, reg_id, email,
                                participant_count=1, discount_amount=0,
                                square_discount_id=None, use_deposit=False):
    import uuid as _uuid
    if not SQUARE_ACCESS_TOKEN:
        raise Exception('Square not configured')
    name = prog.get('name', 'Program Registration')
    if participant_count > 1:
        name += f' ({participant_count} participants)'
    if use_deposit:
        name += ' — Deposit'
    payload = {
        'idempotency_key': str(_uuid.uuid4()),
        'quick_pay': {
            'name': name,
            'price_money': {'amount': amount_cents, 'currency': 'USD'},
            'location_id': SQUARE_LOCATION_ID,
        },
        'checkout_options': {
            'redirect_url': f'https://rolecall.hwtco.org/register/{prog.get("slug","")}/confirmation?reg={reg_id}',
            'ask_for_shipping_address': False,
        },
        'pre_populated_data': {
            'buyer_email': email,
        },
    }
    r = requests.post(f'{SQUARE_API_BASE}/v2/online-checkout/payment-links',
        json=payload, headers=square_headers(), timeout=15)
    data = r.json()
    if r.status_code not in (200, 201):
        errs = data.get('errors') or [{}]
        raise Exception(errs[0].get('detail', 'Square error'))
    link = data.get('payment_link', {})
    return link.get('url'), link.get('id'), link.get('order_id')


# ═══════════════════════════════════════════════════════════════
#  DISCOUNT CODES
# ═══════════════════════════════════════════════════════════════

def square_create_discount(name, discount_type, value):
    import uuid as _u
    disc_id = '#disc_' + _u.uuid4().hex[:16]
    payload = {
        'idempotency_key': str(_u.uuid4()),
        'object': {
            'type': 'DISCOUNT',
            'id': disc_id,
            'discount_data': {
                'name': name,
                'discount_type': 'FIXED_AMOUNT' if discount_type == 'fixed' else 'FIXED_PERCENTAGE',
            }
        }
    }
    if discount_type == 'fixed':
        payload['object']['discount_data']['amount_money'] = {'amount': value, 'currency': 'USD'}
    else:
        payload['object']['discount_data']['percentage'] = str(value)
    try:
        r = requests.post(f'{SQUARE_API_BASE}/v2/catalog/object',
            json=payload, headers=square_headers(), timeout=10)
        data = r.json()
        if r.status_code == 200:
            return data.get('catalog_object', {}).get('id')
        app.logger.error(f'Square discount error: {data}')
    except Exception as e:
        app.logger.error(f'Square discount exception: {e}')
    return None


@app.route('/api/programs/<pid>/discount-codes', methods=['GET'])
def get_discount_codes(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    codes = fetchall(conn, 'SELECT * FROM discount_codes WHERE program_id=%s ORDER BY created_at DESC', (pid,))
    conn.close()
    return jsonify(codes)


@app.route('/api/programs/<pid>/discount-codes', methods=['POST'])
def create_discount_code(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required'}), 400
    discount_type = d.get('discount_type', 'percent')
    discount_value = int(d.get('discount_value') or 0)
    conn = get_db()
    prog = fetchone(conn, 'SELECT name FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    sq_id = None
    is_sib = bool(d.get('is_sibling_discount') or False)
    if not is_sib:
        sq_id = square_create_discount(f'{prog["name"]} -- {code}', discount_type, discount_value)
    import uuid as _u
    try:
        sql = (
            'INSERT INTO discount_codes'
            ' (id, program_id, code, description, square_discount_id, discount_type,'
            ' discount_value, min_spend, is_sibling_discount, max_uses, expires_at, active)'
            ' VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)'
        )
        params = (
            _u.uuid4().hex, pid, code,
            d.get('description','') or '',
            sq_id, discount_type, discount_value,
            int(d.get('min_spend_cents') or 0),
            is_sib,
            d.get('max_uses') or None,
            d.get('expires_at') or None
        )
        execute(conn, sql, params)
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'square_id': sq_id})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/programs/<pid>/discount-codes/<cid>', methods=['DELETE'])
def delete_discount_code(pid, cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE discount_codes SET active=FALSE WHERE id=%s AND program_id=%s', (cid, pid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/public/program/<slug>/validate-discount', methods=['POST'])
def validate_discount(slug):
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required'}), 400
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    dc = fetchone(conn, 'SELECT * FROM discount_codes WHERE program_id=%s AND code=%s AND active=TRUE', (prog['id'], code))
    if not dc:
        conn.close()
        return jsonify({'valid': False, 'error': 'Invalid or expired code'})
    if dc.get('max_uses') and (dc.get('uses') or 0) >= dc['max_uses']:
        conn.close()
        return jsonify({'valid': False, 'error': 'This code has reached its maximum uses'})
    price = prog.get('price') or 0
    num_regs = int(d.get('num_registrations') or 1)
    basket = int(d.get('basket_cents') or (price * num_regs))
    min_spend = dc.get('min_spend') or 0
    if min_spend > 0 and basket < min_spend:
        conn.close()
        return jsonify({'valid': False, 'error': f'This code requires a minimum purchase of ${min_spend/100:.2f}'})
    is_sib = bool(dc.get('is_sibling_discount'))
    if is_sib:
        if num_regs < 2:
            conn.close()
            return jsonify({'valid': False, 'error': 'Sibling discount requires 2+ participants'})
        disc_per = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
        discount_amount = disc_per * (num_regs - 1)
    else:
        if dc['discount_type'] == 'percent':
            discount_amount = int(price * dc['discount_value'] / 100)
        else:
            discount_amount = min(dc['discount_value'], price)
    final_price = max(0, basket - discount_amount)
    label = f'{dc["discount_value"]}{"%" if dc["discount_type"]=="percent" else " cents"} off'
    if is_sib:
        label = f'Sibling discount: {label} per additional participant'
    if min_spend:
        label += f' (min. ${min_spend/100:.2f})'
    conn.close()
    return jsonify({
        'valid': True, 'discount_amount': discount_amount,
        'final_price': final_price, 'is_sibling': is_sib,
        'square_discount_id': dc.get('square_discount_id'), 'label': label,
    })


@app.route('/api/programs/<pid>/registrations/<rid>/send-payment-link', methods=['POST'])
def send_registration_payment_link(pid, rid):
    """Resend or create a new payment link for a pending_payment registration."""
    err = require_auth()
    if err: return err
    conn = get_db()
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s AND program_id=%s', (rid, pid))
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not reg or not prog:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    # Use existing link if still valid
    existing = reg.get('square_checkout_id') or reg.get('waitlist_payment_link')
    amount = prog.get('price') or 0
    pay_url, link_id, order_id = square_create_payment_link(
        prog, rid, reg['guardian_email'], reg.get('guardian_name',''), amount,
        note=f'{reg.get("child_first_name","")} {reg.get("child_last_name","")} — {prog["name"]}')
    if not pay_url:
        conn.close()
        return jsonify({'error': 'Could not create payment link'}), 500
    execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s',
        (link_id, order_id, rid))
    conn.commit()
    # Email the family
    try:
        send_email([reg['guardian_email']], f'Complete your registration — {prog["name"]}',
            f'<div style="font-family:-apple-system,sans-serif;max-width:560px">'
            f'<h2 style="color:#145466">Complete Your Registration</h2>'
            f'<p>Hi {reg.get("guardian_name","")},</p>'
            f'<p>Your registration for <strong>{prog["name"]}</strong> is not yet complete. '
            f'Click below to complete your payment and secure your spot.</p>'
            f'<p style="margin:24px 0"><a href="{pay_url}" style="background:#145466;color:#fff;'
            f'padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">'
            f'Complete Payment</a></p>'
            f'<p style="color:#6b7280;font-size:13px">Or copy this link: {pay_url}</p>'
            f'<p>Horizon West Theatre Company</p></div>')
    except Exception as e:
        app.logger.warning(f'Payment link email failed: {e}')
    conn.close()
    return jsonify({'ok': True, 'payment_url': pay_url})


@app.route('/api/programs/<pid>/registrations/<rid>/send-balance-link', methods=['POST'])
def send_balance_payment_link(pid, rid):
    """Send a payment link for the remaining balance on a deposit registration."""
    err = require_auth()
    if err: return err
    conn = get_db()
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s AND program_id=%s', (rid, pid))
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not reg or not prog:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    balance = reg.get('balance_due') or 0
    if balance <= 0:
        conn.close()
        return jsonify({'error': 'No balance due'}), 400
    pay_url, link_id, order_id = square_create_payment_link(
        prog, rid + '_balance', reg['guardian_email'], reg.get('guardian_name',''), balance,
        note=f'Balance payment — {reg.get("child_first_name","")} {reg.get("child_last_name","")} — {prog["name"]}')
    if not pay_url:
        conn.close()
        return jsonify({'error': 'Could not create payment link'}), 500
    execute(conn, 'UPDATE program_registrations SET balance_payment_link=%s WHERE id=%s', (pay_url, rid))
    conn.commit()
    try:
        send_email([reg['guardian_email']], f'Balance payment due — {prog["name"]}',
            f'<div style="font-family:-apple-system,sans-serif;max-width:560px">'
            f'<h2 style="color:#145466">Balance Payment Due</h2>'
            f'<p>Hi {reg.get("guardian_name","")},</p>'
            f'<p>Your remaining balance of <strong>${balance/100:.2f}</strong> is due for '
            f'<strong>{prog["name"]}</strong>.</p>'
            f'<p style="margin:24px 0"><a href="{pay_url}" style="background:#145466;color:#fff;'
            f'padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">'
            f'Pay Balance — ${balance/100:.2f}</a></p>'
            f'<p>Horizon West Theatre Company</p></div>')
    except Exception as e:
        app.logger.warning(f'Balance link email failed: {e}')
    conn.close()
    return jsonify({'ok': True, 'payment_url': pay_url})
