import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup

# ---------- Tunables ----------
CATEGORY_TEXT_KEYWORDS = [
    # nav text heuristics
    "shop", "store", "products", "collection", "collections",
    "catalog", "category", "categories",
    "men", "women", "kids", "new", "sale", "outlet"
]
CATEGORY_HREF_HINTS = [
    "/shop", "/store", "/product-category", "/category", "/categories",
    "/collections", "/catalog"
]
MAX_CATEGORY_LINKS = 25         # safety cap
MAX_PAGES_PER_CATEGORY = 10     # pagination cap
CONCURRENT_REQUESTS = 5         # polite concurrency
RENDER_JS = True                # many stores are JS-rendered
TIMEOUT_SEC = 40
# ------------------------------

PRICE_RE = re.compile(r"([€$£₹]|AED|USD|EUR|GBP|PKR)\s*[\d{1,3}.,]+|\d[\d,.\s]*\s*(AED|USD|EUR|GBP|PKR)", re.I)

def same_domain(a: str, b: str) -> bool:
    try:
        return urlparse(a).netloc == urlparse(b).netloc
    except:
        return False

def looks_like_category_link(text: str, href: str) -> bool:
    t = (text or "").strip().lower()
    h = (href or "").strip().lower()
    if any(k in t for k in CATEGORY_TEXT_KEYWORDS):
        return True
    if any(hint in h for hint in CATEGORY_HREF_HINTS):
        return True
    # Very broad last resort: URLs that look like taxonomy listings
    if re.search(r"/(men|women|kids|new|sale)(/|$)", h):
        return True
    return False

def extract_jsonld_products(soup: BeautifulSoup, base_url: str):
    """Parse schema.org Product JSON-LD blocks, very reliable when present."""
    products = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue

        # JSON-LD can be a dict or a list; normalize
        items = data if isinstance(data, list) else [data]
        for item in items:
            # Unwrap @graph if present
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                items.extend(item["@graph"])
                continue

            if not isinstance(item, dict):
                continue

            # Accept Product or Offers nested in Product
            if (item.get("@type") == "Product") or ("Product" in item.get("@type", [])):
                name = item.get("name")
                url = item.get("url")
                if url:
                    url = urljoin(base_url, url)

                # Price extraction from offers (could be list)
                price = None
                offers = item.get("offers")
                if isinstance(offers, list) and offers:
                    for off in offers:
                        price = off.get("price") or off.get("priceSpecification", {}).get("price")
                        if price:
                            break
                elif isinstance(offers, dict):
                    price = offers.get("price") or offers.get("priceSpecification", {}).get("price")

                if name and url:
                    products.append({
                        "name": name.strip(),
                        "url": url,
                        "price": str(price).strip() if price else None
                    })
    return products

def extract_products_fallback(soup: BeautifulSoup, base_url: str):
    """
    Generic, best-effort product parsing using common CSS patterns from Shopify,
    WooCommerce, Magento, BigCommerce, custom stores, etc.
    """
    products = []
    candidates = []

    # Very common wrappers/cards
    selectors = [
        # Generic cards
        ".product-card, .product, .grid-product, .card__content, .product-tile, .product-item, .productGrid-item",
        # WooCommerce
        "ul.products li.product",
        # Shopify common
        ".product-grid .grid__item, .collection .grid__item",
        # Magento-ish
        ".products-grid .item, .product-item-info",
    ]

    for sel in selectors:
        found = soup.select(sel)
        if found:
            candidates.extend(found)

    seen_urls = set()
    for node in candidates:
        # Try to find the product link and name
        a = node.select_one("a[href*='/product'], a[href*='/products'], a[href*='/item'], a[href*='/shop'], a[href]")
        title_el = (node.select_one("[itemprop='name']") or
                    node.select_one(".product-title, .card__heading, .full-unstyled-link, .grid-product__title, h2, h3"))
        price_el = (node.select_one("[itemprop='price']") or
                    node.select_one(".price, .price__regular, .price-item, .product-price, .amount, .price-box"))

        href = a.get("href").strip() if a and a.get("href") else None
        name = (title_el.get_text(" ", strip=True) if title_el else
                (a.get_text(" ", strip=True) if a else None))

        url = urljoin(base_url, href) if href else None
        if not url or url in seen_urls:
            continue

        # Basic price normalization
        price_text = None
        if price_el:
            text = price_el.get_text(" ", strip=True)
            m = PRICE_RE.search(text)
            price_text = m.group(0) if m else text if text else None

        if name and url:
            seen_urls.add(url)
            products.append({"name": name, "url": url, "price": price_text})

    # Deduplicate by URL
    return products

def find_pagination_links(soup: BeautifulSoup, base_url: str):
    pages = set()
    # Look for classic pagination containers
    for a in soup.select("a[rel='next'], .pagination a, nav[aria-label*='pagination'] a, a.page-numbers, a.next"):
        href = a.get("href")
        if href:
            pages.add(urljoin(base_url, href))
    return list(pages)

async def fetch_html(crawler: AsyncWebCrawler, url: str):
    res = await crawler.arun(url=url, depth=1, render_js=RENDER_JS, timeout=TIMEOUT_SEC)
    return res.html

def extract_category_links(homepage_html: str, homepage_url: str):
    soup = BeautifulSoup(homepage_html, "html.parser")
    links = set()
    for a in soup.select("a[href]"):
        href = a.get("href")
        text = a.get_text(" ", strip=True)
        full = urljoin(homepage_url, href)
        if same_domain(full, homepage_url) and looks_like_category_link(text, href):
            links.add(full)
    # Keep it reasonable
    return list(list(links)[:MAX_CATEGORY_LINKS])

async def scrape_single_category(crawler: AsyncWebCrawler, category_url: str, sem: asyncio.Semaphore):
    async with sem:
        try:
            html = await fetch_html(crawler, category_url)
        except Exception as e:
            return category_url, {"error": f"fetch_failed: {e}", "products": []}

    soup = BeautifulSoup(html, "html.parser")

    # Prefer JSON-LD first
    products = extract_jsonld_products(soup, category_url)

    # Fallback to CSS-based extraction
    if not products:
        products = extract_products_fallback(soup, category_url)

    # Try pagination (limited)
    seen_urls = {category_url}
    pages_to_visit = find_pagination_links(soup, category_url)[:MAX_PAGES_PER_CATEGORY]

    for page in pages_to_visit:
        if page in seen_urls:
            continue
        seen_urls.add(page)
        async with sem:
            try:
                paged_html = await fetch_html(crawler, page)
            except Exception:
                continue
        psoup = BeautifulSoup(paged_html, "html.parser")
        # Merge JSON-LD + fallback for each page
        more = extract_jsonld_products(psoup, page) or extract_products_fallback(psoup, page)
        products.extend(more)

    # Basic dedupe by URL
    dedup = {}
    for p in products:
        dedup[p["url"]] = p
    return category_url, {"products": list(dedup.values())}

async def scrape_products(homepage_url: str):
    # Normalize
    if not homepage_url.startswith("http"):
        homepage_url = "https://" + homepage_url

    async with AsyncWebCrawler() as crawler:
        # Fetch homepage
        home_html = await fetch_html(crawler, homepage_url)
        category_links = extract_category_links(home_html, homepage_url)

        sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
        results = {}
        tasks = []
        for cat in category_links:
            tasks.append(scrape_single_category(crawler, cat, sem))

        for coro in asyncio.as_completed(tasks):
            category_url, data = await coro
            results[category_url] = data

        return {
            "homepage": homepage_url,
            "categories_found": category_links,
            "data": results
        }
