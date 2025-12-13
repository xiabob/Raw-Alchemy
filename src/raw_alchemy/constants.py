# -*- coding: utf-8 -*-
"""
Shared constants and mappings for the Raw Alchemy application.
"""

# ==========================================
#              COLOR & LOG MAPPINGS
# ==========================================

# Maps user-facing Log space names to their corresponding linear color gamuts
# that are recognized by the 'colour-science' library.
LOG_TO_WORKING_SPACE = {
    'F-Log': 'F-Gamut',
    'F-Log2': 'F-Gamut',
    'F-Log2C': 'F-Gamut C',
    'V-Log': 'V-Gamut',
    'N-Log': 'N-Gamut',
    'L-Log': 'ITU-R BT.2020',
    'Canon Log 2': 'Cinema Gamut',
    'Canon Log 3': 'Cinema Gamut',
    'S-Log3': 'S-Gamut3',
    'S-Log3.Cine': 'S-Gamut3.Cine',
    'Arri LogC3': 'ARRI Wide Gamut 3',
    'Arri LogC4': 'ARRI Wide Gamut 4',
    'Log3G10': 'REDWideGamutRGB',
}

# Maps composite or non-standard Log names to the actual function name
# used in the 'colour-science' library's registries.
LOG_ENCODING_MAP = {
    'S-Log3.Cine': 'S-Log3',
    'F-Log2C': 'F-Log2',
}

# ==========================================
#              PROCESSING SETTINGS
# ==========================================

# Available auto-exposure metering modes.
METERING_MODES = [
    'average',        # Geometric mean (default)
    'center-weighted',# Center-weighted average
    'highlight-safe', # Highlight protection (ETTR)
    'hybrid',         # Hybrid (average + highlight limiting)
    'matrix',         # Matrix / Evaluative metering
]