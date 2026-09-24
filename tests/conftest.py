import os

_REQUIRED_DEFAULTS = {
    "GOOGLE_MAPS_BROWSER_KEY": "test-browser-key",
    "GOOGLE_MAPS_MAP_ID": "test-map-id",
    "LLM_API_KEY": "test-llm-key",
    "LLM_MODEL": "claude-sonnet-4-5",
}

for _key, _value in _REQUIRED_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# Force tracing off regardless of the developer's own shell environment. If a real
# LANGSMITH_API_KEY happens to be set globally, app.config's own startup logic would
# otherwise flip LANGSMITH_TRACING on (via setdefault) and @traceable would attempt
# real network calls during a test run — direct assignment here runs first and wins,
# since app.config only ever uses setdefault for this variable.
os.environ["LANGSMITH_TRACING"] = "false"
