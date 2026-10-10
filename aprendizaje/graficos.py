"""
Gráficos SVG sin librerías externas (se ven en GitHub y en cualquier navegador).

Convenciones:
- Paleta categórica validada para daltonismo, siempre en el mismo orden
  (la serie i usa el color i). Modo claro y oscuro con @media en el SVG.
- Líneas de 2 px, marcadores de radio 4 con anillo del color de fondo,
  barras de máximo 24 px con extremo redondeado, cuadrícula fina y discreta.
- El texto nunca usa el color de la serie: la identidad la da la marca
  junto al texto (leyenda), y cada marca tiene <title> como información al
  pasar el mouse.
- Un solo eje Y por gráfico: dos medidas distintas van en gráficos separados.
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

# Paleta categórica (claro, oscuro) en orden fijo
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
          ("#e87ba4", "#d55181"), ("#008300", "#008300"), ("#4a3aa7", "#9085e9"), ("#e34948", "#e66767")]
TINTA = {"superficie": ("#fcfcfb", "#1a1a19"), "primaria": ("#0b0b0b", "#ffffff"),
         "secundaria": ("#52514e", "#c3c2b7"), "tenue": ("#898781", "#898781"),
         "cuadricula": ("#e1e0d9", "#2c2c2a"), "eje": ("#c3c2b7", "#383835")}
FUENTE = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _estilos() -> str:
    claro = [f".f-{k}{{fill:{c}}}.s-{k}{{stroke:{c}}}" for k, (c, _) in TINTA.items()]
    oscuro = [f".f-{k}{{fill:{c}}}.s-{k}{{stroke:{c}}}" for k, (_, c) in TINTA.items()]
    claro += [f".f-serie{i}{{fill:{c}}}.s-serie{i}{{stroke:{c}}}" for i, (c, _) in enumerate(SERIES)]
    oscuro += [f".f-serie{i}{{fill:{c}}}.s-serie{i}{{stroke:{c}}}" for i, (_, c) in enumerate(SERIES)]
    return ("<style>text{font-family:" + FUENTE + ";font-variant-numeric:tabular-nums}"
            + "".join(claro) + "@media (prefers-color-scheme: dark){" + "".join(oscuro) + "}</style>")


def _serie(i: int) -> int:
    if i >= len(SERIES):
        raise ValueError("Máximo 8 series por gráfico: agrupe el resto o use varios gráficos.")
    return i


class Lienzo:
    """Acumula elementos SVG y los serializa."""

    def __init__(self, ancho: int, alto: int, titulo: str, subtitulo: str = ""):
        self.ancho, self.alto = ancho, alto
        self.partes: List[str] = [f'<rect class="f-superficie" width="{ancho}" height="{alto}" rx="8"/>']
        self.texto(20, 28, titulo, tam=16, clase="primaria", peso="600")
        if subtitulo:
            self.texto(20, 48, subtitulo, tam=12, clase="secundaria")
        self.titulo = titulo

    def texto(self, x: float, y: float, contenido: str, tam: int = 11, clase: str = "secundaria",
              ancla: str = "start", peso: str = "400", rotar: Optional[float] = None) -> None:
        rot = f' transform="rotate({rotar} {x:.1f} {y:.1f})"' if rotar is not None else ""
        self.partes.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{tam}" font-weight="{peso}" '
                           f'text-anchor="{ancla}" class="f-{clase}"{rot}>{escape(str(contenido))}</text>')

    def linea(self, x1, y1, x2, y2, clase: str = "cuadricula", grosor: float = 1) -> None:
        self.partes.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                           f'class="s-{clase}" stroke-width="{grosor}"/>')

    def polilinea(self, puntos: Sequence[Tuple[float, float]], clase: str, grosor: float = 2) -> None:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in puntos)
        self.partes.append(f'<polyline points="{pts}" fill="none" class="s-{clase}" stroke-width="{grosor}" '
                           f'stroke-linejoin="round" stroke-linecap="round"/>')

    def punto(self, x: float, y: float, clase: str, r: float = 4, titulo: str = "") -> None:
        """Marcador con anillo de 2 px del color de fondo (se lee sobre las líneas)."""
        tip = f"<title>{escape(titulo)}</title>" if titulo else ""
        self.partes.append(f'<g>{tip}<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + 2}" class="f-superficie"/>'
                           f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" class="f-{clase}"/></g>')

    def crudo(self, svg: str) -> None:
        self.partes.append(svg)

    def svg(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.ancho} {self.alto}" '
                f'width="{self.ancho}" height="{self.alto}" role="img" aria-label="{escape(self.titulo)}">'
                f"<title>{escape(self.titulo)}</title>{_estilos()}" + "".join(self.partes) + "</svg>\n")


def guardar(svg: str, ruta: str) -> str:
    os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    return ruta


# ---------------------------------------------------------------------------
# Escalas y ejes
# ---------------------------------------------------------------------------

def _marcas(minimo: float, maximo: float, n: int = 5) -> List[float]:
    """Marcas "redondas" (1, 2, 2.5, 5 × 10^k) que cubren el rango."""
    if maximo <= minimo:
        maximo = minimo + 1
    paso_crudo = (maximo - minimo) / n
    base = 10 ** math.floor(math.log10(paso_crudo))
    paso = min((m * base for m in (1, 2, 2.5, 5, 10) if m * base >= paso_crudo), default=10 * base)
    inicio = math.floor(minimo / paso) * paso
    marcas, v = [], inicio
    while v <= maximo + paso * 1e-9:
        marcas.append(round(v, 10))
        v += paso
    if marcas[-1] < maximo:
        marcas.append(round(marcas[-1] + paso, 10))
    return marcas


def _fmt(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", ".")
    if v == int(v):
        return str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".")


class _Marco:
    """Área de trazado con un eje X y UN eje Y."""

    def __init__(self, lz: Lienzo, xs: Sequence[float], ys: Sequence[float], eje_x: str, eje_y: str,
                 y_desde_cero: bool = False, margen_der: int = 120, formato_y=_fmt):
        self.lz = lz
        self.x0, self.x1 = 64, lz.ancho - margen_der
        self.y0, self.y1 = lz.alto - 52, 88
        y_min = 0.0 if y_desde_cero else min(ys)
        self.marcas_y = _marcas(y_min, max(ys))
        self.ymin, self.ymax = self.marcas_y[0], self.marcas_y[-1]
        self.xmin, self.xmax = min(xs), max(xs)
        for v in self.marcas_y:
            y = self.y(v)
            lz.linea(self.x0, y, self.x1, y, "cuadricula")
            lz.texto(self.x0 - 8, y + 4, formato_y(v), ancla="end", clase="tenue")
        lz.linea(self.x0, self.y0, self.x1, self.y0, "eje")
        lz.texto((self.x0 + self.x1) / 2, lz.alto - 14, eje_x, ancla="middle", clase="secundaria")
        lz.texto(18, (self.y0 + self.y1) / 2, eje_y, ancla="middle", clase="secundaria", rotar=-90)

    def x(self, v: float) -> float:
        if self.xmax == self.xmin:
            return (self.x0 + self.x1) / 2
        return self.x0 + (v - self.xmin) / (self.xmax - self.xmin) * (self.x1 - self.x0)

    def y(self, v: float) -> float:
        return self.y0 - (v - self.ymin) / (self.ymax - self.ymin) * (self.y0 - self.y1)

    def marcas_x(self, valores: Sequence[float], formato=_fmt) -> None:
        for v in valores:
            self.lz.linea(self.x(v), self.y0, self.x(v), self.y0 + 4, "eje")
            self.lz.texto(self.x(v), self.y0 + 18, formato(v), ancla="middle", clase="tenue")


def _leyenda(lz: Lienzo, nombres: Sequence[str], x: float, y: float) -> None:
    """Leyenda horizontal: muestra de color + nombre en tinta secundaria."""
    for i, nombre in enumerate(nombres):
        lz.crudo(f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="14" height="4" rx="2" class="f-serie{_serie(i)}"/>')
        lz.texto(x + 20, y - 3, nombre, clase="secundaria")
        x += 34 + 6.5 * len(nombre)


# ---------------------------------------------------------------------------
# Tipos de gráfico
# ---------------------------------------------------------------------------

def lineas(x: Sequence[float], series: Dict[str, Sequence[float]], titulo: str, subtitulo: str,
           eje_x: str, eje_y: str, ancho: int = 720, alto: int = 380, marcar_x: Optional[float] = None,
           texto_marca: str = "", y_desde_cero: bool = False, formato_y=_fmt, formato_x=_fmt,
           marcas_x: Optional[Sequence[float]] = None) -> str:
    """Una o varias series sobre un mismo eje. Leyenda si hay 2 o más series;
    etiqueta directa al final de cada línea si son 4 o menos."""
    nombres = list(series)
    lz = Lienzo(ancho, alto, titulo, subtitulo)
    todos = [v for s in series.values() for v in s]
    m = _Marco(lz, x, todos, eje_x, eje_y, y_desde_cero, formato_y=formato_y)
    m.marcas_x(marcas_x if marcas_x is not None else x, formato_x)
    if marcar_x is not None:
        lz.linea(m.x(marcar_x), m.y1, m.x(marcar_x), m.y0, "eje", 1)
        lz.texto(m.x(marcar_x) + 6, m.y0 - 8, texto_marca, clase="secundaria")
    for i, (nombre, ys) in enumerate(series.items()):
        clase = f"serie{_serie(i)}"
        lz.polilinea([(m.x(a), m.y(b)) for a, b in zip(x, ys)], clase)
        if len(x) <= 30:
            for a, b in zip(x, ys):
                lz.punto(m.x(a), m.y(b), clase, titulo=f"{nombre}: {formato_x(a)} → {formato_y(b)}")
    if len(nombres) >= 2:
        _leyenda(lz, nombres, m.x0, 70)
    if 2 <= len(nombres) <= 4:
        # Etiquetas directas al final; si chocan, se deja solo la leyenda
        finales = sorted(((m.y(ys[-1]), n) for n, ys in series.items()))
        if all(b[0] - a[0] >= 14 for a, b in zip(finales, finales[1:])):
            for y, nombre in finales:
                lz.texto(m.x1 + 8, y + 4, nombre, clase="secundaria")
    return lz.svg()


def barras_horizontales(etiquetas: Sequence[str], valores: Sequence[float], titulo: str,
                        subtitulo: str, ancho: int = 720, formato=_fmt, eje: str = "") -> str:
    """Una sola serie: barras desde una línea base común, valor en la punta."""
    alto_fila = 30
    alto = 90 + alto_fila * len(etiquetas) + 30
    lz = Lienzo(ancho, alto, titulo, subtitulo)
    x0 = 20 + 7 * max(len(e) for e in etiquetas) + 12
    x1 = ancho - 80
    vmax = max(valores) or 1
    marcas = _marcas(0, vmax, 4)
    escala = lambda v: x0 + v / marcas[-1] * (x1 - x0)
    y_ini = 74
    for v in marcas:
        lz.linea(escala(v), y_ini - 6, escala(v), y_ini + alto_fila * len(etiquetas), "cuadricula")
        lz.texto(escala(v), y_ini + alto_fila * len(etiquetas) + 16, formato(v), ancla="middle", clase="tenue")
    if eje:
        lz.texto((x0 + x1) / 2, alto - 8, eje, ancla="middle", clase="secundaria")
    grosor = 18
    for i, (e, v) in enumerate(zip(etiquetas, valores)):
        yc = y_ini + i * alto_fila + alto_fila / 2
        lz.texto(x0 - 10, yc + 4, e, ancla="end", clase="primaria")
        largo = max(escala(v) - x0, 0.0)
        r = min(4.0, largo / 2)
        # Extremo redondeado (4 px) solo en la punta; cuadrado en la línea base
        camino = (f"M{x0:.1f},{yc - grosor / 2:.1f} h{largo - r:.1f} a{r},{r} 0 0 1 {r},{r} "
                  f"v{grosor - 2 * r:.1f} a{r},{r} 0 0 1 {-r},{r} h{-(largo - r):.1f} z")
        lz.crudo(f'<path d="{camino}" class="f-serie0"><title>{escape(e)}: {formato(v)}</title></path>')
        lz.texto(x0 + largo + 6, yc + 4, formato(v), clase="primaria")
    lz.linea(x0, y_ini - 6, x0, y_ini + alto_fila * len(etiquetas), "eje")
    return lz.svg()


def mapas_por_grupo(coordenadas: Dict[str, Tuple[float, float]], grupo: Dict[str, int],
                    nombres_grupo: Sequence[str], segmentos: Sequence[Tuple[str, str]],
                    titulo: str, subtitulo: str = "", columnas: int = 3, lado: int = 260) -> str:
    """Pequeños múltiplos: un mapa por grupo, sus estaciones resaltadas y las
    demás en gris. (Más de 3 colores en un mismo diagrama de dispersión no se
    distinguen bien; un panel por grupo evita depender del color.)"""
    k = len(nombres_grupo)
    filas = math.ceil(k / columnas)
    ancho = 20 + columnas * (lado + 16)
    alto = 70 + filas * (lado + 34)
    lz = Lienzo(ancho, alto, titulo, subtitulo)
    lats = [c[0] for c in coordenadas.values()]
    lons = [c[1] for c in coordenadas.values()]
    # Proyección equirectangular con corrección por la latitud media
    cos_lat = math.cos(math.radians(sum(lats) / len(lats)))
    rango = max(max(lats) - min(lats), (max(lons) - min(lons)) * cos_lat)
    pad = 16

    for g in range(k):
        fila, col = divmod(g, columnas)
        ox, oy = 20 + col * (lado + 16), 70 + fila * (lado + 34)
        proy = lambda lat, lon: (ox + pad + ((lon - min(lons)) * cos_lat) / rango * (lado - 2 * pad),
                                 oy + 24 + pad + (max(lats) - lat) / rango * (lado - 2 * pad))
        miembros = sorted(e for e, gg in grupo.items() if gg == g)
        lz.crudo(f'<rect x="{ox}" y="{oy}" width="{lado}" height="{lado + 24}" rx="6" fill="none" '
                 f'class="s-cuadricula" stroke-width="1"/>')
        lz.crudo(f'<rect x="{ox + 10}" y="{oy + 9}" width="10" height="10" rx="2" class="f-serie{_serie(g)}"/>')
        lz.texto(ox + 26, oy + 18, f"{nombres_grupo[g]} ({len(miembros)})", clase="primaria", peso="600")
        for a, b in segmentos:
            (xa, ya), (xb, yb) = proy(*coordenadas[a]), proy(*coordenadas[b])
            lz.linea(xa, ya, xb, yb, "eje", 1.5)
        for e in sorted(coordenadas):
            if grupo.get(e) != g:
                x, y = proy(*coordenadas[e])
                lz.crudo(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" class="f-tenue"><title>{escape(e)}</title></circle>')
        for e in miembros:
            x, y = proy(*coordenadas[e])
            lz.punto(x, y, f"serie{_serie(g)}", titulo=f"{e} — {nombres_grupo[g]}")
    return lz.svg()


def dendrograma(fusiones: Sequence[Tuple[int, int, float, int]], hojas: Sequence[str],
                grupo_hoja: Sequence[int], nombres_grupo: Sequence[str], titulo: str,
                subtitulo: str = "", altura_corte: Optional[float] = None) -> str:
    """Dendrograma horizontal (hojas en filas, altura de fusión en X).
    fusiones al estilo scipy: (id_a, id_b, distancia, tamaño); los ids >= n son
    los grupos creados en fusiones anteriores."""
    n = len(hojas)
    alto_fila = 13
    alto = 146 + n * alto_fila
    ancho = 820
    lz = Lienzo(ancho, alto, titulo, subtitulo)
    x0, x1 = 190, ancho - 40
    y_ini = 110

    # Orden de las hojas: recorrido en profundidad desde la última fusión
    hijos = {n + i: (a, b) for i, (a, b, _, _) in enumerate(fusiones)}
    orden: List[int] = []
    pila = [n + len(fusiones) - 1] if fusiones else list(range(n))
    while pila:
        nodo = pila.pop()
        if nodo < n:
            orden.append(nodo)
        else:
            a, b = hijos[nodo]
            pila.extend([b, a])
    fila = {hoja: i for i, hoja in enumerate(orden)}
    dmax = max((f[2] for f in fusiones), default=1.0) or 1.0
    marcas = _marcas(0, dmax, 5)
    escala = lambda d: x0 + d / marcas[-1] * (x1 - x0)
    for v in marcas:
        lz.linea(escala(v), y_ini - 8, escala(v), y_ini + n * alto_fila, "cuadricula")
        lz.texto(escala(v), y_ini + n * alto_fila + 16, _fmt(v), ancla="middle", clase="tenue")
    lz.texto((x0 + x1) / 2, alto - 8, "distancia de fusión (Ward)", ancla="middle", clase="secundaria")

    posicion: Dict[int, Tuple[float, float]] = {}   # nodo -> (x, y)
    for hoja in range(n):
        y = y_ini + fila[hoja] * alto_fila + alto_fila / 2
        posicion[hoja] = (x0, y)
        g = grupo_hoja[hoja]
        lz.texto(x0 - 14, y + 3.5, hojas[hoja], tam=9, ancla="end", clase="secundaria")
        lz.crudo(f'<circle cx="{x0 - 6}" cy="{y:.1f}" r="3.5" class="f-serie{_serie(g)}">'
                 f'<title>{escape(hojas[hoja])} — {escape(nombres_grupo[g])}</title></circle>')
    for i, (a, b, d, _) in enumerate(fusiones):
        (xa, ya), (xb, yb) = posicion[a], posicion[b]
        xd = escala(d)
        lz.crudo(f'<path d="M{xa:.1f},{ya:.1f} H{xd:.1f} V{yb:.1f} H{xb:.1f}" fill="none" '
                 f'class="s-secundaria" stroke-width="1"/>')
        posicion[n + i] = (xd, (ya + yb) / 2)
    if altura_corte is not None:
        xc = escala(altura_corte)
        lz.linea(xc, y_ini - 8, xc, y_ini + n * alto_fila, "tenue", 1)
        lz.texto(xc + 4, y_ini - 12, "corte", clase="secundaria")
    _leyenda(lz, list(nombres_grupo), 20, 70)
    return lz.svg()
