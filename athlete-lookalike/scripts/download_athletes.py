#!/usr/bin/env python3
"""
Download headshots for all NBA and NFL players.

Data sources:
- NBA: Uses nba_api for player list, ESPN for headshots
- NFL: Uses ESPN API for player list and headshots

Usage:
    python scripts/download_athletes.py --league nba
    python scripts/download_athletes.py --league nfl
    python scripts/download_athletes.py --league all
"""

import argparse
import json
import os
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data" / "profiles"

# Rate limiting
REQUEST_DELAY = 0.1  # seconds between requests
MAX_WORKERS = 5

# ESPN CDN URLs for headshots
ESPN_NBA_HEADSHOT = "https://a.espncdn.com/combiner/i?img=/i/headshots/nba/players/full/{player_id}.png&w=350&h=254"
ESPN_NFL_HEADSHOT = "https://a.espncdn.com/combiner/i?img=/i/headshots/nfl/players/full/{player_id}.png&w=350&h=254"

# ESPN API endpoints
ESPN_NBA_ATHLETES_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
ESPN_NFL_ATHLETES_API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"

# Team IDs for each league
NBA_TEAM_IDS = list(range(1, 31))  # 30 NBA teams
NFL_TEAM_IDS = list(range(1, 35))  # 32 NFL teams (some IDs skipped)


def get_session() -> requests.Session:
    """Create a requests session with retry logic."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    })
    return session


def download_image(session: requests.Session, url: str, save_path: Path) -> bool:
    """Download an image from URL to save_path."""
    try:
        response = session.get(url, timeout=10)
        if response.status_code == 200 and len(response.content) > 1000:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        print(f"  Error downloading {url}: {e}")
        return False


def sanitize_name(name: str) -> str:
    """Sanitize player name for use as directory name."""
    # Remove special characters, keep alphanumeric and spaces
    sanitized = "".join(c if c.isalnum() or c == " " else "" for c in name)
    # Replace spaces with underscores and strip
    return sanitized.strip().replace(" ", "_")


def fetch_nba_players_from_espn(session: requests.Session) -> list[dict]:
    """Fetch all NBA players from ESPN API."""
    players = []

    print("Fetching NBA players from ESPN...")
    for team_id in NBA_TEAM_IDS:
        try:
            url = ESPN_NBA_ATHLETES_API.format(team_id=team_id)
            response = session.get(url, timeout=10)
            if response.status_code != 200:
                continue

            data = response.json()
            team_name = data.get("team", {}).get("displayName", f"Team {team_id}")

            for athlete in data.get("athletes", []):
                player_id = athlete.get("id")
                full_name = athlete.get("fullName", athlete.get("displayName", ""))

                if player_id and full_name:
                    players.append({
                        "id": player_id,
                        "name": full_name,
                        "team": team_name,
                        "league": "nba"
                    })

            print(f"  {team_name}: {len(data.get('athletes', []))} players")
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  Error fetching team {team_id}: {e}")
            continue

    return players


def fetch_nba_historical_players(session: requests.Session) -> list[dict]:
    """Fetch historical NBA players using Basketball Reference or similar."""
    # Use a comprehensive player list from basketball-reference
    # This endpoint provides all-time player data
    players = []

    print("\nFetching historical NBA players...")

    # NBA Stats API - all players endpoint
    try:
        url = "https://stats.nba.com/stats/commonallplayers"
        params = {
            "LeagueID": "00",
            "Season": "2024-25",
            "IsOnlyCurrentSeason": "0"  # Get ALL players in history
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Referer": "https://www.nba.com/",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true"
        }

        response = session.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            results = data.get("resultSets", [{}])[0]
            headers_list = results.get("headers", [])
            rows = results.get("rowSet", [])

            # Find column indices
            id_idx = headers_list.index("PERSON_ID") if "PERSON_ID" in headers_list else 0
            name_idx = headers_list.index("DISPLAY_FIRST_LAST") if "DISPLAY_FIRST_LAST" in headers_list else 2

            for row in rows:
                player_id = row[id_idx]
                full_name = row[name_idx]

                if player_id and full_name:
                    players.append({
                        "id": str(player_id),
                        "name": full_name,
                        "team": "Historical",
                        "league": "nba"
                    })

            print(f"  Found {len(players)} total NBA players in history")
        else:
            print(f"  NBA Stats API returned {response.status_code}")

    except Exception as e:
        print(f"  Error fetching historical players: {e}")

    return players


def fetch_nfl_players_from_espn(session: requests.Session) -> list[dict]:
    """Fetch all NFL players from ESPN API."""
    players = []

    print("Fetching NFL players from ESPN...")
    for team_id in NFL_TEAM_IDS:
        try:
            url = ESPN_NFL_ATHLETES_API.format(team_id=team_id)
            response = session.get(url, timeout=10)
            if response.status_code != 200:
                continue

            data = response.json()
            team_name = data.get("team", {}).get("displayName", f"Team {team_id}")

            team_count = 0
            # NFL roster has nested structure: athletes[] contains position groups
            # Each position group has items[] with actual players
            for position_group in data.get("athletes", []):
                for athlete in position_group.get("items", []):
                    player_id = athlete.get("id")
                    full_name = athlete.get("fullName", athlete.get("displayName", ""))

                    if player_id and full_name:
                        players.append({
                            "id": player_id,
                            "name": full_name,
                            "team": team_name,
                            "league": "nfl"
                        })
                        team_count += 1

            print(f"  {team_name}: {team_count} players")
            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  Error fetching team {team_id}: {e}")
            continue

    return players


def fetch_nfl_historical_players(session: requests.Session) -> list[dict]:
    """Fetch historical NFL players from ESPN's all-time lists."""
    players = []

    print("\nFetching historical NFL players from ESPN...")

    # ESPN has paginated athlete lists per team's history
    # We'll use the search endpoint to find more players
    positions = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P"]

    for pos in positions:
        try:
            # ESPN search API for players
            url = f"https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes"
            params = {
                "limit": 1000,
                "active": "false",  # Include retired players
                "position": pos
            }

            response = session.get(url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                for athlete in data.get("items", []):
                    player_id = athlete.get("id")
                    full_name = athlete.get("fullName", "")

                    if player_id and full_name:
                        players.append({
                            "id": player_id,
                            "name": full_name,
                            "position": pos,
                            "team": "Historical",
                            "league": "nfl"
                        })

                print(f"  Position {pos}: {len(data.get('items', []))} players")

            time.sleep(REQUEST_DELAY)

        except Exception as e:
            print(f"  Error fetching {pos} players: {e}")

    return players


def download_player_headshot(
    session: requests.Session,
    player: dict,
    output_dir: Path
) -> tuple[str, bool]:
    """Download headshot for a single player."""
    league = player["league"]
    player_id = player["id"]
    player_name = sanitize_name(player["name"])

    # Create directory for this player
    player_dir = output_dir / league / player_name
    image_path = player_dir / f"{player_name}.png"

    # Skip if already downloaded
    if image_path.exists():
        return player["name"], True

    # Get the appropriate URL
    if league == "nba":
        # Try ESPN first, then NBA.com
        urls = [
            ESPN_NBA_HEADSHOT.format(player_id=player_id),
            f"https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png",
            f"https://cdn.nba.com/headshots/nba/latest/260x190/{player_id}.png"
        ]
    else:  # nfl
        urls = [
            ESPN_NFL_HEADSHOT.format(player_id=player_id),
            f"https://a.espncdn.com/i/headshots/nfl/players/full/{player_id}.png"
        ]

    # Try each URL until one works
    for url in urls:
        if download_image(session, url, image_path):
            return player["name"], True
        time.sleep(REQUEST_DELAY)

    return player["name"], False


def download_all_players(players: list[dict], output_dir: Path, max_workers: int = MAX_WORKERS):
    """Download headshots for all players using thread pool."""
    session = get_session()

    print(f"\nDownloading {len(players)} player headshots...")

    successful = 0
    failed = 0
    failed_names = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_player_headshot, session, player, output_dir): player
            for player in players
        }

        for i, future in enumerate(as_completed(futures), 1):
            player = futures[future]
            try:
                name, success = future.result()
                if success:
                    successful += 1
                else:
                    failed += 1
                    failed_names.append(name)

                if i % 100 == 0:
                    print(f"  Progress: {i}/{len(players)} ({successful} success, {failed} failed)")

            except Exception as e:
                failed += 1
                failed_names.append(player["name"])
                print(f"  Error processing {player['name']}: {e}")

    print(f"\nDownload complete!")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")

    if failed_names and len(failed_names) <= 20:
        print(f"  Failed players: {', '.join(failed_names)}")

    return successful, failed


def save_player_manifest(players: list[dict], output_dir: Path, league: str):
    """Save a JSON manifest of all players."""
    manifest_path = output_dir / f"{league}_players.json"
    with open(manifest_path, "w") as f:
        json.dump(players, f, indent=2)
    print(f"Saved manifest: {manifest_path}")


def main():
    parser = argparse.ArgumentParser(description="Download athlete headshots")
    parser.add_argument(
        "--league",
        choices=["nba", "nfl", "all"],
        default="all",
        help="Which league(s) to download"
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only download current players (skip historical)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DATA_DIR,
        help="Output directory for downloaded images"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help="Number of parallel download workers"
    )

    args = parser.parse_args()

    session = get_session()
    all_players = []

    # Fetch player lists
    if args.league in ["nba", "all"]:
        nba_players = fetch_nba_players_from_espn(session)
        if not args.current_only:
            nba_historical = fetch_nba_historical_players(session)
            # Merge and deduplicate by ID
            existing_ids = {p["id"] for p in nba_players}
            for p in nba_historical:
                if p["id"] not in existing_ids:
                    nba_players.append(p)
                    existing_ids.add(p["id"])

        print(f"\nTotal NBA players: {len(nba_players)}")
        save_player_manifest(nba_players, args.output_dir, "nba")
        all_players.extend(nba_players)

    if args.league in ["nfl", "all"]:
        nfl_players = fetch_nfl_players_from_espn(session)
        if not args.current_only:
            nfl_historical = fetch_nfl_historical_players(session)
            # Merge and deduplicate by ID
            existing_ids = {p["id"] for p in nfl_players}
            for p in nfl_historical:
                if p["id"] not in existing_ids:
                    nfl_players.append(p)
                    existing_ids.add(p["id"])

        print(f"\nTotal NFL players: {len(nfl_players)}")
        save_player_manifest(nfl_players, args.output_dir, "nfl")
        all_players.extend(nfl_players)

    # Download headshots
    if all_players:
        download_all_players(all_players, args.output_dir, args.workers)
    else:
        print("No players found to download.")


if __name__ == "__main__":
    main()
