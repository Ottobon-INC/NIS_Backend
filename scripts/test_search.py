import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

query = "ajay vallabha"
url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
try:
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        html = resp.read().decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        results = soup.find_all("div", class_="result__body")
        print(f"Found {len(results)} results")
        for idx, r in enumerate(results[:5]):
            title = r.find("a", class_="result__url")
            snip = r.find("a", class_="result__snippet")
            print(f"[{idx+1}] URL: {title.get_text().strip() if title else ''}")
            print(f"    Snippet: {snip.get_text().strip() if snip else ''}")
except Exception as e:
    print("Error:", e)
