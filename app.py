import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from difflib import SequenceMatcher
import concurrent.futures
import io
import matplotlib.pyplot as plt
from playwright.sync_api import sync_playwright
import os
import subprocess

# Auto-install Playwright Chromium binaries on deployment servers
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.run(["pip", "install", "playwright"])
    from playwright.sync_api import sync_playwright

# Ensure Chromium browser binary is installed on the host
os.system("playwright install chromium")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculates string similarity ratio between two texts."""
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

def fetch_html_with_playwright(url: str) -> str:
    """Renders JS DOM while bypassing basic bot detection / Cloudflare challenges."""
    try:
        with sync_playwright() as p:
            # 1. Launch with flags that mask automation features
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--disable-extensions",
                ]
            )

            # 2. Emulate a real desktop browser context
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                is_mobile=False,
                has_touch=False,
                locale="en-US",
                timezone_id="America/New_York"
            )

            page = context.new_page()

            # 3. Mask navigator.webdriver in JavaScript context
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # 4. Navigate and wait for anti-bot challenges to solve
            page.goto(url, wait_until="domcontentloaded", timeout=25000)

            # Check if landed on a challenge screen (e.g., Cloudflare Turnstile/Just a moment...)
            page_title = page.title().lower()
            if "just a moment" in page_title or "attention required" in page_title or "challenge" in page_title:
                # Give Cloudflare JS challenge up to 6 seconds to complete automatically
                page.wait_for_timeout(6000)

            html = page.content()
            browser.close()
            return html
    except Exception:
        return ""

def analyze_url(url: str) -> dict:
    """Fetches a URL and performs H1, Title, Description, and SEO checks."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    result = {
        "URL": url,
        "Status": "Success",
        "H1 Count": 0,
        "H1 Content": "",
        "Meta Title": "",
        "Meta Description": "",
        "Is Missing H1": True,
        "Has Multiple H1s": False,
        "H1 Length Optimal": False,
        "Title Relevance Score (%)": 0.0,
        "Description Relevance Score (%)": 0.0,
        "Page Context Match Score (%)": 0.0,
        "SEO Grade": "Fail",
        "Issues": []
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    html_content = ""
    try:
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if response.ok:
            html_content = response.text
    except Exception:
        pass

    soup = BeautifulSoup(html_content, "html.parser") if html_content else None
    h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all("h1")] if soup else []

    # Fallback to Playwright if static scraping misses the H1 (e.g., React/Next.js pages)
    if not h1_tags:
        rendered_html = fetch_html_with_playwright(url)
        if rendered_html:
            soup = BeautifulSoup(rendered_html, "html.parser")
            h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all("h1")]

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

    # 2. Extract Meta Title & Description
    title_tag = soup.find("title")
    result["Meta Title"] = title_tag.get_text(strip=True) if title_tag else ""

    desc_tag = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "description"})
    result["Meta Description"] = desc_tag["content"].strip() if (desc_tag and "content" in desc_tag.attrs) else ""

    # 3. Extract Body Context
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.extract()
    body_text = soup.get_text(separator=" ", strip=True)[:3000]

    # 4. Perform SEO & Relevance Checks
    primary_h1 = h1_tags[0] if h1_tags else ""

    if primary_h1:
        h1_len = len(primary_h1)
        if 20 <= h1_len <= 70:
            result["H1 Length Optimal"] = True
        elif h1_len < 20:
            result["Issues"].append("H1 is too short (< 20 chars)")
        else:
            result["Issues"].append("H1 is too long (> 70 chars)")

        title_sim = calculate_similarity(primary_h1, result["Meta Title"])
        desc_sim = calculate_similarity(primary_h1, result["Meta Description"])
        context_sim = calculate_similarity(primary_h1, body_text[:500])

        result["Title Relevance Score (%)"] = round(title_sim * 100, 1)
        result["Description Relevance Score (%)"] = round(desc_sim * 100, 1)
        result["Page Context Match Score (%)"] = round(context_sim * 100, 1)

        if title_sim < 0.2:
            result["Issues"].append("Low correlation with Meta Title")

    if not result["Issues"]:
        result["SEO Grade"] = "Pass (Optimized)"
    elif not result["Is Missing H1"] and not result["Has Multiple H1s"]:
        result["SEO Grade"] = "Needs Improvement"
    else:
        result["SEO Grade"] = "Critical SEO Error"

    result["Issues"] = "; ".join(result["Issues"]) if result["Issues"] else "None"
    return result


def generate_report_card_image(df: pd.DataFrame) -> io.BytesIO:
    """Generates an image summary report of the audit results."""
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
        f"- Align H1 keywords closely with your Meta Title & Description."
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


# --- Streamlit UI ---
st.set_page_config(page_title="Bulk H1 SEO Checker", page_icon="🔍", layout="wide")

st.title("🔍 Bulk H1 & SEO Context Checker")
st.write("Audit your H1 tags for missing elements, duplicates, length optimization, and contextual alignment.")

input_mode = st.radio("Choose Input Method:", ["Paste URLs", "Upload File (CSV/TXT)"], horizontal=True)

urls_to_check = []

if input_mode == "Paste URLs":
    raw_urls = st.text_area("Enter URLs (one per line):", placeholder="https://example.com\nhttps://example.org/blog")
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

if st.button("Run SEO Audit", type="primary"):
    if not urls_to_check:
        st.warning("Please provide at least one URL.")
    else:
        st.info(f"Auditing {len(urls_to_check)} URL(s)... Please wait.")

        results = []
        progress_bar = st.progress(0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(analyze_url, url) for url in urls_to_check]
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                results.append(future.result())
                progress_bar.progress((i + 1) / len(urls_to_check))

        df_results = pd.DataFrame(results)

        st.success("Audit Completed!")

        # Metrics display
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total URLs Scanned", len(df_results))
        col2.metric("Missing H1", len(df_results[df_results["Is Missing H1"] == True]))
        col3.metric("Multiple H1s", len(df_results[df_results["Has Multiple H1s"] == True]))
        col4.metric("SEO Passed", len(df_results[df_results["SEO Grade"] == "Pass (Optimized)"]))

        # Results Table
        st.subheader("Detailed Audit Results")
        st.dataframe(df_results, use_container_width=True)

        # Downloads
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
