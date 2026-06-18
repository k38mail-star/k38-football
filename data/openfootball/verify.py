#!/usr/bin/env python3
import json, os, sys

target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
os.chdir(target_dir)

files = sorted([f for f in os.listdir(".") if f.endswith(".json") and f != "verify.py"])

print(f"Total JSON files: {len(files)}")
print("=" * 70)

all_ok = True
for fname in files:
    fpath = os.path.join(".", fname)
    size = os.path.getsize(fpath)
    try:
        with open(fpath, "r") as f:
            data = json.load(f)
        status = "OK"
        if isinstance(data, dict):
            info = str(list(data.keys())[:5])
        elif isinstance(data, list):
            info = f"list[{len(data)} items]"
        else:
            info = type(data).__name__
    except Exception as e:
        status = f"FAIL: {e}"
        all_ok = False
    print(f"  [{status:4s}]  {fname:35s}  {size:>6,} bytes  {info}")

print("=" * 70)
total_size = sum(os.path.getsize(f) for f in files if f != "verify.py")
print(f"Total size: {total_size:,} bytes ({total_size/1024:.1f} KB)")
print(f"All valid:  {'YES' if all_ok else 'NO'}")

# Quick samples
print()
print("--- clubs.json top-5 ---")
with open("clubs.json") as f:
    clubs = json.load(f)
for i, club in enumerate(clubs[:5]):
    print(f"  {i+1}. {club.get('name', '?')} ({club.get('country', '?')})")

print()
print("--- worldcup_2022.json ---")
with open("worldcup_2022.json") as f:
    wc = json.load(f)
rounds = wc.get("rounds", [])
print(f"  Rounds: {len(rounds)}")
if rounds:
    r1 = rounds[0]
    matches = r1.get("matches", [])
    print(f"  First round: {r1.get('name', '?')} ({len(matches)} matches)")
    if matches:
        m = matches[0]
        t1 = m.get("team1", {}).get("name", "?")
        t2 = m.get("team2", {}).get("name", "?")
        print(f"  First match: {t1} vs {t2}")

print()
print("--- league_en.1.json (Premier League) ---")
with open("league_en.1.json") as f:
    pl = json.load(f)
print(f"  Name: {pl.get('name', '?')}")
print(f"  Season: {pl.get('season', '?')}")
rounds = pl.get("rounds", [])
print(f"  Rounds: {len(rounds)}")
if rounds:
    matches = rounds[0].get("matches", [])
    print(f"  First round matches: {len(matches)}")
