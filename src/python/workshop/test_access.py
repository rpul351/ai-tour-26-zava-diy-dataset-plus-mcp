"""Tests for the access list. Run with: python test_access.py"""

import json
import tempfile
from pathlib import Path

from access import GLOBAL_RLS_ID, STORE_RLS_IDS, describe_viewer, load_access_list


def write(users) -> Path:
    path = Path(tempfile.mkdtemp()) / "access.json"
    path.write_text(json.dumps({"users": users}), encoding="utf-8")
    return path


def raises(path: Path) -> bool:
    try:
        load_access_list(path)
    except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return True
    return False


def test_super_manager_gets_the_all_stores_identity():
    acl = load_access_list(write({"Prof": {"role": "super_manager"}}))
    assert acl.rls_id_for("prof") == GLOBAL_RLS_ID


def test_store_manager_gets_only_that_stores_identity():
    acl = load_access_list(write({"sam": {"role": "store_manager", "store": "Zava Retail Kirkland"}}))
    assert acl.rls_id_for("sam") == STORE_RLS_IDS["Zava Retail Kirkland"]
    assert acl.rls_id_for("sam") != GLOBAL_RLS_ID


def test_names_are_not_case_or_space_sensitive():
    acl = load_access_list(write({"  Alice ": {"role": "super_manager"}}))
    assert acl.rls_id_for("ALICE") == GLOBAL_RLS_ID and acl.rls_id_for(" alice") == GLOBAL_RLS_ID


def test_someone_not_on_the_list_gets_nothing():
    acl = load_access_list(write({"alice": {"role": "super_manager"}}))
    assert acl.rls_id_for("mallory") is None
    assert acl.rls_id_for("") is None and acl.rls_id_for(None) is None


def test_a_bad_list_is_refused_not_guessed():
    assert raises(write({"x": {"role": "admin"}}))
    assert raises(write({"x": {"role": "store_manager", "store": "Zava Retail Nowhere"}}))
    assert raises(write({"x": {"role": "store_manager"}}))
    assert raises(write({}))
    bad = Path(tempfile.mkdtemp()) / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert raises(bad)


def test_a_missing_list_raises_so_the_service_fails_closed():
    try:
        load_access_list(Path(tempfile.mkdtemp()) / "missing.json")
    except OSError:
        return
    raise AssertionError("a missing access list must raise")


def test_every_store_in_the_example_file_is_valid():
    example = Path(__file__).with_name("access_list.example.json")
    assert len(load_access_list(example).users) >= 2


def test_the_model_is_told_who_is_asking_from_the_identity():
    assert "super manager" in describe_viewer(GLOBAL_RLS_ID) and "all 8 stores" in describe_viewer(GLOBAL_RLS_ID)
    kirkland = describe_viewer(STORE_RLS_IDS["Zava Retail Kirkland"], "ranjith-pulluri")
    assert "Ranjith Pulluri" in kirkland and "only Zava Retail Kirkland" in kirkland and "super manager" not in kirkland


def test_an_unknown_identity_is_described_as_the_narrowest():
    text = describe_viewer("not-a-real-id")
    assert "narrowest" in text and "super manager" not in text


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
