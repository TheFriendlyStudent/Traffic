#!/usr/bin/env python3
"""
Traffic Data Downloader - Fixed Version
Queries the OnBase public records system directly to get document IDs.
Uses street names/codes to fetch traffic count PDFs.
"""

import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Any
import sys
import argparse
from urllib.parse import quote

OUTPUT_DIR = Path("traffic_data")
OUTPUT_DIR.mkdir(exist_ok=True)

# This is the OnBase public access endpoint that serves traffic documents
ONBASE_SEARCH_URL = "https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/search"
ONBASE_DOWNLOAD_URL = "https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document"

# Headers for OnBase requests
ONBASE_HEADERS = {
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


def fetch_segments() -> List[Dict]:
    """Fetch all segments from ArcGIS."""
    print("🔍 Fetching segments from ArcGIS...")
    
    map_server_url = "https://gisarc2022.glastonbury-ct.gov/server/rest/services/GlastonburyPublic/StreetsExB/MapServer/1/query"
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json"
    }
    
    try:
        response = requests.get(map_server_url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        print(f"✅ Found {len(features)} segments\n")
        return features
    except Exception as e:
        print(f"❌ Error fetching segments: {e}\n")
        return []


def search_onbase_for_document(street_name: str, street_code: str = None) -> Dict[str, Any]:
    """
    Search OnBase public records for traffic count document.
    Queries the public search interface directly.
    
    Args:
        street_name: Name of the street (e.g., "MAIN STREET")
        street_code: Optional STCODE from segment attributes
        
    Returns:
        Dict with doc_id and doc_hash if found
    """
    
    # Try different query patterns
    search_terms = [
        street_name.strip(),                           # Full name
        street_name.split()[0] if street_name else "", # First word
    ]
    
    if street_code:
        search_terms.append(street_code)  # Street code
    
    for search_term in search_terms:
        if not search_term:
            continue
        
        try:
            # OnBase has a search interface that returns document links
            # We need to query their public access system
            
            # Method 1: Try direct API query with keyword
            search_url = "https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Search"
            
            search_params = {
                "query": search_term,
                "type": "TrafficCount",  # Document type
                "f": "json"
            }
            
            response = requests.get(
                search_url,
                params=search_params,
                headers=ONBASE_HEADERS,
                timeout=10,
                verify=False
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "results" in data and data["results"]:
                        result = data["results"][0]
                        return {
                            "doc_id": result.get("DocumentID") or result.get("id"),
                            "doc_hash": result.get("Hash") or result.get("DocumentHash"),
                            "title": result.get("Title"),
                            "found_by": search_term
                        }
                except:
                    pass
            
            # Method 2: Query through the public records system
            # The traffic count interface has a specific URL pattern
            doc_search_url = f"https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/GetTrafficCount?streetName={quote(search_term)}"
            
            response = requests.get(
                doc_search_url,
                headers=ONBASE_HEADERS,
                timeout=10,
                verify=False
            )
            
            if response.status_code == 200 and len(response.content) > 1000:
                # Successfully retrieved a document
                return {
                    "doc_id": search_term,
                    "doc_hash": None,
                    "url": doc_search_url,
                    "found_by": search_term
                }
        
        except Exception as e:
            continue
    
    return None


def fetch_document_by_street(street_name: str, output_file: str) -> bool:
    """
    Fetch a traffic count PDF by street name.
    Uses the public traffic count interface directly.
    """
    
    try:
        # The public interface accepts street name queries
        doc_url = f"https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/GetTrafficCount?streetName={quote(street_name)}"
        
        response = requests.get(
            doc_url,
            headers=ONBASE_HEADERS,
            timeout=30,
            stream=True,
            verify=False,
            allow_redirects=True
        )
        
        # Check if we got a valid PDF
        content_type = response.headers.get('content-type', '').lower()
        
        if response.status_code != 200:
            return False
        
        if 'application/json' in content_type or response.text.strip().startswith('{'):
            # Got error response
            return False
        
        # Check file size from header
        content_length = response.headers.get('content-length')
        if content_length and int(content_length) < 1000:
            # Too small, likely an error
            return False
        
        # Save the document
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Validate saved file
        file_size = Path(output_file).stat().st_size
        if file_size > 1000:  # Must be >1KB
            return True
        else:
            output_file.unlink()
            return False
    
    except Exception as e:
        return False


def batch_download_by_street_names(segments: List[Dict]) -> None:
    """Download traffic PDFs using street names."""
    
    print("=" * 60)
    print(f"📥 Downloading traffic count PDFs for {len(segments)} segments")
    print("=" * 60 + "\n")
    
    successful = 0
    failed = 0
    
    for i, segment in enumerate(segments, 1):
        attributes = segment.get("attributes", {})
        street_name = attributes.get("NAME") or attributes.get("STREETFORM", f"Segment_{i}")
        street_code = attributes.get("STCODE", "")
        objectid = attributes.get("OBJECTID", i)
        
        output_file = OUTPUT_DIR / f"document_{i:04d}_{objectid}_{street_code}.pdf"
        
        # Skip if already exists
        if output_file.exists():
            print(f"[{i}/{len(segments)}] ⏭️  {street_name} (exists)")
            continue
        
        print(f"[{i}/{len(segments)}] 📄 {street_name}...", end=" ", flush=True)
        
        if fetch_document_by_street(street_name, str(output_file)):
            file_size = output_file.stat().st_size / 1024
            print(f"✅ ({file_size:.1f} KB)")
            successful += 1
        else:
            print(f"❌")
            failed += 1
            if output_file.exists():
                output_file.unlink()
        
        # Rate limiting
        time.sleep(0.3)
    
    print(f"\n" + "=" * 60)
    print(f"Results: {successful} downloaded, {failed} failed")
    print("=" * 60 + "\n")


def save_segment_list(segments: List[Dict]) -> None:
    """Save segment list for reference."""
    segment_list = []
    
    for i, segment in enumerate(segments, 1):
        attributes = segment.get("attributes", {})
        segment_list.append({
            "index": i,
            "objectid": attributes.get("OBJECTID"),
            "name": attributes.get("NAME"),
            "streetform": attributes.get("STREETFORM"),
            "stcode": attributes.get("STCODE"),
            "rmstation": attributes.get("RMSTATION")
        })
    
    list_file = OUTPUT_DIR / "segment_list.json"
    with open(list_file, 'w') as f:
        json.dump(segment_list, f, indent=2)
    
    print(f"✅ Segment list saved to: {list_file}\n")


def main():
    """Main execution."""
    
    print("=" * 60)
    print("Traffic Count PDF Downloader - Street-Based")
    print("=" * 60 + "\n")
    
    # Step 1: Fetch segments
    segments = fetch_segments()
    if not segments:
        print("❌ No segments found. Exiting.\n")
        return 1
    
    # Step 2: Save segment list
    print("💾 Saving segment list...")
    save_segment_list(segments)
    
    # Step 3: Download by street name
    print("Starting downloads...\n")
    batch_download_by_street_names(segments)
    
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Segments processed: {len(segments)}")
    print(f"Output directory: {OUTPUT_DIR.absolute()}")
    print("\nFiles created:")
    print(f"  • segment_list.json - All segments")
    print(f"  • document_*.pdf - Downloaded PDFs")
    print("\nTo check results:")
    print(f"  ls {OUTPUT_DIR}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
