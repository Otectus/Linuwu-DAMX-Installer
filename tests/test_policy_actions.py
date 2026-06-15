"""
Cross-check that the daemon's polkit action map stays in sync with the polkit
policy file, and that the policy/D-Bus config XML are well-formed.

This guards against silent drift: if archer_dbus.POLKIT_ACTIONS references an
action id that the .policy file doesn't define, every call to that method would
fail authorization at runtime. Run directly: `python3 tests/test_policy_actions.py`.

Parses POLKIT_ACTIONS out of archer_dbus.py via AST (ast.literal_eval) instead
of importing it, so this test needs no dbus/gi dependencies.
"""

import ast
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DBUS_PY = REPO_ROOT / "gui" / "archer_dbus.py"
POLICY = REPO_ROOT / "gui" / "io.otectus.Archer1.policy"
DBUS_CONF = REPO_ROOT / "gui" / "io.otectus.Archer1.conf"


def _load_polkit_actions_map():
    """Extract the POLKIT_ACTIONS dict literal from archer_dbus.py via AST."""
    tree = ast.parse(DBUS_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "POLKIT_ACTIONS":
                    return ast.literal_eval(node.value)
    raise AssertionError("POLKIT_ACTIONS not found in archer_dbus.py")


def _load_policy_action_ids():
    root = ET.fromstring(POLICY.read_text())
    return {a.attrib["id"] for a in root.iter("action")}


def test_policy_actions_in_sync():
    mapped = _load_polkit_actions_map()
    declared = _load_policy_action_ids()

    missing = sorted({a for a in mapped.values() if a not in declared})
    assert not missing, (
        f"POLKIT_ACTIONS references action ids not defined in the policy: {missing}"
    )

    # Every declared action should be referenced by at least one command, else
    # it's dead policy (a warning, not fatal, but worth surfacing).
    unused = sorted(declared - set(mapped.values()))
    assert not unused, f"Policy declares actions never used by the daemon: {unused}"


def test_xml_well_formed():
    # Raises on malformed XML.
    ET.fromstring(POLICY.read_text())
    ET.fromstring(DBUS_CONF.read_text())


def main():
    test_xml_well_formed()
    print("OK: policy and dbus-conf XML are well-formed")
    test_policy_actions_in_sync()
    mapped = _load_polkit_actions_map()
    print(f"OK: all {len(set(mapped.values()))} polkit actions in sync with policy")
    print("PASS: policy cross-check complete")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
