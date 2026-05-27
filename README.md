# Glastonbury Traffic Analysis System

Automated traffic data collection and analysis for Glastonbury, CT using public OnBase records and ArcGIS data.

## Overview

This project integrates two data sources:
1. **ArcGIS Map Server** - Street segment geometry and metadata
2. **OnBase Public Access** - PDF traffic count reports

It provides tools for:
- Automated PDF download from OnBase
- Road network graph analysis
- Volume/Capacity (V/C) ratio calculations
- Year-over-year traffic trend analysis
- Traffic bottleneck identification

## Quick Start

### 1. Test the API Connection

```bash
python fetch_traffic_data.py --test
```

This validates the OnBase API is working and can fetch documents.

### 2. Get Ready for Batch Download

Create `document_hashes.txt` with street-to-hash mappings:

```
# Format: STREET_NAME|DOCUMENT_HASH
MAIN ST|AdzJUwDCr1WBUTV48f%C3%81mNHVPlw%C3%81nk3pnW%C3%818C2UMXr8dOkFC02SXgofIbbgNNkFzRworVow8jJzlWMI%C3%81pn1Rtm8k%3D
GROVE ST|Ab9yIBtXbJ0q8vdKSDMdvFilsNLv%C3%81KU7isUhJgZM5YRTS5IGrU7ZfIS1gDSm%C3%815ukJz9%C3%813Wd9Qb42waCdRYGrzWk%3D
```

### 3. Batch Download PDFs

```bash
python fetch_traffic_data.py --batch
```

Downloads all documents to `traffic_data/document_*.pdf`

### 4. Analyze Results

```bash
python traffic_analysis.py
```

Generates traffic analysis, V/C ratios, and trends.

## Scripts

### fetch_traffic_data.py

Downloads traffic count PDFs from OnBase using the corrected API pattern.

**Usage:**
```bash
# Test with known working document
python fetch_traffic_data.py --test

# Download single document
python fetch_traffic_data.py --doc-id "<document_hash>"

# Batch download using document_hashes.txt
python fetch_traffic_data.py --batch

# Specify custom hashes file
python fetch_traffic_data.py --batch --hashes-file custom_hashes.txt
```

**Key Functions:**
- `fetch_segments()` - Get all segments from ArcGIS
- `get_document_metadata(doc_hash)` - Retrieve document metadata
- `download_document_pdf(doc_hash, output_file)` - Download PDF
- `batch_download(doc_hashes)` - Download multiple documents

### traffic_analysis.py

Advanced traffic analysis using road network graphs and statistical methods.

**Features:**
- Road network as directed weighted graph (NetworkX)
- V/C (Volume/Capacity) ratio calculations
- Bottleneck detection
- Year-over-year traffic comparison
- Traffic trend analysis

**Usage:**
```bash
python traffic_analysis.py
```

**Key Classes:**
- `TrafficNetwork` - Graph-based road network representation
- `TrafficDataAnalyzer` - Multi-year analysis and trends

### scripty.py

Original script for detecting and analyzing traffic segments.

## API Documentation

### OnBase API Pattern

**Step 1: Get Metadata**
```
POST https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document/{doc_hash}/
Headers: Content-Type: application/json, Sec-Fetch-Mode: cors
Body: {}
Response: {"ID": "...", "Size": 33288, "ViewerMode": "PDF", ...}
```

**Step 2: Download PDF**
```
GET https://onbasepublic.glastonbury-ct.gov/PublicAccess/api/Document/{doc_hash}/
Headers: Accept: */*
Response: PDF file (binary)
```

See `API_IMPLEMENTATION_GUIDE.md` for detailed reference.

## Data Files

| File | Purpose | Status |
|------|---------|--------|
| `traffic_data/segments.json` | All street segments (~127) | ✅ Complete |
| `traffic_data/features.json` | ArcGIS feature data | ✅ Complete |
| `traffic_data/document_*.pdf` | Downloaded PDFs | ❌ Need hashes |
| `glastonbury_aadt.csv` | Annual Average Daily Traffic | ✅ Available |
| `document_hashes.txt` | Street-to-hash mapping | ❌ Needed |

## Architecture

```
┌─────────────────────────────────────────┐
│  ArcGIS Map Server                      │
│  (Street segments)                      │
└──────────────┬──────────────────────────┘
               │
       ┌───────▼────────┐
       │  segments.json │
       └────────┬───────┘
                │
    ┌───────────┴─────────────┐
    │  fetch_traffic_data.py  │
    │  (Corrected OnBase API) │
    └───────────┬─────────────┘
                │
    ┌───────────▼──────────────┐
    │  PDF Files              │
    │  (traffic_data/*.pdf)   │
    └───────────┬──────────────┘
                │
    ┌───────────▼──────────────┐
    │ traffic_analysis.py      │
    │ (V/C, Trends, Graphs)   │
    └──────────────────────────┘
```

## Key Findings

1. **API Corrected** - OnBase requires JSON POST + GET (not GET alone)
2. **All Segments Available** - 127 street segments retrieved from ArcGIS
3. **Document Hashes Required** - Need mapping from streets to OnBase IDs
4. **URL Encoding Matters** - Hashes use UTF-8 percent encoding (e.g., %C3%81 = Á)

## Next Steps

1. **Find document hashes** for remaining ~125 streets
   - Use OnBase search API
   - Web scraping of public interface
   - Manual lookup via browser
   - Contact Glastonbury public records

2. **Create `document_hashes.txt`** with all street-to-hash mappings

3. **Run batch download** to collect all PDFs

4. **Analyze traffic** using traffic_analysis.py

## Requirements

Python 3.7+

**Dependencies:**
- requests (HTTP)
- networkx (graph analysis)
- numpy (statistics)
- pathlib (file operations)

Install:
```bash
pip install requests networkx numpy
```

## SSL Warning

You may see:
```
InsecureRequestWarning: Unverified HTTPS request is being made to host 'onbasepublic.glastonbury-ct.gov'
```

This is safe to ignore for this public API.

## Files

### Core Scripts
- `fetch_traffic_data.py` - Main PDF downloader
- `traffic_analysis.py` - Analysis tools
- `scripty.py` - Original segment detector

### Documentation
- `README.md` - This file
- `API_IMPLEMENTATION_GUIDE.md` - API reference
- `CURRENT_STATUS.md` - Project status and blockers

### Data
- `traffic_data/` - Downloaded data directory
- `document_hashes.txt` - Street-to-document mapping (create this)

## References

- OnBase Public Access: https://onbasepublic.glastonbury-ct.gov/PublicAccess/
- Traffic Count Records: https://onbasepublic.glastonbury-ct.gov/PavClient/PublicRecordTrafficCount/
- ArcGIS Map Server: https://gisarc2022.glastonbury-ct.gov/server/rest/services/GlastonburyPublic/StreetsExB/

## Status

| Component | Status |
|-----------|--------|
| API Connection | ✅ Fixed & Verified |
| Segment Retrieval | ✅ All 127 retrieved |
| PDF Download Code | ✅ Ready |
| Document Hashes | ❌ Blocking issue |
| Analysis Tools | ✅ Ready |
| Batch Processing | ⏳ Awaiting hashes |

---

**Last Updated:** 2025  
**Project Status:** API Fixed - Awaiting Document Hash Discovery
