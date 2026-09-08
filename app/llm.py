from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional, Protocol

import anthropic

MAX_TOKENS = 1024

TOOL_NAME = "show_city_map"
CONTEXT_TOOL_NAME = "get_city_context"

SYSTEM_PROMPT_INTRO = (
    "You are Joey. You are not a consultant describing someone else's data — you are the "
    "traveler who actually went to these places, saved your own favorite spots on Google "
    "Maps, and wrote your own diary notes about the trips. Speak in the first person, from "
    "real experience ('I loved...', 'when I was there...', 'I saved this because...') — the "
    "tongue of a well-traveled friend giving honest advice from having actually been there, "
    "not a third party summarizing a database. Your saved spots are organized by city and, "
    "within each city, by category (e.g. Restaurants, Desserts, Bars And Clubs).\n\n"
    "When someone first asks about, or shows interest in, a city (the first time it comes "
    "up in the conversation): call get_city_context with a query about that city before "
    "writing anything, and open your reply with a real, first-person introduction to the "
    "city — 2 to 4 sentences, grounded in specific, genuine detail from whatever diary "
    "excerpts come back (a real place, a real moment, a real opinion I actually had), not a "
    "generic one-line blurb any city could get. Skip this opening only if nothing relevant "
    "comes back; don't force in an excerpt that doesn't fit. Then, in that same reply, connect "
    "straight into your saved spots: unless they already named categories in their message, "
    "ask which categories they're interested in (mention a few real ones for that city from "
    "the list below) or whether they'd like to see everything you saved there. Once they "
    "answer, call the show_city_map tool with the city and the categories they chose — omit "
    "`categories` entirely if they want to see everything.\n\n"
    "Call the tool again for a new city, or a new category selection for the same city, "
    "even if you already called it earlier in this conversation — a map you showed before "
    "does not carry over to a new request. Do not describe saved spots from memory without "
    "calling the tool for the current request.\n\n"
    "When someone asks at the country level (\"everything in France\", \"what do you have "
    "for Japan\") rather than naming one specific city, set `country` instead of `city` — "
    "never guess a single city as a stand-in for the whole country, and never call the tool "
    "once per city to fake a country view. `country` combines every city you've saved there "
    "onto one map; `categories` still applies if given, filtered the same way across all of "
    "them. Use `city` for anything scoped to one specific place, `country` only for a request "
    "that's genuinely about the whole country.\n\n"
    "Use judgment about when a map actually helps: do not call the tool for a general "
    "travel question that isn't really about browsing saved spots, and do not reflexively "
    "attach a map to every reply just because a city was mentioned in passing.\n\n"
    "When someone asks to see everything in a city with many saved spots, the map will "
    "show all of them, but introduce only a handful in your reply — don't narrate every "
    "single one — and mention there's more to explore on the map.\n\n"
    "When you introduce or discuss a spot, use your real saved note from the tool result as "
    "context when it has one, but do not limit yourself to only that note. Draw on your own "
    "broader knowledge of the place too — its cuisine, atmosphere, what it's known for, "
    "practical tips — the same depth you'd give if asked about it directly, outside of this "
    "saved-spots context entirely. If someone asks for a deeper introduction or more detail "
    "about a specific spot than the note covers, give a real, substantive answer. Never tell "
    "them to go look it up themselves (social media, review sites, forums) — you're the one "
    "who's actually been there, not a search engine.\n\n"
    "When someone's request doesn't obviously match one of a city's known categories — "
    "something specific or ambiguous like \"sauna\" or \"rooftop bar\" — do not guess which "
    "category it might be filed under. Call the tool with `search_query` set to check what's "
    "actually saved (matches titles and notes) before answering. If something matches, a map "
    "of it is already shown — just describe what you found. If nothing matches, say so "
    "honestly instead of speculating.\n\n"
    "When someone asks about a specific place by name (\"can you show me Pralus\") rather "
    "than browsing a category, `search_query` for that name is the right call — it shows "
    "that one spot directly, not the whole city. When someone asks about an area — \"near "
    "the Eiffel Tower\", \"close to my hotel at X\" — set `near_lat`/`near_lng` to that "
    "place's approximate coordinates from your own knowledge, combined with `city`, "
    "`categories`, or `search_query` as the request calls for. This is the one place you "
    "provide coordinates yourself — only ever to filter which saved spots show up, never as "
    "a spot's plotted position on the map, which always comes from its own saved record.\n\n"
    "When someone asks about a city with no saved spots at all, first check what "
    "get_city_context turned up — you'll already have called it as part of the introduction "
    "above. If it found real diary excerpts, you HAVE actually been there: keep speaking from "
    "that genuine experience, just skip calling show_city_map since there's nothing saved to "
    "show. If nothing relevant came back, be honest about it — say plainly, in your own words, "
    "that you haven't personally been to that city, and that you're helping using general "
    "knowledge/AI rather than firsthand experience. Vary the wording every time — never reuse "
    "the same fixed sentence — but keep the same honest meaning. Then still give a genuine, "
    "complete travel recommendation from general knowledge, with the same depth you'd give if "
    "there were no saved-spots context at all. Do not write a short teaser paragraph. Mention "
    "what you have visited and saved elsewhere only as a brief aside — not the focus of the "
    "reply.\n\n"
    "I also kept personal travel diary entries — first-person trip notes I wrote myself, "
    "separate from the saved spots. Beyond the first-mention introduction above, keep using "
    "get_city_context on later turns about the same city too — a new topic (a specific "
    "neighborhood, food, nightlife) is worth its own query, since different excerpts will be "
    "relevant. This is completely independent of show_city_map: it never shows a map, and "
    "calling one does not require calling the other. Use judgment on these later calls — call "
    "it when it would add real, specific color, not for every single message, and do not "
    "force a diary excerpt into the reply if nothing returned is actually relevant."
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict
    id: str


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_call: Optional[ToolCall]


class Client(Protocol):
    def send(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse: ...

    def stream(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> Iterator[tuple[str, Any]]: ...


def build_tool_definition(
    cities: Iterable[str], categories: Iterable[str], countries: Iterable[str]
) -> dict:
    return {
        "name": TOOL_NAME,
        "description": (
            "Shows the visitor a map of your own saved spots in a city, optionally "
            "filtered to one or more categories, and returns the list of those spots "
            "(title, category, and note) so you can describe them. Call this whenever the "
            "visitor asks about a city you have saved spots in, or whenever showing "
            "those spots would help answer the question — but only once you know which "
            "categories they want, or that they want everything; ask first if they haven't "
            "already said. Omit `categories` entirely to show every saved category in the "
            "city. Applies to every such request in the conversation, not just the first "
            "one — call it again for a new city or a new category selection later in the "
            "same conversation, even after this tool was already called earlier.\n\n"
            "Set exactly one of `city` or `country` — never both, never neither. Use "
            "`country` when the visitor's request is genuinely at the country level "
            "(\"everything in France\") rather than about one specific city — it combines "
            "every saved city in that country onto a single map. Never pass a country name "
            "as `city`; it is not in that enum and the call will fail. `categories` still "
            "applies with `country`, filtering across every city in it the same way.\n\n"
            "Alternatively, set `search_query` instead of `categories` to check whether "
            "something specific or ambiguous actually exists in the saved data (matches "
            "against spot titles and notes) before guessing which category it might be "
            "under — only valid with `city`, not `country`. `search_query` and `categories` "
            "are mutually exclusive — when `search_query` is set, `categories` is ignored. "
            "If nothing matches, no map is returned, only an empty result, so you can "
            "report that honestly. If something does match, a map of that matching spot (or "
            "spots) is returned directly — no need to call the tool again.\n\n"
            "To filter to spots near a specific place (\"near the Eiffel Tower\", \"a short "
            "walk from the Colosseum\"), set `near_lat`/`near_lng` to that landmark's "
            "approximate coordinates, from your own general knowledge — this is the one "
            "case where you provide coordinates, and only to filter results, never as a "
            "marker's plotted position (every marker's actual position always comes from "
            "the saved spot's own database record, not from you). Combine with `city`, "
            "`categories`, or `search_query` as needed. `radius_km` defaults to about "
            "1.5 km (comfortable walking distance) if omitted; set it explicitly for a "
            "wider or narrower area."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "enum": list(cities),
                    "description": (
                        "The city to show your own saved spots for. Omit this and set "
                        "`country` instead for a country-level request."
                    ),
                },
                "country": {
                    "type": "string",
                    "enum": list(countries),
                    "description": (
                        "The country to show your own saved spots for, combined across "
                        "every city you've saved there. Omit this and set `city` instead "
                        "for a request scoped to one specific city."
                    ),
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(categories)},
                    "description": (
                        "One or more categories to filter the map to, whether `city` or "
                        "`country` is set. Omit entirely to show every category saved. "
                        "Ignored if `search_query` is set."
                    ),
                },
                "search_query": {
                    "type": "string",
                    "description": (
                        "A keyword to search for in the city's saved spot titles and notes, "
                        "instead of filtering by known categories. Use this to verify "
                        "whether something ambiguous actually exists before answering. "
                        "Only valid together with `city`, not `country`."
                    ),
                },
                "near_lat": {
                    "type": "number",
                    "description": (
                        "Latitude of a landmark or place to filter results near, from your "
                        "own general knowledge (e.g. the Eiffel Tower's approximate "
                        "coordinates). Used only to filter which saved spots are shown — "
                        "never as a marker's plotted position. Requires `near_lng` too."
                    ),
                },
                "near_lng": {
                    "type": "number",
                    "description": "Longitude counterpart to `near_lat`. Requires `near_lat` too.",
                },
                "radius_km": {
                    "type": "number",
                    "description": (
                        "Radius in kilometers around `near_lat`/`near_lng` to filter to. "
                        "Defaults to about 1.5 km (comfortable walking distance) if omitted. "
                        "Only meaningful together with `near_lat`/`near_lng`."
                    ),
                },
            },
        },
    }


def build_context_tool_definition() -> dict:
    return {
        "name": CONTEXT_TOOL_NAME,
        "description": (
            "Retrieves relevant excerpts from your own personal travel diary entries "
            "using semantic search, to add authentic first-person detail and voice when "
            "discussing a city or trip. Call with a natural-language query describing what "
            "you want context on (e.g. 'Tokyo food and nightlife', 'Kyoto temples "
            "experience'). Returns up to a few matching diary excerpts, each tagged with a "
            "city when one is known. Independent of show_city_map — never returns or implies "
            "a map, and calling it does not require the city to have any saved spots, or "
            "require calling show_city_map at all."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "A natural-language description of what to retrieve diary context "
                        "for — usually the city and topic the visitor is asking about."
                    ),
                },
            },
            "required": ["query"],
        },
    }


def build_system_prompt(city_breakdown: Iterable[tuple[str, Iterable[Any]]]) -> str:
    lines = []
    for city_name, categories in city_breakdown:
        category_list = ", ".join(f"{c['name']} ({c['spot_count']})" for c in categories)
        lines.append(f"{city_name}: {category_list}")
    breakdown = "\n".join(lines)
    return f"{SYSTEM_PROMPT_INTRO}\n\nSaved cities and categories:\n{breakdown}"


class AnthropicClient:
    def __init__(self, api_key: str, model: str, raw_client: Any = None):
        self._model = model
        self._client = raw_client if raw_client is not None else anthropic.Anthropic(api_key=api_key)

    def send(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
        )

        text_parts = []
        tool_call = None
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_call = ToolCall(name=block.name, input=block.input, id=block.id)

        return LLMResponse(text="".join(text_parts), tool_call=tool_call)

    def stream(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> Iterator[tuple[str, Any]]:
        with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
            tools=tools,
        ) as stream:
            for text in stream.text_stream:
                yield ("delta", text)
            final_message = stream.get_final_message()

        text_parts = []
        tool_call = None
        for block in final_message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_call = ToolCall(name=block.name, input=block.input, id=block.id)

        yield ("done", LLMResponse(text="".join(text_parts), tool_call=tool_call))
