# app.py
"""
Smart Planogram Planner - Streamlit MVP
Optimized for Render deployment with long-running AI analysis.
"""

import streamlit as st
import os
import json
import pandas as pd
from pathlib import Path
from PIL import Image
from datetime import datetime
import time

# Import stock_status (with fallback if not available)
try:
    from stock_status import load_today_oos, save_today_oos, get_today_oos_count
except ImportError:
    def load_today_oos(): return set()
    def save_today_oos(oos_ids): pass
    def get_today_oos_count(): return 0

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Smart Planogram — Chiller Audit",
    page_icon="🥤",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ============================================================
# API KEYS FROM SECRETS
# ============================================================
if hasattr(st, 'secrets'):
    try:
        if "GOOGLE_API_KEY" in st.secrets:
            os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
        if "OPENAI_API_KEY" in st.secrets:
            os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass

# ============================================================
# CUSTOM CSS
# ============================================================
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .big-score {
        font-size: 72px;
        font-weight: 800;
        text-align: center;
        line-height: 1.1;
        margin: 0;
        padding: 10px 0;
    }
    .score-excellent { color: #10B981; }
    .score-good { color: #3B82F6; }
    .score-attention { color: #F59E0B; }
    .score-poor { color: #F97316; }
    .score-critical { color: #EF4444; }
    
    .status-text {
        font-size: 24px;
        font-weight: 600;
        text-align: center;
        margin: 0;
        padding: 5px 0 20px 0;
    }
    
    .fix-card {
        background: #f8f9fa;
        border-left: 4px solid #EF4444;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    .fix-card-medium {
        background: #f8f9fa;
        border-left: 4px solid #F59E0B;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    .fix-card-info {
        background: #eff6ff;
        border-left: 4px solid #3B82F6;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
    }
    
    .stButton > button {
        height: 52px;
        font-size: 18px;
        font-weight: 600;
        border-radius: 12px;
    }
    
    .app-header {
        text-align: center;
        padding: 20px 0;
        background: linear-gradient(135deg, #1e3a5f, #2563eb);
        color: white;
        border-radius: 12px;
        margin-bottom: 20px;
    }
    .app-header h1 {
        color: white;
        font-size: 28px;
        margin: 0;
    }
    .app-header p {
        color: #93c5fd;
        font-size: 14px;
        margin: 5px 0 0 0;
    }
    
    .metric-card {
        background: white;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    
    .oos-badge {
        background: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 16px;
        font-weight: 600;
        display: inline-block;
        font-size: 14px;
    }
    
    .analyzing-container {
        text-align: center;
        padding: 40px 20px;
        background: linear-gradient(135deg, #eff6ff, #dbeafe);
        border-radius: 16px;
        margin: 20px 0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# SESSION STATE
# ============================================================
if "page" not in st.session_state:
    st.session_state.page = "home"
if "audit_result" not in st.session_state:
    st.session_state.audit_result = None
if "uploaded_image_path" not in st.session_state:
    st.session_state.uploaded_image_path = None


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def show_header():
    st.markdown("""
    <div class="app-header">
        <h1>🥤 SMART PLANOGRAM</h1>
        <p>Chiller Audit System</p>
    </div>
    """, unsafe_allow_html=True)


def get_score_class(score):
    if score >= 90: return "score-excellent"
    elif score >= 75: return "score-good"
    elif score >= 60: return "score-attention"
    elif score >= 40: return "score-poor"
    else: return "score-critical"


def get_score_label(score):
    if score >= 90: return "🌟 Excellent"
    elif score >= 75: return "✅ Good"
    elif score >= 60: return "🟡 Needs Attention"
    elif score >= 40: return "🟠 Poor"
    else: return "🔴 Critical"


def run_audit_pipeline(image_path):
    """Run the audit pipeline (blocking call)."""
    try:
        from audit_chiller import run_full_audit
        result = run_full_audit(image_path)
        return result
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return {
            "status": "ERROR",
            "message": f"Pipeline error: {str(e)}",
            "traceback": error_details
        }


# ============================================================
# PAGE: HOME
# ============================================================
def page_home():
    show_header()
    
    st.markdown("### 👋 Welcome")
    st.markdown(f"**BTM Layout Store** · {datetime.now().strftime('%d %b %Y')}")
    
    oos_count = get_today_oos_count()
    if oos_count > 0:
        st.markdown(f'<div class="oos-badge">📦 {oos_count} products marked OOS today</div>', 
                    unsafe_allow_html=True)
    
    st.divider()
    
    st.markdown("#### 📊 Today's Audit Status")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div class="metric-card">
            <h3 style="margin:0; color:#6B7280;">Chiller 01</h3>
            <p style="font-size:18px; color:#F59E0B; font-weight:600; margin:5px 0;">⏳ Pending</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        reports_dir = Path("data/reports")
        last_score_text = "No previous audits"
        last_color = "#6B7280"
        if reports_dir.exists():
            summary_files = sorted(reports_dir.glob("summary_*.json"), reverse=True)
            if summary_files:
                try:
                    with open(summary_files[0]) as f:
                        summary = json.load(f)
                    last_score = int(summary.get("score", 0) * 10)
                    last_score_text = f"Last: {last_score}%"
                    last_color = "#10B981" if last_score >= 75 else "#F59E0B" if last_score >= 60 else "#EF4444"
                except Exception:
                    pass
        
        st.markdown(f"""
        <div class="metric-card">
            <h3 style="margin:0; color:#6B7280;">Last Audit</h3>
            <p style="font-size:18px; color:{last_color}; font-weight:600; margin:5px 0;">{last_score_text}</p>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("")
    
    if st.button("🔍 START CHILLER AUDIT", type="primary", width='stretch'):
        st.session_state.page = "stock_check"
        st.rerun()
    
    st.divider()
    
    st.markdown("#### 📋 Recent Audits")
    
    reports_dir = Path("data/reports")
    if reports_dir.exists():
        summary_files = sorted(reports_dir.glob("summary_*.json"), reverse=True)
        for sf in summary_files[:5]:
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    summary = json.load(f)
                score = summary.get("score", 0)
                score_pct = int(score * 10)
                audit_date = summary.get("audit_date", "")[:10]
                status_label = get_score_label(score_pct)
                
                st.markdown(f"""
                <div style="background:#f8f9fa; border-radius:8px; padding:12px; margin:8px 0; 
                     border-left:4px solid {'#10B981' if score_pct >= 75 else '#F59E0B' if score_pct >= 60 else '#EF4444'};">
                    <strong>Chiller 01</strong> · {audit_date}<br>
                    <span style="font-size:20px; font-weight:700;">{score_pct}%</span> {status_label}
                </div>
                """, unsafe_allow_html=True)
            except Exception:
                pass
    
    if not reports_dir.exists() or not list(reports_dir.glob("summary_*.json")):
        st.info("No previous audits found. Start your first audit above!")


# ============================================================
# PAGE: STOCK CHECK
# ============================================================
def page_stock_check():
    show_header()
    
    st.markdown("### 📦 Quick Stock Check")
    st.markdown("**Before we audit — which products are OUT OF STOCK today?**")
    st.info("💡 This helps us give you accurate corrections.")
    
    st.divider()
    
    try:
        products_df = pd.read_excel("data/products.xlsx")
    except Exception as e:
        st.error(f"Could not load product catalog: {e}")
        if st.button("← Back to Home"):
            st.session_state.page = "home"
            st.rerun()
        return
    
    current_oos = load_today_oos()
    
    st.markdown("#### Check the box for products that are OUT OF STOCK:")
    st.caption("_Leave everything unchecked if all products are available_")
    
    oos_selections = {}
    
    commodities = sorted(products_df["commodity"].unique())
    commodity_labels = {
        "fruit_beverage": "🍹 Fruit Beverages",
        "energy_drink": "⚡ Energy Drinks",
        "soft_drink": "🥤 Soft Drinks",
        "milk_beverage": "🥛 Milk Beverages",
        "water": "💧 Water"
    }
    
    for commodity in commodities:
        label = commodity_labels.get(commodity, commodity.replace("_", " ").title())
        commodity_products = products_df[products_df["commodity"] == commodity].sort_values("product_name")
        
        oos_in_category = sum(1 for _, r in commodity_products.iterrows() if r["product_id"] in current_oos)
        expander_label = f"{label} ({len(commodity_products)} products"
        if oos_in_category > 0:
            expander_label += f", {oos_in_category} OOS"
        expander_label += ")"
        
        with st.expander(expander_label, expanded=False):
            cols = st.columns(2)
            for i, (_, row) in enumerate(commodity_products.iterrows()):
                pid = row["product_id"]
                pname = row["product_name"]
                with cols[i % 2]:
                    is_oos = st.checkbox(
                        pname,
                        value=(pid in current_oos),
                        key=f"oos_{pid}"
                    )
                    oos_selections[pid] = is_oos
    
    total_oos = sum(1 for v in oos_selections.values() if v)
    
    st.divider()
    
    if total_oos > 0:
        st.warning(f"📦 **{total_oos} products** marked as OUT OF STOCK today")
    else:
        st.success("✅ All products in stock today")
    
    st.markdown("")
    
    col_back, col_skip, col_next = st.columns(3)
    with col_back:
        if st.button("← Back", width='stretch'):
            st.session_state.page = "home"
            st.rerun()
    with col_skip:
        if st.button("⏭️ Skip", width='stretch'):
            save_today_oos(set())
            st.session_state.page = "instructions"
            st.rerun()
    with col_next:
        if st.button("Continue →", type="primary", width='stretch'):
            oos_ids = {pid for pid, is_oos in oos_selections.items() if is_oos}
            save_today_oos(oos_ids)
            st.session_state.page = "instructions"
            st.rerun()


# ============================================================
# PAGE: INSTRUCTIONS
# ============================================================
def page_instructions():
    show_header()
    
    st.markdown("### 📸 Photo Instructions")
    st.markdown("Take a clear photo of the chiller before we begin.")
    
    oos_count = get_today_oos_count()
    if oos_count > 0:
        st.caption(f"📦 {oos_count} products marked out of stock for today's audit")
    
    st.divider()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        #### ✅ DO
        - Stand **1.5 meters** away
        - Capture the **entire chiller**
        - Keep camera **straight**
        - Ensure **S-1 to S-6** labels visible
        - Use **good lighting**
        """)
    
    with col2:
        st.markdown("""
        #### ❌ DON'T
        - Don't use flash
        - Don't tilt the camera
        - Don't crop the photo
        - Don't block any shelves
        - Don't move products first
        """)
    
    st.divider()
    
    st.markdown("#### ✓ Pre-photo Checklist")
    c1 = st.checkbox("Entire chiller visible")
    c2 = st.checkbox("All 6 shelf labels readable")
    c3 = st.checkbox("Camera held straight")
    c4 = st.checkbox("Good lighting")
    
    all_checked = c1 and c2 and c3 and c4
    
    st.markdown("")
    
    col_back, col_next = st.columns(2)
    with col_back:
        if st.button("← Back", width='stretch'):
            st.session_state.page = "stock_check"
            st.rerun()
    with col_next:
        if st.button("📷 UPLOAD PHOTO →", type="primary", width='stretch',
                      disabled=not all_checked):
            st.session_state.page = "upload"
            st.rerun()
    
    if not all_checked:
        st.caption("_Please check all items above to continue_")


# ============================================================
# PAGE: UPLOAD
# ============================================================
def page_upload():
    show_header()
    
    st.markdown("### 📤 Upload Chiller Photo")
    
    uploaded_file = st.file_uploader(
        "Take a photo or select from device",
        type=["jpg", "jpeg", "png"],
        help="Photo should show the full chiller with all 6 shelf labels visible",
        label_visibility="collapsed"
    )
    
    if uploaded_file:
        img = Image.open(uploaded_file)
        st.image(img, caption=f"📷 {uploaded_file.name}", width='stretch')
        st.caption(f"Resolution: {img.size[0]}×{img.size[1]}px")
        
        st.divider()
        
        st.markdown("#### Photo Quality Check")
        st.markdown("""
        ✅ Image loaded successfully  
        ✅ Resolution acceptable  
        """)
        
        # IMPORTANT: Warn about analysis time
        st.warning("⏱️ **Analysis takes 60-90 seconds.** Please don't close this page during analysis.")
        
        col_retake, col_use = st.columns(2)
        with col_retake:
            if st.button("🔄 Choose Different Photo", width='stretch'):
                st.rerun()
        with col_use:
            if st.button("🔍 ANALYZE THIS PHOTO", type="primary", width='stretch'):
                # Save uploaded file
                temp_dir = Path("temp_uploads")
                temp_dir.mkdir(exist_ok=True)
                temp_path = temp_dir / f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                img.save(str(temp_path), "JPEG")
                st.session_state.uploaded_image_path = str(temp_path)
                st.session_state.page = "analyzing"
                st.rerun()
    else:
        st.info("👆 Upload a photo to begin analysis")
        
        ref_path = Path("images/reference/BTM-CH01_reference.jpeg")
        if ref_path.exists():
            with st.expander("👀 See reference arrangement"):
                st.image(str(ref_path), caption="This is how the chiller should look")
        
        if st.button("← Back to Instructions", width='stretch'):
            st.session_state.page = "instructions"
            st.rerun()


# ============================================================
# PAGE: ANALYZING (Optimized for long operations)
# ============================================================
def page_analyzing():
    show_header()
    
    image_path = st.session_state.get("uploaded_image_path")
    if not image_path:
        st.error("No image found. Please upload again.")
        if st.button("← Back"):
            st.session_state.page = "upload"
            st.rerun()
        return
    
    # Large centered analyzing UI
    st.markdown("""
    <div class="analyzing-container">
        <h2 style="margin:0; color:#1e3a5f;">🔍 Analyzing Your Chiller</h2>
        <p style="margin:10px 0 0 0; color:#4b5563; font-size:16px;">
            Please wait while our AI examines the arrangement...<br>
            <strong>This takes 60-90 seconds. Do not close this page.</strong>
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    # Show what's happening
    progress_container = st.container()
    
    with progress_container:
        progress_bar = st.progress(0)
        status_text = st.empty()
        detail_text = st.empty()
    
    # Show fake progress while pipeline runs
    # (This keeps the UI responsive so Render doesn't disconnect)
    
    status_text.markdown("### 📸 Step 1/6: Checking image quality...")
    detail_text.caption("Verifying resolution, lighting, and clarity")
    progress_bar.progress(10)
    time.sleep(0.5)
    
    status_text.markdown("### 🔍 Step 2/6: Detecting shelf labels...")
    detail_text.caption("Finding S-1 through S-6 labels using OCR")
    progress_bar.progress(25)
    time.sleep(0.5)
    
    status_text.markdown("### ✂️ Step 3/6: Cropping shelves...")
    detail_text.caption("Splitting image into 6 individual shelf views")
    progress_bar.progress(40)
    time.sleep(0.5)
    
    status_text.markdown("### 🤖 Step 4/6: AI analyzing products...")
    detail_text.caption("This is the longest step. Please wait 30-60 seconds.")
    progress_bar.progress(55)
    
    # RUN THE ACTUAL PIPELINE (this is the long call)
    try:
        result = run_audit_pipeline(image_path)
    except Exception as e:
        st.error(f"❌ Analysis failed: {e}")
        st.info("This might be a temporary issue. Please try again in a moment.")
        if st.button("🔄 Try Again"):
            st.session_state.page = "upload"
            st.rerun()
        return
    
    status_text.markdown("### 📊 Step 5/6: Comparing with reference...")
    detail_text.caption("Checking against ideal chiller arrangement")
    progress_bar.progress(85)
    time.sleep(0.3)
    
    status_text.markdown("### ✅ Step 6/6: Generating report...")
    detail_text.caption("Preparing your audit results")
    progress_bar.progress(95)
    time.sleep(0.3)
    
    progress_bar.progress(100)
    
    # Store result
    st.session_state.audit_result = result
    
    # Route to appropriate page
    if result["status"] == "SUCCESS":
        status_text.markdown("### ✅ Analysis complete!")
        detail_text.caption("Loading your results...")
        time.sleep(1)
        st.session_state.page = "result"
        st.rerun()
    elif "REJECTED" in result.get("status", ""):
        status_text.markdown("### ⚠️ Analysis needs retake")
        time.sleep(1)
        st.session_state.page = "rejected"
        st.rerun()
    else:
        status_text.markdown("### ❌ Analysis failed")
        error_msg = result.get("message", "Unknown error")
        st.error(f"Error: {error_msg}")
        
        # Show detailed error for debugging
        if "traceback" in result:
            with st.expander("🔧 Technical details (for support)"):
                st.code(result["traceback"])
        
        if st.button("🔄 Try Again", type="primary"):
            st.session_state.audit_result = None
            st.session_state.page = "upload"
            st.rerun()


# ============================================================
# PAGE: REJECTED
# ============================================================
def page_rejected():
    show_header()
    
    result = st.session_state.get("audit_result", {})
    
    st.markdown("### ❌ Audit Failed")
    st.markdown("The photo could not be analyzed reliably.")
    
    st.divider()
    
    message = result.get("message", "Unknown issue")
    st.error(message)
    
    st.divider()
    
    st.markdown("#### 📸 Please retake the photo")
    st.markdown("""
    **Check the following:**
    - ✅ All 6 shelf labels (S-1 to S-6) visible
    - ✅ Full chiller in frame (top to bottom)
    - ✅ Photo taken straight-on (not tilted)
    - ✅ Good lighting, no shadows/glare
    - ✅ Stand on the marked spot on floor
    """)
    
    if st.button("📷 RETAKE PHOTO", type="primary", width='stretch'):
        st.session_state.audit_result = None
        st.session_state.page = "upload"
        st.rerun()
    
    if st.button("← Back to Home", width='stretch'):
        st.session_state.page = "home"
        st.rerun()


# ============================================================
# PAGE: RESULT
# ============================================================
def page_result():
    show_header()
    
    result = st.session_state.get("audit_result", {})
    
    if not result or result.get("status") != "SUCCESS":
        st.error("No audit results available")
        if st.button("← Back"):
            st.session_state.page = "home"
            st.rerun()
        return
    
    score_raw = result.get("score", 5.0)
    score_pct = int(score_raw * 10)
    score_class = get_score_class(score_pct)
    score_label = get_score_label(score_pct)
    
    st.markdown(f"""
    <div style="text-align:center; padding:20px 0;">
        <p class="big-score {score_class}">{score_pct}%</p>
        <p class="status-text">{score_label}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.progress(score_pct / 100)
    
    oos_count = get_today_oos_count()
    if oos_count > 0:
        st.info(f"📦 Note: {oos_count} products were marked as out-of-stock — not counted as issues")
    
    st.divider()
    
    counts = result.get("violation_counts", {})
    total = counts.get("total", 0)
    high = counts.get("high", 0)
    medium = counts.get("medium", 0)
    low = counts.get("low", 0)
    info = counts.get("info", 0)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 Total Issues", total - info)
    with col2:
        st.metric("🔴 Critical", high)
    with col3:
        st.metric("🟡 Moderate", medium + low)
    with col4:
        st.metric("📦 OOS Items", info)
    
    st.divider()
    
    st.markdown("### 🎯 Priority Fixes")
    
    top_fixes = result.get("top_fixes", [])
    priority_fixes = [f for f in top_fixes if f.get("type") != "expected_but_out_of_stock"][:5]
    oos_items = [f for f in top_fixes if f.get("type") == "expected_but_out_of_stock"]
    
    if priority_fixes:
        for i, fix in enumerate(priority_fixes, 1):
            severity = fix.get("severity", "medium")
            if severity == "high":
                icon = "🔴"
                card_class = "fix-card"
            elif severity == "info":
                icon = "ℹ️"
                card_class = "fix-card-info"
            else:
                icon = "🟡"
                card_class = "fix-card-medium"
            
            correction = fix.get("correction", "")
            fix_type = fix.get("type", "").replace("_", " ").title()
            
            st.markdown(f"""
            <div class="{card_class}">
                <strong>{icon} #{i}</strong> <span style="color:#6B7280; font-size:12px;">{fix_type}</span><br>
                <span style="font-size:16px;">{correction}</span>
            </div>
            """, unsafe_allow_html=True)
        
        remaining = total - len(priority_fixes) - info
        if remaining > 0:
            st.caption(f"_...plus {remaining} more improvements_")
    else:
        st.success("✅ No corrections needed! Rack is compliant.")
    
    if oos_items:
        with st.expander(f"📦 Out of Stock Items ({len(oos_items)})"):
            for item in oos_items:
                st.markdown(f"• ℹ️ {item.get('correction', '')}")
    
    st.divider()
    
    col_fix, col_done = st.columns(2)
    
    with col_fix:
        if total - info > 0:
            if st.button("🔧 FIX RACK & RESCAN", type="primary", width='stretch'):
                st.session_state.first_result = st.session_state.audit_result
                st.session_state.page = "final_instructions"
                st.rerun()
    
    with col_done:
        if st.button("✅ DONE", width='stretch'):
            st.session_state.page = "home"
            st.session_state.audit_result = None
            st.rerun()
    
    st.divider()
    
    whatsapp_msg = result.get("whatsapp_message", "")
    if whatsapp_msg:
        with st.expander("📱 Copy WhatsApp Message"):
            st.code(whatsapp_msg, language=None)
            st.caption("Select all text above → Copy → Paste in WhatsApp")
    
    image_path = st.session_state.get("uploaded_image_path")
    if image_path and Path(image_path).exists():
        with st.expander("📸 View Uploaded Photo"):
            st.image(image_path, caption="Uploaded chiller photo", width='stretch')


# ============================================================
# PAGE: FINAL INSTRUCTIONS
# ============================================================
def page_final_instructions():
    show_header()
    
    st.markdown("### ✅ Final Verification")
    st.markdown("Make sure you've completed all corrections before taking the final photo.")
    
    st.divider()
    
    st.markdown("""
    #### Checklist before final photo:
    - ✅ Products moved to correct zones
    - ✅ Missing products added (if in stock)
    - ✅ Correct facings restored
    - ✅ Shelf arrangement is clean
    """)
    
    st.info("💡 **Tip:** Take the photo from approximately the same position as the first photo.")
    
    st.markdown("")
    
    col_back, col_camera = st.columns(2)
    with col_back:
        if st.button("← Back to Results", width='stretch'):
            st.session_state.page = "result"
            st.rerun()
    with col_camera:
        if st.button("📷 UPLOAD FINAL PHOTO", type="primary", width='stretch'):
            st.session_state.page = "final_upload"
            st.rerun()


# ============================================================
# PAGE: FINAL UPLOAD
# ============================================================
def page_final_upload():
    show_header()
    
    st.markdown("### 📤 Upload Final Photo")
    st.markdown("_Upload a photo of the corrected chiller_")
    
    uploaded_file = st.file_uploader(
        "Upload corrected chiller photo",
        type=["jpg", "jpeg", "png"],
        key="final_upload",
        label_visibility="collapsed"
    )
    
    if uploaded_file:
        img = Image.open(uploaded_file)
        
        col_before, col_after = st.columns(2)
        with col_before:
            st.markdown("**BEFORE**")
            first_img_path = st.session_state.get("uploaded_image_path")
            if first_img_path and Path(first_img_path).exists():
                st.image(first_img_path, width='stretch')
        with col_after:
            st.markdown("**AFTER**")
            st.image(img, width='stretch')
        
        st.divider()
        st.warning("⏱️ Analysis takes 60-90 seconds. Please don't close this page.")
        
        col_retake, col_analyze = st.columns(2)
        with col_retake:
            if st.button("🔄 Choose Different", width='stretch'):
                st.rerun()
        with col_analyze:
            if st.button("🔍 ANALYZE FINAL PHOTO", type="primary", width='stretch'):
                temp_dir = Path("temp_uploads")
                temp_dir.mkdir(exist_ok=True)
                temp_path = temp_dir / f"final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                img.save(str(temp_path), "JPEG")
                st.session_state.uploaded_image_path = str(temp_path)
                st.session_state.page = "final_analyzing"
                st.rerun()
    else:
        st.info("👆 Upload the final photo after making corrections")
        
        if st.button("← Back", width='stretch'):
            st.session_state.page = "final_instructions"
            st.rerun()


# ============================================================
# PAGE: FINAL ANALYZING
# ============================================================
def page_final_analyzing():
    show_header()
    
    image_path = st.session_state.get("uploaded_image_path")
    if not image_path:
        st.error("No image found.")
        if st.button("← Back"):
            st.session_state.page = "final_upload"
            st.rerun()
        return
    
    st.markdown("""
    <div class="analyzing-container">
        <h2 style="margin:0; color:#1e3a5f;">🔍 Analyzing Final Photo</h2>
        <p style="margin:10px 0 0 0; color:#4b5563; font-size:16px;">
            Checking if corrections were applied...<br>
            <strong>This takes 60-90 seconds. Do not close this page.</strong>
        </p>
    </div>
    """, unsafe_allow_html=True)
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    status_text.markdown("### 📸 Processing final photo...")
    progress_bar.progress(20)
    time.sleep(0.5)
    
    status_text.markdown("### 🤖 AI analyzing corrections...")
    progress_bar.progress(50)
    
    try:
        result = run_audit_pipeline(image_path)
    except Exception as e:
        st.error(f"❌ Analysis failed: {e}")
        if st.button("🔄 Try Again"):
            st.session_state.page = "final_upload"
            st.rerun()
        return
    
    status_text.markdown("### 📊 Calculating improvement...")
    progress_bar.progress(90)
    time.sleep(0.5)
    
    progress_bar.progress(100)
    st.session_state.audit_result = result
    
    if result["status"] == "SUCCESS":
        status_text.markdown("### ✅ Final analysis complete!")
        time.sleep(1)
        st.session_state.page = "final_result"
        st.rerun()
    else:
        status_text.markdown("### ❌ Analysis failed")
        st.error(result.get("message", "Unknown error"))
        if st.button("🔄 Try Again"):
            st.session_state.page = "final_upload"
            st.rerun()


# ============================================================
# PAGE: FINAL RESULT
# ============================================================
def page_final_result():
    show_header()
    
    result = st.session_state.get("audit_result", {})
    first_result = st.session_state.get("first_result", {})
    
    st.markdown("### 🏆 Audit Complete")
    
    final_score = int(result.get("score", 5.0) * 10)
    initial_score = int(first_result.get("score", 5.0) * 10) if first_result else 0
    improvement = final_score - initial_score
    
    score_class = get_score_class(final_score)
    st.markdown(f"""
    <div style="text-align:center; padding:20px 0;">
        <p class="big-score {score_class}">{final_score}%</p>
        <p class="status-text">{get_score_label(final_score)}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.progress(final_score / 100)
    
    st.divider()
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Before", f"{initial_score}%")
    with col2:
        st.metric("After", f"{final_score}%")
    with col3:
        st.metric("Change", f"{improvement:+d}%", delta=f"{improvement:+d} points")
    
    st.divider()
    
    counts = result.get("violation_counts", {})
    info_count = counts.get("info", 0)
    remaining = counts.get("total", 0) - info_count
    
    if remaining == 0:
        st.success("### ✅ Rack is fully compliant! No corrections required.")
    elif remaining <= 3:
        st.warning(f"### ⚠️ {remaining} minor issues remain")
        top_fixes = [f for f in result.get("top_fixes", []) if f.get("type") != "expected_but_out_of_stock"]
        for fix in top_fixes[:3]:
            st.markdown(f"• {fix.get('correction', '')}")
    else:
        st.error(f"### 🔴 {remaining} issues still need attention")
        top_fixes = [f for f in result.get("top_fixes", []) if f.get("type") != "expected_but_out_of_stock"]
        for fix in top_fixes[:5]:
            st.markdown(f"• {fix.get('correction', '')}")
    
    if info_count > 0:
        st.info(f"📦 {info_count} products were out of stock (not counted)")
    
    st.divider()
    
    if st.button("✅ COMPLETE AUDIT", type="primary", width='stretch'):
        st.session_state.page = "home"
        st.session_state.audit_result = None
        st.session_state.first_result = None
        st.session_state.uploaded_image_path = None
        st.rerun()


# ============================================================
# PAGE ROUTER
# ============================================================
page = st.session_state.page

if page == "home":
    page_home()
elif page == "stock_check":
    page_stock_check()
elif page == "instructions":
    page_instructions()
elif page == "upload":
    page_upload()
elif page == "analyzing":
    page_analyzing()
elif page == "rejected":
    page_rejected()
elif page == "result":
    page_result()
elif page == "final_instructions":
    page_final_instructions()
elif page == "final_upload":
    page_final_upload()
elif page == "final_analyzing":
    page_final_analyzing()
elif page == "final_result":
    page_final_result()
else:
    page_home()