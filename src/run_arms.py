"""Ask the models the frozen questions and save every raw reply.

Run with:
    uv run src/run_arms.py smoke              # 30 questions, both thinking settings
    uv run src/run_arms.py smoke --limit 1    # just one question, to test the plumbing
    uv run src/run_arms.py full               # all 200 questions

Haiku runs with its default thinking setting in the full run (decided
after the smoke test). The smoke test also tried thinking switched off.

Arm A: Claude Haiku 5.5, told to copy the exact passage that answers.
Arm B: Perplexity Decider Flash v1.3 "locate", which returns positions
       in the text we sent, not words of its own.
Added later: the larger Decider v1.3, asked in exactly the same way.

Memory check: Haiku again, given only the paper's title and the question,
       no paper text. This measures how much it can answer from memory.

One request per question for each arm. Arms A and B carry the whole paper.
Every reply is appended to a file under raw/ the moment it arrives, with
token usage, time taken and request id. A question that already has a
saved reply is never asked again.
"""

import json
import random
import sys
import time
from pathlib import Path

import os

import anthropic
import requests
from dotenv import load_dotenv

from fetch_papers import load_papers

HAIKU = "claude-haiku-5-5"
DECIDER = "pplx-decider-flash-v1.3"
DECIDER_LARGE = "pplx-decider-v1.3"  # added after the main results, same questions and wording
SEED = 14
SMOKE_N = 30
MAX_TRIES = 5

HAIKU_SYSTEM = """You answer questions about a document by quoting it.

Return the exact passage from the document that answers the question. Copy it character for character: do not paraphrase, summarise, correct, or join separate passages. Give the shortest passage that fully answers the question.

If the document does not contain the answer, set "found" to false and "quote" to an empty string."""

HAIKU_SCHEMA = {
    "type": "object",
    "properties": {"quote": {"type": "string"}, "found": {"type": "boolean"}},
    "required": ["quote", "found"],
    "additionalProperties": False,
}


MEMORY_SYSTEM = """You are asked a question about a research paper. You have NOT been given the paper, only its title.

Give your best answer from memory in as few words as possible. If you have no idea, set "known" to false and "answer" to an empty string."""

MEMORY_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "known": {"type": "boolean"}},
    "required": ["answer", "known"],
    "additionalProperties": False,
}


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["id"] for line in path.read_text().splitlines() if line.strip()}


def save(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def with_retries(call):
    """Run one API call. If told to slow down (429) or the server is
    overloaded, wait as long as it asks and try again."""
    for attempt in range(MAX_TRIES):
        try:
            return call()
        except Exception as e:  # noqa: BLE001 - we re-raise anything that is not a retryable status
            status = getattr(e, "status_code", None)
            if status not in (429, 500, 502, 503, 529) or attempt == MAX_TRIES - 1:
                raise
            headers = getattr(getattr(e, "response", None), "headers", {}) or {}
            wait = min(float(headers.get("retry-after", 5 * (attempt + 1))), 120)
            print(f"    (status {status}, waiting {wait:.0f}s)", flush=True)
            time.sleep(wait)


def _haiku_call(client: anthropic.Anthropic, system: str, user: str, schema: dict, thinking: str) -> dict:
    kwargs = {}
    if thinking == "off":
        kwargs["thinking"] = {"type": "disabled"}
    # thinking == "default": send nothing, so the model uses its own default.
    started = time.time()
    msg = with_retries(
        lambda: client.messages.create(
            model=HAIKU,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            **kwargs,
        )
    )
    seconds = time.time() - started
    reply_text = "".join(b.text for b in msg.content if b.type == "text")
    return {
        "model": HAIKU,
        "thinking": thinking,
        "seconds": round(seconds, 2),
        "request_id": msg._request_id,
        "stop_reason": msg.stop_reason,
        "usage": msg.usage.model_dump(),
        "reply_text": reply_text,  # raw, unparsed: scoring does the parsing
    }


def ask_haiku(client: anthropic.Anthropic, text: str, question: str, thinking: str) -> dict:
    user = f"<document>\n{text}\n</document>\n\nQuestion: {question}"
    return _haiku_call(client, HAIKU_SYSTEM, user, HAIKU_SCHEMA, thinking)


def ask_memory(client: anthropic.Anthropic, title: str, question: str) -> dict:
    """The same model with no paper attached, only the title."""
    user = f"Paper title: {title}\n\nQuestion: {question}"
    return _haiku_call(client, MEMORY_SYSTEM, user, MEMORY_SCHEMA, "default")


def ask_locate(key: str, text: str, question: str, model: str = DECIDER) -> dict:
    """One direct web request. Perplexity's Python kit (0.46.1) rejects the
    "locate" question type before sending, so we call the service itself."""

    def call():
        r = requests.post(
            "https://api.perplexity.ai/v1/decisions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "state": text,
                "questions": {"q": {"type": "locate", "instructions": question}},
            },
            timeout=120,
        )
        if r.status_code != 200:
            err = RuntimeError(f"Perplexity returned {r.status_code}: {r.text[:300]}")
            err.status_code, err.response = r.status_code, r
            raise err
        return r

    started = time.time()
    r = with_retries(call)
    seconds = time.time() - started
    body = r.json()
    return {
        "model": body.get("model"),
        "seconds": round(seconds, 2),
        "request_id": r.headers.get("x-request-id"),
        "usage": body.get("usage"),
        "answer": (body.get("answers") or {}).get("q"),
        "sent_chars": len(text),
    }


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode not in ("smoke", "full"):
        raise SystemExit("Say which run: smoke or full")
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None

    papers = {p["paper"]: p for p in load_papers()}
    questions = [json.loads(line) for line in Path("data/questions.jsonl").read_text().splitlines()]

    if mode == "smoke":
        questions = random.Random(SEED).sample(questions, SMOKE_N)
        runs = [
            ("haiku", "default", Path("raw/smoke/llm_thinking_default.jsonl")),
            ("haiku", "off", Path("raw/smoke/llm_thinking_off.jsonl")),
            ("locate", None, Path("raw/smoke/locate.jsonl")),
            ("memory", None, Path("raw/smoke/memory.jsonl")),
        ]
    else:
        runs = [
            ("haiku", "default", Path("raw/llm.jsonl")),
            ("locate", None, Path("raw/locate.jsonl")),
            ("memory", None, Path("raw/memory.jsonl")),
            ("locate_large", None, Path("raw/locate_decider.jsonl")),
        ]
    if limit:
        questions = questions[:limit]

    load_dotenv(".env")
    haiku_client = anthropic.Anthropic()
    locate_key = os.environ["PERPLEXITY_API_KEY"]

    for arm, thinking, path in runs:
        already = done_ids(path)
        todo = [q for q in questions if q["id"] not in already]
        label = f"{arm}" + (f" (thinking {thinking})" if thinking else "")
        print(f"\n{label}: {len(todo)} to ask, {len(questions) - len(todo)} already saved -> {path}", flush=True)
        for n, q in enumerate(todo, 1):
            text = papers[q["paper"]]["text"]
            try:
                if arm == "haiku":
                    row = ask_haiku(haiku_client, text, q["question"], thinking)
                elif arm == "memory":
                    row = ask_memory(haiku_client, papers[q["paper"]]["title"], q["question"])
                elif arm == "locate_large":
                    row = ask_locate(locate_key, text, q["question"], DECIDER_LARGE)
                else:
                    row = ask_locate(locate_key, text, q["question"])
            except Exception as e:  # noqa: BLE001 - report and stop, never save a made-up row
                print(f"  {q['id']} FAILED: {type(e).__name__}: {str(e)[:300]}", flush=True)
                raise SystemExit(1)
            save(path, {"id": q["id"], **row})
            print(f"  {n}/{len(todo)} {q['id']} {row['seconds']}s", flush=True)

    print("\nDone.")


if __name__ == "__main__":
    main()
