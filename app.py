#!/usr/bin/env python3
"""
K38 足球监控 — Web 仪表盘
Flask 应用，提供本地可视化界面
"""

import json
from datetime import datetime

from flask import Flask, render_template, jsonify, request

import settings
from models import get_db, init_db
from collector import (
    load_seed_data,
    collect_from_api,
    ensure_prediction_context_for_fixture,
    get_h2h_cache,
    get_team_injuries,
    USE_MOCK,
)

app = Flask(__name__)

# 确保数据库就绪
init_db()

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

CLUB_TEAM_NAMES_CN = {
    "Liverpool": "利物浦",
    "Man City": "曼城",
    "Manchester City": "曼城",
    "Barcelona": "巴塞罗那",
    "Real Madrid": "皇家马德里",
    "AC Milan": "AC米兰",
    "Inter Milan": "国际米兰",
    "Inter": "国际米兰",
    "Bayern Munich": "拜仁慕尼黑",
    "Bayern München": "拜仁慕尼黑",
    "Borussia Dortmund": "多特蒙德",
}

COUNTRY_TRANSLATIONS = [
    ("AD", "Andorra", "安道尔"),
    ("AE", "United Arab Emirates", "阿拉伯联合酋长国"),
    ("AF", "Afghanistan", "阿富汗"),
    ("AG", "Antigua & Barbuda", "安提瓜和巴布达"),
    ("AI", "Anguilla", "安圭拉"),
    ("AL", "Albania", "阿尔巴尼亚"),
    ("AM", "Armenia", "亚美尼亚"),
    ("AO", "Angola", "安哥拉"),
    ("AQ", "Antarctica", "南极洲"),
    ("AR", "Argentina", "阿根廷"),
    ("AS", "American Samoa", "美属萨摩亚"),
    ("AT", "Austria", "奥地利"),
    ("AU", "Australia", "澳大利亚"),
    ("AW", "Aruba", "阿鲁巴"),
    ("AX", "Åland Islands", "奥兰群岛"),
    ("AZ", "Azerbaijan", "阿塞拜疆"),
    ("BA", "Bosnia & Herzegovina", "波斯尼亚和黑塞哥维那"),
    ("BB", "Barbados", "巴巴多斯"),
    ("BD", "Bangladesh", "孟加拉国"),
    ("BE", "Belgium", "比利时"),
    ("BF", "Burkina Faso", "布基纳法索"),
    ("BG", "Bulgaria", "保加利亚"),
    ("BH", "Bahrain", "巴林"),
    ("BI", "Burundi", "布隆迪"),
    ("BJ", "Benin", "贝宁"),
    ("BL", "St. Barthélemy", "圣巴泰勒米"),
    ("BM", "Bermuda", "百慕大"),
    ("BN", "Brunei", "文莱"),
    ("BO", "Bolivia", "玻利维亚"),
    ("BQ", "Caribbean Netherlands", "荷属加勒比区"),
    ("BR", "Brazil", "巴西"),
    ("BS", "Bahamas", "巴哈马"),
    ("BT", "Bhutan", "不丹"),
    ("BV", "Bouvet Island", "布韦岛"),
    ("BW", "Botswana", "博茨瓦纳"),
    ("BY", "Belarus", "白俄罗斯"),
    ("BZ", "Belize", "伯利兹"),
    ("CA", "Canada", "加拿大"),
    ("CC", "Cocos (Keeling) Islands", "科科斯（基林）群岛"),
    ("CD", "Congo - Kinshasa", "刚果（金）"),
    ("CF", "Central African Republic", "中非共和国"),
    ("CG", "Congo - Brazzaville", "刚果（布）"),
    ("CH", "Switzerland", "瑞士"),
    ("CI", "Côte d’Ivoire", "科特迪瓦"),
    ("CK", "Cook Islands", "库克群岛"),
    ("CL", "Chile", "智利"),
    ("CM", "Cameroon", "喀麦隆"),
    ("CN", "China", "中国"),
    ("CO", "Colombia", "哥伦比亚"),
    ("CR", "Costa Rica", "哥斯达黎加"),
    ("CU", "Cuba", "古巴"),
    ("CV", "Cape Verde", "佛得角"),
    ("CW", "Curaçao", "库拉索"),
    ("CX", "Christmas Island", "圣诞岛"),
    ("CY", "Cyprus", "塞浦路斯"),
    ("CZ", "Czechia", "捷克"),
    ("DE", "Germany", "德国"),
    ("DJ", "Djibouti", "吉布提"),
    ("DK", "Denmark", "丹麦"),
    ("DM", "Dominica", "多米尼克"),
    ("DO", "Dominican Republic", "多米尼加共和国"),
    ("DZ", "Algeria", "阿尔及利亚"),
    ("EC", "Ecuador", "厄瓜多尔"),
    ("EE", "Estonia", "爱沙尼亚"),
    ("EG", "Egypt", "埃及"),
    ("EH", "Western Sahara", "西撒哈拉"),
    ("ER", "Eritrea", "厄立特里亚"),
    ("ES", "Spain", "西班牙"),
    ("ET", "Ethiopia", "埃塞俄比亚"),
    ("FI", "Finland", "芬兰"),
    ("FJ", "Fiji", "斐济"),
    ("FK", "Falkland Islands", "福克兰群岛"),
    ("FM", "Micronesia", "密克罗尼西亚"),
    ("FO", "Faroe Islands", "法罗群岛"),
    ("FR", "France", "法国"),
    ("GA", "Gabon", "加蓬"),
    ("GB", "United Kingdom", "英国"),
    ("GD", "Grenada", "格林纳达"),
    ("GE", "Georgia", "格鲁吉亚"),
    ("GF", "French Guiana", "法属圭亚那"),
    ("GG", "Guernsey", "根西岛"),
    ("GH", "Ghana", "加纳"),
    ("GI", "Gibraltar", "直布罗陀"),
    ("GL", "Greenland", "格陵兰"),
    ("GM", "Gambia", "冈比亚"),
    ("GN", "Guinea", "几内亚"),
    ("GP", "Guadeloupe", "瓜德罗普"),
    ("GQ", "Equatorial Guinea", "赤道几内亚"),
    ("GR", "Greece", "希腊"),
    ("GS", "South Georgia & South Sandwich Islands", "南乔治亚和南桑威奇群岛"),
    ("GT", "Guatemala", "危地马拉"),
    ("GU", "Guam", "关岛"),
    ("GW", "Guinea-Bissau", "几内亚比绍"),
    ("GY", "Guyana", "圭亚那"),
    ("HK", "Hong Kong SAR China", "中国香港特别行政区"),
    ("HM", "Heard & McDonald Islands", "赫德岛和麦克唐纳群岛"),
    ("HN", "Honduras", "洪都拉斯"),
    ("HR", "Croatia", "克罗地亚"),
    ("HT", "Haiti", "海地"),
    ("HU", "Hungary", "匈牙利"),
    ("ID", "Indonesia", "印度尼西亚"),
    ("IE", "Ireland", "爱尔兰"),
    ("IL", "Israel", "以色列"),
    ("IM", "Isle of Man", "马恩岛"),
    ("IN", "India", "印度"),
    ("IO", "British Indian Ocean Territory", "英属印度洋领地"),
    ("IQ", "Iraq", "伊拉克"),
    ("IR", "Iran", "伊朗"),
    ("IS", "Iceland", "冰岛"),
    ("IT", "Italy", "意大利"),
    ("JE", "Jersey", "泽西岛"),
    ("JM", "Jamaica", "牙买加"),
    ("JO", "Jordan", "约旦"),
    ("JP", "Japan", "日本"),
    ("KE", "Kenya", "肯尼亚"),
    ("KG", "Kyrgyzstan", "吉尔吉斯斯坦"),
    ("KH", "Cambodia", "柬埔寨"),
    ("KI", "Kiribati", "基里巴斯"),
    ("KM", "Comoros", "科摩罗"),
    ("KN", "St. Kitts & Nevis", "圣基茨和尼维斯"),
    ("KP", "North Korea", "朝鲜"),
    ("KR", "South Korea", "韩国"),
    ("KW", "Kuwait", "科威特"),
    ("KY", "Cayman Islands", "开曼群岛"),
    ("KZ", "Kazakhstan", "哈萨克斯坦"),
    ("LA", "Laos", "老挝"),
    ("LB", "Lebanon", "黎巴嫩"),
    ("LC", "St. Lucia", "圣卢西亚"),
    ("LI", "Liechtenstein", "列支敦士登"),
    ("LK", "Sri Lanka", "斯里兰卡"),
    ("LR", "Liberia", "利比里亚"),
    ("LS", "Lesotho", "莱索托"),
    ("LT", "Lithuania", "立陶宛"),
    ("LU", "Luxembourg", "卢森堡"),
    ("LV", "Latvia", "拉脱维亚"),
    ("LY", "Libya", "利比亚"),
    ("MA", "Morocco", "摩洛哥"),
    ("MC", "Monaco", "摩纳哥"),
    ("MD", "Moldova", "摩尔多瓦"),
    ("ME", "Montenegro", "黑山"),
    ("MF", "St. Martin", "法属圣马丁"),
    ("MG", "Madagascar", "马达加斯加"),
    ("MH", "Marshall Islands", "马绍尔群岛"),
    ("MK", "North Macedonia", "北马其顿"),
    ("ML", "Mali", "马里"),
    ("MM", "Myanmar (Burma)", "缅甸"),
    ("MN", "Mongolia", "蒙古"),
    ("MO", "Macao SAR China", "中国澳门特别行政区"),
    ("MP", "Northern Mariana Islands", "北马里亚纳群岛"),
    ("MQ", "Martinique", "马提尼克"),
    ("MR", "Mauritania", "毛里塔尼亚"),
    ("MS", "Montserrat", "蒙特塞拉特"),
    ("MT", "Malta", "马耳他"),
    ("MU", "Mauritius", "毛里求斯"),
    ("MV", "Maldives", "马尔代夫"),
    ("MW", "Malawi", "马拉维"),
    ("MX", "Mexico", "墨西哥"),
    ("MY", "Malaysia", "马来西亚"),
    ("MZ", "Mozambique", "莫桑比克"),
    ("NA", "Namibia", "纳米比亚"),
    ("NC", "New Caledonia", "新喀里多尼亚"),
    ("NE", "Niger", "尼日尔"),
    ("NF", "Norfolk Island", "诺福克岛"),
    ("NG", "Nigeria", "尼日利亚"),
    ("NI", "Nicaragua", "尼加拉瓜"),
    ("NL", "Netherlands", "荷兰"),
    ("NO", "Norway", "挪威"),
    ("NP", "Nepal", "尼泊尔"),
    ("NR", "Nauru", "瑙鲁"),
    ("NU", "Niue", "纽埃"),
    ("NZ", "New Zealand", "新西兰"),
    ("OM", "Oman", "阿曼"),
    ("PA", "Panama", "巴拿马"),
    ("PE", "Peru", "秘鲁"),
    ("PF", "French Polynesia", "法属波利尼西亚"),
    ("PG", "Papua New Guinea", "巴布亚新几内亚"),
    ("PH", "Philippines", "菲律宾"),
    ("PK", "Pakistan", "巴基斯坦"),
    ("PL", "Poland", "波兰"),
    ("PM", "St. Pierre & Miquelon", "圣皮埃尔和密克隆群岛"),
    ("PN", "Pitcairn Islands", "皮特凯恩群岛"),
    ("PR", "Puerto Rico", "波多黎各"),
    ("PS", "Palestinian Territories", "巴勒斯坦领土"),
    ("PT", "Portugal", "葡萄牙"),
    ("PW", "Palau", "帕劳"),
    ("PY", "Paraguay", "巴拉圭"),
    ("QA", "Qatar", "卡塔尔"),
    ("RE", "Réunion", "留尼汪"),
    ("RO", "Romania", "罗马尼亚"),
    ("RS", "Serbia", "塞尔维亚"),
    ("RU", "Russia", "俄罗斯"),
    ("RW", "Rwanda", "卢旺达"),
    ("SA", "Saudi Arabia", "沙特阿拉伯"),
    ("SB", "Solomon Islands", "所罗门群岛"),
    ("SC", "Seychelles", "塞舌尔"),
    ("SD", "Sudan", "苏丹"),
    ("SE", "Sweden", "瑞典"),
    ("SG", "Singapore", "新加坡"),
    ("SH", "St. Helena", "圣赫勒拿"),
    ("SI", "Slovenia", "斯洛文尼亚"),
    ("SJ", "Svalbard & Jan Mayen", "斯瓦尔巴和扬马延"),
    ("SK", "Slovakia", "斯洛伐克"),
    ("SL", "Sierra Leone", "塞拉利昂"),
    ("SM", "San Marino", "圣马力诺"),
    ("SN", "Senegal", "塞内加尔"),
    ("SO", "Somalia", "索马里"),
    ("SR", "Suriname", "苏里南"),
    ("SS", "South Sudan", "南苏丹"),
    ("ST", "São Tomé & Príncipe", "圣多美和普林西比"),
    ("SV", "El Salvador", "萨尔瓦多"),
    ("SX", "Sint Maarten", "荷属圣马丁"),
    ("SY", "Syria", "叙利亚"),
    ("SZ", "Eswatini", "斯威士兰"),
    ("TC", "Turks & Caicos Islands", "特克斯和凯科斯群岛"),
    ("TD", "Chad", "乍得"),
    ("TF", "French Southern Territories", "法属南部领地"),
    ("TG", "Togo", "多哥"),
    ("TH", "Thailand", "泰国"),
    ("TJ", "Tajikistan", "塔吉克斯坦"),
    ("TK", "Tokelau", "托克劳"),
    ("TL", "Timor-Leste", "东帝汶"),
    ("TM", "Turkmenistan", "土库曼斯坦"),
    ("TN", "Tunisia", "突尼斯"),
    ("TO", "Tonga", "汤加"),
    ("TR", "Türkiye", "土耳其"),
    ("TT", "Trinidad & Tobago", "特立尼达和多巴哥"),
    ("TV", "Tuvalu", "图瓦卢"),
    ("TW", "Taiwan", "台湾"),
    ("TZ", "Tanzania", "坦桑尼亚"),
    ("UA", "Ukraine", "乌克兰"),
    ("UG", "Uganda", "乌干达"),
    ("UM", "U.S. Outlying Islands", "美国本土外小岛屿"),
    ("US", "United States", "美国"),
    ("UY", "Uruguay", "乌拉圭"),
    ("UZ", "Uzbekistan", "乌兹别克斯坦"),
    ("VA", "Vatican City", "梵蒂冈"),
    ("VC", "St. Vincent & Grenadines", "圣文森特和格林纳丁斯"),
    ("VE", "Venezuela", "委内瑞拉"),
    ("VG", "British Virgin Islands", "英属维尔京群岛"),
    ("VI", "U.S. Virgin Islands", "美属维尔京群岛"),
    ("VN", "Vietnam", "越南"),
    ("VU", "Vanuatu", "瓦努阿图"),
    ("WF", "Wallis & Futuna", "瓦利斯和富图纳"),
    ("WS", "Samoa", "萨摩亚"),
    ("YE", "Yemen", "也门"),
    ("YT", "Mayotte", "马约特"),
    ("ZA", "South Africa", "南非"),
    ("ZM", "Zambia", "赞比亚"),
    ("ZW", "Zimbabwe", "津巴布韦"),
]

COUNTRY_ALIASES = {
    "Antigua and Barbuda": ("安提瓜和巴布达", "AG"),
    "Bahamas": ("巴哈马", "BS"),
    "Bolivia": ("玻利维亚", "BO"),
    "Bosnia": ("波黑", "BA"),
    "Bosnia and Herzegovina": ("波黑", "BA"),
    "Bosnia & Herzegovina": ("波黑", "BA"),
    "British Virgin Islands": ("英属维尔京群岛", "VG"),
    "Burma": ("缅甸", "MM"),
    "Cape Verde Islands": ("佛得角", "CV"),
    "Chinese Taipei": ("中国台北", "TW"),
    "Congo": ("刚果", "CG"),
    "Congo DR": ("刚果", "CD"),
    "Curacao": ("库拉索", "CW"),
    "Czech Republic": ("捷克", "CZ"),
    "DR Congo": ("刚果", "CD"),
    "England": ("英格兰", None),
    "Eswatini": ("斯威士兰", "SZ"),
    "Faroe Islands": ("法罗群岛", "FO"),
    "Hong Kong": ("中国香港", "HK"),
    "Hong Kong, China": ("中国香港", "HK"),
    "Indonesia": ("印尼", "ID"),
    "Ivory Coast": ("科特迪瓦", "CI"),
    "Korea DPR": ("朝鲜", "KP"),
    "Korea Republic": ("韩国", "KR"),
    "Kosovo": ("科索沃", "XK"),
    "Kyrgyz Republic": ("吉尔吉斯斯坦", "KG"),
    "Laos": ("老挝", "LA"),
    "Macau": ("中国澳门", "MO"),
    "Macao": ("中国澳门", "MO"),
    "Macedonia": ("北马其顿", "MK"),
    "Micronesia": ("密克罗尼西亚", "FM"),
    "Moldova": ("摩尔多瓦", "MD"),
    "Myanmar": ("缅甸", "MM"),
    "Northern Ireland": ("北爱尔兰", None),
    "Palestine": ("巴勒斯坦", "PS"),
    "Republic of Ireland": ("爱尔兰", "IE"),
    "Russia": ("俄罗斯", "RU"),
    "Samoa": ("萨摩亚", "WS"),
    "Saudi": ("沙特", "SA"),
    "Scotland": ("苏格兰", None),
    "Sint Maarten": ("荷属圣马丁", "SX"),
    "St. Kitts and Nevis": ("圣基茨和尼维斯", "KN"),
    "St. Lucia": ("圣卢西亚", "LC"),
    "St. Vincent and the Grenadines": ("圣文森特和格林纳丁斯", "VC"),
    "Syria": ("叙利亚", "SY"),
    "Taiwan": ("中国台北", "TW"),
    "Tanzania": ("坦桑尼亚", "TZ"),
    "The Gambia": ("冈比亚", "GM"),
    "Trinidad and Tobago": ("特立尼达和多巴哥", "TT"),
    "Turkey": ("土耳其", "TR"),
    "Türkiye": ("土耳其", "TR"),
    "UAE": ("阿联酋", "AE"),
    "United Arab Emirates": ("阿联酋", "AE"),
    "United States": ("美国", "US"),
    "United States of America": ("美国", "US"),
    "USA": ("美国", "US"),
    "Vietnam": ("越南", "VN"),
    "Wales": ("威尔士", None),
}

SUBDIVISION_FLAGS = {
    "England": "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "英格兰": "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "Scotland": "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "苏格兰": "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
    "Wales": "\U0001f3f4\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f",
    "威尔士": "\U0001f3f4\U000e0067\U000e0062\U000e0077\U000e006c\U000e0073\U000e007f",
    "Northern Ireland": "🇬🇧",
    "北爱尔兰": "🇬🇧",
}


def _flag_from_country_code(code):
    if not code or len(code) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code.upper())


TEAM_NAMES_CN = dict(CLUB_TEAM_NAMES_CN)
TEAM_NAMES_CN.update({english: chinese for _, english, chinese in COUNTRY_TRANSLATIONS})
TEAM_NAMES_CN.update({english: chinese for english, (chinese, _) in COUNTRY_ALIASES.items()})

TEAM_FLAGS = {
    27: "🇵🇹",
    2000: "🇨🇳",
    2001: "🇧🇷",
}
for code, english, chinese in COUNTRY_TRANSLATIONS:
    flag = _flag_from_country_code(code)
    TEAM_FLAGS[english] = flag
    TEAM_FLAGS[chinese] = flag
for english, (chinese, code) in COUNTRY_ALIASES.items():
    flag = _flag_from_country_code(code)
    if flag:
        TEAM_FLAGS[english] = flag
        TEAM_FLAGS[chinese] = flag
TEAM_FLAGS.update(SUBDIVISION_FLAGS)


def _normalize_events(raw):
    """Normalize OpenFootball style events to match detail display format."""
    if not isinstance(raw, list):
        return raw
    result = []
    for e in raw:
        if isinstance(e, dict) and 'name' in e and 'minute' in e:
            result.append({
                'type': 'Goal',
                'time': {'elapsed': e.get('minute', 0), 'extra': None},
                'team': {'name': '', 'id': None},
                'player': {'name': e.get('name', ''), 'id': None},
                'detail': 'Normal Goal',
                'comments': ''
            })
        else:
            result.append(e)
    return result


def status_emoji(status):
    if not status:
        return "📋"
    if "Finished" in status:
        return "🏁"
    if "Half" in status or "Live" in status or status in ("Second Half", "First Half", "In Progress"):
        return "🟢"
    if "Penalty" in status or "Extra" in status:
        return "⚡"
    if "Suspended" in status or "Interrupted" in status:
        return "⏸"
    return "📋"


def get_status_sort_key(status):
    """排序：进行中 > 半场 > 未开始 > 已结束"""
    if not status:
        return 3
    if "Half" in status or status in ("First Half", "Halftime"):
        return 1
    if "Live" in status or status in ("Second Half", "In Progress"):
        return 0
    if "Finished" in status:
        return 4
    if "Extra" in status or "Penalty" in status:
        return 0
    if "Suspended" in status or "Interrupted" in status:
        return 2
    return 3


def format_score(h, a):
    if h is None and a is None:
        return "vs"
    return f"{h if h is not None else '?'} - {a if a is not None else '?'}"


def _is_chinese_name(name):
    return any("\u4e00" <= char <= "\u9fff" for char in name or "")


def enrich_team_fields(match):
    home_team = match.get("home_team") or ""
    away_team = match.get("away_team") or ""
    home_team_id = match.get("home_team_id")
    away_team_id = match.get("away_team_id")

    match["home_team_cn"] = home_team if _is_chinese_name(home_team) else TEAM_NAMES_CN.get(home_team, "")
    match["away_team_cn"] = away_team if _is_chinese_name(away_team) else TEAM_NAMES_CN.get(away_team, "")
    match["home_team_en"] = TEAM_NAMES_EN.get(home_team, home_team if not _is_chinese_name(home_team) else "")
    match["away_team_en"] = TEAM_NAMES_EN.get(away_team, away_team if not _is_chinese_name(away_team) else "")
    match["home_flag"] = TEAM_FLAGS.get(home_team_id) or TEAM_FLAGS.get(home_team) or TEAM_FLAGS.get(match["home_team_en"], "")
    match["away_flag"] = TEAM_FLAGS.get(away_team_id) or TEAM_FLAGS.get(away_team) or TEAM_FLAGS.get(match["away_team_en"], "")
    return match


def latest_goal_hint(events):
    """Return a short display hint for the latest goal event."""
    goals = [event for event in events if event.get("type") == "Goal"]
    if not goals:
        return ""
    latest = max(goals, key=lambda item: int(item.get("time", {}).get("elapsed", 0)) if isinstance(item.get("time"), dict) else int(item.get("time") or 0))
    player = latest.get("player") or latest.get("detail", "").strip()
    team = latest.get("team", "")
    minute_raw = latest.get("time", "")
    if isinstance(minute_raw, dict):
        minute = str(minute_raw.get("elapsed", ""))
    else:
        minute = str(minute_raw)
    label = f"{minute}' " if minute != "" else ""
    return f"⚽ {label}{team} {player}".strip()


def is_finished(status):
    return bool(status and "Finished" in status)


def _match_timestamp(match):
    value = match.get("match_date") or ""
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0


def _team_identity(match, side):
    return {
        "id": match.get(f"{side}_team_id"),
        "name": match.get(f"{side}_team") or "",
    }


def _same_team(identity, team_id, team_name):
    id_matches = identity.get("id") is not None and team_id is not None and identity["id"] == team_id
    name_matches = bool(identity.get("name") and identity["name"] == team_name)
    return id_matches or name_matches


def _match_has_team(match, identity):
    return (
        _same_team(identity, match.get("home_team_id"), match.get("home_team"))
        or _same_team(identity, match.get("away_team_id"), match.get("away_team"))
    )


def _team_result(match, identity):
    if _same_team(identity, match.get("home_team_id"), match.get("home_team")):
        side = "home"
        goals_for = int(match["home_goals"])
        goals_against = int(match["away_goals"])
        ht_for = match.get("halftime_home")
        ht_against = match.get("halftime_away")
    elif _same_team(identity, match.get("away_team_id"), match.get("away_team")):
        side = "away"
        goals_for = int(match["away_goals"])
        goals_against = int(match["home_goals"])
        ht_for = match.get("halftime_away")
        ht_against = match.get("halftime_home")
    else:
        return None

    if goals_for > goals_against:
        outcome = "win"
    elif goals_for < goals_against:
        outcome = "loss"
    else:
        outcome = "draw"

    halftime_lead = (
        ht_for is not None
        and ht_against is not None
        and int(ht_for) > int(ht_against)
    )
    return {
        "side": side,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "outcome": outcome,
        "halftime_lead": halftime_lead,
    }


def _team_prediction_stats(team_name, identity, matches):
    recent = sorted(
        [match for match in matches if _match_has_team(match, identity)],
        key=_match_timestamp,
        reverse=True,
    )[:5]
    results = [_team_result(match, identity) for match in recent]
    results = [result for result in results if result]
    played = len(results)
    wins = sum(1 for result in results if result["outcome"] == "win")
    draws = sum(1 for result in results if result["outcome"] == "draw")
    losses = sum(1 for result in results if result["outcome"] == "loss")
    goals_for = sum(result["goals_for"] for result in results)
    goals_against = sum(result["goals_against"] for result in results)
    halftime_leads = [result for result in results if result["halftime_lead"]]
    halftime_lead_wins = sum(1 for result in halftime_leads if result["outcome"] == "win")

    return {
        "team": team_name,
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": wins / played if played else 0,
        "avg_goals_for": goals_for / played if played else 0,
        "avg_goals_against": goals_against / played if played else 0,
        "halftime_leads": len(halftime_leads),
        "halftime_lead_win_rate": halftime_lead_wins / len(halftime_leads) if halftime_leads else None,
    }


def _head_to_head_stats(matches, home_identity, away_identity):
    h2h_matches = [
        match for match in matches
        if _match_has_team(match, home_identity) and _match_has_team(match, away_identity)
    ]
    home_wins = away_wins = draws = 0
    for match in h2h_matches:
        home_result = _team_result(match, home_identity)
        if not home_result:
            continue
        if home_result["outcome"] == "win":
            home_wins += 1
        elif home_result["outcome"] == "loss":
            away_wins += 1
        else:
            draws += 1
    total = home_wins + away_wins + draws
    return {
        "total": total,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "draws": draws,
        "home_win_rate": home_wins / total if total else 0,
        "away_win_rate": away_wins / total if total else 0,
    }


def _api_h2h_stats(home_team_id, away_team_id):
    cached = get_h2h_cache(home_team_id, away_team_id) if home_team_id and away_team_id else None
    if not cached:
        return {
            "total": 0,
            "home_wins": 0,
            "away_wins": 0,
            "draws": 0,
            "home_win_rate": 0,
            "away_win_rate": 0,
            "draw_rate": 0,
            "fixtures": [],
            "fetched_at": None,
            "fresh": False,
        }

    total = cached["total"]
    if cached["team1_id"] == int(home_team_id):
        home_wins = cached["team1_wins"]
        away_wins = cached["team2_wins"]
    else:
        home_wins = cached["team2_wins"]
        away_wins = cached["team1_wins"]
    draws = cached["draws"]
    return {
        "total": total,
        "home_wins": home_wins,
        "away_wins": away_wins,
        "draws": draws,
        "home_win_rate": home_wins / total if total else 0,
        "away_win_rate": away_wins / total if total else 0,
        "draw_rate": draws / total if total else 0,
        "fixtures": cached["fixtures"],
        "fetched_at": cached["fetched_at"],
        "fresh": cached["fresh"],
    }


def _initial_team_elo(team_id, team_name):
    if team_id is not None:
        return 1500.0
    return 1500.0 if team_name else 1500.0


def _elo_key(match, side):
    return match.get(f"{side}_team_id") or match.get(f"{side}_team")


def _calculate_elos(matches):
    ratings = {}
    for match in sorted(matches, key=_match_timestamp):
        home_key = _elo_key(match, "home")
        away_key = _elo_key(match, "away")
        if not home_key or not away_key:
            continue
        home_rating = ratings.get(home_key, _initial_team_elo(match.get("home_team_id"), match.get("home_team")))
        away_rating = ratings.get(away_key, _initial_team_elo(match.get("away_team_id"), match.get("away_team")))
        expected_home = 1 / (1 + 10 ** ((away_rating - (home_rating + 60)) / 400))
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        if home_goals > away_goals:
            score_home = 1.0
        elif home_goals < away_goals:
            score_home = 0.0
        else:
            score_home = 0.5
        goal_margin = abs(home_goals - away_goals)
        multiplier = 1.0 if goal_margin <= 1 else 1.0 + min(goal_margin - 1, 3) * 0.25
        delta = 24 * multiplier * (score_home - expected_home)
        ratings[home_key] = home_rating + delta
        ratings[away_key] = away_rating - delta
    return ratings


def _elo_stats(home_identity, away_identity, completed_matches):
    ratings = _calculate_elos(completed_matches)
    home_key = home_identity.get("id") or home_identity.get("name")
    away_key = away_identity.get("id") or away_identity.get("name")
    home_elo = ratings.get(home_key, 1500.0)
    away_elo = ratings.get(away_key, 1500.0)
    expected_home = 1 / (1 + 10 ** ((away_elo - (home_elo + 60)) / 400))
    expected_away = 1 - expected_home
    return {
        "home_elo": round(home_elo),
        "away_elo": round(away_elo),
        "home_rate": expected_home,
        "away_rate": expected_away,
    }


def _injury_context(home_team_id, away_team_id):
    home = get_team_injuries(home_team_id) if home_team_id else {"injuries": [], "fresh": False, "fetched_at": None}
    away = get_team_injuries(away_team_id) if away_team_id else {"injuries": [], "fresh": False, "fetched_at": None}
    home_count = len(home.get("injuries", []))
    away_count = len(away.get("injuries", []))
    return {
        "home": home.get("injuries", []),
        "away": away.get("injuries", []),
        "home_count": home_count,
        "away_count": away_count,
        "home_penalty": min(20, home_count * 5),
        "away_penalty": min(20, away_count * 5),
        "home_fetched_at": home.get("fetched_at"),
        "away_fetched_at": away.get("fetched_at"),
        "home_fresh": home.get("fresh", False),
        "away_fresh": away.get("fresh", False),
    }


def _form_rates(home_stats, away_stats):
    home_score = 0.35 + home_stats["win_rate"] * 0.45 + max(-0.2, min(0.2, (home_stats["avg_goals_for"] - home_stats["avg_goals_against"]) * 0.08))
    away_score = 0.35 + away_stats["win_rate"] * 0.45 + max(-0.2, min(0.2, (away_stats["avg_goals_for"] - away_stats["avg_goals_against"]) * 0.08))
    if home_stats["played"] == 0 and away_stats["played"] > 0:
        home_score = 0.45
    if away_stats["played"] == 0 and home_stats["played"] > 0:
        away_score = 0.45
    total = max(0.01, home_score + away_score)
    return home_score / total, away_score / total


def _weighted_team_rates(home_stats, away_stats, h2h_stats, elo_stats):
    form_home, form_away = _form_rates(home_stats, away_stats)
    h2h_home = h2h_stats["home_win_rate"] if h2h_stats["total"] else 0.5
    h2h_away = h2h_stats["away_win_rate"] if h2h_stats["total"] else 0.5
    if h2h_stats["total"] and h2h_home == 0 and h2h_away == 0:
        h2h_home = h2h_away = 0.5
    home_rate = form_home * 0.40 + h2h_home * 0.30 + elo_stats["home_rate"] * 0.30
    away_rate = form_away * 0.40 + h2h_away * 0.30 + elo_stats["away_rate"] * 0.30
    return home_rate, away_rate


def _apply_injury_penalties(home_rate, away_rate, injuries):
    home_rate = max(0.05, home_rate - injuries["home_penalty"] / 100)
    away_rate = max(0.05, away_rate - injuries["away_penalty"] / 100)
    return home_rate, away_rate


def _prediction_probabilities(home_rate, away_rate, h2h_stats):
    diff = abs(home_rate - away_rate)
    draw_rate = max(0.18, min(0.32, 0.30 - diff * 0.25))
    if h2h_stats["total"]:
        draw_rate = max(0.16, min(0.36, draw_rate * 0.65 + h2h_stats["draw_rate"] * 0.35))
    team_total = max(0.01, home_rate + away_rate)
    remaining = 1 - draw_rate
    home_raw = remaining * (home_rate / team_total)
    away_raw = remaining * (away_rate / team_total)
    return _normalize_probabilities(home_raw, draw_rate, away_raw)


def _team_display_name(match, side):
    enriched = enrich_team_fields(dict(match))
    return enriched.get(f"{side}_team_en") or enriched.get(f"{side}_team") or ""


def _build_prediction_detail(winner, home_name, away_name, confidence):
    if winner == "draw":
        return f"{home_name} 与 {away_name}实力接近，预计平局概率较高"
    winner_name = home_name if winner == "home" else away_name
    loser_name = away_name if winner == "home" else home_name
    if confidence >= 65:
        return f"{winner_name}近期指标优于{loser_name}，预计获胜"
    return f"{winner_name}略占优势，但比赛仍有变数"


def _predicted_score(home_stats, away_stats, winner):
    home_expected = (
        (home_stats["avg_goals_for"] or 1.0) + (away_stats["avg_goals_against"] or 1.0)
    ) / 2 + 0.2
    away_expected = (
        (away_stats["avg_goals_for"] or 1.0) + (home_stats["avg_goals_against"] or 1.0)
    ) / 2
    home_score = max(0, min(5, round(home_expected)))
    away_score = max(0, min(5, round(away_expected)))

    if winner == "home" and home_score <= away_score:
        home_score = away_score + 1
    elif winner == "away" and away_score <= home_score:
        away_score = home_score + 1
    elif winner == "draw":
        tied = round((home_expected + away_expected) / 2)
        home_score = away_score = max(0, min(4, tied))

    return f"{home_score}-{away_score}"


def _normalize_probabilities(home_raw, draw_raw, away_raw):
    total = home_raw + draw_raw + away_raw
    home_prob = round(home_raw / total * 100)
    draw_prob = round(draw_raw / total * 100)
    away_prob = 100 - home_prob - draw_prob
    return home_prob, draw_prob, away_prob


def _prediction_factors(home_name, away_name, home_stats, away_stats, h2h_stats, injury_stats):
    factors = []
    for side, stats in (("home", home_stats), ("away", away_stats)):
        if not stats["played"]:
            continue
        team_name = home_name if side == "home" else away_name
        if stats["wins"] >= 3:
            factors.append({
                "text": f"{team_name} won {stats['wins']} of last {stats['played']} matches",
                "type": "positive",
                "team": side,
            })
        elif stats["losses"] >= 3:
            factors.append({
                "text": f"{team_name} lost {stats['losses']} of last {stats['played']}",
                "type": "negative",
                "team": side,
            })
        factors.append({
            "text": f"{team_name} scores {stats['avg_goals_for']:.1f} goals per match",
            "type": "stat",
            "team": side,
        })
        if stats["halftime_lead_win_rate"] is not None:
            factors.append({
                "text": f"{team_name} wins {round(stats['halftime_lead_win_rate'] * 100)}% when leading at halftime",
                "type": "stat",
                "team": side,
            })

    if h2h_stats["total"]:
        if h2h_stats["home_wins"] > h2h_stats["away_wins"]:
            factors.append({
                "text": f"{home_name} H2H wins {h2h_stats['home_wins']} of {h2h_stats['total']}",
                "type": "positive",
                "team": "home",
            })
        elif h2h_stats["away_wins"] > h2h_stats["home_wins"]:
            factors.append({
                "text": f"{away_name} H2H wins {h2h_stats['away_wins']} of {h2h_stats['total']}",
                "type": "positive",
                "team": "away",
            })
        else:
            factors.append({
                "text": f"H2H is even across {h2h_stats['total']} matches",
                "type": "stat",
                "team": "draw",
            })

    if injury_stats["home_count"]:
        factors.append({
            "text": f"{home_name} {injury_stats['home_count']} injuries, -{injury_stats['home_penalty']}%",
            "type": "negative",
            "team": "home",
        })
    if injury_stats["away_count"]:
        factors.append({
            "text": f"{away_name} {injury_stats['away_count']} injuries, -{injury_stats['away_penalty']}%",
            "type": "negative",
            "team": "away",
        })
    return factors[:6]


def build_match_prediction(fixture_id, fixture=None):
    if fixture:
        ensure_prediction_context_for_fixture(fixture)

    with get_db() as conn:
        should_refresh_context = False
        if fixture is None:
            row = conn.execute(
                "SELECT * FROM football_matches WHERE fixture_id = ?",
                (fixture_id,),
            ).fetchone()
            if not row:
                return None
            fixture = dict(row)
            should_refresh_context = True
        completed_rows = conn.execute(
            """
            SELECT * FROM football_matches
            WHERE fixture_id != ?
              AND home_goals IS NOT NULL
              AND away_goals IS NOT NULL
              AND status LIKE '%Finished%'
            ORDER BY match_date DESC
            """,
            (fixture_id,),
        ).fetchall()

    if should_refresh_context:
        ensure_prediction_context_for_fixture(fixture)

    completed_matches = [dict(row) for row in completed_rows]
    same_league_matches = [
        match for match in completed_matches
        if match.get("league_id") == fixture.get("league_id")
    ]
    home_identity = _team_identity(fixture, "home")
    away_identity = _team_identity(fixture, "away")
    home_name = _team_display_name(fixture, "home")
    away_name = _team_display_name(fixture, "away")

    home_stats = _team_prediction_stats(home_name, home_identity, completed_matches)
    away_stats = _team_prediction_stats(away_name, away_identity, completed_matches)
    local_h2h_stats = _head_to_head_stats(same_league_matches, home_identity, away_identity)
    h2h_stats = _api_h2h_stats(fixture.get("home_team_id"), fixture.get("away_team_id"))
    if not h2h_stats["total"] and local_h2h_stats["total"]:
        h2h_stats = {
            **local_h2h_stats,
            "draw_rate": local_h2h_stats["draws"] / local_h2h_stats["total"],
            "fixtures": [],
            "fetched_at": None,
            "fresh": False,
        }
    elo_stats = _elo_stats(home_identity, away_identity, completed_matches)
    injury_stats = _injury_context(fixture.get("home_team_id"), fixture.get("away_team_id"))

    if home_stats["played"] == 0 and away_stats["played"] == 0:
        return {
            "fixture_id": fixture_id,
            "home_team": home_name,
            "away_team": away_name,
            "prediction": {
                "winner": None,
                "confidence": 0,
                "home_win_prob": 0,
                "draw_prob": 0,
                "away_win_prob": 0,
                "factors": [],
                "predicted_score": None,
                "prediction_detail": "暂无足够数据预测",
                "model_weights": {"recent_form": 40, "h2h": 30, "elo": 30},
                "h2h_summary": {
                    "total": h2h_stats["total"],
                    "home_wins": h2h_stats["home_wins"],
                    "away_wins": h2h_stats["away_wins"],
                    "draws": h2h_stats["draws"],
                    "fetched_at": h2h_stats.get("fetched_at"),
                },
                "injury_summary": {
                    "home_count": injury_stats["home_count"],
                    "away_count": injury_stats["away_count"],
                    "home_penalty": injury_stats["home_penalty"],
                    "away_penalty": injury_stats["away_penalty"],
                    "home_injuries": injury_stats["home"][:5],
                    "away_injuries": injury_stats["away"][:5],
                },
                "insufficient_data": True,
            },
        }

    home_rate, away_rate = _weighted_team_rates(home_stats, away_stats, h2h_stats, elo_stats)
    home_rate, away_rate = _apply_injury_penalties(home_rate, away_rate, injury_stats)
    home_prob, draw_prob, away_prob = _prediction_probabilities(home_rate, away_rate, h2h_stats)

    if draw_prob >= home_prob and draw_prob >= away_prob:
        winner = "draw"
        confidence = draw_prob
    elif home_prob >= away_prob:
        winner = "home"
        confidence = home_prob
    else:
        winner = "away"
        confidence = away_prob

    factors = _prediction_factors(home_name, away_name, home_stats, away_stats, h2h_stats, injury_stats)
    return {
        "fixture_id": fixture_id,
        "home_team": home_name,
        "away_team": away_name,
        "prediction": {
            "winner": winner,
            "confidence": confidence,
            "home_win_prob": home_prob,
            "draw_prob": draw_prob,
            "away_win_prob": away_prob,
            "factors": factors,
            "predicted_score": _predicted_score(home_stats, away_stats, winner),
            "prediction_detail": _build_prediction_detail(winner, home_name, away_name, confidence),
            "model_weights": {"recent_form": 40, "h2h": 30, "elo": 30},
            "h2h_summary": {
                "total": h2h_stats["total"],
                "home_wins": h2h_stats["home_wins"],
                "away_wins": h2h_stats["away_wins"],
                "draws": h2h_stats["draws"],
                "home_win_rate": round(h2h_stats["home_win_rate"] * 100),
                "away_win_rate": round(h2h_stats["away_win_rate"] * 100),
                "fetched_at": h2h_stats.get("fetched_at"),
            },
            "injury_summary": {
                "home_count": injury_stats["home_count"],
                "away_count": injury_stats["away_count"],
                "home_penalty": injury_stats["home_penalty"],
                "away_penalty": injury_stats["away_penalty"],
                "home_injuries": injury_stats["home"][:5],
                "away_injuries": injury_stats["away"][:5],
            },
            "elo_summary": {
                "home_elo": elo_stats["home_elo"],
                "away_elo": elo_stats["away_elo"],
                "home_rate": round(elo_stats["home_rate"] * 100),
                "away_rate": round(elo_stats["away_rate"] * 100),
            },
            "insufficient_data": False,
        },
    }


REFERENCE_CORNER_PREDICTION = {
    "first_half": {"low": 4, "high": 5, "expected": 4.5},
    "full_time": {"low": 9, "high": 10, "expected": 9.5},
}


def _json_stats(match):
    stats = match.get("stats") or {}
    if isinstance(stats, dict):
        return stats
    try:
        parsed = json.loads(stats)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stat_number(value):
    if value is None or value == "":
        return None
    cleaned = str(value).replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _stat_value(stats, stat_name, identity, period=None):
    keys = []
    if identity.get("id") is not None:
        keys.append(str(identity["id"]))
    if identity.get("name"):
        keys.append(str(identity["name"]))

    labels = [stat_name]
    if period:
        labels = [
            f"{period} {stat_name}",
            f"{stat_name} {period}",
        ]

    for label in labels:
        for key in keys:
            value = _stat_number(stats.get(f"{label}_{key}"))
            if value is not None:
                return value

    for raw_key, raw_value in stats.items():
        key = str(raw_key)
        if not any(key.endswith(f"_{team_key}") for team_key in keys):
            continue
        key_lower = key.lower()
        if stat_name.lower() not in key_lower:
            continue
        if period and period.lower() not in key_lower:
            continue
        if not period and "first half" in key_lower:
            continue
        value = _stat_number(raw_value)
        if value is not None:
            return value
    return None


def _corner_record_for_team(match, identity):
    if _same_team(identity, match.get("home_team_id"), match.get("home_team")):
        side = "home"
        team_identity = _team_identity(match, "home")
        opponent_identity = _team_identity(match, "away")
    elif _same_team(identity, match.get("away_team_id"), match.get("away_team")):
        side = "away"
        team_identity = _team_identity(match, "away")
        opponent_identity = _team_identity(match, "home")
    else:
        return None

    stats = _json_stats(match)
    corners_for = _stat_value(stats, "Corner Kicks", team_identity)
    corners_against = _stat_value(stats, "Corner Kicks", opponent_identity)
    if corners_for is None and corners_against is None:
        return None

    return {
        "side": side,
        "corners_for": corners_for,
        "corners_against": corners_against,
        "first_half_for": _stat_value(stats, "Corner Kicks", team_identity, period="First Half"),
        "first_half_against": _stat_value(stats, "Corner Kicks", opponent_identity, period="First Half"),
    }


def _average(values):
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _team_corner_stats(identity, matches):
    records = []
    for match in sorted(matches, key=_match_timestamp, reverse=True):
        record = _corner_record_for_team(match, identity)
        if record:
            records.append(record)
        if len(records) >= 10:
            break

    first_half_pairs = [
        record["first_half_for"] / record["corners_for"]
        for record in records
        if record.get("first_half_for") is not None and record.get("corners_for")
    ]
    first_half_share = _average(first_half_pairs)
    if first_half_share is None:
        first_half_share = 0.45
    first_half_share = max(0.35, min(0.55, first_half_share))

    return {
        "played": len(records),
        "avg_for": _average([record["corners_for"] for record in records]),
        "avg_against": _average([record["corners_against"] for record in records]),
        "avg_first_half_for": _average([record["first_half_for"] for record in records]),
        "avg_first_half_against": _average([record["first_half_against"] for record in records]),
        "first_half_share": first_half_share,
    }


def _blend_values(primary, secondary):
    values = [value for value in (primary, secondary) if value is not None]
    return sum(values) / len(values) if values else None


def _corner_range(expected, spread):
    low = max(0, round(expected - spread))
    high = max(low + 1, round(expected + spread))
    return {"low": int(low), "high": int(high), "expected": round(expected, 1)}


def _side_corner_expectation(team_stats, opponent_stats, venue):
    expected = _blend_values(team_stats["avg_for"], opponent_stats["avg_against"])
    if expected is None:
        return None, None

    venue_multiplier = 1.05 if venue == "home" else 0.95
    full_time = max(0, expected * venue_multiplier)
    first_half = _blend_values(
        team_stats["avg_first_half_for"],
        opponent_stats["avg_first_half_against"],
    )
    if first_half is None:
        first_half = full_time * team_stats["first_half_share"]
    else:
        first_half = max(0, first_half * venue_multiplier)
    return full_time, first_half


def _reference_corner_prediction(fixture_id, fixture):
    home_name = _team_display_name(fixture, "home")
    away_name = _team_display_name(fixture, "away")
    return {
        "fixture_id": fixture_id,
        "home_team": home_name,
        "away_team": away_name,
        "prediction": {
            "first_half": dict(REFERENCE_CORNER_PREDICTION["first_half"]),
            "full_time": dict(REFERENCE_CORNER_PREDICTION["full_time"]),
            "home_corners": None,
            "away_corners": None,
            "data_points": 0,
            "insufficient_data": True,
            "reference_used": True,
            "detail": "历史角球数据不足，使用世界杯场均角球参考值",
        },
    }


def build_corner_prediction(fixture_id, fixture=None):
    with get_db() as conn:
        if fixture is None:
            row = conn.execute(
                "SELECT * FROM football_matches WHERE fixture_id = ?",
                (fixture_id,),
            ).fetchone()
            if not row:
                return None
            fixture = dict(row)

        completed_rows = conn.execute(
            """
            SELECT * FROM football_matches
            WHERE fixture_id != ?
              AND home_goals IS NOT NULL
              AND away_goals IS NOT NULL
              AND status LIKE '%Finished%'
            ORDER BY match_date DESC
            """,
            (fixture_id,),
        ).fetchall()

    completed_matches = [dict(row) for row in completed_rows]
    home_identity = _team_identity(fixture, "home")
    away_identity = _team_identity(fixture, "away")
    home_stats = _team_corner_stats(home_identity, completed_matches)
    away_stats = _team_corner_stats(away_identity, completed_matches)
    data_points = home_stats["played"] + away_stats["played"]

    if data_points < 3:
        return _reference_corner_prediction(fixture_id, fixture)

    home_full, home_first = _side_corner_expectation(home_stats, away_stats, "home")
    away_full, away_first = _side_corner_expectation(away_stats, home_stats, "away")
    if home_full is None or away_full is None:
        return _reference_corner_prediction(fixture_id, fixture)

    total_full = home_full + away_full
    total_first = (home_first or home_full * 0.45) + (away_first or away_full * 0.45)
    home_name = _team_display_name(fixture, "home")
    away_name = _team_display_name(fixture, "away")

    return {
        "fixture_id": fixture_id,
        "home_team": home_name,
        "away_team": away_name,
        "prediction": {
            "first_half": _corner_range(total_first, 0.7),
            "full_time": _corner_range(total_full, 1.1),
            "home_corners": {
                "expected_first_half": round(home_first or home_full * 0.45, 1),
                "expected_full_time": round(home_full, 1),
                "history_matches": home_stats["played"],
                "avg_for": round(home_stats["avg_for"], 1) if home_stats["avg_for"] is not None else None,
                "avg_against": round(home_stats["avg_against"], 1) if home_stats["avg_against"] is not None else None,
            },
            "away_corners": {
                "expected_first_half": round(away_first or away_full * 0.45, 1),
                "expected_full_time": round(away_full, 1),
                "history_matches": away_stats["played"],
                "avg_for": round(away_stats["avg_for"], 1) if away_stats["avg_for"] is not None else None,
                "avg_against": round(away_stats["avg_against"], 1) if away_stats["avg_against"] is not None else None,
            },
            "data_points": data_points,
            "insufficient_data": False,
            "reference_used": False,
            "detail": "结合同队历史角球、对手被角球和主客场因素生成",
        },
    }


def compute_standings(league_filter="all"):
    """Calculate league standings from finished match results."""
    query = "SELECT * FROM football_matches WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL"
    params = []
    if league_filter != "all":
        query += " AND league_id = ?"
        params.append(int(league_filter))
    query += " ORDER BY league_id, match_date"

    tables = {}
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    for row in rows:
        match = dict(row)
        if not is_finished(match.get("status")):
            continue

        league_id = match.get("league_id")
        league_name = match.get("league_name") or settings.LEAGUES.get(league_id, str(league_id))
        table = tables.setdefault(
            league_id,
            {
                "league_id": league_id,
                "league_name": league_name,
                "league_color": LEAGUE_COLORS.get(league_id, "#666"),
                "teams": {},
            },
        )

        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        _apply_result(table["teams"], match["home_team"], home_goals, away_goals)
        _apply_result(table["teams"], match["away_team"], away_goals, home_goals)

    standings = []
    for table in tables.values():
        teams = sorted(
            table["teams"].values(),
            key=lambda team: (
                -team["points"],
                -team["goal_difference"],
                -team["goals_for"],
                team["team"],
            ),
        )
        for index, team in enumerate(teams, start=1):
            team["rank"] = index
        table["teams"] = teams
        standings.append(table)

    standings.sort(key=lambda table: table["league_name"])
    return standings


def _apply_result(teams, team_name, goals_for, goals_against):
    team = teams.setdefault(
        team_name,
        {
            "team": team_name,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        },
    )
    team["played"] += 1
    team["goals_for"] += goals_for
    team["goals_against"] += goals_against
    team["goal_difference"] = team["goals_for"] - team["goals_against"]
    if goals_for > goals_against:
        team["wins"] += 1
        team["points"] += 3
    elif goals_for == goals_against:
        team["draws"] += 1
        team["points"] += 1
    else:
        team["losses"] += 1


@app.route("/")
def index():
    return render_template(
        "index.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/matches")
def api_matches():
    league = request.args.get("league", "all")
    status_filter = request.args.get("status", "all")

    with get_db() as conn:
        if league == "all":
            rows = conn.execute(
                "SELECT * FROM football_matches ORDER BY match_date DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM football_matches WHERE league_id = ? ORDER BY match_date DESC",
                (int(league),)
            ).fetchall()

    matches = []
    for r in rows:
        m = dict(r)
        m["stats"] = json.loads(m.get("stats", "{}"))
        m["events"] = _normalize_events(json.loads(m.get("events", "[]")))
        m["score_display"] = format_score(m.get("home_goals"), m.get("away_goals"))
        m["status_sort"] = get_status_sort_key(m.get("status"))
        m["emoj"] = status_emoji(m.get("status"))
        m["league_color"] = LEAGUE_COLORS.get(m.get("league_id"), "#666")
        m["latest_goal"] = latest_goal_hint(m["events"])
        enrich_team_fields(m)
        matches.append(m)

    # 排序：进行中优先，然后是今天，最后按时间
    matches.sort(key=lambda m: (m["status_sort"], m.get("match_date", "")))

    if status_filter == "live":
        matches = [m for m in matches if m["status_sort"] <= 2]
    elif status_filter == "finished":
        matches = [m for m in matches if m["status_sort"] == 4]
    elif status_filter == "upcoming":
        matches = [m for m in matches if m["status_sort"] == 3 and m.get("home_goals") is None and m.get("away_goals") is None]

    for match in matches:
        if match["status_sort"] == 3 and match.get("home_goals") is None and match.get("away_goals") is None:
            prediction = build_match_prediction(match["fixture_id"], match)
            match["prediction"] = prediction["prediction"] if prediction else None
            corner_prediction = build_corner_prediction(match["fixture_id"], match)
            match["corner_prediction"] = corner_prediction["prediction"] if corner_prediction else None

    return jsonify({
        "matches": matches,
        "total": len(matches),
        "is_mock": USE_MOCK,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/match/<int:fixture_id>")
def api_match_detail(fixture_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM football_matches WHERE fixture_id = ?",
            (fixture_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "not found"}), 404

    m = dict(row)
    m["stats"] = json.loads(m.get("stats", "{}"))
    m["events"] = _normalize_events(json.loads(m.get("events", "[]")))
    m["score_display"] = format_score(m.get("home_goals"), m.get("away_goals"))
    m["status_sort"] = get_status_sort_key(m.get("status"))
    m["latest_goal"] = latest_goal_hint(m["events"])
    return jsonify(m)


@app.route("/api/predict/<int:fixture_id>")
def api_predict(fixture_id):
    prediction = build_match_prediction(fixture_id)
    if not prediction:
        return jsonify({"error": "not found"}), 404
    return jsonify(prediction)


@app.route("/api/predict/corners/<int:fixture_id>")
def api_predict_corners(fixture_id):
    prediction = build_corner_prediction(fixture_id)
    if not prediction:
        return jsonify({"error": "not found"}), 404
    return jsonify(prediction)


@app.route("/api/predictions")
def api_predictions():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM football_matches
            WHERE home_goals IS NULL
              AND away_goals IS NULL
            ORDER BY match_date
            """
        ).fetchall()

    predictions = []
    for row in rows:
        match = dict(row)
        if get_status_sort_key(match.get("status")) != 3:
            continue
        match["status_sort"] = 3
        match["league_color"] = LEAGUE_COLORS.get(match.get("league_id"), "#666")
        enrich_team_fields(match)
        prediction = build_match_prediction(match["fixture_id"], match)
        match["prediction"] = prediction["prediction"] if prediction else None
        predictions.append(match)

    predictions.sort(
        key=lambda match: (
            -(match.get("prediction") or {}).get("confidence", 0),
            match.get("match_date") or "",
        )
    )
    return jsonify({
        "predictions": predictions,
        "total": len(predictions),
        "is_mock": USE_MOCK,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/predictions")
def predictions():
    return render_template("predictions.html")


@app.route("/standings")
def standings():
    return render_template(
        "standings.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/standings")
def api_standings():
    league = request.args.get("league", "all")
    return jsonify({
        "standings": compute_standings(league),
        "is_mock": USE_MOCK,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/refresh")
def api_refresh():
    """手动刷新数据"""
    try:
        count = collect_from_api()
        msg = f"从 API 采集到 {count} 场比赛"
    except Exception as e:
        msg = f"采集失败: {e}"

    return jsonify({"message": msg, "is_mock": USE_MOCK})


@app.route("/api/seed")
def api_seed():
    """加载种子数据"""
    count = load_seed_data()
    return jsonify({"message": f"已加载 {count} 场模拟比赛", "count": count})


@app.route("/match/<int:fixture_id>")
def match_detail(fixture_id):
    return render_template("match.html", fixture_id=fixture_id)


if __name__ == "__main__":
    # 首次启动自动加载种子数据
    with get_db() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM football_matches").fetchone()[0]
        if cnt == 0:
            n = load_seed_data()
            print(f"[K38] 已加载 {n} 场种子数据")

    app.run(host="127.0.0.1", port=6789, debug=True)
