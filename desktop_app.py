import ctypes
import re
import sys
import traceback
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk, messagebox

import ledger_engine as eng

MONEY_COLS_HELP = "Double-click a row where noted to edit it."

# A warm ledger-book look: aged paper, ink brown, rust-red accent.
# Swap these if you want a different default palette.
BG = "#f2e9d6"
SURFACE = "#fbf5e8"
SURFACE2 = "#ece0c4"
INK = "#2c2013"
INK_DIM = "#6c5c42"
LINE = "#d9cba8"
ACCENT = "#9a3324"
ACCENT2 = "#a9762f"
GOOD = "#3d7a4a"
GOOD_BG = "#d9d9c2"
WARN = "#b0791e"
WARN_BG = "#e7d7b9"
BAD = "#a3283f"
BAD_BG = "#e7cec1"

ROW_EVEN_BG = SURFACE
ROW_ODD_BG = SURFACE2

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
DISPLAY_FONT_NAME = "Rye"
BODY_FONT_NAME = "Libre Franklin"
RESOLVED = {"display": "Georgia", "body": "Segoe UI"}


def load_local_fonts():
    """Registers the bundled .ttf files for this process only (Windows) so the
    app can use the same Rye/Libre Franklin faces as the browser version
    without installing anything system-wide. Falls back silently elsewhere."""
    if sys.platform != "win32" or not FONTS_DIR.is_dir():
        return
    FR_PRIVATE = 0x10
    try:
        for f in FONTS_DIR.glob("*.ttf"):
            ctypes.windll.gdi32.AddFontResourceExW(str(f), FR_PRIVATE, 0)
    except Exception:
        pass


def resolve_fonts(root):
    """Returns (display_family, body_family) — the real bundled faces if Tk can
    see them after load_local_fonts(), else the closest built-in stand-ins."""
    available = set(tkfont.families(root))
    display = DISPLAY_FONT_NAME if DISPLAY_FONT_NAME in available else "Georgia"
    body = BODY_FONT_NAME if BODY_FONT_NAME in available else "Segoe UI"
    return display, body


def center(win, parent):
    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    x = parent.winfo_x() + (parent.winfo_width() - w) // 2
    y = parent.winfo_y() + (parent.winfo_height() - h) // 2
    win.geometry(f"+{max(x,0)}+{max(y,0)}")


def _sort_key(raw):
    s = str(raw).strip()
    stripped = s.replace("$", "").replace(",", "").replace("%", "").replace("★", "").strip()
    try:
        return (0, float(stripped))
    except ValueError:
        return (1, s.lower())


def _reorder_by_sort(tree, col, reverse):
    items = [(tree.set(k, col), k) for k in tree.get_children("")]
    items.sort(key=lambda pair: _sort_key(pair[0]), reverse=reverse)
    for index, (_, k) in enumerate(items):
        tree.move(k, "", index)


def sort_tree_column(tree, col, reverse):
    """Header-click handler. Reorders only — never touches row tags, since some
    trees (Recipes, Pricing Watch, Crafted Inventory) use tags for status coloring
    rather than zebra striping."""
    tree._sort_state = (col, reverse)
    _reorder_by_sort(tree, col, reverse)
    tree.heading(col, command=lambda: sort_tree_column(tree, col, not reverse))


def restore_sort(tree):
    """Call after repopulating a tree whose rows are colored by something other than
    zebra striping (status tags) — reapplies the tree's last sort, if any, without
    touching tags. Needed because every refresh fully deletes and re-inserts rows,
    which would otherwise silently drop any sort the user clicked into place."""
    state = getattr(tree, "_sort_state", None)
    if state:
        _reorder_by_sort(tree, *state)


def stripe_tree(tree):
    """Call after repopulating a plain zebra-striped tree — reapplies the last sort
    (see restore_sort) and re-stripes; both must happen after every refresh since
    rows are fully deleted and re-inserted each time."""
    restore_sort(tree)
    for i, k in enumerate(tree.get_children("")):
        tree.item(k, tags=("even" if i % 2 == 0 else "odd",))


def configure_tier_tags(tree):
    tree.tag_configure("tier_healthy", background=GOOD_BG, foreground=GOOD)
    tree.tag_configure("tier_good", background=SURFACE2, foreground=GOOD)
    tree.tag_configure("tier_tight", background=WARN_BG, foreground=WARN)
    tree.tag_configure("tier_problematic", background=BAD_BG, foreground=BAD)


def make_tree(parent, columns, widths=None, height=10, sortable=True):
    frame = ttk.Frame(parent, relief="solid", borderwidth=1)
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse", height=height)
    tree.tag_configure("even", background=ROW_EVEN_BG)
    tree.tag_configure("odd", background=ROW_ODD_BG)
    for c in columns:
        header_text = c.upper()
        if sortable:
            tree.heading(c, text=header_text, command=lambda c=c: sort_tree_column(tree, c, False))
        else:
            tree.heading(c, text=header_text)
        tree.column(c, width=(widths or {}).get(c, 110), anchor="w", stretch=True)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


def autowrap_toolbar(bar, label):
    """Lets `label` wrap onto extra lines so the buttons beside it are never pushed
    off the edge of a narrow window or a high-DPI display."""
    def refit(_event=None):
        others = sum(c.winfo_reqwidth() + 16 for c in bar.winfo_children() if c is not label)
        avail = max(140, bar.winfo_width() - others - 30)
        if str(label.cget("wraplength")) != str(avail):
            label.configure(wraplength=avail, justify="left")
    bar.bind("<Configure>", refit)


_SCROLL_FRAMES = []
_WHEEL = {"bound": False}


def _wheel_router(event):
    live = [f for f in _SCROLL_FRAMES if f.winfo_exists()]
    if not live:
        return
    try:
        under = live[0].winfo_containing(event.x_root, event.y_root)
    except (tk.TclError, KeyError):
        return
    for frame in list(_SCROLL_FRAMES):
        if not frame.winfo_exists():
            _SCROLL_FRAMES.remove(frame)
        elif frame.winfo_ismapped() and under is not None and (under == frame or str(under).startswith(str(frame) + ".")):
            frame.scroll_by(event)
            return


def _focus_router(event):
    """Tabbing/clicking into a field that's scrolled out of view scrolls it into view."""
    path = str(event.widget)
    for frame in list(_SCROLL_FRAMES):
        if frame.winfo_exists() and path.startswith(str(frame) + "."):
            frame.reveal(event.widget)
            return


class ScrollFrame(ttk.Frame):
    """A frame that scrolls when its contents are taller (or wider) than the room
    it's given. Put widgets in `.body`. The mouse wheel works anywhere over it
    (hold Shift for sideways)."""

    def __init__(self, parent, max_height=None):
        super().__init__(parent)
        self.max_height = max_height      # cap the visible height (then scroll); None = fill the space given
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=BG, yscrollincrement=24, xscrollincrement=24)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vsb.set, xscrollcommand=self.hsb.set)
        self.body = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._needs_v = self._needs_h = False
        self.body.bind("<Configure>", self._sync)
        self.bind("<Configure>", self._sync)
        if not _WHEEL["bound"]:
            _WHEEL["bound"] = True
            self.bind_all("<MouseWheel>", _wheel_router, add="+")
            self.bind_all("<FocusIn>", _focus_router, add="+")
            # otherwise wheeling past a dropdown silently changes its selection
            self.unbind_class("TCombobox", "<MouseWheel>")
        _SCROLL_FRAMES.append(self)

    def _sync(self, _event=None):
        total_w, total_h = self.winfo_width(), self.winfo_height()
        if total_w <= 1:
            return
        body_w, body_h = self.body.winfo_reqwidth(), self.body.winfo_reqheight()
        if self.max_height:
            self.canvas.configure(height=min(body_h, self.max_height))
            self._needs_v = body_h > self.max_height
        else:
            self._needs_v = body_h > total_h
        self._needs_h = body_w > total_w - 18
        (self.vsb.grid if self._needs_v else self.vsb.grid_remove)()
        (self.hsb.grid if self._needs_h else self.hsb.grid_remove)()
        canvas_w = max(self.canvas.winfo_width(), 1)
        self.canvas.itemconfigure(self._window, width=max(canvas_w, body_w))
        self.canvas.configure(scrollregion=(0, 0, max(canvas_w, body_w), max(self.canvas.winfo_height(), body_h)))
        if not self._needs_v:
            self.canvas.yview_moveto(0)
        if not self._needs_h:
            self.canvas.xview_moveto(0)

    def reveal(self, widget):
        if not self._needs_v:
            return
        view_h = self.canvas.winfo_height()
        total_h = max(self.body.winfo_reqheight(), view_h)
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        view_top = self.canvas.canvasy(0)
        if top < view_top:
            self.canvas.yview_moveto(max(0, top - 8) / total_h)
        elif bottom > view_top + view_h:
            self.canvas.yview_moveto(min(total_h - view_h, bottom + 8 - view_h) / total_h)

    def scroll_by(self, event):
        notches = max(1, abs(event.delta) // 120)
        steps = -notches if event.delta > 0 else notches
        if event.state & 0x1:
            if self._needs_h:
                self.canvas.xview_scroll(steps * 2, "units")
        elif self._needs_v:
            self.canvas.yview_scroll(steps * 2, "units")


class IngredientLinesEditor(ttk.Frame):
    """A small editable list of (ingredient, qty) rows used inside the recipe dialog."""

    def __init__(self, parent, ingredient_names, initial_lines, on_change=None):
        super().__init__(parent)
        self.ingredient_names = ingredient_names
        self.on_change = on_change
        self.rows = []
        cap = int(300 * float(self.tk.call("tk", "scaling")) / 1.333)      # ~8 lines, then scroll
        self.scroller = ScrollFrame(self, max_height=cap)
        self.rows_frame = self.scroller.body
        self.scroller.pack(fill="x")
        for name, qty in initial_lines:
            self._add_row(name, qty)
        if not initial_lines and ingredient_names:
            self._add_row(ingredient_names[0], 1)
        ttk.Button(self, text="+ ingredient line", command=lambda: self._add_row(ingredient_names[0] if ingredient_names else "", 1, reveal=True)).pack(anchor="w", pady=(4, 0))

    def _add_row(self, name, qty, reveal=False):
        row = ttk.Frame(self.rows_frame)
        row.pack(fill="x", pady=2)
        combo = ttk.Combobox(row, values=self.ingredient_names, state="readonly", width=24)
        combo.set(name)
        combo.pack(side="left", padx=(0, 6))
        qty_var = tk.StringVar(value=str(qty))
        qty_entry = ttk.Entry(row, textvariable=qty_var, width=8)
        qty_entry.pack(side="left", padx=(0, 6))
        entry = {"frame": row, "combo": combo, "qty_var": qty_var}
        remove_btn = ttk.Button(row, text="✖", width=3, command=lambda: self._remove_row(entry))
        remove_btn.pack(side="left")
        self.rows.append(entry)
        if reveal:
            def to_bottom():
                self.scroller.update_idletasks()
                self.scroller._sync()
                self.scroller.canvas.yview_moveto(1.0)
            self.after_idle(to_bottom)
        if self.on_change:
            combo.bind("<<ComboboxSelected>>", lambda e: self.on_change())
            qty_entry.bind("<KeyRelease>", lambda e: self.on_change())
            self.on_change()

    def _remove_row(self, entry):
        entry["frame"].destroy()
        self.rows.remove(entry)
        if self.on_change:
            self.on_change()

    def get_lines(self, name_to_id):
        out = []
        for e in self.rows:
            name = e["combo"].get()
            try:
                qty = float(e["qty_var"].get())
            except ValueError:
                qty = 0
            if name in name_to_id and qty > 0:
                out.append({"ingredientId": name_to_id[name], "qty": qty})
        return out


class RecipeDialog(tk.Toplevel):
    def __init__(self, app, recipe_id=None):
        super().__init__(app)
        self.app = app
        self.recipe_id = recipe_id
        self.existing = app.data["recipes"].get(recipe_id) if recipe_id else None
        self.title("Edit Recipe" if self.existing else "Add Recipe")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(background=BG)

        ids_sorted = sorted(app.data["ingredients"], key=lambda i: app.data["ingredients"][i]["name"])
        self.name_to_id = {app.data["ingredients"][i]["name"]: i for i in ids_sorted}
        names_sorted = [app.data["ingredients"][i]["name"] for i in ids_sorted]

        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=self.existing["name"] if self.existing else "")
        ttk.Entry(form, textvariable=self.name_var, width=36).grid(row=0, column=1, columnspan=3, sticky="we", pady=2)

        ttk.Label(form, text="Category").grid(row=1, column=0, sticky="w")
        self.cat_var = tk.StringVar(value=self.existing["category"] if self.existing else "General")
        ttk.Entry(form, textvariable=self.cat_var, width=14).grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(form, text="Yield / craft").grid(row=1, column=2, sticky="w")
        self.yield_var = tk.StringVar(value=str(self.existing["yieldQty"]) if self.existing else "1")
        ttk.Entry(form, textvariable=self.yield_var, width=8).grid(row=1, column=3, sticky="w", pady=2)

        ttk.Label(form, text="Sale price").grid(row=2, column=0, sticky="w")
        self.price_var = tk.StringVar(value=str(self.existing["salePrice"]) if self.existing else str(app.data["settings"]["priceCap"]))
        price_entry = ttk.Entry(form, textvariable=self.price_var, width=8)
        price_entry.grid(row=2, column=1, sticky="w", pady=2)
        price_entry.bind("<KeyRelease>", lambda e: self._update_margin_preview())

        self.active_var = tk.BooleanVar(value=self.existing["active"] if self.existing else True)
        ttk.Checkbutton(form, text="Active (included in planner by default)", variable=self.active_var).grid(row=2, column=2, columnspan=2, sticky="w")

        self.margin_var = tk.StringVar(value="—")

        ttk.Label(form, text="Ingredients").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        initial_lines = [(eng.ing_name(app.data, l["ingredientId"]), l["qty"]) for l in self.existing["ingredients"]] if self.existing else []
        self.lines_editor = IngredientLinesEditor(form, names_sorted, initial_lines, on_change=self._update_margin_preview)
        self.lines_editor.grid(row=3, column=1, columnspan=3, sticky="we", pady=(8, 0))

        ttk.Label(form, textvariable=self.margin_var, font=(RESOLVED["body"], 10, "bold"), foreground=GOOD).grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 0))

        btns = ttk.Frame(form)
        btns.grid(row=5, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left")

        yield_entry_widgets = [w for w in form.grid_slaves(row=1, column=3)]
        for w in yield_entry_widgets:
            w.bind("<KeyRelease>", lambda e: self._update_margin_preview())

        self._update_margin_preview()
        center(self, app)

    def _update_margin_preview(self):
        try:
            yield_qty = max(1, float(self.yield_var.get() or 1))
        except ValueError:
            yield_qty = 1
        try:
            sale = max(0.0, float(self.price_var.get() or 0))
        except ValueError:
            sale = 0.0
        lines = self.lines_editor.get_lines(self.name_to_id) if hasattr(self, "lines_editor") else []
        ingredient_cost = sum(eng.ing_cost(self.app.data, l["ingredientId"])["cost"] * l["qty"] for l in lines)
        labor_cost = eng.labor_cost_per_craft(self.app.data)
        cost_total = ingredient_cost + labor_cost
        cost_per_item = cost_total / yield_qty
        net_sale = eng.net_of_tax(self.app.data, sale)
        profit = net_sale - cost_per_item
        if net_sale > 0:
            margin_pct = profit / net_sale * 100
            self.margin_var.set(
                f"{margin_pct:.0f}% margin is {eng.fmt_money(profit)}  "
                f"(cost {eng.fmt_money(cost_per_item)}/item — ingredients {eng.fmt_money(ingredient_cost/yield_qty)} + labor {eng.fmt_money(labor_cost/yield_qty)}; sale {eng.fmt_money(sale)})"
            )
        else:
            self.margin_var.set(f"Cost {eng.fmt_money(cost_per_item)}/item (incl. labor) — set a sale price to see margin")

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Name is required.", parent=self)
            return
        lines = self.lines_editor.get_lines(self.name_to_id)
        if not lines:
            messagebox.showerror("Missing ingredients", "Add at least one ingredient.", parent=self)
            return
        try:
            yield_qty = max(1, int(float(self.yield_var.get())))
            sale_price = max(0.0, float(self.price_var.get()))
        except ValueError:
            messagebox.showerror("Invalid number", "Yield and sale price must be numbers.", parent=self)
            return
        payload = {"name": name, "category": self.cat_var.get(), "yieldQty": yield_qty,
                   "salePrice": sale_price, "active": self.active_var.get(), "ingredients": lines}
        data = self.app.data
        if self.recipe_id:
            data["recipes"][self.recipe_id] = payload
        else:
            new_id = eng.unique_id(eng.slugify(name), set(data["recipes"]))
            data["recipes"][new_id] = payload
            data["plan"]["targets"][new_id] = {"enabled": payload["active"], "qty": 100}
        eng.save_data(data)
        self.app.refresh_all()
        self.destroy()


class IngredientDialog(tk.Toplevel):
    def __init__(self, app, ing_id=None):
        super().__init__(app)
        self.app = app
        self.ing_id = ing_id
        existing = app.data["ingredients"].get(ing_id) if ing_id else None
        self.title("Edit Ingredient" if existing else "Add Ingredient")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(background=BG)

        form = ttk.Frame(self, padding=12)
        form.pack()
        ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar(value=existing["name"] if existing else "")
        ttk.Entry(form, textvariable=self.name_var, width=28).grid(row=0, column=1, pady=2)
        ttk.Label(form, text="Unit").grid(row=1, column=0, sticky="w")
        self.unit_var = tk.StringVar(value=existing["unit"] if existing else "ea")
        ttk.Entry(form, textvariable=self.unit_var, width=28).grid(row=1, column=1, pady=2)

        ttk.Separator(form).grid(row=2, column=0, columnspan=2, sticky="we", pady=8)
        self.custom_var = tk.BooleanVar(value=(existing or {}).get("costMode") == "custom")
        ttk.Checkbutton(form, text="Not bought from a vendor (grown, made in-house, foraged...)",
                        variable=self.custom_var, command=self._toggle_custom).grid(row=3, column=0, columnspan=2, sticky="w")
        self.custom_frame = ttk.Frame(form)
        self.custom_frame.grid(row=4, column=0, columnspan=2, sticky="we", pady=(4, 0))
        ttk.Label(self.custom_frame, text="Cost/unit").grid(row=0, column=0, sticky="w")
        self.custom_cost_var = tk.StringVar(value=str((existing or {}).get("customCost", 0.0)))
        ttk.Entry(self.custom_frame, textvariable=self.custom_cost_var, width=10).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(self.custom_frame, text="Acquisition note").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.custom_label_var = tk.StringVar(value=(existing or {}).get("customLabel", ""))
        ttk.Entry(self.custom_frame, textvariable=self.custom_label_var, width=28).grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(self.custom_frame, text="Shown on the Planner's What To Order list instead of a vendor, e.g. \"Harvest from garden\" or \"Hand-roll in back room\".",
                  wraplength=320, justify="left", foreground=INK_DIM).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._toggle_custom()

        btns = ttk.Frame(form)
        btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left")
        center(self, app)

    def _toggle_custom(self):
        state = "normal" if self.custom_var.get() else "disabled"
        for child in self.custom_frame.winfo_children():
            if isinstance(child, (ttk.Entry,)):
                child.configure(state=state)

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Name is required.", parent=self)
            return
        unit = self.unit_var.get().strip() or "ea"
        ing_data = {"name": name, "unit": unit}
        if self.custom_var.get():
            try:
                cost = float(self.custom_cost_var.get() or 0)
            except ValueError:
                messagebox.showerror("Invalid number", "Cost/unit must be a number.", parent=self)
                return
            ing_data["costMode"] = "custom"
            ing_data["customCost"] = cost
            ing_data["customLabel"] = self.custom_label_var.get().strip() or "Acquire manually"
        data = self.app.data
        if self.ing_id:
            data["ingredients"][self.ing_id] = ing_data
        else:
            new_id = eng.unique_id(eng.slugify(name), set(data["ingredients"]))
            data["ingredients"][new_id] = ing_data
            data["inventory"][new_id] = {"qty": 0, "preferredVendorId": None}
        eng.save_data(data)
        self.app.refresh_all()
        self.destroy()


class ConversionDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Add Conversion")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(background=BG)

        ids_sorted = sorted(app.data["ingredients"], key=lambda i: app.data["ingredients"][i]["name"])
        self.name_to_id = {app.data["ingredients"][i]["name"]: i for i in ids_sorted}
        names_sorted = [app.data["ingredients"][i]["name"] for i in ids_sorted]

        form = ttk.Frame(self, padding=12)
        form.pack()
        ttk.Label(form, text="Input ingredient").grid(row=0, column=0, sticky="w")
        self.in_var = tk.StringVar(value=names_sorted[0] if names_sorted else "")
        ttk.Combobox(form, textvariable=self.in_var, values=names_sorted, state="readonly", width=22).grid(row=0, column=1, pady=2)
        ttk.Label(form, text="Input qty").grid(row=0, column=2, sticky="w")
        self.in_qty_var = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.in_qty_var, width=8).grid(row=0, column=3, pady=2)

        ttk.Label(form, text="Output ingredient").grid(row=1, column=0, sticky="w")
        self.out_var = tk.StringVar(value=names_sorted[0] if names_sorted else "")
        ttk.Combobox(form, textvariable=self.out_var, values=names_sorted, state="readonly", width=22).grid(row=1, column=1, pady=2)
        ttk.Label(form, text="Output qty").grid(row=1, column=2, sticky="w")
        self.out_qty_var = tk.StringVar(value="1")
        ttk.Entry(form, textvariable=self.out_qty_var, width=8).grid(row=1, column=3, pady=2)

        ttk.Label(form, text="Processing cost (total, optional)").grid(row=2, column=0, columnspan=2, sticky="w")
        self.cost_var = tk.StringVar(value="0")
        ttk.Entry(form, textvariable=self.cost_var, width=8).grid(row=2, column=2, pady=2)

        btns = ttk.Frame(form)
        btns.grid(row=3, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left")
        center(self, app)

    def _save(self):
        in_id = self.name_to_id.get(self.in_var.get())
        out_id = self.name_to_id.get(self.out_var.get())
        if not in_id or not out_id or in_id == out_id:
            messagebox.showerror("Invalid", "Pick two different ingredients.", parent=self)
            return
        try:
            in_qty = float(self.in_qty_var.get())
            out_qty = float(self.out_qty_var.get())
            cost = float(self.cost_var.get() or 0)
        except ValueError:
            messagebox.showerror("Invalid number", "Quantities and cost must be numbers.", parent=self)
            return
        if in_qty <= 0 or out_qty <= 0:
            messagebox.showerror("Invalid", "Quantities must be greater than zero.", parent=self)
            return
        data = self.app.data
        new_id = eng.unique_id("conv-" + eng.slugify(f"{in_id}-{out_id}"), {c["id"] for c in data["conversions"]})
        data["conversions"].append({"id": new_id, "inputId": in_id, "inputQty": in_qty,
                                     "outputId": out_id, "outputQty": out_qty, "cost": cost})
        eng.save_data(data)
        self.app.refresh_all()
        self.destroy()


class VendorDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Add Vendor Price")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()
        self.configure(background=BG)

        ids_sorted = sorted(app.data["ingredients"], key=lambda i: app.data["ingredients"][i]["name"])
        self.name_to_id = {app.data["ingredients"][i]["name"]: i for i in ids_sorted}
        names_sorted = [app.data["ingredients"][i]["name"] for i in ids_sorted]

        form = ttk.Frame(self, padding=12)
        form.pack()
        ttk.Label(form, text="Ingredient").grid(row=0, column=0, sticky="w")
        self.ing_var = tk.StringVar(value=names_sorted[0] if names_sorted else "")
        ttk.Combobox(form, textvariable=self.ing_var, values=names_sorted, state="readonly", width=24).grid(row=0, column=1, columnspan=2, pady=2, sticky="w")

        ttk.Label(form, text="Vendor name").grid(row=1, column=0, sticky="w")
        self.vendor_var = tk.StringVar(value=app.data["settings"].get("lastVendorName", ""))
        ttk.Entry(form, textvariable=self.vendor_var, width=26).grid(row=1, column=1, columnspan=2, pady=2, sticky="w")

        ttk.Label(form, text="Town").grid(row=2, column=0, sticky="w")
        self.town_var = tk.StringVar(value=app.data["settings"].get("lastVendorTown", ""))
        ttk.Entry(form, textvariable=self.town_var, width=26).grid(row=2, column=1, columnspan=2, pady=2, sticky="w")

        ttk.Label(form, text="Price (blank = TBD)").grid(row=3, column=0, sticky="w")
        self.price_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.price_var, width=10).grid(row=3, column=1, pady=2, sticky="w")

        ttk.Label(form, text="Stock").grid(row=4, column=0, sticky="w")
        self.stock_var = tk.StringVar(value="unknown")
        ttk.Combobox(form, textvariable=self.stock_var, values=["unknown", "available", "out"], state="readonly", width=12).grid(row=4, column=1, pady=2, sticky="w")

        btns = ttk.Frame(form)
        btns.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Save", command=self._save).pack(side="left")
        center(self, app)

    def _save(self):
        vendor_name = self.vendor_var.get().strip()
        if not vendor_name:
            messagebox.showerror("Missing name", "Vendor name is required.", parent=self)
            return
        price_raw = self.price_var.get().strip()
        try:
            price = None if not price_raw else max(0.0, float(price_raw))
        except ValueError:
            messagebox.showerror("Invalid price", "Price must be a number, or blank for TBD.", parent=self)
            return
        data = self.app.data
        new_id = eng.unique_id("v-" + eng.slugify(vendor_name), {v["id"] for v in data["vendors"]})
        data["vendors"].append({"id": new_id, "ingredientId": self.name_to_id[self.ing_var.get()],
                                 "vendorName": vendor_name, "town": self.town_var.get().strip(),
                                 "price": price, "stock": self.stock_var.get()})
        data["settings"]["lastVendorName"] = vendor_name
        data["settings"]["lastVendorTown"] = self.town_var.get().strip()
        eng.save_data(data)
        self.app.refresh_all()
        self.destroy()


def inline_edit_entry(tree, row_id, col, initial, on_commit, validate=None):
    """Float an Entry directly over a treeview cell. Enter (or clicking away)
    commits and closes; Escape cancels and closes. No popup window, nothing to
    reposition — it just edits in place."""
    bbox = tree.bbox(row_id, col)
    if not bbox:
        return
    x, y, w, h = bbox
    var = tk.StringVar(value=initial)
    entry = ttk.Entry(tree, textvariable=var)
    entry.place(x=x, y=y, width=w, height=h)
    entry.focus_set()
    entry.select_range(0, "end")
    state = {"done": False}

    def commit(event=None):
        if state["done"]:
            return
        raw = var.get()
        if validate and not validate(raw):
            return
        state["done"] = True
        entry.destroy()
        on_commit(raw)

    def cancel(event=None):
        if state["done"]:
            return
        state["done"] = True
        entry.destroy()

    entry.bind("<Return>", commit)
    entry.bind("<KP_Enter>", commit)
    entry.bind("<Escape>", cancel)
    entry.bind("<FocusOut>", commit)


def inline_edit_combobox(tree, row_id, col, options, initial, on_commit):
    """Same idea as inline_edit_entry, but a dropdown floated over the cell."""
    bbox = tree.bbox(row_id, col)
    if not bbox:
        return
    x, y, w, h = bbox
    var = tk.StringVar(value=initial)
    combo = ttk.Combobox(tree, textvariable=var, values=options, state="readonly")
    combo.place(x=x, y=y, width=w, height=h)
    combo.focus_set()
    state = {"done": False}

    def commit(event=None):
        if state["done"]:
            return
        state["done"] = True
        combo.destroy()
        on_commit(var.get())

    def cancel(event=None):
        if state["done"]:
            return
        state["done"] = True
        combo.destroy()

    combo.bind("<<ComboboxSelected>>", commit)
    combo.bind("<Return>", commit)
    combo.bind("<Escape>", cancel)
    combo.bind("<FocusOut>", commit)



class CounterOrderDialog(tk.Toplevel):
    """The register: ring items up, watch the running total, copy the receipt.
    Not modal, so the ledger stays usable underneath. The order itself lives on
    the app (app.counter_order), so closing this window -- or switching theme,
    which rebuilds every window -- never loses it."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Counter Order")
        self.transient(app)
        self.configure(background=BG)
        self.item_var = tk.StringVar()
        self.qty_var = tk.StringVar(value="1")
        self.label_to_id = {}

        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)
        form.columnconfigure(0, weight=1)

        pick = ttk.Frame(form)
        pick.grid(row=0, column=0, sticky="ew")
        pick.columnconfigure(0, weight=1)
        self.item_combo = ttk.Combobox(pick, textvariable=self.item_var, state="readonly", width=34)
        self.item_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(pick, text="Qty").grid(row=0, column=1, padx=(0, 4))
        qty_entry = ttk.Entry(pick, textvariable=self.qty_var, width=5)
        qty_entry.grid(row=0, column=2, padx=(0, 6))
        qty_entry.bind("<Return>", lambda e: self._add())
        ttk.Button(pick, text="Add item to order", command=self._add).grid(row=0, column=3)

        frame, self.tree = make_tree(form, ["Item", "Qty", "Price", "Total"], {"Item": 220, "Qty": 60, "Price": 80, "Total": 90},
                                     height=9, sortable=False)
        frame.grid(row=1, column=0, sticky="nsew", pady=(10, 6))
        form.rowconfigure(1, weight=1)
        self.tree.bind("<Double-1>", self._edit_qty)
        self.tree.bind("<Delete>", lambda e: self._remove_selected())
        ttk.Label(form, text="Double-click a Qty to change it. Select a line and press Delete to remove it.",
                  foreground=INK_DIM).grid(row=2, column=0, sticky="w")

        self.total_var = tk.StringVar()
        ttk.Label(form, textvariable=self.total_var, font=(RESOLVED["display"], 18), foreground=ACCENT).grid(row=3, column=0, sticky="e", pady=(8, 4))

        btns = ttk.Frame(form)
        btns.grid(row=4, column=0, sticky="e")
        ttk.Button(btns, text="Remove Selected", command=self._remove_selected).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Reset", command=self._reset).pack(side="left", padx=(0, 6))
        self.copy_btn = ttk.Button(btns, text="Copy Receipt", command=self._copy)
        self.copy_btn.pack(side="left")

        self.refresh()
        self.update_idletasks()
        self.minsize(self.winfo_reqwidth(), self.winfo_reqheight())
        center(self, app)
        qty_entry.focus_set()

    @property
    def order(self):
        return self.app.counter_order

    def refresh(self):
        """Re-reads recipes and prices (the ledger may have changed underneath)
        and redraws the receipt."""
        data = self.app.data
        recipes = sorted(((rid, r) for rid, r in data["recipes"].items() if r.get("active")), key=lambda kv: kv[1]["name"])
        if not recipes:
            recipes = sorted(data["recipes"].items(), key=lambda kv: kv[1]["name"])
        self.label_to_id = {f"{r['name']}  —  {eng.fmt_money(r.get('salePrice') or 0)}": rid for rid, r in recipes}
        labels = list(self.label_to_id)
        self.item_combo.configure(values=labels)
        if self.item_var.get() not in self.label_to_id:
            self.item_var.set(labels[0] if labels else "")
        self.order[:] = [l for l in self.order if l["recipeId"] in data["recipes"]]
        self.tree.delete(*self.tree.get_children())
        for line in self.order:
            r = data["recipes"][line["recipeId"]]
            price = r.get("salePrice") or 0
            self.tree.insert("", "end", iid=line["recipeId"], values=(
                r["name"], f"{line['qty']:g}", eng.fmt_money(price), eng.fmt_money(price * line["qty"])))
        stripe_tree(self.tree)
        self.total_var.set(f"Total: {eng.fmt_money(eng.receipt_total(data, self.order))}")

    @staticmethod
    def _whole_number(raw):
        try:
            qty = int(float(str(raw).strip()))
        except ValueError:
            return None
        return qty if qty > 0 else None

    def _add(self):
        rid = self.label_to_id.get(self.item_var.get())
        if not rid:
            messagebox.showerror("No item", "Pick an item first.", parent=self)
            return
        qty = self._whole_number(self.qty_var.get())
        if qty is None:
            messagebox.showerror("Invalid quantity", "Quantity must be a whole number, 1 or more.", parent=self)
            return
        eng.add_to_receipt(self.order, rid, qty)
        self.qty_var.set("1")
        self.refresh()

    def _edit_qty(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id or self.tree.identify_column(event.x) != "#2":
            return

        def commit(raw, rid=row_id):
            qty = self._whole_number(raw)
            if qty is None:
                messagebox.showerror("Invalid quantity", "Quantity must be a whole number, 1 or more.", parent=self)
                return
            for line in self.order:
                if line["recipeId"] == rid:
                    line["qty"] = qty
            self.refresh()
        inline_edit_entry(self.tree, row_id, "#2", self.tree.set(row_id, "Qty"), commit)

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a line to remove first.", parent=self)
            return
        self.order[:] = [l for l in self.order if l["recipeId"] != sel[0]]
        self.refresh()

    def _reset(self):
        if self.order and not messagebox.askyesno("Reset order", "Clear everything on this order?", parent=self):
            return
        self.order.clear()
        self.refresh()

    def _copy(self):
        if not eng.receipt_rows(self.app.data, self.order):
            messagebox.showinfo("Nothing to copy", "The order is empty.", parent=self)
            return
        self.clipboard_clear()
        self.clipboard_append(eng.receipt_text(self.app.data, self.order, self.app.receipt_title()))
        self.update()
        self.copy_btn.configure(text="Copied!")
        self.after(1500, lambda: self.copy_btn.winfo_exists() and self.copy_btn.configure(text="Copy Receipt"))


class SettingsFrame(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        s = app.data["settings"]

        pricing = ttk.LabelFrame(self, text="Pricing Rules", padding=10)
        pricing.pack(fill="x", pady=(0, 10))
        ttk.Label(pricing, text="Maximum sale price").grid(row=0, column=0, sticky="w")
        self.cap_var = tk.StringVar(value=str(s["priceCap"]))
        ttk.Entry(pricing, textvariable=self.cap_var, width=10).grid(row=0, column=1, padx=6)
        ttk.Label(pricing, text="Recipe grade by profit margin:", font=(RESOLVED["body"], 10, "bold")).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(pricing, text="Healthy at or above margin %").grid(row=2, column=0, sticky="w")
        self.healthy_var = tk.StringVar(value=str(s.get("marginHealthyPercent", 80)))
        ttk.Entry(pricing, textvariable=self.healthy_var, width=10).grid(row=2, column=1, padx=6)
        ttk.Label(pricing, text="Good at or above margin %").grid(row=3, column=0, sticky="w")
        self.good_var = tk.StringVar(value=str(s.get("marginGoodPercent", 65)))
        ttk.Entry(pricing, textvariable=self.good_var, width=10).grid(row=3, column=1, padx=6)
        ttk.Label(pricing, text="Problematic at or below margin %").grid(row=4, column=0, sticky="w")
        self.tight_var = tk.StringVar(value=str(s.get("marginProblematicMaxPercent", 20)))
        ttk.Entry(pricing, textvariable=self.tight_var, width=10).grid(row=4, column=1, padx=6)
        self.tier_hint_var = tk.StringVar()
        ttk.Label(pricing, textvariable=self.tier_hint_var, foreground=INK_DIM, wraplength=420, justify="left").grid(row=5, column=0, columnspan=2, sticky="w")
        for var in (self.healthy_var, self.good_var, self.tight_var):
            var.trace_add("write", lambda *a: self._update_tier_hint())
        self._update_tier_hint()
        ttk.Label(pricing, text="Tax rate % (reduces revenue used for profit calc)").grid(row=6, column=0, sticky="w", pady=(8, 0))
        self.tax_var = tk.StringVar(value=str(s.get("taxRatePercent", 0)))
        ttk.Entry(pricing, textvariable=self.tax_var, width=10).grid(row=6, column=1, padx=6, pady=(8, 0))
        ttk.Label(pricing, text="Placeholder until you know your actual rate — 0% changes nothing.", foreground=INK_DIM).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Button(pricing, text="Save pricing rules", command=self._save_pricing).grid(row=8, column=0, pady=(8, 0), sticky="w")

        labor = ttk.LabelFrame(self, text="Labor & Overhead", padding=10)
        labor.pack(fill="x", pady=(0, 10))
        ttk.Label(labor, text="Added to every craft's cost — covers processing time and staffing overhead.", wraplength=420, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(labor, text="Process time (minutes/craft)").grid(row=1, column=0, sticky="w")
        self.process_time_var = tk.StringVar(value=str(s.get("processTimeMinutes", 3.0)))
        ttk.Entry(labor, textvariable=self.process_time_var, width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(labor, text="Labor rate ($ per 30 min)").grid(row=2, column=0, sticky="w")
        self.labor_rate_var = tk.StringVar(value=str(s.get("laborRatePer30Min", 1.50)))
        ttk.Entry(labor, textvariable=self.labor_rate_var, width=10).grid(row=2, column=1, sticky="w")
        self.labor_preview_var = tk.StringVar(value="")
        ttk.Label(labor, textvariable=self.labor_preview_var, font=(RESOLVED["body"], 10, "bold"), foreground=GOOD).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(labor, text="Save labor settings", command=self._save_labor).grid(row=4, column=0, pady=(8, 0), sticky="w")
        self.process_time_var.trace_add("write", lambda *a: self._update_labor_preview())
        self.labor_rate_var.trace_add("write", lambda *a: self._update_labor_preview())
        self._update_labor_preview()

        business = ttk.LabelFrame(self, text="Business Info", padding=10)
        business.pack(fill="x", pady=(0, 10))
        ttk.Label(business, text="Shows in the window title and header. Any ingredient can also get its own custom cost/acquisition note — see Ingredients.", wraplength=420, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(business, text="Business name").grid(row=1, column=0, sticky="w")
        self.business_name_var = tk.StringVar(value=s.get("businessName", "My Business"))
        ttk.Entry(business, textvariable=self.business_name_var, width=30).grid(row=1, column=1, sticky="w")
        ttk.Label(business, text="Tagline").grid(row=2, column=0, sticky="w")
        self.tagline_var = tk.StringVar(value=s.get("tagline", ""))
        ttk.Entry(business, textvariable=self.tagline_var, width=30).grid(row=2, column=1, sticky="w")
        ttk.Label(business, text="Icon (one emoji)").grid(row=3, column=0, sticky="w")
        self.app_icon_var = tk.StringVar(value=s.get("appIcon", "\U0001F4D2"))
        ttk.Entry(business, textvariable=self.app_icon_var, width=6).grid(row=3, column=1, sticky="w")
        ttk.Button(business, text="Save business info", command=self._save_business).grid(row=4, column=0, pady=(8, 0), sticky="w")

    def _update_tier_hint(self):
        try:
            h, g, p = (float(v.get()) for v in (self.healthy_var, self.good_var, self.tight_var))
            self.tier_hint_var.set(
                f"Problematic: {p:g}% and under  ·  Tight: over {p:g}% up to {g:g}%  ·  "
                f"Good: {g:g}% up to {h:g}%  ·  Healthy: {h:g}% and up")
        except ValueError:
            self.tier_hint_var.set("Enter numbers to preview the four grades")

    def _save_pricing(self):
        try:
            cap = float(self.cap_var.get())
            healthy = float(self.healthy_var.get())
            good = float(self.good_var.get())
            problematic = float(self.tight_var.get())
            tax = float(self.tax_var.get())
        except ValueError:
            messagebox.showerror("Invalid number", "Pricing fields must be numbers.")
            return
        if not (problematic < good <= healthy):
            messagebox.showerror("Check the grades", "The cutoffs need to run from low to high:\nProblematic < Good <= Healthy.")
            return
        s = self.app.data["settings"]
        s["priceCap"], s["taxRatePercent"] = cap, tax
        s["marginHealthyPercent"], s["marginGoodPercent"], s["marginProblematicMaxPercent"] = healthy, good, problematic
        eng.save_data(self.app.data)
        self.app.refresh_all()
        messagebox.showinfo("Saved", "Pricing rules saved.")

    def _update_labor_preview(self):
        try:
            minutes = float(self.process_time_var.get() or 0)
            rate = float(self.labor_rate_var.get() or 0)
            cost = minutes * (rate / 30.0)
            self.labor_preview_var.set(f"= {eng.fmt_money(cost)} labor added to every craft")
        except ValueError:
            self.labor_preview_var.set("Enter numbers to preview the labor cost per craft")

    def _save_labor(self):
        try:
            minutes = float(self.process_time_var.get())
            rate = float(self.labor_rate_var.get())
        except ValueError:
            messagebox.showerror("Invalid number", "Process time and labor rate must be numbers.")
            return
        s = self.app.data["settings"]
        s["processTimeMinutes"], s["laborRatePer30Min"] = minutes, rate
        eng.save_data(self.app.data)
        self.app.refresh_all()
        messagebox.showinfo("Saved", "Labor settings saved.")

    def _save_business(self):
        name = self.business_name_var.get().strip() or "My Business"
        icon = self.app_icon_var.get().strip() or "\U0001F4D2"
        s = self.app.data["settings"]
        s["businessName"], s["tagline"], s["appIcon"] = name, self.tagline_var.get().strip(), icon
        eng.save_data(self.app.data)
        self.app.apply_branding()
        self.app.refresh_all()
        messagebox.showinfo("Saved", "Business info saved.")


_ERRORS_SHOWN = {"n": 0}


def report_error(text, parent=None, title="Something went wrong", hint=""):
    """pythonw has no console, so without this an error just looks like a blank or
    frozen window. Show it, and also write it to stderr (run_desktop.bat saves
    that to error_log.txt)."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()
    except Exception:
        pass
    if _ERRORS_SHOWN["n"] >= 3:      # don't bury the user if something keeps failing
        return
    _ERRORS_SHOWN["n"] += 1
    body = hint or "The ledger hit an error. A copy is saved in error_log.txt next to the program."
    try:
        messagebox.showerror(title, body + "\n\n" + text[-1200:], parent=parent)
    except Exception:
        pass


class LedgerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        win_w = min(1180, max(800, self.winfo_screenwidth() - 60))
        win_h = min(720, max(520, self.winfo_screenheight() - 120))
        self.geometry(f"{win_w}x{win_h}")
        self.minsize(min(900, win_w), min(600, win_h))
        self.data = eng.load_data()
        self.counter_order = []          # the current receipt; not saved, lives until Reset
        self.counter_dialog = None

        load_local_fonts()
        display, body = resolve_fonts(self)
        RESOLVED["display"], RESOLVED["body"] = display, body
        self.configure(background=BG)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=INK, font=(body, 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=(body, 10))
        style.configure("TButton", background=SURFACE2, foreground=INK, font=(body, 10), padding=5, bordercolor=LINE)
        style.map("TButton", background=[("active", ACCENT2), ("pressed", ACCENT)], foreground=[("active", SURFACE), ("pressed", SURFACE)])
        style.configure("TCheckbutton", background=BG, foreground=INK, font=(body, 10))
        style.configure("TRadiobutton", background=BG, foreground=INK, font=(body, 10))
        style.configure("TEntry", fieldbackground=SURFACE, foreground=INK, bordercolor=LINE)
        style.configure("TCombobox", fieldbackground=SURFACE, foreground=INK, background=SURFACE2)
        style.configure("TLabelframe", background=BG, bordercolor=LINE)
        style.configure("TLabelframe.Label", background=BG, foreground=ACCENT, font=(display, 12))
        style.configure("TNotebook", background=BG, bordercolor=LINE)
        style.configure("TNotebook.Tab", background=SURFACE2, foreground=INK_DIM, font=(body, 10, "bold"), padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", SURFACE)])
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=INK, font=(body, 10), rowheight=24, bordercolor=LINE)
        style.configure("Treeview.Heading", background=SURFACE2, foreground=INK_DIM, font=(body, 9, "bold"))
        style.map("Treeview", background=[("selected", ACCENT2)], foreground=[("selected", SURFACE)])
        global ROW_EVEN_BG, ROW_ODD_BG
        ROW_EVEN_BG, ROW_ODD_BG = SURFACE, SURFACE2

        header = ttk.Frame(self, padding=(12, 10, 12, 4))
        header.pack(fill="x")
        # The button is packed first so a narrow window or high display scaling
        # clips the subtitle instead of pushing the button off the edge.
        ttk.Button(header, text="Counter Order", command=self._open_counter_order).pack(side="right")
        self.title_label = ttk.Label(header, font=(display, 20), foreground=ACCENT)
        self.title_label.pack(side="left")
        self.subtitle_label = ttk.Label(header, foreground=INK_DIM)
        self.subtitle_label.pack(side="left")
        self.apply_branding()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_dash = ttk.Frame(self.notebook)
        self.tab_recipes = ttk.Frame(self.notebook)
        self.tab_ing = ttk.Frame(self.notebook)
        self.tab_vendors = ttk.Frame(self.notebook)
        self.tab_inv = ttk.Frame(self.notebook)
        self.tab_crafted = ttk.Frame(self.notebook)
        self.tab_planner = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        for frame, label in [
            (self.tab_dash, "Dashboard"), (self.tab_recipes, "Recipes"), (self.tab_ing, "Ingredients"),
            (self.tab_vendors, "Vendors"), (self.tab_inv, "Raw Inventory"), (self.tab_crafted, "Crafted Inventory"),
            (self.tab_planner, "Planner"),
            (self.tab_settings, "Settings"),
        ]:
            self.notebook.add(frame, text=label)

        self._build_dashboard()
        self._build_recipes()
        self._build_ingredients()
        self._build_vendors()
        self._build_inventory()
        self._build_crafted()
        self._build_planner()
        self.settings_scroll = ScrollFrame(self.tab_settings)
        self.settings_scroll.pack(fill="both", expand=True)
        self.settings_frame = SettingsFrame(self.settings_scroll.body, self)
        self.settings_frame.pack(fill="both", expand=True)

        self.refresh_all()

    # ---------- Dashboard ----------
    def _build_dashboard(self):
        top = ttk.Frame(self.tab_dash, padding=10)
        top.pack(fill="x")
        self.metric_vars = {k: tk.StringVar(value="—") for k in ["active", "short", "overcap", "problematic"]}
        labels = [("active", "Active Recipes"), ("short", "Ingredients Short"), ("overcap", "Over Max Price"), ("problematic", "Problematic Tier")]
        for i, (key, label) in enumerate(labels):
            box = ttk.LabelFrame(top, text=label, padding=10)
            box.grid(row=0, column=i, padx=6, sticky="ew")
            top.columnconfigure(i, weight=1)
            ttk.Label(box, textvariable=self.metric_vars[key], font=(RESOLVED["body"], 18, "bold"), foreground=INK).pack()

        mid = ttk.Frame(self.tab_dash, padding=10)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(1, weight=1)

        ttk.Label(mid, text="Acquire Next", font=(RESOLVED["display"], 14), foreground=ACCENT).grid(row=0, column=0, sticky="w")
        grow_frame, self.grow_tree = make_tree(mid, ["Ingredient", "Shortage", "Recipes Using", "Score"],
                                                {"Ingredient": 150}, height=8)
        grow_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))

        ttk.Label(mid, text="Pricing Watch", font=(RESOLVED["display"], 14), foreground=ACCENT).grid(row=0, column=1, sticky="w")
        watch_frame, self.watch_tree = make_tree(mid, ["Recipe", "Cost/Item", "Sale Price", "Flag"],
                                                  {"Recipe": 170}, height=8)
        watch_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        configure_tier_tags(self.watch_tree)

    # ---------- Recipes ----------
    def _build_recipes(self):
        top = ttk.Frame(self.tab_recipes, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        hint = ttk.Label(top, text="Double-click a recipe row to toggle Active on/off.", foreground=INK_DIM)
        hint.pack(side="left")
        ttk.Button(top, text="Add Recipe", command=lambda: RecipeDialog(self)).pack(side="right", padx=4)
        ttk.Button(top, text="Edit Selected", command=self._edit_selected_recipe).pack(side="right", padx=4)
        ttk.Button(top, text="Delete Selected", command=self._delete_selected_recipe).pack(side="right", padx=4)
        autowrap_toolbar(top, hint)

        cols = ["Name", "Category", "Yield", "Labor/Item", "Craft Cost", "Cost/Item", "Sale Price", "Profit", "Margin", "Tier", "Active"]
        widths = {"Name": 200, "Category": 90, "Yield": 56, "Labor/Item": 92, "Craft Cost": 88, "Cost/Item": 88,
                  "Sale Price": 112, "Profit": 76, "Margin": 72, "Tier": 96, "Active": 64}
        frame, self.recipes_tree = make_tree(self.tab_recipes, cols, widths, height=16)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        configure_tier_tags(self.recipes_tree)
        self.recipes_tree.bind("<Double-1>", self._toggle_recipe_active)

    def _selected_recipe_id(self):
        sel = self.recipes_tree.selection()
        return sel[0] if sel else None

    def _toggle_recipe_active(self, event):
        row_id = self.recipes_tree.identify_row(event.y)
        if not row_id:
            return
        r = self.data["recipes"].get(row_id)
        if not r:
            return
        r["active"] = not r["active"]
        eng.save_data(self.data)
        self.refresh_all()

    def _edit_selected_recipe(self):
        rid = self._selected_recipe_id()
        if not rid:
            messagebox.showinfo("No selection", "Select a recipe first.")
            return
        RecipeDialog(self, rid)

    def _delete_selected_recipe(self):
        rid = self._selected_recipe_id()
        if not rid:
            messagebox.showinfo("No selection", "Select a recipe first.")
            return
        name = self.data["recipes"][rid]["name"]
        if messagebox.askyesno("Delete recipe", f'Delete "{name}"?'):
            del self.data["recipes"][rid]
            self.data.get("crafted", {}).pop(rid, None)
            eng.save_data(self.data)
            self.refresh_all()

    # ---------- Ingredients ----------
    def _build_ingredients(self):
        top = ttk.Frame(self.tab_ing, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Button(top, text="Add Ingredient", command=lambda: IngredientDialog(self)).pack(side="right", padx=4)
        ttk.Button(top, text="Edit Selected", command=self._edit_selected_ingredient).pack(side="right", padx=4)
        ttk.Button(top, text="Delete Selected", command=self._delete_selected_ingredient).pack(side="right", padx=4)

        frame, self.ing_tree = make_tree(self.tab_ing, ["Name", "Unit", "Cost", "Source"], {"Name": 170}, height=4)
        frame.pack(fill="both", expand=True, padx=10, pady=(6, 6))

        conv_top = ttk.Frame(self.tab_ing, padding=(10, 4, 10, 0))
        conv_top.pack(fill="x")
        ttk.Label(conv_top, text="Conversions (e.g. Sugarcane → Sugar)", font=(RESOLVED["display"], 13), foreground=ACCENT).pack(side="left")
        ttk.Button(conv_top, text="Add Conversion", command=lambda: ConversionDialog(self)).pack(side="right", padx=4)
        ttk.Button(conv_top, text="Delete Selected", command=self._delete_selected_conversion).pack(side="right", padx=4)

        conv_frame, self.conv_tree = make_tree(self.tab_ing, ["Conversion", "Processing Cost"], {"Conversion": 260}, height=4)
        conv_frame.pack(fill="x", padx=10, pady=(6, 10))

    def _edit_selected_ingredient(self):
        sel = self.ing_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select an ingredient first.")
            return
        IngredientDialog(self, sel[0])

    def _delete_selected_ingredient(self):
        sel = self.ing_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select an ingredient first.")
            return
        ing_id = sel[0]
        blockers = eng.used_in_recipes(self.data, ing_id) + eng.used_in_conversions(self.data, ing_id)
        if blockers:
            messagebox.showerror("Can't delete", f"\"{eng.ing_name(self.data, ing_id)}\" is still used in {len(blockers)} recipe(s)/conversion(s). Remove those first.")
            return
        if messagebox.askyesno("Delete ingredient", "Delete this ingredient and its vendor prices?"):
            self.data["vendors"] = [v for v in self.data["vendors"] if v["ingredientId"] != ing_id]
            self.data["inventory"].pop(ing_id, None)
            del self.data["ingredients"][ing_id]
            eng.save_data(self.data)
            self.refresh_all()

    def _delete_selected_conversion(self):
        sel = self.conv_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a conversion first.")
            return
        if messagebox.askyesno("Delete conversion", "Delete this conversion?"):
            self.data["conversions"] = [c for c in self.data["conversions"] if c["id"] != sel[0]]
            eng.save_data(self.data)
            self.refresh_all()

    # ---------- Vendors ----------
    def _build_vendors(self):
        top = ttk.Frame(self.tab_vendors, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        hint = ttk.Label(top, text="Double-click any cell to edit in place (Ingredient renames it everywhere) — Enter saves, Esc cancels. ★ = cheapest.", foreground=INK_DIM)
        hint.pack(side="left")
        ttk.Button(top, text="Add Vendor Price", command=lambda: VendorDialog(self)).pack(side="right", padx=4)
        ttk.Button(top, text="Delete Selected", command=self._delete_selected_vendor).pack(side="right", padx=4)
        autowrap_toolbar(top, hint)

        frame, self.vendor_tree = make_tree(
            self.tab_vendors, ["Ingredient", "Vendor", "Town", "Price", "Stock", "Note"],
            {"Ingredient": 140, "Vendor": 150, "Note": 220}, height=18,
        )
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.vendor_tree.bind("<Double-1>", self._vendor_cell_click)

    def _vendor_cell_click(self, event):
        tree = self.vendor_tree
        row_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        v = next((x for x in self.data["vendors"] if x["id"] == row_id), None)
        if not v:
            return
        field = {"#1": "ingredient", "#2": "vendorName", "#3": "town", "#4": "price", "#5": "stock", "#6": "note"}.get(col)
        if not field:
            return

        def save():
            eng.save_data(self.data)
            self.refresh_all()

        if field == "ingredient":
            ing_id = v["ingredientId"]

            def commit_rename(raw):
                self._rename_ingredient(ing_id, raw)
            inline_edit_entry(tree, row_id, col, self.data["ingredients"][ing_id]["name"], commit_rename)
        elif field == "stock":
            options = ["unknown", "available", "out"]

            def commit_stock(chosen):
                v["stock"] = chosen if chosen in options else "unknown"
                save()
            inline_edit_combobox(tree, row_id, col, options, v.get("stock", "unknown"), commit_stock)
        elif field == "price":
            initial = "" if v.get("price") is None else f"{v['price']:g}"

            def commit_price(raw):
                text = raw.replace("$", "").strip()
                if text == "" or text.lower() == "tbd":
                    v["price"] = None
                else:
                    try:
                        v["price"] = max(0.0, float(text))
                    except ValueError:
                        messagebox.showerror("Invalid price", "Price must be a number, or blank for TBD.")
                        return
                save()
            inline_edit_entry(tree, row_id, col, initial, commit_price)
        else:
            initial = v.get(field, "") or ""

            def commit_text(raw):
                text = raw.strip()
                if field == "vendorName" and not text:
                    return
                v[field] = text
                save()
            inline_edit_entry(tree, row_id, col, initial, commit_text)

    def _rename_ingredient(self, ing_id, raw):
        """Fixes a misspelled ingredient name. Recipes, conversions, vendors and
        inventory all point at the ingredient by id, so only the name changes."""
        name = raw.strip()
        ing = self.data["ingredients"][ing_id]
        if not name or name == ing["name"]:
            return
        clash = next((o["name"] for i, o in self.data["ingredients"].items()
                      if i != ing_id and o["name"].lower() == name.lower()), None)
        if clash:
            messagebox.showerror("Name already used", f"There's already an ingredient called \"{clash}\".")
            return
        ing["name"] = name
        eng.save_data(self.data)
        self.refresh_all()

    def _delete_selected_vendor(self):
        sel = self.vendor_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a vendor row first.")
            return
        vendor_id = sel[0]
        if messagebox.askyesno("Delete vendor price", "Delete this vendor price?"):
            v = next((x for x in self.data["vendors"] if x["id"] == vendor_id), None)
            self.data["vendors"] = [x for x in self.data["vendors"] if x["id"] != vendor_id]
            if v:
                inv = self.data["inventory"].get(v["ingredientId"])
                if inv and inv.get("preferredVendorId") == vendor_id:
                    inv["preferredVendorId"] = None
            eng.save_data(self.data)
            self.refresh_all()

    # ---------- Inventory ----------
    def _build_inventory(self):
        top = ttk.Frame(self.tab_inv, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        hint = ttk.Label(top, text="Double-click On Hand, To Order or Preferred Source to edit right in the table — Enter saves, Esc cancels.", foreground=INK_DIM)
        hint.pack(side="left")
        self.inv_total_var = tk.StringVar(value="Total value: —")
        ttk.Label(top, textvariable=self.inv_total_var, font=(RESOLVED["body"], 10, "bold"), foreground=INK).pack(side="right", padx=(10, 0))
        self.inv_copy_btn = ttk.Button(top, text="Copy Order List", command=self._copy_inventory_order_list)
        self.inv_copy_btn.pack(side="right")
        ttk.Button(top, text="Mark Order Received", command=self._receive_order).pack(side="right", padx=(0, 6))
        self.inv_freeze_btn = ttk.Button(top, text="Mark Unavailable", command=self._toggle_unavailable)
        self.inv_freeze_btn.pack(side="right", padx=(0, 6))
        autowrap_toolbar(top, hint)

        frame, self.inv_tree = make_tree(
            self.tab_inv, ["Ingredient", "Unit", "On Hand", "To Order", "Preferred Source", "Unit Cost", "Value"],
            {"Ingredient": 170, "To Order": 100, "Preferred Source": 170}, height=18,
        )
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        configure_tier_tags(self.inv_tree)       # red rows = marked unavailable
        self.inv_tree.bind("<Double-1>", self._inventory_cell_click)
        self.inv_tree.bind("<<TreeviewSelect>>", lambda e: self._sync_freeze_button())

    def _copy_inventory_order_list(self):
        """Copies the To Order column as 'Item | Note' lines -- the typed note, or the
        quantity What To Order says to get. Rows marked unavailable are left out:
        they can't be acquired right now."""
        needs = eng.order_needs(self.data)
        lines = []
        for iid in sorted(self.data["ingredients"], key=lambda i: self.data["ingredients"][i]["name"]):
            e = eng.to_order_entry(self.data, iid, needs)
            if e["text"] and not e["frozen"]:
                lines.append(f"{eng.ing_name(self.data, iid)} | {e['text']}")
        if not lines:
            messagebox.showinfo("Nothing to copy", "Nothing to order right now.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.update()
        self.inv_copy_btn.configure(text="Copied!")
        self.after(1500, lambda: self.inv_copy_btn.configure(text="Copy Order List"))

    def _receive_order(self):
        """Adds every To Order quantity to On Hand and clears the typed notes --
        marking that the order came in. Rows marked unavailable (red) are left
        completely alone, so they stay on What To Order. A typed note supplies its
        first number (so '50 (ask Sam)' still works); notes with no number are skipped."""
        to_add, unparsed, frozen = eng.plan_receipt(self.data)
        if not to_add and not unparsed and not frozen:
            messagebox.showinfo("Nothing to receive", "Nothing to order right now.")
            return
        if not to_add:
            msg = "Nothing to add to On Hand."
            if unparsed:
                msg += "\n\nNo number found in:\n" + "\n".join(f"{name}: \"{note}\"" for name, note in unparsed)
            if frozen:
                msg += "\n\nMarked unavailable (left alone):\n" + "\n".join(f"{name}: {text}" for name, text in frozen)
            messagebox.showwarning("Nothing received", msg)
            return

        lines = [f"{name}: On Hand +{qty:g}" for _, name, qty, _ in to_add]
        msg = "Add these to On Hand?\n\n" + "\n".join(lines)
        if frozen:
            msg += "\n\nMarked unavailable (left alone):\n" + "\n".join(f"{name}: {text}" for name, text in frozen)
        if unparsed:
            msg += "\n\nSkipped (no number found, left as-is):\n" + "\n".join(f"{name}: \"{note}\"" for name, note in unparsed)
        if not messagebox.askyesno("Mark Order Received", msg):
            return
        eng.apply_receipt(self.data, to_add)
        eng.save_data(self.data)
        self.refresh_all()

    def _selected_inventory_id(self):
        sel = self.inv_tree.selection()
        return sel[0] if sel else None

    def _sync_freeze_button(self):
        iid = self._selected_inventory_id()
        frozen = bool(iid) and eng.is_unavailable(self.data, iid)
        self.inv_freeze_btn.configure(text="Mark Available" if frozen else "Mark Unavailable")

    def _toggle_unavailable(self):
        """Freezes the selected row (couldn't be acquired) or thaws it again."""
        iid = self._selected_inventory_id()
        if not iid:
            messagebox.showinfo("No selection", "Select an ingredient row first.")
            return
        eng.set_unavailable(self.data, iid, not eng.is_unavailable(self.data, iid))
        eng.save_data(self.data)
        self.refresh_all()

    def _inventory_cell_click(self, event):
        tree = self.inv_tree
        row_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not row_id:
            return
        if col == "#3":  # On Hand
            def commit(raw, ing_id=row_id):
                try:
                    qty = max(0.0, float(raw))
                except ValueError:
                    messagebox.showerror("Invalid number", "On hand must be a number.")
                    return
                inv = self.data["inventory"].setdefault(ing_id, {"qty": 0, "preferredVendorId": None})
                inv["qty"] = qty
                eng.save_data(self.data)
                self.refresh_all()
            inline_edit_entry(tree, row_id, col, tree.set(row_id, col), commit)
        elif col == "#4":  # To Order: a typed note, or what What To Order says to get
            shown = tree.set(row_id, col)

            def commit(raw, ing_id=row_id, shown=shown):
                text = raw.strip()
                inv = self.data["inventory"].setdefault(ing_id, {"qty": 0, "preferredVendorId": None, "toOrder": ""})
                if text == shown and not (inv.get("toOrder") or "").strip():
                    return      # untouched automatic quantity: don't turn it into a typed note
                inv["toOrder"] = text
                eng.save_data(self.data)
                self.refresh_all()
            inline_edit_entry(tree, row_id, col, shown, commit)
        elif col == "#5":  # Preferred Source
            vendors_here = [v for v in self.data["vendors"] if v["ingredientId"] == row_id]
            options = ["cheapest available"] + [
                v["vendorName"] + (f" ({eng.fmt_money(v['price'])})" if v.get("price") is not None else " (TBD)") for v in vendors_here
            ]
            ids = [None] + [v["id"] for v in vendors_here]

            def commit(chosen, ing_id=row_id):
                pid = ids[options.index(chosen)] if chosen in options else None
                inv = self.data["inventory"].setdefault(ing_id, {"qty": 0, "preferredVendorId": None})
                inv["preferredVendorId"] = pid
                eng.save_data(self.data)
                self.refresh_all()
            inline_edit_combobox(tree, row_id, col, options, tree.set(row_id, col), commit)

    # ---------- Crafted Inventory ----------
    def _build_crafted(self):
        top = ttk.Frame(self.tab_crafted, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        hint = ttk.Label(top, text="Finished items on hand. Double-click On Hand or Set Point to edit — Enter saves, Esc cancels. "
                                   "Set Point is how many you want to keep made up; the Planner uses it to work out what to make.",
                         foreground=INK_DIM)
        hint.pack(side="left")
        self.crafted_total_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.crafted_total_var, font=(RESOLVED["body"], 10, "bold"), foreground=INK).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="Restock Planner to Set Points", command=self._restock_to_set_points).pack(side="right")
        autowrap_toolbar(top, hint)

        frame, self.crafted_tree = make_tree(
            self.tab_crafted, ["Recipe", "Category", "On Hand", "Set Point", "Short", "Cost/Item", "Value"],
            {"Recipe": 220}, height=18,
        )
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        configure_tier_tags(self.crafted_tree)
        self.crafted_tree.bind("<Double-1>", self._crafted_cell_click)

    def _edit_crafted_field(self, rid, field, raw):
        try:
            value = max(0.0, float(raw))
        except ValueError:
            messagebox.showerror("Invalid number", "Enter a number.")
            return
        eng.crafted_entry(self.data, rid)[field] = value
        eng.save_data(self.data)
        self.refresh_all()

    def _crafted_cell_click(self, event):
        tree = self.crafted_tree
        row_id = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not row_id or col not in ("#3", "#4"):
            return
        field = "qty" if col == "#3" else "setPoint"
        inline_edit_entry(tree, row_id, col, tree.set(row_id, col),
                          lambda raw, rid=row_id, f=field: self._edit_crafted_field(rid, f, raw))

    def _refresh_crafted(self):
        tree = self.crafted_tree
        tree.delete(*tree.get_children())
        total = 0.0
        for rid, r in sorted(self.data["recipes"].items(), key=lambda kv: kv[1]["name"]):
            c = self.data.get("crafted", {}).get(rid) or {}
            have, point = c.get("qty") or 0, c.get("setPoint") or 0
            m = eng.recipe_metrics(self.data, r)
            value = have * m["costPerItem"]
            total += value
            short = eng.crafted_short(self.data, rid)
            tree.insert("", "end", iid=rid, values=(
                r["name"], r["category"], f"{have:g}", f"{point:g}", f"{short:g}" if short else "—",
                eng.fmt_money(m["costPerItem"]), eng.fmt_money(value),
            ))
        restore_sort(tree)
        for i, rid in enumerate(tree.get_children("")):
            c = self.data.get("crafted", {}).get(rid) or {}
            if eng.crafted_short(self.data, rid) > 0:
                tag = "tier_problematic" if (c.get("qty") or 0) <= 0 else "tier_tight"
            else:
                tag = "even" if i % 2 == 0 else "odd"
            tree.item(rid, tags=(tag,))
        self.crafted_total_var.set(f"Stock value at cost: {eng.fmt_money(total)}")

    def _restock_to_set_points(self):
        """Points the Planner at the gap between each active recipe's set point and
        what's made up. Recipes with no set point are left exactly as they are."""
        gaps = []
        for rid, r in self.data["recipes"].items():
            point = (self.data.get("crafted", {}).get(rid) or {}).get("setPoint") or 0
            if r.get("active") and point > 0:
                gaps.append((rid, r["name"], eng.crafted_short(self.data, rid)))
        if not gaps:
            messagebox.showinfo("No set points", "No active recipe has a set point yet. Set them on the Crafted Inventory tab first.")
            return
        needed = sum(1 for _, _, g in gaps if g > 0)
        if not messagebox.askyesno(
            "Restock Planner",
            f"{len(gaps)} active recipe(s) have a set point; {needed} are under it.\n\n"
            "Their Planner targets will be set to the shortfall, and only the ones that are short will be enabled. "
            "Recipes without a set point are left alone.\n\nContinue?"):
            return
        for rid, _, gap in gaps:
            self.data["plan"]["targets"][rid] = {"enabled": gap > 0, "qty": gap}
        eng.save_data(self.data)
        self.refresh_all()
        self.notebook.select(self.tab_planner)

    # ---------- Planner ----------
    def _build_planner(self):
        top = ttk.Frame(self.tab_planner, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        hint = ttk.Label(top, text="Double-click a cell to edit.")
        hint.pack(side="left")
        self.bulk_qty_var = tk.StringVar(value="100")
        ttk.Entry(top, textvariable=self.bulk_qty_var, width=8).pack(side="left", padx=(10, 4))
        ttk.Button(top, text="Set target for all enabled", command=self._bulk_apply).pack(side="left", padx=(0, 12))
        ttk.Button(top, text="Mark Made…", command=self._mark_made).pack(side="left", padx=(0, 12))
        ttk.Button(top, text="Restock to Set Points", command=self._restock_to_set_points).pack(side="left")
        autowrap_toolbar(top, hint)

        plan_frame, self.plan_tree = make_tree(
            self.tab_planner, ["Enabled", "Recipe", "In Stock", "Set Point", "Target Qty", "Crafts Needed", "Run Cost"],
            {"Recipe": 180}, height=4,
        )
        plan_frame.pack(fill="both", expand=True, padx=10, pady=(6, 6))
        self.plan_tree.bind("<Double-1>", self._planner_cell_click)

        order_label = ttk.Frame(self.tab_planner, padding=(10, 4, 10, 0))
        order_label.pack(fill="x")
        ttk.Label(order_label, text="What To Order", font=(RESOLVED["display"], 14), foreground=ACCENT).pack(side="left")
        self.order_total_var = tk.StringVar(value="")
        ttk.Label(order_label, textvariable=self.order_total_var, foreground=INK_DIM).pack(side="left", padx=10)
        self.copy_all_btn = ttk.Button(order_label, text="Copy List", command=self._copy_order_list)
        self.copy_all_btn.pack(side="right")
        copy_hint = ttk.Label(order_label, text="Ctrl+C copies the selected row", foreground=INK_DIM)
        copy_hint.pack(side="right", padx=10)
        autowrap_toolbar(order_label, copy_hint)

        order_frame, self.order_tree = make_tree(
            self.tab_planner, ["Ingredient", "Short", "Do This"], {"Ingredient": 140, "Do This": 420}, height=4,
        )
        order_frame.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        configure_tier_tags(self.order_tree)     # red rows = marked unavailable on Raw Inventory
        self.order_items = {}
        self.order_tree.bind("<Control-c>", lambda e: self._copy_order_list(selected_only=True))

    def _copy_order_list(self, selected_only=False):
        """Copies 'Item xQty' lines -- the thing you actually acquire (e.g. the
        raw material, not the converted product) -- ready to paste into chat or a note."""
        keys = self.order_tree.selection() if selected_only else self.order_tree.get_children()
        lines = [f"{self.order_items[k][0]} x{self.order_items[k][1]:g}" for k in keys if k in self.order_items]
        if not lines:
            return "break"
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.update()
        self.copy_all_btn.configure(text="Copied!")
        self.after(1500, lambda: self.copy_all_btn.configure(text="Copy List"))
        return "break"

    def _planner_cell_click(self, event):
        tree = self.plan_tree
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        col = tree.identify_column(event.x)
        if col == "#1":  # Enabled
            t = self.data["plan"]["targets"].get(row_id, {"enabled": False, "qty": 0})
            t["enabled"] = not t.get("enabled", False)
            self.data["plan"]["targets"][row_id] = t
            eng.save_data(self.data)
            self.refresh_all()
        elif col in ("#3", "#4"):  # In Stock / Set Point (same finished-goods record as the Crafted tab)
            inline_edit_entry(tree, row_id, col, tree.set(row_id, col),
                              lambda raw, rid=row_id, f=("qty" if col == "#3" else "setPoint"): self._edit_crafted_field(rid, f, raw))
        elif col == "#5":  # Target Qty
            def commit(raw, rid=row_id):
                try:
                    qty = max(0.0, float(raw))
                except ValueError:
                    messagebox.showerror("Invalid number", "Target quantity must be a number.")
                    return
                cur = self.data["plan"]["targets"].get(rid, {"enabled": False, "qty": 0})
                self.data["plan"]["targets"][rid] = {"enabled": cur.get("enabled", False), "qty": qty}
                eng.save_data(self.data)
                self.refresh_all()
            inline_edit_entry(tree, row_id, col, tree.set(row_id, col), commit)

    def _bulk_apply(self):
        try:
            qty = max(0.0, float(self.bulk_qty_var.get()))
        except ValueError:
            messagebox.showerror("Invalid number", "Target quantity must be a number.")
            return
        for rid, t in self.data["plan"]["targets"].items():
            if t.get("enabled"):
                t["qty"] = qty
        eng.save_data(self.data)
        self.refresh_all()

    def _mark_made(self):
        sel = self.plan_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a recipe in the table above first.")
            return
        rid = sel[0]
        r = self.data["recipes"][rid]
        t = self.data["plan"]["targets"].get(rid, {"enabled": False, "qty": 0})
        yield_qty = r["yieldQty"] if r.get("yieldQty", 0) > 0 else 1
        default_crafts = max(1, -(-int(t.get("qty", 0)) // yield_qty)) if t.get("qty", 0) > 0 else 1

        dialog = tk.Toplevel(self)
        dialog.title(f"Mark Made — {r['name']}")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.configure(background=BG)
        form = ttk.Frame(dialog, padding=12)
        form.pack()
        uses_parts = [f"{eng.ing_name(self.data, li['ingredientId'])} x{li['qty']:g}" for li in r["ingredients"]]
        ttk.Label(form, text=f"How many times did you craft \"{r['name']}\"?").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(form, text="(each craft uses: " + ", ".join(uses_parts) + ")",
                  foreground=INK_DIM, wraplength=340, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        crafts_var = tk.StringVar(value=str(default_crafts))
        ttk.Entry(form, textvariable=crafts_var, width=8).grid(row=2, column=0, sticky="w")
        ttk.Label(form, text=f"Also adds the finished items ({yield_qty} per craft) to Crafted Inventory.",
                  foreground=INK_DIM, wraplength=340, justify="left").grid(row=2, column=1, sticky="w", padx=(10, 0))

        def confirm():
            try:
                crafts = int(float(crafts_var.get()))
            except ValueError:
                messagebox.showerror("Invalid number", "Enter a whole number of crafts.", parent=dialog)
                return
            if crafts <= 0:
                messagebox.showerror("Invalid number", "Must be at least 1.", parent=dialog)
                return
            notes = []
            shortfalls = eng.apply_made(self.data, rid, crafts, notes)
            eng.save_data(self.data)
            self.refresh_all()
            dialog.destroy()
            converted = "Not enough on hand, so these came from their base ingredient:\n" + "\n".join(notes)
            if shortfalls:
                msg = "Inventory was set to 0 for:\n" + "\n".join(shortfalls)
                messagebox.showwarning("Stock ran short", msg + ("\n\n" + converted if notes else ""))
            elif notes:
                messagebox.showinfo("Used base ingredients", converted)

        btns = ttk.Frame(form)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=dialog.destroy).pack(side="left", padx=4)
        ttk.Button(btns, text="Deduct & Update Planner", command=confirm).pack(side="left")
        center(dialog, self)

    def receipt_title(self):
        return self.data["settings"].get("businessName") or "Receipt"

    def _open_counter_order(self):
        if self.counter_dialog is not None and self.counter_dialog.winfo_exists():
            self.counter_dialog.deiconify()
            self.counter_dialog.lift()
            self.counter_dialog.focus_force()
            return
        self.counter_dialog = CounterOrderDialog(self)

    def _refresh_counter(self):
        if self.counter_dialog is not None and self.counter_dialog.winfo_exists():
            self.counter_dialog.refresh()

    def apply_branding(self):
        s = self.data["settings"]
        name = s.get("businessName", "My Business")
        icon = s.get("appIcon", "\U0001F4D2")
        tagline = s.get("tagline", "")
        self.title(f"{name} — Ledger")
        self.title_label.configure(text=f"{icon} {name}")
        self.subtitle_label.configure(text=f"  {tagline} — data saves to ledger_data.json" if tagline else "  data saves to ledger_data.json")

    # ---------- refresh ----------
    def refresh_all(self):
        self._refresh_dashboard()
        self._refresh_recipes()
        self._refresh_ingredients()
        self._refresh_vendors()
        self._refresh_inventory()
        self._refresh_crafted()
        self._refresh_planner()
        self._refresh_counter()

    def _refresh_dashboard(self):
        recipes = list(self.data["recipes"].items())
        metrics = {rid: eng.recipe_metrics(self.data, r) for rid, r in recipes}
        active_n = sum(1 for _, r in recipes if r["active"])
        over_cap = sum(1 for rid, _ in recipes if metrics[rid]["overCap"])
        problematic = sum(1 for rid, _ in recipes if metrics[rid]["tier"] == "problematic")
        plan = eng.compute_plan(self.data)
        short_lines = sum(1 for s in plan["shortages"] if s["shortage"] > 0)

        self.metric_vars["active"].set(f"{active_n} / {len(recipes)}")
        self.metric_vars["short"].set(str(short_lines))
        self.metric_vars["overcap"].set(str(over_cap))
        self.metric_vars["problematic"].set(str(problematic))

        self.grow_tree.delete(*self.grow_tree.get_children())
        for g in plan["growNext"]:
            self.grow_tree.insert("", "end", values=(eng.ing_name(self.data, g["id"]), int(g["shortage"]), g["numRecipes"], int(g["score"])))

        self.watch_tree.delete(*self.watch_tree.get_children())
        for rid, r in recipes:
            m = metrics[rid]
            if m["tier"] in ("healthy", "good") and not m["overCap"]:
                continue
            flag = ("OVER MAX, " if m["overCap"] else "") + m["tier"]
            self.watch_tree.insert("", "end", values=(r["name"], eng.fmt_money(m["costPerItem"]), eng.fmt_money(r["salePrice"]), flag),
                                    tags=(f"tier_{m['tier']}",))
        restore_sort(self.watch_tree)
        stripe_tree(self.grow_tree)

    def _refresh_recipes(self):
        self.recipes_tree.delete(*self.recipes_tree.get_children())
        for rid, r in sorted(self.data["recipes"].items(), key=lambda kv: kv[1]["name"]):
            m = eng.recipe_metrics(self.data, r)
            margin = "—" if m["margin"] is None else f"{m['margin']*100:.1f}%"
            tier = m["tier"]
            name = r["name"] + (" ⚠️" if m["craft"]["warn"] else "")
            yield_qty = r["yieldQty"] if r.get("yieldQty", 0) > 0 else 1
            labor_per_item = m["craft"]["laborCost"] / yield_qty
            self.recipes_tree.insert("", "end", iid=rid, values=(
                name, r["category"], r["yieldQty"], eng.fmt_money(labor_per_item), eng.fmt_money(m["craft"]["total"]), eng.fmt_money(m["costPerItem"]),
                eng.fmt_money(r["salePrice"]) + (" (over max)" if m["overCap"] else ""), eng.fmt_money(m["profit"]),
                margin, tier, "Yes" if r["active"] else "No",
            ), tags=(f"tier_{m['tier']}",))
        restore_sort(self.recipes_tree)

    def _refresh_ingredients(self):
        self.ing_tree.delete(*self.ing_tree.get_children())
        reason_map = {"conversion": "via conversion", "vendor": "vendor", "custom": "custom cost",
                      "no-price": "no data", "circular": "circular!"}
        for iid in sorted(self.data["ingredients"], key=lambda i: self.data["ingredients"][i]["name"]):
            ing = self.data["ingredients"][iid]
            res = eng.ing_cost(self.data, iid)
            cost_txt = "NO PRICE" if res["warn"] else eng.fmt_money(res["cost"])
            self.ing_tree.insert("", "end", iid=iid, values=(ing["name"], ing["unit"], cost_txt, reason_map.get(res["reason"], res["reason"])))
        stripe_tree(self.ing_tree)

        self.conv_tree.delete(*self.conv_tree.get_children())
        for c in self.data["conversions"]:
            desc = f"{c['inputQty']:g}× {eng.ing_name(self.data, c['inputId'])} → {c['outputQty']:g}× {eng.ing_name(self.data, c['outputId'])}"
            self.conv_tree.insert("", "end", iid=c["id"], values=(desc, eng.fmt_money(c.get("cost") or 0)))
        stripe_tree(self.conv_tree)

    def _refresh_vendors(self):
        self.vendor_tree.delete(*self.vendor_tree.get_children())
        for iid in sorted(self.data["ingredients"], key=lambda i: self.data["ingredients"][i]["name"]):
            cheap = eng.cheapest_vendor(self.data, iid)
            rows = sorted([v for v in self.data["vendors"] if v["ingredientId"] == iid],
                          key=lambda v: (v["price"] is None, v.get("price") or 0))
            for v in rows:
                price_txt = "TBD" if v.get("price") is None else eng.fmt_money(v["price"])
                if cheap and v["id"] == cheap["id"]:
                    price_txt += " ★"
                self.vendor_tree.insert("", "end", iid=v["id"], values=(
                    self.data["ingredients"][iid]["name"], v["vendorName"], v.get("town") or "—",
                    price_txt, v.get("stock", "unknown"), v.get("note", ""),
                ))
        stripe_tree(self.vendor_tree)

    def _refresh_inventory(self):
        selected = self._selected_inventory_id()
        needs = eng.order_needs(self.data)
        self.inv_tree.delete(*self.inv_tree.get_children())
        total = 0.0
        for iid in sorted(self.data["ingredients"], key=lambda i: self.data["ingredients"][i]["name"]):
            ing = self.data["ingredients"][iid]
            inv = self.data["inventory"].get(iid, {"qty": 0, "preferredVendorId": None})
            res = eng.ing_cost(self.data, iid)
            value = (inv.get("qty") or 0) * res["cost"]
            total += value
            pref_id = inv.get("preferredVendorId")
            if pref_id:
                v = next((x for x in self.data["vendors"] if x["id"] == pref_id), None)
                pref_txt = v["vendorName"] if v else "cheapest available"
            else:
                pref_txt = "cheapest available"
            self.inv_tree.insert("", "end", iid=iid, values=(
                ing["name"], ing["unit"], f"{inv.get('qty', 0):g}", eng.to_order_entry(self.data, iid, needs)["text"], pref_txt,
                "NO PRICE" if res["warn"] else eng.fmt_money(res["cost"]), eng.fmt_money(value),
            ))
        stripe_tree(self.inv_tree)
        for iid in self.inv_tree.get_children():
            if eng.is_unavailable(self.data, iid):          # frozen rows show red
                self.inv_tree.item(iid, tags=("tier_problematic",))
        if selected and self.inv_tree.exists(selected):
            self.inv_tree.selection_set(selected)
        self._sync_freeze_button()
        self.inv_total_var.set(f"Total value: {eng.fmt_money(total)}")

    def _refresh_planner(self):
        plan = eng.compute_plan(self.data)
        run_by_id = {row["recipeId"]: row for row in plan["rows"]}
        self.plan_tree.delete(*self.plan_tree.get_children())
        for rid, r in sorted(self.data["recipes"].items(), key=lambda kv: kv[1]["name"]):
            t = self.data["plan"]["targets"].get(rid, {"enabled": False, "qty": 0})
            run = run_by_id.get(rid)
            c = self.data.get("crafted", {}).get(rid) or {}
            self.plan_tree.insert("", "end", iid=rid, values=(
                "☑" if t.get("enabled") else "☐", r["name"], f"{c.get('qty') or 0:g}", f"{c.get('setPoint') or 0:g}",
                f"{t.get('qty', 0):g}",
                run["crafts"] if run else "—", eng.fmt_money(run["runCost"]) if run else "—",
            ))
        stripe_tree(self.plan_tree)

        shortages = [s for s in plan["shortages"] if s["shortage"] > 0]
        order_total = 0.0
        self.order_tree.delete(*self.order_tree.get_children())
        self.order_items = {}
        unavailable_rows = []
        for s in shortages:
            last = eng.resolve_purchase_steps(self.data, s["id"], s["shortage"])[-1]
            if last["type"] == "buy":
                order_total += last["vendor"]["price"] * last["qty"]
            self.order_items[s["id"]] = (eng.ing_name(self.data, last["ingredientId"]), last["qty"])
            blocked = eng.is_unavailable(self.data, last["ingredientId"])
            if blocked:
                unavailable_rows.append(s["id"])
            self.order_tree.insert("", "end", iid=s["id"], values=(
                eng.ing_name(self.data, s["id"]), int(s["shortage"]),
                eng.order_line_text(self.data, s["id"], s["shortage"]) + ("  [marked unavailable]" if blocked else ""),
            ))
        stripe_tree(self.order_tree)
        for rid in unavailable_rows:
            self.order_tree.item(rid, tags=("tier_problematic",))
        self.order_total_var.set(f"Estimated spend: {eng.fmt_money(order_total)}")


def _tk_callback_error(self, exc, val, tb):
    report_error("".join(traceback.format_exception(exc, val, tb)), parent=self)


LedgerApp.report_callback_exception = _tk_callback_error


def main():
    try:
        app = LedgerApp()
    except Exception:
        text = traceback.format_exc()
        stray = tk._default_root
        if stray is not None:
            try:
                stray.destroy()
            except Exception:
                pass
        holder = tk.Tk()
        holder.withdraw()
        report_error(text, parent=holder, title="The ledger couldn't start",
                     hint="The ledger couldn't start. If the details below mention ledger_data.json, "
                          "that file may be damaged: copy it somewhere safe, delete it from this folder, "
                          "and start again. Otherwise send this message to whoever supports you.")
        holder.destroy()
        return
    app.mainloop()


if __name__ == "__main__":
    main()
