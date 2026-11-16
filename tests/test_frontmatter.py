import random
import string

import pytest

from libra.study import frontmatter as fm


def test_fuzz_dump_load_round_trip():
    rng = random.Random(1234)
    alphabet = string.printable + "é" + chr(0x2028)
    for _ in range(5000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8)))
        dumped = fm.dump({"k": s})
        loaded, _ = fm.load(dumped)
        assert loaded == {"k": s}, repr(s)


def test_scalar_types_round_trip():
    d = {
        "none": None,
        "true": True,
        "false": False,
        "zero": 0,
        "negative": -7,
        "big": 10**12,
        "float1": 1.5,
        "float2": -0.25,
        "str_float": "1.0",
        "str_int": "42",
        "str_true": "true",
        "str_null": "null",
        "empty": "",
        "padded": " padded ",
        "colon": "a: b",
        "hash": "has # hash",
        "quote": 'quote " inside',
        "slash": "back\\slash",
        "multiline": "line1\nline2\n",
    }
    dumped = fm.dump(d, "line1\n\nline2")
    loaded, body = fm.load(dumped)
    assert loaded == d
    assert body == "line1\n\nline2"


def test_backward_compat_old_escaping():
    text = '---\nk: "a\\\\b \\"q\\""\n---\n'
    loaded, _ = fm.load(text)
    assert loaded == {"k": 'a\\b "q"'}


def test_no_header_raises_no_frontmatter_header():
    with pytest.raises(fm.NoFrontmatterHeader):
        fm.load("just body text\nno header at all\n")


def test_no_header_is_frontmatter_error_subclass():
    assert issubclass(fm.NoFrontmatterHeader, fm.FrontmatterError)


def test_unclosed_header_raises_frontmatter_error():
    with pytest.raises(fm.FrontmatterError):
        fm.load("---\nkey: value\nbody without closing ---\n")


def test_header_line_without_colon_raises_frontmatter_error():
    with pytest.raises(fm.FrontmatterError) as exc:
        fm.load("---\nthis line has no colon\n---\nbody\n")
    assert not isinstance(exc.value, fm.NoFrontmatterHeader)


def test_blank_lines_in_header_ignored():
    loaded, _ = fm.load("---\nkey1: value1\n\nkey2: value2\n---\nbody\n")
    assert loaded == {"key1": "value1", "key2": "value2"}


def test_dump_preserves_key_order():
    d = {"z": 1, "a": 2, "m": 3}
    dumped = fm.dump(d)
    assert dumped.index("z:") < dumped.index("a:") < dumped.index("m:")


def test_block_list_loads_flat_keys_and_body():
    loaded, body = fm.load(
        "---\nkey1: value1\ntags:\n  - a\n  - b\nkey2: value2\n---\nbody\n"
    )
    assert loaded == {"key1": "value1", "tags": ["a", "b"], "key2": "value2"}
    assert body == "body"


def test_block_list_items_use_scalar_rules():
    loaded, _ = fm.load(
        "---\nvals:\n  - 3\n  - \"x: y\"\n  - true\n---\n"
    )
    assert loaded == {"vals": [3, "x: y", True]}


def test_blank_line_between_list_items_does_not_end_list():
    loaded, _ = fm.load("---\ntags:\n  - a\n\n  - b\n---\n")
    assert loaded == {"tags": ["a", "b"]}


def test_empty_value_with_next_key_loads_none():
    loaded, _ = fm.load("---\nempty:\nnext: value\n---\n")
    assert loaded == {"empty": None, "next": "value"}


def test_list_under_final_key_before_closing_delimiter():
    loaded, _ = fm.load("---\nkey1: value1\nfinal:\n  - a\n  - b\n---\n")
    assert loaded == {"key1": "value1", "final": ["a", "b"]}


@pytest.mark.parametrize(
    "text",
    [
        "---\nk: v\n  - a\n---\n",
        "---\n  - a\n---\n",
    ],
)
def test_continuation_line_raises_frontmatter_error(text):
    with pytest.raises(fm.FrontmatterError):
        fm.load(text)


@pytest.mark.parametrize(
    "lst",
    [
        ["a", "b c", "1.0", "true", "x: y", ""],
        ["only"],
        [1, 2.5, True],
    ],
    ids=["mixed_strings", "single", "non_string_scalars"],
)
def test_block_list_round_trip(lst):
    text = fm.dump({"tags": lst, "after": "v"})
    data, _ = fm.load(text)
    assert data == {"tags": lst, "after": "v"}


def test_tuple_dumps_and_loads_as_list():
    text = fm.dump({"tags": ("a", "b")})
    data, _ = fm.load(text)
    assert data == {"tags": ["a", "b"]}


def test_empty_list_loads_as_none():
    text = fm.dump({"k": []})
    data, _ = fm.load(text)
    assert data == {"k": None}


def test_dump_block_list_text():
    text = fm.dump({"tags": ["a", "b"]})
    assert text == "---\ntags:\n  - a\n  - b\n---\n"


def test_block_list_note_round_trip_stable():
    text = "---\ntags:\n  - a\n  - b\n---\nbody\n"
    data, body = fm.load(text)
    assert (data, fm.load(fm.dump(data, body))[1]) == (
        data,
        body,
    )
    assert fm.load(fm.dump(data, body))[0] == data
