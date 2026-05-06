#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
else
    SCRIPT_DIR="$(pwd)"
fi

HERMES_ROOT="${HERMES_ROOT:-}"
HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
SKILLHUB_URL_VALUE="${SKILLHUB_URL:-https://skillhub.ingarena.net}"
SKILLHUB_TOKEN_VALUE="${SKILLHUB_TOKEN:-}"
PATCH_REPO="${HERMES_SKILLHUB_PATCH_REPO:-arxeme/hermes-skillhub-patch}"
PATCH_REF="${HERMES_SKILLHUB_PATCH_REF:-main}"
PATCH_RAW_BASE="${HERMES_SKILLHUB_PATCH_RAW_BASE:-https://raw.githubusercontent.com/${PATCH_REPO}/${PATCH_REF}}"
CHECK_ONLY=0
NO_BACKUP=0
RESTORE=0
PATCHER_PATH=""
PATCHER_TMP=""

cleanup() {
    if [[ -n "$PATCHER_TMP" ]]; then
        rm -f "$PATCHER_TMP"
    fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Usage: ./install.sh --hermes-root PATH [options]

Options:
  --hermes-root PATH   Hermes checkout/install root containing tools/skills_hub.py
  --hermes-home PATH   Hermes runtime home (default: ~/.hermes)
  --skillhub-url URL   SkillHub base URL (default: https://skillhub.ingarena.net)
  --token TOKEN        SkillHub API token to store in <HERMES_HOME>/.env
  --repo OWNER/REPO    Patch repo for remote self-install (default: arxeme/hermes-skillhub-patch)
  --ref REF            Patch repo ref (default: main)
  --check              Validate patch applicability without modifying Hermes code
  --no-backup          Do not create tools/skills_hub.py.bak
  --restore            Restore tools/skills_hub.py from backup (.bak)
  -h, --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hermes-root)
            [[ $# -ge 2 ]] || { echo "--hermes-root requires a path" >&2; exit 1; }
            HERMES_ROOT="$2"
            shift 2
            ;;
        --hermes-home)
            [[ $# -ge 2 ]] || { echo "--hermes-home requires a path" >&2; exit 1; }
            HERMES_HOME="$2"
            shift 2
            ;;
        --skillhub-url)
            [[ $# -ge 2 ]] || { echo "--skillhub-url requires a URL" >&2; exit 1; }
            SKILLHUB_URL_VALUE="$2"
            shift 2
            ;;
        --token)
            [[ $# -ge 2 ]] || { echo "--token requires a token" >&2; exit 1; }
            SKILLHUB_TOKEN_VALUE="$2"
            shift 2
            ;;
        --repo)
            [[ $# -ge 2 ]] || { echo "--repo requires OWNER/REPO" >&2; exit 1; }
            PATCH_REPO="$2"
            PATCH_RAW_BASE="https://raw.githubusercontent.com/${PATCH_REPO}/${PATCH_REF}"
            shift 2
            ;;
        --ref)
            [[ $# -ge 2 ]] || { echo "--ref requires a ref" >&2; exit 1; }
            PATCH_REF="$2"
            PATCH_RAW_BASE="https://raw.githubusercontent.com/${PATCH_REPO}/${PATCH_REF}"
            shift 2
            ;;
        --check)
            CHECK_ONLY=1
            shift
            ;;
        --no-backup)
            NO_BACKUP=1
            shift
            ;;
        --restore)
            RESTORE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$HERMES_ROOT" ]]; then
    if [[ -f "tools/skills_hub.py" ]]; then
        HERMES_ROOT="$(pwd)"
    else
        echo "--hermes-root is required unless run from a Hermes root" >&2
        exit 1
    fi
fi

python_cmd() {
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
    elif command -v python >/dev/null 2>&1; then
        echo "python"
    else
        echo "python3"
    fi
}

quote_env_value() {
    local py
    py="$(python_cmd)"
    "$py" -c "import sys,shlex; sys.stdout.write(shlex.quote(sys.argv[1]))" "$1"
}

upsert_env_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    local tmp="${env_file}.tmp"
    local quoted

    [[ -n "$value" ]] || return 0
    quoted="$(quote_env_value "$value")"

    mkdir -p "$(dirname "$env_file")"
    touch "$env_file"
    chmod 600 "$env_file"

    if grep -qE "^${key}=" "$env_file"; then
        awk -v key="$key" -v quoted="$quoted" '
            $0 ~ "^" key "=" {
                print key "=" quoted
                next
            }
            { print }
        ' "$env_file" > "$tmp"
    else
        cp "$env_file" "$tmp"
        printf '%s=%s\n' "$key" "$quoted" >> "$tmp"
    fi

    mv "$tmp" "$env_file"
    chmod 600 "$env_file"
}

resolve_patcher() {
    local local_patcher="${SCRIPT_DIR}/scripts/apply_patch.py"

    if [[ -f "$local_patcher" ]]; then
        PATCHER_PATH="$local_patcher"
        return
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "scripts/apply_patch.py not found locally and curl is unavailable." >&2
        echo "Run from a local clone, or install curl for remote one-line installation." >&2
        exit 1
    fi

    PATCHER_TMP="$(mktemp "${TMPDIR:-/tmp}/hermes-skillhub-patcher.XXXXXX.py")"
    if ! curl -fsSL "${PATCH_RAW_BASE}/scripts/apply_patch.py" -o "$PATCHER_TMP"; then
        echo "Failed to download ${PATCH_RAW_BASE}/scripts/apply_patch.py" >&2
        exit 1
    fi
    chmod 0700 "$PATCHER_TMP"
    PATCHER_PATH="$PATCHER_TMP"
}

py="$(python_cmd)"
patch_args=(--hermes-root "$HERMES_ROOT")
if [[ "$CHECK_ONLY" -eq 1 ]]; then
    patch_args+=(--check)
fi
if [[ "$NO_BACKUP" -eq 1 ]]; then
    patch_args+=(--no-backup)
fi
if [[ "$RESTORE" -eq 1 ]]; then
    patch_args+=(--restore)
fi

resolve_patcher
"$py" "$PATCHER_PATH" "${patch_args[@]}"

if [[ "$CHECK_ONLY" -eq 0 && "$RESTORE" -eq 0 ]]; then
    HERMES_ENV_FILE="${HERMES_HOME}/.env"
    upsert_env_value "$HERMES_ENV_FILE" "SKILLHUB_URL" "$SKILLHUB_URL_VALUE"
    upsert_env_value "$HERMES_ENV_FILE" "SKILLHUB_TOKEN" "$SKILLHUB_TOKEN_VALUE"

    echo "Updated ${HERMES_ENV_FILE}:"
    echo "  SKILLHUB_URL=${SKILLHUB_URL_VALUE}"
    if [[ -n "$SKILLHUB_TOKEN_VALUE" ]]; then
        echo "  SKILLHUB_TOKEN=<set>"
    else
        echo "  SKILLHUB_TOKEN=<unchanged or empty>"
    fi
fi
