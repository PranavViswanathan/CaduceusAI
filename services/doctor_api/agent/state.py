from typing import Optional, TypedDict


class AgentState(TypedDict):
    """Typed state passed between every node in the CaduceusAI agent graph.

    Fields are merged incrementally — each node returns only the keys it
    modifies and LangGraph preserves the rest unchanged.
    """

    # ── Request context ──────────────────────────────────────────────────────
    query: str
    """The raw clinical query submitted by the clinician."""

    patient_id: Optional[str]
    """Optional patient UUID to associate this query with a patient record."""

    actor_id: Optional[str]
    """UUID of the authenticated doctor who submitted the query (for audit)."""

    ip_address: Optional[str]
    """Client IP address captured at the HTTP boundary (for audit)."""

    # ── Triage result ─────────────────────────────────────────────────────────
    query_type: str
    """Classification produced by triage_node: 'routine' | 'complex' | 'urgent'."""

    # ── RAG context ───────────────────────────────────────────────────────────
    rag_context: list[str]
    """Knowledge-base documents retrieved by rag_node (empty for other paths)."""

    # ── Reasoning trace ───────────────────────────────────────────────────────
    chain_of_thought: str
    """Step-by-step reasoning produced by reasoning_node (empty for other paths)."""

    # ── Final response ────────────────────────────────────────────────────────
    response: str
    """The agent's final response text returned to the caller."""

    confidence: float
    """Model confidence in the response as a float in [0.0, 1.0]."""

    # ── Escalation state ──────────────────────────────────────────────────────
    requires_escalation: bool
    """True when the query was routed to escalation_node."""

    escalation_id: Optional[str]
    """UUID of the AgentEscalation record created by escalation_node, if any."""

    # ── Retraining signal ─────────────────────────────────────────────────────
    feedback_score: Optional[float]
    """Clinician feedback score (0.0–1.0) for a prior response on this topic.
    Passed in from the API caller; triggers retraining if below threshold."""

    feedback_assessment_id: Optional[str]
    """Assessment UUID associated with the feedback, forwarded to the retrain queue."""
