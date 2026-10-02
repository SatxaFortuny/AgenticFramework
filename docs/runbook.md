# Runbook

Symptom-first. Find the closest matching symptom, apply the fix. Each entry
links back to the postmortem it came from, if any, for the full diagnostic
story.

---

## `CreateContainerError` with `openat2 ... No such file or directory`

**Symptom:**
```
kubectl get pods
orchestrator-xxxxx   0/1   CreateContainerError
```
```
kubectl describe pod <pod-name>
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
   `k8s/05-orchestrator.yaml` for the pattern).
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
kubectl logs -l app=orchestrator --tail=60
```
Look for the traceback right after `CRITICAL PIPELINE ERROR`. Common causes
seen so far:
- Missing/misnamed API key env var for a model provider (see next entry)
- Ollama model not pulled yet (`kubectl exec -it deploy/ollama -- ollama list`)
- ChromaDB unreachable (only relevant for functionalities using
  `retrieve_context`)

---

## `groq.GroqError: The api_key client option must be set ...`

**Symptom:** Traceback in orchestrator logs, this exact message, when a
functionality using `provider: groq` builds its pipeline for the first time.

**Cause:** `GROQ_API_KEY` isn't set in the orchestrator pod's environment, or
a `secretKeyRef` in the Deployment points at a Secret key name that doesn't
match what the Secret actually contains (this fails silently at `kubectl
apply` time - only surfaces at runtime).

**Fix:**
```bash
# confirm the secret exists and check its actual key name(s)
kubectl get secret groq-credentials -o jsonpath='{.data}' | python3 -m json.tool

# if missing or misnamed, recreate with the key name the manifest expects
kubectl delete secret groq-credentials  # if it exists with the wrong key
kubectl create secret generic groq-credentials --from-literal=GROQ_API_KEY='...'

kubectl rollout restart deployment orchestrator
```

Naming convention: use the provider-prefixed name (`GROQ_API_KEY`,
`OPENAI_API_KEY`, etc.) rather than a generic `api-key`, since a generic name
collides the moment a second provider needs a key in the same or a sibling
secret.

**Related:** `docs/postmortems/2026-09-27-crio-configmap-nested-paths.md`
(Incident 3)

---

## Pod stuck on an old ReplicaSet after `kubectl apply -k .`

**Symptom:**
```
kubectl get pods
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
kubectl delete -k .
kubectl get pods            # confirm everything's gone
kubectl apply -k .
kubectl get pods -w
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
kubectl rollout restart deployment <name>
```
