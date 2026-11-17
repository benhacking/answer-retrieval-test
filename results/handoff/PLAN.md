# Plan: ask Decider Flash first, send its blanks to Haiku

Written on 16 November 2026, before the fresh run. No model had been
called for this test when this file was committed.

One thing was already known when this was written. The "replay" in step 1
uses only replies saved in the main run, and its numbers had been worked
out once already (197 of 200 from the right place, about $0.54 per 1,000
questions). So this plan was fixed before the fresh run, not before the
replay.

## The question

If we ask Perplexity Decider Flash locate first, and send only the
questions it leaves blank to Claude Haiku 5.5, how do accuracy, cost and
time compare with Haiku on its own?

## Fixed before running

1. Same 200 questions, same 25 paper texts, same request wording and same
   model versions as the main run (`pplx-decider-flash-v1.3`,
   `claude-haiku-5-5` with default thinking). The request code is reused
   from `src/run_arms.py` without changes.
2. Same scoring code, unchanged (`src/score.py`, used the same way as
   `src/score_run.py`). No AI judge. "Correct" means the scoring code
   labels the answer `exact` or `right_place`.
3. "Blank" means Decider Flash returned no span. Only blanks go to Haiku.
   An answer Flash takes from the wrong place stays as the answer and
   counts as wrong, because a real product would not know it was wrong.
4. The headline numbers use Haiku's answers as returned. A second line
   shows the same numbers after the one-line check (a quote that is not
   in the paper is thrown away and counted as no answer).
5. Main-run files are not changed. Everything new goes under
   `results/handoff/`.

## Steps

1. Replay, no cost. Combine the main run's saved Flash answers with the
   main run's saved Haiku answer wherever Flash was blank. Score it.
2. Fresh run. Ask Flash all 200 questions again. For each blank, ask
   Haiku. Save every raw reply with the time it was asked, token counts
   and time taken. One attempt per question; nothing is re-asked.
3. Baseline. Haiku on its own, using the main run's figures. A fresh
   Haiku-only run on all 200 is not planned.
4. Cost. Flash on all 200 plus Haiku on the blanks only, from the token
   counts in the logs and the same prices as the main run. Scaled as
   total cost / 200 x 1,000.
5. Time. Flash time alone for answered questions; Flash time plus Haiku
   time for blanks. Median and 90th percentile.
6. Consistency. How many of the fresh run's blanks are the same
   questions as the main run's 49.

## Exploratory (not part of the main result)

- Would also sending low-confidence Flash answers to Haiku catch Flash's
  wrong-place answers, and what would it cost? Replay only.
- The same replay with the larger Decider v1.3 asked first. Replay only.

## Added later on 16 November 2026: fresh runs of Haiku and Decider

Written after the fresh Flash-then-Haiku results were known, and before
either of the runs below.

Step 3 above said a fresh Haiku-only run was not planned. That left the
results table comparing a fresh combo with a Haiku figure from the main
run. To put every column on the same footing:

- Ask Haiku all 200 questions again, on its own. Same wording, model
  and settings. This becomes the Haiku-only baseline.
- Ask the larger Decider v1.3 all 200 questions again, the same way.
- Same scoring code. One attempt per question. Whatever comes back is
  reported, next to the main-run figures.
- The Flash-then-Haiku result already recorded is not changed.
