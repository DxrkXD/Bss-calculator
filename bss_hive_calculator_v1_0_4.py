import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import re
import json
import os
import sys
import threading
import urllib.request
import urllib.error
import webbrowser
from collections import defaultdict

# ==========================================================
# App metadata
# ==========================================================
APP_NAME = "BSS Calculator - Made By DxrkXD"
APP_VERSION = "1.0.8"
# settings loaded later (after functions defined)
settings = None
APP_AUTHOR = "Made By DxrkXD"

# Update checker JSON (host this file on GitHub raw)
# Example JSON:
# {"latest":"1.0.6","download_url":"https://github.com/.../releases/download/v1.0.6/bss_hive_calculator.exe","notes":"..."}
UPDATE_JSON_URL = "https://raw.githubusercontent.com/DxrkXD/Bss-calculator/main/update.json"


def resource_path(relative_path: str) -> str:
    """EXE-safe path (PyInstaller --onefile)."""
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# ==========================================================
# Settings + Tooltips
# ==========================================================

DEFAULT_SETTINGS = {
    "theme": "dark",              # "dark" or "light"
    "auto_update_check": True,
    "remember_inputs": True,
    "enable_tooltips": True,
}

def _appdata_dir() -> str:
    # Windows: LOCALAPPDATA, else home
    base = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "BSSCalculator")
    os.makedirs(d, exist_ok=True)
    return d

SETTINGS_PATH = os.path.join(_appdata_dir(), "settings.json")
LAST_INPUTS_PATH = os.path.join(_appdata_dir(), "last_inputs.json")

def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                s.update({k: data.get(k, v) for k, v in DEFAULT_SETTINGS.items()})
    except Exception:
        pass
    # normalize
    s["theme"] = "dark" if str(s.get("theme", "dark")).lower() != "light" else "light"
    for k in ("auto_update_check", "remember_inputs", "enable_tooltips"):
        s[k] = bool(s.get(k, DEFAULT_SETTINGS[k]))
    return s

def save_settings(s: dict) -> None:
    try:
        payload = {k: s.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS.keys()}
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass

class Tooltip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(self.tip, text=self.text, justify="left",
                             padx=8, pady=6, font=("Segoe UI", 9))
            label.pack()
            # Theme the tooltip roughly
            if dark:
                label.configure(bg="#1f1f1f", fg="#f0f0f0")
            else:
                label.configure(bg="#ffffe0", fg="#111111")
        except Exception:
            self.tip = None

    def hide(self, _=None):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None

def add_tooltip(widget, text: str):
    # Uses global `settings`
    try:
        if settings.get("enable_tooltips", True):
            Tooltip(widget, text)
    except Exception:
        pass


def set_app_icon(root: tk.Tk):
    """
    Optional icon support:
    - Put app.ico next to the .py when building
    - For the EXE icon itself, also pass: --icon app.ico
    """
    try:
        ico = resource_path("app.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass

# Load settings now that load_settings/save_settings exist
settings = load_settings()



# ==========================================================
# Honey parse/format
# ==========================================================

def parse_honey(text: str) -> float:
    text = (text or "").strip().upper()
    if text in ("", "0"):
        return 0.0
    m = re.fullmatch(r"([\d.]+)\s*([KMBTQ]?)", text)
    if not m:
        raise ValueError("Use values like 11.94T, 500B, 1.2Q (or 0)")
    num = float(m.group(1))
    suf = m.group(2)
    mult = {"": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12, "Q": 1e15}
    return num * mult[suf]

def format_honey(h: float) -> str:
    if h <= 0:
        return "0"
    for suf, val in [("Q", 1e15), ("T", 1e12), ("B", 1e9), ("M", 1e6)]:
        if h >= val:
            return f"{h / val:.3f}{suf}"
    return f"{h:,.0f}"

# ==========================================================
# Hive costs (known 1–20; projected 21+)
# ==========================================================

# ==========================================================
# Bee Level (Bond) Costs per Bee
# Source: in‑game bond required per level (index = current level)
# Example: level 21 -> 22 costs BOND_TABLE[21] bond per bee.
# ==========================================================

BOND_TABLE = [
    0,
    10,
    40,
    200,
    750,
    4000,
    15000,
    60000,
    270000,
    450000,
    1200000,
    2000000,
    4000000,
    7000000,
    15000000,
    120000000,
    450000000,
    1900000000,
    7500000000,
    15000000000,
    475000000000,
    4500000000000,
    95000000000000,
    5000000000000000,
    95000000000000000,
]

def cost_per_bee(level: int) -> int:
    """Bond needed to level ONE bee from `level` to `level+1`."""
    if level < 0:
        raise ValueError("Level cannot be negative.")
    if level < len(BOND_TABLE):
        return int(BOND_TABLE[level])

    # Extrapolate beyond the last known level using the last growth ratio
    last = float(BOND_TABLE[-1])
    prev = float(BOND_TABLE[-2])
    ratio = last / prev if prev > 0 else 2.0
    steps = level - (len(BOND_TABLE) - 1)
    return int(last * (ratio ** steps))

# ==========================================================
# Blender recipes (raw expansion)
# Fixes:
# - Swirled Wax = 3333 Royal Jelly
# - Caustic Wax = 5252 Royal Jelly
# ==========================================================

BLENDER_RECIPES = {
    "Red Extracts": {"Strawberries": 50, "Royal Jelly": 10},
    "Blue Extracts": {"Blueberries": 50, "Royal Jelly": 10},
    "Enzymes": {"Pineapples": 50, "Royal Jelly": 10},
    "Oil": {"Sunflower Seeds": 50, "Royal Jelly": 10},
    "Gumdrops": {"Blueberries": 3, "Strawberries": 3, "Pineapples": 3},
    "Glue": {"Gumdrops": 50, "Royal Jelly": 10},
    "Tropical Drinks": {"Coconuts": 10, "Enzymes": 2, "Oil": 2},
    "Purple Potion": {"Neonberries": 3, "Red Extracts": 3, "Blue Extracts": 3, "Glue": 3},

    "Soft Wax": {"Honeysuckles": 5, "Oil": 1, "Enzymes": 1, "Royal Jelly": 10},
    "Hard Wax": {"Soft Wax": 3, "Enzymes": 3, "Bitterberries": 33, "Royal Jelly": 33},
    "Swirled Wax": {"Hard Wax": 3, "Soft Wax": 9, "Purple Potion": 6, "Royal Jelly": 3333},
    "Caustic Wax": {"Hard Wax": 5, "Enzymes": 5, "Neonberries": 25, "Royal Jelly": 5252},

    "Moon Charms": {"Pineapples": 5, "Gumdrops": 5, "Royal Jelly": 1},
    "Glitter": {"Moon Charms": 25, "Magic Bean": 1},
    "Star Jelly": {"Royal Jelly": 100, "Glitter": 3},

    "Super Smoothies": {"Neonberries": 3, "Star Jelly": 3, "Purple Potion": 3, "Tropical Drinks": 6},
    "Turpentine": {"Super Smoothies": 10, "Caustic Wax": 10, "Star Jelly": 100, "Honeysuckles": 1000},
}

def expand_to_raw(item: str, amount: int, totals: defaultdict):
    if amount <= 0:
        return
    if item not in BLENDER_RECIPES:
        totals[item] += amount
        return
    for sub, sub_amt in BLENDER_RECIPES[item].items():
        expand_to_raw(sub, amount * sub_amt, totals)

def compute_raw_from_crafted(crafted_needed: dict) -> dict:
    req = defaultdict(int)
    for item, amt in crafted_needed.items():
        expand_to_raw(item, int(amt), req)
    return dict(sorted(req.items(), key=lambda x: x[0].lower()))

# ==========================================================
# Crafting targets
# ==========================================================

CRAFT_TARGETS = {
    "Dark Scythe": {
        "Honey": "2.5T",
        "Resources": {
            "Red Extracts": 1500,
            "Stingers": 150,
            "Hard Wax": 100,
            "Caustic Wax": 50,
            "Super Smoothies": 50,
            "Invigorating Vial": 3,
        },
    },
    "Gummyballer": {
        "Honey": "10T",
        "Resources": {
            "Glue": 1500,
            "Gumdrops": 2000,
            "Super Smoothies": 50,
            "Turpentine": 5,
            "Satisfying Vial": 3,
        },
    },
    "Tide Popper": {
        "Honey": "2.5T",
        "Resources": {
            "Blue Extracts": 1500,
            "Stingers": 150,
            "Tropical Drinks": 150,
            "Swirled Wax": 75,
            "Super Smoothies": 50,
            "Comforting Vial": 3,
        },
    },

    "Gummy Mask": {
        "Honey": "5B",
        "Resources": {
            "Glue": 250,
            "Enzymes": 100,
            "Oil": 100,
            "Glitter": 100,
            "Satisfying Vial": 1,
        },
    },
    "Demon Mask": {
        "Honey": "5B",
        "Resources": {
            "Stingers": 500,
            "Red Extracts": 250,
            "Enzymes": 150,
            "Glue": 100,
            "Invigorating Vial": 1,
        },
    },
    "Diamond Mask": {
        "Honey": "5B",
        "Resources": {
            "Blue Extracts": 250,
            "Oil": 150,
            "Glitter": 100,
            "Diamond Egg": 5,
            "Refreshing Vial": 1,
        },
    },

    "Coconut Clogs": {
        "Honey": "10B",
        "Resources": {
            "Coconuts": 150,
            "Tropical Drinks": 50,
            "Glue": 100,
            "Oil": 100,
            "Comforting Vial": 1,
        },
    },
    "Coconut Canister": {
        "Honey": "25B",
        "Resources": {
            "Coconuts": 250,
            "Tropical Drinks": 150,
            "Red Extracts": 150,
            "Blue Extracts": 150,
            "Comforting Vial": 2,
        },
    },
    "Coconut Belt": {
        "Honey": "7.5T",
        "Resources": {
            "Coconuts": 500,
            "Tropical Drinks": 1500,
            "Purple Potion": 200,
            "Hard Wax": 200,
            "Comforting Vial": 3,
            "Turpentine": 3,
        },
    },

    "Gummy Boots": {
        "Honey": "100B",
        "Resources": {
            "Glue": 500,
            "Red Extracts": 250,
            "Blue Extracts": 250,
            "Glitter": 250,
            "Satisfying Vial": 1,
            "Comforting Vial": 1,
        },
    },

    "Heat-Treated Planter": {
        "Honey": "750B",
        "Resources": {
            "Motivating Vial": 75,
            "Red Extracts": 750,
            "Hard Wax": 150,
            "Swirled Wax": 25,
            "Turpentine": 1,
        },
    },
    "Hydroponic Planter": {
        "Honey": "750B",
        "Resources": {
            "Motivating Vial": 75,
            "Blue Extracts": 750,
            "Soft Wax": 500,
            "Caustic Wax": 25,
            "Turpentine": 1,
        },
    },
    "Petal Planter": {
        "Honey": "5T",
        "Resources": {
            "Magic Bean": 100,
            "Soft Wax": 100,
            "Hard Wax": 250,
            "Swirled Wax": 50,
            "Turpentine": 25,
        },
    },
    "Planter Of Plenty": {
        "Honey": "100T",
        "Resources": {
            "Magic Bean": 500,
            "Super Smoothies": 100,
            "Swirled Wax": 100,
            "Caustic Wax": 100,
            "Turpentine": 25,
        },
    },
}

# ==========================================================
# UI helpers: scrollable frame
# ==========================================================

class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)  # Windows wheel

    def _on_configure(self, _=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

# ==========================================================
# App + Theme
# ==========================================================

root = tk.Tk()
root.title(f"{APP_NAME} v{APP_VERSION}")
set_app_icon(root)

# ==========================================================
# Menubar (File / Help) — restored
# ==========================================================

def _version_tuple(v: str):
    # supports "1.0.6" etc
    parts = []
    for x in re.findall(r"\d+", v or ""):
        try:
            parts.append(int(x))
        except Exception:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])

def check_for_updates(show_if_latest: bool = True):
    """Check UPDATE_JSON_URL for latest version. Runs in a background thread."""
    def worker():
        try:
            req = urllib.request.Request(UPDATE_JSON_URL, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            latest = str(data.get("latest", "")).strip()
            url = str(data.get("download_url", "")).strip()
            notes = str(data.get("notes", "")).strip()

            if not latest:
                raise ValueError("Update JSON missing 'latest'.")

            if _version_tuple(latest) > _version_tuple(APP_VERSION):
                msg = f"New version available!\n\nCurrent: {APP_VERSION}\nLatest: {latest}"
                if notes:
                    msg += f"\n\nNotes:\n{notes}"
                if messagebox.askyesno("Update Available", msg + "\n\nOpen download page?"):
                    if url:
                        webbrowser.open(url)
                    else:
                        webbrowser.open("https://github.com/DxrkXD/Bss-calculator/releases")
            else:
                if show_if_latest:
                    messagebox.showinfo("Up to date", f"You're on the latest version: {APP_VERSION}")
        except Exception as e:
            messagebox.showerror("Update check failed", str(e))

    threading.Thread(target=worker, daemon=True).start()

def show_about():
    messagebox.showinfo(
        "About",
        f"{APP_NAME}\nVersion: {APP_VERSION}\n{APP_AUTHOR}"
    )

def open_github():
    webbrowser.open("https://github.com/DxrkXD/Bss-calculator")

menubar = tk.Menu(root)

file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label="Save Profile…", command=lambda: save_profile())
file_menu.add_command(label="Load Profile…", command=lambda: load_profile())
file_menu.add_command(label="Export Results…", command=lambda: export_results())
file_menu.add_separator()
file_menu.add_command(label="Exit", command=root.quit)
menubar.add_cascade(label="File", menu=file_menu)

help_menu = tk.Menu(menubar, tearoff=0)
help_menu.add_command(label="Check for Updates", command=lambda: check_for_updates(True))
help_menu.add_command(label="GitHub", command=open_github)
help_menu.add_separator()
help_menu.add_command(label="About", command=show_about)
menubar.add_cascade(label="Help", menu=help_menu)

root.config(menu=menubar)

def animate_window_title(duration_ms: int = 2200, interval_ms: int = 120):
    base = f"{APP_NAME} v{APP_VERSION}"
    start = 0
    def tick():
        nonlocal start
        dots = (start // interval_ms) % 4
        root.title(base + ("." * dots))
        start += interval_ms
        if start < duration_ms:
            root.after(interval_ms, tick)
        else:
            root.title(base)
    tick()

root.geometry("1200x960")
root.minsize(1200, 960)

BASE_FONT = ("Segoe UI", 10)
TITLE_FONT = ("Segoe UI", 16, "bold")
CARD_TITLE_FONT = ("Segoe UI", 11, "bold")

dark = (settings.get("theme","dark") == "dark")
style = ttk.Style()

# ----------------------------------------------------------
# Card helper (for consistent panels)
# ----------------------------------------------------------
def card_frame(parent, title: str = "", padding: int = 12):
    """Creates a nice 'card' container. Title optional."""
    if title:
        lf = ttk.Labelframe(parent, text=title, padding=padding)
        return lf
    f = ttk.Frame(parent, padding=padding)
    return f


status_var = tk.StringVar(value="Ready")

def set_status(text: str):
    status_var.set(text)

def labeled_entry(parent, label, default="0", width=16):
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=6)
    ttk.Label(row, text=label).pack(side="left")
    ent = ttk.Entry(row, width=width)
    ent.pack(side="right")
    ent.insert(0, default)
    return ent

def copy_text_widget(text_widget: tk.Text):
    root.clipboard_clear()
    root.clipboard_append(text_widget.get("1.0", "end-1c"))
    set_status("Copied to clipboard")

def clear_text_widget(text_widget: tk.Text):
    text_widget.config(state="normal")
    text_widget.delete("1.0", tk.END)
    text_widget.config(state="disabled")
    set_status("Cleared output")

def reset_entries(entries, default="0"):
    for e in entries:
        try:
            e.delete(0, tk.END)
            e.insert(0, default)
        except Exception:
            pass
    set_status("Reset to 0")

def apply_theme():
    global style
    if dark:
        C_BG = "#0F1115"
        C_CARD = "#151A21"
        C_ENTRY = "#1C2330"
        C_BORDER = "#2A3441"
        C_TEXT = "#E6EAF0"
        C_MUTED = "#AAB4C0"
        C_ACCENT = "#4DA3FF"
        C_TEXTBOX = "#0E1218"
    else:
        C_BG = "#F5F7FB"
        C_CARD = "#FFFFFF"
        C_ENTRY = "#FFFFFF"
        C_BORDER = "#D6DCE6"
        C_TEXT = "#121826"
        C_MUTED = "#5A6472"
        C_ACCENT = "#2563EB"
        C_TEXTBOX = "#FFFFFF"

    style.theme_use("clam")
    root.configure(bg=C_BG)

    style.configure(".", font=BASE_FONT, background=C_BG, foreground=C_TEXT)
    style.configure("TFrame", background=C_BG)
    style.configure("Card.TFrame", background=C_CARD)
    style.configure("TLabel", background=C_BG, foreground=C_TEXT)
    style.configure("Muted.TLabel", background=C_BG, foreground=C_MUTED)
    style.configure("CardTitle.TLabel", background=C_CARD, foreground=C_TEXT, font=CARD_TITLE_FONT)
    style.configure("Title.TLabel", background=C_BG, foreground=C_TEXT, font=TITLE_FONT)

    style.configure("TNotebook", background=C_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=C_CARD, foreground=C_TEXT, padding=(12, 8))
    style.map("TNotebook.Tab", background=[("selected", C_ENTRY)])

    style.configure("TLabelframe", background=C_CARD, foreground=C_TEXT, bordercolor=C_BORDER)
    style.configure("TLabelframe.Label", background=C_CARD, foreground=C_TEXT, font=CARD_TITLE_FONT)

    style.configure("TEntry", fieldbackground=C_ENTRY, foreground=C_TEXT, bordercolor=C_BORDER)
    style.configure("TCombobox", fieldbackground=C_ENTRY, foreground=C_TEXT)
    style.map("TCombobox", fieldbackground=[("readonly", C_ENTRY)], foreground=[("readonly", C_TEXT)])

    style.configure("TButton", background=C_CARD, foreground=C_TEXT, bordercolor=C_BORDER, padding=(12, 8))
    style.map("TButton", background=[("active", C_ENTRY)])
    style.configure("Accent.TButton", background=C_ACCENT, foreground="white", padding=(14, 10))
    style.map("Accent.TButton", background=[("active", C_ACCENT)])

    style.configure("Vertical.TScrollbar", background=C_CARD, troughcolor=C_BG, bordercolor=C_BORDER, arrowcolor=C_TEXT)

    # Text widgets
    for tb in (hive_output, craft_output, blender_output, hourly_output):
        tb.configure(bg=C_TEXTBOX, fg=C_TEXT, insertbackground=C_TEXT)

    # Canvas backgrounds
    craft_have_scroll.canvas.configure(bg=C_CARD)
    blender_ing_scroll.canvas.configure(bg=C_CARD)

    status_bar.configure(background=C_BG, foreground=C_MUTED)

def toggle_theme():
    global dark
    dark = not dark
    apply_theme()
    set_status("Theme changed")

def make_tab_header(parent, title: str, subtitle: str):
    header = ttk.Frame(parent)
    header.pack(fill="x", pady=(0, 10))

    left = ttk.Frame(header)
    left.pack(side="left", fill="x", expand=True)

    ttk.Label(left, text=title, style="Title.TLabel").pack(anchor="w")
    ttk.Label(left, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

    right = ttk.Frame(header)
    right.pack(side="right")
    ttk.Button(right, text="Toggle Light/Dark", command=toggle_theme).pack()


def get_active_output_widget():
    """Returns the Text widget for the currently selected tab."""
    try:
        tab = notebook.select()
        if tab == str(tab_hive):
            return hive_output
        if tab == str(tab_crafting):
            return craft_output
        if tab == str(tab_blender):
            return blender_output
        if "tab_hourly" in globals() and tab == str(tab_hourly):
            return hourly_output
        if "tab_settings" in globals() and tab == str(tab_settings):
            return None
    except Exception:
        return None
    return None

# ==========================================================
# Profile save/load (JSON) includes Hourly tab state too
# ==========================================================

def get_profile_state() -> dict:
    return {
        "theme_dark": dark,
        "hive": {
            "bees_in_hive": bees_in_hive_entry.get(),
            "bees_leveling": bees_leveling_entry.get(),
            "current_level": current_entry.get(),
            "target_level": target_entry.get(),
            "hourly": hive_hourly_entry.get(),
            "current_honey": hive_current_honey_entry.get(),
            "level_entire_hive": bool(level_entire_hive_var.get()),
            "gifted_puppy": bool(gifted_puppy_var.get()),
            "reindeer_antlers": bool(reindeer_antlers_var.get()),
            "moon_amulet": moon_amulet_entry.get(),
            "extra_bonus": extra_bonus_entry.get(),
        },
        "crafting": {
            "selected_target": craft_var.get(),
            "honey_have": craft_honey_have.get(),
            "have_by_target": {
                t: {k: craft_have_store[t].get(k, "0") for k in CRAFT_TARGETS[t]["Resources"].keys()}
                for t in CRAFT_TARGETS.keys()
            },
            "cart": craft_cart_items.copy(),
            "hide_completed": bool(hide_completed_var.get()),
        },
        "blender": {
            "selected_item": bl_items[bl_index] if bl_items else "",
            "qty": bl_qty.get(),
            "queue": blender_queue_items.copy(),
        },
        "hourly_calc": {
            "hourly": hourly_hourly_entry.get(),
            "current": hourly_current_entry.get(),
            "target": hourly_target_entry.get(),
        }
    }

def apply_profile_state(state: dict):
    global dark
    if not isinstance(state, dict):
        return

    dark = bool(state.get("theme_dark", True))

    hive = state.get("hive", {})
    bees_in_hive_entry.delete(0, tk.END); bees_in_hive_entry.insert(0, hive.get("bees_in_hive", "0"))
    bees_leveling_entry.delete(0, tk.END); bees_leveling_entry.insert(0, hive.get("bees_leveling", "0"))
    current_entry.delete(0, tk.END); current_entry.insert(0, hive.get("current_level", "0"))
    target_entry.delete(0, tk.END); target_entry.insert(0, hive.get("target_level", "0"))
    hive_hourly_entry.delete(0, tk.END); hive_hourly_entry.insert(0, hive.get("hourly", "0"))
    hive_current_honey_entry.delete(0, tk.END); hive_current_honey_entry.insert(0, hive.get("current_honey", "0"))
    level_entire_hive_var.set(bool(hive.get("level_entire_hive", True)))
    gifted_puppy_var.set(bool(hive.get("gifted_puppy", False)))
    reindeer_antlers_var.set(bool(hive.get("reindeer_antlers", False)))
    moon_amulet_entry.delete(0, tk.END); moon_amulet_entry.insert(0, hive.get("moon_amulet", "0"))
    extra_bonus_entry.delete(0, tk.END); extra_bonus_entry.insert(0, hive.get("extra_bonus", "0"))
    refresh_bonus_label()

    crafting = state.get("crafting", {})
    craft_honey_have.delete(0, tk.END); craft_honey_have.insert(0, crafting.get("honey_have", "0"))
    hide_completed_var.set(bool(crafting.get("hide_completed", False)))

    have_by_target = crafting.get("have_by_target", {})
    if isinstance(have_by_target, dict):
        for t, d in have_by_target.items():
            if t in craft_have_store and isinstance(d, dict):
                craft_have_store[t].update({k: str(v) for k, v in d.items()})

    cart = crafting.get("cart", [])
    if isinstance(cart, list):
        craft_cart_items.clear()
        craft_cart_items.extend([x for x in cart if isinstance(x, str) and x in CRAFT_TARGETS])

    sel = crafting.get("selected_target", craft_var.get())
    if sel in CRAFT_TARGETS:
        craft_var.set(sel)

    rebuild_craft_have()
    refresh_cart_ui()

    blender = state.get("blender", {})
    bl_qty.delete(0, tk.END); bl_qty.insert(0, blender.get("qty", "1"))

    queue = blender.get("queue", [])
    if isinstance(queue, list):
        blender_queue_items.clear()
        for it in queue:
            if isinstance(it, dict) and it.get("item") in BLENDER_RECIPES:
                try:
                    q = int(it.get("qty", 1))
                except Exception:
                    q = 1
                blender_queue_items.append({"item": it["item"], "qty": max(1, q)})
    refresh_blender_queue_ui()

    sel_item = blender.get("selected_item", "")
    if sel_item in BLENDER_RECIPES:
        set_bl_slide(bl_items.index(sel_item))

    hourly = state.get("hourly_calc", {})
    hourly_hourly_entry.delete(0, tk.END); hourly_hourly_entry.insert(0, hourly.get("hourly", "0"))
    hourly_current_entry.delete(0, tk.END); hourly_current_entry.insert(0, hourly.get("current", "0"))
    hourly_target_entry.delete(0, tk.END); hourly_target_entry.insert(0, hourly.get("target", "0"))

    apply_theme()
    set_status("Profile loaded")

def save_profile():
    try:
        fp = filedialog.asksaveasfilename(
            title="Save profile",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not fp:
            return
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(get_profile_state(), f, indent=2)
        set_status("Profile saved")
    except Exception as e:
        messagebox.showerror("Error", str(e))

def load_profile():
    try:
        fp = filedialog.askopenfilename(
            title="Load profile",
            filetypes=[("JSON", "*.json")]
        )
        if not fp:
            return
        with open(fp, "r", encoding="utf-8") as f:
            state = json.load(f)
        apply_profile_state(state)
    except Exception as e:
        messagebox.showerror("Error", str(e))


def export_results():
    """Export current tab's output to a .txt file."""
    try:
        w = get_active_output_widget()
        if not w:
            messagebox.showinfo("Export", "Nothing to export on this tab yet.")
            return
        text = w.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Export", "Nothing to export on this tab yet.")
            return
        default_name = f"bss_results_{APP_VERSION.replace('.','_').replace('v','')}.txt"
        fp = filedialog.asksaveasfilename(
            title="Export Results",
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")]
        )
        if not fp:
            return
        with open(fp, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        set_status(f"Exported results to {os.path.basename(fp)}")
    except Exception as e:
        messagebox.showerror("Export Failed", str(e))

# ==========================================================
# Notebook / tabs
# ==========================================================

notebook = ttk.Notebook(root)
notebook.pack(fill="both", expand=True, padx=14, pady=14)

# Footer
footer = tk.Label(root, text=f"{APP_NAME} v{APP_VERSION} — {APP_AUTHOR}", anchor="w", padx=10)
footer.pack(side="bottom", fill="x")

tab_hive = ttk.Frame(notebook)
tab_craft = ttk.Frame(notebook)
tab_blender = ttk.Frame(notebook)
tab_hourly = ttk.Frame(notebook)
tab_settings = ttk.Frame(notebook)

notebook.add(tab_hive, text="Hive")
notebook.add(tab_craft, text="Crafting")
notebook.add(tab_blender, text="Blender")
notebook.add(tab_hourly, text="Hourly")
notebook.add(tab_settings, text="Settings")

# ==========================================================
# TAB: Hive
# ==========================================================

make_tab_header(tab_hive, "Hive Calculator", "Makeover UI • presets • per-bee cost • level all or selected bees")

hive_body = ttk.Frame(tab_hive)
hive_body.pack(fill="both", expand=True)

hive_left = ttk.Frame(hive_body)
hive_left.pack(side="left", fill="y", padx=(0, 12))

hive_right = ttk.Frame(hive_body)
hive_right.pack(side="right", fill="both", expand=True)

hive_inputs = ttk.LabelFrame(hive_left, text="Inputs", padding=12)
hive_inputs.pack(fill="x", pady=(0, 12))

hive_bonus = ttk.LabelFrame(hive_left, text="Bond From Treats Bonus", padding=12)
hive_bonus.pack(fill="x", pady=(0, 12))

hive_actions = ttk.LabelFrame(hive_left, text="Actions", padding=12)
hive_actions.pack(fill="x")

hive_results = ttk.LabelFrame(hive_right, text="Results", padding=12)
hive_results.pack(fill="both", expand=True)

bees_in_hive_entry = labeled_entry(hive_inputs, "Bees in hive (total):", "0")
bees_leveling_entry = labeled_entry(hive_inputs, "Bees being leveled:", "0")
current_entry = labeled_entry(hive_inputs, "Current level:", "0")
target_entry = labeled_entry(hive_inputs, "Target level:", "0")
hive_hourly_entry = labeled_entry(hive_inputs, "Honey / hour:", "0")
hive_current_honey_entry = labeled_entry(hive_inputs, "Current honey:", "0")

level_entire_hive_var = tk.BooleanVar(value=True)
ttk.Checkbutton(hive_inputs, text="Level entire hive (use total)", variable=level_entire_hive_var).pack(anchor="w", pady=(8, 0))

gifted_puppy_var = tk.BooleanVar(value=False)
reindeer_antlers_var = tk.BooleanVar(value=False)
ttk.Checkbutton(hive_bonus, text="Gifted Puppy Bee (+20%)", variable=gifted_puppy_var).pack(anchor="w", pady=2)
ttk.Checkbutton(hive_bonus, text="Reindeer Antlers (+3%)", variable=reindeer_antlers_var).pack(anchor="w", pady=2)

moon_amulet_entry = labeled_entry(hive_bonus, "Moon Amulet bonus (0–10%):", "0", width=10)
extra_bonus_entry = labeled_entry(hive_bonus, "Extra bonus (custom):", "0", width=10)

total_bonus_label = ttk.Label(hive_bonus, text="Total Bonus: 100.00%  (100% = normal)", style="Muted.TLabel")
total_bonus_label.pack(anchor="w", pady=(8, 0))

progress_bar = ttk.Progressbar(hive_actions, length=260, mode="determinate")
progress_bar.pack(fill="x", pady=(0, 10))

def preset_50_bees():
    bees_in_hive_entry.delete(0, tk.END); bees_in_hive_entry.insert(0, "50")
    level_entire_hive_var.set(True)
    set_status("Preset: 50 bees")

def preset_100_bonus():
    gifted_puppy_var.set(False)
    reindeer_antlers_var.set(False)
    moon_amulet_entry.delete(0, tk.END); moon_amulet_entry.insert(0, "0")
    extra_bonus_entry.delete(0, tk.END); extra_bonus_entry.insert(0, "0")
    refresh_bonus_label()
    set_status("Preset: 100% bonus")

preset_row = ttk.Frame(hive_actions)
preset_row.pack(fill="x", pady=(0, 10))
ttk.Label(preset_row, text="Presets:", style="Muted.TLabel").pack(anchor="w")
btns = ttk.Frame(preset_row)
btns.pack(fill="x", pady=(6, 0))
ttk.Button(btns, text="50 Bees", command=preset_50_bees).pack(side="left", padx=(0, 6))
ttk.Button(btns, text="100% Bonus", command=preset_100_bonus).pack(side="left")

hive_summary = ttk.Frame(hive_results, style="Card.TFrame")
hive_summary.pack(fill="x", pady=(0, 10))

sum_total = ttk.Label(hive_summary, text="Total: —", style="CardTitle.TLabel")
sum_total.pack(anchor="w")
sum_remaining = ttk.Label(hive_summary, text="Remaining: —", style="Muted.TLabel")
sum_remaining.pack(anchor="w", pady=(4, 0))
sum_time = ttk.Label(hive_summary, text="Time: —", style="Muted.TLabel")
sum_time.pack(anchor="w", pady=(2, 0))
sum_perbee = ttk.Label(hive_summary, text="Per bee: —", style="Muted.TLabel")
sum_perbee.pack(anchor="w", pady=(2, 0))

hive_out_wrap = ttk.Frame(hive_results)
hive_out_wrap.pack(fill="both", expand=True)

hive_output = tk.Text(hive_out_wrap, height=20, wrap="word", borderwidth=0, state="disabled")
hive_output.pack(side="left", fill="both", expand=True)

hive_out_scroll = ttk.Scrollbar(hive_out_wrap, orient="vertical", command=hive_output.yview)
hive_out_scroll.pack(side="right", fill="y")
hive_output.configure(yscrollcommand=hive_out_scroll.set)

hive_out_btns = ttk.Frame(hive_results)
hive_out_btns.pack(fill="x", pady=(10, 0))
ttk.Button(hive_out_btns, text="Copy Results", command=lambda: copy_text_widget(hive_output)).pack(side="left", padx=(0, 6))
ttk.Button(hive_out_btns, text="Clear Results", command=lambda: clear_text_widget(hive_output)).pack(side="left")

def get_total_bonus_percent() -> float:
    total = 100.0
    if gifted_puppy_var.get():
        total += 20.0
    moon = float((moon_amulet_entry.get() or "0").strip() or "0")
    if not (0 <= moon <= 10):
        raise ValueError("Moon Amulet bonus must be between 0 and 10.")
    total += moon
    if reindeer_antlers_var.get():
        total += 3.0
    extra = float((extra_bonus_entry.get() or "0").strip() or "0")
    if extra < 0:
        raise ValueError("Extra bonus cannot be negative.")
    total += extra
    return total

def refresh_bonus_label(*_):
    try:
        total_bonus_label.config(text=f"Total Bonus: {get_total_bonus_percent():.2f}%  (100% = normal)")
    except Exception:
        total_bonus_label.config(text="Total Bonus: (check inputs)")

moon_amulet_entry.bind("<KeyRelease>", refresh_bonus_label)
extra_bonus_entry.bind("<KeyRelease>", refresh_bonus_label)

def _get_bees_used() -> int:
    bees_in_hive = int(bees_in_hive_entry.get() or "0")
    bees_leveling = int(bees_leveling_entry.get() or "0")
    if level_entire_hive_var.get():
        if bees_in_hive <= 0:
            raise ValueError("Bees in hive must be > 0.")
        return bees_in_hive
    if bees_leveling <= 0:
        raise ValueError("Bees being leveled must be > 0 (or enable level entire hive).")
    return bees_leveling

def calculate_hive():
    try:
        bees_used = _get_bees_used()
        cur = int(current_entry.get() or "0")
        tgt = int(target_entry.get() or "0")
        hourly = parse_honey(hive_hourly_entry.get() or "0")
        current_honey = parse_honey(hive_current_honey_entry.get() or "0")

        if cur >= tgt:
            raise ValueError("Target level must be higher than current.")
        if hourly <= 0:
            raise ValueError("Honey / hour must be > 0.")

        bonus_mult = get_total_bonus_percent() / 100.0

        total_required = 0.0
        per_bee_required = 0.0
        breakdown = []

        for lvl in range(cur, tgt):
            per_bee_step = cost_per_bee(lvl) / bonus_mult
            per_bee_required += per_bee_step
            step_total = per_bee_step * bees_used
            total_required += step_total
            breakdown.append(
                f"Level {lvl} → {lvl+1}: {format_honey(step_total)} "
                f"(per bee: {format_honey(per_bee_step)})"
                + ("  [estimated]" if lvl >= 20 else "")
            )

        remaining = max(0.0, total_required - current_honey)
        hours = remaining / hourly
        days = hours / 24

        progress = 0.0
        if total_required > 0:
            progress = min(100.0, (current_honey / total_required) * 100.0)
        progress_bar["value"] = progress

        mode_text = "ENTIRE HIVE" if level_entire_hive_var.get() else "SELECTED BEES"

        sum_total.config(text=f"Total: {format_honey(total_required)}")
        sum_remaining.config(text=f"Remaining: {format_honey(remaining)}   •   Progress: {progress:.2f}%")
        sum_time.config(text=f"Time: {hours:.2f} hours   ({days:.2f} days)")
        sum_perbee.config(text=f"Per bee (total range): {format_honey(per_bee_required)}")

        hive_output.config(state="normal")
        hive_output.delete("1.0", tk.END)
        hive_output.insert(
            tk.END,
            f"Mode: {mode_text}\n"
            f"Bees counted: {bees_used}\n"
            f"Levels: {cur} → {tgt}\n"
            f"Bonus: {get_total_bonus_percent():.2f}%\n\n"
            f"TOTAL Required: {format_honey(total_required)}\n"
            f"Per Bee Required: {format_honey(per_bee_required)}\n"
            f"Remaining: {format_honey(remaining)}\n"
            f"Time: {hours:.2f} hours ({days:.2f} days)\n\n"
            "Breakdown:\n" + "\n".join(breakdown)
        )
        hive_output.config(state="disabled")
        set_status("Hive calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

ttk.Button(hive_actions, text="Calculate", style="Accent.TButton", command=calculate_hive).pack(fill="x", pady=(0, 8))

hive_action_row = ttk.Frame(hive_actions)
hive_action_row.pack(fill="x")
ttk.Button(hive_action_row, text="Reset Hive Inputs", command=lambda: reset_entries(
    [bees_in_hive_entry, bees_leveling_entry, current_entry, target_entry, hive_hourly_entry, hive_current_honey_entry,
     moon_amulet_entry, extra_bonus_entry], "0"
)).pack(side="left", padx=(0, 6))
ttk.Button(hive_action_row, text="Save Profile", command=save_profile).pack(side="left", padx=(0, 6))
ttk.Button(hive_action_row, text="Load Profile", command=load_profile).pack(side="left")

# ==========================================================
# TAB: Crafting
# ==========================================================

make_tab_header(tab_craft, "Crafting Calculator", "Search • recent • cart totals • hides completed • auto-expands raw mats")

craft_body = ttk.Frame(tab_craft)
craft_body.pack(fill="both", expand=True)

craft_left = ttk.Frame(craft_body)
craft_left.pack(side="left", fill="both", padx=(0, 12))

craft_right = ttk.Frame(craft_body)
craft_right.pack(side="right", fill="both", expand=True)

craft_select = ttk.LabelFrame(craft_left, text="Target", padding=12)
craft_select.pack(fill="x", pady=(0, 12))

craft_have_card = ttk.LabelFrame(craft_left, text="What you already have", padding=12)
craft_have_card.pack(fill="both", expand=True)

craft_cart_card = ttk.LabelFrame(craft_left, text="Cart (multi-target totals)", padding=12)
craft_cart_card.pack(fill="x", pady=(12, 0))

craft_results = ttk.LabelFrame(craft_right, text="Results", padding=12)
craft_results.pack(fill="both", expand=True)

all_targets_sorted = sorted(CRAFT_TARGETS.keys(), key=lambda s: s.lower())

ttk.Label(craft_select, text="Search targets:", style="Muted.TLabel").pack(anchor="w")
craft_search_var = tk.StringVar(value="")
craft_search_entry = ttk.Entry(craft_select, textvariable=craft_search_var)
craft_search_entry.pack(fill="x", pady=(4, 10))

craft_var = tk.StringVar(value=all_targets_sorted[0])
craft_dropdown = ttk.Combobox(craft_select, textvariable=craft_var, state="readonly", values=all_targets_sorted)
craft_dropdown.pack(fill="x", pady=(0, 8))

ttk.Label(craft_select, text="Recent:", style="Muted.TLabel").pack(anchor="w")
craft_recent_var = tk.StringVar(value="")
craft_recent_dropdown = ttk.Combobox(craft_select, textvariable=craft_recent_var, state="readonly", values=[])
craft_recent_dropdown.pack(fill="x", pady=(4, 10))

craft_honey_have = labeled_entry(craft_select, "Honey you have:", "0")

hide_completed_var = tk.BooleanVar(value=False)
ttk.Checkbutton(craft_select, text="Hide completed items in list", variable=hide_completed_var, command=lambda: rebuild_craft_have()).pack(anchor="w", pady=(8, 0))

craft_have_store = {t: {} for t in CRAFT_TARGETS.keys()}

craft_have_scroll = ScrollableFrame(craft_have_card)
craft_have_scroll.pack(fill="both", expand=True)

craft_have_entries = {}

def save_current_have_to_store():
    t = craft_var.get()
    if t not in craft_have_store:
        return
    for item, ent in craft_have_entries.items():
        craft_have_store[t][item] = ent.get() or "0"

def rebuild_craft_have():
    save_current_have_to_store()
    for w in craft_have_scroll.inner.winfo_children():
        w.destroy()
    craft_have_entries.clear()

    target = craft_var.get()
    reqs = CRAFT_TARGETS[target]["Resources"]

    hdr = ttk.Frame(craft_have_scroll.inner)
    hdr.pack(fill="x", pady=(0, 8))
    ttk.Label(hdr, text="Item", style="CardTitle.TLabel").pack(side="left")
    ttk.Label(hdr, text="Required", style="CardTitle.TLabel").pack(side="left", padx=(220, 0))
    ttk.Label(hdr, text="Have", style="CardTitle.TLabel").pack(side="right")

    for item, required in reqs.items():
        have_val = craft_have_store[target].get(item, "0")
        try:
            have_num = int(float(have_val)) if str(have_val).strip() else 0
        except Exception:
            have_num = 0

        if hide_completed_var.get() and have_num >= int(required):
            continue

        row = ttk.Frame(craft_have_scroll.inner)
        row.pack(fill="x", pady=4)

        ttk.Label(row, text=item).pack(side="left")
        ttk.Label(row, text=str(required), style="Muted.TLabel").pack(side="left", padx=(10, 0))

        ent = ttk.Entry(row, width=10)
        ent.pack(side="right")
        ent.insert(0, str(have_val))
        craft_have_entries[item] = ent

craft_out_wrap = ttk.Frame(craft_results)
craft_out_wrap.pack(fill="both", expand=True)

craft_output = tk.Text(craft_out_wrap, height=24, wrap="word", borderwidth=0, state="disabled")
craft_output.pack(side="left", fill="both", expand=True)

craft_out_scroll = ttk.Scrollbar(craft_out_wrap, orient="vertical", command=craft_output.yview)
craft_out_scroll.pack(side="right", fill="y")
craft_output.configure(yscrollcommand=craft_out_scroll.set)

craft_out_btns = ttk.Frame(craft_results)
craft_out_btns.pack(fill="x", pady=(10, 0))
ttk.Button(craft_out_btns, text="Copy Results", command=lambda: copy_text_widget(craft_output)).pack(side="left", padx=(0, 6))
ttk.Button(craft_out_btns, text="Clear Results", command=lambda: clear_text_widget(craft_output)).pack(side="left")

recent_targets = []
def push_recent(target: str):
    if target in recent_targets:
        recent_targets.remove(target)
    recent_targets.insert(0, target)
    del recent_targets[8:]
    craft_recent_dropdown["values"] = recent_targets
    craft_recent_var.set(target)

def apply_craft_search(*_):
    q = (craft_search_var.get() or "").strip().lower()
    craft_dropdown["values"] = all_targets_sorted if not q else [t for t in all_targets_sorted if q in t.lower()]
craft_search_var.trace_add("write", apply_craft_search)

def calculate_craft():
    try:
        save_current_have_to_store()
        target = craft_var.get()
        push_recent(target)

        data = CRAFT_TARGETS[target]
        required_honey = parse_honey(data["Honey"])
        have_honey = parse_honey(craft_honey_have.get() or "0")
        missing_honey = max(0.0, required_honey - have_honey)

        remaining_crafted = {}
        for item, required in data["Resources"].items():
            have_txt = (craft_have_store[target].get(item, "0") or "0").strip()
            have = int(float(have_txt)) if have_txt else 0
            if have < 0:
                raise ValueError(f"{item}: cannot be negative.")
            remaining_crafted[item] = max(0, int(required) - have)

        raw_required = compute_raw_from_crafted(remaining_crafted)
        bottlenecks = sorted([(k, v) for k, v in raw_required.items() if v > 0], key=lambda x: x[1], reverse=True)[:5]

        lines = []
        lines.append(f"🎯 Target: {target}")
        lines.append(f"💰 Honey required: {format_honey(required_honey)}")
        lines.append(f"💰 Honey you have: {format_honey(have_honey)}")
        lines.append(f"💰 Honey missing: {format_honey(missing_honey)}")
        lines.append("")
        lines.append("📌 Still needed:")
        any_needed = False
        for item, amt in remaining_crafted.items():
            if amt > 0:
                lines.append(f"• {item}: {amt}")
                any_needed = True
        if not any_needed:
            lines.append("• None")

        lines.append("")
        lines.append("📦 RAW materials needed (auto):")
        any_raw = False
        for raw_item, amt in raw_required.items():
            if amt > 0:
                lines.append(f"• {raw_item}: {amt}")
                any_raw = True
        if not any_raw:
            lines.append("• None")

        if bottlenecks:
            lines.append("")
            lines.append("🔥 Biggest RAW bottlenecks:")
            for k, v in bottlenecks:
                lines.append(f"• {k}: {v}")

        craft_output.config(state="normal")
        craft_output.delete("1.0", tk.END)
        craft_output.insert(tk.END, "\n".join(lines))
        craft_output.config(state="disabled")

        rebuild_craft_have()
        set_status("Crafting calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

craft_btns = ttk.Frame(craft_select)
craft_btns.pack(fill="x", pady=(10, 0))
ttk.Button(craft_btns, text="Calculate", style="Accent.TButton", command=calculate_craft).pack(side="left", fill="x", expand=True)

def reset_current_target_have():
    t = craft_var.get()
    craft_have_store[t] = {k: "0" for k in CRAFT_TARGETS[t]["Resources"].keys()}
    rebuild_craft_have()
    set_status("Target reset to 0")

craft_btns2 = ttk.Frame(craft_select)
craft_btns2.pack(fill="x", pady=(8, 0))
ttk.Button(craft_btns2, text="Reset This Target to 0", command=reset_current_target_have).pack(side="left", padx=(0, 6))
ttk.Button(craft_btns2, text="Save Profile", command=save_profile).pack(side="left", padx=(0, 6))
ttk.Button(craft_btns2, text="Load Profile", command=load_profile).pack(side="left")

def on_recent_select(_=None):
    val = craft_recent_var.get()
    if val in CRAFT_TARGETS:
        craft_var.set(val)
        rebuild_craft_have()
        set_status("Selected recent target")
craft_recent_dropdown.bind("<<ComboboxSelected>>", on_recent_select)

def on_craft_change(_=None):
    rebuild_craft_have()
    craft_output.config(state="normal")
    craft_output.delete("1.0", tk.END)
    craft_output.insert(tk.END, "Enter what you already have, then click Calculate.\n")
    craft_output.config(state="disabled")
craft_dropdown.bind("<<ComboboxSelected>>", on_craft_change)

# Cart
craft_cart_items = []
craft_cart_list = tk.Listbox(craft_cart_card, height=6)
craft_cart_list.pack(fill="x")

cart_btn_row = ttk.Frame(craft_cart_card)
cart_btn_row.pack(fill="x", pady=(8, 0))

def refresh_cart_ui():
    craft_cart_list.delete(0, tk.END)
    for t in craft_cart_items:
        craft_cart_list.insert(tk.END, t)

def cart_add_current():
    save_current_have_to_store()
    t = craft_var.get()
    if t not in craft_cart_items:
        craft_cart_items.append(t)
        refresh_cart_ui()
        set_status("Added to cart")

def cart_remove_selected():
    sel = list(craft_cart_list.curselection())
    if not sel:
        return
    for i in reversed(sel):
        try:
            craft_cart_items.pop(i)
        except Exception:
            pass
    refresh_cart_ui()
    set_status("Removed from cart")

def cart_clear():
    craft_cart_items.clear()
    refresh_cart_ui()
    set_status("Cart cleared")

def cart_calculate_totals():
    try:
        save_current_have_to_store()
        if not craft_cart_items:
            raise ValueError("Cart is empty. Add targets first.")

        total_required_honey = 0.0
        total_remaining_crafted = defaultdict(int)

        for t in craft_cart_items:
            data = CRAFT_TARGETS[t]
            total_required_honey += parse_honey(data["Honey"])
            for item, req in data["Resources"].items():
                have_txt = craft_have_store[t].get(item, "0")
                try:
                    have = int(float(have_txt)) if str(have_txt).strip() else 0
                except Exception:
                    have = 0
                total_remaining_crafted[item] += max(0, int(req) - have)

        total_raw_map = compute_raw_from_crafted(dict(total_remaining_crafted))

        have_honey = parse_honey(craft_honey_have.get() or "0")
        total_missing_honey = max(0.0, total_required_honey - have_honey)

        bottlenecks = sorted([(k, v) for k, v in total_raw_map.items() if v > 0], key=lambda x: x[1], reverse=True)[:8]

        lines = []
        lines.append("🛒 CART TOTALS")
        lines.append(f"Targets: {', '.join(craft_cart_items)}")
        lines.append(f"💰 Total honey required: {format_honey(total_required_honey)}")
        lines.append(f"💰 Honey you have: {format_honey(have_honey)}")
        lines.append(f"💰 Honey missing: {format_honey(total_missing_honey)}")
        lines.append("")
        lines.append("📌 Still needed (combined):")
        any_need = False
        for item, amt in sorted(total_remaining_crafted.items(), key=lambda x: x[0].lower()):
            if amt > 0:
                lines.append(f"• {item}: {amt}")
                any_need = True
        if not any_need:
            lines.append("• None")

        lines.append("")
        lines.append("📦 RAW materials needed (combined):")
        any_raw = False
        for k, v in total_raw_map.items():
            if v > 0:
                lines.append(f"• {k}: {v}")
                any_raw = True
        if not any_raw:
            lines.append("• None")

        if bottlenecks:
            lines.append("")
            lines.append("🔥 Biggest RAW bottlenecks:")
            for k, v in bottlenecks:
                lines.append(f"• {k}: {v}")

        craft_output.config(state="normal")
        craft_output.delete("1.0", tk.END)
        craft_output.insert(tk.END, "\n".join(lines))
        craft_output.config(state="disabled")
        set_status("Cart calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

ttk.Button(cart_btn_row, text="Add", command=cart_add_current).pack(side="left", padx=(0, 6))
ttk.Button(cart_btn_row, text="Remove", command=cart_remove_selected).pack(side="left", padx=(0, 6))
ttk.Button(cart_btn_row, text="Clear", command=cart_clear).pack(side="left", padx=(0, 6))
ttk.Button(cart_btn_row, text="Calculate Cart", style="Accent.TButton", command=cart_calculate_totals).pack(side="right")

# ==========================================================
# TAB: Blender
# ==========================================================

make_tab_header(tab_blender, "Blender Calculator", "Slide • queue • totals • raw expansion")

bl_body = ttk.Frame(tab_blender)
bl_body.pack(fill="both", expand=True)

bl_left = ttk.Frame(bl_body)
bl_left.pack(side="left", fill="both", padx=(0, 12))

bl_right = ttk.Frame(bl_body)
bl_right.pack(side="right", fill="both", expand=True)

bl_card = ttk.LabelFrame(bl_left, text="Blender (single craft)", padding=12)
bl_card.pack(fill="x", pady=(0, 12))

bl_ing_card = ttk.LabelFrame(bl_left, text="Direct ingredients", padding=12)
bl_ing_card.pack(fill="both", expand=True)

bl_queue_card = ttk.LabelFrame(bl_left, text="Queue (multiple crafts)", padding=12)
bl_queue_card.pack(fill="x", pady=(12, 0))

bl_results = ttk.LabelFrame(bl_right, text="Results", padding=12)
bl_results.pack(fill="both", expand=True)

bl_items = sorted(BLENDER_RECIPES.keys(), key=lambda s: s.lower())
bl_index = 0

nav = ttk.Frame(bl_card)
nav.pack(fill="x")
btn_prev = ttk.Button(nav, text="◀ Prev")
btn_prev.pack(side="left")
bl_title = ttk.Label(nav, text="", style="CardTitle.TLabel")
bl_title.pack(side="left", padx=10)
btn_next = ttk.Button(nav, text="Next ▶")
btn_next.pack(side="right")

qty_row = ttk.Frame(bl_card)
qty_row.pack(fill="x", pady=(12, 0))
ttk.Label(qty_row, text="Quantity:").pack(side="left")
bl_qty = ttk.Entry(qty_row, width=10)
bl_qty.pack(side="left", padx=8)
bl_qty.insert(0, "1")

ttk.Button(bl_card, text="Calculate", style="Accent.TButton", command=lambda: calculate_blender_single()).pack(fill="x", pady=(10, 0))

blender_ing_scroll = ScrollableFrame(bl_ing_card)
blender_ing_scroll.pack(fill="both", expand=True)

bl_out_wrap = ttk.Frame(bl_results)
bl_out_wrap.pack(fill="both", expand=True)

blender_output = tk.Text(bl_out_wrap, height=24, wrap="word", borderwidth=0, state="disabled")
blender_output.pack(side="left", fill="both", expand=True)

bl_scroll = ttk.Scrollbar(bl_out_wrap, orient="vertical", command=blender_output.yview)
bl_scroll.pack(side="right", fill="y")
blender_output.configure(yscrollcommand=bl_scroll.set)

bl_out_btns = ttk.Frame(bl_results)
bl_out_btns.pack(fill="x", pady=(10, 0))
ttk.Button(bl_out_btns, text="Copy Results", command=lambda: copy_text_widget(blender_output)).pack(side="left", padx=(0, 6))
ttk.Button(bl_out_btns, text="Clear Results", command=lambda: clear_text_widget(blender_output)).pack(side="left")

def render_bl_ingredients(name: str):
    for w in blender_ing_scroll.inner.winfo_children():
        w.destroy()
    for ing, amt in BLENDER_RECIPES[name].items():
        row = ttk.Frame(blender_ing_scroll.inner)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=ing).pack(side="left")
        ttk.Label(row, text=str(amt), style="Muted.TLabel").pack(side="right")

def set_bl_slide(i: int):
    global bl_index
    bl_index = i % len(bl_items)
    name = bl_items[bl_index]
    bl_title.config(text=name)
    render_bl_ingredients(name)

def prev_bl():
    set_bl_slide(bl_index - 1)

def next_bl():
    set_bl_slide(bl_index + 1)

btn_prev.config(command=prev_bl)
btn_next.config(command=next_bl)

def calculate_blender_single():
    try:
        name = bl_items[bl_index]
        qty = int(float(bl_qty.get() or "0"))
        if qty <= 0:
            raise ValueError("Quantity must be > 0.")

        direct = {k: v * qty for k, v in BLENDER_RECIPES[name].items()}
        raw = compute_raw_from_crafted({name: qty})

        lines = []
        lines.append(f"🧪 Craft: {name}")
        lines.append(f"🔢 Quantity: {qty}")
        lines.append("")
        lines.append("📌 Direct ingredients:")
        for ing, amt in direct.items():
            lines.append(f"• {ing}: {amt}")
        lines.append("")
        lines.append("📦 RAW materials (fully expanded):")
        for ing, amt in raw.items():
            if amt > 0:
                lines.append(f"• {ing}: {amt}")

        blender_output.config(state="normal")
        blender_output.delete("1.0", tk.END)
        blender_output.insert(tk.END, "\n".join(lines))
        blender_output.config(state="disabled")
        set_status("Blender calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

# Queue
blender_queue_items = []
queue_list = tk.Listbox(bl_queue_card, height=6)
queue_list.pack(fill="x")

queue_btns = ttk.Frame(bl_queue_card)
queue_btns.pack(fill="x", pady=(8, 0))

def refresh_blender_queue_ui():
    queue_list.delete(0, tk.END)
    for x in blender_queue_items:
        queue_list.insert(tk.END, f"{x['qty']} × {x['item']}")

def queue_add_current():
    try:
        item = bl_items[bl_index]
        qty = int(float(bl_qty.get() or "0"))
        if qty <= 0:
            raise ValueError("Quantity must be > 0.")
        blender_queue_items.append({"item": item, "qty": qty})
        refresh_blender_queue_ui()
        set_status("Added to queue")
    except Exception as e:
        messagebox.showerror("Error", str(e))

def queue_remove_selected():
    sel = list(queue_list.curselection())
    if not sel:
        return
    for i in reversed(sel):
        try:
            blender_queue_items.pop(i)
        except Exception:
            pass
    refresh_blender_queue_ui()
    set_status("Removed from queue")

def queue_clear():
    blender_queue_items.clear()
    refresh_blender_queue_ui()
    set_status("Queue cleared")

def queue_calculate_totals():
    try:
        if not blender_queue_items:
            raise ValueError("Queue is empty. Add items first.")

        total_direct = defaultdict(int)
        total_raw = defaultdict(int)

        for x in blender_queue_items:
            item = x["item"]
            qty = int(x["qty"])
            for ing, amt in BLENDER_RECIPES[item].items():
                total_direct[ing] += amt * qty
            expanded = compute_raw_from_crafted({item: qty})
            for k, v in expanded.items():
                total_raw[k] += v

        bottlenecks = sorted([(k, v) for k, v in total_raw.items() if v > 0], key=lambda x: x[1], reverse=True)[:8]

        lines = []
        lines.append("📦 BLENDER QUEUE TOTALS")
        lines.append("Queue:")
        for x in blender_queue_items:
            lines.append(f"• {x['qty']} × {x['item']}")
        lines.append("")
        lines.append("📌 Direct ingredients (combined):")
        for k, v in sorted(total_direct.items(), key=lambda x: x[0].lower()):
            if v > 0:
                lines.append(f"• {k}: {v}")
        lines.append("")
        lines.append("📦 RAW materials (combined):")
        for k, v in sorted(total_raw.items(), key=lambda x: x[0].lower()):
            if v > 0:
                lines.append(f"• {k}: {v}")

        if bottlenecks:
            lines.append("")
            lines.append("🔥 Biggest RAW bottlenecks:")
            for k, v in bottlenecks:
                lines.append(f"• {k}: {v}")

        blender_output.config(state="normal")
        blender_output.delete("1.0", tk.END)
        blender_output.insert(tk.END, "\n".join(lines))
        blender_output.config(state="disabled")
        set_status("Queue calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

ttk.Button(queue_btns, text="Add", command=queue_add_current).pack(side="left", padx=(0, 6))
ttk.Button(queue_btns, text="Remove", command=queue_remove_selected).pack(side="left", padx=(0, 6))
ttk.Button(queue_btns, text="Clear", command=queue_clear).pack(side="left", padx=(0, 6))
ttk.Button(queue_btns, text="Calculate Queue", style="Accent.TButton", command=queue_calculate_totals).pack(side="right")

# ==========================================================
# TAB: Hourly Calculator (NEW, same makeover UI)

# ==========================================================
# TAB: Settings
# ==========================================================

make_tab_header(
    tab_settings,
    "Settings",
    "Customize theme, tooltips, auto-update checking, and saved inputs."
)

settings_card = card_frame(tab_settings)
settings_card.pack(fill="x", padx=18, pady=(10, 14))

# Theme
theme_var = tk.StringVar(value="dark" if dark else "light")
ttk.Label(settings_card, text="Theme").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 6))
theme_combo = ttk.Combobox(settings_card, state="readonly", width=18, textvariable=theme_var,
                           values=["dark", "light"])
theme_combo.grid(row=0, column=1, sticky="w", padx=10, pady=(10, 6))
add_tooltip(theme_combo, "Choose Dark or Light theme. Saved automatically.")

# Toggles
auto_update_var = tk.BooleanVar(value=bool(settings.get("auto_update_check", True)))
remember_var = tk.BooleanVar(value=bool(settings.get("remember_inputs", True)))
tooltips_var = tk.BooleanVar(value=bool(settings.get("enable_tooltips", True)))

auto_cb = ttk.Checkbutton(settings_card, text="Auto-check for updates on startup", variable=auto_update_var)
auto_cb.grid(row=1, column=0, columnspan=2, sticky="w", padx=10, pady=4)
add_tooltip(auto_cb, "If enabled, the app silently checks for a newer version when it starts.")

remember_cb = ttk.Checkbutton(settings_card, text="Remember my last inputs", variable=remember_var)
remember_cb.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=4)
add_tooltip(remember_cb, "Saves your last-entered values and loads them next time you open the app.")

tips_cb = ttk.Checkbutton(settings_card, text="Enable tooltips (hover help)", variable=tooltips_var)
tips_cb.grid(row=3, column=0, columnspan=2, sticky="w", padx=10, pady=(4, 10))
add_tooltip(tips_cb, "Shows small explanations when you hover over certain inputs.")

btn_row = ttk.Frame(tab_settings)
btn_row.pack(fill="x", padx=18, pady=(0, 12))

def apply_settings():
    global dark
    settings["theme"] = theme_var.get()
    settings["auto_update_check"] = bool(auto_update_var.get())
    settings["remember_inputs"] = bool(remember_var.get())
    settings["enable_tooltips"] = bool(tooltips_var.get())
    save_settings(settings)

    dark = (settings.get("theme", "dark") == "dark")
    apply_theme()
    set_status("Settings saved")

ttk.Button(btn_row, text="Save Settings", command=apply_settings).pack(side="left")
ttk.Button(btn_row, text="Check for Updates", command=lambda: check_for_updates(manual=True)).pack(side="left", padx=10)


# ==========================================================

make_tab_header(tab_hourly, "Hourly Calculator", "Enter hourly honey + current + target • shows time and progress")

hour_body = ttk.Frame(tab_hourly)
hour_body.pack(fill="both", expand=True)

hour_left = ttk.Frame(hour_body)
hour_left.pack(side="left", fill="y", padx=(0, 12))

hour_right = ttk.Frame(hour_body)
hour_right.pack(side="right", fill="both", expand=True)

hour_inputs = ttk.LabelFrame(hour_left, text="Inputs", padding=12)
hour_inputs.pack(fill="x", pady=(0, 12))

hour_actions = ttk.LabelFrame(hour_left, text="Actions", padding=12)
hour_actions.pack(fill="x")

hour_results = ttk.LabelFrame(hour_right, text="Results", padding=12)
hour_results.pack(fill="both", expand=True)

hourly_hourly_entry = labeled_entry(hour_inputs, "Honey / hour:", "0")
hourly_current_entry = labeled_entry(hour_inputs, "Current honey:", "0")
hourly_target_entry = labeled_entry(hour_inputs, "Target honey:", "0")

hour_summary = ttk.Frame(hour_results, style="Card.TFrame")
hour_summary.pack(fill="x", pady=(0, 10))

hour_sum_remaining = ttk.Label(hour_summary, text="Remaining: —", style="CardTitle.TLabel")
hour_sum_remaining.pack(anchor="w")
hour_sum_time = ttk.Label(hour_summary, text="Time: —", style="Muted.TLabel")
hour_sum_time.pack(anchor="w", pady=(4, 0))
hour_sum_progress = ttk.Label(hour_summary, text="Progress: —", style="Muted.TLabel")
hour_sum_progress.pack(anchor="w", pady=(2, 0))

hour_out_wrap = ttk.Frame(hour_results)
hour_out_wrap.pack(fill="both", expand=True)

hourly_output = tk.Text(hour_out_wrap, height=24, wrap="word", borderwidth=0, state="disabled")
hourly_output.pack(side="left", fill="both", expand=True)

hourly_scroll = ttk.Scrollbar(hour_out_wrap, orient="vertical", command=hourly_output.yview)
hourly_scroll.pack(side="right", fill="y")
hourly_output.configure(yscrollcommand=hourly_scroll.set)

hour_btns = ttk.Frame(hour_results)
hour_btns.pack(fill="x", pady=(10, 0))
ttk.Button(hour_btns, text="Copy Results", command=lambda: copy_text_widget(hourly_output)).pack(side="left", padx=(0, 6))
ttk.Button(hour_btns, text="Clear Results", command=lambda: clear_text_widget(hourly_output)).pack(side="left")

def calculate_hourly():
    try:
        hourly = parse_honey(hourly_hourly_entry.get() or "0")
        cur = parse_honey(hourly_current_entry.get() or "0")
        tgt = parse_honey(hourly_target_entry.get() or "0")

        if hourly <= 0:
            raise ValueError("Honey / hour must be > 0.")
        if tgt <= 0:
            raise ValueError("Target honey must be > 0.")
        if cur < 0:
            raise ValueError("Current honey cannot be negative.")

        remaining = max(0.0, tgt - cur)
        hours = remaining / hourly if hourly > 0 else 0.0
        days = hours / 24.0

        progress = 0.0
        if tgt > 0:
            progress = min(100.0, (cur / tgt) * 100.0)

        hour_sum_remaining.config(text=f"Remaining: {format_honey(remaining)}")
        hour_sum_time.config(text=f"Time: {hours:.2f} hours ({days:.2f} days)")
        hour_sum_progress.config(text=f"Progress: {progress:.2f}%")

        lines = []
        lines.append(f"Hourly honey: {format_honey(hourly)}/hr")
        lines.append(f"Current: {format_honey(cur)}")
        lines.append(f"Target: {format_honey(tgt)}")
        lines.append("")
        lines.append(f"Remaining: {format_honey(remaining)}")
        lines.append(f"Time: {hours:.2f} hours")
        lines.append(f"Days: {days:.2f} days")
        lines.append(f"Progress: {progress:.2f}%")

        hourly_output.config(state="normal")
        hourly_output.delete("1.0", tk.END)
        hourly_output.insert(tk.END, "\n".join(lines))
        hourly_output.config(state="disabled")
        set_status("Hourly calculated")

    except Exception as e:
        messagebox.showerror("Error", str(e))

ttk.Button(hour_actions, text="Calculate", style="Accent.TButton", command=calculate_hourly).pack(fill="x", pady=(0, 8))
ttk.Button(hour_actions, text="Reset Hourly Inputs", command=lambda: reset_entries(
    [hourly_hourly_entry, hourly_current_entry, hourly_target_entry], "0"
)).pack(fill="x")

# ==========================================================
# Keyboard shortcuts
# ==========================================================

def calculate_current_tab(event=None):
    try:
        tab = notebook.index(notebook.select())
        if tab == 0:
            calculate_hive()
        elif tab == 1:
            calculate_craft()
        elif tab == 2:
            calculate_blender_single()
        else:
            calculate_hourly()
    except Exception:
        pass

def copy_current_tab(event=None):
    tab = notebook.index(notebook.select())
    if tab == 0:
        copy_text_widget(hive_output)
    elif tab == 1:
        copy_text_widget(craft_output)
    elif tab == 2:
        copy_text_widget(blender_output)
    else:
        copy_text_widget(hourly_output)

root.bind("<Return>", calculate_current_tab)
root.bind("<Control-c>", copy_current_tab)

# ==========================================================
# Status bar
# ==========================================================

status_bar = tk.Label(root, textvariable=status_var, anchor="w", padx=10, pady=6)
status_bar.pack(side="bottom", fill="x")

# ==========================================================
# Init
# ==========================================================



def _safe_set(entry_widget, value: str):
    try:
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, value)
    except Exception:
        pass

def save_last_inputs():
    if not settings.get("remember_inputs", True):
        return
    try:
        data = {
            "hive": {
                "bees": hive_bees_entry.get(),
                "current": current_entry.get(),
                "target": target_entry.get(),
                "hourly": hive_hourly_entry.get(),
                "current_honey": hive_current_honey_entry.get(),
                "gifted_puppy": bool(gifted_puppy_var.get()),
                "reindeer": bool(reindeer_antlers_var.get()),
                "moon": moon_amulet_entry.get(),
                "extra": extra_bonus_entry.get(),
                "level_entire": bool(level_entire_var.get()),
            },
            "hourly": {
                "hourly": hourly_rate_entry.get() if 'hourly_rate_entry' in globals() else "",
                "current": hourly_current_entry.get() if 'hourly_current_entry' in globals() else "",
                "target": hourly_target_entry.get() if 'hourly_target_entry' in globals() else "",
            },
        }
        with open(LAST_INPUTS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_last_inputs():
    if not settings.get("remember_inputs", True):
        return
    try:
        if not os.path.exists(LAST_INPUTS_PATH):
            return
        with open(LAST_INPUTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        hive = (data or {}).get("hive", {})
        _safe_set(hive_bees_entry, str(hive.get("bees","")))
        _safe_set(current_entry, str(hive.get("current","")))
        _safe_set(target_entry, str(hive.get("target","")))
        _safe_set(hive_hourly_entry, str(hive.get("hourly","")))
        _safe_set(hive_current_honey_entry, str(hive.get("current_honey","")))
        gifted_puppy_var.set(bool(hive.get("gifted_puppy", False)))
        reindeer_antlers_var.set(bool(hive.get("reindeer", False)))
        _safe_set(moon_amulet_entry, str(hive.get("moon","")))
        _safe_set(extra_bonus_entry, str(hive.get("extra","")))
        level_entire_var.set(bool(hive.get("level_entire", True)))

        hr = (data or {}).get("hourly", {})
        if 'hourly_rate_entry' in globals():
            _safe_set(hourly_rate_entry, str(hr.get("hourly","")))
        if 'hourly_current_entry' in globals():
            _safe_set(hourly_current_entry, str(hr.get("current","")))
        if 'hourly_target_entry' in globals():
            _safe_set(hourly_target_entry, str(hr.get("target","")))
    except Exception:
        pass

def init():
    refresh_bonus_label()
    rebuild_craft_have()
    refresh_cart_ui()
    set_bl_slide(0)
    refresh_blender_queue_ui()
    apply_theme()
    set_status("Ready")

init()
root.mainloop()
