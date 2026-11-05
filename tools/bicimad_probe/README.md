# BiciMAD Probe

Herramientas locales y separadas de Flutter para estudiar capturas propias y hacer pruebas de lectura de la api de MPass.

No modifican la app oficial, no desactivan certificate pinning y no intentan eludir controles de integridad. No guardes credenciales, tokens, HAR reales ni respuestas crudas en el repositorio.

## Instalacion de Dependencias

Desde la raiz del repositorio:

```powershell
python -m pip install -r .\tools\bicimad_probe\requirements.txt
```

## Configuracion Tecnica Inicial

Antes del primer uso con login, guarda una sola vez `passKey` y `X-ClientId` en el almacen seguro de credenciales de Windows:

```powershell
python .\tools\bicimad_probe\configure_local_probe.py
```

El programa pedira ambos valores con `getpass`, no los mostrara y no los guardara en archivos del repositorio.

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

La respuesta cruda, el access token, el id de usuario, el NIF, el email, el device ID, `passKey`, `X-ClientId` y la contrasena no se imprimen. Solo `passKey` y `X-ClientId` se guardan en keyring, y solo el device ID generado se guarda en `private/`.

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

Ejecuta el comando desde la raiz. Pedira solamente el usuario/email y la
contraseña de EMT OpenAPI; la contraseña se oculta. Obtiene el `accessToken` con
el login de MobilityLabs y lo usa para consultar las estaciones, sin guardarlo
ni mostrarlo:

```powershell
python .\tools\bicimad_probe\fetch_stations.py
```

Se guardan ambos resultados dentro de `tools/bicimad_probe/private/`:

- `stations_raw.json`: respuesta original completa del endpoint.
- `stations_normalized.json`: identificador, numero, nombre, direccion,
  coordenadas y campos de disponibilidad/capacidad; omite datos auxiliares.

La carpeta `private/` esta excluida de Git; no copies ni publiques la respuesta
original.

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
