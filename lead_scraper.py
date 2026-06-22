"""
DMV Lead Scraper  —  LM Digital Scaling
Finds local contractors/service businesses in DC, Maryland, Virginia
that have NO website — those are your sales leads.
Uses the free OpenStreetMap Overpass API (no account or API key needed).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
import csv
import threading
import time
from geopy.geocoders import Nominatim

# ══════════════════════════════════════════════════════════════════════════════
# BRAND THEME — LM Digital Scaling (black background, gold accent)
# ══════════════════════════════════════════════════════════════════════════════
BG_BLACK   = "#0D0D0D"   # main window background (near-black)
PANEL      = "#1A1A1A"   # slightly lighter panels / inputs
ROW_EVEN   = "#161616"   # table row shade A (dark gray)
ROW_ODD    = "#212121"   # table row shade B (slightly lighter dark gray)
GOLD       = "#F5B800"   # primary accent
GOLD_HOVER = "#FFCB30"   # lighter gold for hover
GOLD_PRESS = "#D9A300"   # darker gold for pressed
WHITE      = "#FFFFFF"   # primary text
GRAY       = "#A0A0A0"   # secondary / hint text
DISABLED   = "#3A3A3A"   # disabled button fill

UI_FONT = "Helvetica Neue"  # clean modern stack; falls back to system default


# ── How to map plain-English business types to OpenStreetMap tags ──────────
# Overpass uses special tags to label businesses. This dictionary lets you
# type normal words and we translate them behind the scenes.
CATEGORY_MAP = {
    "plumber":        [("craft", "plumber"), ("shop", "plumber")],
    "electrician":    [("craft", "electrician")],
    "landscaper":     [("craft", "gardener"), ("landuse", "grass")],
    "landscaping":    [("craft", "gardener")],
    "junk removal":   [("shop", "junk_removal"), ("amenity", "waste_transfer_station")],
    "painter":        [("craft", "painter")],
    "roofer":         [("craft", "roofer"), ("craft", "roofing")],
    "cleaner":        [("craft", "cleaning"), ("shop", "dry_cleaning")],
    "cleaning":       [("craft", "cleaning")],
    "carpenter":      [("craft", "carpenter")],
    "hvac":           [("craft", "hvac"), ("shop", "hvac")],
    "contractor":     [("craft", "construction"), ("office", "contractor")],
    "handyman":       [("craft", "handyman")],
    "locksmith":      [("craft", "locksmith")],
    "moving":         [("shop", "moving")],
    "pest control":   [("craft", "pest_control"), ("shop", "pest_control")],
    "auto repair":    [("shop", "car_repair")],
    "mechanic":       [("shop", "car_repair")],
    "towing":         [("shop", "towing")],
    "tree service":   [("craft", "tree_surgeon")],
    "tree":           [("craft", "tree_surgeon")],
    "pool service":   [("craft", "pool_cleaning"), ("shop", "swimming_pool")],
    "masonry":        [("craft", "stonemason"), ("craft", "bricklayer")],
    "paving":         [("craft", "paving")],
    "drywall":        [("craft", "plasterer")],
    "flooring":       [("craft", "flooring")],
    "solar":          [("craft", "solar_panel_installer")],
    "welding":        [("craft", "welder")],
    "fence":          [("craft", "fence_installer")],
    "gutters":        [("craft", "gutter_cleaning")],
    "restaurant":     [("amenity", "restaurant")],
    "cafe":           [("amenity", "cafe")],
    "barber":         [("shop", "barber")],
    "hair salon":     [("shop", "hairdresser")],
    "nail salon":     [("shop", "nail_salon")],
    "laundry":        [("shop", "laundry")],
    "storage":        [("shop", "storage_rental")],
}

# Website-related tags that Overpass returns — we check all of these
WEBSITE_TAGS = ["website", "contact:website", "url", "contact:url", "facebook",
                "contact:facebook", "instagram", "contact:instagram"]

SOCIAL_TAGS = ["facebook", "contact:facebook", "instagram", "contact:instagram",
               "twitter", "contact:twitter", "yelp"]


# ══════════════════════════════════════════════════════════════════════════════
# OVERPASS API
# ══════════════════════════════════════════════════════════════════════════════

class OverpassError(Exception):
    """Raised when every Overpass mirror fails. Carries a human-readable reason."""
    pass


# Public Overpass API mirrors, tried in order. The browser-style headers below
# defeat the HTTP 406 "bot gate" on the main instance, so overpass-api.de stays
# first as the highest-capacity option; the rest are fallbacks if it is busy,
# rate-limited, or down. (Mirror availability changes often — June 2026 set.)
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

# Realistic browser headers. Without an Accept + User-Agent, several mirrors
# now reject the request with HTTP 406 (Not Acceptable) as anti-bot filtering.
OVERPASS_HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
}

OVERPASS_TIMEOUT = 60  # seconds per mirror; a timeout moves on to the next mirror


def geocode_area(area_name):
    """
    Convert a place name like 'Rockville, MD' into a bounding box
    (a rectangle on the map) that Overpass can search inside.
    Returns (south, west, north, east) coordinates or None if not found.
    """
    geolocator = Nominatim(user_agent="dmv_lead_scraper_v1")
    try:
        location = geolocator.geocode(
            area_name + ", DMV area USA",
            exactly_one=True,
            timeout=10
        )
        if not location:
            # Try without the DMV hint
            location = geolocator.geocode(area_name + ", USA", exactly_one=True, timeout=10)
        if not location:
            return None
        # Build a bounding box ~15 miles around the center point
        lat, lon = location.latitude, location.longitude
        delta = 0.22  # roughly 15 miles in degrees
        return (lat - delta, lon - delta, lat + delta, lon + delta)
    except Exception:
        return None


def build_overpass_query(tags, bbox):
    """
    Build the Overpass QL query string.
    bbox = (south, west, north, east)
    tags = list of (key, value) tuples like [("craft", "plumber")]
    """
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    parts = []
    for key, val in tags:
        parts.append(f'node["{key}"="{val}"]({bbox_str});')
        parts.append(f'way["{key}"="{val}"]({bbox_str});')
        parts.append(f'relation["{key}"="{val}"]({bbox_str});')
    query = "[out:json][timeout:60];\n(\n"
    query += "\n".join(parts)
    query += "\n);\nout center tags;"
    return query


def run_overpass_query(query):
    """
    Send the query to a free Overpass API mirror and return the parsed JSON.
    Tries each mirror in OVERPASS_SERVERS in turn. If a mirror times out,
    refuses (HTTP 406/429/etc.), or can't be reached, we record WHY and move
    on to the next one. If every mirror fails, raise OverpassError with the
    collected, human-readable reasons so the popup shows the real cause.
    """
    problems = []
    for server in OVERPASS_SERVERS:
        host = server.split("/")[2]
        try:
            resp = requests.post(
                server,
                data={"data": query},
                headers=OVERPASS_HEADERS,
                timeout=OVERPASS_TIMEOUT,
            )
        except requests.exceptions.Timeout:
            problems.append(f"• {host}: timed out after {OVERPASS_TIMEOUT}s")
            continue
        except requests.exceptions.ConnectionError:
            problems.append(f"• {host}: could not connect (network or DNS problem)")
            continue
        except requests.exceptions.RequestException as ex:
            problems.append(f"• {host}: request failed ({type(ex).__name__})")
            continue

        # Got a response — interpret the status code.
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                problems.append(f"• {host}: HTTP 200 but the reply was not valid JSON")
                continue
        elif resp.status_code == 406:
            problems.append(f"• {host}: HTTP 406 Not Acceptable (rejected as a bot)")
        elif resp.status_code == 429:
            problems.append(f"• {host}: HTTP 429 Too Many Requests (rate-limited)")
        elif resp.status_code in (502, 503, 504):
            problems.append(f"• {host}: HTTP {resp.status_code} (server busy/overloaded)")
        else:
            problems.append(f"• {host}: HTTP {resp.status_code}")

    # Every mirror failed.
    raise OverpassError(
        "Could not get data from any Overpass mirror.\n\nWhat each one said:\n"
        + "\n".join(problems)
        + "\n\nThis is usually temporary — the free public servers get busy. "
          "Wait a minute and try the search again."
    )


def has_website(tags):
    """Return True if any website-like tag exists and is non-empty."""
    for tag in ["website", "contact:website", "url", "contact:url"]:
        val = tags.get(tag, "").strip()
        if val and val not in ("no", "none", "unknown"):
            return True
    return False


def get_social(tags):
    """Return a short string listing any social media found."""
    found = []
    mapping = {
        "facebook": "Facebook", "contact:facebook": "Facebook",
        "instagram": "Instagram", "contact:instagram": "Instagram",
        "twitter": "Twitter", "contact:twitter": "Twitter",
        "yelp": "Yelp",
    }
    seen = set()
    for tag, label in mapping.items():
        if label not in seen and tags.get(tag, "").strip():
            found.append(label)
            seen.add(label)
    return ", ".join(found) if found else "None"


def extract_address(tags):
    """Build a readable address from OSM address tags."""
    parts = []
    housenumber = tags.get("addr:housenumber", "")
    street      = tags.get("addr:street", "")
    city        = tags.get("addr:city", "")
    state       = tags.get("addr:state", "")
    postcode    = tags.get("addr:postcode", "")
    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif street:
        parts.append(street)
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    if postcode:
        parts.append(postcode)
    return ", ".join(parts) if parts else "No address listed"


def scrape_leads(category_input, area_input, callback):
    """
    Main logic: geocode the area, query Overpass, filter results.
    Runs in a background thread so the UI stays responsive.
    callback(results, error_message) is called when done.
    results = list of dicts with keys: name, phone, address, category, social
    """
    # Step 1: figure out which OSM tags to search
    key = category_input.strip().lower()
    tags = CATEGORY_MAP.get(key)
    if not tags:
        # Generic fallback: search by name keyword isn't possible in Overpass easily,
        # so try shop + amenity + craft with a name~ filter
        tags = [("craft", key), ("shop", key), ("amenity", key)]

    # Step 2: geocode the area
    bbox = geocode_area(area_input.strip())
    if not bbox:
        callback([], f"Could not find the location: '{area_input}'\n\nTry being more specific, e.g. 'Rockville, MD' or 'Arlington, VA'.")
        return

    # Step 3: build and run the query
    query = build_overpass_query(tags, bbox)
    try:
        data = run_overpass_query(query)
    except OverpassError as ex:
        callback([], str(ex))
        return

    # Step 4: filter — keep only those WITHOUT a website
    leads = []
    seen_ids = set()
    for element in data.get("elements", []):
        elem_id = element.get("id")
        if elem_id in seen_ids:
            continue
        seen_ids.add(elem_id)

        tags_osm = element.get("tags", {})
        name = tags_osm.get("name", "").strip()
        if not name:
            continue  # skip unnamed entries

        if has_website(tags_osm):
            continue  # already has a website — not a lead

        phone   = tags_osm.get("phone", tags_osm.get("contact:phone", tags_osm.get("telephone", "No phone listed")))
        address = extract_address(tags_osm)
        social  = get_social(tags_osm)

        # Determine display category
        cat = (tags_osm.get("craft") or tags_osm.get("shop") or
               tags_osm.get("amenity") or category_input).replace("_", " ").title()

        leads.append({
            "name":     name,
            "phone":    phone,
            "address":  address,
            "category": cat,
            "social":   social,
        })

    callback(leads, None)


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class FlatButton(tk.Label):
    """
    A flat, fully color-controllable button built on tk.Label.

    Why not tk.Button? On macOS the native button ignores custom background
    colors, so a 'gold' tk.Button would still render as a default gray pill.
    A Label honors bg/fg on every platform, giving us the exact brand look
    with hover + pressed states.

    primary=True  -> gold fill, black text
    primary=False -> transparent (black) fill, gold text, gold outline
    """
    def __init__(self, parent, text, command, primary=True):
        self.command = command
        self.primary = primary
        self._enabled = True

        if primary:
            self._fill, self._text_col, self._hover = GOLD, BG_BLACK, GOLD_HOVER
        else:
            self._fill, self._text_col, self._hover = BG_BLACK, GOLD, PANEL

        super().__init__(
            parent, text=text, bg=self._fill, fg=self._text_col,
            font=(UI_FONT, 12, "bold"), padx=20, pady=9, cursor="hand2",
        )
        if not primary:
            # Gold outline for the secondary button (renders on macOS too).
            self.config(highlightbackground=GOLD, highlightcolor=GOLD,
                        highlightthickness=2, bd=0)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _e):
        if self._enabled:
            self.config(bg=self._hover)

    def _on_leave(self, _e):
        if self._enabled:
            self.config(bg=self._fill)

    def _on_press(self, _e):
        if self._enabled:
            self.config(bg=GOLD_PRESS if self.primary else "#2E2E2E")

    def _on_release(self, _e):
        if self._enabled:
            self.config(bg=self._hover)
            if callable(self.command):
                self.command()

    def set_text(self, text):
        self.config(text=text)

    def set_enabled(self, enabled):
        self._enabled = enabled
        if enabled:
            self.config(bg=self._fill, fg=self._text_col, cursor="hand2")
            if not self.primary:
                self.config(highlightbackground=GOLD)
        else:
            self.config(bg=DISABLED, fg=GRAY, cursor="arrow")
            if not self.primary:
                self.config(highlightbackground=DISABLED)


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

class LeadScraperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LM Digital Scaling — Lead Scraper")
        self.geometry("1080x700")
        self.minsize(900, 560)
        self.configure(bg=BG_BLACK)

        self.leads = []  # holds the current results
        self._init_styles()
        self._build_ui()

    # ── ttk styling (Treeview, Entry, Scrollbars) ─────────────────────────────
    def _init_styles(self):
        style = ttk.Style()
        # 'clam' lets us fully control colors on every OS (macOS 'aqua' won't).
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        # Dark text-input fields with a gold cursor.
        style.configure(
            "Dark.TEntry",
            fieldbackground=PANEL, background=PANEL, foreground=WHITE,
            insertcolor=GOLD, bordercolor="#333333", lightcolor="#333333",
            darkcolor="#333333", borderwidth=1, padding=6,
        )
        style.map("Dark.TEntry",
                  bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)])

        # Results table: dark rows, white text, gold headings.
        style.configure(
            "Lead.Treeview",
            background=ROW_EVEN, fieldbackground=ROW_EVEN, foreground=WHITE,
            rowheight=30, borderwidth=0, font=(UI_FONT, 11),
        )
        style.configure(
            "Lead.Treeview.Heading",
            background=GOLD, foreground=BG_BLACK, relief="flat",
            font=(UI_FONT, 11, "bold"), padding=(8, 8),
        )
        style.map("Lead.Treeview.Heading",
                  background=[("active", GOLD_HOVER)])
        # Selected row = gold highlight with black text.
        style.map("Lead.Treeview",
                  background=[("selected", GOLD)],
                  foreground=[("selected", BG_BLACK)])

        # Dark scrollbars.
        for orient in ("Vertical", "Horizontal"):
            style.configure(
                f"Dark.{orient}.TScrollbar",
                background=PANEL, troughcolor=BG_BLACK, bordercolor=BG_BLACK,
                arrowcolor=GOLD, relief="flat",
            )
            style.map(f"Dark.{orient}.TScrollbar",
                      background=[("active", "#2E2E2E")])

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG_BLACK, pady=18, padx=24)
        header.pack(fill="x")

        # Logo placeholder. To use a real logo later, drop a PNG next to this
        # file and replace this block with:
        #     self.logo_img = tk.PhotoImage(file="lm_logo.png")
        #     tk.Label(header, image=self.logo_img, bg=BG_BLACK).pack(side="left")
        logo_box = tk.Frame(header, bg=PANEL, width=62, height=62,
                            highlightbackground=GOLD, highlightthickness=2)
        logo_box.pack(side="left", padx=(0, 18))
        logo_box.pack_propagate(False)
        tk.Label(logo_box, text="LM", font=(UI_FONT, 20, "bold"),
                 bg=PANEL, fg=GOLD).pack(expand=True)

        title_box = tk.Frame(header, bg=BG_BLACK)
        title_box.pack(side="left", anchor="w")
        tk.Label(title_box, text="LM Digital Scaling",
                 font=(UI_FONT, 22, "bold"), fg=WHITE, bg=BG_BLACK
                 ).pack(anchor="w")
        tk.Label(title_box, text="LEAD SCRAPER",
                 font=(UI_FONT, 12, "bold"), fg=GOLD, bg=BG_BLACK
                 ).pack(anchor="w")

        # Thin gold divider under the header.
        tk.Frame(self, bg=GOLD, height=2).pack(fill="x")

        # ── Search bar ────────────────────────────────────────────────────────
        search_frame = tk.Frame(self, bg=BG_BLACK, padx=24, pady=18)
        search_frame.pack(fill="x")

        # Category input
        tk.Label(search_frame, text="Business Type", font=(UI_FONT, 10, "bold"),
                 bg=BG_BLACK, fg=GRAY).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.category_var = tk.StringVar()
        cat_entry = ttk.Entry(search_frame, textvariable=self.category_var, width=22,
                              font=(UI_FONT, 12), style="Dark.TEntry")
        cat_entry.grid(row=1, column=0, padx=(0, 18), sticky="w")
        cat_entry.insert(0, "plumber")

        # Area input
        tk.Label(search_frame, text="City / Area", font=(UI_FONT, 10, "bold"),
                 bg=BG_BLACK, fg=GRAY).grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.area_var = tk.StringVar()
        area_entry = ttk.Entry(search_frame, textvariable=self.area_var, width=26,
                               font=(UI_FONT, 12), style="Dark.TEntry")
        area_entry.grid(row=1, column=1, padx=(0, 18), sticky="w")
        area_entry.insert(0, "Rockville, MD")

        # Search button (primary — gold)
        self.search_btn = FlatButton(search_frame, "Search", self._start_search,
                                     primary=True)
        self.search_btn.grid(row=1, column=2, padx=(0, 12))

        # Export button (secondary — gold outline)
        self.export_btn = FlatButton(search_frame, "Export to CSV", self._export_csv,
                                     primary=False)
        self.export_btn.grid(row=1, column=3)
        self.export_btn.set_enabled(False)

        # Hint line
        tk.Label(search_frame,
                 text='Examples — Type:  junk removal · landscaper · electrician · roofer    |    '
                      'Area:  Silver Spring, MD · Alexandria, VA · NW Washington DC',
                 font=(UI_FONT, 9), fg=GRAY, bg=BG_BLACK
                 ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(12, 0))

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready. Enter a business type and area, then click Search.")
        status_bar = tk.Label(self, textvariable=self.status_var, font=(UI_FONT, 10),
                              bg=PANEL, fg=GRAY, anchor="w", padx=24, pady=8)
        status_bar.pack(fill="x")

        # ── Results table ─────────────────────────────────────────────────────
        table_frame = tk.Frame(self, bg=BG_BLACK, padx=24, pady=12)
        table_frame.pack(fill="both", expand=True)

        columns = ("name", "phone", "address", "category", "social")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 selectmode="browse", style="Lead.Treeview")

        col_cfg = [
            ("name",     "Business Name",  240),
            ("phone",    "Phone",          150),
            ("address",  "Address",        320),
            ("category", "Category",       120),
            ("social",   "Social Media",   150),
        ]
        for col_id, heading, width in col_cfg:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, minwidth=80)

        # Scrollbars
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview,
                            style="Dark.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview,
                            style="Dark.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Alternating dark row shades (NOT white) for readability.
        self.tree.tag_configure("odd",  background=ROW_ODD,  foreground=WHITE)
        self.tree.tag_configure("even", background=ROW_EVEN, foreground=WHITE)

        # ── Footer count label ────────────────────────────────────────────────
        self.count_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.count_var, font=(UI_FONT, 11, "bold"),
                 bg=BG_BLACK, fg=GOLD, anchor="w", padx=24, pady=10
                 ).pack(fill="x")

        # Allow pressing Enter to search
        self.bind("<Return>", lambda e: self._start_search())

    # ── Search logic ──────────────────────────────────────────────────────────

    def _start_search(self):
        if not self.search_btn._enabled:
            return  # already searching
        category = self.category_var.get().strip()
        area     = self.area_var.get().strip()

        if not category or not area:
            messagebox.showwarning("Missing Info",
                                   "Please enter both a business type and a city/area.")
            return

        # Clear old results
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.leads = []
        self.export_btn.set_enabled(False)
        self.count_var.set("")
        self.search_btn.set_enabled(False)
        self.search_btn.set_text("Searching…")
        self.status_var.set(f"Searching for '{category}' businesses in '{area}' — this may take 10–30 seconds…")
        self.update_idletasks()

        # Run in background thread so the window doesn't freeze
        thread = threading.Thread(
            target=scrape_leads,
            args=(category, area, self._on_results),
            daemon=True
        )
        thread.start()

    def _on_results(self, leads, error):
        # This is called from the background thread — schedule UI update on main thread
        self.after(0, lambda: self._display_results(leads, error))

    def _display_results(self, leads, error):
        self.search_btn.set_enabled(True)
        self.search_btn.set_text("Search")

        if error:
            self.status_var.set("Error — see message.")
            messagebox.showerror("Search Error", error)
            return

        self.leads = leads

        if not leads:
            self.status_var.set("Search complete. No leads found — try a different category or broader area.")
            self.count_var.set("0 leads found.")
            return

        for i, lead in enumerate(leads):
            tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", values=(
                lead["name"],
                lead["phone"],
                lead["address"],
                lead["category"],
                lead["social"],
            ), tags=(tag,))

        self.export_btn.set_enabled(True)
        self.status_var.set("Done! These businesses have NO website — they're your leads.")
        self.count_var.set(f"{len(leads)} lead{'s' if len(leads) != 1 else ''} found — businesses with NO website.")

    # ── CSV Export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self.leads:
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save leads as CSV",
            initialfile="dmv_leads.csv"
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["name", "phone", "address", "category", "social"])
                writer.writeheader()
                writer.writerows(self.leads)
            messagebox.showinfo("Saved!", f"Your leads have been saved to:\n{filepath}\n\nYou can now open it in Excel.")
        except Exception as ex:
            messagebox.showerror("Save Error", f"Could not save file:\n{ex}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = LeadScraperApp()
    app.mainloop()
