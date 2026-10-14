# ADR 0006: Default-deny network policies, Calico, Sealed Secrets

## Status

Accepted. Completes the network half of ADR 0005.

## Decision

1. **CNI: Calico** (`minikube start --cni=calico`; k3s's bundled controller
   later). kindnet accepts NetworkPolicy objects and silently ignores them.
   Cilium FQDN policy stays deferred (ADR 0005): the llm-groq gateway already
   confines the orchestrator to one host.
2. **Every zone: default-deny ingress and egress, plus DNS**, then explicit
   allows in `k8s/base/<zone>/networkpolicies.yaml` (hardening lives in the
   base, ADR 0004).
3. **Allowed paths:** ingress controller -> orchestrator; orchestrator ->
   conversation-db, vector-store, llm-local, llm-groq, tool-weather,
   tool-finance; db-bootstrap and postgres-backup -> conversation-db.
   Nothing else crosses zones. `llm-groq` is the only pod with internet egress
   (TCP 443, public addresses only). `tool-finance` accepts one caller on one
   port and has no egress.
4. **Secrets:** Sealed Secrets (`scripts/seal-secrets.sh`). Same scoping as
   ADR 0005: `groq-credentials` only in `models`, `postgres-credentials` only
   in `data`, `db-role-credentials` in `data` and `app` (no backup password in
   `app`). The sealing key must be backed up outside git.
5. **Ingress** is opt-in via `k8s/components/ingress-nginx` (minikube) or
   `ingress-traefik` (k3s): TLS, timeouts, rate limit, basic auth, body limit.
6. **Tests:** `scripts/04-test-policies.sh`, run in CI on kind + Calico with
   stub workloads (`.github/workflows/network-policies.yml`), and by hand
   against the real cluster.

## Consequences

- Pulling Ollama models needs `k8s/optional/ollama-pull-egress.yaml` for the
  duration of the pull.
- A new workload that talks to another zone needs a policy line in the same PR.
- No `minikube` or `prod` overlay is added (ADR 0004: one overlay per real machine).
