# Resultados - Actividad 4: agrupamiento de estaciones de TransMilenio

Generado el 2026-10-10 con `python -m actividad4 agrupar`.

## Datos y atributos

Fuente: entradas y salidas cada 15 minutos publicadas por TRANSMILENIO S.A., sumadas por hora (`datos/afluencia_transmilenio_real.csv`).

80 estaciones. Cada una se describe con 6 atributos calculados a partir de sus entradas y salidas, y luego estandarizados (puntuación z):

| Atributo | Descripción | Media | Desv. |
|---|---|---|---|
| `log_volumen` | log10 de las entradas de un día hábil promedio | 3.949 | 0.350 |
| `pico_am_entradas` | fracción de las entradas del día hábil entre 5:00 y 8:59 | 0.221 | 0.174 |
| `pico_pm_entradas` | fracción de las entradas del día hábil entre 16:00 y 19:59 | 0.390 | 0.143 |
| `pico_am_salidas` | fracción de las salidas del día hábil entre 6:00 y 9:59 | 0.407 | 0.146 |
| `pico_pm_salidas` | fracción de las salidas del día hábil entre 17:00 y 20:59 | 0.214 | 0.122 |
| `ratio_fin_de_semana` | entradas de un día de fin de semana o festivo / entradas de un día hábil | 0.381 | 0.107 |

## Elección del número de grupos

![Codo](codo.svg)

![Silueta](silueta.svg)

| k | SSE (k-medias) | Silueta k-medias | Silueta Ward |
|---|---|---|---|
| 2 | 238.3 | 0.472 | 0.465 |
| 3 | 181.3 | 0.291 | 0.263 |
| 4 | 151.0 | 0.300 | 0.295 |
| 5 | 128.5 | 0.280 | 0.315 |
| 6 | 108.5 | 0.292 | 0.293 |
| 7 | 94.6 | 0.263 | 0.259 |
| 8 | 82.6 | 0.293 | 0.253 |

La silueta de k-medias es máxima en k = 2. **Se usa k = 2.**

## Grupos encontrados (k-medias)

| Grupo | Estaciones | Entradas/día | `pico_am_entradas` | `pico_pm_entradas` | `pico_am_salidas` | `pico_pm_salidas` | `ratio_fin_de_semana` |
|---|---|---|---|---|---|---|---|
| 1. Empleo / oficinas | 60 | 7.901 | 0.14 | 0.46 | 0.48 | 0.15 | 0.36 |
| 2. Residencial | 20 | 12.674 | 0.48 | 0.18 | 0.20 | 0.40 | 0.44 |

- **Empleo / oficinas** (60): 7 de Agosto, Alcalá, Av. 39, Av. 68, Av. Chile, Av. El Dorado, Av. Jiménez, Av. Rojas, CAD, CAN, CDS - Carrera 32, Calle 100, Calle 106, Calle 127, Calle 161, Calle 22, Calle 26, Calle 34, Calle 45, Calle 57, Calle 76, Calle 85, Campín, Carrera 43, Carrera 47, Carrera 53, Centro Memoria, Ciudad Universitaria, Concejo de Bogotá, Corferias, De La Sabana, Distrito Grafiti, El Tiempo - Maloka, Escuela Militar, Ferias, Flores, Gobernación, Héroes, La Castellana, Las Aguas, Marly, Modelia, Movistar Arena, Museo del Oro, NQS Calle 75, Normandía, Paloquemao, Pepe Sierra, Polo, Pradera, Prado, Puente Aranda, Quinta Paredes, Ricaurte, Salitre - El Greco, San Façón - Carrera 22, U. Nacional, Universidades, Virrey, Zona Industrial.
- **Residencial** (20): Américas - Av. Boyacá, Av. Boyacá, Av. Ciudad de Cali, Banderas, Biblioteca Tintal, Calle 142, Calle 146, Carrera 90, Granja - Carrera 77, Mandalay, Marsella, Mazurén, Minuto de Dios, Portal 80, Portal Américas, Portal El Dorado, Portal Norte, Quirigua, Toberín, Transversal 86.

![Mapa de los grupos](mapa_clusters.svg)

![Perfil horario de entradas](perfiles_entradas.svg)

![Perfil horario de salidas](perfiles_salidas.svg)

## Comparación con el agrupamiento jerárquico (Ward)

![Dendrograma](dendrograma.svg)

| Medida | k-medias | Jerárquico (Ward) |
|---|---|---|
| Silueta promedio | 0.472 | 0.465 |
| Índice de Rand ajustado vs. vocación supuesta en la muestra | 0.025 | -0.030 |

Concordancia entre los dos métodos (índice de Rand ajustado): **0.688**. Estaciones asignadas distinto: Av. Boyacá, Calle 142, Calle 146, Mazurén, Minuto de Dios, Toberín.

## ¿Se cumplen los supuestos de la muestra?

La muestra sintética se generó suponiendo una vocación para cada estación: empleo o educativa / ocio según una lista de atractores (Calle 72, Calle 100, CAN, U. Nacional, Campín, Corferias, ...), residencial si es portal o está a más de 7,5 km del centro, y mixta en otro caso. Esa vocación no se usó para agrupar. La tabla la compara con los grupos encontrados en los datos reales:

| Grupo \ vocación | residencial | empleo | educativa_ocio | mixta |
|---|---|---|---|---|
| Empleo / oficinas | 16 | 18 | 9 | 17 |
| Residencial | 17 | 0 | 0 | 3 |

## De vuelta a la base de conocimiento

Los grupos se exportan como hechos lógicos en [perfiles.kb](perfiles.kb) (`perfil_estacion(Estacion, Perfil).`) y se consultan junto con las reglas de la Actividad 2. Por ejemplo, el perfil de las estaciones de integración que infiere la base de conocimiento:

```text
perfil_estacion(E, P), estacion_de_integracion(E)
  Av. Jiménez: empleo
  Calle 100: empleo
  Escuela Militar: empleo
  Héroes: empleo
  Las Aguas: empleo
  Ricaurte: empleo
  Universidades: empleo
```

La asignación completa de cada estación está en [asignacion.csv](asignacion.csv).
