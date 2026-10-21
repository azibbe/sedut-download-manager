Video Grabber — Chrome extension (Manifest V3)

Cara pasang
  1. Buka chrome://extensions
  2. Hidupkan "Developer mode" (atas kanan)
  3. Klik "Load unpacked" -> pilih folder ini (video-grabber)
  4. Pin ikon merah pada toolbar

Cara guna
  - Buka laman yang ada video, MAIN video tu sekejap (supaya stream dikesan dari rangkaian).
  - Lencana merah pada ikon = bilangan video dikesan dalam tab tu.
  - Klik ikon -> "Muat turun".
      MP4/WebM/MOV  -> terus ke folder Downloads.
      HLS (.m3u8)   -> pilih kualiti -> segmen dimuat turun & digabung -> .ts atau .mp4.
      DASH (.mpd)   -> belum disokong; "Salin URL" dan guna yt-dlp/ffmpeg.

Cara kesan
  - Rangkaian: webRequest tengok Content-Type video/* , HLS, DASH, atau sambungan .mp4/.webm/.m3u8 dll.
    (segmen .ts/.m4s diabaikan supaya senarai tak semak)
  - DOM: <video>, <source>, meta og:video, pautan <a> ke fail video.

Had (jujur)
  - Video dilindungi DRM (Netflix, Disney+, Spotify, dsb. — Widevine/FairPlay/SAMPLE-AES) TIDAK disokong, sengaja.
  - YouTube / laman MSE yang potong video kepada range kecil: tak dapat fail penuh. Guna yt-dlp.
  - HLS dengan audio berasingan: dapat 2 fail (video + audio). Gabung:
      ffmpeg -i "x (video).mp4" -i "x (audio).m4a" -c copy out.mp4
  - HLS digabung dalam RAM — video sangat panjang (berjam, >2GB) mungkin gagal.
  - Siaran langsung: hanya tetingkap playlist semasa.
  - Hormati hak cipta & terma laman — guna untuk kandungan yang anda berhak simpan.

Fail
  manifest.json   konfigurasi MV3
  background.js   service worker: pengesanan rangkaian, senarai per tab, muat turun, peraturan Referer
  content.js      imbas DOM
  hls.js          parser M3U8 (master/media, AES-128, BYTERANGE, EXT-X-MAP)
  offscreen.*     muat turun + gabung segmen HLS, nyahsulit AES-128 (WebCrypto)
  popup.*         UI
