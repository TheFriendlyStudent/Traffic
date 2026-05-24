#!/usr/bin/env python3
"""
Script to fetch traffic data from ArcGIS Experience and associated PDFs from OnBase.

Usage:
    python fetch_traffic_data.py                           # Fetch ArcGIS data
    python fetch_traffic_data.py --doc-id <document_id>   # Fetch specific document
    python fetch_traffic_data.py --batch                  # Fetch batch of documents
"""

import os
import json
import requests
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
import time
from urllib.parse import quote
import sys
import argparse

# Configuration
ARCGIS_ITEM_ID = "dcd740154f9d4b79a3f6ad094b7834d1"
ARCGIS_API_BASE = "https://experience.arcgis.com/api/experience"
ONBASE_API_URL = "https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document"
OUTPUT_DIR = Path("traffic_data")
MAX_RETRIES = 3
TIMEOUT = 30

# Create output directory
OUTPUT_DIR.mkdir(exist_ok=True)

def fetch_arcgis_data():
    """Fetch data from ArcGIS Experience API."""
    print("Fetching ArcGIS Experience data...")
    
    # Try to fetch the experience configuration
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        # Note: Direct API access may not be available
        # The ArcGIS Experience is JavaScript-based and requires browser rendering
        print("⚠ ArcGIS Experience API requires browser (JavaScript rendering)")
        print("  To extract document IDs: use browser DevTools Network tab")
        print("  Or manually inspect the feature data from the map interface")
        return None
    except Exception as e:
        print(f"⚠ Could not fetch ArcGIS config: {e}")
        return None

def fetch_feature_service_data():
    """
    Fetch data from the feature service referenced in the experience.
    The data source appears to be: dataSource_1-19428a2e2e0-layer-4-1:1134
    """
    print("\nFetching feature service data...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    try:
        # Common ArcGIS REST API endpoints
        # The experience likely references a public feature service
        feature_service_url = "https://services.arcgis.com/sharing/rest/content/items"
        
        params = {
            "f": "json",
            "token": ""
        }
        
        response = requests.get(feature_service_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        print(f"✓ Retrieved feature service data")
        return data
    except Exception as e:
        print(f"⚠ Feature service fetch failed: {e}")
        return None

def fetch_onbase_document(document_id: str, output_file: str, use_curl: bool = False) -> bool:
    """
    Fetch a document from OnBase using either requests or curl.
    
    Args:
        document_id: The OnBase document identifier
        output_file: Path to save the document
        use_curl: Use curl command instead of requests library
        
    Returns:
        True if successful, False otherwise
    """
    print(f"\nFetching document: {document_id[:50]}...")
    
    # Construct the OnBase API URL
    url = f"{ONBASE_API_URL}/{document_id}/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Sec-Fetch-Storage-Access": "none",
        "Connection": "keep-alive",
        "Referer": "https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/index.html?OBKey__102_1=MAIN%20ST",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Priority": "u=4",
        "TE": "trailers"
    }
    
    if use_curl:
        return _fetch_with_curl(url, headers, output_file)
    else:
        return _fetch_with_requests(url, headers, output_file)

def _fetch_with_requests(url: str, headers: Dict, output_file: str) -> bool:
    """Fetch document using requests library."""
    try:
        # OnBase documents are fetched via GET request (not POST)
        response = requests.get(
            url,
            headers=headers,
            timeout=TIMEOUT,
            stream=True,
            verify=False,
            allow_redirects=True
        )
        response.raise_for_status()
        
        # Check if we got a PDF or error JSON
        content_type = response.headers.get('content-type', '').lower()
        
        if 'application/json' in content_type or response.text.strip().startswith('{'):
            # Got JSON error response
            print(f"✗ API returned error: {response.text[:100]}")
            return False
        
        # Save the document
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = Path(output_file).stat().st_size
        print(f"✓ Saved to {output_file} ({file_size:,} bytes)")
        return True
        
    except Exception as e:
        print(f"✗ Failed with requests: {e}")
        return False

def _fetch_with_curl(url: str, headers: Dict, output_file: str) -> bool:
    """Fetch document using curl command."""
    try:
        # Build curl command
        curl_cmd = ["curl.exe", "-X", "GET"]
        
        # Add headers
        for key, value in headers.items():
            curl_cmd.extend(["-H", f"{key}: {value}"])
        
        # Add output and URL
        curl_cmd.extend(["-o", output_file])
        curl_cmd.append(url)
        
        # Execute curl
        result = subprocess.run(
            curl_cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT
        )
        
        if result.returncode == 0 and Path(output_file).exists():
            file_size = Path(output_file).stat().st_size
            print(f"✓ Downloaded with curl ({file_size:,} bytes)")
            return True
        else:
            print(f"✗ curl failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"✗ Failed with curl: {e}")
        return False

def extract_document_ids_from_features(features: List[Dict]) -> List[str]:
    """
    Extract OnBase document IDs from feature properties.
    Looks for common field names that might contain document IDs or links.
    """
    document_ids = []
    
    for feature in features:
        props = feature.get("properties", {})
        
        # Look for fields that might contain document IDs
        for field_name, field_value in props.items():
            if field_value and isinstance(field_value, str):
                # Check if it looks like an OnBase document ID (long encoded string)
                if len(field_value) > 50 and any(c in field_value for c in ['%', 'C3', 'C1']):
                    document_ids.append(field_value)
                    print(f"Found potential document ID in field '{field_name}'")
    
    return document_ids

def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Fetch traffic data from ArcGIS Experience and OnBase documents"
    )
    parser.add_argument("--doc-id", help="Specific document ID to fetch")
    parser.add_argument("--use-curl", action="store_true", help="Use curl instead of requests library")
    parser.add_argument("--batch", action="store_true", help="Process batch mode (load doc IDs from file)")
    parser.add_argument("--docs-file", default="document_ids.txt", help="File containing document IDs (one per line)")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Traffic Data Fetcher - ArcGIS + OnBase Integration")
    print("=" * 60)
    
    # If specific document ID provided
    if args.doc_id:
        output_file = OUTPUT_DIR / f"document_{hash(args.doc_id) % 10000}.pdf"
        fetch_onbase_document(args.doc_id, str(output_file), use_curl=args.use_curl)
        return
    
    # Batch mode
    if args.batch and Path(args.docs_file).exists():
        print(f"\nProcessing documents from {args.docs_file}...")
        with open(args.docs_file, 'r') as f:
            doc_ids = [line.strip() for line in f if line.strip()]
        
        print(f"Found {len(doc_ids)} document IDs")
        for i, doc_id in enumerate(doc_ids, 1):
            print(f"\n[{i}/{len(doc_ids)}]", end="")
            output_file = OUTPUT_DIR / f"document_{i:04d}.pdf"
            fetch_onbase_document(doc_id, str(output_file), use_curl=args.use_curl)
            time.sleep(1)  # Rate limiting
        return
    
    # Default: Fetch ArcGIS data
    print("\nFetching ArcGIS Experience data...")
    
    arcgis_data = fetch_arcgis_data()
    if arcgis_data:
        config_file = OUTPUT_DIR / "arcgis_config.json"
        with open(config_file, 'w') as f:
            json.dump(arcgis_data, f, indent=2)
        print(f"✓ Saved to {config_file}")
    
    feature_data = fetch_feature_service_data()
    if feature_data:
        features_file = OUTPUT_DIR / "features.json"
        with open(features_file, 'w') as f:
            json.dump(feature_data, f, indent=2)
        print(f"✓ Saved to {features_file}")
    
    # Example document fetch
    example_doc_id = "AdzJUwDCr1WBUTV48f%C3%81mNHVPlw%C3%81nk3pnW%C3%818C2UMXr8dOkFC02SXgofIbbgNNkFzRworVow8jJzlWMI%C3%81pn1Rtm8k%3D"
    
    print("\n" + "=" * 60)
    print("Attempting to fetch sample document from OnBase...")
    print("=" * 60)
    
    output_file = OUTPUT_DIR / "sample_document.pdf"
    success = fetch_onbase_document(example_doc_id, str(output_file), use_curl=args.use_curl)
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Output directory: {OUTPUT_DIR.absolute()}")
    print("\nUsage examples:")
    print("  python fetch_traffic_data.py")
    print("  python fetch_traffic_data.py --doc-id '<document-id>'")
    print("  python fetch_traffic_data.py --batch --docs-file document_ids.txt")
    print("  python fetch_traffic_data.py --use-curl")

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
