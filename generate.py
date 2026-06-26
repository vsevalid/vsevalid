#!/usr/bin/env python3
"""GitHub profile SVG generator for vsevalid (Vsevolod)."""

from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import requests

# ── config ────────────────────────────────────────────────────────────────────

USERNAME = "vsevalid"
NAME = "Vsevolod"
CACHE_FILE = Path("cache.json")
ASCII_FILE = Path("face.txt")
GH_GRAPHQL = "https://api.github.com/graphql"
GH_REST = "https://api.github.com"

# ── api helpers ───────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"bearer {token}", "Accept": "application/vnd.github+json"}


def gql(token: str, query: str, variables: dict | None = None) -> dict:
    r = requests.post(
        GH_GRAPHQL,
        json={"query": query, "variables": variables or {}},
        headers=_headers(token),
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def rest(token: str, path: str, **params: Any) -> Any:
    r = requests.get(
        f"{GH_REST}{path}",
        headers=_headers(token),
        params=params or None,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── graphql queries ───────────────────────────────────────────────────────────

_USER_Q = """
query($login: String!, $after: String) {
  user(login: $login) {
    followers { totalCount }
    repositories(
      ownerAffiliations: OWNER
      privacy: PUBLIC
      first: 100
      after: $after
    ) {
      totalCount
      nodes { nameWithOwner stargazerCount isFork }
      pageInfo { hasNextPage endCursor }
    }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
    }
    repositoriesContributedTo(
      contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
      includeUserRepositories: false
      first: 1
    ) { totalCount }
  }
}
"""


def fetch_stats(token: str) -> dict:
    all_repos: list[dict] = []
    cursor: str | None = None
    total_public = 0
    data: dict = {}

    while True:
        data = gql(token, _USER_Q, {"login": USERNAME, "after": cursor})["user"]
        page = data["repositories"]
        all_repos.extend(page["nodes"])
        total_public = page["totalCount"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    owned = [r for r in all_repos if not r["isFork"]]
    stars = sum(r["stargazerCount"] for r in owned)
    cc = data["contributionsCollection"]
    commits = cc["totalCommitContributions"] + cc["restrictedContributionsCount"]

    return {
        "repos": len(owned),
        "repos_total": total_public,
        "contributed": data["repositoriesContributedTo"]["totalCount"],
        "stars": stars,
        "followers": data["followers"]["totalCount"],
        "commits": commits,
        "repo_names": [r["nameWithOwner"] for r in owned],
    }


# ── lines-of-code (cached per repo) ──────────────────────────────────────────

def fetch_loc(token: str, repo_names: list[str], cache: dict) -> tuple[int, int, int]:
    """Returns (total, added, deleted). Caches by repo hash."""
    total_add = total_del = 0

    for repo in repo_names:
        key = hashlib.md5(repo.encode()).hexdigest()
        if key in cache:
            total_add += cache[key]["add"]
            total_del += cache[key]["del"]
            continue

        owner, name = repo.split("/", 1)
        data = None
        for _ in range(5):
            try:
                data = rest(token, f"/repos/{owner}/{name}/stats/contributors")
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    break
                time.sleep(2)
                continue
            if isinstance(data, list):
                break
            time.sleep(3)  # 202 = GitHub still computing stats, retry

        if not isinstance(data, list):
            continue

        add = del_ = 0
        login_lower = USERNAME.lower()
        for contributor in data:
            author = contributor.get("author") or {}
            if author.get("login", "").lower() == login_lower:
                for week in contributor.get("weeks", []):
                    add += week.get("a", 0)
                    del_ += week.get("d", 0)

        cache[key] = {"add": add, "del": del_}
        total_add += add
        total_del += del_
        time.sleep(0.3)  # stay within rate limits

    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return total_add + total_del, total_add, total_del


# ── ascii portrait ────────────────────────────────────────────────────────────

def load_ascii() -> list[str]:
    lines = ASCII_FILE.read_text().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return [l.rstrip() for l in lines]


# ── svg colors ────────────────────────────────────────────────────────────────

DARK: dict[str, str] = {
    "bg": "#0d1117",
    "bg2": "#0a0c10",
    "border": "#30363d",
    "titlebar": "#161b22",
    "text": "#e6edf3",
    "dim": "#7d8590",
    "label": "#9198a1",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "red": "#f85149",
    "portrait": "#84e0b0",
    "dot_r": "#ff5f57",
    "dot_y": "#ffbd2e",
    "dot_g": "#28c840",
    "sep": "#21262d",
}

LIGHT: dict[str, str] = {
    "bg": "#ffffff",
    "bg2": "#f6f8fa",
    "border": "#d1d9e0",
    "titlebar": "#f6f8fa",
    "text": "#1f2328",
    "dim": "#636c76",
    "label": "#59636e",
    "accent": "#0969da",
    "green": "#1a7f37",
    "red": "#cf222e",
    "portrait": "#1f9a61",
    "dot_r": "#ff5f57",
    "dot_y": "#ffbd2e",
    "dot_g": "#28c840",
    "sep": "#d1d9e0",
}


# ── svg builder ───────────────────────────────────────────────────────────────

W = 940
H = 432
TITLE_H = 30
PANEL_L = 320       # left (portrait) panel width
CHAR_W = 0.6        # Courier advance width per em
MONO = "'Courier New', Courier, monospace"


def _x(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def _fmt(n: int) -> str:
    return f"{n:,}"


def make_svg(stats: dict, ascii_lines: list[str], c: dict[str, str]) -> str:
    # ── portrait: fill panel width (aspect-locked), anchored to bottom ──
    maxlen = max((len(l) for l in ascii_lines), default=1)
    fs = (PANEL_L - 2) / (maxlen * CHAR_W)   # scale so widest row spans the panel
    lh_a = fs * 1.2
    art_w = maxlen * fs * CHAR_W
    ax = (PANEL_L - art_w) / 2               # ≈0, edge to edge
    last_baseline = H - 5
    ay0 = last_baseline - (len(ascii_lines) - 1) * lh_a

    art_rows = []
    for i, line in enumerate(ascii_lines):
        y = ay0 + i * lh_a
        art_rows.append(
            f'<text x="{ax:.1f}" y="{y:.2f}" xml:space="preserve">{_x(line)}</text>'
        )
    portrait = "\n    ".join(art_rows)

    # ── info panel ──
    ix = PANEL_L + 26          # left edge of info text
    vx = ix + 96               # value column (after gutter label)
    rx = W - 24                # right edge
    rows: list[str] = []
    y = TITLE_H + 34.0

    def T(content: str, yy: float, xx: float, size: float,
          weight: str = "normal", anchor: str = "start") -> str:
        return (
            f'<text x="{xx:.0f}" y="{yy:.1f}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{content}</text>'
        )

    def rule(yy: float) -> str:
        return (
            f'<line x1="{ix}" y1="{yy:.1f}" x2="{rx}" y2="{yy:.1f}" '
            f'stroke="{c["sep"]}" stroke-width="1"/>'
        )

    def kv(label: str, value_spans: str, yy: float) -> str:
        return (
            T(f'<tspan fill="{c["label"]}">{_x(label)}</tspan>', yy, ix, 11.5)
            + T(value_spans, yy, vx, 11.5)
        )

    def section(title: str, yy: float) -> str:
        return T(
            f'<tspan fill="{c["accent"]}">▸ </tspan>'
            f'<tspan fill="{c["accent"]}" font-weight="600">{_x(title)}</tspan>',
            yy, ix, 11.5,
        )

    # header + "open to work" badge (pulsing dot)
    badge_y = y - 7
    rows.append(
        f'<circle cx="{rx-118}" cy="{badge_y:.1f}" r="4" fill="{c["green"]}"/>'
        + T(f'<tspan fill="{c["green"]}">open to work</tspan>', badge_y + 4, rx - 106, 11)
    )
    rows.append(T(
        f'<tspan fill="{c["text"]}" font-weight="700">{_x(NAME)}</tspan>'
        f'<tspan fill="{c["dim"]}" font-size="14"> @{USERNAME}</tspan>',
        y, ix, 21,
    ))
    y += 21
    # role line
    rows.append(T(
        f'<tspan fill="{c["dim"]}">// </tspan>'
        f'<tspan fill="{c["accent"]}">Software Engineer</tspan>'
        f'<tspan fill="{c["dim"]}"> · 6+ yrs commercial · MVP → Production</tspan>',
        y, ix, 11.5,
    ))
    y += 14
    rows.append(rule(y))
    y += 21

    # quick facts
    def val(s: str) -> str:
        return f'<tspan fill="{c["text"]}">{_x(s)}</tspan>'

    rows.append(kv("OS", val("macOS · Windows"), y));           y += 17
    rows.append(kv("IDE", val("VSCode · PyCharm"), y));          y += 17
    rows.append(kv("Spoken", val("Russian · English · Ukrainian"), y)); y += 23

    # stack
    rows.append(section("Stack", y)); y += 18
    stack = [
        ("Backend", "Python · FastAPI · asyncio · SQLAlchemy · PostgreSQL · Redis"),
        ("Frontend", "React · TypeScript · Vite · Leaflet"),
        ("DevOps", "Docker · Linux · Nginx · GitHub Actions"),
        ("Automation", "Chrome Ext MV3 · Playwright · FFmpeg · Celery"),
        ("Integrate", "REST · WebSocket · Payment / Crypto APIs"),
    ]
    for label, value in stack:
        rows.append(kv("  " + label, val(value), y)); y += 16.5
    y += 8

    # github stats
    rows.append(section("GitHub", y)); y += 18

    repos     = _fmt(stats["repos"])
    contribs  = _fmt(stats["contributed"])
    commits   = _fmt(stats["commits"])
    stars     = _fmt(stats["stars"])
    followers = _fmt(stats["followers"])
    loc_total = _fmt(stats["loc_total"])
    loc_add   = _fmt(stats["loc_add"])
    loc_del   = _fmt(stats["loc_del"])

    col2 = ix + 290

    def stat(label: str, value: str, xx: float, yy: float) -> str:
        return (
            T(f'<tspan fill="{c["label"]}">{_x(label)}</tspan>', yy, xx, 11.5)
            + T(f'<tspan fill="{c["text"]}" font-weight="600">{_x(value)}</tspan>',
                yy, xx + 92, 11.5)
        )

    rows.append(stat("  Repos", repos, ix, y) + stat("Stars", stars, col2, y));     y += 17
    rows.append(stat("  Commits", commits, ix, y) + stat("Followers", followers, col2, y)); y += 17
    rows.append(stat("  Contributed", f"{contribs} repos", ix, y)); y += 17
    rows.append(
        T(f'<tspan fill="{c["label"]}">  LOC</tspan>', y, ix, 11.5)
        + T(
            f'<tspan fill="{c["text"]}" font-weight="600">{loc_total}</tspan>'
            f'<tspan fill="{c["dim"]}">  (</tspan>'
            f'<tspan fill="{c["green"]}">+{loc_add}</tspan>'
            f'<tspan fill="{c["dim"]}">  </tspan>'
            f'<tspan fill="{c["red"]}">-{loc_del}</tspan>'
            f'<tspan fill="{c["dim"]}">)</tspan>',
            y, ix + 92, 11.5,
        )
    )
    # footer, anchored to the bottom of the window
    y = H - 42
    rows.append(rule(y)); y += 19
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows.append(
        T(
            f'<tspan fill="{c["accent"]}">vsevalid.dev</tspan>'
            f'<tspan fill="{c["sep"]}">   ·   </tspan>'
            f'<tspan fill="{c["accent"]}">@vsevalid</tspan>'
            f'<tspan fill="{c["sep"]}">   ·   </tspan>'
            f'<tspan fill="{c["accent"]}">hi@vsevalid.dev</tspan>',
            y, ix, 11.5,
        )
        + T(f'<tspan fill="{c["dim"]}">updated {updated}</tspan>', y, rx, 9.5,
            anchor="end")
    )

    info = "\n  ".join(rows)

    return f"""\
<svg width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg" font-family="{MONO}">
  <rect width="{W}" height="{H}" rx="9" fill="{c["bg"]}"/>
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="8.5" fill="none" stroke="{c["border"]}"/>

  <!-- left panel -->
  <path d="M0 9 a9 9 0 0 1 9 -9 h{PANEL_L-9} v{H} h{-(PANEL_L-9)} a9 9 0 0 1 -9 -9 Z" fill="{c["bg2"]}"/>
  <line x1="{PANEL_L}" y1="{TITLE_H}" x2="{PANEL_L}" y2="{H}" stroke="{c["sep"]}"/>

  <!-- title bar -->
  <path d="M0 9 a9 9 0 0 1 9 -9 h{W-18} a9 9 0 0 1 9 9 v{TITLE_H-9} h{-W} Z" fill="{c["titlebar"]}"/>
  <line x1="0" y1="{TITLE_H}" x2="{W}" y2="{TITLE_H}" stroke="{c["border"]}"/>
  <circle cx="17" cy="{TITLE_H/2:.0f}" r="5" fill="{c["dot_r"]}"/>
  <circle cx="34" cy="{TITLE_H/2:.0f}" r="5" fill="{c["dot_y"]}"/>
  <circle cx="51" cy="{TITLE_H/2:.0f}" r="5" fill="{c["dot_g"]}"/>
  <text x="{W/2:.0f}" y="{TITLE_H/2+4:.0f}" font-size="11.5" fill="{c["dim"]}"
        text-anchor="middle">{_x(NAME)} — profile</text>

  <!-- portrait -->
  <clipPath id="pclip"><rect x="0" y="{TITLE_H}" width="{PANEL_L-1}" height="{H-TITLE_H}"/></clipPath>
  <g clip-path="url(#pclip)" fill="{c["portrait"]}" font-size="{fs:.2f}" opacity="0.92">
    {portrait}
  </g>

  <!-- info -->
  {info}
</svg>
"""


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set GH_TOKEN or ACCESS_TOKEN env var")

    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}

    print("Fetching GitHub stats...")
    stats = fetch_stats(token)
    print(f"  repos={stats['repos']}  commits={stats['commits']}  stars={stats['stars']}")

    print(f"Fetching LOC for {len(stats['repo_names'])} repos (cached: {len(cache)})...")
    loc_total, loc_add, loc_del = fetch_loc(token, stats["repo_names"], cache)
    stats.update(loc_total=loc_total, loc_add=loc_add, loc_del=loc_del)
    print(f"  LOC={loc_total:,}  +{loc_add:,}  -{loc_del:,}")

    ascii_lines = load_ascii()
    print(f"Loaded {len(ascii_lines)} portrait lines")

    for mode, colors in [("light", LIGHT), ("dark", DARK)]:
        path = Path(f"{mode}_mode.svg")
        path.write_text(make_svg(stats, ascii_lines, colors))
        print(f"Written {path}")


if __name__ == "__main__":
    main()
