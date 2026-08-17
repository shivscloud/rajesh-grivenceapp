# Grievance Management System — Microservices Edition

The original single Flask app is now split into **4 independently
deployable services**, each with its own Dockerfile, its own Mongo
database, and its own Kubernetes Deployment + Service:

```
                              (browser)
                                 |
                                 | http://<minikube-ip>:30080   (NodePort)
                                 v
                       +-------------------+
                       |  frontend-service | :5000   (HTML, Flask sessions)
                       +-------------------+
                        |        |        |
              Bearer JWT|        |        | Bearer JWT
                        v        |        v
              +----------------+ |  +----------------+
              |  auth-service  | |  | audit-service  |  :5003
              |     :5001      | |  |  (ClusterIP,   |
              | (users, JWTs)  | |  |  internal only)|
              +----------------+ |  +----------------+
                        ^        v         ^
                        |  +----------------+
                        |  |grievance-service|:5002
                        |  |  (grievances)   |
                        |  +----------------+
                        |        |          |
                        +--------+----------+
                                 |
                                 v
                       +-------------------+
                       |  mongo (Stateful  |
                       |   Set, 1 replica) |
                       |  auth_db          |
                       |  grievance_db     |
                       |  audit_db         |
                       +-------------------+
```

| Service             | Owns                | Port | K8s Service type | Reachable from outside cluster? |
|----------------------|--------------------|------|-------------------|----------------------------------|
| `frontend-service`   | nothing (BFF/UI)   | 5000 | **NodePort**      | Yes — the only entrypoint |
| `auth-service`       | `users` collection | 5001 | ClusterIP         | No |
| `grievance-service`  | `grievances`       | 5002 | ClusterIP         | No |
| `audit-service`      | `audit_logs`       | 5003 | ClusterIP         | No |
| `mongo`               | all 3 databases   | 27017| Headless (ClusterIP: None) | No |

Every backend-to-backend call carries a JWT issued by `auth-service` on
login (`Authorization: Bearer <token>`), which `grievance-service` and
`audit-service` verify **locally** using a shared `JWT_SECRET` — no
service ever calls auth-service just to check "is this token real?".
That's the one idea worth understanding before reading the code: it's
what makes these 3 backend services independently scalable without
auth-service becoming a bottleneck every request has to round-trip
through.

## Project layout

```
auth-service/        Flask API — register/login/JWT issuance, user directory
grievance-service/    Flask API — grievance CRUD
audit-service/        Flask API — append-only action log
frontend-service/     Flask app — renders the HTML you already had, calls the 3 APIs above
docker-compose.yml     Run all 4 + Mongo locally with plain Docker (no k8s needed)
k8s/                   Kubernetes manifests, numbered in apply order
k8s/deploy-minikube.sh One-shot build + deploy script for Minikube
```

## Step 0 — sanity check locally with docker-compose first

Skip straight to Minikube if you want, but this is the fastest possible
feedback loop while you're still iterating on the code:

```bash
docker compose up --build
# open http://localhost:5000, register a user, file a grievance
```

`Ctrl+C`, then `docker compose down -v` to tear it down (the `-v` also
drops the Mongo volume, so you get a clean database next time).

## Step 1 — install Minikube + kubectl (skip if already installed)

```bash
# macOS
brew install minikube kubectl

# Linux
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl
```

## Step 2 — deploy everything with one script

```bash
chmod +x k8s/deploy-minikube.sh
./k8s/deploy-minikube.sh
```

This script (fully commented, open it and read along):
1. Starts Minikube if it isn't already running.
2. Runs `eval $(minikube docker-env)` so `docker build` builds images
   straight into Minikube's own Docker daemon — no image registry
   needed for local testing.
3. Builds all 4 images: `auth-service:v1`, `grievance-service:v1`,
   `audit-service:v1`, `frontend-service:v1`.
4. Applies the k8s manifests **in dependency order**: namespace ->
   config/secrets -> Mongo -> auth-service -> grievance-service ->
   audit-service -> frontend-service.
5. Waits for every rollout to finish, then opens a tunnel to
   `frontend-service` and prints the URL to open in your browser.

If you'd rather run each step yourself to see what's happening:

```bash
minikube start
eval $(minikube docker-env)
docker build -t auth-service:v1      ./auth-service
docker build -t grievance-service:v1 ./grievance-service
docker build -t audit-service:v1     ./audit-service
docker build -t frontend-service:v1  ./frontend-service

kubectl apply -f k8s/00-namespace.yaml
kubectl apply -f k8s/01-configmap.yaml
kubectl apply -f k8s/02-secret.yaml
kubectl apply -f k8s/03-mongo-statefulset.yaml
kubectl apply -f k8s/04-mongo-service.yaml
kubectl apply -f k8s/10-auth-deployment.yaml
kubectl apply -f k8s/11-auth-service.yaml
kubectl apply -f k8s/12-grievance-deployment.yaml
kubectl apply -f k8s/13-grievance-service.yaml
kubectl apply -f k8s/14-audit-deployment.yaml
kubectl apply -f k8s/15-audit-service.yaml
kubectl apply -f k8s/16-frontend-deployment.yaml
kubectl apply -f k8s/17-frontend-service.yaml

kubectl get pods -n grievance-system -w   # Ctrl+C once everything is Running/Ready
minikube service frontend-service -n grievance-system
```

## Step 3 — poke around and learn the moving parts

```bash
# See every object this project created
kubectl get all -n grievance-system

# Watch a service's logs live
kubectl logs -f -n grievance-system deployment/grievance-service

# Get a shell-less curl straight to an INTERNAL-only service, to prove
# ClusterIP really isn't reachable from your laptop directly...
curl http://$(minikube ip):5001/healthz     # <-- this will just hang/fail, on purpose

# ...then reach it properly via port-forward instead:
kubectl port-forward -n grievance-system svc/auth-service 5001:5001 &
curl http://localhost:5001/healthz          # now it answers

# Force a pod to restart and watch the Service route around it with zero
# dropped requests from the frontend's perspective (readiness probes at work):
kubectl delete pod -n grievance-system -l app=grievance-service --field-selector status.phase=Running -l app=grievance-service | head -1
kubectl get pods -n grievance-system -w
```

### Why NodePort for frontend-service but ClusterIP for the other three?

Short version (full version is a comment block right above
`spec.type: NodePort` in `k8s/17-frontend-service.yaml`):
`frontend-service` is the only service a browser ever talks to directly,
so it's the only one that needs a door cut through the cluster's network
boundary to the outside world. `NodePort` opens a fixed port
(`30080` here) on **every** Minikube node's real network interface and
forwards it to the Service, which then load-balances across the
`frontend-service` pods. The other 3 services stay `ClusterIP`
(internal-only) on purpose — there's no reason `auth-service`'s
`/api/login` should be curl-able from outside the cluster when the
frontend already fronts it.

## Step 4 — later: moving this to EKS (AWS)

You won't rewrite any application code for this — only the "how do I
get traffic in / where do images live" pieces change:

1. **Push images to a real registry** (Minikube's `imagePullPolicy: Never`
   trick only works locally). Create an ECR repo per service and push:
   ```bash
   aws ecr create-repository --repository-name grievance/auth-service
   docker tag auth-service:v1 <account-id>.dkr.ecr.<region>.amazonaws.com/grievance/auth-service:v1
   docker push <account-id>.dkr.ecr.<region>.amazonaws.com/grievance/auth-service:v1
   # repeat per service
   ```
2. **Update each Deployment's `image:`** to the ECR URI, and change
   `imagePullPolicy: Never` -> `IfNotPresent` (or drop it, `IfNotPresent`
   is the default) in all 4 `*-deployment.yaml` files.
3. **Create the cluster**: `eksctl create cluster --name grievance --nodes 3`
   (or Terraform, if that's your team's standard).
4. **Swap storage**: Minikube's `mongo` PersistentVolumeClaim uses
   whatever default StorageClass Minikube ships with. On EKS you'll want
   the `gp3` (or `gp2`) EBS StorageClass via the AWS EBS CSI driver —
   add `storageClassName: gp3` under `volumeClaimTemplates` in
   `03-mongo-statefulset.yaml`. For anything beyond a learning/demo
   deployment, replace the single-replica Mongo StatefulSet with a
   managed database (Amazon DocumentDB, which speaks the Mongo wire
   protocol) instead of running Mongo yourself in-cluster.
5. **Swap `frontend-service`'s NodePort for a real entrypoint**: either
   change `k8s/17-frontend-service.yaml`'s `type:` to `LoadBalancer`
   (provisions an AWS NLB automatically), or — the more common
   production pattern — install the **AWS Load Balancer Controller**
   and apply `k8s/18-ingress.yaml` with an `alb` ingress class instead
   of `nginx`, which provisions an Application Load Balancer with proper
   host-based routing and (optionally) ACM-managed TLS.
6. **Secrets**: replace the plaintext `02-secret.yaml` with either
   AWS Secrets Manager + the External Secrets Operator, or `eksctl`'s
   built-in IRSA + `kubectl create secret` from your CI pipeline — never
   commit real values the way this repo's placeholder file does.
7. Everything else — the namespace, the ConfigMap, all 4 Deployments'
   probes/resources, the ClusterIP Services, the JWT-based service-to-
   service auth — carries over to EKS completely unchanged, because none
   of it was ever Minikube-specific. That's the point of building on
   plain Kubernetes primitives from day one.

## Local development without any containers at all

Each service still runs standalone for fast iteration:

```bash
cd auth-service && cp .env.example .env && pip install -r requirements.txt && python app.py
# repeat for grievance-service, audit-service, frontend-service in separate terminals
# (you'll also need a local MongoDB running on localhost:27017 — see docker-compose.yml)
```
