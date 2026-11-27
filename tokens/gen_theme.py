#!/usr/bin/env python3
"""Generate OS theme files from tokens.json.

Usage: gen_theme.py <tokens.json> <output-dir> [<Kvantum themes folder>]

Writes, for every realm x {Light, Dark}:
  color-schemes/Huginn<Realm><Mode>.colors   KDE colour scheme (KDE and Qt apps' colours)
  gtk/Huginn<Realm><Mode>.css                named colours for libadwaita (GTK 4)
  gtk/Huginn<Realm><Mode>-gtk3.css           the colours of Huginn's own GTK 3 theme (/usr/share/themes/Huginn)
  kvantum/Huginn<Realm><Mode>/               a Kvantum widget style for Qt apps (when the Kvantum themes folder is
                                             given: KvAdapta's drawing, recoloured with the realm and the mode)
and once:
  qml/Tokens.qml                             singleton for the shell's QML (panel, dock, control centre)
The shell puts the realm's set in place for each user when the realm or dark changes (apps/huginn_look.py).
"""
import colorsys
import json
import re
import sys
from pathlib import Path


def rgb(value: str, over: str = "#FFFFFF") -> tuple[int, int, int]:
    """'#RRGGBB' or 'rgba(r,g,b,a)' -> opaque (r, g, b); rgba is flattened onto `over`."""
    value = value.strip()
    if value.startswith("#"):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    m = re.fullmatch(r"rgba\(([^)]+)\)", value)
    if not m:
        raise ValueError(f"unsupported colour: {value}")
    r, g, b, a = (float(x) for x in m.group(1).split(","))
    base = rgb(over)
    return tuple(round(c * a + bc * (1 - a)) for c, bc in zip((r, g, b), base))


def kde(value: str, over: str = "#FFFFFF") -> str:
    return ",".join(str(c) for c in rgb(value, over))


def hexa(value: str, over: str = "#FFFFFF") -> str:
    return "#%02X%02X%02X" % rgb(value, over)


def mix(a: str, b: str, t: float) -> str:
    ca, cb = rgb(a), rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def luminance(value: str) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def color_scheme(name: str, base: dict, tones: dict, danger: str) -> str:
    accent = tones["accent"]
    on_accent = "#0B1512" if luminance(accent) > 0.35 else "#FFFFFF"
    win, view = base["window"], base["view"]
    hover = hexa(base["hover"], win)

    def group(bg, alt, fg=base["text"]):
        return "\n".join([
            f"BackgroundAlternate={kde(alt)}", f"BackgroundNormal={kde(bg)}",
            f"DecorationFocus={kde(accent)}", f"DecorationHover={kde(accent)}",
            f"ForegroundActive={kde(accent)}", f"ForegroundInactive={kde(base['text_secondary'])}",
            f"ForegroundLink={kde(accent)}", f"ForegroundNegative={kde(danger)}",
            f"ForegroundNeutral={kde(base['text_secondary'])}", f"ForegroundNormal={kde(fg)}",
            f"ForegroundPositive={kde(accent)}", f"ForegroundVisited={kde(mix(accent, base['text_secondary'], 0.5))}",
        ])

    sections = {
        "ColorEffects:Disabled": "Color=56,56,56\nColorAmount=0\nColorEffect=0\nContrastAmount=0.65\nContrastEffect=1\nIntensityAmount=0.1\nIntensityEffect=2",
        "ColorEffects:Inactive": "ChangeSelectionColor=true\nColor=112,111,110\nColorAmount=0.025\nColorEffect=2\nContrastAmount=0.1\nContrastEffect=2\nEnable=false\nIntensityAmount=0\nIntensityEffect=0",
        "Colors:Button": group(hexa(base["capsule"], win), hover),
        "Colors:Complementary": group(tones["tint_b"], tones["tint_a"]),
        "Colors:Header": group(tones["tint_b"], tones["tint_a"]),
        "Colors:Header][Inactive": group(win, win),
        "Colors:Selection": group(accent, mix(accent, win, 0.25), on_accent)
            .replace(f"ForegroundActive={kde(accent)}", f"ForegroundActive={kde(on_accent)}")
            .replace(f"ForegroundLink={kde(accent)}", f"ForegroundLink={kde(on_accent)}")
            .replace(f"ForegroundInactive={kde(base['text_secondary'])}", f"ForegroundInactive={kde(on_accent)}"),
        "Colors:Tooltip": group(base["tooltip_bg"], base["menu_bg"]),
        "Colors:View": group(view, mix(view, win, 0.5)),
        "Colors:Window": group(win, base["menu_bg"]),
        "General": f"ColorScheme={name}\nName={name}\nshadeSortColumn=true\nAccentColor={kde(accent)}",
        "KDE": "contrast=4",
        "WM": "\n".join([
            f"activeBackground={kde(tones['tint_b'])}", f"activeBlend={kde(tones['tint_a'])}",
            f"activeForeground={kde(base['text'])}", f"inactiveBackground={kde(win)}",
            f"inactiveBlend={kde(win)}", f"inactiveForeground={kde(base['text_secondary'])}",
        ]),
    }
    return "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items()) + "\n"


def gtk_css(base: dict, tones: dict, danger: str, radius: dict) -> str:
    accent = tones["accent"]
    on_accent = "#0B1512" if luminance(accent) > 0.35 else "#FFFFFF"
    win = base["window"]
    pairs = {
        "accent_color": accent, "accent_bg_color": accent, "accent_fg_color": on_accent,
        "destructive_color": danger, "destructive_bg_color": danger, "destructive_fg_color": "#FFFFFF",
        "window_bg_color": win, "window_fg_color": base["text"],
        "view_bg_color": base["view"], "view_fg_color": base["text"],
        "headerbar_bg_color": tones["tint_b"], "headerbar_fg_color": base["text"],
        "headerbar_backdrop_color": win, "headerbar_border_color": hexa(base["separator"]),
        "sidebar_bg_color": tones["tint_a"], "sidebar_fg_color": base["text"],
        "card_bg_color": hexa(base["capsule"], win), "card_fg_color": base["text"],
        "popover_bg_color": base["menu_bg"], "popover_fg_color": base["text"],
        "dialog_bg_color": base["menu_bg"], "dialog_fg_color": base["text"],
        # GTK 3 names
        "theme_bg_color": win, "theme_fg_color": base["text"], "theme_base_color": base["view"],
        "theme_text_color": base["text"], "theme_selected_bg_color": accent,
        "theme_selected_fg_color": on_accent, "borders": hexa(base["menu_border"]),
    }
    lines = [f"@define-color {k} {v};" for k, v in pairs.items()]
    lines += [
        "", f"button, entry, spinbutton, combobox > box {{ border-radius: {radius['control']}px; }}",
        f"popover > contents, menu, .card {{ border-radius: {radius['card']}px; }}",
        f"window.csd, window.csd decoration {{ border-radius: {radius['window']}px; }}",
    ]
    return "\n".join(lines) + "\n"


def rgba_css(value: str, alpha: float) -> str:
    r, g, b = rgb(value)
    return f"rgba({r}, {g}, {b}, {alpha})"


def gtk3_css(base: dict, tones: dict, danger: str, dark: bool) -> str:
    """The colours Huginn's GTK 3 theme (/usr/share/themes/Huginn: Adwaita's shapes) draws with; huginn_look.py puts
    the realm's and mode's into ~/.config/gtk-3.0/colors.css, which comes after the theme's own and so wins."""
    accent = tones["accent"]
    on_accent = "#0B1512" if luminance(accent) > 0.35 else "#FFFFFF"
    win = base["window"]
    c = {"window": win, "view": base["view"], "text": base["text"], "soft": base["text_secondary"],
         "header": tones["tint_b"], "sidebar": tones["tint_a"], "card": hexa(base["capsule"], win),
         "border": hexa(base["menu_border"], win), "menu": hexa(base["menu_bg"], win), "tooltip": hexa(base["tooltip_bg"], win),
         "accent": accent, "on_accent": on_accent, "danger": danger}
    lines = ["/* Huginn's colours for its GTK 3 theme (generated by tokens/gen_theme.py). */"]
    lines += [f"@define-color huginn_{k} {v};" for k, v in c.items()]
    return "\n".join(lines) + "\n"


# Kvantum: KvAdapta's drawing (flat, gently rounded), every colour in it moved onto Huginn's: the greys onto the
# mode's surfaces (keeping how much lighter or darker each was than KvAdapta's window colour), the cyans and teals
# onto the realm's accent, the reds onto Huginn's danger colour.
def _hls(hexv: str) -> tuple:
    r, g, b = rgb(hexv)
    return colorsys.rgb_to_hls(r / 255, g / 255, b / 255)


def _hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def recolour(colour: str, src_window: str, src_accent: str, window: str, accent: str, danger: str) -> str:
    h, l, s = _hls(colour)
    if s > 0.35 and l > 0.15:
        hue = h * 360
        if 160 <= hue <= 210 or 260 <= hue <= 300:                    # KvAdapta's cyans, teals (and its purple)
            ah, al, as_ = _hls(accent)
            sh, sl, _ = _hls(src_accent)
            return _hex(ah, al + (l - sl), as_)
        if hue < 20 or hue > 340:
            dh, dl, ds = _hls(danger)
            return _hex(dh, dl, ds)
        return colour
    wh, wl, ws = _hls(window)
    _, swl, _ = _hls(src_window)
    return _hex(wh, wl + (l - swl), ws)


def kvantum(name: str, base: dict, tones: dict, danger: str, dark: bool, src: Path, out: Path) -> None:
    kind = "KvAdaptaDark" if dark else "KvAdapta"
    svg = (src / kind / f"{kind}.svg").read_text(encoding="utf-8")
    cfg = (src / kind / f"{kind}.kvconfig").read_text(encoding="utf-8")
    src_window = "#263238" if dark else "#e7e8eb"
    found = re.search(r"window\.color=(#[0-9a-fA-F]{6})", cfg)
    if found:
        src_window = found.group(1)
    src_accent = "#00bcd4"
    win, accent = base["window"], tones["accent"]
    svg = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: recolour(m.group(0), src_window, src_accent, win, accent, danger), svg)
    on_accent = "#0B1512" if luminance(accent) > 0.35 else "#FFFFFF"
    colours = {
        "window.color": win, "base.color": base["view"], "alt.base.color": mix(base["view"], win, 0.5),
        "button.color": hexa(base["capsule"], win), "light.color": mix(win, "#FFFFFF", 0.12), "mid.light.color": mix(win, "#FFFFFF", 0.06),
        "dark.color": mix(win, "#000000", 0.35), "mid.color": mix(win, "#000000", 0.15),
        "highlight.color": accent, "inactive.highlight.color": mix(accent, win, 0.4),
        "text.color": base["text"], "window.text.color": base["text"], "button.text.color": base["text"],
        "disabled.text.color": base["text_tertiary"], "tooltip.text.color": base["text"], "highlight.text.color": on_accent,
        "link.color": accent, "link.visited.color": mix(accent, base["text_secondary"], 0.5), "progress.indicator.text.color": base["text"],
    }

    def general_colours(m: re.Match) -> str:
        body = m.group(0)
        for k, v in colours.items():
            body = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={v}", body, flags=re.M)
        return body
    cfg = re.sub(r"#[0-9a-fA-F]{6}\b", lambda m: recolour(m.group(0), src_window, src_accent, win, accent, danger), cfg)
    cfg = re.sub(r"\[GeneralColors\][^\[]*", general_colours, cfg)        # after: these are Huginn's exactly

    def on_accent_text(m: re.Match) -> str:                         # picked rows and menu items sit on the accent
        body = m.group(0)
        for k in ("text.press.color", "text.toggle.color") + (("text.focus.color",) if m.group(1) == "MenuItem" else ()):
            body = re.sub(rf"^{re.escape(k)}=.*$", f"{k}={on_accent}", body, flags=re.M)
        return body
    cfg = re.sub(r"\[(ItemView|MenuItem)\][^\[]*", on_accent_text, cfg)
    cfg = re.sub(r"^author=.*$", "author=Huginn OS (from KvAdapta by Tsu Jan)", cfg, count=1, flags=re.M)
    cfg = re.sub(r"^comment=.*$", f"comment={name}: Huginn's look for Qt apps", cfg, count=1, flags=re.M)
    folder = out / "kvantum" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.svg").write_text(svg, encoding="utf-8")
    (folder / f"{name}.kvconfig").write_text(cfg, encoding="utf-8")


def qml_tokens(t: dict) -> str:
    out = ["// Generated by gen_theme.py - do not edit.", "pragma Singleton", "import QtQuick", "", "QtObject {"]
    for k, v in t["radius"].items():
        out.append(f"    readonly property int radius{k.title()}: {v}")
    for k, v in t["space"].items():
        out.append(f"    readonly property int space{k.title()}: {v}")
    out.append(f"    readonly property int hoverMs: {t['motion']['hover_ms']}")
    out.append(f"    readonly property int pressMs: {t['motion']['press_ms']}")
    out.append(f"    readonly property real pressScale: {t['motion']['press_scale']}")
    out.append(f"    readonly property real panelOpacity: {t['glass']['panel_opacity']}")
    out.append(f"    readonly property real popupOpacity: {t['glass']['popup_opacity']}")
    out.append(f"    readonly property int blurRadius: {t['glass']['blur_radius_px']}")
    out.append(f"    readonly property string fontUi: \"{t['font']['ui']}\"")
    out.append(f"    readonly property string fontMono: \"{t['font']['mono']}\"")
    out.append("    readonly property var realms: (" + json.dumps(t["realms"], ensure_ascii=False) + ")")
    out.append("}")
    return "\n".join(out) + "\n"


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        return 2
    tokens = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    kv_src = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    for sub in ("color-schemes", "gtk", "qml"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    failures = []
    for realm, spec in tokens["realms"].items():
        for mode in ("light", "dark"):
            base, tones = tokens[mode], spec[mode]
            name = f"Huginn{realm.title()}{mode.title()}"
            danger = tokens["danger"][mode]
            (out / "color-schemes" / f"{name}.colors").write_text(color_scheme(name, base, tones, danger), encoding="utf-8")
            (out / "gtk" / f"{name}.css").write_text(gtk_css(base, tones, danger, tokens["radius"]), encoding="utf-8")
            (out / "gtk" / f"{name}-gtk3.css").write_text(gtk3_css(base, tones, danger, mode == "dark"), encoding="utf-8")
            if kv_src is not None:
                kvantum(name, base, tones, danger, mode == "dark", kv_src, out)
            # Contrast gate: body text on window >= 7, secondary >= 4.5, accent as text on view >= 3.
            checks = [("text/window", contrast(base["text"], base["window"]), 7.0),
                      ("secondary/window", contrast(base["text_secondary"], base["window"]), 4.5),
                      ("accent/view", contrast(tones["accent"], base["view"]), 3.0)]
            for label, ratio, need in checks:
                flag = "ok " if ratio >= need else "LOW"
                print(f"{flag} {name:28s} {label:18s} {ratio:5.2f} (min {need})")
                if ratio < need:
                    failures.append((name, label))
    (out / "qml" / "Tokens.qml").write_text(qml_tokens(tokens), encoding="utf-8")
    (out / "qml" / "qmldir").write_text("module org.huginn.tokens\nsingleton Tokens 1.0 Tokens.qml\n", encoding="utf-8")
    print(f"wrote {len(tokens['realms']) * 2} colour schemes + GTK css + Tokens.qml to {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
