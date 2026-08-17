"""
frontend-service
=================
OWNS: no database at all. This is a "Backend-For-Frontend" (BFF) -- it
renders the same Jinja templates the original monolith used, but instead
of querying MongoDB directly it makes HTTP calls to auth-service,
grievance-service and audit-service over the Kubernetes cluster network,
and stitches the JSON responses into the same template variables the
templates already expect.

Why keep this separate from the API services instead of folding the HTML
into, say, grievance-service?
  - The browser-facing session cookie (Flask `session`) belongs here and
    ONLY here. None of the JSON API services keep any browser state.
  - It's the only service that needs an external entry point at all
    (Ingress / NodePort) -- auth, grievance and audit only need to be
    reachable from INSIDE the cluster. That's a real, deployable
    difference in exposure, which is exactly the kind of thing a service
    boundary should track.
  - It could be swapped for a totally different UI (a React SPA calling
    the same three APIs) without anyone touching auth/grievance/audit.
"""
import os
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, session, url_for

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# ==================== SERVICE DISCOVERY ====================
# These hostnames resolve via Kubernetes' internal DNS (CoreDNS) to each
# service's ClusterIP -- e.g. "auth-service" resolves because there is a
# Service object literally named "auth-service" in the same namespace
# (k8s/11-auth-service.yaml). Locally / in docker-compose these instead
# point at container names on the shared docker network. Either way, the
# application code never hardcodes an IP address.
AUTH_SERVICE_URL = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:5001')
GRIEVANCE_SERVICE_URL = os.getenv('GRIEVANCE_SERVICE_URL', 'http://grievance-service:5002')
AUDIT_SERVICE_URL = os.getenv('AUDIT_SERVICE_URL', 'http://audit-service:5003')
REQUEST_TIMEOUT = float(os.getenv('UPSTREAM_TIMEOUT_SECONDS', '5'))


@app.context_processor
def inject_now_year():
    return {'now_year': datetime.utcnow().year}


# ==================== HELPERS ====================
def auth_headers():
    """Every call to a backend service carries the JWT we got at login,
    the same way a browser carries a cookie -- this is what lets
    grievance-service and audit-service know who's asking without ever
    seeing a password or a Flask session."""
    token = session.get('token')
    return {'Authorization': f'Bearer {token}'} if token else {}


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'token' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'token' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


def fmt(iso_ts):
    """API services return ISO-8601 timestamps (JSON has no native date
    type); the templates expect the same 'YYYY-MM-DD HH:MM' shape the
    original monolith produced, so we reformat here at the UI edge."""
    if not iso_ts:
        return ''
    try:
        return datetime.fromisoformat(iso_ts).strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return iso_ts


# ==================== AUTH ROUTES ====================
@app.route('/')
def index():
    if 'token' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        payload = {
            'email': request.form.get('email', ''),
            'username': request.form.get('username', ''),
            'password': request.form.get('password', ''),
            'confirm_password': request.form.get('confirm_password', ''),
            'full_name': request.form.get('full_name', ''),
            'phone': request.form.get('phone', ''),
        }
        try:
            resp = requests.post(f'{AUTH_SERVICE_URL}/api/register', json=payload,
                                  timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return render_template('register.html', error=f'auth-service unreachable: {exc}')

        if resp.status_code == 201:
            return render_template('register.html', success='Registration successful! Please login.')
        return render_template('register.html', error=resp.json().get('error', 'Registration failed'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        payload = {'email': request.form.get('email', ''), 'password': request.form.get('password', '')}
        try:
            resp = requests.post(f'{AUTH_SERVICE_URL}/api/login', json=payload,
                                  timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return render_template('login.html', error=f'auth-service unreachable: {exc}')

        if resp.status_code != 200:
            return render_template('login.html', error=resp.json().get('error', 'Login failed'))

        body = resp.json()
        user = body['user']
        # The JWT is the ONLY credential we keep server-side in the Flask
        # session; we never see or store the password itself here.
        session['token'] = body['token']
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['email'] = user['email']
        session['role'] = user['role']
        session['full_name'] = user['full_name']
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ==================== DASHBOARD ====================
@app.route('/dashboard')
@login_required
def dashboard():
    try:
        resp = requests.get(f'{GRIEVANCE_SERVICE_URL}/api/grievances/stats',
                             headers=auth_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        recent = body['recent']
        for g in recent:
            g['created_at'] = fmt(g['created_at'])
        return render_template('dashboard.html', user={'full_name': session.get('full_name')},
                                stats=body['stats'], recent_grievances=recent)
    except requests.RequestException as exc:
        return render_template('dashboard.html', error=str(exc), stats={}, recent_grievances=[])


# ==================== GRIEVANCE MANAGEMENT ====================
@app.route('/grievance/create', methods=['GET', 'POST'])
@login_required
def create_grievance():
    categories = ['Technical', 'Administrative', 'Service Quality', 'Billing', 'Other']
    priorities = ['Low', 'Medium', 'High', 'Urgent']

    if request.method == 'POST':
        payload = {
            'title': request.form.get('title', ''),
            'description': request.form.get('description', ''),
            'category': request.form.get('category', ''),
            'priority': request.form.get('priority', 'Medium'),
        }
        try:
            resp = requests.post(f'{GRIEVANCE_SERVICE_URL}/api/grievances', json=payload,
                                  headers=auth_headers(), timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            return render_template('create_grievance.html', error=str(exc),
                                    categories=categories, priorities=priorities)

        if resp.status_code == 201:
            return render_template('create_grievance.html', success='Grievance created successfully!',
                                    categories=categories, priorities=priorities)
        return render_template('create_grievance.html',
                                error=resp.json().get('error', 'Error creating grievance'),
                                categories=categories, priorities=priorities)

    return render_template('create_grievance.html', categories=categories, priorities=priorities)


@app.route('/grievances')
@login_required
def view_grievances():
    status_filter = request.args.get('status', 'all')
    try:
        resp = requests.get(f'{GRIEVANCE_SERVICE_URL}/api/grievances',
                             params={'status': status_filter}, headers=auth_headers(),
                             timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        grievances = resp.json()
        for g in grievances:
            g['created_at'] = fmt(g['created_at'])
            g['updated_at'] = fmt(g['updated_at'])
        return render_template('view_grievances.html', grievances=grievances,
                                selected_status=status_filter)
    except requests.RequestException as exc:
        return render_template('view_grievances.html', error=str(exc), grievances=[],
                                selected_status='all')


@app.route('/grievance/<grievance_id>')
@login_required
def grievance_detail(grievance_id):
    try:
        resp = requests.get(f'{GRIEVANCE_SERVICE_URL}/api/grievances/{grievance_id}',
                             headers=auth_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        return render_template('error.html', error=str(exc)), 502

    if resp.status_code == 404:
        return render_template('error.html', error='Grievance not found'), 404
    if resp.status_code == 403:
        return render_template('error.html', error='Unauthorized access'), 403
    if resp.status_code != 200:
        return render_template('error.html', error='Could not load grievance'), 500

    grievance = resp.json()
    grievance['created_at'] = fmt(grievance['created_at'])
    grievance['updated_at'] = fmt(grievance['updated_at'])

    # Second service-to-service-style call, this time frontend -> auth,
    # to resolve the filer's display name for the detail page.
    filer = None
    try:
        u_resp = requests.get(f'{AUTH_SERVICE_URL}/api/users/{grievance["user_id"]}',
                               headers=auth_headers(), timeout=REQUEST_TIMEOUT)
        if u_resp.status_code == 200:
            filer = u_resp.json()
    except requests.RequestException:
        pass  # a missing filer name shouldn't break the whole page

    return render_template('grievance_detail.html', grievance=grievance, filer=filer,
                            statuses=['open', 'in_progress', 'resolved', 'closed'])


@app.route('/grievance/<grievance_id>/status', methods=['POST'])
@login_required
@admin_required
def update_grievance_status(grievance_id):
    new_status = request.form.get('status')
    try:
        requests.put(f'{GRIEVANCE_SERVICE_URL}/api/grievances/{grievance_id}/status',
                      json={'status': new_status}, headers=auth_headers(),
                      timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        pass
    return redirect(url_for('grievance_detail', grievance_id=grievance_id))


# ==================== USER DIRECTORY ====================
@app.route('/users')
@login_required
def list_users():
    role_filter = request.args.get('role', 'all')
    try:
        if session.get('role') == 'admin':
            resp = requests.get(f'{AUTH_SERVICE_URL}/api/users', params={'role': role_filter},
                                 headers=auth_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            users = resp.json()
        else:
            role_filter = 'all'
            resp = requests.get(f'{AUTH_SERVICE_URL}/api/users/{session["user_id"]}',
                                 headers=auth_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            users = [resp.json()]

        for u in users:
            u['created_at'] = (u.get('created_at') or '')[:10]
        return render_template('list_users.html', users=users, selected_role=role_filter)
    except requests.RequestException as exc:
        return render_template('list_users.html', error=str(exc), users=[], selected_role='all')


@app.route('/user/profile', methods=['GET', 'POST'])
@login_required
def user_profile():
    user_id = session['user_id']
    try:
        if request.method == 'POST':
            payload = {'full_name': request.form.get('full_name', ''),
                       'phone': request.form.get('phone', '')}
            resp = requests.put(f'{AUTH_SERVICE_URL}/api/users/{user_id}', json=payload,
                                 headers=auth_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            user = resp.json()
            session['full_name'] = user['full_name']  # keep navbar greeting in sync
            return render_template('user_profile.html', user=user, success='Profile updated successfully!')

        resp = requests.get(f'{AUTH_SERVICE_URL}/api/users/{user_id}', headers=auth_headers(),
                             timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return render_template('user_profile.html', user=resp.json())
    except requests.RequestException as exc:
        return render_template('user_profile.html', error=str(exc), user=None)


# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def page_not_found(_error):
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template('error.html', error='Server error'), 500


# ==================== KUBERNETES HEALTH PROBES ====================
# frontend-service has no database of its own, so its readiness check
# instead confirms it can actually reach auth-service (its most critical
# upstream - without it, nobody can log in). This is what "readiness"
# should mean for a service that is really just a client of other
# services: not "am I up" but "can I currently do my job".
@app.route('/healthz')
def healthz():
    return {'status': 'alive', 'service': 'frontend-service'}, 200


@app.route('/readyz')
def readyz():
    try:
        r = requests.get(f'{AUTH_SERVICE_URL}/healthz', timeout=2)
        if r.status_code == 200:
            return {'status': 'ready', 'auth_service': 'reachable'}, 200
    except requests.RequestException as exc:
        return {'status': 'not-ready', 'detail': str(exc)}, 503
    return {'status': 'not-ready', 'auth_service': 'unreachable'}, 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)),
             debug=os.getenv('FLASK_ENV', 'development') == 'development')
