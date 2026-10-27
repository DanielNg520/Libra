"""Pure core of the lecture map: tokens, term weights, monotone deck alignment, spans, chapter scores (ADR-0041 P2)."""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

log = logging.getLogger(__name__)

WINDOW_S = 300.0
TOP_PAGES = 3
WEAK_SCORE = 0.08
PAGE_MAX_DF = 1 / 3
CHAPTER_MAX_DF = 0.5
TOP_CHAPTERS = 3
TOP_TERMS = 8
ALSO_RATIO = 0.9

STOPWORDS: frozenset[str] = frozenset(
    """
    the and for that this with you are have was but not what can all one two will
    they there their then than when where which who how why our your from into out
    about just like its it's also very some more most much many any each other only
    over such these those them him her his she because would could should been being
    were does did done doing get got going know see say said use used using make made
    let lets now well okay yeah right thing things way here time first second next
    last same new look looking want need take give think thank really actually
    basically kind sort three four five six seven eight nine ten lot little bit today
    gonna don't i'm we're that's there's you're can't won't isn't page figure slide
    lecture example examples
    """.split()
)

NOISE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?s)\$\$.*?\$\$"),
    re.compile(r"\$[^$\n]*\$"),
    re.compile(r"\\[A-Za-z]+"),
    re.compile(r"(?im)^.*\b(diagram|image|photo|red box|footer|description)\b.*$"),
    re.compile(r"\b(theta|sigma|alpha|beta|lambda|hat|sqrt|frac|sim|mathbf|mathcal)\b", re.IGNORECASE),
)


def clean_text(text: str) -> str:
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z][a-z']+", text.lower())
    kept: list[str] = []
    for w in words:
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]
        if len(w) >= 3 and w not in STOPWORDS:
            kept.append(w)
    bigrams = [f"{kept[i]} {kept[i + 1]}" for i in range(len(kept) - 1)]
    return kept + bigrams


@dataclass(frozen=True, slots=True)
class TermSpace:
    idf: dict[str, float]

    @classmethod
    def build(cls, docs: Sequence[Sequence[str]], max_df: float) -> TermSpace:
        n = len(docs)
        if n == 0:
            return cls({})
        df: dict[str, int] = {}
        for doc in docs:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        threshold = n * max_df
        return cls({term: math.log(n / count) for term, count in df.items() if count < threshold})

    def vector(self, tokens: Iterable[str]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for token in tokens:
            if token in self.idf:
                counts[token] = counts.get(token, 0) + 1
        if not counts:
            return {}
        raw = {term: (1 + math.log(count)) * self.idf[term] for term, count in counts.items()}
        norm = math.sqrt(sum(w * w for w in raw.values()))
        return {term: w / norm for term, w in raw.items()}

    @staticmethod
    def cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
        small, large = (a, b) if len(a) <= len(b) else (b, a)
        return sum(weight * large[term] for term, weight in small.items() if term in large)


@dataclass(frozen=True, slots=True)
class Window:
    start: float
    end: float
    text: str


def transcript_windows(segments: Sequence[Mapping[str, object]], window_s: float = WINDOW_S) -> list[Window]:
    windows: list[Window] = []
    if not segments:
        return windows
    window_start = float(segments[0]["start"])
    texts: list[str] = []
    for index, segment in enumerate(segments):
        texts.append(str(segment["text"]))
        if float(segment["end"]) - window_start >= window_s:
            windows.append(Window(window_start, float(segment["end"]), " ".join(texts)))
            if index + 1 < len(segments):
                window_start = float(segments[index + 1]["start"])
            texts = []
    if texts:
        windows.append(Window(window_start, float(segments[-1]["end"]), " ".join(texts)))
    return windows


def deck_order(rel: str, track: str) -> tuple[int, int] | None:
    name = PurePosixPath(rel).name.lower()
    if track == "lecture":
        match = re.search(r"lec(?:ture)?\s*[-_]?\s*0*(\d+)", name)
        if match:
            if "note" in name:
                rank = 1
            elif "add" in name:
                rank = 2
            elif "handout" in name:
                rank = 3
            else:
                rank = 0
            return (int(match.group(1)), rank)
    elif track == "discussion":
        match = re.search(r"discussion\s+0*(\d+)\b", name)
        if match:
            return (int(match.group(1)), 0)
    return None


@dataclass(frozen=True, slots=True)
class Unit:
    rel: str
    order: tuple[int, int] | None
    pages: Mapping[int, str]
    duplicates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnitVectors:
    rel: str
    pages: dict[int, dict[str, float]]
    merged: dict[str, float]


def unit_vectors(unit: Unit, space: TermSpace) -> UnitVectors:
    page_vectors = {page: space.vector(tokenize(text)) for page, text in unit.pages.items()}
    merged: dict[str, float] = {}
    for vector in page_vectors.values():
        for term, weight in vector.items():
            if weight > merged.get(term, 0.0):
                merged[term] = weight
    return UnitVectors(unit.rel, page_vectors, merged)


def page_scores(vec: Mapping[str, float], uv: UnitVectors) -> dict[int, float]:
    return {page: TermSpace.cosine(vec, vector) for page, vector in uv.pages.items()}


def unit_score(vec: Mapping[str, float], uv: UnitVectors) -> float:
    if not uv.pages or not vec:
        return 0.0
    scores = sorted(page_scores(vec, uv).values(), reverse=True)
    top = scores[:TOP_PAGES]
    return sum(top) / len(top)


def align(scores: Sequence[Sequence[float]], allowed: Sequence[frozenset[int] | None]) -> list[int]:
    window_count = len(scores)
    if window_count == 0:
        return []
    unit_count = len(scores[0]) if window_count > 0 else 0
    if unit_count == 0:
        return [0] * window_count

    best: list[list[float]] = []
    back: list[list[int]] = []
    for i in range(window_count):
        row_best: list[float] = []
        row_back: list[int] = []
        prefix_val = -math.inf
        prefix_arg = 0
        for j in range(unit_count):
            if allowed[i] is not None and j not in allowed[i]:
                cell = -math.inf
            else:
                cell = scores[i][j]
            if i == 0:
                row_best.append(cell)
                row_back.append(j)
                continue
            elif best[i - 1][j] > prefix_val:
                prefix_val = best[i - 1][j]
                prefix_arg = j
            row_best.append(cell + prefix_val if cell != -math.inf and prefix_val != -math.inf else -math.inf)
            row_back.append(prefix_arg)
        best.append(row_best)
        back.append(row_back)

    final = 0
    final_best = -math.inf
    for j in range(unit_count):
        if best[window_count - 1][j] > final_best:
            final_best = best[window_count - 1][j]
            final = j
    if final_best == -math.inf:
        if any(a is not None for a in allowed):
            log.warning("lecture map anchors contradict deck order; ignoring them")
            return align(scores, [None] * window_count)
        return [0] * window_count

    path = [0] * window_count
    path[window_count - 1] = final
    for i in range(window_count - 1, 0, -1):
        path[i - 1] = back[i][path[i]]
    return path


@dataclass(frozen=True, slots=True)
class Anchor:
    transcript: str
    from_s: float
    to_s: float
    unit: int


def _span(
    transcript_id: str,
    start: float,
    end: float,
    unit_index: int,
    window_indices: Sequence[int],
    all_windows: Sequence[Window],
    units: Sequence[Unit],
    vectors: Sequence[UnitVectors],
    space: TermSpace,
    anchors: Sequence[Anchor],
) -> dict:
    span_text = " ".join(all_windows[i].text for i in window_indices)
    span_vec = space.vector(tokenize(span_text))
    uv = vectors[unit_index]

    raw_score = unit_score(span_vec, uv)
    score = round(raw_score, 3)

    page_sims = page_scores(span_vec, uv)
    if page_sims:
        best_page_score = max(page_sims.values())
        pages_candidates = [
            (page, sim) for page, sim in page_sims.items() if sim >= 0.5 * best_page_score and sim > 0
        ]
        pages_candidates.sort(key=lambda item: (-item[1], item[0]))
        pages = sorted(page for page, _ in pages_candidates[:8])
    else:
        pages = []

    common_terms = {
        term: span_vec[term] * uv.merged[term]
        for term in set(span_vec) & set(uv.merged)
    }
    terms = sorted(common_terms, key=lambda t: (-common_terms[t], t))[:TOP_TERMS]

    also: list[str] = []
    if score > 0:
        also_scores = [
            (other_uv.rel, unit_score(span_vec, other_uv))
            for other_uv in vectors
            if other_uv is not uv
        ]
        also_scores = [(rel, s) for rel, s in also_scores if s >= ALSO_RATIO * score]
        also_scores.sort(key=lambda item: (-item[1], item[0]))
        also = [rel for rel, _ in also_scores[:3]]

    if any(
        anchor.transcript == transcript_id
        and anchor.unit == unit_index
        and start < anchor.to_s
        and end > anchor.from_s
        for anchor in anchors
    ):
        status = "confirmed"
    else:
        status = "matched" if score >= WEAK_SCORE else "unmatched"

    span_dict: dict = {
        "from_s": round(start, 1),
        "to_s": round(end, 1),
        "deck": units[unit_index].rel if status != "unmatched" else None,
    }
    if status == "unmatched":
        span_dict["candidate"] = units[unit_index].rel
    span_dict["status"] = status
    span_dict["score"] = score
    span_dict["pages"] = pages
    span_dict["also"] = also
    span_dict["terms"] = terms
    return span_dict


def align_track(
    transcripts: Sequence[tuple[str, Sequence[Window]]],
    units: Sequence[Unit],
    vectors: Sequence[UnitVectors],
    space: TermSpace,
    anchors: Sequence[Anchor],
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}

    if not units:
        for transcript_id, windows in transcripts:
            if not windows:
                result[transcript_id] = []
                continue
            start = windows[0].start
            end = windows[-1].end
            result[transcript_id] = [
                {
                    "from_s": round(start, 1),
                    "to_s": round(end, 1),
                    "deck": None,
                    "candidate": None,
                    "status": "unmatched",
                    "score": 0.0,
                    "pages": [],
                    "also": [],
                    "terms": [],
                }
            ]
        return result

    all_windows: list[Window] = []
    window_transcript: list[str] = []
    for transcript_id, windows in transcripts:
        for window in windows:
            all_windows.append(window)
            window_transcript.append(transcript_id)

    window_vectors = [space.vector(tokenize(w.text)) for w in all_windows]

    scores: list[list[float]] = []
    allowed: list[frozenset[int] | None] = []
    for w_index, window in enumerate(all_windows):
        transcript_id = window_transcript[w_index]
        anchor_units = [
            anchor.unit
            for anchor in anchors
            if anchor.transcript == transcript_id and window.start < anchor.to_s and window.end > anchor.from_s
        ]
        allowed.append(frozenset(anchor_units) if anchor_units else None)

        window_scores = [unit_score(window_vectors[w_index], uv) for uv in vectors]
        scores.append(window_scores)

    assignment = align(scores, allowed)

    spans_by_transcript: dict[str, list[tuple[float, float, int, list[int]]]] = {t_id: [] for t_id, _ in transcripts}
    for w_index, unit_index in enumerate(assignment):
        window = all_windows[w_index]
        transcript_id = window_transcript[w_index]
        if spans_by_transcript[transcript_id] and spans_by_transcript[transcript_id][-1][2] == unit_index:
            start, _, _, indices = spans_by_transcript[transcript_id][-1]
            indices.append(w_index)
            spans_by_transcript[transcript_id][-1] = (start, window.end, unit_index, indices)
        else:
            spans_by_transcript[transcript_id].append((window.start, window.end, unit_index, [w_index]))

    for transcript_id, span_list in spans_by_transcript.items():
        spans_out: list[dict] = []
        for start, end, unit_index, window_indices in span_list:
            spans_out.append(
                _span(transcript_id, start, end, unit_index, window_indices, all_windows, units, vectors, space, anchors)
            )
        result[transcript_id] = spans_out

    return result


@dataclass(frozen=True, slots=True)
class Chapter:
    book: str
    title: str
    first: int
    last: int
    tokens: tuple[str, ...]


def chapter_links(units: Sequence[Unit], chapters: Sequence[Chapter]) -> dict[str, list[dict]]:
    if not chapters:
        return {}

    space = TermSpace.build([list(chapter.tokens) for chapter in chapters], CHAPTER_MAX_DF)
    chapter_vectors = [space.vector(chapter.tokens) for chapter in chapters]

    result: dict[str, list[dict]] = {}
    for unit in units:
        unit_text = tokenize(" ".join(unit.pages.values()))
        unit_vec = space.vector(unit_text)
        if not unit_vec:
            continue
        chapter_scores = [TermSpace.cosine(unit_vec, cv) for cv in chapter_vectors]
        ranked = sorted(
            range(len(chapters)),
            key=lambda i: (-chapter_scores[i], i),
        )
        top = [i for i in ranked[:TOP_CHAPTERS] if chapter_scores[i] > 0]
        if not top:
            continue
        links: list[dict] = []
        for chapter_index in top:
            chapter = chapters[chapter_index]
            common_terms = {
                term: unit_vec[term] * chapter_vectors[chapter_index][term]
                for term in set(unit_vec) & set(chapter_vectors[chapter_index])
            }
            terms = sorted(common_terms, key=lambda t: (-common_terms[t], t))[:6]
            links.append(
                {
                    "book": chapter.book,
                    "title": chapter.title,
                    "first": chapter.first,
                    "last": chapter.last,
                    "score": round(chapter_scores[chapter_index], 3),
                    "terms": terms,
                }
            )
        result[unit.rel] = links
    return result


def spans_summary(spans_by_id: Mapping[str, Sequence[Mapping[str, object]]]) -> tuple[int, int]:
    matched = 0
    unmatched = 0
    for spans in spans_by_id.values():
        for span in spans:
            if span["status"] != "unmatched":
                matched += 1
            else:
                unmatched += 1
    return (matched, unmatched)
