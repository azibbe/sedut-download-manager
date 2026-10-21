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
    // nama generik (index.m3u8, playlist.m3u8 …) — tambah folder induk supaya boleh dibezakan
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

// ---------- Senarai video ----------
async function renderList() {
  const { items, blobVideos } = await msg({ type: 'get-items', tabId: tab.id });
  const hideSmall = $('#hideSmall').checked;
  const shown = items.filter((it) => !(hideSmall && it.kind === 'file' && it.size && it.size < 500 * 1024));
  const list = $('#list');
  list.replaceChildren();

  if (!shown.length) {
    list.append(el('div', { class: 'empty' }, items.length ? 'Hanya fail kecil dikesan (nyahtanda "sembunyi kecil").' : 'Tiada video dikesan lagi. Main video dalam laman ini, kemudian buka semula.'));
  }

  shown.forEach((it, idx) => {
    const status = el('div');
    const controls = el('div', { class: 'row' });
    const card = el('div', { class: 'item' },
      el('div', { class: 'name', title: it.url }, shortName(it.url)),
      el('div', { class: 'meta' },
        el('span', { class: `tag ${it.kind}` }, it.kind === 'file' ? (it.ext || 'video').toUpperCase() : it.kind.toUpperCase()),
        it.size ? el('span', { class: 'tag' }, fmtSize(it.size)) : null,
        el('span', { class: 'tag' }, it.source === 'network' ? 'rangkaian' : 'DOM'),
      ),
      controls, status);

    const copyBtn = el('button', { class: 'ghost', onclick: async () => {
      await navigator.clipboard.writeText(it.url);
      copyBtn.textContent = 'Disalin ✓';
      setTimeout(() => (copyBtn.textContent = 'Salin URL'), 1200);
    } }, 'Salin URL');

    if (it.kind === 'file') {
      const b = el('button', { onclick: async () => {
        b.disabled = true;
        const r = await msg({ type: 'download-file', url: it.url, ext: it.ext, title: title(), referer: tab.url });
        status.replaceChildren(r.ok ? el('div', { class: 'note' }, 'Muat turun dimulakan ✓') : el('div', { class: 'err' }, r.error));
        b.disabled = false;
      } }, 'Muat turun');
      controls.append(b, copyBtn);
    } else if (it.kind === 'hls') {
      const b = el('button', { onclick: () => prepareHls(it, controls, status, b) }, 'Muat turun');
      controls.append(b, copyBtn);
    } else {
      controls.append(copyBtn);
      status.append(el('div', { class: 'note' }, 'DASH (.mpd) belum disokong — salin URL dan guna yt-dlp/ffmpeg.'));
    }
    list.append(card);
  });

  $('#hint').textContent = blobVideos && !items.some((i) => i.kind !== 'file' || i.source === 'network')
    ? 'Laman ini guna video blob/MSE. Main video dahulu supaya stream (HLS/MP4) dikesan dari rangkaian.'
    : '';
}

async function prepareHls(it, controls, status, btn) {
  btn.disabled = true;
  status.replaceChildren(el('div', { class: 'note' }, 'Membaca playlist…'));
  const r = await msg({ type: 'hls-info', url: it.url });
  btn.disabled = false;
  if (!r.ok) { status.replaceChildren(el('div', { class: 'err' }, `Gagal baca playlist: ${r.error}`)); return; }
  const info = r.info;

  if (!info.isMaster) {
    if (info.encryption === 'DRM') { status.replaceChildren(el('div', { class: 'err' }, 'Stream ini dilindungi DRM — tidak boleh dimuat turun.')); return; }
    status.replaceChildren(el('div', { class: 'note' }, `${info.segments} segmen, ~${Math.round(info.duration / 60)} min${info.endList ? '' : ' (langsung)'}`));
    return startHls({ url: it.url }, status);
  }

  // master: pilih kualiti
  const sel = el('select');
  info.variants.forEach((v, i) => {
    const label = `${v.resolution || '?'} · ${(v.bandwidth / 1e6).toFixed(2)} Mbps${v.audioUrl ? ' · audio asing' : ''}`;
    sel.append(el('option', { value: String(i) }, label));
  });
  const go = el('button', { onclick: () => {
    const v = info.variants[+sel.value];
    go.disabled = true;
    startHls({ url: it.url, variantUrl: v.url, audioUrl: v.audioUrl }, status);
  } }, 'Mula');
  controls.replaceChildren(sel, go);
  status.replaceChildren();
}

async function startHls(opts, status) {
  const r = await msg({ type: 'hls-download', ...opts, title: title(), referer: tab.url });
  if (!r.ok) status.replaceChildren(el('div', { class: 'err' }, r.error || 'Gagal mula'));
  else status.replaceChildren(el('div', { class: 'note' }, 'Dimulakan — lihat kemajuan di atas.'));
  renderJobs();
}

// ---------- Kemajuan job HLS ----------
async function renderJobs() {
  const { jobs } = await msg({ type: 'get-jobs' });
  const box = $('#jobs');
  box.replaceChildren();
  for (const [id, j] of Object.entries(jobs)) {
    const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
    const finished = j.status === 'siap' || j.status === 'gagal';
    box.append(el('div', { class: 'job' },
      el('div', { class: 'name' }, j.title),
      el('div', { class: 'meta' }, el('span', { class: 'tag' }, j.status), j.total ? el('span', { class: 'tag' }, `${j.done}/${j.total} segmen`) : null, j.bytes ? el('span', { class: 'tag' }, fmtSize(j.bytes)) : null),
      el('div', { class: 'bar' }, (() => { const d = el('div'); d.style.width = `${finished && j.status === 'siap' ? 100 : pct}%`; return d; })()),
      j.error ? el('div', { class: 'err' }, j.error) : null,
      j.note ? el('div', { class: 'note' }, j.note) : null,
      el('div', { class: 'row' }, finished
        ? el('button', { class: 'ghost', onclick: async () => { await msg({ type: 'dismiss-job', jobId: id }); renderJobs(); } }, 'Tutup')
        : el('button', { class: 'ghost', onclick: () => msg({ type: 'hls-cancel', jobId: id }) }, 'Batal')),
    ));
  }
}

(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  $('#hideSmall').addEventListener('change', renderList);
  $('#clear').addEventListener('click', async () => { await msg({ type: 'clear', tabId: tab.id }); renderList(); });
  await renderList();
  await renderJobs();
  setInterval(renderJobs, 1000);
})();
