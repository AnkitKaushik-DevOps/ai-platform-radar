"""
AI Platform Update Tracker
Monitors OpenAI and Azure for deprecations, new tools, and announcements.
Outputs a dated digest to the digests/ folder.
"""

import os
import json
import hashlib
import feedparser
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Sources ────────────────────────────────────────────────────────────────────

FEEDS = [
    {
        "name": "OpenAI",
        "type": "rss",
        "url": "https://openai.com/blog/rss.xml",
        "tags": ["openai"],
    },
    {
        "name": "OpenAI Changelog",
        "type": "rss",
        "url": "https://platform.openai.com/docs/changelog/rss",
        "tags": ["openai", "changelog"],
    },
    {
        "name": "Azure AI Updates",
        "type": "rss",
        "url": "https://azurecomcdn.azureedge.net/en-us/updates/feed/?category=ai-machine-learning",
        "tags": ["azure", "ai"],
    },
    {
        "name": "Azure Updates (All)",
        "type": "rss",
        "url": "https://azurecomcdn.azureedge.net/en-us/updates/feed/",
        "tags": ["azure"],
    },
    {
        "name": "GitHub Changelog",
        "type": "rss",
        "url": "https://github.blog/changelog/feed/",
        "tags": ["github"],
    },
]

# Keywords that flag an item as a deprecation or new launch
DEPRECATION_KEYWORDS = [
    "deprecat", "retire", "end of life", "eol", "sunset",
    "discontinu", "legacy", "migration required", "no longer supported",
    "will be removed", "being removed",
]

LAUNCH_KEYWORDS = [
    "launch", "announc", "introduc", "new ", "generally available",
    "ga ", "preview", "release", "now available", "shipping",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def item_id(entry: dict) -> str:
    """Stable ID for deduplication across runs."""
    key = (entry.get("link") or entry.get("title") or "")
    return hashlib.md5(key.encode()).hexdigest()


def classify(title: str, summary: str) -> list[str]:
    text = (title + " " + summary).lower()
    labels = []
    if any(k in text for k in DEPRECATION_KEYWORDS):
        labels.append("⚠️ DEPRECATION")
    if any(k in text for k in LAUNCH_KEYWORDS):
        labels.append("🚀 NEW LAUNCH")
    if not labels:
        labels.append("ℹ️ UPDATE")
    return labels


def fetch_feed(source: dict) -> list[dict]:
    items = []
    try:
        feed = feedparser.parse(source["url"])
        for entry in feed.entries[:15]:          # cap per feed
            title   = entry.get("title", "").strip()
            link    = entry.get("link", "")
            summary = entry.get("summary", entry.get("description", ""))
            pub     = entry.get("published", entry.get("updated", ""))

            # strip HTML tags from summary
            import re
            summary_clean = re.sub(r"<[^>]+>", "", summary).strip()
            summary_clean = summary_clean[:300] + ("…" if len(summary_clean) > 300 else "")

            items.append({
                "id":      item_id(entry),
                "source":  source["name"],
                "tags":    source["tags"],
                "title":   title,
                "link":    link,
                "summary": summary_clean,
                "pub":     pub,
                "labels":  classify(title, summary_clean),
            })
    except Exception as exc:
        print(f"  [WARN] Could not fetch {source['name']}: {exc}")
    return items


def load_seen(path: Path) -> set:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_seen(path: Path, seen: set):
    path.write_text(json.dumps(list(seen), indent=2))


# ── Digest builder ─────────────────────────────────────────────────────────────

def build_digest(items: list[dict], date_str: str) -> str:
    sections = {
        "⚠️ DEPRECATION": [],
        "🚀 NEW LAUNCH":  [],
        "ℹ️ UPDATE":      [],
    }

    for item in items:
        primary = item["labels"][0]
        sections[primary].append(item)

    lines = [
        f"# AI Platform Update Digest — {date_str}",
        "",
        f"> Auto-generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"> Sources: OpenAI Blog, OpenAI Changelog, Azure AI Updates, GitHub Changelog",
        "",
    ]

    total = len(items)
    dep   = len(sections["⚠️ DEPRECATION"])
    new   = len(sections["🚀 NEW LAUNCH"])
    upd   = len(sections["ℹ️ UPDATE"])

    lines += [
        "## Summary",
        "",
        f"| Category | Count |",
        f"|---|---|",
        f"| ⚠️ Deprecations | {dep} |",
        f"| 🚀 New Launches | {new} |",
        f"| ℹ️ Other Updates | {upd} |",
        f"| **Total** | **{total}** |",
        "",
    ]

    for label, section_items in sections.items():
        if not section_items:
            continue
        lines.append(f"## {label}s")
        lines.append("")
        for item in section_items:
            lines.append(f"### [{item['title']}]({item['link']})")
            lines.append(f"**Source:** {item['source']}  ")
            if item['pub']:
                lines.append(f"**Published:** {item['pub']}  ")
            if item['summary']:
                lines.append(f"")
                lines.append(f"{item['summary']}")
            lines.append("")

    if not items:
        lines += ["_No new updates since last run._", ""]

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    root      = Path(__file__).parent.parent
    digests   = root / "digests"
    seen_path = root / ".seen_ids.json"

    digests.mkdir(exist_ok=True)

    print("Fetching feeds…")
    all_items = []
    for source in FEEDS:
        print(f"  → {source['name']}")
        all_items.extend(fetch_feed(source))

    seen     = load_seen(seen_path)
    new_seen = set()
    fresh    = []

    for item in all_items:
        new_seen.add(item["id"])
        if item["id"] not in seen:
            fresh.append(item)

    print(f"Found {len(fresh)} new items (out of {len(all_items)} total).")

    date_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_path = digests / f"{date_str}.md"
    digest_text = build_digest(fresh, date_str)
    digest_path.write_text(digest_text, encoding="utf-8")
    print(f"Digest written → {digest_path}")

    # Update the rolling README summary
    readme_path = root / "README.md"
    update_readme(readme_path, fresh, date_str)

    save_seen(seen_path, seen | new_seen)
    print("Done.")


def update_readme(readme_path: Path, items: list[dict], date_str: str):
    dep = [i for i in items if "⚠️ DEPRECATION" in i["labels"]]
    new = [i for i in items if "🚀 NEW LAUNCH"  in i["labels"]]

    badge_dep = f"![Deprecations](https://img.shields.io/badge/deprecations-{len(dep)}-red)"
    badge_new = f"![New Tools](https://img.shields.io/badge/new_tools-{len(new)}-green)"

    content = f"""# 🤖 AI Platform Update Tracker

Automated daily digest of OpenAI and Azure deprecations, new tool launches, and announcements.

{badge_dep} {badge_new} ![Last Run](https://img.shields.io/badge/last_run-{date_str}-blue)

## What this tracks
- **OpenAI** — blog posts, model deprecations, API changes, changelog
- **Azure** — AI/ML service updates, retirements, new service launches
- **GitHub** — Copilot and Actions changelog

## Latest digest ({date_str})

| | |
|---|---|
| ⚠️ Deprecations today | {len(dep)} |
| 🚀 New launches today | {len(new)} |

{"### ⚠️ Deprecations" + chr(10) + chr(10) + chr(10).join(f"- [{i['title']}]({i['link']}) — *{i['source']}*" for i in dep[:5]) if dep else ""}

{"### 🚀 New Launches" + chr(10) + chr(10) + chr(10).join(f"- [{i['title']}]({i['link']}) — *{i['source']}*" for i in new[:5]) if new else ""}

## Digest archive
All digests are stored in [`/digests`](./digests/) as dated Markdown files.

---
*Auto-updated daily via GitHub Actions*
"""
    readme_path.write_text(content, encoding="utf-8")
    print(f"README updated → {readme_path}")


if __name__ == "__main__":
    main()
