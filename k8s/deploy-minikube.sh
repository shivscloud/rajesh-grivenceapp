#!/usr/bin/env bash
# deploy-minikube.sh
# ---------------------------------------------------------------------------
# Builds all 4 microservice images and deploys the whole rajeshapp stack onto
# a local Minikube cluster, using the SAME manifests you'd point at a real
# cluster (production-style image references, ClusterIP-only frontend behind
# an Ingress, NetworkPolicies, etc) - the only Minikube-specific step is how
# the images get onto the node (`minikube image load` below), since there's
# no real registry in this local setup.
#
# Usage (from the project root, the folder that contains k8s/):
#   ./k8s/deploy-minikube.sh
# ---------------------------------------------------------------------------

set -euo pipefail  # exit immediately on any error, undefined var, or failed pipe stage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
NAMESPACE="rajeshapp"

echo "==> Checking prerequisites..."
command -v minikube >/dev/null || { echo "minikube is not installed"; exit 1; }
command -v kubectl  >/dev/null || { echo "kubectl is not installed"; exit 1; }
command -v docker   >/dev/null || { echo "docker is not installed"; exit 1; }

echo "==> Ensuring Minikube is running..."
# --cni=calico: without this, the NetworkPolicy objects in
# 50-network-policies.yaml apply with no error but are NOT actually
# enforced (Minikube's default CNI ignores them) - see that file's comment.
if ! minikube status >/dev/null 2>&1; then
    minikube start --cpus=4 --memory=4096 --cni=calico
fi

echo "==> Enabling required addons (ingress, metrics-server)..."
minikube addons enable ingress
minikube addons enable metrics-server

echo "==> Building all 4 microservice images with the host Docker daemon..."
# Built normally (NOT inside Minikube's docker-env) because the production
# manifests use imagePullPolicy: IfNotPresent + `minikube image load` below,
# which is closer to "push to a registry, cluster pulls it" than the
# dev-only "build straight inside the cluster's daemon" shortcut was.
docker build -t rajeshapp/auth-service:v1      "$PROJECT_ROOT/auth-service"
docker build -t rajeshapp/grievance-service:v1 "$PROJECT_ROOT/grievance-service"
docker build -t rajeshapp/audit-service:v1     "$PROJECT_ROOT/audit-service"
docker build -t rajeshapp/frontend-service:v1  "$PROJECT_ROOT/frontend-service"

echo "==> Loading images into the Minikube node (stand-in for a registry pull)..."
minikube image load rajeshapp/auth-service:v1
minikube image load rajeshapp/grievance-service:v1
minikube image load rajeshapp/audit-service:v1
minikube image load rajeshapp/frontend-service:v1

echo "==> Applying namespace, quota/limits, config and secrets..."
# Applied individually (not `kubectl apply -f k8s/`) so the Namespace,
# ResourceQuota/LimitRange, ConfigMap and Secret unambiguously exist before
# anything that references them is created.
kubectl apply -f "$SCRIPT_DIR/00-namespace.yaml"
kubectl apply -f "$SCRIPT_DIR/01-resourcequota-limitrange.yaml"
kubectl apply -f "$SCRIPT_DIR/02-configmap.yaml"
kubectl apply -f "$SCRIPT_DIR/03-secret.yaml"

echo "==> Applying MongoDB (StatefulSet + headless Service)..."
kubectl apply -f "$SCRIPT_DIR/04-mongo-statefulset.yaml"
kubectl apply -f "$SCRIPT_DIR/05-mongo-service.yaml"
echo "==> Waiting for MongoDB to be ready before starting the app services..."
kubectl rollout status statefulset/mongo -n "$NAMESPACE" --timeout=120s

echo "==> Applying auth-service..."
kubectl apply -f "$SCRIPT_DIR/10-auth-deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/11-auth-service.yaml"

echo "==> Applying grievance-service..."
kubectl apply -f "$SCRIPT_DIR/20-grievance-deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/21-grievance-service.yaml"

echo "==> Applying audit-service..."
kubectl apply -f "$SCRIPT_DIR/30-audit-deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/31-audit-service.yaml"

echo "==> Applying frontend-service..."
kubectl apply -f "$SCRIPT_DIR/40-frontend-deployment.yaml"
kubectl apply -f "$SCRIPT_DIR/41-frontend-service.yaml"

echo "==> Waiting for all 4 Deployments to roll out..."
kubectl rollout status deployment/auth-service      -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/grievance-service -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/audit-service     -n "$NAMESPACE" --timeout=120s
kubectl rollout status deployment/frontend-service  -n "$NAMESPACE" --timeout=120s

echo "==> Applying NetworkPolicies (enforced only if the cluster CNI supports it)..."
kubectl apply -f "$SCRIPT_DIR/50-network-policies.yaml"

echo "==> Applying Ingress..."
kubectl apply -f "$SCRIPT_DIR/60-ingress.yaml"

echo "==> Applying HorizontalPodAutoscalers (needs metrics-server, enabled above)..."
kubectl apply -f "$SCRIPT_DIR/70-hpa.yaml"

echo ""
echo "==> Deployment complete. Current pods:"
kubectl get pods -n "$NAMESPACE" -o wide

echo ""
echo "==> To reach the app, add this to /etc/hosts once:"
echo "    echo \"\$(minikube ip) rajeshapp.local\" | sudo tee -a /etc/hosts"
echo "    then open http://rajeshapp.local"
echo ""
echo "==> Or, without touching /etc/hosts, port-forward instead:"
echo "    kubectl -n $NAMESPACE port-forward svc/frontend-service 5000:5000"
echo "    then open http://localhost:5000"
