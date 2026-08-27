"""Popular-station presets and the interactive terminal picker.

Every URL here was verified working (variant selection, playlist parse, and
segment download) before being added.
"""

from __future__ import annotations

STATIONS: dict[str, str] = {
    "cbc-radio2": "https://cbcradiolive.akamaized.net/hls/live/2041057/ES_R2ETR/master.m3u8",
    "cbc-radio1-toronto": "https://cbcradiolive.akamaized.net/hls/live/2041056/ES_R1ETO/master.m3u8",
    "fip": "https://stream.radiofrance.fr/fip/fip.m3u8",
    "france-inter": "https://stream.radiofrance.fr/franceinter/franceinter.m3u8",
    "franceinfo": "https://stream.radiofrance.fr/franceinfo/franceinfo.m3u8",
}


def pick_station() -> str:
    """Numbered menu of presets plus a custom-URL option; returns the chosen URL."""
    names = sorted(STATIONS)
    print("Choose a station:")
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name}")
    print(f"  {len(names) + 1}. enter a custom URL")
    while True:
        choice = input("> ").strip()
        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(names):
                return STATIONS[names[n - 1]]
            if n == len(names) + 1:
                url = input("URL: ").strip()
                if url:
                    return url
        print("Enter a number from the list.")
