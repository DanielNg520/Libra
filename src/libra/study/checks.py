"""Lesson rule engine: loads vault `Tools/lesson_rules.toml`, picks a profile per lesson, runs its rules (ADR-0046)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType

from libra.study.check_kinds import KINDS, LessonParseError, Note, param_ok, parse_lesson

__all__ = [
    "Failure",
    "Profile",
    "Rule",
    "RuleFileError",
    "RuleSet",
    "RULES_RELPATH",
    "RESERVED_KEYS",
    "check_text",
    "lesson_paths",
    "load_rules",
    "parse_rules",
]

RULES_RELPATH = "Tools/lesson_rules.toml"
RESERVED_KEYS = frozenset({"text", "kind", "profiles", "enabled", "planned_kind"})


class RuleFileError(ValueError):
    """The rule file is missing, unparsable, or invalid."""


@dataclass(frozen=True)
class Rule:
    id: str
    text: str
    kind: str
    profiles: tuple[str, ...]
    enabled: bool
    planned_kind: str | None
    params: Mapping[str, object]


@dataclass(frozen=True)
class Profile:
    name: str
    extends: str | None
    overrides: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class Failure:
    rule: str
    rel: str
    line: int | None
    message: str
    note: bool = False

    def format(self) -> str:
        prefix = "note " if self.note else ""
        if self.line is not None:
            return f"{prefix}{self.rule} {self.rel}:{self.line} {self.message}"
        return f"{prefix}{self.rule} {self.rel} {self.message}"


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    profiles: Mapping[str, Profile]
    select: tuple[tuple[str, str], ...]
    exclude: tuple[str, ...]

    def profile_for(self, rel: str) -> str | None:
        if any(fnmatchcase(rel, pattern) for pattern in self.exclude):
            return None
        for glob, profile in self.select:
            if fnmatchcase(rel, glob):
                return profile
        return None

    def rules_for(self, profile: str) -> list[Rule]:
        if profile not in self.profiles:
            raise RuleFileError(f"unknown profile {profile!r}")

        chain: list[str] = []
        current: str | None = profile
        while current is not None:
            chain.append(current)
            current = self.profiles[current].extends

        merged: dict[str, dict[str, object]] = {}
        for name in reversed(chain):
            overrides = self.profiles[name].overrides
            for rule_id, values in overrides.items():
                merged.setdefault(rule_id, {}).update(values)

        result: list[Rule] = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            if not any(name in chain for name in rule.profiles):
                continue
            params = dict(rule.params)
            params.update(merged.get(rule.id, {}))
            result.append(replace(rule, params=MappingProxyType(params)))
        return result

    def manual_rules(self, profile: str) -> list[Rule]:
        return [rule for rule in self.rules_for(profile) if rule.kind == "manual"]


def _check_params(
    kind: str,
    params: Mapping[str, object],
    context: str,
) -> None:
    spec = KINDS[kind]
    for name, type_name in spec.required.items():
        if name not in params:
            raise RuleFileError(f"{context}: missing required param {name!r}")
    for name, value in params.items():
        expected = spec.required.get(name) or spec.optional.get(name)
        if expected is None:
            raise RuleFileError(f"{context}: unknown param {name!r}")
        if not param_ok(value, expected):
            raise RuleFileError(
                f"{context}: param {name!r} must be {expected}"
            )
    if spec.validate is not None:
        error = spec.validate(dict(params))
        if error is not None:
            raise RuleFileError(f"{context}: {error}")


def _parse_rule(rule_id: str, raw: Mapping[str, object], profile_names: set[str]) -> Rule:
    if not isinstance(raw, Mapping):
        raise RuleFileError(f"rule {rule_id!r}: must be a table")

    if "text" not in raw:
        raise RuleFileError(f"rule {rule_id!r}: missing required key 'text'")
    text = raw["text"]
    if not isinstance(text, str) or not text:
        raise RuleFileError(f"rule {rule_id!r}: 'text' must be a non-empty string")

    if "kind" not in raw:
        raise RuleFileError(f"rule {rule_id!r}: missing required key 'kind'")
    kind = raw["kind"]
    if not isinstance(kind, str):
        raise RuleFileError(f"rule {rule_id!r}: 'kind' must be a string")
    if kind not in KINDS:
        raise RuleFileError(f"rule {rule_id!r}: unknown kind {kind!r}")

    if "profiles" not in raw:
        raise RuleFileError(f"rule {rule_id!r}: missing required key 'profiles'")
    profiles_raw = raw["profiles"]
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise RuleFileError(f"rule {rule_id!r}: 'profiles' must be a non-empty list")
    profiles_list: list[str] = []
    for item in profiles_raw:
        if not isinstance(item, str):
            raise RuleFileError(f"rule {rule_id!r}: profile names must be strings")
        if item not in profile_names:
            raise RuleFileError(f"rule {rule_id!r}: unknown profile {item!r}")
        profiles_list.append(item)

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise RuleFileError(f"rule {rule_id!r}: 'enabled' must be a bool")

    planned_kind = raw.get("planned_kind")
    if planned_kind is not None:
        if kind != "manual":
            raise RuleFileError(
                f"rule {rule_id!r}: 'planned_kind' only allowed for manual rules"
            )
        if not isinstance(planned_kind, str):
            raise RuleFileError(f"rule {rule_id!r}: 'planned_kind' must be a string")

    params: dict[str, object] = {}
    for key, value in raw.items():
        if key not in RESERVED_KEYS:
            params[key] = value

    _check_params(kind, params, f"rule {rule_id!r}")

    return Rule(
        id=rule_id,
        text=text,
        kind=kind,
        profiles=tuple(profiles_list),
        enabled=enabled,
        planned_kind=planned_kind,
        params=MappingProxyType(params),
    )


def _parse_profile(
    name: str,
    raw: Mapping[str, object],
    profile_names: set[str],
) -> Profile:
    if not isinstance(raw, Mapping):
        raise RuleFileError(f"profile {name!r}: must be a table")

    for key in raw:
        if key not in {"extends", "overrides"}:
            raise RuleFileError(f"profile {name!r}: unknown key {key!r}")

    extends = raw.get("extends")
    if extends is not None:
        if not isinstance(extends, str):
            raise RuleFileError(f"profile {name!r}: 'extends' must be a string")
        if extends not in profile_names:
            raise RuleFileError(f"profile {name!r}: extends unknown profile {extends!r}")

    overrides_raw = raw.get("overrides", {})
    if not isinstance(overrides_raw, Mapping):
        raise RuleFileError(f"profile {name!r}: 'overrides' must be a table")
    overrides: dict[str, Mapping[str, object]] = {}
    for rule_id, values in overrides_raw.items():
        if not isinstance(values, Mapping):
            raise RuleFileError(
                f"profile {name!r}: override {rule_id!r} must be a table"
            )
        overrides[rule_id] = MappingProxyType(dict(values))

    return Profile(
        name=name,
        extends=extends,
        overrides=MappingProxyType(overrides),
    )


def _validate_extends_cycle(profiles: Mapping[str, Profile]) -> None:
    for name in profiles:
        seen: set[str] = set()
        current: str | None = name
        while current is not None:
            if current in seen:
                raise RuleFileError(f"extends cycle involving profile {name!r}")
            seen.add(current)
            current = profiles[current].extends


def _validate_overrides(rules: Mapping[str, Rule], profiles: Mapping[str, Profile]) -> None:
    for profile_name, profile in profiles.items():
        for rule_id, values in profile.overrides.items():
            if rule_id not in rules:
                raise RuleFileError(
                    f"profile {profile_name!r}: override for unknown rule {rule_id!r}"
                )
            rule = rules[rule_id]
            spec = KINDS[rule.kind]
            all_names = set(spec.required) | set(spec.optional)
            for param_name in values:
                if param_name not in all_names:
                    raise RuleFileError(
                        f"profile {profile_name!r}: unknown param {param_name!r} "
                        f"for rule {rule_id!r}"
                    )
                expected = spec.required.get(param_name) or spec.optional[param_name]
                if not param_ok(values[param_name], expected):
                    raise RuleFileError(
                        f"profile {profile_name!r}: param {param_name!r} "
                        f"for rule {rule_id!r} must be {expected}"
                    )
            merged = dict(rule.params)
            merged.update(values)
            if spec.validate is not None:
                error = spec.validate(merged)
                if error is not None:
                    raise RuleFileError(
                        f"profile {profile_name!r}: override for rule {rule_id!r}: {error}"
                    )


def parse_rules(text: str) -> RuleSet:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise RuleFileError(f"invalid TOML: {exc}") from exc

    if not isinstance(data, dict):
        raise RuleFileError("top level must be a table")

    allowed_top = {"exclude", "select", "profiles", "rules"}
    for key in data:
        if key not in allowed_top:
            raise RuleFileError(f"unknown top-level key {key!r}")

    if "select" not in data:
        raise RuleFileError("missing required top-level key 'select'")
    if "profiles" not in data:
        raise RuleFileError("missing required top-level key 'profiles'")
    if "rules" not in data:
        raise RuleFileError("missing required top-level key 'rules'")

    exclude_raw = data.get("exclude", [])
    if not isinstance(exclude_raw, list):
        raise RuleFileError("'exclude' must be a list of strings")
    exclude: list[str] = []
    for item in exclude_raw:
        if not isinstance(item, str):
            raise RuleFileError("'exclude' must be a list of strings")
        exclude.append(item)

    select_raw = data["select"]
    if not isinstance(select_raw, list) or not select_raw:
        raise RuleFileError("'select' must be a non-empty array of tables")
    select: list[tuple[str, str]] = []
    for i, entry in enumerate(select_raw):
        if not isinstance(entry, Mapping):
            raise RuleFileError(f"select[{i}]: must be a table")
        if set(entry) != {"glob", "profile"}:
            raise RuleFileError(f"select[{i}]: must have exactly keys 'glob' and 'profile'")
        glob = entry["glob"]
        profile = entry["profile"]
        if not isinstance(glob, str):
            raise RuleFileError(f"select[{i}]: 'glob' must be a string")
        if not isinstance(profile, str):
            raise RuleFileError(f"select[{i}]: 'profile' must be a string")
        select.append((glob, profile))

    profiles_raw = data["profiles"]
    if not isinstance(profiles_raw, Mapping):
        raise RuleFileError("'profiles' must be a table")
    profile_names: set[str] = set()
    for name in profiles_raw:
        if not isinstance(name, str):
            raise RuleFileError("profile names must be strings")
        profile_names.add(name)

    profiles: dict[str, Profile] = {}
    for name, raw in profiles_raw.items():
        profiles[name] = _parse_profile(name, raw, profile_names)
    _validate_extends_cycle(profiles)

    for glob, profile in select:
        if profile not in profile_names:
            raise RuleFileError(f"select: unknown profile {profile!r}")

    rules_raw = data["rules"]
    if not isinstance(rules_raw, Mapping):
        raise RuleFileError("'rules' must be a table")
    if not rules_raw:
        raise RuleFileError("'rules' must be a non-empty table")

    rules: dict[str, Rule] = {}
    for rule_id, raw in rules_raw.items():
        rules[rule_id] = _parse_rule(rule_id, raw, profile_names)

    _validate_overrides(rules, profiles)

    return RuleSet(
        rules=tuple(rules.values()),
        profiles=MappingProxyType(profiles),
        select=tuple(select),
        exclude=tuple(exclude),
    )


def load_rules(vault: Path) -> RuleSet:
    path = vault / RULES_RELPATH
    if not path.is_file():
        raise RuleFileError(f"rule file missing: {RULES_RELPATH}")
    return parse_rules(path.read_text(encoding="utf-8"))


def check_text(text: str, rel: str, vault: Path, rules: Sequence[Rule]) -> list[Failure]:
    try:
        lesson = parse_lesson(text, rel)
    except LessonParseError as exc:
        return [Failure("parse", rel, None, f"frontmatter: {exc}")]

    failures: list[Failure] = []
    for rule in rules:
        spec = KINDS[rule.kind]
        if spec.check is None:
            continue
        for item in spec.check(lesson, rule.params, vault):
            if isinstance(item, Note):
                failures.append(Failure(rule.id, rel, item.line, item.message, note=True))
            else:
                line, message = item
                failures.append(Failure(rule.id, rel, line, message))
    return failures


def lesson_paths(vault: Path, ruleset: RuleSet, roots: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    for root in roots:
        base = vault / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if not path.is_file():
                continue
            rel = path.relative_to(vault).as_posix()
            if ruleset.profile_for(rel) is not None:
                seen.add(rel)
    return sorted(seen)
