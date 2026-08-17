"""
audit-service
=============
OWNS: the `audit_logs` collection (its own Mongo database, `audit_db`).
JOB : append-only "who did what, when" trail. Every other service calls
      POST /api/logs as a fire-and-forget side-effect of a real action.

Why pull this out into its OWN service instead of writing directly to a
shared audit_logs table from every service?
  - It is a genuinely different concern: write-heavy, append-only,
    accessed almost exclusively by admins, and never on the hot path of a
    user-facing request. That profile can be scaled/tuned completely
    differently from grievance-service (e.g. batched writes, a capped
    collection, a different retention policy) without touching anything
    else.
  - It demonstrates the "internal-only" service pattern: unlike
    auth-service and grievance-service, audit-service is NEVER called
    directly by the frontend/browser, only by other backend services over
    the cluster-internal network. That's why its k8s Service is ClusterIP
    only (see k8s/15-audit-service.yaml) -- there is no reason it should
    ever be reachable from outside the cluster.
"""
import os
import time
from datetime import datetime

from flask import Flask, request, jsonify
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
import jwt
from functools import wraps

app = Flask(__name__)

MONGO_URI = os.getenv('MONGO_URI', 'mongodb://root:example@mongo:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'audit_db')
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-jwt-secret-change-in-production')

# See auth-service/app.py for the full explanation - short version: retry
# at startup, and /readyz below retries lazily forever after, so a Mongo
# pod that's slow to boot no longer permanently strands this service at
# 0/1 Ready.
def connect_mongo(retries=5, delay_seconds=2):
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print(f"[audit-service] MongoDB connected -> database '{MONGO_DB}' (attempt {attempt}/{retries})")
            return client, client[MONGO_DB]
        except ServerSelectionTimeoutError as exc:
            print(f"[audit-service] MongoDB connection attempt {attempt}/{retries} failed: {exc}")
            if attempt < retries:
                time.sleep(delay_seconds)
    print(f"[audit-service] MongoDB still unreachable after {retries} attempts; "
          f"will keep retrying lazily on every /readyz check")
    return None, None


mongo_client, db = connect_mongo()


def init_db():
    if db is None:
        return
    if 'audit_logs' not in db.list_collection_names():
        db.create_collection('audit_logs')
        db['audit_logs'].create_index('user_id')
        db['audit_logs'].create_index('timestamp')
        print("[audit-service] audit_logs collection + indexes created")


init_db()


def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'missing bearer token'}), 401
        token = auth_header.split(' ', 1)[1]
        try:
            request.claims = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        except jwt.InvalidTokenError:
            return jsonify({'error': 'invalid token'}), 401
        return f(*args, **kwargs)
    return wrapper


# ==================== WRITE (called by other services, no auth) ====
# Deliberately unauthenticated: this endpoint is only reachable from
# inside the cluster (ClusterIP, no Ingress route to it), and requiring
# every caller to pass a token here would mean auth-service would have to
# generate a *service* token for itself just to log its own login events
# -- unnecessary complexity for an internal fire-and-forget call. In a
# real production system this is where you'd add mTLS between services
# (e.g. via a service mesh like Istio/Linkerd) rather than app-level auth.
@app.route('/api/logs', methods=['POST'])
def create_log():
    data = request.get_json(force=True, silent=True) or {}
    db['audit_logs'].insert_one({
        'user_id': data.get('user_id'),
        'action': data.get('action', 'UNKNOWN'),
        'details': data.get('details', ''),
        'source': data.get('source', 'unknown-service'),
        'timestamp': datetime.utcnow(),
    })
    return jsonify({'message': 'logged'}), 201


# ==================== READ (admin only, called by the frontend) ====
@app.route('/api/logs', methods=['GET'])
@token_required
def list_logs():
    if request.claims.get('role') != 'admin':
        return jsonify({'error': 'admin role required'}), 403
    limit = min(int(request.args.get('limit', 50)), 200)
    logs = list(db['audit_logs'].find().sort('timestamp', -1).limit(limit))
    for entry in logs:
        entry['_id'] = str(entry['_id'])
        entry['timestamp'] = entry['timestamp'].isoformat()
    return jsonify(logs), 200


@app.route('/healthz')
def healthz():
    return jsonify({'status': 'alive', 'service': 'audit-service'}), 200


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
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5003)),
             debug=os.getenv('FLASK_ENV', 'development') == 'development')
