import time
import random
import pandas as pd
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
import requests
import streamlit as st
from playwright.sync_api import sync_playwright

# --- STREAMLIT PAGE CONFIG (MUST BE AT THE VERY TOP) ---
st.set_page_config(page_title="Bulk H1 SEO Checker", page_icon="🔍", layout="wide")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculates string similarity ratio normalized on a 0 to 1 scale."""
    if not text1 or not text2:
        return 0.0
    return round(SequenceMatcher(None, text1.lower(), text2.lower()).ratio(), 2)

def extract_h1_headings(soup: BeautifulSoup) -> list:
    """Extracts text from <h1> tags and elements marked with ARIA role='heading' aria-level='1'."""
    h1s = []
    
    # Standard <h1> tags
    for tag in soup.find_all("h1"):
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    # ARIA level 1 headings
    aria_h1s = soup.find_all(attrs={"role": "heading", "aria-level": "1"})
    for tag in aria_h1s:
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    return h1s

def capture_screenshot_only(url: str, user_agent: str) -> bytes:
    """Helper function to grab a screenshot via Playwright if initial request was static."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(user_agent=user_agent, viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1000)
            screenshot = page.screenshot(full_page=False)
            browser.close()
            return screenshot
    except Exception:
        return None

def fetch_page_data(url: str) -> dict:
    """
    Hybrid Fetching Strategy:
    1. Tries stealth HTTP request with full browser headers first.
    2. Falls back to headless Playwright if static parse yields no H1 or fails.
    3. Captures a screenshot via Playwright.
    """
    data = {
        "h1_tags": [],
        "meta_title": "",
        "body_text": "",
        "success": False,
        "is_cloudflare": False,
        "screenshot": None
    }

    user_agent = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    }

    # --- PATH 1: Fast & Stealth HTTP Fetch ---
    try:
        response = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        if response.ok and "just a moment" not in response.text.lower() and "enable javascript" not in response.text.lower():
            soup = BeautifulSoup(response.text, "html.parser")
            h1s = extract_h1_headings(soup)
            
            if h1s:
                title_tag = soup.find("title")
                data["h1_tags"] = h1s
                data["meta_title"] = title_tag.get_text(strip=True) if title_tag else ""
                
                for el in soup(["script", "style", "nav", "footer", "header"]):
                    el.extract()
                data["body_text"] = soup.get_text(separator=" ", strip=True)[:2000]
                data["success"] = True
                
                # Fetch screenshot via Playwright
                data["screenshot"] = capture_screenshot_only(url, user_agent)
                return data
    except Exception:
        pass

    # --- PATH 2: Playwright Headless Fallback & Screenshot Capture ---
    try:
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
                user_agent=user_agent,
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York"
            )

            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(2000)

            page_title = page.title().lower()
            if "just a moment" in page_title or "attention required" in page_title or "challenge" in page_title:
                data["is_cloudflare"] = True
                browser.close()
                return data

            h1_elements = page.locator("h1, [role='heading'][aria-level='1']").all_inner_texts()
            cleaned_h1s = [text.strip().replace("\n", " ") for text in h1_elements if text.strip()]
            
            data["h1_tags"] = list(set(cleaned_h1s))
            data["meta_title"] = page.title()
            
            raw_body = page.evaluate("() => document.body ? document.body.innerText : ''")
            data["body_text"] = " ".join(raw_body.split())[:2000] if raw_body else ""
            
            # Capture page screenshot byte payload directly from Playwright session
            data["screenshot"] = page.screenshot(full_page=False)
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
        "URL": str(url),
        "Status": "Success",
        "H1 Count": 0,
        "H1 Content": "",
        "Is Missing H1": True,
        "Has Multiple H1s": False,
        "H1 Length Optimal": False,
        "Relevance Score": 0.0,
        "SEO Grade": "Fail",
        "Issues": "",
        "Screenshot": None
    }

    issues_list = []

    time.sleep(random.uniform(1.5, 2.5))

    page_data = fetch_page_data(url)

    if page_data["is_cloudflare"]:
        result["Status"] = "Blocked"
        result["Issues"] = "Cloudflare Bot Protection Active"
        return result

    if not page_data["success"]:
        result["Status"] = "Failed to load"
        result["Issues"] = "Could not fetch content (Timeout/Block)"
        return result

    result["Screenshot"] = page_data["screenshot"]
    h1_tags = page_data["h1_tags"]
    meta_title = page_data["meta_title"]
    body_text = page_data["body_text"]

    # 1. Process H1 tags
    result["H1 Count"] = len(h1_tags)

    if len(h1_tags) == 0:
        result["Is Missing H1"] = True
        issues_list.append("Missing H1 tag")
    elif len(h1_tags) > 1:
        result["Is Missing H1"] = False
        result["Has Multiple H1s"] = True
        result["H1 Content"] = " | ".join(h1_tags)
        issues_list.append(f"Multiple H1 tags found ({len(h1_tags)})")
    else:
        result["Is Missing H1"] = False
        result["H1 Content"] = h1_tags[0]

    # 2. Relevance Calculation
    primary_h1 = h1_tags[0] if h1_tags else ""

    if primary_h1:
        h1_len = len(primary_h1)
        if 20 <= h1_len <= 70:
            result["H1 Length Optimal"] = True
        elif h1_len < 20:
            issues_list.append("H1 is too short (< 20 chars)")
        else:
            issues_list.append("H1 is too long (> 70 chars)")

        title_sim = calculate_similarity(primary_h1, meta_title)
        context_sim = calculate_similarity(primary_h1, body_text[:500])
        
        result["Relevance Score"] = round((title_sim + context_sim) / 2, 2)

        if title_sim < 0.2:
            issues_list.append("Low correlation with page context")

    if not issues_list:
        result["SEO Grade"] = "Pass (Optimized)"
    elif not result["Is Missing H1"] and not result["Has Multiple H1s"]:
        result["SEO Grade"] = "Needs Improvement"
    else:
        result["SEO Grade"] = "Critical SEO Error"

    result["Issues"] = "; ".join(issues_list) if issues_list else "None"
    return result

# --- STREAMLIT UI ---
st.title("🔍 Bulk H1 SEO Checker (Max 3 URLs)")
st.write("Audit up to 3 URLs for H1 tags, duplicates, length, and contextual relevance.")

input_mode = st.radio("Choose Input Method:", ["Paste URLs", "Upload File (CSV/TXT)"], horizontal=True)

urls_to_check = []

if input_mode == "Paste URLs":
    raw_urls = st.text_area("Enter URLs (one per line, max 3):", placeholder="https://example.com\nhttps://example.org/blog")
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

# Enforce 3 URL limit
if len(urls_to_check) > 3:
    st.warning(f"Maximum limit is 3 URLs per batch. Processing only the first 3 of {len(urls_to_check)} URLs.")
    urls_to_check = urls_to_check[:3]

if st.button("Run SEO Audit", type="primary"):
    if not urls_to_check:
        st.warning("Please provide at least one URL.")
    else:
        st.info(f"Auditing {len(urls_to_check)} URL(s)... Fetching content and screenshots.")

        results = []
        progress_bar = st.progress(0)

        for i, url in enumerate(urls_to_check):
            results.append(analyze_url(url))
            progress_bar.progress((i + 1) / len(urls_to_check))

        df_results = pd.DataFrame(results)

        # Separate binary screenshots from clean tabular DataFrame export
        screenshots = df_results[["URL", "Screenshot"]].copy()
        df_display = df_results.drop(columns=["Screenshot"])

        # PyArrow Compatibility
        df_display["URL"] = df_display["URL"].astype(str)
        df_display["Status"] = df_display["Status"].astype(str)
        df_display["H1 Count"] = pd.to_numeric(df_display["H1 Count"], errors="coerce").fillna(0).astype(int)
        df_display["H1 Content"] = df_display["H1 Content"].astype(str)
        df_display["Is Missing H1"] = df_display["Is Missing H1"].astype(bool)
        df_display["Has Multiple H1s"] = df_display["Has Multiple H1s"].astype(bool)
        df_display["H1 Length Optimal"] = df_display["H1 Length Optimal"].astype(bool)
        df_display["Relevance Score"] = pd.to_numeric(df_display["Relevance Score"], errors="coerce").fillna(0.0).astype(float)
        df_display["SEO Grade"] = df_display["SEO Grade"].astype(str)
        df_display["Issues"] = df_display["Issues"].astype(str)

        st.success("Audit Completed!")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total URLs Scanned", len(df_display))
        col2.metric("Missing H1", len(df_display[df_display["Is Missing H1"] == True]))
        col3.metric("Multiple H1s", len(df_display[df_display["Has Multiple H1s"] == True]))
        col4.metric("SEO Passed", len(df_display[df_display["SEO Grade"] == "Pass (Optimized)"]))

        st.subheader("Detailed Audit Results")
        st.dataframe(df_display, use_container_width=True)

        # --- SCREENSHOT DISPLAY SECTION ---
        st.subheader("📸 Page Screenshots")
        img_cols = st.columns(len(screenshots))
        for idx, row in screenshots.iterrows():
            with img_cols[idx]:
                st.write(f"**{row['URL']}**")
                if row["Screenshot"]:
                    st.image(row["Screenshot"], caption="Captured result page", use_column_width=True)
                else:
                    st.caption("No screenshot available.")

        # --- NATIVE SUMMARY REPORT CARD (REPLACES MATPLOTLIB) ---
        st.subheader("📊 Audit Summary Card")
        total = len(df_display)
        optimized = len(df_display[df_display["SEO Grade"] == "Pass (Optimized)"])
        missing_h1 = len(df_display[df_display["Is Missing H1"] == True])
        multiple_h1 = len(df_display[df_display["Has Multiple H1s"] == True])
        opt_pct = (optimized / total) * 100 if total else 0.0

        st.markdown(
            f"""
            <div style="background-color: #f4f4f9; padding: 20px; border-radius: 8px; border: 1px solid #ddd; font-family: monospace;">
                <h4>SEO H1 AUDIT REPORT SUMMARY</h4>
                <hr>
                <ul>
                    <li><b>Total URLs Scanned:</b> {total}</li>
                    <li><b>Fully Optimized Pages:</b> {optimized} ({opt_pct:.1f}%)</li>
                    <li><b>Missing H1 Errors:</b> {missing_h1}</li>
                    <li><b>Multiple H1 Errors:</b> {multiple_h1}</li>
                </ul>
                <b>Top Recommendations:</b>
                <ul>
                    <li>Ensure every page has exactly ONE &lt;h1&gt; tag.</li>
                    <li>Keep H1 lengths between 20 to 70 characters.</li>
                    <li>Maintain a high relevance score (above 0.50).</li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

        st.subheader("📥 Export Options")
        csv_data = df_display.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📄 Download Results as CSV",
            data=csv_data,
            file_name="h1_seo_audit_results.csv",
            mime="text/csv"
        )
