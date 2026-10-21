// content.js — imbas DOM untuk elemen <video>, <source>, og:video & pautan video
(() => {
  if (window.__videoGrabberLoaded) return;
  window.__videoGrabberLoaded = true;

  const VIDEO_LINK = /\.(mp4|webm|mov|m4v|mkv|ogv|m3u8|mpd)(\?|#|$)/i;
  const sent = new Set();
  let timer = null;

  function abs(u) {
    try { return new URL(u, location.href).href; } catch { return null; }
  }

  function scan() {
    const items = [];
    let blobVideos = 0;
    const push = (url, mime, fromVideoTag) => {
      url = url && abs(url);
      if (!url) return;
      if (url.startsWith('blob:') || url.startsWith('mediasource:')) { blobVideos++; return; }
      if (!/^https?:/i.test(url) || sent.has(url)) return;
      sent.add(url);
      items.push({ url, mime: mime || '', fromVideoTag: !!fromVideoTag });
    };

    document.querySelectorAll('video').forEach((v) => {
      push(v.currentSrc || v.src, '', true);
      v.querySelectorAll('source').forEach((s) => push(s.src, s.type, true));
    });
    document.querySelectorAll('meta[property^="og:video"], meta[name^="twitter:player:stream"]').forEach((m) => {
      const c = m.getAttribute('content');
      if (c && VIDEO_LINK.test(c)) push(c, '', false);
    });
    document.querySelectorAll('a[href]').forEach((a) => {
      if (VIDEO_LINK.test(a.href)) push(a.href, '', false);
    });

    if (items.length || blobVideos) {
      chrome.runtime.sendMessage({ type: 'dom-videos', items, blobVideos }).catch(() => {});
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(scan, 800);
  }

  scan();
  new MutationObserver(schedule).observe(document.documentElement, {
    childList: true, subtree: true, attributes: true, attributeFilter: ['src'],
  });
  // video yang tukar sumber semasa main
  document.addEventListener('loadstart', schedule, true);
})();
