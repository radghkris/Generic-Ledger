# Crafted Inventory — Handoff Guide

Covers the **Crafted Inventory** tab, the Planner changes that go with it, and the "Mark Made" link.
Desktop app only (`desktop_app.py` + `ledger_engine.py`). The Streamlit app does not have this feature.

## 1. What it's for

Raw Inventory answers "what ingredients do we have?". Crafted Inventory answers "how many **finished** items do we have made up, and how many do we *want* on hand?".

Each recipe gets two numbers:

| Field | Meaning |
|---|---|
| **On Hand** | Finished items currently made up |
| **Set Point** | How many we want to keep made up (0 = not tracked) |

**Short** = Set Point − On Hand, never below 0. The Planner uses the shortfall to decide what to make.

## 2. Day-to-day use

1. **Take stock.** Crafted Inventory tab → double-click **On Hand** on each recipe, type the count, Enter. Esc cancels; clicking away also saves.
2. **Set targets.** Double-click **Set Point** and enter how many to keep on hand. Leave at 0 for anything you don't want managed this way.
3. **Plan.** Click **Restock to Set Points** (on either the Crafted tab or the Planner). Confirm the prompt. The app jumps to the Planner with targets filled in; **What To Order** then shows the raw materials needed.
4. **Craft, then record it.** In the Planner select the recipe → **Mark Made…** → enter how many crafts you did. That deducts ingredients, adds the finished items to Crafted stock, and lowers the Planner target by the same amount.
5. **Selling does not update stock.** After selling, lower **On Hand** by hand (see §6).

Row colors on the Crafted tab: amber = under set point, red = under set point with none on hand, plain/striped = at or above set point.

## 3. What "Restock to Set Points" does (exactly)

For every recipe that is **active** and has a **set point > 0**:

- Planner target ← shortfall (Set Point − On Hand, min 0)
- Enabled ← true only if the shortfall is > 0

Not touched: recipes with no set point, and inactive recipes (including their targets and Enabled flags). It **overwrites** existing targets for the recipes it does touch, which is why it asks for confirmation. Targets are counted in **finished items**; crafts needed = target ÷ yield, rounded up (existing Planner behavior).

## 4. Where it lives in the code

**`ledger_engine.py`**
- `crafted_entry(data, recipe_id)` — returns (and creates on first use) `data["crafted"][recipe_id]`.
- `crafted_short(data, recipe_id)` — the shortfall, clamped at 0.
- `apply_made(data, recipe_id, crafts, notes=None)` — deducts raw ingredients (never below 0), reduces the plan target, **and adds `crafts × yield` to crafted `qty`**. If an ingredient is short on hand but has a conversion (e.g. 0 Sugar, conversion 1 Sugarcane → 5 Sugar), the shortfall is assumed to have come from the base ingredient: whole conversion batches are taken out of its stock and the unused remainder of the output is added back (71 Sugar needed, 0 on hand → 15 Sugarcane used, 4 Sugar left). It chains through further conversions. A line per conversion is appended to `notes` if a list is passed. Returns a list of ingredient shortfalls for the warning dialog.
- `load_data()` — adds an empty `"crafted": {}` to older data files on load. Nothing else in the file is modified.

**`desktop_app.py`** (all methods on `LedgerApp`)
- `_build_crafted`, `_refresh_crafted` — the tab, its table, row tinting, stock-value total.
- `_crafted_cell_click` — maps double-clicks on columns `#3` (On Hand) and `#4` (Set Point) to the inline editor.
- `_edit_crafted_field(rid, field, raw)` — validates, writes, saves, refreshes. Shared by the Crafted tab **and** the Planner.
- `_restock_to_set_points` — the restock action in §3.
- Planner: columns are now `Enabled, Recipe, In Stock, Set Point, Target Qty, Crafts Needed, Run Cost`. In `_planner_cell_click`: `#1` toggles Enabled, `#3`/`#4` edit the crafted record, `#5` edits Target Qty. **If you add or reorder Planner columns, update these indices.**
- `refresh_all` calls `_refresh_crafted` before `_refresh_planner`.
- `_delete_selected_recipe` also removes that recipe's crafted record.

## 5. Data model

Stored in `ledger_data.json` alongside everything else:

```json
"crafted": {
  "sample-product": { "qty": 15.0, "setPoint": 60.0 }
}
```

- Keyed by recipe id. A recipe with no entry is treated as `qty 0, setPoint 0`; entries are created lazily on first edit or first Mark Made.
- Numbers are floats and displayed with `:g` (so `15.0` shows as `15`).
- Stock value on the tab = `qty × cost per item` using the live recipe cost (ingredients + labor, ÷ yield). It moves when ingredient prices or labor settings change; it is not a historical cost.

## 6. Known limits / decisions to revisit

- **No "sold" action.** Selling doesn't reduce On Hand. A small "Sold…" button (qty → subtract, floor at 0) next to Mark Made would be the natural addition.
- **Mark Made vs. Restock can double-count if misused.** Targets are meant to be *remaining items to make*. Restock sets them from the shortfall; Mark Made lowers them as you craft. Don't hand-edit On Hand *and* run Mark Made for the same batch.
- **Inventory is not reduced below zero** on Mark Made. An ingredient with nothing to convert from (or whose base ingredient is also short) is clamped to 0 and warned about, so the books can drift if raw stock wasn't accurate. Short ingredients that *do* have a conversion are taken from the base ingredient, even if that ingredient is normally bought directly. Ingredients marked "not bought from a vendor" (custom cost) are never converted.
- **Whole items are assumed** in practice but nothing enforces integers.
- **Inactive recipes are skipped** by Restock. Re-activate a recipe on the Recipes tab to include it.
- **Desktop only.** `app.py` (Streamlit) shares the engine, so it will not break, but it has no UI for this data.
- **Existing Mark Made on old data:** crafted stock only counts from the first Mark Made after upgrading; past batches aren't backfilled.

## 7. Test checklist (no automated tests exist in the repo)

1. Fresh/old data file loads; `crafted` appears as `{}`; other data is unchanged.
2. Set On Hand and Set Point on the Crafted tab; confirm Short, tint colors, and the stock-value total.
3. Edit In Stock / Set Point from the Planner — the Crafted tab shows the same numbers.
4. Restock: decline (nothing changes) → accept (targets = shortfall; only short recipes enabled; recipes with no set point untouched; lands on Planner).
5. Mark Made 4 crafts of a yield-1 recipe: On Hand +4, target −4, ingredients deducted, shortage warning only when raw stock runs out.
6. Delete a recipe: its crafted record disappears. Toggle dark mode: the tab survives the rebuild.
7. Sort a Crafted column, edit a cell — the sort should persist.

These were run as ad-hoc scripts when the feature was built (all passing), not kept as a suite.

## 8. Tab rename

The old **Inventory** tab is now **Raw Inventory**. Code still calls it `tab_inv` / `inv_tree` / `_refresh_inventory`; only the tab label changed.

## 9. Generic Ledger notes

Ported from the Smokehouse (Blackwater) ledger. The code and behavior are the same. Two things came along with it:

- **Sort persistence.** Tables now keep their sort across edits and refreshes (`restore_sort` / `_reorder_by_sort` in `desktop_app.py`). Previously, sorting Recipes or the Pricing Watch and then editing anything dropped the sort, and sorting wiped the margin-tier row colors. Both are fixed.
- **Tab rename.** Same as §8: Inventory is now **Raw Inventory**.
