#!/usr/bin/env bash

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_OWNER="richardbored"
GITHUB_REPOSITORY="ai-code-review"
GITHUB_BRANCH="main"
SOURCE_FILE="ai_code_review.py"
COMMAND_NAME="ai-code-review"

DOWNLOAD_URL="https://raw.githubusercontent.com/${GITHUB_OWNER}/${GITHUB_REPOSITORY}/${GITHUB_BRANCH}/${SOURCE_FILE}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info() {
    printf '%s\n' "$*"
}

error() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

download_file() {
    local url="$1"
    local destination="$2"

    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error \
            "$url" \
            --output "$destination"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet "$url" --output-document="$destination"
    else
        error "curl or wget is required."
    fi
}

add_unix_path() {
    local bin_dir="$1"
    local shell_name
    local shell_config
    local path_line

    shell_name="$(basename "${SHELL:-}")"
    path_line="export PATH=\"${bin_dir}:\$PATH\""

    case "$shell_name" in
        zsh)
            shell_config="$HOME/.zshrc"
            ;;
        bash)
            if [[ "$(uname -s)" == "Darwin" ]]; then
                shell_config="$HOME/.bash_profile"
            else
                shell_config="$HOME/.bashrc"
            fi
            ;;
        *)
            shell_config="$HOME/.profile"
            ;;
    esac

    touch "$shell_config"

    if ! grep -Fqx "$path_line" "$shell_config"; then
        {
            printf '\n'
            printf '# AI Code Review\n'
            printf '%s\n' "$path_line"
        } >> "$shell_config"

        info "Added $bin_dir to PATH in $shell_config"
    fi
}

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

case "$(uname -s)" in
    Darwin|Linux)
        PLATFORM="unix"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        PLATFORM="windows"
        ;;
    *)
        error "Unsupported operating system: $(uname -s)"
        ;;
esac

# ---------------------------------------------------------------------------
# Unix installation
# ---------------------------------------------------------------------------

install_unix() {
    local install_dir="$HOME/.local/share/ai-code-review"
    local bin_dir="$HOME/.local/bin"
    local script_path="$install_dir/$SOURCE_FILE"
    local launcher_path="$bin_dir/$COMMAND_NAME"

    mkdir -p "$install_dir" "$bin_dir"

    info "Downloading AI Code Review..."
    download_file "$DOWNLOAD_URL" "$script_path"

    chmod 755 "$script_path"

    cat > "$launcher_path" <<EOF
#!/bin/sh
exec python3 "$script_path" "\$@"
EOF

    chmod 755 "$launcher_path"

    add_unix_path "$bin_dir"

    info
    info "AI Code Review was installed successfully."
    info "Command: $COMMAND_NAME"
    info
    info "Restart your terminal or run:"
    info "  export PATH=\"$bin_dir:\$PATH\""
}

# ---------------------------------------------------------------------------
# Windows installation through Git Bash/MSYS2
# ---------------------------------------------------------------------------

install_windows() {
    command -v powershell.exe >/dev/null 2>&1 ||
        error "PowerShell is required for Windows installation."

    local local_app_data
    local install_dir
    local bin_dir
    local script_path
    local cmd_path
    local windows_script_path
    local windows_bin_dir

    local_app_data="$(
        powershell.exe -NoProfile -Command \
            '[Environment]::GetFolderPath("LocalApplicationData")' |
            tr -d '\r'
    )"

    [[ -n "$local_app_data" ]] ||
        error "Could not determine the Windows Local AppData directory."

    if command -v cygpath >/dev/null 2>&1; then
        install_dir="$(cygpath -u "$local_app_data")/AI-Code-Review"
        windows_script_path="$local_app_data\\AI-Code-Review\\$SOURCE_FILE"
    else
        error "cygpath is required when installing from Git Bash or MSYS2."
    fi

    bin_dir="$install_dir/bin"
    script_path="$install_dir/$SOURCE_FILE"
    cmd_path="$bin_dir/$COMMAND_NAME.cmd"
    windows_bin_dir="$local_app_data\\AI-Code-Review\\bin"

    mkdir -p "$install_dir" "$bin_dir"

    info "Downloading AI Code Review..."
    download_file "$DOWNLOAD_URL" "$script_path"

    cat > "$cmd_path" <<EOF
@echo off
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 "$windows_script_path" %*
) else (
    python "$windows_script_path" %*
)
EOF

    WINDOWS_BIN_DIR="$windows_bin_dir" powershell.exe -NoProfile -Command '
        $newDirectory = $env:WINDOWS_BIN_DIR
        $currentPath = [Environment]::GetEnvironmentVariable(
            "Path",
            "User"
        )

        $entries = @(
            $currentPath -split ";" |
            Where-Object { $_ -ne "" }
        )

        if ($entries -notcontains $newDirectory) {
            $updatedPath = (
                $entries + $newDirectory |
                Select-Object -Unique
            ) -join ";"

            [Environment]::SetEnvironmentVariable(
                "Path",
                $updatedPath,
                "User"
            )
        }
    '

    info
    info "AI Code Review was installed successfully."
    info "Command: $COMMAND_NAME"
    info
    info "Close and reopen your terminal before using the command."
}

# ---------------------------------------------------------------------------
# Run installer
# ---------------------------------------------------------------------------

if [[ "$PLATFORM" == "windows" ]]; then
    install_windows
else
    install_unix
fi