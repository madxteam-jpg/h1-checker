import time
import random
import pandas as pd
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
import requests
import streamlit as st
import streamlit.components.v1 as components
from playwright.sync_api import sync_playwright

# --- STREAMLIT PAGE CONFIG (MUST BE AT THE VERY TOP) ---
st.set_page_config(page_title="Bulk H1 SEO Checker", page_icon="🔍", layout="wide")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

def calculate_similarity(text1: str, text2: str) -> float:
    if not text1 or not text2:
        return 0.0
    return round(SequenceMatcher(None, text1.lower(), text2.lower()).ratio(), 2)

def extract_h1_headings(soup: BeautifulSoup) -> list:
    h1s = []
    for tag in soup.find_all("h1"):
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    aria_h1s = soup.find_all(attrs={"role": "heading", "aria-level": "1"})
    for tag in aria_h1s:
        text = tag.get_text(strip=True)
        if text and text not in h1s:
            h1s.append(text)
            
    return h1s

def fetch_page_data(url: str) -> dict:
    data = {
        "h1_tags": [],
        "meta_title": "",
        "body_text": "",
        "success": False,
        "is_cloudflare": False
    }

    user_agent = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

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
                return data
    except Exception:
        pass

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
            )
            context = browser.new_context(user_agent=user_agent, viewport={"width": 1280, "height": 800})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(2000)

            page_title = page.title().lower()
            if "just a moment" in page_title or "attention required" in page_title:
                data["is_cloudflare"] = True
                browser.close()
                return data

            h1_elements = page.locator("h1, [role='heading'][aria-level='1']").all_inner_texts()
            cleaned_h1s = [text.strip().replace("\n", " ") for text in h1_elements if text.strip()]
            
            data["h1_tags"] = list(set(cleaned_h1s))
            data["meta_title"] = page.title()
            
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
        "URL": str(url),
        "Status": "Success",
        "H1 Count": 0,
        "H1 Content": "",
        "Is Missing H1": True,
        "Has Multiple H1s": False,
        "H1 Length Optimal": False,
        "Relevance Score": 0.0,
        "SEO Grade": "Fail",
        "Issues": ""
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

    h1_tags = page_data["h1_tags"]
    meta_title = page_data["meta_title"]
    body_text = page_data["body_text"]

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

if len(urls_to_check) > 3:
    st.warning(f"Maximum limit is 3 URLs per batch. Processing only the first 3 of {len(urls_to_check)} URLs.")
    urls_to_check = urls_to_check[:3]

if st.button("Run SEO Audit", type="primary"):
    if not urls_to_check:
        st.warning("Please provide at least one URL.")
    else:
        st.info(f"Auditing {len(urls_to_check)} URL(s)... Fetching content.")

        results = []
        progress_bar = st.progress(0)

        for i, url in enumerate(urls_to_check):
            results.append(analyze_url(url))
            progress_bar.progress((i + 1) / len(urls_to_check))

        df_display = pd.DataFrame(results)

        st.success("Audit Completed!")

        # --- HTML CONTAINER FOR SCREENSHOT CAPTURE (ID: report-summary-card) ---
        total = len(df_display)
        optimized = len(df_display[df_display["SEO Grade"] == "Pass (Optimized)"])
        missing_h1 = len(df_display[df_display["Is Missing H1"] == True])
        multiple_h1 = len(df_display[df_display["Has Multiple H1s"] == True])
        opt_pct = (optimized / total) * 100 if total else 0.0

        st.markdown(
            f"""
            <div id="report-summary-card" style="background-color: #ffffff; padding: 25px; border-radius: 10px; border: 2px solid #e0e0e0; font-family: sans-serif; margin-bottom: 20px;">
                <h3 style="color: #1E88E5; margin-top:0;">📊 SEO H1 Audit Summary Report</h3>
                <hr style="border: 0.5px solid #eee;">
                <div style="display: flex; justify-content: space-around; background-color: #f8f9fa; padding: 15px; border-radius: 8px;">
                    <div style="text-align: center;">
                        <h4 style="margin:0; color:#555;">Scanned</h4>
                        <p style="font-size: 22px; font-weight: bold; margin:0;">{total}</p>
                    </div>
                    <div style="text-align: center;">
                        <h4 style="margin:0; color:#4CAF50;">Optimized</h4>
                        <p style="font-size: 22px; font-weight: bold; margin:0; color:#4CAF50;">{optimized} ({opt_pct:.1f}%)</p>
                    </div>
                    <div style="text-align: center;">
                        <h4 style="margin:0; color:#F44336;">Missing H1</h4>
                        <p style="font-size: 22px; font-weight: bold; margin:0; color:#F44336;">{missing_h1}</p>
                    </div>
                    <div style="text-align: center;">
                        <h4 style="margin:0; color:#FF9800;">Multiple H1s</h4>
                        <p style="font-size: 22px; font-weight: bold; margin:0; color:#FF9800;">{multiple_h1}</p>
                    </div>
                </div>
                <h4 style="margin-top: 20px;">Detailed Breakdown</h4>
                {df_display[['URL', 'H1 Count', 'H1 Content', 'SEO Grade', 'Issues']].to_html(index=False, classes='table table-striped')}
            </div>
            """,
            unsafe_allow_html=True
        )

        st.subheader("Detailed Audit Results Table")
        st.dataframe(df_display, use_container_width=True)

        st.subheader("📥 Export Options")
        
        # --- CLIENT-SIDE SCREENSHOT DOWNLOAD BUTTON ---
        components.html(
            """
            <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.png"></script>
            <script>
            function captureReport() {
                const reportElement = window.parent.document.getElementById("report-summary-card");
                if (reportElement) {
                    html2canvas(reportElement, { scale: 2 }).then(canvas => {
                        const image = canvas.toDataURL("image/png");
                        const link = document.createElement("a");
                        link.href = image;
                        link.download = "seo_audit_summary_report.png";
                        link.click();
                    });
                } else {
                    alert("Report card element not found.");
                }
            }
            </script>
            <button onclick="captureReport()" style="
                background-color: #ff4b4b;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 16px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;">
                📸 Download Screenshot of Report Summary
            </button>
            """,
            height=60
        )

        csv_data = df_display.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📄 Download Results as CSV",
            data=csv_data,
            file_name="h1_seo_audit_results.csv",
            mime="text/csv"
        )
