"""Policy engine: agent-independent enforcement rules (docs/policy-engine.md).

The source of truth is python/rak/policy/. Plugins carry a byte-identical copy in _vendor/rak_policy/
(scripts/vendor_policy.py writes it; a test fails if a copy differs), so no plugin needs `pip install`.
"""
from .engine import CHECKS, Decision, Event, PolicyError, evaluate, evaluate_closed, load_rules  # noqa: F401
from .adapters import claude_code_ask, claude_code_event  # noqa: F401
