"""Export cached readings and textbook text to vault Tools/readings for agent search (ADR-0041 P3)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path

from libra.config import Settings
from libra.lecture_map import course_names
from libra.sources import TEXTBOOKS_DIR, SourceFile, list_sources, reconcile_index
from libra.source_pages import cached_pages
from libra.textbooks import is_searchable, pdf_page_texts
from libra.lecture_docs import sha256_file

READINGS_DIR = "Tools/readings"
MANIFEST_NAME = "manifest.json"
EXPORT_VERSION = 1

log = logging.getLogger(__name__)


def _load_manifest(root: Path) -> dict[str, str]:
    path = root / MANIFEST_NAME
    if not path.exists():
        log.debug("readings export: no manifest at %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            isinstance(data, dict)
            and data.get("version") == EXPORT_VERSION
            and isinstance(data.get("files"), dict)
        ):
            return {
                str(k): v
                for k, v in data["files"].items()
                if isinstance(k, str) and isinstance(v, str)
            }
        log.warning("readings export: malformed manifest at %s", path)
    except (OSError, json.JSONDecodeError):
        log.warning("readings export: unreadable manifest at %s", path, exc_info=True)
    return {}


def _render(kind: str, rel: str, pages: dict[int, str]) -> str:
    lines = [f"# {rel}", f"Kind: {kind}", ""]
    for n in sorted(pages):
        text = pages[n].strip()
        if text:
            lines.extend([f"### Page {n}", "", text, ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _delete_file(path: Path, deleted: list[Path]) -> None:
    try:
        path.unlink()
        deleted.append(path)
    except OSError:
        log.warning("readings export: failed to delete %s", path, exc_info=True)


def _prune_course(root: Path, course: str, kept: set[str], deleted: list[Path]) -> None:
    course_dir = root / course
    if not course_dir.exists():
        return
    for md in course_dir.rglob("*.md"):
        try:
            rel = md.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel[:-3] not in kept:
            _delete_file(md, deleted)
    for tmp in course_dir.rglob("*.tmp"):
        _delete_file(tmp, deleted)
    for dirpath, dirnames, _ in os.walk(course_dir, topdown=False):
        for dirname in dirnames:
            d = Path(dirpath) / dirname
            try:
                d.rmdir()
            except OSError:
                pass
    try:
        course_dir.rmdir()
    except OSError:
        pass


def _extract_pdf(vault: Path, rel: str) -> list[str] | None:
    try:
        return pdf_page_texts(vault / rel)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.warning(
            "readings export: text extraction failed for %s: %s",
            rel,
            type(exc).__name__,
        )
        return None


def _process_source(
    root: Path,
    vault: Path,
    settings: Settings,
    source: SourceFile,
    manifest: dict[str, str],
    kept: set[str],
    export_path: Path,
    written: list[Path],
) -> None:
    kept.add(source.rel)
    is_textbook = source.rel.startswith(f"{source.rel.split('/')[0]}/{TEXTBOOKS_DIR}/") and source.rel.lower().endswith(".pdf")
    pdf_key = is_textbook
    if is_textbook:
        key = "pdf:" + sha256_file(vault / source.rel)
        if manifest.get(source.rel) == key and export_path.exists():
            return
        pages_list = _extract_pdf(vault, source.rel)
        if pages_list is None:
            return
        pages = {i + 1: text for i, text in enumerate(pages_list)}
        kind = "textbook"
    else:
        pages = cached_pages(settings, source)
        if not pages:
            if source.rel.lower().endswith(".pdf"):
                key = "pdf:" + sha256_file(vault / source.rel)
                if manifest.get(source.rel) == key and export_path.exists():
                    return
                pages_list = _extract_pdf(vault, source.rel)
                if pages_list is None:
                    return
                if not is_searchable(pages_list):
                    kept.discard(source.rel)
                    return
                pages = {i + 1: text for i, text in enumerate(pages_list)}
                pdf_key = True
                kind = "reading"
            else:
                kept.discard(source.rel)
                return
        else:
            kind = "reading"
    body = _render(kind, source.rel, pages)
    if not any(text.strip() for text in pages.values()):
        kept.discard(source.rel)
        return
    if not pdf_key:
        key = "read:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    if manifest.get(source.rel) != key or not export_path.exists():
        _write_atomic(export_path, body)
        written.append(export_path)
        manifest[source.rel] = key


def write_readings(settings: Settings) -> list[Path]:
    vault = settings.obsidian_academic_vault_dir
    if vault is None:
        return []
    root = vault / READINGS_DIR
    root.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(root)
    original_manifest = dict(manifest)
    written: list[Path] = []
    deleted: list[Path] = []

    for course in course_names(vault):
        try:
            sources = list_sources(settings, course)
            reconcile_index(settings, course, sources)
            kept: set[str] = set()
            for source in sources:
                if source.kind not in ("doc", "photo"):
                    continue
                export_path = root / (source.rel + ".md")
                _process_source(root, vault, settings, source, manifest, kept, export_path, written)

            for rel in list(manifest):
                if rel.startswith(f"{course}/") and rel not in kept:
                    del manifest[rel]
            _prune_course(root, course, kept, deleted)
        except Exception as exc:
            log.warning("readings export %s failed: %s", course, type(exc).__name__, exc_info=True)

    if manifest != original_manifest or not (root / MANIFEST_NAME).exists():
        manifest_text = json.dumps(
            {"version": EXPORT_VERSION, "files": dict(sorted(manifest.items()))},
            indent=1,
            ensure_ascii=False,
        ) + "\n"
        _write_atomic(root / MANIFEST_NAME, manifest_text)

    if written or deleted:
        log.info("readings export: %d written, %d deleted", len(written), len(deleted))
    return written
