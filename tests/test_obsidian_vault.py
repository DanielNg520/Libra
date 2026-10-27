from datetime import date
from pathlib import Path

import pytest

from libra.obsidian_vault import VaultWriteError, write_note


class FakeSettings:
    def __init__(self, ghostwriter_dir=None, obsidian_academic_vault_dir=None,
                 obsidian_creative_vault_dir=None):
        self.ghostwriter_dir = ghostwriter_dir
        self.obsidian_academic_vault_dir = obsidian_academic_vault_dir
        self.obsidian_creative_vault_dir = obsidian_creative_vault_dir


def test_write_note_creates_file_with_frontmatter(tmp_path):
    fake_settings = FakeSettings(obsidian_academic_vault_dir=tmp_path)
    path = write_note(
        tmp_path,
        title="Hello World",
        content="body text",
        flow="academic",
        tags=["a", "b"],
        settings=fake_settings,
    )
    text = path.read_text(encoding="utf-8")

    assert path.exists()
    assert text.startswith("---\n")
    assert "title: Hello World" in text
    assert "flow: academic" in text
    assert "tags: [a, b]" in text
    assert text.endswith("body text")


def test_write_note_slug_and_date_in_filename(tmp_path):
    fake_settings = FakeSettings(obsidian_academic_vault_dir=tmp_path)
    path = write_note(
        tmp_path,
        title="Hello World",
        content="body text",
        flow="academic",
        settings=fake_settings,
    )

    assert path.name == f"hello-world-{date.today().isoformat()}.md"


def test_write_note_collision_appends_counter(tmp_path):
    fake_settings = FakeSettings(obsidian_academic_vault_dir=tmp_path)
    first = write_note(
        tmp_path,
        title="Hello World",
        content="body text",
        flow="academic",
        settings=fake_settings,
    )
    second = write_note(
        tmp_path,
        title="Hello World",
        content="body text",
        flow="academic",
        settings=fake_settings,
    )

    assert first != second
    assert first.exists()
    assert second.exists()
    assert f"-2-{date.today().isoformat()}.md" in second.name


def test_write_note_none_vault_dir_raises():
    with pytest.raises(VaultWriteError):
        write_note(None, title="x", content="y", flow="academic", settings=FakeSettings())


def test_write_note_rejects_path_outside_allowed_roots(tmp_path):
    with pytest.raises(VaultWriteError):
        write_note(
            tmp_path,
            title="x",
            content="y",
            flow="academic",
            settings=FakeSettings(),
        )


def test_write_note_escapes_quotes_in_title_with_colon(tmp_path):
    fake_settings = FakeSettings(obsidian_academic_vault_dir=tmp_path)
    path = write_note(
        tmp_path,
        title='He said "hi": ok',
        content="body",
        flow="academic",
        settings=fake_settings,
    )
    text = path.read_text(encoding="utf-8")
    assert 'title: "He said \\"hi\\": ok"' in text
