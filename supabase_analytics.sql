-- ════════════════════════════════════════════════════════════════════════════
--  BEVERRA CENTRAL — Views Analitik (Marketing & Purchasing)
--  Jalankan di Supabase SQL Editor. Aman diulang (create or replace).
--  Butuh tabel: orders, order_items, products.
-- ════════════════════════════════════════════════════════════════════════════

-- 1) Penjualan harian 14 hari terakhir (untuk grafik tren)
create or replace view public.v_an_daily_sales as
select (o.transaction_date at time zone 'Asia/Jakarta')::date as tgl,
       count(*)                        as jml_order,
       coalesce(sum(o.grand_total), 0) as omzet
from public.orders o
where o.transaction_date >= now() - interval '14 days'
  and o.is_canceled is not true
group by 1
order by 1;

-- 2) Penjualan per channel 30 hari (Shopee/TikTok/Tokopedia/…)
create or replace view public.v_an_channel as
select case
         when o.salesorder_no ilike 'TT-%' then 'TikTok'
         when o.salesorder_no ilike 'SP-%' then 'Shopee'
         when o.source_name ilike '%lazada%'   or o.salesorder_no ilike 'LZ%'  then 'Lazada'
         when o.source_name ilike '%akulaku%'  or o.salesorder_no ilike 'AKL%' then 'Akulaku'
         when o.source_name ilike '%tokopedia%' then 'Tokopedia'
         else coalesce(o.source_name, 'Lainnya')
       end                             as channel,
       count(*)                        as jml_order,
       coalesce(sum(o.grand_total), 0) as omzet
from public.orders o
where o.transaction_date >= now() - interval '30 days'
  and o.is_canceled is not true
group by 1
order by omzet desc;

-- 3) Top SKU 30 hari (paling laku) — untuk marketing
create or replace view public.v_an_top_sku as
select oi.item_code,
       max(oi.item_name)         as item_name,
       sum(oi.qty)               as qty,
       coalesce(sum(oi.amount),0) as omzet
from public.order_items oi
join public.orders o on o.salesorder_no = oi.salesorder_no
where o.transaction_date >= now() - interval '30 days'
  and o.is_canceled is not true
  and coalesce(oi.is_canceled_item, false) = false
group by oi.item_code
order by qty desc
limit 20;

-- 4) Stok menipis — untuk purchasing (kecepatan jual 14 hari)
create or replace view public.v_an_low_stock as
with vel as (
  select oi.item_code, sum(oi.qty)::numeric / 14.0 as jual_harian
  from public.order_items oi
  join public.orders o on o.salesorder_no = oi.salesorder_no
  where o.transaction_date >= now() - interval '14 days'
    and o.is_canceled is not true
    and coalesce(oi.is_canceled_item, false) = false
  group by oi.item_code
)
select p.item_code,
       p.item_name,
       p.total_available                                    as stok,
       round(v.jual_harian, 2)                              as jual_harian,
       round(p.total_available / nullif(v.jual_harian, 0), 1) as hari_tersisa
from public.products p
join vel v on v.item_code = p.item_code
where v.jual_harian > 0
  and p.total_available <= v.jual_harian * 7      -- stok < 7 hari
order by hari_tersisa asc nulls last
limit 60;

-- 5) Barang diborong 30 hari (qty >= 10 dalam 1 baris order)
create or replace view public.v_an_bulk as
select o.salesorder_no,
       o.transaction_date as tgl,
       case
         when o.salesorder_no ilike 'TT-%' then 'TikTok'
         when o.salesorder_no ilike 'SP-%' then 'Shopee'
         when o.source_name ilike '%tokopedia%' then 'Tokopedia'
         else coalesce(o.source_name, 'Lainnya')
       end                as channel,
       o.customer_name,
       oi.item_code,
       oi.item_name,
       oi.qty,
       oi.amount
from public.order_items oi
join public.orders o on o.salesorder_no = oi.salesorder_no
where coalesce(oi.is_canceled_item, false) = false
  and oi.qty >= 10
  and o.transaction_date >= now() - interval '30 days'
order by oi.qty desc
limit 60;

-- 6) Dead stock — stok > 0 tapi tak laku 30 hari (modal nyangkut)
create or replace view public.v_an_dead_stock as
with sold as (
  select distinct oi.item_code
  from public.order_items oi
  join public.orders o on o.salesorder_no = oi.salesorder_no
  where o.transaction_date >= now() - interval '30 days'
    and oi.item_code is not null
)
select p.item_code,
       p.item_name,
       p.total_available                                       as stok,
       p.last_cogs,
       round(p.total_available * coalesce(p.last_cogs, 0))::bigint as modal_nyangkut
from public.products p
where p.total_available > 0
  and p.item_code not in (select item_code from sold)
order by modal_nyangkut desc
limit 60;

-- 7) KPI ringkas (1 baris) — untuk kartu atas
create or replace view public.v_an_kpi as
select
  (select coalesce(sum(grand_total),0) from public.orders
     where (transaction_date at time zone 'Asia/Jakarta')::date = (now() at time zone 'Asia/Jakarta')::date
       and is_canceled is not true)                                                   as omzet_hari_ini,
  (select count(*) from public.orders
     where (transaction_date at time zone 'Asia/Jakarta')::date = (now() at time zone 'Asia/Jakarta')::date
       and is_canceled is not true)                                                   as order_hari_ini,
  (select coalesce(sum(grand_total),0) from public.orders
     where transaction_date >= now() - interval '7 days' and is_canceled is not true) as omzet_7hari,
  (select count(*) from public.orders
     where transaction_date >= now() - interval '7 days' and is_canceled is not true) as order_7hari,
  (select count(*) from public.v_an_low_stock)                                        as sku_menipis,
  (select count(*) from public.v_an_dead_stock)                                       as sku_dead;

-- Keamanan: view hormati RLS penanya + boleh dibaca user login
do $$
declare v text;
begin
  foreach v in array array[
    'v_an_daily_sales','v_an_channel','v_an_top_sku','v_an_low_stock',
    'v_an_bulk','v_an_dead_stock','v_an_kpi'
  ]
  loop
    execute format('alter view public.%I set (security_invoker = on);', v);
    execute format('grant select on public.%I to authenticated;', v);
  end loop;
end $$;
