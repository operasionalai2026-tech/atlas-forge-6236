"""BVR-DB Dashboard — Flask server (tema putih/biru/pink)
Data viewer + kontrol sync + laporan, semua via backend (key tidak di client).
"""
from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))
from bvr_sync import config  # baca kredensial dari file `env` (service_role, server-side)

app = Flask(__name__)
CORS(app)
PY = sys.executable  # python yang menjalankan server ini


def _supabase():
    """Pakai service_role dari env (bypass RLS). Hanya dipakai di backend —
    key TIDAK pernah dikirim ke browser."""
    from supabase import create_client
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


@app.route("/api/sync", methods=["POST"])
def trigger_sync():
    cmd = request.json.get("cmd", "--all")
    try:
        result = subprocess.run(
            [PY, str(PROJECT_DIR / "run_sync.py")] + cmd.split(),
            cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=3600,
        )
        return jsonify({
            "ok": result.returncode == 0, "command": cmd,
            "stdout": (result.stdout[-1500:] if result.stdout else ""),
            "stderr": (result.stderr[-500:] if result.stderr else ""),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stats")
def stats():
    tables = ["orders", "order_items", "products", "product_stocks", "preorder_stocks", "sync_log"]
    out = {}
    try:
        sb = _supabase()
        for t in tables:
            try:
                res = sb.table(t).select("*", count="exact").limit(1).execute()
                out[t] = res.count
            except Exception:
                out[t] = None
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table/<table>")
def fetch_table(table):
    cols = request.args.get("select", "*")
    limit = int(request.args.get("limit", "50"))
    try:
        sb = _supabase()
        data = sb.table(table).select(cols).limit(limit).execute()
        return jsonify(data.data if hasattr(data, "data") else data)
    except Exception as e:
        return jsonify({"error": str(e), "table": table}), 500


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BVR-DB Dashboard</title>
<style>
  :root{
    --blue:#2563eb; --blue-l:#3b82f6; --blue-soft:#eff4ff;
    --pink:#ec4899; --pink-l:#f472b6; --pink-soft:#fdf2f8;
    --bg:#f6f8fc; --card:#ffffff; --text:#1e293b; --muted:#64748b;
    --border:#e6ebf5; --green:#10b981; --amber:#f59e0b; --red:#ef4444;
    --shadow:0 1px 3px rgba(37,99,235,.06),0 8px 24px rgba(37,99,235,.06);
  }
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
  .wrap{max-width:1500px;margin:0 auto;padding:24px}

  header{background:linear-gradient(120deg,var(--blue) 0%,var(--pink) 100%);color:#fff;border-radius:18px;padding:26px 30px;box-shadow:var(--shadow);margin-bottom:22px}
  header h1{font-size:26px;font-weight:700;display:flex;align-items:center;gap:10px}
  header p{opacity:.92;font-size:13px;margin-top:4px}

  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:22px}
  .stat{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;box-shadow:var(--shadow);position:relative;overflow:hidden}
  .stat::before{content:'';position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--blue)}
  .stat.pink::before{background:var(--pink)}
  .stat .label{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.4px}
  .stat .num{font-size:30px;font-weight:800;margin-top:6px;color:var(--text)}
  .stat .ic{position:absolute;right:16px;top:16px;font-size:24px;opacity:.35}

  .grid2{display:grid;grid-template-columns:1.3fr 1fr;gap:22px;margin-bottom:22px}
  @media(max-width:1000px){.grid2{grid-template-columns:1fr}}

  .card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;box-shadow:var(--shadow)}
  .card h2{font-size:16px;font-weight:700;margin-bottom:16px;display:flex;align-items:center;gap:8px}
  .card h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--blue)}
  .card.pink h2 .dot{background:var(--pink)}

  .btns{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .btn{padding:11px 14px;border:none;border-radius:10px;cursor:pointer;font-weight:600;font-size:13px;transition:.15s;display:flex;align-items:center;justify-content:center;gap:6px}
  .btn:hover{transform:translateY(-1px);box-shadow:0 6px 16px rgba(37,99,235,.18)}
  .btn:active{transform:translateY(0)}
  .btn-blue{background:var(--blue);color:#fff}
  .btn-blue-o{background:var(--blue-soft);color:var(--blue);border:1px solid #dbe7ff}
  .btn-pink{background:var(--pink);color:#fff}
  .btn-pink-o{background:var(--pink-soft);color:var(--pink);border:1px solid #fbd6e8}
  .btn-amber{background:#fff7ed;color:#c2680c;border:1px solid #fde3c4}
  .btn-green{background:#ecfdf5;color:#047857;border:1px solid #c3f0dd}
  .btn.full{grid-column:1/-1}
  .divider{grid-column:1/-1;height:1px;background:var(--border);margin:4px 0}

  .out{margin-top:14px;background:#0f1b33;color:#a5e6b8;border-radius:10px;padding:14px;font-family:'Consolas',monospace;font-size:12px;max-height:220px;overflow:auto;white-space:pre-wrap;display:none}
  .out.show{display:block}
  .out.err{color:#ffb4b4}

  .status-item{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border:1px solid var(--border);border-radius:10px;margin-bottom:9px;font-size:13px}
  .pill{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}
  .pill.on{background:#ecfdf5;color:#047857}
  .pill.off{background:#fef2f2;color:#b91c1c}
  .pill.wait{background:#fff7ed;color:#c2680c}

  .viewer{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px;box-shadow:var(--shadow)}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px;border-bottom:2px solid var(--border);padding-bottom:2px}
  .tab{padding:9px 16px;cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);border-radius:9px 9px 0 0;border-bottom:3px solid transparent;margin-bottom:-2px}
  .tab:hover{color:var(--blue);background:var(--blue-soft)}
  .tab.active{color:var(--pink);border-bottom-color:var(--pink)}

  .toolbar{display:flex;gap:12px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
  .search{padding:9px 14px;border:1px solid var(--border);border-radius:10px;font-size:13px;width:240px;outline:none;transition:.15s}
  .search:focus{border-color:var(--blue-l);box-shadow:0 0 0 3px var(--blue-soft)}
  .rowcount{font-size:12px;color:var(--muted)}

  .tblwrap{overflow:auto;max-height:520px;border:1px solid var(--border);border-radius:12px}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  thead th{position:sticky;top:0;background:var(--blue-soft);color:var(--blue);padding:11px 12px;text-align:left;font-weight:700;white-space:nowrap;border-bottom:1px solid var(--border)}
  tbody td{padding:9px 12px;border-bottom:1px solid #f1f5f9;white-space:nowrap;max-width:280px;overflow:hidden;text-overflow:ellipsis}
  tbody tr:nth-child(even){background:#fafbff}
  tbody tr:hover{background:var(--pink-soft)}
  .num{color:var(--blue);font-weight:600}
  .null{color:#cbd5e1;font-style:italic}
  .badge{padding:3px 9px;border-radius:6px;font-size:11px;font-weight:700}
  .b-ok{background:#ecfdf5;color:#047857}.b-cancel{background:#fef2f2;color:#b91c1c}.b-pending{background:#fff7ed;color:#c2680c}

  .loading{text-align:center;padding:40px;color:var(--muted)}
  .footer{text-align:center;color:var(--muted);font-size:12px;margin-top:26px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📊 BVR-DB Dashboard</h1>
    <p>Integrasi Jubelio → Supabase · kontrol sync, laporan & data viewer</p>
  </header>

  <!-- STAT CARDS -->
  <div class="stats" id="stats">
    <div class="stat"><div class="label">Orders</div><div class="num" id="s-orders">…</div><div class="ic">🧾</div></div>
    <div class="stat pink"><div class="label">Products</div><div class="num" id="s-products">…</div><div class="ic">🎁</div></div>
    <div class="stat"><div class="label">Order Items</div><div class="num" id="s-order_items">…</div><div class="ic">📦</div></div>
    <div class="stat pink"><div class="label">Preorder (PO)</div><div class="num" id="s-preorder_stocks">…</div><div class="ic">🚚</div></div>
    <div class="stat"><div class="label">Sync Log</div><div class="num" id="s-sync_log">…</div><div class="ic">📜</div></div>
  </div>

  <div class="grid2">
    <!-- SYNC CONTROL -->
    <div class="card">
      <h2><span class="dot"></span> Kontrol Sync</h2>
      <div class="btns">
        <button class="btn btn-blue" onclick="runSync('--products')">📦 Master Produk</button>
        <button class="btn btn-blue-o" onclick="runSync('--stock-only')">📊 HPP + Stok (cepat)</button>
        <button class="btn btn-blue" onclick="runSync('--orders --lookback-days 7')">🧾 Order (7 hari)</button>
        <button class="btn btn-blue-o" onclick="runSync('--preorder')">🚚 PO / Inbound</button>
        <button class="btn btn-pink full" onclick="runSync('--all')">✨ Sync Semua</button>
        <div class="divider"></div>
        <button class="btn btn-amber" onclick="runSync('--report-stock')">⚠️ Alert Stok (WA)</button>
        <button class="btn btn-green" onclick="runSync('--report-trend')">📈 Alert Tren (WA)</button>
        <button class="btn btn-blue-o full" onclick="runSync('--check')">🔍 Cek Koneksi</button>
      </div>
      <div class="out" id="out"></div>
    </div>

    <!-- STATUS -->
    <div class="card pink">
      <h2><span class="dot"></span> Status Sistem</h2>
      <div class="status-item"><span>🔗 Supabase</span><span class="pill on">Terhubung</span></div>
      <div class="status-item"><span>🟢 Jubelio API</span><span class="pill on">Aktif</span></div>
      <div class="status-item"><span>💬 Fonnte (WhatsApp)</span><span class="pill wait" id="p-fonnte">Cek…</span></div>
      <div class="status-item"><span>⏰ Scheduler (Task)</span><span class="pill off" id="p-sched">Belum diset</span></div>
      <div style="margin-top:14px;font-size:12px;color:var(--muted);line-height:1.7">
        <b>Saran jadwal:</b><br>
        • Order tiap 15 mnt · Stok+HPP tiap 2 jam<br>
        • Master produk 1×/hari · Alert stok tiap 3 jam<br>
        • Alert tren tiap 1 jam
      </div>
    </div>
  </div>

  <!-- DATA VIEWER -->
  <div class="viewer">
    <h2 style="font-size:16px;font-weight:700;margin-bottom:16px">📚 Data Viewer</h2>
    <div class="tabs" id="tabs"></div>
    <div class="toolbar">
      <input class="search" id="search" placeholder="🔍 Cari dalam tabel…">
      <span class="rowcount" id="rowcount"></span>
      <button class="btn btn-blue-o" style="padding:8px 14px" onclick="loadTable(cur)">🔄 Refresh</button>
    </div>
    <div id="tbl" class="tblwrap"><div class="loading">Memuat…</div></div>
  </div>

  <div class="footer">BVR-DB · dibuat untuk BEVERRA · data real-time dari Supabase</div>
</div>

<script>
const TABLES = {
  orders:          {label:'Orders',        cols:'salesorder_no,source_name,store_name,grand_total,escrow_amount,status,transaction_date'},
  products:        {label:'Products',      cols:'item_code,item_name,last_cogs,total_available,weight_gram,item_group_name,brand_name'},
  order_items:     {label:'Order Items',   cols:'salesorder_no,item_code,item_name,variant,qty,price,disc_amount,amount'},
  product_stocks:  {label:'Stok/Gudang',   cols:'item_id,location_id,location_code,on_hand,available,reserved'},
  preorder_stocks: {label:'Preorder (PO)', cols:'purchaseorder_no,item_code,item_name,qty_po,qty_fulfilled,qty_pending,location_name'},
  sync_log:        {label:'Sync Log',      cols:'run_id,module,status,records_processed,records_failed,finished_at'},
};
let cur='orders', rawData=[];

// ── stats ──
async function loadStats(){
  try{
    const r=await fetch('/api/stats'); const d=await r.json();
    for(const k in d){ const el=document.getElementById('s-'+k); if(el) el.textContent = d[k]==null?'—':Number(d[k]).toLocaleString('id-ID'); }
  }catch(e){}
}

// ── sync ──
async function runSync(cmd){
  const o=document.getElementById('out'); o.className='out show'; o.textContent='⏳ Menjalankan: '+cmd+' …';
  try{
    const r=await fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})});
    const d=await r.json();
    o.className='out show'+(d.ok?'':' err');
    o.textContent=(d.ok?'✅ SELESAI':'❌ GAGAL')+' — '+cmd+'\n\n'+(d.stdout||'')+(d.stderr?('\n[ERR]\n'+d.stderr):'');
    loadStats(); loadTable(cur);
  }catch(e){ o.className='out show err'; o.textContent='❌ '+e.message; }
}

// ── tabs ──
function buildTabs(){
  const t=document.getElementById('tabs'); t.innerHTML='';
  for(const k in TABLES){
    const d=document.createElement('div'); d.className='tab'+(k===cur?' active':''); d.textContent=TABLES[k].label;
    d.onclick=()=>{cur=k; document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); d.classList.add('active'); document.getElementById('search').value=''; loadTable(k);};
    t.appendChild(d);
  }
}

// ── table ──
function fmtCell(col,val){
  if(val===null||val===undefined) return '<span class="null">NULL</span>';
  if(col==='status'){ const v=String(val).toUpperCase(); let c='b-pending';
    if(v.includes('COMPLET')||v==='OK') c='b-ok'; else if(v.includes('CANCEL')||v.includes('BATAL')) c='b-cancel';
    return '<span class="badge '+c+'">'+val+'</span>'; }
  if(typeof val==='number') return '<span class="num">'+val.toLocaleString('id-ID')+'</span>';
  if(typeof val==='string' && /^\d{4}-\d{2}-\d{2}T/.test(val)) return new Date(val).toLocaleString('id-ID');
  return String(val);
}
function render(rows){
  const box=document.getElementById('tbl');
  if(!rows.length){ box.innerHTML='<div class="loading">📭 Tabel kosong</div>'; document.getElementById('rowcount').textContent=''; return; }
  const cols=TABLES[cur].cols.split(',');
  let h='<table><thead><tr>'+cols.map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>';
  rows.forEach(r=>{ h+='<tr>'+cols.map(c=>'<td>'+fmtCell(c,r[c])+'</td>').join('')+'</tr>'; });
  box.innerHTML=h+'</tbody></table>';
  document.getElementById('rowcount').textContent='Menampilkan '+rows.length+' baris';
}
async function loadTable(t){
  cur=t; const box=document.getElementById('tbl'); box.innerHTML='<div class="loading">Memuat…</div>';
  try{
    const r=await fetch('/api/table/'+t+'?select='+encodeURIComponent(TABLES[t].cols)+'&limit=200');
    const d=await r.json();
    if(d.error){ box.innerHTML='<div class="loading">⚠️ '+d.error+'</div>'; return; }
    rawData=d; render(d);
  }catch(e){ box.innerHTML='<div class="loading">❌ '+e.message+'</div>'; }
}
document.getElementById('search').addEventListener('input',e=>{
  const q=e.target.value.toLowerCase();
  render(!q?rawData:rawData.filter(row=>Object.values(row).some(v=>String(v).toLowerCase().includes(q))));
});

buildTabs(); loadTable('orders'); loadStats();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
