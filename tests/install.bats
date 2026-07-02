#!/usr/bin/env bats
# Tests for install.sh — CLI argument parsing and module selection logic
#
# NOTE: lib/utils.sh defines a run() function that overwrites Bats' built-in
# run command (see utils.bats). Never use Bats `run` in this file — capture
# exit status explicitly: `status=0; cmd || status=$?`.

setup() {
    DRY_RUN=0
    NO_CONFIRM=0
    VERBOSE=0
    LOG_FILE=""
    REBOOT_REQUIRED=0
    source "$BATS_TEST_DIRNAME/../lib/utils.sh"
    # Override error() to not exit
    error() { echo "ERROR: $*"; return 1; }
    # Source install.sh (main is guarded, won't execute)
    source "$BATS_TEST_DIRNAME/../install.sh"
}

@test "parse_args sets --all flag" {
    SELECT_ALL_RECOMMENDED=0
    parse_args --all
    [ "$SELECT_ALL_RECOMMENDED" -eq 1 ]
}

@test "parse_args sets --dry-run flag" {
    DRY_RUN=0
    parse_args --dry-run
    [ "$DRY_RUN" -eq 1 ]
}

@test "parse_args sets --verbose flag" {
    VERBOSE=0
    parse_args --verbose
    [ "$VERBOSE" -eq 1 ]
}

@test "parse_args sets --log flag with file" {
    LOG_FILE=""
    parse_args --log /tmp/test.log
    [ "$LOG_FILE" = "/tmp/test.log" ]
}

@test "check_conflicts detects driver+thermal conflict" {
    MODULE_SELECTED=(1 0 0 0 0 0 0 1 0 0 0 0 0)
    ! check_conflicts
}

@test "check_conflicts passes when no conflict" {
    MODULE_SELECTED=(1 1 0 0 0 0 0 0 0 0 0 0 0)
    check_conflicts
}

@test "MODULE_IDS contains all 13 modules" {
    [ "${#MODULE_IDS[@]}" -eq 13 ]
}

@test "MODULE_IDS and MODULE_LABELS have same length" {
    [ "${#MODULE_IDS[@]}" -eq "${#MODULE_LABELS[@]}" ]
}

@test "is_known_module accepts every canonical module ID" {
    local id
    for id in "${MODULE_IDS[@]}"; do
        is_known_module "$id" || { echo "rejected canonical id: $id"; return 1; }
    done
}

@test "is_known_module rejects path-traversal attempts" {
    ! is_known_module "../../tmp/evil"
    ! is_known_module "../etc/x"
    ! is_known_module "/etc/passwd"
    ! is_known_module ".hidden"
    ! is_known_module ""
}

@test "is_known_module rejects shell metacharacters" {
    ! is_known_module "driver;rm -rf /"
    ! is_known_module 'driver$(whoami)'
    ! is_known_module "driver|cat"
    ! is_known_module "driver\`id\`"
}

@test "is_known_module rejects unknown but well-formed IDs" {
    ! is_known_module "unknown"
    ! is_known_module "fakemod"
}

@test "module_index returns correct positions and fails for unknown" {
    [ "$(module_index driver)" = "0" ]
    [ "$(module_index thermal)" = "7" ]
    [ "$(module_index firmware)" = "$(( ${#MODULE_IDS[@]} - 1 ))" ]
    status=0; module_index not-a-module >/dev/null || status=$?
    [ "$status" -ne 0 ]
}

@test "is_module_selected / set_module_selected key off IDs" {
    MODULE_SELECTED=(); for _ in "${MODULE_IDS[@]}"; do MODULE_SELECTED+=(0); done
    set_module_selected driver 1
    is_module_selected driver
    ! is_module_selected thermal
    set_module_selected driver 0
    ! is_module_selected driver
}

@test "conflict detection survives MODULE_IDS reordering" {
    # Simulate a future reorder/insert: driver and thermal no longer at 0/7.
    MODULE_IDS=("gui" "thermal" "battery" "driver")
    MODULE_SELECTED=(0 0 0 0)
    set_module_selected driver 1
    set_module_selected thermal 1
    ! check_conflicts
    set_module_selected thermal 0
    check_conflicts
}

@test "verify_modules returns non-zero when a module fails verification" {
    # Select only the first module and force its verify to fail.
    MODULE_SELECTED=(); for _ in "${MODULE_IDS[@]}"; do MODULE_SELECTED+=(0); done
    MODULE_SELECTED[0]=1
    FAILED_MODULES=()
    # Stub sourcing + a failing verify (avoid touching the real module).
    source() { :; }
    module_verify() { return 1; }
    # Call in the current shell (not a subshell) so VERIFY_PASSED/VERIFY_TOTAL
    # side effects are observable; guard the expected failure from errexit.
    status=0; verify_modules || status=$?
    [ "$status" -ne 0 ]
    [ "$VERIFY_PASSED" -eq 0 ]
    [ "$VERIFY_TOTAL" -eq 1 ]
}

@test "verify_modules skips modules that failed to install" {
    MODULE_SELECTED=(); for _ in "${MODULE_IDS[@]}"; do MODULE_SELECTED+=(0); done
    MODULE_SELECTED[0]=1
    FAILED_MODULES=("${MODULE_IDS[0]}")
    source() { :; }
    module_verify() { return 0; }
    verify_modules
    [ "$VERIFY_TOTAL" -eq 0 ]
}
