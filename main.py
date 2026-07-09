from docs import DOCUMENTS
from retriever import NaiveRetriever
from model_provider import generate

SYSTEM_PROMPT = """
You are a documentation assistant for the Fetchly HTTP \
client library. Answer the user's question using ONLY the provided \
documentation excerpts below. If the excerpts don't contain the answer, \
say so explicitly rather than guessing.
"""

def answer_question(query: str, retriever: NaiveRetriever, k: int = 2) -> str:
    chunks = retriever.retrieve(query, k=k)

    if not chunks:
        context = "(no relevant documentation found)"
    else:
        context = "\n\n".join(
            f"--- {c['title']} ---\n{c['text'].strip()}" for c in chunks
        )

    user_message = f"Documentation excerpts:\n\n{context}\n\nQuestion: {query}"
    return generate(SYSTEM_PROMPT, user_message)


if __name__ == "__main__":
    retriever = NaiveRetriever(DOCUMENTS)
    query = "How do I make Fetchly automatically retry a request?"
    print(f"Q: {query}\n")
    print("A:", answer_question(query, retriever))
