import csv
import random
from pathlib import Path

random.seed(42)  # reproducible

ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "data"

CORE_SKU_FILE = DATA_DIR / "processed" / "core_15_skus.csv"
PRODUCTS_FILE = DATA_DIR / "raw" / "Products.csv"

OUT_DIR = DATA_DIR / "synthetic"   
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# ASUMSI RESEP 
# ---------------------------------------------------------------------------
# CATATAN DOSIS ESPRESSO:
# Semua 15 SKU inti, berdasar Description di Products.csv, secara eksplisit
# menyebut "1 shot espresso" -> TIDAK ada penggandaan dosis untuk
# latte/cappuccino (rule "2 shot untuk latte/cappuccino" versi sebelumnya
# DIHAPUS karena tidak didukung deskripsi produk). Standar dosis modern
# specialty coffee (bukan standar Italia lama 7-14g) memang ~18-20g per
# serving, dipakai seragam untuk semua minuman berbasis espresso di menu ini.

GRAM_PER_SHOT = 18          # g coffee dose per serving espresso (standar modern, bukan per "shot" lama)
HOT_WATER_ML = 30           # ml hot water tambahan untuk Americano
MILK_ML_HOT = 180           # ml milk input untuk hot latte-based
MILK_ML_ICE = 180           # ml milk input untuk iced latte-based
SYRUP_ML = 15               # ml flavored syrup per serving
ICE_G = 120                 # g ice per iced beverage
CHOCOLATE_POWDER_G = 15     # g chocolate powder per mocha
CITRUS_JUICE_ML = 60        # ml jus citrus untuk Sitrus Cafe (espresso + jus citrus, tanpa susu)

# Safety-stock & reorder assumptions (retail/F&B rule of thumb)
SAFETY_FACTOR = 1.5         # SafetyStock = 1.5 x avg_daily_usage (buffer ~1.5 hari)
LEAD_TIME_DAYS_DEFAULT = 2  # waktu supplier kirim ulang bahan baku

OUTLETS = ["Outlet_Bandung", "Outlet_Jakarta", "Outlet_Surabaya"]

# ---------------------------------------------------------------------------
# 1. LOAD DATA SUMBER
# ---------------------------------------------------------------------------
def load_core_skus():
    with open(CORE_SKU_FILE, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_products():
    with open(PRODUCTS_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {int(r["ProductId"]): r for r in rows}


# ---------------------------------------------------------------------------
# 2. MASTER INGREDIENTS
# ---------------------------------------------------------------------------
# id, name, category, unit, unit_cost(Rp), shelf_life_days, lead_time_days, supplier_type
INGREDIENTS = [
    ("ING01", "Biji Kopi Arabica", "Coffee Bean", "g", 350, 180, 3, "Roaster Partner"),
    ("ING02", "Biji Kopi Houseblend", "Coffee Bean", "g", 280, 180, 3, "Roaster Partner"),
    ("ING03", "Susu UHT Full Cream", "Dairy", "ml", 18, 10, 2, "Distributor Susu"),
    ("ING04", "Sirup Gula Aren", "Syrup", "ml", 40, 90, 5, "Supplier Sirup"),
    ("ING05", "Sirup Vanilla", "Syrup", "ml", 45, 120, 5, "Supplier Sirup"),
    ("ING06", "Sirup Apple Pie", "Syrup", "ml", 48, 120, 5, "Supplier Sirup"),
    ("ING07", "Sirup Butterscotch", "Syrup", "ml", 48, 120, 5, "Supplier Sirup"),
    ("ING08", "Bubuk Coklat", "Powder", "g", 90, 180, 5, "Supplier Bahan Kering"),
    ("ING09", "Es Batu", "Ice", "g", 2, 1, 1, "Produksi Internal"),
    ("ING10", "Air Panas/Dingin", "Water", "ml", 0.5, 365, 1, "Produksi Internal"),
    ("ING11", "Cup Hot 12oz", "Packaging", "pcs", 800, 365, 4, "Supplier Kemasan"),
    ("ING12", "Cup Ice 16oz", "Packaging", "pcs", 900, 365, 4, "Supplier Kemasan"),
    ("ING13", "Lid Cup", "Packaging", "pcs", 250, 365, 4, "Supplier Kemasan"),
    ("ING14", "Straw", "Packaging", "pcs", 150, 365, 4, "Supplier Kemasan"),
    ("ING15", "Jus Citrus", "Juice", "ml", 30, 3, 2, "Supplier Buah Segar"),
]
ING_BY_NAME = {row[1]: row[0] for row in INGREDIENTS}


def write_ingredients():
    path = OUT_DIR / "ingredients.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["IngredientId", "IngredientName", "Category", "Unit",
                    "UnitCostRp", "ShelfLifeDays", "LeadTimeDays", "SupplierType"])
        w.writerows(INGREDIENTS)
    return path


# ---------------------------------------------------------------------------
# 3. BOM RULE-BASED GENERATOR
#    Baca nama/variant/deskripsi produk -> tentukan komponen resep
# ---------------------------------------------------------------------------
def build_recipe(product):
    """Return list of (ingredient_name, qty, unit) for one product,
    based on simple keyword rules on Name/Variant/Description."""
    name = product["ProductName"].lower()
    variant = product["Variant"].lower()
    desc = product["Description"].lower()
    text = f"{name} {variant} {desc}"

    recipe = []
    is_ice = "ice" in variant or "dingin" in desc or "es batu" in desc
    is_hot = "hot" in variant or ("ice" not in variant and not is_ice)
    is_arabica = "arabica" in text
    is_houseblend = "houseblend" in text or "houesblend" in text

    # --- bean base: semua 15 SKU ini "1 shot espresso" per Description ->
    #     dosis seragam GRAM_PER_SHOT, tanpa multiplier jenis minuman.
    bean = "Biji Kopi Arabica" if is_arabica else "Biji Kopi Houseblend"
    if not is_arabica and not is_houseblend:
        bean = "Biji Kopi Houseblend"  # default rumah
    recipe.append((bean, GRAM_PER_SHOT, "g"))

    # --- americano / long black: tambah air, tanpa susu
    if "americano" in name or "shakencano" in name:
        recipe.append(("Air Panas/Dingin", HOT_WATER_ML, "ml"))

    # --- espresso murni: tidak ada tambahan lain
    if "espresso" in name and "latte" not in name and "cappuccino" not in name:
        pass

    # --- latte-based / milk-based drinks
    # CATATAN Butterscotch (id 25): tidak punya varian Ice di katalog
    # (hanya beda ukuran reguler vs "Gedhe"/id 26), jadi selalu diperlakukan
    # sebagai Hot -> default is_hot di atas sudah benar untuk kasus ini.
    milk_keywords = ["latte", "cappuccino", "moca", "friendly coffee", "butterscotch"]
    if any(k in name for k in milk_keywords):
        milk_ml = MILK_ML_ICE if is_ice else MILK_ML_HOT
        recipe.append(("Susu UHT Full Cream", milk_ml, "ml"))

    # --- flavor syrups by product name
    if "vanilla" in name:
        recipe.append(("Sirup Vanilla", SYRUP_ML, "ml"))
    if "apple pie" in name:
        recipe.append(("Sirup Apple Pie", SYRUP_ML, "ml"))
    if "butterscotch" in name:
        recipe.append(("Sirup Butterscotch", SYRUP_ML, "ml"))
    if "sitrus" in name or "citrus" in name:
        recipe.append(("Jus Citrus", CITRUS_JUICE_ML, "ml"))
    if "friendly coffee" in name or "shakencano" in name:
        recipe.append(("Sirup Gula Aren", SYRUP_ML, "ml"))  # ciri khas gula aren
    if "moca" in name:
        recipe.append(("Bubuk Coklat", CHOCOLATE_POWDER_G, "g"))

    # --- ice / packaging
    if is_ice:
        recipe.append(("Es Batu", ICE_G, "g"))
        recipe.append(("Cup Ice 16oz", 1, "pcs"))
        recipe.append(("Straw", 1, "pcs"))
    else:
        recipe.append(("Cup Hot 12oz", 1, "pcs"))
    recipe.append(("Lid Cup", 1, "pcs"))

    return recipe


def write_bom(core_skus, products):
    path = OUT_DIR / "bom.csv"
    rows = []
    for sku in core_skus:
        pid = int(sku["ProductId"])
        product = products[pid]
        recipe = build_recipe(product)
        for ing_name, qty, unit in recipe:
            ing_id = ING_BY_NAME[ing_name]
            rows.append([pid, product["ProductName"], product["Variant"],
                         ing_id, ing_name, round(qty, 1), unit])

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ProductId", "ProductName", "Variant",
                     "IngredientId", "IngredientName", "QtyPerServing", "Unit"])
        w.writerows(rows)
    return path, rows


# ---------------------------------------------------------------------------
# 4. INVENTORY GENERATOR (diturunkan dari avg daily usage per outlet)
# ---------------------------------------------------------------------------
def compute_daily_demand_per_outlet(core_skus):
    """avg daily unit sold per outlet, proxy dari TotalQtySold/ActiveDays/OutletCoverage."""
    demand = {}
    for sku in core_skus:
        pid = int(sku["ProductId"])
        total_qty = float(sku["TotalQtySold"])
        active_days = float(sku["ActiveDays"])
        outlet_coverage = float(sku["OutletCoverage"]) or 1
        avg_daily_total = total_qty / active_days
        avg_daily_per_outlet = avg_daily_total / outlet_coverage
        demand[pid] = avg_daily_per_outlet
    return demand


def compute_ingredient_daily_usage(bom_rows, daily_demand_per_outlet):
    """Sum(avg_daily_demand_per_outlet[product] * qty_per_serving) per ingredient."""
    usage = {}
    for pid, pname, variant, ing_id, ing_name, qty, unit in bom_rows:
        d = daily_demand_per_outlet.get(pid, 0)
        usage.setdefault(ing_id, {"name": ing_name, "unit": unit, "usage": 0.0})
        usage[ing_id]["usage"] += d * qty
    return usage


def write_inventory(bom_rows, daily_demand_per_outlet):
    path = OUT_DIR / "inventory.csv"
    ing_usage = compute_ingredient_daily_usage(bom_rows, daily_demand_per_outlet)
    lead_time_by_id = {row[0]: row[6] for row in INGREDIENTS}

    rows = []
    # Pilih 2 skenario shortage yang sengaja diinjeksikan untuk demo
    # (di Outlet_Bandung, karena itu contoh skenario di dokumen sprint)
    shortage_targets = {
        ("Outlet_Bandung", ING_BY_NAME["Susu UHT Full Cream"]),
        ("Outlet_Bandung", ING_BY_NAME["Es Batu"]),
    }

    for outlet in OUTLETS:
        for ing_id, info in ing_usage.items():
            avg_daily_usage = info["usage"]
            lead_time = lead_time_by_id.get(ing_id, LEAD_TIME_DAYS_DEFAULT)
            safety_stock = round(avg_daily_usage * SAFETY_FACTOR, 1)
            reorder_point = round(avg_daily_usage * lead_time + safety_stock, 1)

            # Kondisi normal: current stock antara reorder_point*1.3 - 2.2x
            # (variasi per outlet supaya tidak seragam sempurna)
            noise = random.uniform(1.3, 2.2)
            current_stock = round(reorder_point * noise, 1)

            status = "AMAN"
            if (outlet, ing_id) in shortage_targets:
                # Sengaja set di bawah reorder point (kasus demo shortage)
                current_stock = round(safety_stock * random.uniform(0.5, 0.85), 1)
                status = "KRITIS"
            elif current_stock < reorder_point:
                status = "PERLU_REORDER"

            rows.append([
                outlet, ing_id, info["name"],
                round(avg_daily_usage, 2), current_stock, safety_stock,
                reorder_point, lead_time, status
            ])

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["OutletId", "IngredientId", "IngredientName",
                     "AvgDailyUsage", "CurrentStock", "SafetyStock",
                     "ReorderPoint", "LeadTimeDays", "InitialStatus"])
        w.writerows(rows)
    return path, rows


# ---------------------------------------------------------------------------
# 5. LOG RINGKASAN (untuk ditempel di README / proposal)
# ---------------------------------------------------------------------------
def write_log(bom_rows, inventory_rows):
    path = OUT_DIR / "generation_log.txt"
    kritis = [r for r in inventory_rows if r[-1] == "KRITIS"]
    perlu = [r for r in inventory_rows if r[-1] == "PERLU_REORDER"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("RINGKASAN GENERATE DATA SINTETIS\n")
        f.write("=================================\n")
        f.write(f"Total baris BOM       : {len(bom_rows)}\n")
        f.write(f"Total baris Inventory : {len(inventory_rows)}\n")
        f.write(f"Outlet dengan status KRITIS       : {len(kritis)} baris\n")
        f.write(f"Outlet dengan status PERLU_REORDER: {len(perlu)} baris\n\n")
        f.write("Asumsi kunci:\n")
        f.write(f"  - {GRAM_PER_SHOT} g biji kopi per serving espresso (dosis modern, seragam, "
                 "tanpa multiplier shot; sesuai deskripsi produk yang semuanya '1 shot')\n")
        f.write(f"  - Susu hot {MILK_ML_HOT} ml / ice {MILK_ML_ICE} ml per gelas milk-based\n")
        f.write(f"  - Syrup {SYRUP_ML} ml per gelas flavored\n")
        f.write(f"  - Es batu {ICE_G} g per gelas ice\n")
        f.write(f"  - SafetyStock = {SAFETY_FACTOR} x rata-rata pemakaian harian\n")
        f.write("  - ReorderPoint = avg_daily_usage x LeadTimeDays + SafetyStock\n")
        f.write("  - Skenario shortage sengaja diinjeksi di Outlet_Bandung "
                 f"untuk Susu ({ING_BY_NAME['Susu UHT Full Cream']}) & "
                 f"Es Batu ({ING_BY_NAME['Es Batu']}) sebagai demo case.\n\n")
        f.write("Contoh baris KRITIS (untuk demo scenario):\n")
        for r in kritis:
            f.write(f"  {r}\n")
    return path


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    core_skus = load_core_skus()
    products = load_products()

    ing_path = write_ingredients()
    bom_path, bom_rows = write_bom(core_skus, products)
    daily_demand = compute_daily_demand_per_outlet(core_skus)
    inv_path, inv_rows = write_inventory(bom_rows, daily_demand)
    log_path = write_log(bom_rows, inv_rows)

    print("Selesai. File tersimpan di:", OUT_DIR)
    for p in [ing_path, bom_path, inv_path, log_path]:
        print(" -", p.name)


if __name__ == "__main__":
    main()
