# openITCOCKPIT MCP Server — Phase 2: Gap-Analyse

Stand: 2026-08-03. Testumgebung: `10.211.55.120` (openITCOCKPIT 5.6.1, Ubuntu Noble, arm64).
Alle Aussagen unten sind entweder durch Backend-Quellcode (`/opt/openitc/frontend/src/`), Angular-Frontend-TS (`/opt/openitc/frontend-angular/source/`) oder einen echten API-Aufruf gegen die Testumgebung verifiziert — nicht geraten.

## 0. Rahmendaten

- **MCP-SDK**: `fastmcp` (auf dem Testserver installiert: `3.0.0b1`, dazu `mcp==1.26.0`). Lokal im Repo **nicht gepinnt** — kein `requirements.txt`/`pyproject.toml` vorhanden.
- **Transport**: Streamable HTTP (`mcp.run(transport="http", host="0.0.0.0", port=8000)`) — **ungebunden an localhost**, **keine Authentifizierung** auf MCP-Ebene. Jeder mit Netzwerkzugriff auf Port 8000 kann alle Tools inkl. `CreateHost` (Schreibzugriff) ohne weitere Anmeldung aufrufen.
- **Python-Kompatibilität**: Der Code nutzt `X | None`-Typannotationen (Zeile 21), was **Python ≥3.10 voraussetzt**. Lokal (macOS) ist nur Python 3.9.6 installiert — der Code kann dort nicht importiert werden. Lief nur, weil ich mit einer Stub-Version von `fastmcp` getestet und den echten Lauf auf dem Server (Python 3.12.3, `fastmcp` bereits installiert) durchgeführt habe.

## 1. Aktuell exponierte Tools — Live-Testergebnis

| Tool | Registriert als MCP-Tool? | Live-Test | Ergebnis |
|---|---|---|---|
| `GetLast24hLogentries` | ✅ | ✅ aufgerufen | Funktioniert. Liefert Host-/Service-Alerts der letzten 24h, korrekt geparst. |
| `GetHostinfo(hostname)` | ✅ | ✅ aufgerufen (existierender + nicht existierender Host) | Funktioniert korrekt (leeres Ergebnis bei unbekanntem Host ist korrektes Verhalten, kein Bug). |
| `getServicesbyState(state)` | ✅ | ✅ aufgerufen (`CRITICAL` + ungültiger Wert) | **Bug gefunden**, siehe Abschnitt 3. |
| `CreateHost(name, address, description)` | ✅ | ✅ aufgerufen (Host angelegt, ID 34, anschließend über API wieder gelöscht) | Funktioniert technisch, aber siehe Abschnitt 3 (fehlende Absicherung als Schreib-Tool). |
| `getDetailedSecurityUpdateStatus` | ✅ | ✅ aufgerufen | Funktioniert (leere Liste, da Testumgebung aktuell keine Security-Updates offen hat). |
| `getDetailedCommonUpdateStatus` | ✅ | ✅ aufgerufen | Funktioniert (leere Liste, gleicher Grund). |
| `getHostUpdateStatus(hostname)` | ❌ **kein `@mcp.tool`** | — | Toter Code — Funktion existiert, ist aber nicht als Tool registriert und über MCP nicht erreichbar. |
| `getUpdateStatus()` | ❌ **kein `@mcp.tool`** | — | Gleiches Problem. |

## 2. Endpunkt-Abdeckung vs. Backend-Realität

Untersucht wurden die Controller, die für Monitoring-Auswertung am relevantesten sind (17 im Detail per Subagent analysiert) plus eine vollständige Auflistung aller 74 Controller zur Einordnung. Nutzen-Einschätzung bezieht sich auf den Zweck "LLM soll Monitoring-Daten abfragen/korrelieren", wie im System-Prompt des MCP-Servers beschrieben.

| Bereich (Controller) | Status | Nutzen | Anmerkung |
|---|---|---|---|
| Hosts | **Teilweise abgedeckt** | — | Nur Filter auf `Hosts.name`. Filterbar wären zusätzlich u.a. `Hosts.id/uuid`, `Hoststatus.current_state`, `keywords`, `Hostgroups.id`, `problem_has_been_acknowledged`, `scheduled_downtime_depth` (siehe Tabelle 3). |
| Services | **Teilweise abgedeckt** | — | Nur Filter auf `Servicestatus.current_state`. Keine Möglichkeit, nach Host, Hostgroup, Servicegroup, Keyword oder Ack/Downtime-Status zu filtern. |
| Logentries | **Teilweise abgedeckt** | — | Nur letzte 24h, kein Host-Filter (`filter[Host.id]`), kein `logentry_type`-Filter. Zeitraum ist hart auf 24h codiert statt parametrisierbar. |
| Patchstatus | **Teilweise abgedeckt** | — | Nur die zwei Update-Flags. Kein Filter auf Hostname, OS-Typ, Reboot-Required einzeln abrufbar. |
| **Downtimes** | **Lücke** | **hoch** | Aktive/geplante Downtimes sind Kernbestandteil von Monitoring-Korrelation (im System-Prompt explizit gefordert). Kein Tool vorhanden. |
| **Acknowledgements** | **Lücke** | **hoch** | Ebenfalls im System-Prompt gefordert, komplett ungenutzt. |
| **Hostgroups / Servicegroups** | **Lücke** | **mittel–hoch** | Wichtig für gruppierte Auswertungen ("wie ist der Zustand der Gruppe X"), aktuell nur pro Einzel-Host/-Service abfragbar. |
| **Notifications** | **Lücke** | **mittel** | Für "wer wurde wann benachrichtigt"-Fragen relevant, rein lesend, einfach zu integrieren. |
| **Nagiostats** | **Lücke** | **mittel** | Systemweiter Monitoring-Engine-Status (Checks/Minute, Latenz) — nützlich für "ist das Monitoring selbst gesund". Rein lesend, keine Filter nötig. |
| Hostescalations / Serviceescalations | Lücke | niedrig | Eher Konfigurationsdaten als Live-Monitoring-Signal. |
| Contacts / Contactgroups | Lücke | niedrig | Für "wer ist zuständig"-Fragen ggf. mittel, aber kein akuter Bedarf laut System-Prompt. |
| Cronjobs / Changelogs / Hosttemplates / Commands | Lücke | niedrig | Admin-/Konfigurationsbereich, nicht Monitoring-Auswertung. |
| Alle übrigen (Automaps, Backups, Calendars, Containers, Eventlogs, Graphgenerators, Metrics, Statistics, Statusmaps/-pages, Systemsettings, Tenants, Timeperiods, Users/Usergroups, Wizards, u.a. — 74 Controller insgesamt) | **nicht im Detail untersucht** | vermutlich niedrig bis irrelevant für MCP-Zweck | Größtenteils Admin-UI/Konfiguration/Reporting-Rendering. Bei Bedarf gezielt nachanalysieren, keine pauschale Aussage ohne Code-Verifikation. |

## 3. Bugs / Schwachstellen — priorisiert

1. **[Hoch/Sicherheit] Hartkodierter API-Key im Quellcode, in Git-Historie über mehrere Commits.** `oitc_mcp.py:16` enthält den API-Key als Default-Wert für `os.environ.get(...)`. Er ist damit im Repo lesbar — und **zusätzlich in der Git-Historie mit einem älteren, ebenfalls funktionsfähigen Key** (Commit vor `d517e54`, andere Instanz `demo.openitcockpit.io`). Ein `.env`-Umzug allein reicht nicht — die Historie bleibt kompromittiert, solange sie nicht bereinigt wird (separate, mit dir abzustimmende Entscheidung, da das History-Rewrite bedeutet).
2. **[Hoch/Sicherheit] MCP-Server ohne Authentifizierung auf `0.0.0.0:8000`.** Jeder im Netz erreichbare Client kann `CreateHost` (Schreibzugriff) ohne jede Prüfung aufrufen.
3. **[Hoch/Korrektheit] `getServicesbyState` validiert den `state`-Parameter nicht.** Live verifiziert: ein ungültiger Wert (`"NOTASTATE"`) führt nicht zu einem Fehler oder leerem Ergebnis, sondern liefert einen großen, fachlich falschen Ergebnis-Datensatz zurück (in diesem Fall zufällig alle Services mit Status UNKNOWN, ca. 90 KB Rohdaten) — für ein LLM nicht von einem korrekten Treffer unterscheidbar. Ursache: Backend-Filtertyp `state` erwartet einen der bekannten Namen (`ok/warning/critical/unknown`); bei unbekanntem String greift offenbar ein Fallback/keine Filterung statt eines Fehlers. Tool muss den Wert vor dem Request gegen die erlaubte Menge validieren.
4. **[Mittel/Robustheit] `CreateHost` ist ein Schreib-Tool ohne Env-Flag-Absicherung**, entgegen der eigenen Anforderung ("Schreibende Operationen nur hinter einem Env-Flag aktiv, standardmäßig aus"). Aktuell jederzeit aktiv. Zusätzlich hartkodiert `container_id=9` und `hosttemplate_id=1` — funktioniert nur, weil diese IDs in der Testumgebung existieren; auf einer anderen Instanz vermutlich Fehlschlag oder (schlimmer) falscher Container/Template.
5. **[Mittel/Totter Code] `getHostUpdateStatus` und `getUpdateStatus`** sind definiert, aber nicht registriert (`@mcp.tool` fehlt) — verwirrend beim Lesen/Warten des Codes, sollten entfernt oder aktiviert werden.
6. **[Mittel/Kompatibilität] Python-Versionsanforderung nicht dokumentiert.** `X | None`-Syntax erfordert Python ≥3.10; ohne `requirements.txt`/README-Hinweis leicht zu übersehen (genau passiert: lokal nur 3.9 verfügbar).
7. **[Niedrig] `print(resp)` in `getHostUpdateStatus`** (Zeile 254) würde bei Aktivierung Rohdaten inkl. potenziell sensibler Felder ins Log schreiben — passt nicht zur eigenen Anforderung "API-Key niemals loggen" (hier zwar nicht der Key selbst, aber unreflektiertes Rohdaten-Logging als Muster).
8. **[Niedrig] Kein strukturiertes Fehlerhandling.** `require_success` wirft eine generische `RuntimeError` mit dem vollen Response-Body — bei Auth-Fehlern würde das den Klartext-Fehler (kein Secret, aber ggf. interne Details) an das LLM als Tool-Error durchreichen statt einer sprechenden, handlungsleitenden Meldung.

## 4. Abweichungen Backend ↔ Frontend

- **Zwei unterschiedliche Filter-Übertragungsmuster im Frontend**: Hosts/Services/Hostgroups/Servicegroups-Hauptlisten nutzen inzwischen **POST mit Filter im Body** (`{filter: {...}}`), während Logentries, Patchstatus, Downtimes, Acknowledgements, Contacts, Notifications, Host-/Serviceescalations weiterhin klassisches **GET mit `filter[Model.feld]`-Query-Notation** verwenden. Der MCP-Server nutzt aktuell ausschließlich GET+Query — das funktioniert laut Live-Test weiterhin auch für Hosts/Services (Backend unterstützt beides), ist aber nicht der vom aktuellen Frontend bevorzugte Weg.
- **String- vs. Zahl-Inkonsistenz bei Statuswerten, durchgängiges Muster**: Frontend sendet Statuswerte immer als lesbare Strings (`'critical'`, `'up'`, `'recovery'`, …), Backend-Antworten liefern denselben Zustand aber als **Zahl** (`current_state: number`, `state: number`). Betrifft Hosts, Services, Acknowledgements, Notifications gleichermaßen. Für neue Tools wichtig: **Filter-Wert als String senden, Antwort als Zahl interpretieren** — nicht symmetrisch behandeln.
- **`Host` vs. `Hosts` (Singular/Plural) bei Logentries**: Der Filter für Host-bezogene Logentries heißt `filter[Host.id]` (Singular!), während er bei praktisch allen anderen Controllern `Hosts.*` (Plural) lautet. Leicht zu verwechseln, im Code exakt so verifiziert.
- **Downtime/Acknowledgement-Erstellung liegt außerhalb der von mir untersuchten Controller.** `DowntimesController` und `AcknowledgementsController` bieten nur Lese- und Löschoperationen; das eigentliche Setzen läuft über Nagios-External-Commands (vermutlich ein separater Plugin-Controller, nicht Teil dieser Analyse). Für ein zukünftiges Schreib-Tool "Downtime anlegen" oder "Acknowledge setzen" ist **weitere gezielte Recherche nötig**, bevor das geplant werden kann — dazu jetzt keine Aussage, die über Vermutung hinausgeht.

## 5. Filter-Parameter-Referenztabelle (Kernbereiche)

| Endpunkt | Methode/URL | Wichtige Filter (Backend-verifiziert) | Frontend-Serialisierung |
|---|---|---|---|
| Hosts | `GET/POST /hosts/index.json` | `Hosts.id`, `Hosts.uuid`, `Hosts.name` (like/rlike), `Hosts.address`, `Hosts.disabled`, `Hosts.satellite_id`, `Hosts.host_type`, `Hostgroups.id`, `Hoststatus.current_state` (state-Typ, String-Namen), `Hoststatus.problem_has_been_acknowledged`, `Hoststatus.scheduled_downtime_depth`, `Hoststatus.notifications_enabled`, `Hoststatus.active_checks_enabled`, `Hosts.keywords`/`not_keywords` | POST-Body `{filter:{...}}` (neu) oder GET `filter[Hosts.name]=...` (funktioniert weiterhin) |
| Services | `GET/POST /services/index.json` | `Services.id`, `Services.uuid`, `Hosts.id`, `Hosts.satellite_id`, `Services.service_type`, `servicename`/`servicedescription` (like), `keywords`/`not_keywords`, `Hostgroups.id`, `Servicegroups.id`, `Servicestatus.current_state` (state-Typ), `Servicestatus.problem_has_been_acknowledged`, `Servicestatus.scheduled_downtime_depth` | Analog Hosts |
| Logentries | `GET /logentries/index.json` | `Logentries.logentry_type` (numerisch, equals), `Logentries.logentry_data` (like), `filter[Host.id]` (Singular!, Array möglich), `filter[from]`/`filter[to]` (Format `dd.mm.YYYY HH:MM`, wie im MCP-Code bereits genutzt) | GET `filter[...]`/`filter[...][]` |
| Patchstatus | `GET /patchstatus/index.json` | `Hosts.name`/`Hosts.id`, `PackagesHostDetails.os_type` (Array), `os_name`, `os_version`, `available_updates`/`available_security_updates` (greater_equals, numerisch), `reboot_required` (bool) | GET `filter[...]`/`filter[...][]` |
| Downtimes (Lücke) | `GET /downtimes/host.json` bzw. `.../service.json` | `Hosts.name`/`servicename`, `DowntimeHosts.author_name`/`comment_data`, `was_cancelled`, `hideExpired`, `isRunning`, `from`/`to` | GET `filter[...]` |
| Acknowledgements (Lücke) | `GET /acknowledgements/host/{id}.json` bzw. `.../service/{id}.json` | `AcknowledgementHosts.comment_data`/`author_name`, `state` (Array, String-Namen), `from`/`to` | GET `filter[...]`/`filter[...][]` — **erfordert Host-/Service-ID**, kein globaler Listenendpunkt |
| Hostgroups/Servicegroups (Lücke) | `GET/POST .../index.json`, `.../extended.json` | `Containers.name`, `*.description`, `*.keywords`/`not_keywords`, erweitert: `Hoststatus.current_state`/`Servicestatus.current_state` (Array) | POST-Body für Hauptliste, GET `filter[...][]` für Extended-Ansicht |
| Notifications (Lücke) | `GET /notifications/index.json` (Host) bzw. `.../services.json` | `NotificationHosts.output`/`state` (Array), `Hosts.name`, `Contacts.name`, `Commands.name`, `from`/`to` (Service analog mit `NotificationServices.*`, `servicename`) | GET `filter[...]`/`filter[...][]` |
| Nagiostats (Lücke) | `GET /nagiostats/index.json` | keine Filter — statischer Systemstatus-Dump | — |

## 6. Vorschlag für Phase 3 (zur Entscheidung, nicht umgesetzt)

Kurz begründet, keine Umsetzung ohne dein Go:

1. **Sicherheit zuerst** (unabhängig vom Feature-Umfang): API-Key aus Default-Wert entfernen, `.env`/`.env.example` einführen, `.gitignore` prüfen. Git-Historie-Bereinigung separat besprechen (eigene Entscheidung wegen Force-Push-Charakter). MCP-Server-Auth und/oder Bind auf `127.0.0.1` klären.
2. **Bestehende Tools reparieren statt neue bauen**: `getServicesbyState`-Validierung (Bug #3), `CreateHost` hinter Env-Flag (Standard aus), toten Code (`getHostUpdateStatus`/`getUpdateStatus`) entfernen oder sauber registrieren.
3. **Höchster Nutzenzuwachs**: Downtimes- und Acknowledgements-Lesetools (Kernanforderung aus eurem eigenen System-Prompt, aktuell nicht abgedeckt, rein lesend, Filter-Parameter bereits oben verifiziert).
4. **Danach**: Hostgroups/Servicegroups- und Nagiostats-Lesetools (mittlerer Nutzen, einfache Umsetzung, keine bekannten Backend-Fallstricke).
5. **Zurückgestellt**: alles Schreibende über External-Commands (Downtime anlegen, Acknowledge setzen) — dafür erst den zuständigen Plugin-Controller identifizieren, bevor das geplant wird.
6. **Begleitend**: `requirements.txt`/`pyproject.toml` mit gepinnter `fastmcp`/`mcp`-Version, Python-≥3.10-Hinweis in README, Unit-Tests + Smoke-Test-Skript wie im Auftrag beschrieben.

**STOP — Phase 2 Ende. Ich warte auf deine Entscheidung, was aus Abschnitt 6 (oder in welcher Reihenfolge/Kombination) in Phase 3 umgesetzt wird.**
