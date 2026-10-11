"""map-concepts: the concept map with prerequisites (spec §4.4).

The models live in agent/types.py because this folder name isn't importable and services need
them. Graph rules are code (agent/plan.py), run as validators, so a bad map earns one re-ask.
"""

from agent.types import MapInput, MapOutput

CALLS = {"map": (MapInput, MapOutput)}
