=========== START (don't include this line) ===========



\# Smart Planogram Planner



AI-powered visual audit system for J24 store chillers/racks.



\## Purpose



Staff uploads a photo of a chiller → system compares against reference layout + rules → returns specific corrections and a compliance score.



\## Architecture



\- Vision LLM: Gemini 3.6 Flash (primary), GPT-4o-mini (fallback)

\- OCR: EasyOCR (shelf boundary detection)

\- Rule Engine: Deterministic Python-based comparison

\- Data: Excel (pilot) → Postgres (production)



\## Setup



Install dependencies:



&#x20;   pip install -r requirements.txt



Set API keys:



&#x20;   setx GOOGLE\_API\_KEY "your-key-here"

&#x20;   setx OPENAI\_API\_KEY "your-key-here"



Close and reopen terminal after setting keys.



\## Project Structure



\- data/ — Product catalog, rules, reference maps

\- images/reference/ — Reference photos (ideal chiller state)

\- images/products/ — Individual product images

\- images/shelves/ — Auto-generated shelf crops

\- images/staff\_uploads/ — Actual daily audit photos



\## Pipeline Scripts



1\. validate\_files.py — Sanity-check catalog/rules consistency

2\. test\_ocr.py — Detect shelf label positions using OCR

3\. crop\_shelves.py — Split reference image into 6 shelf strips

4\. analyze\_shelves\_gemini.py — AI-identify products per shelf

5\. compare\_engine.py (coming) — Compare actual vs expected



\## Pilot Scope



\- 1 store: BTM

\- 1 rack: Chiller (BTM-CH01)

\- 6 shelves, \~150 SKUs

\- Target: 90%+ product accuracy, 9+/10 score after corrections



\## Milestones



\- \[x] M0: Physical rack preparation

\- \[x] M1: Data setup (catalog + rules + reference)

\- \[x] M2: Reference understanding (AI extraction)

\- \[ ] M3: Actual image processing pipeline

\- \[ ] M4: Rule engine and comparison

\- \[ ] M5: Correction/scoring engine

\- \[ ] M6: Streamlit web interface

\- \[ ] M7: Pilot testing



=========== END (don't include this line) ===========

