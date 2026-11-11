"""Tests for the textbook-kb MCP server: the tool list, every flowchart box of the three tools, the lock,
the log lines, and stdio.

Most tests talk to the server in-process with the official SDK's Client (the same "tools/list" and
"tools/call" messages an agent sends, without a subprocess). One test runs the server as a real subprocess
over stdio, written like the Lecture 7 hands-on client (stdio_client + ClientSession).

Every test that searches uses the fake_textbook fixture: textbook_kb.retriever becomes a HybridRetriever over
hand-written stand-in sections, with a fake Chroma collection that finds nothing (so the ranking is BM25
only). No test reads the real index, starts Chroma or downloads the embedding model (decision TK8). The
stand-in texts are short made-up sentences, not NCERT text.
"""

import asyncio
import logging
import sys
import threading
import time
from typing import Any

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from socratic_tutor import config
from socratic_tutor.retrieval import HybridRetriever
from socratic_tutor.tools import textbook_kb
from socratic_tutor.tools import textbook_kb_server


# ---------------------------------------------------------------------------
# Stand-ins for the index and for Chroma
# ---------------------------------------------------------------------------


class FakeIndex:
    """Stand-in for NCERTIndex: just the list of sections, held in memory."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks


class NoDenseHits:
    """Stand-in for the Chroma collection: it stores the texts it is given, and its search finds nothing."""

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}

    def get(self, include: list[str]) -> dict[str, list[str]]:
        ids = list(self.documents)
        texts: list[str] = []
        for chunk_id in ids:
            texts.append(self.documents[chunk_id])
        return {"ids": ids, "documents": texts}

    def upsert(self, ids: list[str], documents: list[str]) -> None:
        for chunk_id, text in zip(ids, documents):
            self.documents[chunk_id] = text

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.documents.pop(chunk_id, None)

    def query(self, query_texts: list[str], n_results: int, include: list[str]) -> dict[str, list[list[Any]]]:
        return {"ids": [[]], "distances": [[]]}


def section(chapter_num: str, chapter_title: str, section_id: str, title: str, content: str,
            equations: list[str] | None = None) -> dict[str, Any]:
    """One stand-in Class 10 section with the same fields as a real chunk in .index/chunks.json."""
    if equations is None:
        equations = []
    return {
        "chunk_id": "fake_c10_ch" + chapter_num + "_sec_" + section_id.replace(".", "_"),
        "class_num": "10",
        "subject": "Science",
        "chapter_num": chapter_num,
        "chapter_title": chapter_title,
        "section_id": section_id,
        "section_title": title,
        "content": content,
        "equations": equations,
    }


LIGHT: str = "Light - Reflection and Refraction"
EYE: str = "Human Eye and the Colourful World"
ELECTRICITY: str = "Electricity"

# A section longer than one excerpt: 40 lines of 49 characters, joined by line breaks (1,999 characters).
LONG_LINE: str = "Light bends at the surface between air and glass."
LONG_CONTENT: str = "\n".join([LONG_LINE] * 40)


def stand_in_sections() -> list[dict[str, Any]]:
    """Six stand-in sections, built fresh for each test, so a test that changes one can't affect another."""
    return [
        section("9", LIGHT, "9.1", "Reflection of Light", "A polished surface such as a mirror reflects most of the light falling on it."),
        section("9", LIGHT, "9.2.4", "Mirror Formula and Magnification", "The mirror formula links the object distance, the image distance and the focal length.",
                ["1/f = 1/v + 1/u", "m = h'/h = -v/u"]),
        section("9", LIGHT, "9.3", "Refraction of Light", LONG_CONTENT),
        section("10", EYE, "10.3", "Refraction of Light Through a Prism", "A glass prism bends light when it goes in and again when it comes out into the air."),
        section("10", EYE, "10.5", "Atmospheric Refraction", "Light from a star bends as it goes through layers of air of different density."),
        section("11", ELECTRICITY, "11.7", "Heating Effect of Electric Current", "The filament of a bulb glows because the electric current heats it."),
    ]


QUERY: str = "why does light bend when it goes from air into glass"


@pytest.fixture
def fake_textbook(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Put a retriever over the stand-in sections in place of the real one, and return those sections."""
    sections = stand_in_sections()
    # The server and textbook_kb both look up textbook_kb.retriever at call time, so this swaps it everywhere.
    # monkeypatch puts the real retriever back after the test.
    monkeypatch.setattr(textbook_kb, "retriever", HybridRetriever(index=FakeIndex(sections), dense_collection=NoDenseHits()))
    return sections


@pytest.fixture
def empty_textbook(monkeypatch: pytest.MonkeyPatch) -> None:
    """An index with no sections: what a fresh clone has before scripts/build_index.py is run."""
    monkeypatch.setattr(textbook_kb, "retriever", HybridRetriever(index=FakeIndex([]), dense_collection=NoDenseHits()))


class LineCollector(logging.Handler):
    """Collects the textbook-kb log lines, so a test can read exactly what was logged."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def log_lines() -> Any:
    """Every line the server logs during the test (the logger doesn't pass lines on to pytest's own capture)."""
    collector = LineCollector()
    textbook_kb_server.logger.addHandler(collector)
    yield collector.lines
    textbook_kb_server.logger.removeHandler(collector)


def list_tools() -> list[Any]:
    """Ask the server for its tools, the way an MCP client does at start-up."""

    async def ask() -> list[Any]:
        async with Client(textbook_kb_server.mcp) as client:
            listing = await client.list_tools()
            return listing.tools

    return asyncio.run(ask())


def tool_named(name: str) -> Any:
    """One tool from the listing, by name."""
    for tool in list_tools():
        if tool.name == name:
            return tool
    raise AssertionError("no tool named " + name)


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call a tool through the client and return the whole result, so a test can check is_error too."""

    async def ask() -> Any:
        async with Client(textbook_kb_server.mcp) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(ask())


def call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a tool through the client and return its result as a plain dict."""
    # structured_content is the dict the tool returned ({"ok": ..., ...}).
    return call_tool(name, arguments).structured_content


def hit_ids(result: dict[str, Any]) -> list[str]:
    """The section ids of a search result, in order."""
    ids: list[str] = []
    for hit in result["hits"]:
        ids.append(hit["section_id"])
    return ids


# ---------------------------------------------------------------------------
# The tool list and its labels (decisions TK2, TK4, TK7; evidence: "a tool list with schemas", capstone guide p.3)
# ---------------------------------------------------------------------------


def test_the_server_lists_exactly_three_tools() -> None:
    """TK2: search, section and exemplar, nothing else. Adding any tool (say, one that rebuilds the index) fails this."""
    names: list[str] = []
    for tool in list_tools():
        names.append(tool.name)
    assert names == ["search_textbook", "get_section", "get_exemplar"]


def test_every_tool_is_marked_read_only_and_local() -> None:
    """TK7: every tool only reads (the export lists it as "read") and touches only the local index."""
    for tool in list_tools():
        assert tool.annotations is not None, tool.name
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.open_world_hint is False, tool.name


def test_top_k_is_1_to_8_in_the_schema() -> None:
    """TK4: the schema itself says top_k is an integer from 1 to 8, default 4, so the model sees the range."""
    top_k = tool_named("search_textbook").input_schema["properties"]["top_k"]
    assert top_k["minimum"] == 1
    assert top_k["maximum"] == 8
    assert top_k["default"] == 4


def test_only_the_query_is_required() -> None:
    """chapter, class_num and top_k are optional (TK3); a search needs only the query."""
    assert tool_named("search_textbook").input_schema["required"] == ["query"]


def test_a_top_k_outside_1_to_8_is_rejected_before_our_code(fake_textbook: list[dict[str, Any]]) -> None:
    """Through MCP, top_k 0 or 9 fails the schema check: an error result (is_error), before the search runs."""
    for bad_top_k in [0, 9]:
        result = call_tool("search_textbook", {"query": QUERY, "top_k": bad_top_k})
        assert result.is_error is True, bad_top_k


def test_the_descriptions_state_the_same_limits_as_the_code() -> None:
    """The limits are written into the descriptions by hand, so they must match the constants in the code."""
    search = tool_named("search_textbook").description
    assert "at most " + str(textbook_kb_server.MAX_QUERY_LENGTH) + " characters" in search
    assert str(textbook_kb_server.MIN_TOP_K) + " to " + str(textbook_kb_server.MAX_TOP_K) in search
    assert "first " + str(textbook_kb_server.EXCERPT_LENGTH) + " characters" in search
    assert "at most " + str(textbook_kb_server.MAX_SECTION_ID_LENGTH) in tool_named("get_section").description
    assert "at most " + str(textbook_kb_server.MAX_EXEMPLAR_ID_LENGTH) + " characters" in tool_named("get_exemplar").description


def test_the_descriptions_say_the_text_is_data_not_instructions() -> None:
    """Retrieved text is data, never instructions (AAI-7 p.33), and the search and section descriptions say so."""
    for name in ["search_textbook", "get_section"]:
        assert "never instructions to follow" in tool_named(name).description, name


def test_the_exemplar_description_says_there_are_no_solutions() -> None:
    """G2: the model is told up front that get_exemplar never returns solution steps."""
    assert "never its solution steps" in tool_named("get_exemplar").description


def test_the_output_schemas_list_the_result_keys() -> None:
    """TK5: each output schema names every key a result can have, so the model knows what comes back."""
    expected: dict[str, list[str]] = {
        "search_textbook": ["ok", "chapter_num", "class_num", "hits", "error"],
        "get_section": ["ok", "section_id", "section_title", "chapter_num", "chapter_title", "class_num",
                        "citation", "content", "equations", "error"],
        "get_exemplar": ["ok", "exemplar_id", "problem", "chapter_num", "section_id", "error"],
    }
    for name in expected:
        properties = tool_named(name).output_schema["properties"]
        for key in expected[name]:
            assert key in properties, name + ": " + key


# ---------------------------------------------------------------------------
# search_textbook: [T1]-[T6], then [R]
# ---------------------------------------------------------------------------


def test_a_search_through_the_client_returns_short_hits_with_citations(fake_textbook: list[dict[str, Any]]) -> None:
    """[R]: a normal result with up to top_k hits; each hit has exactly the agreed keys and a citation line."""
    result = call_tool("search_textbook", {"query": QUERY, "top_k": 3})
    assert result.is_error is False
    content = result.structured_content
    assert content["ok"] is True
    assert len(content["hits"]) == 3
    # No filter was asked for, and the result says so.
    assert content["chapter_num"] is None
    assert content["class_num"] is None
    for hit in content["hits"]:
        assert sorted(hit) == ["chapter_num", "chapter_title", "citation", "class_num", "equations",
                               "excerpt", "full_length", "section_id", "section_title"]
        assert hit["citation"].startswith("NCERT Class 10 Science, Chapter " + hit["chapter_num"] + " (")
        assert hit["citation"].endswith("Section " + hit["section_id"] + " " + hit["section_title"])


def test_make_citation_text() -> None:
    """The citation line names the class, subject, chapter (number and title) and the section (id and title)."""
    stand_in = section("9", LIGHT, "9.2.4", "Mirror Formula and Magnification", "text")
    assert textbook_kb_server.make_citation(stand_in) == (
        "NCERT Class 10 Science, Chapter 9 (Light - Reflection and Refraction), "
        "Section 9.2.4 Mirror Formula and Magnification"
    )


def test_a_chapter_number_keeps_only_that_chapter(fake_textbook: list[dict[str, Any]]) -> None:
    """[T4] + [T5]: chapter "9" returns only Chapter 9 sections, and the result says which chapter it used."""
    content = call("search_textbook", {"query": QUERY, "chapter": "9"})
    assert content["ok"] is True
    assert content["chapter_num"] == "9"
    assert len(content["hits"]) == 3
    for hit in content["hits"]:
        assert hit["chapter_num"] == "9"


def test_a_chapter_title_works_in_any_case_and_spacing(fake_textbook: list[dict[str, Any]]) -> None:
    """[T4]: the title, as the concept graph writes it, finds the chapter even with other capitals and spaces."""
    by_number = call("search_textbook", {"query": QUERY, "chapter": "10"})
    by_title = call("search_textbook", {"query": QUERY, "chapter": "  human eye AND the   colourful world "})
    assert by_title["ok"] is True
    assert by_title["chapter_num"] == "10"
    assert hit_ids(by_title) == hit_ids(by_number)


def test_the_server_passes_the_chapter_number_to_textbook_kb(
    fake_textbook: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """[T5] (decision TK1): the server turns a title into the number and textbook_kb does the filtering."""
    calls: list[dict[str, Any]] = []

    def recording_search(query: str, chapter: str | None = None, top_k: int = 4,
                         class_num: str | None = None) -> list[dict[str, Any]]:
        # Remember how the server called textbook_kb.search_textbook, and find nothing.
        calls.append({"query": query, "chapter": chapter, "top_k": top_k, "class_num": class_num})
        return []

    monkeypatch.setattr(textbook_kb, "search_textbook", recording_search)
    call("search_textbook", {"query": "  " + QUERY + " ", "chapter": "Electricity", "class_num": "10", "top_k": 2})
    assert calls == [{"query": QUERY, "chapter": "11", "top_k": 2, "class_num": "10"}]


def test_an_unknown_chapter_is_refused_with_the_known_chapters(fake_textbook: list[dict[str, Any]]) -> None:
    """[T4]: an unknown chapter is an error that lists the real chapters and doesn't repeat the text it was sent."""
    content = call("search_textbook", {"query": QUERY, "chapter": "Photosynthesis"})
    assert content["ok"] is False
    assert "9 (Light - Reflection and Refraction)" in content["error"]
    assert "10 (Human Eye and the Colourful World)" in content["error"]
    assert "11 (Electricity)" in content["error"]
    assert "Photosynthesis" not in content["error"]


def test_a_blank_chapter_means_no_filter(fake_textbook: list[dict[str, Any]]) -> None:
    """[T1]: a chapter of only spaces counts as "not given", so the search is the same as without a chapter."""
    blank = call("search_textbook", {"query": QUERY, "chapter": "   "})
    none_given = call("search_textbook", {"query": QUERY})
    assert blank["ok"] is True
    assert blank["chapter_num"] is None
    assert hit_ids(blank) == hit_ids(none_given)


def test_class_10_is_accepted_and_another_class_is_refused(fake_textbook: list[dict[str, Any]]) -> None:
    """[T4]: class "10" is in the index; class "9" isn't, so it's an error listing the classes there are."""
    accepted = call("search_textbook", {"query": QUERY, "class_num": "10"})
    assert accepted["ok"] is True
    assert accepted["class_num"] == "10"
    refused = call("search_textbook", {"query": QUERY, "class_num": "9"})
    assert refused["ok"] is False
    assert refused["error"] == "Unknown class_num. Classes in the textbook index: 10."


def test_an_empty_query_is_refused(fake_textbook: list[dict[str, Any]]) -> None:
    """[T2]: a query of only spaces is empty once tidied, so it's refused."""
    content = call("search_textbook", {"query": "   "})
    assert content["ok"] is False
    assert content["error"].startswith("query is empty")


def test_a_query_at_the_limit_is_accepted_and_one_more_character_is_refused(fake_textbook: list[dict[str, Any]]) -> None:
    """[T2]: exactly 500 characters is fine; 501 is refused, and the message says how long it was."""
    at_limit = "light " * 83 + "ab"
    assert len(at_limit) == 500
    assert call("search_textbook", {"query": at_limit})["ok"] is True
    too_long = at_limit + "c"
    content = call("search_textbook", {"query": too_long})
    assert content["ok"] is False
    assert content["error"].startswith("query is longer than 500 characters (501)")


def test_top_k_outside_1_to_8_in_a_direct_python_call_is_refused(fake_textbook: list[dict[str, Any]]) -> None:
    """[T2]: the code checks top_k too, for callers that skip the MCP schema (direct Python calls)."""
    for bad_top_k in [0, 9]:
        result = textbook_kb_server.search_steps(QUERY, None, None, bad_top_k)
        assert result == {"ok": False, "error": "top_k must be from 1 to 8."}, bad_top_k


def test_an_empty_index_fails_closed_for_search(empty_textbook: None) -> None:
    """[T3] (decision TK6): no sections loaded is an error that says to build the index, never an empty list."""
    content = call("search_textbook", {"query": QUERY})
    assert content == {"ok": False, "error": textbook_kb_server.EMPTY_INDEX_ERROR}
    assert "scripts/build_index.py" in content["error"]


def test_a_query_that_matches_nothing_is_an_error(fake_textbook: list[dict[str, Any]]) -> None:
    """[T6]: "???" has no words to match, so nothing is found; that's an error asking to rephrase, not an
    empty list the model could read as "the textbook doesn't cover this"."""
    content = call("search_textbook", {"query": "???"})
    assert content == {"ok": False, "error": "No textbook section matched the query. Rephrase it with the key words of the question."}
    in_chapter = call("search_textbook", {"query": "???", "chapter": "9"})
    assert in_chapter["error"].startswith("No textbook section matched the query in chapter 9.")


def test_a_long_section_is_shortened_and_its_full_length_given(fake_textbook: list[dict[str, Any]]) -> None:
    """[T6]: section 9.3 is 1,999 characters, so its hit has an excerpt within 1,200 and the full length."""
    content = call("search_textbook", {"query": QUERY, "chapter": "9"})
    long_hit = None
    for hit in content["hits"]:
        if hit["section_id"] == "9.3":
            long_hit = hit
    assert long_hit is not None
    assert long_hit["full_length"] == len(LONG_CONTENT)
    assert len(long_hit["excerpt"]) <= textbook_kb_server.EXCERPT_LENGTH + len(" ...")
    assert long_hit["excerpt"].endswith(" ...")


def test_make_excerpt_cuts_at_a_line_break() -> None:
    """[T6]: the cut falls at the end of a line, never in the middle of one."""
    excerpt = textbook_kb_server.make_excerpt(LONG_CONTENT)
    # 24 lines of 49 characters and 23 line breaks = 1,199 characters fit; the 25th line doesn't.
    assert excerpt == "\n".join([LONG_LINE] * 24) + " ..."


def test_make_excerpt_cuts_at_a_space_when_there_is_no_line_break() -> None:
    """[T6]: one long paragraph with no line breaks is cut at its last space, so no word is cut in half."""
    paragraph = "refraction " * 200
    excerpt = textbook_kb_server.make_excerpt(paragraph)
    assert excerpt.endswith("refraction ...")
    assert len(excerpt) <= textbook_kb_server.EXCERPT_LENGTH + len(" ...")


def test_make_excerpt_returns_a_short_section_whole() -> None:
    """[T6]: a section within the limit comes back unchanged, with no " ..." added."""
    assert textbook_kb_server.make_excerpt("Short text.") == "Short text."


def test_changing_a_hit_does_not_change_the_index(fake_textbook: list[dict[str, Any]]) -> None:
    """[T6]: each hit is a new dict with a new equations list, so editing the result leaves the index as it was."""
    result = textbook_kb_server.search_steps("mirror formula focal length", "9", None, 4)
    for hit in result["hits"]:
        hit["equations"].append("changed")
        hit["section_title"] = "changed"
    for stand_in in fake_textbook:
        assert "changed" not in stand_in["equations"]
        assert stand_in["section_title"] != "changed"


# ---------------------------------------------------------------------------
# SEARCH_LOCK: one call at a time into textbook_kb (decision TK10)
# ---------------------------------------------------------------------------

# How many calls the lock test sends at once.
LOCK_THREADS: int = 8


def test_only_one_search_runs_at_a_time(fake_textbook: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """TK10: 8 searches started together never run inside textbook_kb at the same time.

    The stand-in search counts how many calls are inside it at once and waits a moment, so without the lock
    several would overlap and the highest count would be above 1.
    """
    state: dict[str, int] = {"inside": 0, "most_inside": 0}
    count_lock = threading.Lock()

    def slow_search(query: str, chapter: str | None = None, top_k: int = 4,
                    class_num: str | None = None) -> list[dict[str, Any]]:
        # Count this call in, remember the highest count, wait a moment, then count it out.
        with count_lock:
            state["inside"] = state["inside"] + 1
            if state["inside"] > state["most_inside"]:
                state["most_inside"] = state["inside"]
        time.sleep(0.02)
        with count_lock:
            state["inside"] = state["inside"] - 1
        return []

    monkeypatch.setattr(textbook_kb, "search_textbook", slow_search)
    # A Barrier for 8 threads: none of them goes past wait() until all 8 have called it.
    start_together = threading.Barrier(LOCK_THREADS)
    results: list[dict[str, Any]] = []

    def search_when_all_are_ready() -> None:
        # The timeout stops the test from hanging for ever if a thread never arrives.
        start_together.wait(timeout=10)
        results.append(textbook_kb_server.run_and_log(
            "search_textbook", textbook_kb_server.search_steps,
            {"query": QUERY, "chapter": None, "class_num": None, "top_k": 4},
        ))

    threads: list[threading.Thread] = []
    for thread_number in range(LOCK_THREADS):
        threads.append(threading.Thread(target=search_when_all_are_ready))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == LOCK_THREADS
    assert state["most_inside"] == 1


# ---------------------------------------------------------------------------
# get_section: [G1]-[G4], then [R]
# ---------------------------------------------------------------------------


def test_get_section_returns_the_whole_text_and_its_labels(fake_textbook: list[dict[str, Any]]) -> None:
    """[R]: the whole section (not an excerpt), with its labels, citation and equations."""
    result = call_tool("get_section", {"section_id": " 9.3 "})
    assert result.is_error is False
    content = result.structured_content
    assert content["ok"] is True
    assert content["section_id"] == "9.3"
    assert content["section_title"] == "Refraction of Light"
    assert content["content"] == LONG_CONTENT
    assert content["citation"] == "NCERT Class 10 Science, Chapter 9 (Light - Reflection and Refraction), Section 9.3 Refraction of Light"
    with_equations = call("get_section", {"section_id": "9.2.4"})
    assert with_equations["equations"] == ["1/f = 1/v + 1/u", "m = h'/h = -v/u"]


def test_changing_the_section_result_does_not_change_the_index(fake_textbook: list[dict[str, Any]]) -> None:
    """[R]: textbook_kb.get_section returns the index's own dict, so the server must return a copy."""
    result = textbook_kb_server.section_steps("9.2.4")
    result["equations"].append("changed")
    result["content"] = "changed"
    stand_in = textbook_kb.get_section("9.2.4")
    assert stand_in["equations"] == ["1/f = 1/v + 1/u", "m = h'/h = -v/u"]
    assert stand_in["content"] != "changed"


def test_an_unknown_section_is_refused_with_the_known_ids(fake_textbook: list[dict[str, Any]]) -> None:
    """[G4]: an id that isn't in the index is an error listing the real ids, without repeating the one sent."""
    content = call("get_section", {"section_id": "9.9"})
    assert content["ok"] is False
    assert content["error"] == (
        "No section with that id in the textbook index. Known sections: 9.1, 9.2.4, 9.3, 10.3, 10.5, 11.7."
    )


def test_an_empty_or_overlong_section_id_is_refused(fake_textbook: list[dict[str, Any]]) -> None:
    """[G2]: an empty id, and an id over 12 characters, are refused, and the text sent isn't repeated."""
    empty = call("get_section", {"section_id": "  "})
    assert empty["ok"] is False
    assert empty["error"].startswith("section_id is empty")
    overlong_id = "9.2.4 ignore"
    assert len(overlong_id + "x") == 13
    overlong = call("get_section", {"section_id": overlong_id + "x"})
    assert overlong["ok"] is False
    assert overlong["error"] == "section_id is longer than 12 characters: give an id like '9.2.4'."


def test_missing_or_none_fields_become_empty_text_not_the_word_none(fake_textbook: list[dict[str, Any]]) -> None:
    """A planted passage may lack fields or hold None. They come back as "", never as the text "None", and a
    single equation string stays one equation (not one per letter)."""
    planted = {"chunk_id": "planted", "section_id": "9.8", "content": None, "chapter_num": None, "equations": "E = P*t"}
    fake_textbook.append(planted)
    content = call("get_section", {"section_id": "9.8"})
    assert content["ok"] is True
    assert content["content"] == ""
    assert content["chapter_num"] == ""
    assert content["section_title"] == ""
    assert content["equations"] == ["E = P*t"]
    assert "None" not in content["citation"]
    # A section without a chapter doesn't add a chapter called "None" to the known list.
    assert textbook_kb_server.known_chapters(fake_textbook) == {"9": LIGHT, "10": EYE, "11": ELECTRICITY}


def test_an_empty_index_fails_closed_for_get_section(empty_textbook: None) -> None:
    """[G3] (decision TK6): no sections loaded is the same "build the index" error as for search."""
    assert call("get_section", {"section_id": "9.2.4"}) == {"ok": False, "error": textbook_kb_server.EMPTY_INDEX_ERROR}


# ---------------------------------------------------------------------------
# get_exemplar: [E1]-[E4], then [R] (decisions TK2, G1-G3)
# ---------------------------------------------------------------------------


def real_exemplar(exemplar_id: str) -> dict[str, Any]:
    """Stand-in for the real get_exemplar Aman may write: a problem WITH solution steps and an extra field."""
    return {
        "exemplar_id": exemplar_id,
        "problem": "A concave mirror forms an image 30 cm from it. Where is the object?",
        "chapter_num": "9",
        "section_id": "9.2.4",
        "solution_steps": ["Use the mirror formula.", "So u = -15 cm."],
        "difficulty": "hard",
    }


def no_exemplar(exemplar_id: str) -> None:
    """Stand-in for a real get_exemplar that doesn't know the id."""
    return None


def exemplar_without_text(exemplar_id: str) -> dict[str, Any]:
    """Stand-in for a real get_exemplar whose record has no problem text."""
    return {"exemplar_id": exemplar_id, "problem": "   "}


# A made-up file path with a user's name in it, the kind of text a real error message contains.
FAKE_PRIVATE_PATH: str = "C:\\Users\\someone\\exemplars.json"


def broken_exemplar(exemplar_id: str) -> dict[str, Any]:
    """Stand-in for a get_exemplar that crashes, with a private path in its error message."""
    raise FileNotFoundError("Cannot open " + FAKE_PRIVATE_PATH)


def test_the_placeholder_is_refused_as_not_indexed_yet() -> None:
    """[E3] (G1): today's textbook_kb.get_exemplar returns a made-up problem for ANY id; the tool refuses it."""
    # The real placeholder, unchanged, is what this test runs against.
    assert textbook_kb.get_exemplar("ex_9_12") == {"exemplar_id": "ex_9_12", "problem": "Sample exemplar problem"}
    content = call("get_exemplar", {"exemplar_id": "ex_9_12"})
    assert content == {"ok": False, "error": "Exemplar problems aren't indexed yet, so there is nothing real to return."}


def test_a_real_exemplar_keeps_only_the_agreed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """[E4] (G2, G3): with a real get_exemplar, the tool passes on the id, problem, chapter and section ONLY.
    The solution steps and the extra "difficulty" field are left out."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", real_exemplar)
    content = call("get_exemplar", {"exemplar_id": "ex_9_12"})
    assert content == {
        "ok": True,
        "exemplar_id": "ex_9_12",
        "problem": "A concave mirror forms an image 30 cm from it. Where is the object?",
        "chapter_num": "9",
        "section_id": "9.2.4",
    }
    # Not even a trace of the solution anywhere in the result.
    assert "u = -15 cm" not in str(content)


def test_exemplar_steps_itself_never_returns_solution_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """[E4] (G2) without MCP in between: the server's own function leaves the solution out.

    This is the guard that matters (see the next test: the SDK's output schema is NOT a second guard).
    """
    monkeypatch.setattr(textbook_kb, "get_exemplar", real_exemplar)
    result = textbook_kb_server.exemplar_steps("ex_9_12")
    assert sorted(result) == ["chapter_num", "exemplar_id", "ok", "problem", "section_id"]
    assert "u = -15 cm" not in str(result)


def test_the_output_schema_is_not_a_guard_for_the_text_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Why [E4]'s own field list is the only guard: if the steps ever returned an undeclared key, the SDK trims
    it from structured_content, but the TEXT copy of the result (which an agent may read) is built from the raw
    result and still holds it. Found by the independent review; this test pins how SDK 2.3 behaves."""

    def leaky_steps(exemplar_id: str) -> dict[str, Any]:
        # A broken version of exemplar_steps that lets the solution through.
        return {"ok": True, "exemplar_id": exemplar_id, "problem": "A problem.", "solution_steps": "u = -15 cm"}

    # The tool looks up exemplar_steps at call time, so this replaces the steps for one call.
    monkeypatch.setattr(textbook_kb_server, "exemplar_steps", leaky_steps)
    result = call_tool("get_exemplar", {"exemplar_id": "ex_9_12"})
    # The structured copy is trimmed to the declared keys...
    assert result.structured_content == {"ok": True, "exemplar_id": "ex_9_12", "problem": "A problem."}
    # ...but the text copy is not, so a leaky exemplar_steps WOULD reach the model.
    assert "u = -15 cm" in result.content[0].text


def test_small_edits_to_the_placeholder_are_still_caught() -> None:
    """[E3]: case, spaces and punctuation don't matter, so a slightly edited stub still counts as the placeholder.
    A real problem text doesn't."""
    for stub_text in ["Sample exemplar problem.", "SAMPLE EXEMPLAR PROBLEM", "Sample exemplar problem #1", " sample  exemplar-problem "]:
        assert textbook_kb_server.is_placeholder({"exemplar_id": "x", "problem": stub_text}) is True, stub_text
    assert textbook_kb_server.is_placeholder(real_exemplar("ex_9_12")) is False
    assert textbook_kb_server.is_placeholder(None) is False


def test_no_exemplar_found_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """[E2]: when the real function finds nothing (None), the tool says so."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", no_exemplar)
    assert call("get_exemplar", {"exemplar_id": "ex_9_99"}) == {"ok": False, "error": "No exemplar problem with that id."}


def test_an_exemplar_without_problem_text_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """[E4]: a record with no real problem text is refused rather than passed on empty."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", exemplar_without_text)
    content = call("get_exemplar", {"exemplar_id": "ex_9_12"})
    assert content == {"ok": False, "error": "The exemplar has no problem text, so nothing was returned."}


def test_an_empty_or_overlong_exemplar_id_is_refused() -> None:
    """[E1]: an empty id, and one over 60 characters, are refused before textbook_kb is asked."""
    assert call("get_exemplar", {"exemplar_id": " "}) == {"ok": False, "error": "exemplar_id is empty."}
    content = call("get_exemplar", {"exemplar_id": "e" * 61})
    assert content == {"ok": False, "error": "exemplar_id is longer than 60 characters."}


def test_a_crash_gives_only_the_error_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """[W]: a crash inside textbook_kb becomes an error result with the error's TYPE only, never its message,
    which here holds a private path."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", broken_exemplar)
    result = textbook_kb_server.run_and_log("get_exemplar", textbook_kb_server.exemplar_steps, {"exemplar_id": "ex_9_12"})
    assert result == {"ok": False, "error": "Unexpected problem in get_exemplar (FileNotFoundError), so nothing was returned."}
    assert "someone" not in result["error"]


def test_a_crash_through_the_client_is_a_normal_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """[W] through MCP: the agent gets a normal result (is_error False) saying what went wrong, not a crash."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", broken_exemplar)
    result = call_tool("get_exemplar", {"exemplar_id": "ex_9_12"})
    assert result.is_error is False
    assert result.structured_content["ok"] is False
    assert "(FileNotFoundError)" in result.structured_content["error"]


# ---------------------------------------------------------------------------
# [L] one log line per call: safe facts, never the query's words
# ---------------------------------------------------------------------------


def test_each_call_logs_one_line_without_the_query(fake_textbook: list[dict[str, Any]], log_lines: list[str]) -> None:
    """[L]: one line per call. A search logs its filter, the query's length and the section ids, not the query."""
    call("search_textbook", {"query": QUERY, "chapter": "9", "top_k": 2})
    assert len(log_lines) == 1
    line = log_lines[0]
    assert line.startswith("tool=search_textbook ok=True chapter=9 class=- query_chars=" + str(len(QUERY)) + " sections=")
    assert QUERY not in line
    # A distinctive word of the query, in case only part of it slipped in.
    assert "glass" not in line


def test_a_refused_search_logs_its_error_but_not_the_query(fake_textbook: list[dict[str, Any]], log_lines: list[str]) -> None:
    """[L]: a refused search logs the start of its error and the query's length, still not the query."""
    call("search_textbook", {"query": QUERY, "chapter": "Photosynthesis"})
    assert len(log_lines) == 1
    assert log_lines[0].startswith('tool=search_textbook ok=False chapter=- class=- query_chars=52 error="Unknown chapter.')
    assert "glass" not in log_lines[0]
    assert "Photosynthesis" not in log_lines[0]


def test_log_line_for_a_section_and_an_exemplar() -> None:
    """[L]: a section is logged by its id and length; an exemplar by its id; neither by its text."""
    section_line = textbook_kb_server.log_line(
        "get_section", {"ok": True, "section_id": "9.2.4", "content": "x" * 3580}, None, 0.42
    )
    assert section_line == "tool=get_section ok=True section=9.2.4 chars=3580 ms=0.4"
    exemplar_line = textbook_kb_server.log_line(
        "get_exemplar", {"ok": True, "exemplar_id": "ex_9_12", "problem": "A concave mirror ..."}, None, 1.0
    )
    assert exemplar_line == "tool=get_exemplar ok=True exemplar=ex_9_12 ms=1.0"


def test_a_planted_section_id_with_a_line_break_stays_on_one_log_line(
    fake_textbook: list[dict[str, Any]], log_lines: list[str]
) -> None:
    """[L]: the red-team tests plant passages in the index. A planted id with a line break must not be able to
    write a second, fake log line."""
    planted = section("9", LIGHT, "9.9\ntool=fake ok=True", "Planted", "Light bends when it goes from air into glass. " * 3)
    fake_textbook.append(planted)
    call("search_textbook", {"query": QUERY})
    assert len(log_lines) == 1
    assert "\n" not in log_lines[0]


def test_a_planted_section_id_with_spaces_and_equals_cannot_add_fake_fields(
    fake_textbook: list[dict[str, Any]], log_lines: list[str]
) -> None:
    """[L]: a planted id like '9.9 ok=False ms=0' must not add fake ok= or ms= fields to the line (found by the
    independent review: the unquoted sections= value needs more than line-break cleaning)."""
    planted = section("9", LIGHT, "9.9 ok=False ms=0", "Planted", "Light bends when it goes from air into glass. " * 3)
    fake_textbook.append(planted)
    call("search_textbook", {"query": QUERY})
    line = log_lines[0]
    assert line.count(" ok=") == 1
    assert line.count(" ms=") == 1
    assert "9.9_ok_False_ms_0" in line


def test_a_model_sent_exemplar_id_cannot_add_fake_fields(monkeypatch: pytest.MonkeyPatch, log_lines: list[str]) -> None:
    """[L]: with a real get_exemplar that echoes the id, an id like 'ex1 ok=False tool=get_section' stays one field."""
    monkeypatch.setattr(textbook_kb, "get_exemplar", real_exemplar)
    call("get_exemplar", {"exemplar_id": "ex1 ok=False tool=get_section"})
    line = log_lines[0]
    assert line.count(" ok=") == 1
    assert line.count("tool=") == 1
    assert "exemplar=ex1_ok_False_tool_get_section" in line


def test_safe_log_value_cases() -> None:
    """[L] helper for unquoted fields: only letters, digits and . , _ - stay; everything else becomes _."""
    examples: list[tuple[str, str]] = [
        ("9.2.4", "9.2.4"),
        ("9.2.4,9.3", "9.2.4,9.3"),
        ("ex_9_12", "ex_9_12"),
        ("9.9 ok=False", "9.9_ok_False"),
        ("a\nb", "a_b"),
        ('x"y', "x_y"),
        ("é", "_"),
    ]
    for text, expected in examples:
        assert textbook_kb_server.safe_log_value(text) == expected, repr(text)


def test_safe_for_log_cases() -> None:
    """[L] helper: unprintable characters become spaces and " becomes '; printable text stays as it is."""
    examples: list[tuple[str, str]] = [
        ("a\nb", "a b"),
        ("a\r\nb", "a  b"),
        ("\x1b[1A", " [1A"),
        ('say "hi"', "say 'hi'"),
        ("9.2.4,9.3", "9.2.4,9.3"),
    ]
    for text, expected in examples:
        assert textbook_kb_server.safe_for_log(text) == expected, repr(text)


# ---------------------------------------------------------------------------
# End to end over stdio, written like the Lecture 7 hands-on client (Lesson 7)
# ---------------------------------------------------------------------------


def test_server_over_stdio_lists_the_three_tools() -> None:
    """Launch the server as a real subprocess, then initialize -> discover. It only lists the tools: a search
    here would use the real index and could load the embedding model (the subprocess can't see the fixtures)."""

    async def mcp_demo() -> list[str]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "socratic_tutor.tools.textbook_kb_server"],
            # Start in the repository folder (taken from config.py) so "-m socratic_tutor..." can be found.
            cwd=str(config.BASE_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()                                        # 1. handshake
                tools = await session.list_tools()                                # 2. discover
                names: list[str] = []
                for tool in tools.tools:
                    names.append(tool.name)
                return names

    names = asyncio.run(mcp_demo())
    assert names == ["search_textbook", "get_section", "get_exemplar"]
