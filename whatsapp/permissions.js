/**
 * permissions.js — batasan topik per grup WhatsApp.
 *
 * Grup yang TIDAK terdaftar di sini -> semua topik diizinkan (default longgar).
 * Tambahkan entri baru untuk membatasi grup lain di masa depan.
 */
'use strict';

const GROUP_RESTRICTIONS = {
  // Grup "Testing" — dilarang tahu harga (HPP/modal) & omzet, boleh tanya stok/preorder/retur.
  '120363413555722826@g.us': { deny: ['harga', 'omzet'] },
};

function isAllowed(groupJid, topic) {
  const cfg = GROUP_RESTRICTIONS[groupJid];
  if (!cfg) return true;
  return !cfg.deny.includes(topic);
}

module.exports = { isAllowed };
