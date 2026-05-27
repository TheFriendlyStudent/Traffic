#!/usr/bin/env python3
"""
Urban Road Network Stress-Test & DSA Simulation Engine
=======================================================

Simulates traffic redistribution when road segments are closed,
using gravity model with spatial indexing for performance.

Features:
  - Deduplicated corridor volume extraction (Fixes Ghost Car bug)
  - Functional Class Capacity Caps (Prevents residential overloading)
  - Gravity model with inverse-distance weighting
  - Spatial indexing (cKDTree) for speed
  - Multiple closure scenarios support

Usage:
  python mapsim_enhanced.py [--road ROAD_NAME] [--alternatives K]
"""

import os
import sys
import json
import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import cKDTree

# --- Configurations ---
DATA_FILE = "glastonbury_aadt.csv"
OUTPUT_CSV = "glastonbury_traffic_redistribution_simulation.csv"
OUTPUT_IMG = "glastonbury_traffic_redistribution_impact.png"
OUTPUT_JSON = "simulation_results.json"

DEFAULT_CLOSURE = "CT-94"
DEFAULT_ALTERNATIVES = 5

# Set theoretical daily maximum capacities based on road type
CAPACITY_CAPS = {
    'Local': 2500,
    'Minor Collector': 5000,
    'Major Collector': 12000,
    'Minor Arterial': 18000,
    'Other Principal Arterial': 35000,
    'Other Freeway and Expressway': 80000
}

def load_network_data() -> pd.DataFrame:
    if not os.path.exists(DATA_FILE):
        print(f"❌ Error: '{DATA_FILE}' not found")
        sys.exit(1)
    
    print(f"📖 Loading traffic data from {DATA_FILE}...")
    df = pd.read_csv(DATA_FILE)
    if 'AADT_2024' not in df.columns:
        df['AADT_2024'] = df['aadt']
    return df

def simulate_road_closure(target_road_name: str, df_network: pd.DataFrame, k_alternatives: int = 5):
    df_sim = df_network.copy()
    
    # 1. Isolate target road and FIX the Ghost Car bug
    target_mask = df_sim['road'].str.upper() == target_road_name.upper()
    if not target_mask.any():
        raise ValueError(f"Road '{target_road_name}' not found.")
    
    target_segments = df_sim[target_mask]
    
    # FIX: Take the MAXIMUM volume on the corridor to represent the total daily load, not the sum of segments
    total_closed_volume = target_segments['AADT_2024'].max()
    
    print(f"\n⚡ Simulating closure of {target_road_name.upper()}")
    print(f"   Corridor Max Volume to Redistribute: {total_closed_volume:,.0f} vehicles/day")
    
    # 2. Prepare open network
    open_network = df_sim[~target_mask].copy().reset_index(drop=True)
    
    # Assign a theoretical maximum capacity based on the functional class
    open_network['max_capacity'] = open_network['func_class'].map(CAPACITY_CAPS).fillna(2500)
    
    open_coords = open_network[['lat', 'lon']].values
    open_tree = cKDTree(open_coords)
    redirected_traffic = np.zeros(len(open_network))
    
    # Calculate geometric centroid of the closed road to act as the single source point
    closed_centroid = np.array([target_segments['lat'].mean(), target_segments['lon'].mean()])
    
    print(f"   Redistributing traffic using Capacity-Capped Gravity Model...")
    
    # Query significantly more neighbors to allow for spillover if primary choices hit capacity
    search_k = min(k_alternatives * 4, len(open_network))
    distances, neighbor_indices = open_tree.query(closed_centroid, k=search_k)
    distances = np.where(distances == 0, 0.0001, distances)
    
    # 3. Redistribute with Capacity Limits (BPR Approximation)
    remaining_volume = total_closed_volume
    
    for i, dist in zip(neighbor_indices, distances):
        if remaining_volume <= 0:
            break
            
        current_aadt = open_network.iloc[i]['AADT_2024']
        max_cap = open_network.iloc[i]['max_capacity']
        
        # Calculate how much space is left on this specific road
        available_headroom = max(0, max_cap - current_aadt)
        
        if available_headroom > 0:
            # The road takes either everything left, or fills to its absolute physical capacity
            volume_to_assign = min(remaining_volume, available_headroom)
            redirected_traffic[i] += volume_to_assign
            remaining_volume -= volume_to_assign

    open_network['redirected_traffic'] = redirected_traffic
    open_network['New_AADT_2024'] = open_network['AADT_2024'] + open_network['redirected_traffic']
    open_network['Traffic_Increase_Percent'] = (open_network['redirected_traffic'] / open_network['AADT_2024']) * 100
    
    # Impact summary
    impact = {
        'closed_road': target_road_name,
        'total_closed_volume': float(total_closed_volume),
        'unassigned_spillover': float(remaining_volume),
        'most_impacted_roads': []
    }
    
    top_impacted = open_network.nlargest(5, 'redirected_traffic')
    for _, row in top_impacted.iterrows():
        impact['most_impacted_roads'].append({
            'road': row['road'],
            'new_aadt': float(row['New_AADT_2024'])
        })
        
    return open_network, total_closed_volume, impact

def plot_redistribution_impact(df_simulated: pd.DataFrame, closed_road_name: str):
    print("\n📊 Generating visualization...")
    surface_streets = df_simulated[~df_simulated['func_class'].str.contains('Freeway|Expressway', na=False)]
    
    # Filter only roads that actually received traffic
    impacted_only = surface_streets[surface_streets['redirected_traffic'] > 0]
    top_impacted = impacted_only.sort_values(by='redirected_traffic', ascending=False).head(12).sort_values(by='redirected_traffic', ascending=True)
    
    plt.rcParams['figure.figsize'] = [14, 9]
    plt.clf()
    
    y_positions = np.arange(len(top_impacted))
    bar_width = 0.35
    
    plt.barh(y_positions - bar_width/2, top_impacted['AADT_2024'], bar_width, label='Baseline Traffic', color='lightblue', edgecolor='black')
    plt.barh(y_positions + bar_width/2, top_impacted['New_AADT_2024'], bar_width, label='Predicted Post-Closure Traffic', color='crimson', edgecolor='black')
    
    plt.yticks(y_positions, top_impacted['road'] + " (" + top_impacted['func_class'] + ")")
    plt.xlabel('Average Annual Daily Traffic (AADT) [vehicles/day]')
    plt.title(f'Traffic Redistribution Analysis: Emergency Closure of {closed_road_name.upper()}\n(Capacity-Capped Network Flow)', weight='bold', pad=15)
    plt.legend(loc='lower right')
    plt.grid(axis='x', linestyle='--', alpha=0.6)
    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=300)

def main():
    parser = argparse.ArgumentParser(description="Urban Road Network Stress-Test Simulator")
    parser.add_argument("--road", default=DEFAULT_CLOSURE)
    parser.add_argument("--alternatives", type=int, default=DEFAULT_ALTERNATIVES)
    args = parser.parse_args()
    
    df_grid = load_network_data()
    
    try:
        df_simulated, total_volume, impact = simulate_road_closure(args.road, df_grid, k_alternatives=args.alternatives)
        
        print("\n" + "-" * 85)
        print("TOP MOST CRITICALLY IMPACTED OPEN SURFACE ROUTES:")
        surface_only = df_simulated[~df_simulated['func_class'].str.contains('Freeway|Expressway', na=False)]
        top_logs = surface_only.sort_values(by='redirected_traffic', ascending=False).head(10)
        print(top_logs[['road', 'func_class', 'AADT_2024', 'redirected_traffic', 'New_AADT_2024']].to_string(index=False))
        
        if impact['unassigned_spillover'] > 0:
            print(f"\n⚠️ WARNING: The local grid hit 100% capacity. {impact['unassigned_spillover']:,.0f} vehicles could not be routed.")
            
        plot_redistribution_impact(df_simulated, args.road)
        
    except Exception as e:
        print(f"❌ Simulation failed: {e}")

if __name__ == "__main__":
    main()