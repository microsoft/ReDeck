"""ReDeck — Agent-based slide repair with tool-calling loop.

Active modules:
  - dispatcher.py:     Main dispatcher (Phase 1 content patch → Phase 2 agent repair)
  - agent_repair.py:   AgentRepair (autonomous tool-calling repair agent)
  - spatial_state.py:  Static code analysis for element positions
  - slide_manifest.py: Issue filtering and containment overlap detection
"""
