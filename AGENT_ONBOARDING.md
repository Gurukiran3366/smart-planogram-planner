This is specifically for AI agents. Paste this in a file called `AGENT\_ONBOARDING.md`:



```markdown

\# AI Agent Onboarding Instructions



If you are an AI coding assistant helping with this project, read this first.



\## Project Context Priority



Read in this order for complete understanding:



1\. \*\*SYSTEM\_CONTEXT.md\*\* — Full architecture, data schemas, script details

2\. \*\*ARCHITECTURE.md\*\* — Visual pipeline flow

3\. \*\*API\_GUIDE.md\*\* — How to switch AI models

4\. \*\*QUICK\_START.md\*\* — Common commands

5\. \*\*README.md\*\* — Basic project intro



\## Critical Rules



\### Rule 1: Never hardcode API keys

API keys are set as environment variables. Access via:

```python

os.environ.get("GOOGLE\_API\_KEY")

os.environ.get("OPENAI\_API\_KEY")

Rule 2: Preserve the architectural separation

"AI detects what's there → Deterministic code judges if it's correct"



Do NOT mix these:



AI (process\_staff\_photo.py) should ONLY detect and report

Judgment (compare\_engine.py, scoring\_engine.py) should be pure Python logic

Rule 3: Data files are ground truth

data/products.xlsx is the source of truth for products

data/expected\_map\_BTM\_CH01.json is the locked reference — do NOT modify without human approval

data/chiller\_rules.json contains business logic — treat as configuration

Rule 4: Test with existing photos before adding new logic

Test data in images/staff\_uploads/ includes 8 real-world scenarios. Use these to validate any changes.



Rule 5: Preserve the pipeline stages

The 6-stage pipeline exists for good reasons:



Image quality check → prevents wasted API calls

OCR shelf detection → deterministic positioning

Shelf cropping → improves AI accuracy per shelf

AI product detection → the only AI step

Sanity validation → catches AI failures

Comparison + scoring → business logic

Do NOT combine stages or add AI to stages 5-6.



Current Development Focus

Milestone 6: Streamlit Web App



The backend is complete. Now building the UI so store staff can:



Upload photos via browser

See results visually

View audit history

Do NOT rebuild the backend. Wrap it with Streamlit.



Common Requests You'll Handle

"Fix the scoring formula" → Edit scoring\_engine.py calculate\_score function

"Improve AI detection" → Edit prompt in process\_staff\_photo.py analyze\_all\_shelves\_one\_call

"Add a new violation type" → Edit compare\_engine.py and add to VIOLATION\_WEIGHTS

"Handle new photo scenario" → Test with existing photos first, then adjust validators

"Switch AI model" → Follow API\_GUIDE.md

"Add another chiller/store" → Parameterize hardcoded values (rack\_id, crop boundaries, reference files)

What NOT to Do

Do not train ML models locally (out of scope)

Do not switch to different OCR without discussion (EasyOCR was chosen for Windows stability)

Do not modify the locked expected\_map without human verification

Do not remove the sanity validator (it prevents false alarms to staff)

Do not combine multiple API calls back into per-shelf calls (6x cost increase)

Testing Any Change

Always test with:



Bash



\# Test on clean data first

python audit\_chiller.py images/staff\_uploads/shelfmessing.jpeg



\# Then test on rejection scenarios

python audit\_chiller.py images/staff\_uploads/wrongshelf.jpeg  # Should REJECT



\# Then batch test all

python audit\_chiller.py

When Asked for Recommendations

Reference the file structure. Suggest solutions that:



Reuse existing utilities

Follow the pipeline stage pattern

Are testable with the 8 existing photos

Are documented in SYSTEM\_CONTEXT.md

Contact Points

If you need clarification about:



Business rules → data/chiller\_rules.json

Product data → data/products.xlsx

Ideal layout → data/expected\_map\_BTM\_CH01.json

Pipeline behavior → run scripts and observe output

Development history → SYSTEM\_CONTEXT.md section "Development History"

text





\---



\## Part 4: Push all documentation to GitHub



```cmd

cd C:\\Smart\_planogram



git add QUICK\_START.md

git add AGENT\_ONBOARDING.md



git commit -m "Add onboarding docs for new developers and AI agents"



git push

Part 5: The Ultimate Test — Try It Yourself

Before trusting this on a new laptop, do this simulation on your current laptop:



Create a temporary folder somewhere else:

cmd



cd C:\\

git clone https://github.com/Gurukiran3366/Assortment.git test\_clone

cd test\_clone

Try to set it up as if you knew nothing:

cmd



pip install -r requirements.txt

python audit\_chiller.py images/staff\_uploads/shelfmessing.jpeg

If it works from scratch, your docs are complete

If something breaks, note what was missing → add to docs

Delete the test clone: rmdir /s /q C:\\test\_clone

This proves your setup instructions actually work.



Part 6: What to Say to a New AI Agent

Recommended flow when starting a new AI conversation:



Message 1 (paste the master onboarding prompt from Part 2 above)

Wait for AI to confirm understanding

The AI should respond with:



Summary of the 6-stage pipeline

Current model in use

Next milestone (M6 Streamlit web app)

Message 2: Your specific task

Now you can request specific help:



text



Great, you understand the context. Now help me with:

\[Your specific task]

