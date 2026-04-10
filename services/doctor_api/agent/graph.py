"""LangGraph StateGraph definition for the CaduceusAI agent.

Graph topology
──────────────

             ┌─────────────┐
             │  triage_node │  ← entry point
             └──────┬───────┘
          ┌─────────┼──────────┐
       routine   complex    urgent
          │         │          │
          ▼         ▼          │
       rag_node  reasoning_node│
          │      ┌─────┴─────┐ │
          │   conf≥0.5  conf<0.5│
          │      │         └──┼─┘
          │      ▼            ▼
          │  retraining   escalation_node
          └──► trigger_node      │
                   │             ▼
                  END           END

All terminal nodes (retraining_trigger_node, escalation_node) write to
the audit log before finishing.

LangGraph Studio compatibility
───────────────────────────────
The module-level `graph` variable is the compiled graph.  Point LangGraph
Studio at this file via langgraph.json:

    {
      "graphs": { "caduceus_agent": "./agent/graph.py:graph" }
    }

Call `get_graph_definition()` to obtain a JSON-serialisable representation
for custom visualisation endpoints.
"""

from langgraph.graph import END, StateGraph

from .nodes import (
    escalation_node,
    rag_node,
    reasoning_node,
    retraining_trigger_node,
    triage_node,
)
from .state import AgentState


# ── Conditional edge routing functions ───────────────────────────────────────


def _route_after_triage(state: AgentState) -> str:
    """Route to rag, reasoning, or escalation based on triage classification."""
    return state["query_type"]  # "routine" | "complex" | "urgent"


def _route_after_reasoning(state: AgentState) -> str:
    """Escalate if reasoning confidence is low; otherwise proceed to retrain check."""
    return "escalate" if state["confidence"] < 0.5 else "respond"


# ── Graph construction ────────────────────────────────────────────────────────


def _build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)

    workflow.add_node("triage", triage_node)
    workflow.add_node("rag", rag_node)
    workflow.add_node("reasoning", reasoning_node)
    workflow.add_node("escalation", escalation_node)
    workflow.add_node("retraining_trigger", retraining_trigger_node)

    workflow.set_entry_point("triage")

    workflow.add_conditional_edges(
        "triage",
        _route_after_triage,
        {
            "routine": "rag",
            "complex": "reasoning",
            "urgent": "escalation",
        },
    )

    workflow.add_conditional_edges(
        "reasoning",
        _route_after_reasoning,
        {
            "escalate": "escalation",
            "respond": "retraining_trigger",
        },
    )

    workflow.add_edge("rag", "retraining_trigger")
    workflow.add_edge("escalation", END)
    workflow.add_edge("retraining_trigger", END)

    return workflow


# Module-level compiled graph — referenced by LangGraph Studio.
graph = _build_graph().compile()


def get_graph_definition() -> dict:
    """Return the graph structure as a JSON-serialisable dict.

    Suitable for the /v1/agent/graph visualisation endpoint or for embedding
    in developer tooling.  Uses LangGraph's built-in graph introspection.
    """
    return graph.get_graph().to_json()
