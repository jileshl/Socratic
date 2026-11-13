"""learner-store MCP server: the learner model as tools (capstone guide p.12, "learner-store: read, update
mastery; explain why this write needs no approval").

    get_learner_profile   READ   mastery per topic, misconceptions seen, lessons that worked, failure streaks
    update_mastery        WRITE  set one topic's mastery from a graded quiz (0 to 1)

Why update_mastery needs no teacher approval, unlike question-bank.propose_question:
- it changes only this student's own record, under a pseudonymous ID, never anything another student sees;
- the value comes from the grader's code (math-tools), not from a model, and it is checked (0 to 1, a known
  topic, a valid ID);
- it is reversible (the next quiz result overwrites it) and deletable ("Delete my data", or the teacher);
- a person approving every quiz score would make the tutor unusable, with no safety gain.
Only the supervisor (code) writes mastery; the tool hooks give this write to no model-driven agent.

Run it: python -m socratic_tutor.tools.learner_store_server            (stdio)
        python -m socratic_tutor.tools.learner_store_server --http 8104 (HTTP, inside Docker)
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore

logger = logging.getLogger("learner-store")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

STUDENT_ID = re.compile(r"^stu_[A-Za-z0-9_]{1,40}$")


class ProfileResult(TypedDict, total=False):
    ok: bool
    student_id: str
    mastery: dict[str, float]
    misconceptions: list[dict[str, Any]]
    lessons: list[Any]
    failure_streaks: dict[str, int]
    error: str


class UpdateResult(TypedDict, total=False):
    ok: bool
    student_id: str
    concept_id: str
    mastery: float
    error: str


def _store() -> LearnerStore:
    return LearnerStore()


mcp = MCPServer(
    "learner-store",
    instructions="The learner model for one pseudonymous student: read it, or set one topic's mastery from a graded quiz.",
)


PROFILE_DESCRIPTION = ("Read one student's learner record: mastery per topic (0 to 1), misconceptions seen (with whether "
                       "they are sorted), teaching lessons that worked, and failure streaks per topic. The ID is pseudonymous (stu_...).")
UPDATE_DESCRIPTION = ("Set one topic's mastery (0 to 1) for one student, from a quiz the grader's code has marked. WRITE tool: "
                      "it changes only this student's own record and is reversible, so it needs no teacher approval.")


@mcp.tool(description=PROFILE_DESCRIPTION, annotations=ToolAnnotations(readOnlyHint=True))
def get_learner_profile(student_id: str) -> ProfileResult:
    """Read one student's learner record: mastery per topic (0 to 1), misconceptions seen (with whether they are
    sorted), teaching lessons that worked, and failure streaks per topic. The ID is pseudonymous (stu_...)."""
    if not STUDENT_ID.match(student_id or ""):
        return {"ok": False, "error": "student_id must look like stu_<letters/digits>"}
    try:
        p = _store().get_profile(student_id)
    except Exception as error:  # errors are results, not crashes (capstone guide p.3)
        logger.info("tool=get_learner_profile ok=False error=%s", type(error).__name__)
        return {"ok": False, "error": f"could not read the record ({type(error).__name__})"}
    logger.info("tool=get_learner_profile ok=True topics=%d", len(p.get("mastery_map") or {}))
    return {"ok": True, "student_id": student_id, "mastery": dict(p.get("mastery_map") or {}),
            "misconceptions": list(p.get("misconceptions") or []), "lessons": list(p.get("lessons") or []),
            "failure_streaks": dict(p.get("failure_streaks") or {})}


@mcp.tool(description=UPDATE_DESCRIPTION, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True))
def update_mastery(student_id: str, concept_id: str, score: float) -> UpdateResult:
    """Set one topic's mastery (0 to 1) for one student, from a quiz the grader's code has marked. WRITE tool:
    it changes only this student's own record and is reversible; see the module notes for why it needs no
    teacher approval."""
    if not STUDENT_ID.match(student_id or ""):
        return {"ok": False, "error": "student_id must look like stu_<letters/digits>"}
    if concept_id not in ConceptGraph().concepts:
        return {"ok": False, "error": f"unknown topic: {concept_id}"}
    try:
        _store().update_mastery(student_id, concept_id, float(score))
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    except Exception as error:
        logger.info("tool=update_mastery ok=False error=%s", type(error).__name__)
        return {"ok": False, "error": f"could not update ({type(error).__name__})"}
    logger.info("tool=update_mastery ok=True concept=%s", concept_id)
    return {"ok": True, "student_id": student_id, "concept_id": concept_id, "mastery": round(float(score), 2)}


if __name__ == "__main__":
    from socratic_tutor.tools.serve import main

    main(mcp)
