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

El programa pedira unicamente:

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

La respuesta cruda, el access token, el id de usuario, el NIF, el email, el device ID, `passKey`, `X-ClientId` y la contrasena no se imprimen. `passKey` y `X-ClientId` se leen del keyring local o de variables de entorno, y solo el device ID generado se guarda en `private/`.

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
GET https://openapi.emtmadrid.es/v2/transport/bicimad/stations/
```

Ejecuta el comando desde la raiz. En una terminal interactiva pedira solamente
el usuario/email y la contraseña de EMT OpenAPI; la contraseña se oculta.
Obtiene el `accessToken` con el login de MobilityLabs y lo usa para consultar
las estaciones, sin guardarlo ni mostrarlo:

```powershell
python .\tools\bicimad_probe\fetch_stations.py
```

Los nombres de salida se pueden cambiar; ambos se guardan dentro de
`tools/bicimad_probe/private/` y deben ser nombres de archivo, no rutas:

```powershell
python .\tools\bicimad_probe\fetch_stations.py `
  --raw-filename estaciones_raw.json `
  --normalized-filename estaciones_normalizadas.json
```

Por defecto se usan `stations_raw.json` y `stations_normalized.json`. Si vuelves
a ejecutar el comando con los mismos nombres, los archivos se reemplazan.

Se guardan ambos resultados dentro de `tools/bicimad_probe/private/`:

- `stations_raw.json`: respuesta original completa del endpoint.
- `stations_normalized.json`: identificador, numero, nombre, direccion,
  coordenadas y campos de disponibilidad/capacidad; omite datos auxiliares.

La carpeta `private/` esta excluida de Git; no copies ni publiques la respuesta
original.

### Ejecucion periodica en Linux con cron

Para ejecuciones no interactivas, configura las variables de entorno
`BICIMAD_EMT_EMAIL` y `BICIMAD_EMT_PASSWORD`. No incluyas las credenciales
directamente en la entrada de cron. Una opcion es guardar las dos variables en
`tools/bicimad_probe/private/emt_credentials.env`, con sintaxis de shell:

```sh
BICIMAD_EMT_EMAIL='tu-correo'
BICIMAD_EMT_PASSWORD='tu-contrasena'
```

Restringe el acceso al archivo:

```sh
chmod 600 tools/bicimad_probe/private/emt_credentials.env
```

Anade esta entrada con `crontab -e`, sustituyendo la ruta del repositorio y
ajustando las rutas de `python3` y `flock` si fuera necesario. Se ejecuta cada
cinco minutos, evita ejecuciones simultaneas y anade la salida a un log privado:

```cron
BICIMAD_REPO=/ruta/absoluta/al/repositorio
*/5 * * * * cd "$BICIMAD_REPO" && set -a && . "$BICIMAD_REPO/tools/bicimad_probe/private/emt_credentials.env" && set +a && /usr/bin/flock -n "$BICIMAD_REPO/tools/bicimad_probe/private/fetch_stations.lock" /usr/bin/python3 "$BICIMAD_REPO/tools/bicimad_probe/fetch_stations.py" --raw-filename stations_raw.json --normalized-filename stations_normalized.json >> "$BICIMAD_REPO/tools/bicimad_probe/private/fetch_stations.log" 2>&1
```

Los nombres por defecto se pueden omitir de la linea de cron. Con nombres fijos,
cada ejecucion correcta reemplaza los archivos de salida anteriores. Si no hay
variables de credenciales y no existe una terminal interactiva, el programa
falla de forma segura en vez de quedarse esperando una entrada.

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
