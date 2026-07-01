-- ════════════════════════════════════════════════════════════════════════════
--  BVR-DB — Skema Supabase untuk Integrasi Jubelio
--  Jalankan sekali di Supabase → SQL Editor (atau psql) sebelum sync pertama.
--  Idempotent: aman dijalankan berulang (pakai IF NOT EXISTS).
-- ════════════════════════════════════════════════════════════════════════════

-- ── MODUL 2: MASTER PRODUK ──────────────────────────────────────────────────
create table if not exists public.products (
    item_id           bigint       primary key,          -- id internal Jubelio (SKU level)
    item_code         text         not null unique,       -- SKU
    item_name         text,
    item_group_id     bigint,                             -- id master/katalog Jubelio
    item_group_name   text,                               -- nama produk master
    item_category_id  bigint,                             -- id kategori
    brand_name        text,
    barcode           text,
    variation_name    text,                               -- nama varian (cth "Ungu")
    is_bundle         boolean      default false,
    sell_price        numeric(18,4),                      -- harga jual master
    last_cogs         numeric(18,4),                      -- HPP terbaru (dari inventory/v2)
    average_cost      numeric(18,4),
    weight_gram       numeric(14,4),                      -- package_weight (utk ongkir)
    package_length    numeric(14,4),
    package_width     numeric(14,4),
    package_height    numeric(14,4),
    total_on_hand     numeric(18,4) default 0,
    total_available   numeric(18,4) default 0,
    total_reserved    numeric(18,4) default 0,
    total_on_order    numeric(18,4) default 0,
    thumbnail         text,
    description       text,
    variation_values  jsonb,
    source_channel    text         default 'jubelio',
    created_at        timestamptz  default now(),
    updated_at        timestamptz  default now()
);
create index if not exists idx_products_item_code on public.products (item_code);
create index if not exists idx_products_group_id  on public.products (item_group_id);

-- ALTER idempoten — utk skema lama yg sudah terlanjur dibuat versi sebelumnya
alter table public.products add column if not exists item_group_name  text;
alter table public.products add column if not exists item_category_id bigint;
alter table public.products add column if not exists barcode          text;
alter table public.products add column if not exists variation_name   text;
alter table public.products add column if not exists sell_price       numeric(18,4);
alter table public.products add column if not exists package_length   numeric(14,4);
alter table public.products add column if not exists package_width    numeric(14,4);
alter table public.products add column if not exists package_height   numeric(14,4);
alter table public.products add column if not exists description      text;

-- Breakdown stock per gudang/lokasi (multi-gudang)
create table if not exists public.product_stocks (
    item_id       bigint  not null references public.products (item_id) on delete cascade,
    location_id   bigint  not null,
    location_code text,
    on_hand       numeric(18,4) default 0,
    on_order      numeric(18,4) default 0,
    reserved      numeric(18,4) default 0,
    available     numeric(18,4) default 0,
    updated_at    timestamptz   default now(),
    primary key (item_id, location_id)
);

-- ── MODUL 1: PENJUALAN — HEADER ORDER ───────────────────────────────────────
create table if not exists public.orders (
    salesorder_id        bigint      primary key,          -- PK stabil Jubelio
    salesorder_no        text        not null unique,       -- nomor order Jubelio (key upsert bisnis)
    ref_no               text,
    invoice_no           text,                              -- invoice internal Jubelio
    invoice_id           bigint,
    store_so_number      text,                              -- nomor order marketplace toko
    -- channel / toko
    source               integer,                           -- kode channel (64=Shopee, dst)
    source_name          text,                              -- SHOPEE / TIKTOK / TOKOPEDIA / LAZADA / AKULAKU
    store_id             bigint,
    store_name           text,
    -- tanggal siklus order
    transaction_date     timestamptz,                       -- order masuk
    created_date         timestamptz,
    payment_date         timestamptz,                       -- tanggal bayar (nullable)
    awb_created_date     timestamptz,                       -- resi dibuat
    shipped_date         timestamptz,                       -- dikirim
    completed_date       timestamptz,                       -- selesai
    mp_completed_date    timestamptz,
    due_date             timestamptz,
    last_modified        timestamptz,                       -- dipakai utk incremental watermark
    -- status
    status               text,                              -- internal_status (COMPLETED/CANCELED/...)
    channel_status       text,
    wms_status           text,
    is_paid              boolean,
    is_cod               boolean,
    is_canceled          boolean,
    cancel_reason        text,
    -- pembeli & pengiriman
    customer_name        text,
    shipping_full_name   text,
    shipping_address     text,
    shipping_area        text,
    shipping_city        text,
    shipping_province    text,
    shipping_post_code   text,
    shipping_phone       text,
    courier              text,
    shipper              text,
    tracking_number      text,
    -- finansial (header)
    sub_total            numeric(18,4),
    total_disc           numeric(18,4),
    total_tax            numeric(18,4),
    add_disc             numeric(18,4),
    add_fee              numeric(18,4),
    service_fee          numeric(18,4),                     -- biaya layanan / admin marketplace
    shipping_cost        numeric(18,4),                     -- ongkir tercatat
    buyer_shipping_cost  numeric(18,4),                     -- ongkir ditanggung pembeli
    insurance_cost       numeric(18,4),
    voucher_amount       numeric(18,4),                     -- voucher/promo (jika ada)
    discount_marketplace numeric(18,4),
    cod_fee              numeric(18,4),
    order_processing_fee numeric(18,4),
    grand_total          numeric(18,4),
    total_amount_mp      numeric(18,4),                     -- nilai di marketplace
    escrow_amount        numeric(18,4),                     -- NET SETTLEMENT (yg benar2 diterima)
    sum_cogs             numeric(18,4),
    total_weight_kg      numeric(14,4),
    note                 text,
    source_channel       text        default 'jubelio',
    created_at           timestamptz default now(),
    updated_at           timestamptz default now()
);
create index if not exists idx_orders_last_modified   on public.orders (last_modified desc);
create index if not exists idx_orders_transaction_date on public.orders (transaction_date desc);
create index if not exists idx_orders_source_name      on public.orders (source_name);
create index if not exists idx_orders_status           on public.orders (status);

-- ── MODUL 1: PENJUALAN — ITEM ORDER (per SKU) ───────────────────────────────
create table if not exists public.order_items (
    salesorder_detail_id  bigint  primary key,             -- id baris detail Jubelio
    order_id              bigint  not null references public.orders (salesorder_id) on delete cascade,
    salesorder_no         text,                             -- denormalisasi utk query cepat
    item_id               bigint,
    item_code             text,                             -- SKU
    item_name             text,
    variant               text,                             -- variasi
    qty                   numeric(18,4),
    unit                  text,
    price                 numeric(18,4),                    -- harga jual satuan (setelah nego channel)
    sell_price            numeric(18,4),
    original_price        numeric(18,4),                    -- harga normal
    disc_percent          numeric(9,4),
    disc_amount           numeric(18,4),                    -- diskon per item
    disc_marketplace      numeric(18,4),                    -- diskon/voucher platform per item
    tax_amount            numeric(18,4),
    amount                numeric(18,4),                    -- subtotal bersih baris
    weight_gram           numeric(14,4),
    loc_id                bigint,
    loc_name              text,
    item_group_id         bigint,
    channel_order_detail_id text,
    promotion_id          bigint,
    promotion_name        text,
    is_canceled_item      boolean,
    is_return_resolved    boolean,
    status                text,
    created_at            timestamptz default now(),
    updated_at            timestamptz default now()
);
create index if not exists idx_order_items_order_id  on public.order_items (order_id);
create index if not exists idx_order_items_item_code on public.order_items (item_code);

-- ── PREORDER STOCK (PO/Inbound — belum diterima) ──────────────────────────────
-- Catatan: 1 PO bisa punya banyak item, jadi kunci unik = (PO + item + lokasi),
-- BUKAN purchaseorder_no saja.
create table if not exists public.preorder_stocks (
    preorder_id       bigserial   primary key,
    item_id           bigint,
    item_code         text,
    item_name         text,
    purchaseorder_no  text,                                -- nomor PO (tidak unik sendiri)
    qty_po            numeric(18,4),                       -- qty_in_base (total PO)
    qty_fulfilled     numeric(18,4),                       -- sudah diterima
    qty_pending       numeric(18,4),                       -- belum = po - fulfilled
    location_id       bigint,
    location_name     text,
    transaction_date  timestamptz,                         -- PO date
    variation_values  jsonb,
    thumbnail         text,
    source_channel    text         default 'jubelio',
    created_at        timestamptz  default now(),
    updated_at        timestamptz  default now(),
    constraint uq_preorder_po_item unique (purchaseorder_no, item_id, location_id)
);
create index if not exists idx_preorder_po_no      on public.preorder_stocks (purchaseorder_no);
create index if not exists idx_preorder_item_code  on public.preorder_stocks (item_code);

-- Idempoten: kalau tabel versi lama (purchaseorder_no unique) sudah terlanjur dibuat,
-- perbaiki jadi composite key.
do $$
begin
    if exists (select 1 from information_schema.table_constraints
               where table_name='preorder_stocks' and constraint_name='preorder_stocks_purchaseorder_no_key') then
        alter table public.preorder_stocks drop constraint preorder_stocks_purchaseorder_no_key;
    end if;
    if not exists (select 1 from information_schema.table_constraints
                   where table_name='preorder_stocks' and constraint_name='uq_preorder_po_item') then
        alter table public.preorder_stocks add constraint uq_preorder_po_item
            unique (purchaseorder_no, item_id, location_id);
    end if;
end $$;

-- ── OPERASIONAL: LOG SYNC & WATERMARK ───────────────────────────────────────
create table if not exists public.sync_log (
    id                 bigserial   primary key,
    run_id             text,
    module             text,                                -- 'orders' | 'products'
    started_at         timestamptz default now(),
    finished_at        timestamptz,
    status             text,                                -- 'success' | 'failed' | 'partial'
    records_processed  integer     default 0,
    records_failed     integer     default 0,
    error_message      text,
    details            jsonb
);
create index if not exists idx_sync_log_module on public.sync_log (module, started_at desc);

create table if not exists public.sync_state (
    module         text        primary key,                 -- 'orders'
    last_watermark timestamptz,                              -- max(last_modified) terakhir sukses
    updated_at     timestamptz default now()
);

-- ── TRIGGER: auto-refresh updated_at saat UPDATE ────────────────────────────
create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

do $$
declare t text;
begin
    foreach t in array array['products','product_stocks','orders','order_items']
    loop
        execute format('drop trigger if exists trg_updated_at on public.%I;', t);
        execute format(
            'create trigger trg_updated_at before update on public.%I
             for each row execute function public.set_updated_at();', t);
    end loop;
end $$;

-- ── VIEW: MARGIN RIIL per baris order (join HPP master) ──────────────────────
create or replace view public.v_order_item_margin as
select
    oi.salesorder_detail_id,
    oi.order_id,
    o.salesorder_no,
    o.source_name,
    o.store_name,
    o.transaction_date,
    o.status,
    oi.item_code,
    oi.item_name,
    oi.variant,
    oi.qty,
    oi.amount                                   as revenue_line,      -- pendapatan baris (net diskon)
    p.last_cogs,
    (coalesce(p.last_cogs,0) * oi.qty)          as cogs_line,         -- HPP x qty
    (oi.amount - coalesce(p.last_cogs,0) * oi.qty) as gross_margin_line
from public.order_items oi
join public.orders   o on o.salesorder_id = oi.order_id
left join public.products p on p.item_code = oi.item_code;

-- ── VIEW: SKU pada penjualan yg TIDAK match master produk ───────────────────
create or replace view public.v_unmatched_skus as
select distinct oi.item_code
from public.order_items oi
left join public.products p on p.item_code = oi.item_code
where p.item_code is null
  and oi.item_code is not null;
