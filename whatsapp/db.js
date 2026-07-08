/**
 * db.js — koneksi ringan ke Supabase (REST/PostgREST) dari Node.js.
 * Baca kredensial dari file `env` (root proyek) — sama seperti notify.js.
 */
'use strict';
const fs = require('fs');
const path = require('path');

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
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    store[key] = val;
  }
}

const projectRoot = path.join(__dirname, '..');
const fileStore = {};
loadEnvFile(path.join(projectRoot, 'env'), fileStore);
loadEnvFile(path.join(projectRoot, '.env'), fileStore);
const get = (k, d) => (process.env[k] != null ? process.env[k] : (fileStore[k] != null ? fileStore[k] : d));

const SUPABASE_URL = get('SUPABASE_URL');
const SUPABASE_KEY = get('SUPABASE_SERVICE_ROLE_KEY') || get('SUPABASE_KEY');

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.warn('[db.js] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY belum diisi di env — query akan gagal.');
}

/** SELECT sederhana lewat PostgREST. params = query string PostgREST (select, filter, order, limit, dll). */
async function pg(table, params) {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${qs}`, {
    headers: { apikey: SUPABASE_KEY, Authorization: `Bearer ${SUPABASE_KEY}` },
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Supabase ${table} gagal [${res.status}]: ${body.slice(0, 200)}`);
  }
  return res.json();
}

module.exports = { pg };
