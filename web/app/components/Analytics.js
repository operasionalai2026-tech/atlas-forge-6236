"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import Logo from "@/app/components/Logo";
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";

const PIE = ["#2563eb", "#ec4899", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#64748b"];
const rupiah = (n) => "Rp" + Number(n || 0).toLocaleString("id-ID");
const rpShort = (n) => {
  n = Number(n || 0);
  if (n >= 1e9) return "Rp" + (n / 1e9).toFixed(1) + "M";
  if (n >= 1e6) return "Rp" + (n / 1e6).toFixed(1) + "jt";
  if (n >= 1e3) return "Rp" + (n / 1e3).toFixed(0) + "rb";
  return "Rp" + n;
};
const tgl = (s) => new Date(s).toLocaleDateString("id-ID", { day: "numeric", month: "short" });

export default function Analytics({ email }) {
  const router = useRouter();
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    (async () => {
      const sb = createClient();
      const kpi = await sb.from("v_an_kpi").select("*").single();
      if (kpi.error) {
        setErr(kpi.error.message);
        setD({});
        return;
      }
      const [daily, channel, top, low, bulk, dead] = await Promise.all([
        sb.from("v_an_daily_sales").select("*"),
        sb.from("v_an_channel").select("*"),
        sb.from("v_an_top_sku").select("*").limit(10),
        sb.from("v_an_low_stock").select("*"),
        sb.from("v_an_bulk").select("*"),
        sb.from("v_an_dead_stock").select("*"),
      ]);
      setD({
        kpi: kpi.data,
        daily: daily.data || [],
        channel: channel.data || [],
        top: (top.data || []).slice().reverse(),
        low: low.data || [],
        bulk: bulk.data || [],
        dead: dead.data || [],
      });
    })();
  }, []);

  async function logout() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  const modalTotal = (d?.dead || []).reduce((s, r) => s + Number(r.modal_nyangkut || 0), 0);

  return (
    <div className="wrap">
      <header className="hdr">
        <div className="brand">
          <Logo size={44} />
          <div>
            <h1>Beverra Central</h1>
            <p>Analitik — penunjang keputusan Marketing & Purchasing</p>
          </div>
        </div>
        <div className="user">
          <div className="nav">
            <Link href="/" className="navlink">📊 Data</Link>
            <span className="navlink active">📈 Analitik</span>
          </div>
          <button className="btn-out" onClick={logout}>Keluar</button>
        </div>
      </header>

      {err && (
        <div className="banner">
          ⚠️ View analitik belum dibuat. Jalankan <b>supabase_analytics.sql</b> di Supabase → SQL Editor. <span className="dim">({err})</span>
        </div>
      )}

      {!d ? (
        <div className="loading" style={{ background: "#fff", borderRadius: 16 }}>Memuat analitik…</div>
      ) : (
        <>
          {/* KPI */}
          <div className="stats">
            <div className="stat"><div className="label">Omzet Hari Ini</div><div className="num">{rpShort(d.kpi?.omzet_hari_ini)}</div><div className="stat-ic">💰</div></div>
            <div className="stat pink"><div className="label">Order Hari Ini</div><div className="num">{Number(d.kpi?.order_hari_ini || 0).toLocaleString("id-ID")}</div><div className="stat-ic">🧾</div></div>
            <div className="stat"><div className="label">Omzet 7 Hari</div><div className="num">{rpShort(d.kpi?.omzet_7hari)}</div><div className="stat-ic">📈</div></div>
            <div className="stat pink"><div className="label">SKU Menipis</div><div className="num">{Number(d.kpi?.sku_menipis || 0).toLocaleString("id-ID")}</div><div className="stat-ic">⚠️</div></div>
            <div className="stat"><div className="label">Dead Stock</div><div className="num">{Number(d.kpi?.sku_dead || 0).toLocaleString("id-ID")}</div><div className="stat-ic">🧊</div></div>
          </div>

          {/* MARKETING */}
          <h2 className="sect">📣 Marketing — Penjualan</h2>
          <div className="grid2">
            <div className="card">
              <h3>Tren Penjualan 14 Hari</h3>
              {mounted && (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={d.daily} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f9" />
                    <XAxis dataKey="tgl" tickFormatter={tgl} fontSize={11} stroke="#94a3b8" />
                    <YAxis tickFormatter={rpShort} fontSize={11} stroke="#94a3b8" width={54} />
                    <Tooltip formatter={(v) => rupiah(v)} labelFormatter={tgl} />
                    <Line type="monotone" dataKey="omzet" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
            <div className="card">
              <h3>Omzet per Channel (30 hari)</h3>
              {mounted && (
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie data={d.channel} dataKey="omzet" nameKey="channel" cx="50%" cy="50%" outerRadius={90} label={(e) => e.channel}>
                      {d.channel.map((_, i) => <Cell key={i} fill={PIE[i % PIE.length]} />)}
                    </Pie>
                    <Tooltip formatter={(v) => rupiah(v)} />
                  </PieChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="card" style={{ marginTop: 22 }}>
            <h3>Top 10 SKU Terlaris (30 hari)</h3>
            {mounted && (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={d.top} layout="vertical" margin={{ top: 4, right: 20, left: 10, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f9" horizontal={false} />
                  <XAxis type="number" fontSize={11} stroke="#94a3b8" />
                  <YAxis type="category" dataKey="item_code" width={90} fontSize={11} stroke="#94a3b8" />
                  <Tooltip formatter={(v, n) => (n === "qty" ? v + " pcs" : rupiah(v))} />
                  <Bar dataKey="qty" fill="#ec4899" radius={[0, 5, 5, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="card" style={{ marginTop: 22 }}>
            <h3>🛒 Barang Diborong (qty ≥ 10 / order, 30 hari)</h3>
            <TableList
              rows={d.bulk}
              empty="Belum ada pembelian borongan"
              cols={[
                ["tgl", "Tanggal", (v) => new Date(v).toLocaleDateString("id-ID", { dateStyle: "medium" })],
                ["channel", "Channel"],
                ["item_code", "SKU"],
                ["item_name", "Nama", (v) => <span className="ell">{v}</span>],
                ["qty", "Qty", (v) => <b className="cnum">{v}</b>],
                ["customer_name", "Pembeli", (v) => <span className="ell">{v || "—"}</span>],
              ]}
            />
          </div>

          {/* PURCHASING */}
          <h2 className="sect">📦 Purchasing — Stok</h2>
          <div className="grid2">
            <div className="card">
              <h3>⚠️ Stok Menipis (&lt; 7 hari)</h3>
              <TableList
                rows={d.low}
                empty="Aman — tidak ada stok kritis"
                cols={[
                  ["item_code", "SKU"],
                  ["item_name", "Nama", (v) => <span className="ell">{v}</span>],
                  ["stok", "Stok", (v) => <b className="cnum">{v}</b>],
                  ["jual_harian", "Jual/hari"],
                  ["hari_tersisa", "Sisa (hari)", (v) => <span className={"badge " + (v <= 3 ? "b-cancel" : "b-pending")}>{v}</span>],
                ]}
              />
            </div>
            <div className="card">
              <h3>🧊 Dead Stock — Modal Nyangkut: <span className="cnum">{rupiah(modalTotal)}</span></h3>
              <TableList
                rows={d.dead}
                empty="Tidak ada dead stock"
                cols={[
                  ["item_code", "SKU"],
                  ["item_name", "Nama", (v) => <span className="ell">{v}</span>],
                  ["stok", "Stok", (v) => <b className="cnum">{v}</b>],
                  ["modal_nyangkut", "Modal", (v) => rupiah(v)],
                ]}
              />
            </div>
          </div>
          <div style={{ height: 30 }} />
        </>
      )}
    </div>
  );
}

function TableList({ rows, cols, empty }) {
  if (!rows || rows.length === 0) return <div className="loading">📭 {empty}</div>;
  return (
    <div className="tblwrap" style={{ maxHeight: 340 }}>
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c[0]}>{c[1]}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c[0]}>{c[2] ? c[2](r[c[0]]) : (r[c[0]] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
