def normalize_events(raw):
    if not isinstance(raw, list):
        return []
    events = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        time_value = item.get("time")
        if isinstance(time_value, dict):
            time_value = time_value.get("elapsed")
        team = item.get("team")
        player = item.get("player")
        events.append({
            "time": time_value,
            "team": team.get("name") if isinstance(team, dict) else team,
            "player": player.get("name") if isinstance(player, dict) else player,
            "type": item.get("type", ""),
            "detail": item.get("detail", ""),
        })
    return events


def status_emoji(status):
    status = str(status or "").lower()
    if any(key in status for key in ("first half", "second half", "live", "progress", "halftime")):
        return "🟢"
    if any(key in status for key in ("match finished", "finished", "after")):
        return "🏁"
    return "📋"


def get_status_sort_key(status):
    status = str(status or "").lower()
    if any(key in status for key in ("first half", "second half", "live", "progress", "halftime")):
        return 1
    if any(key in status for key in ("not started", "time to be defined", "scheduled")):
        return 3
    if any(key in status for key in ("match finished", "finished", "after", "penalties")):
        return 4
    return 3


def format_score(home, away):
    if home is None or away is None:
        return "vs"
    return f"{home}:{away}"


def latest_goal_hint(events):
    goals = [event for event in events if str(event.get("type", "")).lower() == "goal"]
    if not goals:
        return ""
    goal = goals[-1]
    minute = goal.get("time")
    player = goal.get("player") or goal.get("team") or ""
    return f"{minute}' {player}".strip()
