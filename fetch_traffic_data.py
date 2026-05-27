#!/usr/bin/env python3
"""
Traffic Count PDF Downloader - CORRECT API Pattern
Uses the proper two-step process:
1. POST to get document metadata (JSON response)
2. Download PDF using returned ID

Example working request:
  POST https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document/{doc_hash}/
  Headers: Content-Type: application/json, etc.
  Body: {}
  Response: {"ID": "...", "Size": 33288, "ViewerMode": "PDF", ...}
"""

import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Optional
import sys
import argparse
from urllib.parse import quote

OUTPUT_DIR = Path("traffic_data")
OUTPUT_DIR.mkdir(exist_ok=True)

# Headers matching the working curl command
ONBASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/json",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Priority": "u=0",
    "TE": "trailers"
}

ONBASE_API = "https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document"
TIMEOUT = 30

def fetch_segments() -> List[Dict]:
    """Fetch all segments from ArcGIS."""
    print("📍 Querying ArcGIS Map Server for segments...")
    
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


def get_document_metadata(doc_hash: str) -> Optional[Dict]:
    """
    Step 1: POST to get document metadata.
    
    This returns JSON with document info like:
    {
        "ID": "Ab9yIBtXbJ0q8vdKSDMdvFilsNLvÁKU7isUhJgZM5YRTS5IGrU7ZfIS1gDSmÁ5ukJz9Á3Wd9Qb42waCdRYGrzWk=",
        "Size": 33288,
        "ViewerMode": "PDF",
        "IsAboveDownloadThreshold": false
    }
    """
    
    try:
        url = f"{ONBASE_API}/{doc_hash}/"
        
        # Set Origin and Referer
        headers = ONBASE_HEADERS.copy()
        headers["Origin"] = "https://onbasepublic.glastonbury-ct.gov"
        
        response = requests.post(
            url,
            headers=headers,
            json={},
            timeout=TIMEOUT,
            verify=False
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                return data
            except:
                return None
        
        return None
        
    except Exception as e:
        return None


def download_document_pdf(doc_hash: str, output_file: str, street_name: str = "") -> bool:
    """
    Download the PDF file using the document hash.
    Tries multiple methods to get the actual PDF.
    """
    
    output_file = str(output_file)  # Ensure it's a string
    
    try:
        # Method 1: Get metadata first (POST)
        metadata = get_document_metadata(doc_hash)
        
        if metadata:
            print(f"   ℹ Metadata: {metadata.get('Size', 'N/A')} bytes, {metadata.get('ViewerMode', 'N/A')}")
        
        # Method 2: Try GET request for PDF
        url = f"{ONBASE_API}/{doc_hash}/"
        
        headers = ONBASE_HEADERS.copy()
        headers["Accept"] = "*/*"  # Accept any content
        headers["Origin"] = "https://onbasepublic.glastonbury-ct.gov"
        if street_name:
            headers["Referer"] = f"https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/index.html?OBKey__102_1={street_name}"
        
        response = requests.get(
            url,
            headers=headers,
            timeout=TIMEOUT,
            stream=True,
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            
            # Check if we got a PDF
            if 'application/pdf' in content_type or 'application/octet-stream' in content_type:
                with open(output_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = Path(output_file).stat().st_size
                if file_size > 1000:
                    return True
                else:
                    Path(output_file).unlink()
            elif 'application/json' in content_type:
                # Try POST method instead
                pass
        
        # Method 3: Try POST for PDF (direct body)
        response = requests.post(
            url,
            headers=ONBASE_HEADERS,
            json={},
            timeout=TIMEOUT,
            stream=True,
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '').lower()
            
            if 'application/pdf' in content_type or 'application/octet-stream' in content_type:
                with open(output_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = Path(output_file).stat().st_size
                if file_size > 1000:
                    return True
                else:
                    Path(output_file).unlink()
    
    except Exception as e:
        pass
    
    return False


def batch_download(doc_hashes: Dict[str, str]) -> None:
    """Download multiple documents."""
    
    print("=" * 70)
    print(f"📥 DOWNLOADING {len(doc_hashes)} DOCUMENTS")
    print("=" * 70 + "\n")
    
    successful = 0
    failed = 0
    
    for i, (street_name, doc_hash) in enumerate(doc_hashes.items(), 1):
        output_file = OUTPUT_DIR / f"document_{i:04d}_{street_name[:20]}.pdf"
        
        if output_file.exists():
            print(f"[{i:3d}/{len(doc_hashes)}] ⏭️  {street_name:40s} (exists)")
            successful += 1
            continue
        
        print(f"[{i:3d}/{len(doc_hashes)}] 📄 {street_name:40s}...", end=" ", flush=True)
        
        if download_document_pdf(doc_hash, str(output_file), street_name):
            file_size = output_file.stat().st_size / 1024
            print(f"✅ ({file_size:.1f} KB)")
            successful += 1
        else:
            print(f"❌")
            failed += 1
            if output_file.exists():
                output_file.unlink()
        
        time.sleep(0.2)
    
    print(f"\n" + "=" * 70)
    print(f"Results: {successful} downloaded, {failed} failed")
    print("=" * 70 + "\n")

def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Download traffic count PDFs from OnBase (Glastonbury, CT)"
    )
    parser.add_argument("--doc-id", help="Specific document hash to fetch")
    parser.add_argument("--batch", action="store_true", help="Batch download from hashes_file")
    parser.add_argument("--hashes-file", default="document_hashes.txt", help="File with doc hashes (format: StreetName|DocumentHash)")
    parser.add_argument("--test", action="store_true", help="Test with known working document")
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("TRAFFIC COUNT PDF DOWNLOADER - CORRECTED API METHOD")
    print("=" * 70 + "\n")
    
    # Test mode with known working document
    if args.test:
        print("🧪 Testing with known working document hash...\n")
        test_hash = "AdzJUwDCr1WBUTV48f%C3%81mNHVPlw%C3%81nk3pnW%C3%818C2UMXr8dOkFC02SXgofIbbgNNkFzRworVow8jJzlWMI%C3%81pn1Rtm8k%3D"
        test_file = OUTPUT_DIR / "test_document.pdf"
        
        print("📄 Fetching metadata...")
        metadata = get_document_metadata(test_hash)
        
        if metadata:
            print(f"✅ Got metadata:")
            print(f"   ID: {metadata.get('ID', 'N/A')[:50]}...")
            print(f"   Size: {metadata.get('Size', 'N/A')} bytes")
            print(f"   Type: {metadata.get('ViewerMode', 'N/A')}")
            print(f"   Download Threshold: {metadata.get('IsAboveDownloadThreshold', 'N/A')}\n")
            
            print("📥 Downloading PDF...")
            if download_document_pdf(test_hash, str(test_file), "MAIN ST"):
                file_size = test_file.stat().st_size / 1024
                print(f"✅ Successfully downloaded ({file_size:.1f} KB)\n")
            else:
                print("❌ Failed to download PDF\n")
        else:
            print("❌ Failed to get metadata\n")
        
        return 0
    
    # Single document fetch
    if args.doc_id:
        output_file = OUTPUT_DIR / f"document_{hash(args.doc_id) % 10000}.pdf"
        print(f"📥 Downloading document: {args.doc_id[:50]}...\n")
        if download_document_pdf(args.doc_id, str(output_file)):
            print(f"\n✅ Downloaded to {output_file}\n")
        else:
            print(f"\n❌ Failed to download\n")
        return 0
    
    # Batch mode
    if args.batch:
        if not Path(args.hashes_file).exists():
            print(f"❌ File not found: {args.hashes_file}\n")
            print("Format: Each line should contain:")
            print("  StreetName|DocumentHash")
            print("\nExample:")
            print("  MAIN ST|AdzJUwDCr1WBUTV48f%C3%81mNHVPlw...")
            return 1
        
        # Read document hashes
        doc_hashes = {}
        with open(args.hashes_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if '|' in line:
                    street, doc_hash = line.split('|', 1)
                    doc_hashes[street.strip()] = doc_hash.strip()
        
        if not doc_hashes:
            print(f"❌ No document hashes found in {args.hashes_file}\n")
            return 1
        
        batch_download(doc_hashes)
        
        print("=" * 70)
        print("Summary")
        print("=" * 70)
        print(f"Documents processed: {len(doc_hashes)}")
        print(f"Output directory: {OUTPUT_DIR.absolute()}")
        pdf_files = list(OUTPUT_DIR.glob("document_*.pdf"))
        print(f"PDFs created: {len(pdf_files)}")
        
        return 0
    
    # Default: Show help
    print("📖 Usage:\n")
    print(f"  {Path(__file__).name} --test")
    print(f"    Test with known working document\n")
    print(f"  {Path(__file__).name} --doc-id <hash>")
    print(f"    Download single document\n")
    print(f"  {Path(__file__).name} --batch")
    print(f"    Batch download from {args.hashes_file}\n")
    print("Example hashes_file format:")
    print("  # Comment line")
    print("  MAIN ST|AdzJUwDCr1WBUTV48f%C3%81...")
    print("  CHURCH ST|BxzKVyFdS2XCVUW59g%D4%92...")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
