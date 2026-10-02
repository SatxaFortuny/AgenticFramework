# Postmortem: First minikube deployment of the app/functionality restructure

**Date:** 2026-09-27
**Scope:** First attempt to run Batch 1 (two-tier app config) + Batch 2
(app/functionality/conversation_id routing, LangGraph checkpointer) on the
actual minikube cluster, after both had already been verified locally with
bare `uvicorn` processes.

**Summary:** Three separate, unrelated bugs surfaced back-to-back the moment
the new config layout met the real cluster. None of them existed in local
dev - they were all specific to how Kubernetes/CRI-O/podman handle things
that a bare `uvicorn` process never touches: multi-level ConfigMap mounts,
Docker build context symlinks, and Secret key naming. Total time from first
`CreateContainerError` to a working `/chat` response: roughly 45 minutes
across the three incidents below.

---

## Incident 1: CRI-O can't create multi-level ConfigMap mount paths

**Symptom:**

```
orchestrator-5f76ff44b6-mcskp   0/1   CreateContainerError
```

```
kubectl describe pod orchestrator-5f76ff44b6-mcskp
...
Warning  Failed  kubelet  Error: container create failed: creating `/app/configs`:
openat2 `app/configs`: No such file or directory
```

**Context:** Batch 1 restructured config from a flat `configs/config.yaml` to
`configs/{app}/app.yaml` + `functionalities/*.yaml` + `blueprints/*.yaml`.
The first attempt at a k8s manifest for this used a single ConfigMap volume
with nested `items[].path` values (e.g.
`path: greeting_finance_app/functionalities/greeting_bot.yaml`) to
reconstruct that directory tree at mount time.

**Diagnosis:** The error is CRI-O-specific (this cluster runs
`--container-runtime=crio`). CRI-O's volume mounter does not reliably
auto-create multi-level directories implied by a ConfigMap item's `path`
when that path contains a `/`. Docker's default runtime tends to paper over
this; CRI-O does not. This wasn't visible in any earlier testing because
local dev never goes through a container runtime at all.

**Fix:** Split the single nested-path volume into three separate volumes,
each targeting one subdirectory with *flat* (no-slash) item paths:

```yaml
volumeMounts:
  - name: app-yaml-volume
    mountPath: /app/configs/greeting_finance_app
  - name: functionalities-volume
    mountPath: /app/configs/greeting_finance_app/functionalities
  - name: blueprints-volume
    mountPath: /app/configs/greeting_finance_app/blueprints
```

Each volume's `items[].path` is now a single filename with no `/`. The
nesting comes from having three separate `mountPath`s instead of slashes
inside one volume's items.

**Verification:** `kubectl exec -it deploy/orchestrator -- find /app/configs`
showed the correct reconstructed tree; the orchestrator's startup log line
`Loaded 1 app(s): {...}` confirmed `discover_apps()` found it.

**Follow-up incident this exposed:** even after this fix, the *next* deploy
failed the same way but one level deeper (see Incident 2) - the mountPath
`/app/configs/greeting_finance_app` itself still didn't exist yet at
container-create time, because nothing in the image had ever created it.

---

## Incident 2: A local-dev symlink poisoned the Docker build context

**Symptom (after fixing Incident 1):**

```
STEP 7/11: RUN mkdir -p /app/configs/greeting_finance_app/functionalities /app/configs/greeting_finance_app/blueprints
mkdir: cannot create directory '/app/configs': File exists
Error: building at STEP "RUN mkdir -p ...": while running runtime: exit status 1
```

**Context:** The fix for Incident 1 required the image to already contain
the mount-point directories (CRI-O won't create them at container-create
time - see Incident 1). The natural fix was `RUN mkdir -p ...` in the
Dockerfile. That single `mkdir -p` failed immediately on the *first* path
component, `/app/configs`, claiming it already existed - but as something
that wasn't a directory.

**Diagnosis:** `src/orchestrator/` has a `configs` symlink checked into the
repo (pointing at `../../configs`), which is what lets `uvicorn api:app` work
correctly when run locally from inside `src/orchestrator/` - it lets
`discover_apps("configs")`'s relative path resolve to the real top-level
`configs/` directory without needing an absolute path or an env var.

`COPY . .` in the Dockerfile copies that symlink into the image *as a
symlink*, verbatim. Its target (`../../configs`, relative to `/app`) doesn't
exist inside the container, so it lands as a **dangling symlink** at
`/app/configs`. `mkdir -p` checks each path component and fails as soon as it
finds something at that path that isn't a directory - a dangling symlink
qualifies, so it refused to proceed, even for the first component.

This is a genuinely easy trap: the same relative-path trick that makes local
dev convenient is exactly what breaks the Docker build, because `COPY`
doesn't know the symlink was meant for host-side convenience only.

**Fix:** Clear the path before creating it, so the pre-existing symlink is
removed first regardless of what it is:

```dockerfile
RUN rm -rf /app/configs && \
    mkdir -p /app/configs/greeting_finance_app/functionalities \
             /app/configs/greeting_finance_app/blueprints
```

**Alternative not taken (worth doing later):** add `configs` to a
`.dockerignore` in `src/orchestrator/` so `COPY . .` never picks up the
symlink at all. This is the cleaner long-term fix - the `rm -rf` above is a
safety net for anyone who forgets the `.dockerignore` exists, but the
`.dockerignore` entry is what actually prevents the collision in the first
place. Flagged, not yet done.

**Verification:** rebuild succeeded; `kubectl exec ... find /app/configs`
after redeploy showed the ConfigMap-mounted files, not a dangling symlink.

---

## Incident 3: Missing/misnamed Groq API key

**Symptom (after fixing Incidents 1 and 2):**

```
curl -X POST http://localhost:8000/chat ... -> {"detail":"Internal pipeline error"}
```

```
kubectl logs -l app=orchestrator --tail=60
...
groq.GroqError: The api_key client option must be set either by passing
api_key to the client or by setting the GROQ_API_KEY environment variable
```

**Context:** `greeting_bot`'s functionality config pins `provider: groq`
explicitly (it doesn't inherit the app's Ollama default - see
ADR 0001). Nothing in the cluster had `GROQ_API_KEY` set; local dev testing
up to this point had exercised `greeting_bot` from bare `uvicorn` on a
machine where that env var happened to already be exported in the shell,
masking the gap.

**Diagnosis:** Straightforward once the traceback was visible -
`api.py`'s generic `except Exception` handler intentionally logs the full
traceback via `logger.exception` before returning an opaque `500` to the
client (so internal errors are debuggable without leaking implementation
details over the API). `kubectl logs` surfaced the real cause immediately.

There was a secondary wrinkle: a `groq-credentials` Secret already existed
in the cluster from earlier work, but under the key `api-key` rather than
`GROQ_API_KEY`. `secretKeyRef.key` has to match the Secret's actual data key
exactly - a mismatch there produces no error at all on `kubectl apply`, only
a runtime failure when the pod actually tries to use the (absent) env var.

**Fix:**

```yaml
- name: GROQ_API_KEY
  valueFrom:
    secretKeyRef:
      name: groq-credentials
      key: GROQ_API_KEY   # renamed from `api-key` for provider-name clarity
```

with the Secret recreated to use the matching key name:

```bash
kubectl delete secret groq-credentials
kubectl create secret generic groq-credentials --from-literal=GROQ_API_KEY='...'
```

Decided to rename the Secret's key rather than just match the manifest to
whatever the Secret already had, specifically because a generic key name
like `api-key` collides the moment a second provider needs its own key in
the same or a sibling secret.

**Verification:** `curl /chat` against `greeting_bot` returned a real model
response; `finance_bot` (Ollama, no Groq dependency) was also tested
separately to confirm this fix didn't mask anything else.

---

## What would have caught these earlier

- **Readiness probes** (not yet in the manifests - tracked as its own batch)
  would have made "pod is Running but not actually healthy" visible in
  `kubectl get pods` immediately, rather than requiring a `curl` to discover
  the pod was up but non-functional.
- **A `.dockerignore` in `src/orchestrator/`** excluding the `configs`
  symlink would have prevented Incident 2 outright rather than requiring a
  runtime `rm -rf` workaround.
- **Testing the Docker build in isolation** (`podman build` alone, before
  ever involving minikube/CRI-O) would have caught Incident 2 without CRI-O
  in the loop at all, since it's purely a build-context problem.
- **A pre-flight check for required Secrets/env vars** at orchestrator
  startup (fail fast with a clear message: "GROQ_API_KEY not set for
  functionality X's model") would have turned Incident 3's opaque 500 into
  an immediate, clear startup failure instead of a runtime surprise on first
  request.

See `docs/runbook.md` for the generic, symptom-first version of these three
fixes for future incidents of the same shape.
