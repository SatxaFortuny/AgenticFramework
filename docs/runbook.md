# Runbook

Symptom-first. Find the closest matching symptom, apply the fix. Each entry
links back to the postmortem it came from, if any, for the full diagnostic
story.

---

## `CreateContainerError` with `openat2 ... No such file or directory`

**Symptom:**
```
kubectl get pods -n app
orchestrator-xxxxx   0/1   CreateContainerError
```
```
kubectl -n <namespace> describe pod <pod-name>
...
Error: container create failed: creating `/app/configs/...`: openat2 ...: No such file or directory
```

**Cause:** CRI-O cannot auto-create multi-level directories for a ConfigMap
(or similar) volume mount, whether because an `items[].path` contains a `/`
or because an intermediate directory in a nested `mountPath` doesn't already
exist inside the image.

**Fix:**
1. Check every ConfigMap/Secret volume's `items[].path` in the failing
   Deployment - none should contain a `/`. If one does, split it into a
   separate volume + separate `mountPath` per subdirectory instead (see
   `k8s/base/app/orchestrator.yaml` for the pattern).
2. Check the Dockerfile pre-creates every directory any volume in the
   manifest mounts onto (`RUN mkdir -p ...`). CRI-O mounts *onto* existing
   directories; it does not create them for you.

**Related:** `docs/postmortems/2026-09-27-crio-configmap-nested-paths.md`
(Incident 1)

---

## `podman build` fails with `mkdir: cannot create directory '<path>': File exists`

**Symptom:** A `RUN mkdir -p <path>` step in a Dockerfile fails, claiming a
directory already exists, even though nothing in the Dockerfile explicitly
created it.

**Cause:** `COPY . .` copied something from the build context that already
occupies that path - most likely a symlink checked into the repo for local
dev convenience (e.g. a `configs` symlink pointing outside the build
context), which lands as a **dangling symlink** in the image. `mkdir -p`
refuses to proceed once it finds a non-directory at any path component.

**Fix:**
1. Immediate: add `rm -rf <path> &&` before the `mkdir -p` in the Dockerfile.
2. Proper: add the offending path to a `.dockerignore` in that build context
   so `COPY . .` never picks it up. Check `git ls-files -s <path>` or
   `ls -la <path>` to confirm whether it's a symlink before assuming it's a
   real directory that snuck in some other way.

**Related:** `docs/postmortems/2026-09-27-crio-configmap-nested-paths.md`
(Incident 2)

---

## `/chat` returns `{"detail":"Internal pipeline error"}` with no other info

**Symptom:** API returns a generic 500, no detail in the response body.

**Cause:** `api.py` intentionally logs the real exception via
`logger.exception` and returns an opaque message to the client - the detail
is always in the pod logs, never in the HTTP response, on purpose.

**Fix:**
```bash
kubectl -n app logs -l app=orchestrator --tail=60
```
Look for the traceback right after `CRITICAL PIPELINE ERROR`. Common causes
seen so far:
- The Groq gateway rejecting the key or unreachable (see next entry)
- Ollama model not pulled yet (`kubectl -n models exec -it deploy/ollama -- ollama list`)
- ChromaDB unreachable (only relevant for functionalities using
  `retrieve_context`)

---

## Groq calls fail: `401`, `403`, connection error, or `llm-groq` not Ready

The orchestrator does not hold the Groq key. It talks to the `llm-groq` nginx
gateway in the `models` namespace (`GROQ_API_BASE`), which adds the real key
and forwards to `api.groq.com`. The orchestrator's own `GROQ_API_KEY` is a
placeholder, so `groq.GroqError: The api_key client option must be set` can no
longer happen; look at the gateway instead.

**Symptoms and causes:**
- `401 Invalid API Key` in the orchestrator logs: the key in the `models`
  namespace is wrong. (The key in `app` is irrelevant: there is none.)
- `llm-groq` pod in `CreateContainerConfigError`: the Secret or its key name
  is missing in the `models` namespace (Incident 3: this only surfaces when
  the container is created, not at `kubectl apply`).
- `llm-groq` in `CrashLoopBackOff` with `BIO_new_file() failed` or `cannot
  load certificate`: the image has no CA bundle at the path in
  `llm-groq.conf.template` (`proxy_ssl_trusted_certificate`).
- `502`/`504` from the gateway: it cannot reach `api.groq.com` (no internet
  from the node, or, once network policies exist, an egress rule is missing).

**Fix:**
```bash
kubectl -n models logs deploy/llm-groq
kubectl -n models get secret groq-credentials -o jsonpath='{.data}' | python3 -m json.tool   # key name must be GROQ_API_KEY

# recreate with the key name the manifest expects
kubectl -n models delete secret groq-credentials
kubectl -n models create secret generic groq-credentials --from-literal=GROQ_API_KEY='...'
kubectl -n models rollout restart deployment llm-groq
```

Naming convention: use the provider-prefixed name (`GROQ_API_KEY`,
`OPENAI_API_KEY`, etc.) rather than a generic `api-key`, since a generic name
collides the moment a second provider needs a key in the same or a sibling
secret.

**Related:** `docs/postmortems/2026-09-27-crio-configmap-nested-paths.md`
(Incident 3)

---

## `chromadb-0` in `CrashLoopBackOff`: `attempt to write a readonly database`

**Symptom:**
```
kubectl -n data logs chromadb-0 --previous
...
Error creating Frontend Config: SqlxError(Database(SqliteError { code: 8,
message: "attempt to write a readonly database" }))
```
The pod is `CrashLoopBackOff` and the startup probe reports `connection refused`.

**Cause:** Chroma runs as UID 10001, but the PVC is owned by root. `fsGroup`
is not applied on minikube's hostPath-backed volumes, so Chroma cannot write
its SQLite file in `/chroma/chroma`. Typically the volume was first written
by an earlier root-run deploy.

**Fix:** the `fix-permissions` init container in
`k8s/base/data/chromadb.yaml` chowns the volume to 10001 before Chroma starts
(root only for that init container, minimal capabilities). If you ever see
this on another non-root pod with a PVC, the same pattern applies. If the
init container is present and it still fails, the on-disk data may be from
an incompatible Chroma version; with no data you need to keep:
```bash
kubectl -n data delete pvc chroma-storage-chromadb-0
```

---

## Pod stuck on an old ReplicaSet after `kubectl apply -k k8s/overlays/dev`

**Symptom:**
```
kubectl get pods -n app
orchestrator-aaaaaa   0/1   CreateContainerError   (new)
orchestrator-bbbbbb   1/1   Running                (old, still there)
```

**Cause:** Kubernetes won't tear down a working old ReplicaSet's pod until
the new one is healthy - this is the safety mechanism working as intended,
not a bug. But it means stale/duplicate pods accumulate visibly while you're
debugging a failing rollout.

**Fix:** Either wait it out once the new pod is actually fixed (it'll
converge on its own), or force a clean slate while iterating on a fix:
```bash
kubectl delete -k k8s/overlays/dev
kubectl get pods -A            # confirm everything's gone
kubectl apply -k k8s/overlays/dev
kubectl get pods -A -w
```

---

## Rebuilt image doesn't seem to change pod behavior

**Symptom:** You changed code/Dockerfile, rebuilt, redeployed, but the pod
behaves exactly as before the change.

**Cause:** `minikube image load` with the same tag (`latest`) can leave stale
cached image content loaded, and `imagePullPolicy: IfNotPresent` means the
pod happily runs that stale image without complaint. `kubectl apply` also
won't restart a Deployment whose spec text didn't change, even if the image
*content* behind an unchanged tag did.

**Fix:** `setup.sh` now does this automatically (`--overwrite` on
`minikube image load` + `kubectl rollout restart` after apply). If running
steps manually instead of via the script:
```bash
minikube image load <tarball> --overwrite
kubectl -n <namespace> rollout restart deployment <name>
```
