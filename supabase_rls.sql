-- ════════════════════════════════════════════════════════════════════════════
--  BVR-DB — Keamanan RLS (Row Level Security)
--  Jalankan di Supabase SQL Editor SETELAH schema + reports.
--  Efek: data HANYA bisa dibaca user yang SUDAH LOGIN (role authenticated).
--        Engine sync pakai service_role → otomatis bypass RLS (tetap bisa tulis).
--        anon (belum login) → TIDAK bisa baca apa pun.
-- ════════════════════════════════════════════════════════════════════════════

-- 1) Aktifkan RLS + policy "boleh baca kalau sudah login" untuk semua tabel
do $$
declare t text;
begin
    foreach t in array array[
        'orders','order_items','products','product_stocks',
        'preorder_stocks','sync_log','sync_state'
    ]
    loop
        execute format('alter table public.%I enable row level security;', t);
        execute format('drop policy if exists "auth_read" on public.%I;', t);
        execute format(
            'create policy "auth_read" on public.%I for select to authenticated using (true);', t);
    end loop;
end $$;

-- 2) Views: hormati RLS penanya (security_invoker) + boleh dibaca authenticated
do $$
declare v text;
begin
    foreach v in array array[
        'v_order_item_margin','v_unmatched_skus','v_orders_channel',
        'v_sales_velocity','v_restock_urgent','v_dead_stock',
        'v_bulk_orders','v_sales_trend_12h','v_top_seller_24h'
    ]
    loop
        -- lewati kalau view belum dibuat
        if exists (select 1 from information_schema.views
                   where table_schema='public' and table_name=v) then
            execute format('alter view public.%I set (security_invoker = on);', v);
            execute format('grant select on public.%I to authenticated;', v);
        end if;
    end loop;
end $$;

-- Catatan:
--  • Menulis data hanya lewat service_role (engine sync) → aman.
--  • Untuk menambah anggota tim: Supabase Dashboard → Authentication → Users →
--    "Add user" / "Invite". Matikan signup publik di Authentication → Providers →
--    Email → nonaktifkan "Enable sign ups" supaya hanya user undangan yang bisa masuk.
