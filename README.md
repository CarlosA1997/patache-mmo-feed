# Patache MMO Feed

Recolector automatico de datos SMTR Patache para el Meteo Marino Operacional.

El flujo se ejecuta cada 10 minutos y publica solamente JSON meteorologico en
GitHub Pages. Las credenciales se guardan como secretos de GitHub Actions:

- `PATACHE_USER`
- `PATACHE_PASSWORD`

Nunca se deben escribir credenciales en archivos, commits, issues ni registros.

La salida consumible por el MMO es:

`https://USUARIO.github.io/patache-mmo-feed/patache_mmo_source.json`
