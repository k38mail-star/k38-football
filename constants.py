import settings

COLOR_PALETTE = ("#e74c3c", "#2ecc71", "#f39c12", "#3498db", "#9b59b6", "#1abc9c", "#e67e22")
LEAGUE_COLORS = {
    league_id: COLOR_PALETTE[index % len(COLOR_PALETTE)]
    for index, league_id in enumerate(settings.LEAGUES)
}
LEAGUE_ICONS = ("🏆", "🇬🇧", "🇪🇸", "🇮🇹", "🇩🇪", "🇫🇷", "🇨🇳", "⚽")

TEAM_NAMES_EN = {
    "利物浦": "Liverpool",
    "曼城": "Man City",
    "巴塞罗那": "Barcelona",
    "皇家马德里": "Real Madrid",
    "AC米兰": "AC Milan",
    "国际米兰": "Inter Milan",
    "拜仁慕尼黑": "Bayern Munich",
    "多特蒙德": "Borussia Dortmund",
    "中国": "China",
    "巴西": "Brazil",
    "葡萄牙": "Portugal",
    "刚果": "Congo DR",
    "英格兰": "England",
    "法国": "France",
    "德国": "Germany",
    "意大利": "Italy",
    "西班牙": "Spain",
    "荷兰": "Netherlands",
    "阿根廷": "Argentina",
}

TEAM_NAMES_CN = {english: chinese for chinese, english in TEAM_NAMES_EN.items()}
TEAM_FLAGS = {
    "China": "🇨🇳",
    "Brazil": "🇧🇷",
    "Portugal": "🇵🇹",
    "Congo DR": "🇨🇩",
    "England": "🏴",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Italy": "🇮🇹",
    "Spain": "🇪🇸",
    "Netherlands": "🇳🇱",
    "Argentina": "🇦🇷",
}


def _is_chinese_name(name):
    return any("\u4e00" <= char <= "\u9fff" for char in str(name or ""))


def enrich_team_fields(match):
    for side in ("home", "away"):
        raw = match.get(f"{side}_team") or ""
        if _is_chinese_name(raw):
            cn = raw
            en = TEAM_NAMES_EN.get(raw, raw)
        else:
            en = raw
            cn = TEAM_NAMES_CN.get(raw, "")
        match[f"{side}_team_cn"] = cn
        match[f"{side}_team_en"] = en
        match[f"{side}_flag"] = TEAM_FLAGS.get(en, "")
    return match
