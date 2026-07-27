"""
Quick manual test client.

    python client.py

Requires the API running, e.g.:
    uvicorn api.main:app --reload --app-dir <repo_root>
(run from inside api_demo/, with api_demo's parent = AgenticFramework repo root
 so `from api.main import app` / `from core import ...` resolve)
"""
import requests

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "sk-fetchly-demo-key-123"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def create_conversation() -> str:
    r = requests.post(f"{BASE_URL}/conversations", headers=HEADERS)
    r.raise_for_status()
    conversation_id = r.json()["conversation_id"]
    print(f"conversation_id: {conversation_id}\n")
    return conversation_id


def ask(conversation_id: str, content: str) -> str:
    r = requests.post(
        f"{BASE_URL}/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"content": content},
    )
    r.raise_for_status()
    data = r.json()
    print(f"Q: {content}")
    print(f"A: {data['answer']}\n")
    return data["answer"]


if __name__ == "__main__":
    cid = create_conversation()
    ask(cid, "How do I retry a request?")
    ask(cid, "What about the backoff interval for that?")
