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

## Correr las pruebas

```bash
pytest tests/ -v
```

Las pruebas usan datos OHLC **sinteticos** (random walk generado con semilla
fija, mas variantes con huecos de precio y velas planas) para comprobar que
`smc_engine.py` no rompe con datos raros. No sustituyen al backtest contra
historico real.
