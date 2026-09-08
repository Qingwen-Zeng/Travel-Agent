from types import SimpleNamespace

from app.llm import (
    AnthropicClient,
    build_context_tool_definition,
    build_system_prompt,
    build_tool_definition,
)


class FakeMessages:
    def __init__(self, response):
        self._response = response
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return self._response


class FakeRawClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def _text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _tool_use_response(name, tool_input, tool_id="toolu_1"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name=name, input=tool_input, id=tool_id)]
    )


def test_build_tool_definition_has_expected_name_and_city_enum():
    tool = build_tool_definition(["Zurich", "Barcelona"], ["Restaurants", "Bars"], ["Switzerland"])

    assert tool["name"] == "show_city_map"
    assert "map" in tool["description"].lower()
    assert "city" in tool["description"].lower()
    assert tool["input_schema"]["properties"]["city"]["enum"] == ["Zurich", "Barcelona"]
    assert "required" not in tool["input_schema"]


def test_build_tool_definition_country_is_optional_with_enum():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland", "France"])

    country_schema = tool["input_schema"]["properties"]["country"]
    assert country_schema["enum"] == ["Switzerland", "France"]
    assert "required" not in tool["input_schema"]


def test_build_tool_definition_description_states_city_and_country_are_mutually_exclusive():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])

    description = tool["description"].lower()
    assert "exactly one of `city` or `country`" in description


def test_build_tool_definition_categories_is_optional_array_with_enum():
    tool = build_tool_definition(["Zurich"], ["Restaurants", "Bars"], ["Switzerland"])

    categories_schema = tool["input_schema"]["properties"]["categories"]
    assert categories_schema["type"] == "array"
    assert categories_schema["items"]["enum"] == ["Restaurants", "Bars"]


def test_build_tool_definition_description_states_trigger_condition():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])

    description = tool["description"].lower()
    assert "whenever" in description or "should be called" in description
    assert "categor" in description
    assert "everything" in description or "all" in description


def test_build_tool_definition_search_query_is_optional_plain_string():
    tool = build_tool_definition(["Zurich"], ["Restaurants", "Bars"], ["Switzerland"])

    search_schema = tool["input_schema"]["properties"]["search_query"]
    assert search_schema["type"] == "string"
    assert "enum" not in search_schema


def test_build_tool_definition_description_explains_search_query():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])

    description = tool["description"].lower()
    assert "search_query" in description
    assert "categories" in description


def test_build_tool_definition_has_near_lat_lng_and_radius_as_plain_numbers():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])

    properties = tool["input_schema"]["properties"]
    for field in ("near_lat", "near_lng", "radius_km"):
        assert properties[field]["type"] == "number"
        assert "enum" not in properties[field]


def test_build_tool_definition_description_explains_near_filtering_never_plots_markers():
    tool = build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])

    description = tool["description"].lower()
    assert "near_lat" in description
    assert "never as a marker" in description


def test_build_context_tool_definition_has_expected_name_and_query_param():
    tool = build_context_tool_definition()

    assert tool["name"] == "get_city_context"
    assert tool["input_schema"]["properties"]["query"]["type"] == "string"
    assert "enum" not in tool["input_schema"]["properties"]["query"]
    assert tool["input_schema"]["required"] == ["query"]


def test_build_context_tool_definition_description_notes_independence_from_map():
    tool = build_context_tool_definition()

    description = tool["description"].lower()
    assert "show_city_map" in description
    assert "independent" in description or "never" in description


def test_build_system_prompt_includes_city_category_breakdown():
    city_breakdown = [
        ("Zurich", [{"name": "Restaurants", "spot_count": 10}, {"name": "Bars", "spot_count": 3}]),
        ("Barcelona", [{"name": "Restaurants", "spot_count": 12}]),
    ]

    prompt = build_system_prompt(city_breakdown)

    assert "Zurich" in prompt
    assert "Restaurants (10)" in prompt
    assert "Bars (3)" in prompt
    assert "Barcelona" in prompt
    assert "Restaurants (12)" in prompt


def test_build_system_prompt_instructs_asking_about_categories_first():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "categor" in lowered
    assert "ask" in lowered


def test_build_system_prompt_instructs_judgment_about_showing_the_map():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "not" in lowered and "every" in lowered


def test_build_system_prompt_instructs_searching_before_guessing_a_category():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "search_query" in lowered
    assert "guess" in lowered


def test_build_system_prompt_instructs_full_recommendations_for_unsaved_cities():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "no saved spots" in lowered
    assert "full" in lowered or "genuine" in lowered or "complete" in lowered
    assert "aside" in lowered or "brief" in lowered


def test_build_system_prompt_instructs_honest_first_person_when_never_been():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "haven't personally been" in lowered
    assert "vary the wording" in lowered
    assert "get_city_context" in lowered


def test_build_system_prompt_establishes_first_person_joey_persona():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "joey" in lowered
    assert "first person" in lowered


def test_build_system_prompt_instructs_calling_get_city_context_for_diary_color():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "get_city_context" in lowered
    assert "diary" in lowered
    assert "independent" in lowered


def test_build_system_prompt_instructs_diary_intro_before_category_question():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    first_mention_idx = lowered.index("first")
    get_city_context_idx = lowered.index("get_city_context")
    ask_categories_idx = lowered.index("ask which categories")

    assert first_mention_idx < get_city_context_idx < ask_categories_idx


def test_build_system_prompt_instructs_multi_sentence_diary_intro():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "2 to 4 sentences" in lowered
    assert "generic" in lowered


def test_build_system_prompt_instructs_using_country_for_country_level_requests():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "`country`" in lowered
    assert "never guess a single city" in lowered


def test_build_system_prompt_instructs_near_lat_lng_for_proximity_requests():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "near_lat" in lowered
    assert "never as a spot's plotted position" in lowered


def test_build_system_prompt_instructs_search_query_for_a_single_named_spot():
    prompt = build_system_prompt([])

    lowered = prompt.lower()
    assert "search_query" in lowered
    assert "one spot directly" in lowered


def test_send_returns_text_when_model_does_not_call_tool():
    raw = FakeRawClient(_text_response("Hello there!"))
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)

    response = client.send(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert response.text == "Hello there!"
    assert response.tool_call is None


def test_send_returns_tool_call_when_model_calls_tool():
    raw = FakeRawClient(
        _tool_use_response("show_city_map", {"city": "Zurich", "categories": ["Bars"]}, tool_id="toolu_42")
    )
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)

    response = client.send(
        system="sys", messages=[{"role": "user", "content": "tell me about zurich"}], tools=[]
    )

    assert response.text == ""
    assert response.tool_call.name == "show_city_map"
    assert response.tool_call.input == {"city": "Zurich", "categories": ["Bars"]}
    assert response.tool_call.id == "toolu_42"


def test_send_passes_model_system_messages_and_tools_to_raw_client():
    raw = FakeRawClient(_text_response("ok"))
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)
    tools = [build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])]
    messages = [{"role": "user", "content": "hi"}]

    client.send(system="be nice", messages=messages, tools=tools)

    kwargs = raw.messages.last_call_kwargs
    assert kwargs["model"] == "claude-sonnet-4-5"
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == messages
    assert kwargs["tools"] == tools


class FakeStreamContext:
    def __init__(self, text_chunks, final_message):
        self._text_chunks = text_chunks
        self._final_message = final_message

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(self._text_chunks)

    def get_final_message(self):
        return self._final_message


class FakeStreamingMessages:
    def __init__(self, text_chunks, final_message):
        self._text_chunks = text_chunks
        self._final_message = final_message
        self.last_call_kwargs = None

    def stream(self, **kwargs):
        self.last_call_kwargs = kwargs
        return FakeStreamContext(self._text_chunks, self._final_message)


class FakeStreamingRawClient:
    def __init__(self, text_chunks, final_message):
        self.messages = FakeStreamingMessages(text_chunks, final_message)


def test_stream_yields_deltas_then_done_with_text_response():
    raw = FakeStreamingRawClient(["Hello", " there"], _text_response("Hello there"))
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)

    events = list(client.stream(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[]))

    assert events[0] == ("delta", "Hello")
    assert events[1] == ("delta", " there")
    assert events[2][0] == "done"
    assert events[2][1].text == "Hello there"
    assert events[2][1].tool_call is None


def test_stream_yields_done_with_tool_call_when_model_calls_tool():
    raw = FakeStreamingRawClient(
        [], _tool_use_response("show_city_map", {"city": "Zurich"}, tool_id="toolu_9")
    )
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)

    events = list(
        client.stream(system="sys", messages=[{"role": "user", "content": "zurich?"}], tools=[])
    )

    assert events == [("done", events[0][1])]
    done_response = events[-1][1]
    assert done_response.text == ""
    assert done_response.tool_call.name == "show_city_map"
    assert done_response.tool_call.input == {"city": "Zurich"}
    assert done_response.tool_call.id == "toolu_9"


def test_stream_passes_model_system_messages_and_tools_to_raw_client():
    raw = FakeStreamingRawClient(["ok"], _text_response("ok"))
    client = AnthropicClient(api_key="unused", model="claude-sonnet-4-5", raw_client=raw)
    tools = [build_tool_definition(["Zurich"], ["Restaurants"], ["Switzerland"])]
    messages = [{"role": "user", "content": "hi"}]

    list(client.stream(system="be nice", messages=messages, tools=tools))

    kwargs = raw.messages.last_call_kwargs
    assert kwargs["model"] == "claude-sonnet-4-5"
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == messages
    assert kwargs["tools"] == tools
