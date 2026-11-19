"""Owner-run LangSmith eval for the chat agent's Faithfulness/Groundedness and Answer
Relevancy — NOT part of the pytest suite or CI (tests/conftest.py deliberately forces
LANGSMITH_TRACING=false and fake API keys for every test, since the unit suite uses
canned fake models with no real generation to judge). This script makes real LLM calls
(the agent model + a judge model) and costs a small amount of real API spend per run —
run it by hand after a system-prompt or model change, not on every commit.

Usage:
    python scripts/eval_langsmith.py

Requires the same .env as the web app, plus LANGSMITH_API_KEY set (tracing/eval
results are uploaded to LangSmith). Prints the experiment URL LangSmith returns so you
can inspect per-example scores there.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import Client
from langsmith.evaluation import evaluate

from app.agent import AgentContext, build_graph
from app.config import settings
from app.main import _build_tools_and_system, _model, _story_embedder, _story_index
from app.db import get_readonly_connection

DATASET_NAME = "travel-agent-faithfulness-relevancy"

# A separate, stronger model does the judging, never the same model that generated the
# answer — grading with the exact model under test risks it rubber-stamping its own
# mistakes. Reuses the same Gemini API key, just a different (and typically pricier,
# fine for a small offline eval run) model.
JUDGE_MODEL_NAME = "gemini-3.1-pro-preview"

RECURSION_LIMIT = 9

# Each covers a distinct code path in app/agent.py so the eval actually exercises every
# grounding source, not just the easy cases.
EXAMPLES = [
    {"question": "Taipei Restaurant Recommendations"},
    {"question": "New York City Things To Do"},
    {"question": "Bangkok Bars And Clubs"},
    {"question": "Boston Dessert Spots"},
    {"question": "Lebanon Restaurants"},  # country-level branch
    {"question": "What's a good coffee shop within walking distance of the Eiffel Tower?"},  # near_lat/lng radius
    {"question": "Is there anywhere in Tokyo that does late-night ramen?"},  # search_query disambiguation
    {"question": "What do you know about dog-friendly cafes in Reykjavik?"},  # expected: no match, must say so honestly
    {"question": "What was it actually like visiting Kyoto's temples — any personal stories?"},  # get_city_context
    {"question": "I'm spending a week in Taipei — what should I eat and what should I do while I'm there?"},  # chained tool calls
    {"question": "What's good in Taipei?"},  # ambiguous category — should ask, not guess
]


def ensure_dataset(client: Client) -> str:
    if client.has_dataset(dataset_name=DATASET_NAME):
        return DATASET_NAME
    dataset = client.create_dataset(
        dataset_name=DATASET_NAME,
        description="Representative questions for the travel agent, covering every "
        "grounding source (DB spot lookup, country-level, radius filter, search_query, "
        "empty result, diary RAG, chained tool calls, ambiguous category).",
    )
    client.create_examples(
        dataset_id=dataset.id,
        examples=[{"inputs": {"question": ex["question"]}} for ex in EXAMPLES],
    )
    return DATASET_NAME


def target(inputs: dict) -> dict:
    """Runs one example through the real agent graph and returns the answer plus the
    tool-call context it was grounded in — the same ToolMessage content the model
    itself read before answering (app/agent.py's _tool_result_content /
    _context_result_content), with zero extra plumbing inside app/."""
    conn = get_readonly_connection(settings.database_path)
    try:
        tools, system = _build_tools_and_system(conn)
        graph = build_graph(_model, tools)
        context = AgentContext(conn=conn, story_index=_story_index, embedder=_story_embedder)

        result = graph.invoke(
            {
                "messages": [
                    SystemMessage(content=system),
                    HumanMessage(content=inputs["question"]),
                ],
                "map_payload": None,
            },
            context=context,
            config={"recursion_limit": RECURSION_LIMIT},
        )

        # The system prompt's own per-city category breakdown (app/llm.py's
        # build_system_prompt) is real, DB-sourced grounding the model can answer
        # from directly without calling a tool (e.g. "I have Restaurants, Desserts,
        # ... saved in Taipei") — include it so the faithfulness judge doesn't mark
        # those claims as unsupported just because no ToolMessage carried them.
        contexts = [system] + [
            m.content for m in result["messages"] if isinstance(m, ToolMessage)
        ]
        return {"answer": result["messages"][-1].text, "contexts": contexts}
    finally:
        conn.close()


def _judge(prompt: str) -> dict:
    judge = ChatGoogleGenerativeAI(model=JUDGE_MODEL_NAME, api_key=settings.llm_api_key)
    response = judge.invoke(prompt).text
    # Judge is asked for raw JSON; strip markdown code fences if it added them anyway.
    cleaned = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


def faithfulness(run, example) -> dict:
    answer = run.outputs.get("answer", "")
    contexts = run.outputs.get("contexts", [])
    if not contexts:
        # No tool was called (e.g. a direct non-factual reply) — nothing to ground
        # against, so faithfulness doesn't apply to this example.
        return {"key": "faithfulness", "score": None, "comment": "no retrieved context"}

    prompt = f"""You are grading whether an AI travel assistant's answer is faithful to \
its retrieved context (it must not state anything the context doesn't support).

This assistant is deliberately designed to speak with a real first-person voice and \
personal opinion (e.g. "vibrant", "incredible", "felt like coming home"), and — when \
discussing one specific named real-world place directly — is explicitly instructed to \
draw on general knowledge beyond the retrieved context (cuisine, atmosphere, what a \
place is known for). Both are intended product behavior, not hallucination.

Question: {example.inputs["question"]}

Retrieved context (JSON, one entry per tool call):
{json.dumps(contexts, indent=2)}

Answer to grade:
{answer}

List only CONCRETE, CHECKABLE factual claims in the answer — specific place names, \
specific categories said to be saved, specific counts, specific details/features \
attributed to a specific place. Do NOT extract subjective/atmospheric opinion or mood \
language (e.g. "vibrant", "amazing", "felt like home") as claims — that is voice, not \
a factual assertion. Do NOT extract general-knowledge elaboration about a named \
real-world place as unsupported unless it actually contradicts the context or asserts \
something clearly false about that place. Then mark each extracted claim "supported" \
or "unsupported" by the context (a claim about saved categories/spots is supported only \
if the context actually contains it). Respond with ONLY this JSON shape, no other text:
{{"claims": [{{"claim": "...", "supported": true}}, ...]}}"""

    result = _judge(prompt)
    claims = result.get("claims", [])
    if not claims:
        return {"key": "faithfulness", "score": None, "comment": "no claims extracted"}
    score = sum(1 for c in claims if c.get("supported")) / len(claims)
    return {"key": "faithfulness", "score": score, "value": result}


def answer_relevancy(run, example) -> dict:
    answer = run.outputs.get("answer", "")
    contexts = run.outputs.get("contexts", [])
    prompt = f"""You are grading whether an AI travel assistant's answer actually \
addresses the visitor's question — not whether it's factually correct, only whether \
it's on-topic and responsive.

IMPORTANT: this app shows actual spot recommendations as a map plus auto-generated \
cards (title/category/note) in the UI, separate from the prose text — the prose is \
deliberately brief and is NOT supposed to re-narrate every spot the cards already show. \
So if the retrieved context below contains real matching results (e.g. actual \
restaurant/spot names for what was asked), the request IS satisfied even if the prose \
text itself just says something like "I've pulled up my saved spots" without listing \
them — do NOT score that low. Only score low when the context shows nothing relevant \
was retrieved/returned, or the prose text contradicts or ignores what was asked despite \
having relevant results available.

This assistant sometimes asks a clarifying question before retrieving anything. That is \
ACCEPTABLE and should NOT be scored low when the question itself gives no real signal \
about which categories/topics the visitor wants (e.g. "what's good in Taipei?" with no \
topic at all). But if the question's own wording already clearly implies one or more \
topics — even several, even without naming an exact category ("what should I eat and \
do" implies food + activities) — then asking instead of retrieving/answering at all is \
NON-RESPONSIVE and should score low.

Question: {example.inputs["question"]}

Retrieved context (JSON, one entry per tool call — empty if no tool was called):
{json.dumps(contexts, indent=2)}

Answer to grade:
{answer}

Respond with ONLY this JSON shape, no other text:
{{"score": 0.0, "reasoning": "..."}} where score is between 0.0 (irrelevant/stalls when \
the question already gave enough signal to answer) and 1.0 (fully addresses the \
question, or reasonably asks because the question genuinely gave no signal at all)."""

    result = _judge(prompt)
    return {"key": "answer_relevancy", "score": result.get("score"), "value": result}


# Regression bar — re-run this script by hand after a system-prompt or model change and
# compare against these; tighten once real scores establish a baseline.
THRESHOLDS = {"faithfulness": 0.9, "answer_relevancy": 0.8}


def main() -> None:
    client = Client()
    dataset_name = ensure_dataset(client)

    results = evaluate(
        target,
        data=dataset_name,
        evaluators=[faithfulness, answer_relevancy],
        experiment_prefix="travel-agent-eval",
    )

    scores: dict[str, list[float]] = {"faithfulness": [], "answer_relevancy": []}
    for row in results:
        for eval_result in row["evaluation_results"]["results"]:
            if eval_result.score is not None:
                scores[eval_result.key].append(eval_result.score)

    print()
    failed = False
    for key, threshold in THRESHOLDS.items():
        values = scores[key]
        if not values:
            print(f"{key}: no scored examples")
            continue
        mean = sum(values) / len(values)
        status = "OK" if mean >= threshold else "BELOW THRESHOLD"
        if mean < threshold:
            failed = True
        print(f"{key}: mean={mean:.2f} over {len(values)} examples (threshold {threshold}) [{status}]")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
