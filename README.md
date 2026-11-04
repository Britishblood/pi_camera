# Raspberry Pi Camera

`raspberry_pi_camera` ist ein Kameradienst für einen Raspberry Pi. Eine USB-UVC-Kamera wird **einmal** über OpenCV geöffnet und kontinuierlich ausgelesen. Parallel dazu bietet der Raspberry Pi:

- einen **kleinen MJPEG-Live-Stream**;
- **hochaufgelöste Einzelaufnahmen** nach einem GPIO-Trigger oder per HTTP-Anfrage;
- zwei umschaltbare Aufnahmemodi mit getrennten Verzögerungen: `bed` (Druckbett) und `fill_level` (Füllstand);
- eine verlustfreie Speicherung der von OpenCV empfangenen Frames als **unkomprimierte RGB-TIFFs**.

Das Projekt wurde für die **Innomaker U20CAM-1080P** entwickelt. Die Preview-Auflösung bleibt unabhängig von der Kamera niedrig.

> **Stand:** Entwicklungsprototyp. Kamera- und GPIO-Funktionen müssen auf der tatsächlichen Hardware getestet werden. Der automatische Bildtransfer auf den Windows-PC ist noch nicht implementiert.

## Projektstruktur

```text
raspberry_pi_camera/
├── main.py             # Start, Konfiguration über Kommandozeilenparameter, GPIO
├── camera.py           # CameraManager: ein zentraler Aufnahme-Thread
├── capture.py          # CaptureController: Trigger, Delays, TIFF-Speicherung
├── server.py           # Flask: MJPEG-Stream und einfache Steuerungs-API
├── setup.sh            # Einmalige Einrichtung auf Raspberry Pi OS
├── requirements.txt    # Python-Pakete für die virtuelle Umgebung
├── .gitignore
└── images/             # Wird beim Betrieb angelegt und nicht mit Git versioniert
    ├── bed/
    └── fill_level/
```

## Voraussetzungen

- Raspberry Pi mit Raspberry Pi OS / Debian und Zugang zum Paketmanager `apt`.
- USB-UVC-Kamera, unter Linux z. B. `/dev/video0`.
- GPIO-Taster an **BCM GPIO 27**.
- Für die **erste Einrichtung** Zugang zu den benötigten Paketquellen. **Für den späteren lokalen Betrieb ist keine Internetverbindung erforderlich.**
- Ein PC im gleichen lokalen Netz für die Live-Vorschau und API-Abfragen.

## Installation

Repository auf dem Raspberry Pi klonen und in das Verzeichnis wechseln:

```bash
git clone <URL-DEINES-REPOSITORIES>
cd raspberry_pi_camera
```

Die mitgelieferte Einrichtung ausführen:

```bash
bash setup.sh
```

`setup.sh` installiert die Systempakete `python3-venv`, `python3-pip`, `python3-numpy`, `python3-opencv`, `python3-gpiozero` und `python3-lgpio`. Anschließend erstellt es bei Bedarf die **`.venv` mit `--system-site-packages`**, installiert `flask` und `tifffile` aus `requirements.txt` und prüft die wichtigsten Importe.

Das Setup kann erneut ausgeführt werden. Eine bestehende `.venv`, die **ohne** Zugriff auf Systempakete erstellt wurde, wird nicht automatisch überschrieben; das Skript meldet diesen Fall.

Die `.venv` muss nicht aktiviert werden. Verwende direkt ihren Interpreter:

```bash
.venv/bin/python main.py
```

## Starten

Beispiel für die aktuelle USB-Kamera:

```bash
.venv/bin/python main.py \
  --device 0 \
  --width 1920 \
  --height 1080 \
  --fps 30 \
  --preview-width 640 \
  --preview-fps 5 \
  --bed-delay 2 \
  --fill-delay 5 \
  --port 8080
```

`--bed-delay` und `--fill-delay` sind **Sekunden**. Der aktive Modus ist beim Start `bed` und kann später per API gewechselt werden. Mit `Ctrl+C` wird das Programm beendet.

Für einen Test ohne GPIO-Taster:

```bash
.venv/bin/python main.py --no-gpio
```

Weitere Optionen:

| Option | Standard | Bedeutung |
| --- | --- | --- |
| `--device` | `0` | OpenCV-Kameraindex |
| `--width`, `--height` | `1920`, `1080` | Gewünschte Kameraauflösung |
| `--fps` | `30` | Gewünschte Aufnahme-FPS |
| `--preview-width` | `640` | Breite der Netzwerk-Vorschau (Seitenverhältnis bleibt erhalten) |
| `--preview-fps` | `5` | Maximale Vorschau-Bildrate je Stream-Client |
| `--bed-delay` | `2.0` | Verzögerung für Druckbettaufnahme in Sekunden |
| `--fill-delay` | `5.0` | Verzögerung für Füllstandsaufnahme in Sekunden |
| `--output` | `images/` im Projekt | Speicherverzeichnis |
| `--host` | `0.0.0.0` | Bind-Adresse des HTTP-Servers |
| `--port` | `8080` | HTTP-Port |
| `--no-gpio` | aus | Testbetrieb ohne GPIO-Taster |

**Hinweis zur Bildrate:** Die Werte sind Anforderungen an die Kamera, keine Garantie. Auflösung, FPS und MJPEG-Unterstützung hängen vom UVC-Gerät, Treiber und Raspberry-Pi-Modell ab. Die tatsächliche Aufnahme-FPS lässt sich über `/status` prüfen.

## Bedienung und HTTP-Schnittstelle

Ersetze in den folgenden Adressen `192.168.50.2` durch die tatsächliche IP-Adresse des Raspberry Pi.

### Live-Stream

Im Browser öffnen:

```text
http://192.168.50.2:8080/video
```

Der Stream wird aus den kontinuierlich aufgenommenen Frames erzeugt, **verkleinert und als JPEG übertragen**. Die Kamera selbst läuft weiterhin mit der konfigurierten hohen Auflösung. Eine Stream-Verbindung ist nicht notwendig, damit Triggeraufnahmen funktionieren.

### Status

```text
GET /status
```

Beispiel in Windows PowerShell:

```powershell
Invoke-RestMethod http://192.168.50.2:8080/status
```

Die Antwort enthält unter anderem Kamera-Status, geschätzte FPS, aktiven Aufnahmemodus, Delays, geplante Aufnahmen, Anzahl gespeicherter Bilder und den letzten Fehler.

### Modus und Verzögerungen ändern

```text
POST /config
```

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri http://192.168.50.2:8080/config `
    -ContentType 'application/json' `
    -Body '{"mode":"fill_level","bed_delay_s":2,"fill_level_delay_s":5}'
```

Die Modi heißen `bed` und `fill_level`. Änderungen gelten für **neue** Trigger; bereits eingeplante Aufnahmen behalten ihren ursprünglich ermittelten Zeitpunkt. Einstellungen liegen derzeit nur im Arbeitsspeicher und gehen bei einem Neustart verloren.

### Manuelles Foto

```text
POST /snapshot
```

```powershell
Invoke-RestMethod `
    -Method Post `
    -Uri http://192.168.50.2:8080/snapshot `
    -ContentType 'application/json' `
    -Body '{"mode":"bed"}'
```

Ohne Angabe von `mode` gilt der aktuell eingestellte Modus. Ein manueller Snapshot wird **ohne Modus-Delay** angefordert und **nicht** von der GPIO-Sperrzeit blockiert. Die HTTP-Antwort mit `queued: true` bedeutet nur, dass die Aufnahme angefordert wurde, **nicht**, dass die Datei bereits gespeichert ist.

## GPIO-Trigger und Sperrzeit

Der GPIO-Taster verwendet **BCM GPIO 27** mit `pull_up=False` und einer Entprellzeit von 50 ms. Jeder akzeptierte Tastendruck plant genau eine Aufnahme im aktuell gewählten Modus nach dessen Verzögerung.

**Gewünschtes Verhalten:** Nach einem akzeptierten Tastendruck werden weitere GPIO-Trigger für

```python
cooldown_s = max(10.0, bed_delay_s, fill_level_delay_s)
```

ignoriert. Die Sperrzeit beginnt beim Tastendruck und wird für diesen Trigger festgehalten. Beispiel: Bei `bed_delay_s=2` und `fill_level_delay_s=20` beträgt sie 20 Sekunden.

> **Achtung:** Die ursprünglich bereitgestellte Fassung von `capture.py` verwendet noch eine **feste 10-Sekunden-Sperrzeit**. Für das oben beschriebene dynamische Verhalten müssen die zuletzt besprochenen Änderungen an `CaptureController.button_pressed()` und `status()` in deinem Repository enthalten sein. Die README allein ändert den Code nicht.

## Bildspeicherung

Bilder werden derzeit **lokal auf dem Raspberry Pi** gespeichert:

```text
images/
├── bed/
│   └── bed_YYYYMMDD_HHMMSS_ffffff_<id>.tif
└── fill_level/
    └── fill_level_YYYYMMDD_HHMMSS_ffffff_<id>.tif
```

Ein separater Speicher-Thread schreibt die Aufnahmen als **unkomprimiertes RGB-TIFF**. Das blockiert nicht die kontinuierliche Kameraerfassung. Die Datei wird zunächst temporär geschrieben und erst nach erfolgreichem Schreiben auf den endgültigen Dateinamen umbenannt.

**Wichtig:** Der USB-UVC-Kameramodus `MJPG` ist bereits verlustbehaftet. TIFF bewahrt das von OpenCV **dekodierte** Bild ohne zusätzliche verlustbehaftete Kompression; es stellt keine ursprünglichen Sensordaten wieder her.

Ein automatischer Download auf Windows und das anschließende Löschen bestätigter Dateien vom Pi werden in einer späteren Version ergänzt. Bis dahin ist der freie Speicherplatz auf dem Pi zu beachten.

## Sicherheit und Netzwerk

Die aktuelle Anwendung verwendet den integrierten Flask-Entwicklungsserver über **unverschlüsseltes HTTP**. Sie ist **nicht** für einen ungeschützten Internet- oder VPN-Zugang vorgesehen.

Optional lässt sich für die **schreibenden** API-Endpunkte (`/config` und `/snapshot`) ein Token setzen:

```bash
export PI_CAMERA_TOKEN='EIN_LANGES_ZUFAELLIGES_TOKEN'
.venv/bin/python main.py
```

Dann muss der Client den Header `X-API-Token` senden. `/video` und `/status` sind in dieser Version nicht durch dieses Token geschützt. Weil kein TLS eingerichtet ist, ersetzt das Token keine geeignete Netzwerkabsicherung. Für den Betrieb die Zugriffe per Firewall auf vertrauenswürdige Geräte begrenzen; vor einer VPN-Freigabe Authentifizierung und sicheren Transport ergänzen.

## Geplante Erweiterungen

- PySide6-Windows-GUI mit Stream, Moduswahl und Delay-Einstellungen.
- Automatische, überprüfte Bildübertragung auf den Windows-PC mit anschließendem Löschen auf dem Pi.
- Speicherung der Einstellungen über Neustarts hinweg.
- Optionaler automatischer Start als `systemd`-Dienst.
- Test und Anpassung der Kameraauflösung für die HQ Camera über den CSI-USB-UVC-Adapter.

## Fehlerbehebung

**Kamera lässt sich nicht öffnen:** Prüfen, ob noch `button.py`, die alte `camera.py` oder ein anderer Prozess die Kamera verwendet; USB-Verbindung und Geräteindex kontrollieren.

**Stream funktioniert, Fotos fehlen:** Status unter `/status` abfragen und `last_error` sowie freien Speicherplatz prüfen.

**Framerate zu niedrig:** Gemessene `fps_estimate` beobachten, UVC-Modi prüfen und gegebenenfalls die Kameraauflösung oder Ziel-FPS reduzieren. Die Preview-FPS beeinflussen nicht direkt die Kamera-FPS.

**GPIO funktioniert nicht:** GPIO-Nummerierung **BCM 27**, Verdrahtung, Benutzerrechte und installierte GPIO-Backends prüfen. Für reine Kameratests `--no-gpio` nutzen.
