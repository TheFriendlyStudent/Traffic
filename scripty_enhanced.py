#!/usr/bin/env python3
"""
Glastonbury, CT Traffic Analysis & Visualization
=================================================
Integrates multiple data sources:
1. UConn CTI Streetlight AADT (2016-2024)
2. ArcGIS Glastonbury StreetsExB segments
3. OnBase traffic count PDFs
4. V/C ratio analysis and bottleneck detection

Features:
  - Interactive Folium heatmap
  - Road segment V/C ratio analysis
  - Bottleneck detection (V/C > 0.75)
  - Year-over-year trends
  - Traffic redistribution simulations
  - OnBase PDF document integration

Usage:
  python scripty_enhanced.py [--download-pdfs] [--analyze-vc] [--all]

Outputs:
  glastonbury_traffic_heatmap.html - Interactive map
  glastonbury_aadt.csv - AADT data
  glastonbury_analysis_report.json - Analysis results
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
import pandas as pd
import numpy as np
import folium
from folium.plugins import HeatMap
from pyproj import Transformer

# Import our custom modules
try:
    from traffic_analysis import TrafficNetwork, TrafficDataAnalyzer, load_aadt_data
except ImportError:
    print("⚠️  traffic_analysis module not found. V/C analysis disabled.")
    TrafficNetwork = None

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_URL = "https://gis.cti.uconn.edu/arcgis/rest/services/CTI/Streetlight_AADT/MapServer"

LAYERS = {
    0: "Local Intersections",
    1: "Ramp Segments",
    2: "Ramp Terminals",
    3: "State Intersections",
    4: "State Segments",
    5: "Town Segments",
}

AADT_YEARS = [2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017, 2016]
TOWN_FILTER = "Glastonbury"

PROJ_FROM = "EPSG:6434"  # NAD83(2011) Connecticut State Plane
PROJ_TO   = "EPSG:4326"  # WGS84

OUTPUT_DIR = Path(".")
CSV_OUT    = OUTPUT_DIR / "glastonbury_aadt.csv"
MAP_OUT    = OUTPUT_DIR / "glastonbury_traffic_heatmap.html"
REPORT_OUT = OUTPUT_DIR / "glastonbury_analysis_report.json"
VC_CSV_OUT = OUTPUT_DIR / "glastonbury_vc_analysis.csv"

AADT_BREAKS = [500, 1500, 3000, 6000, 12000, 25000]
AADT_COLORS = ["#313695", "#74add1", "#a8d16a", "#fee090", "#f46d43", "#d73027", "#a50026"]

_transformer = Transformer.from_crs(PROJ_FROM, PROJ_TO, always_xy=True)


def project_ring(coords: list) -> list:
    """Convert State Plane ft → WGS84 lat/lon."""
    out = []
    for pt in coords:
        x, y = (pt[0], pt[1]) if isinstance(pt, (list, tuple)) else (pt["x"], pt["y"])
        lon, lat = _transformer.transform(x, y)
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    return out


def midpoint(coords: list) -> Optional[Tuple]:
    """Return midpoint of polyline as (lat, lon)."""
    if not coords:
        return None
    mid = len(coords) // 2
    return coords[mid]


def aadt_color(aadt: int) -> str:
    """Get color for AADT value."""
    for i, brk in enumerate(AADT_BREAKS):
        if aadt < brk:
            return AADT_COLORS[i]
    return AADT_COLORS[-1]


def fetch_layer(layer_id: int, layer_name: str) -> list:
    """Fetch Glastonbury features from MapServer layer, paginated."""
    url = f"{BASE_URL}/{layer_id}/query"
    page_size = 2000
    offset = 0
    all_feats = []

    while True:
        params = {
            "where": f"TownName = '{TOWN_FILTER}'",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        try:
            r = requests.get(url, params=params, timeout=30,
                           headers={"User-Agent": "GlastonburyTrafficAnalysis/2.0"})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            print(f"    ⚠️  Layer {layer_id} offset={offset}: {exc}")
            break

        if "error" in data:
            print(f"    ⚠️  Layer {layer_id}: {data['error'].get('message')}")
            break

        feats = data.get("features", [])
        all_feats.extend(feats)

        if len(feats) < page_size:
            break
        offset += page_size
        time.sleep(0.15)

    print(f"  Layer {layer_id} ({layer_name}): {len(all_feats)} features")
    return all_feats


def best_aadt(attrs: dict) -> Tuple[int, int]:
    """Return (aadt_value, year) from most recent non-null year."""
    for yr in AADT_YEARS:
        val = attrs.get(f"AADT_{yr}")
        if val and int(val) > 0:
            return int(val), yr
    return 0, 0


def features_to_rows(features: list, layer_name: str) -> list:
    """Parse ArcGIS features into flat rows with reprojected coordinates."""
    rows = []
    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry", {})

        paths = geom.get("paths", [])
        all_coords = []
        for path in paths:
            all_coords.extend(project_ring(path))

        mid = midpoint(all_coords)
        if mid is None:
            continue

        aadt, year = best_aadt(attrs)
        rows.append({
            "lat": mid[0],
            "lon": mid[1],
            "aadt": aadt,
            "year": year,
            "road": attrs.get("RoadName", "Unknown"),
            "func_class": attrs.get("FunctionalClass", ""),
            "layer": layer_name,
            "coords": all_coords,
            **{f"AADT_{yr}": attrs.get(f"AADT_{yr}") for yr in AADT_YEARS},
        })
    return rows


def build_map(df: pd.DataFrame, vc_data: Optional[pd.DataFrame] = None) -> folium.Map:
    """Build interactive Folium map with heatmap and V/C analysis."""
    center_lat = df["lat"].mean()
    center_lon = df["lon"].mean()

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # Title
    m.get_root().html.add_child(folium.Element("""
    <div style="position:fixed;top:15px;left:60px;z-index:9999;
                background:white;padding:10px 16px;border-radius:8px;
                border:2px solid #555;font-family:sans-serif;font-size:14px;
                box-shadow:2px 2px 6px rgba(0,0,0,.3)">
      <b>Glastonbury, CT — Traffic Analysis</b><br>
      <span style="font-size:11px;color:#666">
        AADT 2016–2024 · V/C Analysis · OnBase Integration
      </span>
    </div>"""))

    # Heatmap layer
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

    # Road segments layer
    seg_group = folium.FeatureGroup(name="Road Segments (colored by AADT)", show=True)
    for _, row in df.iterrows():
        coords = row.get("coords", [])
        if len(coords) < 2:
            continue
        
        aadt_label = f"{int(row['aadt']):,}" if row["aadt"] else "N/A"
        
        # Check if this segment has V/C data
        vc_info = ""
        if vc_data is not None:
            matching = vc_data[vc_data['road'] == row['road']]
            if not matching.empty:
                vc_ratio = matching.iloc[0].get('vc_ratio', 0)
                vc_info = f"<br>V/C Ratio: <b>{vc_ratio:.2f}</b>"
        
        popup_html = (
            f"<div style='font-family:sans-serif;font-size:12px;min-width:150px'>"
            f"<b>{row['road']}</b><br>"
            f"AADT ({row['year']}): <b>{aadt_label}</b> veh/day<br>"
            f"Class: {row['func_class']}<br>"
            f"Layer: {row['layer']}"
            f"{vc_info}"
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

    # Bottleneck markers (from V/C analysis)
    if vc_data is not None:
        bottlenecks = vc_data[vc_data['vc_ratio'] > 0.75]
        if len(bottlenecks) > 0:
            bn_group = folium.FeatureGroup(name="🚨 Bottlenecks (V/C > 0.75)", show=True)
            for _, row in bottlenecks.iterrows():
                folium.CircleMarker(
                    location=[row['lat'], row['lon']],
                    radius=8,
                    color='red',
                    fill=True,
                    fillColor='crimson',
                    fillOpacity=0.7,
                    weight=2,
                    popup=f"<b>{row['road']}</b><br>V/C: {row['vc_ratio']:.2f}",
                ).add_to(bn_group)
            bn_group.add_to(m)

    # Legend
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


def analyze_vc_ratios(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """Analyze V/C ratios for all segments."""
    if TrafficNetwork is None:
        print("⚠️  V/C analysis skipped (traffic_analysis module not available)")
        return None, {}

    print("\n🔍 Analyzing V/C Ratios...")
    
    network = TrafficNetwork()
    
    # Add traffic volumes
    for _, row in df.iterrows():
        obj_id = df.index.get_loc(row.name) if hasattr(df.index, 'get_loc') else row.name
        network.add_traffic_volume(obj_id, int(row['aadt']), 'both')
    
    # Calculate V/C for each segment
    vc_data = []
    for idx, row in df.iterrows():
        vc_ratio = network.calculate_vc_ratio(idx)
        if vc_ratio:
            vc_data.append({
                'road': row['road'],
                'lat': row['lat'],
                'lon': row['lon'],
                'aadt': row['aadt'],
                'vc_ratio': vc_ratio
            })
    
    vc_df = pd.DataFrame(vc_data) if vc_data else pd.DataFrame()
    
    # Identify bottlenecks
    bottlenecks = network.identify_bottlenecks(threshold=0.75)
    
    report = {
        'total_segments': len(df),
        'segments_analyzed': len(vc_data),
        'bottleneck_count': len(bottlenecks),
        'bottlenecks': [
            {
                'segment_id': seg_id,
                'vc_ratio': vc,
                'road': df.iloc[seg_id]['road'] if seg_id < len(df) else 'Unknown'
            }
            for seg_id, vc in bottlenecks[:10]
        ]
    }
    
    if bottlenecks:
        print(f"✅ Found {len(bottlenecks)} bottlenecks (V/C > 0.75)")
        for seg_id, vc in bottlenecks[:5]:
            road = df.iloc[seg_id]['road'] if seg_id < len(df) else 'Unknown'
            print(f"   {road}: V/C = {vc:.2f}")
    
    return vc_df, report


def main():
    parser = argparse.ArgumentParser(description="Glastonbury Traffic Analysis")
    parser.add_argument("--download-pdfs", action="store_true", help="Download PDFs from OnBase")
    parser.add_argument("--analyze-vc", action="store_true", help="Analyze V/C ratios")
    parser.add_argument("--all", action="store_true", help="Run all analyses")
    args = parser.parse_args()

    print("=" * 70)
    print("  GLASTONBURY TRAFFIC ANALYSIS SUITE")
    print("  Integrating UConn CTI, ArcGIS, and OnBase Data")
    print("=" * 70 + "\n")

    all_rows = []

    for layer_id, layer_name in LAYERS.items():
        feats = fetch_layer(layer_id, layer_name)
        if feats:
            rows = features_to_rows(feats, layer_name)
            all_rows.extend(rows)

    if not all_rows:
        print("\n❌ No data fetched.")
        sys.exit(1)

    df = pd.DataFrame(all_rows)
    df = df[df["aadt"] > 0].reset_index(drop=True)

    print(f"\n✅ {len(df)} road segments with AADT data")
    print(f"   AADT range: {int(df['aadt'].min()):,} – {int(df['aadt'].max()):,} veh/day")
    print(f"   Years: {sorted(df['year'].unique())}")

    # Save CSV
    csv_df = df.drop(columns=["coords"], errors="ignore")
    csv_df.to_csv(CSV_OUT, index=False)
    print(f"\n💾 Data → {CSV_OUT}")

    # V/C Analysis
    vc_data = None
    report_data = {'analysis_type': 'Traffic Analysis', 'timestamp': str(pd.Timestamp.now())}
    
    if args.analyze_vc or args.all:
        vc_data, vc_report = analyze_vc_ratios(df)
        if vc_data is not None:
            vc_data.to_csv(VC_CSV_OUT, index=False)
            print(f"💾 V/C Analysis → {VC_CSV_OUT}")
            report_data['vc_analysis'] = vc_report

    # Build map
    print("\n🗺️  Building interactive map...")
    m = build_map(df, vc_data)
    m.save(str(MAP_OUT))
    print(f"✅ Map → {MAP_OUT}")

    # Save report
    with open(REPORT_OUT, 'w') as f:
        json.dump(report_data, f, indent=2)
    print(f"📊 Report → {REPORT_OUT}")

    # PDF Download Info
    if args.download_pdfs or args.all:
        print("\n📥 OnBase PDF Integration:")
        print("   Run: python fetch_traffic_data.py --batch")
        print("   After creating document_hashes.txt")

    print("\n" + "=" * 70)
    print("✅ Open glastonbury_traffic_heatmap.html in a browser to view results")
    print("=" * 70)


if __name__ == "__main__":
    main()
