"""What the brief tracks. Edit these lists to re-target it for a client or sector."""

# key, label, Yahoo ticker, unit, kind ("price" -> % change, "yield" -> point change), group
MARKETS = [
    ("usdzar", "USD/ZAR (up = weaker rand)", "ZAR=X", "R per $", "price", "Rand"),
    ("eurzar", "EUR/ZAR", "EURZAR=X", "R per €", "price", "Rand"),
    ("gbpzar", "GBP/ZAR", "GBPZAR=X", "R per £", "price", "Rand"),
    ("top40", "JSE Top 40 (Satrix 40 ETF)", "STX40.JO", "ZAc", "price", "Equities"),
    ("sp500", "S&P 500", "^GSPC", "points", "price", "Equities"),
    ("em", "Emerging markets (MSCI EM ETF)", "EEM", "$", "price", "Equities"),
    ("gold", "Gold", "GC=F", "$/oz", "price", "Commodities"),
    ("platinum", "Platinum", "PL=F", "$/oz", "price", "Commodities"),
    ("brent", "Brent crude", "BZ=F", "$/bbl", "price", "Commodities"),
    ("copper", "Copper", "HG=F", "$/lb", "price", "Commodities"),
    ("us10y", "US 10-year Treasury yield", "^TNX", "%", "yield", "Global rates"),
]

# Fallback for the rand if Yahoo fails: European Central Bank reference rates.
ECB_FX = {"usdzar": "USD", "eurzar": "EUR", "gbpzar": "GBP"}

SARB_URL = "https://custom.resbank.co.za/SarbWebApi/WebIndicators/HomePageRates"
FRANKFURTER_URL = "https://api.frankfurter.app"

NEWS_FEEDS = [
    ("Google News", "https://news.google.com/rss/search?q=(%22South+Africa%22+economy)+OR+rand+OR+JSE+OR+SARB+OR+Eskom+OR+Treasury+when:2d&hl=en-ZA&gl=ZA&ceid=ZA:en"),
    ("Google News", "https://news.google.com/rss/search?q=%22South+Africa%22+(acquisition+OR+merger+OR+takeover+OR+results+OR+listing)+when:2d&hl=en-ZA&gl=ZA&ceid=ZA:en"),
    ("Moneyweb", "https://www.moneyweb.co.za/feed/"),
]

# Tags applied to headlines by keyword (whole words, case-insensitive).
NEWS_TAGS = {
    "Rates & inflation": ["sarb", "repo", "interest rate", "inflation", "cpi", "kganyago", "mpc", "prime"],
    "Rand & markets": ["rand", "jse", "bond", "bonds", "yield", "stocks", "shares", "market", "markets"],
    "Fiscal & policy": ["treasury", "budget", "godongwana", "tax", "debt", "gnu", "minister", "policy", "mtbps"],
    "Energy & logistics": ["eskom", "load shedding", "loadshedding", "electricity", "transnet", "port", "ports", "rail", "fuel", "petrol"],
    "Mining & commodities": ["gold", "platinum", "pgm", "coal", "iron ore", "mining", "anglo", "sibanye", "commodity", "commodities"],
    "Deals & companies": ["acquisition", "acquire", "merger", "takeover", "stake", "deal", "ipo", "listing", "results", "earnings", "profit"],
    "Trade & global": ["tariff", "tariffs", "agoa", "exports", "imports", "trade", "china", "fed", "federal reserve"],
}

MAX_HEADLINES = 25
