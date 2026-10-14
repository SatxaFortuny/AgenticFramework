# ADR 0004: One hardened base, thin per-environment overlays

## Status

Accepted.

## Context

The manifests were a flat `k8s/0N-*.yaml` list with a root `kustomization.yaml`,
tuned for one minikube. A second environment (k3s with a GPU) is coming, and a
setting that differs between environments is exactly where "secure in dev,
open in prod" (or the reverse) creeps in.

## Decision

1. **`k8s/base/` holds everything that must be identical everywhere**, security
   settings included (non-root, read-only root filesystem, dropped
   capabilities, probes, ServiceAccounts, and later the NetworkPolicies).
   **`k8s/overlays/<env>/` holds only values that depend on the machine**:
   sizes, CPU/GPU mode, storage. Today there is one overlay, `dev`; `prod` is
   added when the k3s machine exists and its real sizes are known.

2. **One directory per trust zone** under `base/` (`app`, `data`, `models`,
   `tools`), each with its own `kustomization.yaml` that sets `namespace:`.
   See ADR 0005.

3. **The ConfigMap is generated next to the files it reads**
   (`configs/kustomization.yaml`), and `base/app` includes that directory as a
   resource. Kustomize only lets a generator read files inside its own
   directory (Flux and Argo CD enforce the same), so the alternatives were to
   move `configs/` or to put the generator beside it. Nothing moved, so local
   dev (`uvicorn` reading `./configs`) and the tests are untouched. Adding a
   file means adding one line to that kustomization.

4. **`scripts/check-manifests.py` runs on the rendered output** (locally and
   in CI) so the structure is verified, not assumed: every object is in one of
   the four namespaces, every workload has its own ServiceAccount, every pod
   satisfies the Pod Security profile its namespace enforces, every Service
   selects a workload, and every `*.svc.cluster.local` address in an env value
   points at a Service and port that exist.

## Alternatives considered

- **Copy-pasted manifests per environment** - rejected: they drift, and the
  drift is silent.
- **Helm** - rejected for now: templating logic and a values schema for a
  cluster this size; kustomize is built into `kubectl`.
- **A `minikube` overlay plus a `dev` overlay** - rejected: on one machine
  they are the same thing. An overlay nobody deploys is just stale config.
- **Symlinking `configs/` into the base** - rejected: depends on how kustomize
  treats a link pointing outside the directory, and a symlink in git is the
  same class of trap as Incident 2.

## Consequences

- Hardening can only be weakened by editing the base, which shows up in review
  for every environment at once.
- Deploy with `kubectl apply -k k8s/overlays/dev`; the old root
  `kustomization.yaml` is gone.
- GPU-mode resources are the base default; `overlays/dev` raises them for CPU
  inference. The prod overlay will add `nvidia.com/gpu: 1`.
