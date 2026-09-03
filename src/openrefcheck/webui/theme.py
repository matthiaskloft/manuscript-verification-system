"""Color tokens shared by the web GUI screens — same palette as the former PySide6 app."""

from __future__ import annotations

BG = "#dcdad5"
PANEL_BG = "#f3f2ef"
SIDEBAR_BG = "#e7e5e0"
CONTENT_BG = "#f3f2ef"
BORDER = "#c6c3bc"
BORDER_SOFT = "#e4e1db"
DASHED_BORDER = "#b8b5ad"
DROPZONE_BG = "#fbfaf8"

TEXT = "#26241f"
TEXT_STRONG = "#3d3b35"
TEXT_MUTED = "#5c594f"
TEXT_FAINT = "#8a877f"
TEXT_QUIET = "#a5a29a"

ACCENT = "#3f6ba8"
ACCENT_HOVER = "#4c7bb5"
ACCENT_BORDER = "#33578a"

BLOCKER_BG = "#fbe3d8"
BLOCKER_BORDER = "#c9532e"
BLOCKER_FG = "#8c2f10"

STATUS = {
    "verified": {"bg": "#e8f0e6", "border": "#a8c39c", "fg": "#3c5c33", "dot": "#5d8a4c"},
    "review": {"bg": "#fbf1dd", "border": "#dcbb78", "fg": "#7a5a12", "dot": "#c99526"},
    "halluc": {"bg": "#fbeae5", "border": "#d6a294", "fg": "#8c2f1c", "dot": "#bf4a2e"},
    "dup": {"bg": "#eeece7", "border": "#c6c3bc", "fg": "#5c594f", "dot": "#98958d"},
    "unchecked": {"bg": "#eceff3", "border": "#b6bfcb", "fg": "#3f5570", "dot": "#7d93ac"},
}

# Not a member of STATUS above, deliberately: a retracted work is normally *verified*
# too — verification is what found the retraction — so this is worn alongside a status
# badge rather than instead of one. Darker and more saturated than any of them, because
# it is the only marking on this screen that means "do not cite this".
RETRACTED_PALETTE = {"bg": "#f6d9d0", "border": "#a8391a", "fg": "#7a2410", "dot": "#a8391a"}

MODE_PALETTE = {
    "local": {"bg": "#eef4ec", "border": "#a8c39c", "fg": "#3c5c33", "dot": "#5d8a4c"},
    "demo": {"bg": "#fdf6e8", "border": "#dcbb78", "fg": "#7a5a12", "dot": "#c99526"},
    "prod": {"bg": "#eef1f5", "border": "#b6bfcb", "fg": "#3f5570", "dot": "#7d93ac"},
}

FONT_FAMILY = "'Segoe UI', system-ui, sans-serif"
MONO_FAMILY = "Consolas, monospace"

PRIMARY_BUTTON = (
    f"background:linear-gradient(180deg,{ACCENT_HOVER},{ACCENT}); color:#fff; "
    f"border:1px solid {ACCENT_BORDER}; border-radius:4px; font-weight:600;"
)
PRIMARY_BUTTON_DISABLED = "background:#eceae5; color:#a5a29a; border:1px solid #cdcac3; border-radius:4px; font-weight:600;"
SECONDARY_BUTTON = (
    "background:linear-gradient(180deg,#fdfdfc,#eeece7); color:" + TEXT + "; "
    "border:1px solid #a9a69e; border-radius:4px;"
)

GLOBAL_CSS = f"""
html, body {{ margin:0; height:100%; }}
body {{ background:{BG}; font-family:{FONT_FAMILY}; color:{TEXT}; }}
.nicegui-content {{ padding:0; height:100vh; }}
.rc-mono {{ font-family:{MONO_FAMILY}; }}
.rc-sidebar {{ background:{SIDEBAR_BG}; border-right:1px solid {BORDER}; }}
.rc-content {{ background:{CONTENT_BG}; }}
.rc-panel {{ background:#fff; border:1px solid #cdcac3; border-radius:6px; }}
.rc-compact-number.q-field {{ width:64px; }}
.rc-compact-number .q-field__control,
.rc-compact-number .q-field__marginal {{ height:30px; min-height:30px; }}
.rc-compact-number .q-field__native {{ min-height:30px; padding-top:0; padding-bottom:0; }}
.rc-navbtn {{ text-align:left; border:none; border-left:3px solid transparent; background:transparent;
  color:{TEXT_MUTED}; font-weight:400; font-size:13px; padding:9px 14px; cursor:pointer; width:100%; }}
.rc-navbtn .q-btn__content {{ width:100%; justify-content:flex-start; text-align:left; }}
.rc-navbtn:hover {{ background:{PANEL_BG}; }}
.rc-navbtn.active {{ border-left:3px solid {ACCENT}; background:{PANEL_BG}; color:{TEXT}; font-weight:600; }}
.rc-badge {{ display:inline-flex; align-items:center; gap:4px; padding:2px 6px; border-radius:3px; font-size:10.5px; font-weight:500; }}
.rc-dot {{ width:6px; height:6px; border-radius:3px; display:inline-block; }}
.rc-dropzone {{ border:2px dashed {DASHED_BORDER}; border-radius:6px; background:{DROPZONE_BG}; }}
.rc-scroll::-webkit-scrollbar {{ width:11px; height:11px; }}
.rc-scroll::-webkit-scrollbar-thumb {{ background:{BORDER}; border-radius:4px; }}
.rc-upload.q-uploader {{ box-shadow:none; max-height:none; background:{DROPZONE_BG}; }}
.rc-upload .q-uploader__header {{ background:transparent; color:inherit; box-shadow:none; width:100%; height:100%; padding:0; cursor:pointer; }}
.rc-upload .q-uploader__header-content {{ padding:0; width:100%; height:100%; }}
.rc-upload .q-uploader__header-content > div {{ width:100%; height:100%; }}
.rc-upload .q-uploader__header .flex.flex-center {{ position:relative; width:100%; height:100%; align-items:center; justify-content:center; }}
.rc-upload .q-uploader__header .q-btn {{ position:absolute; inset:0; width:100%; height:100%; opacity:0; border-radius:0; }}
.rc-upload .q-uploader__header .col.column.justify-center {{ pointer-events:none; text-align:center; flex:none; width:auto; height:auto; }}
.rc-upload .q-uploader__title {{ font-size:13px; font-weight:600; color:{TEXT_STRONG}; }}
.rc-upload .q-uploader__title::after {{
  content:"or click anywhere to browse \\00b7  PDF · DOCX"; display:block; margin-top:6px;
  font-family:{MONO_FAMILY}; font-size:11px; font-weight:400; color:{TEXT_FAINT};
}}
.rc-upload .q-uploader__subtitle {{ display:none; }}
.rc-upload .q-uploader__list {{ display:none; }}
.rc-upload .q-uploader__dnd {{ border-radius:6px; }}
"""


def status_badge_html(text: str, palette: dict, extra_style: str = "") -> str:
    return (
        f'<span class="rc-badge" style="background:{palette["bg"]}; border:1px solid {palette["border"]}; '
        f'color:{palette["fg"]}; {extra_style}">'
        f'<span class="rc-dot" style="background:{palette["dot"]}"></span>{text}</span>'
    )
