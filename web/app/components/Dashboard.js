"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const TABLES = {
  orders:          { label: "Orders",        cols: ["salesorder_no","source_name","store_name","grand_total","escrow_amount","status","transaction_date"] },
  products:        { label: "Products",      cols: ["item_code","item_name","last_cogs","total_available","weight_gram","item_group_name","brand_name"] },
  order_items:     { label: "Order Items",   cols: ["salesorder_no","item_code","item_name","variant","qty","price","disc_amount","amount"] },
  product_stocks:  { label: "Stok/Gudang",   cols: ["item_id","location_id","location_code","on_hand","available","reserved"] },
  preorder_stocks: { label: "Preorder (PO)", cols: ["purchaseorder_no","item_code","item_name","qty_po","qty_fulfilled","qty_pending","location_name"] },
  sync_log:        { label: "Sync Log",      cols: ["run_id","module","status","records_processed","records_failed","finished_at"] },
};

const STAT_TABLES = ["orders", "order_items", "products", "product_stocks", "preorder_stocks", "sync_log"];
const STAT_LABEL = { orders: "Orders", order_items: "Order Items", products: "Products", product_stocks: "Stok Gudang", preorder_stocks: "Preorder", sync_log: "Sync Log" };

function fmtCell(col, val) {
  if (val === null || val === undefined) return <span className="cnull">NULL</span>;
  if (col === "status") {
    const v = String(val).toUpperCase();
    let c = "b-pending";
    if (v.includes("COMPLET") || v === "OK") c = "b-ok";
    else if (v.includes("CANCEL") || v.includes("BATAL")) c = "b-cancel";
    return <span className={"badge " + c}>{val}</span>;
  }
  if (typeof val === "number") return <span className="cnum">{val.toLocaleString("id-ID")}</span>;
  if (typeof val === "string" && /^\d{4}-\d{2}-\d{2}T/.test(val))
    return new Date(val).toLocaleString("id-ID");
  return String(val);
}

export default function Dashboard({ email }) {
  const router = useRouter();
  const [supabase] = useState(() => createClient());
  const [stats, setStats] = useState({});
  const [cur, setCur] = useState("orders");
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  const loadStats = useCallback(async () => {
    const out = {};
    for (const t of STAT_TABLES) {
      const { count } = await supabase.from(t).select("*", { count: "exact", head: true });
      out[t] = count;
    }
    setStats(out);
  }, [supabase]);

  const loadTable = useCallback(async (t) => {
    setLoading(true);
    const { data, error } = await supabase
      .from(t)
      .select(TABLES[t].cols.join(","))
      .limit(200);
    setRows(error ? [] : data || []);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);
  useEffect(() => {
    loadTable(cur);
  }, [cur, loadTable]);

  async function logout() {
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  const cols = TABLES[cur].cols;
  const shown = !q
    ? rows
    : rows.filter((r) =>
        Object.values(r).some((v) => String(v).toLowerCase().includes(q.toLowerCase()))
      );

  return (
    <div className="wrap">
      <header className="hdr">
        <div>
          <h1>📊 BVR-DB Dashboard</h1>
          <p>Integrasi Jubelio → Supabase · data real-time</p>
        </div>
        <div className="user">
          <div>👤 {email}</div>
          <button className="btn-out" onClick={logout}>Keluar</button>
        </div>
      </header>

      <div className="stats">
        {STAT_TABLES.map((t, i) => (
          <div className={"stat" + (i % 2 ? " pink" : "")} key={t}>
            <div className="label">{STAT_LABEL[t]}</div>
            <div className="num">
              {stats[t] == null ? "…" : Number(stats[t]).toLocaleString("id-ID")}
            </div>
          </div>
        ))}
      </div>

      <div className="viewer">
        <h2>📚 Data Viewer</h2>
        <div className="tabs">
          {Object.keys(TABLES).map((t) => (
            <button
              key={t}
              className={"tab" + (t === cur ? " active" : "")}
              onClick={() => { setQ(""); setCur(t); }}
            >
              {TABLES[t].label}
            </button>
          ))}
        </div>
        <div className="toolbar">
          <input
            className="search"
            placeholder="🔍 Cari dalam tabel…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="rowcount">
            {loading ? "Memuat…" : `Menampilkan ${shown.length} baris`}
          </span>
        </div>
        <div className="tblwrap">
          {loading ? (
            <div className="loading">Memuat…</div>
          ) : shown.length === 0 ? (
            <div className="loading">📭 Tidak ada data</div>
          ) : (
            <table>
              <thead>
                <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={i}>
                    {cols.map((c) => <td key={c}>{fmtCell(c, r[c])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
