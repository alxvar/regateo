"""The engine's opponents: scripted sparring partners, LLM personas, the plain end-to-end agent,
idea-1's Boulware engine and the red-team attackers. Agent builders never see this package
(docs/06-agent-contract.md §5).

Importing it registers every kind: scripted:<name>, persona:<name>, o1, boulware and redteam:<name>.
"""
from regateo.opponents import boulware, llm, redteam, scripted  # noqa: F401  (registers builders)
