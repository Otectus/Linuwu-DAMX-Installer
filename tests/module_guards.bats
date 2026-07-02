#!/usr/bin/env bats
# Module-contract guard tests: modules must fail by RETURNING non-zero (so
# install.sh's per-module rollback runs), never by exiting the installer, and
# must not mutate anything under --dry-run.
#
# Unlike modules.bats, setup() here does NOT source lib/utils.sh (its run()
# would shadow bats' run helper) and does NOT override error() — the whole
# point is to exercise the REAL error()/warn() behavior. Each test runs the
# module in a throwaway bash child.

@test "gui module_install returns 1 (does not exit) when source files are missing" {
    # Real error() exits the whole installer; the module must warn+return
    # instead so a missing file fails just this module (F-STAB3).
    mkdir -p "$BATS_TEST_TMPDIR/empty/gui"
    run bash -c '
        set -uo pipefail
        cd "$1"
        DRY_RUN=1 NO_CONFIRM=1 VERBOSE=0 LOG_FILE="" REBOOT_REQUIRED=0
        INSTALLED_FILES="" INSTALLED_PACKAGES=""
        source lib/utils.sh          # real error(): exit 1
        SCRIPT_DIR="$2/empty"        # no GUI sources here
        source modules/gui.sh
        rc=0; module_install || rc=$?
        echo "SURVIVED rc=$rc"       # only prints if module RETURNED
    ' _ "$BATS_TEST_DIRNAME/.." "$BATS_TEST_TMPDIR"
    [ "$status" -eq 0 ]
    [[ "$output" == *"SURVIVED rc=1"* ]]
}
