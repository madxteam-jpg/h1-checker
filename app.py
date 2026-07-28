import os
import time
import random
import io
import pandas as pd
import matplotlib.pyplot as plt
from difflib import SequenceMatcher
import streamlit as st

# --- STREAMLIT PAGE CONFIG (MUST BE AT THE VERY TOP) ---
st.set_page_config(page_title="Bulk H1 SEO Checker", page_icon="🔍", layout="wide")

# Install Playwright browser binary on host automatically
os.system("playwright install chromium")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculates string similarity ratio normalized on a 0 to 1 scale."""
    if not text1 or not text2:
        return 0.0
    return round(SequenceMatcher(None, text1.lower(), text2.lower()).ratio(), 2)

def fetch_page_data_with_playwright(url: str) -> dict:
    """
    Renders the live DOM directly using Playwright, bypassing static scraper detection,
    extracting H1s (including Shadow DOM/ARIA headings), Meta Title, and Body Context.
    """
    data = {
        "h1_tags": [],
        "meta_title": "",
        "body_text": "",
        "success": False
    }

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--disable-extensions",
                    "--window-size=1920,1080",
                ]
            )

            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                is_mobile=False,
                locale="en-US",
                timezone_id="America/New_York",
                permissions=["geolocation"]
            )

            page = context.new_page()

            # Mask automation signature flags
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
            """)

            # 1. Navigate to URL
            page.goto(url, wait_until="domcontentloaded", timeout=35000)

            # 2. Simulate slight human mouse interaction and scroll sequence
            page.mouse.move(100, 200)
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollBy(0, 400)")

            # 3. Handle Cloudflare / bot challenge screens if detected
            page_title = page.title().lower()
            if "just a moment" in page_title or "attention required" in page_title or "challenge" in page_title:
                page.wait_for_timeout(7000)

            # 4. Wait up to 5s for dynamic client-side JS / React hydration
            page.wait_for_timeout(4000)

            # 5. Native DOM Extraction (Queries live elements directly, including ARIA H1s)
            h1_elements = page.locator("h1, [role='heading'][aria-level='1']").all_inner_texts()
            
            # Clean and deduplicate extracted headings
            cleaned_h1s = []
            for text in h1_elements:
                clean_text = text.strip().replace("\n", " ")
                if clean_text and clean_text not in cleaned_h1s:
                    cleaned_h1s.append(clean_text)

            data["h1_tags"] = cleaned_h1s
            data["meta_title"] = page.title()
            
            # Extract main body text directly from browser DOM
            raw_body = page.evaluate("() => document.body ? document.body.innerText : ''")
            data["body_text"] = " ".join(raw_body.split())[:2000] if raw_body else ""
            data["success"] = True

            browser.close()
            return data
    except Exception:
        return data

def analyze_url(url: str) -> dict:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = {
        "URL": url,
        "Status": "Success",
        "H1 Count": 0,
        "H1 Content": "",
        "Is Missing H1": True,
        "Has Multiple H1s": False,
        "H1 Length Optimal": False,
        "Relevance Score": 0.0,
        "SEO Grade": "Fail",
        "Issues": []
    }

    # Inter-request delay (2.0s - 3.5s) to avoid triggering IP velocity checks
    time.sleep(random.uniform(2.0, 3.5))

    page_data = fetch_page_data_with_playwright(url)

    if not page_data["success"]:
        result["Status"] = "Failed to load page"
        result["Issues"].append("Could not fetch page content (Timeout / Cloudflare Block)")
        return result

    h1_tags = page_data["h1_tags"]
    meta_title = page_data["meta_title"]
    body_text = page_data["body_text"]

    # 1. Process H1 tags
    result["H1 Count"] = len(h1_tags)

    if len(h1_tags) == 0:
        result["Is Missing H1"] = True
        result["Issues"].append("Missing H1 tag")
    elif len(h1_tags) > 1:
        result["Is Missing H1"] = False
        result["Has Multiple H1s"] = True
        result["H1 Content"] = " | ".join(h1_tags)
        result["Issues"].append(f"Multiple H1 tags found ({len(h1_tags)})")
    else:
        result["Is Missing H1"] = False
        result["H1 Content"] = h1_tags[0]

    # 2. Calculate Consolidated Relevance Score (0 to 1 scale)
    primary_h1 = h1_tags[0] if h1_tags else ""

    if primary_h1:
        h1_len = len(primary_h1)
        if 20 <= h1_len <= 70:
            result["H1 Length Optimal"] = True
        elif h1_len < 20:
            result["Issues"].append("H1 is too short (< 20 chars)")
        else:
            result["Issues"].append("H1 is too long (> 70 chars)")

        title_sim = calculate_similarity(primary_h1, meta_title)
        context_sim = calculate_similarity(primary_h1, body_text[:500])
        
        result["Relevance Score"] = round((title_sim + context_sim) / 2, 2)

        if title_sim < 0.2:
            result["Issues"].append("Low correlation with page context")

    if not result["Issues"]:
        result["SEO Grade"] = "Pass (Optimized)"
    elif not result["Is Missing H1"] and not result["Has Multiple H1s"]:
        result["SEO Grade"] = "Needs Improvement"
    else:
        result["SEO Grade"] = "Critical SEO Error"

    result["Issues"] = "; ".join(result["Issues"]) if result["Issues"] else "None"
    return result

def generate_report_card_image(df: pd.DataFrame) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axis("off")

    total = len(df)
    missing_h1 = len(df[df["Is Missing H1"] == True])
    multiple_h1 = len(df[df["Has Multiple H1s"] == True])
    optimized = len(df[df["SEO Grade"] == "Pass (Optimized)"])

    content = (
        f"SEO H1 AUDIT REPORT SUMMARY\n"
        f"{'='*35}\n\n"
        f"• Total URLs Scanned: {total}\n"
        f"• Fully Optimized Pages: {optimized} ({(optimized/total)*100 if total else 0:.1f}%)\n"
        f"• Missing H1 Errors: {missing_h1}\n"
        f"• Multiple H1 Errors: {multiple_h1}\n\n"
        f"Top Recommendations:\n"
        f"- Ensure every page has exactly ONE <h1> tag.\n"
        f"- Keep H1 lengths between 20 to 70 characters.\n"
        f"- Maintain a high relevance score (above 0.50)."
    )

    ax.text(
        0.05, 0.95, content,
        fontsize=14, verticalalignment="top", fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=1", facecolor="#f4f4f9", edgecolor="#333333")
    )

    buffer = io.BytesIO()
    plt.savefig(buffer, format="png", bbox_inches="tight", dpi=200)
    buffer.seek(0)
    plt.close(fig)
    return buffer

# --- STREAMLIT UI ---
st.title("🔍 Bulk H1 SEO Checker (Max 5 URLs)")
st.write("Audit up to 5 URLs for H1 tags, duplicates, length, and contextual relevance.")

input_mode = st.radio("Choose Input Method:", ["Paste URLs", "Upload File (CSV/TXT)"], horizontal=True)

urls_to_check = []

if input_mode == "Paste URLs":
    raw_urls = st.text_area("Enter URLs (one per line, max 5):", placeholder="https://example.com\nhttps://example.org/blog")
    if raw_urls:
        urls_to_check = [u.strip() for u in raw_urls.split("\n") if u.strip()]
else:
    uploaded_file = st.file_uploader("Upload CSV or TXT file containing URLs", type=["csv", "txt"])
    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            df_upload = pd.read_csv(uploaded_file)
            urls_to_check = df_upload.iloc[:, 0].dropna().tolist()
        else:
            urls_to_check = [line.decode("utf-8").strip() for line in uploaded_file if line.strip()]

# Enforce 5 URL limit
if len(urls_to_check) > 5:
    st.warning(f"Maximum limit is 5 URLs per batch. Only the first 5 of {len(urls_to_check)} URLs will be processed.")
    urls_to_check = urls_to_check[:5]

if st.button("Run SEO Audit", type="primary"):
    if not urls_to_check:
        st.warning("Please provide at least one URL.")
    else:
        st.info(f"Auditing {len(urls_to_check)} URL(s)... Performing full browser rendering per URL.")

        results = []
        progress_bar = st.progress(0)

        for i, url in enumerate(urls_to_check):
            results.append(analyze_url(url))
            progress_bar.progress((i + 1) / len(urls_to_check))

        df_results = pd.DataFrame(results)

        st.success("Audit Completed!")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total URLs Scanned", len(df_results))
        col2.metric("Missing H1", len(df_results[df_results["Is Missing H1"] == True]))
        col3.metric("Multiple H1s", len(df_results[df_results["Has Multiple H1s"] == True]))
        col4.metric("SEO Passed", len(df_results[df_results["SEO Grade"] == "Pass (Optimized)"]))

        st.subheader("Detailed Audit Results")
        st.dataframe(df_results, use_container_width=True)

        st.subheader("📥 Export Options")
        d_col1, d_col2 = st.columns(2)

        csv_data = df_results.to_csv(index=False).encode("utf-8")
        d_col1.download_button(
            label="📄 Download Results as CSV",
            data=csv_data,
            file_name="h1_seo_audit_results.csv",
            mime="text/csv"
        )

        img_buffer = generate_report_card_image(df_results)
        d_col2.download_button(
            label="🖼️ Download Summary Report as PNG Image",
            data=img_buffer,
            file_name="h1_seo_report_summary.png",
            mime="image/png"
        )
