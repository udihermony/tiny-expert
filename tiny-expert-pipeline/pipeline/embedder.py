"""Compute embeddings for chunks using sentence-transformers."""

_model = None


def get_model():
    """Lazy-load the embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts):
    """Compute embeddings for a list of texts. Returns list of lists."""
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return [emb.tolist() for emb in embeddings]


def embed_chunks(chunks):
    """Add embeddings to chunk dicts in-place."""
    texts = [c["text"] for c in chunks]
    if not texts:
        return chunks

    embeddings = embed_texts(texts)
    for chunk, emb in zip(chunks, embeddings):
        chunk["embedding"] = emb

    return chunks
