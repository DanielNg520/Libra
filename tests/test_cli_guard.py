from __future__ import annotations

from typing import Any

import pytest

from libra import cli


def _parse_args(argv: list[str]) -> Any:
    return cli._build_parser().parse_args(argv)


@pytest.mark.parametrize("agent_var", cli.AGENT_VARS)
@pytest.mark.parametrize(
    ("argv", "name"),
    [
        (["login"], "login"),
        (["fetch"], "fetch"),
        (["export"], "export"),
        (["whisper"], "whisper"),
        (["read", "--course", "ECE 108", "ECE 108/x.pdf", "--fetch"], "read --fetch"),
    ],
)
def test_agent_refusal_owner_only_commands(agent_var: str, argv: list[str], name: str) -> None:
    args = _parse_args(argv)
    env = {agent_var: "1"}

    message = cli._agent_refusal(args, env, True)

    assert message is not None
    assert f"libra: {name} is owner-only" in message
    assert "LIBRA_OWNER_OK=1" in message
@pytest.mark.parametrize(
    "argv",
    [
        ["status"],
        ["read", "--course", "ECE 108", "ECE 108/x.pdf"],
        ["ocr", "x.png"],
    ],
)
def test_agent_refusal_allows_non_owner_commands(argv: list[str]) -> None:
    args = _parse_args(argv)
    for agent_var in cli.AGENT_VARS:
        assert cli._agent_refusal(args, {agent_var: "1"}, True) is None


@pytest.mark.parametrize("stdin_tty", [True, False])
def test_agent_refusal_empty_env_allows_fetch(stdin_tty: bool) -> None:
    args = _parse_args(["fetch"])
    assert cli._agent_refusal(args, {}, stdin_tty) is None


@pytest.mark.parametrize("stdin_tty", [False, True])
def test_agent_refusal_ssh_connection(stdin_tty: bool) -> None:
    args = _parse_args(["fetch"])
    env = {"SSH_CONNECTION": "1.2.3.4 1 5.6.7.8 22"}
    message = cli._agent_refusal(args, env, stdin_tty)
    if stdin_tty:
        assert message is None
    else:
        assert message is not None


@pytest.mark.parametrize("override", ["1", "0"])
def test_agent_refusal_owner_ok_override(override: str) -> None:
    args = _parse_args(["fetch"])
    env = {"CLAUDECODE": "1", "LIBRA_OWNER_OK": override}
    message = cli._agent_refusal(args, env, True)
    if override == "1":
        assert message is None
    else:
        assert message is not None


def test_agent_refusal_empty_agent_var_not_agent() -> None:
    args = _parse_args(["fetch"])
    assert cli._agent_refusal(args, {"CLAUDECODE": ""}, True) is None


def test_main_refuses_fetch_for_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for var in (*cli.AGENT_VARS, "SSH_CONNECTION", "LIBRA_OWNER_OK"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")

    def fail_if_called() -> None:
        pytest.fail("cli._settings should not be called for agent refusal")

    monkeypatch.setattr(cli, "_settings", fail_if_called)

    assert cli.main(["fetch"]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("libra: fetch is owner-only")
