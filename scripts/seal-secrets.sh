#!/usr/bin/env bash
# Creates the Secrets of ADR 0005 as SealedSecrets under k8s/secrets/ (safe to commit).
# For a FRESH cluster: it generates new database passwords, and the db-bootstrap
# Job sets the roles' passwords once, so re-running this against a cluster that
# already has a database would desynchronise them.
#
# Prerequisites: kubeseal, and the controller installed:
#   helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
#   helm install sealed-secrets sealed-secrets/sealed-secrets -n kube-system
#   kubectl -n kube-system rollout status deploy/sealed-secrets
# Back up the controller key (do NOT commit it) or `minikube delete` makes every
# sealed file unreadable:
#   kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > ~/af-sealed-key.backup.yaml
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=k8s/secrets
if [[ -d $OUT && -z "${FORCE:-}" ]]; then echo "$OUT exists; FORCE=1 to overwrite"; exit 1; fi
mkdir -p $OUT/models $OUT/data $OUT/app

: "${GROQ_API_KEY:=}"
if [[ -z $GROQ_API_KEY ]]; then read -rsp "Groq API key: " GROQ_API_KEY; echo; fi
PGSUPER="$(openssl rand -base64 24)"
MIG="$(openssl rand -base64 24)"; APP="$(openssl rand -base64 24)"; BAK="$(openssl rand -base64 24)"

seal() { # ns name KEY=VAL...
  local ns=$1 name=$2; shift 2; local args=()
  for kv in "$@"; do args+=(--from-literal="$kv"); done
  kubectl create secret generic "$name" -n "$ns" "${args[@]}" --dry-run=client -o yaml \
    | kubeseal --controller-name sealed-secrets --controller-namespace kube-system --format yaml \
    > "$OUT/$ns/$name.sealed.yaml"
  echo "wrote $OUT/$ns/$name.sealed.yaml"
}
seal models groq-credentials     GROQ_API_KEY="$GROQ_API_KEY"
seal data   postgres-credentials POSTGRES_USER=af POSTGRES_PASSWORD="$PGSUPER" POSTGRES_DB=af
seal data   db-role-credentials  DB_NAME=af MIGRATOR_PASSWORD="$MIG" APP_PASSWORD="$APP" BACKUP_PASSWORD="$BAK"
seal app    db-role-credentials  DB_NAME=af MIGRATOR_PASSWORD="$MIG" APP_PASSWORD="$APP"   # no backup password in app

cat > $OUT/kustomization.yaml <<'YAML'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - models/groq-credentials.sealed.yaml
  - data/postgres-credentials.sealed.yaml
  - data/db-role-credentials.sealed.yaml
  - app/db-role-credentials.sealed.yaml
YAML
