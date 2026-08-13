File 1: SYSTEM\_CONTEXT.md (The Master Document)

This is the most important file. Create it in C:\\Smart\_planogram\\SYSTEM\_CONTEXT.md:



Markdown



\# Smart Planogram Planner — Complete System Context



\## 1. WHAT THIS SYSTEM DOES



This is an AI-powered visual audit system for J24 retail store chillers (refrigerators).



\*\*The Problem:\*\*

Every morning, a store staff member checks the chiller arrangement. Currently they take a WhatsApp photo, send it to a backend person, who eyeballs it and gives verbal instructions. This is inconsistent, slow, and unscalable.



\*\*The Solution:\*\*

Staff uploads a chiller photo → system automatically detects what products are where → compares against the ideal reference layout → generates a compliance score (0-10) and specific correction instructions.



\*\*Current Scope:\*\*

\- 1 store: J24 BTM Layout, Bangalore

\- 1 rack: Beverage Chiller (Rack ID: BTM-CH01)

\- 6 shelves with \~46-52 beverage products

\- Pilot phase — proving the concept works before scaling



\---



\## 2. ARCHITECTURE OVERVIEW

Staff Photo (JPEG)

│

▼

\[Image Quality Check] ── reject if blurry/dark/low-res

│

▼

\[OCR Shelf Detection] ── find S-1 through S-6 labels using EasyOCR

│

▼

\[Shelf Cropping] ── split image into 6 shelf strips using midpoint boundaries

│

▼

\[AI Product Detection] ── send 6 shelf crops to Vision LLM in ONE API call

│ returns structured JSON with product IDs per shelf

▼

\[Sanity Validation] ── reject if AI hallucinated (>12 products per shelf, etc.)

│

▼

\[Comparison Engine] ── diff actual\_map vs expected\_map (locked reference)

│

▼

\[Scoring Engine] ── percentage-based score + priority-ranked corrections

│

▼

\[Staff Report] ── WhatsApp-ready formatted message with top 5 fixes



text





\### Key Design Principle

\*\*AI only detects "what is there." All judgment about "is this correct?" is done by deterministic code (comparison engine + rules).\*\* This separation is critical — it means rules can change without retraining AI, and AI can be swapped without touching business logic.



\---



\## 3. TECHNOLOGY STACK



| Component | Technology | Purpose |

|-----------|-----------|---------|

| Language | Python 3.11+ | All backend code |

| OCR | EasyOCR | Detect shelf label positions (S-1 through S-6) |

| Image Processing | OpenCV (cv2) | Image quality checks, shelf cropping |

| Vision AI (current) | Google Gemini 3.5 Flash Lite | Product detection per shelf (free tier, has hallucination issues) |

| Vision AI (planned) | OpenAI GPT-4o or Anthropic Claude | Better accuracy, \~$0.02/audit |

| Data Storage | Excel (.xlsx) for pilot | Product catalog, reference layout |

| Data Storage (planned) | PostgreSQL / Supabase | For production scale |

| Web Framework (planned) | Streamlit | Staff-facing web interface |

| Version Control | Git + GitHub | Code management |

| Deployment (planned) | Streamlit Cloud (free) | Public URL for staff access |



\### API Keys Required

\- `GOOGLE\_API\_KEY` — Google AI Studio (for Gemini models)

\- `OPENAI\_API\_KEY` — OpenAI Platform (for GPT-4o, when approved)

\- Set as Windows environment variables: `setx KEY\_NAME "value"`, then reopen terminal



\---



\## 4. PROJECT STRUCTURE

Smart\_planogram/

│

├── SYSTEM\_CONTEXT.md ← THIS FILE (you're reading it)

├── README.md ← Quick overview + setup instructions

├── requirements.txt ← Python package dependencies

├── .gitignore ← Files excluded from Git

│

├── data/

│ ├── products.xlsx ← Master product catalog (52 SKUs currently)

│ ├── reference\_layout.xlsx ← Ideal shelf placement per rack

│ ├── chiller\_rules.json ← Machine-readable merchandising rules (10 rule types)

│ ├── expected\_map\_BTM\_CH01.json ← LOCKED verified reference map (ground truth)

│ ├── shelf\_boundaries.json ← OCR-detected label positions from reference image

│ ├── shelf\_crops.json ← Metadata about reference shelf crops

│ ├── actual\_maps/ ← AI-generated maps from staff photos

│ │ ├── actual\_map\_shelfmessing.json

│ │ ├── actual\_map\_wrongshelf.json

│ │ └── ... (one per photo processed)

│ ├── comparisons/ ← Comparison results (expected vs actual)

│ │ ├── comparison\_shelfmessing.json

│ │ └── ...

│ ├── reports/ ← Final audit reports

│ │ ├── whatsapp\_shelfmessing.txt ← Staff-facing message

│ │ ├── detailed\_shelfmessing.txt ← Full detailed report

│ │ └── summary\_shelfmessing.json ← Machine-readable summary

│ └── audit\_logs/ ← Audit execution logs

│

├── images/

│ ├── reference/

│ │ └── BTM-CH01\_reference.jpeg ← Gold-standard reference photo

│ ├── products/ ← Individual product images (48 files)

│ │ ├── Amul Kool Cafe 180ml\_\_AMUL\_KOOL\_CAFE\_180.webp

│ │ └── ... (naming: "Display Name\_\_PRODUCT\_ID.ext")

│ ├── shelves/ ← Auto-generated shelf crops from reference

│ │ ├── shelf\_1.jpg through shelf\_6.jpg

│ │ └── \_debug\_boundaries.jpg ← Visual debug of crop boundaries

│ ├── staff\_uploads/ ← Test photos from real store

│ │ ├── shelfmessing.jpeg ← Messy chiller (primary test case)

│ │ ├── wrongshelf.jpeg ← Products on wrong shelves

│ │ ├── missingproduct.jpeg ← Products deliberately missing

│ │ ├── poorlight.jpeg ← Poor lighting scenario

│ │ ├── poorlight2.jpeg ← Dim lighting scenario

│ │ ├── tilted.jpeg ← Tilted camera angle

│ │ ├── tooclose.jpeg ← Photo taken too close

│ │ └── shelfblocked.jpeg ← Shelf partially blocked

│ ├── staff\_processing/ ← Auto-generated crops from staff photos

│ │ ├── shelfmessing/shelf\_1.jpg through shelf\_6.jpg

│ │ └── ...

│ └── debug/ ← Debug visualizations

│

└── scripts (all .py files in root)/

├── audit\_chiller.py ← MAIN ENTRY POINT — runs full pipeline

├── process\_staff\_photo.py ← Stage 1-3: image → AI → actual\_map.json

├── validate\_actual\_map.py ← Stage 4: sanity check on AI output

├── compare\_engine.py ← Stage 5: diff expected vs actual

├── scoring\_engine.py ← Stage 6: score + priority + formatted report

├── validate\_files.py ← Data hygiene: check catalog/rules consistency

├── validate\_json.py ← JSON syntax checker for expected\_map

├── check\_expected\_map.py ← Validate the locked reference map

├── test\_ocr.py ← Test EasyOCR on reference image

├── crop\_shelves.py ← Crop reference image into 6 shelf strips

├── analyze\_shelves\_gemini.py ← Extract reference map using Gemini

├── image\_quality\_check.py ← Standalone image quality tester

├── list\_gemini\_models.py ← Utility: list available Gemini models

├── debug\_shelf\_positions.py ← Debug: compare label positions between photos

├── diagnose\_ids.py ← Debug: find product ID mismatches

└── test\_openai.py ← Test OpenAI API connection



text





\---



\## 5. DATA SCHEMAS



\### 5.1 Product Catalog (`products.xlsx`)



| Column | Type | Description | Example |

|--------|------|-------------|---------|

| product\_id | string (PK) | Unique ID, format: BRAND\_VARIANT\_SIZE | COCACOLA\_250 |

| product\_name | string | Display name | Coca-Cola 250ml |

| brand | string | Brand name | Coca-Cola |

| commodity | string | Category (must match rules) | soft\_drink |

| pack\_size\_ml | integer | Volume in ml | 250 |

| price\_point | integer | Price in ₹ | 20 |

| colour\_tone | string | dark / light | dark |

| size\_band | string | small / medium / large | small |

| is\_fast\_moving | boolean | High sales velocity | TRUE |

| is\_high\_margin | boolean | High profit margin | TRUE |

| is\_water | boolean | Is plain water | FALSE |

| package\_type | string | PET / can / tetra / carton | PET |

| image\_url | string | Path to product image | images/products/... |



\*\*Commodity values (must match chiller\_rules.json):\*\*

\- `fruit\_beverage` — juices, fruit drinks

\- `energy\_drink` — energy drinks

\- `soft\_drink` — carbonated soft drinks

\- `milk\_beverage` — flavored milk, protein drinks, buttermilk

\- `water` — plain water



\### 5.2 Chiller Rules (`chiller\_rules.json`)



Contains 10 rule types:



| Rule ID | Type | Description | Severity |

|---------|------|-------------|----------|

| CHILLER\_SHELF\_COMMODITY | shelf\_commodity | Each shelf has designated product types | high |

| CHILLER\_COLOUR\_FLOW | colour\_zone | Dark products left, light products right | medium |

| CHILLER\_PACK\_SIZE\_FLOW | pack\_size\_zone | Small packs left, large packs right | medium |

| CHILLER\_ROW\_UNIFORMITY | row\_uniformity | Price-point rows should have similar sizes | low |

| CHILLER\_PRIORITY\_PLACEMENT | priority\_visibility | Fast-moving/high-margin products get priority zones | medium |

| CHILLER\_TETRA\_CORNER | tetra\_pack\_corner | Tetra packs at shelf corners | low |

| CHILLER\_WATER\_PLACEMENT | water\_placement | Water bottles on Shelf 6 right side | high |

| CHILLER\_FACING\_LOGIC | facing\_allocation | Each product gets 1 facing first; extras only for fast-movers | medium |

| CHILLER\_BRAND\_MULTI\_SIZE | brand\_multi\_facing\_exception | Same brand can have facings on multiple shelves for different pack sizes | low |

| CHILLER\_OOS\_REPLACEMENT | out\_of\_stock\_replacement | OOS products can be replaced if substitute matches commodity, colour, and size | medium |



\*\*Shelf commodity map (hard rule):\*\*

\- Shelf 1: Fruit Beverages

\- Shelf 2: Energy Drinks

\- Shelf 3: Soft Drinks (₹20 packs)

\- Shelf 4: Milk Beverages

\- Shelf 5: Fruit \& Soft Drinks (₹10 packs)

\- Shelf 6: Soft Drinks (750ml+) + Water



\### 5.3 Expected Map (`expected\_map\_BTM\_CH01.json`)



Human-verified ground truth. Structure:

```json

{

&#x20; "rack\_id": "BTM-CH01",

&#x20; "extraction\_status": "VERIFIED - locked reference",

&#x20; "shelves": \[

&#x20;   {

&#x20;     "shelf\_number": 1,

&#x20;     "expected\_commodities": \["fruit\_beverage"],

&#x20;     "products": \[

&#x20;       {

&#x20;         "product\_id": "MAAZA\_150",

&#x20;         "zone": "left",

&#x20;         "facings": 1,

&#x20;         "confidence": "verified"

&#x20;       }

&#x20;     ]

&#x20;   }

&#x20; ]

}

5.4 Actual Map (actual\_map\_\*.json)

AI-generated from staff photo. Same structure as expected map plus:



JSON



{

&#x20; "source\_image": "images/staff\_uploads/shelfmessing.jpeg",

&#x20; "processed\_at": "2026-08-13T16:11:39",

&#x20; "model\_used": "gemini-3.5-flash-lite",

&#x20; "api\_calls\_used": 1,

&#x20; "shelves": \[...]

}

5.5 Comparison Result (comparison\_\*.json)

JSON



{

&#x20; "rack\_id": "BTM-CH01",

&#x20; "violation\_counts": {"high": 9, "medium": 11, "low": 0, "info": 0, "total": 20},

&#x20; "violations": \[

&#x20;   {

&#x20;     "type": "missing\_product",

&#x20;     "severity": "high",

&#x20;     "product\_id": "PEPSI\_1250",

&#x20;     "product\_name": "Pepsi 1.25L",

&#x20;     "description": "Pepsi 1.25L is missing from the chiller",

&#x20;     "correction": "Add Pepsi 1.25L to Shelf 6 (left zone)"

&#x20;   }

&#x20; ]

}

5.6 Audit Report Summary (summary\_\*.json)

JSON



{

&#x20; "rack\_id": "BTM-CH01",

&#x20; "score": 6.3,

&#x20; "status": "🟡 NEEDS ATTENTION",

&#x20; "violation\_counts": {...},

&#x20; "top\_fixes": \[

&#x20;   {"priority": 1, "type": "missing\_product", "correction": "Add Pepsi 1.25L to Shelf 6"}

&#x20; ]

}

6\. PIPELINE SCRIPTS — DETAILED

6.1 audit\_chiller.py — THE MAIN ENTRY POINT

What it does: Orchestrates the full audit pipeline end-to-end.



Usage:



Bash



\# Audit a single photo

python audit\_chiller.py images/staff\_uploads/shelfmessing.jpeg



\# Audit all test photos

python audit\_chiller.py

Flow:



Calls process\_photo() from process\_staff\_photo.py

Calls validate\_actual\_map() — rejects if AI hallucinated

Calls compare\_maps() from compare\_engine.py

Calls generate\_audit\_report() from scoring\_engine.py

Returns structured result with score, violations, WhatsApp message

Outputs:



data/actual\_maps/actual\_map\_<name>.json

data/comparisons/comparison\_<name>.json

data/reports/whatsapp\_<name>.txt

data/reports/detailed\_<name>.txt

data/reports/summary\_<name>.json

data/audit\_logs/audit\_<timestamp>.json

6.2 process\_staff\_photo.py — Image Processing + AI Detection

What it does: Takes a raw staff photo, processes it through quality checks, OCR, cropping, and AI analysis.



Key functions:



check\_image\_quality(path) — blur/brightness/resolution check

detect\_shelves\_via\_ocr(path) — finds S-1 to S-6 labels using EasyOCR

get\_shelf\_positions(path) — OCR with fallback to reference positions

crop\_shelves(path, positions, folder) — midpoint-based cropping into 6 strips

analyze\_all\_shelves\_one\_call(crops, catalog, rules) — sends 6 images to Vision LLM in ONE API call

process\_photo(path) — orchestrates all of the above

Important technical details:



Shelf cropping uses MIDPOINT boundaries between label positions (not fixed offsets)

This handles varying camera distances/angles across different staff photos

If OCR detects <4 shelves, uses fallback Y-coordinates from reference image

The AI prompt explicitly tells the model NOT to combine products across shelf images

Each shelf crop is saved for debugging in images/staff\_processing/<photo\_name>/

AI Model Configuration:



Python



MODEL\_NAME = "gemini-3.5-flash-lite"  # Current (free but hallucination-prone)

\# Planned upgrade to: "gpt-4o" (OpenAI) or "claude-3-5-sonnet" (Anthropic)

Horizontal crop boundaries (hardcoded for this specific chiller):



Python



CROP\_LEFT = 350   # Skip shelf label column on left

CROP\_RIGHT = 1150 # Skip glass edge on right

6.3 validate\_actual\_map.py — Post-AI Sanity Check

What it does: Catches AI hallucinations before they cause false audit results.



Checks performed:



Per-shelf product count ≤ 12 (critical if exceeded)

Duplicate product IDs on same shelf (warning)

Excessive facings per product ≤ 5 (warning)

Total products 5-65 range (critical if outside)

Total products < 20 (warning — unusually low)

If REJECT: Returns a staff-friendly message asking them to retake the photo with specific guidance.



6.4 compare\_engine.py — Expected vs Actual Comparison

What it does: Diffs the expected reference map against the AI-detected actual map.



Violation types detected:



Type	Severity	When

missing\_product	high	Product expected but not found anywhere

missing\_product\_partial	medium	Product on some expected shelves but not all

wrong\_shelf	high	Product found on incorrect shelf

duplicate\_on\_wrong\_shelf	medium	Product on correct shelf AND extra wrong shelves

wrong\_zone	medium	Right shelf but wrong position (left/center/right)

low\_facing	medium	Fewer facings than expected

excess\_facing\_non\_fast\_moving	low	Extra facings for slow-moving product

wrong\_commodity\_on\_shelf	high	Product category doesn't match shelf designation

unknown\_product	medium	Product detected but not in catalog

low\_confidence\_detection	info	AI uncertain about detection

Multi-shelf product handling:

Products like Raskik can legitimately appear on Shelf 1 AND Shelf 5 (different pack sizes). The engine handles this by:



Checking which expected locations are satisfied

Generating ONE consolidated "move" message (not contradictory per-location messages)

Using "Shelf X OR Shelf Y" wording when multiple valid locations exist

6.5 scoring\_engine.py — Score + Priority + Reports

Scoring formula (percentage-based):



text



properly\_placed = total\_expected - count\_of\_problem\_products

base\_score = (properly\_placed / total\_expected) \* 10

minor\_deductions = 0.15 per wrong\_zone + 0.10 per facing\_issue (capped at 2.0)

commodity\_penalty = 0.5 per wrong\_commodity\_on\_shelf (capped at 1.5)

final\_score = max(1.0, base\_score - minor\_deductions - commodity\_penalty)

Score interpretation:



Score	Status	Meaning

9.0-10.0	🌟 EXCELLENT	Rack meets high standards

7.5-8.9	✅ GOOD	Minor improvements needed

6.0-7.4	🟡 NEEDS ATTENTION	Several issues to address

4.0-5.9	🟠 POOR	Major reorganization needed

1.0-3.9	🔴 CRITICAL	Immediate action required

Priority ranking: Violations are ranked by type priority (wrong\_commodity > missing > wrong\_shelf > wrong\_zone > facing) then by severity. Top 5 are shown to staff.



Output formats:



WhatsApp text — emoji-based, mobile-friendly, copy-paste ready

Detailed report — full breakdown by violation type

JSON summary — machine-readable for dashboards

7\. KNOWN ISSUES AND LIMITATIONS

7.1 AI Model Quality

Current model (gemini-3.5-flash-lite) occasionally hallucinates — reports products from adjacent shelves together, especially on photos taken at unusual angles

Sanity validator catches the worst cases but some subtle errors slip through

Fix: Switch to GPT-4o or Claude 3.5 Sonnet (pending management approval for \~$0.02/audit cost)

7.2 OCR Shelf Detection

OCR reads "S" as "5" sometimes (handled in code with normalization)

If fewer than 4 out of 6 shelf labels are detected, system uses fallback Y-coordinates from the reference image

Best results when shelf labels are clean, high-contrast (black text on white), and unobstructed

7.3 Hardcoded Crop Boundaries

CROP\_LEFT = 350 and CROP\_RIGHT = 1150 are specific to the BTM chiller dimensions

Will need adjustment for different chiller models or if the chiller is replaced

Future: auto-detect chiller boundaries using edge detection

7.4 Zone Assignment Sensitivity

"left/center/right" zone assignment is approximate (divide shelf width into thirds)

Products near zone boundaries may be assigned differently by AI vs reference

This generates false "wrong zone" violations — accepted as low-impact (medium severity)

7.5 Product Catalog Completeness

Currently 52 products. Needs expansion to 100-150 SKUs for production use

Catalog team to provide full product list with attributes

Missing products from catalog → AI reports as "UNKNOWN" → causes false violations

7.6 Single Chiller Support

Currently hardcoded for rack BTM-CH01

Scaling to multiple chillers/stores requires parameterizing rack ID, crop boundaries, and reference maps

Architecture supports this — just needs configuration, not redesign

8\. SETUP INSTRUCTIONS

8.1 Prerequisites

Python 3.11+

Git

Internet connection (for AI API calls)

8.2 Installation

Bash



git clone https://github.com/Gurukiran3366/Assortment.git

cd Assortment

pip install -r requirements.txt

8.3 Environment Variables

Bash



\# Windows

setx GOOGLE\_API\_KEY "AIza-your-key"

setx OPENAI\_API\_KEY "sk-your-key"

\# Close and reopen terminal after setting



\# Linux/Mac

export GOOGLE\_API\_KEY="AIza-your-key"

export OPENAI\_API\_KEY="sk-your-key"

8.4 Verify Setup

Bash



python validate\_files.py          # Check data consistency

python test\_ocr.py                # Check OCR works

python image\_quality\_check.py     # Check quality gate on test photos

8.5 Run a Full Audit

Bash



python audit\_chiller.py images/staff\_uploads/shelfmessing.jpeg

9\. DEVELOPMENT HISTORY

Milestone 0: Physical Preparation

Labeled chiller shelves S-1 through S-6 with printed stickers

Marked floor position for consistent photo angle

Took reference photo and 8 test scenario photos

Milestone 1: Data Setup

Created product catalog (52 SKUs) from actual chiller inventory

Created reference layout mapping products to shelf/zone/facing

Translated merchandising rules into machine-readable JSON (10 rule types)

Built validation scripts to ensure data consistency

Milestone 2: Reference Understanding

Used EasyOCR to detect shelf label positions from reference image

Built shelf cropping pipeline (midpoint-based boundaries)

Used Gemini AI to extract product-by-product reference map

Human-verified and locked the reference map as ground truth

Milestone 3: Actual Image Processing

Built end-to-end pipeline: photo → quality check → OCR → crop → AI → actual\_map

Optimized from 6 API calls per audit to 1 (6x cost reduction)

Tested across 8 real-world scenarios (messy, tilted, blocked, wrong-shelf, etc.)

Milestone 4: Comparison Engine

Built expected-vs-actual diff engine detecting 10 violation types

Handled multi-shelf products (same product on Shelf 1 AND Shelf 5) with consolidated messages

Eliminated contradictory correction instructions

Milestone 5: Scoring + Validation

Implemented percentage-based scoring (not arbitrary deductions)

Built sanity validator to catch AI hallucinations before they reach staff

Created WhatsApp-ready formatted messages with top-5 priority fixes

Built full audit pipeline orchestrator (audit\_chiller.py)

Milestone 6: Web App (NEXT)

Streamlit-based browser interface for staff photo upload

Real-time pipeline execution with progress display

Milestone 7: Pilot Testing (FINAL)

Daily use by real store staff for 1-2 weeks

Measure accuracy, adoption, compliance improvement

10\. FUTURE ROADMAP

Short-term (next 4 weeks)

&#x20;Switch to GPT-4o/Claude for reliable AI detection

&#x20;Build Streamlit web app

&#x20;Expand product catalog to 150+ SKUs

&#x20;Deploy to cloud for staff access

&#x20;Run 1-2 week pilot at BTM store

Medium-term (2-3 months)

&#x20;Add support for multiple chillers/rack types

&#x20;Add support for multiple stores

&#x20;Build manager dashboard (scores over time, compliance trends)

&#x20;Add audit history and comparison over days

&#x20;Implement colour-flow and pack-size-flow rule checks

Long-term (6+ months)

&#x20;Train custom YOLO model on accumulated real audit photos (reduce API costs to zero)

&#x20;Add offline/PWA support for stores with poor internet

&#x20;Implement out-of-stock detection linked to inventory system

&#x20;Automate WhatsApp delivery of audit results

&#x20;Scale to 100+ stores

text





\---



\## File 2: `ARCHITECTURE.md` — Visual Architecture Reference



Create `C:\\Smart\_planogram\\ARCHITECTURE.md`:



```markdown

\# Architecture Reference



\## End-to-End Pipeline Flow

STAFF PHOTO

│

▼

┌─────────────────────────────────────┐

│ IMAGE QUALITY CHECK │

│ - Resolution ≥ 600x800 │

│ - Blur score ≥ 100 │

│ - Brightness 50-220 │

│ REJECT if fails │

└──────────────┬──────────────────────┘

│ pass

▼

┌─────────────────────────────────────┐

│ OCR SHELF DETECTION (EasyOCR) │

│ - Find S-1 through S-6 labels │

│ - Handle "5" misread as "S" │

│ - Fallback to reference positions │

│ if < 4 shelves detected │

└──────────────┬──────────────────────┘

│

▼

┌─────────────────────────────────────┐

│ SHELF CROPPING (OpenCV) │

│ - Midpoint boundaries between labels │

│ - Horizontal crop: x=350 to x=1150 │

│ - Saves 6 individual shelf images │

└──────────────┬──────────────────────┘

│

▼

┌─────────────────────────────────────┐

│ AI PRODUCT DETECTION (Vision LLM) │

│ - All 6 shelf images in ONE call │

│ - Constrained by product catalog │

│ - Returns: product\_id, zone, facings │

│ - Current: Gemini 3.5 Flash Lite │

│ - Planned: GPT-4o / Claude Sonnet │

└──────────────┬──────────────────────┘

│

▼

┌─────────────────────────────────────┐

│ SANITY VALIDATION │

│ - Max 12 products per shelf │

│ - Min 5 total products │

│ - Max 65 total products │

│ - No excessive facings (>5) │

│ REJECT if critical issues found │

└──────────────┬──────────────────────┘

│ pass

▼

┌─────────────────────────────────────┐

│ COMPARISON ENGINE │

│ - Load locked expected\_map │

│ - Build product indices │

│ - Detect: missing, wrong\_shelf, │

│ wrong\_zone, facing issues, │

│ unauthorized, wrong\_commodity │

│ - Consolidated multi-shelf handling │

└──────────────┬──────────────────────┘

│

▼

┌─────────────────────────────────────┐

│ SCORING ENGINE │

│ - % of correctly placed products │

│ - Minor deductions for zone/facing │

│ - Penalty for wrong commodity │

│ - Score range: 1.0 to 10.0 │

│ - Priority-ranked top 5 fixes │

└──────────────┬──────────────────────┘

│

▼

┌─────────────────────────────────────┐

│ OUTPUT │

│ - WhatsApp-ready text message │

│ - Detailed report (for manager) │

│ - JSON summary (for dashboard) │

│ - Audit log entry │

└─────────────────────────────────────┘



text





\## Data Flow

products.xlsx ──────────────────────────┐

reference\_layout.xlsx ──────────────────┤

chiller\_rules.json ─────────────────────┤

▼

expected\_map\_BTM\_CH01.json ─── COMPARISON ENGINE

▲

staff\_photo.jpeg ── PIPELINE ── actual\_map.json

│

▼

comparison.json

│

▼

score + whatsapp\_msg



text





\## Script Dependency Graph

audit\_chiller.py (MAIN)

├── process\_staff\_photo.py

│ ├── EasyOCR (shelf detection)

│ ├── OpenCV (cropping)

│ └── Gemini/OpenAI API (product detection)

├── validate\_actual\_map.py

├── compare\_engine.py

│ ├── expected\_map\_BTM\_CH01.json

│ ├── products.xlsx

│ └── chiller\_rules.json

└── scoring\_engine.py

