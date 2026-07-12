"""
Phase 2: main.py now just calls the shared factory instead of building
components itself -- keeps it in sync with whatever the eval runner uses.
"""

from core.build import build_default_pipeline

if __name__ == "__main__":
    orchestrator, context = build_default_pipeline()

    query = "How do I make Fetchly automatically retry a request?"
    print(f"Q: {query}\n")

    result = orchestrator.run(query, context)
    print("A:", result.answer)

    print("\n--- trace ---")
    for step in result.trace:
        print(step)