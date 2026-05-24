#!/usr/bin/env python3
import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import cKDTree

# --- Configurations ---
DATA_FILE = "glastonbury_aadt.csv"
OUTPUT_CSV = "glastonbury_traffic_redistribution_simulation.csv"
OUTPUT_IMG = "glastonbury_traffic_redistribution_impact.png"

def load_network_data():
    if not os.path.exists(DATA_FILE):
        print(f"❌ Error: Cannot find your base dataset file '{DATA_FILE}' in the directory.")
        sys.exit(1)
    print(f"📖 Ingesting spatial street grid metrics from {DATA_FILE}...")
    return pd.read_csv(DATA_FILE)

def simulate_road_closure(target_road_name, df_network, k_alternatives=5):
    """
    Simulates the structural deletion of a road corridor and redistributes its traffic 
    volume to the k-nearest geographically adjacent open street segments using a gravity model.
    """
    df_sim = df_network.copy()
    
    # Isolate target road segments to remove
    target_mask = df_sim['road'].str.upper() == target_road_name.upper()
    if not target_mask.any():
        available_roads = sorted(df_sim['road'].dropna().unique()[:10])
        raise ValueError(f"Target road '{target_road_name}' not found. Sample of valid options: {available_roads}")
        
    target_segments = df_sim[target_mask]
    total_closed_volume = target_segments['AADT_2024'].sum()
    
    # Isolate remaining open network segments
    open_network = df_sim[~target_mask].copy().reset_index(drop=True)
    open_coords = open_network[['lat', 'lon']].values
    
    # Build spatial index tree for high-speed coordinate distance vectors
    open_tree = cKDTree(open_coords)
    
    # Initialize a fast numpy array tracking redirected traffic allocation increments
    redirected_traffic = np.zeros(len(open_network))
    
    print(f"⚡ Processing closure model... Redistributing traffic from {len(target_segments)} closed blocks...")
    for idx, row in target_segments.iterrows():
        segment_volume = row['AADT_2024']
        coord = np.array([row['lat'], row['lon']])
        
        # Query tree for the closest k alternative routes
        distances, neighbor_indices = open_tree.query(coord, k=k_alternatives)
        
        # Handle exact coordinate matches to avoid division by zero
        distances = np.where(distances == 0, 0.0001, distances)
        
        # Gravity weighting: Flow is inversely proportional to squared spatial distance
        raw_weights = 1.0 / (distances ** 2)
        normalized_weights = raw_weights / np.sum(raw_weights)
        
        # Accumulate redirected vectors directly onto index targets
        for i, weight in zip(neighbor_indices, normalized_weights):
            redirected_traffic[i] += segment_volume * weight
            
    # Compile metrics back onto the network dataframe
    open_network['redirected_traffic'] = redirected_traffic
    open_network['New_AADT_2024'] = open_network['AADT_2024'] + open_network['redirected_traffic']
    open_network['Traffic_Increase_Percent'] = (open_network['redirected_traffic'] / open_network['AADT_2024']) * 100
    
    return open_network, total_closed_volume

def plot_redistribution_impact(df_simulated, closed_road_name):
    print("📊 Compiling double-bar comparative network asset plots...")
    # Filter out highways to examine local surface network vulnerability closely
    surface_streets = df_simulated[~df_simulated['func_class'].str.contains('Freeway|Expressway', na=False)]
    
    # Isolate the top 12 surface streets bearing the heaviest redirection loads
    top_impacted = surface_streets.sort_values(by='redirected_traffic', ascending=False).head(12).copy()
    top_impacted = top_impacted.sort_values(by='redirected_traffic', ascending=True) # Ascending for clear horizontal visual alignment
    
    plt.rcParams['figure.figsize'] = [12, 7]
    plt.rcParams['font.size'] = 10
    plt.clf()
    
    y_positions = np.arange(len(top_impacted))
    bar_width = 0.35
    
    # Construct side-by-side bar plots mapping original vs predicted traffic
    plt.barh(y_positions - bar_width/2, top_impacted['AADT_2024'], bar_width, 
             label='Original Traffic Baseline (2024)', color='lightgray', edgecolor='black')
    plt.barh(y_positions + bar_width/2, top_impacted['New_AADT_2024'], bar_width, 
             label='Predicted Traffic Post-Closure Spillover', color='crimson', edgecolor='black')
    
    plt.yticks(y_positions, top_impacted['road'] + " (" + top_impacted['func_class'] + ")")
    plt.xlabel('Average Annual Daily Traffic (AADT) Volume Count (Vehicles/Day)')
    plt.ylabel('Alternative Local Surface Network Routes')
    plt.title(f'Traffic Redistribution Simulation Matrix: Emergency Closure of {closed_road_name.upper()}\nPredicted Spillover Trajectories onto Adjacent Surrounding Local Corridors', 
              weight='bold', pad=15)
    plt.legend(loc='lower right')
    plt.grid(axis='x', linestyle='--', alpha=0.6)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=300)
    print(f"✅ Stress-test visualization exported to disk: '{OUTPUT_IMG}'")

def main():
    print("=" * 85)
    print("🚀 URBAN GRID STRUCTURAL STRESS-TESTER & NODE DELETION HYPOTHETICAL SIMULATOR")
    print("=" * 85 + "\n")
    
    # Ingest baseline
    df_grid = load_network_data()
    
    # Define Target Road Closure
    # We choose CT-94 (Hebron Avenue) because it represents the highest surface arterial bottleneck
    target_closure = "CT-94" 
    
    try:
        # Run simulation
        df_simulated, total_redirected_vol = simulate_road_closure(target_closure, df_grid, k_alternatives=5)
        print(f"✅ Success! Simulated closure of {target_closure.upper()}. Total system load shifted: {total_redirected_vol:,} vehicles/day.")
        
        # Display top 10 segments experiencing the heaviest absolute volume increases
        print("\n" + "-" * 85)
        print("TOP 10 MOST CRITICALLY IMPACTED OPEN SURFACE ROUTES (ABSOLUTE VOLUME FLUX):")
        print("-" * 85)
        surface_only = df_simulated[~df_simulated['func_class'].str.contains('Freeway|Expressway', na=False)]
        top_logs = surface_only.sort_values(by='redirected_traffic', ascending=False).head(10)
        
        print(top_logs[['road', 'func_class', 'AADT_2024', 'redirected_traffic', 'New_AADT_2024', 'Traffic_Increase_Percent']].to_string(index=False))
        print("-" * 85)
        
        # Save output matrix
        df_simulated.to_csv(OUTPUT_CSV, index=False)
        print(f"📊 Relational dataset matrix successfully outputted to: '{OUTPUT_CSV}'")
        
        # Generate chart
        plot_redistribution_impact(df_simulated, target_closure)
        
    except Exception as e:
        print(f"❌ Simulation execution aborted: {e}")

if __name__ == "__main__":
    main()