import json
import math
import re
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "ledger_data.json"

# Starting data for a brand-new install: one clearly-fake example product so
# the mechanics (vendors, a conversion, a custom-cost/hand-made ingredient)
# are visible on first launch. Replace or delete all of it freely -- none of
# it is read by the code, it's just seed content.
SEED = {
    "ingredients": {
        "material-a": {"name": "Material A (example)", "unit": "ea"},
        "material-b": {"name": "Material B (example)", "unit": "ea"},
        "bulk-supply": {"name": "Bulk Supply (example)", "unit": "ea"},
        "portioned-supply": {"name": "Portioned Supply (example)", "unit": "ea"},
        "hand-finished-part": {"name": "Hand-Finished Part (example)", "unit": "ea",
                                "costMode": "custom", "customCost": 0.10, "customLabel": "Make in-house"},
    },
    "conversions": [
        {"id": "bulk-to-portioned", "inputId": "bulk-supply", "inputQty": 1, "outputId": "portioned-supply",
         "outputQty": 10, "cost": 0, "note": "1 Bulk Supply → 10 Portioned Supply"},
    ],
    "vendors": [
        {"id": "sample-supplier-a", "ingredientId": "material-a", "vendorName": "Sample Supplier", "town": "Sample Town", "price": 1.00, "stock": "unknown"},
        {"id": "sample-supplier-b", "ingredientId": "material-b", "vendorName": "Sample Supplier", "town": "Sample Town", "price": 0.50, "stock": "unknown"},
        {"id": "sample-supplier-bulk", "ingredientId": "bulk-supply", "vendorName": "Sample Supplier", "town": "Sample Town", "price": 5.00, "stock": "unknown"},
    ],
    "recipes": {
        "sample-product": {
            "name": "Sample Product (example — rename or delete me)", "category": "General", "yieldQty": 5,
            "salePrice": 3.00, "active": True,
            "ingredients": [
                {"ingredientId": "material-a", "qty": 2},
                {"ingredientId": "material-b", "qty": 1},
                {"ingredientId": "portioned-supply", "qty": 3},
                {"ingredientId": "hand-finished-part", "qty": 1},
            ],
        },
    },
    "inventory": {ing_id: {"qty": 0, "preferredVendorId": None} for ing_id in [
        "material-a", "material-b", "bulk-supply", "portioned-supply", "hand-finished-part",
    ]},
    "plan": {"targets": {"sample-product": {"enabled": True, "qty": 20}}},
    "crafted": {},
    "settings": {
        "businessName": "My Business", "tagline": "Product costing & production planner", "appIcon": "\U0001F4D2",
        "priceCap": 5.00,
        "marginHealthyPercent": 80, "marginGoodPercent": 65, "marginProblematicMaxPercent": 20,
        "laborRatePer30Min": 0.0, "processTimeMinutes": 0.0, "taxRatePercent": 0.0,
    },
}

# Settings keys that may be missing from a data file saved before a given
# feature existed. load_data() backfills only the missing keys onto an
# existing file -- it never touches what's already there.
SETTINGS_DEFAULTS = SEED["settings"]


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for key, default in SETTINGS_DEFAULTS.items():
            if key not in data.setdefault("settings", {}):
                data["settings"][key] = default
                changed = True
        if "crafted" not in data:
            data["crafted"] = {}
            changed = True
        for rows_name in ("vendors", "conversions"):
            if dedupe_ids(data.get(rows_name, [])):
                changed = True
        if changed:
            save_data(data)
        return data
    save_data(SEED)
    return json.loads(json.dumps(SEED))


def dedupe_ids(rows):
    """Repairs a list whose rows share an "id" (an earlier version could create
    these after a delete-then-add). The first row keeps its id; later ones get
    a fresh one. Returns True if anything changed."""
    taken, changed = set(), False
    for row in rows:
        if row["id"] in taken:
            row["id"] = unique_id(row["id"], taken | {r["id"] for r in rows})
            changed = True
        taken.add(row["id"])
    return changed


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip()).strip("-")
    return s or "item"


def unique_id(base, existing):
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def fmt_money(n):
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return "—"
    return f"${n:.2f}"


def ing_name(data, ing_id):
    ing = data["ingredients"].get(ing_id)
    return ing["name"] if ing else ing_id


def cheapest_vendor(data, ing_id):
    pool = [v for v in data["vendors"] if v["ingredientId"] == ing_id and v.get("price") is not None]
    return min(pool, key=lambda v: v["price"]) if pool else None


def ing_cost(data, ing_id, visiting=None):
    visiting = visiting or frozenset()
    if ing_id in visiting:
        return {"cost": 0.0, "warn": True, "reason": "circular"}
    ing = data["ingredients"].get(ing_id, {})
    if ing.get("costMode") == "custom":
        return {"cost": ing.get("customCost") or 0.0, "warn": False, "reason": "custom"}
    conv = next((c for c in data["conversions"] if c["outputId"] == ing_id), None)
    if conv:
        sub = ing_cost(data, conv["inputId"], visiting | {ing_id})
        out_qty = conv.get("outputQty") or 1
        cost = (sub["cost"] * (conv.get("inputQty") or 1) + (conv.get("cost") or 0)) / out_qty
        return {"cost": cost, "warn": sub["warn"], "reason": "conversion", "via": conv["inputId"]}
    inv = data["inventory"].get(ing_id, {})
    vendor = None
    pref_id = inv.get("preferredVendorId")
    if pref_id:
        vendor = next((v for v in data["vendors"] if v["id"] == pref_id and v.get("price") is not None), None)
    if not vendor:
        vendor = cheapest_vendor(data, ing_id)
    if vendor:
        return {"cost": vendor["price"], "warn": False, "reason": "vendor", "vendorId": vendor["id"]}
    return {"cost": 0.0, "warn": True, "reason": "no-price"}


def labor_cost_per_craft(data):
    """Overhead cost of the time a single craft/batch-slot takes to produce,
    using the shared Process Time x Labor Rate settings (same for every
    recipe -- see Settings). Both default to 0, so this is a no-op until set."""
    s = data["settings"]
    minutes = s.get("processTimeMinutes") or 0.0
    rate_per_30 = s.get("laborRatePer30Min") or 0.0
    return minutes * (rate_per_30 / 30.0)


def net_of_tax(data, amount):
    """What's actually kept from a sale after the tax rate (0% by default)."""
    rate = (data["settings"].get("taxRatePercent") or 0.0) / 100.0
    return amount * (1 - rate)


def recipe_craft_cost(data, recipe):
    total, warn, lines = 0.0, False, []
    for ri in recipe.get("ingredients", []):
        res = ing_cost(data, ri["ingredientId"])
        warn = warn or res["warn"]
        line_cost = res["cost"] * ri["qty"]
        total += line_cost
        lines.append({**ri, "unitCost": res["cost"], "lineCost": line_cost, "warn": res["warn"]})
    labor = labor_cost_per_craft(data)
    total += labor
    return {"total": total, "lines": lines, "warn": warn, "ingredientCost": total - labor, "laborCost": labor}


def recipe_metrics(data, recipe):
    craft = recipe_craft_cost(data, recipe)
    yield_qty = recipe["yieldQty"] if recipe.get("yieldQty", 0) > 0 else 1
    cost_per_item = craft["total"] / yield_qty
    sale = recipe.get("salePrice") or 0.0
    net_sale = net_of_tax(data, sale)
    profit = net_sale - cost_per_item
    margin = (profit / net_sale) if net_sale > 0 else None
    s = data["settings"]
    tier = margin_tier(s, margin)
    return {"craft": craft, "costPerItem": cost_per_item, "profit": profit, "margin": margin,
            "tier": tier, "overCap": sale > s["priceCap"], "netSale": net_sale}


def margin_tier(settings, margin):
    """Grade a profit margin (a fraction, 0.65 = 65%) into one of four tiers using
    the three cutoffs in Settings:
        healthy      at or over the healthy cutoff                       (default 80% and up)
        good         at or over the good cutoff                          (default 65% up to 80%)
        tight        above the problematic cutoff, below the good one    (default 20% up to 65%)
        problematic  at or under the problematic cutoff, or no revenue   (default 20% and under)
    The margin is rounded to one decimal first so the tier always agrees with the
    percentage shown on screen."""
    if margin is None:
        return "problematic"
    pct = round(margin * 100, 1)
    if pct <= settings.get("marginProblematicMaxPercent", 20):
        return "problematic"
    if pct >= settings.get("marginHealthyPercent", 80):
        return "healthy"
    if pct >= settings.get("marginGoodPercent", 65):
        return "good"
    return "tight"


def compute_plan(data):
    rows, totals = [], {}
    for rid, r in data["recipes"].items():
        t = data["plan"]["targets"].get(rid)
        if not t or not t.get("enabled") or not (t.get("qty", 0) > 0):
            continue
        yield_qty = r["yieldQty"] if r.get("yieldQty", 0) > 0 else 1
        crafts = math.ceil(t["qty"] / yield_qty)
        craft = recipe_craft_cost(data, r)
        rows.append({"recipe": r, "recipeId": rid, "target": t["qty"], "crafts": crafts,
                     "craftCost": craft["total"], "runCost": crafts * craft["total"], "warn": craft["warn"]})
        for ri in r.get("ingredients", []):
            need = crafts * ri["qty"]
            bucket = totals.setdefault(ri["ingredientId"], {"required": 0, "recipeIds": set()})
            bucket["required"] += need
            bucket["recipeIds"].add(rid)
    shortages = []
    for ing_id, d in totals.items():
        on_hand = data["inventory"].get(ing_id, {}).get("qty", 0)
        shortage = max(0, d["required"] - on_hand)
        shortages.append({"id": ing_id, "required": d["required"], "onHand": on_hand,
                          "shortage": shortage, "numRecipes": len(d["recipeIds"]),
                          "score": shortage * len(d["recipeIds"])})
    shortages.sort(key=lambda x: -x["shortage"])
    grow_next = sorted([s for s in shortages if s["shortage"] > 0], key=lambda x: -x["score"])[:5]
    return {"rows": rows, "shortages": shortages, "growNext": grow_next}


def used_in_recipes(data, ing_id):
    return [r for r in data["recipes"].values() if any(ri["ingredientId"] == ing_id for ri in r.get("ingredients", []))]


def used_in_conversions(data, ing_id):
    return [c for c in data["conversions"] if c["inputId"] == ing_id or c["outputId"] == ing_id]


def resolve_purchase_steps(data, ing_id, qty):
    steps, visiting, cur_id, cur_qty = [], set(), ing_id, qty
    for _ in range(20):
        if cur_id in visiting:
            steps.append({"type": "circular", "ingredientId": cur_id, "qty": cur_qty})
            break
        visiting.add(cur_id)
        ing = data["ingredients"].get(cur_id, {})
        if ing.get("costMode") == "custom":
            steps.append({"type": "custom", "ingredientId": cur_id, "qty": cur_qty,
                          "label": ing.get("customLabel") or "Acquire manually"})
            break
        conv = next((c for c in data["conversions"] if c["outputId"] == cur_id), None)
        if conv:
            input_qty_needed = math.ceil(cur_qty / (conv.get("outputQty") or 1)) * (conv.get("inputQty") or 1)
            steps.append({"type": "convert", "fromId": conv["inputId"], "fromQty": input_qty_needed,
                          "outputId": cur_id, "outputQty": cur_qty})
            cur_id, cur_qty = conv["inputId"], input_qty_needed
            continue
        inv = data["inventory"].get(cur_id, {})
        vendor = None
        pref_id = inv.get("preferredVendorId")
        if pref_id:
            vendor = next((v for v in data["vendors"] if v["id"] == pref_id and v.get("price") is not None), None)
        if not vendor:
            vendor = cheapest_vendor(data, cur_id)
        if vendor:
            steps.append({"type": "buy", "ingredientId": cur_id, "qty": cur_qty, "vendor": vendor})
        else:
            steps.append({"type": "no-source", "ingredientId": cur_id, "qty": cur_qty})
        break
    return steps


def crafted_entry(data, recipe_id):
    """Finished-goods record for a recipe: how many are made up (qty) and how many
    we want to keep on hand (setPoint). Created on first use."""
    return data.setdefault("crafted", {}).setdefault(recipe_id, {"qty": 0, "setPoint": 0})


def crafted_short(data, recipe_id):
    """How many finished items we're under the set point (never negative)."""
    c = data.get("crafted", {}).get(recipe_id) or {}
    return max(0.0, (c.get("setPoint") or 0) - (c.get("qty") or 0))


def apply_made(data, recipe_id, crafts):
    """Deduct ingredients for `crafts` batches of recipe_id from inventory, add the
    finished items to crafted stock, and reduce its remaining plan target by the
    items produced. Returns a list of human-readable ingredient shortfalls
    (inventory is clamped to 0, never negative)."""
    r = data["recipes"][recipe_id]
    yield_qty = r["yieldQty"] if r.get("yieldQty", 0) > 0 else 1
    shortfalls = []
    for li in r.get("ingredients", []):
        need = crafts * li["qty"]
        inv = data["inventory"].setdefault(li["ingredientId"], {"qty": 0, "preferredVendorId": None})
        have = inv.get("qty", 0) or 0
        if need > have:
            shortfalls.append(f"{ing_name(data, li['ingredientId'])} (had {have:g}, used {need:g})")
        inv["qty"] = max(0.0, have - need)
    t = data["plan"]["targets"].get(recipe_id, {"enabled": False, "qty": 0})
    t["qty"] = max(0.0, (t.get("qty", 0) or 0) - crafts * yield_qty)
    data["plan"]["targets"][recipe_id] = t
    c = crafted_entry(data, recipe_id)
    c["qty"] = (c.get("qty") or 0) + crafts * yield_qty
    return shortfalls


def add_to_receipt(order, recipe_id, qty):
    """Adds `qty` of a recipe to a counter order (a list of {"recipeId", "qty"}),
    merging with an existing line for the same item."""
    for line in order:
        if line["recipeId"] == recipe_id:
            line["qty"] += qty
            return
    order.append({"recipeId": recipe_id, "qty": qty})


def receipt_rows(data, order):
    """(name, qty, unit price, line total) for each line at the recipe's current
    sale price. Lines for recipes that have since been deleted are skipped."""
    rows = []
    for line in order:
        r = data["recipes"].get(line["recipeId"])
        if not r:
            continue
        price = r.get("salePrice") or 0
        rows.append((r["name"], line["qty"], price, price * line["qty"]))
    return rows


def receipt_total(data, order):
    return sum(row[3] for row in receipt_rows(data, order))


def receipt_text(data, order, title="Receipt"):
    """Plain-text receipt, ready to paste into chat or a note."""
    rows = receipt_rows(data, order)
    lines = [title, ""]
    for name, qty, price, total in rows:
        lines.append(f"{qty:g} x {name} @ {fmt_money(price)} = {fmt_money(total)}")
    lines += ["", f"Total: {fmt_money(sum(r[3] for r in rows))}"]
    return "\n".join(lines)


def order_line_text(data, top_id, shortage_qty):
    steps = resolve_purchase_steps(data, top_id, shortage_qty)
    last = steps[-1]
    if last["type"] == "custom":
        main = last["label"]
    elif last["type"] == "buy":
        v = last["vendor"]
        town = f" ({v['town']})" if v.get("town") else ""
        main = f"Buy {last['qty']:g} {ing_name(data, last['ingredientId'])} — {v['vendorName']}{town} @ {fmt_money(v['price'])}/ea = {fmt_money(v['price'] * last['qty'])}"
    elif last["type"] == "no-source":
        main = f"No price set for {ing_name(data, last['ingredientId'])} — add a vendor"
    else:
        main = f"Circular conversion on {ing_name(data, last['ingredientId'])}"
    if len(steps) > 1:
        via = ", ".join(f"{s['outputQty']:g} {ing_name(data, s['outputId'])} ← {s['fromQty']:g} {ing_name(data, s['fromId'])}" for s in steps[:-1])
        main += f"  (via {via})"
    return main
