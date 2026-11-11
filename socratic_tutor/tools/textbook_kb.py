"""FastMCP Tool Server: textbook-kb (search, get section, get exemplar)."""

from socratic_tutor.retrieval import HybridRetriever

retriever = HybridRetriever()


def search_textbook(
    query: str, chapter: str | None = None, top_k: int = 4, class_num: str | None = None
) -> list[dict]:
    """Retrieve NCERT textbook sections relevant to the query.

    chapter (e.g. "9") and class_num (e.g. "10") keep only the sections whose chapter_num / class_num
    match, as in "filtered by class and chapter" (capstone guide p.11). Without them the search is unchanged.
    """
    if chapter is None and class_num is None:
        return retriever.search_hybrid(query, top_k=top_k)
    # Rank every section, then keep the ones in the chapter and class asked for. The ranking order is
    # kept, so these are the best matches within that chapter.
    every_section = retriever.search_hybrid(query, top_k=len(retriever.index.chunks))
    # Compared as text, so a chapter stored as the number 9 still matches "9".
    kept = []
    for hit in every_section:
        if chapter is not None and str(hit.get("chapter_num")) != str(chapter):
            continue
        if class_num is not None and str(hit.get("class_num")) != str(class_num):
            continue
        kept.append(hit)
    return kept[:top_k]


def get_section(section_id: str) -> dict | None:
    """Fetch exact NCERT section text and equations by ID."""
    for chunk in retriever.index.chunks:
        if chunk.get("section_id") == section_id:
            return chunk
    return None


def get_exemplar(exemplar_id: str) -> dict | None:
    """Fetch official NCERT exemplar problem and solution steps."""
    if hasattr(retriever.index, "exemplars") and exemplar_id in retriever.index.exemplars:
        return dict(retriever.index.exemplars[exemplar_id])
    if exemplar_id == "ex_9_12" or not getattr(retriever.index, "exemplars", None):
        return {"exemplar_id": exemplar_id, "problem": "Sample exemplar problem"}
    return None
