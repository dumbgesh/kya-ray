"""
desktop/ui/styles.py - Visual styles, color palettes, and QSS stylesheets for PySide6 UI.

Reference design:
- Outer floating window: Light grey (#F0F1F4) with rounded corners (16px).
- Inner content card: Pure white (#FFFFFF) with subtle grey border (#E2E4E9) and rounded corners (12px).
- Header: 'Kya-Ray' title, blue intent pill badge, minimize and close controls, followed by a thin divider.
- Central response area: Clean markdown typography without source-text preview card.
- Footer: Thin divider, 'Ready when you are.' status on left, copy & resize buttons on right.
"""

PALETTE = {
    # Outer container
    "outer_bg": "#F0F1F4",
    "outer_border": "#E1E4EA",

    # Inner card
    "bg_main": "#FFFFFF",
    "inner_bg": "#FFFFFF",
    "inner_border": "#E2E4E9",
    "border": "#E2E4E9",
    "border_light": "#F0F1F4",
    "divider": "#F0F1F4",

    # Cards and surfaces
    "bg_card": "#F8F9FA",
    "bg_card_hover": "#F1F3F4",

    # Core brand colors
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_active": "#1E40AF",

    # Text hierarchy
    "text_primary": "#1F242F",       # Window title and major headers
    "text_body": "#374151",          # Response body text
    "text_secondary": "#5F6368",     # Sub-labels
    "text_muted": "#8C93A0",         # Footer status ("Ready when you are.")

    # Status & alerts
    "error": "#D93025",
    "error_bg": "#FCE8E6",
    "success": "#10B981",
    "success_bg": "#E6F4EA",

    # Intent Pill Badge
    "pill_bg": "#EBF2FF",
    "pill_fg": "#2563EB",
    "pill_border": "#D2E3FC",
    "pill_active_bg": "#2563EB",
    "pill_active_fg": "#FFFFFF",

    # Action / Icon buttons (copy, resize)
    "btn_bg": "#F3F4F6",
    "btn_border": "#E5E7EB",
    "btn_hover": "#E5E7EB",
    "btn_active": "#D1D5DB",

    # Scrollbar
    "scrollbar_track": "transparent",
    "scrollbar_thumb": "#D1D5DB",
    "scrollbar_thumb_hover": "#9CA3AF",
}

LIGHT_THEME_QSS = f"""
QWidget {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: {PALETTE["text_body"]};
}}

/* Outer Window Frame */
QFrame#containerFrame, QFrame#outerContainer {{
    background-color: {PALETTE["outer_bg"]};
    border: 1px solid {PALETTE["outer_border"]};
    border-radius: 16px;
}}

/* Inner Content Card */
QFrame#innerCard {{
    background-color: {PALETTE["inner_bg"]};
    border: 1px solid {PALETTE["inner_border"]};
    border-radius: 12px;
}}

/* Header Bar */
QFrame#headerBar {{
    background-color: transparent;
    border: none;
    padding: 0px;
}}

QLabel#titleLabel {{
    font-size: 16px;
    font-weight: 700;
    color: {PALETTE["text_primary"]};
    letter-spacing: 0.2px;
}}

/* Intent Badge */
QLabel#intentBadge {{
    background-color: {PALETTE["pill_bg"]};
    color: {PALETTE["pill_fg"]};
    border: 1px solid {PALETTE["pill_border"]};
    border-radius: 11px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 700;
}}

/* Header Controls (Minimize & Close) */
QPushButton#minimizeButton, QPushButton#closeButton {{
    background-color: transparent;
    color: #6B7280;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    font-weight: normal;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
}}

QPushButton#minimizeButton:hover, QPushButton#closeButton:hover {{
    background-color: {PALETTE["btn_bg"]};
    color: {PALETTE["text_primary"]};
}}

QPushButton#minimizeButton:pressed, QPushButton#closeButton:pressed {{
    background-color: {PALETTE["btn_hover"]};
}}

/* Horizontal Dividers */
QFrame#divider {{
    background-color: {PALETTE["divider"]};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* Central Response Browser */
QTextBrowser#responseBrowser {{
    background-color: transparent;
    border: none;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13.5px;
    line-height: 1.55;
    color: {PALETTE["text_body"]};
    padding: 2px 0px;
    selection-background-color: {PALETTE["pill_bg"]};
    selection-color: {PALETTE["pill_fg"]};
}}

/* Source Text Card (Legacy support) */
QFrame#sourceCard {{
    background-color: {PALETTE["bg_card"]};
    border: 1px solid {PALETTE["border"]};
    border-radius: 6px;
    padding: 6px 10px;
}}

QLabel#sourcePrefix {{
    font-size: 10px;
    font-weight: 700;
    color: {PALETTE["text_muted"]};
}}

QLabel#sourceSnippet {{
    font-size: 12px;
    color: {PALETTE["text_secondary"]};
}}

/* Footer Bar */
QFrame#footerBar {{
    background-color: transparent;
    border: none;
    padding: 0px;
}}

QLabel#statusLabel, QLabel#hintLabel {{
    font-size: 12px;
    font-weight: 400;
    color: {PALETTE["text_muted"]};
}}

/* Control Buttons (Copy & Grip Handle) */
QPushButton#actionButton, QPushButton#copyButton, QWidget#gripHandle {{
    background-color: {PALETTE["btn_bg"]};
    border: 1px solid {PALETTE["btn_border"]};
    border-radius: 8px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0px;
}}

QPushButton#actionButton:hover, QPushButton#copyButton:hover, QWidget#gripHandle:hover {{
    background-color: {PALETTE["btn_hover"]};
    border-color: #D1D5DB;
}}

QPushButton#actionButton:pressed, QPushButton#copyButton:pressed {{
    background-color: {PALETTE["btn_active"]};
}}

QPushButton#actionButton[copied="true"], QPushButton#copyButton[copied="true"] {{
    background-color: {PALETTE["success_bg"]};
    border-color: #A7F3D0;
}}

/* Smooth Scrollbars */
QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {PALETTE["scrollbar_thumb"]};
    min-height: 24px;
    border-radius: 3px;
}}

QScrollBar::handle:vertical:hover {{
    background: {PALETTE["scrollbar_thumb_hover"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
    height: 0px;
}}
"""
