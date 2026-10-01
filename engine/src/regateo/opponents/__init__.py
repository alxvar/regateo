"""The engine's opponents: scripted sparring partners, LLM personas, the plain end-to-end agent and
idea-1's Boulware engine. Agent builders never see this package (docs/06-agent-contract.md §5).

Importing it registers every kind: scripted:<name>, persona:<name>, o1 and boulware.
"""
from regateo.opponents import boulware, llm, scripted  # noqa: F401  (registers builders)
