"""Playwright-based discovery engine for finding document links on AMC websites.

Supports three strategies:
1. link_extraction: Navigate and extract download links from rendered DOM
2. api_intercept: Intercept API calls to capture document metadata
3. network_intercept: Monitor all network requests for document downloads

All AMC sites are JavaScript SPAs requiring headless browser automation.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, parse_qs

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Route, Request

from models.schemas import DiscoveredDocumentModel, DocumentStatus
from observability.logger import get_logger

logger = get_logger(__name__, component="discovery")

# File extensions we care about
DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".zip"}
DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",
    "application/zip",
    "application/x-zip-compressed",
    "text/csv",
}


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication by removing tracking params."""
    parsed = urlparse(url)
    # Remove common tracking/cache-busting parameters
    skip_params = {"t", "timestamp", "v", "ver", "cache", "_", "cb", "rand"}
    params = parse_qs(parsed.query)
    filtered = {k: v for k, v in params.items() if k.lower() not in skip_params}
    
    # Reconstruct with sorted params for consistency
    sorted_query = "&".join(
        f"{k}={v[0]}" for k, v in sorted(filtered.items())
    ) if filtered else ""
    
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if sorted_query:
        normalized += f"?{sorted_query}"
    return normalized


def url_fingerprint(url: str) -> str:
    """Generate a SHA-256 fingerprint of a normalized URL."""
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def extract_filename_from_url(url: str) -> Optional[str]:
    """Extract filename from URL path."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path:
        name = path.split("/")[-1]
        if "." in name:
            return name
    return None


def get_file_type(url: str, content_type: Optional[str] = None) -> Optional[str]:
    """Determine file type from URL or content-type header."""
    # Try URL extension first
    filename = extract_filename_from_url(url)
    if filename:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext in {"pdf", "xlsx", "xls", "csv", "zip"}:
            return ext
    
    # Fall back to content-type
    if content_type:
        ct = content_type.lower()
        if "pdf" in ct:
            return "pdf"
        elif "spreadsheet" in ct or "excel" in ct:
            return "xlsx"
        elif "csv" in ct:
            return "csv"
        elif "zip" in ct:
            return "zip"
    
    return None


class DiscoveryEngine:
    """Discovers document download links from AMC websites using Playwright."""

    def __init__(self, download_dir: str = "./downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._browser: Optional[Browser] = None
        self._playwright = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        return self

    async def __aexit__(self, *args):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _create_stealth_context(self, config: dict) -> BrowserContext:
        """Create a browser context with stealth settings to avoid detection."""
        anti_bot = config.get("anti_bot", {})
        user_agent = anti_bot.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

        context = await self._browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            java_script_enabled=True,
            accept_downloads=True,
        )

        # Add stealth scripts to avoid detection
        await context.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // Override chrome.runtime
            window.chrome = { runtime: {} };
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

        return context

    async def _random_delay(self, config: dict) -> None:
        """Apply random delay to simulate human behavior."""
        anti_bot = config.get("anti_bot", {})
        delay_range = anti_bot.get("random_delay_ms", [1000, 3000])
        delay = random.uniform(delay_range[0] / 1000, delay_range[1] / 1000)
        await asyncio.sleep(delay)

    async def _get_page_structure_hash(self, page: Page) -> str:
        """Capture a structural fingerprint of the page for drift detection.
        
        Hashes the DOM structure (tag names + classes) to detect when
        a page layout has fundamentally changed.
        """
        structure = await page.evaluate("""
            () => {
                function getStructure(el, depth = 0) {
                    if (depth > 5) return '';
                    const tag = el.tagName?.toLowerCase() || '';
                    const cls = el.className?.toString().trim().substring(0, 50) || '';
                    const id_attr = el.id || '';
                    let result = `${tag}.${cls}#${id_attr}`;
                    for (const child of (el.children || [])) {
                        result += '>' + getStructure(child, depth + 1);
                    }
                    return result;
                }
                return getStructure(document.body);
            }
        """)
        return hashlib.sha256(structure.encode()).hexdigest()[:16]

    async def _extract_page_context(self, page: Page, link_element: Any) -> dict:
        """Extract contextual information around a download link.
        
        Captures surrounding text, dropdown selections, and data attributes
        to aid in document classification.
        """
        context = {}
        try:
            # Get surrounding text (parent and siblings)
            surrounding = await page.evaluate("""
                (el) => {
                    const parent = el.parentElement;
                    const grandparent = parent?.parentElement;
                    return {
                        link_text: el.textContent?.trim().substring(0, 200) || '',
                        parent_text: parent?.textContent?.trim().substring(0, 500) || '',
                        grandparent_text: grandparent?.textContent?.trim().substring(0, 500) || '',
                        title: el.getAttribute('title') || '',
                        aria_label: el.getAttribute('aria-label') || '',
                        data_attrs: Object.fromEntries(
                            [...el.attributes].filter(a => a.name.startsWith('data-'))
                            .map(a => [a.name, a.value])
                        ),
                    };
                }
            """, link_element)
            context.update(surrounding)

            # Capture any active dropdown/select values on the page
            dropdowns = await page.evaluate("""
                () => {
                    const selects = document.querySelectorAll('select');
                    const result = {};
                    selects.forEach((s, i) => {
                        const name = s.name || s.id || `select_${i}`;
                        const option = s.options[s.selectedIndex];
                        result[name] = option ? option.textContent.trim() : '';
                    });
                    return result;
                }
            """)
            context["active_dropdowns"] = dropdowns

        except Exception as e:
            logger.warning("page_context_extraction_failed", error=str(e))
            
        return context

    async def discover(
        self,
        source_config: dict,
        pipeline_run_id: Optional[str] = None,
    ) -> list[DiscoveredDocumentModel]:
        """Discover document links from an AMC source.
        
        Args:
            source_config: Source configuration dictionary from sources.yaml
            pipeline_run_id: Optional pipeline run ID for tracking
            
        Returns:
            List of discovered document models with URLs and context
        """
        strategy = source_config.get("discovery", {}).get("strategy", "link_extraction")
        source_key = source_config["source_key"]
        
        logger.info(
            "discovery_started",
            source_key=source_key,
            strategy=strategy,
            url=source_config["base_url"],
        )

        context = await self._create_stealth_context(source_config)
        
        try:
            if strategy == "network_intercept":
                documents = await self._discover_via_network_intercept(context, source_config)
            elif strategy == "api_intercept":
                documents = await self._discover_via_api_intercept(context, source_config)
            else:
                documents = await self._discover_via_link_extraction(context, source_config)

            # Enrich all documents with common metadata
            for doc in documents:
                doc.source_key = source_key
                doc.url_fingerprint = url_fingerprint(doc.url)
                if not doc.filename:
                    doc.filename = extract_filename_from_url(doc.url)
                if not doc.file_type:
                    doc.file_type = get_file_type(doc.url)
                if pipeline_run_id:
                    from uuid import UUID as UUIDType
                    doc.pipeline_run_id = UUIDType(pipeline_run_id)

            logger.info(
                "discovery_completed",
                source_key=source_key,
                documents_found=len(documents),
            )
            return documents
            
        except Exception as e:
            logger.error(
                "discovery_failed",
                source_key=source_key,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
        finally:
            await context.close()

    async def _discover_via_link_extraction(
        self, context: BrowserContext, config: dict
    ) -> list[DiscoveredDocumentModel]:
        """Strategy 1: Navigate page, wait for JS render, extract download links."""
        page = await context.new_page()
        documents = []
        
        try:
            url = config["base_url"]
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Execute navigation steps
            nav_steps = config.get("discovery", {}).get("navigation_steps", [])
            for step in nav_steps:
                await self._execute_nav_step(page, step, config)

            await self._random_delay(config)

            # Get page structure hash for drift detection
            page_hash = await self._get_page_structure_hash(page)
            
            # Extract download links
            selectors = config.get("discovery", {}).get("download_selectors", [])
            all_selector = ", ".join(selectors) if selectors else "a[href]"
            
            links = await page.query_selector_all(all_selector)
            
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    
                    # Resolve relative URLs
                    full_url = urljoin(url, href)
                    
                    # Check if this looks like a document link
                    if not self._is_document_url(full_url, config):
                        continue
                    
                    # Extract page context around this link
                    page_ctx = await self._extract_page_context(page, link)
                    page_ctx["page_structure_hash"] = page_hash
                    
                    doc = DiscoveredDocumentModel(
                        url=full_url,
                        filename=extract_filename_from_url(full_url),
                        file_type=get_file_type(full_url),
                        status=DocumentStatus.DISCOVERED,
                        page_context=page_ctx,
                    )
                    documents.append(doc)
                    
                except Exception as e:
                    logger.warning("link_extraction_error", error=str(e))
                    continue

        finally:
            await page.close()
        
        return documents

    async def _discover_via_network_intercept(
        self, context: BrowserContext, config: dict
    ) -> list[DiscoveredDocumentModel]:
        """Strategy 2: Monitor network requests to find document download URLs."""
        page = await context.new_page()
        documents = []
        intercepted_urls: list[dict] = []
        
        api_patterns = config.get("discovery", {}).get("api_patterns", [])
        
        async def handle_response(response):
            """Capture responses that look like document downloads or API responses."""
            url = response.url
            content_type = response.headers.get("content-type", "")
            
            # Check if response is a document
            is_doc_response = any(
                mime in content_type.lower() 
                for mime in DOCUMENT_MIME_TYPES
            )
            
            # Check if URL matches API patterns
            is_api_match = any(
                self._url_matches_pattern(url, pattern)
                for pattern in api_patterns
            )
            
            if is_doc_response or is_api_match:
                intercepted_urls.append({
                    "url": url,
                    "content_type": content_type,
                    "status": response.status,
                })
                logger.debug("network_intercept_hit", url=url, content_type=content_type)
        
        page.on("response", handle_response)
        
        try:
            url = config["base_url"]
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Execute navigation steps
            nav_steps = config.get("discovery", {}).get("navigation_steps", [])
            for step in nav_steps:
                await self._execute_nav_step(page, step, config)

            await self._random_delay(config)
            
            # Also try link extraction as fallback
            selectors = config.get("discovery", {}).get("download_selectors", [])
            if selectors:
                all_selector = ", ".join(selectors)
                links = await page.query_selector_all(all_selector)
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        if href:
                            full_url = urljoin(url, href)
                            if self._is_document_url(full_url, config):
                                page_ctx = await self._extract_page_context(page, link)
                                intercepted_urls.append({
                                    "url": full_url,
                                    "content_type": "",
                                    "page_context": page_ctx,
                                })
                    except Exception:
                        continue

            # Get page hash
            page_hash = await self._get_page_structure_hash(page)
            
            # Convert intercepted URLs to documents
            seen_urls = set()
            for item in intercepted_urls:
                item_url = item["url"]
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                
                page_ctx = item.get("page_context", {})
                page_ctx["page_structure_hash"] = page_hash
                page_ctx["intercepted_content_type"] = item.get("content_type", "")
                
                doc = DiscoveredDocumentModel(
                    url=item_url,
                    filename=extract_filename_from_url(item_url),
                    file_type=get_file_type(item_url, item.get("content_type")),
                    status=DocumentStatus.DISCOVERED,
                    page_context=page_ctx,
                )
                documents.append(doc)
                
        finally:
            await page.close()
        
        return documents

    async def _discover_via_api_intercept(
        self, context: BrowserContext, config: dict
    ) -> list[DiscoveredDocumentModel]:
        """Strategy 3: Intercept and replay API calls to enumerate documents."""
        # This strategy is similar to network_intercept but focuses on
        # intercepting API responses that contain document metadata/lists
        return await self._discover_via_network_intercept(context, config)

    async def _execute_nav_step(self, page: Page, step: dict, config: dict) -> None:
        """Execute a single navigation step (click, wait, etc)."""
        action = step.get("action", "")
        
        try:
            if action == "wait_for_load":
                timeout = step.get("timeout", 10000)
                await page.wait_for_load_state("networkidle", timeout=timeout)
                
            elif action == "wait_for_selector":
                selector = step.get("selector", "")
                timeout = step.get("timeout", 10000)
                await page.wait_for_selector(selector, timeout=timeout)
                
            elif action == "click":
                selector = step.get("selector", "")
                optional = step.get("optional", False)
                try:
                    await page.click(selector, timeout=5000)
                    await asyncio.sleep(1)  # Wait for UI to respond
                except Exception:
                    if not optional:
                        raise
                    logger.debug("optional_click_skipped", selector=selector)
                    
            elif action == "wait":
                duration = step.get("duration", 1000)
                await asyncio.sleep(duration / 1000)
                
            elif action == "scroll":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.warning(
                "nav_step_failed",
                action=action,
                error=str(e),
                step=step,
            )

    def _is_document_url(self, url: str, config: dict) -> bool:
        """Check if a URL likely points to a downloadable document."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        
        # Check file extension
        allowed_types = config.get("file_types", ["xlsx", "pdf", "zip"])
        for ext in allowed_types:
            if path_lower.endswith(f".{ext}"):
                return True
        
        # Check for download-related URL patterns
        download_patterns = [
            r"download", r"binary", r"attachment", r"portfolio",
            r"factsheet", r"disclosure",
        ]
        url_lower = url.lower()
        for pattern in download_patterns:
            if re.search(pattern, url_lower):
                # But exclude navigation pages
                if not any(x in url_lower for x in ["javascript:", "mailto:", "#"]):
                    return True
        
        return False

    def _url_matches_pattern(self, url: str, pattern: str) -> bool:
        """Check if a URL matches a glob-like pattern."""
        # Convert glob pattern to regex
        regex = pattern.replace("*", ".*").replace("?", ".")
        return bool(re.search(regex, url, re.IGNORECASE))

    async def download_file(
        self,
        url: str,
        source_config: dict,
        target_dir: Optional[str] = None,
    ) -> tuple[str, int]:
        """Download a file from a URL using the browser context.
        
        Args:
            url: URL to download
            source_config: Source configuration for stealth settings
            target_dir: Optional target directory for downloads
            
        Returns:
            Tuple of (local_path, file_size_bytes)
        """
        save_dir = Path(target_dir) if target_dir else self.download_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        
        context = await self._create_stealth_context(source_config)
        page = await context.new_page()
        
        try:
            # Try direct download via navigation
            async with page.expect_download(timeout=60000) as download_info:
                await page.goto(url, timeout=30000)
            
            download = await download_info.value
            filename = download.suggested_filename or extract_filename_from_url(url) or "document"
            save_path = save_dir / filename
            await download.save_as(str(save_path))
            
            # If the downloaded file is a zip archive, extract it and locate the document
            if save_path.suffix.lower() == ".zip":
                import zipfile
                extract_dir = save_path.with_suffix("")
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(save_path, "r") as zip_ref:
                    zip_ref.extractall(extract_dir)
                
                # Search for target spreadsheet or PDF nested within the extracted archive
                extracted_files = list(extract_dir.glob("**/*"))
                target_file = None
                for f in extracted_files:
                    if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".pdf", ".csv"}:
                        target_file = f
                        break
                
                if target_file:
                    save_path = target_file
                    logger.info("zip_file_extracted", zip_path=filename, nested_file=target_file.name)
            
            file_size = save_path.stat().st_size
            logger.info("file_downloaded", url=url, path=str(save_path), size=file_size)
            
            return str(save_path), file_size
            
        except Exception:
            # Fallback: use httpx for direct download
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                resp = await client.get(url, headers={
                    "User-Agent": source_config.get("anti_bot", {}).get(
                        "user_agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0"
                    )
                })
                resp.raise_for_status()
                
                # Determine filename
                filename = extract_filename_from_url(url) or "document"
                cd = resp.headers.get("content-disposition", "")
                if "filename=" in cd:
                    filename = cd.split("filename=")[-1].strip('"\'')
                
                save_path = save_dir / filename
                save_path.write_bytes(resp.content)
                
                # If the downloaded file is a zip archive, extract it and locate the document
                if save_path.suffix.lower() == ".zip":
                    import zipfile
                    extract_dir = save_path.with_suffix("")
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(save_path, "r") as zip_ref:
                        zip_ref.extractall(extract_dir)
                    
                    # Search for target spreadsheet or PDF nested within the extracted archive
                    extracted_files = list(extract_dir.glob("**/*"))
                    target_file = None
                    for f in extracted_files:
                        if f.is_file() and f.suffix.lower() in {".xlsx", ".xls", ".pdf", ".csv"}:
                            target_file = f
                            break
                    
                    if target_file:
                        save_path = target_file
                        logger.info("zip_file_extracted_httpx", zip_path=filename, nested_file=target_file.name)
                
                file_size = save_path.stat().st_size
                logger.info("file_downloaded_httpx", url=url, path=str(save_path), size=file_size)
                
                return str(save_path), file_size
        finally:
            await page.close()
            await context.close()
