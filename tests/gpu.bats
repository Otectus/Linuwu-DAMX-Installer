#!/usr/bin/env bats
# Tests for modules/gpu.sh — mkinitcpio shim lifecycle (F-STAB1).
#
# The shim swap must survive interrupts: a no-op /usr/local/bin/mkinitcpio
# left behind silently breaks every future initramfs rebuild. These tests
# exercise the trap-protected window in throwaway bash children so signals
# land on the child, not on bats, and so bats' own `run` helper stays
# usable here (this file never sources lib/utils.sh in the bats process —
# its run() would shadow the builtin, see utils.bats).

# Common child preamble: source the product code with sudo dropped and the
# shim path redirected into the test tmpdir.
_child_preamble='
    set -euo pipefail
    cd "$1"
    DRY_RUN=0 NO_CONFIRM=1 VERBOSE=0 LOG_FILE="" REBOOT_REQUIRED=0
    source lib/utils.sh
    run_sudo() { "$@"; }
    source modules/gpu.sh
    _GPU_SHIM_PATH="$2/mkinitcpio"
'

@test "gpu shim: normal window swaps in shim, restores wrapper, disarms traps" {
    run bash -c "$_child_preamble"'
        printf "#!/bin/sh\necho original\n" > "$_GPU_SHIM_PATH"
        _gpu_shim_install
        grep -q "exit 0" "$_GPU_SHIM_PATH" || { echo "shim not in place"; exit 1; }
        [ -f "$_GPU_SHIM_PATH.archer-bak" ] || { echo "backup missing"; exit 1; }
        _gpu_shim_cleanup
        grep -q "original" "$_GPU_SHIM_PATH" || { echo "wrapper not restored"; exit 1; }
        [ ! -f "$_GPU_SHIM_PATH.archer-bak" ] || { echo "stray backup"; exit 1; }
        [ -z "$(trap -p EXIT INT TERM)" ] || { echo "traps still armed"; exit 1; }
        echo OK
    ' _ "$BATS_TEST_DIRNAME/.." "$BATS_TEST_TMPDIR"
    [ "$status" -eq 0 ]
    [[ "$output" == *"OK"* ]]
}

@test "gpu shim: SIGTERM mid-window restores wrapper and re-raises the signal" {
    printf '#!/bin/sh\necho original\n' > "$BATS_TEST_TMPDIR/mkinitcpio"
    run bash -c "$_child_preamble"'
        _gpu_shim_install
        kill -TERM "$$"     # simulate interrupt while envycontrol runs
        echo "NOT-REACHED"  # must never print: signal must not be swallowed
    ' _ "$BATS_TEST_DIRNAME/.." "$BATS_TEST_TMPDIR"
    [ "$status" -eq 143 ]   # 128+SIGTERM: killed by the re-raised signal
    [[ "$output" != *"NOT-REACHED"* ]]
    grep -q "original" "$BATS_TEST_TMPDIR/mkinitcpio"
    [ ! -f "$BATS_TEST_TMPDIR/mkinitcpio.archer-bak" ]
}

@test "gpu shim: SIGTERM with no pre-existing wrapper removes shim cleanly" {
    run bash -c "$_child_preamble"'
        _gpu_shim_install
        kill -TERM "$$"
        echo "NOT-REACHED"
    ' _ "$BATS_TEST_DIRNAME/.." "$BATS_TEST_TMPDIR"
    [ "$status" -eq 143 ]
    [[ "$output" != *"NOT-REACHED"* ]]
    [ ! -f "$BATS_TEST_TMPDIR/mkinitcpio" ]
    [ ! -f "$BATS_TEST_TMPDIR/mkinitcpio.archer-bak" ]
}
