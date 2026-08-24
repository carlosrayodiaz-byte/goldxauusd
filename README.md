# Bot de senales XAUUSD — Fase 1 (deteccion + journaling)

Bot local en Python que se conecta a un terminal MetaTrader 5 (cuenta demo,
**solo lectura de mercado**), detecta estructura de mercado y triggers de
Smart Money Concepts sobre XAUUSD, y registra cada deteccion en una base de
datos SQLite local.

## Ejecutar backtest real esta noche

Pasos exactos, sin dar nada por sabido. Necesitas: Windows con el terminal
MT5 ya instalado y una cuenta demo abierta (ver seccion 1 mas abajo si
todavia no la tienes).

**1. Clonar esta rama** (abre una terminal / PowerShell donde quieras el
proyecto):
```bash
git clone --branch claude/xauusd-trading-signals-phase1-kj0va4 https://github.com/carlosrayodiaz-byte/goldxauusd.git
cd goldxauusd
```
Si ya tenias el repo clonado de antes, en vez de clonar de nuevo:
```bash
cd goldxauusd
git checkout claude/xauusd-trading-signals-phase1-kj0va4
git pull origin claude/xauusd-trading-signals-phase1-kj0va4
```

**2. Crear el entorno virtual e instalar dependencias:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
(en Windows, `.venv\Scripts\activate`; si usas Git Bash es `source .venv/Scripts/activate`)

**3. Configurar `.env`:**
```bash
copy .env.example .env
```
Abre `.env` con un editor de texto y rellena exactamente estos tres campos
con los datos de TU cuenta demo (los mismos que usaste para loguearte en el
terminal MT5 — estan en el correo de bienvenida del broker, o en
**Herramientas > Opciones > Servidor** dentro del terminal):
```
MT5_LOGIN=<tu numero de cuenta demo, solo digitos>
MT5_PASSWORD=<la password de la cuenta demo>
MT5_SERVER=<el nombre EXACTO del servidor, ej. ICMarkets-Demo>
```
No hace falta tocar nada mas del `.env` (`MT5_TERMINAL_PATH` solo si tienes
varios terminales MT5 instalados y quieres apuntar a uno especifico).

**4. Dejar el terminal MT5 abierto y logueado** con esa misma cuenta demo
(el bot se conecta al terminal que ya esta corriendo, no abre uno nuevo).

**5. Confirmar el nombre exacto del simbolo del oro en tu broker:** en el
Market Watch del terminal, busca el oro — puede llamarse `XAUUSD`,
`XAUUSD.m`, `GOLD`, etc. Si NO es exactamente `XAUUSD`, pasalo con `--symbol`
en el paso siguiente (o edita `SYMBOL` en `.env`).

**6. Correr el backtest real (SIN `--dry-run`), pidiendo los ultimos 3 meses
de M1:**
```bash
python backtest.py --months 3
```
O si tu simbolo no es `XAUUSD`:
```bash
python backtest.py --months 3 --symbol XAUUSD.m
```
Puede tardar varios minutos (descarga M1/M5/M15/H1 en bloques semanales).
Al terminar vas a tener:
- `data/signals.db` — la base de datos real, con `source="backtest"`.
- `data/backtest_diagnostics.txt` — cobertura real de fechas, huecos,
  duplicados, alineacion de timestamps entre timeframes, y el offset
  estimado de zona horaria del servidor del broker.

**Nota:** el flujo completo de este script (parseo de argumentos, motor SMC,
escritura idempotente en SQLite, resumen final) ya quedo validado end-to-end
en esta sesion con `python backtest.py --dry-run` (datos sinteticos, sin
MT5) — ver mas abajo. Lo unico que no se pudo probar sin una maquina con MT5
real es la conexion en si misma (`mt5.initialize()`, `copy_rates_range()`) y
si tu broker realmente tiene 3 meses de historico M1 disponibles.

## Alcance de esta fase

Incluido:
- Descarga de velas OHLC en M1/M5/M15/H1 desde MT5.
- Bias direccional en M15/H1 (swing highs/lows, BOS, CHoCH) via
  [`smartmoneyconcepts`](https://pypi.org/project/smartmoneyconcepts/).
- Triggers en M1/M5: Fair Value Gaps, Order Blocks, barridos de liquidez.
- Marcado de confluencia (trigger a favor del bias), pero **se registran
  TODOS los triggers**, confluentes o no, para poder analizar despues si el
  filtro de bias realmente aporta.
- Journaling idempotente en SQLite.
- Bucle en vivo alineado al cierre de vela M1.
- Backtest offline contra historico de MT5.

Explicitamente **NO** incluido en esta fase (fases futuras): ejecucion de
ordenes, alertas por Telegram, capa macro o de sentimiento social, gestion de
riesgo / position sizing. El login a MT5 es unicamente para leer datos de
mercado; en ningun punto del codigo se llama a funciones de trading.

## Estructura del proyecto

```
config.py        Parametros (simbolo, timeframes, rutas, parametros SMC).
mt5_client.py     Conexion a MT5 y descarga de OHLC. Reconexion automatica.
smc_engine.py     Wrapper sobre smartmoneyconcepts. Puro: DataFrame -> BiasResult/TriggerSignal.
database.py       Esquema SQLite + insercion/consulta idempotente.
main.py           Bucle en vivo (produccion).
backtest.py       Motor SMC sobre historico de MT5, sin conexion en vivo.
tests/            Pruebas de sanity de smc_engine.py y database.py con datos sinteticos.

# Fase 2 -- capa macro, independiente de todo lo anterior (ver seccion propia mas abajo)
macro_config.py    Parametros de la capa macro (series FRED, filtros CFTC, calendario FOMC, cache).
macro_database.py  Cache SQLite propia (data/macro_cache.db), tabla macro_snapshots.
macro_engine.py    Ingesta: real yields, DXY, COT oro, calendario NFP/CPI/FOMC. SOLO ingesta, sin score/bias.
```

## 1. Instalar el terminal MT5 y abrir una cuenta demo

1. Descarga e instala el terminal MetaTrader 5 de tu bróker (o el genérico
   de MetaQuotes) desde su sitio oficial.
2. Abre el terminal, ve a **Archivo > Abrir una cuenta** y elige una **cuenta
   demo** (no uses una cuenta real para este bot).
3. Al crear la cuenta demo, el terminal te muestra (y puedes recuperar luego
   en **Herramientas > Opciones > Servidor**, o en el correo de bienvenida):
   - **Login** (numero de cuenta)
   - **Password**
   - **Server** (nombre exacto del servidor del broker, ej. `ICMarkets-Demo`)
4. Deja el terminal MT5 abierto e identifica el simbolo exacto del oro en tu
   broker (puede ser `XAUUSD`, `XAUUSD.m`, `GOLD`, etc. — revisa el Market
   Watch del terminal) y usalo en `SYMBOL` si difiere de `XAUUSD`.
5. Asegurate de que el simbolo tenga suficiente historico disponible en el
   Market Watch (click derecho > "Grafico" o aumenta el historico descargado
   si `backtest.py` reporta pocas velas).

## 2. Instalar dependencias

Requiere Python 3.10+ y Windows (o Wine) porque el paquete `MetaTrader5`
solo funciona junto a un terminal MT5 instalado localmente.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## 3. Configurar `.env`

```bash
copy .env.example .env         # Windows
```

Edita `.env` con tu login/password/server de la cuenta demo (ver paso 1).
Nunca compartas ni subas este archivo a git (ya esta en `.gitignore`).

## 4. Validar el motor contra historico: `backtest.py` PRIMERO

Antes de dejar el bot corriendo en vivo, valida que el motor de deteccion
funciona bien contra datos reales:

```bash
python backtest.py --months 3
```

Esto descarga ~3 meses de M1/M5/M15/H1 del simbolo configurado (en bloques
semanales, para no toparse con el limite de "maximo de barras en el grafico"
del terminal), calcula la misma logica de bias/triggers que usaria en vivo
(sin fuga de informacion futura, ver "Metodologia" en `backtest.py`), y
guarda todo en `data/signals.db` con `source="backtest"`. Al final imprime un
resumen por tipo de trigger y confluencia.

Ademas escribe `data/backtest_diagnostics.txt` con lo que no cabe en la
tabla `signals`:
- Cobertura real de datos por timeframe (primera/ultima vela, cuantas velas
  llegaron realmente — util si el broker no tiene los 3 meses completos).
- Timestamps duplicados y huecos de tiempo (>4h) en las velas descargadas
  (fines de semana normales, o caidas de feed del broker).
- Velas mal alineadas al limite de minuto esperado por timeframe (M5 en
  multiplos de 5, M15 en multiplos de 15, H1 en minuto 0) y si la zona
  horaria de la columna `time` es consistente ENTRE los cuatro timeframes
  (deberian venir todas del mismo reloj de servidor; si difieren, es un bug
  real, no la limitacion de offset conocida).
- El offset estimado entre el reloj del servidor del broker y UTC real (ver
  limitacion de zona horaria mas abajo).
- Ventanas de 2+ dias seguidos sin ninguna senal generada (M1+M5), con
  contexto de si hubo datos M1 ese dia y que bias predomino.

Revisa `data/backtest_diagnostics.txt` y la base de datos (con cualquier
cliente SQLite, ej. `DB Browser for SQLite`, o `sqlite3 data/signals.db`)
para inspeccionar las senales antes de confiar en el motor.

### Modo `--dry-run` (sin MT5, solo para validar el flujo del script)

```bash
python backtest.py --dry-run
```

No conecta a MT5: genera OHLC sintetico (los mismos generadores que usa
`tests/conftest.py`) y corre el mismo flujo completo — parseo de argumentos,
calculo de bias/triggers, escritura idempotente en SQLite, reporte de
diagnostico y resumen final. Escribe en archivos **separados**
(`data/dry_run_signals.db` y `data/dry_run_diagnostics.txt`) para no mezclar
nunca datos falsos con un backtest real. Sirve para comprobar que el script
en si no esta roto antes de tener acceso a MT5; **no reemplaza** al backtest
real de la seccion anterior, porque no valida nada de la conexion a MT5 ni
de la calidad de los datos reales del broker. Tambien se puede activar con
la variable de entorno `BACKTEST_DRY_RUN=1` en vez del flag.

## 5. Correr en vivo: `main.py`

```bash
python main.py
```

El bot se conecta a MT5, y cada minuto (alineado al cierre real de la vela
M1) descarga OHLC, calcula bias y triggers, y guarda las senales nuevas en
`data/signals.db` con `source="live"`. Los logs se imprimen en consola y se
guardan (rotados) en `logs/bot.log`. `Ctrl+C` para detenerlo.

## Esquema de la base de datos

Tabla `signals` (`database.py`):

| Columna | Descripcion |
|---|---|
| `id` | PK autoincremental |
| `detected_at` | Cuando el bot inserto la fila (UTC) |
| `candle_time` | Vela donde se confirmo el patron (UTC) — usada para idempotencia |
| `symbol` | Simbolo (ej. XAUUSD) |
| `source` | `live` o `backtest` |
| `bias_direction` / `bias_timeframe` | Bias vigente al detectar el trigger |
| `trigger_type` | `fvg` \| `order_block` \| `liquidity_sweep` |
| `trigger_direction` / `trigger_timeframe` | Direccion y TF (M1/M5) del trigger |
| `price_at_detection` | Precio de referencia al confirmarse |
| `top` / `bottom` | Limites de la zona (FVG/OB); en liquidez, `top` = nivel del pool |
| `confluente` | 1 si el trigger va a favor del bias, 0 si no (se guardan ambos) |
| `notas` | Texto explicando el porque (velas de origen/confirmacion, bias usado, etc.) |

Un indice `UNIQUE(symbol, source, trigger_timeframe, trigger_type, trigger_direction, candle_time, top, bottom)`
hace la insercion idempotente (`INSERT OR IGNORE`): reiniciar el bot o
re-correr el backtest sobre la misma ventana no genera duplicados.

## Limitaciones conocidas de esta fase

- El bias combina M15 y H1 con H1 como dominante (cae a M15 si H1 esta
  neutral). Ambos valores individuales quedan en `notas` para poder auditar
  el criterio.
- Para Order Blocks, `smartmoneyconcepts` no expone un indice explicito de
  "vela de confirmacion" (como si hace con BOS/CHoCH via `BrokenIndex`, o FVG
  via la vela siguiente). Se usa la vela de origen del bloque como
  `candle_time`; la ruptura que realmente lo confirma ocurre unas pocas velas
  despues. Esto es una aproximacion estandar en herramientas de charting SMC,
  pero puede adelantar ligeramente el bias comparado en la confluencia de
  `order_block` durante el backtest. Ver docstring de `smc_engine.py`.
- No hay gestion de riesgo, position sizing, ni conexion de escritura a la
  cuenta: el login a MT5 es solo de lectura de mercado.
- **Zona horaria**: MT5 devuelve los timestamps de velas en la hora del
  *servidor del broker*, no en UTC real. `mt5_client.py` los etiqueta como
  UTC (`pd.to_datetime(..., utc=True)`) porque es la convencion mas simple
  para que toda la logica interna (comparaciones, `merge_asof`, dedup por
  `candle_time`) sea consistente entre timeframes — y lo es, porque todos los
  timeframes vienen del mismo reloj de servidor. Pero la hora "UTC" que ves
  en la base de datos puede estar desplazada respecto a UTC real (tipicamente
  0 a 3 horas, segun el broker, y a veces con un salto extra por DST que no
  coincide con el DST de tu zona). `backtest.py` estima ese offset
  comparando el ultimo tick contra la hora del sistema y lo reporta en
  `backtest_diagnostics.txt`; ajustalo mentalmente (o corrigelo en el
  analisis) si necesitas horas exactas en UTC real.

## Fase 2 — Capa macro (ingesta, aislada)

`macro_engine.py` es un modulo **totalmente independiente** de todo lo de
arriba: no importa `smc_engine.py` ni `database.py`, y no calcula ningun
"score" ni bias combinado ni ventana de no-trade. Eso es trabajo de una
fase posterior, pendiente de revisar el backtest de Fase 1. Hoy solo
descarga, parsea, cachea y valida cuatro fuentes de datos macro, cada una
aislada de las demas (si una API esta caida, las otras tres se siguen
intentando igual).

### Las cuatro fuentes

1. **Real yields** — FRED, serie `DFII10` (TIPS a 10 anos, real yield ya
   calculado por FRED) + `DGS10` (nominal, solo de contexto).
2. **DXY** — `yfinance` (ticker `DX-Y.NYB`) como primera opcion. **Ojo**:
   ese ticker especifico tiene fallos de fiabilidad documentados en Yahoo
   Finance (HTTP 500/429 recurrentes solo en `DX-Y.NYB`, mientras otros
   tickers funcionan bien —
   [issue #2721 en ranaroussi/yfinance](https://github.com/ranaroussi/yfinance/issues/2721)).
   Por eso hay un fallback automatico a [Stooq](https://stooq.com)
   (`dx.f`, CSV publico sin API key) si yfinance falla o devuelve datos
   vacios. Si en tu maquina yfinance funciona sin problemas, no notaras el
   fallback; si falla, `macro_engine.py` lo hace transparente y lo deja
   registrado en `notas`/logs de cual fuente vino cada dato.
3. **COT (posicionamiento)** — CFTC Disaggregated Futures-Only para oro
   (COMEX, codigo de contrato `088691`), via el dataset publico de Socrata
   (`publicreporting.cftc.gov`, sin API key). Se calcula la posicion neta
   de "managed money" (largos - cortos) y su percentil sobre los ultimos 3
   anos (`>= percentil 90` o `<= percentil 10` se marca como
   `extreme="long"`/`"short"`). El CFTC publica los viernes a las 15:30 ET,
   con posiciones al martes anterior — el `report_date` guardado es el del
   martes, no el del viernes de publicacion.
4. **Calendario de alto impacto** — NFP y CPI via el calendario de
   publicaciones de FRED (`fred/releases/dates`, `release_id=50` y `=10`
   respectivamente), con la hora estandar de publicacion del BLS (8:30 AM
   ET) pegada encima porque FRED solo da la fecha, no la hora. FOMC via una
   lista estatica en `macro_config.py` (`FOMC_MEETING_DATES`): **no
   encontramos una API gratuita con calendario forward fiable** — Trading
   Economics exige plan de pago para el calendario de eventos futuros (su
   "guest key" gratuito solo expone series de muestra, no el calendario).
   La Fed publica su calendario anual de reuniones con mucha antelacion en
   [federalreserve.gov/monetarypolicy/fomccalendars.htm](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm);
   **las fechas en `FOMC_MEETING_DATES` no se verificaron contra esa pagina
   en vivo** (este entorno de desarrollo no tuvo acceso de red a
   `federalreserve.gov`) — revisalas ahi antes de confiar en ellas, y
   actualiza la lista manualmente 1-2 veces al ano.

### Configurar `.env` para la capa macro

Solo hace falta una clave nueva, `FRED_API_KEY` (Stooq y el CFTC Socrata no
requieren API key):

1. Crea una cuenta gratuita en https://fredaccount.stlouisfed.org/
2. Una vez logueado, ve a https://fredaccount.stlouisfed.org/apikeys y pulsa
   "Request API Key" (uso no comercial, es instantaneo, no requiere
   aprobacion manual).
3. Copia la clave a tu `.env`:
   ```
   FRED_API_KEY=tu_clave_de_32_caracteres
   ```

### Cache local (`data/macro_cache.db`)

Cada fuente se cachea en su propia tabla `macro_snapshots` (base de datos
SQLite separada de `data/signals.db`, ver `macro_database.py`), con un
tiempo de frescura distinto por fuente (`CACHE_MAX_AGE_HOURS` en
`macro_config.py`): ~20h para real yields/DXY, ~4 dias para COT (semanal),
~12h para el calendario. Dentro de esa ventana, `fetch_*()` no vuelve a
golpear la API — usa lo que ya esta guardado.

### Uso

```bash
# Sanity check en vivo: descarga una vez cada fuente (ignora cache) y valida
# que la forma/rango de los datos es la esperada. Codigo de salida != 0 si
# alguna fuente falla.
python macro_engine.py --check

# Descarga (o usa cache si esta fresca) las 4 fuentes y las guarda.
python macro_engine.py --collect
python macro_engine.py --collect --no-cache   # fuerza descarga fresca
```

Cada fuente falla de forma aislada: si FRED esta caido, `--check`/`--collect`
igual intentan DXY, COT y el calendario, y reportan `[FALLO] real_yields: ...`
solo para esa fuente sin tumbar el resto del proceso.

### Limitaciones conocidas / sin verificar en vivo

Este modulo se desarrollo en un entorno sin acceso de red a
`api.stlouisfed.org`, `query1.finance.yahoo.com`, `stooq.com` ni
`publicreporting.cftc.gov` (proxy de salida bloqueado), asi que **nada de
esto se pudo probar contra las APIs reales** — solo con datos sinteticos
mockeados (`tests/test_macro_engine.py`, 30+ tests de parseo/cache/percentil/
zona horaria, ninguno golpea la red). Antes de confiar en el modulo, corre
`python macro_engine.py --check` en una maquina con acceso a internet y
revisa la salida. Puntos concretos a vigilar:

- **Nombres de campo del CFTC**: el dataset de Socrata usa (segun
  documentacion y scrapers publicos) `m_money_positions_long_all` /
  `m_money_positions_short_all` para las posiciones de managed money. El
  codigo prueba esos nombres con un fallback a variantes `_old`, y si
  ninguno existe lanza un error explicito listando los campos que si
  llegaron, en vez de devolver silenciosamente un numero incorrecto. Si
  `--check` falla en `cot_gold` con un error de "Ninguno de los campos
  esperados...", el dataset cambio de esquema y hay que ajustar
  `_MM_LONG_FIELD_CANDIDATES`/`_MM_SHORT_FIELD_CANDIDATES` en
  `macro_engine.py`.
- **Filtro de contrato CFTC**: se filtra primero por
  `cftc_contract_market_code='088691'` (codigo de gold COMEX) y, si no
  devuelve filas, cae a un filtro por nombre exacto
  (`GOLD - COMMODITY EXCHANGE INC.`). Si ambos fallan, el error lo dice
  explicitamente en vez de devolver una lista vacia silenciosa.
- **Sintaxis SoQL exacta** (`$where` con comparacion de fecha sobre
  `report_date_as_yyyy_mm_dd`) no se pudo probar contra el endpoint real.
- **FOMC**: ver arriba — lista estatica sin verificar contra
  federalreserve.gov.
- **DXY via yfinance**: el fallback a Stooq tampoco se pudo probar contra
  la red real; se probo solo el parseo del formato CSV de Stooq con texto
  sintetico.

## Correr las pruebas

```bash
pytest tests/ -v
```

Las pruebas de Fase 1 usan datos OHLC **sinteticos** (random walk generado
con semilla fija, mas variantes con huecos de precio y velas planas) para
comprobar que `smc_engine.py` no rompe con datos raros; no sustituyen al
backtest contra historico real. Las pruebas de Fase 2
(`tests/test_macro_engine.py`) prueban parseo, cache, percentil y
conversion de zona horaria con payloads sinteticos y funciones mockeadas,
sin tocar la red; no sustituyen a `python macro_engine.py --check`.
