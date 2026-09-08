import os

_REQUIRED_DEFAULTS = {
    "GOOGLE_MAPS_BROWSER_KEY": "test-browser-key",
    "GOOGLE_MAPS_MAP_ID": "test-map-id",
    "LLM_API_KEY": "test-llm-key",
    "LLM_MODEL": "claude-sonnet-4-5",
}

for _key, _value in _REQUIRED_DEFAULTS.items():
    os.environ.setdefault(_key, _value)
