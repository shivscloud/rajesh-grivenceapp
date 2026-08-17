# rajeshapp Helm chart

Templated version of the 17 files in `k8s/`. Same objects, same behavior —
now driven by one `values.yaml` instead of hand-edited YAML per environment.

## Layout

```
rajeshapp/
├── Chart.yaml              chart metadata (name, version)
├── values.yaml              every configurable default lives here
├── README.md                 this file
└── templates/
    ├── namespace.yaml
    ├── configmap.yaml
    ├── secret.yaml
    ├── mongo.yaml            StatefulSet + headless Service
    ├── deployment.yaml       ONE template, loops over .Values.services
    ├── service.yaml          Service + HPA, same loop
    ├── ingress.yaml          only rendered if ingress.enabled
    ├── networkpolicy.yaml    only rendered if networkPolicies.enabled
    └── NOTES.txt              printed after `helm install`
```

The 4 raw `*-deployment.yaml` / `*-service.yaml` files became **one**
`deployment.yaml` and **one** `service.yaml` that loop over the
`services:` map in `values.yaml`. Adding a 5th microservice later means
adding one block to `values.yaml` — not writing two new template files.

## Install

```bash
cd rajeshapp
helm lint .                                   # catches template errors
helm template . | less                        # see the exact YAML it would apply
helm install rajeshapp . --create-namespace   # namespace.yaml template also creates it
kubectl get all -n rajeshapp
```

## Upgrade after a code change

```bash
docker build -t rajeshapp/auth-service:v2 ./auth-service
minikube image load rajeshapp/auth-service:v2       # Minikube only
helm upgrade rajeshapp . --set image.tag=v2
```

## Environments

```bash
helm install rajeshapp . -f values.yaml -f values.yaml
helm upgrade --install rajeshapp . -f values.yaml -f values-production.yaml \
  --set secrets.jwtSecret=$JWT_SECRET \
  --set secrets.mongoPassword=$MONGO_PASSWORD
```

Real secrets are passed with `--set`/`--set-string` at install/upgrade
time (from your CI secret store), never committed to a values file — see
the comment at the top of `templates/secret.yaml`.

## Uninstall

```bash
helm uninstall rajeshapp -n rajeshapp
```

This deletes everything Helm created **except** the mongo PVC (by design —
Kubernetes never auto-deletes PersistentVolumeClaims, so a bad
`helm uninstall` can't wipe your database by accident):

```bash
kubectl get pvc -n rajeshapp
kubectl delete pvc mongo-data-mongo-0 -n rajeshapp   # only if you really want to lose the data
```
