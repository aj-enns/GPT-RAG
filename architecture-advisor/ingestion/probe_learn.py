"""Inspect contentbrowser response."""
import httpx, json
r = httpx.get(
    "https://learn.microsoft.com/api/contentbrowser/search/architectures",
    params={"locale": "en-us", "$top": 2},
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=20,
)
data = r.json()
print("status", r.status_code)
print("top keys:", list(data.keys()))
for item in data.get("results", [])[:2]:
    print("---")
    print(json.dumps(item, indent=2))
print("===")
print("Non-result keys:", {k: v for k, v in data.items() if k != "results"})
