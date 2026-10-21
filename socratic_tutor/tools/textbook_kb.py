"""FastMCP Tool Server: textbook-kb (search, get section, get exemplar)."""

from socratic_tutor.retrieval import HybridRetriever

retriever = HybridRetriever()


def search_textbook(query: str, chapter: str | None = None, top_k: int = 4) -> list[dict]:
    """Retrieve NCERT textbook sections relevant to the query."""
    return retriever.search_hybrid(query, top_k=top_k)


def get_section(section_id: str) -> dict | None:
    """Fetch exact NCERT section text and equations by ID."""
    for chunk in retriever.index.chunks:
        if chunk.get("section_id") == section_id:
            return chunk
    return None


def get_exemplar(exemplar_id: str) -> dict | None:
    """Fetch official NCERT exemplar problem and solution steps."""
    # Placeholder
    return {"exemplar_id": exemplar_id, "problem": "Sample exemplar problem"}
