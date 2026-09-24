from app.llm import build_system_prompt


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
