# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, session, send_from_directory, send_file
from flask_cors import CORS
import psycopg2
import psycopg2.extras
import hashlib
import hmac
import os
import uuid
import json
from datetime import datetime, date
from werkzeug.utils import secure_filename
import requests
import re
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

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">1</div>
        <p style="margin:0;font-size:14px;color:#374151">Go to the <strong>Team Universal site</strong> and scroll down until you find the <strong>Access myImpact</strong> button on the right side of the screen.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">2</div>
        <p style="margin:0;font-size:14px;color:#374151">Select the <strong>division of the company</strong> you work for.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">3</div>
        <p style="margin:0;font-size:14px;color:#374151">Login using your <strong>SSO</strong>.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">4</div>
        <p style="margin:0;font-size:14px;color:#374151">Click on the <strong>Log Your Hours</strong> page on the top option bar.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">5</div>
        <p style="margin:0;font-size:14px;color:#374151">Click the <strong>Log Individual Hours</strong> button.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">6</div>
        <p style="margin:0;font-size:14px;color:#374151">Enter <strong>Horizon West Theater Company</strong> into the organization name and search for the company &mdash; or if you&rsquo;ve entered hours with this organization before, it should show up under <strong>My Recent Organizations</strong>.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">7</div>
        <p style="margin:0;font-size:14px;color:#374151">Once you have selected Horizon West Theater Company as your organization, enter the <strong>date range</strong> you volunteered and <strong>how many hours</strong>. Click <strong>Save and Proceed</strong> once all information is entered.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">8</div>
        <p style="margin:0;font-size:14px;color:#374151">Review your submission and click <strong>Submit</strong>.</p>
      </div>

      <div style="margin-bottom:16px;display:flex;align-items:flex-start;gap:12px">
        <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0;margin-top:2px">9</div>
        <p style="margin:0;font-size:14px;color:#374151">A <strong>confirmation page</strong> will then appear saying your submission was successful.</p>
      </div>

    </div>

    <div style="background:#f0f8fa;border-radius:10px;padding:20px 24px;margin:24px 0;border-left:4px solid #145466">
      <strong style="color:#145466">Did you know?</strong>
      <p style="margin:8px 0 0;font-size:14px;color:#374151">Once you have completed <strong>52 hours</strong> of volunteering you qualify for <strong>Club 52</strong>. After the completion of <strong>104 hours</strong>, you will reach <strong>Club 52 Elite</strong> status. Club 52 and Club 52 Elite members qualify for the <strong>Universal Orlando Foundation grant</strong> at the end of the calendar year where you can choose a non-profit of your choosing to donate grant money to. <strong>Horizon West Theater Company qualifies</strong> for this event and hopes you will consider donating your grant money to our cause.</p>
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
        # Fix rows where context_type is NULL — assume production since that's the original use
        "UPDATE audition_settings SET context_type='production' WHERE context_type IS NULL",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS roles_requested TEXT DEFAULT '[]'",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS cast_role TEXT",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS submitter_passphrase TEXT",
        """ALTER TABLE audition_settings ADD COLUMN IF NOT EXISTS allow_slots BOOLEAN DEFAULT FALSE""",
        """CREATE TABLE IF NOT EXISTS audition_slots (
            id TEXT PRIMARY KEY,
            context_type TEXT NOT NULL,
            context_id TEXT NOT NULL,
            slot_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            slot_type TEXT DEFAULT 'in_person',
            location TEXT DEFAULT '',
            capacity INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT NOW())""",
        """ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS slot_id TEXT REFERENCES audition_slots(id) ON DELETE SET NULL""",
        """ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS audition_type TEXT DEFAULT 'virtual'""",
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
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS booking_mode BOOLEAN DEFAULT FALSE",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS max_sessions_per_reg INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS rental_spaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            capacity INTEGER,
            amenities TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS rental_partners (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            contact_name TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            organization_type TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS rental_requests (
            id TEXT PRIMARY KEY,
            partner_id TEXT REFERENCES rental_partners(id) ON DELETE SET NULL,
            space_id TEXT REFERENCES rental_spaces(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            purpose TEXT DEFAULT '',
            start_date TEXT NOT NULL,
            end_date TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            recurring BOOLEAN DEFAULT FALSE,
            recurrence_pattern TEXT DEFAULT '',
            recurrence_end_date TEXT DEFAULT '',
            estimated_attendance INTEGER,
            rate_type TEXT DEFAULT 'hourly',
            rate_amount INTEGER DEFAULT 0,
            total_amount INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            notes TEXT DEFAULT '',
            approved_by TEXT DEFAULT '',
            approved_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS rental_agreements (
            id TEXT PRIMARY KEY,
            request_id TEXT REFERENCES rental_requests(id) ON DELETE CASCADE,
            contract_html TEXT DEFAULT '',
            signing_token TEXT UNIQUE,
            partner_signed_name TEXT DEFAULT '',
            partner_signed_at TIMESTAMP,
            partner_signed_ip TEXT DEFAULT '',
            admin_notes TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS rental_occurrences (
            id TEXT PRIMARY KEY,
            request_id TEXT REFERENCES rental_requests(id) ON DELETE CASCADE,
            occurrence_date TEXT NOT NULL,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            status TEXT DEFAULT 'scheduled',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        "ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS deposit_amount INTEGER DEFAULT 0",
        """CREATE TABLE IF NOT EXISTS discount_codes (
            id TEXT PRIMARY KEY,
            program_id TEXT REFERENCES youth_programs(id) ON DELETE CASCADE,
            code TEXT NOT NULL,
            square_discount_id TEXT,
            discount_type TEXT NOT NULL DEFAULT 'percent',
            discount_value INTEGER NOT NULL DEFAULT 0,
            max_uses INTEGER,
            uses INTEGER DEFAULT 0,
            expires_at TEXT,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(program_id, code))""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS discount_code TEXT""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS discount_amount INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS payment_type TEXT DEFAULT 'full'""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS balance_due INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS balance_payment_link TEXT""",
        """ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS min_spend INTEGER DEFAULT 0""",
        """ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS is_sibling_discount BOOLEAN DEFAULT FALSE""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_enabled BOOLEAN DEFAULT FALSE""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_type TEXT DEFAULT 'percent'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sibling_discount_value INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS sibling_discount_amount INTEGER DEFAULT 0""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS participant_count INTEGER DEFAULT 1""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS siblings_json TEXT DEFAULT '[]'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS program_location TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS schedule_type TEXT DEFAULT 'date_range'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS meeting_days TEXT DEFAULT '[]'""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS meeting_start_time TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS meeting_end_time TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS single_date TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS schedule_notes TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS form_fields TEXT DEFAULT '{}'""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS allergies TEXT DEFAULT ''""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS pickup_contacts TEXT DEFAULT ''""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS photo_consent BOOLEAN DEFAULT FALSE""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS pronouns TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS registration_note TEXT DEFAULT ''""",
        """ALTER TABLE productions ADD COLUMN IF NOT EXISTS registration_note TEXT DEFAULT ''""",
        """ALTER TABLE youth_programs ADD COLUMN IF NOT EXISTS sessions_enabled BOOLEAN DEFAULT FALSE""",
        """CREATE TABLE IF NOT EXISTS program_sessions (
            id TEXT PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES youth_programs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            day_of_week TEXT DEFAULT '',
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            start_date TEXT DEFAULT '',
            end_date TEXT DEFAULT '',
            location TEXT DEFAULT '',
            capacity INTEGER,
            price_override INTEGER,
            status TEXT DEFAULT 'open',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW())""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS session_ids TEXT DEFAULT '[]'""",
        """ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS registration_form_type TEXT DEFAULT 'youth'""",
        """CREATE TABLE IF NOT EXISTS pending_donations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            message TEXT,
            square_order_id TEXT,
            square_checkout_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS cart_discount_codes (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            discount_type TEXT NOT NULL DEFAULT 'percent',
            discount_value INTEGER NOT NULL DEFAULT 0,
            min_spend INTEGER DEFAULT 0,
            max_uses INTEGER,
            uses INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT TRUE,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT NOW())""",
        """CREATE TABLE IF NOT EXISTS cart_orders (
            id TEXT PRIMARY KEY,
            guardian_name TEXT NOT NULL,
            guardian_email TEXT NOT NULL,
            guardian_phone TEXT,
            items_json TEXT NOT NULL,
            cart_discount_code TEXT,
            cart_discount_amount INTEGER DEFAULT 0,
            total_cents INTEGER NOT NULL,
            square_order_id TEXT,
            square_checkout_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW())""",
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

        # Rising Stars production registration fields
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS slug TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS stage TEXT DEFAULT 'main'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS registration_status TEXT DEFAULT 'draft'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS registration_form_type TEXT DEFAULT 'youth'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS price INTEGER DEFAULT 0",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS deposit_amount INTEGER DEFAULT 0",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS capacity INTEGER",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS registration_open_date TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS registration_close_date TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS waitlist_auto_charge BOOLEAN DEFAULT TRUE",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS program_info TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS program_images TEXT DEFAULT '[]'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS custom_fields TEXT DEFAULT '[]'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS form_fields TEXT DEFAULT '{}'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS sibling_discount_enabled BOOLEAN DEFAULT FALSE",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS sibling_discount_type TEXT DEFAULT 'percent'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS sibling_discount_value INTEGER DEFAULT 0",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS program_location TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS schedule_type TEXT DEFAULT 'date_range'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS meeting_days TEXT DEFAULT '[]'",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS meeting_start_time TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS meeting_end_time TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS single_date TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS schedule_notes TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS square_catalog_item_id TEXT",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS director TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS venue TEXT DEFAULT ''",
        "ALTER TABLE productions ADD COLUMN IF NOT EXISTS image_url TEXT",

        # Allow program_registrations to link to a production instead of a program
        "ALTER TABLE program_registrations ALTER COLUMN program_id DROP NOT NULL",
        "ALTER TABLE program_registrations ADD COLUMN IF NOT EXISTS production_id TEXT REFERENCES productions(id) ON DELETE CASCADE",

        # Discount codes for productions
        "ALTER TABLE discount_codes ADD COLUMN IF NOT EXISTS production_id TEXT REFERENCES productions(id) ON DELETE CASCADE",
        "ALTER TABLE discount_codes ALTER COLUMN program_id DROP NOT NULL",

        # Interest list for productions
        "ALTER TABLE interest_list_entries ADD COLUMN IF NOT EXISTS production_id TEXT REFERENCES productions(id) ON DELETE CASCADE",
        "ALTER TABLE interest_list_entries ALTER COLUMN program_id DROP NOT NULL",
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
    # Add rental occurrences as synthetic calendar events
    try:
        conn2 = get_db()
        rentals = fetchall(conn2, '''SELECT ro.*, rr.title, rr.start_time AS req_start, rr.end_time AS req_end,
            rp.name AS partner_name, rs.name AS space_name
            FROM rental_occurrences ro
            JOIN rental_requests rr ON rr.id=ro.request_id
            LEFT JOIN rental_partners rp ON rp.id=rr.partner_id
            LEFT JOIN rental_spaces rs ON rs.id=rr.space_id
            WHERE ro.status != \'cancelled\' ''') or []
        conn2.close()
        for r in rentals:
            events.append({
                'id': 'rental_' + r['id'],
                'name': f"{r.get('title','')} \u2013 {r.get('partner_name','')}",
                'event_date': r.get('occurrence_date',''),
                'start_time': r.get('start_time') or r.get('req_start',''),
                'end_time': r.get('end_time') or r.get('req_end',''),
                'event_type_name': 'Venue Rental',
                'event_type_color': '#7c3aed',
                'status': r.get('status','scheduled'),
                'location': r.get('space_name',''),
                'is_rental': True,
                'required_waivers': [], 'elics': [], 'staff': [],
            })
    except Exception as e:
        app.logger.warning(f'Rental calendar merge error: {e}')
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
    programs = fetchall(conn, '''SELECT yp.*, v.name as default_elic_name,
        (SELECT COUNT(*) FROM program_registrations WHERE program_id=yp.id AND status='confirmed') AS reg_confirmed,
        (SELECT COUNT(*) FROM program_registrations WHERE program_id=yp.id AND status='pending_payment') AS reg_pending,
        (SELECT COUNT(*) FROM program_registrations WHERE program_id=yp.id AND status='waitlisted') AS reg_waitlisted,
        (SELECT COUNT(*) FROM program_registrations WHERE program_id=yp.id AND status NOT IN (\'cancelled\',\'waitlisted\')) AS reg_enrolled
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


@app.route('/api/portal/messages/unread-summary')
def portal_unread_summary():
    err = require_auth()
    if err: return err
    conn = get_db()
    total = (fetchone(conn, "SELECT COALESCE(SUM(unread_admin),0) AS t FROM portal_message_threads WHERE unread_admin>0") or {}).get('t', 0)
    by_program = fetchall(conn, """
        SELECT program_id, COALESCE(SUM(unread_admin),0) AS unread
        FROM portal_message_threads
        WHERE unread_admin>0 AND program_id IS NOT NULL
        GROUP BY program_id""")
    conn.close()
    return jsonify({'total': int(total), 'by_program': {r['program_id']: int(r['unread']) for r in (by_program or [])}})


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
    row = fetchone(conn, '''SELECT *, COALESCE(allow_slots, FALSE) AS allow_slots
        FROM audition_settings WHERE context_id=%s AND context_type=%s''',
        (context_id, context_type))
    # Load slots
    slots = fetchall(conn, '''SELECT as2.*,
        (SELECT COUNT(*) FROM audition_submissions WHERE slot_id=as2.id) AS booked_count
        FROM audition_slots as2
        WHERE as2.context_id=%s AND as2.context_type=%s
        ORDER BY as2.slot_date, as2.start_time''', (context_id, context_type)) or []
    conn.close()
    if not row:
        resp = jsonify({'context_type': context_type, 'context_id': context_id,
            'is_open': False, 'roles': [], 'allow_video_link': True,
            'allow_resume_link': True, 'allow_headshot_link': True,
            'allow_slots': False, 'slots': slots})
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    try: row['roles'] = json.loads(row.get('roles') or '[]')
    except Exception: row['roles'] = []
    row['slots'] = slots
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
    allow_slots  = bool(d.get('allow_slots', False))
    if existing:
        execute(conn, """UPDATE audition_settings SET is_open=%s,title=%s,description=%s,
            audition_date=%s,audition_time=%s,location=%s,roles=%s,instructions=%s,
            email_submissions=%s,allow_video_link=%s,allow_resume_link=%s,allow_headshot_link=%s,
            allow_slots=%s, updated_at=NOW() WHERE context_id=%s AND context_type=%s""",
            (is_open,title,desc,aud_date,aud_time,location,roles_json,instructions,
             email_sub,allow_video,allow_resume,allow_head,allow_slots,context_id,context_type))
    else:
        sid = str(uuid.uuid4())
        execute(conn, """INSERT INTO audition_settings
            (id,context_type,context_id,is_open,title,description,audition_date,audition_time,
             location,roles,instructions,email_submissions,allow_video_link,allow_resume_link,allow_headshot_link,allow_slots)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (sid,context_type,context_id,is_open,title,desc,aud_date,aud_time,
             location,roles_json,instructions,email_sub,allow_video,allow_resume,allow_head,allow_slots))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/auditions/list/<context_type>/<context_id>', methods=['GET'])
def get_audition_submissions(context_type, context_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        rows = fetchall(conn, """SELECT s.id, s.context_type, s.context_id, s.family_id,
            s.participant_id, s.submitter_name, s.submitter_email, s.role_requested,
            s.video_url, s.resume_url, s.headshot_url, s.notes, s.status, s.admin_notes,
            s.submitted_at, s.updated_at,
            COALESCE(s.roles_requested, '[]') as roles_requested,
            COALESCE(s.cast_role, '') as cast_role,
            COALESCE(s.audition_type, 'virtual') as audition_type,
            s.slot_id,
            sl.slot_date, sl.start_time, sl.end_time, sl.location as slot_location
            FROM audition_submissions s
            LEFT JOIN audition_slots sl ON sl.id=s.slot_id
            WHERE s.context_type=%s AND s.context_id=%s ORDER BY s.submitted_at DESC""",
            (context_type, context_id))
    except Exception as e:
        app.logger.error(f'get_audition_submissions error: {e}')
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


@app.route('/api/auditions/slots/<context_type>/<context_id>', methods=['GET'])
def get_audition_slots(context_type, context_id):
    conn = get_db()
    slots = fetchall(conn, '''SELECT as2.*,
        (SELECT COUNT(*) FROM audition_submissions WHERE slot_id=as2.id) AS booked_count
        FROM audition_slots as2
        WHERE as2.context_id=%s AND as2.context_type=%s AND as2.status != 'cancelled'
        ORDER BY as2.slot_date, as2.start_time''', (context_id, context_type)) or []
    conn.close()
    return jsonify(slots)


@app.route('/api/auditions/slots/create', methods=['POST'])
def create_audition_slot_v2():
    err = require_auth()
    if err: return err
    import uuid as _uas
    d = request.json or {}
    conn = get_db()
    sid = str(_uas.uuid4())
    execute(conn, '''INSERT INTO audition_slots
        (id, context_type, context_id, slot_date, start_time, end_time,
         slot_type, location, capacity, sort_order, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open')''',
        (sid,
         d.get('context_type', 'program'),
         d.get('context_id', ''),
         (d.get('slot_date') or '').strip(),
         (d.get('start_time') or '').strip(),
         (d.get('end_time') or '').strip(),
         d.get('slot_type', 'in_person'),
         (d.get('location') or '').strip() or None,
         int(d.get('capacity') or 1),
         int(d.get('sort_order') or 0)))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': sid})


@app.route('/api/auditions/slots/generate', methods=['POST'])
def generate_audition_slots():
    err = require_auth()
    if err: return err
    import uuid as _uasg
    import datetime as _dtasg
    d = request.json or {}
    context_type = d.get('context_type', 'program')
    context_id = d.get('context_id', '')
    start_date = d.get('start_date')
    end_date = d.get('end_date') or start_date
    open_time = d.get('open_time', '10:00')
    close_time = d.get('close_time', '17:00')
    slot_duration = int(d.get('slot_duration_minutes') or 15)
    gap_minutes = int(d.get('gap_minutes') or 5)
    capacity = int(d.get('capacity') or 1)
    slot_type = d.get('slot_type', 'in_person')
    location = (d.get('location') or '').strip()
    days_of_week = d.get('days_of_week') or []
    if not start_date or not open_time or not close_time:
        return jsonify({'error': 'start_date, open_time and close_time required'}), 400
    DAY_MAP = {'Monday':0,'Tuesday':1,'Wednesday':2,'Thursday':3,'Friday':4,'Saturday':5,'Sunday':6}
    allowed_days = set(DAY_MAP[d2] for d2 in days_of_week if d2 in DAY_MAP) if days_of_week else set(range(7))
    try:
        cur = _dtasg.date.fromisoformat(start_date)
        end = _dtasg.date.fromisoformat(end_date)
        ot = _dtasg.time.fromisoformat(open_time)
        ct = _dtasg.time.fromisoformat(close_time)
    except Exception as e:
        return jsonify({'error': f'Invalid date/time: {e}'}), 400
    slot_td = _dtasg.timedelta(minutes=slot_duration)
    gap_td = _dtasg.timedelta(minutes=gap_minutes)
    conn = get_db()
    created = 0
    sort_order = 0
    while cur <= end:
        if cur.weekday() in allowed_days:
            slot_start = _dtasg.datetime.combine(cur, ot)
            slot_end_limit = _dtasg.datetime.combine(cur, ct)
            while slot_start + slot_td <= slot_end_limit:
                s_end = slot_start + slot_td
                execute(conn, '''INSERT INTO audition_slots
                    (id, context_type, context_id, slot_date, start_time, end_time,
                     slot_type, location, capacity, sort_order, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open')''',
                    (str(_uasg.uuid4()), context_type, context_id,
                     cur.isoformat(),
                     slot_start.strftime('%H:%M'), s_end.strftime('%H:%M'),
                     slot_type, location or None,
                     capacity, sort_order))
                sort_order += 1
                created += 1
                slot_start = s_end + gap_td
        cur += _dtasg.timedelta(days=1)
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'created': created})


@app.route('/api/auditions/slots/<sid>', methods=['DELETE'])
def delete_audition_slot(sid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM audition_slots WHERE id=%s', (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


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

    # Handle slot booking
    slot_id = d.get('slot_id') or None
    audition_type = d.get('audition_type') or 'virtual'
    if slot_id:
        slot = fetchone(conn, 'SELECT * FROM audition_slots WHERE id=%s AND context_id=%s',
            (slot_id, context_id))
        if not slot:
            conn.close()
            return jsonify({'error': 'Slot not found'}), 400
        if slot.get('status') == 'full':
            conn.close()
            return jsonify({'error': 'This slot is full. Please choose another time.'}), 400
        booked = (fetchone(conn, 'SELECT COUNT(*) AS c FROM audition_submissions WHERE slot_id=%s', (slot_id,)) or {}).get('c', 0)
        if int(booked) >= int(slot.get('capacity') or 1):
            conn.close()
            return jsonify({'error': 'This slot is now full. Please choose another time.'}), 400
        audition_type = 'in_person'

    passphrase  = (d.get('passphrase') or '').strip()
    family      = fetchone(conn, 'SELECT * FROM families WHERE passphrase=%s', (passphrase,)) if passphrase else None
    family_id   = family['id'] if family else None
    sid = str(uuid.uuid4())
    execute(conn, """INSERT INTO audition_submissions
        (id,context_type,context_id,family_id,participant_id,submitter_name,
         submitter_email,role_requested,video_url,resume_url,headshot_url,notes,submitter_passphrase,
         slot_id,audition_type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
        sid, context_type, context_id, family_id,
        d.get('participant_id') or None, name,
        (d.get('submitter_email') or '').strip() or None,
        json.dumps(d.get('roles_requested') or ([d.get('role_requested')] if d.get('role_requested') else [])),
        (d.get('video_url') or '').strip() or None,
        (d.get('resume_url') or '').strip() or None,
        (d.get('headshot_url') or '').strip() or None,
        (d.get('notes') or '').strip() or None,
        passphrase or None,
        slot_id, audition_type,
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


# ─────────────────────────────────────────────
#  REGISTRATION SETTINGS
# ─────────────────────────────────────────────

@app.route('/api/programs/<pid>/registration-settings', methods=['PUT'])
def save_registration_settings(pid):
    err = require_permission('youth')
    if err: return err
    import json as _json
    d = request.json or {}
    conn = get_db()
    images = d.get('program_images') or []
    custom_fields = d.get('custom_fields') or []
    execute(conn, '''UPDATE youth_programs SET
        registration_status=%s, registration_form_type=%s, slug=%s,
        capacity=%s, price=%s, deposit_amount=%s, sessions_enabled=%s,
        booking_mode=%s, max_sessions_per_reg=%s,
        sibling_discount_enabled=%s, sibling_discount_type=%s, sibling_discount_value=%s,
        registration_open_date=%s, registration_close_date=%s, waitlist_auto_charge=%s,
        program_info=%s, custom_fields=%s, square_catalog_item_id=%s,
        registration_note=%s,
        program_location=%s, schedule_type=%s, meeting_days=%s,
        meeting_start_time=%s, meeting_end_time=%s, single_date=%s, schedule_notes=%s,
        start_date=%s, end_date=%s, form_fields=%s
        WHERE id=%s''',
        (d.get('registration_status') or 'draft',
         d.get('registration_form_type') or 'youth',
         (d.get('slug') or '').strip().lower().replace(' ', '-') or None,
         d.get('capacity') or None,
         int(d.get('price_cents') or 0),
         int(d.get('deposit_amount') or 0),
         bool(d.get('sessions_enabled')),
         bool(d.get('booking_mode')),
         int(d.get('max_sessions_per_reg') or 0),
         bool(d.get('sibling_discount_enabled')),
         d.get('sibling_discount_type') or 'percent',
         int(d.get('sibling_discount_value') or 0),
         d.get('registration_open_date') or None,
         d.get('registration_close_date') or None,
         bool(d.get('waitlist_auto_charge', True)),
         (d.get('program_info') or '').strip(),
         _json.dumps(custom_fields),
         d.get('square_catalog_item_id') or None,
         (d.get('registration_note') or '').strip(),
         (d.get('program_location') or '').strip(),
         d.get('schedule_type') or 'date_range',
         _json.dumps(d.get('meeting_days') or []),
         (d.get('meeting_start_time') or '').strip(),
         (d.get('meeting_end_time') or '').strip(),
         (d.get('single_date') or '').strip(),
         (d.get('schedule_notes') or '').strip(),
         d.get('start_date') or None,
         d.get('end_date') or None,
         _json.dumps(d.get('form_fields') or {}),
         pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ─────────────────────────────────────────────
#  DISCOUNT CODES
# ─────────────────────────────────────────────

@app.route('/api/programs/<pid>/discount-codes', methods=['GET'])
def get_discount_codes(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    codes = fetchall(conn, 'SELECT * FROM discount_codes WHERE program_id=%s ORDER BY created_at DESC', (pid,))
    conn.close()
    return jsonify(codes or [])


@app.route('/api/programs/<pid>/discount-codes', methods=['POST'])
def create_discount_code(pid):
    err = require_auth()
    if err: return err
    import uuid as _u
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required'}), 400
    discount_type = d.get('discount_type', 'percent')
    discount_value = int(d.get('discount_value') or 0)
    min_spend = int(d.get('min_spend_cents') or 0)
    max_uses = d.get('max_uses') or None
    is_sibling = bool(d.get('is_sibling_discount'))
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    sq_id = None
    try:
        sq_id = square_create_discount(f'{prog["name"]} — {code}', discount_type, discount_value)
    except Exception as e:
        app.logger.warning(f'Square discount create failed: {e}')
    try:
        execute(conn, '''INSERT INTO discount_codes
            (id, program_id, code, square_discount_id, discount_type, discount_value,
             min_spend, is_sibling_discount, max_uses, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)''',
            (_u.uuid4().hex, pid, code, sq_id, discount_type, discount_value,
             min_spend, is_sibling, max_uses))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/programs/<pid>/discount-codes/<cid>', methods=['DELETE'])
def delete_discount_code(pid, cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE discount_codes SET active=FALSE WHERE id=%s AND program_id=%s', (cid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/public/program/<slug>/validate-discount', methods=['POST'])
def validate_discount(slug):
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'valid': False, 'error': 'Code required'})
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not prog:
        conn.close()
        return jsonify({'valid': False, 'error': 'Program not found'})
    dc = fetchone(conn, 'SELECT * FROM discount_codes WHERE program_id=%s AND code=%s AND active=TRUE', (prog['id'], code))
    conn.close()
    if not dc:
        return jsonify({'valid': False, 'error': 'Invalid or expired code'})
    if dc.get('max_uses') and (dc.get('uses') or 0) >= dc['max_uses']:
        return jsonify({'valid': False, 'error': 'This code has reached its maximum uses'})
    price = prog.get('price') or 0
    num_regs = int(d.get('num_registrations') or 1)
    basket = price * num_regs
    min_spend = dc.get('min_spend') or 0
    if min_spend > 0 and basket < min_spend:
        return jsonify({'valid': False, 'error': f'This code requires a minimum spend of ${min_spend/100:.2f}'})
    is_sib = bool(dc.get('is_sibling_discount'))
    if is_sib:
        if num_regs < 2:
            return jsonify({'valid': False, 'error': 'Sibling discount requires 2+ participants'})
        per_child = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
        discount_amount = per_child * (num_regs - 1)
        label = f'Sibling discount: {dc["discount_value"]}{"%" if dc["discount_type"]=="percent" else "¢"} off each additional participant'
    else:
        if dc['discount_type'] == 'percent':
            discount_amount = int(basket * dc['discount_value'] / 100)
            label = f'{dc["discount_value"]}% off'
        else:
            discount_amount = min(dc['discount_value'] * num_regs, basket)
            label = f'${dc["discount_value"]/100:.2f} off'
    if min_spend:
        label += f' (min. ${min_spend/100:.2f})'
    final_price = max(0, basket - discount_amount)
    return jsonify({'valid': True, 'discount_amount': discount_amount,
                    'final_price': final_price, 'is_sibling': is_sib,
                    'label': label, 'square_discount_id': dc.get('square_discount_id')})


def square_create_discount(name, discount_type, value):
    import uuid as _u
    if not SQUARE_ACCESS_TOKEN:
        return None
    payload = {'idempotency_key': _u.uuid4().hex, 'object': {
        'type': 'DISCOUNT', 'id': '#discount_' + _u.uuid4().hex[:12],
        'discount_data': {'name': name, 'discount_type': 'FIXED_AMOUNT' if discount_type == 'fixed' else 'FIXED_PERCENTAGE'}}}
    if discount_type == 'fixed':
        payload['object']['discount_data']['amount_money'] = {'amount': value, 'currency': 'USD'}
    else:
        payload['object']['discount_data']['percentage'] = str(value)
    try:
        r = requests.post(f'{SQUARE_API_BASE}/v2/catalog/object', json=payload, headers=square_headers(), timeout=10)
        data = r.json()
        return data.get('catalog_object', {}).get('id')
    except Exception:
        return None


# ─────────────────────────────────────────────
#  EMAIL TEMPLATES
# ─────────────────────────────────────────────

@app.route('/api/email-templates')
def get_email_templates():
    err = require_auth()
    if err: return err
    conn = get_db()
    templates = fetchall(conn, 'SELECT * FROM email_templates ORDER BY is_system DESC, name')
    conn.close()
    return jsonify(templates)


@app.route('/api/email-templates/reset/<key>', methods=['POST'])
def reset_system_template(key):
    err = require_admin()
    if err: return err
    conn = get_db()
    try:
        # Direct targeted reset for each known system template
        DEFAULTS = {
            'universal_reminder': (
                'Reminder: Submit Your Volunteer Hours - Universal Giving',
                '<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">\n  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center">\n    <h2 style="color:#fff;margin:0;font-size:22px">Your Volunteer Hours Make a Difference!</h2>\n    <p style="color:rgba(255,255,255,0.8);margin:8px 0 0;font-size:14px">Universal Team Member Giving Guide</p>\n  </div>\n  <div style="background:#fff;padding:28px 32px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px">\n    <p>Hi {{name}},</p>\n    <p>Thank you so much for volunteering with <strong>Horizon West Theatre Company</strong>! As a Universal Team Member, you can submit your hours through <strong>Universal Giving</strong> and potentially qualify for grant funding on our behalf.</p>\n    <p style="font-size:14px;color:#6b7280">Here is a step-by-step guide to logging your hours:</p>\n\n    <div style="margin:20px 0">\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">1</div>\n          <strong>Go to the Team Universal site</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step1.png" alt="Team Universal home page" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">2</div>\n          <strong>Scroll down and click &ldquo;Access myImpact&rdquo; on the home page</strong>\n        </div>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">3</div>\n          <strong>Select the company you work for &amp; log in with your SSO</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step2.png" alt="Select company and login" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">4</div>\n          <strong>Go to the &ldquo;Log Your Hours&rdquo; page</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step3.png" alt="myImpact home - Log Your Hours" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">5</div>\n          <strong>Click the &ldquo;Log Individual Hours&rdquo; button</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step4.png" alt="Log Individual Hours button" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">6</div>\n          <strong>Search for &ldquo;Horizon West Theater Company&rdquo;</strong>\n        </div>\n        <span style="color:#6b7280;font-size:13px">Enter the organization name and search, or select it if it already appears from a previous entry.</span>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step5.png" alt="Search for organization" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">7</div>\n          <strong>Enter your date range and hours, then click &ldquo;Save and Proceed&rdquo;</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step6.png" alt="Enter hours" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">8</div>\n          <strong>Review your submission and click &ldquo;Submit&rdquo;</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step7.png" alt="Review and submit" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n      <div style="margin-bottom:20px">\n        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">\n          <div style="background:#145466;color:#fff;border-radius:50%;width:28px;height:28px;min-width:28px;line-height:28px;text-align:center;font-size:13px;font-weight:700;flex-shrink:0">9</div>\n          <strong>A confirmation page will appear &mdash; you&#x2019;re all set!</strong>\n        </div>\n        <img src="https://rolecall.hwtco.org/static/images/universal_step8.png" alt="Confirmation" style="width:100%;border-radius:8px;border:1px solid #e5e7eb;margin:10px 0 18px;display:block"/>\n      </div>\n\n    </div>\n\n    <div style="background:#f0f8fa;border-radius:10px;padding:20px 24px;margin:24px 0;border-left:4px solid #145466">\n      <strong style="color:#145466">Did you know?</strong>\n      <p style="margin:8px 0 0;font-size:14px;color:#374151">Once you complete <strong>52 hours</strong> of volunteering you qualify for <strong>Club 52</strong>. After <strong>104 hours</strong> you reach <strong>Club 52 Elite</strong> status. Both levels qualify for the Universal Orlando Foundation grant &mdash; where you can choose a non-profit to receive grant money. <strong>Horizon West Theater Company qualifies</strong> and hopes you will consider donating your grant to our cause!</p>\n    </div>\n\n    {{hours_section}}\n\n    <p>If you have any questions or need help logging your hours, please reach out to us at <a href="mailto:info@hwtco.org" style="color:#145466">info@hwtco.org</a>.</p>\n    <p>With gratitude,<br/><strong>Horizon West Theatre Company</strong></p>\n  </div>\n</div>\''
            ),
        }
        if key not in DEFAULTS:
            # Fall back to full reseed for other templates
            seed_system_email_templates(conn)
            conn.commit()
            conn.close()
            return jsonify({'ok': True})
        subj, body = DEFAULTS[key]
        execute(conn,
            "UPDATE email_templates SET subject=%s, body=%s WHERE template_key=%s OR id=%s",
            (subj, body, key, key))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        app.logger.error(f'reset_system_template error: {e}')
        try: conn.rollback(); conn.close()
        except: pass
        return jsonify({'error': str(e)}), 500


@app.route('/api/email-templates/<tid>', methods=['PUT'])
def update_email_template(tid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE email_templates SET name=%s, subject=%s, body=%s WHERE id=%s',
        (d.get('name',''), d.get('subject',''), d.get('body',''), tid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/email-templates', methods=['POST'])
def create_email_template():
    err = require_admin()
    if err: return err
    d = request.json or {}
    tid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO email_templates (id,name,subject,body) VALUES (%s,%s,%s,%s)',
            (tid, d.get('name',''), d.get('subject',''), d.get('body','')))
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
        'SELECT e.*, p.name as program_name, p.status as program_status FROM youth_program_enrollments e JOIN youth_programs p ON e.program_id=p.id WHERE e.youth_id=%s ORDER BY e.enrolled_date DESC', (yid,))
    try:
        y['notes'] = fetchall(conn, 'SELECT * FROM youth_notes WHERE youth_id=%s ORDER BY created_at DESC', (yid,))
        y['incidents'] = fetchall(conn, 'SELECT * FROM youth_incidents WHERE youth_id=%s ORDER BY incident_date DESC', (yid,))
    except Exception:
        y['notes'] = []; y['incidents'] = []
    # Include family data if linked
    if y.get('family_id'):
        y['family'] = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (y['family_id'],))
    else:
        y['family'] = None
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>/family', methods=['PUT'])
def set_youth_family(yid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    family_id = d.get('family_id') or None
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=%s WHERE id=%s', (family_id, yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'family_id': family_id})

def default_passphrase(first_name, last_name):
    """Generate default portal passphrase: firstname_lastname_hwtc (lowercase)"""
    first = (first_name or '').strip().lower().replace(' ', '')
    last  = (last_name  or '').strip().lower().replace(' ', '')
    return f"{first}_{last}_hwtc"

@app.route('/api/youth/backfill-passphrases', methods=['POST'])
def backfill_passphrases():
    err = require_admin()
    if err: return err
    conn = get_db()
    students = fetchall(conn, "SELECT id, first_name, last_name FROM youth_participants WHERE passphrase IS NULL OR passphrase = ''")
    count = 0
    for s in students:
        pp = default_passphrase(s['first_name'], s['last_name'])
        execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE id=%s', (pp, s['id']))
        count += 1
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'updated': count})

@app.route('/api/youth', methods=['POST'])
def create_youth():
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    yid = str(uuid.uuid4())
    pp = default_passphrase(d.get('first_name',''), d.get('last_name',''))
    conn = get_db()
    execute(conn,
        'INSERT INTO youth_participants (id,first_name,last_name,dob,program,status,medical_notes,allergies,photo_consent,medical_consent,passphrase) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (yid, d.get('first_name',''), d.get('last_name',''), d.get('dob') or None, d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0, pp))
    for g in d.get('guardians', []):
        execute(conn, 'INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), yid, g['name'], g.get('relationship',''), g.get('phone',''), g.get('email',''), 1 if g.get('is_primary') else 0))
    if d.get('emergency_name') and d.get('emergency_phone'):
        execute(conn, 'INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), yid, d.get('emergency_name',''), d.get('emergency_relationship',''), d.get('emergency_phone','')))
    conn.commit()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    y['guardians'] = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s', (yid,))
    y['emergency_contacts'] = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (yid,))
    y['waivers'] = []
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['PUT'])
def update_youth(yid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn,
        'UPDATE youth_participants SET first_name=%s,last_name=%s,dob=%s,program=%s,status=%s,medical_notes=%s,allergies=%s,photo_consent=%s,medical_consent=%s,shirt_size=%s WHERE id=%s',
        (d.get('first_name',''), d.get('last_name',''), d.get('dob') or None, d.get('program',''), d.get('status','active'),
         d.get('medical_notes',''), d.get('allergies',''), 1 if d.get('photo_consent') else 0, 1 if d.get('medical_consent') else 0,
         d.get('shirt_size',''), yid))
    conn.commit()
    y = fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))
    conn.close()
    return jsonify(y)

@app.route('/api/youth/<yid>', methods=['DELETE'])
def delete_youth(yid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_participants WHERE id=%s', (yid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/guardians', methods=['POST'])
def add_guardian(yid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    gid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO youth_guardians (id,youth_id,name,relationship,phone,email,is_primary) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (gid, yid, d.get('name',''), d.get('relationship',''), d.get('phone',''), d.get('email',''), 1 if d.get('is_primary') else 0))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_guardians WHERE id=%s', (gid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/guardians/<gid>', methods=['PUT'])
def update_guardian(gid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_guardians SET name=%s,relationship=%s,phone=%s,email=%s,is_primary=%s WHERE id=%s',
            (d.get('name',''), d.get('relationship',''), d.get('phone',''), d.get('email',''),
             1 if d.get('is_primary') else 0, gid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_guardians WHERE id=%s', (gid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/guardians/<gid>', methods=['DELETE'])
def delete_guardian(gid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_guardians WHERE id=%s', (gid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/emergency-contacts/<ecid>', methods=['PUT'])
def update_emergency_contact(ecid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_emergency_contacts SET name=%s,relationship=%s,phone=%s WHERE id=%s',
            (d.get('name',''), d.get('relationship',''), d.get('phone',''), ecid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_emergency_contacts WHERE id=%s', (ecid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/emergency-contacts/<ecid>', methods=['DELETE'])
def delete_emergency_contact(ecid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_emergency_contacts WHERE id=%s', (ecid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/emergency-contacts', methods=['POST'])
def add_emergency_contact(yid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO youth_emergency_contacts (id,youth_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
            (eid, yid, d.get('name',''), d.get('relationship',''), d['phone']))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_emergency_contacts WHERE id=%s', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/<yid>/authorized-pickups', methods=['GET'])
def get_authorized_pickups(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    pickups = fetchall(conn, 'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority', (yid,))
    conn.close()
    return jsonify(pickups)

@app.route('/api/youth/<yid>/authorized-pickups', methods=['POST'])
def add_authorized_pickup(yid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    if not d.get('name','').strip():
        return jsonify({'error': 'Name required'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    max_p = fetchone(conn, 'SELECT COALESCE(MAX(priority),0) as m FROM youth_authorized_pickups WHERE youth_id=%s', (yid,))
    priority = (max_p['m'] or 0) + 1
    execute(conn, 'INSERT INTO youth_authorized_pickups (id,youth_id,name,relationship,phone,priority) VALUES (%s,%s,%s,%s,%s,%s)',
            (pid, yid, d['name'].strip(), d.get('relationship','').strip(), d.get('phone','').strip(), priority))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_authorized_pickups WHERE id=%s', (pid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/authorized-pickups/<pid>', methods=['PUT'])
def update_authorized_pickup(pid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_authorized_pickups SET name=%s,relationship=%s,phone=%s WHERE id=%s',
            (d.get('name','').strip(), d.get('relationship','').strip(), d.get('phone','').strip(), pid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_authorized_pickups WHERE id=%s', (pid,))
    conn.close()
    return jsonify(row or {'ok': True})

@app.route('/api/youth/authorized-pickups/<pid>', methods=['DELETE'])
def delete_authorized_pickup(pid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_authorized_pickups WHERE id=%s', (pid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/notes', methods=['GET'])
def get_youth_notes(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    notes = fetchall(conn, 'SELECT * FROM youth_notes WHERE youth_id=%s ORDER BY created_at DESC', (yid,))
    conn.close()
    return jsonify(notes)

@app.route('/api/youth/<yid>/notes', methods=['POST'])
def add_youth_note(yid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not d.get('content','').strip():
        return jsonify({'error': 'Note content required'}), 400
    nid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO youth_notes (id,youth_id,author,author_id,content,note_type)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (nid, yid, session.get('user_name','Staff'), session.get('user_id'),
         d['content'].strip(), d.get('note_type','general')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_notes WHERE id=%s', (nid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/notes/<nid>', methods=['DELETE'])
def delete_youth_note(nid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_notes WHERE id=%s', (nid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/incidents', methods=['GET'])
def get_youth_incidents(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    incidents = fetchall(conn, 'SELECT * FROM youth_incidents WHERE youth_id=%s ORDER BY incident_date DESC, created_at DESC', (yid,))
    conn.close()
    return jsonify(incidents)

@app.route('/api/youth/<yid>/incidents', methods=['POST'])
def add_youth_incident(yid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not d.get('title','').strip() or not d.get('incident_date','').strip():
        return jsonify({'error': 'Title and date required'}), 400
    iid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO youth_incidents
        (id,youth_id,incident_date,title,description,severity,reported_by,reported_by_id,follow_up,resolved)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (iid, yid, d['incident_date'], d['title'].strip(),
         d.get('description','').strip(), d.get('severity','minor'),
         session.get('user_name','Staff'), session.get('user_id'),
         d.get('follow_up','').strip(), False))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_incidents WHERE id=%s', (iid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/incidents/<iid>', methods=['PUT'])
def update_youth_incident(iid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE youth_incidents SET title=%s,description=%s,severity=%s,
        incident_date=%s,follow_up=%s,resolved=%s WHERE id=%s''',
        (d.get('title',''), d.get('description',''), d.get('severity','minor'),
         d.get('incident_date',''), d.get('follow_up',''),
         bool(d.get('resolved',False)), iid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM youth_incidents WHERE id=%s', (iid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth/incidents/<iid>', methods=['DELETE'])
def delete_youth_incident(iid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_incidents WHERE id=%s', (iid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/history', methods=['GET'])
def get_youth_history(yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Sign-in history with event names
    signins = fetchall(conn, '''SELECT ys.*, e.name as event_name, e.event_date,
        e.start_time, yp.name as program_name
        FROM youth_sign_ins ys
        LEFT JOIN events e ON ys.event_id=e.id
        LEFT JOIN youth_programs yp ON e.program_id=yp.id
        WHERE ys.youth_id=%s ORDER BY ys.sign_in_time DESC''', (yid,))
    conn.close()
    return jsonify(signins)

@app.route('/api/youth/<yid>/waivers', methods=['POST'])
def add_youth_waiver(yid):
    err = require_permission('youth')
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
    d = request.json or {}
    if not d.get('name') or not d.get('email') or not d.get('password'):
        return jsonify({'error': 'Name, email, and password are required'}), 400
    pw_hash = hashlib.sha256(d.get('password','').encode()).hexdigest()
    uid_ = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO users (id,name,email,password_hash,role,role_permissions) VALUES (%s,%s,%s,%s,%s,%s)',
                (uid_, d.get('name',''), d.get('email',''), pw_hash, d.get('role','staff'), '{}'))
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
        v.name as default_elic_name,
        (SELECT COUNT(*) FROM program_registrations WHERE production_id=p.id AND status NOT IN ('cancelled','waitlisted')) AS reg_enrolled,
        (SELECT COUNT(*) FROM program_registrations WHERE production_id=p.id AND status='waitlisted') AS reg_waitlisted
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
    err = require_permission('productions')
    if err: return err
    d = request.json or {}
    pid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO productions (id,name,production_type,stage,start_date,end_date,description,status,default_elic_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (pid, d.get('name',''), d.get('production_type','show'), d.get('stage','mainstage'),
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
    err = require_permission('productions')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE productions SET name=%s,production_type=%s,stage=%s,start_date=%s,end_date=%s,description=%s,status=%s,default_elic_id=%s,image_url=%s WHERE id=%s',
            (d.get('name',''), d.get('production_type','show'), d.get('stage','mainstage'),
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
    err = require_permission('productions')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM productions WHERE id=%s', (pid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/members', methods=['POST'])
def add_production_member(pid):
    err = require_permission('productions')
    if err: return err
    d = request.json or {}
    mid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO production_members (id,production_id,volunteer_id,role,department,status,notes) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                (mid, pid, d.get('volunteer_id'), d.get('role',''), d.get('department',''), d.get('status','confirmed'), d.get('notes','')))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback(); conn.close()
        return jsonify({'error': 'This volunteer is already in this production'}), 400
    row = fetchone(conn, '''SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
        FROM production_members pm JOIN volunteers v ON pm.volunteer_id=v.id WHERE pm.id=%s''', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/members/<mid>', methods=['PUT'])
@app.route('/api/productions/<pid>/team-member/<mid>', methods=['PUT'])
def update_production_member(mid, pid=None):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE production_members SET
        role=%s, department=%s, status=%s, notes=%s,
        bio=%s, photo_url=%s WHERE id=%s''',
        (d.get('role',''), d.get('department',''),
         d.get('status','confirmed'), d.get('notes',''),
         d.get('bio',''), d.get('photo_url',''), mid))
    conn.commit()
    row = fetchone(conn, '''SELECT pm.*, v.name as volunteer_name, v.email as volunteer_email
        FROM production_members pm JOIN volunteers v ON pm.volunteer_id=v.id WHERE pm.id=%s''', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/members/<mid>', methods=['DELETE'])
def remove_production_member(mid):
    err = require_permission('productions')
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
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
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
    err = require_permission('youth')
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

def get_cumulative_benefits(conn, tier_id):
    """Return all benefits for a tier including all benefits from lower tiers (cumulative)."""
    if not tier_id: return []
    tier = fetchone(conn, 'SELECT min_amount FROM donor_tiers WHERE id=%s', (tier_id,))
    if not tier: return []
    min_amount = tier['min_amount'] or 0
    return fetchall(conn, '''
        SELECT b.*, t.name as tier_name, t.min_amount
        FROM donor_tier_benefits b
        JOIN donor_tiers t ON b.tier_id=t.id
        WHERE t.min_amount <= %s
        ORDER BY t.min_amount ASC, b.sort_order ASC, b.name ASC
    ''', (min_amount,))

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
        GROUP BY t.id ORDER BY t.min_amount ASC''')
    for tier in tiers:
        tier['own_benefits'] = fetchall(conn, 'SELECT * FROM donor_tier_benefits WHERE tier_id=%s ORDER BY sort_order,name', (tier['id'],))
        tier['benefits'] = get_cumulative_benefits(conn, tier['id'])
    conn.close()
    return jsonify(tiers)

@app.route('/api/donor-tiers', methods=['POST'])
def create_donor_tier():
    err = require_auth()
    if err: return err
    d = request.json or {}
    tid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_tiers (id,name,min_amount,max_amount,color,description,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (tid, d.get('name',''), d.get('min_amount',0), d.get('max_amount') or None,
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
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE donor_tiers SET name=%s,min_amount=%s,max_amount=%s,color=%s,description=%s,sort_order=%s WHERE id=%s',
        (d.get('name',''), d.get('min_amount',0), d.get('max_amount') or None,
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
    d = request.json or {}
    bid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_tier_benefits (id,tier_id,name,description,is_trackable,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (bid, tid, d.get('name',''), d.get('description',''), d.get('is_trackable',True), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_tier_benefits WHERE id=%s', (bid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-benefits/<bid>', methods=['PUT'])
def update_tier_benefit(bid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE donor_tier_benefits SET name=%s,description=%s,is_trackable=%s,sort_order=%s WHERE id=%s',
        (d.get('name',''), d.get('description',''), d.get('is_trackable',True), d.get('sort_order',0), bid))
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
    for c in campaigns:
        try:
            c['benefits'] = fetchall(conn, '''SELECT * FROM campaign_benefits
                WHERE campaign_id=%s ORDER BY min_amount ASC, sort_order ASC, name ASC''', (c['id'],))
        except Exception:
            c['benefits'] = []
    conn.close()
    return jsonify(campaigns)

@app.route('/api/donor-campaigns/<cid>/benefits')
def get_campaign_benefits(cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, 'SELECT * FROM campaign_benefits WHERE campaign_id=%s ORDER BY min_amount ASC, sort_order ASC', (cid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/donor-campaigns/<cid>/benefits', methods=['POST'])
def create_campaign_benefit(cid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not (d.get('name') or '').strip(): return jsonify({'error': 'Name is required'}), 400
    bid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO campaign_benefits (id,campaign_id,name,description,min_amount,is_trackable,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (bid, cid, (d.get('name') or '').strip(), (d.get('description') or '').strip(),
         float(d.get('min_amount') or 0), bool(d.get('is_trackable',False)),
         int(d.get('sort_order',0))))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM campaign_benefits WHERE id=%s', (bid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-campaigns/benefits/<bid>', methods=['PUT'])
def update_campaign_benefit(bid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE campaign_benefits SET name=%s, description=%s, min_amount=%s, is_trackable=%s
        WHERE id=%s''',
        ((d.get('name') or '').strip(), (d.get('description') or '').strip(),
         float(d.get('min_amount') or 0), bool(d.get('is_trackable',False)), bid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM campaign_benefits WHERE id=%s', (bid,))
    conn.close()
    return jsonify(row or {'ok': True})

@app.route('/api/donor-campaigns/benefits/<bid>', methods=['DELETE'])
def delete_campaign_benefit(bid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM campaign_benefits WHERE id=%s', (bid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-campaigns', methods=['POST'])
def create_donor_campaign():
    err = require_auth()
    if err: return err
    d = request.json or {}
    cid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_campaigns (id,name,description,goal_amount,start_date,end_date,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (cid, d.get('name',''), d.get('description',''), d.get('goal_amount') or None,
         d.get('start_date') or None, d.get('end_date') or None, d.get('status','active')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_campaigns WHERE id=%s', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-campaigns/<cid>', methods=['PUT'])
def update_donor_campaign(cid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE donor_campaigns SET name=%s,description=%s,goal_amount=%s,start_date=%s,end_date=%s,status=%s WHERE id=%s',
        (d.get('name',''), d.get('description',''), d.get('goal_amount') or None,
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

# ── Donors  -  static routes MUST come before <did> dynamic routes ──
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
    d = request.json or {}
    did = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donors
        (id,type,display_name,legal_name,email,phone,address,website,
         volunteer_id,is_anonymous,recognition_name,notes,internal_rating,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)''',
        (did, d.get('type','individual'), d.get('display_name',''), d.get('legal_name',''),
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
@app.route('/api/donations/all')
def get_all_donations():
    """Return all donations with donor name, for bulk editing."""
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, """
        SELECT dd.*, dn.display_name as donor_name, c.name as campaign_name
        FROM donor_donations dd
        JOIN donors dn ON dd.donor_id = dn.id
        LEFT JOIN donor_campaigns c ON dd.campaign_id = c.id
        ORDER BY dd.donation_date ASC NULLS LAST, dn.display_name ASC
    """)
    conn.close()
    return jsonify(rows)

@app.route('/api/donations/bulk-update', methods=['POST'])
def bulk_update_donations():
    """Update multiple donations at once."""
    err = require_auth()
    if err: return err
    updates = request.json.get('updates', [])
    if not updates:
        return jsonify({'error': 'No updates provided'}), 400
    conn = get_db()
    updated = 0
    errors = []
    affected_donors = set()
    for u in updates:
        did = u.get('id')
        if not did:
            continue
        try:
            execute(conn, """UPDATE donor_donations SET
                amount=%s, donation_date=%s, type=%s,
                payment_status=%s, campaign_id=%s,
                check_number=%s, notes=%s WHERE id=%s""",
                (u.get('amount'), u.get('donation_date'),
                 u.get('type','cash'), u.get('payment_status','received'),
                 u.get('campaign_id') or None,
                 u.get('check_number',''), u.get('notes',''), did))
            affected_donors.add(u['donor_id'])
            updated += 1
        except Exception as e:
            errors.append(str(e)[:60])
    conn.commit()
    for donor_id in affected_donors:
        try:
            recalc_donor_totals(conn, donor_id)
        except Exception:
            pass
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'updated': updated, 'errors': errors[:5]})

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
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE donors SET type=%s,display_name=%s,legal_name=%s,email=%s,phone=%s,
        address=%s,website=%s,volunteer_id=%s,is_anonymous=%s,recognition_name=%s,
        notes=%s,internal_rating=%s,status=%s WHERE id=%s''',
        (d.get('type','individual'), d.get('display_name',''), d.get('legal_name',''),
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
    d = request.json or {}
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
    # Cumulative tier benefits (this tier + all lower tiers)
    donor['benefits'] = get_cumulative_benefits(conn, donor.get('tier_id'))

    # Campaign-specific benefits  -  for each campaign this donor has donated to,
    # show which benefits they've earned based on their total to that campaign
    try:
        campaign_totals = fetchall(conn, '''
            SELECT campaign_id, c.name as campaign_name,
                   SUM(amount) FILTER (WHERE payment_status='received') as total
            FROM donor_donations dd
            JOIN donor_campaigns c ON dd.campaign_id=c.id
            WHERE dd.donor_id=%s AND dd.campaign_id IS NOT NULL
            GROUP BY campaign_id, c.name
            HAVING SUM(amount) FILTER (WHERE payment_status='received') > 0
        ''', (did,))
        campaign_benefits = []
        for ct in campaign_totals:
            earned = fetchall(conn, '''
                SELECT * FROM campaign_benefits
                WHERE campaign_id=%s AND min_amount <= %s
                ORDER BY min_amount ASC, sort_order ASC
            ''', (ct['campaign_id'], float(ct['total'] or 0)))
            if earned:
                campaign_benefits.append({
                    'campaign_id': ct['campaign_id'],
                    'campaign_name': ct['campaign_name'],
                    'total_donated': float(ct['total'] or 0),
                    'benefits': earned
                })
        donor['campaign_benefits'] = campaign_benefits
    except Exception as e:
        app.logger.warning(f'campaign benefits for donor {did}: {e}')
        donor['campaign_benefits'] = []

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
    d = request.json or {}
    donation_id = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_donations
        (id,donor_id,campaign_id,amount,donation_date,type,payment_status,check_number,notes,created_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (donation_id, did, d.get('campaign_id') or None,
         d.get('amount',0), d['donation_date'],
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
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE donor_donations SET amount=%s,donation_date=%s,type=%s,
        payment_status=%s,campaign_id=%s,check_number=%s,notes=%s WHERE id=%s''',
        (d.get('amount',0), d['donation_date'], d.get('type','cash'),
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
    d = request.json or {}
    template_id = d.get('template_id')
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
    name         = row.get('recognition_name') or row['display_name']
    amount       = '${:,.2f}'.format(float(row['amount']))
    campaign_str = ' for ' + row['campaign_name'] if row.get('campaign_name') else ''
    date_str     = str(row.get('donation_date',''))

    # Look up donor's current tier and benefits for placeholders
    donor = fetchone(conn, '''SELECT dn.total_donated, t.name as tier_name, t.id as tier_id
        FROM donors dn LEFT JOIN donor_tiers t ON dn.tier_id=t.id
        WHERE dn.id=%s''', (row['donor_id'],))
    tier_name = donor['tier_name'] if donor and donor.get('tier_name') else ''
    benefits_html = ''
    benefits_text = ''

    all_benefits = []

    # Tier benefits (cumulative)
    if donor and donor.get('tier_id'):
        tier_benefits = get_cumulative_benefits(conn, donor['tier_id'])
        all_benefits += [dict(b, source='tier') for b in tier_benefits]

    # Campaign-specific benefits  -  include all that the donation amount qualifies for
    if row.get('campaign_id') and row.get('amount'):
        try:
            camp_benefits = fetchall(conn, '''SELECT * FROM campaign_benefits
                WHERE campaign_id=%s AND min_amount <= %s
                ORDER BY min_amount ASC, sort_order ASC''',
                (row['campaign_id'], float(row['amount'])))
            all_benefits += [dict(b, source='campaign') for b in camp_benefits]
        except Exception:
            pass

    if all_benefits:
        def benefit_li(b):
            source_tag = ''
            if b.get('source') == 'campaign':
                source_tag = f'<em style="font-size:11px;color:#888">Campaign</em> '
            elif b.get('tier_name'):
                source_tag = f'<em style="font-size:11px;color:#888">{b["tier_name"]}</em> '
            return (f'<li style="margin-bottom:4px">{source_tag}{b["name"]}'
                    + (f'  -  {b["description"]}' if b.get('description') else '')
                    + '</li>')
        benefits_html = '<ul style="margin:8px 0;padding-left:20px">' + \
            ''.join(benefit_li(b) for b in all_benefits) + '</ul>'
        benefits_text = '\n'.join(
            f'• {b["name"]}' + (f'  -  {b["description"]}' if b.get('description') else '')
            for b in all_benefits)
    # Load template
    tmpl = None
    if template_id:
        tmpl = fetchone(conn, 'SELECT * FROM donor_email_templates WHERE id=%s', (template_id,))
    if not tmpl:
        tmpl = fetchone(conn, "SELECT * FROM donor_email_templates WHERE is_default=TRUE AND template_type='thankyou' LIMIT 1")
    if tmpl:
        def sub(text):
            return (text or '')\
                .replace('{{name}}', name)\
                .replace('{{amount}}', amount)\
                .replace('{{campaign}}', row.get('campaign_name','') or '')\
                .replace('{{date}}', date_str)\
                .replace('{{tier}}', tier_name)\
                .replace('{{benefits}}', benefits_html)\
                .replace('{{benefits_text}}', benefits_text)
        subject    = sub(tmpl['subject'])
        html_body  = sub(tmpl['body'])
        from_email = tmpl.get('from_email') or None
        from_name  = tmpl.get('from_name') or ''
        from_addr  = (f'{from_name} <{from_email}>' if from_name and from_email else from_email) if from_email else None
    else:
        subject   = 'Thank You for Your Generous Support  -  HWTC'
        from_addr = None
        html_body = '''<div style="font-family:-apple-system,sans-serif;max-width:600px;margin:0 auto">
        <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:32px;text-align:center;border-radius:12px 12px 0 0">
            <h1 style="color:#fff;font-size:24px;margin:16px 0 0">Thank You!</h1></div>
        <div style="padding:32px;background:#fff;border-radius:0 0 12px 12px;border:1px solid #e0e0db;border-top:none">
            <p style="font-size:16px">Dear {name},</p>
            <p style="font-size:15px;color:#5f5e5a;line-height:1.7">On behalf of Horizon West Theatre Company, thank you for your generous contribution of <strong>{amount}</strong>{campaign_str}.</p>
            <div style="background:#f0f8fa;border-left:4px solid #145466;padding:16px;margin:24px 0">
                <div style="font-weight:700">{amount}</div><div style="font-size:13px;color:#5f5e5a">Date: {date}</div></div>
            <p style="font-size:15px;color:#5f5e5a">With gratitude,<br/><strong>Horizon West Theatre Company</strong></p></div>
        <p style="text-align:center;font-size:11px;color:#9b9b94;margin-top:16px">Horizon West Theatre Company is a 501(c)(3) non-profit organization.</p>
        </div>'''.format(name=name, amount=amount, campaign_str=campaign_str, date=date_str)
    ok, err_msg = send_email([row['email']], subject, html_body, from_addr)
    if ok:
        execute(conn, '''UPDATE donor_donations SET thank_you_sent=TRUE,
            thank_you_sent_at=NOW(), thank_you_sent_by=%s WHERE id=%s''',
            (session.get('user_name',''), donation_id))
        cid = str(uuid.uuid4())
        execute(conn, '''INSERT INTO donor_communications (id,donor_id,type,subject,body,sent_by)
            VALUES (%s,%s,'email',%s,%s,%s)''',
            (cid, row['donor_id'], subject,
             'Thank you sent for {}{}'.format(amount, campaign_str),
             session.get('user_name','')))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    conn.close()
    return jsonify({'error': err_msg or 'Failed to send email'}), 500

# ── Donor Email Templates ──
@app.route('/api/donor-email-templates')
def get_donor_email_templates():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, 'SELECT * FROM donor_email_templates ORDER BY name')
    conn.close()
    return jsonify(rows)

@app.route('/api/donor-email-templates', methods=['POST'])
def create_donor_email_template():
    err = require_auth()
    if err: return err
    d = request.json or {}
    tid = str(uuid.uuid4())
    conn = get_db()
    if d.get('is_default'):
        execute(conn, "UPDATE donor_email_templates SET is_default=FALSE WHERE template_type=%s",
            (d.get('template_type','thankyou'),))
    execute(conn, '''INSERT INTO donor_email_templates
        (id,name,subject,body,from_email,from_name,template_type,is_default)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
        (tid, d.get('name',''), d.get('subject',''), d.get('body',''),
         d.get('from_email',''), d.get('from_name',''),
         d.get('template_type','thankyou'), d.get('is_default',False)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM donor_email_templates WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/donor-email-templates/<tid>', methods=['PUT'])
def update_donor_email_template(tid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    if d.get('is_default'):
        execute(conn, "UPDATE donor_email_templates SET is_default=FALSE WHERE template_type=%s AND id!=%s",
            (d.get('template_type','thankyou'), tid))
    execute(conn, '''UPDATE donor_email_templates SET name=%s,subject=%s,body=%s,
        from_email=%s,from_name=%s,template_type=%s,is_default=%s WHERE id=%s''',
        (d.get('name',''), d.get('subject',''), d.get('body',''),
         d.get('from_email',''), d.get('from_name',''),
         d.get('template_type','thankyou'), d.get('is_default',False), tid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donor-email-templates/<tid>', methods=['DELETE'])
def delete_donor_email_template(tid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM donor_email_templates WHERE id=%s', (tid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/donors/<did>/benefits/use', methods=['POST'])
def record_benefit_use(did):
    err = require_auth()
    if err: return err
    d = request.json or {}
    uid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO donor_benefit_usage (id,donor_id,benefit_id,notes,recorded_by)
        VALUES (%s,%s,%s,%s,%s)''',
        (uid, did, d.get('benefit_id'), d.get('notes',''), session.get('user_name','')))
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
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE donors SET tier_id=%s, tier_override=%s WHERE id=%s',
        (d.get('tier_id') or None, d.get('override', False), did))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  STATIC PAGES
# ─────────────────────────────────────────────

@app.route('/kiosk')
def kiosk_page():
    resp = send_from_directory('static', 'kiosk.html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/pickup')
def pickup_page():
    return send_from_directory('static', 'pickup.html')

@app.route('/portal')
def portal_page():
    resp = send_from_directory('static', 'portal.html')
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/join')
def join_page():
    resp = send_from_directory('static', 'join.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

# ─────────────────────────────────────────────
#  NAV ICONS
# ─────────────────────────────────────────────

@app.route('/api/nav-icons')
def get_nav_icons():
    conn = get_db()
    rows = fetchall(conn, 'SELECT key, lucide_name FROM nav_icons')
    conn.close()
    return jsonify({r['key']: r['lucide_name'] for r in rows})

@app.route('/api/nav-icons', methods=['PUT'])
def save_nav_icons():
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    for key, name in d.items():
        if name:
            execute(conn, '''INSERT INTO nav_icons (key, lucide_name) VALUES (%s,%s)
                ON CONFLICT (key) DO UPDATE SET lucide_name=EXCLUDED.lucide_name''', (key, name))
        else:
            execute(conn, 'DELETE FROM nav_icons WHERE key=%s', (key,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

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
    err = require_auth()
    if err: return err
    d = request.json or {}
    tid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO event_types (id,name,color,description) VALUES (%s,%s,%s,%s)',
        (tid, d.get('name',''), d.get('color','blue'), d.get('description','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM event_types WHERE id=%s', (tid,))
    conn.close()
    return jsonify(row)

@app.route('/api/event-types/<tid>', methods=['PUT'])
def update_event_type(tid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE event_types SET name=%s,color=%s WHERE id=%s',
        (d.get('name',''), d.get('color','blue'), tid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/event-types/<tid>', methods=['DELETE'])
def delete_event_type(tid):
    err = require_auth()
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
    elics = fetchall(conn, '''SELECT e.*, v.name as volunteer_name
        FROM elics e LEFT JOIN volunteers v ON e.volunteer_id=v.id ORDER BY v.name''')
    conn.close()
    return jsonify(elics)

@app.route('/api/elics', methods=['POST'])
def create_elic():
    err = require_auth()
    if err: return err
    d = request.json or {}
    eid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO elics (id, volunteer_id, pin, is_master, assigned_events)
        VALUES (%s,%s,%s,%s,%s)''',
        (eid, d.get('volunteer_id'), d.get('pin','0000'),
         d.get('is_master', False), json.dumps(d.get('assigned_events',[]))))
    conn.commit()
    row = fetchone(conn, '''SELECT e.*, v.name as volunteer_name
        FROM elics e LEFT JOIN volunteers v ON e.volunteer_id=v.id WHERE e.id=%s''', (eid,))
    conn.close()
    return jsonify(row)

@app.route('/api/elics/<eid>', methods=['PUT'])
def update_elic(eid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE elics SET volunteer_id=%s, pin=%s, is_master=%s, assigned_events=%s WHERE id=%s',
        (d.get('volunteer_id'), d.get('pin','0000'),
         d.get('is_master',False), json.dumps(d.get('assigned_events',[])), eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/elics/<eid>', methods=['DELETE'])
def delete_elic(eid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM elics WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/elic-auth', methods=['POST'])
@app.route('/api/kiosk/elic-login', methods=['POST'])
def kiosk_elic_auth():
    d = request.json or {}
    pin = d.get('pin','')
    conn = get_db()
    elic = fetchone(conn, '''SELECT e.*, v.name as volunteer_name
        FROM elics e LEFT JOIN volunteers v ON e.volunteer_id=v.id
        WHERE e.pin=%s''', (pin,))
    if not elic:
        conn.close(); return jsonify({'error': 'Invalid PIN'}), 401
    # Get assigned events  -  check both assigned_events field AND event_elics table
    assigned = json.loads(elic.get('assigned_events') or '[]')
    # Also get events assigned via the event detail page (event_elics table)
    event_elics_rows = fetchall(conn, 'SELECT event_id FROM event_elics WHERE elic_id=%s', (elic['id'],))
    for row in event_elics_rows:
        if row['event_id'] not in assigned:
            assigned.append(row['event_id'])
    if elic.get('is_master'):
        events = fetchall(conn, '''
            SELECT e.*, p.name as production_name,
                   COALESCE(p.stage,'mainstage') as stage,
                   p.stage as production_stage,
                   pg.name as program_name
            FROM events e
            LEFT JOIN productions p ON e.production_id=p.id
            LEFT JOIN youth_programs pg ON e.program_id=pg.id
            ORDER BY e.event_date DESC NULLS LAST, e.name''')
    else:
        if assigned:
            placeholders = ','.join(['%s']*len(assigned))
            events = fetchall(conn, f'''
                SELECT e.*, p.name as production_name,
                       COALESCE(p.stage,'mainstage') as stage,
                       p.stage as production_stage,
                       pg.name as program_name
                FROM events e
                LEFT JOIN productions p ON e.production_id=p.id
                LEFT JOIN youth_programs pg ON e.program_id=pg.id
                WHERE e.id IN ({placeholders})''', tuple(assigned))
        else:
            events = []
    conn.close()
    return jsonify({'ok': True, 'elic': elic, 'events': events})

# ─────────────────────────────────────────────
#  CHECKLIST ITEMS
# ─────────────────────────────────────────────

@app.route('/api/checklist-items')
def get_checklist_items():
    # No auth required  -  kiosk needs this without an admin session
    conn = get_db()
    items = fetchall(conn, 'SELECT * FROM checklist_items ORDER BY sort_order, label')
    conn.close()
    return jsonify(items)

@app.route('/api/checklist-items', methods=['POST'])
def create_checklist_item():
    err = require_auth()
    if err: return err
    d = request.json or {}
    iid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO checklist_items (id,label,required,sort_order) VALUES (%s,%s,%s,%s)',
        (iid, d.get('label',''), d.get('required',False), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM checklist_items WHERE id=%s', (iid,))
    conn.close()
    return jsonify(row)

@app.route('/api/checklist-items/<iid>', methods=['PUT'])
def update_checklist_item(iid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE checklist_items SET label=%s, required=%s, sort_order=%s WHERE id=%s',
        (d.get('label',''), d.get('required',False), d.get('sort_order',0), iid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/checklist-items/<iid>', methods=['DELETE'])
def delete_checklist_item(iid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM checklist_items WHERE id=%s', (iid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/opening-checklist-items')
def get_opening_checklist_items():
    # No auth required  -  kiosk needs this without an admin session
    conn = get_db()
    items = fetchall(conn, 'SELECT * FROM opening_checklist_items ORDER BY sort_order, label')
    conn.close()
    return jsonify(items)

@app.route('/api/opening-checklist-items', methods=['POST'])
def create_opening_checklist_item():
    err = require_auth()
    if err: return err
    d = request.json or {}
    iid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO opening_checklist_items (id,label,required,sort_order) VALUES (%s,%s,%s,%s)',
        (iid, d.get('label',''), d.get('required',False), d.get('sort_order',0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM opening_checklist_items WHERE id=%s', (iid,))
    conn.close()
    return jsonify(row)

@app.route('/api/opening-checklist-items/<iid>', methods=['PUT'])
def update_opening_checklist_item(iid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE opening_checklist_items SET label=%s, required=%s, sort_order=%s WHERE id=%s',
        (d.get('label',''), d.get('required',False), d.get('sort_order',0), iid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/opening-checklist-items/<iid>', methods=['DELETE'])
def delete_opening_checklist_item(iid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM opening_checklist_items WHERE id=%s', (iid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  PENDING HOURS
# ─────────────────────────────────────────────

@app.route('/api/pending-hours')
def get_pending_hours():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT ph.*, v.name as volunteer_name
        FROM pending_hours ph
        LEFT JOIN volunteers v ON ph.volunteer_id=v.id
        WHERE ph.status IN ('pending','pending_review','pending_profile')
        ORDER BY ph.submitted_at DESC NULLS LAST''')
    conn.close()
    return jsonify(rows)

@app.route('/api/pending-hours/<hid>', methods=['PUT'])
def update_pending_hours(hid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    try:
        hours = round(float(d.get('hours', 0)), 2)
        if hours <= 0: return jsonify({'error': 'Hours must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid hours value'}), 400
    conn = get_db()
    execute(conn, 'UPDATE pending_hours SET hours=%s WHERE id=%s', (hours, hid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'hours': hours})

@app.route('/api/hours/<hid>', methods=['PUT'])
def update_approved_hours(hid):
    err = require_permission('hours')
    if err: return err
    d = request.json or {}
    try:
        hours = round(float(d.get('hours', 0)), 2)
        if hours <= 0: return jsonify({'error': 'Hours must be greater than 0'}), 400
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid hours value'}), 400
    conn = get_db()
    row = fetchone(conn, 'SELECT * FROM hours WHERE id=%s', (hid,))
    if not row: conn.close(); return jsonify({'error': 'Record not found'}), 404
    event = d.get('event', row.get('event','')).strip() or row.get('event','')
    date  = d.get('date',  row.get('date',''))  or row.get('date','')
    execute(conn, 'UPDATE hours SET hours=%s, event=%s, date=%s WHERE id=%s', (hours, event, date, hid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'hours': hours, 'event': event, 'date': date})

@app.route('/api/pending-hours/<hid>/approve', methods=['POST'])
def approve_pending_hours(hid):
    err = require_auth()
    if err: return err
    conn = get_db()
    ph = fetchone(conn, 'SELECT * FROM pending_hours WHERE id=%s', (hid,))
    if not ph: conn.close(); return jsonify({'error': 'Not found'}), 404
    pid = str(uuid.uuid4())
    try:
        execute(conn, '''INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
            (pid, ph['volunteer_id'], ph['event'], ph.get('event_id'),
             ph['date'], ph['hours'], ph.get('role',''), ph.get('notes','')))
    except Exception:
        # May already exist  -  just mark as approved
        pass
    execute(conn, "UPDATE pending_hours SET status='approved' WHERE id=%s", (hid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-hours/<hid>/reject', methods=['POST'])
def reject_pending_hours(hid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE pending_hours SET status='rejected' WHERE id=%s", (hid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  ALERTS & NOTIFICATIONS
# ─────────────────────────────────────────────

@app.route('/api/alerts')
def get_alerts():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT * FROM alerts WHERE status='active'
        ORDER BY created_at DESC LIMIT 50''')
    conn.close()
    return jsonify(rows)

@app.route('/api/alerts', methods=['POST'])
def create_alert():
    err = require_auth()
    if err: return err
    d = request.json or {}
    aid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO alerts (id,type,message,source,status)
        VALUES (%s,%s,%s,%s,'active')''',
        (aid, d.get('type','info'), d.get('message',''), d.get('source','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/alerts/<aid>/dismiss', methods=['POST'])
def dismiss_alert(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE alerts SET status='dismissed' WHERE id=%s", (aid,))
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
    rows = fetchall(conn, '''SELECT el.*, e.name as event_name, e.event_date,
        v.name as elic_name
        FROM event_logs el
        LEFT JOIN events e ON el.event_id=e.id
        LEFT JOIN elics eli ON el.elic_id=eli.id
        LEFT JOIN volunteers v ON eli.volunteer_id=v.id
        ORDER BY el.timestamp DESC LIMIT 200''')
    for row in rows:
        row['checklist'] = fetchall(conn,
            'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id', (row['id'],))
        row['log_id'] = row['id']
    conn.close()
    return jsonify(rows)

@app.route('/api/event-logs/<lid>/report')
def get_event_log_report(lid):
    err = require_auth()
    if err: return err
    conn = get_db()
    row = fetchone(conn, '''SELECT el.*, e.name as event_name, e.event_date,
        v.name as elic_name
        FROM event_logs el
        LEFT JOIN events e ON el.event_id=e.id
        LEFT JOIN elics eli ON el.elic_id=eli.id
        LEFT JOIN volunteers v ON eli.volunteer_id=v.id
        WHERE el.id=%s''', (lid,))
    if not row:
        conn.close(); return jsonify({'error': 'Log not found'}), 404
    # Closing checklist (this log)
    row['checklist'] = fetchall(conn,
        'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id', (lid,))
    # Opening checklist (find the open log for the same event)
    open_log = fetchone(conn, '''SELECT el.*, v.name as elic_name
        FROM event_logs el
        LEFT JOIN elics eli ON el.elic_id=eli.id
        LEFT JOIN volunteers v ON eli.volunteer_id=v.id
        WHERE el.event_id=%s AND el.action='open'
        ORDER BY el.id LIMIT 1''', (row['event_id'],))
    if open_log:
        row['opening_checklist'] = fetchall(conn,
            'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id',
            (open_log['id'],))
        row['open_elic_name'] = open_log.get('elic_name','')
        row['open_timestamp'] = str(open_log.get('timestamp','') or '')
    else:
        row['opening_checklist'] = []
        row['open_elic_name'] = ''
        row['open_timestamp'] = ''
    row['hours'] = fetchall(conn, '''SELECT h.*, v.name as volunteer_name
        FROM hours h JOIN volunteers v ON h.volunteer_id=v.id
        WHERE h.event_id=%s ORDER BY v.name''', (row['event_id'],))
    conn.close()
    return jsonify(row)

# ─────────────────────────────────────────────
#  EMAIL SETTINGS
# ─────────────────────────────────────────────

@app.route('/api/email-settings')
def get_email_settings_route():
    err = require_auth()
    if err: return err
    s = get_email_settings()
    return jsonify(s)

@app.route('/api/email-settings', methods=['PUT'])
def save_email_settings_route():
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    # Ensure rental columns exist
    for col in ['rental_approver_emails TEXT DEFAULT \'\'', 'rental_approval_levels TEXT DEFAULT \'[]\'']:
        try:
            execute(conn, f'ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS {col}')
            conn.commit()
        except Exception:
            pass
    allowed = ['resend_api_key','from_email','sender_identities','report_recipients','report_recipient_user_ids',
        'alert_pending_hours','alert_profile_updates','alert_callouts','alert_waiver_expiry',
        'alert_conflicts','alert_waivers','alert_event_not_opened','alert_event_not_closed',
        'auto_send_checklist_report','alert_new_rsvp','alert_role_filled',
        'rental_approver_emails','rental_approval_levels']
    sets = []; vals = []
    for key in allowed:
        if key in d:
            sets.append(f'{key}=%s')
            val = d[key]
            if isinstance(val, list): val = json.dumps(val)
            vals.append(val)
    if sets:
        vals.append(1)
        execute(conn, f"UPDATE email_settings SET {','.join(sets)} WHERE id=%s", vals)
        conn.commit()
    else:
        app.logger.warning(f'save_email_settings: nothing to save. keys in d: {list(d.keys())}')
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/email-templates/<tid>/test', methods=['POST'])
def test_template_email(tid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    tmpl = fetchone(conn, 'SELECT * FROM email_templates WHERE id=%s', (tid,))
    user = fetchone(conn, 'SELECT email, name FROM users WHERE id=%s', (session.get('user_id',''),))
    conn.close()
    if not tmpl: return jsonify({'error': 'Template not found'}), 404
    to = (d.get('to') or '').strip() or (user['email'] if user else '')
    if not to: return jsonify({'error': 'No recipient email  -  add your email to your user profile.'}), 400
    # Replace variables with sample values
    sample = {
        '{{name}}': user['name'] if user else 'Test User',
        '{{email}}': to,
        '{{volunteer_name}}': user['name'] if user else 'Test User',
        '{{event_name}}': 'Sample Event',
        '{{event_date}}': 'June 1, 2025',
        '{{hours}}': '3',
        '{{month}}': 'June',
        '{{year}}': '2025',
        '{{link}}': '#',
        '{{signup_link}}': '#',
        '{{review_link}}': '#',
        '{{temp_password}}': 'TEMP-1234',
        '{{role}}': 'Stage Crew',
        '{{location}}': 'HWTC Theatre',
        '{{message}}': 'We would love to have you join us!',
        '{{date}}': 'June 1, 2025',
        '{{elic_name}}': 'Test ELIC',
        '{{volunteer_count}}': '12',
        '{{total_hours}}': '36',
        '{{checklist_html}}': '<p><em>(Checklist items would appear here)</em></p>',
        '{{hours_html}}': '<p><em>(Hours breakdown would appear here)</em></p>',
        '{{participant_name}}': 'Test Participant',
        '{{pickup_name}}': 'Unknown Person',
        '{{timestamp}}': 'June 1, 2025 at 3:00 PM',
        '{{interests}}': 'Acting, Stage Crew',
        '{{employer_program}}': 'Disney Cast Member',
        '{{how_heard}}': 'Social Media',
        '{{notes}}': ' - ',
        '{{phone}}': '555-1234',
    }
    body = tmpl['body']
    subject = '[TEST] ' + tmpl['subject']
    for var, val in sample.items():
        body = body.replace(var, val)
        subject = subject.replace(var, val)
    # Wrap with test banner
    body = f'''<div style="background:#fef9c3;border:2px dashed #f59e0b;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-family:sans-serif;font-size:13px;color:#854d0e">
        <strong>⚠️ This is a test email</strong>  -  sent to {to}. Sample values have been substituted for real data.
    </div>''' + body
    ok, msg = send_email([to], subject, body)
    if ok: return jsonify({'ok': True, 'sent_to': to})
    return jsonify({'error': msg or 'Failed to send'}), 500

@app.route('/api/email-settings/test', methods=['POST'])
def test_email_route():
    err = require_admin()
    if err: return err
    d = request.json or {}
    to = (d.get('to') or '').strip()
    # Fall back to current user's email
    if not to:
        conn = get_db()
        user = fetchone(conn, 'SELECT email FROM users WHERE id=%s', (session.get('user_id',''),))
        conn.close()
        to = user['email'] if user else ''
    if not to: return jsonify({'error': 'No recipient email found. Please save your email address in your user profile.'}), 400
    ok, msg = send_email([to], 'RoleCall Test Email',
        '<p style="font-family:sans-serif">This is a test email from RoleCall. If you received this, email is working correctly.</p>')
    if ok: return jsonify({'ok': True, 'sent_to': to})
    return jsonify({'error': msg or 'Failed to send'}), 500

# ─────────────────────────────────────────────
#  USERS (additional routes)
# ─────────────────────────────────────────────

@app.route('/api/users/<uid>', methods=['PUT'])
def update_user(uid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    if d.get('password'):
        pw_hash = hashlib.sha256(d.get('password','').encode()).hexdigest()
        execute(conn, 'UPDATE users SET name=%s, email=%s, password_hash=%s WHERE id=%s',
            (d.get('name',''), d.get('email',''), pw_hash, uid))
    else:
        execute(conn, 'UPDATE users SET name=%s, email=%s WHERE id=%s',
            (d.get('name',''), d.get('email',''), uid))
    if 'permissions' in d:
        execute(conn, 'UPDATE users SET role_permissions=%s WHERE id=%s',
            (json.dumps(d.get('permissions','[]')), uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>', methods=['DELETE'])
def delete_user(uid):
    err = require_admin()
    if err: return err
    if uid == session.get('user_id'):
        return jsonify({'error': 'Cannot delete your own account'}), 400
    conn = get_db()
    execute(conn, 'DELETE FROM users WHERE id=%s', (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>/permissions', methods=['PUT'])
def update_user_permissions(uid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE users SET role_permissions=%s WHERE id=%s',
        (json.dumps(d.get('permissions',{})), uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/users/<uid>/send-reset-link', methods=['POST'])
def send_reset_link(uid):
    err = require_admin()
    if err: return err
    conn = get_db()
    user = fetchone(conn, 'SELECT * FROM users WHERE id=%s', (uid,))
    if not user: conn.close(); return jsonify({'error': 'User not found'}), 404
    import secrets
    temp_pw = secrets.token_urlsafe(10)
    # Use SHA-256 to match the login route
    pw_hash = hashlib.sha256(temp_pw.encode()).hexdigest()
    execute(conn, 'UPDATE users SET password_hash=%s WHERE id=%s', (pw_hash, uid))
    conn.commit()
    html_body = f'''<div style="font-family:-apple-system,sans-serif;max-width:500px;margin:0 auto">
        <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px;text-align:center;border-radius:12px 12px 0 0">
            <h2 style="color:#fff;margin:0">RoleCall  -  Temporary Password</h2>
        </div>
        <div style="padding:28px;background:#fff;border-radius:0 0 12px 12px;border:1px solid #e0e0db;border-top:none">
            <p style="font-size:15px;color:#1a1a17">Hi {user['name']},</p>
            <p style="font-size:14px;color:#5f5e5a;line-height:1.7">A temporary password has been generated for your RoleCall account. Use it to log in, then change your password right away.</p>
            <div style="background:#f0f8fa;border-left:4px solid #145466;padding:16px 20px;border-radius:0 8px 8px 0;margin:20px 0;text-align:center">
                <div style="font-size:11px;font-weight:700;color:#145466;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px">Temporary Password</div>
                <div style="font-size:22px;font-weight:800;font-family:monospace;color:#0d3d4d;letter-spacing:2px">{temp_pw}</div>
            </div>
            <p style="font-size:13px;color:#9b9b94;">If you did not request this, please contact your administrator.</p>
        </div>
    </div>'''
    fi = (request.json or {}).get('from_identity') or {}
    ok, msg = send_email([user['email']], 'Your RoleCall Temporary Password', html_body, fi.get('email') or None, fi.get('name') or None)
    conn.close()
    if ok: return jsonify({'ok': True})
    return jsonify({'error': msg or 'Failed to send email. Check that your Resend API key is configured in Settings → Email.'}), 500

# ─────────────────────────────────────────────
#  FAMILIES & PORTAL
# ─────────────────────────────────────────────

@app.route('/api/families')
def get_families():
    err = require_auth()
    if err: return err
    conn = get_db()
    families = fetchall(conn, '''SELECT f.*, COUNT(y.id) as youth_count
        FROM families f LEFT JOIN youth_participants y ON y.family_id=f.id
        GROUP BY f.id ORDER BY f.name''')
    conn.close()
    return jsonify(families)

@app.route('/api/families', methods=['POST'])
def create_family():
    err = require_auth()
    if err: return err
    d = request.json or {}
    fid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO families (id,name,passphrase,email,phone) VALUES (%s,%s,%s,%s,%s)',
        (fid, d.get('name',''), d.get('passphrase',''), d.get('email',''), d.get('phone','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (fid,))
    conn.close()
    return jsonify(row)

@app.route('/api/families/<fid>', methods=['PUT'])
def update_family(fid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE families SET name=%s, passphrase=%s, email=%s, phone=%s WHERE id=%s',
        (d.get('name',''), d.get('passphrase',''), d.get('email',''), d.get('phone',''), fid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/passphrase', methods=['PUT'])
def set_youth_passphrase(yid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE id=%s',
        (d.get('passphrase',''), yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/auth', methods=['POST'])
@app.route('/api/portal/login', methods=['POST'])
def portal_auth():
    d = request.json or {}
    passphrase = (d.get('passphrase') or '').strip().lower()
    if not passphrase: return jsonify({'error': 'Passphrase required'}), 400
    conn = get_db()

    # Try family passphrase first
    family = fetchone(conn, 'SELECT * FROM families WHERE LOWER(passphrase)=%s', (passphrase,))
    if family:
        members = fetchall(conn, 'SELECT * FROM youth_participants WHERE family_id=%s ORDER BY first_name', (family['id'],))
        # Stamp last login for all members
        for m in members:
            execute(conn, 'UPDATE youth_participants SET portal_last_login=NOW() WHERE id=%s', (m['id'],))
        conn.commit()
        conn.close()
        return jsonify({'type':'family','family':family,'members':members,'passphrase':passphrase})

    # Try individual youth passphrase
    youth = fetchone(conn, 'SELECT * FROM youth_participants WHERE LOWER(passphrase)=%s', (passphrase,))
    if youth:
        execute(conn, 'UPDATE youth_participants SET portal_last_login=NOW() WHERE id=%s', (youth['id'],))
        conn.commit()
        family_row = fetchone(conn, 'SELECT * FROM families WHERE id=%s', (youth.get('family_id'),)) if youth.get('family_id') else None
        conn.close()
        return jsonify({'type':'participant','participant':youth,'family':family_row,'members':[youth],'passphrase':passphrase})

    conn.close()
    return jsonify({'error': 'Passphrase not found. Please check with HWTC staff.'}), 401

@app.route('/api/portal/change-passphrase', methods=['POST'])
def portal_change_passphrase():
    d = request.json or {}
    current      = (d.get('current_passphrase') or '').strip().lower()
    new_pp       = (d.get('new_passphrase') or '').strip()
    change_type  = d.get('change_type', 'auto')  # 'family', 'individual', or 'auto'
    youth_id     = d.get('youth_id')
    if not current or not new_pp:
        return jsonify({'error': 'Current and new passphrase required'}), 400
    if len(new_pp) < 4:
        return jsonify({'error': 'New passphrase must be at least 4 characters'}), 400
    conn = get_db()
    # Try family passphrase
    family = fetchone(conn, 'SELECT * FROM families WHERE LOWER(passphrase)=%s', (current,))
    if family:
        if change_type == 'individual' and youth_id:
            # Change just this child's passphrase
            taken = fetchone(conn, 'SELECT id FROM youth_participants WHERE LOWER(passphrase)=%s AND id!=%s', (new_pp.lower(), youth_id))
            if taken: conn.close(); return jsonify({'error': 'That passphrase is already in use'}), 400
            execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE id=%s', (new_pp, youth_id))
        else:
            # Change family passphrase
            taken = fetchone(conn, 'SELECT id FROM families WHERE LOWER(passphrase)=%s AND id!=%s', (new_pp.lower(), family['id']))
            if taken: conn.close(); return jsonify({'error': 'That passphrase is already in use'}), 400
            execute(conn, 'UPDATE families SET passphrase=%s WHERE id=%s', (new_pp, family['id']))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    # Try individual youth passphrase
    youth = fetchone(conn, 'SELECT * FROM youth_participants WHERE LOWER(passphrase)=%s', (current,))
    if youth:
        taken = fetchone(conn, 'SELECT id FROM youth_participants WHERE LOWER(passphrase)=%s AND id!=%s', (new_pp.lower(), youth['id']))
        if taken: conn.close(); return jsonify({'error': 'That passphrase is already in use'}), 400
        if youth.get('family_id') and change_type != 'individual':
            # Update all family members too
            execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE family_id=%s', (new_pp, youth['family_id']))
        else:
            execute(conn, 'UPDATE youth_participants SET passphrase=%s WHERE id=%s', (new_pp, youth['id']))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    conn.close()
    return jsonify({'error': 'Current passphrase incorrect'}), 401

@app.route('/api/portal/announcements')
def get_portal_announcements():
    conn = get_db()
    prod_id = request.args.get('production_id')
    prog_id = request.args.get('program_id')
    try:
        if prod_id:
            rows = fetchall(conn, '''SELECT * FROM portal_announcements
                WHERE production_id=%s AND status='published' ORDER BY created_at DESC''', (prod_id,))
        elif prog_id:
            rows = fetchall(conn, '''SELECT * FROM portal_announcements
                WHERE program_id=%s AND status='published' ORDER BY created_at DESC''', (prog_id,))
        else:
            rows = fetchall(conn, "SELECT * FROM portal_announcements WHERE status='published' ORDER BY created_at DESC")
    except Exception as e:
        rows = []
    conn.close()
    return jsonify(rows)

@app.route('/api/portal/contact-production', methods=['POST'])
def portal_contact_production():
    d = request.json or {}
    conn = get_db()
    prod = fetchone(conn, 'SELECT * FROM productions WHERE id=%s', (d.get('production_id'),))
    conn.close()
    if not prod: return jsonify({'error': 'Not found'}), 404
    s = get_email_settings()
    recipients = get_recipient_emails(s)
    if recipients:
        send_email(recipients, f'Portal Message: {d.get("subject","")}',
            f'<p style="font-family:sans-serif">From: {d.get("from_name","")} ({d.get("from_email","")})<br/>'
            f'Production: {prod["name"]}<br/><br/>{d.get("message","")}</p>')
    return jsonify({'ok': True})


@app.route('/api/portal/program/<pid>/instructor', methods=['GET'])
def portal_program_instructor(pid):
    """Return instructor bio/photo for a program - called by portal when viewing a program."""
    conn = get_db()
    row = fetchone(conn, '''SELECT v.name as instructor_name, v.bio as instructor_bio,
        v.photo_url as instructor_photo
        FROM youth_programs yp
        LEFT JOIN volunteers v ON v.id=yp.instructor_id
        WHERE yp.id=%s''', (pid,))
    conn.close()
    if not row:
        return jsonify({})
    return jsonify(row)


@app.route('/api/portal/participant/<yid>')
def portal_get_participant(yid):
    conn = get_db()
    errors = []

    # Program enrollments
    try:
        enrollments = fetchall(conn, '''SELECT ype.*, yp.name as program_name, yp.description,
            yp.status as program_status, yp.instructor_id,
            v.name as instructor_name, v.bio as instructor_bio,
            v.photo_url as instructor_photo
            FROM youth_program_enrollments ype
            JOIN youth_programs yp ON ype.program_id=yp.id
            LEFT JOIN volunteers v ON v.id=yp.instructor_id
            WHERE ype.youth_id=%s ORDER BY ype.created_at DESC''', (yid,))
    except Exception as e:
        enrollments = []; errors.append(f'enrollments: {e}')

    # Productions
    try:
        productions = fetchall(conn, '''SELECT p.id, p.name, p.stage, p.status,
            p.description, p.image_url, p.director, p.venue,
            ypm.role as cast_role, ypm.id as member_id
            FROM youth_production_members ypm
            JOIN productions p ON ypm.production_id=p.id
            WHERE ypm.youth_id=%s ORDER BY p.name''', (yid,))
    except Exception as e:
        productions = []; errors.append(f'productions: {e}')

    # Announcements  -  from both productions and programs
    prod_ids = [p['id'] for p in productions]
    prog_ids = [e['program_id'] for e in enrollments if e.get('program_id')]
    try:
        announcements = []
        if prod_ids:
            placeholders = ','.join(['%s']*len(prod_ids))
            announcements += fetchall(conn, f'''SELECT * FROM portal_announcements
                WHERE production_id IN ({placeholders}) AND status='published'
                ORDER BY created_at DESC''', tuple(prod_ids))
        if prog_ids:
            placeholders = ','.join(['%s']*len(prog_ids))
            announcements += fetchall(conn, f'''SELECT * FROM portal_announcements
                WHERE program_id IN ({placeholders}) AND status='published'
                ORDER BY created_at DESC''', tuple(prog_ids))
        announcements.sort(key=lambda a: a.get('created_at',''), reverse=True)
    except Exception as e:
        announcements = []; errors.append(f'announcements: {e}')

    # Files  -  fetch for all productions and programs the participant is in
    try:
        files = []
        all_placeholders = []
        all_vals = []
        if prod_ids:
            ph = ','.join(['%s']*len(prod_ids))
            prod_files = fetchall(conn, f'SELECT * FROM portal_files WHERE production_id IN ({ph}) AND (description IS NULL OR description!=\'__folder__\') ORDER BY folder, title', tuple(prod_ids))
            files.extend(prod_files)
        if prog_ids:
            ph = ','.join(['%s']*len(prog_ids))
            prog_files = fetchall(conn, f'SELECT * FROM portal_files WHERE program_id IN ({ph}) AND (description IS NULL OR description!=\'__folder__\') ORDER BY folder, title', tuple(prog_ids))
            files.extend(prog_files)
    except Exception as e:
        files = []; errors.append(f'files: {e}')

    conn.close()
    if errors:
        app.logger.error(f'portal_get_participant {yid}: {errors}')

    return jsonify({
        'enrollments': enrollments,
        'productions': productions,
        'announcements': announcements,
        'files': files,
        '_errors': errors if errors else None,
    })

@app.route('/api/portal/youth/<yid>/profile')
def portal_youth_profile(yid):
    conn = get_db()
    youth = fetchone(conn, '''SELECT y.*, f.name as family_name
        FROM youth_participants y LEFT JOIN families f ON y.family_id=f.id
        WHERE y.id=%s''', (yid,))
    if not youth: conn.close(); return jsonify({'error': 'Not found'}), 404
    youth['guardians'] = fetchall(conn, 'SELECT * FROM youth_guardians WHERE youth_id=%s ORDER BY is_primary DESC', (yid,))
    youth['emergency'] = fetchall(conn, 'SELECT * FROM youth_emergency_contacts WHERE youth_id=%s', (yid,))
    youth['authorized_pickups'] = fetchall(conn, 'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority', (yid,))
    youth['waivers'] = fetchall(conn, '''SELECT yw.*, wt.name as type_name, wt.template_body, wt.can_sign_online
        FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id
        WHERE yw.youth_id=%s ORDER BY yw.signed_date DESC''', (yid,))
    # Get signable waivers not yet signed  -  includes program-required ones
    signed_ids = [w['waiver_type_id'] for w in youth['waivers']]
    all_signable = fetchall(conn, "SELECT * FROM waiver_types WHERE can_sign_online=TRUE ORDER BY name")
    # Also include program-required waivers even if not marked can_sign_online (show as required)
    prog_ids = [e['program_id'] for e in fetchall(conn,
        'SELECT program_id FROM youth_program_enrollments WHERE youth_id=%s', (yid,))]
    prog_required = []
    if prog_ids:
        placeholders = ','.join(['%s']*len(prog_ids))
        prog_required = fetchall(conn, f'''SELECT wt.* FROM program_required_waivers prw
            JOIN waiver_types wt ON prw.waiver_type_id=wt.id
            WHERE prw.program_id IN ({placeholders})''', tuple(prog_ids))
    # Merge: signable + program-required not yet signed, deduplicated
    all_needed = {w['id']: w for w in all_signable}
    for w in prog_required:
        if w['id'] not in all_needed:
            w = dict(w); w['required_by_program'] = True
            all_needed[w['id']] = w
    youth['signable_waivers'] = [w for wid2, w in all_needed.items() if wid2 not in signed_ids]
    conn.close()
    return jsonify(youth)

@app.route('/api/portal/youth/<yid>/shirt-size', methods=['POST'])
def portal_set_shirt_size(yid):
    d = request.json or {}
    size = d.get('shirt_size','').strip()
    valid = ['','YXS','YS','YM','YL','YXL','AS','AM','AL','AXL','A2XL']
    if size not in valid:
        return jsonify({'error': 'Invalid size'}), 400
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET shirt_size=%s WHERE id=%s', (size or None, yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'shirt_size': size})

@app.route('/api/portal/youth/<yid>/sign-waiver', methods=['POST'])
def portal_sign_youth_waiver(yid):
    d = request.json or {}
    waiver_type_id = d.get('waiver_type_id','').strip()
    signed_name = d.get('signed_name','').strip()
    if not waiver_type_id or not signed_name:
        return jsonify({'error': 'Waiver type and signature required'}), 400
    conn = get_db()
    # Verify waiver type exists and can be signed online
    wt = fetchone(conn, 'SELECT * FROM waiver_types WHERE id=%s AND can_sign_online=TRUE', (waiver_type_id,))
    if not wt:
        conn.close()
        return jsonify({'error': 'This waiver cannot be signed online'}), 400
    # Check not already signed
    existing = fetchone(conn, 'SELECT id FROM youth_waivers WHERE youth_id=%s AND waiver_type_id=%s', (yid, waiver_type_id))
    if existing:
        conn.close()
        return jsonify({'error': 'Waiver already signed'}), 400
    wid = str(uuid.uuid4())
    from datetime import date
    execute(conn, '''INSERT INTO youth_waivers
        (id, youth_id, waiver_type_id, signed_date, signed_name, signed_via)
        VALUES (%s, %s, %s, %s, %s, %s)''',
        (wid, yid, waiver_type_id, date.today().isoformat(), signed_name, 'portal'))
    conn.commit()
    row = fetchone(conn, '''SELECT yw.*, wt.name as type_name
        FROM youth_waivers yw JOIN waiver_types wt ON yw.waiver_type_id=wt.id
        WHERE yw.id=%s''', (wid,))
    conn.close()
    return jsonify(row)

@app.route('/api/portal/youth/<yid>/request-update', methods=['POST'])
def portal_youth_request_update(yid):
    d = request.json or {}
    conn = get_db()
    # Log a note for staff to review
    nid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO pending_hours (id,volunteer_id,event,date,hours,notes,status)
        VALUES (%s,%s,'Profile Update Request',CURRENT_DATE,0,%s,'pending_review')''',
        (nid, yid, json.dumps(d)))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/files')
def portal_get_files():
    program_id    = request.args.get('program_id') or request.args.get('context_id') if request.args.get('context_type','production')=='program' else None
    production_id = request.args.get('production_id') or (request.args.get('context_id') if request.args.get('context_type','production')=='production' else None)
    conn = get_db()
    if program_id:
        rows = fetchall(conn, "SELECT * FROM portal_files WHERE program_id=%s AND (description IS NULL OR description!='__folder__') ORDER BY folder, title", (program_id,))
    elif production_id:
        rows = fetchall(conn, "SELECT * FROM portal_files WHERE production_id=%s AND (description IS NULL OR description!='__folder__') ORDER BY folder, title", (production_id,))
    else:
        rows = fetchall(conn, "SELECT * FROM portal_files WHERE description IS NULL OR description!='__folder__' ORDER BY created_at DESC")
    conn.close()
    return jsonify(rows)

@app.route('/api/portal/callout')
def portal_callout():
    """System-wide announcement shown on portal login screen."""
    conn = get_db()
    try:
        row = fetchone(conn, "SELECT value FROM settings WHERE key='portal_callout'")
        conn.close()
        if row:
            import json as _json
            val = _json.loads(row['value']) if isinstance(row['value'], str) else row['value']
            return jsonify({'callout': val})
    except Exception:
        conn.close()
    return jsonify({'callout': None})

@app.route('/api/portal/instructor-login', methods=['POST'])
def portal_instructor_login():
    d = request.json or {}
    email    = (d.get('email') or '').strip().lower()
    password = d.get('password','')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    conn = get_db()
    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    user = fetchone(conn, 'SELECT * FROM users WHERE LOWER(email)=%s AND password_hash=%s', (email, pw_hash))
    if not user:
        conn.close()
        return jsonify({'error': 'Invalid email or password'}), 401
    perms = {}
    try: perms = json.loads(user.get('role_permissions') or '{}')
    except Exception: pass
    conn.close()
    return jsonify({
        'type': 'instructor',
        'user': {'id': user['id'], 'name': user['name'], 'email': user['email'],
                 'role': user['role'], 'permissions': perms}
    })

# ─────────────────────────────────────────────
#  PRODUCTIONS (additional routes)
# ─────────────────────────────────────────────

@app.route('/api/productions/<pid>/youth-members')
def get_prod_youth_members(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT ypm.*, y.first_name, y.last_name,
        y.first_name||' '||y.last_name as name
        FROM youth_production_members ypm
        JOIN youth_participants y ON ypm.youth_id=y.id
        WHERE ypm.production_id=%s ORDER BY y.last_name, y.first_name''', (pid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/productions/<pid>/youth-members', methods=['POST'])
def enroll_youth_in_prod(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not d:
        return jsonify({'error': 'No data received'}), 400
    conn = get_db()
    try:
        youth_ids = d.get('youth_ids') or ([d.get('youth_id')] if d.get('youth_id') else [])
        if not youth_ids:
            conn.close()
            return jsonify({'error': 'No youth specified'}), 400
        enrolled = 0
        skipped = 0
        for yid in youth_ids:
            if not yid: continue
            mid = str(uuid.uuid4())
            existing = fetchone(conn, 'SELECT id FROM youth_production_members WHERE production_id=%s AND youth_id=%s', (pid, yid))
            if existing:
                skipped += 1
                continue
            execute(conn, '''INSERT INTO youth_production_members (id,production_id,youth_id,role)
                VALUES (%s,%s,%s,%s)''',
                (mid, pid, yid, d.get('role','')))
            enrolled += 1
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'enrolled': enrolled, 'skipped': skipped})
    except Exception as e:
        app.logger.error(f'enroll_youth_in_prod error: {e}')
        try: conn.rollback(); conn.close()
        except Exception: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/productions/<pid>/youth-members/<mid>', methods=['PUT'])
def update_youth_prod_member(pid, mid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_production_members SET role=%s WHERE id=%s AND production_id=%s',
        (d.get('role',''), mid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/youth-members/<mid>', methods=['DELETE'])
def unenroll_youth_from_prod(pid, mid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_production_members WHERE id=%s AND production_id=%s', (mid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/conflicts')
def get_production_conflicts(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT sc.*, v.name as person_name,
        e.name as event_name
        FROM schedule_conflicts sc
        LEFT JOIN volunteers v ON sc.volunteer_id=v.id
        LEFT JOIN events e ON sc.event_id=e.id
        WHERE sc.production_id=%s ORDER BY sc.created_at DESC''', (pid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/productions/<pid>/conflicts', methods=['POST'])
def add_production_conflict(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    cid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO schedule_conflicts
        (id,production_id,event_id,volunteer_id,status,event_date,notes,approved,source)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (cid, pid, d.get('event_id') or None, d.get('volunteer_id') or None,
         d.get('status','absent'), d.get('event_date') or None,
         d.get('notes',''), d.get('approved', False), d.get('source','staff')))
    conn.commit()
    row = fetchone(conn, '''SELECT sc.*, v.name as person_name, e.name as event_name
        FROM schedule_conflicts sc
        LEFT JOIN volunteers v ON sc.volunteer_id=v.id
        LEFT JOIN events e ON sc.event_id=e.id WHERE sc.id=%s''', (cid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/conflicts/<cid>', methods=['PUT'])
def update_production_conflict(pid, cid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE schedule_conflicts SET
        status=%s, event_date=%s, notes=%s, approved=%s WHERE id=%s AND production_id=%s''',
        (d.get('status','absent'), d.get('event_date') or None,
         d.get('notes',''), d.get('approved', False), cid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/conflicts/<cid>', methods=['DELETE'])
def delete_production_conflict(pid, cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM schedule_conflicts WHERE id=%s AND production_id=%s', (cid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/team')
def get_production_team(pid):
    conn = get_db()
    # Return public-facing team bios (headshots, bios  -  no volunteer required)
    rows = fetchall(conn, '''SELECT * FROM production_team_bios
        WHERE production_id=%s ORDER BY sort_order, name''', (pid,))
    # Also include production_members (crew with volunteer links) as fallback
    if not rows:
        rows = fetchall(conn, '''SELECT pm.id, pm.role, pm.bio,
            pm.photo_url as headshot_url,
            v.name, pm.department, pm.status
            FROM production_members pm
            JOIN volunteers v ON pm.volunteer_id=v.id
            WHERE pm.production_id=%s ORDER BY pm.department, v.name''', (pid,))
    conn.close()
    return jsonify(rows)

@app.route('/api/productions/<pid>/team', methods=['POST'])
def add_team_bio(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not d.get('name'):
        return jsonify({'error': 'Name is required'}), 400
    mid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO production_team_bios
        (id, production_id, name, role, bio, headshot_url, sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (mid, pid, (d.get('name') or '').strip(), (d.get('role') or '').strip(),
         (d.get('bio') or '').strip(), (d.get('headshot_url') or '').strip(),
         d.get('sort_order', 0)))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM production_team_bios WHERE id=%s', (mid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/team/<mid>', methods=['PUT'])
def update_team_bio(pid, mid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE production_team_bios SET
        name=%s, role=%s, bio=%s, headshot_url=%s, sort_order=%s
        WHERE id=%s AND production_id=%s''',
        ((d.get('name') or '').strip(), (d.get('role') or '').strip(),
         (d.get('bio') or '').strip(), (d.get('headshot_url') or '').strip(),
         d.get('sort_order', 0), mid, pid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM production_team_bios WHERE id=%s', (mid,))
    conn.close()
    return jsonify(row or {'ok': True})

@app.route('/api/productions/<pid>/team/<mid>', methods=['DELETE'])
def delete_team_bio(pid, mid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_team_bios WHERE id=%s AND production_id=%s', (mid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/general-content')
def get_general_content(pid):
    conn = get_db()
    row = fetchone(conn, 'SELECT general_content FROM productions WHERE id=%s', (pid,))
    conn.close()
    return jsonify({'content': row['general_content'] if row else ''})

@app.route('/api/productions/<pid>/general-content', methods=['PUT'])
def save_general_content(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE productions SET general_content=%s WHERE id=%s',
        (d.get('content',''), pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/about', methods=['PUT'])
def update_production_about(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE productions SET
        director=%s, venue=%s, performance_location=%s,
        start_date=%s, end_date=%s, description=%s,
        portal_color=%s, portal_image_url=%s WHERE id=%s''',
        (d.get('director',''), d.get('venue',''), d.get('performance_location',''),
         d.get('start_date') or None, d.get('end_date') or None,
         d.get('description',''), d.get('portal_color',''), d.get('portal_image_url',''), pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/announcements', methods=['POST'])
def create_portal_announcement(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    aid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO portal_announcements
        (id,production_id,title,body,status,created_by)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (aid, pid, d.get('title',''), d.get('body',''),
         d.get('status','draft'), session.get('user_name','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM portal_announcements WHERE id=%s', (aid,))
    conn.close()
    return jsonify(row)

@app.route('/api/productions/<pid>/announcements/<aid>', methods=['PUT'])
def update_portal_announcement(pid, aid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE portal_announcements SET title=%s, body=%s, status=%s WHERE id=%s AND production_id=%s',
        (d.get('title',''), d.get('body',''), d.get('status','draft'), aid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/announcements/<aid>', methods=['DELETE'])
def delete_portal_announcement(pid, aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM portal_announcements WHERE id=%s AND production_id=%s', (aid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/announcements/<aid>/push', methods=['POST'])
def push_announcement(pid, aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE portal_announcements SET status='published' WHERE id=%s AND production_id=%s", (aid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth-programs/<pid>/required-waivers', methods=['GET'])
def get_program_required_waivers(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        rows = fetchall(conn, '''SELECT prw.*, wt.name as waiver_name, wt.can_sign_online
            FROM program_required_waivers prw
            JOIN waiver_types wt ON prw.waiver_type_id=wt.id
            WHERE prw.program_id=%s ORDER BY wt.name''', (pid,))
    except Exception:
        rows = []
    conn.close()
    return jsonify(rows)

@app.route('/api/youth-programs/<pid>/required-waivers', methods=['POST'])
def add_program_required_waiver(pid):
    err = require_permission('youth')
    if err: return err
    d = request.json or {}
    rid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, 'INSERT INTO program_required_waivers (id,program_id,waiver_type_id) VALUES (%s,%s,%s)',
                (rid, pid, d.get('waiver_type_id')))
        conn.commit()
        row = fetchone(conn, '''SELECT prw.*, wt.name as waiver_name, wt.can_sign_online
            FROM program_required_waivers prw JOIN waiver_types wt ON prw.waiver_type_id=wt.id
            WHERE prw.id=%s''', (rid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 400

@app.route('/api/youth-programs/<pid>/required-waivers/<wid>', methods=['DELETE'])
def remove_program_required_waiver(pid, wid):
    err = require_permission('youth')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM program_required_waivers WHERE program_id=%s AND waiver_type_id=%s', (pid, wid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/waivers', methods=['POST'])
def add_prod_waiver(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    rid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO production_required_waivers (id,production_id,waiver_type_id) VALUES (%s,%s,%s)',
        (rid, pid, d.get('waiver_type_id')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/productions/<pid>/waivers/<wid>', methods=['DELETE'])
def remove_prod_waiver(pid, wid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM production_required_waivers WHERE production_id=%s AND waiver_type_id=%s', (pid, wid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  KIOSK ROUTES
# ─────────────────────────────────────────────

@app.route('/api/kiosk/interest-types')
def kiosk_interest_types():
    conn = get_db()
    types = fetchall(conn, 'SELECT id, name, color FROM interest_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/kiosk/volunteer-profile/<vol_id>')
def kiosk_volunteer_profile(vol_id):
    conn = get_db()
    vol = fetchone(conn,
        "SELECT id, name, phone, interests, COALESCE(background_check_status,'none') as background_check_status FROM volunteers WHERE id=%s AND status='active'",
        (vol_id,))
    if not vol: conn.close(); return jsonify({'error': 'Not found'}), 404
    ec = fetchone(conn, 'SELECT name, relationship, phone FROM volunteer_emergency_contacts WHERE volunteer_id=%s ORDER BY created_at DESC LIMIT 1', (vol_id,))
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
        "SELECT id, name, phone, interests FROM volunteers WHERE LOWER(name) LIKE %s AND status='active' ORDER BY name LIMIT 20",
        ('%' + q + '%',))
    conn.close()
    return jsonify(vols)

@app.route('/api/kiosk/events')
def kiosk_events():
    conn = get_db()
    events = fetchall(conn, """
        SELECT e.*,
               p.name as production_name,
               COALESCE(p.stage,'mainstage') as stage,
               p.stage as production_stage
        FROM events e
        LEFT JOIN productions p ON e.production_id=p.id
        WHERE e.status='open'
           OR (e.status IN ('draft','published','in_progress')
               AND e.event_date::date >= (CURRENT_DATE - INTERVAL '1 day')
               AND e.event_date::date <= (CURRENT_DATE + INTERVAL '1 day'))
        ORDER BY CASE WHEN e.status='open' THEN 0 ELSE 1 END, e.event_date ASC NULLS LAST
    """)
    conn.close()
    return jsonify(events)

@app.route('/api/kiosk/submit', methods=['POST'])
def kiosk_submit():
    d = request.json or {}
    if not d.get('volunteer_id') or not d.get('event') or not d.get('hours'):
        return jsonify({'error': 'Missing required fields'}), 400
    try:
        hours = float(d.get('hours',0))
        if hours <= 0 or hours > 24:
            return jsonify({'error': 'Hours must be between 0.5 and 24'}), 400
    except Exception:
        return jsonify({'error': 'Invalid hours value'}), 400
    pid = str(uuid.uuid4())
    conn = get_db()
    today_row = fetchone(conn, "SELECT CURRENT_DATE::text as today")
    today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()
    execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        (pid, d.get('volunteer_id'), d.get('event',''), d.get('event_id'), today, hours, d.get('role',''), d.get('notes','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/waiver-check')
def kiosk_waiver_check():
    vol_id = request.args.get('volunteer_id')
    if not vol_id: return jsonify({'issues': [], 'all_clear': True})
    conn = get_db()
    from datetime import date as _date
    today = _date.today()
    required = fetchall(conn, '''SELECT wt.* FROM waiver_types wt
        WHERE wt.required_all=TRUE OR wt.required_for_volunteering=TRUE''')
    issues = []
    for wt in required:
        signed = fetchone(conn, '''SELECT * FROM volunteer_waivers WHERE volunteer_id=%s AND waiver_type_id=%s
            ORDER BY signed_date DESC LIMIT 1''', (vol_id, wt['id']))
        if not signed:
            issues.append({'waiver_type_id': wt['id'], 'name': wt['name'],
                'description': wt.get('description',''), 'status': 'missing',
                'can_sign_online': bool(wt.get('can_sign_online')),
                'template_body': wt.get('template_body','')})
        elif wt.get('expires_days') and signed.get('expiry_date'):
            try:
                exp = __import__('datetime').date.fromisoformat(str(signed['expiry_date'])[:10])
                if exp < today:
                    issues.append({'waiver_type_id': wt['id'], 'name': wt['name'],
                        'description': wt.get('description',''), 'status': 'expired',
                        'can_sign_online': bool(wt.get('can_sign_online')),
                        'template_body': wt.get('template_body','')})
            except Exception:
                pass
    conn.close()
    return jsonify({'issues': issues, 'all_clear': len(issues) == 0})

@app.route('/api/kiosk/sign-waiver', methods=['POST'])
def kiosk_sign_waiver():
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    waiver_type_id = d.get('waiver_type_id')
    signed_name = d.get('signed_name', '')
    if not vol_id or not waiver_type_id: return jsonify({'error': 'Missing fields'}), 400
    conn = get_db()
    wt = fetchone(conn, 'SELECT * FROM waiver_types WHERE id=%s', (waiver_type_id,))
    if not wt: conn.close(); return jsonify({'error': 'Waiver type not found'}), 404
    from datetime import date as _date, timedelta
    today = _date.today()
    expiry = None
    if wt.get('expires_days'):
        expiry = (today + timedelta(days=int(wt['expires_days']))).isoformat()
    wid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO volunteer_waivers
        (id,volunteer_id,waiver_type_id,signed_date,expiry_date,signed_name,signed_via)
        VALUES (%s,%s,%s,%s,%s,%s,'kiosk')''',
        (wid, vol_id, waiver_type_id, today.isoformat(), expiry, signed_name))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/update-profile', methods=['POST'])
def kiosk_update_profile():
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    if not vol_id: return jsonify({'error': 'Missing volunteer_id'}), 400
    conn = get_db()
    updates = []
    params = []
    if d.get('phone') is not None:
        updates.append('phone=%s'); params.append(d['phone'])
    if d.get('interests') is not None:
        updates.append('interests=%s'); params.append(json.dumps(d.get('interests','[]')))
    if updates:
        execute(conn, f"UPDATE volunteers SET {','.join(updates)} WHERE id=%s", tuple(params + [vol_id]))
    if d.get('emergency_contact'):
        ec = d['emergency_contact']
        existing = fetchone(conn, 'SELECT id FROM volunteer_emergency_contacts WHERE volunteer_id=%s', (vol_id,))
        if existing:
            execute(conn, 'UPDATE volunteer_emergency_contacts SET name=%s, relationship=%s, phone=%s WHERE volunteer_id=%s',
                (ec.get('name',''), ec.get('relationship',''), ec.get('phone',''), vol_id))
        else:
            ecid = str(uuid.uuid4())
            execute(conn, 'INSERT INTO volunteer_emergency_contacts (id,volunteer_id,name,relationship,phone) VALUES (%s,%s,%s,%s,%s)',
                (ecid, vol_id, ec.get('name',''), ec.get('relationship',''), ec.get('phone','')))
    conn.commit()
    # Log update request for admin review
    pid = str(uuid.uuid4())
    execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,date,hours,notes,status) VALUES (%s,%s,'Profile Update',CURRENT_DATE,0,'Profile update submitted via kiosk','pending_profile')",
        (pid, vol_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/session/active/<vol_id>')
def kiosk_active_session(vol_id):
    conn = get_db()
    s = fetchone(conn, "SELECT * FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
    conn.close()
    if s: return jsonify({'active': True, 'session': s})
    return jsonify({'active': False})

@app.route('/api/kiosk/session/begin', methods=['POST'])
def kiosk_begin_session():
    d = request.json or {}
    vol_id          = d.get('volunteer_id') or ''
    event_id        = d.get('event_id') or None
    role            = (d.get('role') or '').strip()
    override_reason = (d.get('override_reason') or '').strip()
    if not vol_id: return jsonify({'error': 'Missing volunteer_id'}), 400
    conn = get_db()
    # Require event or override reason
    if not event_id and not override_reason:
        conn.close()
        return jsonify({'error': 'Please select an event or provide an override reason.'}), 400
    # Check event is open if one is specified
    if event_id:
        evt = fetchone(conn, 'SELECT status, name FROM events WHERE id=%s', (event_id,))
        if evt and evt.get('status') != 'open':
            conn.close()
            return jsonify({'error': 'This event is not open yet. Please wait for staff to open it.'}), 400
    existing = fetchone(conn, "SELECT id FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
    if existing: conn.close(); return jsonify({'error': 'Already volunteering  -  please stop your current session first.'}), 400
    event_name = d.get('event_name','')
    if event_id and not event_name:
        evt = fetchone(conn, 'SELECT name FROM events WHERE id=%s', (event_id,))
        if evt: event_name = evt['name']
    if not event_name and override_reason:
        event_name = f'Override: {override_reason}'
    sid = str(uuid.uuid4())
    execute(conn, "INSERT INTO kiosk_sessions (id,volunteer_id,event_id,event_name,role,status) VALUES (%s,%s,%s,%s,%s,'active')",
        (sid, vol_id, event_id or None, event_name, role))
    conn.commit()
    session_row = fetchone(conn, 'SELECT * FROM kiosk_sessions WHERE id=%s', (sid,))
    conn.close()
    return jsonify({'ok': True, 'session_id': sid, 'started_at': str(session_row['started_at']),
                    'is_override': bool(override_reason)})

@app.route('/api/kiosk/session/stop', methods=['POST'])
def kiosk_stop_session():
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    role   = d.get('role','')
    if not vol_id: return jsonify({'error': 'Missing volunteer_id'}), 400
    conn = get_db()
    try:
        sess = fetchone(conn, "SELECT * FROM kiosk_sessions WHERE volunteer_id=%s AND status='active'", (vol_id,))
        if not sess: conn.close(); return jsonify({'error': 'No active session found'}), 400
        time_row = fetchone(conn, "SELECT EXTRACT(EPOCH FROM (NOW() - started_at)) as secs FROM kiosk_sessions WHERE id=%s", (sess['id'],))
        elapsed_secs  = float(time_row['secs']) if time_row and time_row['secs'] else 0
        elapsed_hours = round(max(0.25, elapsed_secs / 3600), 2)
        today_row = fetchone(conn, "SELECT CURRENT_DATE::text as today")
        today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()
        execute(conn, "UPDATE kiosk_sessions SET ended_at=NOW(), hours=%s, status='completed', role=%s WHERE id=%s",
            (elapsed_hours, role or sess['role'], sess['id']))
        pid = str(uuid.uuid4())
        # Override sessions (no event) need admin review before approval
        hours_status = 'pending' if sess.get('event_id') else 'pending_review'
        override_note = ' [Override  -  no event selected]' if not sess.get('event_id') else ''
        execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (pid, vol_id, sess['event_name'] or 'Volunteer Session', sess['event_id'],
             today, elapsed_hours, role or sess['role'],
             'Recorded via kiosk timer' + override_note, hours_status))
        conn.commit()
        try:
            s = get_email_settings()
            if s.get('alert_pending_hours'):
                recipients = get_recipient_emails(s)
                vol = fetchone(conn, 'SELECT name FROM volunteers WHERE id=%s', (vol_id,))
                vol_name = vol['name'] if vol else 'A volunteer'
                if recipients:
                    send_email(recipients, 'RoleCall  -  Hours Submitted: ' + vol_name,
                        '<p style="font-family:sans-serif"><strong>' + vol_name + '</strong> logged <strong>'
                        + str(elapsed_hours) + ' hours</strong> via kiosk timer for <strong>'
                        + (sess['event_name'] or 'a session') + '</strong>.</p>')
        except Exception:
            pass
        conn.close()
        return jsonify({'ok': True, 'hours': elapsed_hours})
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/kiosk/session/stop-by-id', methods=['POST'])
def kiosk_stop_session_by_id():
    d = request.json or {}
    sid = d.get('session_id')
    if not sid: return jsonify({'error': 'Missing session_id'}), 400
    conn = get_db()
    sess = fetchone(conn, "SELECT * FROM kiosk_sessions WHERE id=%s AND status='active'", (sid,))
    if not sess: conn.close(); return jsonify({'error': 'Session not found or already stopped'}), 404
    time_row = fetchone(conn, "SELECT EXTRACT(EPOCH FROM (NOW() - started_at)) as secs FROM kiosk_sessions WHERE id=%s", (sid,))
    elapsed_secs  = float(time_row['secs']) if time_row and time_row['secs'] else 0
    elapsed_hours = round(max(0.25, elapsed_secs / 3600), 2)
    today_row = fetchone(conn, "SELECT CURRENT_DATE::text as today")
    today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()
    execute(conn, "UPDATE kiosk_sessions SET ended_at=NOW(), hours=%s, status='completed' WHERE id=%s", (elapsed_hours, sid))
    pid = str(uuid.uuid4())
    execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        (pid, sess['volunteer_id'], sess['event_name'] or 'Volunteer Session',
         sess['event_id'], today, elapsed_hours, sess['role'], 'Stopped by ELIC'))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'hours': elapsed_hours})

@app.route('/api/kiosk/active-sessions')
def kiosk_active_sessions():
    conn = get_db()
    rows = fetchall(conn, """
        SELECT ks.id, ks.volunteer_id, ks.event_id, ks.event_name, ks.role,
               ks.started_at, ks.status, v.name as volunteer_name,
               EXTRACT(EPOCH FROM (NOW() - ks.started_at)) as elapsed_secs
        FROM kiosk_sessions ks
        JOIN volunteers v ON ks.volunteer_id=v.id
        WHERE ks.status='active' ORDER BY ks.started_at ASC
    """)
    conn.close()
    return jsonify(rows)

@app.route('/api/kiosk/log-full-event', methods=['POST'])
def kiosk_log_full_event():
    d = request.json or {}
    vol_id   = d.get('volunteer_id')
    event_id = d.get('event_id')
    role     = d.get('role','')
    if not vol_id or not event_id: return jsonify({'error': 'Missing volunteer_id or event_id'}), 400
    conn = get_db()
    evt = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (event_id,))
    if not evt: conn.close(); return jsonify({'error': 'Event not found'}), 404
    hours = None
    if evt.get('start_time') and evt.get('end_time'):
        try:
            from datetime import datetime as _dt
            fmt = '%H:%M'
            start = _dt.strptime(str(evt['start_time'])[:5], fmt)
            end   = _dt.strptime(str(evt['end_time'])[:5], fmt)
            diff  = (end - start).seconds / 3600
            if diff > 0: hours = round(diff, 2)
        except Exception: pass
    if not hours: conn.close(); return jsonify({'error': 'Event has no start/end time set.'}), 400
    today_row = fetchone(conn, "SELECT CURRENT_DATE::text as today")
    today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()
    sid = str(uuid.uuid4())
    execute(conn, "INSERT INTO kiosk_sessions (id,volunteer_id,event_id,event_name,role,started_at,ended_at,hours,status) VALUES (%s,%s,%s,%s,%s,NOW(),NOW(),%s,'completed')",
        (sid, vol_id, event_id, evt['name'], role, hours))
    pid = str(uuid.uuid4())
    execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
        (pid, vol_id, evt['name'], event_id, today, hours, role, 'Full event  -  logged via kiosk'))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'hours': hours, 'event': evt['name']})

@app.route('/api/kiosk/submit-independent', methods=['POST'])
def kiosk_submit_independent():
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    activity = (d.get('activity') or '').strip()
    hours = float(d.get('hours') or 0)
    if not vol_id or not activity or hours <= 0:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    vol = fetchone(conn, 'SELECT id, name FROM volunteers WHERE id=%s', (vol_id,))
    if not vol:
        conn.close(); return jsonify({'error': 'Volunteer not found'}), 404
    from datetime import date
    today = date.today().isoformat()
    pid = str(uuid.uuid4())
    execute(conn, """INSERT INTO pending_hours
        (id, volunteer_id, event, event_id, date, hours, role, notes, status)
        VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,'pending')""",
        (pid, vol_id, activity, today, hours,
         'Independent / Off-site', d.get('description','').strip()))
    conn.commit()
    # Notify admins
    try:
        s = get_email_settings()
        recipients = get_recipient_emails(s)
        if recipients and s.get('alert_pending_hours'):
            send_email(recipients,
                f'RoleCall  -  Independent Hours Submitted: {vol["name"]}',
                f'<p style="font-family:sans-serif"><strong>{vol["name"]}</strong> submitted <strong>{hours}h</strong> of independent work: <strong>{activity}</strong>.</p><p style="font-family:sans-serif;color:#666">Please review and approve in RoleCall → Hours.</p>')
    except Exception:
        pass
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/sign-in', methods=['POST'])
def kiosk_youth_sign_in():
    d = request.json or {}
    conn = get_db()
    yid = d.get('youth_id')
    eid = d.get('event_id')
    if not yid: conn.close(); return jsonify({'error': 'Missing youth_id'}), 400
    existing = fetchone(conn, "SELECT id FROM youth_sign_ins WHERE youth_id=%s AND event_id=%s AND signed_out_at IS NULL", (yid, eid))
    if existing: conn.close(); return jsonify({'error': 'Already signed in'}), 400
    sid = str(uuid.uuid4())
    execute(conn, "INSERT INTO youth_sign_ins (id,youth_id,event_id,signed_in_at) VALUES (%s,%s,%s,NOW())",
        (sid, yid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/kiosk/sign-out', methods=['POST'])
def kiosk_youth_sign_out():
    d = request.json or {}
    conn = get_db()
    yid = d.get('youth_id')
    eid = d.get('event_id')
    execute(conn, "UPDATE youth_sign_ins SET signed_out_at=NOW() WHERE youth_id=%s AND event_id=%s AND signed_out_at IS NULL",
        (yid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



# ─────────────────────────────────────────────
#  APPLICATIONS (volunteer interest form)
# ─────────────────────────────────────────────

@app.route('/api/join/interest-types')
def join_interest_types():
    conn = get_db()
    types = fetchall(conn, 'SELECT id, name, color, sub_options, sub_options_label FROM interest_types ORDER BY name')
    conn.close()
    return jsonify(types)

@app.route('/api/join/submit', methods=['POST'])
def join_submit():
    d = request.json or {}
    if not d.get('name') or not d.get('email'):
        return jsonify({'error': 'Name and email are required'}), 400
    aid = str(uuid.uuid4())
    conn = get_db()
    try:
        sub_selections = json.dumps(d.get('sub_selections') or {})
        execute(conn, '''INSERT INTO volunteer_applications
            (id, name, email, phone, pronouns, is_adult, interests, how_heard, notes, status, sub_selections, employer_program)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s)''',
            (aid, (d.get('name') or '').strip(), (d.get('email') or '').strip().lower(),
             (d.get('phone') or '').strip(), (d.get('pronouns') or '').strip(),
             d.get('is_adult', True), json.dumps(d.get('interests', [])),
             (d.get('how_heard') or '').strip(), (d.get('notes') or '').strip(),
             sub_selections, (d.get('employer_program') or '').strip()))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        app.logger.error(f'join_submit: {e}')
        return jsonify({'error': 'Submission failed. Please try again.'}), 500
    try:
        s = get_email_settings()
        recipients = get_recipient_emails(s)
        if recipients:
            interests_str = ', '.join(d.get('interests', [])) or 'None specified'
            age_str = '18 or older' if d.get('is_adult', True) else 'Under 18'
            # Build sub-selections rows
            sub_rows = ''
            sub_sel = d.get('sub_selections') or {}
            for interest, selections in sub_sel.items():
                if selections:
                    sub_rows += f'<tr><td style="padding:8px;font-weight:600;color:#666;width:140px">&nbsp;&nbsp;↳ {interest}</td><td style="padding:8px">{", ".join(selections)}</td></tr>'
            html_body = f'''<div style="font-family:-apple-system,sans-serif;max-width:600px">
                <h2 style="color:#0d3d4d">New Volunteer Interest Submission</h2>
                <table style="width:100%;border-collapse:collapse;font-size:14px">
                  <tr><td style="padding:8px;font-weight:600;color:#666;width:140px">Name</td><td style="padding:8px">{d.get('name','')}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Email</td><td style="padding:8px">{d.get('email','')}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">Phone</td><td style="padding:8px">{d.get('phone',' - ')}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Pronouns</td><td style="padding:8px">{d.get('pronouns',' - ') or ' - '}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">Age</td><td style="padding:8px">{age_str}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Interests</td><td style="padding:8px">{interests_str}</td></tr>
                  {sub_rows}
                  <tr><td style="padding:8px;font-weight:600;color:#666">How they heard</td><td style="padding:8px">{d.get('how_heard',' - ')}</td></tr>
                  <tr style="background:#f9f9f9"><td style="padding:8px;font-weight:600;color:#666">Employer Program</td><td style="padding:8px">{d.get('employer_program',' - ') or ' - '}</td></tr>
                  <tr><td style="padding:8px;font-weight:600;color:#666">Notes</td><td style="padding:8px">{d.get('notes',' - ') or ' - '}</td></tr>
                </table>
            </div>'''
            send_email(recipients, f'New Volunteer Interest  -  {d["name"]}', html_body)
    except Exception:
        pass
    # If Director is selected, send director interest form email
    try:
        interests = d.get('interests', [])
        if any('director' in i.lower() for i in interests):
            applicant_email = (d.get('email') or '').strip()
            applicant_name  = (d.get('name') or '').strip()
            if applicant_email:
                form_url = f'https://rolecall.hwtco.org/director-interest?email={applicant_email}&name={applicant_name}'
                dir_html = (
                    f'<div style="font-family:-apple-system,sans-serif;max-width:600px">'
                    f'<h2 style="color:#145466">Thank you for your interest in directing with HWTC</h2>'
                    f'<p>Hi {applicant_name},</p>'
                    f'<p>Thank you for submitting your volunteer interest form and indicating that you are interested in directing with Horizon West Theatre Company. We are excited to learn more about you!</p>'
                    f'<p>Because directing is a significant responsibility, we would love to know more about your specific directing intentions, experience, and vision. Please take a few minutes to complete our Director Interest Form using the link below:</p>'
                    f'<p style="margin:24px 0"><a href="{form_url}" style="background:#145466;color:#fff;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">Complete Director Interest Form</a></p>'
                    f'<p style="color:#6b7280;font-size:13px">This form helps us understand your goals and find the right fit for you and our productions. It should take about 10 minutes to complete.</p>'
                    f'<p style="color:#6b7280;font-size:13px">If you have any questions, please reach out to us at info@hwtco.org.</p>'
                    f'<p style="color:#9ca3af;font-size:12px;margin-top:24px">Horizon West Theatre Company &mdash; rolecall.hwtco.org</p>'
                    f'</div>'
                )
                send_email([applicant_email], 'HWTC Director Interest Form', dir_html)
    except Exception as e:
        app.logger.warning(f'Director interest email failed: {e}')
    conn.close()
    return jsonify({'ok': True, 'id': aid})

@app.route('/api/applications')
def get_applications():
    err = require_auth()
    if err: return err
    conn = get_db()
    apps = fetchall(conn, 'SELECT * FROM volunteer_applications ORDER BY created_at DESC')
    # Flag duplicates  -  email already exists in volunteers table
    for a in apps:
        if a.get('status') == 'pending':
            existing = fetchone(conn, 'SELECT id, name FROM volunteers WHERE LOWER(email)=LOWER(%s)', (a['email'],))
            a['duplicate_volunteer'] = {'id': existing['id'], 'name': existing['name']} if existing else None
        else:
            a['duplicate_volunteer'] = None
    conn.close()
    return jsonify(apps)

@app.route('/api/applications/<aid>/approve', methods=['POST'])
def approve_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        app_row = fetchone(conn, 'SELECT * FROM volunteer_applications WHERE id=%s', (aid,))
        if not app_row:
            conn.close(); return jsonify({'error': 'Application not found'}), 404

        # Check if volunteer with this email already exists
        existing = fetchone(conn, 'SELECT id FROM volunteers WHERE LOWER(email)=LOWER(%s)', (app_row['email'],))
        sub_selections = app_row.get('sub_selections') or '{}'
        if existing:
            vid = existing['id']
            # Update name/phone/pronouns if blank, merge sub_selections
            execute(conn, """UPDATE volunteers SET
                name=COALESCE(NULLIF(name,''),%s),
                phone=COALESCE(NULLIF(phone,''),%s),
                pronouns=CASE WHEN pronouns IS NULL OR pronouns='' THEN %s ELSE pronouns END,
                employer_program=CASE WHEN employer_program IS NULL OR employer_program='' THEN %s ELSE employer_program END
                WHERE id=%s""",
                (app_row['name'], app_row.get('phone',''), app_row.get('pronouns',''),
                 app_row.get('employer_program','') or '', vid))
            try:
                old_row = fetchone(conn, 'SELECT sub_selections FROM volunteers WHERE id=%s', (vid,))
                old_ss = json.loads((old_row or {}).get('sub_selections') or '{}')
                new_ss = json.loads(sub_selections)
                merged = {**old_ss, **new_ss}
                execute(conn, 'UPDATE volunteers SET sub_selections=%s WHERE id=%s', (json.dumps(merged), vid))
            except Exception:
                pass
        else:
            vid = str(uuid.uuid4())
            interests = app_row.get('interests') or '[]'
            execute(conn, "INSERT INTO volunteers (id,name,email,phone,pronouns,status,interests,sub_selections,employer_program) VALUES (%s,%s,%s,%s,%s,'active',%s,%s,%s)",
                (vid, app_row['name'], app_row['email'], app_row.get('phone',''),
                 app_row.get('pronouns',''), interests, sub_selections,
                 app_row.get('employer_program','') or ''))

        execute(conn, "UPDATE volunteer_applications SET status='approved', volunteer_id=%s, reviewed_at=NOW(), reviewed_by=%s WHERE id=%s",
            (vid, session.get('user_name',''), aid))

        # Copy application notes to volunteer profile notes
        app_notes = (app_row.get('notes') or '').strip()
        if app_notes:
            nid = str(uuid.uuid4())
            execute(conn, "INSERT INTO notes (id,volunteer_id,author,content) VALUES (%s,%s,%s,%s)",
                (nid, vid, 'Join Form', app_notes))

        link_director_submission(conn, vid, app_row.get('email',''))
        conn.commit()
        vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vid,))
        conn.close()
        return jsonify({'ok': True, 'volunteer': vol})
    except Exception as e:
        conn.rollback(); conn.close()
        app.logger.error(f'approve_application {aid}: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/applications/<aid>/decline', methods=['POST'])
def decline_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE volunteer_applications SET status='declined', reviewed_at=NOW(), reviewed_by=%s WHERE id=%s",
        (session.get('user_name',''), aid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/applications/<aid>', methods=['DELETE'])
def delete_application(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM volunteer_applications WHERE id=%s', (aid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─────────────────────────────────────────────
#  PORTAL INSTRUCTOR CONTENT
# ─────────────────────────────────────────────

@app.route('/api/portal/instructor/content/<context_type>/<context_id>')
def get_portal_instructor_content(context_type, context_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Use real column names: program_id / production_id (not context_type/context_id)
    try:
        if context_type == 'production':
            files = fetchall(conn, '''SELECT * FROM portal_files
                WHERE production_id=%s AND (description IS NULL OR description != '__folder__')
                ORDER BY folder, title''', (context_id,))
        elif context_type == 'program':
            files = fetchall(conn, '''SELECT * FROM portal_files
                WHERE program_id=%s AND (description IS NULL OR description != '__folder__')
                ORDER BY folder, title''', (context_id,))
        else:
            files = []
    except Exception as e:
        app.logger.warning(f'portal files fetch failed: {e}')
        files = []
    try:
        if context_type == 'production':
            announcements = fetchall(conn, '''SELECT * FROM portal_announcements
                WHERE production_id=%s ORDER BY created_at DESC''', (context_id,))
        elif context_type == 'program':
            announcements = fetchall(conn, '''SELECT * FROM portal_announcements
                WHERE program_id=%s ORDER BY created_at DESC''', (context_id,))
        else:
            announcements = []
    except Exception as e:
        app.logger.warning(f'announcements fetch failed: {e}')
        announcements = []
    conn.close()
    return jsonify({'files': files, 'announcements': announcements})

# ─────────────────────────────────────────────
#  REPORTS
# ─────────────────────────────────────────────

def build_volunteer_monthly_report(year, month):
    """Build volunteer monthly recap data."""
    conn = get_db()
    import calendar
    month_name = calendar.month_name[int(month)]
    date_prefix = f'{int(year):04d}-{int(month):02d}'

    # Total hours this month
    total = fetchone(conn, """
        SELECT COALESCE(SUM(h.hours),0) as total, COUNT(DISTINCT h.volunteer_id) as vol_count
        FROM hours h WHERE h.date LIKE %s""", (date_prefix+'%',))

    # Top volunteers by hours this month
    top_vols = fetchall(conn, """
        SELECT v.name, SUM(h.hours) as hours, COUNT(*) as entries
        FROM hours h JOIN volunteers v ON h.volunteer_id=v.id
        WHERE h.date LIKE %s GROUP BY v.id, v.name
        ORDER BY hours DESC LIMIT 20""", (date_prefix+'%',))

    # Hours by event
    by_event = fetchall(conn, """
        SELECT h.event, SUM(h.hours) as hours, COUNT(DISTINCT h.volunteer_id) as vol_count
        FROM hours h WHERE h.date LIKE %s
        GROUP BY h.event ORDER BY hours DESC LIMIT 15""", (date_prefix+'%',))

    # New volunteers this month
    new_vols = fetchall(conn, """
        SELECT name, email FROM volunteers
        WHERE created_at::text LIKE %s ORDER BY created_at""", (date_prefix+'%',))

    # Pending hours awaiting approval
    pending = fetchone(conn, """
        SELECT COUNT(*) as c, COALESCE(SUM(hours),0) as total
        FROM pending_hours WHERE date LIKE %s AND status='pending'""", (date_prefix+'%',))

    # Lapsed volunteers (no hours in 60+ days)
    lapsed = fetchall(conn, """
        SELECT v.name, v.email, MAX(h.date) as last_date
        FROM volunteers v JOIN hours h ON h.volunteer_id=v.id
        WHERE v.status='active'
        GROUP BY v.id, v.name, v.email
        HAVING MAX(h.date) < (CURRENT_DATE - INTERVAL '60 days')::text
        ORDER BY last_date ASC LIMIT 20""")

    conn.close()
    return {
        'month': month_name, 'year': int(year),
        'total_hours': float(total['total']) if total else 0,
        'active_volunteers': int(total['vol_count']) if total else 0,
        'top_volunteers': top_vols,
        'hours_by_event': by_event,
        'new_volunteers': new_vols,
        'pending_hours': float(pending['total']) if pending else 0,
        'pending_count': int(pending['c']) if pending else 0,
        'lapsed_volunteers': lapsed,
    }

def build_top_volunteers_report(start_date, end_date, limit=50):
    conn = get_db()
    rows = fetchall(conn, """
        SELECT v.name, v.email, v.phone,
               COALESCE(SUM(h.hours),0) as total_hours,
               COUNT(DISTINCT h.event) as events_count,
               MIN(h.date) as first_date, MAX(h.date) as last_date
        FROM volunteers v
        LEFT JOIN hours h ON h.volunteer_id=v.id
            AND h.date >= %s AND h.date <= %s
        WHERE v.status='active'
        GROUP BY v.id, v.name, v.email, v.phone
        ORDER BY total_hours DESC, v.name ASC
        LIMIT %s""", (start_date, end_date, limit))
    conn.close()
    return rows

def build_lapsed_volunteers_report(days=90):
    conn = get_db()
    rows = fetchall(conn, """
        SELECT v.name, v.email, v.phone,
               MAX(h.date) as last_date,
               COALESCE(SUM(h.hours),0) as total_hours_ever
        FROM volunteers v
        LEFT JOIN hours h ON h.volunteer_id=v.id
        WHERE v.status='active'
        GROUP BY v.id, v.name, v.email, v.phone
        HAVING MAX(h.date) < (CURRENT_DATE - INTERVAL '%s days')::text
            OR MAX(h.date) IS NULL
        ORDER BY last_date ASC NULLS FIRST""" % int(days))
    conn.close()
    return rows

def build_hours_by_event_report(start_date, end_date):
    conn = get_db()
    rows = fetchall(conn, """
        SELECT h.event, h.event_id,
               SUM(h.hours) as total_hours,
               COUNT(DISTINCT h.volunteer_id) as volunteer_count,
               COUNT(*) as entry_count,
               MIN(h.date) as first_date, MAX(h.date) as last_date
        FROM hours h
        WHERE h.date >= %s AND h.date <= %s
        GROUP BY h.event, h.event_id
        ORDER BY total_hours DESC""", (start_date, end_date))
    conn.close()
    return rows

def build_range_recap_report(start_date, end_date):
    """Flexible date-range volunteer recap (used for quarterly/YTD/custom)."""
    conn = get_db()
    import datetime as _dt

    totals = fetchone(conn, """
        SELECT COALESCE(SUM(h.hours),0) as total_hours,
               COUNT(DISTINCT h.volunteer_id) as active_volunteers,
               COUNT(*) as total_entries
        FROM hours h WHERE h.date >= %s AND h.date <= %s""", (start_date, end_date))

    top_vols = fetchall(conn, """
        SELECT v.name, v.email,
               COALESCE(SUM(h.hours),0) as hours,
               COUNT(DISTINCT h.event) as events_count
        FROM hours h JOIN volunteers v ON h.volunteer_id=v.id
        WHERE h.date >= %s AND h.date <= %s
        GROUP BY v.id, v.name, v.email
        ORDER BY hours DESC LIMIT 20""", (start_date, end_date))

    by_event = fetchall(conn, """
        SELECT h.event,
               SUM(h.hours) as hours,
               COUNT(DISTINCT h.volunteer_id) as vol_count
        FROM hours h WHERE h.date >= %s AND h.date <= %s
        GROUP BY h.event ORDER BY hours DESC LIMIT 15""", (start_date, end_date))

    # New volunteers in range
    new_vols = fetchall(conn, """
        SELECT name, email, created_at::date as join_date
        FROM volunteers WHERE created_at::date >= %s AND created_at::date <= %s
        ORDER BY created_at""", (start_date, end_date))

    # Lapsed (60+ days as of end_date)
    lapsed = fetchall(conn, """
        SELECT v.name, v.email, MAX(h.date) as last_date
        FROM volunteers v JOIN hours h ON h.volunteer_id=v.id
        WHERE v.status='active'
        GROUP BY v.id, v.name, v.email
        HAVING MAX(h.date) < (%s::date - INTERVAL '60 days')::text
        ORDER BY last_date ASC LIMIT 20""", (end_date,))

    # Hours by week for sparkline (up to 52 buckets)
    try:
        weekly = fetchall(conn, """
            SELECT TO_CHAR(date::date, 'IYYY-IW') as week,
                   SUM(hours) as hours
            FROM hours WHERE date >= %s AND date <= %s
            GROUP BY week ORDER BY week""", (start_date, end_date))
    except Exception:
        weekly = []

    conn.close()
    return {
        'start_date': start_date, 'end_date': end_date,
        'total_hours': float(totals['total_hours']) if totals else 0,
        'active_volunteers': int(totals['active_volunteers']) if totals else 0,
        'total_entries': int(totals['total_entries']) if totals else 0,
        'top_volunteers': top_vols,
        'hours_by_event': by_event,
        'new_volunteers': new_vols,
        'lapsed_volunteers': lapsed,
        'weekly_hours': weekly,
    }


def build_board_attendance_report(start_date, end_date):
    conn = get_db()
    meetings = fetchall(conn, """
        SELECT bm.id, bm.meeting_date, bm.location, bm.status,
               COUNT(bma.id) as total_members,
               COUNT(CASE WHEN bma.attendance_type IN ('in_person','virtual') OR bma.attended=TRUE THEN 1 END) as attended,
               COUNT(CASE WHEN bma.attendance_type='in_person' THEN 1 END) as in_person,
               COUNT(CASE WHEN bma.attendance_type='virtual' THEN 1 END) as virtual_count
        FROM board_meetings bm
        LEFT JOIN board_meeting_attendance bma ON bma.meeting_id=bm.id
        WHERE bm.meeting_date >= %s AND bm.meeting_date <= %s
        GROUP BY bm.id, bm.meeting_date, bm.location, bm.status
        ORDER BY bm.meeting_date""", (start_date, end_date))

    member_stats = fetchall(conn, """
        SELECT bm.name, bm.role, bm.email,
               COUNT(bma.id) as total_meetings,
               COUNT(CASE WHEN bma.attendance_type IN ('in_person','virtual') OR bma.attended=TRUE THEN 1 END) as attended,
               COUNT(CASE WHEN bma.attendance_type='in_person' THEN 1 END) as in_person,
               COUNT(CASE WHEN bma.attendance_type='virtual' THEN 1 END) as virtual_count
        FROM board_members bm
        LEFT JOIN board_meeting_attendance bma ON bma.member_id=bm.id
        LEFT JOIN board_meetings meet ON bma.meeting_id=meet.id
            AND meet.meeting_date >= %s AND meet.meeting_date <= %s
        WHERE bm.status='active'
        GROUP BY bm.id, bm.name, bm.role, bm.email
        ORDER BY attended DESC, bm.name""", (start_date, end_date))

    total_meetings = len(meetings)
    total_possible = sum(m['total_members'] for m in meetings)
    total_attended = sum(m['attended'] for m in meetings)
    avg_rate = round(total_attended / total_possible * 100) if total_possible else 0

    conn.close()
    return {
        'start_date': start_date, 'end_date': end_date,
        'meetings': meetings,
        'member_stats': member_stats,
        'total_meetings': total_meetings,
        'total_possible': total_possible,
        'total_attended': total_attended,
        'avg_attendance_rate': avg_rate,
    }


def build_enrollment_report(start_date, end_date):
    conn = get_db()
    programs = fetchall(conn, """
        SELECT yp.id, yp.name, yp.program_type, yp.status,
               yp.start_date, yp.end_date,
               COUNT(DISTINCT ype.youth_id) as enrolled_count
        FROM youth_programs yp
        LEFT JOIN youth_program_enrollments ype ON ype.program_id=yp.id
        WHERE yp.created_at::date <= %s
          AND (yp.end_date IS NULL OR yp.end_date >= %s)
        GROUP BY yp.id, yp.name, yp.program_type, yp.status, yp.start_date, yp.end_date
        ORDER BY yp.start_date DESC NULLS LAST, yp.name""", (end_date, start_date))

    total_youth = fetchone(conn, """
        SELECT COUNT(DISTINCT y.id) as c FROM youth_participants y
        WHERE y.status='active'""")

    new_youth = fetchall(conn, """
        SELECT first_name||' '||last_name as name, created_at::date as join_date
        FROM youth_participants
        WHERE created_at::date >= %s AND created_at::date <= %s
        ORDER BY created_at""", (start_date, end_date))

    conn.close()
    return {
        'start_date': start_date, 'end_date': end_date,
        'programs': programs,
        'total_active_youth': int(total_youth['c']) if total_youth else 0,
        'new_youth': new_youth,
    }


def build_report_email_html(report_type, data, params=None):
    """Generate HTML email for a report."""
    from datetime import date
    today = date.today().strftime('%B %d, %Y')
    header = f'''<div style="font-family:-apple-system,sans-serif;max-width:700px;margin:0 auto">
    <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:12px 12px 0 0;color:#fff">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;opacity:0.7;margin-bottom:6px">Horizon West Theatre Company</div>
        <div style="font-size:22px;font-weight:800">{{}}</div>
        <div style="font-size:13px;opacity:0.7;margin-top:4px">Generated {today}</div>
    </div>
    <div style="background:#fff;padding:28px 32px;border:1px solid #e0e0db;border-top:none;border-radius:0 0 12px 12px">'''
    footer = '''</div><p style="text-align:center;font-size:11px;color:#9b9b94;margin-top:16px">
        RoleCall  -  Horizon West Theatre Company Management System</p></div>'''

    def stat_box(label, value, color='#145466'):
        return f'<div style="background:#f0f8fa;border-radius:10px;padding:16px 20px;text-align:center"><div style="font-size:28px;font-weight:900;color:{color}">{value}</div><div style="font-size:12px;color:#5f5e5a;margin-top:4px">{label}</div></div>'

    def table(headers, rows, cols):
        th = ''.join(f'<th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#5f5e5a;border-bottom:2px solid #e0e0db">{h}</th>' for h in headers)
        trs = ''
        for i, r in enumerate(rows):
            bg = '#f9f9f9' if i%2==0 else '#fff'
            tds = ''.join(f'<td style="padding:8px 12px;font-size:13px;border-bottom:1px solid #e0e0db">{str(r.get(c,"") or " - ")}</td>' for c in cols)
            trs += f'<tr style="background:{bg}">{tds}</tr>'
        return f'<table style="width:100%;border-collapse:collapse;margin-top:12px"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'

    if report_type == 'monthly_recap':
        title = f'{data["month"]} {data["year"]}  -  Volunteer Monthly Recap'
        body = f'''<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px">
            {stat_box('Total Hours Logged', f'{data["total_hours"]:.1f}h')}
            {stat_box('Active Volunteers', data["active_volunteers"])}
            {stat_box('Pending Approval', f'{data["pending_count"]} ({data["pending_hours"]:.1f}h)', '#d97706')}
        </div>'''
        if data['top_volunteers']:
            body += f'<div style="font-size:15px;font-weight:700;margin-bottom:8px">Top Volunteers</div>'
            body += table(['Name','Hours','Events'], data['top_volunteers'][:10], ['name','hours','events_count'])
        if data['hours_by_event']:
            body += f'<div style="font-size:15px;font-weight:700;margin:20px 0 8px">Hours by Event</div>'
            body += table(['Event','Hours','Volunteers'], data['hours_by_event'], ['event','hours','vol_count'])
        if data['new_volunteers']:
            body += f'<div style="font-size:15px;font-weight:700;margin:20px 0 8px">New Volunteers ({len(data["new_volunteers"])})</div>'
            body += table(['Name','Email'], data['new_volunteers'], ['name','email'])
        if data['lapsed_volunteers']:
            body += f'<div style="font-size:15px;font-weight:700;margin:20px 0 8px">⚠️ Lapsed Volunteers (60+ days)</div>'
            body += table(['Name','Last Active','Email'], data['lapsed_volunteers'], ['name','last_date','email'])

    elif report_type == 'top_volunteers':
        title = f'Top Volunteers  -  {params.get("start_date","")} to {params.get("end_date","")}'
        body = table(['#','Name','Hours','Events','Last Active'],
            [{**r, '#': i+1} for i,r in enumerate(data)],
            ['#','name','total_hours','events_count','last_date'])

    elif report_type == 'lapsed_volunteers':
        title = f'Lapsed Volunteers ({params.get("days",90)}+ days inactive)'
        body = f'<p style="font-size:14px;color:#5f5e5a;margin-bottom:16px">{len(data)} volunteer{"s" if len(data)!=1 else ""} with no hours in the last {params.get("days",90)} days.</p>'
        body += table(['Name','Last Active','Total Hours','Email'], data, ['name','last_date','total_hours_ever','email'])

    elif report_type == 'hours_by_event':
        title = f'Hours by Event  -  {params.get("start_date","")} to {params.get("end_date","")}'
        body = table(['Event','Total Hours','Volunteers','Entries'], data, ['event','total_hours','volunteer_count','entry_count'])

    else:
        title = 'Volunteer Report'
        body = '<p>Report data</p>'

    return header.format(title) + body + footer, title

@app.route('/api/reports/run', methods=['POST'])
def run_report():
    err = require_auth()
    if err: return err
    d = request.json or {}
    rtype = d.get('report_type')
    params = d.get('params', {})

    import datetime as _dt
    today = _dt.date.today()
    last_month = (today.replace(day=1) - _dt.timedelta(days=1))

    if rtype == 'monthly_recap':
        year  = params.get('year', last_month.year)
        month = params.get('month', last_month.month)
        data  = build_volunteer_monthly_report(year, month)

    elif rtype == 'top_volunteers':
        start = params.get('start_date', today.replace(day=1).isoformat())
        end   = params.get('end_date', today.isoformat())
        limit = params.get('limit', 50)
        data  = build_top_volunteers_report(start, end, limit)

    elif rtype == 'lapsed_volunteers':
        days = params.get('days', 90)
        data = build_lapsed_volunteers_report(days)

    elif rtype == 'hours_by_event':
        start = params.get('start_date', today.replace(day=1).isoformat())
        end   = params.get('end_date', today.isoformat())
        data  = build_hours_by_event_report(start, end)

    elif rtype == 'range_recap':
        start = params.get('start_date', today.replace(day=1).isoformat())
        end   = params.get('end_date', today.isoformat())
        data  = build_range_recap_report(start, end)

    elif rtype == 'board_attendance':
        start = params.get('start_date', today.replace(month=1, day=1).isoformat())
        end   = params.get('end_date', today.isoformat())
        data  = build_board_attendance_report(start, end)

    elif rtype == 'enrollment':
        start = params.get('start_date', today.replace(month=1, day=1).isoformat())
        end   = params.get('end_date', today.isoformat())
        data  = build_enrollment_report(start, end)

    else:
        return jsonify({'error': 'Unknown report type'}), 400

    return jsonify({'ok': True, 'data': data, 'report_type': rtype, 'params': params})

@app.route('/api/reports/export-csv', methods=['POST'])
def export_report_csv():
    err = require_auth()
    if err: return err
    d = request.json or {}
    rtype  = d.get('report_type')
    data   = d.get('data', [])
    params = d.get('params', {})

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)

    col_maps = {
        'monthly_recap':    None,  # handled specially
        'top_volunteers':   (['Name','Email','Phone','Total Hours','Events','First Date','Last Date'],
                             ['name','email','phone','total_hours','events_count','first_date','last_date']),
        'lapsed_volunteers':(['Name','Email','Phone','Last Active','Total Hours Ever'],
                             ['name','email','phone','last_date','total_hours_ever']),
        'hours_by_event':   (['Event','Total Hours','Volunteers','Entries','First Date','Last Date'],
                             ['event','total_hours','volunteer_count','entry_count','first_date','last_date']),
    }

    if rtype == 'monthly_recap' and isinstance(data, dict):
        writer.writerow([f'{data.get("month","")} {data.get("year","")}  -  Volunteer Monthly Recap'])
        writer.writerow([])
        writer.writerow(['Metric','Value'])
        writer.writerow(['Total Hours', data.get('total_hours',0)])
        writer.writerow(['Active Volunteers', data.get('active_volunteers',0)])
        writer.writerow(['Pending Hours', data.get('pending_hours',0)])
        writer.writerow([])
        writer.writerow(['TOP VOLUNTEERS'])
        writer.writerow(['Name','Hours','Events'])
        for r in data.get('top_volunteers',[]):
            writer.writerow([r.get('name',''), r.get('hours',''), r.get('events_count','')])
        writer.writerow([])
        writer.writerow(['HOURS BY EVENT'])
        writer.writerow(['Event','Hours','Volunteers'])
        for r in data.get('hours_by_event',[]):
            writer.writerow([r.get('event',''), r.get('hours',''), r.get('vol_count','')])
        writer.writerow([])
        writer.writerow(['NEW VOLUNTEERS'])
        writer.writerow(['Name','Email'])
        for r in data.get('new_volunteers',[]):
            writer.writerow([r.get('name',''), r.get('email','')])
    elif rtype in col_maps and col_maps[rtype] and isinstance(data, list):
        headers, cols = col_maps[rtype]
        writer.writerow(headers)
        for row in data:
            writer.writerow([row.get(c,'') for c in cols])
    else:
        writer.writerow(['Export not available for this report type'])

    csv_content = output.getvalue()
    from flask import Response
    return Response(csv_content, mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=rolecall_{rtype}.csv'})

@app.route('/api/reports/send-now', methods=['POST'])
def send_report_now():
    """Manually send a report via email."""
    err = require_auth()
    if err: return err
    d = request.json or {}
    rtype   = d.get('report_type')
    params  = d.get('params', {})
    emails  = d.get('emails', [])

    import datetime as _dt
    today = _dt.date.today()
    last_month = (today.replace(day=1) - _dt.timedelta(days=1))

    if rtype == 'monthly_recap':
        data = build_volunteer_monthly_report(
            params.get('year', last_month.year), params.get('month', last_month.month))
    elif rtype == 'top_volunteers':
        data = build_top_volunteers_report(
            params.get('start_date', today.replace(day=1).isoformat()),
            params.get('end_date', today.isoformat()))
    elif rtype == 'lapsed_volunteers':
        data = build_lapsed_volunteers_report(params.get('days', 90))
    elif rtype == 'hours_by_event':
        data = build_hours_by_event_report(
            params.get('start_date', today.replace(day=1).isoformat()),
            params.get('end_date', today.isoformat()))
    else:
        return jsonify({'error': 'Unknown report type'}), 400

    html, subject = build_report_email_html(rtype, data, params)
    if not emails:
        settings = get_email_settings()
        emails = get_recipient_emails(settings)
    if not emails:
        return jsonify({'error': 'No recipients configured'}), 400

    fi = d.get('from_identity') or {}
    ok, msg = send_email(emails, subject, html, fi.get('email') or None, fi.get('name') or None)
    if ok: return jsonify({'ok': True, 'sent_to': emails})
    return jsonify({'error': msg or 'Failed to send'}), 500

# ── Scheduled Reports ──
@app.route('/api/scheduled-reports')
def get_scheduled_reports():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, 'SELECT * FROM scheduled_reports ORDER BY name')
    conn.close()
    return jsonify(rows)

@app.route('/api/scheduled-reports', methods=['POST'])
def create_scheduled_report():
    err = require_auth()
    if err: return err
    d = request.json or {}
    rid = str(uuid.uuid4())
    conn = get_db()
    # Calculate next send date
    import datetime as _dt
    next_send = _compute_next_send(d.get('cadence','monthly'), d.get('send_day',1))
    execute(conn, '''INSERT INTO scheduled_reports
        (id,name,report_type,cadence,send_day,recipient_user_ids,recipient_emails,params,is_active,next_send_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (rid, d.get('name',''), d['report_type'], d.get('cadence','monthly'),
         d.get('send_day',1), json.dumps(d.get('recipient_user_ids',[])),
         d.get('recipient_emails',''), json.dumps(d.get('params',{})),
         d.get('is_active',True), next_send))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM scheduled_reports WHERE id=%s', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/scheduled-reports/<rid>', methods=['PUT'])
def update_scheduled_report(rid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    next_send = _compute_next_send(d.get('cadence','monthly'), d.get('send_day',1))
    execute(conn, '''UPDATE scheduled_reports SET name=%s,report_type=%s,cadence=%s,
        send_day=%s,recipient_user_ids=%s,recipient_emails=%s,params=%s,is_active=%s,next_send_at=%s WHERE id=%s''',
        (d.get('name',''), d['report_type'], d.get('cadence','monthly'),
         d.get('send_day',1), json.dumps(d.get('recipient_user_ids',[])),
         d.get('recipient_emails',''), json.dumps(d.get('params',{})),
         d.get('is_active',True), next_send, rid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/scheduled-reports/<rid>', methods=['DELETE'])
def delete_scheduled_report(rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM scheduled_reports WHERE id=%s', (rid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

def _compute_next_send(cadence, send_day):
    import datetime as _dt
    today = _dt.date.today()
    day = max(1, min(28, int(send_day or 1)))
    if cadence == 'monthly':
        # Next month on send_day
        if today.day < day:
            try: return _dt.date(today.year, today.month, day).isoformat()
            except Exception: pass
        # Move to next month
        nm = today.month % 12 + 1
        ny = today.year + (1 if today.month == 12 else 0)
        try: return _dt.date(ny, nm, day).isoformat()
        except Exception: return None
    elif cadence == 'weekly':
        # Next occurrence of send_day (0=Mon)
        days_ahead = (int(send_day) - today.weekday()) % 7
        if days_ahead == 0: days_ahead = 7
        return (today + _dt.timedelta(days=days_ahead)).isoformat()
    return None

# Cron-style scheduler  -  called on every request, fires due reports
_last_cron_check = [None]
def maybe_run_scheduled_reports():
    import datetime as _dt
    now = _dt.datetime.now()
    last = _last_cron_check[0]
    # Only check once per hour  -  use total_seconds() not .seconds
    if last and (now - last).total_seconds() < 3600: return
    _last_cron_check[0] = now
    try:
        conn = get_db()
        due = fetchall(conn, """SELECT * FROM scheduled_reports
            WHERE is_active=TRUE AND next_send_at IS NOT NULL
            AND next_send_at::date <= CURRENT_DATE""")
        conn.close()
        for r in due:
            try:
                _fire_scheduled_report(r)
            except Exception as e:
                app.logger.error(f'Scheduled report error {r["id"]}: {e}')
    except Exception as e:
        app.logger.error(f'Cron check error: {e}')

def _fire_scheduled_report(r):
    import datetime as _dt
    rtype  = r['report_type']
    params = json.loads(r.get('params') or '{}')
    today  = _dt.date.today()
    lm     = (today.replace(day=1) - _dt.timedelta(days=1))

    if rtype == 'monthly_recap':
        data = build_volunteer_monthly_report(lm.year, lm.month)
    elif rtype == 'top_volunteers':
        start = params.get('start_date', lm.replace(day=1).isoformat())
        end   = params.get('end_date', lm.isoformat())
        data  = build_top_volunteers_report(start, end)
    elif rtype == 'lapsed_volunteers':
        data = build_lapsed_volunteers_report(params.get('days', 90))
    elif rtype == 'hours_by_event':
        start = params.get('start_date', lm.replace(day=1).isoformat())
        end   = params.get('end_date', lm.isoformat())
        data  = build_hours_by_event_report(start, end)
    else:
        return

    html, subject = build_report_email_html(rtype, data, params)

    # Build recipient list
    emails = []
    try:
        uids = json.loads(r.get('recipient_user_ids') or '[]')
        if uids:
            conn = get_db()
            placeholders = ','.join(['%s']*len(uids))
            users = fetchall(conn, f'SELECT email FROM users WHERE id IN ({placeholders})', tuple(uids))
            conn.close()
            emails = [u['email'] for u in users if u.get('email')]
    except Exception: pass
    raw = r.get('recipient_emails','')
    if raw:
        emails += [e.strip() for e in raw.split(',') if e.strip()]
    emails = list(set(emails))
    if not emails: return

    ok, _ = send_email(emails, subject, html)
    if ok:
        # Update last sent and compute next send
        next_send = _compute_next_send(r['cadence'], r['send_day'])
        conn = get_db()
        execute(conn, 'UPDATE scheduled_reports SET last_sent_at=NOW(), next_send_at=%s WHERE id=%s',
                (next_send, r['id']))
        conn.commit(); conn.close()

# Hook cron into every request
@app.after_request
def after_request_cron(response):
    try: maybe_run_scheduled_reports()
    except Exception: pass
    return response

# ─────────────────────────────────────────────
#  PRODUCTION SIGN-IN (ELIC Kiosk)
# ─────────────────────────────────────────────

@app.route('/api/kiosk/production-roster/<event_id>')
def kiosk_production_roster(event_id):
    conn = get_db()
    evt = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (event_id,))
    if not evt:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    prod_id = evt.get('production_id')
    if not prod_id:
        conn.close()
        return jsonify({'members': [], 'production_id': None})
    members = fetchall(conn, '''
        SELECT pm.id as member_id, pm.volunteer_id, pm.role, pm.department, pm.status,
               v.name as volunteer_name,
               pa.id as attendance_id, pa.signed_in_at,
               CASE WHEN pa.id IS NOT NULL AND pa.signed_out_at IS NULL THEN TRUE ELSE FALSE END as signed_in
        FROM production_members pm
        JOIN volunteers v ON pm.volunteer_id=v.id
        LEFT JOIN prod_attendance pa
            ON pa.volunteer_id=pm.volunteer_id AND pa.event_id=%s AND pa.signed_out_at IS NULL
        WHERE pm.production_id=%s AND pm.status != 'dropped'
        ORDER BY pm.department, v.name
    ''', (event_id, prod_id))
    conn.close()
    return jsonify({'ok': True, 'members': members, 'production_id': prod_id})

@app.route('/api/kiosk/production-signin', methods=['POST'])
def kiosk_production_signin():
    d = request.json or {}
    vol_id   = d.get('volunteer_id')
    event_id = d.get('event_id')
    if not vol_id or not event_id:
        return jsonify({'error': 'Missing volunteer_id or event_id'}), 400
    conn = get_db()
    existing = fetchone(conn,
        'SELECT id FROM prod_attendance WHERE volunteer_id=%s AND event_id=%s AND signed_out_at IS NULL',
        (vol_id, event_id))
    if existing:
        conn.close()
        return jsonify({'error': 'Already signed in', 'attendance_id': existing['id']})
    aid = str(uuid.uuid4())
    execute(conn, 'INSERT INTO prod_attendance (id,volunteer_id,event_id,signed_in_at) VALUES (%s,%s,%s,NOW())',
        (aid, vol_id, event_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'attendance_id': aid})

@app.route('/api/kiosk/production-signout', methods=['POST'])
def kiosk_production_signout():
    d = request.json or {}
    att_id   = d.get('attendance_id')
    vol_id   = d.get('volunteer_id')
    event_id = d.get('event_id')
    role     = d.get('role', '')
    if not vol_id or not event_id:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    att = None
    if att_id:
        att = fetchone(conn, 'SELECT * FROM prod_attendance WHERE id=%s', (att_id,))
    if not att:
        att = fetchone(conn,
            'SELECT * FROM prod_attendance WHERE volunteer_id=%s AND event_id=%s AND signed_out_at IS NULL',
            (vol_id, event_id))
    if not att:
        conn.close()
        return jsonify({'error': 'No active sign-in found'}), 404

    # Use full event duration, not elapsed time
    evt = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (event_id,))
    evt_name = evt['name'] if evt else 'Production'
    event_hours = None
    if evt and evt.get('start_time') and evt.get('end_time'):
        try:
            from datetime import datetime as _dt
            fmt = '%H:%M'
            start = _dt.strptime(str(evt['start_time'])[:5], fmt)
            end   = _dt.strptime(str(evt['end_time'])[:5], fmt)
            diff  = (end - start).seconds / 3600
            if diff > 0:
                event_hours = round(diff, 2)
        except Exception:
            pass
    # Fall back to elapsed time if event has no start/end times set
    if not event_hours:
        time_row = fetchone(conn,
            'SELECT EXTRACT(EPOCH FROM (NOW() - signed_in_at)) as secs FROM prod_attendance WHERE id=%s',
            (att['id'],))
        elapsed_secs  = float(time_row['secs']) if time_row and time_row['secs'] else 0
        event_hours   = round(max(0.25, elapsed_secs / 3600), 2)
        hours_source  = 'elapsed time (no event times set)'
    else:
        hours_source = f'full event duration ({evt.get("start_time","")}–{evt.get("end_time","")})'

    today_row = fetchone(conn, 'SELECT CURRENT_DATE::text as today')
    today = today_row['today'] if today_row else __import__('datetime').date.today().isoformat()

    execute(conn, 'UPDATE prod_attendance SET signed_out_at=NOW() WHERE id=%s', (att['id'],))
    pid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO pending_hours (id,volunteer_id,event,event_id,date,hours,role,notes,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')''',
        (pid, vol_id, evt_name, event_id, today, event_hours, role or '',
         f'Production member  -  {hours_source}'))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'hours': event_hours, 'hours_source': hours_source})



# ─────────────────────────────────────────────
#  KIOSK  -  OPEN/CLOSE EVENT & YOUTH
# ─────────────────────────────────────────────

@app.route('/api/kiosk/open-event-checklist', methods=['POST'])
def kiosk_open_event():
    d = request.json or {}
    elic_id  = d.get('elic_id')
    event_id = d.get('event_id')
    responses = d.get('responses', [])
    if not elic_id or not event_id:
        return jsonify({'error': 'Missing elic_id or event_id'}), 400
    conn = get_db()
    try:
        # Log the opening
        log_id = str(uuid.uuid4())
        execute(conn, '''INSERT INTO event_logs (id,event_id,elic_id,action,notes)
            VALUES (%s,%s,%s,'open','Event opened via kiosk')''', (log_id, event_id, elic_id))
        # Save checklist responses
        for r in responses:
            rid = str(uuid.uuid4())
            execute(conn, '''INSERT INTO event_checklist_responses
                (id,event_log_id,checklist_item_id,label,item_type,response)
                VALUES (%s,%s,%s,%s,%s,%s)''',
                (rid, log_id, r.get('item_id',''), r.get('label',''),
                 r.get('type','checkbox'), str(r.get('response',''))))
        # Mark event as open
        execute(conn, "UPDATE events SET status='open' WHERE id=%s", (event_id,))
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'log_id': log_id})
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/kiosk/close-event', methods=['POST'])
def kiosk_close_event():
    d = request.json or {}
    elic_id  = d.get('elic_id')
    event_id = d.get('event_id')
    responses = d.get('responses', [])
    if not elic_id or not event_id:
        return jsonify({'error': 'Missing elic_id or event_id'}), 400
    conn = get_db()
    try:
        log_id = str(uuid.uuid4())
        execute(conn, '''INSERT INTO event_logs (id,event_id,elic_id,action,notes)
            VALUES (%s,%s,%s,'close','Event closed via kiosk')''', (log_id, event_id, elic_id))
        for r in responses:
            rid = str(uuid.uuid4())
            execute(conn, '''INSERT INTO event_checklist_responses
                (id,event_log_id,checklist_item_id,label,item_type,response)
                VALUES (%s,%s,%s,%s,%s,%s)''',
                (rid, log_id, r.get('item_id',''), r.get('label',''),
                 r.get('type','checkbox'), str(r.get('response',''))))
        execute(conn, "UPDATE events SET status='closed' WHERE id=%s", (event_id,))
        # Auto-approve pending kiosk hours for this event
        pending = fetchall(conn,
            "SELECT * FROM pending_hours WHERE event_id=%s AND status='pending'", (event_id,))
        for ph in pending:
            hid = str(uuid.uuid4())
            try:
                execute(conn, '''INSERT INTO hours (id,volunteer_id,event,event_id,date,hours,role,notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (hid, ph['volunteer_id'], ph['event'], ph['event_id'],
                     ph['date'], ph['hours'], ph.get('role',''), ph.get('notes','')))
            except Exception:
                pass
        execute(conn, "UPDATE pending_hours SET status='approved' WHERE event_id=%s AND status='pending'", (event_id,))
        conn.commit()
        # Send checklist report email
        try:
            s = get_email_settings()
            recipients = get_recipient_emails(s)
            if recipients:
                evt = fetchone(conn, 'SELECT name FROM events WHERE id=%s', (event_id,))
                evt_name = evt['name'] if evt else event_id
                now_str = __import__('datetime').datetime.now().strftime('%I:%M %p')
                # Get opening checklist from the open log
                open_log = fetchone(conn, '''SELECT el.*, v.name as elic_name FROM event_logs el
                    LEFT JOIN elics eli ON el.elic_id=eli.id
                    LEFT JOIN volunteers v ON eli.volunteer_id=v.id
                    WHERE el.event_id=%s AND el.action='open' ORDER BY el.id LIMIT 1''', (event_id,))
                open_responses = []
                open_elic_name = ''
                if open_log:
                    open_responses = fetchall(conn,
                        'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id',
                        (open_log['id'],))
                    open_elic_name = open_log.get('elic_name','')
                # Build opening checklist rows
                ol_rows = ''
                for r in open_responses:
                    val = str(r.get('response',''))
                    val_str = '✅ Done' if val=='true' else ('❌ Not Done' if val=='false' else val or ' - ')
                    ol_rows += f'<tr><td style="padding:6px 12px;border-bottom:1px solid #eee">{r.get("label","")}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;font-weight:600">{val_str}</td></tr>'
                # Build closing checklist rows
                cl_rows = ''
                for r in responses:
                    val = str(r.get('response',''))
                    val_str = '✅ Done' if val=='true' else ('❌ Not Done' if val=='false' else val or ' - ')
                    cl_rows += f'<tr><td style="padding:6px 12px;border-bottom:1px solid #eee">{r.get("label","")}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;font-weight:600">{val_str}</td></tr>'
                # Build hours summary
                hrs_rows = ''
                if pending:
                    for ph in pending:
                        vol = fetchone(conn, 'SELECT name FROM volunteers WHERE id=%s', (ph['volunteer_id'],))
                        vname = vol['name'] if vol else 'Unknown'
                        hrs_rows += f'<tr><td style="padding:6px 12px;border-bottom:1px solid #eee">{vname}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;font-weight:600">{ph["hours"]}h</td><td style="padding:6px 12px;border-bottom:1px solid #eee;color:#16a34a">Auto-approved</td></tr>'
                body = f'''<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
                    <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:24px 28px;border-radius:8px 8px 0 0">
                      <div style="color:rgba(255,255,255,0.7);font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Event Closed</div>
                      <h2 style="color:#fff;margin:0;font-size:20px">🔒 {evt_name}</h2>
                      <div style="color:rgba(255,255,255,0.75);font-size:13px;margin-top:6px">Closed at <strong>{now_str}</strong>{" · Closed by "+open_elic_name if open_elic_name else ""}</div>
                    </div>
                    <div style="background:#f8fafc;padding:24px 28px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;border-top:none">
                    {f"""<h3 style="color:#145466;margin-top:0">Opening Checklist</h3>
                    <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0db;margin-bottom:20px">
                    <thead><tr style="background:#f0fdf4"><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Item</th><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Response</th></tr></thead>
                    <tbody>{ol_rows}</tbody></table>""" if ol_rows else ""}
                    {f"""<h3 style="color:#145466">Closing Checklist</h3>
                    <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0db;margin-bottom:20px">
                    <thead><tr style="background:#f0fdf4"><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Item</th><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Response</th></tr></thead>
                    <tbody>{cl_rows}</tbody></table>""" if cl_rows else "<p><em>No closing checklist items recorded.</em></p>"}
                    {f"""<h3 style="color:#145466">Hours Auto-Approved ({len(pending)} volunteer{"s" if len(pending)!=1 else ""})</h3>
                    <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0db;margin-bottom:20px">
                    <thead><tr style="background:#eff6ff"><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Volunteer</th><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Hours</th><th style="padding:8px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;color:#5f5e5a;border-bottom:2px solid #e0e0db">Status</th></tr></thead>
                    <tbody>{hrs_rows}</tbody></table>""" if pending else "<p><em>No hours recorded for this event.</em></p>"}
                    </div></div>'''
                send_email(recipients, f'Event Closed: {evt_name}', body)
        except Exception as e:
            app.logger.error(f'close-event email error: {e}')
        conn.close()
        return jsonify({'ok': True, 'log_id': log_id})
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/kiosk/youth')
def kiosk_get_youth():
    """Get youth participants for ELIC youth sign-in."""
    conn = get_db()
    # Get all active youth for today's events linked to this kiosk session
    youth = fetchall(conn, '''
        SELECT yp.id, yp.first_name, yp.last_name, yp.dob,
               ysi.id as sign_in_id, ysi.signed_in_at, ysi.signed_out_at,
               (SELECT f.passphrase FROM youth_family_links yfl
                JOIN families f ON f.id=yfl.family_id
                WHERE yfl.youth_id=yp.id LIMIT 1) as family_passphrase
        FROM youth_participants yp
        LEFT JOIN youth_sign_ins ysi ON ysi.youth_id=yp.id
            AND ysi.signed_in_at >= NOW() - INTERVAL '12 hours'
            AND ysi.signed_out_at IS NULL
        WHERE yp.status='active'
        ORDER BY yp.last_name, yp.first_name''')
    conn.close()
    return jsonify(youth)

@app.route('/api/kiosk/authorized-pickups/<yid>')
def kiosk_authorized_pickups(yid):
    conn = get_db()
    pickups = fetchall(conn,
        'SELECT * FROM youth_authorized_pickups WHERE youth_id=%s ORDER BY priority', (yid,))
    conn.close()
    return jsonify(pickups)

@app.route('/api/kiosk/youth-for-event/<event_id>')
def kiosk_youth_for_event(event_id):
    """Get youth enrolled in the production or program linked to this event."""
    conn = get_db()
    evt = fetchone(conn, 'SELECT production_id, program_id FROM events WHERE id=%s', (event_id,))
    if not evt:
        conn.close()
        return jsonify([])

    youth = []

    if evt.get('production_id'):
        # Rising Stars production  -  get enrolled cast
        youth = fetchall(conn, '''
            SELECT yp.id, yp.first_name, yp.last_name, yp.dob,
                   ypm.role,
                   (SELECT f.passphrase FROM youth_family_links yfl
                    JOIN families f ON f.id=yfl.family_id
                    WHERE yfl.youth_id=yp.id LIMIT 1) as family_passphrase,
                   ysi.id as sign_in_id, ysi.signed_in_at, ysi.signed_out_at
            FROM youth_production_members ypm
            JOIN youth_participants yp ON ypm.youth_id=yp.id
            LEFT JOIN youth_sign_ins ysi ON ysi.youth_id=yp.id
                AND ysi.event_id=%s AND ysi.signed_out_at IS NULL
            WHERE ypm.production_id=%s
            ORDER BY yp.last_name, yp.first_name''', (event_id, evt['production_id']))

    elif evt.get('program_id'):
        # Youth program  -  get enrolled participants
        youth = fetchall(conn, '''
            SELECT yp.id, yp.first_name, yp.last_name, yp.dob,
                   NULL as role,
                   (SELECT f.passphrase FROM youth_family_links yfl
                    JOIN families f ON f.id=yfl.family_id
                    WHERE yfl.youth_id=yp.id LIMIT 1) as family_passphrase,
                   ysi.id as sign_in_id, ysi.signed_in_at, ysi.signed_out_at
            FROM youth_program_enrollments ype
            JOIN youth_participants yp ON ype.youth_id=yp.id
            LEFT JOIN youth_sign_ins ysi ON ysi.youth_id=yp.id
                AND ysi.event_id=%s AND ysi.signed_out_at IS NULL
            WHERE ype.program_id=%s
            ORDER BY yp.last_name, yp.first_name''', (event_id, evt['program_id']))

    conn.close()
    return jsonify(youth)


# ─────────────────────────────────────────────
#  YOUTH SIGN-INS (ELIC Kiosk)
# ─────────────────────────────────────────────

@app.route('/api/youth-sign-ins')
def get_youth_sign_ins():
    conn = get_db()
    event_id = request.args.get('event_id')
    if event_id:
        rows = fetchall(conn, '''
            SELECT ysi.*, yp.first_name, yp.last_name,
                   yp.first_name||\' \'||yp.last_name as youth_name
            FROM youth_sign_ins ysi
            JOIN youth_participants yp ON ysi.youth_id=yp.id
            WHERE ysi.event_id=%s
            ORDER BY ysi.signed_in_at DESC''', (event_id,))
    else:
        rows = fetchall(conn, '''
            SELECT ysi.*, yp.first_name, yp.last_name,
                   yp.first_name||\' \'||yp.last_name as youth_name
            FROM youth_sign_ins ysi
            JOIN youth_participants yp ON ysi.youth_id=yp.id
            WHERE ysi.signed_in_at >= NOW() - INTERVAL '12 hours'
            ORDER BY ysi.signed_in_at DESC''')
    conn.close()
    return jsonify(rows)

@app.route('/api/youth-sign-ins', methods=['POST'])
def create_youth_sign_in():
    d = request.json or {}
    yid          = d.get('youth_id')
    event_id     = d.get('event_id')
    signed_in_by = d.get('signed_in_by', '')
    if not yid: return jsonify({'error': 'Missing youth_id'}), 400
    conn = get_db()
    # Check not already signed in
    existing = fetchone(conn,
        'SELECT ysi.*, y.first_name, y.last_name FROM youth_sign_ins ysi JOIN youth_participants y ON ysi.youth_id=y.id WHERE ysi.youth_id=%s AND ysi.event_id=%s AND ysi.signed_out_at IS NULL',
        (yid, event_id))
    if existing:
        conn.close()
        return jsonify(existing)  # return existing record, not error
    sid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO youth_sign_ins (id,youth_id,event_id,signed_in_at,signed_in_by)
        VALUES (%s,%s,%s,NOW(),%s)''', (sid, yid, event_id, signed_in_by))
    conn.commit()
    row = fetchone(conn, '''SELECT ysi.*, y.first_name, y.last_name
        FROM youth_sign_ins ysi
        JOIN youth_participants y ON ysi.youth_id=y.id
        WHERE ysi.id=%s''', (sid,))
    conn.close()
    return jsonify(row)

@app.route('/api/youth-sign-ins/<sid>/sign-out', methods=['POST'])
def youth_sign_out(sid):
    d = request.json or {}
    signed_out_by = d.get('signed_out_by', '')
    conn = get_db()
    execute(conn, 'UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by=%s WHERE id=%s',
        (signed_out_by, sid))
    conn.commit()
    row = fetchone(conn, '''SELECT ysi.*, y.first_name, y.last_name
        FROM youth_sign_ins ysi
        JOIN youth_participants y ON ysi.youth_id=y.id
        WHERE ysi.id=%s''', (sid,))
    conn.close()
    return jsonify(row or {'ok': True, 'id': sid, 'signed_out_at': 'now'})


# ─────────────────────────────────────────────
#  CARPOOLS
# ─────────────────────────────────────────────

def _gen_carpool_code():
    import random
    words = ['BLUE','RED','STAR','SUN','MOON','OAK','FOX','BAY','SKY','ZEN','ACE','ARC']
    return random.choice(words) + str(random.randint(10,99))

@app.route('/api/carpools')
def get_carpools():
    err = require_auth()
    if err: return err
    event_id = request.args.get('event_id')
    conn = get_db()
    if event_id:
        rows = fetchall(conn, 'SELECT c.*, COUNT(cm.id) as member_count FROM carpools c LEFT JOIN carpool_members cm ON cm.carpool_id=c.id WHERE c.event_id=%s GROUP BY c.id ORDER BY c.name', (event_id,))
    else:
        rows = fetchall(conn, """SELECT c.*, COUNT(cm.id) as member_count,
            e.name as event_name, e.event_date
            FROM carpools c
            LEFT JOIN carpool_members cm ON cm.carpool_id=c.id
            LEFT JOIN events e ON c.event_id=e.id
            GROUP BY c.id, e.name, e.event_date
            ORDER BY e.event_date DESC NULLS LAST, c.name""")
    for row in rows:
        row['members'] = fetchall(conn, 'SELECT cm.*, y.first_name, y.last_name FROM carpool_members cm JOIN youth_participants y ON cm.youth_id=y.id WHERE cm.carpool_id=%s ORDER BY y.last_name, y.first_name', (row['id'],))
    conn.close()
    return jsonify(rows)

@app.route('/api/carpools', methods=['POST'])
def create_carpool():
    err = require_auth()
    if err: return err
    d = request.json or {}
    cid = str(uuid.uuid4())
    conn = get_db()
    code = _gen_carpool_code()
    for _ in range(10):
        if not fetchone(conn, 'SELECT id FROM carpools WHERE code=%s', (code,)): break
        code = _gen_carpool_code()
    execute(conn, "INSERT INTO carpools (id,event_id,name,driver_name,driver_phone,code,max_seats,notes,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')",
        (cid, d.get('event_id'), d.get('name',''), d['driver_name'], d.get('driver_phone',''), code, d.get('max_seats',6), d.get('notes','')))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM carpools WHERE id=%s', (cid,))
    row['members'] = []; row['member_count'] = 0
    conn.close()
    return jsonify(row)

@app.route('/api/carpools/<cid>', methods=['PUT'])
def update_carpool(cid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE carpools SET name=%s,driver_name=%s,driver_phone=%s,max_seats=%s,notes=%s,status=%s WHERE id=%s',
        (d.get('name',''), d['driver_name'], d.get('driver_phone',''), d.get('max_seats',6), d.get('notes',''), d.get('status','open'), cid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/carpools/<cid>', methods=['DELETE'])
def delete_carpool(cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM carpools WHERE id=%s', (cid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/carpools/<cid>/members', methods=['POST'])
def add_carpool_member(cid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    mid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, "INSERT INTO carpool_members (id,carpool_id,youth_id,added_by,added_via) VALUES (%s,%s,%s,%s,'admin') ON CONFLICT (carpool_id,youth_id) DO NOTHING",
        (mid, cid, d.get('youth_id'), session.get('user_name','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/carpools/<cid>/members/<mid>', methods=['DELETE'])
def remove_carpool_member(cid, mid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM carpool_members WHERE id=%s AND carpool_id=%s', (mid, cid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/carpools')
def portal_get_carpools():
    event_id = request.args.get('event_id')
    conn = get_db()
    try:
        if event_id:
            carpools = fetchall(conn, """SELECT c.*, COUNT(cm.id) as member_count
                FROM carpools c LEFT JOIN carpool_members cm ON cm.carpool_id=c.id
                WHERE c.event_id=%s AND c.status='open'
                GROUP BY c.id ORDER BY c.name""", (event_id,))
        else:
            carpools = fetchall(conn, """SELECT c.*, COUNT(cm.id) as member_count,
                e.name as event_name, e.event_date
                FROM carpools c
                LEFT JOIN carpool_members cm ON cm.carpool_id=c.id
                LEFT JOIN events e ON c.event_id=e.id
                WHERE c.status='open'
                AND (e.event_date IS NULL OR e.event_date >= CURRENT_DATE::text)
                GROUP BY c.id, e.name, e.event_date ORDER BY e.name, c.name""")
        for c in carpools:
            c['members'] = fetchall(conn,
                'SELECT cm.id, y.first_name, y.last_name FROM carpool_members cm JOIN youth_participants y ON cm.youth_id=y.id WHERE cm.carpool_id=%s',
                (c['id'],))
        conn.close()
        return jsonify(carpools)
    except Exception as e:
        conn.close()
        app.logger.error(f'portal_get_carpools error: {e}')
        return jsonify([])

@app.route('/api/portal/carpools/create', methods=['POST'])
def portal_create_carpool():
    d = request.json or {}
    event_id    = (d.get('event_id') or '').strip()
    name        = (d.get('name') or '').strip()
    driver_name = (d.get('driver_name') or '').strip()
    driver_phone= (d.get('driver_phone') or '').strip()
    max_seats   = int(d.get('max_seats') or 6)
    notes       = (d.get('notes') or '').strip()
    youth_ids   = d.get('youth_ids', [])
    if not event_id or not driver_name:
        return jsonify({'error': 'Event and driver name are required'}), 400
    conn = get_db()
    event = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (event_id,))
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    import random, string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    cid = str(uuid.uuid4())
    carpool_name = name or f"{driver_name}'s Carpool"
    execute(conn, '''INSERT INTO carpools (id,event_id,name,driver_name,driver_phone,code,max_seats,notes,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')''',
        (cid, event_id, carpool_name, driver_name, driver_phone, code, max_seats, notes))
    # Auto-add creator's kids
    for yid in youth_ids:
        mid = str(uuid.uuid4())
        try:
            execute(conn, "INSERT INTO carpool_members (id,carpool_id,youth_id,added_by,added_via) VALUES (%s,%s,%s,%s,'portal')",
                (mid, cid, yid, driver_name))
        except Exception: pass
    conn.commit()
    carpool = fetchone(conn, '''SELECT c.*, e.name as event_name, e.event_date
        FROM carpools c JOIN events e ON c.event_id=e.id WHERE c.id=%s''', (cid,))
    carpool['members'] = fetchall(conn,
        'SELECT cm.id, cm.youth_id, y.first_name, y.last_name FROM carpool_members cm JOIN youth_participants y ON cm.youth_id=y.id WHERE cm.carpool_id=%s',
        (cid,))
    conn.close()
    return jsonify({'ok': True, 'carpool': carpool, 'code': code})

@app.route('/api/portal/carpools/leave', methods=['POST'])
def portal_leave_carpool():
    d = request.json or {}
    carpool_id = d.get('carpool_id','').strip()
    youth_ids  = d.get('youth_ids', [])
    if not carpool_id or not youth_ids:
        return jsonify({'error': 'Missing required fields'}), 400
    conn = get_db()
    for yid in youth_ids:
        execute(conn, 'DELETE FROM carpool_members WHERE carpool_id=%s AND youth_id=%s', (carpool_id, yid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/portal/events-for-carpools')
def portal_events_for_carpools():
    """Return upcoming events that have carpools enabled."""
    conn = get_db()
    try:
        events = fetchall(conn, """SELECT e.id, e.name, e.event_date, e.start_time
            FROM events e
            WHERE e.event_date >= CURRENT_DATE::text
            AND e.status IN ('draft','open')
            AND e.carpools_enabled = TRUE
            ORDER BY e.event_date, e.start_time LIMIT 30""")
    except Exception:
        # carpools_enabled column may not exist yet on live DB  -  fall back gracefully
        events = []
    conn.close()
    return jsonify(events)

@app.route('/api/portal/carpools/join', methods=['POST'])
def portal_join_carpool():
    d = request.json or {}
    code       = (d.get('code') or '').strip().upper()
    carpool_id = (d.get('carpool_id') or '').strip()
    youth_ids  = d.get('youth_ids', [])
    passphrase = (d.get('passphrase') or '').strip().lower()
    if not youth_ids:
        return jsonify({'error': 'At least one child required'}), 400
    conn = get_db()
    # Find carpool by ID or code
    if carpool_id:
        carpool = fetchone(conn, "SELECT * FROM carpools WHERE id=%s AND status='open'", (carpool_id,))
    elif code:
        carpool = fetchone(conn, "SELECT * FROM carpools WHERE UPPER(code)=%s AND status='open'", (code,))
    else:
        conn.close()
        return jsonify({'error': 'Carpool ID or code required'}), 400
    if not carpool:
        conn.close()
        return jsonify({'error': 'Carpool not found or no longer open'}), 404
    added = 0
    for yid in youth_ids:
        mid = str(uuid.uuid4())
        try:
            execute(conn, "INSERT INTO carpool_members (id,carpool_id,youth_id,added_by,added_via) VALUES (%s,%s,%s,%s,'portal') ON CONFLICT (carpool_id,youth_id) DO NOTHING",
                (mid, carpool['id'], yid, passphrase or 'parent'))
            added += 1
        except Exception: pass
    conn.commit()
    carpool = fetchone(conn, 'SELECT * FROM carpools WHERE id=%s', (carpool['id'],))
    carpool['members'] = fetchall(conn, 'SELECT cm.id, cm.youth_id, y.first_name, y.last_name FROM carpool_members cm JOIN youth_participants y ON cm.youth_id=y.id WHERE cm.carpool_id=%s', (carpool['id'],))
    conn.close()
    return jsonify({'ok': True, 'added': added, 'carpool': carpool})

@app.route('/api/pickup/queue')
def pickup_queue():
    conn = get_db()
    try:
        # Only show kids from OPEN events (or signed in within last 8 hours as fallback)
        individuals = fetchall(conn, """
            SELECT ysi.*, y.first_name, y.last_name, e.name as event_name, e.id as event_id,
            f.passphrase as family_passphrase
            FROM youth_sign_ins ysi
            JOIN youth_participants y ON ysi.youth_id=y.id
            LEFT JOIN events e ON ysi.event_id=e.id
            LEFT JOIN youth_family_links yfl ON yfl.youth_id=ysi.youth_id
            LEFT JOIN families f ON f.id=yfl.family_id
            WHERE ysi.signed_out_at IS NULL
            AND (
                (e.status = 'open')
                OR (ysi.event_id IS NULL AND ysi.signed_in_at >= NOW() - INTERVAL '8 hours')
            )
            AND NOT EXISTS (
                SELECT 1 FROM carpool_members cm
                JOIN carpools cp ON cm.carpool_id=cp.id
                WHERE cm.youth_id=ysi.youth_id AND cp.event_id=ysi.event_id
            )
            ORDER BY e.name, y.last_name, y.first_name
        """)
        # Also include recently signed-out kids (last 2 hours) so picked-up column updates
        signed_out = fetchall(conn, """
            SELECT ysi.*, y.first_name, y.last_name, e.name as event_name, e.id as event_id
            FROM youth_sign_ins ysi
            JOIN youth_participants y ON ysi.youth_id=y.id
            LEFT JOIN events e ON ysi.event_id=e.id
            WHERE ysi.signed_out_at IS NOT NULL
            AND ysi.signed_out_at >= NOW() - INTERVAL '2 hours'
            AND NOT EXISTS (
                SELECT 1 FROM carpool_members cm
                JOIN carpools cp ON cm.carpool_id=cp.id
                WHERE cm.youth_id=ysi.youth_id AND cp.event_id=ysi.event_id
            )
            ORDER BY ysi.signed_out_at DESC
        """)
        individuals = individuals + signed_out
    except Exception as e:
        app.logger.error(f'pickup_queue individuals error: {e}')
        individuals = []

    try:
        carpools_rows = fetchall(conn, """
            SELECT cp.id as carpool_id, cp.name as carpool_name, cp.code as carpool_code,
                   cp.driver_name, cp.driver_phone, cp.event_id, e.name as event_name
            FROM carpools cp
            JOIN events e ON cp.event_id=e.id
            JOIN carpool_members cm ON cm.carpool_id=cp.id
            JOIN youth_sign_ins ysi ON ysi.youth_id=cm.youth_id AND ysi.event_id=cp.event_id
            WHERE e.status = 'open'
            AND ysi.signed_out_at IS NULL
            GROUP BY cp.id, cp.name, cp.code, cp.driver_name, cp.driver_phone, cp.event_id, e.name
            ORDER BY cp.name
        """)
        for cp in carpools_rows:
            cp['kids'] = fetchall(conn, """
                SELECT ysi.id as sign_in_id, ysi.youth_id, ysi.signed_out_at,
                       y.first_name, y.last_name, cm.id as member_id
                FROM carpool_members cm
                JOIN youth_participants y ON cm.youth_id=y.id
                LEFT JOIN youth_sign_ins ysi ON ysi.youth_id=cm.youth_id
                    AND ysi.event_id=%s
                WHERE cm.carpool_id=%s
                ORDER BY y.last_name, y.first_name
            """, (cp['event_id'], cp['carpool_id']))
        # Also include recently completed carpools (all signed out in last 2 hours) for picked-up column
        completed_carpools = fetchall(conn, """
            SELECT cp.id as carpool_id, cp.name as carpool_name, cp.code as carpool_code,
                   cp.driver_name, cp.driver_phone, cp.event_id, e.name as event_name
            FROM carpools cp
            JOIN events e ON cp.event_id=e.id
            WHERE e.status = 'open'
            AND EXISTS (
                SELECT 1 FROM carpool_members cm
                JOIN youth_sign_ins ysi ON ysi.youth_id=cm.youth_id AND ysi.event_id=cp.event_id
                WHERE cm.carpool_id=cp.id AND ysi.signed_out_at IS NOT NULL
                AND ysi.signed_out_at >= NOW() - INTERVAL '2 hours'
            )
            AND NOT EXISTS (
                SELECT 1 FROM carpool_members cm
                JOIN youth_sign_ins ysi ON ysi.youth_id=cm.youth_id AND ysi.event_id=cp.event_id
                WHERE cm.carpool_id=cp.id AND ysi.signed_out_at IS NULL
            )
            GROUP BY cp.id, cp.name, cp.code, cp.driver_name, cp.driver_phone, cp.event_id, e.name
        """)
        for cp in completed_carpools:
            cp['kids'] = fetchall(conn, """
                SELECT ysi.id as sign_in_id, ysi.youth_id, ysi.signed_out_at,
                       y.first_name, y.last_name, cm.id as member_id
                FROM carpool_members cm
                JOIN youth_participants y ON cm.youth_id=y.id
                LEFT JOIN youth_sign_ins ysi ON ysi.youth_id=cm.youth_id AND ysi.event_id=%s
                WHERE cm.carpool_id=%s
                ORDER BY y.last_name, y.first_name
            """, (cp['event_id'], cp['carpool_id']))
            cp['completed'] = True
        carpools_rows = carpools_rows + completed_carpools
    except Exception as e:
        app.logger.error(f'pickup_queue carpools error: {e}')
        carpools_rows = []

    conn.close()
    return jsonify({'individuals': individuals, 'carpools': carpools_rows})

@app.route('/api/pickup/clear', methods=['POST'])
def pickup_clear():
    """Sign out everyone currently waiting  -  used for manual clear at end of day."""
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, """UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by='staff-clear'
        WHERE signed_out_at IS NULL""")
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/pickup/cleanup', methods=['POST'])
def pickup_cleanup():
    """Clear orphaned sign-ins  -  kids stuck in deleted/closed events."""
    err = require_auth()
    if err: return err
    conn = get_db()
    # Sign out anyone in a closed or deleted event who is still marked as signed in
    result = fetchone(conn, """
        SELECT COUNT(*) as count FROM youth_sign_ins ysi
        LEFT JOIN events e ON ysi.event_id=e.id
        WHERE ysi.signed_out_at IS NULL
        AND (e.id IS NULL OR e.status != 'open')
    """)
    count = result['count'] if result else 0
    execute(conn, """UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by='auto-cleanup'
        WHERE signed_out_at IS NULL
        AND event_id IN (
            SELECT id FROM events WHERE status != 'open'
        )""")
    execute(conn, """UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by='auto-cleanup'
        WHERE signed_out_at IS NULL
        AND event_id IS NOT NULL
        AND event_id NOT IN (SELECT id FROM events)""")
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'cleared': count})

@app.route('/api/pickup/carpool-signout', methods=['POST'])
def carpool_signout():
    d = request.json or {}
    carpool_id    = d.get('carpool_id')
    event_id      = d.get('event_id')
    signed_out_by = d.get('signed_out_by', '')
    if not carpool_id or not event_id:
        return jsonify({'error': 'Missing fields'}), 400
    conn = get_db()
    execute(conn, 'UPDATE youth_sign_ins SET signed_out_at=NOW(), signed_out_by=%s WHERE youth_id IN (SELECT youth_id FROM carpool_members WHERE carpool_id=%s) AND event_id=%s AND signed_out_at IS NULL',
        (signed_out_by, carpool_id, event_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



# ─────────────────────────────────────────────
#  MISSING ROUTES  -  added by audit
# ─────────────────────────────────────────────

# ── Notifications ──
@app.route('/api/notifications')
def get_notifications():
    err = require_auth()
    if err: return err
    conn = get_db()
    needs_action = []
    activity     = []

    # Pending hours awaiting approval
    try:
        pending = fetchall(conn, '''
            SELECT ph.id, ph.volunteer_id, ph.event, ph.event_id, ph.date,
                   ph.hours, ph.role, ph.notes, ph.status, ph.submitted_at,
                   v.name as volunteer_name
            FROM pending_hours ph
            LEFT JOIN volunteers v ON ph.volunteer_id=v.id
            WHERE ph.status IN (\'pending\',\'pending_review\')
            ORDER BY ph.submitted_at DESC NULLS LAST
            LIMIT 100''')
        for ph in pending:
            is_override = ph.get('status') == 'pending_review'
            needs_action.append({
                'id':    ph['id'],
                'type':  'pending_hours',
                'icon':  '⏱',
                'color': 'amber',
                'title': f'{ph["volunteer_name"] or "A volunteer"}  -  {ph["hours"]}h',
                'sub':   f'{ph["event"] or "General"} · {ph["date"] or ""}' +
                         (' · Needs review (no event)' if is_override else ''),
                'data':  ph,
            })
    except Exception as e:
        app.logger.warning(f'notifications pending_hours: {e}')

    # Profile update requests
    try:
        profiles = fetchall(conn, '''
            SELECT ph.id, ph.volunteer_id, ph.notes, ph.submitted_at,
                   v.name as volunteer_name
            FROM pending_hours ph
            LEFT JOIN volunteers v ON ph.volunteer_id=v.id
            WHERE ph.status = \'pending_profile\'
            ORDER BY ph.submitted_at DESC NULLS LAST LIMIT 20''')
        for p in profiles:
            needs_action.append({
                'id':    p['id'],
                'type':  'profile_update',
                'icon':  '👤',
                'color': 'blue',
                'title': f'{p["volunteer_name"] or "A volunteer"}  -  profile update',
                'sub':   'Requested profile change awaiting review',
                'data':  p,
            })
    except Exception as e:
        app.logger.warning(f'notifications profiles: {e}')

    # Recent approved hours (activity feed)
    try:
        recent = fetchall(conn, '''
            SELECT h.*, v.name as volunteer_name
            FROM hours h LEFT JOIN volunteers v ON h.volunteer_id=v.id
            WHERE h.created_at >= NOW() - INTERVAL \'7 days\'
            ORDER BY h.created_at DESC LIMIT 20''')
        for h in recent:
            activity.append({
                'id':    h['id'],
                'type':  'hours_approved',
                'icon':  '✅',
                'color': 'green',
                'title': f'{h["volunteer_name"] or "Volunteer"}  -  {h["hours"]}h approved',
                'sub':   f'{h["event"] or ""} · {h["date"] or ""}',
                'data':  h,
            })
    except Exception as e:
        app.logger.warning(f'notifications activity: {e}')

    conn.close()
    return jsonify({
        'needs_action':  needs_action,
        'activity':      activity,
        'total_action':  len(needs_action),
    })

# ── Email settings extras ──
@app.route('/api/email-settings/check-events', methods=['POST'])
def email_check_events():
    return jsonify({'ok': True})

@app.route('/api/email-settings/send-report/<rid>', methods=['GET','POST'])
def email_send_report(rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # rid can be event_id  -  find the most recent close log
    close_log = fetchone(conn, '''SELECT el.*, e.name as event_name, e.event_date,
        v.name as elic_name
        FROM event_logs el
        LEFT JOIN events e ON el.event_id=e.id
        LEFT JOIN elics eli ON el.elic_id=eli.id
        LEFT JOIN volunteers v ON eli.volunteer_id=v.id
        WHERE el.event_id=%s AND el.action='close'
        ORDER BY el.id DESC LIMIT 1''', (rid,))
    if not close_log:
        conn.close(); return jsonify({'error': 'No closed event log found'}), 404
    # Get opening log
    open_log = fetchone(conn, '''SELECT el.*, v.name as elic_name
        FROM event_logs el
        LEFT JOIN elics eli ON el.elic_id=eli.id
        LEFT JOIN volunteers v ON eli.volunteer_id=v.id
        WHERE el.event_id=%s AND el.action='open'
        ORDER BY el.id LIMIT 1''', (rid,))
    closing_checklist = fetchall(conn,
        'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id',
        (close_log['id'],))
    opening_checklist = fetchall(conn,
        'SELECT * FROM event_checklist_responses WHERE event_log_id=%s ORDER BY id',
        (open_log['id'],)) if open_log else []
    hours = fetchall(conn, '''SELECT h.*, v.name as volunteer_name
        FROM hours h JOIN volunteers v ON h.volunteer_id=v.id
        WHERE h.event_id=%s ORDER BY v.name''', (rid,))
    s = get_email_settings()
    recipients = get_recipient_emails(s)
    conn.close()
    if not recipients:
        return jsonify({'error': 'No report recipients configured in Email Settings'}), 400
    total = sum(float(h.get('hours') or 0) for h in hours)
    def checklist_rows(items, label, icon):
        if not items: return f'<p style="color:#888;font-size:13px"><em>No {label.lower()} items recorded.</em></p>'
        rows = ''.join(f'''<tr>
            <td style="padding:8px 12px;border-bottom:1px solid #eee">{r.get('label','')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:600;color:{'#16a34a' if str(r.get('response','')).lower() in ('true','yes','done') else '#dc2626' if r.get('item_type')=='checkbox' else '#374151'}">
                {'✅ Done' if str(r.get('response','')).lower() in ('true','yes','done') else ('❌ Not Done' if r.get('item_type')=='checkbox' else str(r.get('response',' - ') or ' - '))}
            </td></tr>''' for r in items)
        return f'''<h3 style="color:#145466;font-size:14px;font-weight:700;margin:20px 0 8px">{icon} {label}</h3>
        <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0db;font-size:13px">
        <thead><tr style="background:#f0f8fa"><th style="padding:8px 12px;text-align:left;color:#5f5e5a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Item</th>
        <th style="padding:8px 12px;text-align:left;color:#5f5e5a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Response</th></tr></thead>
        <tbody>{rows}</tbody></table>'''
    hours_html = ''
    if hours:
        hrs_rows = ''.join(f'''<tr><td style="padding:8px 12px;border-bottom:1px solid #eee">{h.get('volunteer_name','')}</td>
            <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:700;color:#145466">{h.get('hours',0)}h</td></tr>''' for h in hours)
        hours_html = f'''<h3 style="color:#145466;font-size:14px;font-weight:700;margin:20px 0 8px">⏱ Volunteer Hours</h3>
        <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0db;font-size:13px">
        <thead><tr style="background:#f0f8fa">
        <th style="padding:8px 12px;text-align:left;color:#5f5e5a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Volunteer</th>
        <th style="padding:8px 12px;text-align:left;color:#5f5e5a;font-size:11px;text-transform:uppercase;letter-spacing:0.5px">Hours</th></tr></thead>
        <tbody>{hrs_rows}</tbody>
        <tfoot><tr style="background:#f0f8fa"><td style="padding:8px 12px;font-weight:700;color:#145466">Total</td>
        <td style="padding:8px 12px;font-weight:800;font-size:16px;color:#145466">{total:.1f}h</td></tr></tfoot></table>'''
    body = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:620px;margin:0 auto">
    <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:10px 10px 0 0;color:#fff">
        <img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" style="height:40px;margin-bottom:12px" alt="HWTC"/>
        <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;opacity:0.7">Event Report</div>
        <div style="font-size:22px;font-weight:800;margin:4px 0">🔒 {close_log.get('event_name','')}</div>
        <div style="font-size:13px;opacity:0.75">{close_log.get('event_date') or ''} &nbsp;·&nbsp; Opened by {open_log.get('elic_name',' - ') if open_log else ' - '} &nbsp;·&nbsp; Closed by {close_log.get('elic_name',' - ')}</div>
    </div>
    <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:28px 32px;border-radius:0 0 10px 10px">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:4px">
            <div style="background:#f0f8fa;border-radius:8px;padding:14px;text-align:center">
                <div style="font-size:26px;font-weight:900;color:#145466">{len(hours)}</div>
                <div style="font-size:11px;color:#888;margin-top:2px">Volunteers</div>
            </div>
            <div style="background:#f0f8fa;border-radius:8px;padding:14px;text-align:center">
                <div style="font-size:26px;font-weight:900;color:#145466">{total:.1f}h</div>
                <div style="font-size:11px;color:#888;margin-top:2px">Total Hours</div>
            </div>
            <div style="background:#f0f8fa;border-radius:8px;padding:14px;text-align:center">
                <div style="font-size:26px;font-weight:900;color:#145466">{len(opening_checklist)+len(closing_checklist)}</div>
                <div style="font-size:11px;color:#888;margin-top:2px">Checklist Items</div>
            </div>
        </div>
        {checklist_rows(opening_checklist, 'Opening Checklist', '🟢')}
        {checklist_rows(closing_checklist, 'Closing Checklist', '✅')}
        {hours_html}
    </div>
    <p style="text-align:center;font-size:11px;color:#9ca3af;margin-top:12px">RoleCall  -  Horizon West Theatre Company</p>
    </div>'''
    subject = f'Event Report: {close_log.get("event_name","")}  -  {close_log.get("event_date","")}'
    fi = (request.json or {}).get('from_identity') or {}
    ok, msg = send_email(recipients, subject, body, fi.get('email') or None, fi.get('name') or None)
    if ok: return jsonify({'ok': True})
    return jsonify({'error': msg or 'Send failed'}), 500

# ── Event waivers ──
@app.route('/api/events/<eid>/email-signups', methods=['POST'])
def email_event_signups(eid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    subject = d.get('subject','').strip()
    body = d.get('body','').strip()
    if not subject or not body:
        return jsonify({'error': 'Subject and message required'}), 400
    conn = get_db()
    event = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (eid,))
    if not event:
        conn.close()
        return jsonify({'error': 'Event not found'}), 404
    # Get emails of all signed-up volunteers (status='interested')
    signups = fetchall(conn, '''SELECT v.email, v.name FROM event_rsvps er
        JOIN volunteers v ON er.volunteer_id=v.id
        WHERE er.event_id=%s AND er.status IN ('interested','confirmed')
        AND v.email IS NOT NULL AND v.email!=''
        ''', (eid,))
    conn.close()
    if not signups:
        return jsonify({'error': 'No signed-up volunteers with email addresses'}), 400
    recipients = list({s['email'].strip().lower() for s in signups if s['email']})
    event_name = event.get('name', 'Event')
    event_date = event.get('event_date', '')
    html_body = f'''<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
      <div style="background:#0d9488;padding:20px;border-radius:8px 8px 0 0">
        <div style="color:rgba(255,255,255,0.8);font-size:12px;margin-bottom:4px">Event Update</div>
        <h2 style="color:white;margin:0">{event_name}</h2>
        {f'<div style="color:rgba(255,255,255,0.8);font-size:13px;margin-top:4px">{event_date}</div>' if event_date else ''}
      </div>
      <div style="background:#f8fafc;padding:24px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;border-top:none">
        <div style="white-space:pre-wrap;font-size:15px;line-height:1.7;color:#1e293b">{body}</div>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0"/>
        <p style="font-size:12px;color:#94a3b8;margin:0">This message was sent to volunteers signed up for <strong>{event_name}</strong> by Horizon West Theater Company.</p>
      </div>
    </div>'''
    try:
        send_email(recipients, subject, html_body)
        return jsonify({'ok': True, 'sent_to': len(recipients)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/<eid>/waivers', methods=['POST'])
def add_event_waiver(eid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    rid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO event_waivers (id,event_id,waiver_type_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
        (rid, eid, d.get('waiver_type_id')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/events/<eid>/waivers/<wid>', methods=['DELETE'])
def remove_event_waiver(eid, wid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_waivers WHERE id=%s AND event_id=%s', (wid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Event ELICs ──
@app.route('/api/events/<eid>/elics', methods=['POST'])
def add_event_elic(eid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    elic_id = d.get('elic_id')
    rid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, 'INSERT INTO event_elics (id,event_id,elic_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
        (rid, eid, elic_id))
    # Also sync to assigned_events on the elic record
    try:
        elic = fetchone(conn, 'SELECT assigned_events FROM elics WHERE id=%s', (elic_id,))
        if elic:
            assigned = json.loads(elic.get('assigned_events') or '[]')
            if eid not in assigned:
                assigned.append(eid)
                execute(conn, 'UPDATE elics SET assigned_events=%s WHERE id=%s', (json.dumps(assigned), elic_id))
    except Exception:
        pass
    conn.commit()
    # Return the full assignment record so frontend can push it properly
    row = fetchone(conn, """SELECT ee.id as assignment_id, el.id as elic_id,
        el.is_master, v.name as volunteer_name, v.id as volunteer_id,
        COALESCE(v.background_check_status,'none') as background_check_status
        FROM event_elics ee JOIN elics el ON ee.elic_id=el.id
        JOIN volunteers v ON el.volunteer_id=v.id
        WHERE ee.event_id=%s AND ee.elic_id=%s""", (eid, elic_id))
    conn.close()
    return jsonify(row or {'ok': True})
def remove_event_elic(eid, rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    # Get elic_id before deleting
    row = fetchone(conn, 'SELECT elic_id FROM event_elics WHERE id=%s AND event_id=%s', (rid, eid))
    execute(conn, 'DELETE FROM event_elics WHERE id=%s AND event_id=%s', (rid, eid))
    # Sync assigned_events
    if row:
        try:
            elic = fetchone(conn, 'SELECT assigned_events FROM elics WHERE id=%s', (row['elic_id'],))
            if elic:
                assigned = json.loads(elic.get('assigned_events') or '[]')
                assigned = [e for e in assigned if e != eid]
                execute(conn, 'UPDATE elics SET assigned_events=%s WHERE id=%s', (json.dumps(assigned), row['elic_id']))
        except Exception:
            pass
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/events/default-elic')
def get_default_elic():
    err = require_auth()
    if err: return err
    prod_id = request.args.get('production_id')
    prog_id = request.args.get('program_id')
    conn = get_db()
    elic = None
    if prod_id:
        p = fetchone(conn, 'SELECT default_elic_id FROM productions WHERE id=%s', (prod_id,))
        if p and p.get('default_elic_id'):
            elic = fetchone(conn, '''SELECT e.*, v.name as volunteer_name FROM elics e
                JOIN volunteers v ON e.volunteer_id=v.id WHERE e.id=%s''', (p['default_elic_id'],))
    elif prog_id:
        p = fetchone(conn, 'SELECT default_elic_id, instructor_id FROM youth_programs WHERE id=%s', (prog_id,))
        if p:
            elic_id = p.get('default_elic_id')
            # Fall back to instructor's elic record if no default_elic_id set
            if not elic_id and p.get('instructor_id'):
                er = fetchone(conn, 'SELECT id FROM elics WHERE volunteer_id=%s', (p['instructor_id'],))
                if er: elic_id = er['id']
            if elic_id:
                elic = fetchone(conn, '''SELECT e.*, v.name as volunteer_name FROM elics e
                    JOIN volunteers v ON e.volunteer_id=v.id WHERE e.id=%s''', (elic_id,))
    conn.close()
    return jsonify({'elic': elic, 'elic_id': elic['id'] if elic else None})

# ── Families ──
@app.route('/api/families/<fid>', methods=['DELETE'])
def delete_family(fid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM families WHERE id=%s', (fid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/families/<fid>/members', methods=['POST'])
def add_family_member(fid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=%s WHERE id=%s', (fid, d.get('youth_id')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/families/<fid>/members/<yid>', methods=['DELETE'])
def remove_family_member(fid, yid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET family_id=NULL WHERE id=%s AND family_id=%s', (yid, fid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal announcements (admin manage) ──
@app.route('/api/portal/announcements', methods=['POST'])
def create_portal_announcement_admin():
    err = require_auth()
    if err: return err
    d = request.json or {}
    aid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO portal_announcements
            (id,production_id,program_id,title,body,status,author_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''',
            (aid, d.get('production_id'), d.get('program_id'),
             d.get('title',''), d.get('body',''),
             d.get('status','draft'), session.get('user_id','')))
        conn.commit()
        row = fetchone(conn, 'SELECT * FROM portal_announcements WHERE id=%s', (aid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.close()
        app.logger.error(f'create_portal_announcement_admin error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/portal/announcements/<aid>', methods=['PUT'])
def update_portal_announcement_admin(aid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE portal_announcements SET title=%s, body=%s, status=%s WHERE id=%s',
        (d.get('title',''), d.get('body',''), d.get('status','published'), aid))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM portal_announcements WHERE id=%s', (aid,))
    conn.close()
    return jsonify(row or {'ok': True})

@app.route('/api/portal/announcements/<aid>', methods=['DELETE'])
def delete_portal_announcement_admin(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM portal_announcements WHERE id=%s', (aid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal files & folders ──
# Real table schema: id, program_id, production_id, title, drive_url, description, folder, author_id

@app.route('/api/portal/files', methods=['POST'])
def create_portal_file():
    err = require_auth()
    if err: return err
    d = request.json or {}
    fid = str(uuid.uuid4())
    conn = get_db()
    program_id    = d.get('program_id') or None
    production_id = d.get('production_id') or None
    title      = d.get('title') or d.get('name','')
    drive_url  = d.get('drive_url') or d.get('url','')
    folder     = d.get('folder','General')
    author_id  = session.get('user_id')
    execute(conn, '''INSERT INTO portal_files
        (id, program_id, production_id, title, drive_url, folder, author_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (fid, program_id, production_id, title, drive_url, folder, author_id))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM portal_files WHERE id=%s', (fid,))
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

@app.route('/api/portal/folders')
def get_portal_folders():
    err = require_auth()
    if err: return err
    program_id    = request.args.get('program_id')
    production_id = request.args.get('production_id')
    conn = get_db()
    if program_id:
        rows = fetchall(conn, "SELECT DISTINCT folder FROM portal_files WHERE program_id=%s AND folder IS NOT NULL ORDER BY folder", (program_id,))
    elif production_id:
        rows = fetchall(conn, "SELECT DISTINCT folder FROM portal_files WHERE production_id=%s AND folder IS NOT NULL ORDER BY folder", (production_id,))
    else:
        rows = []
    conn.close()
    # Return as list of folder name strings for the pill UI
    return jsonify([r['folder'] for r in rows if r.get('folder') and r['folder'] != 'General'])

@app.route('/api/portal/folders', methods=['POST'])
def create_portal_folder():
    """Create a placeholder file entry to register a folder name."""
    err = require_auth()
    if err: return err
    d = request.json or {}
    folder_name   = (d.get('name') or '').strip()
    program_id    = d.get('program_id') or None
    production_id = d.get('production_id') or None
    if not folder_name:
        return jsonify({'error': 'Folder name required'}), 400
    fid = str(uuid.uuid4())
    conn = get_db()
    # Insert a placeholder row so the folder name is registered
    execute(conn, '''INSERT INTO portal_files
        (id, program_id, production_id, title, drive_url, folder, description)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (fid, program_id, production_id,
         '__folder__' + folder_name, '', folder_name, '__folder__'))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'folder': folder_name})

@app.route('/api/portal/folders/<folder_name>', methods=['DELETE'])
def delete_portal_folder(folder_name):
    err = require_auth()
    if err: return err
    program_id    = request.args.get('program_id')
    production_id = request.args.get('production_id')
    conn = get_db()
    # Move files in this folder to General, then delete the placeholder
    if program_id:
        execute(conn, "UPDATE portal_files SET folder='General' WHERE program_id=%s AND folder=%s AND description!='__folder__'", (program_id, folder_name))
        execute(conn, "DELETE FROM portal_files WHERE program_id=%s AND folder=%s AND description='__folder__'", (program_id, folder_name))
    elif production_id:
        execute(conn, "UPDATE portal_files SET folder='General' WHERE production_id=%s AND folder=%s AND description!='__folder__'", (production_id, folder_name))
        execute(conn, "DELETE FROM portal_files WHERE production_id=%s AND folder=%s AND description='__folder__'", (production_id, folder_name))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal callout (POST = set callout) ──
@app.route('/api/portal/callout', methods=['POST'])
def set_portal_callout():
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, "INSERT INTO settings (key,value) VALUES ('portal_callout',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        (json.dumps(d.get('callout')),))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal youth update ──
@app.route('/api/portal/youth/<yid>', methods=['POST'])
def portal_update_youth(yid):
    d = request.json or {}
    conn = get_db()
    # Queue for staff review
    pid = str(uuid.uuid4())
    execute(conn, "INSERT INTO pending_hours (id,volunteer_id,event,date,hours,notes,status) VALUES (%s,%s,'Profile Update Request',CURRENT_DATE,0,%s,'pending_review')",
        (pid, yid, json.dumps(d)))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Portal program waiver status ──
@app.route('/api/portal/production/<pid>/events')
def portal_production_events(pid):
    conn = get_db()
    events = fetchall(conn, '''SELECT e.*,
        et.name as event_type_name, et.color as event_type_color
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        WHERE e.production_id=%s
        ORDER BY e.event_date ASC NULLS LAST, e.start_time ASC NULLS LAST''', (pid,))
    conn.close()
    return jsonify(events)

@app.route('/api/portal/program/<pid>/events')
def portal_program_events(pid):
    conn = get_db()
    events = fetchall(conn, '''SELECT e.*,
        et.name as event_type_name, et.color as event_type_color
        FROM events e
        LEFT JOIN event_types et ON e.event_type_id=et.id
        WHERE e.program_id=%s
        ORDER BY e.event_date ASC NULLS LAST, e.start_time ASC NULLS LAST''', (pid,))
    conn.close()
    return jsonify(events)

@app.route('/api/portal/production/<pid>/conflicts')
def portal_production_conflicts(pid):
    yid = request.args.get('youth_id')
    conn = get_db()
    try:
        if yid:
            conflicts = fetchall(conn, '''SELECT pc.*, e.name as event_name, e.event_date
                FROM production_conflicts pc
                LEFT JOIN events e ON pc.event_id=e.id
                WHERE pc.production_id=%s
                ORDER BY e.event_date ASC NULLS LAST''', (pid,))
            # Mark which ones belong to this youth
            for c in conflicts:
                c['is_mine'] = str(c.get('youth_id','')) == str(yid)
        else:
            conflicts = []
    except Exception:
        conflicts = []
    conn.close()
    return jsonify(conflicts)

@app.route('/api/portal/program/<pid>/waiver-status')
def portal_program_waiver_status(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        required = fetchall(conn, '''SELECT prw.waiver_type_id, wt.name FROM program_required_waivers prw
            JOIN waiver_types wt ON prw.waiver_type_id=wt.id
            WHERE prw.program_id=%s''', (pid,))
    except Exception:
        conn.close()
        return jsonify({'required_waivers': [], 'participants': []})
    if not required:
        conn.close()
        return jsonify({'required_waivers': [], 'participants': []})
    enrolled = fetchall(conn, '''SELECT y.id, y.first_name, y.last_name
        FROM youth_participants y
        JOIN youth_program_enrollments ype ON ype.youth_id=y.id
        WHERE ype.program_id=%s AND y.status='active' ORDER BY y.last_name, y.first_name''', (pid,))
    participants = []
    for y in enrolled:
        signed = fetchall(conn, 'SELECT waiver_type_id FROM youth_waivers WHERE youth_id=%s', (y['id'],))
        signed_ids = {s['waiver_type_id'] for s in signed}
        missing = [r for r in required if r['waiver_type_id'] not in signed_ids]
        participants.append({**y, 'missing_waivers': missing, 'all_signed': len(missing)==0})
    conn.close()
    return jsonify({'required_waivers': required, 'participants': participants})

# ── Youth programs enrollment ──
@app.route('/api/youth-programs/<pid>/enrolled')
def get_program_enrolled(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    try:
        # Step 1: guaranteed columns only (no optional ones)
        rows = fetchall(conn, '''SELECT ype.id as enrollment_id, ype.youth_id, ype.program_id,
            ype.enrolled_date, ype.notes, ype.created_at,
            y.first_name, y.last_name, y.dob,
            y.portal_last_login
            FROM youth_program_enrollments ype
            JOIN youth_participants y ON ype.youth_id=y.id
            WHERE ype.program_id=%s ORDER BY y.last_name, y.first_name''', (pid,))
        # Try to add optional columns one at a time
        for row in rows:
            row.setdefault('shirt_size', '')
            row.setdefault('portal_last_login', None)
            row.setdefault('family_passphrase', None)
            row.setdefault('family_name', None)
            row.setdefault('youth_id', row.get('youth_id'))
        # Attempt to enrich with shirt_size and portal_last_login
        try:
            enriched = fetchall(conn, '''SELECT ype.id as enrollment_id,
                y.shirt_size, y.portal_last_login,
                (SELECT f.passphrase FROM youth_family_links yfl
                 JOIN families f ON f.id=yfl.family_id
                 WHERE yfl.youth_id=y.id LIMIT 1) as family_passphrase,
                (SELECT f.name FROM youth_family_links yfl
                 JOIN families f ON f.id=yfl.family_id
                 WHERE yfl.youth_id=y.id LIMIT 1) as family_name
                FROM youth_program_enrollments ype
                JOIN youth_participants y ON ype.youth_id=y.id
                WHERE ype.program_id=%s''', (pid,))
            enriched_map = {r['enrollment_id']: r for r in enriched}
            for row in rows:
                extra = enriched_map.get(row['enrollment_id'], {})
                row['shirt_size'] = extra.get('shirt_size') or ''
                row['portal_last_login'] = extra.get('portal_last_login')
                row['family_passphrase'] = extra.get('family_passphrase')
                row['family_name'] = extra.get('family_name')
        except Exception as enrich_err:
            app.logger.warning(f'get_program_enrolled enrich failed (non-fatal): {enrich_err}')
    except Exception as e:
        app.logger.error(f'get_program_enrolled error: {e}')
        rows = []
    conn.close()
    return jsonify(rows)

@app.route('/api/youth-programs/<pid>/enroll', methods=['POST'])
def enroll_in_program(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    # Supports both single youth_id and bulk youth_ids array
    youth_ids = d.get('youth_ids') or ([d.get('youth_id')] if d.get('youth_id') else [])
    enrolled_date = d.get('enrolled_date', '') or ''
    notes = d.get('notes', '') or ''
    for yid in youth_ids:
        if not yid: continue
        eid = str(uuid.uuid4())
        execute(conn, '''INSERT INTO youth_program_enrollments (id,youth_id,program_id,enrolled_date,notes)
            VALUES (%s,%s,%s,%s,%s) ON CONFLICT (youth_id,program_id) DO NOTHING''',
            (eid, yid, pid, enrolled_date, notes))
    conn.commit()
    row = fetchone(conn, '''SELECT ype.*, y.first_name, y.last_name, yp.name as program_name
        FROM youth_program_enrollments ype
        JOIN youth_participants y ON ype.youth_id=y.id
        JOIN youth_programs yp ON ype.program_id=yp.id
        WHERE ype.id=%s''', (eid,))
    conn.close()
    return jsonify(row or {'ok': True})

@app.route('/api/youth-enrollments/<eid>', methods=['DELETE'])
def delete_youth_enrollment(eid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM youth_program_enrollments WHERE id=%s', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Volunteer / Youth linking ──
@app.route('/api/volunteers/<vol_id>/link-participant', methods=['POST'])
def link_volunteer_to_participant(vol_id):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET linked_volunteer_id=%s WHERE id=%s', (vol_id, d.get('youth_id')))
    execute(conn, 'UPDATE volunteers SET linked_youth_id=%s WHERE id=%s', (d.get('youth_id'), vol_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/youth/<yid>/link-volunteer', methods=['POST'])
def link_youth_to_volunteer(yid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE youth_participants SET linked_volunteer_id=%s WHERE id=%s', (d.get('volunteer_id'), yid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Users role update ──
@app.route('/api/users/<uid>/role', methods=['PUT'])
def update_user_role(uid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE users SET role=%s WHERE id=%s', (d.get('role','staff'), uid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Waiver toggle required ──
@app.route('/api/waiver-types/<tid>/toggle-required', methods=['POST'])
def toggle_waiver_required(tid):
    err = require_admin()
    if err: return err
    conn = get_db()
    # Toggle both columns  -  required_for_volunteering is used by kiosk, required_all by admin UI
    execute(conn, '''UPDATE waiver_types
        SET required_for_volunteering = NOT COALESCE(required_for_volunteering, FALSE),
            required_all = NOT COALESCE(required_all, FALSE)
        WHERE id=%s''', (tid,))
    conn.commit()
    row = fetchone(conn, 'SELECT required_for_volunteering, required_all FROM waiver_types WHERE id=%s', (tid,))
    conn.close()
    new_val = bool(row['required_for_volunteering']) if row else False
    return jsonify({'ok': True, 'required_all': new_val, 'required_for_volunteering': new_val})

# ── Donors missing routes ──
@app.route('/api/donor-benefits')
def get_all_donor_benefits():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT db.*, dt.name as tier_name FROM donor_tier_benefits db
        JOIN donor_tiers dt ON db.tier_id=dt.id ORDER BY dt.min_amount, db.sort_order''')
    conn.close()
    return jsonify(rows)

@app.route('/api/donations')
def get_all_donations_list():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT dd.*, dn.display_name, c.name as campaign_name
        FROM donor_donations dd
        JOIN donors dn ON dd.donor_id=dn.id
        LEFT JOIN donor_campaigns c ON dd.campaign_id=c.id
        ORDER BY dd.donation_date DESC NULLS LAST LIMIT 500''')
    conn.close()
    return jsonify(rows)

# ── Kiosk unauthorized pickup notify ──
@app.route('/api/kiosk/unauthorized-pickup-notify', methods=['POST'])
def kiosk_unauthorized_pickup_notify():
    d = request.json or {}
    try:
        s = get_email_settings()
        recipients = get_recipient_emails(s)
        if recipients:
            send_email(recipients, 'ALERT: Unauthorized Pickup Attempt',
                f'<p style="font-family:sans-serif;color:#dc2626"><strong>Unauthorized pickup attempt</strong> at the kiosk.<br/>'
                f'Youth: {d.get("youth_name","Unknown")}<br/>'
                f'Attempted by: {d.get("person_name","Unknown")}<br/>'
                f'Time: {__import__("datetime").datetime.now().strftime("%I:%M %p")}</p>')
    except Exception:
        pass
    return jsonify({'ok': True})

# ── Pending profile updates ──
@app.route('/api/pending-profile-updates/<uid>/approve', methods=['POST'])
def approve_profile_update(uid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE pending_hours SET status='approved' WHERE id=%s", (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/pending-profile-updates/<uid>/reject', methods=['POST'])
def reject_profile_update(uid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, "UPDATE pending_hours SET status='rejected' WHERE id=%s", (uid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

init_db()
try:
    _seed_conn = get_db()
    seed_system_email_templates(_seed_conn)
    _seed_conn.commit()
    _seed_conn.close()
except Exception as _e:
    app.logger.warning(f'Email template seed failed: {_e}')

# ── Global error handlers  -  return JSON for all API errors ──
@app.errorhandler(500)
def internal_error(e):
    app.logger.error(f'500: {e}')
    return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Route not found'}), 404
    return e

@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Method not allowed'}), 405
    return e

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    app.logger.error(f'Unhandled: {traceback.format_exc()}')
    # Try to clean up any aborted transaction
    try:
        from psycopg2 import DatabaseError
        conn = get_db()
        conn.rollback()
        conn.close()
    except Exception:
        pass
    return jsonify({'error': str(e)}), 500




# ── Event Staff ──────────────────────────────────────────────────

@app.route('/api/events/<eid>/staff')
def get_event_staff(eid):
    conn = get_db()
    staff = fetchall(conn, '''SELECT es.*, v.name as volunteer_name,
        v.background_check_status, v.email
        FROM event_staff es
        JOIN volunteers v ON es.volunteer_id=v.id
        WHERE es.event_id=%s ORDER BY es.role, v.name''', (eid,))
    conn.close()
    return jsonify(staff)

@app.route('/api/events/<eid>/staff', methods=['POST'])
def add_event_staff(eid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    vol_id = d.get('volunteer_id')
    if not vol_id: return jsonify({'error': 'volunteer_id required'}), 400
    sid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO event_staff (id,event_id,volunteer_id,role,notes)
            VALUES (%s,%s,%s,%s,%s)''',
            (sid, eid, vol_id, (d.get('role') or '').strip(), (d.get('notes') or '').strip()))
        conn.commit()
        row = fetchone(conn, '''SELECT es.*, v.name as volunteer_name,
            v.background_check_status, v.email
            FROM event_staff es JOIN volunteers v ON es.volunteer_id=v.id
            WHERE es.id=%s''', (sid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.rollback(); conn.close()
        if 'unique' in str(e).lower():
            return jsonify({'error': 'This volunteer is already on the staff list'}), 400
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/staff/<sid>', methods=['PUT'])
def update_event_staff(sid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE event_staff SET role=%s, notes=%s WHERE id=%s',
        ((d.get('role') or '').strip(), (d.get('notes') or '').strip(), sid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/events/staff/<sid>', methods=['DELETE'])
def remove_event_staff(sid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_staff WHERE id=%s', (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Event Roles ──────────────────────────────────────────────────

@app.route('/api/events/<eid>/roles')
def get_event_roles(eid):
    conn = get_db()
    roles = fetchall(conn, '''
        SELECT r.*,
            COUNT(rv.id) FILTER (WHERE rv.status='interested') as filled
        FROM event_roles r
        LEFT JOIN event_rsvps rv ON rv.role_id=r.id AND rv.status='interested'
        WHERE r.event_id=%s
        GROUP BY r.id ORDER BY r.sort_order ASC, r.name ASC''', (eid,))
    conn.close()
    return jsonify(roles)

@app.route('/api/events/<eid>/roles', methods=['POST'])
def create_event_role(eid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    if not (d.get('name') or '').strip():
        return jsonify({'error': 'Role name is required'}), 400
    rid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO event_roles (id,event_id,name,slots,description,sort_order)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (rid, eid, d['name'].strip(), int(d.get('slots') or 1),
         (d.get('description') or '').strip(), int(d.get('sort_order') or 0)))
    conn.commit()
    row = fetchone(conn, '''SELECT r.*, 0 as filled FROM event_roles r WHERE r.id=%s''', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/roles/<rid>', methods=['PUT'])
def update_event_role(rid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE event_roles SET name=%s, slots=%s, description=%s
        WHERE id=%s''',
        ((d.get('name') or '').strip(), int(d.get('slots') or 1),
         (d.get('description') or '').strip(), rid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/events/roles/<rid>', methods=['DELETE'])
def delete_event_role(rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_roles WHERE id=%s', (rid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── Event RSVPs ──────────────────────────────────────────────────

@app.route('/api/events/<eid>/rsvps/manual', methods=['POST'])
def add_manual_rsvp(eid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    vol_id = d.get('volunteer_id','').strip()
    if not vol_id:
        return jsonify({'error': 'volunteer_id required'}), 400
    conn = get_db()
    # Check not already in the list
    existing = fetchone(conn, 'SELECT id FROM event_rsvps WHERE event_id=%s AND volunteer_id=%s', (eid, vol_id))
    if existing:
        # Already exists  -  just mark them as confirmed
        execute(conn, "UPDATE event_rsvps SET status='confirmed' WHERE id=%s", (existing['id'],))
        conn.commit()
        row = fetchone(conn, '''SELECT er.*, v.name as vol_name, v.email as volunteer_email
            FROM event_rsvps er LEFT JOIN volunteers v ON er.volunteer_id=v.id
            WHERE er.id=%s''', (existing['id'],))
        conn.close()
        return jsonify(row)
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vol_id,))
    if not vol:
        conn.close(); return jsonify({'error': 'Volunteer not found'}), 404
    rid = str(uuid.uuid4())
    execute(conn, '''INSERT INTO event_rsvps (id,event_id,volunteer_id,volunteer_name,volunteer_email,status)
        VALUES (%s,%s,%s,%s,%s,'confirmed')''',
        (rid, eid, vol_id, vol['name'], vol.get('email','')))
    conn.commit()
    row = fetchone(conn, '''SELECT er.*, v.name as vol_name FROM event_rsvps er
        LEFT JOIN volunteers v ON er.volunteer_id=v.id WHERE er.id=%s''', (rid,))
    conn.close()
    return jsonify(row)

@app.route('/api/events/<eid>/rsvps/<rid>/status', methods=['POST'])
def set_rsvp_status(eid, rid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    status = d.get('status','').strip()
    if status not in ('interested','confirmed','invited'):
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    execute(conn, 'UPDATE event_rsvps SET status=%s WHERE id=%s AND event_id=%s', (status, rid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'status': status})

@app.route('/api/events/<eid>/rsvps')
def get_event_rsvps(eid):
    err = require_auth()
    if err: return err
    conn = get_db()
    rsvps = fetchall(conn, '''SELECT r.*, v.name as vol_name, v.email as vol_email,
        r.last_invited_at
        FROM event_rsvps r LEFT JOIN volunteers v ON r.volunteer_id=v.id
        WHERE r.event_id=%s ORDER BY r.created_at ASC''', (eid,))
    conn.close()
    return jsonify(rsvps)

@app.route('/api/events/<eid>/rsvp-invite', methods=['POST'])
def send_rsvp_invite(eid):
    err = require_permission('events')
    if err: return err
    d = request.json or {}
    conn = get_db()
    evt = fetchone(conn, 'SELECT * FROM events WHERE id=%s', (eid,))
    if not evt: conn.close(); return jsonify({'error': 'Event not found'}), 404
    if evt.get('status') == 'cancelled':
        conn.close(); return jsonify({'error': 'Cannot send invites for a cancelled event'}), 400

    # Get roles for this event
    roles = fetchall(conn, '''
        SELECT r.*, COUNT(rv.id) FILTER (WHERE rv.status=\'interested\') as filled
        FROM event_roles r
        LEFT JOIN event_rsvps rv ON rv.role_id=r.id AND rv.status=\'interested\'
        WHERE r.event_id=%s GROUP BY r.id ORDER BY r.sort_order, r.name''', (eid,))

    target_ids = d.get('volunteer_ids') or []
    if not target_ids:
        vols = fetchall(conn, "SELECT id,name,email FROM volunteers WHERE status='active' AND email!='' AND email IS NOT NULL")
    else:
        vols = fetchall(conn, "SELECT id,name,email FROM volunteers WHERE id=ANY(%s) AND email IS NOT NULL", (target_ids,))

    sent = 0
    skipped = 0
    skipped_names = []
    custom_msg = (d.get('message') or '').strip()
    force_resend = bool(d.get('force_resend', False))
    base_url = request.host_url.rstrip('/')

    # Build roles table HTML for email
    roles_html = ''
    if roles:
        roles_html = '<h3 style="color:#145466;margin-top:24px;font-size:15px">Available Roles</h3>'
        roles_html += '<table style="width:100%;border-collapse:collapse;font-size:14px;margin:8px 0;border:1px solid #e2e8f0">'
        roles_html += '<thead><tr style="background:#f0fdf4"><th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0">Role</th><th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0">Open Slots</th></tr></thead><tbody>'
        for r in roles:
            available = max(0, int(r['slots']) - int(r['filled'] or 0))
            roles_html += f'<tr style="border-bottom:1px solid #f0f0f0"><td style="padding:8px 12px;font-weight:600">{r["name"]}</td>'
            roles_html += f'<td style="padding:8px 12px;color:{"#16a34a" if available>0 else "#dc2626"};font-weight:600">{available} of {r["slots"]} open</td></tr>'
        roles_html += '</tbody></table><p style="font-size:13px;color:#888">You can choose your preferred role when you sign up.</p>'

    for v in vols:
        if not v.get('email'): continue
        existing = fetchone(conn, 'SELECT id, token, status, last_invited_at FROM event_rsvps WHERE event_id=%s AND volunteer_id=%s', (eid, v['id']))

        # Skip if already signed up (interested/confirmed)
        if existing and existing.get('status') in ('interested', 'confirmed'):
            skipped += 1
            skipped_names.append(v['name'])
            continue

        # Skip if invited recently (within 24h) unless force_resend
        if existing and existing.get('last_invited_at') and not force_resend:
            from datetime import datetime as _dt2
            last_sent = existing['last_invited_at']
            last_sent_dt = parse_db_datetime(last_sent)
            if last_sent_dt is None: last_sent_dt = _dt2.utcnow()
            diff = (_dt2.utcnow() - last_sent_dt).total_seconds()
            if diff < 86400:  # 24 hours
                skipped += 1
                skipped_names.append(v['name'])
                continue

        if existing:
            token = existing['token']
            execute(conn, 'UPDATE event_rsvps SET last_invited_at=NOW() WHERE id=%s', (existing['id'],))
        else:
            token = str(uuid.uuid4())
            execute(conn, '''INSERT INTO event_rsvps (id,event_id,volunteer_id,volunteer_name,volunteer_email,token,status,last_invited_at)
                VALUES (%s,%s,%s,%s,%s,%s,'invited',NOW())''',
                (str(uuid.uuid4()), eid, v['id'], v['name'], v['email'], token))

        rsvp_url = f"{base_url}/rsvp/{token}"
        date_str = evt.get('event_date','')
        time_str = evt.get('start_time','')
        if time_str:
            try:
                from datetime import datetime as _dt
                t = _dt.strptime(time_str, '%H:%M')
                time_str = t.strftime('%I:%M %p').lstrip('0')
            except Exception:
                pass

        body = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;background:#ffffff">
          <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:8px 8px 0 0">
            <div style="color:rgba(255,255,255,0.7);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Horizon West Theater Company</div>
            <h2 style="color:#ffffff;margin:0;font-size:22px;font-weight:800">🎭 Volunteer Opportunity</h2>
            <div style="color:rgba(255,255,255,0.85);font-size:16px;font-weight:600;margin-top:6px">{evt['name']}</div>
          </div>
          <div style="background:#f8fafc;padding:28px 32px;border-radius:0 0 8px 8px;border:1px solid #e2e8f0;border-top:none">
            <p style="margin-top:0;color:#374151">Hi {v['name']},</p>
            <p style="color:#374151">We're looking for volunteers for an upcoming event and would love to have you join us!</p>
            <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">
              <tr style="background:#f0f8fa"><td style="padding:10px 14px;font-weight:700;color:#145466;width:100px">📅 Date</td><td style="padding:10px 14px;font-weight:600">{date_str}</td></tr>
              {f'<tr><td style="padding:10px 14px;font-weight:700;color:#145466">⏰ Time</td><td style="padding:10px 14px">{time_str}</td></tr>' if time_str else ''}
              {f'<tr style="background:#f0f8fa"><td style="padding:10px 14px;font-weight:700;color:#145466">📍 Location</td><td style="padding:10px 14px">{evt["location"]}</td></tr>' if evt.get('location') else ''}
            </table>
            {f'<div style="background:#fff8e7;border-left:3px solid #f59e0b;padding:12px 16px;margin:16px 0;border-radius:0 6px 6px 0"><p style="margin:0;color:#374151">{custom_msg}</p></div>' if custom_msg else ''}
            {f'<p style="color:#6b7280">{evt["description"]}</p>' if evt.get('description') else ''}
            {roles_html}
            <div style="text-align:center;margin:28px 0">
              <a href="{rsvp_url}" style="background:#145466;color:#ffffff;text-decoration:none;padding:16px 36px;border-radius:8px;font-size:16px;font-weight:700;display:inline-block;letter-spacing:0.3px">
                {"✋ Sign Up & Choose a Role" if roles else "✋ Yes, I Can Help!"}
              </a>
            </div>
            <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0"/>
            <p style="font-size:12px;color:#9ca3af;margin:0">
              If you're unable to attend, no action is needed  -  we only want to hear from those who can volunteer.<br>
              This invitation was sent to {v['email']} by Horizon West Theater Company.
            </p>
          </div>
        </div>'''

        fi = d.get('from_identity') or {}
        try:
            send_email([v['email']], f'[HWTC] Volunteer Opportunity: {evt["name"]}', body, fi.get('email') or None, fi.get('name') or None)
            sent += 1
            log_volunteer_comm(conn, v['id'], f'Volunteer Opportunity: {evt["name"]}', 'volunteer_opportunity', session.get('user_name','admin'), v['email'])
            # Small delay between emails to avoid rate limiting
            import time as _time
            if sent % 10 == 0:
                _time.sleep(1)
        except Exception as e:
            app.logger.warning(f'RSVP invite email failed for {v["email"]}: {e}')

    conn.commit(); conn.close()
    return jsonify({'ok': True, 'sent': sent, 'skipped': skipped, 'skipped_names': skipped_names})

@app.route('/rsvp/<token>')
def rsvp_page(token):
    conn = get_db()
    rsvp = fetchone(conn, '''SELECT r.*, e.name as event_name, e.event_date, e.start_time,
        e.location, e.description, e.id as event_id, e.status as event_status
        FROM event_rsvps r JOIN events e ON r.event_id=e.id WHERE r.token=%s''', (token,))
    if not rsvp:
        conn.close()
        return '<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>Link not found or expired.</h2></body></html>', 404

    # Event cancelled
    if rsvp.get('event_status') == 'cancelled':
        conn.close()
        return f'''<html><head><title>Event Cancelled</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
          <div style="font-size:48px;margin-bottom:16px">🚫</div>
          <h2 style="color:#dc2626">This Event Has Been Cancelled</h2>
          <p style="color:#6b7280"><strong>{rsvp["event_name"]}</strong> has been cancelled and is no longer accepting sign-ups.</p>
          <p style="color:#6b7280">Thank you for your interest  -  please check back for future events from Horizon West Theater Company.</p>
        </body></html>'''

    # Already signed up
    if rsvp.get('status') == 'interested':
        role_line = f'<p style="color:#16a34a;font-weight:600">Your role: {rsvp["role_name"]}</p>' if rsvp.get('role_name') else ''
        conn.close()
        return f'''<html><head><title>RSVP Confirmed</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
          <div style="font-size:48px;margin-bottom:16px">✅</div>
          <h2 style="color:#145466">You're already signed up!</h2>
          <p>Thanks {rsvp.get("volunteer_name","")}  -  we have your RSVP for <strong>{rsvp["event_name"]}</strong>.</p>
          {role_line}
          <p style="color:#888">We'll be in touch with more details.</p>
        </body></html>'''

    # Load available roles
    roles = fetchall(conn, '''
        SELECT r.*, COUNT(rv.id) FILTER (WHERE rv.status=\'interested\') as filled
        FROM event_roles r
        LEFT JOIN event_rsvps rv ON rv.role_id=r.id AND rv.status=\'interested\'
        WHERE r.event_id=%s GROUP BY r.id ORDER BY r.sort_order, r.name''', (rsvp['event_id'],))
    conn.close()

    date_str = rsvp.get('event_date','')
    vol_name = rsvp.get('volunteer_name','')

    if roles:
        # Show role selection form
        roles_html = ''
        for r in roles:
            available = max(0, int(r['slots']) - int(r['filled'] or 0))
            disabled = 'disabled' if available <= 0 else ''
            style = 'opacity:0.5;cursor:not-allowed' if available <= 0 else 'cursor:pointer'
            badge = f'<span style="font-size:11px;color:{"#16a34a" if available>0 else "#dc2626"};font-weight:600">{""+str(available)+" spot"+ ("s" if available!=1 else "")+" left" if available>0 else "Full"}</span>'
            desc = f'<div style="font-size:12px;color:#666;margin-top:2px">{r["description"]}</div>' if r.get('description') else ''
            roles_html += f'''<label style="display:flex;align-items:center;gap:12px;padding:12px 16px;border:2px solid #e2e8f0;border-radius:10px;margin-bottom:8px;{style}" 
                onclick="if(!this.querySelector('input').disabled) this.closest('form').querySelectorAll('label').forEach(l=>l.style.borderColor='#e2e8f0'); this.style.borderColor='#145466';">
                <input type="radio" name="role_id" value="{r["id"]}" {disabled} style="accent-color:#145466;flex-shrink:0" required/>
                <div style="flex:1">
                  <div style="font-weight:600;font-size:15px">{r["name"]} {badge}</div>
                  {desc}
                </div>
            </label>'''

        return f'''<html><head><title>Sign Up  -  {rsvp["event_name"]}</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:-apple-system,sans-serif;max-width:500px;margin:0 auto;padding:40px 20px">
          <div style="text-align:center;margin-bottom:28px">
            <div style="font-size:40px;margin-bottom:12px">✋</div>
            <h2 style="color:#145466;margin-bottom:6px">Sign up to volunteer!</h2>
            <p style="color:#555">Hi {vol_name}  -  choose your role for:</p>
            <div style="background:#f0fdf4;border:2px solid #86efac;border-radius:10px;padding:14px;margin:16px 0">
              <div style="font-size:18px;font-weight:700;color:#145466">{rsvp["event_name"]}</div>
              {f'<div style="color:#555;margin-top:4px">{date_str}</div>' if date_str else ''}
              {f'<div style="color:#888;font-size:13px">{rsvp["location"]}</div>' if rsvp.get("location") else ''}
            </div>
          </div>
          <form method="POST" action="/rsvp/{token}">
            <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:#888;margin-bottom:10px">Choose a role</div>
            {roles_html}
            <button type="submit" style="width:100%;background:#145466;color:#fff;border:none;border-radius:10px;padding:16px;font-size:16px;font-weight:700;cursor:pointer;margin-top:12px">
              ✅ Confirm Sign-up
            </button>
          </form>
          <p style="text-align:center;font-size:12px;color:#aaa;margin-top:20px">If you can't make it, no action needed.</p>
        </body></html>'''
    else:
        # No roles  -  just confirm directly
        conn2 = get_db()
        execute(conn2, "UPDATE event_rsvps SET status='interested' WHERE token=%s", (token,))
        conn2.commit(); conn2.close()
        return f'''<html><head><title>RSVP Confirmed  -  {rsvp["event_name"]}</title>
        <meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
          <div style="font-size:48px;margin-bottom:16px">🎉</div>
          <h2 style="color:#145466">You're in!</h2>
          <p>Thanks {vol_name}  -  we've recorded your interest in volunteering for <strong>{rsvp["event_name"]}</strong>.</p>
          <p style="color:#888;font-size:14px">We'll follow up with more details. Thank you!</p>
        </body></html>'''

@app.route('/rsvp/<token>', methods=['POST'])
def rsvp_submit(token):
    from flask import request as req
    role_id = req.form.get('role_id','').strip()
    conn = get_db()
    rsvp = fetchone(conn, '''SELECT r.*, e.name as event_name, e.event_date, e.location, e.id as event_id, e.status as event_status
        FROM event_rsvps r JOIN events e ON r.event_id=e.id WHERE r.token=%s''', (token,))
    if not rsvp:
        conn.close()
        return '<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>Link not found.</h2></body></html>', 404
    if rsvp.get('event_status') == 'cancelled':
        conn.close()
        return f'''<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
          <div style="font-size:48px;margin-bottom:16px">🚫</div>
          <h2 style="color:#dc2626">This Event Has Been Cancelled</h2>
          <p style="color:#6b7280"><strong>{rsvp["event_name"]}</strong> has been cancelled. Sign-ups are no longer being accepted.</p>
          <p style="color:#6b7280">Thank you for your interest  -  please check back for future events.</p>
        </body></html>'''

    role_name = ''
    if role_id:
        role = fetchone(conn, 'SELECT * FROM event_roles WHERE id=%s AND event_id=%s', (role_id, rsvp['event_id']))
        if role:
            # Check slot availability
            filled = fetchone(conn, "SELECT COUNT(*) as c FROM event_rsvps WHERE role_id=%s AND status='interested'", (role_id,))
            if filled and int(filled['c']) >= int(role['slots']):
                conn.close()
                return f'''<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
                <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
                  <div style="font-size:48px;margin-bottom:16px">😔</div>
                  <h2 style="color:#dc2626">That role just filled up</h2>
                  <p>Sorry, the <strong>{role["name"]}</strong> slot was just taken. <a href="/rsvp/{token}">Go back</a> to choose another role.</p>
                </body></html>''', 409
            role_name = role['name']

    execute(conn, "UPDATE event_rsvps SET status='interested', role_id=%s, role_name=%s WHERE token=%s",
        (role_id or None, role_name, token))
    conn.commit()
    date_str = rsvp.get('event_date','')

    # Send admin alert emails
    try:
        s = get_email_settings()
        recipients = get_recipient_emails(s)
        if recipients:
            vol_name = rsvp.get('volunteer_name','A volunteer')
            evt_name = rsvp['event_name']
            role_line = f' for <strong>{role_name}</strong>' if role_name else ''
            # New RSVP alert
            if s.get('alert_new_rsvp', True):
                send_email(recipients, f'New Sign-up: {evt_name}',
                    f'<div style="font-family:sans-serif"><p>✋ <strong>{vol_name}</strong> signed up to volunteer{role_line} for <strong>{evt_name}</strong>.</p>'
                    f'{f"<p>Date: {date_str}</p>" if date_str else ""}</div>')
            # Role filled alert
            if role_id and role_name and s.get('alert_role_filled', True):
                filled_now = fetchone(conn, "SELECT COUNT(*) as c FROM event_rsvps WHERE role_id=%s AND status='interested'", (role_id,))
                role_row = fetchone(conn, 'SELECT slots FROM event_roles WHERE id=%s', (role_id,))
                if filled_now and role_row and int(filled_now['c']) >= int(role_row['slots']):
                    send_email(recipients, f'Role Filled: {role_name}  -  {evt_name}',
                        f'<div style="font-family:sans-serif"><p>🎉 The <strong>{role_name}</strong> role for <strong>{evt_name}</strong> is now fully filled ({role_row["slots"]} of {role_row["slots"]} slots).</p></div>')
    except Exception as e:
        app.logger.warning(f'rsvp alert email error: {e}')

    conn.close()
    return f'''<html><head><title>Signed Up!</title>
    <meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="font-family:-apple-system,sans-serif;text-align:center;padding:60px 20px;max-width:500px;margin:0 auto">
      <div style="font-size:48px;margin-bottom:16px">🎉</div>
      <h2 style="color:#145466">You're signed up!</h2>
      <p>Thanks {rsvp.get("volunteer_name","")}! We've got you down for:</p>
      <div style="background:#f0fdf4;border:2px solid #86efac;border-radius:12px;padding:20px;margin:24px 0">
        <div style="font-size:20px;font-weight:700;color:#145466">{rsvp["event_name"]}</div>
        {f'<div style="color:#555;margin-top:6px">{date_str}</div>' if date_str else ''}
        {f'<div style="color:#16a34a;font-weight:600;font-size:16px;margin-top:8px">Role: {role_name}</div>' if role_name else ''}
      </div>
      <p style="color:#888;font-size:14px">We'll follow up with more details as the event approaches. Thank you!</p>
    </body></html>'''

@app.route('/api/events/<eid>/rsvps/<rid>', methods=['DELETE'])
def remove_rsvp(eid, rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM event_rsvps WHERE id=%s AND event_id=%s', (rid, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



# ── Board Management ─────────────────────────────────────────────

@app.route('/api/board/members')
def get_board_members():
    err = require_auth()
    if err: return err
    conn = get_db()
    members = fetchall(conn, '''SELECT bm.*, v.id as vol_id, v.name as vol_name, v.phone as vol_phone,
        v.status as vol_status, v.background_check_status
        FROM board_members bm
        LEFT JOIN volunteers v ON bm.volunteer_id=v.id
        ORDER BY bm.name''')
    for m in members:
        total    = fetchone(conn, 'SELECT COUNT(*) as c FROM board_meeting_attendance WHERE member_id=%s', (m['id'],))
        attended = fetchone(conn, "SELECT COUNT(*) as c FROM board_meeting_attendance WHERE member_id=%s AND attendance_type IN ('in_person','virtual')", (m['id'],))
        m['meetings_total']    = total['c'] if total else 0
        m['meetings_attended'] = attended['c'] if attended else 0
        m['nominations'] = fetchall(conn,
            'SELECT * FROM board_nominations WHERE member_id=%s ORDER BY nomination_date ASC', (m['id'],))
        latest_avail = fetchone(conn,
            'SELECT token, month, year FROM board_availability WHERE member_id=%s ORDER BY year DESC, month DESC LIMIT 1',
            (m['id'],))
        m['latest_availability_token'] = latest_avail['token'] if latest_avail else None
        m['latest_availability_month'] = latest_avail['month'] if latest_avail else None
        m['latest_availability_year']  = latest_avail['year'] if latest_avail else None
    conn.close()
    return jsonify(members)

@app.route('/api/board/members/<mid>/availability-link', methods=['POST'])
def get_member_availability_link(mid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    month = int(d.get('month', datetime.now().month))
    year  = int(d.get('year', datetime.now().year))
    conn = get_db()
    existing = fetchone(conn, 'SELECT token FROM board_availability WHERE member_id=%s AND month=%s AND year=%s', (mid, month, year))
    if existing:
        token = existing['token']
    else:
        token = str(uuid.uuid4())
        execute(conn, "INSERT INTO board_availability (id,member_id,month,year,token,blocked_dates) VALUES (%s,%s,%s,%s,%s,'[]')",
            (str(uuid.uuid4()), mid, month, year, token))
        conn.commit()
    conn.close()
    return jsonify({'token': token, 'month': month, 'year': year})

@app.route('/api/board/members/<mid>/nominations', methods=['POST'])
def add_board_nomination(mid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    if not d.get('nomination_date'):
        return jsonify({'error': 'Nomination date required'}), 400
    nid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO board_nominations (id,member_id,nomination_date,nomination_type,term_years,notes)
        VALUES (%s,%s,%s,%s,%s,%s)''',
        (nid, mid, d['nomination_date'], d.get('nomination_type','election'),
         int(d.get('term_years', 3)), d.get('notes','').strip()))
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM board_nominations WHERE id=%s', (nid,))
    conn.close()
    return jsonify(row)

@app.route('/api/board/nominations/<nid>', methods=['DELETE'])
def delete_board_nomination(nid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM board_nominations WHERE id=%s', (nid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/members', methods=['POST'])
def create_board_member():
    err = require_admin()
    if err: return err
    d = request.json or {}
    if not d.get('name') or not d.get('email'):
        return jsonify({'error': 'Name and email required'}), 400
    mid = str(uuid.uuid4())
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO board_members (id,name,email,role,status,join_date,notes,volunteer_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
            (mid, d['name'].strip(), d['email'].strip().lower(),
             d.get('role','').strip(), d.get('status','active'),
             d.get('join_date') or None, d.get('notes','').strip(),
             d.get('volunteer_id') or None))
        conn.commit()
        row = fetchone(conn, 'SELECT * FROM board_members WHERE id=%s', (mid,))
        conn.close()
        return jsonify(row)
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500

@app.route('/api/board/members/<mid>', methods=['PUT'])
def update_board_member(mid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE board_members SET name=%s,email=%s,role=%s,status=%s,join_date=%s,notes=%s,volunteer_id=%s
        WHERE id=%s''',
        (d.get('name','').strip(), d.get('email','').strip().lower(),
         d.get('role','').strip(), d.get('status','active'),
         d.get('join_date') or None, d.get('notes','').strip(),
         d.get('volunteer_id') or None, mid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/members/<mid>', methods=['DELETE'])
def delete_board_member(mid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM board_members WHERE id=%s', (mid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/meetings')
def get_board_meetings():
    err = require_auth()
    if err: return err
    conn = get_db()
    meetings = fetchall(conn, 'SELECT * FROM board_meetings ORDER BY meeting_date DESC')
    for m in meetings:
        m['attendance'] = fetchall(conn, '''SELECT bma.*, bm.name as member_name, bm.role
            FROM board_meeting_attendance bma JOIN board_members bm ON bma.member_id=bm.id
            WHERE bma.meeting_id=%s ORDER BY bm.name''', (m['id'],))
    conn.close()
    return jsonify(meetings)

@app.route('/api/board/meetings', methods=['POST'])
def create_board_meeting():
    err = require_admin()
    if err: return err
    d = request.json or {}
    if not d.get('meeting_date'):
        return jsonify({'error': 'Meeting date required'}), 400
    mid = str(uuid.uuid4())
    conn = get_db()
    execute(conn, '''INSERT INTO board_meetings (id,meeting_date,meeting_time,location,notes,status)
        VALUES (%s,%s,%s,%s,%s,'scheduled')''',
        (mid, d['meeting_date'], d.get('meeting_time',''), d.get('location',''), d.get('notes','')))
    # Auto-create attendance records for all active members
    members = fetchall(conn, "SELECT id FROM board_members WHERE status='active'")
    for m in members:
        execute(conn, 'INSERT INTO board_meeting_attendance (id,meeting_id,member_id,attended) VALUES (%s,%s,%s,FALSE)',
            (str(uuid.uuid4()), mid, m['id']))
    # Sync to event calendar if requested
    if d.get('sync_to_calendar', True):
        try:
            board_type = fetchone(conn, "SELECT id FROM event_types WHERE LOWER(name)='board meeting'")
            eid = str(uuid.uuid4())
            time_str = d.get('meeting_time','') or None
            location = d.get('location','') or ''
            notes = d.get('notes','') or ''
            execute(conn, '''INSERT INTO events
                (id,name,event_date,start_time,location,description,notes,status,event_type_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s)''',
                (eid, 'Board Meeting', d['meeting_date'], time_str, location,
                 'Monthly board meeting', notes,
                 board_type['id'] if board_type else None))
        except Exception as e:
            app.logger.warning(f'Board meeting calendar sync failed: {e}')
    conn.commit()
    row = fetchone(conn, 'SELECT * FROM board_meetings WHERE id=%s', (mid,))
    row['attendance'] = fetchall(conn, '''SELECT bma.*, bm.name as member_name, bm.role
        FROM board_meeting_attendance bma JOIN board_members bm ON bma.member_id=bm.id
        WHERE bma.meeting_id=%s ORDER BY bm.name''', (mid,))
    # Email all active board members
    try:
        email_members = fetchall(conn, "SELECT name, email FROM board_members WHERE status='active' AND email IS NOT NULL AND email != ''")
        if email_members:
            from calendar import month_name as cal_month_name
            meet_date = d['meeting_date']
            try:
                from datetime import datetime as _dt
                parsed = _dt.strptime(meet_date, '%Y-%m-%d')
                friendly_date = parsed.strftime('%A, %B %-d, %Y')
            except Exception:
                friendly_date = meet_date
            time_str = d.get('meeting_time','')
            location = d.get('location','') or 'TBD'
            notes = d.get('notes','') or ''
            time_line = f'<tr style="background:#f9fafb"><td style="padding:8px 12px;color:#6b7280;font-weight:600">Time</td><td style="padding:8px 12px">{time_str}</td></tr>' if time_str else ''
            notes_line = f'<tr><td style="padding:8px 12px;color:#6b7280;font-weight:600">Notes</td><td style="padding:8px 12px">{notes}</td></tr>' if notes else ''
            for m in email_members:
                body = f'''<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto">
                  <div style="background:linear-gradient(135deg,#0d3d4d,#145466);padding:28px 32px;border-radius:10px 10px 0 0">
                    <img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" style="height:40px;margin-bottom:12px" alt="HWTC"/>
                    <div style="color:#fff;font-size:20px;font-weight:700">📋 Board Meeting Scheduled</div>
                  </div>
                  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:28px 32px;border-radius:0 0 10px 10px">
                    <p style="margin:0 0 16px;font-size:15px">Hi {m['name']},</p>
                    <p style="margin:0 0 20px;font-size:15px;line-height:1.6">A board meeting has been scheduled. Please mark your calendar!</p>
                    <table style="width:100%;border-collapse:collapse;font-size:14px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;margin-bottom:24px">
                      <tr><td style="padding:8px 12px;color:#6b7280;font-weight:600;width:80px">Date</td><td style="padding:8px 12px;font-weight:700;color:#145466">{friendly_date}</td></tr>
                      {time_line}
                      <tr{'style="background:#f9fafb"' if not time_line else ''}><td style="padding:8px 12px;color:#6b7280;font-weight:600">Location</td><td style="padding:8px 12px">{location}</td></tr>
                      {notes_line}
                    </table>
                    <p style="margin:0;font-size:13px;color:#9ca3af">You're receiving this as an active board member of Horizon West Theatre Company.</p>
                  </div>
                </div>'''
                fi = d.get('from_identity') or {}
                send_email([m['email']], f'Board Meeting  -  {friendly_date}', body, fi.get('email') or None, fi.get('name') or None)
    except Exception as e:
        app.logger.warning(f'Board meeting email notification failed: {e}')
    conn.close()
    return jsonify(row)

@app.route('/api/board/meetings/<mid>', methods=['PUT'])
def update_board_meeting(mid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE board_meetings SET meeting_date=%s,meeting_time=%s,location=%s,notes=%s,status=%s
        WHERE id=%s''',
        (d.get('meeting_date',''), d.get('meeting_time',''),
         d.get('location',''), d.get('notes',''), d.get('status','scheduled'), mid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/meetings/<mid>/attendance', methods=['PUT'])
def update_board_attendance(mid):
    err = require_admin()
    if err: return err
    d = request.json or {}
    attendance = d.get('attendance', [])
    conn = get_db()
    for a in attendance:
        atype = a.get('attendance_type', 'absent')
        attended = atype in ('in_person', 'virtual')
        existing = fetchone(conn, 'SELECT id FROM board_meeting_attendance WHERE meeting_id=%s AND member_id=%s', (mid, a['member_id']))
        if existing:
            execute(conn, 'UPDATE board_meeting_attendance SET attended=%s, attendance_type=%s WHERE meeting_id=%s AND member_id=%s',
                (attended, atype, mid, a['member_id']))
        else:
            execute(conn, 'INSERT INTO board_meeting_attendance (id,meeting_id,member_id,attended,attendance_type) VALUES (%s,%s,%s,%s,%s)',
                (str(uuid.uuid4()), mid, a['member_id'], attended, atype))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/meetings/<mid>', methods=['DELETE'])
def delete_board_meeting(mid):
    err = require_admin()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM board_meetings WHERE id=%s', (mid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/board/availability/send', methods=['POST'])
def send_board_availability_request():
    err = require_admin()
    if err: return err
    d = request.json or {}
    month = d.get('month')
    year  = d.get('year')
    if not month or not year:
        return jsonify({'error': 'month and year required'}), 400
    conn = get_db()
    members = fetchall(conn, "SELECT * FROM board_members WHERE status='active'")
    base_url = request.host_url.rstrip('/')
    sent = 0
    month_name = ['','January','February','March','April','May','June',
                  'July','August','September','October','November','December'][int(month)]
    for m in members:
        # Create or get availability record + token
        existing = fetchone(conn, 'SELECT * FROM board_availability WHERE member_id=%s AND month=%s AND year=%s',
            (m['id'], month, year))
        if existing:
            token = existing['token']
        else:
            token = str(uuid.uuid4())
            execute(conn, '''INSERT INTO board_availability (id,member_id,month,year,token,blocked_dates)
                VALUES (%s,%s,%s,%s,%s,'[]')''',
                (str(uuid.uuid4()), m['id'], month, year, token))
        conn2 = get_db()
        tmpl = get_system_template(conn2, 'board_availability')
        conn2.close()
        month_name_str = ['','January','February','March','April','May','June',
                  'July','August','September','October','November','December'][int(month)]
        if tmpl:
            body = tmpl['body'].replace('{{name}}', m['name'])\
                .replace('{{month}}', month_name_str)\
                .replace('{{year}}', str(year))\
                .replace('{{link}}', link)
            subj = tmpl['subject'].replace('{{month}}', month_name_str).replace('{{year}}', str(year))
        else:
            subj = f'Board Meeting Availability  -  {month_name_str} {year}'
            body = f'''<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">
          <h2 style="color:#145466">Board Meeting Availability  -  {month_name_str} {year}</h2>
          <p>Hi {m['name']},</p>
          <p>Please click the link below and mark any dates you <strong>cannot</strong> attend.</p>
          <div style="text-align:center;margin:28px 0">
            <a href="{link}" style="background:#145466;color:#fff;text-decoration:none;padding:14px 32px;border-radius:8px;font-size:16px;font-weight:700;display:inline-block">📅 Submit My Availability</a>
          </div>
        </div>'''
        try:
            fi = d.get('from_identity') or {}
            send_email([m['email']], subj, body, fi.get('email') or None, fi.get('name') or None)
            sent += 1
        except Exception as e:
            app.logger.warning(f'Board availability email failed for {m["email"]}: {e}')
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'sent': sent})

@app.route('/api/board/availability/<month>/<year>')
def get_board_availability(month, year):
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT ba.*, bm.name as member_name, bm.email, bm.role
        FROM board_availability ba JOIN board_members bm ON ba.member_id=bm.id
        WHERE ba.month=%s AND ba.year=%s ORDER BY bm.name''', (month, year))
    conn.close()
    return jsonify(rows)

@app.route('/api/board/recommend/<month>/<year>')
def recommend_board_dates(month, year):
    err = require_auth()
    if err: return err
    conn = get_db()
    members = fetchall(conn, "SELECT id FROM board_members WHERE status='active'")
    total_members = len(members)
    avail = fetchall(conn, 'SELECT * FROM board_availability WHERE month=%s AND year=%s', (month, year))
    # Build blocked date map
    blocked_map = {}
    for a in avail:
        try:
            dates = json.loads(a['blocked_dates'] or '[]')
            for d in dates:
                if d not in blocked_map: blocked_map[d] = 0
                blocked_map[d] += 1
        except Exception:
            pass
    # Generate all dates in month
    import calendar
    year_int = int(year); month_int = int(month)
    _, days_in_month = calendar.monthrange(year_int, month_int)
    from datetime import date as _date
    results = []
    for day in range(1, days_in_month + 1):
        d = _date(year_int, month_int, day)
        date_str = d.strftime('%Y-%m-%d')
        blocked = blocked_map.get(date_str, 0)
        submitted = len(avail)
        # Not blocked = available (members who haven't submitted assumed available)
        available = total_members - blocked
        results.append({
            'date': date_str,
            'day_name': d.strftime('%A'),
            'day': day,
            'available': available,
            'blocked': blocked,
            'total_members': total_members,
            'submitted': submitted,
            'pct': round(available / total_members * 100) if total_members else 0
        })
    results.sort(key=lambda x: (-x['available'], x['date']))
    conn.close()
    return jsonify(results)

# Public board availability form
@app.route('/board/availability/<token>')
def board_availability_form(token):
    conn = get_db()
    record = fetchone(conn, '''SELECT ba.*, bm.name as member_name
        FROM board_availability ba JOIN board_members bm ON ba.member_id=bm.id
        WHERE ba.token=%s''', (token,))
    conn.close()
    if not record:
        return '<html><body style="font-family:sans-serif;text-align:center;padding:60px"><h2>Link not found or expired.</h2></body></html>', 404
    import calendar
    month_name = ['','January','February','March','April','May','June',
                  'July','August','September','October','November','December'][int(record['month'])]
    return f'''<!DOCTYPE html>
<html><head><title>Board Availability  -  {month_name} {record['year']}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f7fa;min-height:100vh}}
  .header{{background:linear-gradient(135deg,#0d3d4d,#145466);padding:24px 20px;color:#fff;text-align:center}}
  .header h1{{font-size:20px;font-weight:800;margin-bottom:4px}}
  .header p{{font-size:14px;opacity:0.8}}
  .card{{background:#fff;border-radius:12px;padding:24px;margin:20px auto;max-width:500px;box-shadow:0 2px 12px rgba(0,0,0,0.08)}}
  h2{{font-size:15px;font-weight:700;color:#145466;margin-bottom:4px}}
  .subtitle{{font-size:13px;color:#888;margin-bottom:16px}}
  .calendar{{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin-bottom:20px}}
  .cal-header{{text-align:center;font-size:11px;font-weight:700;color:#888;padding:4px 0;text-transform:uppercase}}
  .day{{border-radius:8px;border:2px solid #e5e7eb;padding:8px 4px;text-align:center;cursor:pointer;transition:all 0.15s;font-size:13px;font-weight:600;background:#fff;color:#374151;user-select:none}}
  .day:hover{{border-color:#145466;background:#f0f8fa}}
  .day.blocked{{background:#fef2f2;border-color:#fca5a5;color:#dc2626}}
  .day.empty{{border:none;cursor:default;background:transparent}}
  .day.weekend{{color:#9ca3af}}
  .btn{{width:100%;padding:14px;background:#145466;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:700;cursor:pointer;margin-top:8px}}
  .btn:disabled{{opacity:0.6;cursor:not-allowed}}
  .btn-secondary{{background:#f3f4f6;color:#374151;margin-top:8px}}
  .legend{{display:flex;gap:16px;font-size:12px;color:#888;margin-bottom:16px}}
  .legend-dot{{width:14px;height:14px;border-radius:4px;flex-shrink:0}}
  .success{{text-align:center;padding:40px 20px;display:none}}
  .success-icon{{font-size:56px;margin-bottom:12px}}
</style>
</head>
<body>
<div class="header">
  <h1>📅 Board Meeting Availability</h1>
  <p style="font-size:22px;font-weight:800;opacity:1;margin:6px 0 2px">{month_name} {record['year']}</p>
  <p style="font-size:14px;opacity:0.75">{record['member_name']}</p>
</div>
<div class="card" id="main-card">
  <h2>Which dates can't you make it?</h2>
  <p class="subtitle">Tap any dates you are <strong>NOT available</strong>. Leave dates blank if you can attend.</p>
  <div class="legend">
    <div style="display:flex;align-items:center;gap:6px"><div class="legend-dot" style="background:#fff;border:2px solid #e5e7eb"></div> Available</div>
    <div style="display:flex;align-items:center;gap:6px"><div class="legend-dot" style="background:#fef2f2;border:2px solid #fca5a5"></div> Can't make it</div>
  </div>
  <div style="font-size:20px;font-weight:800;color:#145466;margin-bottom:12px;text-align:center">{month_name} {record['year']}</div>
  <div class="calendar" id="calendar"></div>
  <button class="btn" id="submit-btn" onclick="submitAvailability()">✅ Submit My Availability</button>
  <button class="btn btn-secondary" onclick="clearAll()">Clear all</button>
</div>
<div class="card success" id="success-card">
  <div class="success-icon">🎉</div>
  <h2 style="text-align:center;font-size:18px;margin-bottom:8px">Thanks, {record['member_name']}!</h2>
  <p style="text-align:center;color:#888;font-size:14px">Your availability for {month_name} {record['year']} has been recorded. You can update it anytime by clicking this link again.</p>
</div>
<script>
const MONTH={record['month']}, YEAR={record['year']}, TOKEN='{token}'
var blocked = new Set({json.dumps(json.loads(record['blocked_dates'] or '[]'))})

function buildCalendar(){{
  var cal = document.getElementById('calendar')
  cal.innerHTML = ''
  var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']
  days.forEach(function(d){{ var h=document.createElement('div'); h.className='cal-header'; h.textContent=d; cal.appendChild(h) }})
  var firstDay = new Date(YEAR, MONTH-1, 1).getDay()
  var daysInMonth = new Date(YEAR, MONTH, 0).getDate()
  for(var i=0;i<firstDay;i++){{ var e=document.createElement('div'); e.className='day empty'; cal.appendChild(e) }}
  for(var d=1;d<=daysInMonth;d++){{
    var date = YEAR+'-'+(MONTH<10?'0':'')+MONTH+'-'+(d<10?'0':'')+d
    var dow = new Date(YEAR, MONTH-1, d).getDay()
    var el = document.createElement('div')
    el.className = 'day' + (dow===0||dow===6?' weekend':'') + (blocked.has(date)?' blocked':'')
    el.textContent = d
    el.dataset.date = date
    el.addEventListener('click', function(){{ toggleDay(this) }})
    cal.appendChild(el)
  }}
}}

function toggleDay(el){{
  var date = el.dataset.date
  if(blocked.has(date)){{ blocked.delete(date); el.classList.remove('blocked') }}
  else{{ blocked.add(date); el.classList.add('blocked') }}
}}

function clearAll(){{ blocked.clear(); buildCalendar() }}

async function submitAvailability(){{
  var btn = document.getElementById('submit-btn')
  btn.disabled = true; btn.textContent = 'Saving…'
  var r = await fetch('/api/board/availability/submit', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{token: TOKEN, blocked_dates: Array.from(blocked)}})
  }})
  var d = await r.json()
  if(d.error){{ btn.disabled=false; btn.textContent='✅ Submit My Availability'; alert(d.error); return }}
  document.getElementById('main-card').style.display='none'
  document.getElementById('success-card').style.display='block'
}}

buildCalendar()
</script>
</body></html>'''

@app.route('/api/board/availability/submit', methods=['POST'])
def submit_board_availability():
    d = request.json or {}
    token = d.get('token','').strip()
    blocked = d.get('blocked_dates', [])
    if not token:
        return jsonify({'error': 'Invalid token'}), 400
    conn = get_db()
    record = fetchone(conn, 'SELECT id FROM board_availability WHERE token=%s', (token,))
    if not record:
        conn.close(); return jsonify({'error': 'Token not found'}), 404
    execute(conn, 'UPDATE board_availability SET blocked_dates=%s, submitted_at=NOW() WHERE token=%s',
        (json.dumps(blocked), token))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/volunteers/<vol_id>/send-giving-reminder', methods=['POST'])
def send_single_giving_reminder(vol_id):
    err = require_admin()
    if err: return err
    conn = get_db()
    v = fetchone(conn, 'SELECT * FROM volunteers WHERE id=%s', (vol_id,))
    if not v: conn.close(); return jsonify({'error': 'Volunteer not found'}), 404
    prog = (v.get('employer_program') or '').strip()
    if not prog: conn.close(); return jsonify({'error': 'No employer program set for this volunteer'}), 400
    is_disney = 'disney' in prog.lower()
    prog_label = 'Disney Cast Member' if is_disney else 'Universal Team Member'
    submit_name = 'Disney VoluntEARS' if is_disney else 'Universal Giving'
    submit_link = 'https://disneyvoluntears.com' if is_disney else 'https://universalgiving.org'
    icon = '🐭' if is_disney else '🎬'
    conn2 = get_db()
    tmpl = get_system_template(conn2, 'disney_reminder' if is_disney else 'universal_reminder')
    hours_section, total = build_hours_section(conn2, vol_id, submit_name, submit_link)
    conn2.close()
    conn.close()
    if not hours_section:
        return jsonify({'error': 'No hours logged in the last year  -  nothing to remind about'}), 400
    name = (v.get('name') or 'Volunteer').strip()
    if tmpl:
        base_body = tmpl['body'].replace('{{name}}', name)
        subj = tmpl['subject']
    else:
        base_body = f'<p>Hi {name}, please submit your hours to {submit_name}.</p>'
        subj = f'{icon} Reminder: Submit Your Volunteer Hours  -  {prog_label} Giving Program'
    # Inject hours table before the last closing div
    if '</div>' in base_body:
        idx = base_body.rfind('</div>')
        body = base_body[:idx] + hours_section + base_body[idx:]
    else:
        body = base_body + hours_section
    conn3 = get_db()
    d = request.json or {}
    fi = d.get('from_identity') or {}
    ok, msg = send_email([v['email']], subj, body, fi.get('email') or None, fi.get('name') or None)
    if ok:
        log_volunteer_comm(conn3, vol_id, subj,
            'disney_reminder' if is_disney else 'universal_reminder',
            session.get('user_name', 'admin'), v['email'])
        execute(conn3, '''INSERT INTO employer_reminder_log (id, volunteer_id, program_type, sent_by)
            VALUES (%s,%s,%s,%s)''',
            (str(uuid.uuid4()), vol_id, 'disney' if is_disney else 'universal',
             session.get('user_name', 'admin')))
        conn3.commit()
    conn3.close()
    if not ok: return jsonify({'error': msg or 'Failed to send'}), 500
    return jsonify({'ok': True, 'sent_to': v['email'], 'total_hours': total})

def build_hours_section(conn, vol_id, submit_name, submit_link):
    """Build a personalized hours table HTML section for a volunteer."""
    hours = fetchall(conn, """
        SELECT event, date, hours, role FROM hours
        WHERE volunteer_id=%s AND date::date >= (CURRENT_DATE - INTERVAL '365 days')
        ORDER BY date DESC
    """, (vol_id,))
    if not hours:
        return '', 0
    total = sum(float(h.get('hours') or 0) for h in hours)
    def row_bg(i): return 'background:#f9fafb' if i % 2 else ''
    rows = ''.join(f'''<tr style="border-bottom:1px solid #e5e7eb;{row_bg(i)}">
        <td style="padding:7px 10px">{h.get('event') or ' - '}</td>
        <td style="padding:7px 10px;color:#6b7280;white-space:nowrap">{h.get('date') or ' - '}</td>
        <td style="padding:7px 10px;color:#6b7280">{h.get('role') or ' - '}</td>
        <td style="padding:7px 10px;font-weight:600;text-align:right;white-space:nowrap">{float(h.get('hours') or 0):.1f}h</td>
    </tr>''' for i, h in enumerate(hours))
    section = f'''
<div style="margin:24px 0;font-family:-apple-system,sans-serif">
  <div style="background:#f0f8fa;border-left:4px solid #145466;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:16px">
    <strong style="font-size:14px;color:#145466">Your recent volunteer hours  -  {total:.1f}h total</strong>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:13px;border:1px solid #e5e7eb">
    <thead>
      <tr style="background:#145466;color:#fff">
        <th style="padding:8px 10px;text-align:left;font-weight:600">Event</th>
        <th style="padding:8px 10px;text-align:left;font-weight:600">Date</th>
        <th style="padding:8px 10px;text-align:left;font-weight:600">Role</th>
        <th style="padding:8px 10px;text-align:right;font-weight:600">Hours</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
    <tfoot>
      <tr style="background:#f0f8fa;border-top:2px solid #145466">
        <td colspan="3" style="padding:8px 10px;font-weight:700;color:#145466">Total</td>
        <td style="padding:8px 10px;font-weight:800;font-size:15px;color:#145466;text-align:right">{total:.1f}h</td>
      </tr>
    </tfoot>
  </table>
  <p style="font-size:12px;color:#9ca3af;margin-top:8px">Use these hours when submitting at <a href="{submit_link}" style="color:#145466">{submit_link}</a></p>
</div>'''
    return section, total

@app.route('/api/volunteers/employer-giving-stats')
def get_employer_giving_stats():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, """
        SELECT v.id, v.name, v.email, v.employer_program,
            COALESCE(SUM(CASE WHEN h.date::date >= CURRENT_DATE - INTERVAL '90 days' THEN h.hours ELSE 0 END), 0) as recent_hours,
            COALESCE(SUM(h.hours), 0) as total_hours,
            MAX(erl.sent_at) as last_reminder_sent,
            MAX(erl.sent_by) as last_reminder_by
        FROM volunteers v
        LEFT JOIN hours h ON h.volunteer_id = v.id
        LEFT JOIN employer_reminder_log erl ON erl.volunteer_id = v.id
        WHERE v.status = 'active'
          AND (LOWER(v.employer_program) LIKE '%%disney%%' OR LOWER(v.employer_program) LIKE '%%universal%%')
        GROUP BY v.id, v.name, v.email, v.employer_program
        ORDER BY recent_hours DESC, v.name
    """)
    conn.close()
    return jsonify(rows)

@app.route('/api/volunteers/employer-reminder-log')
def get_employer_reminder_log():
    err = require_auth()
    if err: return err
    conn = get_db()
    rows = fetchall(conn, '''SELECT erl.*, v.name as volunteer_name, v.email, v.employer_program
        FROM employer_reminder_log erl
        JOIN volunteers v ON erl.volunteer_id=v.id
        ORDER BY erl.sent_at DESC LIMIT 200''')
    conn.close()
    return jsonify(rows)

@app.route('/api/volunteers/employer-program-reminder', methods=['POST'])
def send_employer_program_reminder():
    err = require_admin()
    if err: return err
    d = request.json or {}
    program_filter = d.get('program')
    min_days = int(d.get('min_days_since_last', 30))  # don't resend within X days
    conn = get_db()
    if program_filter == 'disney':
        condition = "LOWER(v.employer_program) LIKE '%%disney%%'"
    elif program_filter == 'universal':
        condition = "LOWER(v.employer_program) LIKE '%%universal%%'"
    else:
        condition = "(LOWER(v.employer_program) LIKE '%%disney%%' OR LOWER(v.employer_program) LIKE '%%universal%%')"
    volunteers = fetchall(conn, f"""
        SELECT DISTINCT v.id, v.name, v.email, v.employer_program
        FROM volunteers v
        JOIN hours h ON h.volunteer_id=v.id
        WHERE {condition}
          AND v.status='active'
          AND h.date::date >= (CURRENT_DATE - INTERVAL '90 days')
          AND v.email IS NOT NULL AND v.email != ''
    """)
    # Convert to plain dicts so we can add last_sent field
    volunteers = [dict(v) for v in volunteers]
    # Look up last send time for each volunteer separately (avoids DISTINCT + subquery issues)
    for v in volunteers:
        last = fetchone(conn, 'SELECT MAX(sent_at) as last_sent FROM employer_reminder_log WHERE volunteer_id=%s', (v['id'],))
        v['last_sent'] = last['last_sent'] if last else None
    conn.close()
    if not volunteers:
        return jsonify({'ok': True, 'sent': 0, 'skipped': 0, 'message': 'No qualifying volunteers found with recent hours'})
    sent = 0
    skipped = 0
    skipped_names = []
    errors = []
    for v in volunteers:
        # Skip if sent recently
        if v.get('last_sent'):
            from datetime import datetime, timezone
            last = v['last_sent']
            last_dt = parse_db_datetime(last)
            if last_dt is not None:
                diff = (datetime.utcnow() - last_dt).days
                if diff < min_days:
                    skipped += 1
                    skipped_names.append((v.get('name') or 'Unknown') + f' (sent {diff}d ago)')
                    continue
        prog = (v.get('employer_program') or '').strip()
        is_disney = 'disney' in prog.lower()
        submit_link = 'https://disneyvoluntears.com' if is_disney else 'https://universalgiving.org'
        submit_name = 'Disney VoluntEARS' if is_disney else 'Universal Giving'
        tmpl_key = 'disney_reminder' if is_disney else 'universal_reminder'
        conn2 = get_db()
        tmpl = get_system_template(conn2, tmpl_key)
        hours_section, _ = build_hours_section(conn2, v['id'], submit_name, submit_link)
        conn2.close()
        name = (v.get('name') or 'Volunteer').strip()
        if tmpl:
            base_body = tmpl['body'].replace('{{name}}', name)
            subj = tmpl['subject']
        else:
            prog_label = 'Disney Cast Member' if is_disney else 'Universal Team Member'
            subj = f'Reminder: Submit Your Volunteer Hours  -  {prog_label} Giving Program'
            base_body = f'<p>Hi {name}, please consider submitting your volunteer hours to the {prog_label} giving program.</p>'
        # Inject hours table before closing div
        if hours_section:
            if '</div>' in base_body:
                idx = base_body.rfind('</div>')
                body = base_body[:idx] + hours_section + base_body[idx:]
            else:
                body = base_body + hours_section
        else:
            body = base_body
        try:
            fi = d.get('from_identity') or {}
            send_email([v['email']], subj, body, fi.get('email') or None, fi.get('name') or None)
            sent += 1
            conn3 = get_db()
            execute(conn3, '''INSERT INTO employer_reminder_log (id, volunteer_id, program_type, sent_by)
                VALUES (%s,%s,%s,%s)''',
                (str(uuid.uuid4()), v['id'], 'disney' if is_disney else 'universal',
                 session.get('user_name','admin')))
            log_volunteer_comm(conn3, v['id'], subj,
                'disney_reminder' if is_disney else 'universal_reminder',
                session.get('user_name','admin'), v.get('email',''))
            conn3.commit(); conn3.close()
        except Exception as e:
            errors.append(f'{name}: {str(e)}')
    return jsonify({'ok': True, 'sent': sent, 'skipped': skipped,
                    'skipped_names': skipped_names, 'errors': errors,
                    'total': len(volunteers)})

if __name__ == '__main__':
    print('\n🎭 RoleCall is running!')
    print('   Open http://localhost:5000 in your browser\n')
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)


# ═══════════════════════════════════════════════════════════════════════
#  SQUARE INTEGRATION & REGISTRATION SYSTEM
# ═══════════════════════════════════════════════════════════════════════

SQUARE_ACCESS_TOKEN = os.environ.get('SQUARE_ACCESS_TOKEN', '')
SQUARE_LOCATION_ID  = os.environ.get('SQUARE_LOCATION_ID', '')
SQUARE_WEBHOOK_SIG  = os.environ.get('SQUARE_WEBHOOK_SIGNATURE_KEY', '')
SQUARE_ENV          = os.environ.get('SQUARE_ENV', 'sandbox')  # 'sandbox' or 'production'
SQUARE_API_BASE     = 'https://connect.squareup.com' if SQUARE_ENV == 'production' else 'https://connect.squareupsandbox.com'
APP_BASE_URL        = os.environ.get('APP_BASE_URL', 'https://rolecall.hwtco.org')

def square_headers():
    return {'Authorization': f'Bearer {SQUARE_ACCESS_TOKEN}', 'Content-Type': 'application/json', 'Square-Version': '2024-01-18'}

def square_create_payment_link(program, registration_id, guardian_email, guardian_name, amount_cents, note=''):
    """Create a Square hosted checkout link for a registration."""
    import uuid as _uuid
    if not SQUARE_ACCESS_TOKEN or not SQUARE_LOCATION_ID:
        app.logger.error('Square not configured: SQUARE_ACCESS_TOKEN or SQUARE_LOCATION_ID missing')
        return None, None, None
    redirect_url = f"{APP_BASE_URL}/register/{program.get('slug') or program['id']}/confirmation?reg={registration_id}"
    payload = {
        'idempotency_key': str(_uuid.uuid4()),
        'order': {
            'location_id': SQUARE_LOCATION_ID,
            'line_items': [
                {
                    'catalog_object_id': program.get('square_catalog_item_id'),
                    'quantity': '1',
                } if program.get('square_catalog_item_id') else {
                    'name': program['name'][:191],
                    'quantity': '1',
                    'base_price_money': {'amount': amount_cents, 'currency': 'USD'},
                }
            ],
            'reference_id': registration_id[:40],
        },
        'checkout_options': {
            'redirect_url': redirect_url,
            'ask_for_shipping_address': False,
        },
        'pre_populated_data': {
            'buyer_email': guardian_email or '',
        },
        'description': (note or f'Registration: {registration_id}')[:255],
    }
    try:
        r = requests.post(
            f'{SQUARE_API_BASE}/v2/online-checkout/payment-links',
            json=payload, headers=square_headers(), timeout=15)
        data = r.json()
        app.logger.info(f'Square payment link response {r.status_code}: {str(data)[:300]}')
        if r.status_code == 200 and data.get('payment_link'):
            lnk = data['payment_link']
            return lnk.get('url'), lnk.get('id'), lnk.get('order_id')
        app.logger.error(f'Square payment link failed {r.status_code}: {data}')
        return None, None, None
    except Exception as e:
        app.logger.error(f'Square payment link exception: {e}')
        return None, None, None


def get_program_by_slug(slug):
    conn = get_db()
    p = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    conn.close()
    return p


def get_registration_count(conn, program_id):
    r = fetchone(conn, "SELECT COUNT(*) as c FROM program_registrations WHERE program_id=%s AND status IN ('confirmed','pending_payment')", (program_id,))
    return r['c'] if r else 0


def get_waitlist_count(conn, program_id):
    r = fetchone(conn, "SELECT COUNT(*) as c FROM program_registrations WHERE program_id=%s AND status='waitlisted'", (program_id,))
    return r['c'] if r else 0


def next_waitlist_position(conn, program_id):
    r = fetchone(conn, 'SELECT MAX(waitlist_position) as m FROM program_registrations WHERE program_id=%s AND status=%s', (program_id,'waitlisted'))
    return (r['m'] or 0) + 1 if r else 1


def finalize_registration(conn, reg_id, payment_id=None, order_id=None):
    """Mark registration confirmed and create participant records."""
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s', (reg_id,))
    if not reg: return
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (reg.get('program_id'),)) if reg.get('program_id') else None

    # Update registration status
    execute(conn, '''UPDATE program_registrations SET status='confirmed',
        square_payment_id=%s, square_order_id=%s, updated_at=NOW() WHERE id=%s''',
        (payment_id or reg.get('square_payment_id'), order_id or reg.get('square_order_id'), reg_id))

    def get_or_create_participant(first, last, dob, shirt):
        """Find existing participant by guardian email + name, or create new one."""
        if not first:
            return None
        existing = fetchone(conn, '''SELECT yp.* FROM youth_participants yp
            JOIN youth_guardians yg ON yg.youth_id=yp.id
            WHERE LOWER(yg.email)=LOWER(%s)
            AND LOWER(yp.first_name)=LOWER(%s)
            AND LOWER(yp.last_name)=LOWER(%s)''',
            (reg['guardian_email'], first, last or ''))
        if existing:
            return existing
        import uuid as _u
        yid = str(_u.uuid4())
        execute(conn, '''INSERT INTO youth_participants (id, first_name, last_name, dob, shirt_size)
            VALUES (%s,%s,%s,%s,%s)''',
            (yid, first, last or '', dob or None, shirt or ''))
        return fetchone(conn, 'SELECT * FROM youth_participants WHERE id=%s', (yid,))

    def ensure_guardian(youth_id):
        existing = fetchone(conn, 'SELECT id FROM youth_guardians WHERE youth_id=%s AND LOWER(email)=LOWER(%s)',
            (youth_id, reg['guardian_email']))
        if not existing and reg.get('guardian_name'):
            import uuid as _ug
            execute(conn, '''INSERT INTO youth_guardians
                (id, youth_id, name, relationship, email, phone, is_primary)
                VALUES (%s,%s,%s,%s,%s,%s,1) ON CONFLICT DO NOTHING''',
                (str(_ug.uuid4()), youth_id,
                 reg.get('guardian_name') or '',
                 'Parent/Guardian',
                 reg['guardian_email'], reg.get('guardian_phone') or ''))

    def enroll(youth_id):
        if not prog: return
        try:
            import uuid as _ue
            execute(conn, '''INSERT INTO youth_program_enrollments
                (id, youth_id, program_id, enrolled_date, notes)
                VALUES (%s,%s,%s,NOW()::TEXT,%s)
                ON CONFLICT (youth_id, program_id) DO NOTHING''',
                (str(_ue.uuid4()), youth_id, prog['id'], f'Online registration #{reg_id[:8]}'))
        except Exception as e:
            app.logger.warning(f'Enrollment insert: {e}')

    # Primary participant
    youth = get_or_create_participant(
        reg.get('child_first_name'), reg.get('child_last_name'),
        reg.get('child_dob'), reg.get('shirt_size'))
    if youth:
        ensure_guardian(youth['id'])
        enroll(youth['id'])

    # Siblings
    import json as _json_sib
    try:
        siblings = _json_sib.loads(reg.get('siblings_json') or '[]')
    except Exception:
        siblings = []
    for sib in (siblings or []):
        sib_youth = get_or_create_participant(
            (sib.get('first_name') or '').strip(),
            (sib.get('last_name') or '').strip(),
            sib.get('dob'), sib.get('shirt_size'))
        if sib_youth:
            ensure_guardian(sib_youth['id'])
            enroll(sib_youth['id'])

    conn.commit()


# ── Public registration page ──────────────────────────────────────────────────

@app.route('/register/<slug>')
def public_register_page(slug):
    """Public-facing registration / interest list page."""
    return send_from_directory('static', 'register.html')

@app.route('/register/production/<slug>')
def public_register_production_page(slug):
    """Public-facing production registration page."""
    return send_from_directory('static', 'register.html')

@app.route('/register/<slug>/confirmation')
def public_register_confirmation(slug):
    return send_from_directory('static', 'register.html')

@app.route('/register/production/<slug>/confirmation')
def public_register_production_confirmation(slug):
    return send_from_directory('static', 'register.html')


@app.route('/api/public/program/<slug>')
def public_program_info(slug):
    """Public program info — no auth needed."""
    conn = get_db()
    p = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not p:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    # Attach counts
    p['registration_count'] = get_registration_count(conn, p['id'])
    p['waitlist_count'] = get_waitlist_count(conn, p['id'])
    p['spots_remaining'] = max(0, (p.get('capacity') or 999) - p['registration_count']) if p.get('capacity') else None
    # Attach instructor name
    if p.get('instructor_id'):
        v = fetchone(conn, 'SELECT name, bio, photo_url FROM volunteers WHERE id=%s', (p['instructor_id'],))
        if v:
            p['instructor_name'] = v['name']
            p['instructor_bio'] = v.get('bio') or ''
            p['instructor_photo'] = v.get('photo_url') or ''
    conn.close()
    # Remove internal fields
    # Parse JSON fields
    for k in ['custom_fields','program_images','interest_list_fields','meeting_days']:
        if p.get(k):
            try: p[k] = json.loads(p[k])
            except: p[k] = []
    if p.get('form_fields'):
        try: p['form_fields'] = json.loads(p['form_fields'])
        except: p['form_fields'] = {}
    for k in ['default_elic_id','created_by','updated_by','square_catalog_item_id']:
        p.pop(k, None)
    return jsonify(p)


@app.route('/api/public/program/<slug>/register', methods=['POST'])
def public_submit_registration(slug):
    """Submit a registration or interest list entry."""
    d = request.json or {}
    conn = get_db()
    p = fetchone(conn, 'SELECT * FROM youth_programs WHERE slug=%s OR id=%s', (slug, slug))
    if not p:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404

    reg_type = d.get('type', 'registration')  # 'registration' or 'interest'
    email = (d.get('guardian_email') or d.get('email') or '').strip().lower()
    if not email:
        conn.close()
        return jsonify({'error': 'Email is required'}), 400

    # ── Interest list ──────────────────────────────────────────────────
    if reg_type == 'interest' or p.get('registration_status') == 'interest_list':
        try:
            import uuid as _u
            execute(conn, '''INSERT INTO interest_list_entries
                (id, program_id, name, email, phone, child_name, child_age, notes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (program_id, email) DO UPDATE SET
                    name=EXCLUDED.name, phone=EXCLUDED.phone,
                    child_name=EXCLUDED.child_name, child_age=EXCLUDED.child_age,
                    notes=EXCLUDED.notes''',
                (_u.uuid4().hex, p['id'], d.get('name','').strip(), email,
                 d.get('phone','').strip() or None,
                 d.get('child_name','').strip() or None,
                 d.get('child_age','').strip() or None,
                 d.get('notes','').strip() or None))
            conn.commit()
            # Notify admin
            try:
                s = get_email_settings(conn)
                recipients = list(get_recipient_emails(s))
                if recipients:
                    send_email(recipients, f'Interest List: {p["name"]} — {d.get("name","")}',
                        f'<p><strong>{d.get("name","")}</strong> ({email}) joined the interest list for <strong>{p["name"]}</strong>.</p>')
            except Exception: pass
            # Thank-you email to the family
            try:
                submitter_name = (d.get('name') or '').strip().split()[0] or 'there'
                child_name = (d.get('child_name') or '').strip()
                send_email([email], f'You\'re on the interest list — {p["name"]}',
                    f'<div style="font-family:-apple-system,\'DM Sans\',sans-serif;max-width:560px;margin:0 auto;color:#1a2332">'
                    f'<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:28px 24px;text-align:center;border-radius:12px 12px 0 0">'
                    f'<img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" alt="HWTC" style="height:48px;margin-bottom:10px;display:block;margin-left:auto;margin-right:auto"/>'
                    f'</div>'
                    f'<div style="background:#fff;padding:28px 28px 24px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb">'
                    f'<h2 style="color:#0d3d4d;font-size:20px;margin:0 0 12px">You\'re on the list!</h2>'
                    f'<p style="color:#374151;line-height:1.6;margin:0 0 14px">Hi {submitter_name},</p>'
                    f'<p style="color:#374151;line-height:1.6;margin:0 0 14px">'
                    f'Thanks for your interest in <strong>{p["name"]}</strong>{"!" if not child_name else f" for <strong>{child_name}</strong>!"} '
                    f'We\'ve added you to our interest list and will reach out as soon as registration opens.</p>'
                    f'<p style="color:#374151;line-height:1.6;margin:0 0 24px">'
                    f'We\'ll also send you a direct link to register when the time comes, so keep an eye on your inbox.</p>'
                    f'<div style="background:#f0f9ff;border-left:4px solid #145466;padding:14px 16px;border-radius:0 8px 8px 0;margin-bottom:24px">'
                    f'<div style="font-size:13px;color:#145466;font-weight:700;margin-bottom:4px">Program</div>'
                    f'<div style="font-size:15px;font-weight:700;color:#0d3d4d">{p["name"]}</div>'
                    f'</div>'
                    f'<p style="color:#6b7280;font-size:13px;margin:0">Questions? Reply to this email or visit '
                    f'<a href="https://hwtco.org" style="color:#145466">hwtco.org</a>.</p>'
                    f'<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0"/>'
                    f'<p style="color:#9ca3af;font-size:12px;margin:0;text-align:center">'
                    f'Horizon West Theatre Company &nbsp;&middot;&nbsp; Horizon West, FL</p>'
                    f'</div></div>')
            except Exception as e:
                app.logger.warning(f'Interest list thank-you email failed: {e}')
            conn.close()
            return jsonify({'ok': True, 'type': 'interest'})
        except Exception as e:
            conn.close()
            return jsonify({'error': str(e)}), 500

    # ── Registration ───────────────────────────────────────────────────
    if p.get('registration_status') not in ('open',):
        conn.close()
        return jsonify({'error': 'Registrations are not currently open for this program'}), 400

    # Check capacity
    reg_count = get_registration_count(conn, p['id'])
    cap = p.get('capacity')
    is_full = cap and reg_count >= cap

    import uuid as _u2
    rid = _u2.uuid4().hex

    if is_full:
        # Waitlist
        wpos = next_waitlist_position(conn, p['id'])
        execute(conn, '''INSERT INTO program_registrations
            (id, program_id, registration_type, status, waitlist_position,
             child_first_name, child_last_name, child_dob, shirt_size,
             guardian_name, guardian_email, guardian_phone,
             emergency_contact_name, emergency_contact_phone, notes)
            VALUES (%s,%s,'registration','waitlisted',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (rid, p['id'], wpos,
             d.get('child_first_name','').strip(), d.get('child_last_name','').strip(),
             d.get('child_dob') or None, d.get('shirt_size') or None,
             d.get('guardian_name','').strip(), email, d.get('guardian_phone','').strip() or None,
             d.get('emergency_contact_name','').strip() or None,
             d.get('emergency_contact_phone','').strip() or None,
             d.get('notes','').strip() or None))
        conn.commit()
        # Email confirmation
        try:
            send_email([email], f'You\'re on the waitlist — {p["name"]}',
                f'<p>Hi {d.get("guardian_name","")},</p>'
                f'<p>You are #{wpos} on the waitlist for <strong>{p["name"]}</strong>. '
                f'We will contact you if a spot opens up. If you are promoted, you will receive a payment link to secure your spot.</p>'
                f'<p>Horizon West Theatre Company</p>')
        except Exception: pass
        conn.close()
        return jsonify({'ok': True, 'type': 'waitlisted', 'position': wpos, 'registration_id': rid})

    # Available spot
    price = p.get('price') or 0

    # Sessions
    import json as _json2
    session_ids = d.get('session_ids') or []
    if not isinstance(session_ids, list): session_ids = []
    sessions_enabled = bool(p.get('sessions_enabled'))
    session_rows = []
    session_price_total = 0  # price per participant from sessions
    if sessions_enabled and session_ids:
        for sid in session_ids:
            sr = fetchone(conn, 'SELECT * FROM program_sessions WHERE id=%s AND program_id=%s AND status=%s',
                (sid, p['id'], 'open'))
            if sr:
                session_rows.append(sr)
                sp = sr.get('price_override') if sr.get('price_override') is not None else price
                session_price_total += sp
        # When sessions are used, effective per-participant price = sum of selected session prices
        price = session_price_total

    # Siblings (additional children in same order)
    siblings = d.get('siblings') or []
    if not isinstance(siblings, list):
        siblings = []
    participant_count = 1 + len(siblings)
    basket = price * participant_count

    # Apply promo discount code
    discount_amount = 0
    discount_code = (d.get('discount_code') or '').strip().upper()
    if discount_code and price > 0:
        dc = fetchone(conn, '''SELECT * FROM discount_codes
            WHERE program_id=%s AND code=%s AND active=TRUE''', (p['id'], discount_code))
        if dc and (not dc.get('max_uses') or dc.get('uses', 0) < dc['max_uses']):
            min_spend = dc.get('min_spend') or 0
            if not (min_spend > 0 and basket < min_spend):
                is_sib_code = bool(dc.get('is_sibling_discount'))
                if is_sib_code and participant_count >= 2:
                    per_child = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
                    discount_amount = per_child * (participant_count - 1)
                elif not is_sib_code:
                    if dc['discount_type'] == 'percent':
                        discount_amount = int(basket * dc['discount_value'] / 100)
                    else:
                        discount_amount = min(dc['discount_value'] * participant_count, basket)
                execute(conn, 'UPDATE discount_codes SET uses=uses+1 WHERE id=%s', (dc['id'],))
        else:
            discount_code = ''  # invalid, ignore

    # Program-level automatic sibling discount
    sibling_discount_amount = 0
    if p.get('sibling_discount_enabled') and participant_count >= 2 and price > 0:
        sib_type = p.get('sibling_discount_type') or 'percent'
        sib_val = p.get('sibling_discount_value') or 0
        per_sib = int(price * sib_val / 100) if sib_type == 'percent' else min(sib_val, price)
        sibling_discount_amount = per_sib * (participant_count - 1)

    # Deposit payment plan
    deposit = p.get('deposit_amount') or 0
    effective_price = max(0, basket - discount_amount - sibling_discount_amount)
    use_deposit = deposit > 0 and effective_price > deposit and d.get('payment_type') == 'deposit'
    charge_now = deposit if use_deposit else effective_price
    balance_due = max(0, effective_price - deposit) if use_deposit else 0

    def insert_reg(status, extra_cols='', extra_vals=()):
        execute(conn, f'''INSERT INTO program_registrations
            (id, program_id, registration_type, status,
             registration_form_type,
             child_first_name, child_last_name, child_dob, shirt_size,
             guardian_name, guardian_email, guardian_phone,
             emergency_contact_name, emergency_contact_phone, notes,
             allergies, pickup_contacts, photo_consent, pronouns,
             discount_code, discount_amount, sibling_discount_amount,
             participant_count, siblings_json, session_ids,
             payment_type, balance_due{', '+extra_cols if extra_cols else ''})
            VALUES (%s,%s,'registration',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s{', %s'*len(extra_vals)})''',
            (rid, p['id'], status,
             d.get('registration_form_type') or p.get('registration_form_type') or 'youth',
             d.get('child_first_name','').strip(), d.get('child_last_name','').strip(),
             d.get('child_dob') or None, d.get('shirt_size') or None,
             d.get('guardian_name','').strip(), email, d.get('guardian_phone','').strip() or None,
             d.get('emergency_contact_name','').strip() or None,
             d.get('emergency_contact_phone','').strip() or None,
             d.get('notes','').strip() or None,
             d.get('allergies','').strip() or None,
             d.get('pickup_contacts','').strip() or None,
             bool(d.get('photo_consent')),
             d.get('pronouns','').strip() or None,
             discount_code or None, discount_amount, sibling_discount_amount,
             participant_count, _json2.dumps(siblings), _json2.dumps(session_ids),
             'deposit' if use_deposit else 'full', balance_due) + extra_vals)

    if charge_now == 0:
        insert_reg('confirmed')
        finalize_registration(conn, rid)
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed_free', 'registration_id': rid})

    insert_reg('pending_payment')
    conn.commit()

    note = f'{d.get("child_first_name","")} {d.get("child_last_name","")} — {p["name"]}'
    if session_rows:
        note += ' (' + ', '.join(sr['name'] for sr in session_rows) + ')'
    if participant_count > 1:
        note += f' x{participant_count} participants'
    if use_deposit:
        note += f' (deposit ${deposit/100:.2f})'
    pay_url, link_id, order_id = square_create_payment_link(
        p, rid, email, d.get('guardian_name',''), charge_now, note=note)

    if not pay_url:
        conn.close()
        return jsonify({'error': 'Could not create payment link. Please try again.'}), 500

    execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s',
        (link_id, order_id, rid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'type': 'payment_required', 'payment_url': pay_url,
                    'registration_id': rid, 'charge_now': charge_now,
                    'balance_due': balance_due, 'use_deposit': use_deposit})


@app.route('/api/square/webhook', methods=['POST'])
def square_webhook():
    """Handle Square payment webhooks."""
    # Verify signature
    sig = request.headers.get('X-Square-Hmacsha256-Signature', '')
    body = request.get_data(as_text=True)
    if SQUARE_WEBHOOK_SIG:
        import base64 as _b64
        notification_url = f'https://rolecall.hwtco.org/api/square/webhook'
        payload = notification_url + body
        expected = hmac.new(SQUARE_WEBHOOK_SIG.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).digest()
        expected_b64 = _b64.b64encode(expected).decode()
        if not hmac.compare_digest(sig, expected_b64):
            app.logger.warning(f'Webhook signature mismatch. Got: {sig[:20]}... Expected: {expected_b64[:20]}...')
            return jsonify({'error': 'Invalid signature'}), 401

    event = request.json or {}
    event_type = event.get('type', '')
    app.logger.info(f'Square webhook: {event_type}')

    if event_type in ('payment.completed', 'payment.updated'):
        try:
            obj = event.get('data', {}).get('object', {}).get('payment', {})
            payment_id = obj.get('id')
            order_id = obj.get('order_id')
            status = obj.get('status')
            amount_cents = obj.get('amount_money', {}).get('amount', 0)
            if status == 'COMPLETED' and order_id:
                conn = get_db()
                # Check registrations first
                reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE square_order_id=%s OR square_checkout_id=%s',
                    (order_id, order_id))
                if reg and reg['status'] == 'pending_payment':
                    finalize_registration(conn, reg['id'], payment_id, order_id)
                elif reg and reg['status'] == 'waitlisted':
                    execute(conn, "UPDATE program_registrations SET status='confirmed', square_payment_id=%s, updated_at=NOW() WHERE id=%s",
                        (payment_id, reg['id']))
                    finalize_registration(conn, reg['id'], payment_id, order_id)
                    conn.commit()
                else:
                    # Check cart orders
                    import json as _jw
                    cart = fetchone(conn, "SELECT * FROM cart_orders WHERE (square_order_id=%s OR square_checkout_id=%s) AND status='pending'",
                        (order_id, order_id))
                    if cart:
                        execute(conn, "UPDATE cart_orders SET status='completed' WHERE id=%s", (cart['id'],))
                        try:
                            items = _jw.loads(cart.get('items_json') or '[]')
                        except Exception:
                            items = []
                        for it in items:
                            rid = it.get('registration_id')
                            if rid:
                                reg2 = fetchone(conn, 'SELECT status FROM program_registrations WHERE id=%s', (rid,))
                                if reg2 and reg2['status'] == 'pending_payment':
                                    finalize_registration(conn, rid, payment_id, order_id)
                        conn.commit()
                    else:
                        # Check pending donations
                        don = fetchone(conn, "SELECT * FROM pending_donations WHERE (square_order_id=%s OR square_checkout_id=%s) AND status='pending'",
                            (order_id, order_id))
                        if don:
                            finalize_donation(conn, don['id'], payment_id, amount_cents)
                conn.close()
        except Exception as e:
            app.logger.error(f'Webhook processing error: {e}', exc_info=True)

    return jsonify({'ok': True})


def finalize_donation(conn, pending_id, payment_id, amount_cents):
    """Convert a pending donation into a donor_donations record."""
    import uuid as _ud
    don = fetchone(conn, 'SELECT * FROM pending_donations WHERE id=%s', (pending_id,))
    if not don:
        return
    execute(conn, "UPDATE pending_donations SET status='completed' WHERE id=%s", (pending_id,))
    email = (don.get('email') or '').strip().lower()
    name = (don.get('name') or '').strip()
    amount = (amount_cents or don.get('amount_cents') or 0) / 100.0
    today = __import__('datetime').date.today().isoformat()
    # Find or create donor
    donor = fetchone(conn, 'SELECT * FROM donors WHERE LOWER(email)=LOWER(%s)', (email,))
    if not donor:
        did = str(_ud.uuid4())
        execute(conn, '''INSERT INTO donors (id, type, display_name, email, status, created_at)
            VALUES (%s,'individual',%s,%s,'active',NOW())''', (did, name, email))
        donor = fetchone(conn, 'SELECT * FROM donors WHERE id=%s', (did,))
    # Log donation
    execute(conn, '''INSERT INTO donor_donations
        (id, donor_id, amount, donation_date, type, payment_status, notes, created_at)
        VALUES (%s,%s,%s,%s,'square','received',%s,NOW())''',
        (str(_ud.uuid4()), donor['id'], amount, today,
         f'Online donation via Marquee — Square payment {payment_id}' + (f' — {don["message"]}' if don.get('message') else '')))
    recalc_donor_totals(conn, donor['id'])
    conn.commit()
    app.logger.info(f'Donation finalized: ${amount:.2f} from {email}')


# ── Rising Stars Production Registration Routes ──────────────────────────────

def _prod_to_public(prod, conn):
    """Convert a production row to the same shape as public_program_info."""
    import json as _j
    for k in ['program_images', 'custom_fields', 'form_fields', 'meeting_days']:
        v = prod.get(k)
        if v:
            try:
                prod[k] = _j.loads(v)
            except Exception:
                prod[k] = [] if k != 'form_fields' else {}
        else:
            prod[k] = [] if k != 'form_fields' else {}
    reg_count = (fetchone(conn, """SELECT COUNT(*) AS c FROM program_registrations
        WHERE production_id=%s AND status NOT IN ('waitlisted','cancelled')""",
        (prod['id'],)) or {}).get('c', 0)
    prod['registration_count'] = reg_count
    prod['spots_remaining'] = max(0, (prod['capacity'] or 999) - reg_count) if prod.get('capacity') else None
    prod['_context'] = 'production'
    return prod


@app.route('/api/public/production/<slug>')
def public_production_info(slug):
    conn = get_db()
    prod = fetchone(conn, "SELECT * FROM productions WHERE slug=%s OR id=%s", (slug, slug))
    if not prod:
        conn.close()
        return jsonify({'error': 'Production not found'}), 404
    result = _prod_to_public(dict(prod), conn)
    conn.close()
    return jsonify(result)


@app.route('/api/public/production/<slug>/validate-discount', methods=['POST'])
def validate_production_discount(slug):
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'valid': False, 'error': 'Code required'})
    conn = get_db()
    prod = fetchone(conn, "SELECT * FROM productions WHERE slug=%s OR id=%s", (slug, slug))
    if not prod:
        conn.close()
        return jsonify({'valid': False, 'error': 'Production not found'})
    dc = fetchone(conn, "SELECT * FROM discount_codes WHERE production_id=%s AND code=%s AND active=TRUE", (prod['id'], code))
    conn.close()
    if not dc:
        return jsonify({'valid': False, 'error': 'Invalid or expired code'})
    if dc.get('max_uses') and (dc.get('uses') or 0) >= dc['max_uses']:
        return jsonify({'valid': False, 'error': 'This code has reached its maximum uses'})
    price = prod.get('price') or 0
    num_regs = int(d.get('num_registrations') or 1)
    basket = price * num_regs
    min_spend = dc.get('min_spend') or 0
    if min_spend > 0 and basket < min_spend:
        return jsonify({'valid': False, 'error': f'This code requires a minimum spend of ${min_spend/100:.2f}'})
    is_sib = bool(dc.get('is_sibling_discount'))
    if is_sib:
        if num_regs < 2:
            return jsonify({'valid': False, 'error': 'Sibling discount requires 2+ participants'})
        per = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
        discount_amount = per * (num_regs - 1)
        label = f'Sibling discount: {dc["discount_value"]}{"%" if dc["discount_type"]=="percent" else "¢"} off each additional participant'
    else:
        if dc['discount_type'] == 'percent':
            discount_amount = int(basket * dc['discount_value'] / 100)
            label = f'{dc["discount_value"]}% off'
        else:
            discount_amount = min(dc['discount_value'] * num_regs, basket)
            label = f'${dc["discount_value"]/100:.2f} off'
    if min_spend:
        label += f' (min. ${min_spend/100:.2f})'
    return jsonify({'valid': True, 'discount_amount': discount_amount,
                    'final_price': max(0, basket - discount_amount),
                    'is_sibling': is_sib, 'label': label})


@app.route('/api/public/production/<slug>/register', methods=['POST'])
def public_register_production(slug):
    import json as _jc2, uuid as _uc2
    d = request.json or {}
    conn = get_db()
    prod = fetchone(conn, "SELECT * FROM productions WHERE slug=%s OR id=%s", (slug, slug))
    if not prod:
        conn.close()
        return jsonify({'error': 'Production not found'}), 404

    reg_type = d.get('type', 'registration')

    # Interest list
    if reg_type == 'interest':
        name = (d.get('name') or '').strip()
        email = (d.get('email') or '').strip().lower()
        if not name or not email:
            conn.close()
            return jsonify({'error': 'Name and email required'}), 400
        existing = fetchone(conn, 'SELECT id FROM interest_list_entries WHERE production_id=%s AND email=%s', (prod['id'], email))
        if existing:
            conn.close()
            return jsonify({'ok': True, 'message': 'Already on interest list'})
        execute(conn, 'INSERT INTO interest_list_entries (id,production_id,name,email,phone,child_name,child_age) VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (str(_uc2.uuid4()), prod['id'], name, email,
             (d.get('phone') or '').strip(),
             (d.get('child_name') or '').strip(),
             (d.get('child_age') or '').strip()))
        conn.commit()
        # Thank-you email
        try:
            first = name.split()[0]
            send_email([email], f'You\'re on the interest list — {prod["name"]}',
                f'<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">'
                f'<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:28px 24px;text-align:center;border-radius:12px 12px 0 0">'
                f'<img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" alt="HWTC" style="height:48px;display:block;margin:0 auto 10px;mix-blend-mode:screen"/></div>'
                f'<div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb">'
                f'<h2 style="color:#0d3d4d;margin:0 0 12px">You\'re on the list!</h2>'
                f'<p>Hi {first},</p><p>Thanks for your interest in <strong>{prod["name"]}</strong>! We\'ll reach out as soon as registration opens.</p>'
                f'<p style="color:#6b7280;font-size:13px">Horizon West Theatre Company</p></div></div>')
        except Exception: pass
        conn.close()
        return jsonify({'ok': True, 'type': 'interest'})

    # Waitlist
    if reg_type == 'waitlist':
        guardian_email = (d.get('guardian_email') or '').strip().lower()
        if not guardian_email:
            conn.close()
            return jsonify({'error': 'Email required'}), 400
        pos_row = fetchone(conn, "SELECT COALESCE(MAX(waitlist_position),0)+1 AS pos FROM program_registrations WHERE production_id=%s AND status='waitlisted'", (prod['id'],))
        position = (pos_row or {}).get('pos', 1)
        rid = str(_uc2.uuid4())
        execute(conn, '''INSERT INTO program_registrations
            (id, production_id, registration_type, status, child_first_name, child_last_name,
             guardian_name, guardian_email, guardian_phone, notes, waitlist_position)
            VALUES (%s,%s,'registration','waitlisted',%s,%s,%s,%s,%s,%s,%s)''',
            (rid, prod['id'],
             (d.get('child_first_name') or '').strip(),
             (d.get('child_last_name') or '').strip(),
             (d.get('guardian_name') or '').strip(),
             guardian_email,
             (d.get('guardian_phone') or '').strip(),
             (d.get('notes') or '').strip(),
             position))
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'type': 'waitlisted', 'position': position})

    # Full registration
    guardian_email = (d.get('guardian_email') or '').strip().lower()
    if not guardian_email:
        conn.close()
        return jsonify({'error': 'Email required'}), 400
    reg_count = (fetchone(conn, "SELECT COUNT(*) AS c FROM program_registrations WHERE production_id=%s AND status NOT IN ('waitlisted','cancelled')", (prod['id'],)) or {}).get('c', 0)
    if prod.get('capacity') and reg_count >= prod['capacity']:
        conn.close()
        return jsonify({'error': 'Production is now full. Please join the waitlist.'})

    price = prod.get('price') or 0
    siblings = d.get('siblings') or []
    if not isinstance(siblings, list): siblings = []
    participant_count = 1 + len(siblings)
    basket = price * participant_count

    discount_code_used = (d.get('discount_code') or '').strip().upper()
    discount_amount = 0
    sibling_discount_amount = 0
    square_discount_id = None
    if discount_code_used and price > 0:
        dc = fetchone(conn, 'SELECT * FROM discount_codes WHERE production_id=%s AND code=%s AND active=TRUE', (prod['id'], discount_code_used))
        if dc and (not dc.get('max_uses') or dc.get('uses', 0) < dc['max_uses']):
            min_spend = dc.get('min_spend') or 0
            if not (min_spend > 0 and basket < min_spend):
                is_sib_code = bool(dc.get('is_sibling_discount'))
                if is_sib_code and participant_count >= 2:
                    per = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
                    discount_amount = per * (participant_count - 1)
                elif not is_sib_code:
                    discount_amount = int(basket * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'] * participant_count, basket)
                square_discount_id = dc.get('square_discount_id')
                execute(conn, 'UPDATE discount_codes SET uses=uses+1 WHERE id=%s', (dc['id'],))
        else:
            discount_code_used = ''

    if prod.get('sibling_discount_enabled') and participant_count >= 2 and price > 0:
        sib_type = prod.get('sibling_discount_type') or 'percent'
        sib_val = prod.get('sibling_discount_value') or 0
        per_sib = int(price * sib_val / 100) if sib_type == 'percent' else min(sib_val, price)
        sibling_discount_amount = per_sib * (participant_count - 1)

    deposit = prod.get('deposit_amount') or 0
    effective_price = max(0, basket - discount_amount - sibling_discount_amount)
    use_deposit = deposit > 0 and effective_price > deposit and d.get('payment_type') == 'deposit'
    charge_now = deposit if use_deposit else effective_price
    balance_due = max(0, effective_price - deposit) if use_deposit else 0

    rid = str(_uc2.uuid4())
    execute(conn, '''INSERT INTO program_registrations
        (id, production_id, registration_type, status,
         child_first_name, child_last_name, child_dob, shirt_size,
         guardian_name, guardian_email, guardian_phone,
         emergency_contact_name, emergency_contact_phone, notes,
         allergies, pickup_contacts, photo_consent, pronouns,
         discount_code, discount_amount, sibling_discount_amount,
         participant_count, siblings_json, payment_type, balance_due)
        VALUES (%s,%s,'registration',%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s)''',
        (rid, prod['id'],
         'pending_payment' if (price > 0 and charge_now > 0) else 'confirmed',
         (d.get('child_first_name') or '').strip(),
         (d.get('child_last_name') or '').strip(),
         d.get('child_dob') or None, d.get('shirt_size') or None,
         (d.get('guardian_name') or '').strip(),
         guardian_email, (d.get('guardian_phone') or '').strip() or None,
         (d.get('emergency_contact_name') or '').strip() or None,
         (d.get('emergency_contact_phone') or '').strip() or None,
         (d.get('notes') or '').strip() or None,
         (d.get('allergies') or '').strip() or None,
         (d.get('pickup_contacts') or '').strip() or None,
         bool(d.get('photo_consent')),
         (d.get('pronouns') or '').strip() or None,
         discount_code_used or None, discount_amount, sibling_discount_amount,
         participant_count, _jc2.dumps(siblings),
         'deposit' if use_deposit else 'full', balance_due))
    conn.commit()

    if price == 0 or charge_now == 0:
        finalize_registration(conn, rid)
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed', 'registration_id': rid})

    try:
        note = f'{d.get("child_first_name","")} {d.get("child_last_name","")} — {prod["name"]}'
        if use_deposit: note += ' (Deposit)'
        pay_url, link_id, order_id = square_create_payment_link(
            prod, rid, guardian_email,
            d.get('guardian_name', ''), charge_now, note=note)
        execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s',
            (link_id, order_id, rid))
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'type': 'payment_required',
                        'payment_url': pay_url, 'registration_id': rid, 'use_deposit': use_deposit})
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Registration saved but payment link failed: {str(e)}'}), 500


@app.route('/api/public/production/<slug>/registration/<rid>')
def public_production_registration_status(slug, rid):
    conn = get_db()
    prod = fetchone(conn, "SELECT id FROM productions WHERE slug=%s OR id=%s", (slug, slug))
    if not prod:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    reg = fetchone(conn, 'SELECT id, status, child_first_name, child_last_name, guardian_email FROM program_registrations WHERE id=%s AND production_id=%s', (rid, prod['id']))
    conn.close()
    if not reg:
        return jsonify({'error': 'Registration not found'}), 404
    return jsonify(dict(reg))


# ── Production admin registration routes ─────────────────────────────────────

@app.route('/api/productions/<pid>/registrations', methods=['GET'])
def get_production_registrations(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    regs = fetchall(conn, '''SELECT pr.*, p.name AS production_name, p.registration_form_type
        FROM program_registrations pr
        JOIN productions p ON p.id=pr.production_id
        WHERE pr.production_id=%s ORDER BY pr.created_at DESC''', (pid,))
    conn.close()
    return jsonify(regs or [])


@app.route('/api/productions/<pid>/registrations/<rid>', methods=['PUT'])
def update_production_registration(pid, rid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE program_registrations SET
        status=%s, guardian_name=%s, guardian_email=%s, guardian_phone=%s,
        emergency_contact_name=%s, emergency_contact_phone=%s,
        shirt_size=%s, notes=%s, updated_at=NOW()
        WHERE id=%s AND production_id=%s''',
        (d.get('status'), (d.get('guardian_name') or '').strip(),
         (d.get('guardian_email') or '').strip().lower(),
         (d.get('guardian_phone') or '').strip() or None,
         (d.get('emergency_contact_name') or '').strip() or None,
         (d.get('emergency_contact_phone') or '').strip() or None,
         d.get('shirt_size') or None,
         (d.get('notes') or '').strip() or None,
         rid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/productions/<pid>/registrations/<rid>', methods=['DELETE'])
def delete_production_registration(pid, rid):
    err = require_permission('marquee')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM program_registrations WHERE id=%s AND production_id=%s', (rid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/productions/<pid>/registrations/<rid>/promote-waitlist', methods=['POST'])
def promote_production_waitlist(pid, rid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    hold_hours = int(d.get('hold_hours') or 48)
    conn = get_db()
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s AND production_id=%s', (rid, pid))
    prod = fetchone(conn, 'SELECT * FROM productions WHERE id=%s', (pid,))
    if not reg or not prod:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    price = prod.get('price') or 0
    if price == 0:
        execute(conn, "UPDATE program_registrations SET status='confirmed', waitlist_position=NULL WHERE id=%s", (rid,))
        conn.commit()
        try:
            name = reg.get('guardian_name') or reg.get('child_first_name') or 'there'
            send_email([reg['guardian_email']], f'You\'re confirmed — {prod["name"]}',
                f'<p>Hi {name},</p><p>A spot has opened in <strong>{prod["name"]}</strong> and you\'ve been confirmed!</p><p>Horizon West Theatre Company</p>')
        except Exception: pass
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed_free'})
    execute(conn, "UPDATE program_registrations SET status='pending_payment', waitlist_position=NULL WHERE id=%s", (rid,))
    try:
        child = ((reg.get('child_first_name') or '') + ' ' + (reg.get('child_last_name') or '')).strip()
        note = f'Waitlist promotion — {child or reg["guardian_email"]} — {prod["name"]}'
        pay_url, link_id, order_id = square_create_payment_link(prod, rid, reg['guardian_email'], reg.get('guardian_name', ''), price, note=note)
        if pay_url:
            execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s', (link_id, order_id, rid))
    except Exception as e:
        app.logger.warning(f'Waitlist promote payment link failed: {e}')
        pay_url = None
    conn.commit()
    try:
        name = reg.get('guardian_name') or reg.get('child_first_name') or 'there'
        hold_msg = f'Your spot will be held for <strong>{hold_hours} hours</strong>.' if hold_hours else 'Please complete your registration as soon as possible.'
        send_email([reg['guardian_email']], f'A spot opened up — {prod["name"]}',
            f'<p>Hi {name},</p><p>A spot is available in <strong>{prod["name"]}</strong>! {hold_msg}</p>'
            + (f'<p><a href="{pay_url}" style="background:#145466;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:700">Secure My Spot</a></p>' if pay_url else '')
            + '<p>Horizon West Theatre Company</p>')
    except Exception: pass
    conn.close()
    return jsonify({'ok': True, 'type': 'payment_link_sent', 'hold_hours': hold_hours})


@app.route('/api/productions/<pid>/registration-settings', methods=['PUT'])
def save_production_registration_settings(pid):
    err = require_permission('rising_stars')
    if err:
        err = require_permission('productions')
        if err: return err
    import json as _jps
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE productions SET
        registration_status=%s, registration_form_type=%s, slug=%s,
        capacity=%s, price=%s, deposit_amount=%s,
        sibling_discount_enabled=%s, sibling_discount_type=%s, sibling_discount_value=%s,
        registration_open_date=%s, registration_close_date=%s, waitlist_auto_charge=%s,
        program_info=%s, custom_fields=%s, form_fields=%s,
        registration_note=%s,
        program_location=%s, schedule_type=%s, meeting_days=%s,
        meeting_start_time=%s, meeting_end_time=%s, single_date=%s, schedule_notes=%s,
        start_date=%s, end_date=%s
        WHERE id=%s''',
        (d.get('registration_status') or 'draft',
         d.get('registration_form_type') or 'youth',
         re.sub(r'[^a-z0-9-]', '', (d.get('slug') or '').strip().lower().replace(' ', '-')) or None,
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
         _jps.dumps(d.get('custom_fields') or []),
         _jps.dumps(d.get('form_fields') or {}),
         (d.get('registration_note') or '').strip(),
         (d.get('program_location') or '').strip(),
         d.get('schedule_type') or 'date_range',
         _jps.dumps(d.get('meeting_days') or []),
         (d.get('meeting_start_time') or '').strip(),
         (d.get('meeting_end_time') or '').strip(),
         (d.get('single_date') or '').strip(),
         (d.get('schedule_notes') or '').strip(),
         d.get('start_date') or None,
         d.get('end_date') or None,
         pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/productions/<pid>/upload-cover', methods=['POST'])
def upload_production_cover(pid):
    err = require_auth()
    if err: return err
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'Empty file'}), 400
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return jsonify({'error': 'Only JPG, PNG, GIF, or WEBP allowed'}), 400
    conn = get_db()
    prod = fetchone(conn, 'SELECT name, slug FROM productions WHERE id=%s', (pid,))
    conn.close()
    if not prod:
        return jsonify({'error': 'Not found'}), 404
    base = secure_filename((prod.get('slug') or prod.get('name') or pid).replace(' ', '-').lower())
    filename = f'production-{base}-cover{ext}'
    file_bytes = f.read()
    gh_url, gh_err = upload_image_to_github(filename, file_bytes)
    if gh_url:
        url = gh_url
    else:
        app.logger.warning(f'GitHub upload failed ({gh_err}), saving locally')
        with open(os.path.join(app.static_folder, 'images', filename), 'wb') as fp: fp.write(file_bytes)
        url = f'/static/images/{filename}'
    import json as _juc
    conn2 = get_db()
    prod_full = fetchone(conn2, 'SELECT program_images FROM productions WHERE id=%s', (pid,))
    try:
        images = _juc.loads(prod_full.get('program_images') or '[]')
    except Exception:
        images = []
    images = [url] + [img for img in images if img != url]
    execute(conn2, 'UPDATE productions SET program_images=%s WHERE id=%s', (_juc.dumps(images), pid))
    conn2.commit(); conn2.close()
    return jsonify({'ok': True, 'url': url})


@app.route('/api/productions/<pid>/discount-codes', methods=['GET'])
def get_production_discount_codes(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    codes = fetchall(conn, 'SELECT * FROM discount_codes WHERE production_id=%s ORDER BY created_at DESC', (pid,))
    conn.close()
    return jsonify(codes or [])


@app.route('/api/productions/<pid>/discount-codes', methods=['POST'])
def create_production_discount_code(pid):
    err = require_auth()
    if err: return err
    import uuid as _udc
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required'}), 400
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO discount_codes
            (id, production_id, code, discount_type, discount_value,
             min_spend, is_sibling_discount, max_uses, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE)''',
            (_udc.uuid4().hex, pid, code,
             d.get('discount_type', 'percent'),
             int(d.get('discount_value') or 0),
             int(d.get('min_spend_cents') or 0),
             bool(d.get('is_sibling_discount')),
             d.get('max_uses') or None))
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/productions/<pid>/discount-codes/<cid>', methods=['DELETE'])
def delete_production_discount_code(pid, cid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE discount_codes SET active=FALSE WHERE id=%s AND production_id=%s', (cid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/productions/<pid>/notify-interest-list', methods=['POST'])
def notify_production_interest_list(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    prod = fetchone(conn, 'SELECT * FROM productions WHERE id=%s', (pid,))
    if not prod:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    entries = fetchall(conn, 'SELECT * FROM interest_list_entries WHERE production_id=%s', (pid,))
    conn.close()
    if not entries:
        return jsonify({'ok': True, 'sent': 0})
    slug = prod.get('slug') or pid
    reg_url = f'{APP_BASE_URL}/register/production/{slug}'
    sent = 0
    for e in entries:
        email = e.get('email')
        name = (e.get('name') or '').strip().split()[0] or 'there'
        if not email: continue
        try:
            send_email([email], f'Registration is now open — {prod["name"]}',
                f'<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto">'
                f'<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:28px 24px;text-align:center;border-radius:12px 12px 0 0">'
                f'<img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" alt="HWTC" style="height:48px;display:block;margin:0 auto 10px;mix-blend-mode:screen"/></div>'
                f'<div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb">'
                f'<h2 style="color:#0d3d4d;margin:0 0 12px">Registration is now open!</h2>'
                f'<p>Hi {name},</p><p>Registration for <strong>{prod["name"]}</strong> is now open!</p>'
                f'<p style="text-align:center;margin:20px 0"><a href="{reg_url}" style="background:#145466;color:#fff;padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700">Register Now &rarr;</a></p>'
                f'<p style="color:#6b7280;font-size:12px;text-align:center">Horizon West Theatre Company &nbsp;&middot;&nbsp; Horizon West, FL</p>'
                f'</div></div>')
            conn2 = get_db()
            execute(conn2, 'UPDATE interest_list_entries SET notified_at=NOW() WHERE id=%s', (e['id'],))
            conn2.commit(); conn2.close()
            sent += 1
        except Exception as ex:
            app.logger.warning(f'Production interest list notify failed for {email}: {ex}')
    return jsonify({'ok': True, 'sent': sent})


# ── Public cart routes ──────────────────────────────────────────────────────

@app.route('/register/cart')
@app.route('/register/cart/confirmation')
def cart_page():
    return send_from_directory('static', 'cart.html')


@app.route('/api/public/programs')
def public_programs_list():
    """All open programs for the browse/add-more experience."""
    conn = get_db()
    progs = fetchall(conn, """SELECT id, name, slug, description, price, deposit_amount,
        capacity, registration_status, registration_form_type,
        start_date, end_date, sibling_discount_enabled,
        sibling_discount_type, sibling_discount_value
        FROM youth_programs WHERE registration_status='open'
        ORDER BY start_date ASC NULLS LAST, name ASC""")
    for p in progs:
        count = (fetchone(conn, "SELECT COUNT(*) AS c FROM program_registrations WHERE program_id=%s AND status IN ('confirmed','pending_payment')", (p['id'],)) or {}).get('c', 0)
        p['registration_count'] = count
        p['spots_remaining'] = max(0, (p['capacity'] or 999) - count) if p.get('capacity') else None
    conn.close()
    return jsonify(progs or [])


@app.route('/api/public/validate-cart-discount', methods=['POST'])
def validate_cart_discount():
    """Validate a cart-level promo code against the basket total."""
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    basket = int(d.get('basket_cents') or 0)
    if not code:
        return jsonify({'valid': False, 'error': 'Code required'})
    conn = get_db()
    dc = fetchone(conn, "SELECT * FROM cart_discount_codes WHERE UPPER(code)=%s AND active=TRUE", (code,))
    conn.close()
    if not dc:
        return jsonify({'valid': False, 'error': 'Invalid or expired code'})
    if dc.get('max_uses') and (dc.get('uses') or 0) >= dc['max_uses']:
        return jsonify({'valid': False, 'error': 'This code has reached its maximum uses'})
    min_spend = dc.get('min_spend') or 0
    if min_spend > 0 and basket < min_spend:
        return jsonify({'valid': False, 'error': f'This code requires a minimum cart total of ${min_spend/100:.2f}'})
    if dc['discount_type'] == 'percent':
        discount = int(basket * dc['discount_value'] / 100)
        label = f'{dc["discount_value"]}% off your cart'
    else:
        discount = min(dc['discount_value'], basket)
        label = f'${dc["discount_value"]/100:.2f} off your cart'
    if min_spend:
        label += f' (min. ${min_spend/100:.2f})'
    final = max(0, basket - discount)
    return jsonify({'valid': True, 'discount_amount': discount, 'final_price': final, 'label': label})


@app.route('/api/public/cart/checkout', methods=['POST'])
def cart_checkout():
    """Create a single Square payment for a multi-program cart."""
    import json as _jc, uuid as _uc
    d = request.json or {}
    guardian_name = (d.get('guardian_name') or '').strip()
    guardian_email = (d.get('guardian_email') or '').strip().lower()
    guardian_phone = (d.get('guardian_phone') or '').strip()
    items = d.get('items') or []
    cart_code = (d.get('cart_discount_code') or '').strip().upper()

    if not guardian_email or not guardian_name:
        return jsonify({'error': 'Name and email are required'}), 400
    if not items:
        return jsonify({'error': 'Cart is empty'}), 400

    conn = get_db()

    # Resolve each item's program and compute pricing
    line_items = []
    total_cents = 0
    free_items = []   # items with price=0 or fully discounted — auto-confirm
    paid_items = []   # items that need payment

    for item in items:
        prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s OR slug=%s',
            (item.get('program_id',''), item.get('slug','')))
        if not prog:
            conn.close()
            return jsonify({'error': f'Program not found: {item.get("program_name","")}'}), 400

        price = prog.get('price') or 0
        siblings = item.get('siblings') or []
        participant_count = 1 + len(siblings)
        basket = price * participant_count

        # Program promo code
        prog_discount = 0
        prog_code_used = (item.get('promo_code') or '').strip().upper()
        if prog_code_used and price > 0:
            dc = fetchone(conn, 'SELECT * FROM discount_codes WHERE program_id=%s AND code=%s AND active=TRUE', (prog['id'], prog_code_used))
            if dc and (not dc.get('max_uses') or dc.get('uses', 0) < dc['max_uses']):
                min_spend = dc.get('min_spend') or 0
                if not (min_spend > 0 and basket < min_spend):
                    is_sib = bool(dc.get('is_sibling_discount'))
                    if is_sib and participant_count >= 2:
                        per = int(price * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'], price)
                        prog_discount = per * (participant_count - 1)
                    elif not is_sib:
                        prog_discount = int(basket * dc['discount_value'] / 100) if dc['discount_type'] == 'percent' else min(dc['discount_value'] * participant_count, basket)
                    execute(conn, 'UPDATE discount_codes SET uses=uses+1 WHERE id=%s', (dc['id'],))
            else:
                prog_code_used = ''

        # Program-level auto sibling discount
        sib_discount = 0
        if prog.get('sibling_discount_enabled') and participant_count >= 2 and price > 0:
            sib_type = prog.get('sibling_discount_type') or 'percent'
            sib_val = prog.get('sibling_discount_value') or 0
            per_sib = int(price * sib_val / 100) if sib_type == 'percent' else min(sib_val, price)
            sib_discount = per_sib * (participant_count - 1)

        effective = max(0, basket - prog_discount - sib_discount)
        item_data = {
            'program_id': prog['id'],
            'program_name': prog['name'],
            'slug': prog.get('slug') or '',
            'price': price,
            'participant_count': participant_count,
            'child_first_name': (item.get('child_first_name') or '').strip(),
            'child_last_name': (item.get('child_last_name') or '').strip(),
            'child_dob': item.get('child_dob') or '',
            'shirt_size': item.get('shirt_size') or '',
            'notes': (item.get('notes') or '').strip(),
            'custom_field_values': item.get('custom_field_values') or {},
            'siblings': siblings,
            'promo_code': prog_code_used or None,
            'promo_discount': prog_discount,
            'sibling_discount': sib_discount,
            'effective_price': effective,
            'payment_type': item.get('payment_type') or 'full',
            'deposit_amount': prog.get('deposit_amount') or 0,
        }
        line_items.append(item_data)
        total_cents += effective

    # Cart-level discount code
    cart_discount_amount = 0
    cart_code_used = ''
    if cart_code and total_cents > 0:
        cdc = fetchone(conn, "SELECT * FROM cart_discount_codes WHERE UPPER(code)=%s AND active=TRUE", (cart_code,))
        if cdc and (not cdc.get('max_uses') or cdc.get('uses', 0) < cdc['max_uses']):
            min_spend = cdc.get('min_spend') or 0
            if not (min_spend > 0 and total_cents < min_spend):
                if cdc['discount_type'] == 'percent':
                    cart_discount_amount = int(total_cents * cdc['discount_value'] / 100)
                else:
                    cart_discount_amount = min(cdc['discount_value'], total_cents)
                execute(conn, 'UPDATE cart_discount_codes SET uses=uses+1 WHERE id=%s', (cdc['id'],))
                cart_code_used = cart_code

    final_total = max(0, total_cents - cart_discount_amount)

    # Apportion cart discount across paid items proportionally
    if cart_discount_amount > 0 and total_cents > 0:
        remaining_disc = cart_discount_amount
        for i, it in enumerate(line_items):
            if i < len(line_items) - 1:
                share = int(cart_discount_amount * it['effective_price'] / total_cents)
            else:
                share = remaining_disc  # last item gets remainder
            it['cart_discount_share'] = share
            it['effective_price'] = max(0, it['effective_price'] - share)
            remaining_disc -= share

    # Split into free and paid items, create pending registrations for all
    cart_order_id = _uc.uuid4().hex
    reg_ids = []
    for it in line_items:
        rid = _uc.uuid4().hex
        it['registration_id'] = rid
        prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (it['program_id'],))
        # Check capacity
        reg_count = (fetchone(conn, "SELECT COUNT(*) AS c FROM program_registrations WHERE program_id=%s AND status IN ('confirmed','pending_payment')", (it['program_id'],)) or {}).get('c', 0)
        cap = prog.get('capacity') if prog else None
        is_full = cap and reg_count >= cap
        status = 'waitlisted' if is_full else ('confirmed' if it['effective_price'] == 0 else 'pending_payment')
        deposit = it['deposit_amount']
        use_deposit = it['payment_type'] == 'deposit' and deposit > 0 and it['effective_price'] > deposit
        charge_now = deposit if use_deposit else it['effective_price']
        balance_due = max(0, it['effective_price'] - deposit) if use_deposit else 0
        it['charge_now'] = charge_now
        it['balance_due'] = balance_due
        it['use_deposit'] = use_deposit
        wpos = None
        if is_full:
            wpos_row = fetchone(conn, 'SELECT MAX(waitlist_position) AS m FROM program_registrations WHERE program_id=%s AND status=%s', (it['program_id'], 'waitlisted'))
            wpos = ((wpos_row or {}).get('m') or 0) + 1
        execute(conn, '''INSERT INTO program_registrations
            (id, program_id, registration_type, status,
             child_first_name, child_last_name, child_dob, shirt_size,
             guardian_name, guardian_email, guardian_phone, notes,
             discount_code, discount_amount, sibling_discount_amount,
             participant_count, siblings_json,
             payment_type, balance_due, waitlist_position)
            VALUES (%s,%s,'registration',%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,
                    %s,%s,%s)''',
            (rid, it['program_id'], status,
             it['child_first_name'], it['child_last_name'],
             it['child_dob'] or None, it['shirt_size'] or None,
             guardian_name, guardian_email, guardian_phone or None, it['notes'] or None,
             it['promo_code'], it['promo_discount'] + it.get('cart_discount_share', 0), it['sibling_discount'],
             it['participant_count'], _jc.dumps(it['siblings']),
             'deposit' if use_deposit else 'full', balance_due, wpos))
        reg_ids.append(rid)
        if status == 'confirmed':
            finalize_registration(conn, rid)
        if is_full:
            try:
                send_email([guardian_email], f'You\'re on the waitlist — {it["program_name"]}',
                    f'<p>Hi {guardian_name},</p><p>You are #{wpos} on the waitlist for <strong>{it["program_name"]}</strong>. We will contact you if a spot opens up.</p><p>Horizon West Theatre Company</p>')
            except Exception: pass

    # Save cart order
    execute(conn, '''INSERT INTO cart_orders
        (id, guardian_name, guardian_email, guardian_phone, items_json,
         cart_discount_code, cart_discount_amount, total_cents, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')''',
        (cart_order_id, guardian_name, guardian_email, guardian_phone or None,
         _jc.dumps(line_items), cart_code_used or None, cart_discount_amount, final_total))
    conn.commit()

    # If everything is free/waitlisted, no payment needed
    paid_line_items = [it for it in line_items if it['charge_now'] > 0]
    if not paid_line_items:
        execute(conn, "UPDATE cart_orders SET status='completed' WHERE id=%s", (cart_order_id,))
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed_free', 'cart_order_id': cart_order_id,
                        'registration_ids': reg_ids})

    # Build Square order with one line item per paid program
    sq_line_items = []
    for it in paid_line_items:
        name = it['program_name']
        if it['participant_count'] > 1:
            name += f' ({it["participant_count"]} participants)'
        if it['use_deposit']:
            name += ' — Deposit'
        sq_line_items.append({
            'name': name[:191],
            'quantity': '1',
            'base_price_money': {'amount': it['charge_now'], 'currency': 'USD'},
        })

    import uuid as _uc2
    redirect_url = f'{APP_BASE_URL}/register/cart/confirmation?order={cart_order_id}'
    payload = {
        'idempotency_key': _uc2.uuid4().hex,
        'order': {
            'location_id': SQUARE_LOCATION_ID,
            'line_items': sq_line_items,
            'reference_id': cart_order_id[:40],
        },
        'checkout_options': {'redirect_url': redirect_url, 'ask_for_shipping_address': False},
        'pre_populated_data': {'buyer_email': guardian_email},
        'description': f'HWTC Registration — {len(paid_line_items)} program(s)',
    }
    try:
        r = requests.post(f'{SQUARE_API_BASE}/v2/online-checkout/payment-links',
            json=payload, headers=square_headers(), timeout=15)
        data = r.json()
        if r.status_code == 200 and data.get('payment_link'):
            lnk = data['payment_link']
            execute(conn, 'UPDATE cart_orders SET square_order_id=%s, square_checkout_id=%s WHERE id=%s',
                (lnk.get('order_id'), lnk.get('id'), cart_order_id))
            conn.commit()
            conn.close()
            return jsonify({'ok': True, 'type': 'payment_required',
                            'payment_url': lnk.get('url'),
                            'cart_order_id': cart_order_id})
        conn.close()
        return jsonify({'error': 'Could not create payment link. Please try again.'}), 500
    except Exception as e:
        conn.close()
        app.logger.error(f'Cart checkout Square error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/public/cart/order/<oid>')
def get_cart_order_status(oid):
    conn = get_db()
    order = fetchone(conn, 'SELECT id, status, guardian_name, guardian_email, total_cents, items_json FROM cart_orders WHERE id=%s', (oid,))
    conn.close()
    if not order:
        return jsonify({'error': 'Not found'}), 404
    import json as _jo
    try:
        order['items'] = _jo.loads(order.get('items_json') or '[]')
    except Exception:
        order['items'] = []
    return jsonify(order)


# ── Program Sessions ─────────────────────────────────────────────────────────

@app.route('/api/programs/<pid>/sessions', methods=['GET'])
def get_program_sessions(pid):
    conn = get_db()
    sessions = fetchall(conn, '''SELECT ps.*,
        (SELECT COUNT(*) FROM program_registrations
         WHERE program_id=%s AND session_ids LIKE '%%"' || ps.id || '"%%'
         AND status NOT IN ('cancelled','waitlisted')) AS enrolled_count
        FROM program_sessions ps WHERE ps.program_id=%s
        ORDER BY ps.sort_order, ps.day_of_week, ps.start_time''', (pid, pid))
    conn.close()
    return jsonify(sessions or [])


@app.route('/api/programs/<pid>/sessions/generate', methods=['POST'])
def generate_program_sessions(pid):
    """Generate multiple time slots at once for booking mode."""
    err = require_permission('programs')
    if err: return err
    import uuid as _usg
    import datetime as _dt
    d = request.json or {}
    conn = get_db()
    prog = fetchone(conn, 'SELECT id FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404

    start_date = d.get('start_date')
    end_date = d.get('end_date')
    days_of_week = d.get('days_of_week') or []  # e.g. ['Monday', 'Wednesday']
    open_time = d.get('open_time')    # e.g. '10:00'
    close_time = d.get('close_time')  # e.g. '16:00'
    slot_duration = int(d.get('slot_duration_minutes') or 45)
    gap_minutes = int(d.get('gap_minutes') or 0)
    capacity = int(d.get('capacity') or 1)
    price_override = d.get('price_override')
    location = (d.get('location') or '').strip()

    if not start_date or not open_time or not close_time:
        conn.close()
        return jsonify({'error': 'start_date, open_time and close_time are required'}), 400

    DAY_MAP = {'Monday':0,'Tuesday':1,'Wednesday':2,'Thursday':3,'Friday':4,'Saturday':5,'Sunday':6}
    allowed_days = set(DAY_MAP[d] for d in days_of_week if d in DAY_MAP) if days_of_week else set(range(7))

    try:
        cur = _dt.date.fromisoformat(start_date)
        end = _dt.date.fromisoformat(end_date) if end_date else cur
        ot = _dt.time.fromisoformat(open_time)
        ct = _dt.time.fromisoformat(close_time)
    except Exception as e:
        conn.close()
        return jsonify({'error': f'Invalid date/time: {e}'}), 400

    slot_td = _dt.timedelta(minutes=slot_duration)
    gap_td = _dt.timedelta(minutes=gap_minutes)
    created = 0
    sort_order = 0

    while cur <= end:
        if cur.weekday() in allowed_days:
            day_name = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][cur.weekday()]
            slot_start = _dt.datetime.combine(cur, ot)
            slot_end_limit = _dt.datetime.combine(cur, ct)
            while slot_start + slot_td <= slot_end_limit:
                s_end = slot_start + slot_td
                label = f'{cur.strftime("%A, %B %-d")} · {slot_start.strftime("%-I:%M %p")} – {s_end.strftime("%-I:%M %p")}'
                execute(conn, '''INSERT INTO program_sessions
                    (id, program_id, name, day_of_week, start_time, end_time,
                     start_date, end_date, location, capacity, price_override, status, sort_order)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s)''',
                    (str(_usg.uuid4()), pid, label, day_name,
                     slot_start.strftime('%H:%M'), s_end.strftime('%H:%M'),
                     cur.isoformat(), cur.isoformat(),
                     location or None,
                     capacity,
                     int(price_override) if price_override is not None else None,
                     sort_order))
                sort_order += 1
                created += 1
                slot_start = s_end + gap_td
        cur += _dt.timedelta(days=1)

    conn.commit(); conn.close()
    return jsonify({'ok': True, 'created': created})



    err = require_permission('programs')
    if err: return err
    import uuid as _us
    d = request.json or {}
    sid = _us.uuid4().hex
    conn = get_db()
    execute(conn, '''INSERT INTO program_sessions
        (id, program_id, name, day_of_week, start_time, end_time,
         start_date, end_date, location, capacity, price_override, status, sort_order)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (sid, pid,
         (d.get('name') or '').strip(),
         (d.get('day_of_week') or '').strip(),
         (d.get('start_time') or '').strip(),
         (d.get('end_time') or '').strip(),
         (d.get('start_date') or '').strip(),
         (d.get('end_date') or '').strip(),
         (d.get('location') or '').strip(),
         d.get('capacity') or None,
         d.get('price_override') if d.get('price_override') is not None else None,
         d.get('status') or 'open',
         int(d.get('sort_order') or 0)))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': sid})


@app.route('/api/programs/<pid>/sessions/<sid>', methods=['PUT'])
def update_program_session(pid, sid):
    err = require_permission('programs')
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE program_sessions SET
        name=%s, day_of_week=%s, start_time=%s, end_time=%s,
        start_date=%s, end_date=%s, location=%s,
        capacity=%s, price_override=%s, status=%s, sort_order=%s
        WHERE id=%s AND program_id=%s''',
        ((d.get('name') or '').strip(),
         (d.get('day_of_week') or '').strip(),
         (d.get('start_time') or '').strip(),
         (d.get('end_time') or '').strip(),
         (d.get('start_date') or '').strip(),
         (d.get('end_date') or '').strip(),
         (d.get('location') or '').strip(),
         d.get('capacity') or None,
         d.get('price_override') if d.get('price_override') is not None else None,
         d.get('status') or 'open',
         int(d.get('sort_order') or 0),
         sid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/programs/<pid>/sessions/<sid>', methods=['DELETE'])
def delete_program_session(pid, sid):
    err = require_permission('programs')
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM program_sessions WHERE id=%s AND program_id=%s', (sid, pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/public/program/<slug>/sessions', methods=['GET'])
def public_program_sessions(slug):
    conn = get_db()
    prog = fetchone(conn, "SELECT id FROM youth_programs WHERE slug=%s OR id=%s", (slug, slug))
    if not prog:
        conn.close()
        return jsonify([])
    sessions = fetchall(conn, '''SELECT ps.id, ps.name, ps.day_of_week, ps.start_time,
        ps.end_time, ps.start_date, ps.end_date, ps.location, ps.capacity,
        ps.price_override, ps.status, ps.sort_order,
        (SELECT COUNT(*) FROM program_registrations
         WHERE program_id=%s AND session_ids LIKE '%%"' || ps.id || '"%%'
         AND status NOT IN ('cancelled','waitlisted')) AS enrolled_count
        FROM program_sessions ps WHERE ps.program_id=%s AND (ps.status IS NULL OR ps.status NOT IN ('closed','cancelled'))
        ORDER BY ps.sort_order, ps.day_of_week, ps.start_time''', (prog['id'], prog['id']))
    conn.close()
    return jsonify(sessions or [])


@app.route('/api/admin/run-migrations', methods=['POST'])
def run_migrations_manual():
    err = require_auth()
    if err: return err
    conn = get_db()
    results = []
    migrations = [
        "ALTER TABLE audition_settings ADD COLUMN IF NOT EXISTS allow_slots BOOLEAN DEFAULT FALSE",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS rental_approver_emails TEXT DEFAULT ''",
        "ALTER TABLE email_settings ADD COLUMN IF NOT EXISTS rental_approval_levels TEXT DEFAULT '[]'",
        "ALTER TABLE rental_requests ADD COLUMN IF NOT EXISTS approval_level INTEGER DEFAULT 0",
        "ALTER TABLE rental_requests ADD COLUMN IF NOT EXISTS approval_history TEXT DEFAULT '[]'",
        "ALTER TABLE rental_requests ADD COLUMN IF NOT EXISTS denial_reason TEXT DEFAULT ''",
        "ALTER TABLE audition_slots ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'open'",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS slot_id TEXT",
        "ALTER TABLE audition_submissions ADD COLUMN IF NOT EXISTS audition_type TEXT DEFAULT 'virtual'",
        "UPDATE audition_settings SET context_type='production' WHERE context_type IS NULL",
    ]
    for m in migrations:
        try:
            execute(conn, m)
            results.append({'sql': m[:60], 'ok': True})
        except Exception as e:
            results.append({'sql': m[:60], 'error': str(e)})
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'results': results})




@app.route('/api/my/time', methods=['GET'])
def my_time():
    err = require_auth()
    if err: return err
    conn = get_db()
    # Find volunteer record by matching user email
    user = fetchone(conn, 'SELECT * FROM users WHERE id=%s', (session['user_id'],))
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE LOWER(email)=LOWER(%s)', (user['email'],)) if user else None
    if not vol:
        conn.close()
        return jsonify({'volunteer': None, 'hours': [], 'pending': [], 'events': [], 'board_attendance': []})

    # Approved hours
    approved = fetchall(conn, '''SELECT h.*, e.name AS event_name
        FROM hours h LEFT JOIN events e ON e.id=h.event_id
        WHERE h.volunteer_id=%s ORDER BY h.date DESC''', (vol['id'],)) or []

    # Pending hours
    pending = fetchall(conn, '''SELECT ph.*, e.name AS event_name
        FROM pending_hours ph LEFT JOIN events e ON e.id=ph.event_id
        WHERE ph.volunteer_id=%s ORDER BY ph.submitted_at DESC''', (vol['id'],)) or []

    # Events this volunteer can log hours for
    events = fetchall(conn, '''SELECT e.id, e.name, e.event_date
        FROM events e ORDER BY e.event_date DESC LIMIT 50''') or []

    # Board attendance if board member
    board_member = fetchone(conn, 'SELECT bm.* FROM board_members bm JOIN volunteers v ON v.id=bm.volunteer_id WHERE v.id=%s', (vol['id'],))
    board_attendance = []
    if board_member:
        board_attendance = fetchall(conn, '''SELECT bm.meeting_date, bm.meeting_time, bm.location,
            bma.attendance_type
            FROM board_meetings bm
            LEFT JOIN board_meeting_attendance bma ON bma.meeting_id=bm.id AND bma.member_id=%s
            WHERE bm.meeting_date <= CURRENT_DATE::TEXT
            ORDER BY bm.meeting_date DESC LIMIT 24''', (board_member['id'],)) or []

    # Summary stats
    total_approved = sum(float(h.get('hours') or 0) for h in approved)
    total_pending = sum(float(h.get('hours') or 0) for h in pending)
    import datetime as _dt
    this_year = str(_dt.date.today().year)
    ytd = sum(float(h.get('hours') or 0) for h in approved if (h.get('date') or '').startswith(this_year))

    conn.close()
    return jsonify({
        'volunteer': vol,
        'hours': approved,
        'pending': pending,
        'events': events,
        'board_attendance': board_attendance,
        'is_board': bool(board_member),
        'stats': {'total': total_approved, 'pending': total_pending, 'ytd': ytd}
    })


@app.route('/api/my/hours/submit', methods=['POST'])
def my_submit_hours():
    err = require_auth()
    if err: return err
    import uuid as _umh
    d = request.json or {}
    conn = get_db()
    user = fetchone(conn, 'SELECT * FROM users WHERE id=%s', (session['user_id'],))
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE LOWER(email)=LOWER(%s)', (user['email'],)) if user else None
    if not vol:
        conn.close()
        return jsonify({'error': 'No volunteer profile linked to your account. Please contact an admin.'}), 400
    if not d.get('hours') or float(d.get('hours') or 0) <= 0:
        conn.close()
        return jsonify({'error': 'Hours must be greater than 0'}), 400
    hid = str(_umh.uuid4())
    execute(conn, '''INSERT INTO pending_hours (id, volunteer_id, event, event_id, date, hours, role, notes, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')''',
        (hid, vol['id'],
         (d.get('event') or '').strip(),
         d.get('event_id') or None,
         (d.get('date') or '').strip(),
         float(d.get('hours') or 0),
         (d.get('role') or '').strip() or None,
         (d.get('notes') or '').strip() or None))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': hid})


@app.route('/api/my/hours/<hid>', methods=['DELETE'])
def my_delete_pending_hours(hid):
    err = require_auth()
    if err: return err
    conn = get_db()
    user = fetchone(conn, 'SELECT * FROM users WHERE id=%s', (session['user_id'],))
    vol = fetchone(conn, 'SELECT * FROM volunteers WHERE LOWER(email)=LOWER(%s)', (user['email'],)) if user else None
    if not vol:
        conn.close()
        return jsonify({'error': 'No volunteer profile found'}), 400
    execute(conn, "DELETE FROM pending_hours WHERE id=%s AND volunteer_id=%s AND status='pending'", (hid, vol['id']))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── End My Time & Attendance ───────────────────────────────────────────────────

# ── Venue Rentals ─────────────────────────────────────────────────────────────

@app.route('/api/rental/spaces', methods=['GET'])
def get_rental_spaces():
    err = require_permission('rentals', 'view')
    if err: return err
    conn = get_db()
    spaces = fetchall(conn, 'SELECT * FROM rental_spaces ORDER BY sort_order, name') or []
    conn.close()
    return jsonify(spaces)

@app.route('/api/rental/spaces', methods=['POST'])
def create_rental_space():
    err = require_auth()
    if err: return err
    import uuid as _urs
    d = request.json or {}
    conn = get_db()
    sid = str(_urs.uuid4())
    execute(conn, '''INSERT INTO rental_spaces (id, name, description, capacity, amenities, sort_order, active)
        VALUES (%s,%s,%s,%s,%s,%s,TRUE)''',
        (sid, (d.get('name') or '').strip(),
         (d.get('description') or '').strip(),
         d.get('capacity') or None,
         (d.get('amenities') or '').strip(),
         int(d.get('sort_order') or 0)))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': sid})

@app.route('/api/rental/spaces/<sid>', methods=['PUT'])
def update_rental_space(sid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE rental_spaces SET name=%s, description=%s, capacity=%s,
        amenities=%s, sort_order=%s, active=%s WHERE id=%s''',
        ((d.get('name') or '').strip(), (d.get('description') or '').strip(),
         d.get('capacity') or None, (d.get('amenities') or '').strip(),
         int(d.get('sort_order') or 0), bool(d.get('active', True)), sid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/spaces/<sid>', methods=['DELETE'])
def delete_rental_space(sid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM rental_spaces WHERE id=%s', (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/partners', methods=['GET'])
def get_rental_partners():
    err = require_auth()
    if err: return err
    conn = get_db()
    partners = fetchall(conn, 'SELECT * FROM rental_partners ORDER BY name') or []
    conn.close()
    return jsonify(partners)

@app.route('/api/rental/partners', methods=['POST'])
def create_rental_partner():
    err = require_auth()
    if err: return err
    import uuid as _urp
    d = request.json or {}
    conn = get_db()
    pid = str(_urp.uuid4())
    execute(conn, '''INSERT INTO rental_partners
        (id, name, contact_name, contact_email, contact_phone, organization_type, notes, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'active')''',
        (pid, (d.get('name') or '').strip(),
         (d.get('contact_name') or '').strip(),
         (d.get('contact_email') or '').strip(),
         (d.get('contact_phone') or '').strip(),
         (d.get('organization_type') or '').strip(),
         (d.get('notes') or '').strip()))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': pid})

@app.route('/api/rental/partners/<pid>', methods=['PUT'])
def update_rental_partner(pid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE rental_partners SET name=%s, contact_name=%s, contact_email=%s,
        contact_phone=%s, organization_type=%s, notes=%s, status=%s, updated_at=NOW() WHERE id=%s''',
        ((d.get('name') or '').strip(), (d.get('contact_name') or '').strip(),
         (d.get('contact_email') or '').strip(), (d.get('contact_phone') or '').strip(),
         (d.get('organization_type') or '').strip(), (d.get('notes') or '').strip(),
         d.get('status') or 'active', pid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/requests', methods=['GET'])
def get_rental_requests():
    err = require_permission('rentals', 'view')
    if err: return err
    conn = get_db()
    # Ensure new columns exist
    for col_def in [
        "approval_level INTEGER DEFAULT 0",
        "approval_history TEXT DEFAULT '[]'",
        "denial_reason TEXT DEFAULT ''"
    ]:
        try:
            execute(conn, f'ALTER TABLE rental_requests ADD COLUMN IF NOT EXISTS {col_def}')
            conn.commit()
        except Exception:
            pass
    requests_data = fetchall(conn, '''SELECT rr.*, rp.name AS partner_name,
        rp.contact_email AS partner_email, rp.contact_name AS partner_contact,
        rs.name AS space_name,
        ra.id AS agreement_id, ra.status AS agreement_status,
        ra.partner_signed_at, ra.signing_token,
        COALESCE(rr.approval_level, 0) AS approval_level,
        COALESCE(rr.approval_history, '[]') AS approval_history,
        COALESCE(rr.denial_reason, '') AS denial_reason
        FROM rental_requests rr
        LEFT JOIN rental_partners rp ON rp.id=rr.partner_id
        LEFT JOIN rental_spaces rs ON rs.id=rr.space_id
        LEFT JOIN rental_agreements ra ON ra.request_id=rr.id
        ORDER BY rr.start_date DESC, rr.created_at DESC''') or []
    conn.close()
    return jsonify(requests_data)

@app.route('/api/rental/requests', methods=['POST'])
def create_rental_request():
    err = require_permission('rentals')
    if err: return err
    import uuid as _urr
    d = request.json or {}
    conn = get_db()
    rid = str(_urr.uuid4())
    execute(conn, '''INSERT INTO rental_requests
        (id, partner_id, space_id, title, purpose, start_date, end_date,
         start_time, end_time, recurring, recurrence_pattern, recurrence_end_date,
         estimated_attendance, rate_type, rate_amount, total_amount, status, notes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)''',
        (rid, d.get('partner_id') or None, d.get('space_id') or None,
         (d.get('title') or '').strip(),
         (d.get('purpose') or '').strip(),
         (d.get('start_date') or '').strip(),
         (d.get('end_date') or '').strip(),
         (d.get('start_time') or '').strip(),
         (d.get('end_time') or '').strip(),
         bool(d.get('recurring')),
         (d.get('recurrence_pattern') or '').strip(),
         (d.get('recurrence_end_date') or '').strip(),
         d.get('estimated_attendance') or None,
         d.get('rate_type') or 'hourly',
         int(d.get('rate_amount') or 0),
         int(d.get('total_amount') or 0),
         (d.get('notes') or '').strip()))
    # Generate occurrences if recurring
    if d.get('recurring') and d.get('start_date') and d.get('recurrence_end_date'):
        _generate_rental_occurrences(conn, rid, d)
    conn.commit()
    # Send approval notification — use Level 1 emails from approval_levels, fallback to rental_approver_emails
    try:
        import json as _jen
        es = fetchone(conn, 'SELECT rental_approver_emails, rental_approval_levels FROM email_settings WHERE id=1') or {}
        approver_emails = []
        # Try Level 1 from approval levels first
        try:
            levels = _jen.loads(es.get('rental_approval_levels') or '[]')
            if levels and levels[0].get('emails'):
                approver_emails = [e.strip() for e in levels[0]['emails'].replace(',','\n').splitlines() if e.strip()]
        except Exception:
            pass
        # Fall back to flat approver list
        if not approver_emails:
            raw = (es.get('rental_approver_emails') or '').strip()
            approver_emails = [e.strip() for e in raw.replace(',','\n').splitlines() if e.strip()]
        subject = f'New Rental Request Pending Approval: {d.get("title","")}'
        body = f'A new venue rental request has been submitted and requires approval.<br><br><strong>Title:</strong> {d.get("title","")}<br><strong>Start:</strong> {d.get("start_date","")}<br><strong>Purpose:</strong> {d.get("purpose","")}<br><br>Please log in to RoleCall → Venue Rentals to review and approve.'
        for email_addr in approver_emails:
            try:
                send_email(email_addr, subject, body)
            except Exception as email_err:
                app.logger.warning(f'Rental approver email to {email_addr} failed: {email_err}')
        if not approver_emails:
            app.logger.warning('Rental request created but no approver emails configured — check Settings → Email Settings → Venue Rental Approvals')
    except Exception as e:
        app.logger.warning(f'Rental approval notification error: {e}')
    conn.close()
    return jsonify({'ok': True, 'id': rid})

def _generate_rental_occurrences(conn, request_id, d):
    import uuid as _uro2
    import datetime as _dto2
    pattern = d.get('recurrence_pattern') or 'weekly'
    try:
        cur = _dto2.date.fromisoformat(d.get('start_date'))
        end = _dto2.date.fromisoformat(d.get('recurrence_end_date'))
    except Exception:
        return
    while cur <= end:
        execute(conn, '''INSERT INTO rental_occurrences
            (id, request_id, occurrence_date, start_time, end_time, status)
            VALUES (%s,%s,%s,%s,%s,'scheduled')''',
            (str(_uro2.uuid4()), request_id, cur.isoformat(),
             d.get('start_time',''), d.get('end_time','')))
        if pattern == 'weekly':
            cur += _dto2.timedelta(days=7)
        elif pattern == 'biweekly':
            cur += _dto2.timedelta(days=14)
        elif pattern == 'monthly':
            # Same day next month
            month = cur.month + 1 if cur.month < 12 else 1
            year = cur.year + (1 if cur.month == 12 else 0)
            try: cur = cur.replace(year=year, month=month)
            except Exception: break
        elif pattern == 'daily':
            cur += _dto2.timedelta(days=1)
        else:
            break

@app.route('/api/rental/requests/<rid>', methods=['PUT'])
def update_rental_request(rid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE rental_requests SET partner_id=%s, space_id=%s, title=%s,
        purpose=%s, start_date=%s, end_date=%s, start_time=%s, end_time=%s,
        recurring=%s, recurrence_pattern=%s, recurrence_end_date=%s,
        estimated_attendance=%s, rate_type=%s, rate_amount=%s, total_amount=%s,
        status=%s, notes=%s, updated_at=NOW() WHERE id=%s''',
        (d.get('partner_id') or None, d.get('space_id') or None,
         (d.get('title') or '').strip(), (d.get('purpose') or '').strip(),
         (d.get('start_date') or '').strip(), (d.get('end_date') or '').strip(),
         (d.get('start_time') or '').strip(), (d.get('end_time') or '').strip(),
         bool(d.get('recurring')), (d.get('recurrence_pattern') or '').strip(),
         (d.get('recurrence_end_date') or '').strip(),
         d.get('estimated_attendance') or None,
         d.get('rate_type') or 'hourly',
         int(d.get('rate_amount') or 0), int(d.get('total_amount') or 0),
         d.get('status') or 'pending', (d.get('notes') or '').strip(), rid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/requests/<rid>/approve', methods=['POST'])
def approve_rental_request(rid):
    err = require_auth()
    if err: return err
    import json as _jra
    import datetime as _dtra
    d = request.json or {}
    conn = get_db()
    user = fetchone(conn, 'SELECT name, email FROM users WHERE id=%s', (session['user_id'],))
    req = fetchone(conn, 'SELECT * FROM rental_requests WHERE id=%s', (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    # Load approval levels config
    es = fetchone(conn, 'SELECT rental_approval_levels FROM email_settings WHERE id=1') or {}
    try:
        levels = _jra.loads(es.get('rental_approval_levels') or '[]')
    except Exception:
        levels = []
    # Load current approval history
    try:
        history = _jra.loads(req.get('approval_history') or '[]')
    except Exception:
        history = []
    current_level = int(req.get('approval_level') or 0)
    next_level = current_level + 1
    approver_name = (user or {}).get('name', 'Admin')
    approver_email = (user or {}).get('email', '')
    # Add to history
    history.append({
        'level': next_level,
        'approved_by': approver_name,
        'approved_by_email': approver_email,
        'approved_at': _dtra.datetime.now().isoformat(),
        'notes': (d.get('notes') or '').strip()
    })
    # Check if all levels complete
    total_levels = len(levels) if levels else 1
    fully_approved = next_level >= total_levels
    new_status = 'approved' if fully_approved else 'pending'
    execute(conn, '''UPDATE rental_requests SET
        approval_level=%s, approval_history=%s, status=%s,
        approved_by=%s, approved_at=NOW(), updated_at=NOW() WHERE id=%s''',
        (next_level, _jra.dumps(history), new_status,
         approver_name, rid))
    # Notify next level approvers if not fully approved
    if not fully_approved and levels and next_level < len(levels):
        next_level_config = levels[next_level]
        emails_raw = (next_level_config.get('emails') or '').strip()
        emails = [e.strip() for e in emails_raw.replace(',', '\n').splitlines() if e.strip()]
        for em in emails:
            try:
                send_email(em,
                    f'Rental Request Needs Your Approval (Level {next_level+1}): {req.get("title","")}',
                    f'{approver_name} has approved this request at Level {next_level}.<br><br>Title: {req.get("title","")}<br><br>Please log in to RoleCall to review and approve at Level {next_level+1}: {next_level_config.get("label","")}.')
            except Exception: pass
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'fully_approved': fully_approved, 'level': next_level})


@app.route('/api/rental/requests/<rid>/deny', methods=['POST'])
def deny_rental_request(rid):
    err = require_auth()
    if err: return err
    import json as _jrd
    import datetime as _dtrd
    d = request.json or {}
    reason = (d.get('reason') or '').strip()
    conn = get_db()
    user = fetchone(conn, 'SELECT name FROM users WHERE id=%s', (session['user_id'],))
    req = fetchone(conn, 'SELECT * FROM rental_requests WHERE id=%s', (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    try:
        history = _jrd.loads(req.get('approval_history') or '[]')
    except Exception:
        history = []
    history.append({
        'action': 'denied',
        'by': (user or {}).get('name', 'Admin'),
        'at': _dtrd.datetime.now().isoformat(),
        'reason': reason
    })
    execute(conn, '''UPDATE rental_requests SET status='denied', denial_reason=%s,
        approval_history=%s, updated_at=NOW() WHERE id=%s''',
        (reason, _jrd.dumps(history), rid))
    # Notify partner if we have their email
    partner = fetchone(conn, '''SELECT rp.contact_email, rp.contact_name, rp.name AS pname
        FROM rental_requests rr JOIN rental_partners rp ON rp.id=rr.partner_id
        WHERE rr.id=%s''', (rid,))
    if partner and partner.get('contact_email'):
        try:
            send_email(partner['contact_email'],
                f'Rental Request Update: {req.get("title","")}',
                f'Dear {partner.get("contact_name") or partner.get("pname","")},<br><br>We regret to inform you that your venue rental request "{req.get("title","")}" has not been approved at this time.<br><br>{("Reason: "+reason) if reason else ""}<br><br>Please contact us if you have questions.<br><br>Horizon West Theatre Company')
        except Exception: pass
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/rental/requests/<rid>/sendback', methods=['POST'])
def sendback_rental_request(rid):
    err = require_auth()
    if err: return err
    import json as _jrsb
    import datetime as _dtrsb
    d = request.json or {}
    reason = (d.get('reason') or '').strip()
    conn = get_db()
    user = fetchone(conn, 'SELECT name FROM users WHERE id=%s', (session['user_id'],))
    req = fetchone(conn, 'SELECT * FROM rental_requests WHERE id=%s', (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    try:
        history = _jrsb.loads(req.get('approval_history') or '[]')
    except Exception:
        history = []
    history.append({
        'action': 'sent_back',
        'by': (user or {}).get('name', 'Admin'),
        'at': _dtrsb.datetime.now().isoformat(),
        'reason': reason
    })
    execute(conn, '''UPDATE rental_requests SET status='pending', approval_level=0,
        denial_reason=%s, approval_history=%s, updated_at=NOW() WHERE id=%s''',
        (reason, _jrsb.dumps(history), rid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/rental/requests/<rid>', methods=['DELETE'])
def delete_rental_request(rid):
    err = require_auth()
    if err: return err
    conn = get_db()
    execute(conn, 'DELETE FROM rental_agreements WHERE request_id=%s', (rid,))
    execute(conn, 'DELETE FROM rental_occurrences WHERE request_id=%s', (rid,))
    execute(conn, 'DELETE FROM rental_requests WHERE id=%s', (rid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/requests/<rid>/generate-contract', methods=['POST'])
def generate_rental_contract(rid):
    err = require_auth()
    if err: return err
    import uuid as _urgc
    import secrets as _sec
    d = request.json or {}
    conn = get_db()
    req = fetchone(conn, '''SELECT rr.*, rp.name AS partner_name,
        rp.contact_name, rp.contact_email, rp.contact_phone,
        rp.organization_type, rs.name AS space_name, rs.amenities
        FROM rental_requests rr
        LEFT JOIN rental_partners rp ON rp.id=rr.partner_id
        LEFT JOIN rental_spaces rs ON rs.id=rr.space_id
        WHERE rr.id=%s''', (rid,))
    if not req:
        conn.close()
        return jsonify({'error': 'Request not found'}), 404
    token = _sec.token_urlsafe(32)
    custom_terms = (d.get('custom_terms') or '').strip()
    contract_html = _build_rental_contract_html(req, custom_terms)
    # Delete any existing draft agreement
    execute(conn, "DELETE FROM rental_agreements WHERE request_id=%s AND status='draft'", (rid,))
    aid = str(_urgc.uuid4())
    execute(conn, '''INSERT INTO rental_agreements
        (id, request_id, contract_html, signing_token, status)
        VALUES (%s,%s,%s,%s,'draft')''',
        (aid, rid, contract_html, token))
    conn.commit(); conn.close()
    signing_url = f'https://rolecall.hwtco.org/rent/sign/{token}'
    return jsonify({'ok': True, 'id': aid, 'token': token, 'signing_url': signing_url})

def _build_rental_contract_html(req, custom_terms=''):
    import datetime as _dtc
    today = _dtc.date.today().strftime('%B %d, %Y')
    rate_type = req.get('rate_type','hourly')
    rate_cents = int(req.get('rate_amount') or 0)
    rate_str = f'${rate_cents/100:.2f} per {rate_type.replace("_"," ")}'
    total_cents = int(req.get('total_amount') or 0)
    total_str = f'${total_cents/100:.2f}' if total_cents else 'To be invoiced'
    start = req.get('start_date','')
    end = req.get('end_date','')
    date_range = start + (' through ' + end if end and end != start else '')
    time_range = (req.get('start_time','') + (' – ' + req.get('end_time','') if req.get('end_time') else '')) if req.get('start_time') else 'As scheduled'
    default_terms = f'''
<h2 style="color:#0d3d4d;margin-top:24px">VENUE RENTAL AGREEMENT</h2>
<p>This Venue Rental Agreement ("Agreement") is entered into as of <strong>{today}</strong> by and between:</p>
<p><strong>Horizon West Theatre Company</strong> ("HWTC"), a nonprofit performing arts organization located in Winter Garden, FL</p>
<p>and</p>
<p><strong>{req.get('partner_name','')}</strong> ("{req.get('organization_type','Partner')}"), hereinafter referred to as "Renter."</p>

<h3 style="color:#0d3d4d;margin-top:20px">1. RENTAL DETAILS</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:16px">
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc;width:35%">Space</td><td style="padding:6px 10px;border:1px solid #e5e7eb">{req.get('space_name','')}</td></tr>
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc">Date(s)</td><td style="padding:6px 10px;border:1px solid #e5e7eb">{date_range}</td></tr>
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc">Time</td><td style="padding:6px 10px;border:1px solid #e5e7eb">{time_range}</td></tr>
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc">Purpose</td><td style="padding:6px 10px;border:1px solid #e5e7eb">{req.get('purpose','')}</td></tr>
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc">Rate</td><td style="padding:6px 10px;border:1px solid #e5e7eb">{rate_str}</td></tr>
<tr><td style="padding:6px 10px;border:1px solid #e5e7eb;font-weight:700;background:#f8fafc">Total</td><td style="padding:6px 10px;border:1px solid #e5e7eb"><strong>{total_str}</strong></td></tr>
</table>

<h3 style="color:#0d3d4d;margin-top:20px">2. TERMS AND CONDITIONS</h3>
<p><strong>2.1 Payment.</strong> Renter agrees to pay the rental fee as specified above. Payment is due no later than 48 hours prior to the rental date unless otherwise agreed in writing.</p>
<p><strong>2.2 Cancellation.</strong> Cancellations made more than 14 days in advance will receive a full refund. Cancellations within 14 days will forfeit 50% of the rental fee. Cancellations within 48 hours will forfeit the full rental fee.</p>
<p><strong>2.3 Use of Space.</strong> Renter agrees to use the space only for the purpose described above. Renter shall not sublet the space or allow unauthorized parties to use it.</p>
<p><strong>2.4 Care of Facility.</strong> Renter agrees to leave the space in the same condition as found. Renter is responsible for any damage to the facility, equipment, or property caused by Renter or Renter's guests. Renter will be charged for any repairs or cleaning required beyond normal use.</p>
<p><strong>2.5 Capacity.</strong> Renter agrees to not exceed the posted occupancy limits of the space.</p>
<p><strong>2.6 Alcohol &amp; Conduct.</strong> Alcohol is not permitted without prior written approval from HWTC. Renter is responsible for ensuring all guests behave in a respectful manner. HWTC reserves the right to terminate the rental immediately if this clause is violated, with no refund.</p>
<p><strong>2.7 Equipment.</strong> Use of HWTC equipment (lighting, sound, etc.) must be agreed upon in advance and may incur additional fees. Renter shall not move or modify technical equipment without authorization.</p>
<p><strong>2.8 Insurance.</strong> HWTC strongly recommends Renter carry liability insurance for their event. HWTC assumes no liability for injuries or property damage occurring during the rental period.</p>
<p><strong>2.9 Indemnification.</strong> Renter agrees to indemnify and hold harmless HWTC, its officers, directors, volunteers, and agents from any claims, damages, or expenses arising from Renter's use of the facility.</p>
<p><strong>2.10 Compliance.</strong> Renter agrees to comply with all applicable laws, ordinances, and fire codes during use of the facility.</p>
<p><strong>2.11 Recording &amp; Photography.</strong> Renter may not record, photograph, or livestream HWTC proprietary content, costumes, or set pieces without written permission.</p>
'''
    if custom_terms:
        default_terms += f'\n<h3 style="color:#0d3d4d;margin-top:20px">3. ADDITIONAL TERMS</h3>\n<p>{custom_terms}</p>'

    default_terms += '''
<h3 style="color:#0d3d4d;margin-top:20px">4. SIGNATURES</h3>
<p>By signing below, both parties agree to the terms and conditions set forth in this Agreement.</p>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px">
<div style="border-top:2px solid #0d3d4d;padding-top:8px">
<div style="font-weight:700;font-size:14px">Horizon West Theatre Company</div>
<div style="font-size:13px;color:#6b7280;margin-top:4px">Authorized Representative</div>
<div style="margin-top:24px;border-bottom:1px solid #9ca3af;min-height:32px"></div>
<div style="font-size:12px;color:#6b7280;margin-top:4px">Signature &amp; Date</div>
</div>
<div id="partner-signature-block" style="border-top:2px solid #0d3d4d;padding-top:8px">
<div style="font-weight:700;font-size:14px">PARTNER_NAME_PLACEHOLDER</div>
<div style="font-size:13px;color:#6b7280;margin-top:4px">Authorized Representative</div>
<div style="margin-top:24px;border-bottom:1px solid #9ca3af;min-height:32px;background:#f0f9ff"></div>
<div style="font-size:12px;color:#6b7280;margin-top:4px">Digital signature will appear here upon signing</div>
</div>
</div>
'''
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:Georgia,serif;font-size:14px;line-height:1.6;color:#1a2332;max-width:800px;margin:0 auto;padding:40px}}
h2{{font-size:20px;border-bottom:2px solid #145466;padding-bottom:8px}}
h3{{font-size:15px;color:#145466}}p{{margin:0 0 12px}}</style></head>
<body>
<div style="text-align:center;margin-bottom:24px">
<img src="https://raw.githubusercontent.com/hwtcRaja/rolecall/main/static/images/hwtc_logo_teal.png" style="height:60px" alt="HWTC"/>
<div style="font-size:11px;color:#6b7280;margin-top:6px">horizonwesttheatre.com · Winter Garden, FL</div>
</div>
{default_terms}
</body></html>'''

@app.route('/api/rental/agreements/<aid>', methods=['GET'])
def get_rental_agreement(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    agr = fetchone(conn, 'SELECT * FROM rental_agreements WHERE id=%s', (aid,))
    conn.close()
    return jsonify(agr or {})


@app.route('/api/rental/agreements/<aid>/send', methods=['POST'])
def send_rental_agreement(aid):
    err = require_auth()
    if err: return err
    conn = get_db()
    agr = fetchone(conn, '''SELECT ra.*, rr.partner_id, rp.contact_email, rp.contact_name, rp.name AS partner_name, rr.title
        FROM rental_agreements ra
        JOIN rental_requests rr ON rr.id=ra.request_id
        LEFT JOIN rental_partners rp ON rp.id=rr.partner_id
        WHERE ra.id=%s''', (aid,))
    if not agr:
        conn.close()
        return jsonify({'error': 'Agreement not found'}), 404
    signing_url = f'https://rolecall.hwtco.org/rent/sign/{agr["signing_token"]}'
    email_to = agr.get('contact_email','')
    if email_to:
        subject = f'Venue Rental Agreement – {agr.get("title","")}'
        body = f'''Dear {agr.get("contact_name","") or agr.get("partner_name","")},

Please review and digitally sign your venue rental agreement with Horizon West Theatre Company.

Click the link below to review and sign:
{signing_url}

If you have any questions, please contact us.

Horizon West Theatre Company'''
        try:
            send_email(email_to, subject, body)
            execute(conn, "UPDATE rental_agreements SET status='sent', sent_at=NOW() WHERE id=%s", (aid,))
            conn.commit()
        except Exception as e:
            conn.close()
            return jsonify({'error': f'Email failed: {e}'}), 500
    conn.close()
    return jsonify({'ok': True, 'signing_url': signing_url})

@app.route('/rent/sign/<token>', methods=['GET'])
def rental_signing_page(token):
    conn = get_db()
    agr = fetchone(conn, '''SELECT ra.*, rr.title, rp.name AS partner_name
        FROM rental_agreements ra
        JOIN rental_requests rr ON rr.id=ra.request_id
        LEFT JOIN rental_partners rp ON rp.id=rr.partner_id
        WHERE ra.signing_token=%s''', (token,))
    conn.close()
    if not agr:
        return 'Agreement not found.', 404
    if agr.get('partner_signed_at'):
        return f'''<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{{font-family:sans-serif;text-align:center;padding:60px;color:#0d3d4d}}</style></head>
<body><h2>✓ Already Signed</h2><p>This agreement was signed on {agr["partner_signed_at"]}.</p><p>Thank you!</p></body></html>'''
    contract = agr.get('contract_html','')
    return f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign Rental Agreement – {agr.get("title","")}</title>
<style>
body{{font-family:Georgia,serif;font-size:14px;color:#1a2332;margin:0;padding:0;background:#f8fafc}}
.contract-wrap{{max-width:860px;margin:0 auto;background:#fff;padding:40px;box-shadow:0 2px 20px rgba(0,0,0,0.08)}}
.sign-bar{{position:sticky;bottom:0;background:#fff;border-top:2px solid #145466;padding:20px;max-width:860px;margin:0 auto;box-shadow:0 -4px 20px rgba(0,0,0,0.1)}}
.sign-btn{{background:#145466;color:#fff;border:none;padding:14px 32px;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;width:100%}}
.sign-btn:disabled{{background:#9ca3af;cursor:not-allowed}}
input[type=text]{{width:100%;padding:12px 14px;border:2px solid #d1d5db;border-radius:8px;font-size:16px;font-family:Georgia,serif;box-sizing:border-box}}
input[type=text]:focus{{border-color:#145466;outline:none}}
.signed-msg{{background:#dcfce7;color:#166534;padding:20px;border-radius:10px;text-align:center;font-size:18px;font-weight:700;margin-top:20px}}
</style></head><body>
<div class="contract-wrap">
{contract}
</div>
<div class="sign-bar">
<div style="max-width:500px;margin:0 auto">
<div style="font-size:13px;font-weight:700;color:#0d3d4d;margin-bottom:6px">Type your full name to sign this agreement</div>
<input type="text" id="sig-name" placeholder="Your full legal name" oninput="document.getElementById('sign-btn').disabled=this.value.trim().length<3"/>
<div id="sig-error" style="color:#dc2626;font-size:12px;margin-top:4px;display:none"></div>
<button class="sign-btn" id="sign-btn" style="margin-top:10px" disabled onclick="signAgreement()">Sign Agreement</button>
<div style="font-size:11px;color:#9ca3af;margin-top:8px;text-align:center">By clicking "Sign Agreement" you are providing a legally binding digital signature.</div>
</div>
</div>
<script>
async function signAgreement(){{
  const name = document.getElementById('sig-name').value.trim()
  if(name.length < 3){{ document.getElementById('sig-error').style.display=''; document.getElementById('sig-error').textContent='Please enter your full name'; return }}
  const btn = document.getElementById('sign-btn')
  btn.disabled=true; btn.textContent='Signing...'
  const res = await fetch('/rent/sign/{token}', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name}})}})
  const data = await res.json()
  if(data.ok){{
    document.querySelector('.sign-bar').innerHTML = '<div class="signed-msg" style="max-width:500px;margin:0 auto">✓ Agreement Signed!<div style="font-size:14px;font-weight:400;margin-top:4px">Thank you, '+name+'. A copy will be sent to you by email.</div></div>'
    window.scrollTo(0, document.body.scrollHeight)
  }} else {{
    btn.disabled=false; btn.textContent='Sign Agreement'
    document.getElementById('sig-error').style.display=''
    document.getElementById('sig-error').textContent = data.error||'An error occurred. Please try again.'
  }}
}}
</script></body></html>'''

@app.route('/rent/sign/<token>', methods=['POST'])
def submit_rental_signature(token):
    d = request.json or {}
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    conn = get_db()
    agr = fetchone(conn, 'SELECT * FROM rental_agreements WHERE signing_token=%s', (token,))
    if not agr:
        conn.close()
        return jsonify({'error': 'Agreement not found'}), 404
    if agr.get('partner_signed_at'):
        conn.close()
        return jsonify({'error': 'Already signed'}), 400
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    execute(conn, '''UPDATE rental_agreements SET partner_signed_name=%s,
        partner_signed_at=NOW(), partner_signed_ip=%s, status='signed', updated_at=NOW()
        WHERE id=%s''', (name, ip, agr['id']))
    execute(conn, "UPDATE rental_requests SET status='signed', updated_at=NOW() WHERE id=%s",
        (agr['request_id'],))
    conn.commit()
    # Notify admin
    try:
        req = fetchone(conn, '''SELECT rr.title, rp.name AS partner_name FROM rental_requests rr
            LEFT JOIN rental_partners rp ON rp.id=rr.partner_id WHERE rr.id=%s''', (agr['request_id'],))
        admins = fetchall(conn, "SELECT email FROM users WHERE role='admin' AND email IS NOT NULL")
        for admin in (admins or []):
            send_email(admin['email'],
                f'Agreement Signed: {(req or {}).get("title","")}',
                f'{name} has signed the rental agreement for {(req or {}).get("title","")}.<br><br>Log in to RoleCall to view the signed agreement.')
    except Exception: pass
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/rental/occurrences/<request_id>', methods=['GET'])
def get_rental_occurrences(request_id):
    err = require_auth()
    if err: return err
    conn = get_db()
    occs = fetchall(conn, 'SELECT * FROM rental_occurrences WHERE request_id=%s ORDER BY occurrence_date', (request_id,)) or []
    conn.close()
    return jsonify(occs)

@app.route('/api/rental/occurrences/<oid>', methods=['PUT'])
def update_rental_occurrence(oid):
    err = require_auth()
    if err: return err
    d = request.json or {}
    conn = get_db()
    execute(conn, 'UPDATE rental_occurrences SET status=%s, notes=%s WHERE id=%s',
        (d.get('status','scheduled'), (d.get('notes') or '').strip(), oid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ── End Venue Rentals ─────────────────────────────────────────────────────────



@app.route('/api/marquee/orders/cart/<oid>', methods=['DELETE'])
def delete_cart_order(oid):
    err = require_permission('marquee')
    if err: return err
    conn = get_db()
    order = fetchone(conn, 'SELECT * FROM cart_orders WHERE id=%s', (oid,))
    if not order:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    import json as _jd
    try:
        items = _jd.loads(order.get('items_json') or '[]')
    except Exception:
        items = []
    for it in items:
        rid = it.get('registration_id')
        if rid:
            execute(conn, "UPDATE program_registrations SET status='cancelled' WHERE id=%s", (rid,))
    execute(conn, 'DELETE FROM cart_orders WHERE id=%s', (oid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/api/programs/<pid>/registrations/<rid>', methods=['DELETE'])
def delete_registration(pid, rid):
    err = require_permission('marquee')
    if err: return err
    conn = get_db()
    reg = fetchone(conn, 'SELECT id FROM program_registrations WHERE id=%s AND program_id=%s', (rid, pid))
    if not reg:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    execute(conn, 'DELETE FROM program_registrations WHERE id=%s', (rid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


# ── Program cover image upload ────────────────────────────────────────────────

def upload_image_to_github(filename, file_bytes):
    """Upload an image to GitHub repo and return the raw URL. Falls back to local if no token."""
    import base64 as _b64
    GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
    GITHUB_REPO = os.environ.get('GITHUB_REPO', 'hwtcRaja/rolecall')
    GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
    if not GITHUB_TOKEN:
        return None, 'No GITHUB_TOKEN set'
    path = f'static/images/{filename}'
    api_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{path}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
    }
    # Check if file already exists (need its SHA to update)
    sha = None
    try:
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            sha = r.json().get('sha')
    except Exception:
        pass
    payload = {
        'message': f'Upload cover image: {filename}',
        'content': _b64.b64encode(file_bytes).decode('utf-8'),
        'branch': GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha
    try:
        r = requests.put(api_url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            raw_url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}'
            return raw_url, None
        else:
            return None, f'GitHub API error {r.status_code}: {r.text[:200]}'
    except Exception as e:
        return None, str(e)


@app.route('/api/programs/<pid>/upload-cover', methods=['POST'])
def upload_program_cover(pid):
    err = require_permission('youth')
    if err: return err
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': 'Empty file'}), 400
    ext = os.path.splitext(secure_filename(f.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return jsonify({'error': 'Only JPG, PNG, GIF, or WEBP allowed'}), 400
    conn = get_db()
    prog = fetchone(conn, 'SELECT name, slug FROM youth_programs WHERE id=%s', (pid,))
    conn.close()
    if not prog:
        return jsonify({'error': 'Program not found'}), 404
    base = secure_filename((prog.get('slug') or prog.get('name') or pid).replace(' ', '-').lower())
    filename = f'program-{base}-cover{ext}'
    file_bytes = f.read()
    # Try GitHub first
    gh_url, gh_err = upload_image_to_github(filename, file_bytes)
    if gh_url:
        url = gh_url
    else:
        # Fallback to local filesystem
        app.logger.warning(f'GitHub upload failed ({gh_err}), saving locally')
        save_path = os.path.join(app.static_folder, 'images', filename)
        with open(save_path, 'wb') as fp: fp.write(file_bytes)
        url = f'/static/images/{filename}'
    import json as _ji
    conn2 = get_db()
    prog_full = fetchone(conn2, 'SELECT program_images FROM youth_programs WHERE id=%s', (pid,))
    try:
        images = _ji.loads(prog_full.get('program_images') or '[]')
    except Exception:
        images = []
    images = [url] + [img for img in images if img != url]
    execute(conn2, 'UPDATE youth_programs SET program_images=%s WHERE id=%s', (_ji.dumps(images), pid))
    conn2.commit(); conn2.close()
    return jsonify({'ok': True, 'url': url})


# ── Cart discount code admin routes ─────────────────────────────────────────

@app.route('/api/marquee/cart-discount-codes', methods=['GET'])
def get_cart_discount_codes():
    err = require_permission('marquee', 'view')
    if err: return err
    conn = get_db()
    codes = fetchall(conn, 'SELECT * FROM cart_discount_codes ORDER BY created_at DESC')
    conn.close()
    return jsonify(codes or [])


@app.route('/api/marquee/cart-discount-codes', methods=['POST'])
def create_cart_discount_code():
    err = require_permission('marquee')
    if err: return err
    import uuid as _ucc
    d = request.json or {}
    code = (d.get('code') or '').strip().upper()
    if not code:
        return jsonify({'error': 'Code required'}), 400
    conn = get_db()
    try:
        execute(conn, '''INSERT INTO cart_discount_codes
            (id, code, discount_type, discount_value, min_spend, max_uses, description, active)
            VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE)''',
            (_ucc.uuid4().hex, code,
             d.get('discount_type', 'percent'),
             int(d.get('discount_value') or 0),
             int(d.get('min_spend_cents') or 0),
             d.get('max_uses') or None,
             (d.get('description') or '').strip()))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/api/marquee/cart-discount-codes/<cid>', methods=['DELETE'])
def delete_cart_discount_code(cid):
    err = require_permission('marquee')
    if err: return err
    conn = get_db()
    execute(conn, 'UPDATE cart_discount_codes SET active=FALSE WHERE id=%s', (cid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Public donation page routes ──────────────────────────────────────────────

@app.route('/donate')
@app.route('/donate/confirmation')
def donate_page():
    return send_from_directory('static', 'donate.html')


@app.route('/api/public/donate', methods=['POST'])
def submit_donation():
    """Create a Square payment link for a public donation."""
    import uuid as _ud2
    d = request.json or {}
    name = (d.get('name') or '').strip()
    email = (d.get('email') or '').strip().lower()
    amount_dollars = float(d.get('amount') or 0)
    message = (d.get('message') or '').strip()
    if not name or not email:
        return jsonify({'error': 'Name and email are required'}), 400
    if amount_dollars < 1:
        return jsonify({'error': 'Minimum donation is $1.00'}), 400
    amount_cents = int(round(amount_dollars * 100))
    if not SQUARE_ACCESS_TOKEN or not SQUARE_LOCATION_ID:
        return jsonify({'error': 'Payment system not configured'}), 500
    pending_id = _ud2.uuid4().hex
    conn = get_db()
    execute(conn, '''INSERT INTO pending_donations (id, name, email, amount_cents, message)
        VALUES (%s,%s,%s,%s,%s)''', (pending_id, name, email, amount_cents, message or None))
    conn.commit()
    redirect_url = f'{APP_BASE_URL}/donate/confirmation?don={pending_id}'
    payload = {
        'idempotency_key': _ud2.uuid4().hex,
        'order': {
            'location_id': SQUARE_LOCATION_ID,
            'line_items': [{'name': 'Donation — Horizon West Theatre Company',
                            'quantity': '1',
                            'base_price_money': {'amount': amount_cents, 'currency': 'USD'}}],
            'reference_id': pending_id[:40],
        },
        'checkout_options': {'redirect_url': redirect_url, 'ask_for_shipping_address': False},
        'pre_populated_data': {'buyer_email': email},
        'description': f'Donation from {name}' + (f': {message[:100]}' if message else ''),
    }
    try:
        r = requests.post(f'{SQUARE_API_BASE}/v2/online-checkout/payment-links',
            json=payload, headers=square_headers(), timeout=15)
        data = r.json()
        if r.status_code == 200 and data.get('payment_link'):
            lnk = data['payment_link']
            execute(conn, 'UPDATE pending_donations SET square_order_id=%s, square_checkout_id=%s WHERE id=%s',
                (lnk.get('order_id'), lnk.get('id'), pending_id))
            conn.commit()
            conn.close()
            return jsonify({'ok': True, 'payment_url': lnk.get('url'), 'donation_id': pending_id})
        conn.close()
        return jsonify({'error': 'Could not create payment link. Please try again.'}), 500
    except Exception as e:
        conn.close()
        app.logger.error(f'Donation payment link error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/api/public/donation/<did>', methods=['GET'])
def get_donation_status(did):
    conn = get_db()
    don = fetchone(conn, 'SELECT id, status, name, amount_cents FROM pending_donations WHERE id=%s', (did,))
    conn.close()
    if not don:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(don)


# ── Marquee admin routes ─────────────────────────────────────────────────────

@app.route('/api/marquee/orders', methods=['GET'])
def marquee_orders():
    err = require_permission('marquee', 'view')
    if err: return err
    import json as _jo
    conn = get_db()
    # Cart orders (multi-program)
    cart_orders = fetchall(conn, '''SELECT id, guardian_name, guardian_email, guardian_phone,
        items_json, cart_discount_code, cart_discount_amount, total_cents, status, created_at,
        square_order_id
        FROM cart_orders ORDER BY created_at DESC LIMIT 100''')
    for o in (cart_orders or []):
        try: o['items'] = _jo.loads(o.get('items_json') or '[]')
        except: o['items'] = []
    # Single-program orders (have a square_order_id but not from cart_orders)
    cart_order_ids = set(o['square_order_id'] for o in (cart_orders or []) if o.get('square_order_id'))
    single_regs = fetchall(conn, '''SELECT pr.*,
        yp.name AS program_name,
        COALESCE(yp.price,0) AS program_price,
        (COALESCE(yp.price,0) * COALESCE(pr.participant_count,1)
         - COALESCE(pr.discount_amount,0)
         - COALESCE(pr.sibling_discount_amount,0)) AS amount_paid_cents
        FROM program_registrations pr
        JOIN youth_programs yp ON yp.id=pr.program_id
        WHERE pr.square_order_id IS NOT NULL
        AND pr.status != \'waitlisted\'
        ORDER BY pr.created_at DESC LIMIT 100''')
    # Filter out regs that belong to a cart order
    single_regs = [r for r in (single_regs or []) if r.get('square_order_id') not in cart_order_ids]
    conn.close()
    return jsonify({'cart_orders': cart_orders or [], 'single_registrations': single_regs or []})


@app.route('/api/marquee/orders/cart/<oid>', methods=['GET'])
def marquee_cart_order_detail(oid):
    err = require_permission('marquee', 'view')
    if err: return err
    import json as _jo2
    conn = get_db()
    order = fetchone(conn, 'SELECT * FROM cart_orders WHERE id=%s', (oid,))
    if not order:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    try: order['items'] = _jo2.loads(order.get('items_json') or '[]')
    except: order['items'] = []
    # Fetch registration status for each item
    for it in order['items']:
        rid = it.get('registration_id')
        if rid:
            reg = fetchone(conn, 'SELECT status, square_order_id, balance_due FROM program_registrations WHERE id=%s', (rid,))
            if reg:
                it['reg_status'] = reg['status']
                it['balance_due'] = reg.get('balance_due') or 0
    conn.close()
    return jsonify(order)


@app.route('/api/marquee/orders/single/<rid>', methods=['GET'])
def marquee_single_order_detail(rid):
    err = require_permission('marquee', 'view')
    if err: return err
    import json as _jo3
    conn = get_db()
    reg = fetchone(conn, '''SELECT pr.*, yp.name AS program_name, yp.registration_form_type
        FROM program_registrations pr
        JOIN youth_programs yp ON yp.id=pr.program_id
        WHERE pr.id=%s''', (rid,))
    conn.close()
    if not reg:
        return jsonify({'error': 'Not found'}), 404
    try: reg['siblings'] = _jo3.loads(reg.get('siblings_json') or '[]')
    except: reg['siblings'] = []
    return jsonify(reg)



@app.route('/api/marquee/overview', methods=['GET'])
def marquee_overview():
    err = require_permission('marquee', 'view')
    if err: return err
    conn = get_db()
    # Registration counts across programs and productions
    reg_counts = fetchone(conn, '''SELECT
        COUNT(*) FILTER (WHERE status='confirmed') AS confirmed,
        COUNT(*) FILTER (WHERE status='pending_payment') AS pending,
        COUNT(*) FILTER (WHERE status='waitlisted') AS waitlisted,
        COUNT(*) AS total
        FROM program_registrations WHERE status != 'cancelled' ''')
    # Revenue: cart orders + direct registrations
    cart_rev = fetchone(conn, "SELECT COALESCE(SUM(total_cents),0) AS total FROM cart_orders WHERE status='completed'")
    # Direct reg revenue = program price × participant_count - discount - balance_due still owed
    # Safest: use yp.price × participant_count for confirmed regs
    direct_rev = fetchone(conn, '''SELECT COALESCE(SUM(
        COALESCE(yp.price,0) * COALESCE(pr.participant_count,1)
        - COALESCE(pr.discount_amount,0)
        - COALESCE(pr.sibling_discount_amount,0)
    ),0) AS total
    FROM program_registrations pr
    LEFT JOIN youth_programs yp ON yp.id=pr.program_id
    WHERE pr.status=\'confirmed\' ''') or {}
    total_revenue = int((cart_rev or {}).get('total', 0)) + int((direct_rev or {}).get('total', 0))
    # Donations this year
    import datetime as _dt
    year = _dt.date.today().year
    donations_ytd = fetchone(conn, f"SELECT COALESCE(SUM(amount),0) AS total FROM donor_donations WHERE donation_date >= '{year}-01-01' AND type='square'")
    # Recent orders (cart + single, last 8)
    cart_orders = fetchall(conn, '''SELECT id, guardian_name, guardian_email, total_cents, status, created_at,
        (SELECT COUNT(*) FROM json_array_elements(items_json::json)) AS item_count
        FROM cart_orders ORDER BY created_at DESC LIMIT 8''') or []
    # Open products in catalog
    open_programs = (fetchone(conn, "SELECT COUNT(*) AS c FROM youth_programs WHERE registration_status='open'") or {}).get('c', 0)
    open_productions = (fetchone(conn, "SELECT COUNT(*) AS c FROM productions WHERE registration_status='open'") or {}).get('c', 0)
    # Recent donations
    recent_donations = fetchall(conn, '''SELECT pd.name, pd.email, pd.amount_cents, pd.created_at
        FROM pending_donations pd WHERE pd.status='completed'
        ORDER BY pd.created_at DESC LIMIT 5''') or []
    conn.close()
    return jsonify({
        'reg_counts': reg_counts,
        'cart_revenue': total_revenue,
        'donations_ytd': float((donations_ytd or {}).get('total', 0)),
        'open_products': int(open_programs) + int(open_productions),
        'recent_orders': cart_orders,
        'recent_donations': recent_donations,
    })


@app.route('/api/marquee/registrations', methods=['GET'])
def marquee_all_registrations():
    err = require_permission('marquee', 'view')
    if err: return err
    import json as _jmq
    conn = get_db()
    program_id = request.args.get('program_id')
    production_id = request.args.get('production_id')
    status = request.args.get('status')
    q1 = '''SELECT pr.*, yp.name AS program_name, yp.registration_form_type,
        yp.sessions_enabled, yp.price AS program_price, 'program' AS context_type,
        (COALESCE(yp.price,0) * COALESCE(pr.participant_count,1)
         - COALESCE(pr.discount_amount,0)
         - COALESCE(pr.sibling_discount_amount,0)) AS amount_paid_cents
        FROM program_registrations pr
        JOIN youth_programs yp ON yp.id=pr.program_id
        WHERE pr.program_id IS NOT NULL'''
    p1 = []
    if program_id:
        q1 += ' AND pr.program_id=%s'; p1.append(program_id)
    if status:
        q1 += ' AND pr.status=%s'; p1.append(status)
    q2 = '''SELECT pr.*, p.name AS program_name, p.registration_form_type,
        FALSE AS sessions_enabled, 'production' AS context_type
        FROM program_registrations pr
        JOIN productions p ON p.id=pr.production_id
        WHERE pr.production_id IS NOT NULL'''
    p2 = []
    if production_id:
        q2 += ' AND pr.production_id=%s'; p2.append(production_id)
    if status:
        q2 += ' AND pr.status=%s'; p2.append(status)
    regs1 = fetchall(conn, q1 + ' ORDER BY pr.created_at DESC LIMIT 200', p1) or []
    regs2 = (fetchall(conn, q2 + ' ORDER BY pr.created_at DESC LIMIT 200', p2) or []) if not program_id else []
    regs = sorted(regs1 + regs2, key=lambda r: str(r.get('created_at') or ''), reverse=True)[:200]
    # Resolve session names for all program registrations
    sessions_by_program = {}
    for r in regs:
        pid = r.get('program_id')
        if pid and r.get('sessions_enabled') and pid not in sessions_by_program:
            rows = fetchall(conn, 'SELECT id, name FROM program_sessions WHERE program_id=%s', (pid,)) or []
            sessions_by_program[pid] = {s['id']: s['name'] for s in rows}
    for r in regs:
        pid = r.get('program_id')
        smap = sessions_by_program.get(pid, {})
        try:
            sids = _jmq.loads(r.get('session_ids') or '[]')
            r['session_names'] = [smap[sid] for sid in sids if sid in smap]
        except Exception:
            r['session_names'] = []
    programs = fetchall(conn, "SELECT id, name, start_date FROM youth_programs WHERE registration_status != 'draft' ORDER BY start_date ASC NULLS LAST, name ASC")
    productions_rs = fetchall(conn, "SELECT id, name FROM productions WHERE stage='rising_stars' AND registration_status IS NOT NULL AND registration_status != 'draft' ORDER BY name")
    conn.close()
    return jsonify({'registrations': regs, 'programs': programs, 'productions': productions_rs or []})


@app.route('/api/programs/<pid>/sessions/summary', methods=['GET'])
def program_sessions_summary(pid):
    """Return each session with its registered participants."""
    err = require_auth()
    if err: return err
    import json as _jss
    conn = get_db()
    sessions = fetchall(conn, '''SELECT ps.*,
        (SELECT COUNT(*) FROM program_registrations
         WHERE program_id=%s AND session_ids LIKE '%%"' || ps.id || '"%%'
         AND status NOT IN ('cancelled','waitlisted')) AS confirmed_count,
        (SELECT COUNT(*) FROM program_registrations
         WHERE program_id=%s AND session_ids LIKE '%%"' || ps.id || '"%%'
         AND status='waitlisted') AS waitlisted_count
        FROM program_sessions ps WHERE ps.program_id=%s
        ORDER BY ps.sort_order, ps.day_of_week, ps.start_time''', (pid, pid, pid))
    regs = fetchall(conn, '''SELECT pr.*, yp.registration_form_type
        FROM program_registrations pr
        JOIN youth_programs yp ON yp.id=pr.program_id
        WHERE pr.program_id=%s AND pr.session_ids != '[]'
        AND pr.status NOT IN ('cancelled')
        ORDER BY pr.child_last_name, pr.child_first_name''', (pid,)) or []
    # Group registrations by session
    reg_by_session = {}
    for r in regs:
        try:
            sids = _jss.loads(r.get('session_ids') or '[]')
        except Exception:
            sids = []
        for sid in sids:
            if sid not in reg_by_session:
                reg_by_session[sid] = []
            reg_by_session[sid].append(r)
    conn.close()
    return jsonify({'sessions': sessions or [], 'reg_by_session': reg_by_session})


@app.route('/api/public/program/<slug>/registration/<rid>', methods=['GET'])
def get_registration_status(slug, rid):
    """Check registration status — called from confirmation page."""
    conn = get_db()
    reg = fetchone(conn, 'SELECT status, waitlist_position, child_first_name, child_last_name, guardian_email FROM program_registrations WHERE id=%s', (rid,))
    conn.close()
    if not reg:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(reg)


# ── Admin registration management ────────────────────────────────────────────

@app.route('/api/programs/<pid>/registrations', methods=['GET'])
def get_program_registrations(pid):
    err = require_auth()
    if err: return err
    import json as _jreg
    conn = get_db()
    regs = fetchall(conn, '''SELECT pr.*, yp.registration_form_type
        FROM program_registrations pr
        JOIN youth_programs yp ON yp.id=pr.program_id
        WHERE pr.program_id=%s ORDER BY pr.created_at DESC''', (pid,))
    # Resolve session names
    sessions_map = {}
    session_rows = fetchall(conn, 'SELECT id, name FROM program_sessions WHERE program_id=%s', (pid,)) or []
    for sr in session_rows:
        sessions_map[sr['id']] = sr['name']
    for r in (regs or []):
        try:
            sids = _jreg.loads(r.get('session_ids') or '[]')
            r['session_names'] = [sessions_map.get(sid, sid) for sid in sids if sid in sessions_map]
        except Exception:
            r['session_names'] = []
    interest = fetchall(conn, '''SELECT * FROM interest_list_entries
        WHERE program_id=%s ORDER BY created_at DESC''', (pid,))
    counts = {
        'confirmed': sum(1 for r in (regs or []) if r['status'] == 'confirmed'),
        'pending_payment': sum(1 for r in (regs or []) if r['status'] == 'pending_payment'),
        'waitlisted': sum(1 for r in (regs or []) if r['status'] == 'waitlisted'),
        'interest': len(interest or []),
    }
    conn.close()
    return jsonify({'registrations': regs or [], 'interest_list': interest or [], 'counts': counts})


@app.route('/api/programs/<pid>/registrations/<rid>', methods=['PUT'])
def update_registration(pid, rid):
    err = require_auth()
    if err: return err
    import json as _jur
    d = request.json or {}
    conn = get_db()
    execute(conn, '''UPDATE program_registrations SET
        status=%s, notes=%s, shirt_size=%s, guardian_name=%s,
        guardian_email=%s, guardian_phone=%s,
        emergency_contact_name=%s, emergency_contact_phone=%s,
        session_ids=%s,
        updated_at=NOW() WHERE id=%s AND program_id=%s''',
        (d.get('status'), d.get('notes',''), d.get('shirt_size',''),
         d.get('guardian_name',''), d.get('guardian_email',''),
         d.get('guardian_phone',''), d.get('emergency_contact_name',''),
         d.get('emergency_contact_phone',''),
         _jur.dumps(d.get('session_ids') or []),
         rid, pid))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/programs/<pid>/registrations/<rid>/promote-waitlist', methods=['POST'])
def promote_waitlist(pid, rid):
    err = require_auth()
    if err: return err
    import uuid as _upw
    d = request.json or {}
    hold_hours = int(d.get('hold_hours') or 48)
    conn = get_db()
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s AND program_id=%s', (rid, pid))
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not reg or not prog:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    price = prog.get('price') or 0
    # If free, just confirm
    if price == 0:
        execute(conn, "UPDATE program_registrations SET status='confirmed', waitlist_position=NULL WHERE id=%s", (rid,))
        conn.commit()
        try:
            name = reg.get('guardian_name') or reg.get('child_first_name') or 'there'
            send_email([reg['guardian_email']], f'Great news — you\'re in! {prog["name"]}',
                f'<div style="font-family:-apple-system,sans-serif;max-width:560px">'
                f'<h2 style="color:#145466">You\'re Confirmed!</h2>'
                f'<p>Hi {name},</p>'
                f'<p>Great news — a spot has opened up in <strong>{prog["name"]}</strong> and you\'ve been confirmed!</p>'
                f'<p>Horizon West Theatre Company</p></div>')
        except Exception as e:
            app.logger.warning(f'Waitlist confirm email failed: {e}')
        conn.close()
        return jsonify({'ok': True, 'type': 'confirmed_free'})
    # Paid — send payment link and notify of hold window
    execute(conn, "UPDATE program_registrations SET status='pending_payment', waitlist_position=NULL WHERE id=%s", (rid,))
    pay_url, link_id, order_id = square_create_payment_link(
        prog, rid, reg['guardian_email'], reg.get('guardian_name',''), price,
        note=f'Waitlist promotion — {reg.get("child_first_name","")} {reg.get("child_last_name","")} — {prog["name"]}')
    if pay_url:
        execute(conn, 'UPDATE program_registrations SET square_checkout_id=%s, square_order_id=%s WHERE id=%s',
            (link_id, order_id, rid))
    conn.commit()
    # Email family
    try:
        name = reg.get('guardian_name') or reg.get('child_first_name') or 'there'
        child = ((reg.get('child_first_name') or '') + ' ' + (reg.get('child_last_name') or '')).strip()
        hold_msg = f'Your spot will be held for <strong>{hold_hours} hours</strong>.' if hold_hours else 'Please complete your registration as soon as possible.'
        send_email([reg['guardian_email']], f'A spot opened up for you — {prog["name"]}',
            f'<div style="font-family:-apple-system,sans-serif;max-width:560px">'
            f'<h2 style="color:#145466">A Spot Has Opened Up!</h2>'
            f'<p>Hi {name},</p>'
            f'<p>Great news — a spot has become available in <strong>{prog["name"]}</strong>'
            f'{" for " + child if child else ""}. You are next on the waitlist!</p>'
            f'<p>{hold_msg} After that, the spot may be offered to the next person on the waitlist.</p>'
            + (f'<p style="margin:24px 0"><a href="{pay_url}" style="background:#145466;color:#fff;'
               f'padding:13px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">'
               f'Secure My Spot</a></p>'
               f'<p style="color:#6b7280;font-size:13px">Or copy this link: {pay_url}</p>'
               if pay_url else '')
            + f'<p>Horizon West Theatre Company</p></div>')
    except Exception as e:
        app.logger.warning(f'Waitlist promote email failed: {e}')
    conn.close()
    return jsonify({'ok': True, 'type': 'payment_link_sent', 'hold_hours': hold_hours})


@app.route('/api/programs/<pid>/notify-interest-list', methods=['POST'])
def notify_interest_list(pid):
    err = require_auth()
    if err: return err
    conn = get_db()
    prog = fetchone(conn, 'SELECT * FROM youth_programs WHERE id=%s', (pid,))
    if not prog:
        conn.close()
        return jsonify({'error': 'Program not found'}), 404
    entries = fetchall(conn, 'SELECT * FROM interest_list_entries WHERE program_id=%s', (pid,))
    conn.close()
    if not entries:
        return jsonify({'ok': True, 'sent': 0})
    slug = prog.get('slug') or pid
    reg_url = f'{APP_BASE_URL}/register/{slug}'
    sent = 0
    for e in entries:
        email = e.get('email')
        name = (e.get('name') or '').strip().split()[0] or 'there'
        if not email:
            continue
        try:
            send_email([email], f'Registration is now open — {prog["name"]}',
                f'<div style="font-family:-apple-system,sans-serif;max-width:560px;margin:0 auto;color:#1a2332">'
                f'<div style="background:linear-gradient(135deg,#0d3d4d,#1b708d);padding:28px 24px;text-align:center;border-radius:12px 12px 0 0">'
                f'<img src="https://rolecall.hwtco.org/static/images/hwtc_logo_white.png" alt="HWTC" style="height:48px;display:block;margin:0 auto 10px;mix-blend-mode:screen"/>'
                f'</div>'
                f'<div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb">'
                f'<h2 style="color:#0d3d4d;font-size:20px;margin:0 0 12px">Registration is now open!</h2>'
                f'<p style="color:#374151;line-height:1.6;margin:0 0 14px">Hi {name},</p>'
                f'<p style="color:#374151;line-height:1.6;margin:0 0 20px">'
                f'Great news — registration for <strong>{prog["name"]}</strong> is now open. '
                f'You signed up for our interest list and we wanted to make sure you\'re first to know!</p>'
                f'<p style="margin:0 0 24px;text-align:center">'
                f'<a href="{reg_url}" style="background:#145466;color:#fff;padding:13px 28px;border-radius:8px;'
                f'text-decoration:none;font-weight:700;font-size:15px;display:inline-block">Register Now &rarr;</a></p>'
                f'<p style="color:#6b7280;font-size:13px;margin:0">Or copy this link: <a href="{reg_url}" style="color:#145466">{reg_url}</a></p>'
                f'<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0"/>'
                f'<p style="color:#9ca3af;font-size:12px;margin:0;text-align:center">Horizon West Theatre Company &nbsp;&middot;&nbsp; Horizon West, FL</p>'
                f'</div></div>')
            # Stamp notified_at so the UI reflects the notification
            conn2 = get_db()
            execute(conn2, 'UPDATE interest_list_entries SET notified_at=NOW() WHERE id=%s', (e['id'],))
            conn2.commit(); conn2.close()
            sent += 1
        except Exception as ex:
            app.logger.warning(f'Interest list notify failed for {email}: {ex}')
    return jsonify({'ok': True, 'sent': sent})


@app.route('/api/programs/<pid>/registrations/<rid>/finalize', methods=['POST'])
def manual_finalize_registration(pid, rid):
    err = require_permission('marquee')
    if err: return err
    conn = get_db()
    reg = fetchone(conn, 'SELECT * FROM program_registrations WHERE id=%s AND program_id=%s', (rid, pid))
    if not reg:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    finalize_registration(conn, rid)
    conn.commit(); conn.close()
    return jsonify({'ok': True})



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
