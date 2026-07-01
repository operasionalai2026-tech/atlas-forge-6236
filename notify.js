#!/usr/bin/env node
/**
 * notify.js — Pengirim notifikasi WhatsApp via Fonnte (Node.js).
 *
 * Menggantikan pengiriman Fonnte yang sebelumnya di Python.
 * Dipanggil oleh bvr_sync/notifier.py:  node notify.js  (pesan lewat STDIN)
 * Bisa juga manual:                      node notify.js "halo dunia"
 *
 * Tanpa dependency npm — butuh Node.js 18+ (fetch built-in).
 * Membaca kredensial dari file `env` lalu `.env` (process.env tetap menang).
 */
'use strict';
const fs = require('fs');
const path = require('path');

// ── loader env sederhana (tanpa dotenv) ─────────────────────────────────────
function loadEnvFile(file, store) {
  if (!fs.existsSync(file)) return;
  const text = fs.readFileSync(file, 'utf-8');
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if ((val.startsWith('"') && val.endsWith('"')) ||
        (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    store[key] = val; // file `.env` (dimuat kedua) menimpa `env`
  }
}

function getConfig() {
  const dir = __dirname;
  const fileStore = {};
  loadEnvFile(path.join(dir, 'env'), fileStore);
  loadEnvFile(path.join(dir, '.env'), fileStore);
  const get = (k, d) => (process.env[k] != null ? process.env[k] : (fileStore[k] != null ? fileStore[k] : d));
  return {
    token:  (get('FONNTE_TOKEN', '') || '').trim(),
    target: (get('FONNTE_TARGET', '') || '').trim(),
    url:    (get('FONNTE_URL', 'https://api.fonnte.com/send') || '').trim(),
  };
}

// ── baca pesan: argv[2] kalau ada, kalau tidak dari STDIN ────────────────────
function readMessage() {
  const arg = process.argv.slice(2).join(' ').trim();
  if (arg) return Promise.resolve(arg);
  return new Promise((resolve) => {
    let data = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data.trim()));
    // kalau tidak ada stdin (TTY), jangan menggantung
    if (process.stdin.isTTY) resolve('');
  });
}

// ── kirim ke Fonnte ──────────────────────────────────────────────────────────
async function sendFonnte(cfg, message) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const res = await fetch(cfg.url, {
      method: 'POST',
      headers: { Authorization: cfg.token },
      body: new URLSearchParams({ target: cfg.target, message }),
      signal: controller.signal,
    });
    const text = await res.text();
    let ok = res.ok;
    try { ok = ok && (JSON.parse(text).status === true); } catch (_) { /* biar apa adanya */ }
    if (ok) {
      console.log('[notify.js] WhatsApp terkirim.');
      return 0;
    }
    console.error(`[notify.js] Fonnte non-sukses [${res.status}]: ${text.slice(0, 200)}`);
    return 1;
  } catch (err) {
    console.error(`[notify.js] Gagal kirim: ${err.message}`);
    return 1;
  } finally {
    clearTimeout(timer);
  }
}

// ── main ─────────────────────────────────────────────────────────────────────
(async () => {
  const cfg = getConfig();
  if (!cfg.token || !cfg.target) {
    console.log('[notify.js] FONNTE_TOKEN/FONNTE_TARGET kosong — notifikasi dilewati.');
    process.exit(0); // skip dianggap bukan error
  }
  const message = await readMessage();
  if (!message) {
    console.error('[notify.js] Pesan kosong — tidak ada yang dikirim.');
    process.exit(1);
  }
  process.exit(await sendFonnte(cfg, message));
})();
