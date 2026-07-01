from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import colorama; colorama.init()
import inquirer
import xlwings
import asyncio
import httpx
import pandas as pd
import json
import os

load_dotenv()


# ── KONSTANTA ─────────────────────────────────────────────────────────────────
CONCURRENCY = 10
EXCEL_PATH  = 'tabel_diskon_tiktokshop.xlsx'
OUT_SHEET   = 'Harga Diskon'
COL_SKU     = 'B'
COL_DISKON  = 'H'

JUBELIO_LOGIN_URL = 'https://api2.jubelio.com/login'
JUBELIO_INV_URL   = 'https://open.jubelio.com/core-api/inventory/v2/'
JUBELIO_PAGE_SIZE = 100


HEADERS = [
    'Produk ID', 'Nama Produk', 'Stok', 'Nilai Variasi', 'HPP', 'Harga Jual Normal',
    'Harga Diskon', 'Harga Jual Saat Ini', 'Periode Diskon',
    'Sisa Hari', 'Tgl Diskon Mulai', 'Tgl Update', 'URL',
]

# Nama harus sama persis dengan nama folder masing-masing toko
DB_SHOPS = [
    "CARAMEL AKSESORIS",
    "MINZO STORE",
    "MOONKLAZ",
    "NOMIDE STORE",
    "TOPI KECE",
    "TOPI KEREN",
    "YARRA STORE",
]


# ── PILIH TOKO ────────────────────────────────────────────────────────────────
def select_shops():
    answers = inquirer.prompt([
        inquirer.Checkbox(
            'shops',
            message='Pilih toko (SPACE untuk unselect, ENTER konfirmasi)',
            choices=DB_SHOPS,
            default=DB_SHOPS,
        )
    ])
    if not answers:
        return []
    selected = answers['shops']
    if not selected:
        print(colorama.Fore.RED + '    Tidak ada toko yang dipilih.' + colorama.Style.RESET_ALL)
    return selected


# ── CLEAR EXCEL ───────────────────────────────────────────────────────────────
def clear_excel(shops):
    for shop in shops:
        for item in os.listdir(shop):
            if '.xlsx' in item:
                os.remove(f'{shop}/{item}')
        print(colorama.Fore.YELLOW + f'    Berhasil Hapus Excel [{shop}]' + colorama.Style.RESET_ALL)


# ── DOWNLOAD EXCEL ────────────────────────────────────────────────────────────
async def _download_shop_async(playwright, shop, semaphore):
    async with semaphore:
        t_start = datetime.now()
        print(colorama.Fore.CYAN + f'    [{t_start.strftime("%H:%M:%S")}] Mulai Download [{shop}]' + colorama.Style.RESET_ALL)
        browser = await playwright.chromium.launch(
            channel='chrome',
            headless=False,
            args=[
                '--force-device-scale-factor=0.8',
                '--disable-dev-shm-usage',
                '--disable-background-networking',
                '--disable-extensions',
                '--window-position=10000,0',
            ],
        )
        context = await browser.new_context(no_viewport=True, accept_downloads=True)
        await context.add_cookies(json.loads(open(f'{shop}/login.json').read()))
        context.set_default_timeout(600_000)             # 10 menit default
        context.set_default_navigation_timeout(300_000)  # 5 menit navigasi
        page = await context.new_page()
        try:
            await page.goto(
                'https://seller-id.tokopedia.com/product/batch/edit-prods?entry-from=manage',
                timeout=300_000,
                wait_until='domcontentloaded',
            )
            await page.locator('xpath=//button/span[text()="Pilih produk"]').wait_for(
                state='visible', timeout=120_000,
            )
            await page.wait_for_timeout(5000)
            await page.locator('xpath=//button/span[text()="Pilih produk"]').click()
            for i in range(100):
                try:
                    if i > 0:
                        await page.get_by_role('dialog').locator(
                            'xpath=//li[@class="core-pagination-item core-pagination-item-next"]'
                        ).click(timeout=30_000)
                    await page.wait_for_timeout(5000)
                    await page.locator('xpath=(//div[@class="core-checkbox-mask"])[1]').click(force=True)
                except Exception:
                    break
            await page.locator('xpath=//button/span[text()="Pilih yang dicentang"]').click()
            for i in range(1, 3):
                await page.wait_for_timeout(8000)
                await page.locator(f'xpath=(//div[@class="core-radio-mask"])[{i}]').click()
                await page.mouse.move(x=0, y=0)
                await page.wait_for_timeout(8000)
                await page.locator('xpath=//button/span[text()="Buat templat"]').click()
                await page.wait_for_timeout(12_000)  # tunggu server buat template
                async with page.expect_download(timeout=300_000) as download_info:
                    await page.locator('xpath=(//tbody//tr)[1]//span[text()="Unduh"]').click()
                download = await download_info.value
                await download.save_as(f'{shop}/{download.suggested_filename}')
            durasi = (datetime.now() - t_start).total_seconds() / 60
            print(colorama.Fore.YELLOW + f'    [{datetime.now().strftime("%H:%M:%S")}] Berhasil Download Excel [{shop}] — {durasi:.1f} menit' + colorama.Style.RESET_ALL)
        except Exception as e:
            durasi = (datetime.now() - t_start).total_seconds() / 60
            print(colorama.Fore.RED + f'    [{datetime.now().strftime("%H:%M:%S")}] Gagal Download Excel [{shop}] — {durasi:.1f} menit — {e}' + colorama.Style.RESET_ALL)
        finally:
            await page.close()
            await context.close()
            await browser.close()


def download_excel(shops):
    async def _run():
        t_total_start = datetime.now()
        # Batasi 2 browser sekaligus agar tidak overload RAM/network
        semaphore = asyncio.Semaphore(2)
        async with async_playwright() as playwright:
            await asyncio.gather(*[
                _download_shop_async(playwright, shop, semaphore)
                for shop in shops
            ])
        total_menit = (datetime.now() - t_total_start).total_seconds() / 60
        print(colorama.Fore.GREEN + colorama.Style.BRIGHT +
              f'    [{datetime.now().strftime("%H:%M:%S")}] Semua Download Selesai — Total {total_menit:.1f} menit' +
              colorama.Style.RESET_ALL)
    asyncio.run(_run())


# ── LOAD HPP (dari Jubelio API) ───────────────────────────────────────────────
def load_hpp() -> dict:
    """Fetch HPP live dari Jubelio — field last_cogs per item_code."""
    db_hpp = {}
    try:
        with httpx.Client(timeout=30) as client:
            # Login
            resp = client.post(
                JUBELIO_LOGIN_URL,
                json={
                    'email'   : os.getenv('EMAIL_JUBELIO'),
                    'password': os.getenv('PASSWORD_JUBELIO'),
                },
            )
            resp.raise_for_status()
            token   = resp.json()['token']
            headers = {'Authorization': token}

            # Fetch semua halaman
            page = 1
            while True:
                resp = client.get(
                    JUBELIO_INV_URL,
                    headers=headers,
                    params={
                        'page'           : page,
                        'page_size'      : JUBELIO_PAGE_SIZE,
                        'sort_direction' : 'NONE',
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data  = resp.json()
                items = data.get('data', [])
                for item in items:
                    code = item.get('item_code', '').strip()
                    hpp  = float(item.get('last_cogs') or item.get('average_cost') or 0)
                    if code:
                        db_hpp[code] = hpp
                total = data.get('totalCount', 0)
                print(f' [Jubelio] [Load HPP] [{len(db_hpp)}/{total}]', end='\r')
                if len(db_hpp) >= total or not items:
                    break
                page += 1

        print(f' [Jubelio] [Load HPP] Selesai — {len(db_hpp)} SKU          ')
    except Exception as e:
        print(colorama.Fore.RED + f'\n    Gagal load HPP dari Jubelio: {e}' + colorama.Style.RESET_ALL)
    return db_hpp


def _parse_date(value):
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except Exception:
        return None


# ── GRAB FILEPATH ─────────────────────────────────────────────────────────────
def grab_filepath(shop):
    database = {}
    for item in os.listdir(shop):
        if 'basic_information' in item:
            database['basic_information'] = f'{shop}/{item}'
        elif 'sales_information' in item:
            database['sales_information'] = f'{shop}/{item}'
    return database


# ── GRAB HEADERS ──────────────────────────────────────────────────────────────
def grab_headers():
    return {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "bd-device-id": os.getenv("TOKOPEDIA_BD_DEVICE_ID", ""),
        "connection": "keep-alive",
        "content-type": "application/json",
        "cookie": os.getenv("TOKOPEDIA_COOKIE", ""),
        "host": "gql.tokopedia.com",
        "origin": "https://www.tokopedia.com",
        "referer": "https://www.tokopedia.com/",
        "sec-ch-ua": "\"Not;A=Brand\";v=\"99\", \"Google Chrome\";v=\"139\", \"Chromium\";v=\"139\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "x-date": f"{datetime.now(timezone(timedelta(hours=7))).strftime('%a, %d %b %Y %H:%M:%S %z')}",
        "x-device": "desktop",
        "x-price-center": "true",
        "x-source": "tokopedia-lite",
        "x-tkpd-akamai": "pdpGetLayout",
        "x-tkpd-lite-service": "zeus",
        "x-version": "fd05378"
    }


# ── GRAB PAYLOAD ──────────────────────────────────────────────────────────────
def grab_payload(shop, product):
    return [{
        "operationName": "PDPGetLayoutQuery",
        "variables": {
            "shopDomain": shop,
            "productKey": product,
            "layoutID": "",
            "apiVersion": 1,
            "deviceID": os.getenv("TOKOPEDIA_DEVICE_ID", ""),
            "userLocation": {
                "cityID": "176",
                "addressID": "",
                "districtID": "2274",
                "postalCode": "",
                "latlon": ""
            },
            "extParam": ""
        },
        "query": "fragment ProductVariant on pdpDataProductVariant {\n  errorCode\n  parentID\n  defaultChild\n  sizeChart\n  totalStockFmt\n  variants {\n    productVariantID\n    variantID\n    name\n    identifier\n    option {\n      picture {\n        urlOriginal: url\n        urlThumbnail: url100\n        __typename\n      }\n      productVariantOptionID\n      variantUnitValueID\n      value\n      hex\n      stock\n      __typename\n    }\n    __typename\n  }\n  children {\n    productID\n    price\n    priceFmt\n    slashPriceFmt\n    discPercentage\n    optionID\n    optionName\n    productName\n    productURL\n    picture {\n      urlOriginal: url\n      urlThumbnail: url100\n      __typename\n    }\n    stock {\n      stock\n      isBuyable\n      stockWordingHTML\n      minimumOrder\n      maximumOrder\n      __typename\n    }\n    isCOD\n    isWishlist\n    campaignInfo {\n      campaignID\n      campaignType\n      campaignTypeName\n      campaignIdentifier\n      background\n      discountPercentage\n      originalPrice\n      discountPrice\n      stock\n      stockSoldPercentage\n      startDate\n      endDate\n      endDateUnix\n      appLinks\n      isAppsOnly\n      isActive\n      hideGimmick\n      isCheckImei\n      minOrder\n      showStockBar\n      __typename\n    }\n    thematicCampaign {\n      additionalInfo\n      background\n      campaignName\n      icon\n      __typename\n    }\n    ttsPID\n    ttsSKUID\n    __typename\n  }\n  __typename\n}\n\nfragment ProductMedia on pdpDataProductMedia {\n  media {\n    type\n    urlOriginal: URLOriginal\n    urlThumbnail: URLThumbnail\n    urlMaxRes: URLMaxRes\n    videoUrl: videoURLAndroid\n    prefix\n    suffix\n    description\n    variantOptionID\n    __typename\n  }\n  videos {\n    source\n    url\n    __typename\n  }\n  __typename\n}\n\nfragment ProductCategoryCarousel on pdpDataCategoryCarousel {\n  linkText\n  titleCarousel\n  applink\n  list {\n    categoryID\n    icon\n    title\n    isApplink\n    applink\n    __typename\n  }\n  __typename\n}\n\nfragment ProductHighlight on pdpDataProductContent {\n  name\n  price {\n    value\n    currency\n    priceFmt\n    slashPriceFmt\n    discPercentage\n    __typename\n  }\n  campaign {\n    campaignID\n    campaignType\n    campaignTypeName\n    campaignIdentifier\n    background\n    percentageAmount\n    originalPrice\n    discountedPrice\n    originalStock\n    stock\n    stockSoldPercentage\n    threshold\n    startDate\n    endDate\n    endDateUnix\n    appLinks\n    isAppsOnly\n    isActive\n    hideGimmick\n    showStockBar\n    __typename\n  }\n  thematicCampaign {\n    additionalInfo\n    background\n    campaignName\n    icon\n    __typename\n  }\n  stock {\n    useStock\n    value\n    stockWording\n    __typename\n  }\n  variant {\n    isVariant\n    parentID\n    __typename\n  }\n  wholesale {\n    minQty\n    price {\n      value\n      currency\n      __typename\n    }\n    __typename\n  }\n  isCashback {\n    percentage\n    __typename\n  }\n  isTradeIn\n  isOS\n  isPowerMerchant\n  isWishlist\n  isCOD\n  preorder {\n    duration\n    timeUnit\n    isActive\n    preorderInDays\n    __typename\n  }\n  __typename\n}\n\nfragment ProductCustomInfo on pdpDataCustomInfo {\n  icon\n  title\n  isApplink\n  applink\n  separator\n  description\n  __typename\n}\n\nfragment ProductInfo on pdpDataProductInfo {\n  row\n  content {\n    title\n    subtitle\n    applink\n    __typename\n  }\n  __typename\n}\n\nfragment ProductDetail on pdpDataProductDetail {\n  content {\n    title\n    subtitle\n    applink\n    showAtFront\n    isAnnotation\n    __typename\n  }\n  __typename\n}\n\nfragment ProductDataInfo on pdpDataInfo {\n  icon\n  title\n  isApplink\n  applink\n  content {\n    icon\n    text\n    __typename\n  }\n  __typename\n}\n\nfragment ProductSocial on pdpDataSocialProof {\n  row\n  content {\n    icon\n    title\n    subtitle\n    applink\n    type\n    rating\n    __typename\n  }\n  __typename\n}\n\nfragment ProductDetailMediaComponent on pdpDataProductDetailMediaComponent {\n  title\n  description\n  contentMedia {\n    url\n    ratio\n    type\n    __typename\n  }\n  show\n  ctaText\n  __typename\n}\n\nfragment PdpDataComponentShipmentV4 on pdpDataComponentShipmentV4 {\n  data {\n    productID\n    warehouse_info {\n      warehouse_id\n      is_fulfillment\n      district_id\n      postal_code\n      geolocation\n      city_name\n      ttsWarehouseID\n      __typename\n    }\n    useBOVoucher\n    isCOD\n    metadata\n    __typename\n  }\n  __typename\n}\n\nquery PDPGetLayoutQuery($shopDomain: String, $productKey: String, $layoutID: String, $apiVersion: Float, $userLocation: pdpUserLocation, $extParam: String, $deviceID: String) {\n  pdpGetLayout(shopDomain: $shopDomain, productKey: $productKey, layoutID: $layoutID, apiVersion: $apiVersion, userLocation: $userLocation, extParam: $extParam, deviceID: $deviceID) {\n    requestID\n    name\n    pdpSession\n    basicInfo {\n      alias\n      createdAt\n      isQA\n      id: productID\n      shopID\n      shopName\n      minOrder\n      maxOrder\n      weight\n      weightUnit\n      condition\n      status\n      url\n      needPrescription\n      catalogID\n      isLeasing\n      isBlacklisted\n      isTokoNow\n      ttsPID\n      ttsSKUID\n      ttsShopID\n      defaultMediaURL\n      menu {\n        id\n        name\n        url\n        __typename\n      }\n      category {\n        id\n        name\n        title\n        breadcrumbURL\n        isAdult\n        isKyc\n        minAge\n        detail {\n          id\n          name\n          breadcrumbURL\n          isAdult\n          __typename\n        }\n        ttsID\n        ttsDetail {\n          id\n          name\n          breadcrumbURL\n          isAdult\n          __typename\n        }\n        __typename\n      }\n      txStats {\n        transactionSuccess\n        transactionReject\n        countSold\n        paymentVerified\n        itemSoldFmt\n        __typename\n      }\n      stats {\n        countView\n        countReview\n        countTalk\n        rating\n        __typename\n      }\n      productID\n      ttsPID\n      ttsSKUID\n      ttsShopID\n      isAggregatedWithTTS\n      __typename\n    }\n    components {\n      name\n      type\n      position\n      data {\n        ...ProductMedia\n        ...ProductHighlight\n        ...ProductInfo\n        ...ProductDetail\n        ...ProductSocial\n        ...ProductDataInfo\n        ...ProductCustomInfo\n        ...ProductVariant\n        ...ProductCategoryCarousel\n        ...ProductDetailMediaComponent\n        ...PdpDataComponentShipmentV4\n        __typename\n      }\n      __typename\n    }\n    __typename\n  }\n}\n"
    }]


# ── VARIANT TYPE ──────────────────────────────────────────────────────────────
def variant_type(contents):
    return contents['components'][4]['name'] == 'new_variant_options'


# ── PARSE PRODUCT (murni logika, tanpa I/O) ───────────────────────────────────
# Struktur kolom output (A–M):
#   A: Produk ID | B: Nama Produk | C: Stok | D: Nilai Variasi | E: HPP | F: Harga Jual Normal
#   G: Harga Diskon | H: Harga Jual Saat Ini | I: Periode Diskon
#   J: Sisa Hari (formula) | K: Tgl Diskon Mulai | L: Tgl Update | M: URL
def parse_product(contents, url, product_id, db_product_sku, db_hpp, tanggal_update):
    rows      = []
    hpp_misses = set()

    def _build_row(get_sku_name, get_nilai_variasi, get_stok, get_normal_price, get_discount_price,
                   get_product_price, get_discount_period, get_discount_unique):
        hpp_val = db_hpp.get(get_sku_name)
        if hpp_val is None:
            hpp_misses.add(get_sku_name)
            hpp_val = 0
        return [
            product_id, get_sku_name, get_stok, get_nilai_variasi, hpp_val,
            get_normal_price, get_discount_price, get_product_price,
            get_discount_period, None,
            get_discount_unique, tanggal_update,
            url,
        ]

    if variant_type(contents):
        models = json.loads(contents['pdpSession'])['vd']
        db_sku_id = {str(k): str(v['ttssku']) for k, v in models.items()}
        for item in contents['components'][4]['data'][0]['children']:
            get_variant_id                          = str(item['productID'])
            get_sku_id                              = str(db_sku_id[get_variant_id])
            get_sku_name, get_nilai_variasi, get_stok = db_product_sku[get_sku_id]
            if item['campaignInfo']['isActive']:
                rows.append(_build_row(
                    get_sku_name, get_nilai_variasi, get_stok,
                    int(item['campaignInfo']['originalPrice']),
                    int(item['campaignInfo']['discountPrice']),
                    int(item['campaignInfo']['discountPrice']),
                    _parse_date(item['campaignInfo']['endDate']),
                    _parse_date(item['campaignInfo']['startDate']),
                ))
            else:
                rows.append(_build_row(
                    get_sku_name, get_nilai_variasi, get_stok,
                    int(item['price']), 0, int(item['price']),
                    None, None,
                ))
    else:
        get_sku_id                                = str(int(json.loads(contents['pdpSession'])['ttsku']))
        comp                                      = contents['components'][3]['data'][0]
        get_sku_name, get_nilai_variasi, get_stok = db_product_sku[get_sku_id]
        if comp['campaign']['isActive']:
            rows.append(_build_row(
                get_sku_name, get_nilai_variasi, get_stok,
                int(comp['campaign']['originalPrice']),
                int(comp['campaign']['discountedPrice']),
                int(comp['campaign']['discountedPrice']),
                _parse_date(comp['campaign']['endDate']),
                _parse_date(comp['campaign']['startDate']),
            ))
        else:
            price = int(comp['price']['value'])
            rows.append(_build_row(get_sku_name, get_nilai_variasi, get_stok, price, 0, price, None, None))

    return rows, hpp_misses


# ── FETCH PRODUCT (async, 1 HTTP request) ────────────────────────────────────
async def fetch_product(client, semaphore, shop, url, product_id, db_product_sku, db_hpp, tanggal_update):
    async with semaphore:
        try:
            response = await client.post(
                url='https://gql.tokopedia.com/graphql/PDPGetLayoutQuery',
                headers=grab_headers(),
                json=grab_payload(shop=url.split('/')[3], product=url.split('/')[4]),
                timeout=180
            )
            contents = response.json()[0]['data']['pdpGetLayout']
            rows, hpp_misses = parse_product(contents, url, product_id, db_product_sku, db_hpp, tanggal_update)
            for row in rows:
                print(f' [Tokopedia Seller] [Scrape Harga] [{shop}] - {row[1]}')
            return {'ok': True, 'rows': rows, 'hpp_misses': hpp_misses, 'url': url}
        except Exception as e:
            print(f' [Tokopedia Seller] [Scrape Harga] [{shop}] - [Gagal] {url}')
            return {'ok': False, 'rows': [], 'hpp_misses': set(), 'url': url, 'error': str(e)}


# ── SCRAPE SHOP (async, semua produk paralel) ─────────────────────────────────
async def scrape_shop_async(shop, db_product_url, db_product_sku, db_hpp, tanggal_update):
    semaphore = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        tasks = [
            fetch_product(client, semaphore, shop, url, pid, db_product_sku, db_hpp, tanggal_update)
            for pid, url in db_product_url.items()
        ]
        results = await asyncio.gather(*tasks)
    db_contents = []
    failed_urls = []
    hpp_misses  = set()
    for result in results:
        if not result['ok']:
            failed_urls.append(result['url'])
            continue
        hpp_misses.update(result['hpp_misses'])
        for row in result['rows']:
            if row[8] is not None:  # ada periode diskon → hitung sisa hari
                row[9] = f'=I{len(db_contents)+2}-TODAY()'
            db_contents.append(row)
    return db_contents, failed_urls, hpp_misses


# ── GRAB PRODUCT URL ──────────────────────────────────────────────────────────
def grab_product_url(shop):
    database = {}
    with xlwings.App(visible=False) as app:
        workbook  = app.books.open(grab_filepath(shop)['basic_information'])
        worksheet = workbook.sheets[0]
        max_row   = worksheet.used_range.last_cell.row
        for item in worksheet.range(f'A6:I{max_row}').value:
            pid = str(int(item[0]))
            database[pid] = str(item[7])
            print(f' [Tokopedia Seller] [Grab URL] [{shop}] [{len(database)}] - {pid}')
    return database


# ── GRAB PRODUCT SKU ──────────────────────────────────────────────────────────
def grab_product_sku(shop):
    database = {}
    with xlwings.App(visible=False) as app:
        workbook  = app.books.open(grab_filepath(shop)['sales_information'])
        worksheet = workbook.sheets[0]
        max_row   = worksheet.used_range.last_cell.row
        for item in worksheet.range(f'A6:T{max_row}').value:
            sku_id        = str(int(item[3]))
            sku_name      = str(item[7])
            nilai_variasi = str(item[4]) if item[4] is not None else ''
            stok          = int(item[6] or 0)
            database[sku_id] = (sku_name, nilai_variasi, stok)
            print(f' [Tokopedia Seller] [Grab SKU] [{shop}] [{len(database)}] - {sku_id}')
    return database


# ── SYNC SHEETS ───────────────────────────────────────────────────────────────
def sync_sheets(workbook):
    """Sinkronisasi sheet: hanya OUT_SHEET + folder toko yang ada yang dipertahankan."""
    existing = {d for d in DB_SHOPS if os.path.isdir(d)}
    keep     = existing | {OUT_SHEET}

    # Tambah sheet yang belum ada dulu agar workbook tidak pernah 0 sheet
    sheet_names = {s.name for s in workbook.sheets}
    for name in existing:
        if name not in sheet_names:
            workbook.sheets.add(name=name, after=workbook.sheets[-1])

    # Hapus sheet apa pun yang tidak dikenali (Sheet1, toko dihapus, dll)
    for sh in list(workbook.sheets):
        if sh.name not in keep and len(workbook.sheets) > 1:
            sh.delete()


# ── SAVE WORKBOOK ─────────────────────────────────────────────────────────────
def save_workbook(shop, contents):
    with xlwings.App(visible=False) as app:
        if not os.path.exists(EXCEL_PATH):
            wb = app.books.add()
            wb.save(EXCEL_PATH)
            wb.close()
        workbook = app.books.open(EXCEL_PATH)
        sync_sheets(workbook)
        ws = workbook.sheets[shop]
        ws.clear()

        # ── Header ───────────────────────────────────────────────────────────
        ws['A1'].value = HEADERS
        hdr = ws.range('A1:L1')
        hdr.api.Font.Bold = True
        hdr.color = (46, 117, 182)           # biru (#2E75B6)
        hdr.api.Font.Color = 16777215        # putih
        hdr.api.HorizontalAlignment = -4108  # xlCenter
        ws.api.Rows(1).RowHeight = 24

        # ── Data ─────────────────────────────────────────────────────────────
        if contents:
            last_row = len(contents) + 1

            # Paksa kolom teks SEBELUM data ditulis agar Excel tidak konversi angka panjang
            ws.range('A:A').api.NumberFormat = '@'   # Produk ID
            ws.range('D:D').api.NumberFormat = '@'   # Nilai Variasi
            ws.range('M:M').api.NumberFormat = '@'   # URL

            ws.range(f'A2:M{last_row}').value = contents

            # Mata uang Rupiah: E=HPP, F=Harga Jual Normal, G=Harga Diskon, H=Harga Jual Saat Ini
            for col in ('E', 'F', 'G', 'H'):
                ws.range(f'{col}2:{col}{last_row}').api.NumberFormat = \
                    '_-Rp* #.##0_-;-Rp* #.##0_-;_-Rp* "-"_-;_-@_-'

            # Tanggal + waktu (I = Periode Diskon, K = Tgl Diskon Mulai, L = Tgl Update)
            for col in ('I', 'K', 'L'):
                ws.range(f'{col}2:{col}{last_row}').api.NumberFormat = \
                    'DD MMM YYYY HH:MM'

            # Sisa hari: angka bulat; negatif → merah
            ws.range(f'J2:J{last_row}').api.NumberFormat = \
                '0" hari";[Red]-0" hari";"Hari Ini"'

            # Warna baris bergantian (kumpul Union dulu, 1 COM call untuk warna)
            ws_api = ws.api
            even_union = None
            for i in range(2, last_row + 1):
                if i % 2 == 0:
                    rng_row = ws_api.Range(f'A{i}:M{i}')
                    even_union = rng_row if even_union is None \
                        else ws_api.Application.Union(even_union, rng_row)
            if even_union:
                even_union.Interior.Color = 242 + 242 * 256 + 242 * 65536  # abu sangat muda

        # ── Layout ───────────────────────────────────────────────────────────
        ws.range('A:M').autofit()
        ws.range('A:A').column_width = 30   # Produk ID
        ws.range('B:B').column_width = 38   # Nama Produk
        ws.range('C:C').column_width = 10   # Stok
        ws.range('D:D').column_width = 20   # Nilai Variasi
        ws.range('M:M').column_width = 45   # URL
        ws.range('I:I').column_width = 20   # Periode Diskon
        ws.range('K:K').column_width = 20   # Tgl Diskon Mulai
        ws.range('L:L').column_width = 20   # Tgl Update

        workbook.save()


# ── SCRAPE REPORT ─────────────────────────────────────────────────────────────
def _print_scrape_report(shop_reports):
    C   = colorama
    now = datetime.now()
    SEP = '─' * 60
    DBL = '═' * 60

    # Kumpulkan data agregat
    total_ok = total_fail = 0
    all_failed   = []
    all_hpp_miss = set()
    rows_per_shop = []

    for shop, r in shop_reports.items():
        ok   = r['success']
        fail = len(r['failed_urls'])
        total_ok   += ok
        total_fail += fail
        all_failed.extend((shop, u) for u in r['failed_urls'])
        all_hpp_miss.update(r['hpp_misses'])
        rows_per_shop.append((shop, ok, fail))

    # ── Bangun konten plain-text (untuk file) ────────────────────────────
    txt = []
    txt.append(DBL)
    txt.append(f'  LAPORAN SCRAPING — {now.strftime("%d %B %Y, %H:%M")}')
    txt.append(DBL)
    for shop, ok, fail in rows_per_shop:
        suffix = f', {fail} GAGAL' if fail else ''
        txt.append(f'  {shop:<26} {ok} berhasil{suffix}')
    txt.append(SEP)
    total_suffix = f', {total_fail} GAGAL' if total_fail else ''
    txt.append(f'  {"TOTAL":<26} {total_ok} berhasil{total_suffix}')

    if all_failed:
        txt.append('')
        txt.append('  ⚠  URL GAGAL DIAMBIL — perlu cek manual:')
        for shop, url in all_failed:
            txt.append(f'       [{shop}]')
            txt.append(f'       {url}')

    if all_hpp_miss:
        txt.append('')
        txt.append('  ⚠  HPP TIDAK DITEMUKAN — perlu cek di Jubelio:')
        for sku in sorted(all_hpp_miss):
            txt.append(f'       {sku}')

    if not all_failed and not all_hpp_miss:
        txt.append('')
        txt.append('  ✓  Semua data lengkap, tidak ada yang perlu di-follow up.')

    txt.append(DBL)

    # ── Simpan ke file ───────────────────────────────────────────────────
    os.makedirs('laporan', exist_ok=True)
    fname = f'laporan/scraping_{now.strftime("%Y-%m-%d_%H-%M")}.txt'
    with open(fname, 'w', encoding='utf-8') as f:
        f.write('\n'.join(txt) + '\n')

    # ── Print ke console dengan warna ────────────────────────────────────
    print(f'\n{C.Style.BRIGHT}{DBL}')
    print(f'  LAPORAN SCRAPING — {now.strftime("%d %B %Y, %H:%M")}')
    print(f'{DBL}{C.Style.RESET_ALL}')

    for shop, ok, fail in rows_per_shop:
        ok_str   = C.Fore.GREEN + f'{ok} berhasil' + C.Style.RESET_ALL
        fail_str = (', ' + C.Fore.RED + f'{fail} gagal' + C.Style.RESET_ALL) if fail else ''
        print(f'  {shop:<26} {ok_str}{fail_str}')

    print(SEP)
    ok_c   = C.Fore.GREEN + f'{total_ok} berhasil' + C.Style.RESET_ALL
    fail_c = (', ' + C.Fore.RED + f'{total_fail} gagal' + C.Style.RESET_ALL) if total_fail else ''
    print(f'  {"TOTAL":<26} {ok_c}{fail_c}')

    if all_failed:
        print(f'\n{C.Fore.RED}  ⚠  URL GAGAL DIAMBIL — perlu cek manual:{C.Style.RESET_ALL}')
        for shop, url in all_failed:
            print(f'       [{shop}]')
            print(f'       {url}')

    if all_hpp_miss:
        print(f'\n{C.Fore.YELLOW}  ⚠  HPP TIDAK DITEMUKAN — perlu cek di Jubelio:{C.Style.RESET_ALL}')
        for sku in sorted(all_hpp_miss):
            print(f'       {sku}')

    if not all_failed and not all_hpp_miss:
        print(f'\n  {C.Fore.GREEN}✓  Semua data lengkap, tidak ada yang perlu di-follow up.{C.Style.RESET_ALL}')

    print(f'{C.Style.BRIGHT}{DBL}{C.Style.RESET_ALL}')
    print(f'  {C.Fore.CYAN}Laporan disimpan → {fname}{C.Style.RESET_ALL}\n')


# ── SCRAPE DISCOUNT ───────────────────────────────────────────────────────────
def scrape_discount(shops):
    db_hpp        = load_hpp()
    shop_reports  = {}
    t_total_start = datetime.now()
    for shop in shops:
        t_shop_start = datetime.now()
        print(colorama.Fore.CYAN + f'    [{t_shop_start.strftime("%H:%M:%S")}] Mulai Scrape [{shop}]' + colorama.Style.RESET_ALL)
        db_product_sku              = grab_product_sku(shop)
        db_product_url              = grab_product_url(shop)
        tanggal_update              = datetime.now()
        db_contents, failed, misses = asyncio.run(
            scrape_shop_async(shop, db_product_url, db_product_sku, db_hpp, tanggal_update)
        )
        save_workbook(shop, db_contents)
        shop_reports[shop] = {
            'success'    : len(db_contents),
            'failed_urls': failed,
            'hpp_misses' : misses,
        }
        durasi_shop = (datetime.now() - t_shop_start).total_seconds() / 60
        print(colorama.Fore.YELLOW + f'    [{datetime.now().strftime("%H:%M:%S")}] Selesai [{shop}] — {len(db_contents)} SKU — {durasi_shop:.1f} menit' + colorama.Style.RESET_ALL)
    total_menit = (datetime.now() - t_total_start).total_seconds() / 60
    print(colorama.Fore.GREEN + colorama.Style.BRIGHT +
          f'    [{datetime.now().strftime("%H:%M:%S")}] Semua Scrape Selesai — Total {total_menit:.1f} menit' +
          colorama.Style.RESET_ALL)
    _print_scrape_report(shop_reports)


# ── UPDATE HPP (tanpa scrape harga) ───────────────────────────────────────────
def update_hpp(shops):
    """Perbarui hanya kolom D (HPP) dari Jubelio API pada Excel yang sudah ada.
    Tidak melakukan scrape harga — fetch HPP live lalu tulis ke kolom D."""
    if not os.path.exists(EXCEL_PATH):
        print(colorama.Fore.RED + f'    File {EXCEL_PATH} belum ada. Jalankan SCRAPE DISCOUNT dulu.' + colorama.Style.RESET_ALL)
        return

    db_hpp     = load_hpp()
    all_misses = set()

    with xlwings.App(visible=False) as app:
        workbook    = app.books.open(EXCEL_PATH)
        sheet_names = [s.name for s in workbook.sheets]
        for shop in shops:
            if shop not in sheet_names:
                print(colorama.Fore.RED + f'    Sheet [{shop}] tidak ada di Excel — dilewati.' + colorama.Style.RESET_ALL)
                continue

            ws       = workbook.sheets[shop]
            last_row = _last_row(ws, COL_SKU)
            if last_row < 2:
                print(colorama.Fore.YELLOW + f'    [{shop}] kosong — dilewati.' + colorama.Style.RESET_ALL)
                continue

            # Kolom B = Nama Produk = kunci lookup HPP
            names    = ws.range(f'B2:B{last_row}').options(ndim=1).value
            new_hpp  = []
            updated  = 0
            for name in names:
                key = str(name).strip() if name is not None else ''
                val = db_hpp.get(key)
                if val is None:
                    all_misses.add(key)
                    val = 0
                else:
                    updated += 1
                new_hpp.append([val])

            # Tulis ulang kolom D (HPP) + format mata uang
            ws.range(f'D2:D{last_row}').value = new_hpp
            ws.range(f'D2:D{last_row}').api.NumberFormat = \
                '_-Rp* #.##0_-;-Rp* #.##0_-;_-Rp* "-"_-;_-@_-'
            print(colorama.Fore.YELLOW + f'    Update HPP [{shop}] — {updated}/{last_row - 1} SKU' + colorama.Style.RESET_ALL)

        workbook.save()

    if all_misses:
        print(f'\n{colorama.Fore.YELLOW}  ⚠  HPP TIDAK DITEMUKAN — perlu cek di Jubelio:{colorama.Style.RESET_ALL}')
        for sku in sorted(all_misses):
            print(f'       {sku}')
    else:
        print(f'\n  {colorama.Fore.GREEN}✓  Semua HPP berhasil diperbarui.{colorama.Style.RESET_ALL}')


# ── REPORT HELPERS ────────────────────────────────────────────────────────────
def _last_row(sh, col):
    return sh.range(col + str(sh.cells.last_cell.row)).end('up').row

def _col_values(sh, col, start=2, as_str=False):
    lr = _last_row(sh, col)
    if lr < start:
        return []
    vals = sh.range(f'{col}{start}:{col}{lr}').options(ndim=1).value
    if as_str:
        return [str(v).strip() for v in vals if v not in (None, '')]
    return [v for v in vals if v not in (None, '')]


# ── GENERATE REPORT ───────────────────────────────────────────────────────────
def generate_report(shops):
    with xlwings.App(visible=False) as app:
        workbook    = app.books.open(EXCEL_PATH)
        sheet_names = [s.name for s in workbook.sheets]

        # Bangun master SKU unik (urutan terjaga)
        skus = []
        for name in shops:
            if name not in sheet_names:
                continue
            sh = workbook.sheets[name]
            for k in _col_values(sh, COL_SKU, as_str=True):
                if k not in skus:
                    skus.append(k)

        # Kumpulkan harga per toko → DataFrame
        data = {'SKU INDUK': skus}
        for name in shops:
            if name not in sheet_names:
                data[name] = [0] * len(skus)
                continue
            sh   = workbook.sheets[name]
            keys = _col_values(sh, COL_SKU, as_str=True)
            vals = _col_values(sh, COL_DISKON)
            mp   = {k: v for k, v in zip(keys, vals)}
            data[name] = [mp.get(s, 0) for s in skus]

        df = pd.DataFrame(data)

        def status_row(row):
            v = [x for x in row[shops].tolist() if pd.notna(x) and x != 0]
            return "OK" if len(set(v)) <= 1 else "TRIGGER"
        df['STATUS'] = df.apply(status_row, axis=1)

        def delta_row(row):
            v = [x for x in row[shops].tolist() if pd.notna(x) and isinstance(x, (int, float)) and x != 0]
            return 0 if not v else max(v) - min(v)
        df.insert(df.columns.get_loc('STATUS') + 1, 'SELISIH', df.apply(delta_row, axis=1))

        # Tulis ke sheet OUT
        if OUT_SHEET not in [s.name for s in workbook.sheets]:
            workbook.sheets.add(name=OUT_SHEET, after=workbook.sheets[-1])
        out = workbook.sheets[OUT_SHEET]
        out.clear_contents()
        out['A1'].options(index=False).value = df
        out.range('A:Z').autofit()

        # Warnai kolom STATUS (batch via COM Union → 1 COM call per warna)
        status_col = len(shops) + 2
        last       = 1 + len(df)
        rng        = out.range((2, status_col), (last, status_col))
        status_vals = rng.options(ndim=1).value
        ws_api = out.api
        ok_union = trigger_union = None
        for i, v in enumerate(status_vals):
            cell_api = ws_api.Cells(i + 2, status_col)
            if v == "OK":
                ok_union = cell_api if ok_union is None else ws_api.Application.Union(ok_union, cell_api)
            elif v == "TRIGGER":
                trigger_union = cell_api if trigger_union is None else ws_api.Application.Union(trigger_union, cell_api)
        if ok_union:
            ok_union.Interior.Color = 198 + 239 * 256 + 206 * 65536    # hijau muda
        if trigger_union:
            trigger_union.Interior.Color = 255 + 199 * 256 + 206 * 65536  # merah muda

        # Warnai kolom SELISIH (batch via COM Union)
        delta_col  = status_col + 1
        rng_delta  = out.range((2, delta_col), (last, delta_col))
        delta_vals = rng_delta.options(ndim=1).value
        green_union = red_union = None
        for i, v in enumerate(delta_vals):
            if v is None:
                continue
            try:
                v = float(v)
            except Exception:
                continue
            cell_api = ws_api.Cells(i + 2, delta_col)
            if v > 100:
                red_union = cell_api if red_union is None else ws_api.Application.Union(red_union, cell_api)
            else:
                green_union = cell_api if green_union is None else ws_api.Application.Union(green_union, cell_api)
        if red_union:
            red_union.Interior.Color = 255 + 199 * 256 + 206 * 65536   # merah muda
        if green_union:
            green_union.Interior.Color = 198 + 239 * 256 + 206 * 65536  # hijau muda

        # Simpan sebagai file bertanggal
        folder    = os.path.dirname(workbook.fullname)
        base, ext = os.path.splitext(os.path.basename(workbook.fullname))
        new_path  = os.path.join(folder, f'{base}_{datetime.now().strftime("%Y-%m-%d")}{ext}')
        workbook.save(new_path)
        print(colorama.Fore.YELLOW + f'    Berhasil Generate Report → {os.path.basename(new_path)}' + colorama.Style.RESET_ALL)


# ── RUNNING ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(colorama.Back.RED + colorama.Fore.LIGHTWHITE_EX + "\n GENERATOR - Tabel Diskon TiktokShop \n" + colorama.Style.RESET_ALL)
    MENU = [
        " 1. CLEAR EXCEL",
        " 2. DOWNLOAD EXCEL",
        " 3. SCRAPE DISCOUNT",
        " 4. UPDATE HPP",
        " 5. GENERATE REPORT",
        " 6. EXIT",
    ]
    while True:
        try:
            menu = str(inquirer.list_input('PILIH PROGRAM', choices=MENU)).strip()
            if menu == "6. EXIT":
                break
            shops = select_shops()
            if not shops:
                print()
                continue
            if   menu == "1. CLEAR EXCEL":     clear_excel(shops)
            elif menu == "2. DOWNLOAD EXCEL":  download_excel(shops)
            elif menu == "3. SCRAPE DISCOUNT": scrape_discount(shops)
            elif menu == "4. UPDATE HPP":      update_hpp(shops)
            elif menu == "5. GENERATE REPORT": generate_report(shops)
            print()
        except KeyboardInterrupt:
            break
