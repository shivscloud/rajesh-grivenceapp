#!/bin/bash
set -euxo pipefail

exec > >(tee /var/log/user-data.log) 2>&1

REPO_URL="${repo_url}"
APP_HOST_PORT="${app_node_port_host}"
APP_DIR="/opt/rajesh-grievanceapp"
KIND_VERSION="v0.23.0"
KUBECTL_VERSION="v1.30.0"
NAMESPACE="${k8s_namespace}"
HELM_RELEASE="${helm_release_name}"
HELM_CHART_PATH="${helm_chart_path}"

# ---------------------------------------------------------
# 1. Base packages + Docker
# ---------------------------------------------------------
apt-get update -y
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

usermod -aG docker ubuntu
systemctl enable docker
systemctl start docker

# ---------------------------------------------------------
# 2. kubectl
# ---------------------------------------------------------
curl -LO "https://dl.k8s.io/release/$${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# ---------------------------------------------------------
# 3. kind
# ---------------------------------------------------------
curl -Lo /usr/local/bin/kind "https://kind.sigs.k8s.io/dl/$${KIND_VERSION}/kind-linux-amd64"
chmod +x /usr/local/bin/kind

# ---------------------------------------------------------
# 3b. Helm
# ---------------------------------------------------------
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 -o /tmp/get-helm-3
chmod +x /tmp/get-helm-3
/tmp/get-helm-3

# ---------------------------------------------------------
# 4. Clone the app
# ---------------------------------------------------------
git clone "$${REPO_URL}" "$${APP_DIR}"
cd "$${APP_DIR}"

# ---------------------------------------------------------
# 5. kind cluster config - map the frontend NodePort (30080)
#    to a port on the EC2 host itself
# ---------------------------------------------------------
cat > /root/kind-config.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: $${APP_HOST_PORT}
    protocol: TCP
EOF

kind create cluster --name grievance --config /root/kind-config.yaml

# ---------------------------------------------------------
# 6. Build the 4 service images.
#
# IMPORTANT: tagged as "rajeshapp/<service>:v1" - this MUST
# match helm/rajeshapp/values.yaml's `image.registry` (default
# "rajeshapp") + `image.tag` (default "v1"), because that's
# exactly the string the Deployment template builds:
#   "{{ .Values.image.registry }}/{{ $name }}:{{ .Values.image.tag }}"
# It also matches every raw k8s/*-deployment.yaml manifest and
# deploy-minikube.sh in this same repo, so all three deploy
# paths (raw kubectl, minikube script, this EC2/kind script)
# stay consistent. If you ever change values.yaml's
# image.registry/image.tag, update the tags below (and the
# --set overrides further down) to match.
# ---------------------------------------------------------
IMAGE_REGISTRY="rajeshapp"
IMAGE_TAG="v1"

docker build -t "$${IMAGE_REGISTRY}/auth-service:$${IMAGE_TAG}"      ./auth-service
docker build -t "$${IMAGE_REGISTRY}/grievance-service:$${IMAGE_TAG}" ./grievance-service
docker build -t "$${IMAGE_REGISTRY}/audit-service:$${IMAGE_TAG}"     ./audit-service
docker build -t "$${IMAGE_REGISTRY}/frontend-service:$${IMAGE_TAG}"  ./frontend-service

# ---------------------------------------------------------
# 7. Load images into the kind cluster's node
#    (equivalent of minikube's docker-env trick, for kind)
# ---------------------------------------------------------
kind load docker-image "$${IMAGE_REGISTRY}/auth-service:$${IMAGE_TAG}"      --name grievance
kind load docker-image "$${IMAGE_REGISTRY}/grievance-service:$${IMAGE_TAG}" --name grievance
kind load docker-image "$${IMAGE_REGISTRY}/audit-service:$${IMAGE_TAG}"     --name grievance
kind load docker-image "$${IMAGE_REGISTRY}/frontend-service:$${IMAGE_TAG}"  --name grievance

# ---------------------------------------------------------
# 8. Deploy via the repo's own Helm chart (helm/rajeshapp)
#
# --set image.registry / image.tag / image.pullPolicy pin the
# release to the exact images just built and loaded above, so
# this doesn't silently drift if values.yaml's defaults ever
# change. pullPolicy=IfNotPresent is enough (not Never) because
# the image is already present on the node after `kind load`.
# ---------------------------------------------------------
export KUBECONFIG=/root/.kube/config

helm upgrade --install "$${HELM_RELEASE}" "$${HELM_CHART_PATH}" \
  --namespace "$${NAMESPACE}" --create-namespace \
  --set image.registry="$${IMAGE_REGISTRY}" \
  --set image.tag="$${IMAGE_TAG}" \
  --set image.pullPolicy=IfNotPresent \
  --wait --timeout 5m

kubectl -n "$${NAMESPACE}" rollout status deployment --all --timeout=300s || true

# Make kubeconfig usable for the ubuntu user too
mkdir -p /home/ubuntu/.kube
cp /root/.kube/config /home/ubuntu/.kube/config
chown -R ubuntu:ubuntu /home/ubuntu/.kube

echo "Bootstrap complete. Helm release '$${HELM_RELEASE}' installed in namespace '$${NAMESPACE}'. App should be reachable on port $${APP_HOST_PORT}." > /var/log/user-data-complete.log
