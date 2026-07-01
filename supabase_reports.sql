-- ════════════════════════════════════════════════════════════════════════════
--  BVR-DB — Views untuk LAPORAN & ALERT (Stok + Tren/Borongan)
--  Jalankan di Supabase SQL Editor SETELAH supabase_schema.sql.
--  Idempotent (create or replace).
-- ════════════════════════════════════════════════════════════════════════════

-- ── Channel ternormalisasi ───────────────────────────────────────────────────
-- PENTING: TikTok Shop di akun ini masuk sebagai 'Shop | Tokopedia' (merged),
-- dibedakan dari prefix nomor order: TT-=TikTok, SP-=Shopee.
create or replace view public.v_orders_channel as
select
    o.*,
    case
        when o.salesorder_no ilike 'TT-%'                               then 'TIKTOK'
        when o.salesorder_no ilike 'SP-%' or o.source_name = 'SHOPEE'   then 'SHOPEE'
        when o.source_name ilike '%lazada%'                             then 'LAZADA'
        when o.salesorder_no ilike 'AKL-%' or o.source_name ilike '%akulaku%' then 'AKULAKU'
        when o.source_name ilike '%tokopedia%'                         then 'TOKOPEDIA'
        else coalesce(o.source_name, 'LAINNYA')
    end as channel
from public.orders o;

-- ── VELOCITY & DAYS OF COVER (inti alert stok) ───────────────────────────────
-- Kecepatan jual 14 hari → prediksi "stok tinggal berapa hari".
create or replace view public.v_sales_velocity as
with sales as (
    select
        oi.item_code,
        sum(oi.qty) filter (where o.transaction_date >= now() - interval '7 days')  as qty_7d,
        sum(oi.qty) filter (where o.transaction_date >= now() - interval '14 days') as qty_14d,
        sum(oi.qty) filter (where o.transaction_date >= now() - interval '30 days') as qty_30d,
        max(o.transaction_date) as last_sold
    from public.order_items oi
    join public.orders o on o.salesorder_id = oi.order_id
    where coalesce(o.is_canceled, false) = false
    group by oi.item_code
)
select
    p.item_code,
    p.item_name,
    p.total_available,
    p.total_on_hand,
    p.last_cogs,
    coalesce(s.qty_7d, 0)  as qty_7d,
    coalesce(s.qty_14d, 0) as qty_14d,
    coalesce(s.qty_30d, 0) as qty_30d,
    round(coalesce(s.qty_14d, 0) / 14.0, 2) as avg_daily_14d,
    s.last_sold,
    case when coalesce(s.qty_14d, 0) > 0
         then round(p.total_available / (s.qty_14d / 14.0), 1)
         else null end as days_of_cover
from public.products p
left join sales s on s.item_code = p.item_code;

-- ── RESTOCK MENDESAK: stok habis, laku, PO belum cukup ───────────────────────
create or replace view public.v_restock_urgent as
select
    v.item_code, v.item_name, v.total_available, v.avg_daily_14d,
    v.qty_7d, v.days_of_cover,
    coalesce(po.qty_pending, 0) as po_pending
from public.v_sales_velocity v
left join (
    select item_code, sum(qty_pending) as qty_pending
    from public.preorder_stocks group by item_code
) po on po.item_code = v.item_code
where v.avg_daily_14d > 0
  and v.total_available <= 0;

-- ── DEAD STOCK: modal nyangkut (stok ada, lama tak laku) ─────────────────────
create or replace view public.v_dead_stock as
select
    p.item_code, p.item_name, p.total_on_hand, p.last_cogs,
    round(p.total_on_hand * coalesce(p.last_cogs, 0), 0) as modal_nyangkut,
    s.last_sold
from public.products p
left join (
    select oi.item_code, max(o.transaction_date) as last_sold
    from public.order_items oi
    join public.orders o on o.salesorder_id = oi.order_id
    where coalesce(o.is_canceled, false) = false
    group by oi.item_code
) s on s.item_code = p.item_code
where p.total_on_hand > 0
  and (s.last_sold is null or s.last_sold < now() - interval '30 days');

-- ── BORONGAN: qty besar dalam 1 baris order (48 jam terakhir) ────────────────
create or replace view public.v_bulk_orders as
select
    oi.salesorder_detail_id, o.salesorder_no, oc.channel, o.store_name,
    o.customer_name, oi.item_code, oi.item_name, oi.qty, oi.amount,
    o.transaction_date, o.status
from public.order_items oi
join public.orders o          on o.salesorder_id = oi.order_id
join public.v_orders_channel oc on oc.salesorder_id = o.salesorder_id
where coalesce(o.is_canceled, false) = false
  and oi.qty >= 5
  and o.transaction_date >= now() - interval '48 hours'
order by oi.qty desc;

-- ── TREN 12 JAM per SKU per channel (deteksi naik/turun) ─────────────────────
create or replace view public.v_sales_trend_12h as
select
    oi.item_code,
    max(oi.item_name)  as item_name,
    oc.channel,
    coalesce(sum(oi.qty) filter (
        where o.transaction_date >= now() - interval '12 hours'), 0) as qty_now,
    coalesce(sum(oi.qty) filter (
        where o.transaction_date >= now() - interval '24 hours'
          and o.transaction_date <  now() - interval '12 hours'), 0) as qty_prev
from public.order_items oi
join public.orders o          on o.salesorder_id = oi.order_id
join public.v_orders_channel oc on oc.salesorder_id = o.salesorder_id
where coalesce(o.is_canceled, false) = false
  and o.transaction_date >= now() - interval '24 hours'
group by oi.item_code, oc.channel;

-- ── TOP SELLER 24 JAM ────────────────────────────────────────────────────────
create or replace view public.v_top_seller_24h as
select
    oi.item_code,
    max(oi.item_name) as item_name,
    oc.channel,
    sum(oi.qty)     as qty,
    round(sum(oi.amount), 0) as omzet
from public.order_items oi
join public.orders o          on o.salesorder_id = oi.order_id
join public.v_orders_channel oc on oc.salesorder_id = o.salesorder_id
where coalesce(o.is_canceled, false) = false
  and o.transaction_date >= now() - interval '24 hours'
group by oi.item_code, oc.channel
order by qty desc;
