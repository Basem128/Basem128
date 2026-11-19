#!/usr/bin/env python3
"""Create an automatically updating GitHub profile stats SVG.

Reads only the viewer's contribution calendar and owned repository total.
No private repository names, source files, or other sensitive data are written.
"""

import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import sys
from urllib import request, error

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "widget-style.json"
OUTPUT_PATH = ROOT / "assets" / "profile-stats.svg"
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_COLORS = {
    "background": "#110817", "accent": "#aa55e7",
    "primaryText": "#f6f0f9", "secondaryText": "#c0a9d0", "border": "#533668"
}

# Official GitHub Octicons repo-16; retain this notice in generated copies.
OCTICONS_LICENSE = """MIT License
Copyright (c) 2026 GitHub Inc.
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
REPO_ICON_PATH = (
    'M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0'
    ' 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm'
    '10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a'
    '.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25'
    ' 0 0 1-.4-.2Z'
)


def api(token: str, url: str, query: str | None = None) -> tuple:
    body = json.dumps({"query": query}).encode("utf-8") if query else None
    req = request.Request(url, data=body, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "profile-stats-svg",
    })
    try:
        with request.urlopen(req, timeout=40) as response:
            return json.load(response), response.headers
    except error.HTTPError as ex:
        raise RuntimeError(f"GitHub API returned HTTP {ex.code}. Check PROFILE_STATS_TOKEN access.") from ex


def fetch_account(token: str) -> dict:
    account, headers = api(token, "https://api.github.com/user")
    scopes = {scope.strip() for scope in headers.get("X-OAuth-Scopes", "").split(",")}
    if not scopes.intersection({"read:user", "user"}):
        raise RuntimeError(
            "Private contribution access is not verified. Set PROFILE_STATS_TOKEN to a "
            "classic personal access token with read:user scope. No output written."
        )
    for key in ("public_repos", "owned_private_repos"):
        if type(account.get(key)) is not int or account[key] < 0:
            raise RuntimeError(f"GitHub did not return a valid {key}; refusing incomplete totals.")
    return account


def gql(token: str, query: str) -> dict:
    output, _ = api(token, "https://api.github.com/graphql", query)
    if output.get("errors"):
        raise RuntimeError(f"GitHub GraphQL errors: {output['errors']}")
    if not output.get("data"):
        raise RuntimeError("GitHub API returned no data")
    return output["data"]


def year_windows(year: int, today: dt.date):
    """Split each year into half years (always under GraphQL's 1-year limit)."""
    windows = [(dt.date(year, 1, 1), dt.date(year, 6, 30)),
               (dt.date(year, 7, 1), dt.date(year, 12, 31))]
    for beginning, end in windows:
        if beginning > today:
            continue
        end = min(end, today)
        yield beginning, end


def fetch_stats(token: str, expected_login: str | None = None, today: dt.date | None = None) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    account = fetch_account(token)
    user = gql(token, """
    query {
      viewer {
        login
        createdAt
      }
    }
    """)["viewer"]
    login = user["login"]
    if login.casefold() != account["login"].casefold():
        raise RuntimeError("GitHub REST and GraphQL account identities differ. No output written.")
    if expected_login and login.casefold() != expected_login.casefold():
        raise RuntimeError(f"Token is for {login}, but expected {expected_login}. No output written.")

    # Scan every account year, including years omitted from a visibility-limited list.
    years = range(dt.date.fromisoformat(user["createdAt"][:10]).year, today.year + 1)
    contributions = 0
    dates = set()
    for year in years:
        year_total = 0
        for start, end in year_windows(year, today):
            query = f'''query {{
              viewer {{
                contributionsCollection(from: "{start.isoformat()}T00:00:00Z", to: "{end.isoformat()}T23:59:59Z") {{
                  contributionCalendar {{
                    totalContributions
                    weeks {{ contributionDays {{ date contributionCount }} }}
                  }}
                }}
              }}
            }}'''
            calendar = gql(token, query)["viewer"]["contributionsCollection"]["contributionCalendar"]
            contributions += calendar["totalContributions"]
            year_total += calendar["totalContributions"]
            for week in calendar["weeks"]:
                for day in week["contributionDays"]:
                    date = dt.date.fromisoformat(day["date"])
                    if start <= date <= end and day["contributionCount"] > 0:
                        dates.add(day["date"])
        print(f"{year}: {year_total} contributions")

    return {
        "contributions": contributions,
        "repositories": account["public_repos"] + account["owned_private_repos"],
        "active_days": len(dates),
        "updated": today.isoformat(),
    }


def checked_style(data: dict) -> dict:
    result = {}
    for key, default in DEFAULT_COLORS.items():
        value = data.get(key, default)
        if not isinstance(value, str) or not COLOR_RE.fullmatch(value):
            raise ValueError(f"Invalid color in widget-style.json: {key}")
        result[key] = value
    radius = data.get("cornerRadius", 18)
    if not isinstance(radius, (int, float)) or not 0 <= radius <= 40:
        raise ValueError("cornerRadius must be between 0 and 40")
    result["cornerRadius"] = radius
    return result


def svg(stats: dict, style: dict) -> str:
    s = checked_style(style)
    vals = [f"{int(stats['contributions']):,}", f"{int(stats['repositories']):,}",
            f"{int(stats['active_days']):,}"]
    title = html.escape("GitHub activity: contributions, repositories, active days")
    date = html.escape(str(stats["updated"]))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="256" viewBox="0 0 960 256" role="img" aria-label="{title}">
  <title>{title}</title>
  <!-- GitHub Octicons repo-16: https://github.com/primer/octicons
{OCTICONS_LICENSE}
  -->
  <desc>All-time public and private GitHub activity: {vals[0]} contributions, {vals[1]} owned repositories, and {vals[2]} active days.</desc>
  <rect x="1" y="1" width="958" height="254" rx="{s['cornerRadius']}" fill="{s['background']}" stroke="{s['border']}"/>
  <line x1="320" y1="40" x2="320" y2="208" stroke="{s['accent']}" opacity="0.45"/>
  <line x1="640" y1="40" x2="640" y2="208" stroke="{s['accent']}" opacity="0.45"/>
  <g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif" text-anchor="middle">
    <text x="160" y="119" fill="{s['primaryText']}" font-size="44" font-weight="700">{vals[0]}</text>
    <text x="160" y="182" fill="{s['primaryText']}" font-size="21" font-weight="600">Total Contributions</text>
    <text x="160" y="210" fill="{s['secondaryText']}" font-size="16">Public + private</text>
    <path d="M458.02 48.87 A52 52 0 1 0 501.98 48.87" fill="none" stroke="{s['accent']}" stroke-width="5" stroke-linecap="round"/>
    <path d="{REPO_ICON_PATH}" transform="translate(464 34) scale(2)" fill="{s['accent']}"/>
    <text x="480" y="111" fill="{s['primaryText']}" font-size="44" font-weight="700">{vals[1]}</text>
    <text x="480" y="182" fill="{s['primaryText']}" font-size="21" font-weight="600">Owned Repositories</text>
    <text x="480" y="210" fill="{s['secondaryText']}" font-size="16">Public + private</text>
    <text x="800" y="119" fill="{s['primaryText']}" font-size="44" font-weight="700">{vals[2]}</text>
    <text x="800" y="182" fill="{s['primaryText']}" font-size="21" font-weight="600">Active Days</text>
    <text x="800" y="210" fill="{s['secondaryText']}" font-size="16">All time</text>
  </g>
  <text x="936" y="238" fill="{s['secondaryText']}" opacity="0.8" font-size="11" font-family="Arial,sans-serif" text-anchor="end">Updated {date} UTC</text>
</svg>\n'''


def main():
    token = os.environ.get("PROFILE_STATS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing PROFILE_STATS_TOKEN. Add it as a GitHub Actions repository secret.")
    stats = fetch_stats(token, os.environ.get("GITHUB_REPOSITORY_OWNER"))
    style = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    output = svg(stats, style)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"Generated widget for {stats['repositories']} repos, {stats['contributions']} contributions, {stats['active_days']} days")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
