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
import webbrowser
import urllib.parse
from geopy.geocoders import Nominatim

# ══════════════════════════════════════════════════════════════════════════════
# BRAND THEME — LM Digital Scaling (black background, gold accent)
# ══════════════════════════════════════════════════════════════════════════════
BG_BLACK    = "#0D0D0D"
PANEL       = "#1A1A1A"
ROW_EVEN    = "#161616"
ROW_ODD     = "#212121"
GOLD        = "#F5B800"
GOLD_HOVER  = "#FFCB30"
GOLD_PRESS  = "#D9A300"
WHITE       = "#FFFFFF"
GRAY        = "#A0A0A0"
DISABLED    = "#3A3A3A"
GREEN_DARK  = "#1A3A1A"   # "strong lead" row tint
AMBER_DARK  = "#2E2200"   # "sparse data" row tint

UI_FONT = "Helvetica Neue"


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY → OSM TAG MAP
# ══════════════════════════════════════════════════════════════════════════════
# Only craft/shop/office/amenity keys that represent actual businesses.
# "landuse", "leisure", "natural" keys were here before — removed because they
# pull in parks, lawns, and geographic features rather than real companies.
CATEGORY_MAP = {
    "plumber":        [("craft", "plumber"), ("shop", "plumber")],
    "electrician":    [("craft", "electrician")],
    "landscaper":     [("craft", "gardener"), ("craft", "landscape")],
    "landscaping":    [("craft", "gardener"), ("craft", "landscape")],
    "junk removal":   [("shop", "junk_removal")],
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

# OSM keys that flag a geographic/recreational feature — not a business.
# Any element carrying one of these will be excluded regardless of its name.
JUNK_KEYS = {
    "leisure", "natural", "golf", "sport", "landuse",
    "boundary", "place", "highway", "waterway", "railway",
    "aeroway", "historic", "tourism",
}

# Subset of amenity values that are clearly NOT a sellable business
JUNK_AMENITY_VALUES = {
    "park", "bench", "waste_basket", "recycling", "parking",
    "parking_space", "bicycle_parking", "shelter", "toilets",
    "drinking_water", "fountain", "playground", "bbq",
    "waste_transfer_station",   # too generic — industrial, not contractor
    "social_facility", "place_of_worship", "school", "college",
    "university", "hospital", "clinic", "library", "police",
    "fire_station", "post_office", "bus_station", "ferry_terminal",
}


# ══════════════════════════════════════════════════════════════════════════════
# OVERPASS API
# ══════════════════════════════════════════════════════════════════════════════

class OverpassError(Exception):
    pass


OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]

OVERPASS_HEADERS = {
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
}

OVERPASS_TIMEOUT = 60


def geocode_area(area_name):
    geolocator = Nominatim(user_agent="dmv_lead_scraper_v2")
    try:
        loc = geolocator.geocode(area_name + ", DMV area USA",
                                 exactly_one=True, timeout=10)
        if not loc:
            loc = geolocator.geocode(area_name + ", USA",
                                     exactly_one=True, timeout=10)
        if not loc:
            return None
        lat, lon = loc.latitude, loc.longitude
        delta = 0.22  # ~15 miles
        return (lat - delta, lon - delta, lat + delta, lon + delta)
    except Exception:
        return None


def build_overpass_query(tags, bbox):
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    parts = []
    for key, val in tags:
        parts.append(f'node["{key}"="{val}"]({bbox_str});')
        parts.append(f'way["{key}"="{val}"]({bbox_str});')
        parts.append(f'relation["{key}"="{val}"]({bbox_str});')
    return "[out:json][timeout:60];\n(\n" + "\n".join(parts) + "\n);\nout center tags;"


def run_overpass_query(query):
    problems = []
    for server in OVERPASS_SERVERS:
        host = server.split("/")[2]
        try:
            resp = requests.post(server, data={"data": query},
                                 headers=OVERPASS_HEADERS, timeout=OVERPASS_TIMEOUT)
        except requests.exceptions.Timeout:
            problems.append(f"• {host}: timed out after {OVERPASS_TIMEOUT}s")
            continue
        except requests.exceptions.ConnectionError:
            problems.append(f"• {host}: could not connect (network or DNS problem)")
            continue
        except requests.exceptions.RequestException as ex:
            problems.append(f"• {host}: request failed ({type(ex).__name__})")
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                problems.append(f"• {host}: HTTP 200 but reply was not valid JSON")
                continue
        elif resp.status_code == 406:
            problems.append(f"• {host}: HTTP 406 Not Acceptable (rejected as a bot)")
        elif resp.status_code == 429:
            problems.append(f"• {host}: HTTP 429 Too Many Requests (rate-limited)")
        elif resp.status_code in (502, 503, 504):
            problems.append(f"• {host}: HTTP {resp.status_code} (server busy/overloaded)")
        else:
            problems.append(f"• {host}: HTTP {resp.status_code}")

    raise OverpassError(
        "Could not get data from any Overpass mirror.\n\nWhat each one said:\n"
        + "\n".join(problems)
        + "\n\nThis is usually temporary — wait a minute and try again."
    )


# ══════════════════════════════════════════════════════════════════════════════
# DATA EXTRACTION & QUALITY SCORING
# ══════════════════════════════════════════════════════════════════════════════

def is_real_business(tags):
    """
    Return True only if the OSM element looks like an actual business, not a
    geographic/recreational feature.

    Rules (applied in order):
    1. Any of the JUNK_KEYS present → discard (park, leisure, natural, etc.)
    2. amenity present but its value is in JUNK_AMENITY_VALUES → discard
    3. Must have at least one "business signal":
       - a phone/email/address field, OR
       - tagged under craft/shop/office (these are business-specific keys)
       A result with name only and zero signals is probably a landmark.
    """
    # Rule 1 — junk top-level keys
    for jk in JUNK_KEYS:
        if jk in tags:
            return False

    # Rule 2 — junk amenity values
    amenity = tags.get("amenity", "")
    if amenity and amenity in JUNK_AMENITY_VALUES:
        return False

    # Rule 3 — need at least one business signal
    business_keys = {"craft", "shop", "office"}
    has_business_key = any(k in tags for k in business_keys)

    contact_fields = [
        "phone", "contact:phone", "mobile", "contact:mobile", "telephone",
        "email", "contact:email",
        "addr:housenumber", "addr:street", "addr:city",
        "facebook", "contact:facebook", "instagram", "contact:instagram",
        "opening_hours",
    ]
    has_contact = any(tags.get(f, "").strip() for f in contact_fields)

    return has_business_key or has_contact


def has_website(tags):
    for tag in ["website", "contact:website", "url", "contact:url"]:
        val = tags.get(tag, "").strip()
        if val and val.lower() not in ("no", "none", "unknown"):
            return True
    return False


def get_phone(tags):
    for field in ["phone", "contact:phone", "mobile", "contact:mobile", "telephone"]:
        v = tags.get(field, "").strip()
        if v:
            return v
    return ""


def get_email(tags):
    for field in ["email", "contact:email"]:
        v = tags.get(field, "").strip()
        if v:
            return v
    return ""


def get_social(tags):
    mapping = {
        "facebook": "FB", "contact:facebook": "FB",
        "instagram": "IG", "contact:instagram": "IG",
        "twitter": "TW", "contact:twitter": "TW",
        "yelp": "Yelp",
    }
    seen, found = set(), []
    for tag, label in mapping.items():
        if label not in seen and tags.get(tag, "").strip():
            found.append(label)
            seen.add(label)
    return ", ".join(found) if found else ""


def get_opening_hours(tags):
    return tags.get("opening_hours", "").strip()


def extract_address(tags):
    parts = []
    num    = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    city   = tags.get("addr:city", "")
    state  = tags.get("addr:state", "")
    post   = tags.get("addr:postcode", "")
    if num and street:
        parts.append(f"{num} {street}")
    elif street:
        parts.append(street)
    if city:   parts.append(city)
    if state:  parts.append(state)
    if post:   parts.append(post)
    return ", ".join(parts)


def lead_quality(tags, social):
    """
    Return a (score, label, tag_key) tuple used for sorting and display.

    score 3 — Strong lead  : has phone or address + social presence
    score 2 — Good lead    : has phone or address but no social
    score 1 — Verify first : social only (no phone/address)
    score 0 — Sparse data  : nothing but a name — still shown, lowest priority
    """
    phone   = get_phone(tags)
    address = extract_address(tags)
    has_ph  = bool(phone)
    has_adr = bool(address)
    has_soc = bool(social)

    if (has_ph or has_adr) and has_soc:
        return (3, "Strong lead — has social, no site", "strong")
    if has_ph or has_adr:
        return (2, "Good lead", "good")
    if has_soc:
        return (1, "Has social — verify manually", "verify")
    return (0, "Sparse data — verify manually", "sparse")


def scrape_leads(category_input, area_input, callback):
    key  = category_input.strip().lower()
    tags = CATEGORY_MAP.get(key) or [("craft", key), ("shop", key), ("amenity", key)]

    bbox = geocode_area(area_input.strip())
    if not bbox:
        callback([], f"Could not find the location: '{area_input}'\n\n"
                     "Try being more specific, e.g. 'Rockville, MD' or 'Arlington, VA'.")
        return

    query = build_overpass_query(tags, bbox)
    try:
        data = run_overpass_query(query)
    except OverpassError as ex:
        callback([], str(ex))
        return

    leads = []
    seen_ids = set()
    for element in data.get("elements", []):
        elem_id = element.get("id")
        if elem_id in seen_ids:
            continue
        seen_ids.add(elem_id)

        t = element.get("tags", {})
        name = t.get("name", "").strip()
        if not name:
            continue
        if has_website(t):
            continue
        if not is_real_business(t):
            continue

        phone   = get_phone(t)
        email   = get_email(t)
        address = extract_address(t)
        social  = get_social(t)
        hours   = get_opening_hours(t)
        score, quality_label, qtag = lead_quality(t, social)

        cat = (t.get("craft") or t.get("shop") or t.get("office") or
               t.get("amenity") or category_input).replace("_", " ").title()

        # city for browser searches
        city_hint = t.get("addr:city", "") or area_input.strip()

        leads.append({
            "name":     name,
            "phone":    phone    or "—",
            "email":    email    or "—",
            "address":  address  or "—",
            "hours":    hours    or "—",
            "category": cat,
            "social":   social   or "—",
            "quality":  quality_label,
            "qtag":     qtag,
            "score":    score,
            "city_hint": city_hint,
        })

    # Sort: best leads first
    leads.sort(key=lambda x: x["score"], reverse=True)
    callback(leads, None)


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class FlatButton(tk.Label):
    """
    A flat, fully color-controllable button built on tk.Label.
    tk.Button on macOS ignores custom bg, so we use a Label instead.
    primary=True  -> gold fill, black text
    primary=False -> black fill, gold text + gold border
    """
    def __init__(self, parent, text, command, primary=True):
        self.command  = command
        self.primary  = primary
        self._enabled = True
        self._fill    = GOLD    if primary else BG_BLACK
        self._fg      = BG_BLACK if primary else GOLD
        self._hover   = GOLD_HOVER if primary else PANEL

        super().__init__(parent, text=text, bg=self._fill, fg=self._fg,
                         font=(UI_FONT, 12, "bold"), padx=20, pady=9,
                         cursor="hand2")
        if not primary:
            self.config(highlightbackground=GOLD, highlightcolor=GOLD,
                        highlightthickness=2, bd=0)

        self.bind("<Enter>",         self._on_enter)
        self.bind("<Leave>",         self._on_leave)
        self.bind("<Button-1>",      self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _e):
        if self._enabled: self.config(bg=self._hover)
    def _on_leave(self, _e):
        if self._enabled: self.config(bg=self._fill)
    def _on_press(self, _e):
        if self._enabled: self.config(bg=GOLD_PRESS if self.primary else "#2E2E2E")
    def _on_release(self, _e):
        if self._enabled:
            self.config(bg=self._hover)
            if callable(self.command): self.command()

    def set_text(self, t):    self.config(text=t)
    def set_enabled(self, on):
        self._enabled = on
        if on:
            self.config(bg=self._fill, fg=self._fg, cursor="hand2")
            if not self.primary: self.config(highlightbackground=GOLD)
        else:
            self.config(bg=DISABLED, fg=GRAY, cursor="arrow")
            if not self.primary: self.config(highlightbackground=DISABLED)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

# Columns shown in the table and exported to CSV
COLUMNS = [
    ("name",    "Business Name",   200),
    ("phone",   "Phone",           130),
    ("email",   "Email",           170),
    ("address", "Address",         250),
    ("hours",   "Hours",           110),
    ("social",  "Social",          100),
    ("quality", "Lead Quality",    200),
]
CSV_FIELDS = ["name", "phone", "email", "address", "hours",
              "category", "social", "quality", "city_hint"]


class LeadScraperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LM Digital Scaling — Lead Scraper")
        self.geometry("1200x740")
        self.minsize(960, 580)
        self.configure(bg=BG_BLACK)
        self.leads = []
        self._init_styles()
        self._build_ui()

    # ── ttk styling ───────────────────────────────────────────────────────────
    def _init_styles(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        s.configure("Dark.TEntry",
                    fieldbackground=PANEL, background=PANEL, foreground=WHITE,
                    insertcolor=GOLD, bordercolor="#333", lightcolor="#333",
                    darkcolor="#333", borderwidth=1, padding=6)
        s.map("Dark.TEntry",
              bordercolor=[("focus", GOLD)], lightcolor=[("focus", GOLD)])

        s.configure("Lead.Treeview",
                    background=ROW_EVEN, fieldbackground=ROW_EVEN,
                    foreground=WHITE, rowheight=28, borderwidth=0,
                    font=(UI_FONT, 11))
        s.configure("Lead.Treeview.Heading",
                    background=GOLD, foreground=BG_BLACK, relief="flat",
                    font=(UI_FONT, 11, "bold"), padding=(6, 7))
        s.map("Lead.Treeview.Heading",
              background=[("active", GOLD_HOVER)])
        s.map("Lead.Treeview",
              background=[("selected", GOLD)],
              foreground=[("selected", BG_BLACK)])

        for orient in ("Vertical", "Horizontal"):
            s.configure(f"Dark.{orient}.TScrollbar",
                        background=PANEL, troughcolor=BG_BLACK,
                        bordercolor=BG_BLACK, arrowcolor=GOLD, relief="flat")
            s.map(f"Dark.{orient}.TScrollbar",
                  background=[("active", "#2E2E2E")])

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG_BLACK, pady=16, padx=24)
        hdr.pack(fill="x")

        logo_box = tk.Frame(hdr, bg=PANEL, width=60, height=60,
                            highlightbackground=GOLD, highlightthickness=2)
        logo_box.pack(side="left", padx=(0, 16))
        logo_box.pack_propagate(False)
        tk.Label(logo_box, text="LM", font=(UI_FONT, 18, "bold"),
                 bg=PANEL, fg=GOLD).pack(expand=True)

        titles = tk.Frame(hdr, bg=BG_BLACK)
        titles.pack(side="left", anchor="w")
        tk.Label(titles, text="LM Digital Scaling",
                 font=(UI_FONT, 22, "bold"), fg=WHITE, bg=BG_BLACK).pack(anchor="w")
        tk.Label(titles, text="LEAD SCRAPER",
                 font=(UI_FONT, 11, "bold"), fg=GOLD, bg=BG_BLACK).pack(anchor="w")

        tk.Frame(self, bg=GOLD, height=2).pack(fill="x")

        # Search bar
        sf = tk.Frame(self, bg=BG_BLACK, padx=24, pady=16)
        sf.pack(fill="x")

        tk.Label(sf, text="Business Type", font=(UI_FONT, 10, "bold"),
                 bg=BG_BLACK, fg=GRAY).grid(row=0, column=0, sticky="w")
        self.category_var = tk.StringVar()
        ce = ttk.Entry(sf, textvariable=self.category_var, width=20,
                       font=(UI_FONT, 12), style="Dark.TEntry")
        ce.grid(row=1, column=0, padx=(0, 16), sticky="w")
        ce.insert(0, "landscaper")

        tk.Label(sf, text="City / Area", font=(UI_FONT, 10, "bold"),
                 bg=BG_BLACK, fg=GRAY).grid(row=0, column=1, sticky="w")
        self.area_var = tk.StringVar()
        ae = ttk.Entry(sf, textvariable=self.area_var, width=24,
                       font=(UI_FONT, 12), style="Dark.TEntry")
        ae.grid(row=1, column=1, padx=(0, 16), sticky="w")
        ae.insert(0, "Rockville, MD")

        self.search_btn = FlatButton(sf, "Search", self._start_search, primary=True)
        self.search_btn.grid(row=1, column=2, padx=(0, 12))

        self.export_btn = FlatButton(sf, "Export to CSV", self._export_csv, primary=False)
        self.export_btn.grid(row=1, column=3)
        self.export_btn.set_enabled(False)

        tk.Label(sf,
                 text="Examples — Type:  landscaper · junk removal · plumber · roofer · electrician"
                      "    |    Area:  Rockville, MD · Silver Spring, MD · Alexandria, VA",
                 font=(UI_FONT, 9), fg=GRAY, bg=BG_BLACK
                 ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(10, 0))
        tk.Label(sf,
                 text="Tip: Double-click any row to Google the business · Right-click for Google Maps",
                 font=(UI_FONT, 9, "italic"), fg=GOLD, bg=BG_BLACK
                 ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(2, 0))

        # Status bar
        self.status_var = tk.StringVar(
            value="Ready. Enter a business type and area, then click Search.")
        tk.Label(self, textvariable=self.status_var, font=(UI_FONT, 10),
                 bg=PANEL, fg=GRAY, anchor="w", padx=24, pady=7).pack(fill="x")

        # Table
        tf = tk.Frame(self, bg=BG_BLACK, padx=24, pady=10)
        tf.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tf, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse",
                                 style="Lead.Treeview")
        for col_id, heading, width in COLUMNS:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, minwidth=60)

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview,
                            style="Dark.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview,
                            style="Dark.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.grid_rowconfigure(0, weight=1)
        tf.grid_columnconfigure(0, weight=1)

        # Row colour tags — all dark backgrounds, white text
        self.tree.tag_configure("strong", background="#1C2A10", foreground=WHITE)
        self.tree.tag_configure("good",   background=ROW_ODD,   foreground=WHITE)
        self.tree.tag_configure("verify", background="#2A2200",  foreground=WHITE)
        self.tree.tag_configure("sparse", background=ROW_EVEN,  foreground=GRAY)

        # Click handlers
        self.tree.bind("<Double-1>",  self._on_double_click)
        self.tree.bind("<Button-2>",  self._on_right_click)   # macOS two-finger
        self.tree.bind("<Button-3>",  self._on_right_click)   # standard right-click

        # Footer count
        self.count_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.count_var, font=(UI_FONT, 11, "bold"),
                 bg=BG_BLACK, fg=GOLD, anchor="w", padx=24, pady=8).pack(fill="x")

        self.bind("<Return>", lambda e: self._start_search())

    # ── Helpers for browser actions ───────────────────────────────────────────

    def _get_selected_lead(self, event=None):
        """Return the lead dict for the currently selected (or clicked) row."""
        if event:
            row_id = self.tree.identify_row(event.y)
            if row_id:
                self.tree.selection_set(row_id)
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.leads):
            return self.leads[idx]
        return None

    def _on_double_click(self, event):
        lead = self._get_selected_lead(event)
        if not lead:
            return
        # Open a Google search for "<Business Name> <city>" in the default browser
        query = f'{lead["name"]} {lead["city_hint"]}'
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        webbrowser.open(url)

    def _on_right_click(self, event):
        lead = self._get_selected_lead(event)
        if not lead:
            return
        # Build a context menu
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=WHITE,
                       activebackground=GOLD, activeforeground=BG_BLACK,
                       font=(UI_FONT, 11))

        google_q  = urllib.parse.quote(f'{lead["name"]} {lead["city_hint"]}')
        maps_q    = urllib.parse.quote(
            f'{lead["name"]} {lead["address"] if lead["address"] != "—" else lead["city_hint"]}')

        menu.add_command(
            label="Google Search  (verify website exists)",
            command=lambda: webbrowser.open(
                "https://www.google.com/search?q=" + google_q))
        menu.add_command(
            label="Google Maps  (find the location)",
            command=lambda: webbrowser.open(
                "https://www.google.com/maps/search/" + maps_q))
        menu.add_separator()
        if lead["phone"] != "—":
            menu.add_command(
                label=f"Copy phone: {lead['phone']}",
                command=lambda: (self.clipboard_clear(),
                                 self.clipboard_append(lead["phone"])))
        if lead["email"] != "—":
            menu.add_command(
                label=f"Copy email: {lead['email']}",
                command=lambda: (self.clipboard_clear(),
                                 self.clipboard_append(lead["email"])))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ── Search logic ──────────────────────────────────────────────────────────

    def _start_search(self):
        if not self.search_btn._enabled:
            return
        category = self.category_var.get().strip()
        area     = self.area_var.get().strip()
        if not category or not area:
            messagebox.showwarning("Missing Info",
                                   "Please enter both a business type and a city/area.")
            return

        for row in self.tree.get_children():
            self.tree.delete(row)
        self.leads = []
        self.export_btn.set_enabled(False)
        self.count_var.set("")
        self.search_btn.set_enabled(False)
        self.search_btn.set_text("Searching…")
        self.status_var.set(
            f"Searching for '{category}' in '{area}' — this may take 10–30 seconds…")
        self.update_idletasks()

        threading.Thread(target=scrape_leads,
                         args=(category, area, self._on_results),
                         daemon=True).start()

    def _on_results(self, leads, error):
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
            self.status_var.set(
                "Search complete. No leads found — try a different category or broader area.")
            self.count_var.set("0 leads found.")
            return

        for lead in leads:
            self.tree.insert("", "end", values=(
                lead["name"],
                lead["phone"],
                lead["email"],
                lead["address"],
                lead["hours"],
                lead["social"],
                lead["quality"],
            ), tags=(lead["qtag"],))

        self.export_btn.set_enabled(True)
        self.status_var.set(
            "Done!  Double-click a row to Google it · Right-click for more options")
        self.count_var.set(
            f"{len(leads)} lead{'s' if len(leads) != 1 else ''} found — "
            "sorted by lead quality · businesses with NO website")

    # ── CSV export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self.leads:
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Save leads as CSV",
            initialfile="dmv_leads.csv",
        )
        if not filepath:
            return
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS,
                                        extrasaction="ignore")
                writer.writeheader()
                writer.writerows(self.leads)
            messagebox.showinfo(
                "Saved!",
                f"Your leads have been saved to:\n{filepath}\n\n"
                "You can now open it in Excel.")
        except Exception as ex:
            messagebox.showerror("Save Error", f"Could not save file:\n{ex}")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = LeadScraperApp()
    app.mainloop()
