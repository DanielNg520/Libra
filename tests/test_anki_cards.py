import json

from libra.study.anki_cards import (
    DECKS,
    MAX_ANSWER_CHARS,
    Card,
    build_card_prompt,
    lesson_tag,
    note_guid,
    parse_cards,
    reading_embeds,
    reading_sections,
    recall_questions,
    signal_cards,
    to_anki_html,
)
def test_decks_keys():
    assert set(DECKS) == {"PR", "LA", "OP", "DSP", "C", "PY", "DSA"}
    assert DECKS["DSA"] == "Self study::DSA"


def test_recall_questions_extracts_markers():
    lesson = (
        "## Reading\n"
        "some reading text\n"
        "## Recall\n"
        "- What is $P(E^c)$?\n"
        "* Why?\n"
        "1. How?\n"
        "## Sources\n"
        "source text\n"
    )
    assert recall_questions(lesson) == [
        "What is $P(E^c)$?",
        "Why?",
        "How?",
    ]


def test_recall_questions_no_section():
    assert recall_questions("## Reading\nsome text\n") == []


def test_build_card_prompt_numbering_and_lesson():
    questions = ["q1", "q2"]
    prompt = build_card_prompt("lesson body", questions, [])
    assert "Questions:" in prompt
    assert "1. q1" in prompt
    assert "2. q2" in prompt
    assert "Lesson:" in prompt
    assert "lesson body" in prompt


def test_reading_sections_real_headings():
    lesson = (
        "# T\n"
        "## Reading\n"
        "### 1. The preprocessor and `#define` constants\n"
        "body line\n"
        "```c\n"
        "## not an end\n"
        "### not a heading\n"
        "```\n"
        "### 3 Conditional probability\n"
        "## Practice\n"
        "### Hand problems\n"
        "## Recall\n"
        "- Q?\n"
    )
    assert reading_sections(lesson) == [
        "1. The preprocessor and `#define` constants",
        "3 Conditional probability",
    ]


def test_reading_sections_missing_section():
    assert reading_sections("## Recall\n### x\n") == []


def test_reading_embeds_forms():
    lesson = """# T
## Reading
![[Self study/Probability/concepts/De Morgan's laws|De Morgan's laws]]
![[Bayes rule]]
![[Self study/Probability/concepts/Total probability.md#Idea|3]]

![[figures/tree.png]]

See ![[Inline]] here

![[A|Alpha]] ![[B]]
```md
![[Fenced]]
```
## Practice
![[After]]
"""
    assert reading_embeds(lesson) == [
        ("Self study/Probability/concepts/De Morgan's laws", "De Morgan's laws"),
        ("Bayes rule", "Bayes rule"),
        ("Self study/Probability/concepts/Total probability.md", "Total probability"),
        ("A", "Alpha"),
        ("B", "B"),
    ]


def test_reading_embeds_without_reading():
    assert reading_embeds("## Recall\n![[X]]\n") == []


def test_reading_embeds_list_and_callout():
    lesson = "# T\n## Reading\n- ![[A]]\n\n> [!note] Read\n> ![[B|Bee]]\n\n## Practice\n"
    assert reading_embeds(lesson) == [("A", "A"), ("B", "Bee")]


def test_reading_embeds_skip_code_blocks():
    lesson = "# T\n## Reading\nIntro.\n\n    ![[Indented]]\n\n~~~md\n![[Tilde]]\n~~~\n\n![[Real]]\n"
    assert reading_embeds(lesson) == [("Real", "Real")]


def test_reading_sections_skip_tilde_fence():
    lesson = "# T\n## Reading\n### One\n~~~md\n### Not a heading\n~~~\n### Two\n## Practice\n### After\n"
    assert reading_sections(lesson) == ["One", "Two"]


def test_build_card_prompt_with_concepts():
    prompt = build_card_prompt("lesson body", ["q1"], ["Events"], [("Events", "Event body"), ("Bayes", "Bayes body")])
    assert prompt.splitlines()[1] == "The lesson's Reading section embeds concept notes (lines like ![[...]]); their text follows the lesson below and counts as lesson text."
    assert "or the title of an embedded concept note" in prompt
    assert prompt.endswith("lesson body\n\nConcept note: Events\nEvent body\n\nConcept note: Bayes\nBayes body")


def test_build_card_prompt_without_concepts_unchanged():
    plain = build_card_prompt("body", ["q1"], ["Sec A"])
    with_concepts_default = build_card_prompt("body", ["q1"], ["Sec A"], [])
    assert plain == with_concepts_default
    assert "Concept note" not in plain
    assert "embedded concept note" not in plain


def test_build_card_prompt_with_sections():
    prompt = build_card_prompt("body", ["q1"], ["Sec A", "Sec B"])
    assert "Questions:" in prompt
    assert "1. q1" in prompt
    assert "Reading concepts:" in prompt
    assert "1. Sec A" in prompt
    assert "2. Sec B" in prompt
    assert '"section"' in prompt
    assert "body" in prompt


def test_build_card_prompt_without_sections_or_questions():
    prompt = build_card_prompt("body", ["q1"], [])
    assert "Reading concepts:" not in prompt
    prompt = build_card_prompt("body", [], ["Sec A"])
    assert "Questions:" not in prompt
    assert "Reading concepts:" in prompt


def _raw(questions, answers):
    return "leading prose\n```json\n" + json.dumps(
        [{"q": q, "a": a} for q, a in zip(questions, answers)]
    ) + "\n```\ntrailing prose"


def test_parse_cards_success():
    questions = ["First?", "Second?"]
    raw = _raw(questions, ["answer one", "answer two"])
    cards, errors = parse_cards(raw, questions, [])
    assert errors == []
    assert cards == [Card("First?", "answer one"), Card("Second?", "answer two")]


def test_parse_cards_no_json_array():
    cards, errors = parse_cards("no brackets here", ["q"], [])
    assert cards == []
    assert errors == ["no JSON array found"]


def test_parse_cards_invalid_json():
    cards, errors = parse_cards("[not json]", ["q"], [])
    assert cards == []
    assert len(errors) == 1
    assert errors[0].startswith("invalid JSON")


def test_parse_cards_wrong_count():
    questions = ["q1", "q2"]
    raw = _raw(questions, ["a1"])
    cards, errors = parse_cards(raw, questions, [])
    assert cards == []
    assert errors == ["expected 2 cards, got 1"]


def test_parse_cards_question_changed():
    questions = ["original", "q2"]
    raw = _raw(["changed", "q2"], ["a1", "a2"])
    cards, errors = parse_cards(raw, questions, [])
    assert cards == []
    assert errors == ["card 1: question changed"]


def test_parse_cards_empty_answer():
    questions = ["q1", "q2"]
    raw = _raw(questions, ["", "a2"])
    cards, errors = parse_cards(raw, questions, [])
    assert cards == []
    assert errors == ["card 1: empty answer"]


def test_parse_cards_answer_too_long():
    questions = ["q1", "q2"]
    answers = ["a" * (MAX_ANSWER_CHARS + 1), "a2"]
    raw = _raw(questions, answers)
    cards, errors = parse_cards(raw, questions, [])
    assert cards == []
    assert errors == ["card 1: answer too long"]


def test_parse_cards_needs_string_q_and_a():
    questions = ["q1", "q2"]
    raw = "leading\n" + json.dumps([{"q": 1, "a": "a1"}, {"q": "q2", "a": "a2"}]) + "\ntrailing"
    cards, errors = parse_cards(raw, questions, [])
    assert cards == []
    assert errors == ["card 1: needs string q and a"]


def test_parse_cards_with_reading_success():
    questions = ["R?"]
    sections = ["A", "B"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "R?", "a": "r"},
        {"q": "A1?", "a": "a1", "section": "A"},
        {"q": "A2?", "a": "a2", "section": "A"},
        {"q": "B1?", "a": "b1", "section": "B"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == []
    assert cards == [
        Card("R?", "r"),
        Card("A1?", "a1", "A"),
        Card("A2?", "a2", "A"),
        Card("B1?", "b1", "B"),
    ]


def test_parse_cards_reading_only():
    questions = []
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "A1?", "a": "a1", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == []
    assert cards == [Card("A1?", "a1", "A")]


def test_parse_cards_missing_section_coverage():
    questions = ["R?"]
    sections = ["A", "B"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "R?", "a": "r"},
        {"q": "A1?", "a": "a1", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["section 'B': 0 cards, needs 1 to 3"]


def test_parse_cards_unknown_section():
    questions = ["R?"]
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "R?", "a": "r"},
        {"q": "A1?", "a": "a1", "section": "A"},
        {"q": "Z1?", "a": "z1", "section": "Z"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["card 3: unknown section"]


def test_parse_cards_too_many_for_section():
    questions = []
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "A1?", "a": "a1", "section": "A"},
        {"q": "A2?", "a": "a2", "section": "A"},
        {"q": "A3?", "a": "a3", "section": "A"},
        {"q": "A4?", "a": "a4", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["section 'A': 4 cards, needs 1 to 3"]


def test_parse_cards_duplicate_reading_question():
    questions = ["R?"]
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "R?", "a": "r"},
        {"q": "Same?", "a": "a1", "section": "A"},
        {"q": "Same?", "a": "a2", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["card 3: duplicate question"]


def test_parse_cards_reading_repeats_recall_question():
    questions = ["R?"]
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "R?", "a": "r"},
        {"q": "R?", "a": "a1", "section": "A"},
        {"q": "Other?", "a": "a2", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["card 2: duplicate question"]


def test_parse_cards_reading_needs_section_key():
    questions = []
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "A1?", "a": "a1"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == [
        "card 1: needs string q, a and section",
        "section 'A': 0 cards, needs 1 to 3",
    ]


def test_parse_cards_reading_empty_question():
    questions = []
    sections = ["A"]
    raw = "leading\n```json\n" + json.dumps([
        {"q": "  ", "a": "a", "section": "A"},
        {"q": "A2?", "a": "a2", "section": "A"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["card 1: empty question"]


def test_parse_cards_extra_without_sections():
    questions = ["q1"]
    sections = []
    raw = "leading\n```json\n" + json.dumps([
        {"q": "q1", "a": "a1"},
        {"q": "q2", "a": "a2"},
    ]) + "\n```\ntrailing"
    cards, errors = parse_cards(raw, questions, sections)
    assert errors == ["expected 1 cards, got 2"]


def test_to_anki_html_example():
    assert to_anki_html("Use `a<b` and $x^2$ or $$y$$, **key**\nnext") == (
        "Use <code>a&lt;b</code> and \\(x^2\\) or \\[y\\], <b>key</b><br>next"
    )


def test_to_anki_html_escapes_ampersand():
    assert to_anki_html("a & b") == "a &amp; b"


def test_note_guid_properties():
    guid1 = note_guid("path/one.md", "question?")
    guid2 = note_guid("path/one.md", "question?")
    guid3 = note_guid("path/two.md", "question?")
    guid4 = note_guid("path/one.md", "other question?")
    assert guid1 == guid2
    assert guid1 != guid3
    assert guid1 != guid4
    assert guid1.startswith("semai-")
    assert len(guid1) == 26


def test_lesson_tag_example():
    assert lesson_tag("Self study/Probability/02 events and Bayes.md") == (
        "lesson::02_events_and_Bayes"
    )


def test_signal_cards_bullets():
    note = "\n".join(
        [
            "---",
            "tags:",
            "  - topic/dsa",
            "---",
            "# Two pointers",
            "",
            "## Reading",
            "",
            "### Idea",
            "",
            "- idea bullet is not a signal",
            "",
            "### Signals",
            "",
            "- Sorted array plus pair sum",
            "* In-place removal keeping order",
            "  - nested detail",
            "- Sorted array plus pair sum",
            "-  ",
            "```python",
            "- fenced line",
            "```",
            "",
            "### Templates",
            "",
            "- template bullet",
            "",
            "## Problem log",
            "- log bullet",
        ]
    )
    assert signal_cards(note, "Two pointers") == [
        Card("Which pattern fits this signal: Sorted array plus pair sum", "Two pointers"),
        Card("Which pattern fits this signal: In-place removal keeping order", "Two pointers"),
    ]


def test_signal_cards_missing_sections():
    assert signal_cards("# X\n\n### Signals\n\n- a\n", "X") == []
    assert signal_cards("## Reading\n\n### Idea\n\n- a\n", "X") == []
    assert signal_cards("## Reading\n\n## Problem log\n\n### Signals\n\n- a\n", "X") == []


def test_signal_cards_ignores_fenced_headings():
    assert signal_cards(
        "## Reading\n\n```text\n### Signals\n- fake\n```\n\n### Signals\n\n- real\n",
        "P",
    ) == [Card("Which pattern fits this signal: real", "P")]
