#!/usr/bin/env bash
# validate.sh
# ---------------------------------------------------------------------------
# Quick post-deploy health check for every object in the "rajeshapp"
# namespace. Run after deploy-minikube.sh, or any time you want to sanity
# check the cluster state. Non-destructive - read-only kubectl calls only.
set -uo pipefail
NAMESPACE="rajeshapp"

echo "== Namespace =="
kubectl get namespace "$NAMESPACE" || { echo "FAIL: namespace missing"; exit 1; }

echo ""
echo "== Pods =="
kubectl get pods -n "$NAMESPACE" -o wide

echo ""
echo "== Deployments =="
kubectl get deployments -n "$NAMESPACE"

echo ""
echo "== StatefulSets =="
kubectl get statefulsets -n "$NAMESPACE"

echo ""
echo "== Services =="
kubectl get services -n "$NAMESPACE"

echo ""
echo "== PodDisruptionBudgets =="
kubectl get pdb -n "$NAMESPACE"

echo ""
echo "== HorizontalPodAutoscalers (blank targets = metrics-server not ready yet) =="
kubectl get hpa -n "$NAMESPACE"

echo ""
echo "== Ingress =="
kubectl get ingress -n "$NAMESPACE"

echo ""
echo "== ResourceQuota usage =="
kubectl describe resourcequota rajeshapp-quota -n "$NAMESPACE"

echo ""
echo "== Any pod not Running / not Ready =="
kubectl get pods -n "$NAMESPACE" --field-selector=status.phase!=Running
kubectl get pods -n "$NAMESPACE" -o json \
  | grep -B5 '"ready": false' >/dev/null 2>&1 && echo "(see above for details)" || echo "none found"

echo ""
echo "== Direct health-endpoint checks via port-forward (5s each, auto-cleanup) =="
for svc_port in "auth-service:5001" "grievance-service:5002" "audit-service:5003" "frontend-service:5000"; do
  svc="${svc_port%%:*}"
  port="${svc_port##*:}"
  echo "-- $svc --"
  kubectl port-forward -n "$NAMESPACE" "svc/$svc" "$port:$port" >/tmp/pf-$svc.log 2>&1 &
  pf_pid=$!
  sleep 2
  curl -sf "http://localhost:$port/healthz" && echo " [healthz OK]" || echo " [healthz FAILED]"
  curl -sf "http://localhost:$port/readyz"  && echo " [readyz OK]"  || echo " [readyz FAILED]"
  kill "$pf_pid" 2>/dev/null
  wait "$pf_pid" 2>/dev/null
done

echo ""
echo "== Done. For a failing pod, next steps: =="
echo "   kubectl describe pod <name> -n $NAMESPACE   # check Events at the bottom"
echo "   kubectl logs <name> -n $NAMESPACE           # add --previous if it already restarted"
