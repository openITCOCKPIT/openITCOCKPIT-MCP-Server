# Abgleich MCP-Server vs. angeforderte Funktionsliste

Stand: 2026-08-03. Alle Aussagen gegen Backend-Code (`/opt/openitc/frontend/src/`) und Angular-Frontend verifiziert.

> **Update 2026-08-03:** Alle unten als "Fehlt" markierten Read- und Write-Funktionen sind
> mittlerweile umgesetzt (siehe README.md für die vollständige, aktuelle Tool-Liste) und
> live gegen die Testumgebung verifiziert (inkl. Anlegen + Löschen von Testobjekten für jedes
> Write-Tool). Ausnahme: `GetServiceCheckHistory` musste einen serverseitigen Bug in
> openITCOCKPIT 5.6.1 umgehen (`ServicechecksController` crasht mit HTTP 500 auf einen falschen
> SQL-Alias im Standard-Sort) - per explizitem `sort`-Parameter workaroundet, siehe Code-Kommentar
> in `oitc_mcp.py`. Die Tabellen unten bleiben als Snapshot des Rechercheergebnisses vor der
> Umsetzung erhalten.

## GET / Read

| Bereich | Status | Anmerkung |
|---|---|---|
| Hosts | **Teilweise** | `GetHostinfo(hostname)` — nur exakter Name, kein ID/UUID/Keyword/Hostgroup-Filter. |
| Services | **Teilweise** | `getServicesbyState(state)` — nur nach State, keine gezielte Abfrage "Service X auf Host Y". |
| Commands | **Fehlt** | Kein Tool. Backend bereit: `CommandsController::index()`, Filter `Commands.name`/`id`/`command_type`. |
| Templates (Host/Service) | **Fehlt** | Kein Tool. Backend bereit: `HosttemplatesController`/`ServicetemplatesController::index()`, Filter `name`/`id`/`hosttemplatetype_id`. |
| Hostgroups | ✅ **Vorhanden** | `GetHostgroups()`. |
| Contacts | **Fehlt** | Kein Tool. Backend bereit: `ContactsController::index()`, Filter `name`/`email`/`phone`/`id`. |
| Contact Groups | **Fehlt** | Kein Tool. Backend bereit: `ContactgroupsController::index()`. |
| Service Template Groups | **Fehlt** | Kein Tool. Backend bereit: `ServicetemplategroupsController::index()`. |
| Software Inventory | **Fehlt** | **Wichtig:** Das ist NICHT `Patchstatus` (das liefert nur Update-Zähler pro Host). Die eigentliche Paketliste kommt aus `PackagesController::host_linux_packages($hostId)` / `host_windows_apps($hostId)` / `host_macos_apps($hostId)` — je nach OS-Typ unterschiedliche Endpunkte, unterschiedliche Felder (Linux hat `needs_update`/`is_security_update`, Windows/macOS nicht). |
| Patchstatus | ✅ **Vorhanden** | `getDetailedSecurityUpdateStatus()`, `getDetailedCommonUpdateStatus()`. |
| Container Structures | **Fehlt** | Backend bereit, aber **kein einzelner Endpunkt liefert eine fertige verschachtelte Baumstruktur**. Optionen: `showDetails($id, asTree=false)` → flache rekursive Liste mit `parent_id` (Client müsste Baum selbst rekonstruieren), oder `loadContainersByContainerId` → Lazy-Load pro Ebene. Für ein LLM ist die flache Liste vermutlich praktikabler als mehrfache Lazy-Load-Calls. |
| Logentries | **Teilweise** | `GetLast24hLogentries()` — fest auf 24h, kein Host-/Type-Filter, kein wählbarer Zeitraum. |
| Check History | **Fehlt** | Eigenes Konzept, getrennt von Statehistory: **jede einzelne Check-Ausführung** (Output, Latenz, Execution-Time, Rohperfdata) über `HostchecksController`/`ServicechecksController`, Filter `from`/`to`, `states[]`, `host_uuid`/`service_uuid`. |
| Statehistory | **Fehlt** | Eigenes Konzept: nur **State-Wechsel** (nicht jeder Check) über `StatehistoriesController`, Filter `states[]`, `stateTypes[]` (hard/soft), `from`/`to`. |

## Write / Create

| Bereich | Status | Komplexität / Anmerkung |
|---|---|---|
| Hosts | **Teilweise** (gated) | `CreateHost()` existiert, hinter `OITC_ENABLE_WRITE_TOOLS`. Nur `add`, kein `edit`/`delete`. Hardcodierte `container_id=9`/`hosttemplate_id=1`. |
| Services | **Fehlt** | Backend hat `ServicesController::add()`, Payload-Felder für die Service-Entity wurden in dieser Runde noch nicht im Detail erhoben (nur Filter-Felder aus Phase 1/2) — bräuchte einen kurzen Nachrecherche-Pass vor der Umsetzung. |
| Commands | **Fehlt** | **Niedrig.** Payload: `name`, `command_line` (Pflicht), `command_type` (1=Check, 2=Hostcheck, 3=Notification, 4=Eventhandler; Pflicht), `human_args`/`description` (optional). Kompakt, wenig Fallstricke. |
| Templates (Host/Service) | **Fehlt** | **Hoch.** 15-20 Pflichtfelder pro Entität (Check-/Retry-Intervalle, Notification-Optionen mit "mind. eine Option muss an sein"-Regeln, Flap-Detection-Schwellwerte, `contacts`/`contactgroups` als `{_ids:[...]}`). Größtes Fehlerpotenzial der ganzen Liste — ein LLM müsste sehr viele domänenspezifische Werte korrekt raten/erfragen. |
| Hostgroups | **Fehlt** | **Mittel.** Name liegt unter `container.name` (nicht auf der Entität selbst!), zusätzlich `container.parent_id` Pflicht. `description`/`hostgroup_url` optional. |
| Contacts | **Fehlt** | **Hoch.** Pflicht: `name`, `email` oder `phone`, `host_timeperiod_id`, `service_timeperiod_id`, `host_commands`/`service_commands` (je mind. 1 `_id`, das sind Notification-Commands!), mind. eine Host- und eine Service-Notification-Option aktiv, `containers` (mind. 1 `_id`). Viele Fremdschlüssel auf andere Entitäten (Timeperiods, Commands, Containers), die vorher aufgelöst werden müssten. |
| Contact Groups | **Fehlt** | **Mittel.** `container.name`+`container.parent_id` Pflicht, `contacts` mind. 1 `_id` Pflicht. |
| Service Template Groups | **Fehlt** | **Mittel.** `container.name`+`container.parent_id` Pflicht, `servicetemplates` mind. 1 `_id` Pflicht. |
| Host anlegen mit Agent Pull Mode | **Fehlt** | **Hoch, zwei Schritte.** (1) Normaler `HostsController::add()` — `host_type` bleibt Standard, es gibt **kein** Agent-spezifisches Host-Feld. (2) Separater Call `AgentconnectorController::config()` (POST, `host_id`) mit `use_push_mode=false`, `port` (Default 3333), `use_https`/`use_https_verify`, optional `username`/`password` (Basic-Auth gegen den Agenten). Kein dediziertes Token/Secret für Pull Mode gefunden — Authentifizierung läuft über optionale Basic-Auth oder AutoTLS-Zertifikate. Realistisch nur als zwei nacheinander laufende MCP-Tool-Calls (oder ein kombiniertes Tool, das beide Schritte intern ausführt) abbildbar. |

## Einschätzung

- Die Read-Lücken (Commands, Templates, Contacts, Contact Groups, Service Template Groups, Software Inventory, Container Structures, Check History, Statehistory) sind alle **technisch unkompliziert** — reine Index-Abfragen mit bekannten Filtern, ähnlich den bereits gebauten Tools. Realistischer Umfang: 8-10 neue Read-Tools.
- Bei den Write-Lücken ist die Bandbreite groß: Commands ist trivial, Hostgroups/Contactgroups/Servicetemplategroups sind mittel (Container-Pattern muss einmal korrekt implementiert werden, dann wiederverwendbar), aber **Templates und Contacts sind hochkomplex** mit vielen Pflichtfeldern, Cross-Referenzen zu anderen Entitäten (Timeperiods, Commands, Containers) und "mindestens eine Option muss aktiv sein"-Regeln, die ein LLM ohne Rückfragen kaum zuverlässig richtig ausfüllen wird. Der **Agent-Pull-Mode-Host** ist ein Sonderfall mit zwei getrennten API-Calls.
- Alle neuen Write-Tools würden hinter `OITC_ENABLE_WRITE_TOOLS` liegen (Standard: aus), wie schon bei `CreateHost`.

**Empfehlung**: Read-Tools zuerst (geringes Risiko, hoher Nutzen), dann Write in Stufen: erst Commands + Hostgroups/Contactgroups/Servicetemplategroups (Container-Pattern einmal solide bauen), dann erst Contacts/Templates/Agent-Pull-Mode angehen, ggf. mit zusätzlichen Rückfrage-Mechanismen im Tool-Design (z.B. Pflicht-IDs vorher per Read-Tool auflösen lassen).
