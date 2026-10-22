import hashlib
import re
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from bs4 import BeautifulSoup

TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "msclkid", "mc_eid", "mc_cid",
    "_hsenc", "_hsmi", "hsCtaTracking", "campaign", "affiliate"
}

def clean_html_to_text(html_content: Optional[str]) -> str:
    """Strips HTML markup, decodes entities, and normalizes whitespace."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "html.parser")
    # Remove script and style elements
    for script_or_style in soup(["script", "style", "noscript"]):
        script_or_style.decompose()
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()

def canonicalize_url(raw_url: str) -> str:
    """Normalizes an apply URL by removing tracking query params and lowercasing domain."""
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        
        # Filter out tracking parameters
        clean_query_params = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=False):
            if k.lower() not in TRACKING_QUERY_PARAMS:
                clean_query_params.append((k, v))
        clean_query = urlencode(sorted(clean_query_params))
        
        # Strip trailing slash from path
        path = parsed.path.rstrip("/")
        
        return urlunparse((
            parsed.scheme.lower() or "https",
            netloc,
            path,
            parsed.params,
            clean_query,
            "" # Fragment removed for canonical matching
        ))
    except Exception:
        return raw_url.strip().lower()

def normalize_company_name(name: Optional[str]) -> str:
    """Normalizes company names for cross-source matching (e.g. 'Stripe, Inc.' -> 'stripe')."""
    if not name:
        return ""
    s = name.strip().lower()
    # Strip legal entity markers
    s = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|technologies|tech|gmbh|co)\b\.?", "", s)
    # Remove punctuation
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def normalize_job_title(title: Optional[str]) -> str:
    """Normalizes job titles for fuzzy matching across sources."""
    if not title:
        return ""
    s = title.strip().lower()
    # Remove remote tags like (Remote), [100% Remote], - Remote
    s = re.sub(r"[\(\[\-]?\s*(100%\s*)?remote\s*[\)\]]?", "", s, flags=re.IGNORECASE)
    # Remove gender identifiers like (m/f/d), (m/w/d), (f/m/x)
    s = re.sub(r"[\(\[]\s*[m|f|w|d|x](\s*/\s*[m|f|w|d|x])+\s*[\)\]]?", "", s, flags=re.IGNORECASE)
    # Remove punctuation except alphanumeric
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def normalize_location(location: Optional[str]) -> str:
    """Normalizes location string."""
    if not location:
        return "remote"
    s = location.strip().lower()
    if any(k in s for k in ["remote", "anywhere", "worldwide", "global", "telecommute"]):
        return "remote"
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def compute_content_hash(title: str, company: str, clean_desc: str) -> str:
    """Computes SHA-256 fingerprint over title, company, and description."""
    norm_title = normalize_job_title(title)
    norm_comp = normalize_company_name(company)
    norm_desc = re.sub(r"\s+", " ", (clean_desc or "").strip().lower())
    payload = f"{norm_title}|{norm_comp}|{norm_desc}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def compute_cross_source_hash(normalized_company: str, normalized_title: str, normalized_location: str) -> str:
    """Computes SHA-256 cross-source fingerprint for matching identical jobs across job boards."""
    payload = f"{normalized_company}|{normalized_title}|{normalized_location}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
