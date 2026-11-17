"""Scoring rules. Plain Python, no model involved.

The one question that matters most: is this quote really in the document?
"""

import re
import string
import unicodedata
from collections import Counter


def tidy(text: str) -> str:
    """Light clean-up applied to BOTH the quote and the document before the
    substring check: standard Unicode form, non-breaking spaces to ordinary
    spaces, runs of whitespace to one space, no leading or trailing space.
    Nothing else. Letters, punctuation and capitals must match exactly."""
    text = unicodedata.normalize("NFC", text).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_verbatim(quote: str, document: str) -> bool:
    """True if the quote appears word for word in the document."""
    q = tidy(quote)
    return bool(q) and q in tidy(document)


def count_occurrences(quote: str, document: str) -> int:
    q = tidy(quote)
    return tidy(document).count(q) if q else 0


def _answer_tokens(text: str) -> list[str]:
    """Looser clean-up used ONLY to compare a quote with the reference
    answer: lowercase, no punctuation, no a/an/the. (The usual SQuAD rule.)"""
    text = tidy(text).lower()
    text = "".join(ch for ch in text if ch not in set(string.punctuation))
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return text.split()


def exact_match(quote: str, reference: str) -> bool:
    return _answer_tokens(quote) == _answer_tokens(reference)


def f1(quote: str, reference: str) -> float:
    """Word overlap between quote and reference, from 0 (none) to 1 (same words)."""
    q, r = _answer_tokens(quote), _answer_tokens(reference)
    if not q or not r:
        return float(q == r)
    common = sum((Counter(q) & Counter(r)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(q), common / len(r)
    return 2 * precision * recall / (precision + recall)


def find_all(quote: str, document: str) -> list[tuple[int, int]]:
    """Every place the quote appears in the document, as (start, end)
    character positions. Uses the same rule as is_verbatim: words must
    match exactly, only the whitespace between them may differ."""
    words = tidy(quote).split()
    if not words:
        return []
    pattern = r"\s+".join(re.escape(w) for w in words)
    return [m.span() for m in re.finditer(pattern, document)]


def covered_share(spans: list[tuple[int, int]], ref: tuple[int, int]) -> float:
    """Share of the reference answer's characters that fall inside the
    given spans. 0 means the quote is somewhere else entirely, 1 means it
    includes the whole reference answer."""
    a, b = ref
    hit = set()
    for s, e in spans:
        hit.update(range(max(s, a), min(e, b)))
    return len(hit) / (b - a)


def place_score(quote: str, document: str, reference: str, spans: list[tuple[int, int]] | None = None) -> float:
    """How much of the reference answer's location the answer covers.

    The reference sits at one known position in the document. For a quote
    (Haiku) we look up where the quote appears; if it appears more than
    once we take the occurrence that covers the reference best. For locate
    we are given positions directly, and all returned spans count together."""
    refs = find_all(reference, document)
    if len(refs) != 1:
        raise ValueError(f"reference should appear exactly once, found {len(refs)}")
    if spans is not None:
        return covered_share(spans, refs[0])
    return max((covered_share([s], refs[0]) for s in find_all(quote, document)), default=0.0)


_TYPOGRAPHY = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"', "\u2033": '"',
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2032": "'",
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
})


def fold_typography(text: str) -> str:
    """Treat look-alike characters as the same: curly and straight quote
    marks, the various dashes, the single-character ellipsis, ligatures."""
    return tidy(unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY))


def made_up_kind(quote: str, document: str) -> str:
    """For a quote that FAILED the strict check, say why. This never
    rescues a quote: it still counts as made up. It only sorts made-up
    quotes into 'punctuation_only' (every word is right, a look-alike
    character differs) and 'words_changed' (everything else)."""
    return "punctuation_only" if fold_typography(quote) in fold_typography(document) else "words_changed"


def classify(
    quote: str | None,
    document: str,
    reference: str,
    parse_ok: bool = True,
    spans: list[tuple[int, int]] | None = None,
) -> str:
    """One label per answer:
    parse_error  we could not read the reply
    miss         no answer given
    made_up      the quote is not in the document
    exact        in the document, and the same words as our reference answer
    right_place  in the document, overlapping where the reference answer sits
    elsewhere    in the document, but in a different place"""
    if not parse_ok:
        return "parse_error"
    if quote is None or not tidy(quote):
        return "miss"
    if not is_verbatim(quote, document):
        return "made_up"
    if exact_match(quote, reference):
        return "exact"
    return "right_place" if place_score(quote, document, reference, spans) > 0 else "elsewhere"


if __name__ == "__main__":
    # Self-test on cases where we already know the right verdict.
    doc = ("The study ran for 12 weeks.\n\nParticipants  reported higher trust in the tool. "
           "One said \u201cit just works\u201d and left. The control group ran for 8 weeks.")
    ref = "higher trust in the tool"
    assert classify("Participants reported higher trust in the tool.", doc, ref) == "right_place"
    assert classify("higher trust in the tool", doc, ref) == "exact"
    assert classify("higher trust", doc, ref) == "right_place", "a fragment of the reference"
    assert classify("The study ran for 12 weeks.", doc, ref) == "elsewhere"
    assert classify("Higher trust in the tool.", doc, ref) == "made_up", "capital H is not in the document"
    assert classify("participants trusted the tool more", doc, ref) == "made_up", "paraphrase"
    assert classify("Participants reported\nhigher   trust", doc, ref) == "right_place", "whitespace only"
    assert classify("", doc, ref) == "miss"
    assert classify(None, doc, ref) == "miss"
    assert classify("anything", doc, ref, parse_ok=False) == "parse_error"
    assert f1("higher trust", ref) > 0.5 and f1("unrelated words", ref) == 0.0

    # Where the answer sits.
    assert place_score("Participants reported higher trust in the tool.", doc, ref) == 1.0
    assert place_score("higher trust", doc, ref) == 0.5
    assert place_score("The study ran for 12 weeks.", doc, ref) == 0.0
    assert place_score("weeks", doc, ref) == 0.0, "appears twice, neither near the reference"
    start = doc.index("higher")
    assert place_score("", doc, ref, spans=[(start, start + 6), (start + 7, start + 12)]) == 11 / 24
    assert classify("12 weeks", doc, ref, spans=[(17, 25), (start, start + 6)]) == "right_place", "any span counts"

    # Straight quote marks where the document has curly ones: still made up, but punctuation only.
    assert classify('One said "it just works" and left.', doc, ref) == "made_up"
    assert made_up_kind('One said "it just works" and left.', doc) == "punctuation_only"
    assert made_up_kind("One said it really works and left.", doc) == "words_changed"
    print("All scoring self-tests passed.")
