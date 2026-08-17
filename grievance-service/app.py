"""
grievance-service
==================
OWNS: the `grievances` collection (its own Mongo database, `grievance_db`).
JOB : create / list / view / update-status of grievances.

This service NEVER talks to auth-service over the network to check who's
calling. It verifies the JWT's signature *locally* using the same
JWT_SECRET auth-service signed it with (both come from the same K8s
Secret). This is the standard "stateless verification" pattern used across
almost every real microservice system - it keeps auth-service from
becoming a bottleneck / single point of failure that every other request
has to round-trip through.
"""
import os
import time
from datetime import datetime
from functools import wraps

import jwt
import requests
from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from bson.objectid import ObjectId
from bson.errors import InvalidId

app = Flask(__name__)

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://root:example@mongo:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'grievance_db')
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-jwt-secret-change-in-production')
AUDIT_SERVICE_URL = os.getenv('AUDIT_SERVICE_URL', 'http://audit-service:5003')

# See the long comment in auth-service/app.py for why this retries instead
# of connecting once - short version: a single failed attempt at container
# startup used to mean /readyz failed FOREVER, even after Mongo came up,
# because nothing ever tried the connection again.
def connect_mongo(retries=5, delay_seconds=2):
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print(f"[grievance-service] MongoDB connected -> database '{MONGO_DB}' (attempt {attempt}/{retries})")
            return client, client[MONGO_DB]
        except ServerSelectionTimeoutError as exc:
            print(f"[grievance-service] MongoDB connection attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay_seconds)
    print(f"[grievance-service] MongoDB still unreachable after {retries} attempts; "
          f"will keep retrying lazily on every /readyz check")
    return None, None


mongo_client, db = connect_mongo()


def init_db():
    if db is None:
        return
    if 'grievances' not in db.list_collection_names():
        db.create_collection('grievances')
        db['grievances'].create_index('user_id')
        db['grievances'].create_index('status')
        db['grievances'].create_index('created_at')
        print("[grievance-service] grievances collection + indexes created")


init_db()


def to_object_id(raw_id):
    try:
        return ObjectId(raw_id)
    except (InvalidId, TypeError):
        return None


def serialize(g):
    g = dict(g)
    g['_id'] = str(g['_id'])
    g['user_id'] = str(g['user_id'])
    g['created_at'] = g['created_at'].isoformat()
    g['updated_at'] = g['updated_at'].isoformat()
    return g


def log_action(user_id, action, details=''):
    try:
        requests.post(f'{AUDIT_SERVICE_URL}/api/logs',
                       json={'user_id': user_id, 'action': action,
                             'details': details, 'source': 'grievance-service'},
                       timeout=2)
    except requests.RequestException as exc:
        print(f"[grievance-service] audit-service unreachable (non-fatal): {exc}")


def token_required(f):
    """Verifies the JWT's signature + expiry ourselves - no network call
    to auth-service. request.claims ends up holding {sub, username, role,
    email, full_name, iat, exp}, exactly what auth-service put in it."""
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


# ==================== GRIEVANCE CRUD ====================
@app.route('/api/grievances', methods=['POST'])
@token_required
def create_grievance():
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get('title') or '').strip()
    description = (data.get('description') or '').strip()
    category = data.get('category') or ''
    priority = data.get('priority') or 'Medium'

    if not all([title, description, category]):
        return jsonify({'error': 'All fields are required'}), 400

    doc = {
        'user_id': to_object_id(request.claims['sub']),
        'title': title,
        'description': description,
        'category': category,
        'priority': priority,
        'status': 'open',
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
        'attachments': [],
        'comments': [],
    }
    result = db['grievances'].insert_one(doc)
    log_action(request.claims['sub'], 'GRIEVANCE_CREATED', f'Grievance: {title}')
    doc['_id'] = result.inserted_id
    return jsonify(serialize(doc)), 201


@app.route('/api/grievances', methods=['GET'])
@token_required
def list_grievances():
    """Admins see every grievance; regular users only see their own -- the
    scoping rule that used to live in the monolith's view function now
    lives here, since this service is the one that owns the data."""
    status_filter = request.args.get('status', 'all')
    query = {} if request.claims.get('role') == 'admin' else {
        'user_id': to_object_id(request.claims['sub'])
    }
    if status_filter and status_filter != 'all':
        query['status'] = status_filter

    grievances = list(db['grievances'].find(query).sort('created_at', -1))
    return jsonify([serialize(g) for g in grievances]), 200


@app.route('/api/grievances/stats', methods=['GET'])
@token_required
def grievance_stats():
    """Small aggregate endpoint purpose-built for the dashboard, so the
    frontend doesn't have to pull every document just to count them."""
    scope = {} if request.claims.get('role') == 'admin' else {
        'user_id': to_object_id(request.claims['sub'])
    }
    stats = {
        'total': db['grievances'].count_documents(scope),
        'open': db['grievances'].count_documents({**scope, 'status': 'open'}),
        'resolved': db['grievances'].count_documents({**scope, 'status': 'resolved'}),
    }
    recent = list(db['grievances'].find(scope).sort('created_at', -1).limit(5))
    return jsonify({'stats': stats, 'recent': [serialize(g) for g in recent]}), 200


@app.route('/api/grievances/<grievance_id>', methods=['GET'])
@token_required
def get_grievance(grievance_id):
    oid = to_object_id(grievance_id)
    g = db['grievances'].find_one({'_id': oid}) if oid else None
    if not g:
        return jsonify({'error': 'not found'}), 404
    if request.claims.get('role') != 'admin' and str(g['user_id']) != request.claims['sub']:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(serialize(g)), 200


@app.route('/api/grievances/<grievance_id>/status', methods=['PUT'])
@token_required
@admin_required
def update_status(grievance_id):
    data = request.get_json(force=True, silent=True) or {}
    new_status = data.get('status')
    valid_statuses = {'open', 'in_progress', 'resolved', 'closed'}
    oid = to_object_id(grievance_id)

    if not oid or new_status not in valid_statuses:
        return jsonify({'error': 'invalid grievance id or status'}), 400

    db['grievances'].update_one(
        {'_id': oid}, {'$set': {'status': new_status, 'updated_at': datetime.utcnow()}}
    )
    log_action(request.claims['sub'], 'GRIEVANCE_STATUS_UPDATED', f'{grievance_id} -> {new_status}')
    g = db['grievances'].find_one({'_id': oid})
    return jsonify(serialize(g)), 200


# ==================== KUBERNETES HEALTH PROBES ====================
# /healthz -> LIVENESS: "is the Flask process alive and able to answer
#   HTTP at all?" Deliberately does NOT touch Mongo. If this ever starts
#   failing, the kubelet kills and restarts the container (that's what a
#   liveness probe failure means: "this process is stuck, nuke it").
#   A slow/blipping database is NOT a reason to kill a perfectly healthy
#   process, which is exactly why this check is separate from readiness.
#
# /readyz -> READINESS: "can this pod usefully serve traffic RIGHT NOW?"
#   This DOES touch Mongo. If it fails, Kubernetes removes this pod's IP
#   from the Service's Endpoints list (i.e. it stops receiving traffic
#   from other pods / the Ingress) but does NOT restart the container --
#   it keeps checking and adds the pod back the moment Mongo answers
#   again. This is what makes rolling deploys and "mongo pod restarted"
#   events non-events for users: traffic simply routes around the
#   temporarily-unready pod.
@app.route('/healthz')
def healthz():
    return jsonify({'status': 'alive', 'service': 'grievance-service'}), 200


@app.route('/readyz')
def readyz():
    global mongo_client, db
    try:
        if db is None:
            mongo_client, db = connect_mongo(retries=1, delay_seconds=0)
        if db is not None:
            db.command('ping')
            return jsonify({'status': 'ready', 'database': 'connected'}), 200
    except Exception as exc:
        db = None
        return jsonify({'status': 'not-ready', 'detail': str(exc)}), 503
    return jsonify({'status': 'not-ready', 'database': 'disconnected'}), 503


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5002)),
             debug=os.getenv('FLASK_ENV', 'development') == 'development')
