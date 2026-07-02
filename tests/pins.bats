#!/usr/bin/env bats
# Static lint: third-party code built/installed as root must be pinned to a
# reviewed commit from lib/pins.sh (F-SEC2). Pure greps — nothing is sourced,
# so bats' own run helper is usable here.

MODULES_DIR="$BATS_TEST_DIRNAME/../modules"
PINS_FILE="$BATS_TEST_DIRNAME/../lib/pins.sh"

@test "every git clone in modules/ has a matching pinned checkout in the same file" {
    local f clones checkouts
    for f in "$MODULES_DIR"/*.sh; do
        clones=$(grep -c '^[^#]*git clone' "$f") || true
        [ "$clones" -eq 0 ] && continue
        checkouts=$(grep -c 'git -C .* checkout --detach "\$ARCHER_PIN_' "$f") || true
        if [ "$checkouts" -ne "$clones" ]; then
            echo "$f: $clones clone(s) but $checkouts pinned checkout(s)" >&2
            return 1
        fi
    done
}

@test "pins.sh git pins are full 40-hex commit SHAs (not branches or tags)" {
    local line v count=0
    while IFS= read -r line; do
        v="${line#*=}"; v="${v%%#*}"; v="${v//\"/}"; v="${v// /}"
        if ! [[ "$v" =~ ^[0-9a-f]{40}$ ]]; then
            echo "not a 40-hex commit SHA: $line" >&2
            return 1
        fi
        count=$((count + 1))
    done < <(grep -E '^ARCHER_PIN_(LINUWU_SENSE|ACER_WMI_BATTERY|NSV_AUR|ENVYCONTROL)=' "$PINS_FILE")
    [ "$count" -eq 4 ]
}

@test "pip installs in modules/ are pinned to a commit from pins.sh" {
    local unpinned
    unpinned=$(grep -rn '^[^#]*\bpip install' "$MODULES_DIR" | grep -v '@\${ARCHER_PIN_') || true
    if [ -n "$unpinned" ]; then
        echo "unpinned pip install: $unpinned" >&2
        return 1
    fi
}
