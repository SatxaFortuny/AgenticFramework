#!/bin/bash
set -e 

echo "Starting kubernetes deployment"

if ! minikube status > /dev/null 2>&1; then
    echo "Starting minikube"
    minikube start --driver=podman --container-runtime=crio --kubernetes-version=v1.37.0 --ports=8000:30080 --memory=8g --cpus=4
else
    echo "Minikube already started"
fi

# Fail fast with an actionable message instead of a pod stuck in
# CreateContainerConfigError (a missing Secret or key only shows up at
# container-create time, not at `kubectl apply` - see the postmortem,
# Incident 3).
for secret in groq-credentials postgres-credentials; do
    if ! kubectl get secret "$secret" > /dev/null 2>&1; then
        echo "ERROR: Secret '$secret' not found. Create it first - see the README (Quick start, step 1)."
        exit 1
    fi
done

echo "Building orchestrator image"
podman build -t af-orchestrator:latest ./src/orchestrator

echo "Building mcp image"
podman build -t af-tools:latest ./src/tools

echo "Building chromadb"
podman build -t af-chroma:latest -f ./src/orchestrator/infrastructure/Dockerfile.chroma ./src/orchestrator/infrastructure


podman save -o orchestrator.tar localhost/af-orchestrator:latest
podman save -o tools.tar localhost/af-tools:latest
podman save -o chroma.tar localhost/af-chroma:latest

# CHANGED: --overwrite forces minikube to replace its cached image with this
# build's content. Without it, re-running this script after a code change
# (same "latest" tag) can silently leave the *old* image content loaded -
# combined with imagePullPolicy: IfNotPresent in the manifests, pods would
# then run stale code with no error or warning that a rebuild didn't take.
minikube image load orchestrator.tar --overwrite
minikube image load tools.tar --overwrite
minikube image load chroma.tar --overwrite

rm orchestrator.tar tools.tar chroma.tar

echo "Applying manifests"
kubectl apply -k .

# CHANGED: kubectl apply alone won't restart a Deployment whose pod spec
# didn't change (same image tag, same manifest) even if the image *content*
# behind that tag did. Forcing a rollout restart here makes "run setup.sh
# again after a code change" reliably pick up the new image instead of
# depending on kubelet noticing on its own.
echo "Restarting deployments to pick up freshly loaded images"
kubectl rollout restart deployment orchestrator weather-mcp finance-mcp

echo "Deployment complete"
