# ADR 0005: Four trust-zone namespaces, capability-named Services, a Groq gateway

## Status

Accepted. Network policies that enforce the zones are the next step (they need
a CNI that enforces them); until then this ADR gives the structure, Pod
Security enforcement, and credential scoping, but not network isolation.

## Context

Everything ran in the `default` namespace: any pod could reach any other pod,
and the Groq API key sat in the same namespace as the orchestrator. The
orchestrator is the riskiest workload (it feeds untrusted text to an LLM that
can call tools), and the MCP servers are code paths the model controls. The
cluster should be arranged so that compromising one of them does not hand over
the rest.

## Decision

1. **Four namespaces as trust zones**:

   | Namespace | Holds | Pod Security (enforce) |
   |-----------|-------|------------------------|
   | `app`     | orchestrator | `restricted` |
   | `data`    | postgres, chromadb, backups, db bootstrap | `baseline` |
   | `models`  | ollama, llm-groq gateway | `baseline` |
   | `tools`   | weather-mcp, finance-mcp | `restricted` |

   `baseline` is only where something needs it: Chroma's `fix-permissions`
   init container runs as root, and Ollama still runs as root (the GPU will
   need more). Every namespace `warn`s and `audit`s against `restricted`, so
   the gap stays visible instead of being forgotten.

2. **Services are named for the capability, not the product**:
   `conversation-db`, `vector-store`, `llm-local`, `llm-groq`, `tool-weather`,
   `tool-finance`. Cross-namespace callers use the full name
   (`conversation-db.data.svc.cluster.local`). Swapping Chroma for pgvector
   later changes a Deployment, not the orchestrator's config. The
   orchestrator's own Service keeps its name.

3. **One ServiceAccount per workload**, with no RBAC and
   `automountServiceAccountToken: false`. It is an identity today (for audit,
   and for policy later) and nothing more: no pod here talks to the Kubernetes
   API.

4. **Groq is reached through a gateway pod, `llm-groq`, in `models`**: nginx
   that adds the real `Authorization` header and forwards to `api.groq.com`
   over verified TLS. The orchestrator points `GROQ_API_BASE` at it and keeps
   a placeholder key (`ChatGroq` refuses to construct without one). Effects:
   - the Groq key exists only in `models`;
   - `app` needs no internet egress, so a hijacked orchestrator has nowhere to
     send data (once policies exist, only the gateway has an egress rule to
     the internet);
   - the "only api.groq.com" restriction lives in the gateway's config, which
     open-source Calico cannot express in a network policy;
   - the gateway resolves the hostname per request (30 s cache) because
     Groq's addresses change and a static `proxy_pass` would pin the first
     one for the life of the pod.

5. **Credentials only in the namespaces that use them**: `groq-credentials`
   in `models`; `postgres-credentials` (superuser) in `data`;
   `db-role-credentials` in both `data` and `app` with identical values,
   because the bootstrap Job sets the role passwords and the orchestrator logs
   in with them (the `app` copy leaves out `BACKUP_PASSWORD`, which only the
   backup job uses).

## Alternatives considered

- **Everything in `default`, separated by NetworkPolicy alone** - rejected:
  Secrets, ServiceAccounts, and Pod Security are namespace-scoped, so one
  namespace cannot hold different credentials or different profiles per tier.
- **One namespace per workload** - rejected: more policy surface than value;
  the real boundaries are four kinds of trust.
- **Cilium FQDN policy for Groq** - the stronger network-level answer, but a
  heavier CNI; deferred in favour of the gateway, which works with any CNI.
  Revisit if more external hosts are needed.
- **Allow all of port 443 from the orchestrator** - rejected: a hijacked
  orchestrator could exfiltrate to any public HTTPS host.
- **Keep the Groq key in `app`** - rejected: the process most exposed to
  prompt injection should not hold a billable credential.
- **Calling the services by short names** (`conversation-db.data`) -
  rejected in favour of full names, which do not depend on the pod's DNS
  search path.

## Consequences

- Moving from `default` is a fresh start for the volumes: PVCs are
  namespace-scoped, so Postgres history, Ollama models, and Chroma data in
  `default` are not carried over (see the migration notes in the PR/README).
- Postgres and the MCP servers still pass `restricted` on their own; `data`
  is `baseline` only because of Chroma's init container. A non-root-friendly
  volume class (k3s local-path) would let `data` tighten.
- One more pod to maintain (the gateway), and one more place a Groq outage or
  a bad key shows up; the runbook has an entry for it.
- The gateway trusts the pod network: callers reach it over plain HTTP, and
  the key is never sent over that hop, but the prompts are. Network policies
  must restrict who can reach it, otherwise any pod could spend the key.
