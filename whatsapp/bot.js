/**
 * bot.js — Daemon WhatsApp lokal (Baileys) untuk Beverra Central.
 *
 * Jalan TERUS di PC ini (bukan di GitHub Actions — sesi WA butuh koneksi
 * persisten, tidak cocok untuk mesin sesaat). Setelah scan QR sekali, sesi
 * tersimpan di folder `session/` dan otomatis reconnect setiap restart.
 *
 * Ekspos HTTP lokal (default http://127.0.0.1:4001) supaya modul Python
 * (bvr_sync/notifier.py) atau proses lain di PC ini bisa kirim pesan tanpa
 * perlu tahu detail Baileys:
 *   GET  /health         -> { connected, hasQr }
 *   GET  /groups          -> daftar grup WA (id + nama) yang bot ikuti
 *   POST /send  {to, message} -> kirim pesan ke JID (grup atau personal)
 *
 * Cara pakai:
 *   cd whatsapp && npm install && npm start
 *   Scan QR yang muncul di terminal (WhatsApp -> Perangkat Tertaut -> Tautkan Perangkat)
 *   Setelah "WA CONNECTED", buka http://127.0.0.1:4001/groups untuk cari Group ID.
 */
'use strict';
const http = require('http');
const path = require('path');
const fs = require('fs');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const pino = require('pino');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const { handleQuery } = require('./query-handler');

const SESSION_DIR = path.join(__dirname, 'session');
const PORT = parseInt(process.env.WA_PORT || '4001', 10);
const HOST = process.env.WA_HOST || '127.0.0.1';

const logger = pino({ level: process.env.WA_LOG_LEVEL || 'warn' });

let sock = null;
let isConnected = false;
let lastQr = null;
let ownNumber = null; // nomor bot tanpa suffix device, cth "6281234567890"
let ownLid = null;    // WhatsApp sekarang bisa pakai LID (Linked ID) selain nomor
                       // untuk mention, jadi kita cocokkan ke KEDUANYA.

// ── deteksi mention ke bot sendiri di pesan masuk ───────────────────────────
function extractText(msg) {
  return (
    msg?.conversation ||
    msg?.extendedTextMessage?.text ||
    msg?.imageMessage?.caption ||
    msg?.videoMessage?.caption ||
    ''
  );
}

function mentionsBot(msg) {
  const mentioned = msg?.extendedTextMessage?.contextInfo?.mentionedJid || [];
  return mentioned.some((jid) => {
    const id = jid.split('@')[0];
    return id === ownNumber || (ownLid && id === ownLid);
  });
}

function stripMention(text) {
  // buang token "@62xxxx" di awal teks (WhatsApp render mention sbg teks biasa)
  return text.replace(/^@?\d{8,15}\s*/, '').trim();
}

// ── util: nama JID grup dari cache ──────────────────────────────────────────
async function listGroups() {
  if (!sock) return [];
  const map = await sock.groupFetchAllParticipating();
  return Object.values(map).map((g) => ({
    id: g.id,
    name: g.subject,
    participants: (g.participants || []).length,
  }));
}

// ── koneksi Baileys (dengan auto-reconnect) ─────────────────────────────────
async function startSock() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false, // kita tangani sendiri (terminal + PNG)
    browser: ['Beverra Central', 'Chrome', '1.0'],
  });

  sock.ev.on('creds.update', saveCreds);

  // ── dengar pesan masuk: jawab kalau bot di-mention ──────────────────────
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    console.log(`[debug] messages.upsert type=${type} count=${messages.length}`);
    if (type !== 'notify') return;
    for (const m of messages) {
      try {
        const mentioned = m.message?.extendedTextMessage?.contextInfo?.mentionedJid || [];
        console.log(`[debug] pesan dari=${m.key.remoteJid} fromMe=${m.key.fromMe} hasMsg=${!!m.message} mentioned=${JSON.stringify(mentioned)} ownNumber=${ownNumber}`);

        if (m.key.fromMe || !m.message) continue;
        if (!mentionsBot(m.message)) continue;

        const raw = extractText(m.message);
        const question = stripMention(raw);
        console.log(`[tanya] dari ${m.key.remoteJid}: "${question}"`);

        const answer = await handleQuery(question, m.key.remoteJid);
        await sock.sendMessage(m.key.remoteJid, { text: answer }, { quoted: m });
      } catch (e) {
        console.error('[messages.upsert] gagal proses pesan:', e.message);
      }
    }
  });

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      lastQr = qr;
      console.log('\n=== SCAN QR INI DI WHATSAPP (Perangkat Tertaut > Tautkan Perangkat) ===\n');
      qrcodeTerminal.generate(qr, { small: true });
      try {
        const pngPath = path.join(__dirname, 'qr.png');
        await QRCode.toFile(pngPath, qr, { width: 400 });
        console.log(`(atau buka gambar QR: ${pngPath})\n`);
      } catch (e) { /* abaikan — terminal QR sudah cukup */ }
    }

    if (connection === 'open') {
      isConnected = true;
      lastQr = null;
      ownNumber = sock.user?.id?.split(':')[0]?.split('@')[0] || null;
      ownLid = sock.user?.lid?.split(':')[0]?.split('@')[0] || null;
      console.log(`[debug] sock.user = ${JSON.stringify(sock.user)}`);
      console.log(`✅ WA CONNECTED (nomor: ${ownNumber}, lid: ${ownLid}) — daemon siap menerima /send & mention`);
    }

    if (connection === 'close') {
      isConnected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      console.log(`⚠️ Koneksi WA terputus (code=${statusCode}). ${loggedOut ? 'Logout — perlu scan QR ulang.' : 'Menyambung ulang...'}`);
      if (!loggedOut) {
        setTimeout(startSock, 3000); // reconnect otomatis pakai sesi tersimpan
      } else {
        // sesi tidak valid lagi — hapus supaya QR baru diminta
        fs.rmSync(SESSION_DIR, { recursive: true, force: true });
        setTimeout(startSock, 1000);
      }
    }
  });

  return sock;
}

// ── HTTP API lokal ───────────────────────────────────────────────────────────
function normalizeJid(to) {
  // izinkan format praktis: nomor polos, "62xxx@s.whatsapp.net", atau "xxxx@g.us"
  if (to.includes('@')) return to;
  return `${to.replace(/[^0-9]/g, '')}@s.whatsapp.net`;
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');

  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200);
    res.end(JSON.stringify({ connected: isConnected, hasQr: !!lastQr }));
    return;
  }

  if (req.method === 'GET' && req.url === '/groups') {
    if (!isConnected) {
      res.writeHead(503);
      res.end(JSON.stringify({ error: 'WA belum tersambung' }));
      return;
    }
    try {
      const groups = await listGroups();
      res.writeHead(200);
      res.end(JSON.stringify({ groups }, null, 2));
    } catch (e) {
      res.writeHead(500);
      res.end(JSON.stringify({ error: String(e) }));
    }
    return;
  }

  if (req.method === 'POST' && req.url === '/send') {
    if (!isConnected) {
      res.writeHead(503);
      res.end(JSON.stringify({ error: 'WA belum tersambung' }));
      return;
    }
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', async () => {
      try {
        const { to, message } = JSON.parse(body || '{}');
        if (!to || !message) {
          res.writeHead(400);
          res.end(JSON.stringify({ error: 'Wajib isi "to" dan "message"' }));
          return;
        }
        await sock.sendMessage(normalizeJid(to), { text: message });
        res.writeHead(200);
        res.end(JSON.stringify({ ok: true }));
      } catch (e) {
        res.writeHead(500);
        res.end(JSON.stringify({ error: String(e) }));
      }
    });
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: 'not found', routes: ['GET /health', 'GET /groups', 'POST /send'] }));
});

server.listen(PORT, HOST, () => {
  console.log(`WhatsApp daemon HTTP lokal di http://${HOST}:${PORT}`);
});

startSock().catch((e) => {
  console.error('Gagal memulai koneksi WA:', e);
  process.exit(1);
});

process.on('SIGINT', () => process.exit(0));
process.on('SIGTERM', () => process.exit(0));
