import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from urllib.parse import urljoin, urlparse
import time
import logging
import pandas as pd
from typing import Dict, Set, List, Optional
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ScrapingConfig:
    """Configuration settings for scraping"""

    wait_time: int = 3
    timeout: int = 10
    max_depth: int = 1
    use_proxy: bool = False
    proxy: Optional[str] = None


class WebScraper:
    def __init__(self, config: ScrapingConfig):
        self.config = config
        self.logger = logger
        self.visited_urls = set()
        self.base_domain = None
        self.progress_callback = None
        self.total_urls = 0
        self.excluded_extensions = {
            ".js",
            ".css",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".pdf",
            ".xml",
            ".json",
            ".rss",
            ".zip",
            ".gz",
        }

    def setup_driver(self) -> webdriver.Chrome:
        """Configure and return Chrome WebDriver"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-notifications")

        if self.config.use_proxy and self.config.proxy:
            chrome_options.add_argument(f"--proxy-server={self.config.proxy}")

        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        return webdriver.Chrome(options=chrome_options)

    def get_domain(self, url: str) -> str:
        """Extract domain from URL"""
        try:
            return urlparse(url).netloc
        except:
            return ""

    def is_same_domain(self, url: str) -> bool:
        """Check if URL belongs to the same domain"""
        if not self.base_domain:
            return True
        return self.get_domain(url) == self.base_domain

    def is_valid_url(self, url: str) -> bool:
        """Check if URL should be included"""
        try:
            parsed = urlparse(url)
            path = parsed.path.lower()
            # Additional checks for query parameters and fragments
            has_excluded_params = any(
                param in parsed.query.lower()
                for param in ["replytocom", "share", "print"]
            )
            return (
                not any(path.endswith(ext) for ext in self.excluded_extensions)
                and not has_excluded_params
                and self.is_same_domain(url)
                and "#" not in url
            )  # Exclude anchor links
        except:
            return False

    def get_meta_data(self, driver: webdriver.Chrome, url: str) -> Dict:
        """Extract metadata from the page"""
        metadata = {"url": url, "title": "", "description": "", "image": ""}

        try:
            # Get title (try different methods)
            metadata["title"] = driver.title
            if not metadata["title"]:
                title_elem = driver.find_elements(
                    By.CSS_SELECTOR,
                    'meta[property="og:title"], meta[name="twitter:title"], h1',
                )
                if title_elem:
                    metadata["title"] = (
                        title_elem[0].get_attribute("content") or title_elem[0].text
                    )

            # Get meta description
            desc_elem = driver.find_elements(
                By.CSS_SELECTOR,
                'meta[name="description"], meta[property="og:description"], meta[name="twitter:description"]',
            )
            if desc_elem:
                metadata["description"] = desc_elem[0].get_attribute("content")

            # Get share image
            img_elem = driver.find_elements(
                By.CSS_SELECTOR, 'meta[property="og:image"], meta[name="twitter:image"]'
            )
            if img_elem:
                metadata["image"] = img_elem[0].get_attribute("content")

            # Clean up the data
            metadata = {k: str(v).strip() for k, v in metadata.items()}
            return metadata

        except Exception as e:
            self.logger.error(f"Error extracting metadata: {e}")
            return metadata

    def extract_urls_and_metadata(
        self, url: str, current_depth: int = 1, progress_text=None
    ) -> List[Dict]:
        """Extract URLs and metadata recursively based on depth"""
        if not self.base_domain:
            self.base_domain = self.get_domain(url)

        if current_depth > self.config.max_depth:
            return []

        results = []
        driver = None

        try:
            driver = self.setup_driver()
            if progress_text:
                progress_text.text(f"Scanning Depth {current_depth}: {url}")

            if url not in self.visited_urls:
                self.visited_urls.add(url)
                driver.get(url)
                time.sleep(self.config.wait_time)

                # Get metadata for current page
                current_page_data = self.get_meta_data(driver, url)
                results.append(current_page_data)
                self.total_urls += 1

                if progress_text:
                    progress_text.text(
                        f"Found {self.total_urls} URLs... Processing: {url}"
                    )

                # Find all links in the body
                elements = driver.find_elements(By.TAG_NAME, "a")
                discovered_urls = set()

                for element in elements:
                    try:
                        url_value = element.get_attribute("href")
                        if url_value:
                            absolute_url = urljoin(url, url_value)
                            if (
                                absolute_url not in discovered_urls
                                and absolute_url not in self.visited_urls
                                and self.is_valid_url(absolute_url)
                            ):
                                discovered_urls.add(absolute_url)
                    except:
                        continue

                # Process discovered URLs if not at max depth
                if current_depth < self.config.max_depth:
                    for discovered_url in discovered_urls:
                        sub_results = self.extract_urls_and_metadata(
                            discovered_url, current_depth + 1, progress_text
                        )
                        results.extend(sub_results)

            return results

        except Exception as e:
            self.logger.error(f"Error in scraping process: {e}")
            return results

        finally:
            if driver:
                driver.quit()


def main():
    st.set_page_config(page_title="URL Discovery Tool", layout="wide")

    st.title("🔍 URL Discovery Tool")
    st.markdown("Discover and analyze URLs from websites (same domain only)")

    # Input fields
    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input("Enter URL to analyze:", "https://example.com")
    with col2:
        max_depth = st.selectbox(
            "Scan Depth",
            [1, 2, 3],
            0,
            help="Depth 1: Only homepage links\nDepth 2: Homepage + linked pages\nDepth 3: Even deeper",
        )

    # Advanced settings in expander
    with st.expander("Advanced Settings"):
        wait_time = st.slider(
            "Wait Time (seconds)", 1, 10, 3, help="Time to wait for each page to load"
        )
        use_proxy = st.checkbox("Use Proxy", False)
        proxy = st.text_input("Proxy URL (if enabled):", "") if use_proxy else None

    # Create config
    config = ScrapingConfig(
        wait_time=wait_time, max_depth=max_depth, use_proxy=use_proxy, proxy=proxy
    )

    # Initialize scraper
    scraper = WebScraper(config)

    # Display domain info
    if url:
        domain = scraper.get_domain(url)
        st.info(f"Will only analyze URLs from domain: {domain}")

    # Scraping button
    if st.button("Start Analysis"):
        try:
            with st.spinner("Analyzing website..."):
                progress_text = st.empty()
                progress_bar = st.progress(0)
                scraper.total_urls = 0

                results = scraper.extract_urls_and_metadata(
                    url, progress_text=progress_text
                )

                if results:
                    # Convert results to DataFrame
                    df = pd.DataFrame(results)

                    # Display statistics
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total URLs Found", len(df))
                    with col2:
                        st.metric("Scan Depth", max_depth)
                    with col3:
                        st.metric("Domain", scraper.base_domain)

                    # Display results table
                    st.subheader("🔍 Discovered URLs and Metadata")

                    # Format the DataFrame
                    st.dataframe(
                        df.style.set_properties(
                            **{
                                "white-space": "nowrap",
                                "overflow": "hidden",
                                "text-overflow": "ellipsis",
                                "max-width": "0",
                            }
                        ),
                        height=400,
                    )

                    # Download options
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            "Download Results (CSV)",
                            df.to_csv(index=False),
                            "discovered_urls.csv",
                            "text/csv",
                        )
                    with col2:
                        st.download_button(
                            "Download Results (JSON)",
                            df.to_json(orient="records"),
                            "discovered_urls.json",
                            "application/json",
                        )
                else:
                    st.warning("No URLs found or error occurred during analysis")

        except Exception as e:
            st.error(f"Error occurred during analysis: {str(e)}")
            logger.error(f"Analysis error: {e}", exc_info=True)

    # Help section
    with st.expander("ℹ️ Help"):
        st.markdown(
            """
        ### Scan Depth Explained
        - **Depth 1**: Only analyzes links found on the initial page
        - **Depth 2**: Analyzes the initial page and all pages linked from it
        - **Depth 3**: Goes one level deeper, analyzing links found on pages from depth 2

        ### Features
        - Discovers URLs from the same domain only
        - Extracts page titles, descriptions, and share images
        - Excludes resource files (js, css, images, etc.)
        - Shows real-time progress
        - Exports results in CSV or JSON format
        """
        )


if __name__ == "__main__":
    main()

