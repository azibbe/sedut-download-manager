Video Grabber — Chrome extension (Manifest V3)

Detects videos on any web page and downloads them, or hands them to the Sedut
desktop download manager.

Install
  1. Open chrome://extensions
  2. Turn on "Developer mode" (top right)
  3. Click "Load unpacked" -> select this folder (extension/ in the Sedut repo)
  4. Pin the red icon to the toolbar
  5. (Optional) Run ../install.sh so the "Sedut" buttons and the right-click
     menu can send links to the Sedut desktop app (native messaging).
     The extension ID is fixed (mjdkcacdjpnnidoahofhfhgajkomcmmc) by the "key" in manifest.json.

Usage
  - Open a page with a video and PLAY it briefly (so the stream is detected from the network).
  - The red badge on the icon = number of videos detected in that tab.
  - Click the icon -> "Download".
      MP4/WebM/MOV  -> straight to your Downloads folder.
      HLS (.m3u8)   -> pick a quality -> segments are downloaded & joined -> .ts or .mp4.
      DASH (.mpd)   -> not supported by the extension; press "Sedut" (yt-dlp handles it) or "Copy URL".
  - "Sedut" button on each item, or "Page → Sedut" for YouTube/Facebook/TikTok pages.
  - Right-click menu: "Download with Sedut" (links), "Download this media with Sedut"
    (video/audio), "Send this page to Sedut" (page).

How detection works
  - Network: webRequest looks at Content-Type video/*, HLS, DASH, or extensions like .mp4/.webm/.m3u8.
    (.ts/.m4s segments are ignored so the list stays clean)
  - DOM: <video>, <source>, og:video meta tags, <a> links to video files.

Limits
  - DRM-protected video (Netflix, Disney+, Spotify, etc. — Widevine/FairPlay/SAMPLE-AES) is NOT supported, by design.
  - YouTube / MSE sites that split video into small ranges: no full file. Use "Page → Sedut" (yt-dlp).
  - HLS with separate audio: you get 2 files (video + audio). Merge them with:
      ffmpeg -i "x (video).mp4" -i "x (audio).m4a" -c copy out.mp4
  - HLS is joined in RAM — very long videos (hours, >2 GB) may fail.
  - Live streams: only the current playlist window.
  - Respect copyright and each site's terms — only save content you have the right to keep.

Files
  manifest.json   MV3 configuration
  background.js   service worker: network detection, per-tab lists, downloads, Referer rules, Sedut bridge
  content.js      DOM scan
  hls.js          M3U8 parser (master/media, AES-128, BYTERANGE, EXT-X-MAP)
  offscreen.*     downloads + joins HLS segments, AES-128 decryption (WebCrypto)
  popup.*         UI
