#!/usr/bin/env python3
"""
Glastonbury, CT Traffic Heatmap
================================
Fetches road-segment AADT data from the UConn CTI Streetlight AADT
MapServer — a statewide CT dataset with AADT_2016–AADT_2024, filtered
to Glastonbury.

Layers used (all polyline):
  0 – Local Intersections
  1 – Ramp Segments
  2 – Ramp Terminals
  3 – State Intersections
  4 – State Segments
  5 – Town Segments  ← primary source for town roads

Source:
  https://gis.cti.uconn.edu/arcgis/rest/services/CTI/Streetlight_AADT/MapServer

Usage:
  pip install requests pandas folium pyproj
  python glastonbury_traffic_heatmap.py

Outputs:
  glastonbury_traffic_heatmap.html  – interactive Folium map
  glastonbury_aadt.csv              – raw extracted data
"""

import sys
import time
from pathlib import Path

import requests
import pandas as pd
import folium
from folium.plugins import HeatMap
from pyproj import Transformer

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_URL = "https://gis.cti.uconn.edu/arcgis/rest/services/CTI/Streetlight_AADT/MapServer"

# All 6 layers — we merge them; Town Segments (5) is the richest for local roads
LAYERS = {
    0: "Local Intersections",
    1: "Ramp Segments",
    2: "Ramp Terminals",
    3: "State Intersections",
    4: "State Segments",
    5: "Town Segments",
}

# Most recent available year — script falls back automatically if null
AADT_YEARS = [2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]

TOWN_FILTER = "Glastonbury"   # exact TownName value in the service

# CRS: service uses SRID 103016 (NAD83(2011) Connecticut State Plane ft)
# We reproject to WGS84 for Folium
PROJ_FROM = "EPSG:6434"       # 103016 = 6434 in EPSG
PROJ_TO   = "EPSG:4326"

OUTPUT_DIR = Path(".")
CSV_OUT    = OUTPUT_DIR / "glastonbury_aadt.csv"
MAP_OUT    = OUTPUT_DIR / "glastonbury_traffic_heatmap.html"

# ── Coordinate reprojection ─────────────────────────────────────────────────────

_transformer = Transformer.from_crs(PROJ_FROM, PROJ_TO, always_xy=True)

def project_ring(coords: list) -> list[tuple[float, float]]:
    """Convert a list of [x, y] (State Plane ft) → [(lat, lon)] (WGS84)."""
    out = []
    for pt in coords:
        x, y = (pt[0], pt[1]) if isinstance(pt, (list, tuple)) else (pt["x"], pt["y"])
        lon, lat = _transformer.transform(x, y)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    return out

def midpoint(coords: list[tuple]) -> tuple[float, float] | None:
    """Return the midpoint of a polyline as (lat, lon)."""
    if not coords:
        return None
    mid = len(coords) // 2
    return coords[mid]

# ── Data fetch ─────────────────────────────────────────────────────────────────

def fetch_layer(layer_id: int, layer_name: str) -> list[dict]:
    """Fetch all Glastonbury features from one MapServer layer, paginated."""
    url        = f"{BASE_URL}/{layer_id}/query"
    page_size  = 2000
    offset     = 0
    all_feats  = []

    while True:
        params = {
            "where":             f"TownName = '{TOWN_FILTER}'",
            "outFields":         "*",
            "returnGeometry":    "true",
            "outSR":             "",          # keep native CRS; we reproject manually
            "f":                 "json",
            "resultOffset":      offset,
            "resultRecordCount": page_size,
        }
        try:
            r = requests.get(url, params=params, timeout=30,
                             headers={"User-Agent": "GlastonburyTrafficETL/1.0"})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            print(f"    ⚠️  Layer {layer_id} page offset={offset}: {exc}")
            break

        if "error" in data:
            print(f"    ⚠️  Layer {layer_id} error: {data['error'].get('message')}")
            break

        feats = data.get("features", [])
        all_feats.extend(feats)

        if len(feats) < page_size:
            break
        offset += page_size
        time.sleep(0.15)

    print(f"  Layer {layer_id} ({layer_name}): {len(all_feats)} features")
    return all_feats


def best_aadt(attrs: dict) -> tuple[int, int]:
    """Return (aadt_value, year) picking the most recent non-null year."""
    for yr in AADT_YEARS:
        val = attrs.get(f"AADT_{yr}")
        if val and int(val) > 0:
            return int(val), yr
    return 0, 0


def features_to_rows(features: list[dict], layer_name: str) -> list[dict]:
    """Parse ArcGIS polyline features into flat rows with reprojected midpoints."""
    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        geom  = feat.get("geometry", {})

        # polyline geometry: paths = list of rings
        paths = geom.get("paths", [])
        all_coords: list[tuple] = []
        for path in paths:
            all_coords.extend(project_ring(path))

        mid = midpoint(all_coords)
        if mid is None:
            continue

        aadt, year = best_aadt(attrs)
        rows.append({
            "lat":        mid[0],
            "lon":        mid[1],
            "aadt":       aadt,
            "year":       year,
            "road":       attrs.get("RoadName", "Unknown"),
            "func_class": attrs.get("FunctionalClass", ""),
            "layer":      layer_name,
            "coords":     all_coords,  # full polyline for choropleth drawing
            # year columns for CSV
            **{f"AADT_{yr}": attrs.get(f"AADT_{yr}") for yr in AADT_YEARS},
        })
    return rows


# ── Map building ───────────────────────────────────────────────────────────────

AADT_BREAKS = [500, 1500, 3000, 6000, 12000, 25000]
AADT_COLORS = ["#313695", "#74add1", "#a8d16a", "#fee090", "#f46d43", "#d73027", "#a50026"]

def aadt_color(aadt: int) -> str:
    for i, brk in enumerate(AADT_BREAKS):
        if aadt < brk:
            return AADT_COLORS[i]
    return AADT_COLORS[-1]


def build_map(df: pd.DataFrame) -> folium.Map:
    center_lat = df["lat"].mean()
    center_lon = df["lon"].mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # ── Title ──────────────────────────────────────────────────────────────────
    m.get_root().html.add_child(folium.Element("""
    <div style="position:fixed;top:15px;left:60px;z-index:9999;
                background:white;padding:10px 16px;border-radius:8px;
                border:2px solid #555;font-family:sans-serif;font-size:14px;
                box-shadow:2px 2px 6px rgba(0,0,0,.3)">
      <b>Glastonbury, CT — Traffic Volume</b><br>
      <span style="font-size:11px;color:#666">
        AADT 2016–2024 · UConn CTI / CTDOT Streetlight Data
      </span>
    </div>"""))

    # ── Heatmap layer ──────────────────────────────────────────────────────────
    max_aadt = df["aadt"].max() or 1
    heat_data = [
        [row["lat"], row["lon"], row["aadt"] / max_aadt]
        for _, row in df.iterrows()
        if row["aadt"] > 0
    ]
    HeatMap(
        heat_data,
        name="Heat: Traffic Density",
        radius=20,
        blur=18,
        max_zoom=17,
        gradient={"0.2":"#313695","0.4":"#74add1",
                  "0.6":"#fee090","0.8":"#f46d43","1.0":"#a50026"},
    ).add_to(m)

    # ── Choropleth polylines ───────────────────────────────────────────────────
    seg_group = folium.FeatureGroup(name="Road Segments (colored by AADT)", show=True)
    for _, row in df.iterrows():
        coords = row.get("coords", [])
        if len(coords) < 2:
            continue
        aadt_label = f"{int(row['aadt']):,}" if row["aadt"] else "N/A"
        popup_html = (
            f"<div style='font-family:sans-serif;font-size:12px;min-width:150px'>"
            f"<b>{row['road']}</b><br>"
            f"AADT ({row['year']}): <b>{aadt_label}</b> veh/day<br>"
            f"Class: {row['func_class']}<br>"
            f"Layer: {row['layer']}"
            f"</div>"
        )
        folium.PolyLine(
            locations=coords,
            color=aadt_color(row["aadt"]),
            weight=4,
            opacity=0.8,
            tooltip=f"{row['road']}: {aadt_label} veh/day ({row['year']})",
            popup=folium.Popup(popup_html, max_width=220),
        ).add_to(seg_group)
    seg_group.add_to(m)

    # ── Legend ─────────────────────────────────────────────────────────────────
    legend_items = "".join(
        f'<span style="color:{c}">■</span> '
        f'{"< " + f"{AADT_BREAKS[i]:,}" if i < len(AADT_BREAKS) else f"{AADT_BREAKS[-1]:,}+"}'
        f"<br>"
        for i, c in enumerate(AADT_COLORS)
    )
    m.get_root().html.add_child(folium.Element(f"""
    <div style="position:fixed;bottom:30px;left:30px;z-index:9999;
                background:white;padding:10px 14px;border-radius:8px;
                border:2px solid #555;font-family:sans-serif;font-size:12px;
                box-shadow:2px 2px 6px rgba(0,0,0,.3)">
      <b>AADT (veh/day)</b><br>{legend_items}
    </div>"""))

    folium.LayerControl(collapsed=False).add_to(m)
    return m


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  GLASTONBURY TRAFFIC HEATMAP — UConn CTI Streetlight AADT")
    print("=" * 65 + "\n")

    all_rows: list[dict] = []

    for layer_id, layer_name in LAYERS.items():
        feats = fetch_layer(layer_id, layer_name)
        if feats:
            rows = features_to_rows(feats, layer_name)
            all_rows.extend(rows)

    if not all_rows:
        print("\n❌  No data fetched. Check your internet connection.")
        print(f"    Service: {BASE_URL}")
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df = df[df["aadt"] > 0].reset_index(drop=True)

    print(f"\n✅  {len(df)} road segments with AADT data")
    print(f"    AADT range: {int(df['aadt'].min()):,} – {int(df['aadt'].max()):,} veh/day")
    print(f"    Years present: {sorted(df['year'].unique())}")

    # Save CSV (drop the coords column — it's a list, not CSV-friendly)
    csv_df = df.drop(columns=["coords"], errors="ignore")
    csv_df.to_csv(CSV_OUT, index=False)
    print(f"\n💾  CSV  → {CSV_OUT.resolve()}")

    print("🗺️   Building map...")
    m = build_map(df)
    m.save(str(MAP_OUT))
    print(f"✅  Map  → {MAP_OUT.resolve()}")
    print("\n    Open glastonbury_traffic_heatmap.html in any browser.")
    print("    Use the layer control (top-right) to toggle heatmap vs. segments.")


if __name__ == "__main__":
    main()