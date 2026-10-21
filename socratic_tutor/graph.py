"""LangGraph workflow definition for Socratic Tutor."""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from socratic_tutor.state import SocraticState
from socratic_tutor.policy import check_input_guardrails, check_answer_leak
from socratic_tutor import config


# --- Node Definitions ---

def node_input_guardrail(state: SocraticState) -> dict:
    guard_res = check_input_guardrails(state.get("query", ""))
    if not guard_res["passed"]:
        return {
            "steps": ["input_guardrail"],
            "injection_detected": guard_res["is_injection"],
            "teacher_alert_triggered": guard_res["is_distress"],
            "response": "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."
        }
    return {
        "steps": ["input_guardrail"],
        "query": guard_res["sanitized_query"],
        "injection_detected": False
    }


def node_supervisor(state: SocraticState) -> dict:
    # Routes based on mode ("practice" vs "quiz")
    return {"steps": ["supervisor"]}


def node_diagnostician(state: SocraticState) -> dict:
    # Analyzes query for misconceptions
    return {
        "steps": ["diagnostician"],
        "identified_misconception": {"id": "MISCON_LIGHT_01", "name": "Concave image inverted"}
    }


def node_tutor(state: SocraticState) -> dict:
    # Emits Socratic hint
    hint = "Recall the rule for rays passing through the Center of Curvature. Where do they reflect?"
    return {
        "steps": ["tutor"],
        "response": hint,
        "citations": ["NCERT Class 10 Science, Sec 10.2.1"]
    }


def node_grader(state: SocraticState) -> dict:
    return {"steps": ["grader"]}


def node_question_setter(state: SocraticState) -> dict:
    # Proposes question for the shared bank
    return {
        "steps": ["question_setter"],
        "teacher_approval_required": True,
        "teacher_approval_payload": {"concept": "10.2.1", "prompt": "State the laws of reflection."}
    }


# TODO (Milestone 7 / L14): Implement Teacher Approval Gate with interrupt()
def node_teacher_approval_gate(state: SocraticState) -> dict:
    """Pauses graph execution via interrupt() to await teacher sign-off."""
    payload = state.get("teacher_approval_payload", {})
    # In LangGraph: interrupt({"payload": payload, "prompt": "Approve new question for shared bank?"})
    return {
        "steps": ["teacher_approval_gate"],
        "teacher_approval_required": False
    }


def route_guardrail(state: SocraticState) -> str:
    if state.get("injection_detected") or state.get("teacher_alert_triggered"):
        return END
    return "supervisor"


def route_mode(state: SocraticState) -> str:
    # TODO (Milestone 6 / L8): Route between practice hint dialogue and quiz evaluation
    if state.get("mode") == "quiz":
        return "grader"
    return "diagnostician"


# --- Graph Construction ---

def build_graph(checkpointer=None):
    workflow = StateGraph(SocraticState)

    workflow.add_node("input_guardrail", node_input_guardrail)
    workflow.add_node("supervisor", node_supervisor)
    workflow.add_node("diagnostician", node_diagnostician)
    workflow.add_node("tutor", node_tutor)
    workflow.add_node("grader", node_grader)
    workflow.add_node("question_setter", node_question_setter)
    workflow.add_node("teacher_approval_gate", node_teacher_approval_gate)

    workflow.add_edge(START, "input_guardrail")
    workflow.add_conditional_edges("input_guardrail", route_guardrail)
    workflow.add_conditional_edges("supervisor", route_mode)
    workflow.add_edge("diagnostician", "tutor")
    workflow.add_edge("tutor", END)
    workflow.add_edge("grader", END)
    workflow.add_edge("question_setter", "teacher_approval_gate")
    workflow.add_edge("teacher_approval_gate", END)

    return workflow.compile(checkpointer=checkpointer)

