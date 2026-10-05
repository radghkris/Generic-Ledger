# Generic Ledger

A production/recipe costing and planning tool for any small business that makes things to sell — food, tobacco, crafts, retail goods, whatever. Not tied to any specific product or industry.

Two local Python versions, sharing the same logic (`ledger_engine.py`) and the same data file:

- **`desktop_app.py`** — a standalone desktop window (Tkinter). No browser, no extra installs — just Python itself.
- **`app.py`** — a Streamlit version that runs in your browser at `http://localhost:8501`, if you'd rather have that.

## Run the desktop app (recommended if you don't want a browser tab)

Double-click **`run_desktop.bat`**, or from a terminal:

```bash
python desktop_app.py
```

No `pip install` needed — it only uses what Python already includes. `run_desktop.bat` launches it with `pythonw` (no console window) and closes itself immediately; if the window never appears, check `error_log.txt` it creates next to the script, or run `python desktop_app.py` from a terminal directly to see the error live.

## Run the browser (Streamlit) version instead

Double-click **`run.bat`** (sets itself up automatically), or from a terminal:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## First thing to do: set up your business

Open **Settings → Business Info** and set your business name, tagline, and icon — that's what shows in the window title and header. Everything else (recipes, ingredients, vendors) ships with one clearly-labeled example ("Sample Product") so you can see how the pieces fit together; delete it once you've got your own data in.

## Data

Everything you enter is saved to `ledger_data.json`, created next to the scripts the first time you run either version — both read and write the same file. That file is your data; back it up or copy it between machines as needed. It's excluded from this repo (`.gitignore`).

## What it does

- **Dashboard** — shortages weighted by how many active recipes need them ("Acquire Next"), and recipes graded tight or problematic by profit margin (cutoffs are editable in Settings) or over your maximum sale price.
- **Recipes** — ingredients, craft yield, sale price, free-text category; cost, profit and margin computed automatically, including labor. Toggle a recipe active/inactive right from the list.
- **Ingredients & Conversions** — unit costs, plus raw-to-finished conversions (e.g. bulk stock portioned into sellable units) that resolve automatically through the cost engine. Any ingredient can be marked "not bought from a vendor" with its own flat cost and a custom acquisition note (grow it, make it in-house, forage it — whatever fits your business) instead of a vendor price.
- **Vendors** — multiple vendor prices per ingredient across locations; cheapest is flagged automatically. Double-click any cell to edit it — including the Ingredient name, which fixes a misspelling everywhere at once.
- **Raw Inventory** — quantities on hand, an optional preferred supplier, and a free-text **To Order** note per ingredient. Edited in place in the table — no popups. **Copy Order List** copies the notes for pasting elsewhere; **Mark Order Received** adds each note's number to On Hand and clears it.
- **Crafted Inventory** — finished items made up, with a **Set Point** (how many you want to keep on hand). **Restock Planner to Set Points** fills the Planner with the shortfalls, and **Mark Made** adds the finished items here. See `docs/CRAFTED_INVENTORY_HANDOFF.md`.
- **Planner** — set target quantities per recipe, then **What To Order** (with a **Copy List** button, or Ctrl+C for the selected row) tells you exactly what to buy (and from where), make in-house, or otherwise acquire, walking through any conversions along the way. **Mark Made** deducts a completed run's ingredients from Inventory and reduces its remaining target.
- **Settings** — business branding, maximum sale price, margin grade cutoffs (healthy / good / tight / problematic), labor/overhead cost per unit of production time, and a tax-rate placeholder.

## Customizing for your business

- **Business Info** (Settings): name, tagline, icon — shown in the app's title/header.
- **Categories**: free text on each recipe — use whatever groupings make sense (e.g. "Tobacco", "Beverages", "Hardware").
- **Custom-cost ingredients**: for anything you don't buy from a vendor (grown, foraged, made in-house), check "Not bought from a vendor" on that ingredient and give it a flat cost and an acquisition note.
- **Labor & Overhead**: set your time-per-unit and rate once in Settings; it applies to every recipe automatically.
