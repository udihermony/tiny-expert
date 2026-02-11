"""Split parsed sections into overlapping chunks with metadata."""


def estimate_tokens(text):
    """Rough token estimate: ~0.75 tokens per word."""
    return int(len(text.split()) * 0.75)


def chunk_sections(sections, source_id, target_tokens=1500, overlap_tokens=200):
    """Split sections into chunks of ~target_tokens with overlap.

    Each chunk preserves chapter/section metadata from the source.
    """
    chunks = []
    chunk_index = 0

    for section in sections:
        text = section["text"].strip()
        if not text:
            continue

        chapter = section.get("chapter", "")
        sec = section.get("section", "")

        words = text.split()
        # Convert token targets to word counts (~1.33 words per token)
        target_words = int(target_tokens / 0.75)
        overlap_words = int(overlap_tokens / 0.75)

        if len(words) <= target_words:
            # Section fits in one chunk
            chunks.append({
                "id": f"chunk-{source_id}-{chunk_index:04d}",
                "source_id": source_id,
                "chapter": chapter,
                "section": sec,
                "text": text,
                "token_count": estimate_tokens(text),
                "chunk_index": chunk_index
            })
            chunk_index += 1
        else:
            # Split into overlapping chunks
            start = 0
            while start < len(words):
                end = min(start + target_words, len(words))
                chunk_text = " ".join(words[start:end])
                chunks.append({
                    "id": f"chunk-{source_id}-{chunk_index:04d}",
                    "source_id": source_id,
                    "chapter": chapter,
                    "section": sec,
                    "text": chunk_text,
                    "token_count": estimate_tokens(chunk_text),
                    "chunk_index": chunk_index
                })
                chunk_index += 1

                if end >= len(words):
                    break
                start = end - overlap_words

    return chunks
