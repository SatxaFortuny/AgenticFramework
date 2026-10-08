#!/usr/bin/env bash
# Fails if the Chroma client (orchestrator lock file) and the Chroma server
# (Dockerfile.chroma) are pinned to different versions.
set -euo pipefail
cd "$(dirname "$0")/.."

client=$(grep -oP '^chromadb==\K[0-9][0-9.]*' src/orchestrator/requirements.txt || true)
server=$(grep -oP 'ARG CHROMADB_VERSION=\K[0-9][0-9.]*' src/orchestrator/infrastructure/Dockerfile.chroma || true)

if [[ -z "$client" || -z "$server" ]]; then
  echo "Could not read both versions (client='$client', server='$server')" >&2
  exit 1
fi
if [[ "$client" != "$server" ]]; then
  echo "Chroma version skew: client=$client server=$server" >&2
  exit 1
fi
echo "Chroma client and server both pinned to $client"
