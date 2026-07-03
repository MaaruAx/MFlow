#!/usr/bin/env python3
"""
Aggregate release-asset download counts from both Codeberg and GitHub
and publish them as a Shields.io "endpoint" badge JSON file.

Codeberg (Forgejo/Gitea) API:
  GET /api/v1/repos/{owner}/{repo}/releases
GitHub API:
  GET /repos/{owner}/{repo}/releases

Both endpoints return a list of releases, each with an "assets" array
that includes a "download_count" field per asset. This script sums
that field across every asset of every release on both platforms and
writes the combined total to a JSON file in the schema Shields.io's
"endpoint" badge expects:
  https://shields.io/badges/endpoint-badge

Codeberg/GitHub's APIs never expose a download counter for the
auto-generated "Source Code (zip)" / "Source Code (tar.gz)" links on
a release, because those archives are generated on the fly and never
stored or tracked server-side. Downloads from other sites/mirrors
(e.g. itch.io, third-party mirrors, direct source archive downloads)
aren't tracked by either API either. To account for these anyway,
this script also reads an optional plain-text file (EXTRA_DOWNLOADS_PATH)
and adds a manually-entered integer to the total. Lines starting with
"#" are treated as comments and ignored; the first non-comment,
non-blank line must contain the integer. Edit that file by hand
whenever you want to update the manual count; leave the number at 0
(or delete the file) if you don't want to add anything.
"""

import json
import os
import sys

import requests

CODEBERG_OWNER = "MaaruAx"
CODEBERG_REPO = "MFlow"
GITHUB_OWNER = "MaaruAX"
GITHUB_REPO = "MFlow"

OUTPUT_PATH = "downloads.json"
BADGE_LABEL = "Downloads"
BADGE_COLOR = "c4a7e7"
CACHE_SECONDS = 21600  # 6 hours, matches the workflow schedule

# Plain-text file with an optional comment header (lines starting with
# "#") followed by a single integer: manually-tracked downloads that
# the Codeberg/GitHub APIs can't report (source code zip/tar.gz
# downloads, or downloads from other sites/mirrors). Edit the number
# by hand whenever you want to update it. Missing file or invalid
# content is treated as 0, never a hard failure.
EXTRA_DOWNLOADS_PATH = "extra_downloads.txt"


def fetch_all_pages(url, params, headers, page_size_key):
    """Fetch every page of a paginated releases endpoint and return the
    combined list of release objects."""
    releases = []
    page = 1
    page_size = params[page_size_key]
    while True:
        query = dict(params)
        query["page"] = page
        response = requests.get(url, params=query, headers=headers, timeout=30)
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        releases.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return releases


def sum_downloads(releases):
    """Sum the download_count of every asset across every release."""
    total = 0
    for release in releases:
        for asset in release.get("assets", []):
            total += asset.get("download_count", 0)
    return total


def fetch_codeberg_total():
    url = f"https://codeberg.org/api/v1/repos/{CODEBERG_OWNER}/{CODEBERG_REPO}/releases"
    releases = fetch_all_pages(url, {"limit": 50}, headers={}, page_size_key="limit")
    return sum_downloads(releases)


def fetch_github_total():
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases = fetch_all_pages(url, {"per_page": 100}, headers=headers, page_size_key="per_page")
    return sum_downloads(releases)


def read_extra_downloads():
    """Read the manually-tracked extra download count from
    EXTRA_DOWNLOADS_PATH. Lines starting with '#' and blank lines are
    skipped; the first remaining line must be the integer. Returns 0
    if the file is missing, has no such line, or the line isn't a
    valid non-negative integer -- this is always a soft failure, since
    it's a manual/optional number."""
    try:
        with open(EXTRA_DOWNLOADS_PATH, "r", encoding="utf-8") as extra_file:
            lines = extra_file.readlines()
    except FileNotFoundError:
        return 0

    raw_value = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        raw_value = stripped
        break

    if raw_value is None:
        return 0

    try:
        value = int(raw_value)
    except ValueError:
        print(
            f"Warning: {EXTRA_DOWNLOADS_PATH} contains '{raw_value}', "
            "which isn't a valid integer. Ignoring it (treated as 0).",
            file=sys.stderr,
        )
        return 0

    if value < 0:
        print(
            f"Warning: {EXTRA_DOWNLOADS_PATH} contains a negative number "
            f"({value}). Ignoring it (treated as 0).",
            file=sys.stderr,
        )
        return 0

    return value


def format_count(count):
    """Format large numbers the way most download badges do, e.g. 12.3k."""
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k".replace(".0k", "k")
    return f"{count / 1_000_000:.1f}M".replace(".0M", "M")


def main():
    try:
        codeberg_total = fetch_codeberg_total()
        github_total = fetch_github_total()
    except requests.RequestException as error:
        # Fail loudly and leave the output file untouched, so a transient
        # API error never overwrites a good badge with a wrong one.
        print(f"Error fetching download stats: {error}", file=sys.stderr)
        sys.exit(1)

    extra_total = read_extra_downloads()
    total = codeberg_total + github_total + extra_total

    badge_data = {
        "schemaVersion": 1,
        "label": BADGE_LABEL,
        "message": format_count(total),
        "color": BADGE_COLOR,
        "cacheSeconds": CACHE_SECONDS,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as output_file:
        json.dump(badge_data, output_file, indent=2)
        output_file.write("\n")

    print(f"Codeberg downloads: {codeberg_total}")
    print(f"GitHub downloads:   {github_total}")
    print(f"Manual/extra:       {extra_total}")
    print(f"Combined total:     {total}")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
