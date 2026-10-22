// background.js — service worker: kesan video, urus muat turun
import { parseM3U8 } from './hls.js';

const FILE_EXT = ['mp4', 'webm', 'mov', 'm4v', 'mkv', 'ogv', 'flv', 'avi', '3gp'];
const SKIP_EXT = ['ts', 'm4s', 'aac', 'vtt', 'key'];
const HLS_MIME = ['application/vnd.apple.mpegurl', 'application/x-mpegurl', 'audio/mpegurl', 'audio/x-mpegurl'];

// ---------- Storan per tab (storage.session supaya tahan SW mati) ----------
const cache = new Map(); // tabId -> {items:{}, blobVideos:0}
let writeChain = Promise.resolve();

const loading = new Map(); // tabId -> Promise (elak race bila banyak event serentak)
async function getTab(tabId) {
  if (cache.has(tabId)) return cache.get(tabId);
  if (!loading.has(tabId)) {
    const key = `tab_${tabId}`;
    loading.set(tabId, chrome.storage.session.get(key).then((r) => {
      if (!cache.has(tabId)) cache.set(tabId, r[key] || { items: {}, blobVideos: 0 });
      loading.delete(tabId);
      return cache.get(tabId);
    }));
  }
  return loading.get(tabId);
}

function persist(tabId) {
  const data = cache.get(tabId);
  writeChain = writeChain.then(() =>
    data ? chrome.storage.session.set({ [`tab_${tabId}`]: data }) : chrome.storage.session.remove(`tab_${tabId}`)
  ).catch(() => {});
  updateBadge(tabId);
}

function updateBadge(tabId) {
  const data = cache.get(tabId);
  const n = data ? Object.keys(data.items).length : 0;
  chrome.action.setBadgeText({ tabId, text: n ? String(n) : '' }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ tabId, color: '#e11d48' }).catch(() => {});
}

async function clearTab(tabId) {
  cache.set(tabId, { items: {}, blobVideos: 0 });
  persist(tabId);
}

async function addItem(tabId, item) {
  if (tabId < 0 || !/^https?:/i.test(item.url)) return;
  const data = await getTab(tabId);
  const prev = data.items[item.url];
  if (prev) {
    // gabung maklumat: kekalkan saiz terbesar & mime yang diketahui
    prev.size = Math.max(prev.size || 0, item.size || 0) || null;
    prev.mime ||= item.mime;
    prev.kind = prev.kind === 'unknown' ? item.kind : prev.kind;
    if (item.source === 'network') prev.source = 'network';
  } else {
    data.items[item.url] = { ...item, ts: Date.now() };
  }
  persist(tabId);
}

// ---------- Klasifikasi ----------
function extOf(url) {
  try {
    const p = new URL(url).pathname.toLowerCase();
    const m = p.match(/\.([a-z0-9]{2,5})$/);
    return m ? m[1] : '';
  } catch { return ''; }
}

function classify(url, mime) {
  mime = (mime || '').toLowerCase().split(';')[0].trim();
  const ext = extOf(url);
  if (SKIP_EXT.includes(ext) || mime === 'video/mp2t' || mime === 'video/iso.segment') return null;
  if (HLS_MIME.includes(mime) || ext === 'm3u8') return { kind: 'hls', ext: 'm3u8' };
  if (mime === 'application/dash+xml' || ext === 'mpd') return { kind: 'dash', ext: 'mpd' };
  if (mime.startsWith('video/')) return { kind: 'file', ext: FILE_EXT.includes(ext) ? ext : (mime.split('/')[1] || 'mp4').replace('quicktime', 'mov').replace('x-matroska', 'mkv') };
  if (FILE_EXT.includes(ext)) return { kind: 'file', ext };
  return null;
}

function header(headers, name) {
  const h = headers?.find((x) => x.name.toLowerCase() === name);
  return h ? h.value : '';
}

function sizeFromHeaders(headers) {
  const cr = header(headers, 'content-range'); // bytes 0-1/12345
  const total = cr.match(/\/(\d+)\s*$/);
  if (total) return parseInt(total[1], 10);
  const cl = parseInt(header(headers, 'content-length'), 10);
  return Number.isFinite(cl) ? cl : null;
}

// ---------- Pengesanan rangkaian ----------
chrome.webRequest.onBeforeRequest.addListener(
  (d) => { if (d.tabId >= 0 && d.frameId === 0) clearTab(d.tabId); },
  { urls: ['<all_urls>'], types: ['main_frame'] }
);

chrome.webRequest.onHeadersReceived.addListener(
  (d) => {
    if (d.tabId < 0 || d.statusCode >= 400) return;
    const mime = header(d.responseHeaders, 'content-type');
    const c = classify(d.url, mime);
    if (!c) return;
    const size = sizeFromHeaders(d.responseHeaders);
    // segmen kecil (cth. potongan MSE) bukan video penuh — abaikan fail < 50KB tanpa sambungan dikenali
    if (c.kind === 'file' && size && size < 50 * 1024 && !FILE_EXT.includes(extOf(d.url))) return;
    addItem(d.tabId, { url: d.url, kind: c.kind, ext: c.ext, mime: mime.split(';')[0], size, source: 'network' });
  },
  { urls: ['<all_urls>'], types: ['media', 'xmlhttprequest', 'other', 'object'] },
  ['responseHeaders']
);

chrome.tabs.onRemoved.addListener((tabId) => {
  cache.delete(tabId);
  chrome.storage.session.remove(`tab_${tabId}`);
});

// ---------- Referer: sesetengah CDN tolak permintaan tanpa Referer laman asal ----------
let ruleSeq = 1000;
async function addRefererRule(referer, condition) {
  if (!referer || !/^https?:/.test(referer)) return null;
  const id = ruleSeq++;
  await chrome.declarativeNetRequest.updateSessionRules({
    addRules: [{
      id,
      priority: 1,
      action: { type: 'modifyHeaders', requestHeaders: [{ header: 'referer', operation: 'set', value: referer }] },
      condition: { ...condition, tabIds: [chrome.tabs.TAB_ID_NONE] },
    }],
  });
  return id;
}
function removeRule(id) {
  if (id) chrome.declarativeNetRequest.updateSessionRules({ removeRuleIds: [id] }).catch(() => {});
}

// ---------- Nama fail ----------
function safeName(title, ext) {
  let base = (title || 'video').replace(/[\\/:*?"<>|\x00-\x1f~]/g, '_').replace(/\s+/g, ' ').trim();
  base = base.replace(/^\.+/, '').slice(0, 120) || 'video';
  return `${base}.${ext}`;
}

// ---------- Muat turun fail terus ----------
const downloadRules = new Map(); // downloadId -> ruleId
async function downloadFile({ url, title, ext, referer }) {
  let host = '';
  try { host = new URL(url).hostname; } catch {}
  const ruleId = await addRefererRule(referer, { requestDomains: [host] });
  try {
    const id = await chrome.downloads.download({ url, filename: safeName(title, ext || extOf(url) || 'mp4') });
    if (ruleId) {
      downloadRules.set(id, ruleId);
      setTimeout(() => { removeRule(ruleId); downloadRules.delete(id); }, 5 * 60 * 1000);
    }
    return { ok: true, id };
  } catch (e) {
    removeRule(ruleId);
    return { ok: false, error: String(e.message || e) };
  }
}

// ---------- HLS melalui offscreen document ----------
const jobs = {}; // jobId -> {status, done, total, title, error}
const jobRules = {};
const blobDownloads = new Map(); // downloadId -> blobUrl

async function ensureOffscreen() {
  const has = await chrome.offscreen.hasDocument?.();
  if (has) return;
  try {
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['BLOBS'],
      justification: 'Gabungkan segmen HLS menjadi satu fail video untuk dimuat turun.',
    });
  } catch (e) {
    if (!String(e).includes('single offscreen')) throw e;
  }
}

async function startHls({ url, variantUrl, audioUrl, title, referer }) {
  const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  jobs[jobId] = { status: 'mula', done: 0, total: 0, title, error: null };
  jobRules[jobId] = await addRefererRule(referer, { initiatorDomains: [chrome.runtime.id] });
  await ensureOffscreen();
  chrome.runtime.sendMessage({ target: 'offscreen', type: 'hls-start', jobId, url, variantUrl, audioUrl, title });
  return { ok: true, jobId };
}

async function hlsInfo(url) {
  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const pl = parseM3U8(await res.text(), res.url || url);
  if (pl.isMaster) {
    return {
      isMaster: true,
      variants: pl.variants.map((v) => ({
        url: v.url, bandwidth: v.bandwidth, resolution: v.resolution,
        audioUrl: v.audio && pl.audioGroups[v.audio] ? (pl.audioGroups[v.audio].find((a) => a.default) || pl.audioGroups[v.audio][0]).url : null,
      })),
    };
  }
  return { isMaster: false, segments: pl.segments.length, duration: pl.duration, encryption: pl.encryption, endList: pl.endList };
}

chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state || delta.state.current === 'in_progress') return;
  const id = delta.id;
  if (downloadRules.has(id)) { removeRule(downloadRules.get(id)); downloadRules.delete(id); }
  if (blobDownloads.has(id)) {
    chrome.runtime.sendMessage({ target: 'offscreen', type: 'revoke', blobUrl: blobDownloads.get(id) }).catch(() => {});
    blobDownloads.delete(id);
  }
});


// ---------- Sambungan ke app desktop Sedut (native messaging) ----------
const SEDUT_HOST = 'com.sedut.host';

async function sendToSedut({ url, referer, title, kind }) {
  if (!/^(https?|ftp):/i.test(url || '')) return { ok: false, error: 'Link tidak sah' };
  try {
    const r = await chrome.runtime.sendNativeMessage(SEDUT_HOST, {
      action: 'add', url, referer: referer || '', title: title || '', kind: kind || '',
      userAgent: navigator.userAgent,
    });
    return r && r.ok ? { ok: true, how: r.how } : { ok: false, error: r?.error || 'Tiada jawapan dari Sedut' };
  } catch (e) {
    const m = String(e.message || e);
    if (/not found|forbidden|Specified native messaging host/i.test(m)) {
      return { ok: false, error: 'Sedut belum dipasang untuk Chrome. Jalankan: ~/Projects/sedut/install.sh' };
    }
    return { ok: false, error: m };
  }
}

function setupMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: 'sedut-link', title: 'Muat turun dengan Sedut', contexts: ['link'] });
    chrome.contextMenus.create({ id: 'sedut-media', title: 'Muat turun media ini dengan Sedut', contexts: ['video', 'audio'] });
    chrome.contextMenus.create({ id: 'sedut-page', title: 'Hantar halaman ini ke Sedut (YouTube, FB…)', contexts: ['page'] });
  });
}
chrome.runtime.onInstalled.addListener(setupMenus);
chrome.runtime.onStartup.addListener(setupMenus);

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let url = info.menuItemId === 'sedut-link' ? info.linkUrl
          : info.menuItemId === 'sedut-media' ? info.srcUrl
          : info.pageUrl;
  if (url && url.startsWith('blob:')) url = info.pageUrl;   // video MSE: biar yt-dlp urus halaman
  const r = await sendToSedut({ url, referer: info.pageUrl || tab?.url, title: tab?.title });
  if (tab?.id != null) {
    chrome.action.setBadgeText({ tabId: tab.id, text: r.ok ? '✓' : '!' });
    chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: r.ok ? '#16a34a' : '#dc2626' });
    if (!r.ok) chrome.action.setTitle({ tabId: tab.id, title: `Sedut: ${r.error}` });
    setTimeout(() => updateBadge(tab.id), 2500);
  }
});

// ---------- Mesej ----------
async function handle(msg, sender) {
    switch (msg.type) {
      case 'dom-videos': {
        const tabId = sender.tab?.id;
        if (tabId == null) return;
        for (const v of msg.items) {
          const c = classify(v.url, v.mime) || { kind: 'unknown', ext: extOf(v.url) || 'mp4' };
          if (c.kind === 'unknown' && !v.fromVideoTag) continue;
          if (c.kind === 'unknown') c.kind = 'file';
          await addItem(tabId, { url: v.url, kind: c.kind, ext: c.ext, mime: v.mime || '', size: null, source: 'dom' });
        }
        const data = await getTab(tabId);
        if (msg.blobVideos > (data.blobVideos || 0)) { data.blobVideos = msg.blobVideos; persist(tabId); }
        return;
      }
      case 'get-items': {
        const data = await getTab(msg.tabId);
        return { items: Object.values(data.items).sort((a, b) => (b.size || 0) - (a.size || 0)), blobVideos: data.blobVideos || 0, jobs };
      }
      case 'get-jobs':
        return { jobs };
      case 'clear':
        await clearTab(msg.tabId);
        return { ok: true };
      case 'send-to-sedut':
        return await sendToSedut(msg);
      case 'download-file':
        return await downloadFile(msg);
      case 'hls-info':
        try { return { ok: true, info: await hlsInfo(msg.url) }; }
        catch (e) { return { ok: false, error: String(e.message || e) }; }
      case 'hls-download':
        return await startHls(msg);
      case 'hls-cancel':
        chrome.runtime.sendMessage({ target: 'offscreen', type: 'hls-cancel', jobId: msg.jobId }).catch(() => {});
        return { ok: true };
      case 'dismiss-job':
        delete jobs[msg.jobId];
        return { ok: true };

      // --- daripada offscreen ---
      case 'job-progress':
        if (jobs[msg.jobId]) Object.assign(jobs[msg.jobId], { status: msg.status, done: msg.done, total: msg.total, bytes: msg.bytes });
        return;
      case 'job-error':
        if (jobs[msg.jobId]) Object.assign(jobs[msg.jobId], { status: 'gagal', error: msg.error });
        removeRule(jobRules[msg.jobId]); delete jobRules[msg.jobId];
        return;
      case 'job-file': {
        // satu job boleh hasilkan 2 fail (video + audio berasingan)
        try {
          const id = await chrome.downloads.download({ url: msg.blobUrl, filename: safeName(msg.title, msg.ext) });
          blobDownloads.set(id, msg.blobUrl);
        } catch (e) {
          if (jobs[msg.jobId]) Object.assign(jobs[msg.jobId], { status: 'gagal', error: String(e.message || e) });
        }
        return;
      }
      case 'job-done':
        if (jobs[msg.jobId]) Object.assign(jobs[msg.jobId], { status: 'siap', note: msg.note || null });
        removeRule(jobRules[msg.jobId]); delete jobRules[msg.jobId];
        return;
    }
    return { ok: true };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target === 'offscreen') return; // bukan untuk kita
  handle(msg, sender).then(
    (r) => sendResponse(r ?? { ok: true }),
    (e) => sendResponse({ ok: false, error: String(e?.message || e) })
  );
  return true; // respons async
});
