/**
 * query-handler.js — parser pertanyaan sederhana -> query Supabase -> jawaban teks.
 *
 * ATURAN KETAT:
 *   1. Hanya jawab dari data yang benar-benar ada di database. Kalau SKU/topik
 *      tidak ditemukan atau pertanyaan tidak cocok pola yang didukung, balas
 *      jujur "tidak ditemukan / tidak tersedia" — TIDAK PERNAH mengarang angka.
 *   2. Hormati batasan topik per grup (lihat permissions.js). Kalau grup ini
 *      dilarang tahu topik tertentu (mis. harga/omzet), balas jujur "dibatasi"
 *      alih-alih menyembunyikan tanpa penjelasan.
 */
'use strict';
const { pg } = require('./db');
const { isAllowed } = require('./permissions');

const rupiah = (n) => 'Rp' + Math.round(Number(n || 0)).toLocaleString('id-ID');

const HELP = [
  '❓ Pertanyaan tidak dikenali, atau data tidak tersedia untuk topik ini.',
  '',
  'Perintah yang didukung:',
  '• stock <SKU>  (cth: stock MX-5011-2)',
  '• preorder <SKU>  (cth: preorder MX-5011-2)',
  '• preorder  (daftar PO pending)',
  '• omzet hari ini',
  '• omzet 7 hari',
  '• retur',
  '• stok menipis',
  '• dead stock',
  '• top produk',
].join('\n');

const denied = (topic) => `🚫 Maaf, topik "${topic}" dibatasi untuk grup ini.`;

async function handleQuery(text, groupJid) {
  const q = (text || '').trim().toLowerCase();
  if (!q) return HELP;

  try {
    // omzet hari ini
    if (/^omzet\s*(hari ini|hari|today)$/.test(q)) {
      if (!isAllowed(groupJid, 'omzet')) return denied('omzet');
      const rows = await pg('v_an_kpi', { select: 'omzet_hari_ini,order_hari_ini' });
      if (!rows.length) return '❌ Data omzet tidak tersedia (view v_an_kpi belum ada/kosong).';
      const k = rows[0];
      return `💰 Omzet hari ini: ${rupiah(k.omzet_hari_ini)}\n🧾 Order hari ini: ${k.order_hari_ini ?? 0}`;
    }

    // omzet 7 hari / minggu
    if (/^omzet\s*(7 hari|minggu|seminggu)$/.test(q)) {
      if (!isAllowed(groupJid, 'omzet')) return denied('omzet');
      const rows = await pg('v_an_kpi', { select: 'omzet_7hari,order_7hari' });
      if (!rows.length) return '❌ Data omzet tidak tersedia.';
      const k = rows[0];
      return `💰 Omzet 7 hari: ${rupiah(k.omzet_7hari)}\n🧾 Order 7 hari: ${k.order_7hari ?? 0}`;
    }

    // retur (jumlah & nilai retur — nilai retur bukan "harga produk", tetap diizinkan)
    if (/^retur/.test(q)) {
      const rows = await pg('v_an_kpi', { select: 'retur_7hari,nilai_retur_7hari' });
      if (!rows.length) return '❌ Data retur tidak tersedia.';
      const k = rows[0];
      return `↩️ Retur 7 hari: ${k.retur_7hari ?? 0} retur\n💸 Nilai retur: ${rupiah(k.nilai_retur_7hari)}`;
    }

    // stok menipis (qty saja, bukan harga -> selalu diizinkan)
    if (/^(stok menipis|restock|stock rendah|stock menipis)$/.test(q)) {
      const rows = await pg('v_an_low_stock', {
        select: 'item_code,stok,hari_tersisa', order: 'hari_tersisa.asc', limit: '5',
      });
      if (!rows.length) return '✅ Tidak ada SKU dengan stok kritis saat ini (atau view belum tersedia).';
      const list = rows.map((r) => `• ${r.item_code} — sisa ${r.stok} (${r.hari_tersisa ?? '?'} hari)`).join('\n');
      return `⚠️ Stok menipis (top 5):\n${list}`;
    }

    // dead stock (modal_nyangkut = nilai Rupiah -> masuk kategori "harga")
    if (/^dead ?stock$/.test(q)) {
      if (!isAllowed(groupJid, 'harga')) return denied('harga (dead stock menampilkan nilai modal)');
      const rows = await pg('v_an_dead_stock', { select: 'item_code,modal_nyangkut', limit: '1000' });
      if (!rows.length) return '✅ Tidak ada dead stock saat ini (atau view belum tersedia).';
      const total = rows.reduce((s, r) => s + Number(r.modal_nyangkut || 0), 0);
      return `🧊 Dead stock: ${rows.length} SKU\nTotal modal nyangkut: ${rupiah(total)}`;
    }

    // top produk (qty saja, bukan omzet per item -> selalu diizinkan)
    if (/^(top produk|top seller|terlaris)$/.test(q)) {
      const rows = await pg('v_an_top_sku', { select: 'item_code,qty', order: 'qty.desc', limit: '5' });
      if (!rows.length) return '❌ Data penjualan tidak tersedia.';
      const list = rows.map((r, i) => `${i + 1}. ${r.item_code} — ${r.qty} pcs`).join('\n');
      return `🏆 Top 5 produk terlaris (30 hari):\n${list}`;
    }

    // preorder <SKU> atau preorder (daftar pending)
    let mpo = q.match(/^(preorder|po)\s*(.*)$/);
    if (mpo) {
      const sku = mpo[2].trim();
      if (sku) {
        const rows = await pg('preorder_stocks', {
          select: 'purchaseorder_no,item_code,qty_po,qty_fulfilled,qty_pending,location_name',
          item_code: `ilike.${sku}`,
          order: 'qty_pending.desc',
          limit: '5',
        });
        if (!rows.length) return `❌ Tidak ada data preorder untuk SKU "${sku}".`;
        const list = rows.map((r) =>
          `• PO ${r.purchaseorder_no} — dipesan:${r.qty_po ?? 0} diterima:${r.qty_fulfilled ?? 0} pending:${r.qty_pending ?? 0} (${r.location_name || 'gudang tidak diketahui'})`
        ).join('\n');
        return `📥 Preorder ${sku.toUpperCase()}:\n${list}`;
      }
      const rows = await pg('preorder_stocks', {
        select: 'item_code,qty_pending', order: 'qty_pending.desc', limit: '5',
      });
      if (!rows.length) return '✅ Tidak ada preorder yang masih pending saat ini.';
      const list = rows.map((r) => `• ${r.item_code} — pending ${r.qty_pending ?? 0}`).join('\n');
      return `📥 Top 5 preorder pending:\n${list}`;
    }

    // stock <SKU> — fallback TERAKHIR (setelah semua frasa tetap tidak match),
    // supaya "stok menipis" dll tidak ketangkep sebagai pencarian SKU "menipis".
    let m = q.match(/^(stock|stok)\s+(.+)$/);
    if (m) {
      const sku = m[2].trim();
      const rows = await pg('products', {
        select: 'item_code,item_name,total_available,last_cogs',
        item_code: `ilike.${sku}`,
        limit: '1',
      });
      if (!rows.length) return `❌ SKU "${sku}" tidak ditemukan di database.`;
      const p = rows[0];
      const hargaLine = isAllowed(groupJid, 'harga')
        ? `\nHPP: ${p.last_cogs ? rupiah(p.last_cogs) : 'tidak ada data'}`
        : '';
      return `📦 ${p.item_code} — ${p.item_name || '(tanpa nama)'}\nStok tersedia: ${p.total_available ?? 0} pcs${hargaLine}`;
    }

    return HELP;
  } catch (e) {
    console.error('[query-handler] error:', e.message);
    return `⚠️ Gagal mengambil data: ${e.message}`;
  }
}

module.exports = { handleQuery };
