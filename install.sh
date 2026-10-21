#!/usr/bin/env bash
# Pasang Sedut untuk user semasa (tiada sudo).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

missing=()
for b in aria2c yt-dlp ffmpeg; do command -v "$b" >/dev/null || missing+=("$b"); done
/usr/bin/python3 -c "import PySide6" 2>/dev/null || missing+=("pyside6")
if ((${#missing[@]})); then
  echo "Belum dipasang: ${missing[*]}"
  echo "Jalankan: sudo pacman -S --needed pyside6 yt-dlp aria2 ffmpeg"
  exit 1
fi

chmod +x "$DIR/sedut.py"
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf "$DIR/sedut.py" ~/.local/bin/sedut

cat > ~/.local/share/applications/sedut.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Sedut
GenericName=Download Manager
Comment=Paste link, kesan & muat turun fail/video
Exec=$HOME/.local/bin/sedut %u
Icon=folder-download
Terminal=false
Categories=Network;FileTransfer;Qt;
MimeType=x-scheme-handler/sedut;
StartupWMClass=sedut
EOF
update-desktop-database ~/.local/share/applications 2>/dev/null || true

# --- Native messaging host: extension Chrome "Video Grabber" -> Sedut
EXT_ID="mjdkcacdjpnnidoahofhfhgajkomcmmc"   # tetap, dari "key" dalam manifest.json extension
chmod +x "$DIR/sedut_host.py"
for d in ~/.config/google-chrome ~/.config/chromium ~/.config/BraveSoftware/Brave-Browser; do
  [[ "$d" == *google-chrome || -d "$d" ]] || continue
  mkdir -p "$d/NativeMessagingHosts"
  cat > "$d/NativeMessagingHosts/com.sedut.host.json" <<EOF
{
  "name": "com.sedut.host",
  "description": "Sedut download manager",
  "path": "$DIR/sedut_host.py",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXT_ID/"]
}
EOF
  echo "Native host didaftar: $d/NativeMessagingHosts/com.sedut.host.json"
done
echo "Siap. Cari 'Sedut' dalam menu aplikasi, atau taip: sedut"
