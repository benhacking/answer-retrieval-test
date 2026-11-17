# Can't make it up

Agent brief for this project and its current source of truth.

Personal side project. Public data only. The repo will be made public when the post goes out, so write everything here as if a reader will see it.

## Goal

Ask a cheap large language model (LLM) for the exact quote that answers a question about a document it cannot have seen in training. Check with plain Python whether that quote is really in the document. Compare against Perplexity Decider Flash v1.3 `locate`, which returns positions in the source text and so cannot invent wording.

Output: one blog post of 1 to 2 pages, one tweet, and maybe a short thread. Keep the project small enough to match.

## Working rules

- Never commit API keys. They live in `.env`, which git ignores.
- Never invent results, target percentages, or placeholder numbers. Tables and charts stay blank until a run has produced real numbers.
- Check live official docs before relying on API field names. If a software development kit (SDK) attribute differs, print the raw response once and read from that.
- Do not change the frozen sample, model ids, or seed without the author agreeing first.
- Long jobs must print progress to a file under `logs/` and save partial work under `.cache/`, so a run can be watched with `tail -f` and a stopped run can resume.
- Spell out acronyms on first use.
- Personal working notes, if any, live in `AGENTS.local.md`, which is not committed.

## Design

**One experiment, on long documents the models cannot have seen.**

- **Documents:** 25 arXiv papers, frozen in `data/papers.jsonl` on 15 November 2026 with the author's approval.
  - Pool: every paper first submitted 1 October to 10 November 2026 whose main subject is one of `cs.HC`, `cs.CY`, `cs.SE`, `econ.GN`, `physics.soc-ph` (prose-heavy fields). 1,781 papers.
  - Shuffled with seed 14 and read in that order. A paper passes if arXiv has a web-page version, the cleaned text is 20,000 to 80,000 characters, at least 75% of it is in paragraphs of 200+ characters, and there are at most 0.5 inline maths expressions per 1,000 characters. The first 25 that passed are the sample. 203 were tried to find 40 passes; all outcomes are in `data/paper_candidates.jsonl`.
  - The maths limit exists because formulas come out of the web page as LaTeX source. A model that tidied `\text{PR}_{1}` to "PR1" in a quote would be marked as making it up, which would be unfair.
- **Text:** `src/papers.py` turns arXiv's web page into plain text: title, abstract, headings and paragraphs. Reference lists, figures, tables, footnotes, appendices, display equations and author blocks are removed. That string is "the document". Every model gets exactly it, and every quote is checked against it.
- **No republishing:** paper text is not stored in the repo. `data/papers.jsonl` holds identifier, version, link and a SHA-256 fingerprint of the cleaned text. `src/fetch_papers.py` downloads and verifies. Known weakness: if arXiv regenerates a web page, the fingerprint will no longer match for later readers.
- **Questions:** about 8 per paper, about 200 in total. Written by a model from neither arm's vendor: OpenAI `gpt-6.1-sol`. For each question it must also quote the span that answers it. A question is kept only if that span is verbatim in the paper text, using the same substring check as the scoring. The kept span is the reference answer.
- **Freeze before any arm runs:** `data/papers.jsonl` and `data/questions.jsonl` are committed before Haiku or Decider is called. Seed 14 for any random choice.
- **Arm A:** Claude Haiku 5.5 (`claude-haiku-5-5`), told to copy a verbatim quote, returned as JSON with `quote` (string) and `found` (boolean). Thinking is left at the model's default, which is what a developer gets without changing anything (decided after the smoke test).
- **Arm B:** Decider Flash v1.3 (`pplx-decider-flash-v1.3`) with `type: "locate"`. Paper text as `state`, question in `instructions`. Sent as a direct web request, because Perplexity's Python kit rejects `locate`.
- **Arm C, free:** Arm A's answers with any quote that fails the substring check turned into a miss. No extra API calls. This is the "LLM plus a one-line check" baseline.
- **Memory check:** Haiku is asked the same questions with only the paper's title, no text, to measure how much it can answer without the document (decided after the smoke test).

## What the post reports

1. **Made-up rate:** share of non-empty quotes that are not a substring of the document, after light normalisation (Unicode NFC, non-breaking spaces to spaces, collapse whitespace, strip). A paraphrase counts as made-up even if it is factually right. Do not soften this in scoring. Made-up quotes are then sorted, without rescuing any, into "punctuation only" (the quote matches once look-alike characters such as curly and straight quote marks are treated as the same) and "words changed".
2. **Right-place rate:** each reference answer sits at exactly one position in the paper. An answer is in the right place if it overlaps that position. Also report how much of the reference it includes, exact match against the reference (SQuAD-style normalisation), and how often no answer came back.
3. **Cost per 1,000 questions**, from each API's reported token usage, and median latency.
4. **Memory check:** how many questions Haiku answers correctly with no paper attached.

Classification for one answer: `parse_error`, `miss`, `made_up`, `exact`, `right_place`, `elsewhere`. Parse errors are never counted as made-up. For locate, the quote judged for made-up and exact is the highest-`score` span; for right place, all returned spans count together. Also report span count and whether `state[start:end] == text` held on the exact string sent.

Why right place and not exact match: the smoke test showed the two models cut answers differently. Haiku tends to return the whole sentence, locate a short fragment. Exact match punished both for answers that were in the correct spot.

Honest limits to state in the post:

- Questions and reference spans are machine-written. The author hand-checked a sample of 20.
- Reference spans are not human gold, so accuracy numbers are indicative.
- One LLM, one locate model, one kind of document. Most papers are about AI and software, because that is what those fields publish.
- Papers were chosen to be nearly free of maths. Results say nothing about maths-heavy documents.
- "First posted to arXiv in October" does not rule out an earlier copy elsewhere, such as a conference version.
- Decider's training cutoff is unpublished.
- Most papers are longer than the 8K tokens locate was trained on, though inside the 32K it was evaluated on.

## Verified against live docs on 15 November 2026

**Perplexity Decisions API** (docs.perplexity.ai quickstart, API reference, pricing)

- `POST https://api.perplexity.ai/v1/decisions`, header `Authorization: Bearer <key>`. No trailing slash.
- Only `pplx-decider-v1.3` and `pplx-decider-flash-v1.3` serve locate. Pin the versioned name.
- Request: `model`, `state`, `questions` (object keyed by name; each has `type` and `instructions`). For locate, `state` must be a plain string. No `mode: "web_grounding"`. At most 128 questions.
- Response: `answers[name]` is `{"type": "locate", "spans": [...]}`. Each span has `start`, `end`, `text`, `score`. Offsets are Unicode characters, end exclusive. No match gives `[]`. `score` is only described as "higher means more certain".
- Usage: `usage.input_tokens`, `usage.output_tokens`.
- Price: Flash v1.3 $0.01 per million input tokens, output free, no per-request fee.
- Limits: 10 requests per second per organisation; Flash 4,000,000 tokens per minute. A 429 carries `Retry-After`. Responses carry `x-request-id`.
- Locate was trained on inputs up to 8K tokens and evaluated up to 32K. Window is 256K.
- Python kit: `perplexityai` 0.46.1 rejects `type: "locate"` before sending (its own validation does not know the type). A direct `requests.post` works and returns the documented shape, including the `x-request-id` header. Confirmed on 30 real calls.
- Hugging Face card licence for Flash v1.3: `apache-2.0`.

**OpenAI** (developers.openai.com models, pricing, structured outputs guide)

- `gpt-6.1-sol`: $2 input, $10 output per million tokens. Stated knowledge cutoff 30 April 2026. The project key can see this model.
- Structured output: `client.responses.parse(model=..., input=[...], text_format=PydanticModel)`, read `response.output_parsed`. The schema root must be an object, so wrap the list. Check `response.status` before parsing.

**Anthropic** (Claude API reference bundled with Claude Code, cached 3 November 2026; models overview page read 15 November 2026)

- `claude-haiku-5-5`: training data cutoff and reliable knowledge cutoff both listed as June 2026. Context window 1M tokens, max output 128K. The project key can see this model.
- $0.10 input, $0.50 output per million tokens for prompts up to 100K tokens; $0.50 and $2.50 beyond.
- Structured output: `output_config={"format": {...}}` on `messages.create`, or `client.messages.parse`.
- Thinking is on by default and the model decides per question whether to use it. Thinking tokens are billed as output. `thinking={"type": "disabled"}` is accepted. Non-default `temperature` is rejected.

**arXiv** (raw responses read 15 November 2026)

- Listing: `https://export.arxiv.org/api/query` with `search_query=cat:<field> AND submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]`, Atom XML back. Identifiers start with the year and month of first submission (`2610` is October 2026).
- Web page: `https://arxiv.org/html/<id>v<version>`, generated by LaTeXML, with `ltx_` class names. About 1 in 8 papers tried had none.
- Be polite: about one request every 3 seconds.

## Not yet verified

- Decider's training cutoff. Neither the model card nor the blog states one. It launched around 13 November 2026.
- OpenAI `response.usage` field names were taken from SDK source, not the docs page. They worked in practice.

## Layout

```
.env                        # keys, never committed
.env.example                # names of the keys, no values
data/paper_candidates.jsonl # every paper tried, in seed-14 order, with why it passed or failed
data/papers.jsonl           # the frozen 25: identifier, link, fingerprint (no text)
data/papers_text/           # downloaded text, git-ignored
data/questions.jsonl        # the frozen 200: question, reference span, position in paper
raw/smoke/                  # the 30-question rehearsal (not results)
raw/llm.jsonl               # every raw response, appended as we go
raw/locate.jsonl
raw/memory.jsonl            # the memory check: Haiku with no paper attached
results/scores.csv
results/memory.csv
results/charts/
logs/, .cache/              # progress logs and saved partial work, git-ignored
src/papers.py               # arXiv listing, download and text-cleaning rules
src/find_papers.py          # the seed-14 search that produced the candidates
src/freeze_papers.py        # wrote data/papers.jsonl, refuses to overwrite it
src/fetch_papers.py         # download and verify the frozen papers
src/generate_questions.py   # wrote the questions; --freeze refuses to overwrite them
src/score.py                # scoring rules, with self-tests (run it directly)
src/run_arms.py             # asks the models: smoke or full
src/score_run.py            # scores saved replies: smoke or full
src/followup_locate.py      # exploratory: re-asks locate's empty replies with other wordings
src/make_report.py          # builds results/table.md and the chart from results/scores.csv
src/handoff.py              # second run: `run` (combo), `baseline` (each model alone), `report`
src/make_combo_charts.py    # the three charts in the post, from the second run
src/make_cover.py           # the cover image
results/handoff/            # second run (16 November 2026): plan, raw replies, scores, summary
```

Run scripts from the project folder with `uv run src/<name>.py`.

## Milestones

Pause after each one.

1. **Setup and sanity check.** Done on 15 November 2026. Keys in `.env`.
2. **Freeze documents and questions; write scoring.** Done on 15 November 2026. 25 papers and 200 questions (8 per paper) are frozen and committed. `gpt-6.1-sol` wrote 300 questions for about $0.80; 8 were rejected because the answer appeared more than once, 2 because the quote was not in the paper. The author read a seed-14 sample of 20 and approved. `src/score.py` passes its self-tests.
3. **Smoke test both arms on 30 questions.** Done on 15 November 2026 for about 10 cents. Both keys work. Rehearsal numbers only, never to be quoted as results: Haiku returned no made-up quotes with default thinking, and one with thinking off that differed from the paper only in quote-mark style; locate returned nothing on 6 of 30. Led to the right-place measure, the made-up breakdown, the default-thinking choice and the memory check.
4. **Full run** on all frozen questions. Done on 15 November 2026: `uv run src/run_arms.py full`. 600 replies saved (200 each for Haiku, locate and the memory check), no failures or retries, about 37 cents.
5. **Score, one table, one chart.** Scored on 15 November 2026: `uv run src/score_run.py full`, then `uv run src/make_report.py`. Numbers live in `results/table.md`; quote them from there, never from memory. The author then read the one made-up quote, locate's two wrong-place answers, and eight of its 49 empty replies, and judged the questions fair. The made-up quote is reported as "no words changed, quotation marks differ", with the strict count kept visible.
   - Things found while reading the results, to state in the post: Haiku's single made-up quote differs from the paper only in quote-mark style. Locate's empty replies grow with the length of the reference answer (6 of 66 for answers of 5 words or fewer, 29 of 103 for 6 to 15 words, 14 of 31 for 16 or more) and do not clearly depend on paper length or position. In the memory check, the few answers Haiku got right were facts the papers cite from older public sources, not content new to the paper.
   - Follow-up on locate's 49 empty replies (exploratory, run after scoring, `src/followup_locate.py`, replies in `raw/followup/`): asked again in the same words, all 49 were empty again, so the silence is repeatable. Reworded as "Find the passage in the text that answers this question: ...", 14 of the 49 got an answer, all in the right place; as "The sentence in the text that answers this question: ...", 18 did. But the "find" wording, tried on 49 questions locate had answered (picked with seed 14), lost 10 of them. So wording changes which questions get answered; this test does not show that it reduces silence overall.
   - Larger model, added at the author's request after the main results: `pplx-decider-v1.3` ($0.02 per million input tokens, verified on the pricing page 15 November 2026), same questions and wording, replies in `raw/locate_decider.jsonl`. 155 right place, 45 empty, none made up. Only 15 questions were empty on both Decider models.
6. **Findings note, blog draft, tweet draft.** Drafted on 15 November 2026 as local files that are not committed. Measured numbers only. The chart shows three rows, Haiku, Decider and Decider Flash, because the one-line check changes one answer in 200. `PAPERS.md` lists the 25 papers with links.

## Lessons so far

- Look names up, do not guess them. A guessed name in an API query returns nothing and wastes time.
- Never run a long job silently. Print progress and save partial work.
- Identify the script politely in its User-Agent and pace requests. Anonymous, fast scripts get throttled.
- Read the cleaned text, not only the counts. Reading one paper caught a dropped abstract; reading the messiest ones caught the LaTeX problem.
- Rehearse before the real run. Thirty questions showed that our main accuracy measure was unfair to both models, while it was still cheap to fix.
- Choose a document source you are comfortable publishing about, not only one that measures well.

## Handoff test (16 November 2026)

Asked Decider Flash first and sent only its blanks to Haiku. Plan: `results/handoff/PLAN.md`, committed before the fresh run. Code: `src/handoff.py` (`run`, then `report`). Raw replies, scores and summary are under `results/handoff/`.

Fresh run: 197 of 200 from the right place, 50 questions sent to Haiku, $0.55 per 1,000 questions, median 0.56 seconds, 90th percentile 2.52 seconds. Flash left 50 blank (49 in the main run, 48 the same questions). Spent $0.11. Replay-only extras (larger Decider first, confidence cut-offs) are in `results/handoff/summary.txt` and are exploratory.

## Second run of Haiku and Decider on their own (16 November 2026)

Added so the handoff result is compared with baselines from the same run.
Plan note in `results/handoff/PLAN.md`; raw replies in
`results/handoff/raw/haiku_all.jsonl` and `decider.jsonl`.

- Haiku alone: 199 right, 1 not in the paper (P23-Q6: it added the word
  "splats" after "200k"). $1.70 per 1,000, median 1.64 s, 90th percentile 2.15 s.
- Decider alone: 153 right, 47 blank, 0 wrong place. 38 of the blanks were
  the same questions as the main run's 45. $0.21 per 1,000, median 1.33 s.
- From these saved answers, Decider then Haiku on its blanks: 200 right,
  $0.65 per 1,000, median 1.45 s. Not run as a live pipeline.
- `results/charts/outcomes_combo.png` and `cost_time.png` now use the
  second run for every bar.
