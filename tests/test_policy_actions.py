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
import importlib.util
import re
import sys
import types
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


def _load_read_only_commands():
    """Extract the READ_ONLY_COMMANDS frozenset literal via AST."""
    tree = ast.parse(DBUS_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "READ_ONLY_COMMANDS":
                    # frozenset({...}) — evaluate the set literal argument.
                    assert isinstance(node.value, ast.Call), (
                        "READ_ONLY_COMMANDS must be frozenset({...})")
                    return frozenset(ast.literal_eval(node.value.args[0]))
    raise AssertionError("READ_ONLY_COMMANDS not found in archer_dbus.py")


def _authorize_call_strings(tree):
    """All string literals passed as first arg to self._authorize(...)."""
    calls = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_authorize"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            calls.add(node.args[0].value)
    return calls


def _dbus_service_methods(tree):
    """FunctionDefs decorated with @dbus.service.method (signals excluded)."""
    methods = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Attribute) and func.attr == "method":
                methods.append(node)
    return methods


def _snake_case(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


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


def test_authorize_call_sites_are_mapped():
    """Every _authorize("cmd") literal must be in POLKIT_ACTIONS or READ_ONLY_COMMANDS.

    With fail-closed authorization, an unmapped command string is DENIED at
    runtime — a typo in a handler would silently brick that method.
    """
    tree = ast.parse(DBUS_PY.read_text())
    known = set(_load_polkit_actions_map()) | _load_read_only_commands()
    unmapped = sorted(_authorize_call_strings(tree) - known)
    assert not unmapped, (
        f"_authorize() called with commands not in POLKIT_ACTIONS or "
        f"READ_ONLY_COMMANDS (these would be denied): {unmapped}"
    )


def test_every_dbus_method_gated_or_read_only():
    """Every @dbus.service.method handler must call _authorize or be read-only.

    Drift guard for F-SEC1: a future mutating method added without an
    _authorize call (or a deliberate READ_ONLY_COMMANDS entry) fails here
    instead of shipping an ungated root operation.
    """
    tree = ast.parse(DBUS_PY.read_text())
    read_only = _load_read_only_commands()
    offenders = []
    for method in _dbus_service_methods(tree):
        gated = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_authorize"
            for child in method.body
            for n in ast.walk(child)
        )
        if not gated and _snake_case(method.name) not in read_only:
            offenders.append(method.name)
    assert not offenders, (
        f"D-Bus methods neither calling _authorize nor listed in "
        f"READ_ONLY_COMMANDS: {sorted(offenders)}"
    )


def test_authorize_fails_closed_for_unmapped():
    """_authorize must DENY a command that is neither mapped nor read-only.

    Imports archer_dbus with dbus/gi stubbed so no D-Bus stack is needed,
    and patches _check_polkit to raise, proving it is never consulted.
    """
    stub_dbus = types.ModuleType("dbus")
    stub_service = types.ModuleType("dbus.service")

    class _Object:
        pass

    def _decorator_factory(*_a, **_k):
        return lambda f: f

    stub_service.Object = _Object
    stub_service.method = _decorator_factory
    stub_service.signal = _decorator_factory
    stub_service.BusName = object
    stub_dbus.service = stub_service
    stub_dbus.UInt32 = int
    stub_dbus.Interface = object
    stub_dbus.SystemBus = object

    stub_gi = types.ModuleType("gi")
    stub_repository = types.ModuleType("gi.repository")
    stub_glib = types.SimpleNamespace(timeout_add_seconds=lambda *a, **k: None)
    stub_repository.GLib = stub_glib
    stub_gi.repository = stub_repository

    saved = {name: sys.modules.get(name)
             for name in ("dbus", "dbus.service", "gi", "gi.repository")}
    sys.modules.update({
        "dbus": stub_dbus,
        "dbus.service": stub_service,
        "gi": stub_gi,
        "gi.repository": stub_repository,
    })
    sys.path.insert(0, str(REPO_ROOT / "gui"))
    try:
        spec = importlib.util.spec_from_file_location("archer_dbus_under_test", DBUS_PY)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        def _never_called(*_a, **_k):
            raise AssertionError("_check_polkit must not run for unmapped commands")

        mod._check_polkit = _never_called
        fake_self = types.SimpleNamespace(_bus=None)
        result = mod.ArcherDBusService._authorize(
            fake_self, "definitely_not_a_mapped_command", ":1.42")
        assert result is False, (
            f"_authorize fail-opened: returned {result!r} for an unmapped "
            f"command (expected False)"
        )
    finally:
        sys.path.remove(str(REPO_ROOT / "gui"))
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def main():
    test_xml_well_formed()
    print("OK: policy and dbus-conf XML are well-formed")
    test_policy_actions_in_sync()
    mapped = _load_polkit_actions_map()
    print(f"OK: all {len(set(mapped.values()))} polkit actions in sync with policy")
    test_authorize_call_sites_are_mapped()
    print("OK: every _authorize() command string is mapped or read-only")
    test_every_dbus_method_gated_or_read_only()
    print("OK: every D-Bus method is polkit-gated or explicitly read-only")
    test_authorize_fails_closed_for_unmapped()
    print("OK: _authorize denies unmapped commands (fail-closed)")
    print("PASS: policy cross-check complete")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
