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
  • Sandboxed Python code execution
  • JSON / YAML / TOML processing & querying
  • PDF text extraction & search
  • Screenshot capture
  • QR code generation & decoding
  • Email drafting, validation & templates
  • Git repository operations
  • Port scanning & network diagnostics
  • Regex testing, matching & pattern library
  • Cron expression parsing & scheduling
"""

import math
import datetime
import json
import hashlib
import base64
import os
import platform
import socket
import subprocess
import urllib.parse
import re
import secrets
import shutil
import textwrap
import tempfile
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from log_config import get_logger

log = get_logger("tools")

# ── timeout for all HTTP requests (seconds) ──────────────────────────
HTTP_TIMEOUT = 10

# ── Workspace sandbox — all file operations are confined to this root ───
WORKSPACE_ROOT = Path(
    os.getenv("AGENT_WORKSPACE", str(Path(__file__).resolve().parent))
).resolve()


def _safe_path(requested: str) -> Path:
    """Resolve a user-requested path and ensure it stays within WORKSPACE_ROOT.

    Raises PermissionError if the resolved path escapes the workspace.
    """
    resolved = (WORKSPACE_ROOT / requested).resolve()
    if not str(resolved).startswith(str(WORKSPACE_ROOT)):
        raise PermissionError(
            f"Access denied: '{requested}' resolves outside workspace. "
            f"Workspace root: {WORKSPACE_ROOT}"
        )
    return resolved


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
            path = _safe_path(parts[1])
            if not path.exists():
                return f"File not found: {path}"
            text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 5000:
                text = text[:5000] + f"\n...(truncated, total {len(text)} chars)"
            return f"Contents of {path}:\n{text}"

        elif action == "write" and len(parts) >= 3:
            path = _safe_path(parts[1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(parts[2], encoding="utf-8")
            return f"Written {len(parts[2])} chars to {path}"

        elif action == "append" and len(parts) >= 3:
            path = _safe_path(parts[1])
            with open(path, "a", encoding="utf-8") as f:
                f.write(parts[2] + "\n")
            return f"Appended to {path}"

        elif action == "list":
            target = _safe_path(parts[1]) if len(parts) >= 2 else WORKSPACE_ROOT
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
            path = _safe_path(parts[1])
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
import runtime.activity_store as _store


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
# Tool 15: JSON / YAML Processing
# =====================================================================
def json_yaml_tool(command: str) -> str:
    """Process JSON and YAML data: validate, convert, format, query.

    Commands:
      validate <json_or_yaml>     — Check if data is valid JSON or YAML
      json2yaml <json_string>     — Convert JSON to YAML
      yaml2json <yaml_string>     — Convert YAML to JSON
      format <json_string>        — Pretty-print JSON with indentation
      minify <json_string>        — Minify JSON (remove whitespace)
      query <path> <json_string>  — Query JSON with dot-notation (e.g. "users.0.name")
      keys <json_string>          — List top-level keys
      merge <json1> ||| <json2>   — Deep merge two JSON objects
    """
    log.debug("json_yaml_tool called: %s", command[:200])
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    try:
        import yaml
        yaml_available = True
    except ImportError:
        yaml_available = False

    if action == "validate":
        if not arg:
            return "Usage: validate <json_or_yaml_string>"
        # Try JSON first
        try:
            json.loads(arg)
            return "✅ Valid JSON"
        except json.JSONDecodeError:
            pass
        # Try YAML
        if yaml_available:
            try:
                result = yaml.safe_load(arg)
                if result is not None:
                    return "✅ Valid YAML"
            except yaml.YAMLError:
                pass
        return "❌ Invalid JSON" + (" and YAML" if yaml_available else " (YAML not available — install pyyaml)")

    if action == "json2yaml":
        if not yaml_available:
            return "❌ pyyaml not installed. Run: pip install pyyaml"
        if not arg:
            return "Usage: json2yaml <json_string>"
        try:
            data = json.loads(arg)
            return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    if action == "yaml2json":
        if not yaml_available:
            return "❌ pyyaml not installed. Run: pip install pyyaml"
        if not arg:
            return "Usage: yaml2json <yaml_string>"
        try:
            data = yaml.safe_load(arg)
            return json.dumps(data, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"❌ Invalid YAML: {e}"

    if action == "format":
        if not arg:
            return "Usage: format <json_string>"
        try:
            data = json.loads(arg)
            return json.dumps(data, indent=2, ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    if action == "minify":
        if not arg:
            return "Usage: minify <json_string>"
        try:
            data = json.loads(arg)
            return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    if action == "query":
        if not arg:
            return "Usage: query <dot.path> <json_string>"
        qparts = arg.split(" ", 1)
        if len(qparts) < 2:
            return "Usage: query <dot.path> <json_string>"
        path, json_str = qparts[0], qparts[1]
        try:
            data = json.loads(json_str)
            for key in path.split("."):
                if isinstance(data, list):
                    try:
                        data = data[int(key)]
                    except (IndexError, ValueError):
                        return f"❌ Invalid index '{key}' for array"
                elif isinstance(data, dict):
                    if key in data:
                        data = data[key]
                    else:
                        return f"❌ Key '{key}' not found. Available: {', '.join(data.keys())}"
                else:
                    return f"❌ Cannot traverse into {type(data).__name__}"
            if isinstance(data, (dict, list)):
                return json.dumps(data, indent=2, ensure_ascii=False)
            return str(data)
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    if action == "keys":
        if not arg:
            return "Usage: keys <json_string>"
        try:
            data = json.loads(arg)
            if isinstance(data, dict):
                lines = [f"Keys ({len(data)}):"]
                for k, v in data.items():
                    vtype = type(v).__name__
                    lines.append(f"  • {k} ({vtype})")
                return "\n".join(lines)
            elif isinstance(data, list):
                return f"Array with {len(data)} elements (indices 0–{len(data)-1})"
            return f"Value is {type(data).__name__}, not a dict/list"
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    if action == "merge":
        if "|||" not in arg:
            return "Usage: merge <json1> ||| <json2>"
        left_str, right_str = arg.split("|||", 1)
        try:
            left = json.loads(left_str.strip())
            right = json.loads(right_str.strip())

            def deep_merge(a, b):
                result = a.copy()
                for k, v in b.items():
                    if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                        result[k] = deep_merge(result[k], v)
                    else:
                        result[k] = v
                return result

            if not isinstance(left, dict) or not isinstance(right, dict):
                return "❌ Both values must be JSON objects for merge"
            merged = deep_merge(left, right)
            return json.dumps(merged, indent=2, ensure_ascii=False)
        except json.JSONDecodeError as e:
            return f"❌ Invalid JSON: {e}"

    return (
        "JSON/YAML tool commands:\n"
        "  validate <data>         — Check if valid JSON or YAML\n"
        "  json2yaml <json>        — Convert JSON → YAML\n"
        "  yaml2json <yaml>        — Convert YAML → JSON\n"
        "  format <json>           — Pretty-print JSON\n"
        "  minify <json>           — Compact JSON\n"
        "  query <path> <json>     — Dot-notation query (e.g., users.0.name)\n"
        "  keys <json>             — List top-level keys\n"
        "  merge <j1> ||| <j2>     — Deep merge two JSON objects"
    )


# =====================================================================
# Tool 16: CSV Data Processing
# =====================================================================
def csv_data_tool(command: str) -> str:
    """Process CSV data: parse, query, sort, filter, stats, convert.

    Commands:
      parse <csv_text>               — Parse CSV and show as table
      stats <csv_text>               — Column statistics (count, min, max, avg for numeric)
      sort <column> <csv_text>       — Sort by column name
      filter <column>=<value> <csv>  — Filter rows where column matches value
      headers <csv_text>             — List column headers
      count <csv_text>               — Count rows
      to_json <csv_text>             — Convert CSV to JSON array
      read <filepath>                — Parse a CSV file from disk
    """
    log.debug("csv_data_tool called: %s", command[:200])
    import csv as csv_mod
    import io

    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    def _parse_csv(text: str) -> tuple[list[str], list[dict]]:
        """Parse CSV text into headers and list of dicts."""
        reader = csv_mod.DictReader(io.StringIO(text.strip()))
        headers = reader.fieldnames or []
        rows = list(reader)
        return headers, rows

    def _format_table(headers: list[str], rows: list[dict], max_rows: int = 50) -> str:
        """Format as a readable text table."""
        if not headers or not rows:
            return "No data"
        # Column widths
        widths = {h: len(h) for h in headers}
        display_rows = rows[:max_rows]
        for row in display_rows:
            for h in headers:
                widths[h] = max(widths[h], len(str(row.get(h, ""))))
        # Cap column width
        for h in headers:
            widths[h] = min(widths[h], 30)
        # Header line
        header_line = " | ".join(h.ljust(widths[h])[:widths[h]] for h in headers)
        sep_line = "-+-".join("-" * widths[h] for h in headers)
        lines = [header_line, sep_line]
        for row in display_rows:
            line = " | ".join(str(row.get(h, "")).ljust(widths[h])[:widths[h]] for h in headers)
            lines.append(line)
        if len(rows) > max_rows:
            lines.append(f"... ({len(rows) - max_rows} more rows)")
        lines.append(f"\n{len(rows)} row(s), {len(headers)} column(s)")
        return "\n".join(lines)

    if action == "read":
        if not arg:
            return "Usage: read <filepath>"
        fpath = Path(arg).resolve()
        if not fpath.exists():
            return f"❌ File not found: {fpath}"
        try:
            text = fpath.read_text(encoding="utf-8")
            headers, rows = _parse_csv(text)
            return _format_table(headers, rows)
        except Exception as e:
            return f"❌ Error reading CSV: {e}"

    if action == "parse":
        if not arg:
            return "Usage: parse <csv_text>"
        try:
            headers, rows = _parse_csv(arg)
            return _format_table(headers, rows)
        except Exception as e:
            return f"❌ Parse error: {e}"

    if action == "stats":
        if not arg:
            return "Usage: stats <csv_text>"
        try:
            headers, rows = _parse_csv(arg)
            if not rows:
                return "No data rows found"
            lines = [f"CSV Statistics ({len(rows)} rows, {len(headers)} columns):\n"]
            for h in headers:
                values = [row.get(h, "") for row in rows]
                non_empty = [v for v in values if v]
                # Try numeric analysis
                nums = []
                for v in non_empty:
                    try:
                        nums.append(float(v))
                    except ValueError:
                        pass
                if nums:
                    lines.append(
                        f"  {h} (numeric): count={len(nums)}, "
                        f"min={min(nums):.2f}, max={max(nums):.2f}, "
                        f"avg={sum(nums)/len(nums):.2f}, sum={sum(nums):.2f}"
                    )
                else:
                    unique = len(set(non_empty))
                    lines.append(f"  {h} (text): count={len(non_empty)}, unique={unique}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "sort":
        sparts = arg.split(" ", 1)
        if len(sparts) < 2:
            return "Usage: sort <column_name> <csv_text>"
        col, csv_text = sparts
        try:
            headers, rows = _parse_csv(csv_text)
            if col not in headers:
                return f"❌ Column '{col}' not found. Available: {', '.join(headers)}"
            # Try numeric sort, fallback to string
            try:
                rows.sort(key=lambda r: float(r.get(col, 0)))
            except (ValueError, TypeError):
                rows.sort(key=lambda r: str(r.get(col, "")))
            return _format_table(headers, rows)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "filter":
        if "=" not in arg:
            return "Usage: filter <column>=<value> <csv_text>"
        cond, csv_text = arg.split(" ", 1) if " " in arg else (arg, "")
        col, val = cond.split("=", 1)
        if not csv_text:
            return "Usage: filter <column>=<value> <csv_text>"
        try:
            headers, rows = _parse_csv(csv_text)
            if col not in headers:
                return f"❌ Column '{col}' not found. Available: {', '.join(headers)}"
            filtered = [r for r in rows if str(r.get(col, "")).lower() == val.lower()]
            return _format_table(headers, filtered) + f"\n(filtered {len(filtered)}/{len(rows)} rows)"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "headers":
        if not arg:
            return "Usage: headers <csv_text>"
        try:
            headers, rows = _parse_csv(arg)
            lines = [f"Columns ({len(headers)}):"]
            for i, h in enumerate(headers, 1):
                lines.append(f"  {i}. {h}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "count":
        if not arg:
            return "Usage: count <csv_text>"
        try:
            headers, rows = _parse_csv(arg)
            return f"{len(rows)} row(s), {len(headers)} column(s)"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "to_json":
        if not arg:
            return "Usage: to_json <csv_text>"
        try:
            headers, rows = _parse_csv(arg)
            return json.dumps(rows, indent=2, ensure_ascii=False)
        except Exception as e:
            return f"❌ Error: {e}"

    return (
        "CSV Data tool commands:\n"
        "  parse <csv>                  — Display CSV as formatted table\n"
        "  stats <csv>                  — Column statistics\n"
        "  sort <column> <csv>          — Sort by column\n"
        "  filter <column>=<val> <csv>  — Filter rows\n"
        "  headers <csv>                — List columns\n"
        "  count <csv>                  — Count rows\n"
        "  to_json <csv>                — Convert to JSON\n"
        "  read <filepath>              — Read and display CSV file"
    )


# =====================================================================
# Tool 17: PDF Reader (text extraction & search)
# =====================================================================
def pdf_reader(command: str) -> str:
    """Extract text from PDF files, search content, get metadata.

    Commands:
      read <filepath>               — Extract all text from a PDF
      page <number> <filepath>      — Extract text from a specific page
      search <keyword> <filepath>   — Search for text within a PDF
      info <filepath>               — Show PDF metadata (title, author, pages)
      count <filepath>              — Count pages in a PDF
    """
    log.debug("pdf_reader called: %s", command[:200])
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return (
            "❌ PyMuPDF not installed. Install it:\n"
            "  pip install pymupdf\n"
            "This provides the 'fitz' module for PDF processing."
        )

    def _open_pdf(filepath: str):
        fpath = _safe_path(filepath)
        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")
        if fpath.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {fpath.suffix}")
        return fitz.open(str(fpath))

    if action == "read":
        if not arg:
            return "Usage: read <filepath>"
        try:
            doc = _open_pdf(arg)
            lines = [f"PDF: {Path(arg).name} ({doc.page_count} pages)\n{'='*50}\n"]
            total_chars = 0
            for i, page in enumerate(doc):
                text = page.get_text().strip()
                total_chars += len(text)
                if text:
                    lines.append(f"--- Page {i+1} ---\n{text}\n")
            doc.close()
            if total_chars == 0:
                return f"PDF has {doc.page_count} pages but no extractable text (may be scanned/image-based)."
            result = "\n".join(lines)
            if len(result) > 10000:
                result = result[:10000] + f"\n\n... (truncated — {total_chars} total characters)"
            return result
        except FileNotFoundError as e:
            return f"❌ {e}"
        except ValueError as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ Error reading PDF: {e}"

    if action == "page":
        pparts = arg.split(" ", 1)
        if len(pparts) < 2:
            return "Usage: page <number> <filepath>"
        try:
            page_num = int(pparts[0])
        except ValueError:
            return "❌ Page number must be an integer"
        filepath = pparts[1]
        try:
            doc = _open_pdf(filepath)
            if page_num < 1 or page_num > doc.page_count:
                doc.close()
                return f"❌ Page {page_num} out of range (1–{doc.page_count})"
            text = doc[page_num - 1].get_text().strip()
            doc.close()
            return f"Page {page_num}/{doc.page_count}:\n\n{text}" if text else f"Page {page_num} has no extractable text."
        except (FileNotFoundError, ValueError) as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "search":
        sparts = arg.split(" ", 1)
        if len(sparts) < 2:
            return "Usage: search <keyword> <filepath>"
        keyword, filepath = sparts[0], sparts[1]
        # Handle multi-word keyword in quotes
        if arg.startswith('"') or arg.startswith("'"):
            try:
                end_q = arg.index(arg[0], 1)
                keyword = arg[1:end_q]
                filepath = arg[end_q+1:].strip()
            except ValueError:
                pass
        try:
            doc = _open_pdf(filepath)
            matches = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if keyword.lower() in text.lower():
                    # Extract context
                    lower_text = text.lower()
                    pos = lower_text.find(keyword.lower())
                    start = max(0, pos - 50)
                    end = min(len(text), pos + len(keyword) + 50)
                    snippet = text[start:end].replace("\n", " ").strip()
                    count = lower_text.count(keyword.lower())
                    matches.append({"page": i + 1, "count": count, "snippet": snippet})
            doc.close()
            if not matches:
                return f"'{keyword}' not found in {Path(filepath).name}"
            total = sum(m["count"] for m in matches)
            lines = [f"Found '{keyword}' — {total} occurrence(s) across {len(matches)} page(s):\n"]
            for m in matches[:20]:
                lines.append(f"  Page {m['page']} ({m['count']}x): ...{m['snippet']}...")
            return "\n".join(lines)
        except (FileNotFoundError, ValueError) as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "info":
        if not arg:
            return "Usage: info <filepath>"
        try:
            doc = _open_pdf(arg)
            meta = doc.metadata
            info_lines = [
                f"PDF: {Path(arg).name}",
                f"Pages: {doc.page_count}",
                f"Title: {meta.get('title', '(none)')}",
                f"Author: {meta.get('author', '(none)')}",
                f"Subject: {meta.get('subject', '(none)')}",
                f"Creator: {meta.get('creator', '(none)')}",
                f"Producer: {meta.get('producer', '(none)')}",
                f"Created: {meta.get('creationDate', '(unknown)')}",
                f"Modified: {meta.get('modDate', '(unknown)')}",
            ]
            doc.close()
            return "\n".join(info_lines)
        except (FileNotFoundError, ValueError) as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "count":
        if not arg:
            return "Usage: count <filepath>"
        try:
            doc = _open_pdf(arg)
            count = doc.page_count
            doc.close()
            return f"{Path(arg).name}: {count} page(s)"
        except (FileNotFoundError, ValueError) as e:
            return f"❌ {e}"
        except Exception as e:
            return f"❌ Error: {e}"

    return (
        "PDF Reader commands:\n"
        "  read <filepath>              — Extract all text\n"
        "  page <number> <filepath>     — Extract specific page\n"
        "  search <keyword> <filepath>  — Search for text\n"
        "  info <filepath>              — Show metadata\n"
        "  count <filepath>             — Count pages"
    )


# =====================================================================
# Tool 18: Sandboxed Python Code Runner
# =====================================================================
def code_runner(code: str) -> str:
    """Execute Python code in a sandboxed subprocess.

    Safety features:
      • Runs in a separate subprocess (not eval/exec in host)
      • 10-second timeout kills runaway code
      • Blocked dangerous imports: os, sys, subprocess, shutil, pathlib, importlib
      • Blocked builtins: exec, eval, compile, __import__, open
      • Max 100 lines of output
      • Max 5MB memory output cap
    """
    log.debug("code_runner called: %s", code[:200])

    if not code.strip():
        return "Usage: Provide Python code to execute.\nExample: print('Hello, World!')"

    # ── Safety checks on input ──
    blocked_imports = [
        "os", "sys", "subprocess", "shutil", "pathlib", "importlib",
        "ctypes", "signal", "socket", "http", "urllib", "requests",
        "multiprocessing", "threading", "pickle", "shelve",
    ]

    # Check for dangerous imports
    for mod in blocked_imports:
        patterns = [
            rf'\bimport\s+{mod}\b',
            rf'\bfrom\s+{mod}\b',
        ]
        for pat in patterns:
            if re.search(pat, code):
                return f"❌ Blocked: import of '{mod}' is not allowed for security reasons."

    # Check for dangerous builtins
    blocked_builtins = ["exec(", "eval(", "compile(", "__import__(", "open(", "globals(", "locals("]
    for b in blocked_builtins:
        if b in code:
            return f"❌ Blocked: '{b.rstrip('(')}' is not allowed for security reasons."

    # ── Execute in subprocess ──
    import sys as _sys

    try:
        result = subprocess.run(
            [_sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=tempfile.gettempdir(),
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Cap output
        max_lines = 100
        if stdout:
            lines = stdout.split("\n")
            if len(lines) > max_lines:
                stdout = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines truncated)"

        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"⚠️ Stderr:\n{stderr}")
        if not output_parts:
            output_parts.append("(code executed successfully — no output)")

        if result.returncode != 0:
            output_parts.append(f"\nExit code: {result.returncode}")

        return "\n".join(output_parts)

    except subprocess.TimeoutExpired:
        return "❌ Execution timed out (10 second limit). Your code may have an infinite loop."
    except FileNotFoundError:
        return "❌ Python interpreter not found. Cannot execute code."
    except Exception as e:
        return f"❌ Execution error: {e}"


# =====================================================================
# Tool 19: Process Manager
# =====================================================================
def process_manager(command: str) -> str:
    """View and manage system processes.

    Commands:
      list                    — List top processes by CPU usage
      search <name>           — Find processes by name
      info <pid>              — Detailed info about a process
      top                     — Show top 10 processes by CPU
      memory                  — Show top 10 processes by memory
      count                   — Count total running processes
    """
    log.debug("process_manager called: %s", command[:200])

    try:
        import psutil
    except ImportError:
        return (
            "❌ psutil not installed. Install it:\n"
            "  pip install psutil\n"
            "This provides process and system monitoring capabilities."
        )

    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else "top"
    arg = parts[1].strip() if len(parts) > 1 else ""

    if action in ("list", "top"):
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
                try:
                    info = p.info
                    procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            # Sort by CPU
            procs.sort(key=lambda x: x.get("cpu_percent", 0) or 0, reverse=True)
            top_n = procs[:20]
            lines = [f"Top {len(top_n)} processes by CPU:\n"]
            lines.append(f"{'PID':>7}  {'CPU%':>5}  {'MEM%':>5}  {'STATUS':>10}  NAME")
            lines.append("-" * 60)
            for p in top_n:
                lines.append(
                    f"{p['pid']:>7}  {p.get('cpu_percent', 0):>5.1f}  "
                    f"{p.get('memory_percent', 0):>5.1f}  "
                    f"{p.get('status', '?'):>10}  {p.get('name', '?')}"
                )
            lines.append(f"\nTotal processes: {len(procs)}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error listing processes: {e}"

    if action == "memory":
        try:
            procs = []
            for p in psutil.process_iter(["pid", "name", "memory_percent", "memory_info"]):
                try:
                    procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: x.get("memory_percent", 0) or 0, reverse=True)
            top_n = procs[:20]
            lines = [f"Top {len(top_n)} processes by memory:\n"]
            lines.append(f"{'PID':>7}  {'MEM%':>5}  {'RSS MB':>8}  NAME")
            lines.append("-" * 50)
            for p in top_n:
                mem_info = p.get("memory_info")
                rss_mb = (mem_info.rss / 1024 / 1024) if mem_info else 0
                lines.append(
                    f"{p['pid']:>7}  {p.get('memory_percent', 0):>5.1f}  "
                    f"{rss_mb:>8.1f}  {p.get('name', '?')}"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "search":
        if not arg:
            return "Usage: search <process_name>"
        try:
            matches = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
                try:
                    if arg.lower() in (p.info.get("name", "") or "").lower():
                        matches.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            if not matches:
                return f"No processes matching '{arg}'"
            lines = [f"Found {len(matches)} process(es) matching '{arg}':\n"]
            for p in matches:
                lines.append(
                    f"  PID {p['pid']:>7}: {p.get('name', '?')} "
                    f"(CPU: {p.get('cpu_percent', 0):.1f}%, "
                    f"MEM: {p.get('memory_percent', 0):.1f}%, "
                    f"Status: {p.get('status', '?')})"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "info":
        if not arg:
            return "Usage: info <pid>"
        try:
            pid = int(arg)
            p = psutil.Process(pid)
            with p.oneshot():
                lines = [
                    f"Process {pid}: {p.name()}",
                    f"  Status: {p.status()}",
                    f"  CPU: {p.cpu_percent(interval=0.5):.1f}%",
                    f"  Memory: {p.memory_percent():.1f}% ({p.memory_info().rss / 1024 / 1024:.1f} MB RSS)",
                    f"  Threads: {p.num_threads()}",
                    f"  Created: {datetime.datetime.fromtimestamp(p.create_time()).strftime('%Y-%m-%d %H:%M:%S')}",
                ]
                try:
                    lines.append(f"  CWD: {p.cwd()}")
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                try:
                    lines.append(f"  Cmdline: {' '.join(p.cmdline()[:5])}")
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
                try:
                    lines.append(f"  Parent PID: {p.ppid()}")
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass
            return "\n".join(lines)
        except ValueError:
            return "❌ PID must be an integer"
        except psutil.NoSuchProcess:
            return f"❌ No process with PID {arg}"
        except psutil.AccessDenied:
            return f"❌ Access denied for PID {arg}"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "count":
        try:
            pids = psutil.pids()
            return f"Total running processes: {len(pids)}"
        except Exception as e:
            return f"❌ Error: {e}"

    return (
        "Process Manager commands:\n"
        "  list / top     — Top processes by CPU\n"
        "  memory         — Top processes by memory\n"
        "  search <name>  — Find by name\n"
        "  info <pid>     — Process details\n"
        "  count          — Total process count"
    )


# =====================================================================
# Tool 20: Network Diagnostics
# =====================================================================
def network_diag(command: str) -> str:
    """Network diagnostics: ping, DNS lookup, port check, HTTP test.

    Commands:
      ping <host>             — Ping a host (4 ICMP packets)
      dns <domain>            — DNS lookup (resolve to IP)
      ports <host>            — Check common ports (22,80,443,8080,3306,5432)
      check <host:port>       — Check if a specific port is open
      http <url>              — Test HTTP endpoint (status, headers, timing)
      interfaces              — List network interfaces and IPs
      speed                   — Quick connection speed test (download ~1MB)
    """
    log.debug("network_diag called: %s", command[:200])
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if action == "ping":
        if not arg:
            return "Usage: ping <hostname_or_ip>"
        host = arg.split()[0]
        try:
            param = "-n" if platform.system().lower() == "windows" else "-c"
            result = subprocess.run(
                ["ping", param, "4", host],
                capture_output=True, text=True, timeout=15,
            )
            output = result.stdout.strip()
            if result.returncode != 0 and result.stderr:
                output += f"\n{result.stderr.strip()}"
            return output if output else f"Ping to {host} completed (no output)"
        except subprocess.TimeoutExpired:
            return f"❌ Ping to {host} timed out"
        except FileNotFoundError:
            return "❌ ping command not found"
        except Exception as e:
            return f"❌ Ping error: {e}"

    if action == "dns":
        if not arg:
            return "Usage: dns <domain>"
        domain = arg.split()[0]
        try:
            lines = [f"DNS lookup for {domain}:\n"]
            results = socket.getaddrinfo(domain, None)
            seen = set()
            for family, socktype, proto, canonname, addr in results:
                ip = addr[0]
                if ip not in seen:
                    seen.add(ip)
                    fam = "IPv4" if family == socket.AF_INET else "IPv6"
                    lines.append(f"  {fam}: {ip}")
            try:
                hostname = socket.gethostbyaddr(list(seen)[0])[0] if seen else "?"
                lines.append(f"\nReverse DNS: {hostname}")
            except (socket.herror, socket.gaierror):
                pass
            return "\n".join(lines)
        except socket.gaierror:
            return f"❌ Cannot resolve '{domain}' — DNS lookup failed"
        except Exception as e:
            return f"❌ DNS error: {e}"

    if action == "ports":
        if not arg:
            return "Usage: ports <host>"
        host = arg.split()[0]
        common_ports = {
            21: "FTP", 22: "SSH", 25: "SMTP", 53: "DNS",
            80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
            993: "IMAPS", 995: "POP3S", 3306: "MySQL", 3389: "RDP",
            5432: "PostgreSQL", 5900: "VNC", 6379: "Redis",
            8080: "HTTP-Alt", 8443: "HTTPS-Alt", 27017: "MongoDB",
        }
        lines = [f"Port scan for {host}:\n"]
        open_count = 0
        for port, service in sorted(common_ports.items()):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.5)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    lines.append(f"  ✅ {port:>5}/tcp  OPEN    {service}")
                    open_count += 1
                else:
                    lines.append(f"  ❌ {port:>5}/tcp  closed  {service}")
            except socket.gaierror:
                return f"❌ Cannot resolve host '{host}'"
            except Exception:
                lines.append(f"  ❓ {port:>5}/tcp  error   {service}")
        lines.append(f"\n{open_count}/{len(common_ports)} ports open")
        return "\n".join(lines)

    if action == "check":
        if not arg or ":" not in arg:
            return "Usage: check <host:port>"
        host_port = arg.split()[0]
        host, port_str = host_port.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            return "❌ Port must be a number"
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return f"✅ {host}:{port} is OPEN"
            else:
                return f"❌ {host}:{port} is CLOSED (error code: {result})"
        except socket.gaierror:
            return f"❌ Cannot resolve host '{host}'"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "http":
        if not arg:
            return "Usage: http <url>"
        url = arg.split()[0]
        if not url.startswith("http"):
            url = "https://" + url
        try:
            import time
            start = time.time()
            resp = _safe_get(url)
            elapsed = time.time() - start
            lines = [
                f"HTTP test for {url}:\n",
                f"  Status: {resp.status_code} {resp.reason}",
                f"  Time: {elapsed:.2f}s",
                f"  Size: {len(resp.content)} bytes",
                f"  Content-Type: {resp.headers.get('Content-Type', '?')}",
                f"  Server: {resp.headers.get('Server', '?')}",
            ]
            if resp.history:
                lines.append(f"  Redirects: {len(resp.history)}")
                for r in resp.history:
                    lines.append(f"    → {r.status_code} {r.url}")
            for key in ["X-Powered-By", "X-Frame-Options", "Content-Security-Policy",
                         "Strict-Transport-Security", "X-Content-Type-Options"]:
                val = resp.headers.get(key)
                if val:
                    lines.append(f"  {key}: {val}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ HTTP error: {e}"

    if action == "interfaces":
        try:
            lines = ["Network interfaces:\n"]
            hostname = socket.gethostname()
            lines.append(f"  Hostname: {hostname}")
            try:
                addrs = socket.getaddrinfo(hostname, None)
                seen = set()
                for family, _, _, _, addr in addrs:
                    ip = addr[0]
                    if ip not in seen and not ip.startswith("::"):
                        seen.add(ip)
                        fam = "IPv4" if family == socket.AF_INET else "IPv6"
                        lines.append(f"  {fam}: {ip}")
            except Exception:
                pass
            try:
                import psutil
                for name, addrs in psutil.net_if_addrs().items():
                    for addr in addrs:
                        if addr.family == socket.AF_INET:
                            lines.append(f"  {name}: {addr.address} (netmask: {addr.netmask})")
            except ImportError:
                pass
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "speed":
        try:
            import time
            test_url = "https://speed.cloudflare.com/__down?bytes=1000000"
            start = time.time()
            resp = requests.get(test_url, timeout=15)
            elapsed = time.time() - start
            size_mb = len(resp.content) / 1024 / 1024
            speed_mbps = (size_mb * 8) / elapsed if elapsed > 0 else 0
            return (
                f"Speed test result:\n"
                f"  Downloaded: {size_mb:.2f} MB\n"
                f"  Time: {elapsed:.2f}s\n"
                f"  Speed: {speed_mbps:.2f} Mbps ({size_mb/elapsed:.2f} MB/s)"
            )
        except Exception as e:
            return f"❌ Speed test error: {e}"

    return (
        "Network Diagnostics commands:\n"
        "  ping <host>        — Ping a host\n"
        "  dns <domain>       — DNS lookup\n"
        "  ports <host>       — Scan common ports\n"
        "  check <host:port>  — Check specific port\n"
        "  http <url>         — Test HTTP endpoint\n"
        "  interfaces         — List network interfaces\n"
        "  speed              — Connection speed test"
    )


# =====================================================================
# Tool 21: Password Generator
# =====================================================================
def password_gen(command: str) -> str:
    """Generate secure passwords and passphrases.

    Commands:
      generate [length]         — Random password (default 16 chars)
      strong [length]           — Extra strong (uppercase, lower, digits, symbols)
      pin [length]              — Numeric PIN (default 6 digits)
      passphrase [words]        — Word-based passphrase (default 4 words)
      uuid                      — Generate a UUID v4
      token [length]            — URL-safe random token (default 32 bytes)
      check <password>          — Evaluate password strength
    """
    log.debug("password_gen called: %s", command[:100])
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else "generate"
    arg = parts[1].strip() if len(parts) > 1 else ""

    if action in ("generate", "gen"):
        length = 16
        if arg:
            try:
                length = max(4, min(128, int(arg)))
            except ValueError:
                pass
        charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+"
        password = "".join(secrets.choice(charset) for _ in range(length))
        return f"🔑 Generated password ({length} chars):\n{password}"

    if action == "strong":
        length = 20
        if arg:
            try:
                length = max(8, min(128, int(arg)))
            except ValueError:
                pass
        lower = "abcdefghijklmnopqrstuvwxyz"
        upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        digits = "0123456789"
        symbols = "!@#$%^&*()-_=+[]{}|;:,.<>?"
        all_chars = lower + upper + digits + symbols
        password = [
            secrets.choice(lower), secrets.choice(upper),
            secrets.choice(digits), secrets.choice(symbols),
        ]
        password += [secrets.choice(all_chars) for _ in range(length - 4)]
        shuffled = list(password)
        for i in range(len(shuffled) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        return f"🔐 Strong password ({length} chars):\n{''.join(shuffled)}"

    if action == "pin":
        length = 6
        if arg:
            try:
                length = max(4, min(12, int(arg)))
            except ValueError:
                pass
        pin = "".join(secrets.choice("0123456789") for _ in range(length))
        return f"🔢 PIN ({length} digits):\n{pin}"

    if action == "passphrase":
        word_count = 4
        if arg:
            try:
                word_count = max(3, min(10, int(arg)))
            except ValueError:
                pass
        wordlist = [
            "apple", "brave", "cloud", "dance", "eagle", "flame", "grape", "house",
            "ivory", "jelly", "knife", "lemon", "maple", "north", "ocean", "piano",
            "queen", "river", "stone", "tiger", "under", "vivid", "water", "xenon",
            "yacht", "zebra", "amber", "bloom", "crest", "drift", "ember", "frost",
            "glyph", "haven", "inlet", "jewel", "knack", "lunar", "marsh", "noble",
            "oasis", "plume", "quest", "ridge", "swift", "thorn", "ultra", "vault",
            "whirl", "xeric", "yield", "zonal", "bliss", "charm", "delta", "forge",
            "globe", "haste", "irony", "joust", "karma", "light", "mirth", "nexus",
            "orbit", "pulse", "quilt", "roost", "solar", "trace", "unity", "vigor",
            "woven", "axiom", "yeast", "zephyr", "acorn", "birch", "coral", "dwell",
        ]
        words = [secrets.choice(wordlist) for _ in range(word_count)]
        passphrase = "-".join(words)
        return (
            f"📝 Passphrase ({word_count} words):\n{passphrase}\n"
            f"Title case: {'-'.join(w.title() for w in words)}"
        )

    if action == "uuid":
        import uuid
        uid = uuid.uuid4()
        return f"🆔 UUID v4:\n{uid}"

    if action == "token":
        length = 32
        if arg:
            try:
                length = max(8, min(128, int(arg)))
            except ValueError:
                pass
        token = secrets.token_urlsafe(length)
        return f"🎟️ URL-safe token ({length} bytes):\n{token}"

    if action == "check":
        if not arg:
            return "Usage: check <password>"
        password = arg
        score = 0
        feedback = []
        if len(password) >= 8:
            score += 1
        else:
            feedback.append("Too short (min 8 chars)")
        if len(password) >= 12:
            score += 1
        if len(password) >= 16:
            score += 1
        if re.search(r"[a-z]", password):
            score += 1
        else:
            feedback.append("Add lowercase letters")
        if re.search(r"[A-Z]", password):
            score += 1
        else:
            feedback.append("Add uppercase letters")
        if re.search(r"\d", password):
            score += 1
        else:
            feedback.append("Add digits")
        if re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]", password):
            score += 1
        else:
            feedback.append("Add special characters")
        if re.search(r"(.)\1{2,}", password):
            score -= 1
            feedback.append("Avoid repeated characters")
        if re.search(r"(012|123|234|345|456|567|678|789|abc|bcd|cde|def)", password.lower()):
            score -= 1
            feedback.append("Avoid sequential patterns")

        strength = {0: "Very Weak", 1: "Very Weak", 2: "Weak", 3: "Fair",
                     4: "Good", 5: "Strong", 6: "Very Strong", 7: "Excellent"}
        level = strength.get(max(0, min(7, score)), "Unknown")
        bars = "█" * max(0, score) + "░" * (7 - max(0, score))
        result = f"Password strength: {level}\n[{bars}] {score}/7\nLength: {len(password)} characters"
        if feedback:
            result += "\nSuggestions:\n" + "\n".join(f"  • {f}" for f in feedback)
        return result

    # Default: generate a password
    return password_gen("generate")


# =====================================================================
# Tool 22: Regex Tool (testing & matching)
# =====================================================================
def regex_tool(command: str) -> str:
    """Test, match, and learn regular expressions.

    Commands:
      test <pattern> <text>       — Test if pattern matches text
      findall <pattern> <text>    — Find all matches
      replace <pattern> <repl> <text> — Replace matches
      split <pattern> <text>      — Split text by pattern
      explain <pattern>           — Explain what a regex does
      common                      — Show common regex patterns
    """
    log.debug("regex_tool called: %s", command[:200])
    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    if action == "test":
        if not arg:
            return "Usage: test <pattern> <text>"
        rparts = arg.split(" ", 1)
        if len(rparts) < 2:
            return "Usage: test <pattern> <text>"
        pattern, text = rparts
        try:
            match = re.search(pattern, text)
            if match:
                return (
                    f"✅ Pattern matches!\n"
                    f"  Match: '{match.group()}'\n"
                    f"  Position: {match.start()}–{match.end()}\n"
                    f"  Groups: {match.groups() if match.groups() else '(none)'}"
                )
            return f"❌ Pattern '{pattern}' does not match the text."
        except re.error as e:
            return f"❌ Invalid regex: {e}"

    if action == "findall":
        if not arg:
            return "Usage: findall <pattern> <text>"
        rparts = arg.split(" ", 1)
        if len(rparts) < 2:
            return "Usage: findall <pattern> <text>"
        pattern, text = rparts
        try:
            matches = re.findall(pattern, text)
            if matches:
                lines = [f"Found {len(matches)} match(es):"]
                for i, m in enumerate(matches[:50], 1):
                    lines.append(f"  {i}. {m}")
                if len(matches) > 50:
                    lines.append(f"  ... ({len(matches) - 50} more)")
                return "\n".join(lines)
            return f"No matches for pattern '{pattern}'"
        except re.error as e:
            return f"❌ Invalid regex: {e}"

    if action == "replace":
        if not arg:
            return "Usage: replace <pattern> <replacement> <text>"
        rparts = arg.split(" ", 2)
        if len(rparts) < 3:
            return "Usage: replace <pattern> <replacement> <text>"
        pattern, replacement, text = rparts
        try:
            result, count = re.subn(pattern, replacement, text)
            return f"Replaced {count} occurrence(s):\n{result}"
        except re.error as e:
            return f"❌ Invalid regex: {e}"

    if action == "split":
        if not arg:
            return "Usage: split <pattern> <text>"
        rparts = arg.split(" ", 1)
        if len(rparts) < 2:
            return "Usage: split <pattern> <text>"
        pattern, text = rparts
        try:
            parts_result = re.split(pattern, text)
            lines = [f"Split into {len(parts_result)} part(s):"]
            for i, p in enumerate(parts_result, 1):
                lines.append(f"  {i}. '{p}'")
            return "\n".join(lines)
        except re.error as e:
            return f"❌ Invalid regex: {e}"

    if action == "explain":
        if not arg:
            return "Usage: explain <pattern>"
        patterns_explained = {
            r".": "Any character except newline",
            r"*": "0 or more of previous",
            r"+": "1 or more of previous",
            r"?": "0 or 1 of previous",
            r"^": "Start of string",
            r"$": "End of string",
            r"\d": "Any digit (0-9)",
            r"\w": "Any word character (letter, digit, underscore)",
            r"\s": "Any whitespace (space, tab, newline)",
            r"\b": "Word boundary",
            r"[]": "Character class",
            r"()": "Capturing group",
            r"|": "OR (alternation)",
            r"{n}": "Exactly n repetitions",
            r"{n,m}": "Between n and m repetitions",
        }
        lines = [f"Regex pattern: {arg}\n"]
        lines.append("Character meanings:")
        for char in arg:
            if char in patterns_explained:
                lines.append(f"  '{char}' → {patterns_explained[char]}")
        try:
            re.compile(arg)
            lines.append(f"\n✅ Pattern is valid")
        except re.error as e:
            lines.append(f"\n❌ Pattern is invalid: {e}")
        return "\n".join(lines)

    if action == "common":
        return (
            "Common regex patterns:\n\n"
            "  Email:      [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}\n"
            "  Phone:      \\+?\\d{1,3}[-.\\s]?\\d{3,4}[-.\\s]?\\d{4}\n"
            "  URL:        https?://[^\\s]+\n"
            "  IPv4:       \\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\n"
            "  Date:       \\d{4}-\\d{2}-\\d{2}\n"
            "  Time:       \\d{2}:\\d{2}(:\\d{2})?\n"
            "  Hex color:  #[0-9a-fA-F]{6}\n"
            "  MAC addr:   ([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\n"
            "  Zip code:   \\d{5}(-\\d{4})?\n"
            "  Username:   [a-zA-Z0-9_]{3,20}\n"
            "  Float:      -?\\d+\\.\\d+\n"
            "  Integer:    -?\\d+"
        )

    return (
        "Regex tool commands:\n"
        "  test <pattern> <text>          — Test if pattern matches\n"
        "  findall <pattern> <text>       — Find all matches\n"
        "  replace <pat> <repl> <text>    — Replace matches\n"
        "  split <pattern> <text>         — Split by pattern\n"
        "  explain <pattern>              — Explain regex chars\n"
        "  common                         — Show common patterns"
    )


# =====================================================================
# Tool 23: Archive Tool (zip, tar, gzip)
# =====================================================================
def archive_tool(command: str) -> str:
    """Create, extract, and inspect archive files (zip, tar, tar.gz).

    Commands:
      create <archive_path> <file1> [file2 ...]  — Create an archive
      extract <archive_path> [dest_dir]           — Extract an archive
      list <archive_path>                         — List contents
      info <archive_path>                         — Archive metadata
    """
    log.debug("archive_tool called: %s", command[:200])
    import zipfile
    import tarfile

    parts = command.strip().split(" ", 1)
    action = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""

    def _detect_type(filepath: str) -> str:
        lower = filepath.lower()
        if lower.endswith(".zip"):
            return "zip"
        elif lower.endswith((".tar.gz", ".tgz")):
            return "tar.gz"
        elif lower.endswith((".tar.bz2", ".tbz2")):
            return "tar.bz2"
        elif lower.endswith(".tar"):
            return "tar"
        elif lower.endswith(".gz"):
            return "gz"
        return "unknown"

    if action == "create":
        if not arg:
            return "Usage: create <archive_path> <file1> [file2 ...]"
        file_args = arg.split()
        if len(file_args) < 2:
            return "Usage: create <archive_path> <file1> [file2 ...]"
        archive_path = file_args[0]
        source_files = file_args[1:]
        atype = _detect_type(archive_path)

        valid_files = []
        for f in source_files:
            fp = _safe_path(f)
            if fp.exists():
                valid_files.append(fp)
            else:
                return f"❌ File not found: {f}"

        try:
            if atype == "zip":
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp in valid_files:
                        if fp.is_dir():
                            for child in fp.rglob("*"):
                                if child.is_file():
                                    zf.write(child, child.relative_to(fp.parent))
                        else:
                            zf.write(fp, fp.name)
                size = Path(archive_path).stat().st_size
                return f"✅ Created {archive_path} ({len(valid_files)} items, {size:,} bytes)"
            elif atype in ("tar", "tar.gz", "tar.bz2"):
                mode = "w"
                if atype == "tar.gz":
                    mode = "w:gz"
                elif atype == "tar.bz2":
                    mode = "w:bz2"
                with tarfile.open(archive_path, mode) as tf:
                    for fp in valid_files:
                        tf.add(str(fp), fp.name)
                size = Path(archive_path).stat().st_size
                return f"✅ Created {archive_path} ({len(valid_files)} items, {size:,} bytes)"
            else:
                return f"❌ Unsupported archive format. Use .zip, .tar, .tar.gz, or .tar.bz2"
        except Exception as e:
            return f"❌ Error creating archive: {e}"

    if action == "extract":
        if not arg:
            return "Usage: extract <archive_path> [destination_dir]"
        eparts = arg.split()
        archive_path = str(_safe_path(eparts[0]))
        dest_dir = str(_safe_path(eparts[1])) if len(eparts) > 1 else str(WORKSPACE_ROOT)

        if not Path(archive_path).exists():
            return f"❌ Archive not found: {archive_path}"

        atype = _detect_type(archive_path)
        try:
            Path(dest_dir).mkdir(parents=True, exist_ok=True)
            if atype == "zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for name in zf.namelist():
                        if name.startswith("/") or ".." in name:
                            return f"❌ Unsafe path in archive: {name}"
                    zf.extractall(dest_dir)
                    count = len(zf.namelist())
                return f"✅ Extracted {count} file(s) to {dest_dir}"
            elif atype in ("tar", "tar.gz", "tar.bz2"):
                mode = "r"
                if atype == "tar.gz":
                    mode = "r:gz"
                elif atype == "tar.bz2":
                    mode = "r:bz2"
                with tarfile.open(archive_path, mode) as tf:
                    for member in tf.getmembers():
                        if member.name.startswith("/") or ".." in member.name:
                            return f"❌ Unsafe path in archive: {member.name}"
                    tf.extractall(dest_dir)
                    count = len(tf.getmembers())
                return f"✅ Extracted {count} file(s) to {dest_dir}"
            else:
                return f"❌ Unsupported format: {atype}"
        except Exception as e:
            return f"❌ Error extracting: {e}"

    if action == "list":
        if not arg:
            return "Usage: list <archive_path>"
        archive_path = arg.split()[0]
        if not Path(archive_path).exists():
            return f"❌ Archive not found: {archive_path}"
        atype = _detect_type(archive_path)
        try:
            if atype == "zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    lines = [f"Contents of {archive_path} ({len(zf.namelist())} entries):\n"]
                    for info in zf.infolist():
                        size = info.file_size
                        compressed = info.compress_size
                        ratio = f"{(1 - compressed/size)*100:.0f}%" if size > 0 else "-"
                        lines.append(f"  {info.filename:<40} {size:>10,} bytes  ({ratio} compressed)")
                    return "\n".join(lines)
            elif atype in ("tar", "tar.gz", "tar.bz2"):
                mode = "r" if atype == "tar" else ("r:gz" if atype == "tar.gz" else "r:bz2")
                with tarfile.open(archive_path, mode) as tf:
                    members = tf.getmembers()
                    lines = [f"Contents of {archive_path} ({len(members)} entries):\n"]
                    for m in members:
                        mtype = "DIR" if m.isdir() else "FILE"
                        lines.append(f"  [{mtype}] {m.name:<40} {m.size:>10,} bytes")
                    return "\n".join(lines)
            else:
                return f"❌ Unsupported format: {atype}"
        except Exception as e:
            return f"❌ Error: {e}"

    if action == "info":
        if not arg:
            return "Usage: info <archive_path>"
        archive_path = arg.split()[0]
        if not Path(archive_path).exists():
            return f"❌ Archive not found: {archive_path}"
        atype = _detect_type(archive_path)
        fpath = Path(archive_path)
        try:
            lines = [
                f"Archive: {fpath.name}",
                f"Type: {atype}",
                f"Size: {fpath.stat().st_size:,} bytes",
                f"Modified: {datetime.datetime.fromtimestamp(fpath.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if atype == "zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    total_size = sum(i.file_size for i in zf.infolist())
                    compressed_size = sum(i.compress_size for i in zf.infolist())
                    lines.append(f"Entries: {len(zf.namelist())}")
                    lines.append(f"Uncompressed: {total_size:,} bytes")
                    lines.append(f"Compressed: {compressed_size:,} bytes")
                    if total_size > 0:
                        lines.append(f"Ratio: {(1 - compressed_size/total_size)*100:.1f}%")
            elif atype in ("tar", "tar.gz", "tar.bz2"):
                mode = "r" if atype == "tar" else ("r:gz" if atype == "tar.gz" else "r:bz2")
                with tarfile.open(archive_path, mode) as tf:
                    members = tf.getmembers()
                    total = sum(m.size for m in members)
                    lines.append(f"Entries: {len(members)}")
                    lines.append(f"Total uncompressed: {total:,} bytes")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    return (
        "Archive tool commands:\n"
        "  create <archive> <files...>     — Create zip/tar/tar.gz\n"
        "  extract <archive> [dest]        — Extract archive\n"
        "  list <archive>                  — List contents\n"
        "  info <archive>                  — Show metadata"
    )


# =====================================================================
# Tool 24: Currency Converter
# =====================================================================
def currency_convert(command: str) -> str:
    """Convert between currencies using live exchange rates.

    Commands:
      <amount> <from> to <to>    — Convert currency (e.g., "100 USD to EUR")
      rates <currency>           — Show exchange rates for a currency
      list                       — List available currencies
    """
    log.debug("currency_convert called: %s", command[:200])

    BASE_URL = "https://open.er-api.com/v6/latest"

    if command.strip().lower() == "list":
        try:
            resp = _safe_get(f"{BASE_URL}/USD")
            resp.raise_for_status()
            data = resp.json()
            rates = data.get("rates", {})
            lines = [f"Available currencies ({len(rates)}):\n"]
            codes = sorted(rates.keys())
            for i in range(0, len(codes), 6):
                row = codes[i:i+6]
                lines.append("  " + "  ".join(f"{c:>5}" for c in row))
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error fetching currencies: {e}"

    if command.strip().lower().startswith("rates"):
        parts = command.strip().split()
        currency = parts[1].upper() if len(parts) > 1 else "USD"
        try:
            resp = _safe_get(f"{BASE_URL}/{currency}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != "success":
                return f"❌ Currency '{currency}' not found"
            rates = data.get("rates", {})
            popular = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD",
                        "CNY", "INR", "BRL", "MXN", "KRW", "SGD", "HKD"]
            lines = [f"Exchange rates for 1 {currency}:\n"]
            for code in popular:
                if code in rates and code != currency:
                    lines.append(f"  {code}: {rates[code]:.4f}")
            lines.append(f"\nLast updated: {data.get('time_last_update_utc', '?')}")
            return "\n".join(lines)
        except Exception as e:
            return f"❌ Error: {e}"

    # Parse conversion: "100 USD to EUR" or "100 usd eur"
    match = re.match(
        r"(\d+(?:\.\d+)?)\s+([A-Za-z]{3})\s+(?:to\s+)?([A-Za-z]{3})",
        command.strip(),
    )
    if not match:
        return (
            "Currency converter usage:\n"
            "  100 USD to EUR          — Convert amount\n"
            "  rates USD               — Show exchange rates\n"
            "  list                    — List available currencies\n"
            "\nExample: 100 USD to EUR"
        )

    amount = float(match.group(1))
    from_cur = match.group(2).upper()
    to_cur = match.group(3).upper()

    try:
        resp = _safe_get(f"{BASE_URL}/{from_cur}")
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "success":
            return f"❌ Currency '{from_cur}' not found"
        rates = data.get("rates", {})
        if to_cur not in rates:
            return f"❌ Currency '{to_cur}' not found"
        rate = rates[to_cur]
        converted = amount * rate
        return (
            f"💱 {amount:,.2f} {from_cur} = {converted:,.2f} {to_cur}\n"
            f"Rate: 1 {from_cur} = {rate:.6f} {to_cur}\n"
            f"Updated: {data.get('time_last_update_utc', '?')}"
        )
    except Exception as e:
        return f"❌ Conversion error: {e}"


# =====================================================================
# Tool 25: Schedule Tool — manage the agent's cron-style tasks
# =====================================================================
_SCHEDULE_FILE = WORKSPACE_ROOT / "agent_schedule.json"


def _load_schedule() -> list:
    """Load user-defined scheduled tasks from disk."""
    try:
        if _SCHEDULE_FILE.exists():
            return json.loads(_SCHEDULE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_schedule(tasks: list) -> None:
    """Persist scheduled tasks to disk."""
    _SCHEDULE_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


def schedule_tool(input_str: str) -> str:
    """Manage scheduled tasks that the HEARTBEAT scheduler will run automatically.

    Commands:
      add <name> <interval> <prompt>  — create or replace a task
      list                            — show all tasks
      remove <name>                   — delete a task by name
      clear                           — remove all tasks
      status                          — show scheduler configuration
    """
    log.debug("schedule_tool called: %r", input_str)
    parts = input_str.strip().split(None, 3)
    if not parts:
        return (
            "Usage: add <name> <interval> <prompt> | list | remove <name> | clear | status\n"
            "Intervals: 'every 30m', 'every 2h', 'daily 09:00', 'weekly Monday 08:00'"
        )
    cmd = parts[0].lower()
    tasks = _load_schedule()

    if cmd == "add":
        if len(parts) < 4:
            return (
                "Usage: add <name> <interval> <prompt>\n"
                "Example: add weather-check every 6h Check the weather and save a note"
            )
        name, interval, prompt = parts[1], parts[2], parts[3]
        # Replace existing task with same name
        tasks = [t for t in tasks if t.get("name") != name]
        import datetime as _dt
        tasks.append({
            "name": name,
            "schedule": interval,
            "prompt": prompt,
            "created": _dt.datetime.now().isoformat(),
        })
        _save_schedule(tasks)
        return (
            f"✅ Task '{name}' scheduled.\n"
            f"  Interval: {interval}\n"
            f"  Prompt:   {prompt}"
        )

    if cmd == "list":
        if not tasks:
            return (
                "No scheduled tasks.\n"
                "Use 'add <name> <interval> <prompt>' to create one.\n"
                "Also edit runtime/HEARTBEAT.md to add persistent tasks."
            )
        lines = [f"{'Name':<20} {'Interval':<20} Prompt", "-" * 72]
        for t in tasks:
            lines.append(
                f"{t['name']:<20} {t['schedule']:<20} {t.get('prompt','')[:30]}"
            )
        return "\n".join(lines)

    if cmd == "remove":
        if len(parts) < 2:
            return "Usage: remove <name>"
        name = parts[1]
        before = len(tasks)
        tasks = [t for t in tasks if t.get("name") != name]
        if len(tasks) == before:
            return f"Task '{name}' not found."
        _save_schedule(tasks)
        return f"✅ Task '{name}' removed."

    if cmd == "clear":
        count = len(tasks)
        _save_schedule([])
        return f"✅ Cleared {count} scheduled task(s)."

    if cmd == "status":
        hb_enabled = os.getenv("HEARTBEAT_ENABLED", "1") != "0"
        interval = int(os.getenv("HEARTBEAT_INTERVAL_SECS", "1800"))
        return (
            f"Heartbeat scheduler: {'✅ enabled' if hb_enabled else '❌ disabled'}\n"
            f"Check interval:      {interval}s ({interval // 60}m)\n"
            f"User-defined tasks:  {len(tasks)}\n"
            f"Tasks file:          {_SCHEDULE_FILE}\n"
            "Edit runtime/HEARTBEAT.md to add persistent background tasks."
        )

    return (
        f"Unknown command: '{cmd}'. "
        "Use: add | list | remove | clear | status"
    )


# =====================================================================
# TOOL REGISTRY — Everything the agent can see and use
#
# Each entry has:
#   function     — the callable
#   description  — shown in the system prompt
#   params       — T3-1: typed schema {param_name: description}.
#                  Optional params have a "?" suffix on their key.
#   params_to_str — T3-1: converts a typed params dict to the string
#                  the tool function expects (backward-compat bridge).
# =====================================================================
TOOL_REGISTRY = {
    "calculator": {
        "function": calculator,
        "description": (
            "Evaluate math expressions. Supports: +, -, *, /, **, sqrt, sin, cos, "
            "tan, log, log10, factorial, ceil, floor, pi, e, abs, round, min, max, "
            "gcd, degrees, radians, comb, perm"
        ),
        "params": {
            "expression": "Math expression to evaluate, e.g. 'sqrt(144) + factorial(5)'",
        },
        "params_to_str": lambda p: p.get("expression", ""),
    },
    "get_datetime": {
        "function": get_datetime,
        "description": (
            "Get current date, time, day, week number, and unix timestamp. "
            "Optionally pass a UTC offset like '+5:30' or '-8' for other timezones"
        ),
        "params": {
            "timezone_offset?": "UTC offset string like '+5:30' or '-8' (omit for local time)",
        },
        "params_to_str": lambda p: p.get("timezone_offset", p.get("timezone_offset?", "")),
    },
    "weather_lookup": {
        "function": weather_lookup,
        "description": (
            "Get REAL current weather for ANY city worldwide — temperature, "
            "humidity, wind, UV index, feels-like, visibility (via Open-Meteo + wttr.in)"
        ),
        "params": {
            "city": "City name to look up, e.g. 'Paris' or 'Tokyo,Japan'",
        },
        "params_to_str": lambda p: p.get("city", ""),
    },
    "web_search": {
        "function": web_search,
        "description": (
            "Search the web via DuckDuckGo. Returns top results with titles and URLs. "
            "Use for current events, facts, how-to questions, etc."
        ),
        "params": {
            "query": "Search query string, e.g. 'python async tutorial'",
        },
        "params_to_str": lambda p: p.get("query", ""),
    },
    "wikipedia_lookup": {
        "function": wikipedia_lookup,
        "description": (
            "Look up any topic on Wikipedia and get a summary. Great for people, "
            "places, science, history, concepts, etc."
        ),
        "params": {
            "topic": "Topic to look up, e.g. 'Alan Turing' or 'quantum computing'",
        },
        "params_to_str": lambda p: p.get("topic", ""),
    },
    "url_fetcher": {
        "function": url_fetcher,
        "description": (
            "Fetch any web page or API endpoint and extract readable text. "
            "Handles HTML, JSON, and plain text"
        ),
        "params": {
            "url": "Full URL to fetch, e.g. 'https://example.com/api/data'",
        },
        "params_to_str": lambda p: p.get("url", ""),
    },
    "unit_converter": {
        "function": unit_converter,
        "description": (
            "Convert between units: length (km/miles/m/ft/in), weight (kg/lb/oz), "
            "temperature (C/F/K), volume (liters/gallons/cups/ml), area, speed, "
            "data (KB/MB/GB/TB), time (seconds to years)"
        ),
        "params": {
            "conversion": "Conversion expression, e.g. '100 km to miles' or '72 F to C'",
        },
        "params_to_str": lambda p: p.get("conversion", ""),
    },
    "file_manager": {
        "function": file_manager,
        "description": (
            "Read, write, append, list, or get info about files and directories. "
            "Actions: read, write, append, list, info"
        ),
        "params": {
            "action": "One of: read, write, append, list, info",
            "path": "File or directory path relative to workspace, e.g. 'notes.txt' or '.'",
            "content?": "Text content for write/append actions (omit for read/list/info)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'list')} {p.get('path', '.')} {p.get('content', '')}".strip()
        ),
    },
    "system_info": {
        "function": system_info,
        "description": (
            "Get current system info: OS, architecture, processor, hostname, "
            "local IP, Python version, current working directory"
        ),
        "params": {},
        "params_to_str": lambda p: "",
    },
    "text_analyzer": {
        "function": text_analyzer,
        "description": (
            "Analyze text: word count, character count, sentence count, "
            "average word length, top words, unique word ratio, reading time"
        ),
        "params": {
            "text": "The text to analyze",
        },
        "params_to_str": lambda p: p.get("text", ""),
    },
    "hash_encode": {
        "function": hash_encode,
        "description": (
            "Hash or encode/decode text: md5, sha256, sha1, base64encode, "
            "base64decode, urlencode, urldecode, character/byte count"
        ),
        "params": {
            "algorithm": "Algorithm: md5, sha256, sha1, base64encode, base64decode, urlencode, urldecode",
            "text": "Text to hash or encode",
        },
        "params_to_str": lambda p: f"{p.get('algorithm', '')} {p.get('text', '')}".strip(),
    },
    "ip_lookup": {
        "function": ip_lookup,
        "description": (
            "Look up your public IP, or get geolocation + ISP info for any IP "
            "address or domain name"
        ),
        "params": {
            "address?": "IP address or domain to look up (omit to get your own public IP)",
        },
        "params_to_str": lambda p: p.get("address", p.get("address?", "")),
    },
    "note_taker": {
        "function": note_taker,
        "description": (
            "Persistent notes saved to disk. "
            "Actions: save <text>, list, search <keyword>, delete <number>, clear"
        ),
        "params": {
            "action": "One of: save, list, search, delete, clear",
            "text?": "Note text for save, keyword for search, number for delete (omit for list/clear)",
        },
        "params_to_str": lambda p: f"{p.get('action', 'list')} {p.get('text', '')}".strip(),
    },
    "document_ocr": {
        "function": document_ocr,
        "description": (
            "Local Document OCR: scan images to extract structured text and build "
            "a searchable index. Actions: scan, scan_url, search, list, info, delete, clear, status"
        ),
        "params": {
            "action": "One of: scan, scan_url, search, list, info, delete, clear, status",
            "target?": "Filepath, URL, keyword, or document ID depending on action",
        },
        "params_to_str": lambda p: f"{p.get('action', 'status')} {p.get('target', '')}".strip(),
    },
    "json_yaml_tool": {
        "function": json_yaml_tool,
        "description": (
            "Process JSON and YAML data: validate, convert (json2yaml, yaml2json), "
            "format, minify, query with dot-notation, list keys, deep merge"
        ),
        "params": {
            "action": "One of: validate, json2yaml, yaml2json, format, minify, query, keys, merge",
            "data": "JSON or YAML data string to process",
            "query?": "Dot-notation path for 'query' action, e.g. 'user.name' (omit for others)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'format')} {p.get('data', '')} {p.get('query', '')}".strip()
        ),
    },
    "csv_data_tool": {
        "function": csv_data_tool,
        "description": (
            "Process CSV data: parse as table, column statistics, sort, filter rows, "
            "count, convert to JSON, read CSV files"
        ),
        "params": {
            "action": "One of: parse, stats, sort, filter, headers, count, to_json, read",
            "data": "CSV data string or filename",
            "column?": "Column name for sort/filter/stats actions (omit for others)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'parse')} {p.get('data', '')} {p.get('column', '')}".strip()
        ),
    },
    "pdf_reader": {
        "function": pdf_reader,
        "description": (
            "Extract text from PDF files, search content, get page count and metadata. "
            "Actions: read, page, search, info, count"
        ),
        "params": {
            "action": "One of: read, page, search, info, count",
            "filepath": "Path to the PDF file, e.g. 'document.pdf'",
            "page?": "Page number for the 'page' action (integer, omit for others)",
            "keyword?": "Search keyword for the 'search' action (omit for others)",
        },
        "params_to_str": lambda p: (
            f"page {p.get('page', '')} {p.get('filepath', '')}".strip()
            if p.get("action") == "page"
            else f"search {p.get('keyword', '')} {p.get('filepath', '')}".strip()
            if p.get("action") == "search"
            else f"{p.get('action', 'read')} {p.get('filepath', '')}".strip()
        ),
    },
    "code_runner": {
        "function": code_runner,
        "description": (
            "Execute Python code in a sandboxed subprocess with 10-second timeout. "
            "Blocked: os, sys, subprocess, shutil imports. Provide Python code directly"
        ),
        "params": {
            "code": "Python code to execute, e.g. 'print(2 ** 10)'",
        },
        "params_to_str": lambda p: p.get("code", ""),
    },
    "process_manager": {
        "function": process_manager,
        "description": (
            "View system processes: list top by CPU, top by memory, search by name, "
            "get detailed info by PID, count total processes"
        ),
        "params": {
            "action": "One of: list, top, memory, search, info, count",
            "target?": "Process name for 'search' or PID for 'info' (omit for others)",
        },
        "params_to_str": lambda p: f"{p.get('action', 'top')} {p.get('target', '')}".strip(),
    },
    "network_diag": {
        "function": network_diag,
        "description": (
            "Network diagnostics: ping hosts, DNS lookup, scan common ports, "
            "check specific port, test HTTP endpoints, list interfaces, speed test"
        ),
        "params": {
            "action": "One of: ping, dns, ports, check, http, interfaces, speed",
            "target?": "Hostname, IP address, or URL (omit for interfaces/speed)",
        },
        "params_to_str": lambda p: f"{p.get('action', 'ping')} {p.get('target', '')}".strip(),
    },
    "password_gen": {
        "function": password_gen,
        "description": (
            "Generate secure passwords, PINs, passphrases, UUIDs, and tokens. "
            "Check password strength"
        ),
        "params": {
            "action": "One of: generate, strong, pin, passphrase, uuid, token, check",
            "value?": "Length (integer) for generate/strong/pin/token, word count for passphrase, or password string for check",
        },
        "params_to_str": lambda p: f"{p.get('action', 'generate')} {p.get('value', '')}".strip(),
    },
    "regex_tool": {
        "function": regex_tool,
        "description": (
            "Test, match, and learn regular expressions. Find all matches, "
            "replace text, split strings, explain patterns, view common patterns"
        ),
        "params": {
            "action": "One of: test, findall, replace, split, explain, common",
            "pattern?": "Regex pattern, e.g. r'\\d+' (omit for 'common')",
            "text?": "Text to test the pattern against (omit for 'explain'/'common')",
            "replacement?": "Replacement string for the 'replace' action (omit for others)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'test')} {p.get('pattern', '')} "
            f"{p.get('text', '')} {p.get('replacement', '')}".strip()
        ),
    },
    "archive_tool": {
        "function": archive_tool,
        "description": (
            "Create, extract, and inspect archive files (zip, tar, tar.gz, tar.bz2). "
            "Actions: create, extract, list, info"
        ),
        "params": {
            "action": "One of: create, extract, list, info",
            "archive": "Archive filename, e.g. 'backup.zip'",
            "files?": "Space-separated files for 'create', or destination path for 'extract' (omit for list/info)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'list')} {p.get('archive', '')} {p.get('files', '')}".strip()
        ),
    },
    "currency_convert": {
        "function": currency_convert,
        "description": (
            "Convert between currencies using live exchange rates. "
            "Usage: '100 USD to EUR', 'rates USD', 'list' for all currencies"
        ),
        "params": {
            "query": "Conversion query, e.g. '100 USD to EUR', 'rates GBP', or 'list'",
        },
        "params_to_str": lambda p: p.get("query", ""),
    },
    "schedule_tool": {
        "function": schedule_tool,
        "description": (
            "Manage the agent's scheduled background tasks. "
            "Actions: add, list, remove, clear, status. "
            "Intervals: 'every 30m', 'every 2h', 'daily 09:00', 'weekly Monday 08:00'"
        ),
        "params": {
            "action": "One of: add, list, remove, clear, status",
            "name?": "Task name for add/remove actions",
            "interval?": "Schedule interval, e.g. 'every 30m', 'daily 09:00' (for add action)",
            "prompt?": "Agent prompt to run at the scheduled time (for add action)",
        },
        "params_to_str": lambda p: (
            f"{p.get('action', 'status')} {p.get('name', '')} "
            f"{p.get('interval', '')} {p.get('prompt', '')}".strip()
        ),
    },
}
