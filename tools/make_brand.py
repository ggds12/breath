"""Gera a identidade visual do Breath: mascote "Puff" (8 estados animados), símbolo e favicon.

Uso:  python tools/make_brand.py
Saída: web/assets/mascot/*.svg, web/assets/symbol.svg, web/assets/favicon.svg

O Puff é uma nuvenzinha de ar com bochechas cheias soprando fiapos de vento.
Estilo: formas chapadas, rosto recortado na própria forma, cantos macios.
As animações usam SMIL (não dependem de CSS), então funcionam em <img>.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "assets"

INK = "#0E1013"       # grafite do Breath
WHITE = "#FFFFFF"
AIR = "#34D3B4"       # menta "ar"
AIR_2 = "#8BF0DA"

# Corpo: união de círculos (a "nuvem" de ar), centro de respiração em (52, 64).
BODY = [(50, 66, 31), (32, 54, 18), (55, 40, 22), (75, 62, 19)]
CX, CY = 52, 64


def body_shapes(fill: str, mask: str | None = None, outline: bool = False) -> str:
    if outline:
        circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in BODY)
        # contorno pontilhado: desenha o traço e apaga o interior com a mesma união menor
        inner = "".join(f'<circle cx="{x}" cy="{y}" r="{r - 3.4}"/>' for x, y, r in BODY)
        return (f'<mask id="ring"><g fill="#fff">{circles}</g><g fill="#000">{inner}</g></mask>'
                f'<rect x="0" y="0" width="120" height="120" fill="{fill}" mask="url(#ring)" opacity=".9"/>')
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in BODY)
    m = f' mask="url(#{mask})"' if mask else ""
    return f'<g fill="{fill}"{m}>{circles}</g>'


def breathe(content: str, dur: float = 3.6, amount: float = 0.035, squash: float = 1.0) -> str:
    """Respiração: o corpo enche e esvazia em torno do centro."""
    hi = f"{1 + amount} {1 + amount * 0.8}"
    base = f"1 {squash}"
    return (f'<g transform="translate({CX} {CY})"><g>'
            f'<animateTransform attributeName="transform" type="scale" values="{base};{hi};{base}" '
            f'dur="{dur}s" repeatCount="indefinite" calcMode="spline" keySplines=".45 0 .55 1;.45 0 .55 1"/>'
            f'<g transform="translate({-CX} {-CY})">{content}</g></g></g>')


def wisps(color: str, dur: float = 2.4, x0: int = 99) -> str:
    """Três fiapos de vento saindo da boca, em sequência."""
    lines = [f"M{x0} 62 q8 -5 16 -1", f"M{x0 + 2} 71 h15", f"M{x0} 80 q8 5 16 1"]
    out = []
    for i, d in enumerate(lines):
        begin = f"{i * dur / 6:.2f}s"
        out.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="4.2" stroke-linecap="round" opacity="0">'
            f'<animate attributeName="opacity" values="0;1;0" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/>'
            f'<animateTransform attributeName="transform" type="translate" values="-4 0;3 0;8 0" dur="{dur}s" '
            f'begin="{begin}" repeatCount="indefinite"/></path>')
    return "".join(out)


def blink(cx: float, cy: float, inner: str) -> str:
    return (f'<g transform="translate({cx} {cy})"><g>'
            f'<animateTransform attributeName="transform" type="scale" values="1 1;1 1;1 .1;1 1;1 1" '
            f'keyTimes="0;.86;.9;.94;1" dur="4.2s" repeatCount="indefinite"/>'
            f'<g transform="translate({-cx} {-cy})">{inner}</g></g></g>')


EYE_L, EYE_R = (43, 58), (61, 57)
MOUTH = (89, 67)   # na borda da bochecha: um "o" soprando para fora


def face(state: str) -> tuple[str, str]:
    """(recortes do rosto, dentro da máscara) e (extras desenhados por fora)."""
    lx, ly = EYE_L
    rx, ry = EYE_R
    mx, my = MOUTH
    eye = lambda x, y: f'<ellipse cx="{x}" cy="{y}" rx="5.4" ry="8.2"/>'
    if state == "pronto":
        cut = blink((lx + rx) / 2, ly, eye(lx, ly) + eye(rx, ry)) + f'<circle cx="{mx}" cy="{my}" r="5.4"/>'
        return cut, ""
    if state == "buscando":
        eyes = eye(lx, ly) + eye(rx, ry)
        cut = (f'<g>{eyes}<animateTransform attributeName="transform" type="translate" '
               f'values="0 0;-4 0;-4 0;4 0;4 0;0 0" keyTimes="0;.15;.4;.55;.85;1" dur="3s" repeatCount="indefinite"/></g>'
               f'<circle cx="{mx}" cy="{my}" r="3.2"/>')
        return cut, ""
    if state == "processando":
        cut = (eye(lx, ly) + eye(rx, ry) +
               f'<circle cx="{mx}" cy="{my}" r="5.2"><animate attributeName="r" values="4;6;4" dur="1.1s" repeatCount="indefinite"/></circle>')
        return cut, ""
    if state == "sucesso":
        arc = lambda x, y: f'<path d="M{x - 6} {y + 2} q6 -9 12 0" fill="none" stroke="#000" stroke-width="4" stroke-linecap="round"/>'
        cut = arc(lx, ly) + arc(rx, ry) + f'<path d="M{mx - 8} {my - 2} q4 8 9 2" fill="none" stroke="#000" stroke-width="3.6" stroke-linecap="round"/>'
        return cut, ""
    if state == "atencao":
        cut = (f'<circle cx="{lx}" cy="{ly}" r="6.6"/><circle cx="{rx}" cy="{ry}" r="6.6"/>'
               f'<rect x="{mx - 5}" y="{my - 1.8}" width="10" height="3.6" rx="1.8"/>')
        return cut, "sweat"
    if state == "erro":
        x = lambda cx, cy: (f'<path d="M{cx - 5.5} {cy - 5.5} l11 11 M{cx + 5.5} {cy - 5.5} l-11 11" '
                            f'stroke="#000" stroke-width="4" stroke-linecap="round"/>')
        cut = x(lx, ly) + x(rx, ry) + f'<ellipse cx="{mx}" cy="{my + 1}" rx="5" ry="6.5"/>'
        return cut, "gasp"
    if state == "vazio":
        cut = f'<circle cx="{lx}" cy="{ly}" r="2.6"/><circle cx="{rx}" cy="{ry}" r="2.6"/>'
        return cut, ""
    if state == "repouso":
        closed = lambda x, y: f'<path d="M{x - 6} {y} q6 6 12 0" fill="none" stroke="#000" stroke-width="3.8" stroke-linecap="round"/>'
        cut = closed(lx, ly) + closed(rx, ry) + f'<circle cx="{mx}" cy="{my}" r="2.4"/>'
        return cut, "zzz"
    raise ValueError(state)


def extras(kind: str, color: str) -> str:
    if kind == "sweat":
        return (f'<path d="M93 22 q6 9 0 13 q-6 -4 0 -13z" fill="{color}">'
                f'<animateTransform attributeName="transform" type="translate" values="0 0;0 3;0 0" dur="1.6s" repeatCount="indefinite"/></path>')
    if kind == "gasp":
        return (f'<g fill="none" stroke="{color}" stroke-width="3.6" stroke-linecap="round">'
                f'<path d="M99 63 q5 4 0 8"><animate attributeName="opacity" values="1;.2;1" dur=".9s" repeatCount="indefinite"/></path>'
                f'<path d="M106 60 q7 7 0 14"><animate attributeName="opacity" values=".2;1;.2" dur=".9s" repeatCount="indefinite"/></path></g>')
    if kind == "zzz":
        zs = []
        for i, (x, y, s) in enumerate([(88, 34, 1.0), (98, 22, 0.8)]):
            d = f"M{x} {y} h{8 * s} l-{8 * s} {8 * s} h{8 * s}"
            zs.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity="0">'
                      f'<animate attributeName="opacity" values="0;1;0" dur="3s" begin="{i * 1.5}s" repeatCount="indefinite"/>'
                      f'<animateTransform attributeName="transform" type="translate" values="0 4;0 -6" dur="3s" begin="{i * 1.5}s" repeatCount="indefinite"/></path>')
        return "".join(zs)
    return ""


STATES = {
    # estado: (ritmo da respiração, intensidade, achatamento, fiapos?)
    "pronto": (3.6, 0.035, 1.0, 2.6),
    "buscando": (3.0, 0.03, 1.0, 0),
    "processando": (1.1, 0.05, 1.0, 1.0),
    "sucesso": (2.4, 0.05, 1.0, 0),
    "atencao": (1.8, 0.03, 1.0, 0),
    "erro": (0.9, 0.025, 0.93, 0),      # sem fôlego: menor, respiração curta
    "vazio": (4.0, 0.02, 1.0, 0),
    "repouso": (5.0, 0.03, 1.0, 0),
}


def mascot(state: str, color: str, title: str) -> str:
    dur, amount, squash, wisp = STATES[state]
    cut, extra_kind = face(state)
    mask = (f'<mask id="face" maskUnits="userSpaceOnUse" x="0" y="0" width="120" height="120">'
            f'<rect width="120" height="120" fill="#fff"/><g fill="#000">{cut}</g></mask>')
    if state == "vazio":
        body = body_shapes(color, outline=True) + f'<g fill="{color}"><circle cx="{EYE_L[0]}" cy="{EYE_L[1]}" r="2.6"/><circle cx="{EYE_R[0]}" cy="{EYE_R[1]}" r="2.6"/></g>'
    else:
        body = body_shapes(color, mask="face")
    hop = ""
    inner = breathe(body, dur, amount, squash)
    if state == "sucesso":
        inner = (f'<g>{inner}<animateTransform attributeName="transform" type="translate" '
                 f'values="0 0;0 -6;0 0;0 0" keyTimes="0;.18;.36;1" dur="2.4s" repeatCount="indefinite"/></g>')
    parts = [inner]
    if wisp:
        parts.append(wisps(color, wisp))
    parts.append(extras(extra_kind, color))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120" role="img">'
            f'<title>{title}</title><defs>{mask}</defs>{"".join(parts)}{hop}</svg>\n')


def symbol(size_title: str = "Breath") -> str:
    """Ícone do app: Puff grafite sobre um quadrado menta arredondado."""
    cut, _ = face("pronto")
    cut_static = ('<ellipse cx="43" cy="58" rx="5.4" ry="8.2"/><ellipse cx="61" cy="57" rx="5.4" ry="8.2"/>'
                  '<circle cx="89" cy="67" r="5.4"/>')
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in BODY)
    wisp = ('<g fill="none" stroke="{c}" stroke-width="5" stroke-linecap="round">'
            '<path d="M100 58 q7 -4 13 -1"/><path d="M102 67 h11"/><path d="M100 76 q7 4 13 1"/></g>').format(c=INK)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="120" height="120" role="img">'
            f'<title>{size_title}</title>'
            f'<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{AIR_2}"/>'
            f'<stop offset="1" stop-color="{AIR}"/></linearGradient>'
            f'<mask id="face" maskUnits="userSpaceOnUse" x="0" y="0" width="120" height="120"><rect width="120" height="120" fill="#fff"/>'
            f'<g fill="#000">{cut_static}</g></mask></defs>'
            f'<rect width="120" height="120" rx="28" fill="url(#bg)"/>'
            f'<g transform="translate(-7 2)"><g fill="{INK}" mask="url(#face)">{circles}</g>{wisp}</g></svg>\n')


def main() -> None:
    mdir = OUT / "mascot"
    mdir.mkdir(parents=True, exist_ok=True)
    names = {"pronto": "Puff, tranquilo", "buscando": "Puff, procurando", "processando": "Puff, atualizando",
             "sucesso": "Puff, feliz", "atencao": "Puff, atento", "erro": "Puff, sem fôlego",
             "vazio": "Puff, sem dados", "repouso": "Puff, descansando"}
    for state, title in names.items():
        (mdir / f"{state}.svg").write_text(mascot(state, INK, title), encoding="utf-8")
        (mdir / f"{state}-branco.svg").write_text(mascot(state, WHITE, title), encoding="utf-8")
    (OUT / "symbol.svg").write_text(symbol(), encoding="utf-8")
    (OUT / "favicon.svg").write_text(symbol(), encoding="utf-8")
    print("ok:", len(names) * 2, "mascotes + símbolo + favicon")


if __name__ == "__main__":
    main()
