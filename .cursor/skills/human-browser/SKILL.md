---
name: human-browser
description: "Human-like browser automation for cloud agents. Prefers Playwright Chromium; falls back to Carbonyl in tmux with CDP on port 1112. Read and verify pages over CDP (websockets, suppress_origin=True). Drive Carbonyl with real tmux keyboard and mouse input."
environments: [cloud]
---

# Human Browser

Use this skill when you need to browse, inspect, or manually test a web page like a human would — with real keyboard/mouse input and CDP-based verification.

## Backend selection

1. **Playwright first** — launches Chromium with a real desktop Chrome user agent and `--remote-debugging-port=1112`.
2. **Carbonyl fallback** — terminal Chromium in a tmux split pane with the same user agent and CDP port.

Install once per environment:

```bash
cd /workspace   # or wherever this repo lives
pip install -e .
python -m playwright install chromium
```

## Prerequisites

Run this check before starting:

```bash
human-browser status || true
command -v human-browser
command -v tmux
echo "tmux session: ${TMUX:-not in tmux}"
```

- **Playwright path:** works without tmux.
- **Carbonyl path:** requires an active tmux session (`$TMUX` must be set). If missing, tell the user to run inside tmux or use `--backend playwright`.

## Start a session

```bash
human-browser start https://example.com
```

Force a backend when needed:

```bash
human-browser start https://example.com --backend playwright
human-browser start https://example.com --backend carbonyl
```

Confirm CDP is alive:

```bash
human-browser status
curl -s http://127.0.0.1:1112/json/version | head -5
```

## Read and verify (always CDP)

Use these commands to inspect page state. They connect over CDP WebSocket with `suppress_origin=True`.

```bash
human-browser list
human-browser eval "document.title"
human-browser eval "document.body.innerText.slice(0, 2000)"
human-browser html
human-browser html "main"
human-browser snap
human-browser shot /tmp/verify.png
human-browser nav https://other.example
```

Typical verification flow:

```bash
human-browser eval "document.title"
human-browser snap
human-browser eval "document.querySelector('h1')?.textContent"
```

## Human input

### Playwright backend

Keyboard and mouse go through Playwright connected over CDP:

```bash
human-browser type "search query"
human-browser key Enter
human-browser clickxy 300 200
human-browser click "button[type=submit]"
```

### Carbonyl backend

**Do not** use CDP `Input.*` events on Carbonyl. Drive the visible terminal browser with tmux-backed input:

```bash
human-browser type "search query"
human-browser key Enter
human-browser clickxy 40 12
human-browser click "a"
```

`click` resolves element coordinates via CDP, then sends a real tmux mouse click to the Carbonyl pane.

## Stop

```bash
human-browser stop
```

## Data extraction patterns

### Extract structured data from listings

Create a JavaScript extraction file (e.g., `extract.js`):

```javascript
const items = document.querySelectorAll('.listing-item');
const results = [];

items.forEach(item => {
    const data = {
        title: item.querySelector('.title')?.innerText,
        price: item.querySelector('.price')?.innerText,
        link: item.querySelector('a')?.href
    };
    
    if (data.link) results.push(data);
});

JSON.stringify(results, null, 2);
```

Then extract from Python:

```python
result = subprocess.run('human-browser eval "$(cat extract.js)" 2>/dev/null',
                       shell=True, capture_output=True, text=True)
data = json.loads(result.stdout)
```

### Detect when to stop pagination

```python
# Check if results are empty
if len(listings) == 0:
    break

# Or check for "no results" message
no_results = subprocess.run(
    'human-browser eval "document.body.innerText.includes(\'No results\')" 2>/dev/null',
    shell=True, capture_output=True, text=True
).stdout.strip()
if no_results == "true":
    break
```

### Deduplicate across pages

```python
seen_links = set()
unique_items = []

for item in all_items:
    link = item.get('link')
    if link and link not in seen_links:
        seen_links.add(link)
        unique_items.append(item)
```

## Pagination patterns

Many sites use pagination or infinite scroll. Handle them differently:

### URL-based pagination (recommended)

Navigate to each page directly via URL parameters:

```python
for page in range(1, 10):
    url = f"https://example.com/search?query=foo&page={page}"
    subprocess.run(f'human-browser nav "{url}" 2>/dev/null', shell=True)
    time.sleep(3)
    
    # Extract data
    result = subprocess.run('human-browser eval "$(cat extract.js)" 2>/dev/null',
                           shell=True, capture_output=True, text=True)
    
    listings = json.loads(result.stdout)
    if len(listings) == 0:
        break  # No more pages
```

### Infinite scroll (less reliable)

For sites that load content on scroll:

```python
for i in range(50):  # Scroll many times
    subprocess.run('human-browser eval "window.scrollTo(0, document.body.scrollHeight)" 2>/dev/null', 
                  shell=True)
    time.sleep(1.5)
    
    # Check if more content loaded
    count = subprocess.run('human-browser eval "document.querySelectorAll(\'.item\').length" 2>/dev/null',
                          shell=True, capture_output=True, text=True).stdout.strip()
```

### Button-based pagination

Click "Next" buttons between pages:

```bash
# Find and click next button
human-browser eval "document.querySelector('[aria-label=\"Next\"]')?.click()"
```

**Best practice:** Prefer URL-based pagination when possible. It's faster, more reliable, and easier to resume.

## Agent workflow

1. `human-browser start <url>`
2. `human-browser status` — note `backend` and `cdp_alive`
3. Verify expected state with `eval`, `snap`, or `shot`
4. Interact with `type`, `key`, `click`, or `clickxy`
5. Re-verify after each meaningful action
6. For multi-page scraping, use URL pagination (see above)
7. `human-browser stop` when finished

## Constants

| Setting | Value |
|---------|-------|
| CDP port | `1112` |
| User agent | Desktop Chrome on Linux x86_64 |
| Carbonyl flags | `--user-agent=…` `--remote-debugging-port=1112` |
| CDP connect | WebSocket, `suppress_origin=True` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Carbonyl backend requires tmux` | Run inside tmux or `--backend playwright` |
| CDP not alive on 1112 | `human-browser stop` then start again |
| Playwright missing | `pip install -e . && python -m playwright install chromium` |
| Carbonyl missing | `human-browser start --backend carbonyl` auto-installs to `~/.local/share/human-browser/carbonyl` |

## Implementation reference

- CLI: `human-browser` (`human_browser/cli.py`)
- CDP client: `human_browser/cdp.py`
- Backends: `human_browser/backends.py`
- tmux input: `human_browser/tmux_input.py`

## Complete scraping example

Example: scrape all pages of a product listing site.

```python
import subprocess, json, time, csv

def scrape_with_pagination():
    base_url = "https://example.com/products?category=electronics"
    all_products = []
    
    # Start browser
    subprocess.run('human-browser start https://example.com 2>/dev/null', shell=True)
    time.sleep(3)
    
    # Scrape pages 1-10
    for page in range(1, 11):
        url = f"{base_url}&page={page}"
        print(f"Scraping page {page}...")
        
        # Navigate
        subprocess.run(f'human-browser nav "{url}" 2>/dev/null', shell=True)
        time.sleep(3)
        
        # Optional: scroll to trigger lazy loading
        for _ in range(3):
            subprocess.run('human-browser eval "window.scrollTo(0, document.body.scrollHeight)" 2>/dev/null', 
                          shell=True)
            time.sleep(1)
        
        # Extract with JavaScript
        js = '''
        Array.from(document.querySelectorAll('.product')).map(el => ({
            name: el.querySelector('.name')?.innerText,
            price: el.querySelector('.price')?.innerText,
            link: el.querySelector('a')?.href
        })).filter(p => p.link)
        '''
        
        result = subprocess.run(f'human-browser eval {json.dumps(js)} 2>/dev/null',
                               shell=True, capture_output=True, text=True)
        
        try:
            products = json.loads(result.stdout)
            print(f"  Found {len(products)} products")
            
            if len(products) == 0:
                break
            
            all_products.extend(products)
        except:
            print(f"  Failed to parse")
            break
    
    # Deduplicate
    unique_products = []
    seen = set()
    for p in all_products:
        if p['link'] not in seen:
            seen.add(p['link'])
            unique_products.append(p)
    
    # Save to CSV
    with open('products.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'price', 'link'])
        writer.writeheader()
        writer.writerows(unique_products)
    
    print(f"Total unique products: {len(unique_products)}")
    
    # Cleanup
    subprocess.run('human-browser stop 2>/dev/null', shell=True)

if __name__ == "__main__":
    scrape_with_pagination()
```
