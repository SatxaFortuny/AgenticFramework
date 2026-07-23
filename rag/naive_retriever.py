from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from core.interfaces import Retriever
from core.types import ScoredChunk

from typing import Literal
from pydantic import BaseModel

from docs import DOCUMENTS

class NaiveRetrieverConfig(BaseModel):
    type: Literal["naive"]
    def build(self) -> Retriever:
        return NaiveRetriever(DOCUMENTS)

class NaiveRetriever(Retriever):
    def __init__(self, documents: list[dict]):
        self.documents = documents
        texts = [d["text"] for d in documents]
        self.vectorizer = TfidfVectorizer(stop_words="english")
        self.doc_matrix = self.vectorizer.fit_transform(texts)

    def retrieve(self, query: str, k: int = 2) -> list[ScoredChunk]:
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.doc_matrix)[0]
        ranked_idx = scores.argsort()[::-1][:k]
        return [
            ScoredChunk(
                id=self.documents[i]["id"],
                title=self.documents[i]["title"],
                text=self.documents[i]["text"],
                score=float(scores[i]),
            )
            for i in ranked_idx
            if scores[i] > 0
        ]
