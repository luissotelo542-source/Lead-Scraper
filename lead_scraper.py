"""
DMV Lead Scraper
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
    Send the query to the free Overpass API and return the JSON result.
    Tries a backup server if the first one is busy.
    """
    servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    for server in servers:
        try:
            resp = requests.post(server, data={"data": query}, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            time.sleep(2)
    return None


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
    data = run_overpass_query(query)
    if data is None:
        callback([], "Could not reach the Overpass API. Check your internet connection and try again.")
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
# GUI
# ══════════════════════════════════════════════════════════════════════════════

class LeadScraperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DMV Lead Scraper — Find Businesses Without a Website")
        self.geometry("1050x680")
        self.resizable(True, True)
        self.configure(bg="#f0f4f8")

        self.leads = []  # holds the current results
        self._build_ui()

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg="#1a3c5e", pady=12)
        header.pack(fill="x")
        tk.Label(header, text="DMV Lead Scraper",
                 font=("Helvetica", 20, "bold"), fg="white", bg="#1a3c5e").pack()
        tk.Label(header,
                 text="Find contractors & service businesses in DC/MD/VA with NO website",
                 font=("Helvetica", 11), fg="#a8c8e8", bg="#1a3c5e").pack()

        # ── Search bar ────────────────────────────────────────────────────────
        search_frame = tk.Frame(self, bg="#f0f4f8", padx=20, pady=14)
        search_frame.pack(fill="x")

        # Category input
        tk.Label(search_frame, text="Business Type:", font=("Helvetica", 11, "bold"),
                 bg="#f0f4f8").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.category_var = tk.StringVar()
        cat_entry = ttk.Entry(search_frame, textvariable=self.category_var, width=22,
                              font=("Helvetica", 11))
        cat_entry.grid(row=0, column=1, padx=(0, 18))
        cat_entry.insert(0, "plumber")

        # Area input
        tk.Label(search_frame, text="City / Area:", font=("Helvetica", 11, "bold"),
                 bg="#f0f4f8").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.area_var = tk.StringVar()
        area_entry = ttk.Entry(search_frame, textvariable=self.area_var, width=26,
                               font=("Helvetica", 11))
        area_entry.grid(row=0, column=3, padx=(0, 18))
        area_entry.insert(0, "Rockville, MD")

        # Search button
        self.search_btn = tk.Button(
            search_frame, text="  Search  ", font=("Helvetica", 11, "bold"),
            bg="#1a3c5e", fg="white", relief="flat", padx=10, pady=4,
            cursor="hand2", command=self._start_search
        )
        self.search_btn.grid(row=0, column=4, padx=(0, 12))

        # Export button
        self.export_btn = tk.Button(
            search_frame, text="  Export to CSV  ", font=("Helvetica", 11, "bold"),
            bg="#2e7d32", fg="white", relief="flat", padx=10, pady=4,
            cursor="hand2", command=self._export_csv, state="disabled"
        )
        self.export_btn.grid(row=0, column=5)

        # Hint line
        tk.Label(search_frame,
                 text='Examples — Type: "junk removal"  "landscaper"  "electrician"  "roofer"  |  Area: "Silver Spring, MD"  "Alexandria, VA"  "NW Washington DC"',
                 font=("Helvetica", 9), fg="#555", bg="#f0f4f8"
                 ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready. Enter a business type and area, then click Search.")
        status_bar = tk.Label(self, textvariable=self.status_var, font=("Helvetica", 10),
                              bg="#dce8f5", anchor="w", padx=14, pady=5)
        status_bar.pack(fill="x")

        # ── Results table ─────────────────────────────────────────────────────
        table_frame = tk.Frame(self, bg="#f0f4f8", padx=16, pady=8)
        table_frame.pack(fill="both", expand=True)

        columns = ("name", "phone", "address", "category", "social")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                 selectmode="browse")

        col_cfg = [
            ("name",     "Business Name",  220),
            ("phone",    "Phone",          140),
            ("address",  "Address",        300),
            ("category", "Category",       110),
            ("social",   "Social Media",   150),
        ]
        for col_id, heading, width in col_cfg:
            self.tree.heading(col_id, text=heading)
            self.tree.column(col_id, width=width, minwidth=80)

        # Scrollbars
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # Alternate row colours for readability
        self.tree.tag_configure("odd",  background="#ffffff")
        self.tree.tag_configure("even", background="#eaf2fb")

        # ── Footer count label ────────────────────────────────────────────────
        self.count_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.count_var, font=("Helvetica", 10, "bold"),
                 bg="#f0f4f8", fg="#1a3c5e", anchor="w", padx=18, pady=6
                 ).pack(fill="x")

        # Allow pressing Enter to search
        self.bind("<Return>", lambda e: self._start_search())

    # ── Search logic ──────────────────────────────────────────────────────────

    def _start_search(self):
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
        self.export_btn.config(state="disabled")
        self.count_var.set("")
        self.search_btn.config(state="disabled", text="  Searching…  ")
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
        self.search_btn.config(state="normal", text="  Search  ")

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

        self.export_btn.config(state="normal")
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
