"""
auth-service
============
OWNS: the `users` collection (its own Mongo *database*, `auth_db`).
JOB : registration, login, issuing/verifying JWTs, and being the single
      source of truth for "who is this user / what is their role".

Why does this exist as its OWN microservice instead of living inside
grievance-service?
  - Identity/auth is a different *reason to change* than grievance
    business logic (a new password policy shouldn't require redeploying
    the grievance workflow, and vice versa) -> that's the textbook
    definition of a service boundary.
  - It lets us scale/secure it independently -- e.g. put stricter rate
    limiting or a WAF rule in front of just this service later.
  - Every other service can verify a request's identity WITHOUT calling
    this service over the network on every single request, because we
    hand out a signed JWT. Any service that holds the same JWT_SECRET
    (injected via a K8s Secret) can verify the token's signature and
    read the claims locally -- no network hop, no shared database
    dependency, no single point of failure at request time.
"""
import os
import time
from datetime import datetime, timedelta
from functools import wraps

import jwt  # PyJWT - encodes/decodes/verifies the signed JSON Web Token
import requests
from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError
from bson.objectid import ObjectId
from bson.errors import InvalidId
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# ==================== CONFIG (all from env -> ConfigMap/Secret in k8s) ====
# Same Mongo *server* as the other services (simplest possible setup for
# minikube - one StatefulSet, one Pod, one PVC) but each service is only
# ever given / uses its OWN database name inside that server. That's what
# makes this "microservices" rather than "one big shared table space":
# grievance-service literally has no code path that can query auth_db.
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://root:example@mongo:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'auth_db')

# The signing key for JWTs. MUST be identical across auth-service,
# grievance-service and audit-service (all three verify tokens locally) --
# in Kubernetes that's enforced by pointing all three Deployments at the
# same Secret key, see k8s/02-secret.yaml.
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-jwt-secret-change-in-production')
JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '24'))

# Internal-only URL of audit-service, resolved by Kubernetes' built-in
# cluster DNS (CoreDNS). Inside the cluster, a Service named "audit-service"
# in this namespace is reachable at exactly this hostname - no IP addresses,
# no service discovery library needed, K8s does it for free.
AUDIT_SERVICE_URL = os.getenv('AUDIT_SERVICE_URL', 'http://audit-service:5003')

# ---- Mongo connection, WITH RETRY -----------------------------------------
# The original version of this file connected exactly once, at import time:
# if Mongo wasn't accepting connections yet (e.g. `helm install` created this
# Deployment and the mongo StatefulSet at basically the same moment, and
# mongod hadn't finished booting), `db` was set to None and NEVER retried -
# meaning /readyz would fail forever, even minutes later once Mongo was
# clearly up, and the pod would sit at 0/1 Ready until someone manually
# restarted it. Two changes fix that:
#   1. connect_mongo() below retries a few times with a short delay before
#      giving up, so a Mongo pod that's just a few seconds slow to boot no
#      longer causes a permanent failure.
#   2. /readyz (further down) ALSO retries lazily on every single readiness
#      check if `db` is still None - so even in the worst case (Mongo takes
#      longer than every startup retry), the pod self-heals the moment Mongo
#      actually becomes reachable, with zero manual intervention.
# This is a defense-in-depth complement to the Helm chart's initContainer
# (which blocks the pod from starting at all until Mongo's port is open) -
# that fixes the common case at the Kubernetes layer; this fixes it at the
# application layer too, so the service behaves correctly even when run
# outside Kubernetes (bare `python app.py`, docker-compose) where there's no
# initContainer to help it.
def connect_mongo(retries=5, delay_seconds=2):
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print(f"[auth-service] MongoDB connected -> database '{MONGO_DB}' (attempt {attempt}/{retries})")
            return client, client[MONGO_DB]
        except ServerSelectionTimeoutError as exc:
            print(f"[auth-service] MongoDB connection attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay_seconds)
    print(f"[auth-service] MongoDB still unreachable after {retries} attempts; "
          f"will keep retrying lazily on every /readyz check")
    return None, None


mongo_client, db = connect_mongo()


def init_db():
    if db is None:
        return
    if 'users' not in db.list_collection_names():
        db.create_collection('users')
        db['users'].create_index('email', unique=True)
        db['users'].create_index('username', unique=True)
        print("[auth-service] users collection + indexes created")


init_db()


# ==================== HELPERS ====================
def to_object_id(raw_id):
    try:
        return ObjectId(raw_id)
    except (InvalidId, TypeError):
        return None


def public_user(user_doc):
    """Strip password_hash / cast ids before this ever leaves the service."""
    return {
        'id': str(user_doc['_id']),
        'username': user_doc['username'],
        'email': user_doc['email'],
        'full_name': user_doc.get('full_name', ''),
        'phone': user_doc.get('phone', ''),
        'role': user_doc.get('role', 'user'),
        'status': user_doc.get('status', 'active'),
        'created_at': user_doc['created_at'].isoformat() if user_doc.get('created_at') else None,
    }


def issue_token(user_doc):
    """Build the signed JWT that every other service will trust."""
    payload = {
        'sub': str(user_doc['_id']),               # subject = user id
        'username': user_doc['username'],
        'role': user_doc.get('role', 'user'),
        'full_name': user_doc.get('full_name', ''),
        'email': user_doc['email'],
        'iat': datetime.utcnow(),                    # issued-at
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


def log_action(user_id, action, details=''):
    """Fire-and-forget call to audit-service. This is service-to-service
    HTTP over the cluster network (auth-service -> audit-service), and we
    deliberately do NOT let a failure here break the caller's request --
    the audit trail is important but it is not worth failing a login over."""
    try:
        requests.post(
            f'{AUDIT_SERVICE_URL}/api/logs',
            json={'user_id': user_id, 'action': action, 'details': details,
                  'source': 'auth-service'},
            timeout=2,
        )
    except requests.RequestException as exc:
        print(f"[auth-service] audit-service unreachable (non-fatal): {exc}")


def token_required(f):
    """Decorator for endpoints that need *any* logged-in caller."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'missing bearer token'}), 401
        token = auth_header.split(' ', 1)[1]
        try:
            request.claims = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'invalid token'}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.claims.get('role') != 'admin':
            return jsonify({'error': 'admin role required'}), 403
        return f(*args, **kwargs)
    return wrapper


# ==================== AUTH ROUTES ====================
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    confirm_password = data.get('confirm_password') or ''
    full_name = (data.get('full_name') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not all([email, username, password, full_name]):
        return jsonify({'error': 'All fields are required'}), 400
    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if db['users'].find_one({'email': email}):
        return jsonify({'error': 'Email already registered'}), 409
    if db['users'].find_one({'username': username}):
        return jsonify({'error': 'Username already taken'}), 409

    user_doc = {
        'username': username,
        'email': email,
        'password_hash': generate_password_hash(password),
        'full_name': full_name,
        'phone': phone,
        'role': 'user',
        'status': 'active',
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
    }
    try:
        result = db['users'].insert_one(user_doc)
    except DuplicateKeyError:
        return jsonify({'error': 'Email or username already exists'}), 409

    log_action(str(result.inserted_id), 'USER_REGISTERED', f'User {username} registered')
    return jsonify({'message': 'Registration successful'}), 201


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    user = db['users'].find_one({'email': email})
    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid email or password'}), 401
    if user.get('status') != 'active':
        return jsonify({'error': 'Account is disabled'}), 403

    token = issue_token(user)
    log_action(str(user['_id']), 'LOGIN', f'User {user["username"]} logged in')

    return jsonify({'token': token, 'user': public_user(user)}), 200


@app.route('/api/verify', methods=['GET'])
@token_required
def verify():
    """Lets a caller double check a token server-side (mostly for
    debugging / the frontend's "am I still logged in" check). Everyday
    verification by grievance-service / audit-service happens LOCALLY via
    jwt.decode() using the shared secret -- they don't call this endpoint,
    that would turn every single request into two network hops."""
    return jsonify({'valid': True, 'claims': request.claims}), 200


# ==================== USER DIRECTORY / PROFILE ====================
@app.route('/api/users', methods=['GET'])
@token_required
@admin_required
def list_users():
    role_filter = request.args.get('role', 'all')
    query = {} if role_filter == 'all' else {'role': role_filter}
    users = list(db['users'].find(query).sort('created_at', -1))
    return jsonify([public_user(u) for u in users]), 200


@app.route('/api/users/<user_id>', methods=['GET'])
@token_required
def get_user(user_id):
    # Non-admins may only fetch their own record.
    if request.claims.get('role') != 'admin' and request.claims['sub'] != user_id:
        return jsonify({'error': 'forbidden'}), 403
    oid = to_object_id(user_id)
    user = db['users'].find_one({'_id': oid}) if oid else None
    if not user:
        return jsonify({'error': 'not found'}), 404
    return jsonify(public_user(user)), 200


@app.route('/api/users/<user_id>', methods=['PUT'])
@token_required
def update_user(user_id):
    if request.claims['sub'] != user_id:
        return jsonify({'error': 'forbidden'}), 403
    data = request.get_json(force=True, silent=True) or {}
    update = {
        'full_name': (data.get('full_name') or '').strip(),
        'phone': (data.get('phone') or '').strip(),
        'updated_at': datetime.utcnow(),
    }
    oid = to_object_id(user_id)
    db['users'].update_one({'_id': oid}, {'$set': update})
    log_action(user_id, 'PROFILE_UPDATED', 'User updated profile')
    user = db['users'].find_one({'_id': oid})
    return jsonify(public_user(user)), 200


# ==================== KUBERNETES HEALTH PROBES ====================
# See grievance-service/app.py for the long-form explanation of why
# liveness and readiness are two different endpoints -- same reasoning
# applies identically in every service in this project.
@app.route('/healthz')
def healthz():
    return jsonify({'status': 'alive', 'service': 'auth-service'}), 200


@app.route('/readyz')
def readyz():
    global mongo_client, db
    try:
        if db is None:
            # Lazy reconnect: this is what makes the pod self-heal even if
            # every startup retry in connect_mongo() was exhausted before
            # Mongo came up. Kubernetes calls /readyz on a loop for the
            # lifetime of the pod, so the very next probe after Mongo
            # becomes reachable will succeed here - no restart needed.
            mongo_client, db = connect_mongo(retries=1, delay_seconds=0)
        if db is not None:
            db.command('ping')
            return jsonify({'status': 'ready', 'database': 'connected'}), 200
    except Exception as exc:
        db = None  # force the next probe to retry the reconnect from scratch
        return jsonify({'status': 'not-ready', 'detail': str(exc)}), 503
    return jsonify({'status': 'not-ready', 'database': 'disconnected'}), 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5001)),
             debug=os.getenv('FLASK_ENV', 'development') == 'development')
