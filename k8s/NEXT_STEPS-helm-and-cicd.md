# Next: Helm chart + GitHub Actions CI/CD

Once everything in `k8s/` deploys cleanly on Minikube (`./k8s/deploy-minikube.sh`
+ `./k8s/validate.sh` both green), this is the path forward. Nothing here is
built yet — it's the plan for the next iteration.

## Phase 1 — Helm chart

**Goal:** turn the 17 static YAML files into one templated, versioned,
environment-aware chart.

1. `helm create rajeshapp` — scaffolds `Chart.yaml`, `values.yaml`,
   `templates/`.
2. Move each `k8s/*.yaml` into `templates/`, one logical group per file
   (`templates/mongo/`, `templates/auth/`, `templates/grievance/`,
   `templates/audit/`, `templates/frontend/`, `templates/networkpolicy.yaml`,
   `templates/ingress.yaml`).
3. Replace every hardcoded literal with a `{{ .Values.* }}` reference:
   - image repo/tag → `.Values.<service>.image.repository` / `.tag`
   - replica counts → `.Values.<service>.replicaCount`
   - resource requests/limits → `.Values.<service>.resources`
   - `MONGO_URI`, `JWT_SECRET`, etc. → **do not** put real values in
     `values.yaml` in git; template the Secret so values are passed at
     install time (`--set` or `-f values-secret.yaml` that's gitignored),
     or template it to pull from an already-existing Kubernetes Secret via
     `existingSecret:`.
4. One `values-minikube.yaml` and one `values-production.yaml`:
   - `imagePullPolicy`: `IfNotPresent` (minikube) vs pinned digest (prod)
   - `ingress.host`: `rajeshapp.local` vs your real domain
   - `resources`: smaller in minikube, real sizing in prod
   - `networkPolicy.enabled`: `false` on minikube unless running
     `--cni=calico`, `true` in prod
5. Validate with `helm template . -f values-minikube.yaml | kubectl apply
   --dry-run=client -f -` before ever running `helm install` for real.
6. `helm install rajeshapp . -f values-minikube.yaml -n rajeshapp
   --create-namespace` replaces `deploy-minikube.sh`'s manifest-apply steps
   (the image build/load steps stay, or move into CI — see Phase 2).

## Phase 2 — GitHub Actions

**Goal:** every PR is validated automatically; every merge to `main`
deploys itself, with no one running `kubectl apply` by hand.

### `ci.yaml` — runs on every pull request
1. Checkout code.
2. For each of the 4 services: install deps, run `flake8`/`pytest` if tests
   exist, `docker build` to confirm the image still builds cleanly.
3. `helm lint` and `helm template` the chart to catch templating errors
   before merge.
4. (Optional) spin up a `kind` cluster in the runner and
   `helm install --dry-run` against it for a closer-to-real validation.

### `cd.yaml` — runs on merge to `main`
1. Build and tag each service image with the git SHA
   (`ghcr.io/<org>/auth-service:<sha>`), push to GitHub Container Registry
   (or ECR if targeting AWS).
2. `helm upgrade --install rajeshapp ./helm/rajeshapp -f values-production.yaml
   --set auth.image.tag=<sha> --set grievance.image.tag=<sha> ...` against
   the target cluster, using a kubeconfig stored in GitHub Actions Secrets
   (`KUBE_CONFIG_PROD`, base64-encoded).
3. Real secrets (`JWT_SECRET`, `MONGO_ROOT_PASSWORD`, etc.) come from GitHub
   Actions encrypted secrets, passed via `--set-string` at deploy time —
   never written into any file in the repo, matching the warning already in
   `03-secret.yaml`.
4. Post-deploy: run `./k8s/validate.sh`-equivalent checks against the live
   cluster as a smoke test; fail the pipeline (and consider an automatic
   `helm rollback`) if health checks don't pass within a timeout.

## Suggested order of work

1. Get Minikube fully green with the manifests in this zip.
2. Convert to Helm, keep testing on Minikube via `helm install`.
3. Add `ci.yaml` only (build+lint, no deploy) — safe, no cluster credentials
   needed yet.
4. Stand up one real target environment (EKS/GKE/etc.), get one manual
   `helm upgrade --install` working against it by hand.
5. Only then add `cd.yaml` — automation should follow a manual process
   you've already proven works, not replace one you haven't.

Say the word when you're ready for the actual `helm/` chart files or the two
`.github/workflows/*.yaml` files, and we'll build those out the same way —
file by file, fully commented.
