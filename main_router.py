"""
Entry point for the router pipeline (Phase 3), parallel to main.py which
still runs the Phase 2 sequential baseline. Try queries that need the
docs tool, the trivial time tool, and neither, to see all three branches.
"""

from core.build import build_router_pipeline

if __name__ == "__main__":
    orchestrator, context = build_router_pipeline()

    for query in [
        "How do I make Fetchly automatically retry a request?",
        "What time is it right now?",
        "hi, how are you?",
    ]:
        print(f"Q: {query}")
        result = orchestrator.run(query, context)
        print("A:", result.answer)
        print("--- trace ---")
        for step in result.trace:
            print(" ", step)
        print()
