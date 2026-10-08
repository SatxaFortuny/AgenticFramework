#!/usr/bin/env bash
# Reproduces the CI jobs on your machine.
#   scripts/ci-local.sh            lint, format, version check, unit tests, manifests
#   scripts/ci-local.sh --postgres also starts a throwaway Postgres and runs the postgres tests
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0
step() { echo; echo "==> $*"; }
run()  { "$@" || { echo "FAILED: $*"; fail=1; }; }

step "Chroma client/server versions"
run bash scripts/check-chroma-version.sh

step "ruff check"
run ruff check src/

step "ruff format --check"
run ruff format --check src/

step "unit tests"
run pytest -m "not integration and not postgres" -q

step "kubernetes manifests"
if command -v kubeconform >/dev/null && command -v kubectl >/dev/null; then
  kubectl kustomize . > /tmp/rendered.yaml && run kubeconform -strict -summary -ignore-missing-schemas /tmp/rendered.yaml
else
  echo "skipped: kubectl and/or kubeconform not installed"
fi

if [[ "${1:-}" == "--postgres" ]]; then
  step "postgres tests (throwaway container)"
  rt=$(command -v podman || command -v docker)
  name=af-pg-test
  trap '$rt rm -f $name >/dev/null 2>&1' EXIT
  $rt rm -f $name >/dev/null 2>&1
  $rt run -d --name $name -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=test -p 5433:5432 docker.io/library/postgres:16 >/dev/null
  for i in $(seq 1 30); do
    $rt exec $name pg_isready -U postgres -d test >/dev/null 2>&1 && break
    sleep 1
  done
  export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/test
  pytest -m postgres -rs -q | tee /tmp/pg.log
  if grep -Eq '[0-9]+ skipped' /tmp/pg.log; then echo "FAILED: postgres tests were skipped"; fail=1; fi
fi

echo
[[ $fail -eq 0 ]] && echo "All checks passed" || echo "Some checks failed"
exit $fail
