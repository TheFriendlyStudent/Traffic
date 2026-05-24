#!/usr/bin/env python3
"""
Traffic Count PDF Downloader - Reference Page Method
Fetches the OnBase public records reference page to find all available documents.
Then downloads each one.
"""

import requests
import json
import time
from pathlib import Path
from typing import List, Dict, Any, Set
import sys
import re
from urllib.parse import quote, urljoin

OUTPUT_DIR = Path("traffic_data")
OUTPUT_DIR.mkdir(exist_ok=True)

ONBASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Referer": "https://onbasepublic.glastonbury-ct.gov/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_segments() -> List[Dict]:
    """Fetch all segments from ArcGIS."""
    print("🔍 Querying ArcGIS for all segments...")
    
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
        print(f"❌ Error: {e}\n")
        return []


def extract_document_hashes_from_search() -> Dict[str, str]:
    """
    Query the OnBase public records search to find all available traffic count documents.
    Returns a mapping of street names to document hashes.
    """
    
    print("🔎 Searching OnBase for available documents...\n")
    
    documents = {}
    
    # Method 1: Try the API search endpoint
    try:
        # OnBase public search API
        search_url = "https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/DocumentSearch"
        
        search_params = {
            "documentType": "Traffic Count",
            "searchText": "*",
            "resultCount": "1000",
            "f": "json"
        }
        
        response = requests.get(
            search_url,
            params=search_params,
            headers=ONBASE_HEADERS,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                results = data.get("results", [])
                
                for result in results:
                    doc_id = result.get("DocumentID") or result.get("ID") or result.get("Hash")
                    title = result.get("Title") or result.get("DocumentName") or ""
                    
                    if doc_id:
                        documents[title] = doc_id
                        print(f"  Found: {title[:50]}... → {str(doc_id)[:30]}...")
                
                print(f"\n✅ Found {len(documents)} documents via API\n")
                return documents
            except:
                pass
    except:
        pass
    
    # Method 2: Try fetching the directory/list page
    print("  Trying alternative method...")
    try:
        list_url = "https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/index.html"
        
        response = requests.get(
            list_url,
            headers=ONBASE_HEADERS,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            html = response.text
            
            # Extract document hashes from HTML
            # Pattern: data-doc-id="..." or similar
            hash_pattern = r'(AdzJUwDCr1WBUTV48f%C3[^"\'<>]+?%3D)'
            hashes = re.findall(hash_pattern, html)
            
            if hashes:
                for i, hash_val in enumerate(set(hashes), 1):
                    documents[f"Document_{i}"] = hash_val
                    print(f"  Found hash #{i}: {hash_val[:50]}...")
                
                print(f"\n✅ Found {len(documents)} documents via HTML parsing\n")
                return documents
    except:
        pass
    
    return documents


def fetch_document_pdf(doc_hash: str, output_file: str) -> bool:
    """Fetch a PDF document from OnBase."""
    
    try:
        url = f"https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document/{doc_hash}/"
        
        # Use GET request with browser headers
        response = requests.get(
            url,
            headers=ONBASE_HEADERS,
            timeout=30,
            stream=True,
            verify=False,
            allow_redirects=True
        )
        
        if response.status_code != 200:
            return False
        
        content_type = response.headers.get('content-type', '').lower()
        
        if 'application/json' in content_type or response.text.strip().startswith('{'):
            return False
        
        # Save the document
        with open(output_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        file_size = Path(output_file).stat().st_size
        return file_size > 1000
        
    except Exception as e:
        return False


def search_and_download_all() -> None:
    """Main flow: search for documents and download all."""
    
    print("=" * 60)
    print("🔎 Step 1: Searching for all available documents")
    print("=" * 60 + "\n")
    
    documents = extract_document_hashes_from_search()
    
    if not documents:
        print("\n⚠️  No documents found via search")
        print("Falling back to known document...\n")
        # Use the sample document we know works
        documents = {
            "MAIN ST Traffic Count": "AdzJUwDCr1WBUTV48f%C3%81mNHVPlw%C3%81nk3pnW%C3%818C2UMXr8dOkFC02SXgofIbbgNNkFzRworVow8jJzlWMI%C3%81pn1Rtm8k%3D"
        }
    
    print("=" * 60)
    print(f"📥 Step 2: Downloading {len(documents)} documents")
    print("=" * 60 + "\n")
    
    successful = 0
    failed = 0
    
    for i, (title, doc_hash) in enumerate(documents.items(), 1):
        output_file = OUTPUT_DIR / f"document_{i:04d}.pdf"
        
        if output_file.exists():
            print(f"[{i}/{len(documents)}] ⏭️  {title[:40]} (exists)")
            continue
        
        print(f"[{i}/{len(documents)}] 📄 {title[:40]}...", end=" ", flush=True)
        
        if fetch_document_pdf(doc_hash, str(output_file)):
            file_size = output_file.stat().st_size / 1024
            print(f"✅ ({file_size:.1f} KB)")
            successful += 1
        else:
            print(f"❌")
            failed += 1
            if output_file.exists():
                output_file.unlink()
        
        time.sleep(0.3)
    
    print(f"\n" + "=" * 60)
    print(f"Results: {successful} downloaded, {failed} failed")
    print("=" * 60 + "\n")


def main():
    """Main execution."""
    
    print("=" * 60)
    print("Traffic Count PDF Downloader")
    print("Method: OnBase Reference Search")
    print("=" * 60 + "\n")
    
    search_and_download_all()
    
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Output: {OUTPUT_DIR.absolute()}")
    print(f"Files: {list(OUTPUT_DIR.glob('document_*.pdf'))}")
    print("\nNext: Use the PDFs for further analysis")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
