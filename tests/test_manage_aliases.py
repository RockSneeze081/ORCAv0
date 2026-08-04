import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge"))

import manage_aliases
from mesh_bridge import load_aliases


def run(monkeypatch, capsys, *cli_args):
    monkeypatch.setattr(sys, "argv", ["manage_aliases.py", *cli_args])
    exit_code = manage_aliases.main()
    return exit_code, capsys.readouterr()


def test_add_new_alias(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"

    code, out = run(monkeypatch, capsys, "--store", str(store), "add", "ea3jhl", "!a1b2c3d4")

    assert code == 0
    assert "added ea3jhl -> !a1b2c3d4" in out.out
    assert load_aliases(store) == {"ea3jhl": "!a1b2c3d4"}


def test_add_updates_existing_alias(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"
    run(monkeypatch, capsys, "--store", str(store), "add", "ea3jhl", "!a1b2c3d4")

    code, out = run(monkeypatch, capsys, "--store", str(store), "add", "ea3jhl", "!99999999")

    assert code == 0
    assert "updated ea3jhl: !a1b2c3d4 -> !99999999" in out.out
    assert load_aliases(store) == {"ea3jhl": "!99999999"}


def test_add_warns_on_unusual_node_id(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"

    code, out = run(monkeypatch, capsys, "--store", str(store), "add", "weird", "notanodeid")

    assert code == 0
    assert "doesn't look like a Meshtastic node id" in out.err
    assert load_aliases(store) == {"weird": "notanodeid"}


def test_remove_existing_alias(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"
    run(monkeypatch, capsys, "--store", str(store), "add", "ea3jhl", "!a1b2c3d4")

    code, out = run(monkeypatch, capsys, "--store", str(store), "remove", "ea3jhl")

    assert code == 0
    assert "removed ea3jhl" in out.out
    assert load_aliases(store) == {}


def test_remove_nonexistent_alias_fails(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"

    code, out = run(monkeypatch, capsys, "--store", str(store), "remove", "ghost")

    assert code == 1
    assert "no such alias: ghost" in out.err


def test_list_empty_store(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"

    code, out = run(monkeypatch, capsys, "--store", str(store), "list")

    assert code == 0
    assert "no aliases" in out.out


def test_list_populated_store(tmp_path, monkeypatch, capsys):
    store = tmp_path / "alias_store.json"
    run(monkeypatch, capsys, "--store", str(store), "add", "ea3jhl", "!a1b2c3d4")
    run(monkeypatch, capsys, "--store", str(store), "add", "repeater1", "!deadbeef")

    code, out = run(monkeypatch, capsys, "--store", str(store), "list")

    assert code == 0
    assert "ea3jhl" in out.out and "!a1b2c3d4" in out.out
    assert "repeater1" in out.out and "!deadbeef" in out.out
