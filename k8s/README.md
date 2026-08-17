# k8s/ — rajeshapp production-style manifests

Namespace: **`rajeshapp`** (everything below lives inside it).

## File order (this is also the apply order `deploy-minikube.sh` uses)

| File | What it creates | Notes |
|---|---|---|
| `00-namespace.yaml` | Namespace `rajeshapp` | everything else lives here |
| `01-resourcequota-limitrange.yaml` | ResourceQuota + LimitRange | caps total & per-container resource usage |
| `02-configmap.yaml` | ConfigMap `rajeshapp-config` | non-secret config, service-discovery URLs |
| `03-secret.yaml` | Secret `rajeshapp-secrets` | **placeholder creds** — see the warning inside the file |
| `04-mongo-statefulset.yaml` | StatefulSet `mongo` | 1 replica; production note on real replica sets inside |
| `05-mongo-service.yaml` | headless Service `mongo` | gives Mongo pods stable DNS names |
| `10-auth-deployment.yaml` | SA + Deployment + PDB `auth-service` | 2 replicas, signs JWTs |
| `11-auth-service.yaml` | ClusterIP Service `auth-service` | internal only |
| `20-grievance-deployment.yaml` | SA + Deployment + PDB `grievance-service` | 2 replicas, verifies JWTs |
| `21-grievance-service.yaml` | ClusterIP Service `grievance-service` | internal only |
| `30-audit-deployment.yaml` | SA + Deployment `audit-service` | 1 replica, no PDB (see comment inside) |
| `31-audit-service.yaml` | ClusterIP Service `audit-service` | internal only |
| `40-frontend-deployment.yaml` | SA + Deployment + PDB `frontend-service` | 2 replicas, the only public-facing app |
| `41-frontend-service.yaml` | ClusterIP Service `frontend-service` | **not** NodePort — see comment inside |
| `50-network-policies.yaml` | 6 NetworkPolicy objects | default-deny + explicit allow-list; Minikube caveat inside |
| `60-ingress.yaml` | Ingress `rajeshapp-ingress` | single public entry point, TLS block ready to uncomment |
| `70-hpa.yaml` | 3 HorizontalPodAutoscalers | auth/grievance/frontend, needs metrics-server |
| `deploy-minikube.sh` | — | one-shot build + deploy script for local testing |
| `validate.sh` | — | read-only post-deploy health check, run after every deploy |
| `NEXT_STEPS-helm-and-cicd.md` | — | roadmap for turning this into a Helm chart + GitHub Actions |

## Quickstart (Minikube)

```bash
./k8s/deploy-minikube.sh
./k8s/validate.sh
```

## Manual, file-by-file validation

Each file's own header comment documents exactly what to check and how to
troubleshoot it if something's wrong — that's the intended first place to
look before searching elsewhere. In short, after applying any Deployment:

```bash
kubectl rollout status deployment/<name> -n rajeshapp --timeout=120s
kubectl get pods -n rajeshapp -l app=<name>
kubectl port-forward -n rajeshapp svc/<name> <port>:<port>
curl http://localhost:<port>/healthz
curl http://localhost:<port>/readyz
```

If a pod isn't `Running`/ready:
```bash
kubectl describe pod <pod-name> -n rajeshapp   # Events section, bottom of output
kubectl logs <pod-name> -n rajeshapp           # add --previous if it already restarted
```

## What "production-style" means in this manifest set

- Namespaced `ResourceQuota` + `LimitRange` so no single workload can starve
  the rest of the cluster.
- Every Deployment: explicit `RollingUpdate` strategy (`maxUnavailable: 0`),
  `securityContext` (non-root, no privilege escalation, read-only root
  filesystem, all capabilities dropped), a dedicated `ServiceAccount` with
  `automountServiceAccountToken: false`, `startupProbe` +
  `livenessProbe` + `readinessProbe`, and soft pod anti-affinity.
- `PodDisruptionBudget` on every multi-replica Deployment so cluster
  maintenance can't take an entire service down at once.
- `NetworkPolicy` default-deny plus explicit allow rules — the "only
  frontend can reach the backend services" rule is now enforced at the
  network layer, not just a comment.
- Ingress-fronted, TLS-ready public entry point instead of a raw NodePort.
- `HorizontalPodAutoscaler` on the three user-traffic-facing services.

## What's still simplified on purpose (documented, not hidden)

- Mongo is a single replica, not a 3-node replica set — see the comment in
  `04-mongo-statefulset.yaml` for what a real HA setup needs.
- `03-secret.yaml` holds real-looking placeholder values in git — fine for
  Minikube, **not** how you deploy to a real cluster. See that file's
  warning and `NEXT_STEPS-helm-and-cicd.md` for where real secrets belong.
- Egress NetworkPolicies aren't included — only ingress is locked down for
  now (see the caveat in `50-network-policies.yaml`).
