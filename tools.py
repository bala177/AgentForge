"""
tools.py — A powerful, real-world toolbox for the agent.

Every tool is a plain Python function. Tools use free APIs (no API keys)
and standard libraries to provide genuinely useful capabilities:

  • Real weather for ANY city (wttr.in)
  • Web search via DuckDuckGo
  • Wikipedia knowledge lookup
  • Web page fetching & text extraction
  • File operations (read / write / list)
  • System information
  • Text analysis (word count, readability, frequency)
  • Hashing & encoding (SHA-256, MD5, Base64, URL-encode)
  • Enhanced calculator with full math library
  • Timezone-aware date/time
  • Comprehensive unit converter
  • Persistent file-backed notes
  • Local Document OCR (image → text → searchable index)
"""

import math
import datetime
import json
import hashlib
import base64
import os
import platform
import socket
import urllib.parse
import re
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from log_config import get_logger

log = get_logger("tools")

# ── timeout for all HTTP requests (seconds) ──────────────────────────
HTTP_TIMEOUT = 10


def _safe_get(url, **kwargs):
    """requests.get with automatic SSL-verify fallback."""
    kwargs.setdefault("timeout", HTTP_TIMEOUT)
    kwargs.setdefault("headers", {"User-Agent": "AgentForge/1.0"})
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        log.warning("SSL error for %s — retrying without verification", url)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        kwargs["verify"] = False
        return requests.get(url, **kwargs)


# =====================================================================
# Tool 1: Calculator (enhanced)
# =====================================================================
def calculator(expression: str) -> str:
    """Evaluate a math expression. Supports sqrt, sin, cos, tan, log,
    factorial, pi, e, abs, round, min, max, pow, ceil, floor, etc."""
    log.debug("calculator called: %s", expression)
    try:
        allowed = {
            # Built-ins
            "abs": abs, "round": round, "min": min, "max": max, "pow": pow,
            "int": int, "float": float, "sum": sum,
            # Math constants
            "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
            # Math functions
            "sqrt": math.sqrt, "cbrt": lambda x: x ** (1 / 3),
            "ceil": math.ceil, "floor": math.floor,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "asin": math.asin, "acos": math.acos, "atan": math.atan,
            "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
            "log": math.log, "log2": math.log2, "log10": math.log10,
            "exp": math.exp, "factorial": math.factorial,
            "gcd": math.gcd, "degrees": math.degrees, "radians": math.radians,
            "hypot": math.hypot, "comb": math.comb, "perm": math.perm,
        }
        result = eval(expression, {"__builtins__": {}}, allowed)
        return f"Result: {result}"
    except Exception as exc:
        return f"Error evaluating '{expression}': {exc}"


# =====================================================================
# Tool 2: Date / Time (timezone-aware)
# =====================================================================
def get_datetime(query: str = "") -> str:
    """Return the current date & time.  Optionally accepts a UTC offset
    like '+5:30' or '-8' to show time in another timezone."""
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Try to parse an offset from the query
    offset_match = re.search(r'([+-]?\d{1,2})(?::(\d{2}))?', query)
    if offset_match:
        hours = int(offset_match.group(1))
        minutes = int(offset_match.group(2) or 0)
        tz = datetime.timezone(datetime.timedelta(hours=hours, minutes=minutes))
        now = now_utc.astimezone(tz)
        label = f"UTC{'+' if hours >= 0 else ''}{hours}:{minutes:02d}"
    else:
        now = datetime.datetime.now()
        label = "local time"

    return (
        f"Date:       {now.strftime('%Y-%m-%d')}\n"
        f"Time:       {now.strftime('%H:%M:%S')} ({label})\n"
        f"Day:        {now.strftime('%A')}\n"
        f"Week #:     {now.isocalendar()[1]}\n"
        f"Unix epoch: {int(now_utc.timestamp())}"
    )


# =====================================================================
# Tool 3: Real Weather (Open-Meteo primary + wttr.in fallback — no API key)
# =====================================================================

# WMO weather codes → human-readable descriptions
_WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _weather_open_meteo(city: str) -> str:
    """Fetch weather via Open-Meteo (geocoding + forecast). Free, no key."""
    # Step 1: Geocode the city name
    geo_url = "https://geocoding-api.open-meteo.com/v1/search"
    geo_resp = _safe_get(geo_url, params={"name": city, "count": 1,
                            "language": "en", "format": "json"})
    geo_resp.raise_for_status()
    geo_data = geo_resp.json()
    results = geo_data.get("results")
    if not results:
        return ""  # empty = not found, caller will try fallback
    loc = results[0]
    lat, lon = loc["latitude"], loc["longitude"]
    loc_name = loc.get("name", city)
    country = loc.get("country", "")

    # Step 2: Get current weather
    wx_url = "https://api.open-meteo.com/v1/forecast"
    wx_params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                    "weather_code,wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "kmh",
        "timezone": "auto",
    }
    wx_resp = _safe_get(wx_url, params=wx_params)
    wx_resp.raise_for_status()
    wx = wx_resp.json().get("current", {})

    temp_c = wx.get("temperature_2m", "?")
    temp_f = round(temp_c * 9 / 5 + 32, 1) if isinstance(temp_c, (int, float)) else "?"
    feels_c = wx.get("apparent_temperature", "?")
    feels_f = round(feels_c * 9 / 5 + 32, 1) if isinstance(feels_c, (int, float)) else "?"
    code = wx.get("weather_code", -1)
    desc = _WMO_DESCRIPTIONS.get(code, f"Code {code}")
    wind_deg = wx.get("wind_direction_10m", 0)
    # Convert degrees to compass
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    wind_dir = dirs[int((wind_deg + 11.25) / 22.5) % 16] if isinstance(wind_deg, (int, float)) else "?"

    return (
        f"Weather in {loc_name}, {country}:\n"
        f"  Description: {desc}\n"
        f"  Temperature: {temp_c}\u00b0C / {temp_f}\u00b0F\n"
        f"  Feels like:  {feels_c}\u00b0C / {feels_f}\u00b0F\n"
        f"  Humidity:    {wx.get('relative_humidity_2m', '?')}%\n"
        f"  Wind:        {wx.get('wind_speed_10m', '?')} km/h {wind_dir}"
    )


def _weather_wttr(city: str) -> str:
    """Fetch weather via wttr.in (fallback)."""
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    resp = _safe_get(url)
    resp.raise_for_status()
    data = resp.json()

    current = data["current_condition"][0]
    area = data.get("nearest_area", [{}])[0]
    area_name = area.get("areaName", [{}])[0].get("value", city)
    country = area.get("country", [{}])[0].get("value", "")

    return (
        f"Weather in {area_name}, {country}:\n"
        f"  Description: {current['weatherDesc'][0]['value']}\n"
        f"  Temperature: {current['temp_C']}\u00b0C / {current['temp_F']}\u00b0F\n"
        f"  Feels like:  {current['FeelsLikeC']}\u00b0C / {current['FeelsLikeF']}\u00b0F\n"
        f"  Humidity:    {current['humidity']}%\n"
        f"  Wind:        {current['windspeedKmph']} km/h {current['winddir16Point']}\n"
        f"  Visibility:  {current['visibility']} km\n"
        f"  UV Index:    {current['uvIndex']}"
    )


def weather_lookup(city: str) -> str:
    """Get real current weather for any city worldwide.
    Uses Open-Meteo (primary) with wttr.in fallback."""
    city = city.strip()
    if not city:
        return "Please provide a city name."
    log.info("weather_lookup: fetching weather for '%s'", city)

    # Try Open-Meteo first (reliable, fast, no key)
    try:
        result = _weather_open_meteo(city)
        if result:
            return result
        log.warning("Open-Meteo: no geocoding result for '%s', trying wttr.in", city)
    except Exception as exc:
        log.warning("Open-Meteo failed for '%s': %s — trying wttr.in", city, exc)

    # Fallback to wttr.in
    try:
        return _weather_wttr(city)
    except requests.RequestException as exc:
        return f"Could not fetch weather for '{city}': {exc}"
    except (KeyError, IndexError):
        return f"Could not parse weather data for '{city}'."


# =====================================================================
# Tool 4: Web Search (DuckDuckGo Lite — no API key)
# =====================================================================
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return top results."""
    query = query.strip()
    if not query:
        return "Please provide a search query."
    log.info("web_search: query='%s'", query)
    try:
        url = "https://lite.duckduckgo.com/lite/"
        try:
            resp = requests.post(url, data={"q": query}, timeout=HTTP_TIMEOUT,
                                 headers={"User-Agent": "AgentForge/1.0"})
        except requests.exceptions.SSLError:
            log.warning("web_search: SSL error, retrying without verify")
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.post(url, data={"q": query}, timeout=HTTP_TIMEOUT,
                                 verify=False,
                                 headers={"User-Agent": "AgentForge/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        # DuckDuckGo Lite returns results in a table
        for link in soup.select("a.result-link"):
            title = link.get_text(strip=True)
            href = link.get("href", "")
            if title and href:
                results.append(f"  {title}\n    {href}")
            if len(results) >= 8:
                break

        # Fallback: grab all external links
        if not results:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.get_text(strip=True)
                if href.startswith("http") and text and "duckduckgo" not in href.lower():
                    results.append(f"  {text}\n    {href}")
                if len(results) >= 8:
                    break

        if not results:
            return f"No results found for '{query}'."
        return f"Search results for '{query}':\n\n" + "\n\n".join(results)
    except requests.RequestException as exc:
        return f"Search failed: {exc}"


# =====================================================================
# Tool 5: Wikipedia Lookup (API — no key)
# =====================================================================
def wikipedia_lookup(topic: str) -> str:
    """Fetch the summary of a Wikipedia article on any topic."""
    topic = topic.strip()
    if not topic:
        return "Please provide a topic."
    log.info("wikipedia_lookup: topic='%s'", topic)
    try:
        url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(topic)
        resp = _safe_get(url)
        if resp.status_code == 404:
            # Try search
            search_url = "https://en.wikipedia.org/w/api.php"
            params = {"action": "opensearch", "search": topic, "limit": 5, "format": "json"}
            sr = _safe_get(search_url, params=params)
            sr.raise_for_status()
            data = sr.json()
            if len(data) > 1 and data[1]:
                suggestions = ", ".join(data[1][:5])
                return f"No exact article for '{topic}'. Did you mean: {suggestions}?"
            return f"No Wikipedia article found for '{topic}'."

        resp.raise_for_status()
        data = resp.json()
        title = data.get("title", topic)
        extract = data.get("extract", "No summary available.")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        # Trim to ~600 chars for readability
        if len(extract) > 600:
            extract = extract[:597] + "..."

        return f"Wikipedia — {title}\n\n{extract}\n\nRead more: {page_url}"
    except requests.RequestException as exc:
        return f"Wikipedia lookup failed: {exc}"


# =====================================================================
# Tool 6: URL Fetcher (fetch any web page and extract readable text)
# =====================================================================
def url_fetcher(url: str) -> str:
    """Fetch a web page and extract its readable text content."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    log.info("url_fetcher: fetching %s", url)
    try:
        resp = _safe_get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        if "json" in content_type:
            try:
                return f"JSON from {url}:\n{json.dumps(resp.json(), indent=2)[:3000]}"
            except Exception:
                pass

        if "text" in content_type or "html" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            # Remove script/style tags
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            # Collapse blank lines
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            text = "\n".join(lines[:100])  # First 100 lines
            if len(text) > 3000:
                text = text[:3000] + "\n...(truncated)"
            return f"Content from {url}:\n\n{text}"

        return f"Fetched {url} ({len(resp.content)} bytes, type: {content_type})"
    except requests.RequestException as exc:
        return f"Failed to fetch '{url}': {exc}"


# =====================================================================
# Tool 7: Unit Converter (comprehensive)
# =====================================================================
def unit_converter(query: str) -> str:
    """Convert between units. Format: '<value> <from> to <to>'.
    Supports length, weight, temperature, volume, area, speed, data,
    time, and more. Examples: '100 km to miles', '5 gallons to liters'."""

    conversions = {
        # Length
        ("mm", "cm"): lambda v: v / 10,
        ("cm", "mm"): lambda v: v * 10,
        ("cm", "m"): lambda v: v / 100,
        ("m", "cm"): lambda v: v * 100,
        ("m", "km"): lambda v: v / 1000,
        ("km", "m"): lambda v: v * 1000,
        ("m", "ft"): lambda v: v * 3.28084,
        ("ft", "m"): lambda v: v / 3.28084,
        ("ft", "in"): lambda v: v * 12,
        ("in", "ft"): lambda v: v / 12,
        ("in", "cm"): lambda v: v * 2.54,
        ("cm", "in"): lambda v: v / 2.54,
        ("km", "miles"): lambda v: v / 1.60934,
        ("miles", "km"): lambda v: v * 1.60934,
        ("m", "yards"): lambda v: v * 1.09361,
        ("yards", "m"): lambda v: v / 1.09361,
        ("nm", "km"): lambda v: v * 1.852,
        ("km", "nm"): lambda v: v / 1.852,
        # Weight / Mass
        ("g", "kg"): lambda v: v / 1000,
        ("kg", "g"): lambda v: v * 1000,
        ("kg", "lb"): lambda v: v * 2.20462,
        ("lb", "kg"): lambda v: v / 2.20462,
        ("lb", "oz"): lambda v: v * 16,
        ("oz", "lb"): lambda v: v / 16,
        ("oz", "g"): lambda v: v * 28.3495,
        ("g", "oz"): lambda v: v / 28.3495,
        ("kg", "stone"): lambda v: v / 6.35029,
        ("stone", "kg"): lambda v: v * 6.35029,
        ("ton", "kg"): lambda v: v * 907.185,
        ("kg", "ton"): lambda v: v / 907.185,
        ("tonne", "kg"): lambda v: v * 1000,
        ("kg", "tonne"): lambda v: v / 1000,
        # Temperature
        ("f", "c"): lambda v: (v - 32) * 5 / 9,
        ("c", "f"): lambda v: v * 9 / 5 + 32,
        ("c", "k"): lambda v: v + 273.15,
        ("k", "c"): lambda v: v - 273.15,
        ("f", "k"): lambda v: (v - 32) * 5 / 9 + 273.15,
        ("k", "f"): lambda v: (v - 273.15) * 9 / 5 + 32,
        # Volume
        ("liters", "gallons"): lambda v: v / 3.78541,
        ("gallons", "liters"): lambda v: v * 3.78541,
        ("ml", "liters"): lambda v: v / 1000,
        ("liters", "ml"): lambda v: v * 1000,
        ("ml", "oz"): lambda v: v / 29.5735,
        ("oz", "ml"): lambda v: v * 29.5735,
        ("cups", "ml"): lambda v: v * 236.588,
        ("ml", "cups"): lambda v: v / 236.588,
        ("liters", "cups"): lambda v: v * 4.22675,
        ("cups", "liters"): lambda v: v / 4.22675,
        # Area
        ("sqm", "sqft"): lambda v: v * 10.7639,
        ("sqft", "sqm"): lambda v: v / 10.7639,
        ("acres", "sqm"): lambda v: v * 4046.86,
        ("sqm", "acres"): lambda v: v / 4046.86,
        ("hectares", "acres"): lambda v: v * 2.47105,
        ("acres", "hectares"): lambda v: v / 2.47105,
        # Speed
        ("mph", "kph"): lambda v: v * 1.60934,
        ("kph", "mph"): lambda v: v / 1.60934,
        ("knots", "kph"): lambda v: v * 1.852,
        ("kph", "knots"): lambda v: v / 1.852,
        ("mps", "kph"): lambda v: v * 3.6,
        ("kph", "mps"): lambda v: v / 3.6,
        # Data
        ("kb", "mb"): lambda v: v / 1024,
        ("mb", "kb"): lambda v: v * 1024,
        ("mb", "gb"): lambda v: v / 1024,
        ("gb", "mb"): lambda v: v * 1024,
        ("gb", "tb"): lambda v: v / 1024,
        ("tb", "gb"): lambda v: v * 1024,
        ("bytes", "kb"): lambda v: v / 1024,
        ("kb", "bytes"): lambda v: v * 1024,
        # Time
        ("seconds", "minutes"): lambda v: v / 60,
        ("minutes", "seconds"): lambda v: v * 60,
        ("minutes", "hours"): lambda v: v / 60,
        ("hours", "minutes"): lambda v: v * 60,
        ("hours", "days"): lambda v: v / 24,
        ("days", "hours"): lambda v: v * 24,
        ("days", "weeks"): lambda v: v / 7,
        ("weeks", "days"): lambda v: v * 7,
        ("days", "years"): lambda v: v / 365.25,
        ("years", "days"): lambda v: v * 365.25,
    }

    aliases = {
        "fahrenheit": "f", "celsius": "c", "kelvin": "k",
        "mile": "miles", "meter": "m", "meters": "m",
        "kilometer": "km", "kilometers": "km",
        "kilogram": "kg", "kilograms": "kg",
        "pound": "lb", "pounds": "lb",
        "ounce": "oz", "ounces": "oz",
        "inch": "in", "inches": "in",
        "foot": "ft", "feet": "ft",
        "yard": "yards",
        "liter": "liters", "litre": "liters", "litres": "liters",
        "gallon": "gallons",
        "milliliter": "ml", "milliliters": "ml", "millilitres": "ml",
        "cup": "cups",
        "acre": "acres", "hectare": "hectares",
        "knot": "knots",
        "second": "seconds", "sec": "seconds", "secs": "seconds",
        "minute": "minutes", "min": "minutes", "mins": "minutes",
        "hour": "hours", "hr": "hours", "hrs": "hours",
        "day": "days", "week": "weeks", "year": "years",
        "byte": "bytes",
        "tonne": "tonne", "tonnes": "tonne",
        "tons": "ton",
    }

    try:
        clean = query.lower().strip()
        for word in ["convert", "conversion", "please", "what is", "how many"]:
            clean = clean.replace(word, "")
        parts = re.split(r'\bto\b', clean, maxsplit=1)
        if len(parts) != 2:
            return "Use format: '<value> <from_unit> to <to_unit>'  e.g. '100 km to miles'"
        left = parts[0].strip().split()
        value = float(left[0])
        from_u = " ".join(left[1:]).strip()
        to_u = parts[1].strip()
        from_u = aliases.get(from_u, from_u)
        to_u = aliases.get(to_u, to_u)

        key = (from_u, to_u)
        if key in conversions:
            result = conversions[key](value)
            return f"{value} {from_u} = {round(result, 6)} {to_u}"
        return (
            f"Unknown conversion: {from_u} -> {to_u}. Supported categories: "
            "length, weight, temperature, volume, area, speed, data, time."
        )
    except Exception as exc:
        return f"Could not parse. Use format: '100 km to miles'. Error: {exc}"


# =====================================================================
# Tool 8: File Manager (read / write / list)
# =====================================================================
def file_manager(command: str) -> str:
    """Manage files. Commands:
       read <path>           — Read a file's contents
       write <path> <text>   — Write text to a file (creates/overwrites)
       append <path> <text>  — Append text to a file
       list [path]           — List directory contents (default: current dir)
       info <path>           — Show file size, modified date, etc.
    """
    parts = command.strip().split(" ", 2)
    action = parts[0].lower() if parts else ""

    try:
        if action == "read" and len(parts) >= 2:
            path = Path(parts[1])
            if not path.exists():
                return f"File not found: {path}"
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 5000:
                text = text[:5000] + f"\n...(truncated, total {len(text)} chars)"
            return f"Contents of {path}:\n{text}"

        elif action == "write" and len(parts) >= 3:
            path = Path(parts[1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(parts[2], encoding="utf-8")
            return f"Written {len(parts[2])} chars to {path}"

        elif action == "append" and len(parts) >= 3:
            path = Path(parts[1])
            with open(path, "a", encoding="utf-8") as f:
                f.write(parts[2] + "\n")
            return f"Appended to {path}"

        elif action == "list":
            target = Path(parts[1]) if len(parts) >= 2 else Path(".")
            if not target.exists():
                return f"Path not found: {target}"
            entries = sorted(target.iterdir())
            lines = []
            for e in entries[:50]:
                kind = "DIR " if e.is_dir() else "FILE"
                size = e.stat().st_size if e.is_file() else ""
                lines.append(f"  {kind}  {e.name}" + (f"  ({size} bytes)" if size else ""))
            if len(entries) > 50:
                lines.append(f"  ... and {len(entries) - 50} more")
            return f"Contents of {target.resolve()}:\n" + "\n".join(lines)

        elif action == "info" and len(parts) >= 2:
            path = Path(parts[1])
            if not path.exists():
                return f"Path not found: {path}"
            stat = path.stat()
            mod_time = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            return (
                f"Path:     {path.resolve()}\n"
                f"Type:     {'directory' if path.is_dir() else 'file'}\n"
                f"Size:     {stat.st_size:,} bytes\n"
                f"Modified: {mod_time}"
            )

        return ("Usage: read <path> | write <path> <text> | append <path> <text> "
                "| list [path] | info <path>")
    except Exception as exc:
        return f"File operation error: {exc}"


# =====================================================================
# Tool 9: System Info
# =====================================================================
def system_info(query: str = "") -> str:
    """Return information about the current system (OS, CPU, Python, etc.)."""
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown"

    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"

    return (
        f"System:     {platform.system()} {platform.release()}\n"
        f"Version:    {platform.version()}\n"
        f"Machine:    {platform.machine()}\n"
        f"Processor:  {platform.processor()}\n"
        f"Hostname:   {hostname}\n"
        f"Local IP:   {local_ip}\n"
        f"Python:     {platform.python_version()}\n"
        f"CWD:        {os.getcwd()}"
    )


# =====================================================================
# Tool 10: Text Analyzer
# =====================================================================
def text_analyzer(text: str) -> str:
    """Analyze text: character count, word count, sentence count,
    average word length, most common words, and reading time."""
    if not text.strip():
        return "Please provide some text to analyze."

    words = re.findall(r'\b\w+\b', text.lower())
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if s.strip()]
    char_count = len(text)
    word_count = len(words)
    sentence_count = len(sentences)
    avg_word_len = sum(len(w) for w in words) / max(word_count, 1)

    # Reading time (avg 200 words/min)
    read_minutes = word_count / 200
    read_time = f"{read_minutes:.1f} min" if read_minutes >= 1 else f"{read_minutes * 60:.0f} sec"

    # Top 10 most common words (excluding short ones)
    meaningful = [w for w in words if len(w) > 2]
    top_words = Counter(meaningful).most_common(10)
    top_str = ", ".join(f"'{w}' ({c})" for w, c in top_words)

    # Unique word ratio
    unique_ratio = len(set(words)) / max(word_count, 1) * 100

    return (
        f"Characters:      {char_count:,}\n"
        f"Words:           {word_count:,}\n"
        f"Sentences:       {sentence_count:,}\n"
        f"Avg word length: {avg_word_len:.1f} chars\n"
        f"Unique words:    {unique_ratio:.1f}%\n"
        f"Reading time:    ~{read_time}\n"
        f"Top words:       {top_str}"
    )


# =====================================================================
# Tool 11: Hash & Encode
# =====================================================================
def hash_encode(command: str) -> str:
    """Hash or encode/decode text. Commands:
       md5 <text>            — MD5 hash
       sha256 <text>         — SHA-256 hash
       sha1 <text>           — SHA-1 hash
       base64encode <text>   — Base64 encode
       base64decode <text>   — Base64 decode
       urlencode <text>      — URL-encode
       urldecode <text>      — URL-decode
       count <text>          — Character/byte count
    """
    parts = command.strip().split(" ", 1)
    action = parts[0].lower()
    data = parts[1] if len(parts) > 1 else ""

    try:
        if action == "md5":
            return f"MD5: {hashlib.md5(data.encode()).hexdigest()}"
        elif action == "sha256":
            return f"SHA-256: {hashlib.sha256(data.encode()).hexdigest()}"
        elif action == "sha1":
            return f"SHA-1: {hashlib.sha1(data.encode()).hexdigest()}"
        elif action == "base64encode":
            encoded = base64.b64encode(data.encode()).decode()
            return f"Base64: {encoded}"
        elif action == "base64decode":
            decoded = base64.b64decode(data.encode()).decode()
            return f"Decoded: {decoded}"
        elif action == "urlencode":
            return f"URL-encoded: {urllib.parse.quote(data, safe='')}"
        elif action == "urldecode":
            return f"URL-decoded: {urllib.parse.unquote(data)}"
        elif action == "count":
            return f"Characters: {len(data)}, Bytes (UTF-8): {len(data.encode())}"
        else:
            return ("Commands: md5, sha256, sha1, base64encode, base64decode, "
                    "urlencode, urldecode, count")
    except Exception as exc:
        return f"Error: {exc}"


# =====================================================================
# Tool 12: IP & Network Lookup
# =====================================================================
def ip_lookup(query: str = "") -> str:
    """Look up public IP, or get info about any IP/domain.
       Examples: '' (your public IP), '8.8.8.8', 'google.com'
    """
    query = query.strip()
    log.info("ip_lookup: query='%s'", query or "(own IP)")
    try:
        if not query:
            resp = _safe_get("https://ipinfo.io/json")
            resp.raise_for_status()
            data = resp.json()
            return (
                f"Your public IP: {data.get('ip')}\n"
                f"Location:       {data.get('city')}, {data.get('region')}, {data.get('country')}\n"
                f"ISP:            {data.get('org', 'N/A')}\n"
                f"Timezone:       {data.get('timezone', 'N/A')}"
            )
        else:
            target = query
            try:
                ip = socket.gethostbyname(target)
            except socket.gaierror:
                ip = target

            resp = _safe_get(f"https://ipinfo.io/{ip}/json")
            resp.raise_for_status()
            data = resp.json()
            return (
                f"IP:       {data.get('ip')}\n"
                f"Hostname: {data.get('hostname', 'N/A')}\n"
                f"Location: {data.get('city', '?')}, {data.get('region', '?')}, {data.get('country', '?')}\n"
                f"ISP:      {data.get('org', 'N/A')}\n"
                f"Timezone: {data.get('timezone', 'N/A')}"
            )
    except requests.RequestException as exc:
        return f"IP lookup failed: {exc}"


# =====================================================================
# Tool 13: Persistent Notes (v2 — backed by activity_store)
# =====================================================================
import activity_store as _store


def note_taker(action_and_text: str) -> str:
    """Persistent notes saved to disk. Commands:
       save <text>              — Save a new note
       save <text> #tag1 #tag2  — Save with tags
       list                     — Show all notes
       search <keyword>         — Search notes
       delete <id-or-number>    — Delete note by ID or number
       edit <id-or-number> <text> — Edit note text
       pin <id-or-number>       — Pin/unpin a note
       clear                    — Delete all notes
       categories               — List all categories
    """
    parts = action_and_text.strip().split(" ", 1)
    action = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if action == "save" and arg:
        # Extract tags from #hashtags
        import re as _re
        tags = _re.findall(r'#(\w+)', arg)
        text = _re.sub(r'\s*#\w+', '', arg).strip()
        if not text:
            text = arg
            tags = []
        note = _store.save_note(text=text, tags=tags, source="chat")
        total = len(_store.list_notes())
        return f"Note saved! (ID: {note['id']}, {total} total)"

    elif action == "list":
        notes = _store.list_notes()
        if not notes:
            return "No notes saved yet."
        lines = []
        for i, n in enumerate(notes, 1):
            pin = "\U0001f4cc " if n.get("pinned") else ""
            tags = " ".join(f"#{t}" for t in n.get("tags", []))
            tags_str = f"  {tags}" if tags else ""
            lines.append(f"  {i}. {pin}[{n.get('created', '?')}] {n['text']}{tags_str}")
        return f"Your notes ({len(notes)} total):\n" + "\n".join(lines)

    elif action == "search" and arg:
        notes = _store.list_notes(search=arg)
        if not notes:
            return f"No notes matching '{arg}'."
        lines = [f"  {i}. [{n.get('created', '?')}] {n['text']}"
                 for i, n in enumerate(notes, 1)]
        return f"Notes matching '{arg}':\n" + "\n".join(lines)

    elif action == "delete" and arg:
        note = _resolve_note(arg)
        if note:
            _store.delete_note(note["id"])
            return f"Deleted note: {note['text']}"
        return f"Note '{arg}' not found."

    elif action == "edit" and arg:
        edit_parts = arg.split(" ", 1)
        if len(edit_parts) < 2:
            return "Usage: edit <id-or-number> <new text>"
        note = _resolve_note(edit_parts[0])
        if note:
            _store.update_note(note["id"], text=edit_parts[1])
            return f"Note updated: {edit_parts[1]}"
        return f"Note '{edit_parts[0]}' not found."

    elif action == "pin" and arg:
        note = _resolve_note(arg)
        if note:
            new_state = not note.get("pinned", False)
            _store.pin_note(note["id"], new_state)
            return f"Note {'pinned' if new_state else 'unpinned'}: {note['text']}"
        return f"Note '{arg}' not found."

    elif action == "categories":
        cats = _store.get_note_categories()
        if not cats:
            return "No categories yet."
        return "Categories: " + ", ".join(cats)

    elif action == "clear":
        count = _store.clear_notes()
        return f"Cleared all {count} notes."

    return "Usage: save <text> | list | search <keyword> | delete <id> | edit <id> <text> | pin <id> | clear | categories"


def _resolve_note(ref: str):
    """Resolve a note by ID string or 1-based number."""
    # Try direct ID match
    note = _store.get_note(ref)
    if note:
        return note
    # Try as a number (1-based index)
    try:
        idx = int(ref)
        notes = _store.list_notes()
        if 1 <= idx <= len(notes):
            return notes[idx - 1]
    except ValueError:
        pass
    return None


# =====================================================================
# Tool 14: Local Document OCR  (pytesseract + Pillow)
# =====================================================================

# ── OCR index file (JSON-backed on disk) ────────────────────────────
_OCR_INDEX_FILE = Path(__file__).parent / "ocr_index.json"
_OCR_UPLOADS_DIR = Path(__file__).parent / "ocr_uploads"


def _load_ocr_index() -> list[dict]:
    """Load the OCR document index from disk."""
    if _OCR_INDEX_FILE.exists():
        try:
            return json.loads(_OCR_INDEX_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            log.warning("Corrupt OCR index — starting fresh")
    return []


def _save_ocr_index(index: list[dict]):
    """Persist the OCR document index to disk."""
    _OCR_INDEX_FILE.write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _ensure_upload_dir():
    """Create the OCR uploads directory if it doesn't exist."""
    _OCR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _check_tesseract() -> tuple[bool, str]:
    """Check if Tesseract OCR engine is available."""
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return True, f"Tesseract {version}"
    except Exception:
        # Try common install paths on Windows
        import shutil
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                try:
                    import pytesseract
                    pytesseract.pytesseract.tesseract_cmd = p
                    version = pytesseract.get_tesseract_version()
                    return True, f"Tesseract {version} (found at {p})"
                except Exception:
                    continue
        # Check if tesseract is on PATH
        tess_path = shutil.which("tesseract")
        if tess_path:
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = tess_path
                version = pytesseract.get_tesseract_version()
                return True, f"Tesseract {version} (PATH: {tess_path})"
            except Exception:
                pass
        return False, (
            "Tesseract OCR not found. Install it:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  macOS:   brew install tesseract\n"
            "  Linux:   sudo apt install tesseract-ocr"
        )


def _preprocess_image(img):
    """Apply preprocessing to improve OCR accuracy."""
    from PIL import ImageFilter, ImageEnhance, ImageOps

    # Convert to RGB if needed (handles RGBA, P mode, etc.)
    if img.mode not in ("L", "RGB"):
        img = img.convert("RGB")

    # Resize very large images to speed up OCR (max 2500px on longest side)
    max_dim = 2500
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS if hasattr(Image, 'LANCZOS') else Image.ANTIALIAS)
        log.info("Resized image from %dx%d to %dx%d for OCR", w, h, new_w, new_h)

    # Convert to grayscale
    gray = ImageOps.grayscale(img)

    # Increase contrast
    enhancer = ImageEnhance.Contrast(gray)
    gray = enhancer.enhance(2.0)

    # Sharpen
    gray = gray.filter(ImageFilter.SHARPEN)

    # Binarize (adaptive threshold via simple method)
    threshold = 128
    gray = gray.point(lambda x: 255 if x > threshold else 0, "1")

    return gray


def _ocr_image(filepath: str, preprocess: bool = True) -> dict:
    """Run OCR on a single image file. Returns structured result dict."""
    from PIL import Image
    import pytesseract

    # Validate file exists
    fpath = Path(filepath).resolve()
    if not fpath.exists():
        raise FileNotFoundError(f"Image not found: {fpath}")

    supported = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp", ".ppm", ".pgm", ".pbm"}
    if fpath.suffix.lower() not in supported:
        raise ValueError(f"Unsupported format '{fpath.suffix}'. Supported: {', '.join(sorted(supported))}")

    img = Image.open(fpath)
    width, height = img.size

    # Preprocess for better accuracy (also resizes large images)
    processed = _preprocess_image(img) if preprocess else img

    # Run OCR — single call for speed
    text = pytesseract.image_to_string(processed).strip()

    # Word count and basic confidence estimate
    words = text.split() if text else []

    # Get confidence data only for reasonably-sized images
    avg_confidence = 0.0
    if words:
        try:
            ocr_data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in ocr_data["conf"] if int(c) > 0]
            avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        except Exception:
            avg_confidence = -1  # confidence unavailable

    return {
        "file": str(fpath),
        "filename": fpath.name,
        "text": text,
        "word_count": len(words),
        "avg_confidence": avg_confidence,
        "image_size": f"{width}x{height}",
        "format": fpath.suffix.lower(),
    }


def document_ocr(command: str) -> str:
    """Local Document OCR: scan images → extract text → searchable index.

    Commands:
      scan <filepath>          — OCR an image file and add to index
      scan_url <url>           — Download image from URL and OCR it
      search <keyword>         — Search extracted text across all documents
      list                     — List all scanned documents
      info <id-or-number>      — Show full text of a scanned document
      delete <id-or-number>    — Remove a document from the index
      clear                    — Clear the entire OCR index
      status                   — Check Tesseract availability & index stats
    """
    log.debug("document_ocr called: %s", command)
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    # ── status: check Tesseract & show index stats ──
    if action == "status":
        available, msg = _check_tesseract()
        index = _load_ocr_index()
        total_words = sum(d.get("word_count", 0) for d in index)
        return (
            f"Tesseract: {'✅ ' + msg if available else '❌ ' + msg}\n"
            f"Documents indexed: {len(index)}\n"
            f"Total words extracted: {total_words}\n"
            f"Index file: {_OCR_INDEX_FILE}\n"
            f"Uploads dir: {_OCR_UPLOADS_DIR}"
        )

    # ── scan: OCR an image file ──
    if action == "scan" and arg:
        available, msg = _check_tesseract()
        if not available:
            return f"❌ Cannot scan — {msg}"
        try:
            result = _ocr_image(arg)
            # Add to index
            index = _load_ocr_index()
            doc_id = f"ocr_{int(datetime.datetime.now().timestamp())}_{hashlib.md5(arg.encode()).hexdigest()[:6]}"
            doc = {
                "id": doc_id,
                "filename": result["filename"],
                "filepath": result["file"],
                "text": result["text"],
                "word_count": result["word_count"],
                "confidence": result["avg_confidence"],
                "image_size": result["image_size"],
                "format": result["format"],
                "scanned_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            index.append(doc)
            _save_ocr_index(index)
            # Build response
            preview = result["text"][:500]
            if len(result["text"]) > 500:
                preview += "..."
            return (
                f"✅ Document scanned successfully!\n"
                f"─────────────────────────────────\n"
                f"ID:         {doc_id}\n"
                f"File:       {result['filename']}\n"
                f"Size:       {result['image_size']}\n"
                f"Words:      {result['word_count']}\n"
                f"Confidence: {result['avg_confidence']}%\n"
                f"─────────────────────────────────\n"
                f"Extracted text:\n{preview}"
            )
        except FileNotFoundError as e:
            return f"❌ {e}"
        except ValueError as e:
            return f"❌ {e}"
        except Exception as e:
            log.exception("OCR scan failed")
            return f"❌ OCR failed: {e}"

    # ── scan_url: download image from URL then OCR ──
    if action == "scan_url" and arg:
        available, msg = _check_tesseract()
        if not available:
            return f"❌ Cannot scan — {msg}"
        try:
            _ensure_upload_dir()
            # Download the image
            resp = _safe_get(arg)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and not arg.lower().endswith(
                (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp")
            ):
                return f"❌ URL does not appear to be an image (Content-Type: {content_type})"
            # Determine extension
            ext = ".png"
            for e in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"]:
                if arg.lower().endswith(e) or e.replace(".", "/") in content_type:
                    ext = e
                    break
            fname = f"url_{int(datetime.datetime.now().timestamp())}{ext}"
            fpath = _OCR_UPLOADS_DIR / fname
            fpath.write_bytes(resp.content)
            log.info("Downloaded image to %s (%d bytes)", fpath, len(resp.content))
            # Now OCR the downloaded file
            return document_ocr(f"scan {fpath}")
        except requests.RequestException as e:
            return f"❌ Download failed: {e}"
        except Exception as e:
            log.exception("OCR scan_url failed")
            return f"❌ Error: {e}"

    # ── search: full-text search across all scanned documents ──
    if action == "search" and arg:
        index = _load_ocr_index()
        if not index:
            return "No documents in the OCR index yet. Use 'scan <filepath>' to add one."
        keyword = arg.lower()
        matches = []
        for doc in index:
            text_lower = doc.get("text", "").lower()
            if keyword in text_lower:
                # Count occurrences
                count = text_lower.count(keyword)
                # Extract context snippets (up to 3)
                snippets = []
                search_start = 0
                for _ in range(3):
                    pos = text_lower.find(keyword, search_start)
                    if pos == -1:
                        break
                    start = max(0, pos - 40)
                    end = min(len(text_lower), pos + len(keyword) + 40)
                    snippet = doc["text"][start:end].replace("\n", " ")
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(text_lower):
                        snippet += "..."
                    snippets.append(snippet)
                    search_start = pos + len(keyword)
                matches.append({
                    "doc": doc,
                    "count": count,
                    "snippets": snippets,
                })
        if not matches:
            return f"No documents contain '{arg}'."
        lines = [f"Found '{arg}' in {len(matches)} document(s):\n"]
        for i, m in enumerate(matches, 1):
            d = m["doc"]
            lines.append(f"  {i}. {d['filename']} ({m['count']} occurrence{'s' if m['count'] > 1 else ''})")
            lines.append(f"     Scanned: {d.get('scanned_at', '?')}  |  Words: {d['word_count']}")
            for s in m["snippets"]:
                lines.append(f"     → \"{s}\"")
        return "\n".join(lines)

    # ── list: show all scanned documents ──
    if action == "list":
        index = _load_ocr_index()
        if not index:
            return "No documents in the OCR index yet."
        lines = [f"OCR Document Index ({len(index)} documents):\n"]
        for i, doc in enumerate(index, 1):
            preview = doc.get("text", "")[:60].replace("\n", " ")
            if len(doc.get("text", "")) > 60:
                preview += "..."
            lines.append(
                f"  {i}. [{doc.get('scanned_at', '?')}] {doc['filename']}\n"
                f"     Words: {doc['word_count']}  |  Confidence: {doc.get('confidence', '?')}%  |  Size: {doc.get('image_size', '?')}\n"
                f"     Preview: {preview}"
            )
        return "\n".join(lines)

    # ── info: full text of a specific document ──
    if action == "info" and arg:
        doc = _resolve_ocr_doc(arg)
        if not doc:
            return f"Document '{arg}' not found. Use 'list' to see all documents."
        return (
            f"Document: {doc['filename']}\n"
            f"ID: {doc['id']}\n"
            f"Path: {doc.get('filepath', '?')}\n"
            f"Image size: {doc.get('image_size', '?')}\n"
            f"Words: {doc['word_count']}  |  Confidence: {doc.get('confidence', '?')}%\n"
            f"Scanned: {doc.get('scanned_at', '?')}\n"
            f"─────────────────────────────────\n"
            f"{doc.get('text', '(no text extracted)')}"
        )

    # ── delete: remove a document from the index ──
    if action == "delete" and arg:
        doc = _resolve_ocr_doc(arg)
        if not doc:
            return f"Document '{arg}' not found."
        index = _load_ocr_index()
        index = [d for d in index if d["id"] != doc["id"]]
        _save_ocr_index(index)
        return f"Deleted: {doc['filename']} (ID: {doc['id']})"

    # ── clear: wipe the entire index ──
    if action == "clear":
        index = _load_ocr_index()
        count = len(index)
        _save_ocr_index([])
        return f"Cleared {count} document(s) from the OCR index."

    return (
        "Document OCR commands:\n"
        "  scan <filepath>    — OCR an image and add to searchable index\n"
        "  scan_url <url>     — Download image from URL and OCR it\n"
        "  search <keyword>   — Search text across all scanned documents\n"
        "  list               — List all scanned documents\n"
        "  info <id|number>   — Show full extracted text\n"
        "  delete <id|number> — Remove from index\n"
        "  clear              — Clear the entire index\n"
        "  status             — Check Tesseract & index stats"
    )


def _resolve_ocr_doc(ref: str):
    """Resolve an OCR document by ID or 1-based index number."""
    index = _load_ocr_index()
    # Try direct ID match
    for doc in index:
        if doc["id"] == ref:
            return doc
    # Try as a number (1-based)
    try:
        idx = int(ref)
        if 1 <= idx <= len(index):
            return index[idx - 1]
    except ValueError:
        pass
    # Try partial filename match
    ref_lower = ref.lower()
    for doc in index:
        if ref_lower in doc.get("filename", "").lower():
            return doc
    return None


# =====================================================================
# TOOL REGISTRY — Everything the agent can see and use
# =====================================================================
TOOL_REGISTRY = {
    "calculator": {
        "function": calculator,
        "description": (
            "Evaluate math expressions. Supports: +, -, *, /, **, sqrt, sin, cos, "
            "tan, log, log10, factorial, ceil, floor, pi, e, abs, round, min, max, "
            "gcd, degrees, radians, comb, perm"
        ),
    },
    "get_datetime": {
        "function": get_datetime,
        "description": (
            "Get current date, time, day, week number, and unix timestamp. "
            "Optionally pass a UTC offset like '+5:30' or '-8' for other timezones"
        ),
    },
    "weather_lookup": {
        "function": weather_lookup,
        "description": (
            "Get REAL current weather for ANY city worldwide — temperature, "
            "humidity, wind, UV index, feels-like, visibility (via wttr.in)"
        ),
    },
    "web_search": {
        "function": web_search,
        "description": (
            "Search the web via DuckDuckGo. Returns top results with titles and URLs. "
            "Use for current events, facts, how-to questions, etc."
        ),
    },
    "wikipedia_lookup": {
        "function": wikipedia_lookup,
        "description": (
            "Look up any topic on Wikipedia and get a summary. Great for people, "
            "places, science, history, concepts, etc."
        ),
    },
    "url_fetcher": {
        "function": url_fetcher,
        "description": (
            "Fetch any web page or API endpoint and extract readable text. "
            "Handles HTML, JSON, and plain text"
        ),
    },
    "unit_converter": {
        "function": unit_converter,
        "description": (
            "Convert between units: length (km/miles/m/ft/in), weight (kg/lb/oz), "
            "temperature (C/F/K), volume (liters/gallons/cups/ml), area, speed, "
            "data (KB/MB/GB/TB), time (seconds to years). Format: '100 km to miles'"
        ),
    },
    "file_manager": {
        "function": file_manager,
        "description": (
            "Read, write, append, list, or get info about files and directories. "
            "Commands: read/write/append/list/info"
        ),
    },
    "system_info": {
        "function": system_info,
        "description": (
            "Get current system info: OS, architecture, processor, hostname, "
            "local IP, Python version, current working directory"
        ),
    },
    "text_analyzer": {
        "function": text_analyzer,
        "description": (
            "Analyze text: word count, character count, sentence count, "
            "average word length, top words, unique word ratio, reading time"
        ),
    },
    "hash_encode": {
        "function": hash_encode,
        "description": (
            "Hash or encode/decode text: md5, sha256, sha1, base64encode, "
            "base64decode, urlencode, urldecode, character/byte count"
        ),
    },
    "ip_lookup": {
        "function": ip_lookup,
        "description": (
            "Look up your public IP, or get geolocation + ISP info for any IP "
            "address or domain name"
        ),
    },
    "note_taker": {
        "function": note_taker,
        "description": (
            "Persistent notes saved to disk. Commands: save <text>, list, "
            "search <keyword>, delete <number>, clear"
        ),
    },
    "document_ocr": {
        "function": document_ocr,
        "description": (
            "Local Document OCR: scan images to extract structured text and build "
            "a searchable index. Commands: scan <filepath>, scan_url <url>, "
            "search <keyword>, list, info <id>, delete <id>, clear, status"
        ),
    },
}
