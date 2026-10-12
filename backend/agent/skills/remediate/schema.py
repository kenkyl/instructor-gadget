"""remediate: the plan-change "why", remediation lessons and override warnings (spec §4.8).

Never cached: every input carries this learner's results (ADR-0007). Models live in
agent/types.py so services can import them.
"""

from agent.types import (
    ExplainInput,
    ExplainOutput,
    LessonOutput,
    RemediationLessonInput,
    WarningInput,
    WarningOutput,
)

CALLS = {
    "explain_change": (ExplainInput, ExplainOutput),
    "prereq_warning": (WarningInput, WarningOutput),
    "lesson": (RemediationLessonInput, LessonOutput),
}
