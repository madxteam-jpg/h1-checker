import os
import time
import random
import io
import pandas as pd
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup
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

def extract_h1_headings(soup: BeautifulSoup) -> list:
    """Extracts text from <h1> tags and elements marked with ARIA role='heading' aria-level='1'."""
    h1s = []
    
    # 1. Standard <h1> tags
    for tag in soup.find_all("h1"):
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    # 2. Custom elements acting as H1 via ARIA roles
    aria_h1s = soup.find_all(attrs={"role": "heading", "aria-level": "1"})
    for tag in aria_h1s:
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    return h1s

def fetch_html_with_playwright(url: str) -> str:
    """Renders JS DOM with Playwright, scrolling down and waiting for headings to render."""
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
                ]
            )

            context = browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                is_mobile=False,
                locale="en-US",
                timezone_id="America/New_York"
            )

            page = context.new_page()

            # Mask automation flags
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Scroll down to trigger lazy rendering and wait 3-4s
            page.evaluate("window.scrollBy(0, 400)")
            page.wait_for_timeout(3500)

            # Wait explicitly for h1 if present in DOM
            try:
                page.wait_for_selector("h1, [role='heading'][aria-level='1']", timeout=3000)
            except Exception:
                pass

            html = page.content()
            browser.close()
            return html
    except Exception:
        return ""

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

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    # Delay between 2.0 and 4.0 seconds to prevent bot triggers / rate limits
    time.sleep(random.uniform(2.0, 4.0))

    html_content = ""
    try:
        response = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        if response.ok and "just a moment" not in response.text.lower():
            html_content = response.text
    except Exception:
        pass

    soup = BeautifulSoup(html_content, "html.parser") if html_content else None
    h1_tags = extract_h1_headings(soup) if soup else []

    # Fallback to Playwright if initial HTTP request found no H1
    if not h1_tags:
        rendered_html = fetch_html_with_playwright(url)
        if rendered_html:
            soup = BeautifulSoup(rendered_html, "html.parser")
            h1_tags = extract_h1_headings(soup)

    if not soup:
        result["Status"] = "Failed to load page"
        result["Issues"].append("Could not fetch page content")
        return result

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

    # 2. Context Extraction
    title_tag = soup.find("title")
    meta_title = title_tag.get_text(strip=True) if title_tag else ""

    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.extract()
    body_text = soup.get_text(separator=" ", strip=True)[:2000]

    # 3. Calculate Consolidated Relevance Score (0 to 1 scale)
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
        st.info(f"Auditing {len(urls_to_check)} URL(s)... Applying 2-4s delay per request.")

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
