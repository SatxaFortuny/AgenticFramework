from typing import Literal

from pydantic import BaseModel

from core.interfaces import Chunker, Document


class ParagraphChunkerConfig(BaseModel):
    type: Literal["paragraph"]
    chunk_size: int = 1000
    overlap: int = 200

    def build(self) -> Chunker:
        return ParagraphChunker(chunk_size=self.chunk_size, overlap=self.overlap)


class ParagraphChunker(Chunker):
    def __init__(self, chunk_size: int = 1000, overlap: int = 200):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, metadata: dict | None = None) -> list[Document]:
        metadata = metadata or {}
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[Document] = []
        current = ""

        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph

            if len(candidate) > self.chunk_size and current:
                chunks.append(Document(content=current, metadata=dict(metadata)))
                # carry the trailing `overlap` characters into the next chunk
                # so context isn't lost at the boundary
                tail = current[-self.overlap:] if self.overlap else ""
                current = f"{tail}\n\n{paragraph}" if tail else paragraph
            else:
                current = candidate

        if current:
            chunks.append(Document(content=current, metadata=dict(metadata)))

        return chunks