#!/usr/bin/env bash
# Install manifest tracking (Bash)
# Tracks what modules were installed for clean uninstallation.
#
# The manifest lives at /var/lib/archer/install-manifest.json (root-owned, 0644)
# so that install (run as user with sudo) and uninstall (often run via sudo,
# where $HOME=/root) read and write the same path. It also stops local users
# tampering with manifest entries that uninstall.sh later sources.

MANIFEST_DIR="/var/lib/archer"
MANIFEST_FILE="$MANIFEST_DIR/install-manifest.json"

# Legacy locations migrated on first install. Both real-user $HOME and /root
# are checked because earlier versions wrote under whichever HOME was set when
# install.sh ran (sometimes via sudo). DAMX is the project's prior name.
_LEGACY_MANIFEST_CANDIDATES=(
    "${HOME:-}/.local/share/archer/install-manifest.json"
    "${HOME:-}/.local/share/damx/install-manifest.json"
    "/root/.local/share/archer/install-manifest.json"
    "/root/.local/share/damx/install-manifest.json"
)

# Move any legacy manifest into the new location. Idempotent. Run once near
# the start of install.sh / uninstall.sh.
migrate_legacy_manifest() {
    [[ -f "$MANIFEST_FILE" ]] && return 0

    local src
    for src in "${_LEGACY_MANIFEST_CANDIDATES[@]}"; do
        [[ -z "$src" ]] && continue
        [[ -f "$src" ]] || continue

        log "Migrating legacy manifest $src -> $MANIFEST_FILE"
        run_sudo mkdir -p "$MANIFEST_DIR"
        run_sudo chmod 755 "$MANIFEST_DIR"
        run_sudo cp "$src" "$MANIFEST_FILE"
        run_sudo chmod 644 "$MANIFEST_FILE"

        # Older DAMX manifests used the module ID "core-damx" for what is now "driver".
        if has_cmd sed; then
            run_sudo sed -i 's/"core-damx"/"driver"/g' "$MANIFEST_FILE"
        fi

        # Best-effort cleanup of the legacy file (only if writable by us).
        if [[ -w "$src" ]]; then
            rm -f "$src"
        fi
        return 0
    done
    return 0
}

# Write the install manifest after installation.
# Usage: write_manifest "driver battery gpu" "file1 file2" "linuwu-sense/1.0" "envycontrol tlp"
write_manifest() {
    local modules_str="$1"
    local files_str="$2"
    local dkms_str="$3"
    local packages_str="$4"

    run_sudo mkdir -p "$MANIFEST_DIR"
    run_sudo chmod 755 "$MANIFEST_DIR"

    local tmpfile
    tmpfile="$(mktemp)"

    if has_cmd jq; then
        jq -n \
            --arg date "$(date -Iseconds)" \
            --arg version "$INSTALLER_VERSION" \
            --arg model "$ACER_PRODUCT_NAME" \
            --arg family "$MODEL_FAMILY" \
            --arg kernel "$KERNEL_VERSION" \
            --arg modules "$modules_str" \
            --arg files "$files_str" \
            --arg dkms "$dkms_str" \
            --arg packages "$packages_str" \
            '{
                install_date: $date,
                installer_version: $version,
                acer_model: $model,
                model_family: $family,
                kernel_version: $kernel,
                modules_installed: ($modules | split(" ") | map(select(. != ""))),
                files_created: ($files | split(" ") | map(select(. != ""))),
                dkms_modules: ($dkms | split(" ") | map(select(. != ""))),
                packages_installed: ($packages | split(" ") | map(select(. != "")))
            }' > "$tmpfile"
    else
        # Python fallback: pass values via environment to prevent injection
        ARCHER_VERSION="$INSTALLER_VERSION" \
        ARCHER_MODEL="$ACER_PRODUCT_NAME" \
        ARCHER_FAMILY="$MODEL_FAMILY" \
        ARCHER_KERNEL="$KERNEL_VERSION" \
        ARCHER_MODULES="$modules_str" \
        ARCHER_FILES="$files_str" \
        ARCHER_DKMS="$dkms_str" \
        ARCHER_PKGS="$packages_str" \
        ARCHER_MANIFEST="$tmpfile" \
        python3 -c "
import json, datetime, os
manifest = {
    'install_date': datetime.datetime.now().isoformat(),
    'installer_version': os.environ['ARCHER_VERSION'],
    'acer_model': os.environ['ARCHER_MODEL'],
    'model_family': os.environ['ARCHER_FAMILY'],
    'kernel_version': os.environ['ARCHER_KERNEL'],
    'modules_installed': os.environ['ARCHER_MODULES'].split(),
    'files_created': os.environ['ARCHER_FILES'].split(),
    'dkms_modules': os.environ['ARCHER_DKMS'].split(),
    'packages_installed': os.environ['ARCHER_PKGS'].split()
}
with open(os.environ['ARCHER_MANIFEST'], 'w') as f:
    json.dump(manifest, f, indent=2)
"
    fi

    run_sudo install -m 0644 "$tmpfile" "$MANIFEST_FILE"
    rm -f "$tmpfile"
    log "Install manifest written to $MANIFEST_FILE"
}

# Read installed modules from manifest. Returns space-separated list of module IDs.
read_manifest_modules() {
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        echo ""
        return 1
    fi
    if has_cmd jq; then
        jq -r '.modules_installed // [] | join(" ")' "$MANIFEST_FILE"
    else
        ARCHER_MANIFEST="$MANIFEST_FILE" python3 -c "
import json, os, sys
try:
    with open(os.environ['ARCHER_MANIFEST']) as f:
        data = json.load(f)
except (OSError, json.JSONDecodeError) as e:
    print('', flush=True)
    sys.stderr.write(f'manifest read failed: {e}\n')
    sys.exit(1)
print(' '.join(data.get('modules_installed', [])))
"
    fi
}

# Read a specific field from manifest.
read_manifest_field() {
    local field="$1"
    if [[ ! -f "$MANIFEST_FILE" ]]; then
        echo ""
        return 1
    fi
    if has_cmd jq; then
        jq -r --arg f "$field" '.[$f] // "" | if type == "array" then join(" ") else tostring end' "$MANIFEST_FILE"
    else
        ARCHER_MANIFEST="$MANIFEST_FILE" ARCHER_FIELD="$field" python3 -c "
import json, os, sys
try:
    with open(os.environ['ARCHER_MANIFEST']) as f:
        data = json.load(f)
except (OSError, json.JSONDecodeError) as e:
    print('', flush=True)
    sys.stderr.write(f'manifest read failed: {e}\n')
    sys.exit(1)
val = data.get(os.environ['ARCHER_FIELD'], [])
if isinstance(val, list):
    print(' '.join(val))
else:
    print(val)
"
    fi
}

# Check if manifest exists.
has_manifest() {
    [[ -f "$MANIFEST_FILE" ]]
}

# Remove the manifest file.
remove_manifest() {
    run_sudo rm -f "$MANIFEST_FILE"
}
