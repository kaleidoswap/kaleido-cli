"""Tests for kaleido_cli.output helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import kaleido_cli.output as out

# ---------------------------------------------------------------------------
# JSON / agent mode flags
# ---------------------------------------------------------------------------


def test_json_mode_default_is_false():
    assert not out.is_json_mode()


def test_set_json_mode_toggles():
    out.set_json_mode(True)
    assert out.is_json_mode()
    out.set_json_mode(False)
    assert not out.is_json_mode()


def test_set_agent_mode_affects_is_interactive():
    # In test env stdin/stdout are not TTYs, so is_interactive() is already False,
    # but we can confirm agent mode alone is respected too.
    out.set_agent_mode(True)
    assert not out.is_interactive()
    out.set_agent_mode(False)


def test_is_interactive_false_in_test_env():
    """Tests run outside a real TTY — is_interactive() must be False."""
    assert not out.is_interactive()


# ---------------------------------------------------------------------------
# _flatten_dict
# ---------------------------------------------------------------------------


def test_flatten_dict_simple():
    result = out._flatten_dict({"a": 1, "b": 2})
    assert ("a", 1) in result
    assert ("b", 2) in result


def test_flatten_dict_nested():
    result = out._flatten_dict({"outer": {"inner": 42}})
    assert ("outer.inner", 42) in result


def test_flatten_dict_list_of_dicts():
    result = out._flatten_dict({"items": [{"x": 1}, {"x": 2}]})
    assert ("items[0].x", 1) in result
    assert ("items[1].x", 2) in result


def test_flatten_dict_list_of_scalars():
    result = out._flatten_dict({"tags": ["a", "b"]})
    assert ("tags", ["a", "b"]) in result


# ---------------------------------------------------------------------------
# output_model
# ---------------------------------------------------------------------------


def test_output_model_json_mode():
    out.set_json_mode(True)
    data = MagicMock()
    data.model_dump.return_value = {"key": "value"}
    with patch.object(out, "print_json") as mock_print_json:
        out.output_model(data, title="Test")
    mock_print_json.assert_called_once_with({"key": "value"})


def test_output_model_panel_mode():
    out.set_json_mode(False)
    data = MagicMock()
    data.model_dump.return_value = {"key": "hello"}
    with patch.object(out.console, "print") as mock_print:
        out.output_model(data, title="Test Panel")
    mock_print.assert_called_once()
