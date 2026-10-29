# Integracion de seguridad con Wazuh

## Alcance inicial

NeuroFlex emite un archivo local JSONL para Wazuh cuando se configura
`WAZUH_AUDIT_LOG_PATH`. Cada linea contiene un evento de seguridad minimizado:

- fecha y hora del servidor;
- accion y resultado;
- ID y rol local del actor, si existe;
- IP de origen, si esta disponible;
- tipo de recurso y una huella HMAC estable para correlacionarlo.

No se exportan nombres de usuario, correos, identificadores de sesion, datos
del paciente, metricas clinicas, snapshots, PDFs, contrasenas, tokens ni
metadatos de auditoria.

Los primeros casos de uso son: inicio de sesion exitoso o fallido, denegacion de permisos, cambios
de cuenta y rol, acceso a sesiones, ejecucion de inferencia, ciclo completo de
informes y exportacion de auditoria.

## Configuracion de NeuroFlex

En el archivo `.env` del servidor, defina una ruta local que pueda escribir el
proceso de NeuroFlex y leer el servicio Wazuh. Use una clave aleatoria unica:

```dotenv
WAZUH_AUDIT_LOG_PATH=C:\ProgramData\NeuroFlex\logs\security-audit.jsonl
WAZUH_AUDIT_HASH_KEY=secreto-largo-aleatorio-no-compartido
```

En Linux se recomienda una ruta como `/var/log/neuroflex/security-audit.jsonl`
con permisos de escritura solo para la cuenta de servicio de NeuroFlex y
lectura solo para el agente Wazuh.

La ruta de `WAZUH_AUDIT_LOG_PATH` debe coincidir exactamente con la ruta
`<location>` del agente. Reinicie NeuroFlex despues de modificar `.env`.

## Prueba local en Windows

1. Instale Docker Desktop con motor WSL 2 y despliegue el stack `single-node`
   de [Wazuh Docker](https://documentation.wazuh.com/current/deployment-options/docker/wazuh-container.html).
   Genere los certificados y ejecute `docker compose up -d` desde la carpeta
   `single-node`. El panel queda en `https://localhost/`.
2. Instale el agente Wazuh para Windows desde **Agents management > Summary >
   Deploy new agent**. Para un servidor Docker en el mismo PC, indique
   `127.0.0.1` como direccion del manager y confirme que el agente figure
   **Active**. El servicio Windows se llama `WazuhSvc`.
3. Configure `WAZUH_AUDIT_LOG_PATH` y `WAZUH_AUDIT_HASH_KEY` en el `.env` de
   NeuroFlex. Genere una clave aleatoria unica y mantengala fuera de Git.
   Inicie NeuroFlex y realice una accion auditada, por ejemplo un intento de
   inicio de sesion. Compruebe que el archivo JSONL recibe una linea nueva.
4. En `C:\Program Files (x86)\ossec-agent\ossec.conf`, agregue el bloque
   `<localfile>` de la seccion siguiente, usando la ruta real del JSONL.
   Reinicie el agente con `Restart-Service WazuhSvc` desde PowerShell como
   administrador. En `ossec.log` debe aparecer `Analyzing file` con esa ruta.
5. Para mostrar estos eventos como alertas, cree el archivo de reglas
   `neuroflex_rules.xml` desde **Server management > Rules**:

   ```xml
   <group name="neuroflex,">
     <rule id="100100" level="5">
       <decoded_as>json</decoded_as>
       <field name="observer.product">^NeuroFlex Dashboard$</field>
       <description>Evento de auditoria de NeuroFlex</description>
     </rule>
   </group>
   ```

   Reinicie `wazuh.manager`, genere **otro** evento en NeuroFlex y busque
   `rule.id:100100` en **Threat hunting**. La regla de ejemplo alerta sobre
   cada evento para verificar el flujo; ajuste las reglas antes de usarlo en
   produccion.

Los eventos anteriores a la creacion de la regla pueden no aparecer como
alertas. El JSONL, la base SQLite y la clave HMAC son datos locales y no se
deben agregar al repositorio.

## Configuracion del agente Wazuh

Agregue al `ossec.conf` del agente instalado en el mismo host:

```xml
<localfile>
  <location>C:\ProgramData\NeuroFlex\logs\security-audit.jsonl</location>
  <log_format>json</log_format>
  <label key="@source">neuroflex-dashboard</label>
  <label key="application">neuroflex</label>
</localfile>
```

Reinicie el agente Wazuh y compruebe que recibe un evento de prueba. Las reglas
iniciales deben alertar, al menos, ante `authorization_denied`, fallos de
generacion de informe y una frecuencia anomala de acciones de autenticacion o
exportacion.

## Operacion segura

- Mantener el archivo fuera de directorios publicados por el servidor web.
- Rotarlo mediante la politica operativa del host y verificar que Wazuh sigue
  leyendo el archivo nuevo.
- Restringir acceso al archivo y a `WAZUH_AUDIT_HASH_KEY`.
- La huella HMAC permite correlacionar un recurso dentro del SIEM sin revelar
  su identificador original. No cambie la clave mientras se requiera esa
  correlacion historica.
