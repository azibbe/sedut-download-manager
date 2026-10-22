// offscreen.js — muat turun & gabung segmen HLS (perlu DOM untuk Blob URL)
import { parseM3U8, ivFor } from './hls.js';

const CONCURRENCY = 6;
const RETRIES = 3;
const controllers = new Map(); // jobId -> AbortController

function send(msg) { return chrome.runtime.sendMessage(msg).catch(() => {}); }

async function fetchBytes(url, signal, byteRange) {
  const headers = {};
  if (byteRange) headers.Range = `bytes=${byteRange.offset}-${byteRange.offset + byteRange.length - 1}`;
  let lastErr;
  for (let i = 0; i < RETRIES; i++) {
    try {
      const res = await fetch(url, { signal, headers, credentials: 'include' });
      if (!res.ok) throw new Error(`HTTP ${res.status} untuk ${url}`);
      return new Uint8Array(await res.arrayBuffer());
    } catch (e) {
      if (signal.aborted) throw new Error('Dibatalkan');
      lastErr = e;
      await new Promise((r) => setTimeout(r, 800 * (i + 1)));
    }
  }
  throw lastErr;
}

async function fetchPlaylist(url, signal) {
  const res = await fetch(url, { signal, credentials: 'include' });
  if (!res.ok) throw new Error(`HTTP ${res.status} (playlist)`);
  return parseM3U8(await res.text(), res.url || url);
}

const keyCache = new Map();
async function getKey(uri, signal) {
  if (!keyCache.has(uri)) {
    const raw = await fetchBytes(uri, signal);
    keyCache.set(uri, crypto.subtle.importKey('raw', raw, 'AES-CBC', false, ['decrypt']));
  }
  return keyCache.get(uri);
}

// Muat turun satu media playlist -> {blob, ext}
async function downloadMedia(playlistUrl, jobId, label, signal, progress) {
  const pl = await fetchPlaylist(playlistUrl, signal);
  if (pl.isMaster) throw new Error('Playlist media dijangka, dapat master');
  if (pl.encryption === 'DRM') throw new Error('Stream ini dilindungi DRM (Widevine/FairPlay/SAMPLE-AES) — tidak disokong.');
  if (!pl.segments.length) throw new Error('Tiada segmen dalam playlist');

  const parts = new Array(pl.segments.length);
  let next = 0;
  progress.total += pl.segments.length;

  async function worker() {
    while (next < pl.segments.length) {
      const i = next++;
      const seg = pl.segments[i];
      let data = await fetchBytes(seg.url, signal, seg.byteRange);
      if (seg.key && seg.key.method === 'AES-128') {
        const key = await getKey(seg.key.uri, signal);
        data = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-CBC', iv: ivFor(seg.key, seg.seq) }, key, data));
      }
      parts[i] = data;
      progress.done++;
      progress.bytes += data.byteLength;
      send({ type: 'job-progress', jobId, status: `muat turun ${label}`, done: progress.done, total: progress.total, bytes: progress.bytes });
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, pl.segments.length) }, worker));

  let ext = 'ts', type = 'video/mp2t';
  if (pl.map) {
    parts.unshift(await fetchBytes(pl.map.url, signal, pl.map.byteRange)); // init segment fMP4
    ext = 'mp4'; type = 'video/mp4';
  } else if (parts[0] && parts[0][0] !== 0x47) {
    // bukan MPEG-TS (bait sync 0x47) — mungkin fMP4/ADTS
    ext = 'mp4'; type = 'video/mp4';
  }
  return { blob: new Blob(parts, { type }), ext, live: !pl.endList };
}

async function runJob({ jobId, url, variantUrl, audioUrl, title }) {
  const ctrl = new AbortController();
  controllers.set(jobId, ctrl);
  const progress = { done: 0, total: 0, bytes: 0 };
  try {
    let videoUrl = variantUrl || url;
    // kalau diberi master tanpa pilihan, ambil kualiti tertinggi
    const first = await fetchPlaylist(videoUrl, ctrl.signal);
    if (first.isMaster) {
      const best = first.variants[0];
      if (!best) throw new Error('Master playlist tiada varian');
      videoUrl = best.url;
      if (!audioUrl && best.audio && first.audioGroups[best.audio]) {
        const g = first.audioGroups[best.audio];
        audioUrl = (g.find((a) => a.default) || g[0]).url;
      }
    }

    const tasks = [downloadMedia(videoUrl, jobId, 'video', ctrl.signal, progress)];
    if (audioUrl) tasks.push(downloadMedia(audioUrl, jobId, 'audio', ctrl.signal, progress));
    const [video, audio] = await Promise.all(tasks);

    send({ type: 'job-progress', jobId, status: 'menyimpan', done: progress.done, total: progress.total, bytes: progress.bytes });
    await send({ type: 'job-file', jobId, blobUrl: URL.createObjectURL(video.blob), title: audio ? `${title} (video)` : title, ext: video.ext });
    if (audio) {
      await send({ type: 'job-file', jobId, blobUrl: URL.createObjectURL(audio.blob), title: `${title} (audio)`, ext: audio.ext === 'ts' ? 'ts' : 'm4a' });
    }
    const notes = [];
    if (audio) notes.push('Audio berasingan — gabung: ffmpeg -i video -i audio -c copy out.mp4');
    if (video.live) notes.push('Siaran langsung: hanya tetingkap semasa dimuat turun.');
    send({ type: 'job-done', jobId, note: notes.join(' ') || null });
  } catch (e) {
    send({ type: 'job-error', jobId, error: String(e.message || e) });
  } finally {
    controllers.delete(jobId);
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== 'offscreen') return;
  if (msg.type === 'hls-start') runJob(msg);
  else if (msg.type === 'hls-cancel') controllers.get(msg.jobId)?.abort();
  else if (msg.type === 'revoke') setTimeout(() => URL.revokeObjectURL(msg.blobUrl), 10000);
});
