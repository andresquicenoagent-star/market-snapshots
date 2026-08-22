# market-snapshots

Snapshots de mercado calculados cada 15 minutos y publicados aqui.

**Este repo es publico a proposito y solo contiene datos publicos de mercado.** No hay nada
personal: ni operaciones, ni planes de entrada, ni stops, ni la checklist de decision. Todo
eso vive en un repo privado aparte.

## Por que existe

Los entornos de claude.ai no tienen salida a las APIs de los exchanges (OKX, Binance,
Coinbase y Kraken responden 403 o no responden), pero si pueden llegar a `github.com`.

En vez de que Claude vaya a buscar los datos, los datos vienen aqui: GitHub Actions ejecuta
el motor en un runner con internet completo y publica el resultado. Claude solo tiene que
clonar este repo y leer un JSON.

Efecto secundario util: no depende de que ningun ordenador concreto este encendido.

## Contenido

- `get_market_snapshot.py` — el motor. Descarga velas de OKX (API publica, sin API key) y
  calcula EMA 10/21/55, ADX(14) + DI, ATR(14), Squeeze Momentum, rango y posicion en el
  rango, POC / value area, swings y estructura del momentum, en Diario / 4h / 1h. Solo
  libreria estandar de Python.
- `.github/workflows/snapshot.yml` — la tarea programada.
- `snapshots/latest-<ACTIVO>.json` — el ultimo snapshot de cada activo. Se sobrescribe en
  cada ejecucion; el historico no se guarda aqui.

Activos: ETH-USDT, BTC-USDT, SOL-USDT.

## Frescura de los datos

Cada JSON trae `generadoUtc`. **Antes de usarlo hay que mirar ese campo.** Si el snapshot
tiene mas de ~45 minutos, la tarea programada puede estar caida y los numeros ya no
representan el mercado actual.

Los indicadores se calculan sobre **velas cerradas**; la vela viva se ignora a proposito.
`precioActual` es el precio en vivo del momento de la ejecucion, solo como referencia.

## Uso manual

```
python3 get_market_snapshot.py --inst-id ETH-USDT --out-file snapshots/latest-ETHUSDT.json
```

Pasa siempre `--out-file`: la ruta por defecto del script asume la estructura de carpetas del
repo privado, no la de este.

## Sincronia del motor

`get_market_snapshot.py` es **byte a byte identico** al del repo privado. Si se cambia en un
sitio, hay que cambiarlo en el otro: un indicador que difiera entre los dos rompe la premisa
de que el sistema da el mismo veredicto en cualquier dispositivo.

Comprobacion:

```
sha256sum get_market_snapshot.py
```

## Aviso

Esto no es asesoria financiera ni una fuente de señales. Son indicadores calculados sobre
datos publicos.
