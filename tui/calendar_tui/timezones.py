DEFAULT_TIMEZONE = "America/Sao_Paulo"

# Curated, not exhaustive — every event created or edited through this app
# uses one standard timezone (set once, not per-event), so this is the list
# offered when picking it. Brazilian and US timezones first, then a spread of
# other commonly-used ones. Real IANA/Olson identifiers, same format Google
# Calendar's API itself expects for a timeZone value.
COMMON_TIMEZONES = [
    # Brazil
    "America/Sao_Paulo",
    "America/Manaus",
    "America/Rio_Branco",
    "America/Belem",
    "America/Fortaleza",
    "America/Recife",
    "America/Bahia",
    # United States
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    # Rest of world (common)
    "UTC",
    "America/Mexico_City",
    "America/Bogota",
    "America/Argentina/Buenos_Aires",
    "America/Santiago",
    "Europe/London",
    "Europe/Lisbon",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Moscow",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Singapore",
    "Australia/Sydney",
    "Pacific/Auckland",
]
