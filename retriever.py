from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from docs import DOCUMENTS

class NaiveRetriever:
    def __init__(self, documents: list[dict]):
        self.documents = documents
        texts = [d["text"] for d in documents]
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.doc_matrix = self.vectorizer.fit_transform(texts)

    def retrieve(self, query: str, k: int = 2) -> list[dict]:
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.doc_matrix)[0]
        ranked_idx = scores.argsort()[::-1][:k]
        return [
            {**self.documents[i], "score": float(scores[i])}
            for i in ranked_idx
            if scores[i] > 0
        ]

if __name__ == "__main__":
    retriever = NaiveRetriever(DOCUMENTS)
    results = retriever.retrieve("how do I set a timeout on a request", k=2)
    for r in results:
        print(f"[{r['score']:.3f}] {r['title']}")
