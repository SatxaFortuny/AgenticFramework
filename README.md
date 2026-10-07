# AF - Agentic Framework

A config-driven agent orchestrator running on Kubernetes (minikube). Each **app** bundles one or more **functionalities** (bots). Every functionality is a LangGraph pipeline with its own model, tools (MCP servers) and vector store, all defined in YAML.

The bundled demo app, `greeting_finance_app`, has two functionalities:

| Functionality  | Model                          | Tools                           |
|----------------|--------------------------------|---------------------------------|
| `greeting_bot` | Groq `openai/gpt-oss-20b`      | `get_weather` (weather MCP)     |
| `finance_bot`  | Ollama `llama3.1:8b` (app default) | `sql_read`, `sql_write` (finance MCP) |

## Architecture

Everything runs as pods in a local minikube cluster:

| Pod            | Role                                              |
|----------------|---------------------------------------------------|
| `orchestrator` | FastAPI service exposing `/chat`, runs the graphs. Stateless: can run with several replicas |
| `postgres`     | Conversation history (LangGraph checkpoints) and session routing, shared by all orchestrator replicas |
| `ollama`       | Local LLM and embedding model server              |
| `chromadb`     | Vector store                                      |
| `weather-mcp`  | MCP tool server (weather)                         |
| `finance-mcp`  | MCP tool server (finance / SQL)                   |

The orchestrator is exposed as a NodePort service (`30080`). `setup.sh` starts minikube with `--ports=8000:30080`, so it is reachable at **`http://localhost:8000`**.

## Prerequisites

- `podman`
- `minikube`
- `kubectl`
- A [Groq](https://console.groq.com) API key (used by `greeting_bot`)

## Quick start

### 1. Create the secrets

Two Kubernetes Secrets are read by the deployment, so create them once before deploying (`setup.sh` refuses to continue if either is missing):

```bash
kubectl create secret generic groq-credentials \
  --from-literal=GROQ_API_KEY='your-key-here'

kubectl create secret generic postgres-credentials \
  --from-literal=POSTGRES_USER=af \
  --from-literal=POSTGRES_PASSWORD='choose-a-password' \
  --from-literal=POSTGRES_DB=af
```

### 2. Deploy

```bash
./setup.sh
```

The script will:

1. Start minikube (podman driver, CRI-O runtime) if it isn't already running
2. Build the `af-orchestrator`, `af-tools` and `af-chroma` images with podman
3. Load them into minikube (`--overwrite`, so rebuilds always replace the cached image)
4. Apply all manifests with `kubectl apply -k .`
5. Restart the orchestrator and MCP deployments so they pick up the fresh images

Re-run `./setup.sh` after any code change. It is safe to run repeatedly.

### 3. Pull the Ollama models

Models are stored on a persistent volume, so you only need to do this once:

```bash
kubectl exec -it deploy/ollama -- ollama pull llama3.1:8b
kubectl exec -it deploy/ollama -- ollama pull nomic-embed-text
```

### 4. Wait for the pods

```bash
kubectl get pods -w
```

All six pods should reach `1/1 Running`. The first start can be slow while images load. The orchestrator pod briefly shows `Init:0/1` while its `migrate` init container creates the database schema.

## Talking to the bots

Send requests to `/chat` with `curl`.

### Start a conversation

The first message of a conversation names the `app` and `functionality`:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hi there", "app": "greeting_finance_app", "functionality": "greeting_bot"}'
```

```json
{"response":"Hello! 👋 How can I help you today?","conversation_id":"2163b500-53d4-4ebd-b7d6-d164000b9e03"}
```

### Continue it

Every later message only needs the `conversation_id` from the response. The orchestrator remembers which app and functionality it belongs to, and keeps the full message history:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "what did I ask?", "conversation_id": "2163b500-53d4-4ebd-b7d6-d164000b9e03"}'
```

```json
{"response":"You asked: **“What can you help me with?”**","conversation_id":"2163b500-53d4-4ebd-b7d6-d164000b9e03"}
```

### Use a tool

The greeting bot calls the weather MCP server when needed:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "How is the weather in Cambrils?", "conversation_id": "2163b500-53d4-4ebd-b7d6-d164000b9e03"}'
```

```json
{"response":"The weather in Cambrils is sunny, with a temperature around **24 °C**. Enjoy the sunshine!","conversation_id":"2163b500-53d4-4ebd-b7d6-d164000b9e03"}
```

### Try the finance bot

Start a new conversation by naming a different functionality:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello", "app": "greeting_finance_app", "functionality": "finance_bot"}'
```

### Request fields

| Field             | Required            | Description                                          |
|-------------------|---------------------|------------------------------------------------------|
| `message`         | always              | The user's message                                   |
| `app`             | first message only  | App name (a directory under `configs/`)              |
| `functionality`   | first message only  | Functionality name within that app                   |
| `conversation_id` | after the first one | Returned by every response; reuse it to keep context |

Conversations are stored in Postgres, so they survive orchestrator restarts and any replica can continue any conversation. To see it work:

```bash
kubectl delete pod -l app=orchestrator     # restart the orchestrator
# ...wait until it is Ready, then send "what did I ask?" with the same conversation_id:
# the full history is still there.
kubectl scale deployment orchestrator --replicas=2   # and now either replica can answer
```

(Without `PGHOST`/`DATABASE_URL` set - e.g. bare `uvicorn` in local dev - the orchestrator falls back to in-memory storage and logs a warning; those conversations are lost on restart.)

## Configuration

Apps live under `configs/{app}/`:

```
configs/greeting_finance_app/
├── app.yaml              # app name, default model, list of functionalities
├── functionalities/      # per-bot model, tools, vector DB, embeddings
└── blueprints/           # per-bot LangGraph definition
```

Adding a new app or functionality currently means:

1. Adding the files under `configs/`
2. Adding a matching entry to `configMapGenerator` in `kustomization.yaml`
3. Adding the matching volume item in `k8s/05-orchestrator.yaml`

Then run `./setup.sh` again.

## Running the tests

```bash
pytest -m "not integration"          # unit tests, no services needed
```

The Postgres-backed tests (migrations, checkpoint persistence, restart behaviour) skip themselves unless a database is available:

```bash
docker run -d --name af-test-pg -p 5432:5432 -e POSTGRES_USER=af -e POSTGRES_PASSWORD=af -e POSTGRES_DB=af_test postgres:16
TEST_DATABASE_URL=postgresql://af:af@localhost:5432/af_test pytest -m postgres
```

To run the orchestrator locally against that database: `PGHOST=localhost PGUSER=af PGPASSWORD=af PGDATABASE=af_test python migrate.py`, then start it with the same variables.

## Useful commands

```bash
kubectl get pods                              # cluster status
kubectl logs -l app=orchestrator --tail=60    # orchestrator logs
kubectl exec -it deploy/ollama -- ollama list # models available in Ollama
kubectl logs deploy/orchestrator -c migrate   # schema migration output
kubectl exec -it statefulset/postgres -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
kubectl delete -k .                           # remove all workloads (volumes are kept)
minikube stop                                 # stop the cluster
minikube delete                               # remove the cluster completely
```

## Troubleshooting

See [`docs/runbook.md`](docs/runbook.md) for symptom-first fixes, including:

- `CreateContainerError` on the orchestrator
- `{"detail":"Internal pipeline error"}` responses
- `GroqError: The api_key client option must be set`
- Orchestrator stuck in `Init:` / `CreateContainerConfigError`, or `Running` but `0/1` Ready (Postgres)
- Pods stuck on an old ReplicaSet
- Rebuilt images that don't change behavior

The postmortem in [`docs/postmortems/`](docs/postmortems/) covers the CRI-O and podman issues behind several of these.
