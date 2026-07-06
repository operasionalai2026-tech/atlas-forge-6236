"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import Logo from "@/app/components/Logo";

// select = query PostgREST (boleh embed relasi), cols = kolom yang ditampilkan
// (boleh path bertitik utk relasi, mis. "products.item_code"), order = urutan.
const TABLES = {
  orders: {
    label: "Orders",
    select: "salesorder_no,source_name,store_name,grand_total,escrow_amount,status,transaction_date",
    cols: ["salesorder_no","source_name","store_name","grand_total","escrow_amount","status","transaction_date"],
    order: "transaction_date.desc",
  },
  products: {
    label: "Products",
    select: "item_code,item_name,last_cogs,total_available,weight_gram,item_group_name,brand_name",
    cols: ["item_code","item_name","last_cogs","total_available","weight_gram","item_group_name","brand_name"],
  },
  order_items: {
    label: "Order Items",
    select: "salesorder_no,item_code,item_name,variant,qty,price,disc_amount,amount",
    cols: ["salesorder_no","item_code","item_name","variant","qty","price","disc_amount","amount"],
  },
  product_stocks: {
    label: "Stok/Gudang",
    select: "item_id,location_id,location_code,on_hand,on_order,reserved,available,products(item_code,item_name)",
    cols: ["products.item_code","products.item_name","location_code","on_hand","available","on_order","reserved"],
  },
  preorder_stocks: {
    label: "Preorder (PO)",
    select: "purchaseorder_no,item_code,item_name,qty_po,qty_fulfilled,qty_pending,location_name",
    cols: ["purchaseorder_no","item_code","item_name","qty_po","qty_fulfilled","qty_pending","location_name"],
  },
  sales_returns: {
    label: "Retur",
    select: "doc_number,salesorder_id,customer_name,store_name,grand_total,return_type,transaction_date",
    cols: ["doc_number","customer_name","store_name","grand_total","return_type","transaction_date"],
    order: "transaction_date.desc",
  },
  sync_log: {
    label: "Sync Log",
    select: "run_id,module,status,records_processed,records_failed,started_at,finished_at,error_message",
    cols: ["module","status","records_processed","records_failed","started_at","finished_at","error_message"],
    order: "started_at.desc",
  },
};

// label kolom bahasa manusia (fallback ke nama asli)
const LABELS = {
  salesorder_no: "No Order", source_name: "Channel", store_name: "Toko",
  grand_total: "Total", escrow_amount: "Settlement", status: "Status",
  transaction_date: "Tanggal", item_code: "SKU", item_name: "Nama Produk",
  last_cogs: "HPP", total_available: "Stok", weight_gram: "Berat (g)",
  item_group_name: "Kategori", brand_name: "Brand", variant: "Varian",
  qty: "Qty", price: "Harga", disc_amount: "Diskon", amount: "Subtotal",
  location_code: "Gudang", location_name: "Gudang", on_hand: "Fisik",
  available: "Tersedia", on_order: "On Order", reserved: "Reserved",
  purchaseorder_no: "No PO", qty_po: "Qty PO", qty_fulfilled: "Diterima",
  qty_pending: "Pending", module: "Modul", records_processed: "Diproses",
  records_failed: "Gagal", started_at: "Mulai", finished_at: "Selesai",
  error_message: "Keterangan", run_id: "Run ID",
  doc_number: "No Retur", customer_name: "Pembeli", return_type: "Tipe Retur",
  salesorder_id: "Order ID",
};
// kolom bernilai uang → format Rupiah
const MONEY = new Set(["grand_total", "escrow_amount", "last_cogs", "price", "disc_amount", "amount"]);

// ambil nilai kolom (dukung path bertitik utk relasi embed)
function getVal(row, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), row);
}
// key kolom = segmen terakhir dari path; label = versi rapih
function colKey(path) {
  const p = path.split(".");
  return p[p.length - 1];
}
function colLabel(path) {
  const k = colKey(path);
  return LABELS[k] || k;
}

const STAT_TABLES = ["orders", "order_items", "products", "product_stocks", "preorder_stocks", "sales_returns"];
const STAT_LABEL = { orders: "Orders", order_items: "Order Items", products: "Products", product_stocks: "Stok Gudang", preorder_stocks: "Preorder", sales_returns: "Retur" };
const STAT_ICON = { orders: "🧾", order_items: "📦", products: "🎁", product_stocks: "🏬", preorder_stocks: "🚚", sales_returns: "↩️" };

function rupiah(n) {
  return "Rp" + Number(n).toLocaleString("id-ID");
}

function fmtCell(key, val) {
  if (val === null || val === undefined || val === "") return <span className="cnull">—</span>;
  if (key === "status") {
    const v = String(val).toUpperCase();
    let c = "b-pending";
    if (v.includes("COMPLET") || v.includes("SUCCESS") || v === "OK") c = "b-ok";
    else if (v.includes("CANCEL") || v.includes("BATAL") || v.includes("FAIL")) c = "b-cancel";
    return <span className={"badge " + c}>{val}</span>;
  }
  if (key === "error_message")
    return <span className="errmsg" title={String(val)}>{String(val)}</span>;
  if (MONEY.has(key) && typeof val === "number")
    return <span className="cnum">{rupiah(val)}</span>;
  if (typeof val === "number") return <span className="cnum">{val.toLocaleString("id-ID")}</span>;
  if (typeof val === "string" && /^\d{4}-\d{2}-\d{2}T/.test(val))
    return <span className="cdate">{new Date(val).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })}</span>;
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
  const [sync, setSync] = useState({ state: "idle", msg: "" }); // idle|running|done|error
  const [lastSync, setLastSync] = useState(null);
  const pollRef = useRef(null);

  const loadStats = useCallback(async () => {
    const out = {};
    for (const t of STAT_TABLES) {
      const { count } = await supabase.from(t).select("*", { count: "exact", head: true });
      out[t] = count;
    }
    setStats(out);
    const { data } = await supabase
      .from("sync_log")
      .select("module,status,finished_at,records_processed")
      .order("started_at", { ascending: false })
      .limit(1);
    setLastSync(data && data[0] ? data[0] : null);
  }, [supabase]);

  const loadTable = useCallback(async (t) => {
    setLoading(true);
    const cfg = TABLES[t];
    let query = supabase.from(t).select(cfg.select);
    if (cfg.order) {
      const [col, dir] = cfg.order.split(".");
      query = query.order(col, { ascending: dir !== "desc", nullsFirst: false });
    }
    const { data, error } = await query.limit(500);
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

  // ── Sync manual (memicu GitHub Actions di cloud) ──
  function pollSync() {
    let tries = 0;
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      tries++;
      try {
        const d = await (await fetch("/api/sync", { cache: "no-store" })).json();
        if (d.status === "completed") {
          clearInterval(pollRef.current);
          const ok = d.conclusion === "success";
          setSync({ state: ok ? "done" : "error", msg: ok ? "Sync selesai ✓" : "Sync gagal" });
          loadStats();
          loadTable(cur);
        } else if (d.status) {
          setSync({ state: "running", msg: "Sync berjalan di cloud… (" + d.status + ")" });
        }
      } catch {
        /* abaikan error polling sesaat */
      }
      if (tries > 80) clearInterval(pollRef.current); // stop ~6-7 mnt
    }, 5000);
  }

  async function runSync(mode, label) {
    setSync({ state: "running", msg: "Memulai " + label + "…" });
    try {
      const r = await fetch("/api/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        setSync({ state: "error", msg: "Gagal: " + (e.error || r.status) });
        return;
      }
      setSync({ state: "running", msg: label + " berjalan di cloud…" });
      setTimeout(pollSync, 4000); // beri jeda agar run terdaftar dulu
    } catch (e) {
      setSync({ state: "error", msg: "Gagal: " + e.message });
    }
  }

  useEffect(() => () => clearInterval(pollRef.current), []);

  const cols = TABLES[cur].cols;
  const shown = !q
    ? rows
    : rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="wrap">
      <header className="hdr">
        <div className="brand">
          <Logo size={44} />
          <div>
            <h1>Beverra Central</h1>
            <p>Integrasi Jubelio → Supabase · auto-sync tiap 30 menit</p>
          </div>
        </div>
        <div className="user">
          <div className="nav">
            <span className="navlink active">📊 Data</span>
            <Link href="/analytics" className="navlink">📈 Analitik</Link>
          </div>
          <div style={{ fontSize: 12, opacity: 0.9 }}>👤 {email}</div>
          <button className="btn-out" onClick={logout}>Keluar</button>
        </div>
      </header>

      <div className="synccard">
        <div className="sync-left">
          <b>🔄 Sync Manual</b>
          <span className={"sync-status s-" + sync.state}>
            {sync.state !== "idle"
              ? sync.msg
              : lastSync
              ? `Terakhir: ${lastSync.module} · ${lastSync.status} · ${
                  lastSync.finished_at
                    ? new Date(lastSync.finished_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" })
                    : "—"
                }`
              : "Otomatis tiap 30 menit"}
          </span>
        </div>
        <div className="sync-btns">
          <button
            className="btn-sync fast"
            disabled={sync.state === "running"}
            onClick={() => runSync("--orders --stock-only", "Sync cepat")}
          >
            ⚡ Sync Cepat
          </button>
          <button
            className="btn-sync full"
            disabled={sync.state === "running"}
            onClick={() => runSync("--all --report-stock --report-trend", "Sync penuh")}
          >
            ✨ Sync Penuh
          </button>
        </div>
      </div>

      <div className="stats">
        {STAT_TABLES.map((t, i) => (
          <div className={"stat" + (i % 2 ? " pink" : "")} key={t}>
            <div className="label">{STAT_LABEL[t]}</div>
            <div className="num">
              {stats[t] == null ? "…" : Number(stats[t]).toLocaleString("id-ID")}
            </div>
            <div className="stat-ic">{STAT_ICON[t]}</div>
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
                <tr>{cols.map((c) => <th key={c}>{colLabel(c)}</th>)}</tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={i}>
                    {cols.map((c) => <td key={c}>{fmtCell(colKey(c), getVal(r, c))}</td>)}
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
