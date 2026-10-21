Sedut — download manager ringkas untuk CachyOS / KDE Plasma (PySide6)

Pasang:   sudo pacman -S --needed pyside6 yt-dlp aria2 ffmpeg && ./install.sh
Jalan:    sedut            (atau cari "Sedut" dalam menu)
          sedut <url>      (terus kesan)

Guna: paste link dalam kotak atas -> Sedut kesan sendiri (0.5s) -> pilih kualiti/folder -> Muat turun.
  Fail terus  -> aria2c, 8 sambungan, boleh Jeda/Sambung
  Video/HLS   -> yt-dlp (+ffmpeg gabung video+audio jadi mp4, atau MP3)
  YouTube/FB minta log masuk -> tanda "Guna cookies Chrome"

Folder: ~/Downloads/Sedut/{Video,Muzik,Dokumen,Program,Mampatan,Gambar,Lain}
Senarai disimpan: ~/.local/share/sedut/downloads.json
