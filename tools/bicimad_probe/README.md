# BiciMAD Probe

Herramientas locales y separadas de Flutter para estudiar capturas propias y hacer pruebas de lectura de la api de MPass.

No modifican la app oficial, no desactivan certificate pinning y no intentan eludir controles de integridad. No guardes credenciales, tokens, HAR reales ni respuestas crudas en el repositorio.

## Instalacion de Dependencias

Desde la raiz del repositorio:

```powershell
python -m pip install -r .\tools\bicimad_probe\requirements.txt
```

## Configuracion Tecnica Inicial

Antes del primer uso con login, puedes guardar una sola vez `passKey` y `X-ClientId` en el almacen seguro de credenciales disponible en tu sistema:

```powershell
python .\tools\bicimad_probe\configure_local_probe.py
```

El programa pedira ambos valores con `getpass`, no los mostrara y no los guardara en archivos del repositorio. En Linux de escritorio, esto requiere un keyring compatible y desbloqueado.

En un servidor Linux sin keyring, el flujo de login tambien acepta estas variables de entorno:

```text
BICIMAD_PASS_KEY
BICIMAD_X_CLIENT_ID
```

Configura ambas mediante el gestor de secretos de tu entorno y ejecuta `fetch_trips_with_login.py`. Si ambas tienen valor, se usan en lugar del keyring; si ninguna tiene valor, se consulta el keyring local. Si solo una tiene valor, el programa falla sin intentar mezclar fuentes. No guardes los valores en Git ni los incluyas en comandos que queden en el historial de la shell; las variables de entorno pueden ser visibles para procesos con permisos suficientes.

Para no introducir el email y la contraseña de la cuenta en cada ejecucion,
puedes proporcionar ambas variables de entorno:

```text
BICIMAD_EMT_EMAIL
BICIMAD_EMT_PASSWORD
```

Si ambas estan configuradas, se usan en lugar de los prompts; si solo una esta
configurada, el programa falla sin pedir ni mezclar credenciales. Esto permite
ejecuciones no interactivas cuando tambien esta disponible la configuracion
tecnica.

`passKey` y `X-ClientId` deben obtenerse de una captura propia y legitima. No deben compartirse, publicarse, registrarse ni incluirse en Git.

Para eliminar la configuracion tecnica local:

```powershell
python .\tools\bicimad_probe\configure_local_probe.py --clear
```

## Uso Normal Con Login

Ejecutar desde la raiz del repositorio:

```powershell
python .\tools\bicimad_probe\fetch_trips_with_login.py
```

Si las variables de cuenta no estan configuradas, el programa pedira:

- Email.
- Contrasena, oculta con `getpass`.

El `deviceId` se crea o reutiliza automaticamente en:

```text
tools/bicimad_probe/private/generated_device_id.txt
```

El valor no se muestra en consola y queda dentro de `private/`.

Este flujo realiza, en una sola ejecucion, tres llamadas de solo lectura:

1. Login MPass.
2. Consulta de `userdata` para obtener exclusivamente `data.DS_DN`.
3. Consulta de viajes.

Usa una contrasena actual y nunca una contrasena que haya sido expuesta. Este flujo es experimental y puede cambiar si MPass o BiciMAD modifican su API. Solo debe utilizarse para consultar los viajes de la cuenta propia. No implementa reservas, desbloqueos, pagos ni operaciones de escritura.

Si funciona, solo se escribe:

```text
tools/bicimad_probe/private/trips_normalized.json
```

La respuesta cruda, el access token, el id de usuario, el NIF, el email, el device ID, `passKey`, `X-ClientId` y la contrasena no se imprimen. El access token, el id de usuario y su caducidad se guardan en `tools/bicimad_probe/private/mpass_token_cache.json` con permisos restrictivos (0600 en sistemas compatibles) y se reutilizan mientras sigan vigentes, con un margen de seguridad de un minuto. La entrada se vincula mediante un hash al email, la configuracion tecnica y el dispositivo; nunca se guarda la contrasena. Si la cache no se puede leer o escribir, el flujo continua con un login normal. Para forzar un login nuevo, elimina el archivo de cache. `passKey` y `X-ClientId` se leen del keyring local o de variables de entorno, y el device ID generado se guarda en `private/`.

## Diagnostico Temporal de Bicicleta y Precio

Para inspeccionar de forma sanitizada que campos devuelve realmente el endpoint
de viajes, ejecuta desde la raiz:

```powershell
python .\tools\bicimad_probe\diagnose_trip_fields.py
```

El comando pide solamente el correo y la contrasena, reutiliza la configuracion
tecnica y el `deviceId` locales, y realiza el mismo flujo de solo lectura
`login -> userdata -> trips`. La respuesta se analiza solo en memoria: no se
guarda el JSON original ni se imprimen valores de bicicleta, viajes, estaciones,
fechas o identidad. La salida contiene exclusivamente nombres de campos
candidatos, tipos, formatos sanitizados y porcentajes agregados.

## Diagnostico de Paginacion del Historico

La inspeccion estatica de la aplicacion oficial confirma este mecanismo para
`GET /v2/bicimad/trips/`:

1. Primera peticion sin cabecera de paginacion.
2. Siguientes peticiones con la cabecera HTTP `page`: `1`, `2`, `3`, etc.
3. La aplicacion oficial deja de cargar cuando recibe una pagina vacia.

Para medir cuantos viajes permite recuperar realmente la cuenta propia:

```powershell
python .\tools\bicimad_probe\diagnose_trip_pagination.py
```

El diagnostico pide solo correo y contrasena, reutiliza la configuracion tecnica
y el `deviceId` locales, y realiza exclusivamente login, userdata y lecturas de
viajes. Deduplica en memoria por `trip_id`, espera brevemente entre paginas y se
detiene ante una pagina vacia o corta, fin explicito, repeticion completa, error
del backend o el limite local de seguridad de 100 peticiones.

Un cierre TLS `SSLZeroReturnError` durante una pagina provoca un unico reintento
del mismo `GET` tras una espera de 2 segundos. El informe contabiliza ese
reintento y conserva el error si vuelve a producirse. No se reintentan el login
ni `userdata`.

No persiste respuestas ni IDs. Su salida contiene solo conteos agregados, meses
aproximados del rango temporal y el motivo de parada. El limite puede ajustarse
sin superar 1000 paginas:

```powershell
python .\tools\bicimad_probe\diagnose_trip_pagination.py --max-pages 200
```

## Descarga Manual Con Access Token

`fetch_trips.py` hace una unica peticion de solo lectura:

```text
GET https://apiemtpay.emtmadrid.es/v2/bicimad/trips/
```

Este modo pide localmente `accessToken`, `email`, `userId`, `nif`, `deviceId` y `deviceModel`. No guarda esos valores, no los imprime y no vuelca cabeceras completas.

```powershell
python .\tools\bicimad_probe\fetch_trips.py
```

## Consulta de Estaciones

`fetch_stations.py` consulta el catalogo y la disponibilidad de estaciones con
este endpoint de solo lectura:

```text
GET https://apiemtpay.emtmadrid.es/v2/bicimad/stations/
```

Ejecuta el comando desde la raiz. Usa el mismo flujo de login MPass que
`fetch_trips_with_login.py`: pide el email y la contraseña (oculta) o los lee de
`BICIMAD_EMT_EMAIL` y `BICIMAD_EMT_PASSWORD`; reutiliza `passKey`, `X-ClientId`
y el `deviceId` locales, y consulta las estaciones con el token MPass sin
guardarlo ni mostrarlo:

```powershell
python .\tools\bicimad_probe\fetch_stations.py
```

El nombre de salida se puede cambiar; se guarda dentro de
`tools/bicimad_probe/private/` y debe ser un nombre de archivo, no una ruta:

```powershell
python .\tools\bicimad_probe\fetch_stations.py `
  --raw-filename stations_raw_20261107_120000.json
```

Por defecto se crea un archivo `stations_raw_YYYYMMDD_HHMMSS.json` nuevo en cada
ejecucion. Si se indica un nombre personalizado para importarlo a Delta, debe
mantener ese formato.

Se guarda la respuesta original completa del endpoint en
`tools/bicimad_probe/private/`. La normalizacion se realiza durante la
importacion a Delta; no se crea un JSON normalizado intermedio.

Importa un snapshot o todos los snapshots del directorio con:

```powershell
python .\tools\bicimad_probe\stations_raw_json_to_delta.py `
  .\tools\bicimad_probe\private `
  .\tools\bicimad_probe\private\stations_delta
```

El importador normaliza los campos de identificacion, ubicacion y
disponibilidad/capacidad, omite datos auxiliares y agrega los metadatos de
captura a la tabla Delta.

La carpeta `private/` esta excluida de Git; no copies ni publiques la respuesta
original. Igual que el flujo de viajes, acepta `BICIMAD_EMT_EMAIL` y
`BICIMAD_EMT_PASSWORD` para ejecuciones no interactivas.

## Normalizacion

Por cada viaje se conservan solo estos campos:

- `external_id`
- `origin_station_number`
- `origin_station_name`
- `destination_station_number`
- `destination_station_name`
- `started_at`
- `ended_at`
- `duration_minutes`
- `duration_text`

Se descartan datos personales, financieros, dispositivo, bicicleta, coordenadas y penalizaciones.

## Flujo HAR Previo

Guarda el HAR original solo en `tools/bicimad_probe/private/`. Esa carpeta esta ignorada por Git salvo `.gitkeep`.

Sanitiza la captura:

```powershell
python .\tools\bicimad_probe\sanitize_har.py `
  .\tools\bicimad_probe\private\capture.har `
  .\tools\bicimad_probe\private\capture.sanitized.har
```

Analiza solo el HAR sanitizado:

```powershell
python .\tools\bicimad_probe\analyze_har.py `
  .\tools\bicimad_probe\private\capture.sanitized.har
```

## Pruebas

```powershell
python -m unittest discover .\tools\bicimad_probe\tests
```
