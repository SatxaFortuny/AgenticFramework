#!/bin/bash
set -e 

echo "Starting kubernetes deployment"

if ! minikube status > /dev/null 2>&1; then
    echo "Starting minikube"
    minikube start --driver=podman --container-runtime=crio --kubernetes-version=v1.37.0 --ports=8000:30080 --memory=8g --cpus=4
else
    echo "Minikube already started"
fi

echo "Building orchestrator image"
podman build -t af-orchestrator:latest ./src/orchestrator

echo "Building mcp image"
podman build -t af-tools:latest ./src/tools

echo "Building chromadb"
podman build -t af-chroma:latest -f ./src/orchestrator/infrastructure/Dockerfile.chroma ./src/orchestrator/infrastructure


podman save -o orchestrator.tar localhost/af-orchestrator:latest
podman save -o tools.tar localhost/af-tools:latest
podman save -o chroma.tar localhost/af-chroma:latest

minikube image load orchestrator.tar
minikube image load tools.tar
minikube image load chroma.tar

rm orchestrator.tar tools.tar chroma.tar

echo "Applying manifests"
kubectl apply -k .

echo "Deployment complete"
