#!/usr/bin/env bash
# Asserts the allowed paths connect and the forbidden ones time out.
#   STUBS=1      CI: deploy stub listeners (same labels, Services, ports) into empty namespaces
#   (default)    test the real workloads on the current cluster
#   INTERNET=1   also test egress to the public internet
# Probes are throwaway busybox pods carrying the label of the workload they impersonate.
set -uo pipefail
TIMEOUT=${TIMEOUT:-4}; STUBS=${STUBS:-0}; INTERNET=${INTERNET:-0}
IMG=docker.io/library/busybox:1.36

# ns|label|service|port
SERVICES="app|orchestrator|orchestrator-service|8000
data|postgres|conversation-db|5432
data|chromadb|vector-store|8000
models|ollama|llm-local|11434
models|llm-groq|llm-groq|8080
tools|weather-mcp|tool-weather|8000
tools|finance-mcp|tool-finance|8001"
h() { echo "$1.$2.svc.cluster.local"; }

if [ "$STUBS" = 1 ]; then
  echo "==> stubs"
  kubectl create ns ingress-nginx --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  while IFS='|' read -r ns label svc port; do
    kubectl apply -f - >/dev/null <<YAML
apiVersion: apps/v1
kind: Deployment
metadata: {name: $label, namespace: $ns}
spec:
  replicas: 1
  selector: {matchLabels: {app: $label}}
  template:
    metadata: {labels: {app: $label}}
    spec:
      securityContext: {runAsNonRoot: true, runAsUser: 1000, seccompProfile: {type: RuntimeDefault}}
      containers:
        - name: stub
          image: docker.io/library/python:3.12-alpine
          command: [python, -m, http.server, "$port", --directory, /tmp]
          securityContext: {allowPrivilegeEscalation: false, capabilities: {drop: [ALL]}}
---
apiVersion: v1
kind: Service
metadata: {name: $svc, namespace: $ns}
spec:
  selector: {app: $label}
  ports: [{port: $port, targetPort: $port}]
YAML
  done <<< "$SERVICES"
  for ns in app data models tools; do kubectl -n $ns rollout status deploy --timeout=180s || exit 1; done
fi

pass=0; fail=0
probe() { # ns label host port allow|deny description
  local ns=$1 label=$2 host=$3 port=$4 expect=$5 desc=$6 name="probe-$RANDOM" got
  local ov="{\"spec\":{\"securityContext\":{\"runAsNonRoot\":true,\"runAsUser\":1000,\"seccompProfile\":{\"type\":\"RuntimeDefault\"}},\"containers\":[{\"name\":\"$name\",\"image\":\"$IMG\",\"command\":[\"sh\",\"-c\",\"nc -z -w $TIMEOUT $host $port\"],\"securityContext\":{\"allowPrivilegeEscalation\":false,\"capabilities\":{\"drop\":[\"ALL\"]}}}]}}"
  if kubectl -n "$ns" run "$name" --rm -i --restart=Never --quiet --image="$IMG" \
       --labels="app=$label" --overrides="$ov" >/dev/null 2>&1; then got=allow; else got=deny; fi
  if [ "$got" = "$expect" ]; then pass=$((pass+1)); echo "ok    $desc ($expect)"
  else fail=$((fail+1)); echo "FAIL  $desc (expected $expect, got $got)"; fi
}

echo "==> allowed"
probe app orchestrator "$(h conversation-db data)" 5432  allow "orchestrator -> conversation-db"
probe app orchestrator "$(h vector-store data)"    8000  allow "orchestrator -> vector-store"
probe app orchestrator "$(h llm-local models)"     11434 allow "orchestrator -> llm-local"
probe app orchestrator "$(h llm-groq models)"      8080  allow "orchestrator -> llm-groq"
probe app orchestrator "$(h tool-weather tools)"   8000  allow "orchestrator -> tool-weather"
probe app orchestrator "$(h tool-finance tools)"   8001  allow "orchestrator -> tool-finance"
probe data postgres-backup "$(h conversation-db data)" 5432 allow "postgres-backup -> conversation-db"
probe data db-bootstrap    "$(h conversation-db data)" 5432 allow "db-bootstrap -> conversation-db"
probe ingress-nginx ingress "$(h orchestrator-service app)" 8000 allow "ingress-nginx namespace -> orchestrator"

echo "==> forbidden (must time out)"
probe default x "$(h orchestrator-service app)" 8000 deny "other namespace -> orchestrator"
probe tools weather-mcp "$(h conversation-db data)"   5432 deny "weather-mcp -> conversation-db"
probe tools finance-mcp "$(h conversation-db data)"   5432 deny "finance-mcp -> conversation-db"
probe tools finance-mcp "$(h tool-weather tools)"     8000 deny "finance-mcp -> tool-weather"
probe tools weather-mcp "$(h tool-finance tools)"     8001 deny "weather-mcp -> tool-finance"
probe tools weather-mcp "$(h orchestrator-service app)" 8000 deny "weather-mcp -> orchestrator"
probe models ollama     "$(h conversation-db data)"   5432 deny "ollama -> conversation-db"
probe models llm-groq   "$(h vector-store data)"      8000 deny "llm-groq -> vector-store"
probe data chromadb     "$(h conversation-db data)"   5432 deny "chromadb -> conversation-db"
probe app random        "$(h conversation-db data)"   5432 deny "unlabelled app pod -> conversation-db"
probe tools random      "$(h tool-finance tools)"     8001 deny "unlabelled tools pod -> tool-finance"
probe models random     "$(h llm-groq models)"        8080 deny "unlabelled models pod -> llm-groq (key spend)"
probe app orchestrator  "$(h tool-finance tools)"     8000 deny "orchestrator -> tool-finance wrong port"

if [ "$INTERNET" = 1 ]; then
  echo "==> internet egress"
  probe app orchestrator 1.1.1.1 443 deny  "orchestrator -> internet"
  probe tools finance-mcp 1.1.1.1 443 deny "finance-mcp -> internet"
  probe models ollama     1.1.1.1 443 deny "ollama -> internet"
  probe models llm-groq   1.1.1.1 443 allow "llm-groq -> internet 443"
fi
echo; echo "passed=$pass failed=$fail"; [ "$fail" -eq 0 ]
