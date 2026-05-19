"""ReDeck — Agent-based slide repair with tool-calling loop.

Active modules:
  - repair_worker.py:  Main dispatcher (filter → AgentRepair → validate)
  - agent_repair.py:   AgentRepair (autonomous tool-calling repair agent)
  - spatial_state.py:  Static code analysis for element positions
  - slide_manifest.py: Issue filtering and containment overlap detection
"""
