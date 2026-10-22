// hls.js — small M3U8 parser (shared by background & offscreen)

function resolveUrl(u, base) {
  try { return new URL(u, base).href; } catch { return u; }
}

// Parse an attribute list: KEY=VALUE,KEY="VALUE, with commas",...
export function parseAttrs(str) {
  const out = {};
  const re = /([A-Z0-9-]+)=("[^"]*"|[^,]*)/g;
  let m;
  while ((m = re.exec(str))) {
    let v = m[2];
    if (v.startsWith('"')) v = v.slice(1, -1);
    out[m[1]] = v;
  }
  return out;
}

function parseByteRange(str, prevEnd) {
  // "length[@offset]"
  const [len, off] = str.split('@');
  const length = parseInt(len, 10);
  const offset = off !== undefined ? parseInt(off, 10) : (prevEnd || 0);
  return { offset, length };
}

export function parseM3U8(text, baseUrl) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length || !lines[0].startsWith('#EXTM3U')) {
    throw new Error('Not a valid M3U8 playlist');
  }

  const result = {
    isMaster: false,
    variants: [],
    audioGroups: {},      // groupId -> [{name, url, default, language}]
    segments: [],
    map: null,
    mediaSequence: 0,
    endList: false,
    encryption: 'NONE',   // NONE | AES-128 | DRM
    duration: 0,
  };

  let pendingVariant = null;
  let currentKey = null;
  let pendingByteRange = null;
  let pendingDuration = 0;
  let lastByteEnd = 0;
  let seq = 0;

  for (const line of lines) {
    if (line.startsWith('#EXT-X-STREAM-INF:')) {
      result.isMaster = true;
      const a = parseAttrs(line.slice(18));
      pendingVariant = {
        bandwidth: parseInt(a.BANDWIDTH || '0', 10),
        resolution: a.RESOLUTION || '',
        codecs: a.CODECS || '',
        audio: a.AUDIO || null,
      };
    } else if (line.startsWith('#EXT-X-MEDIA:')) {
      const a = parseAttrs(line.slice(13));
      if (a.TYPE === 'AUDIO' && a.URI) {
        const g = a['GROUP-ID'];
        (result.audioGroups[g] ||= []).push({
          name: a.NAME || g,
          language: a.LANGUAGE || '',
          default: a.DEFAULT === 'YES',
          url: resolveUrl(a.URI, baseUrl),
        });
      }
    } else if (line.startsWith('#EXT-X-MEDIA-SEQUENCE:')) {
      seq = result.mediaSequence = parseInt(line.slice(22), 10) || 0;
    } else if (line.startsWith('#EXT-X-KEY:')) {
      const a = parseAttrs(line.slice(11));
      const method = a.METHOD || 'NONE';
      const keyFormat = a.KEYFORMAT || 'identity';
      if (method === 'NONE') {
        currentKey = null;
      } else if (method === 'AES-128' && keyFormat === 'identity') {
        currentKey = { method, uri: resolveUrl(a.URI, baseUrl), iv: a.IV || null };
        if (result.encryption === 'NONE') result.encryption = 'AES-128';
      } else {
        // SAMPLE-AES / FairPlay / Widevine / PlayReady = DRM. Not supported.
        result.encryption = 'DRM';
        currentKey = { method, drm: true };
      }
    } else if (line.startsWith('#EXT-X-MAP:')) {
      const a = parseAttrs(line.slice(11));
      result.map = { url: resolveUrl(a.URI, baseUrl), byteRange: a.BYTERANGE ? parseByteRange(a.BYTERANGE, 0) : null };
    } else if (line.startsWith('#EXT-X-BYTERANGE:')) {
      pendingByteRange = parseByteRange(line.slice(17), lastByteEnd);
    } else if (line.startsWith('#EXTINF:')) {
      pendingDuration = parseFloat(line.slice(8)) || 0;
    } else if (line.startsWith('#EXT-X-ENDLIST')) {
      result.endList = true;
    } else if (!line.startsWith('#')) {
      const url = resolveUrl(line, baseUrl);
      if (pendingVariant) {
        result.variants.push({ ...pendingVariant, url });
        pendingVariant = null;
      } else {
        const seg = { url, seq, duration: pendingDuration, key: currentKey, byteRange: pendingByteRange };
        if (pendingByteRange) lastByteEnd = pendingByteRange.offset + pendingByteRange.length;
        result.segments.push(seg);
        result.duration += pendingDuration;
        pendingByteRange = null;
        pendingDuration = 0;
        seq++;
      }
    }
  }

  result.variants.sort((a, b) => b.bandwidth - a.bandwidth);
  return result;
}

// AES-128 IV: the IV attribute (hex) or the media sequence number as 16-byte big-endian.
export function ivFor(key, seq) {
  const iv = new Uint8Array(16);
  if (key.iv) {
    const hex = key.iv.replace(/^0x/i, '').padStart(32, '0');
    for (let i = 0; i < 16; i++) iv[i] = parseInt(hex.substr(i * 2, 2), 16);
  } else {
    let n = BigInt(seq);
    for (let i = 15; i >= 0 && n > 0n; i--) { iv[i] = Number(n & 0xffn); n >>= 8n; }
  }
  return iv;
}
