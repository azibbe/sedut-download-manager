// popup.js
let tab = null;
const $ = (s) => document.querySelector(s);

function fmtSize(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function shortName(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split('/').filter(Boolean).map(decodeURIComponent);
    let last = parts.pop() || u.hostname;
    // generic names (index.m3u8, playlist.m3u8 …) — prefix the parent folder so they can be told apart
    if (/^(index|playlist|master|chunklist|manifest|prog_index)[^/]*\.(m3u8|mpd)$/i.test(last) && parts.length) last = `${parts.pop()}/${last}`;
    return last.length > 70 ? last.slice(0, 67) + '…' : last;
  } catch { return url; }
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}

const msg = (m) => chrome.runtime.sendMessage(m);
const title = () => (tab?.title || 'video');

// ---------- Video list ----------
async function renderList() {
  const { items, blobVideos } = await msg({ type: 'get-items', tabId: tab.id });
  const hideSmall = $('#hideSmall').checked;
  const shown = items.filter((it) => !(hideSmall && it.kind === 'file' && it.size && it.size < 500 * 1024));
  const list = $('#list');
  list.replaceChildren();

  if (!shown.length) {
    list.append(el('div', { class: 'empty' }, items.length ? 'Only small files detected (untick "hide small").' : 'No videos detected yet. Play the video on this page, then reopen this popup.'));
  }

  shown.forEach((it, idx) => {
    const status = el('div');
    const controls = el('div', { class: 'row' });
    const card = el('div', { class: 'item' },
      el('div', { class: 'name', title: it.url }, shortName(it.url)),
      el('div', { class: 'meta' },
        el('span', { class: `tag ${it.kind}` }, it.kind === 'file' ? (it.ext || 'video').toUpperCase() : it.kind.toUpperCase()),
        it.size ? el('span', { class: 'tag' }, fmtSize(it.size)) : null,
        el('span', { class: 'tag' }, it.source === 'network' ? 'network' : 'DOM'),
      ),
      controls, status);

    const copyBtn = el('button', { class: 'ghost', onclick: async () => {
      await navigator.clipboard.writeText(it.url);
      copyBtn.textContent = 'Copied ✓';
      setTimeout(() => (copyBtn.textContent = 'Copy URL'), 1200);
    } }, 'Copy URL');

    const sedutBtn = el('button', { class: 'sedut', title: 'Send to the Sedut app (aria2c/yt-dlp)', onclick: async () => {
      sedutBtn.disabled = true;
      const r = await msg({ type: 'send-to-sedut', url: it.url, referer: tab.url, title: title(), kind: it.kind });
      status.replaceChildren(r.ok ? el('div', { class: 'note' }, 'Sent to Sedut ✓') : el('div', { class: 'err' }, r.error));
      sedutBtn.disabled = false;
    } }, 'Sedut');

    if (it.kind === 'file') {
      const b = el('button', { onclick: async () => {
        b.disabled = true;
        const r = await msg({ type: 'download-file', url: it.url, ext: it.ext, title: title(), referer: tab.url });
        status.replaceChildren(r.ok ? el('div', { class: 'note' }, 'Download started ✓') : el('div', { class: 'err' }, r.error));
        b.disabled = false;
      } }, 'Download');
      controls.append(b, sedutBtn, copyBtn);
    } else if (it.kind === 'hls') {
      const b = el('button', { onclick: () => prepareHls(it, controls, status, b) }, 'Download');
      controls.append(b, sedutBtn, copyBtn);
    } else {
      controls.append(sedutBtn, copyBtn);
      status.append(el('div', { class: 'note' }, 'DASH (.mpd): the extension can\'t merge it — press "Sedut" (yt-dlp can).'));
    }
    list.append(card);
  });

  $('#hint').textContent = blobVideos && !items.some((i) => i.kind !== 'file' || i.source === 'network')
    ? 'This page uses blob/MSE video. Play the video first so the stream (HLS/MP4) is detected from the network.'
    : '';
}

async function prepareHls(it, controls, status, btn) {
  btn.disabled = true;
  status.replaceChildren(el('div', { class: 'note' }, 'Reading playlist…'));
  const r = await msg({ type: 'hls-info', url: it.url });
  btn.disabled = false;
  if (!r.ok) { status.replaceChildren(el('div', { class: 'err' }, `Failed to read playlist: ${r.error}`)); return; }
  const info = r.info;

  if (!info.isMaster) {
    if (info.encryption === 'DRM') { status.replaceChildren(el('div', { class: 'err' }, 'This stream is DRM-protected — it cannot be downloaded.')); return; }
    status.replaceChildren(el('div', { class: 'note' }, `${info.segments} segments, ~${Math.round(info.duration / 60)} min${info.endList ? '' : ' (live)'}`));
    return startHls({ url: it.url }, status);
  }

  // master: choose quality
  const sel = el('select');
  info.variants.forEach((v, i) => {
    const label = `${v.resolution || '?'} · ${(v.bandwidth / 1e6).toFixed(2)} Mbps${v.audioUrl ? ' · separate audio' : ''}`;
    sel.append(el('option', { value: String(i) }, label));
  });
  const go = el('button', { onclick: () => {
    const v = info.variants[+sel.value];
    go.disabled = true;
    startHls({ url: it.url, variantUrl: v.url, audioUrl: v.audioUrl }, status);
  } }, 'Start');
  controls.replaceChildren(sel, go);
  status.replaceChildren();
}

async function startHls(opts, status) {
  const r = await msg({ type: 'hls-download', ...opts, title: title(), referer: tab.url });
  if (!r.ok) status.replaceChildren(el('div', { class: 'err' }, r.error || 'Failed to start'));
  else status.replaceChildren(el('div', { class: 'note' }, 'Started — see progress above.'));
  renderJobs();
}

// ---------- HLS job progress ----------
async function renderJobs() {
  const { jobs } = await msg({ type: 'get-jobs' });
  const box = $('#jobs');
  box.replaceChildren();
  for (const [id, j] of Object.entries(jobs)) {
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    const finished = j.status === 'done' || j.status === 'failed';
    box.append(el('div', { class: 'job' },
      el('div', { class: 'name' }, j.title),
      el('div', { class: 'meta' }, el('span', { class: 'tag' }, j.status), j.total ? el('span', { class: 'tag' }, `${j.done}/${j.total} segments`) : null, j.bytes ? el('span', { class: 'tag' }, fmtSize(j.bytes)) : null),
      el('div', { class: 'bar' }, (() => { const d = el('div'); d.style.width = `${finished && j.status === 'done' ? 100 : pct}%`; return d; })()),
      j.error ? el('div', { class: 'err' }, j.error) : null,
      j.note ? el('div', { class: 'note' }, j.note) : null,
      el('div', { class: 'row' }, finished
        ? el('button', { class: 'ghost', onclick: async () => { await msg({ type: 'dismiss-job', jobId: id }); renderJobs(); } }, 'Dismiss')
        : el('button', { class: 'ghost', onclick: () => msg({ type: 'hls-cancel', jobId: id }) }, 'Cancel')),
    ));
  }
}

(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('#hideSmall').addEventListener('change', renderList);
  $('#sendPage').addEventListener('click', async () => {
    const r = await msg({ type: 'send-to-sedut', url: tab.url, referer: tab.url, title: title(), kind: 'page' });
    $('#hint').textContent = r.ok ? 'Page sent to Sedut ✓ (yt-dlp will detect the video)' : r.error;
  });
  $('#clear').addEventListener('click', async () => { await msg({ type: 'clear', tabId: tab.id }); renderList(); });
  await renderList();
  await renderJobs();
  setInterval(renderJobs, 1000);
})();
