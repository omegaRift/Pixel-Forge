#!/usr/bin/env bash
# Installs (or updates) Pixel Forge on Linux / a Steam Deck, for the current user.
#
#   One line in Konsole:
#
#     curl -fsSL https://raw.githubusercontent.com/omegaRift/Pixel-Forge/main/install.sh | bash
#
# It downloads the newest release's one-file app (Python, Tk, Pillow, the AI
# engine and the app's font are inside it: nothing else needs installing),
# puts it in your home folder, and adds Pixel Forge to the application menu
# and the desktop. Running it again updates. Nothing is installed
# system-wide, so SteamOS updates don't remove it.
#
#   ... | PF_AI=1 bash               also fetch the AI background-removal model now (179 MB);
#                                    without this the app offers it the first time AI is used
#   ... | PF_TOKEN=<token> bash      for a private copy of the repository (PF_REPO=owner/name):
#                                    a GitHub token that can read its Contents; it is never saved
#
#   bash ~/.local/share/PixelForge/install.sh --uninstall
#                                    remove what this installed (your settings and palettes stay)
#   PF_FILE=/path/to/PixelForge-linux-x86_64 bash install.sh
#                                    install a file you already downloaded (no token needed)

set -euo pipefail

REPO="${PF_REPO:-omegaRift/Pixel-Forge}"
ASSET="PixelForge-linux-x86_64"
API="https://api.github.com/repos/$REPO"

APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/PixelForge"
APP="$APP_DIR/PixelForge"
ICON="$APP_DIR/pixel-forge.png"
MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
MENU_ENTRY="$MENU_DIR/pixel-forge.desktop"
BIN_LINK="$HOME/.local/bin/pixel-forge"
DESKTOP_DIR="$(command -v xdg-user-dir >/dev/null 2>&1 && xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP_ENTRY="$DESKTOP_DIR/Pixel Forge.desktop"
TOKEN="${PF_TOKEN:-${GITHUB_TOKEN:-}}"

say()  { printf '[Pixel Forge] %s\n' "$*"; }
fail() { printf '[Pixel Forge] %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$APP" "$ICON" "$APP_DIR/version" "$APP_DIR/install.sh" "$MENU_ENTRY" "$DESKTOP_ENTRY" "$BIN_LINK"
    rm -f "$APP_DIR/models/isnet-general-use.onnx" "$APP_DIR/models/isnet-general-use.onnx.part"   # the AI model, if downloaded
    rmdir "$APP_DIR/models" 2>/dev/null || true
    rmdir "$APP_DIR" 2>/dev/null || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU_DIR" >/dev/null 2>&1 || true
    say "Removed. Your settings and palettes are still in ${XDG_CONFIG_HOME:-$HOME/.config}/PixelForge."
    exit 0
fi

[ "$(uname -s)" = "Linux" ] || fail "This installer is for Linux (a Steam Deck in Desktop Mode)."
[ "$(uname -m)" = "x86_64" ] || fail "Pixel Forge's Linux build is for x86_64 PCs; this is $(uname -m)."
command -v curl >/dev/null 2>&1 || fail "curl is needed for the download, and wasn't found."

# curl with the token, if there is one (a public repository needs none)
gh_curl() {
    if [ -n "$TOKEN" ]; then
        curl -fsSL -H "Authorization: Bearer $TOKEN" -H "X-GitHub-Api-Version: 2022-11-28" "$@"
    else
        curl -fsSL "$@"
    fi
}

mkdir -p "$APP_DIR" "$MENU_DIR" "$(dirname "$BIN_LINK")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [ -n "${PF_FILE:-}" ]; then
    [ -f "$PF_FILE" ] || fail "PF_FILE is set, but there's no file at: $PF_FILE"
    cp "$PF_FILE" "$tmp/app"
    version="from $(basename "$PF_FILE")"
else
    say "Looking up the newest release of $REPO..."
    if ! release="$(gh_curl -H "Accept: application/vnd.github+json" "$API/releases/latest")"; then
        if [ -z "$TOKEN" ]; then
            fail "Couldn't read the releases. Check the internet connection and try again. (If $REPO is private, set PF_TOKEN to a GitHub token that can read it.)"
        fi
        fail "Couldn't read the releases. Check the token: it needs read access to the Contents of $REPO, and must not have expired."
    fi
    # One field per line, however the JSON was laid out (no jq needed).
    release="$(printf '%s\n' "$release" | tr ',{' '\n\n')"
    version="$(printf '%s\n' "$release" | awk -F'"' '/"tag_name":/ { print $4; exit }')"
    # In the release's JSON each file has its "url" (.../releases/assets/<id>) before its "name".
    asset_url="$(printf '%s\n' "$release" | awk -F'"' -v want="$ASSET" '
        /"url": *"[^"]*\/releases\/assets\/[0-9]+"/ { url = $4 }
        /"name":/ && $4 == want { print url; exit }')"
    [ -n "$asset_url" ] || fail "Release ${version:-?} has no file called $ASSET."
    say "Downloading Pixel Forge $version..."
    gh_curl -H "Accept: application/octet-stream" -o "$tmp/app" "$asset_url" || fail "The download failed. Try again."
fi

# A Linux program starts with the bytes 7f 'E' 'L' 'F': anything else is an error page, not the app.
[ "$(head -c 4 "$tmp/app" | od -An -c | tr -d ' \n')" = "177ELF" ] || fail "What was downloaded isn't the app. Nothing was changed."
chmod +x "$tmp/app"
mv -f "$tmp/app" "$APP"
printf '%s\n' "$version" > "$APP_DIR/version"
ln -sf "$APP" "$BIN_LINK"

# Keep a copy of this installer next to the app, for removing it later.
if [ -f "${BASH_SOURCE[0]:-}" ]; then
    cp -f "${BASH_SOURCE[0]}" "$APP_DIR/install.sh" 2>/dev/null || true
elif [ -z "${PF_FILE:-}" ]; then
    gh_curl -H "Accept: application/vnd.github.raw" -o "$APP_DIR/install.sh" "$API/contents/install.sh" 2>/dev/null || true
fi

# The icon (the anvil). Without it the entry still works, with a generic icon.
icon_line="Icon=applications-graphics"
if [ -z "${PF_FILE:-}" ] && gh_curl -H "Accept: application/vnd.github.raw" -o "$tmp/icon.png" "$API/contents/Forge.png" 2>/dev/null; then
    mv -f "$tmp/icon.png" "$ICON"
fi
[ -f "$ICON" ] && icon_line="Icon=$ICON"

entry() {
    cat <<EOF
[Desktop Entry]
Type=Application
Name=Pixel Forge
GenericName=Pixel Art Editor
Comment=Turn pictures into pixel-art sprites and edit them
Exec="$APP" %f
$icon_line
Terminal=false
Categories=Graphics;2DGraphics;RasterGraphics;
MimeType=image/png;image/jpeg;
EOF
}
entry > "$MENU_ENTRY"
chmod +x "$MENU_ENTRY"
if [ -d "$DESKTOP_DIR" ]; then
    entry > "$DESKTOP_ENTRY"
    chmod +x "$DESKTOP_ENTRY"   # (KDE only runs desktop icons marked executable)
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU_DIR" >/dev/null 2>&1 || true

say "Installed Pixel Forge $version."

# The AI background-removal model: big, so only now if asked for (PF_AI=1).
# The app downloads it itself (--download-ai-model), and offers to on first use otherwise.
if [ "${PF_AI:-}" = "1" ]; then
    if "$APP" --download-ai-model; then
        say "AI background removal is ready (it works without internet from now on)."
    else
        say "The AI model wasn't downloaded. Pixel Forge will offer it again the first time you choose AI removal."
    fi
fi
say "  Start it:      the Pixel Forge icon on the desktop, or the application menu under Graphics"
say "  Gaming Mode:   in Steam (Desktop Mode): Games > Add a Non-Steam Game > Pixel Forge"
say "  Update later:  Pixel Forge updates itself, and tells you when it has (or run this install command again)"
say "  Remove it:     bash \"$APP_DIR/install.sh\" --uninstall    (settings and palettes are kept)"
