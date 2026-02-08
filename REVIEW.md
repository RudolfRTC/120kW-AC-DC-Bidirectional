# Code Review – 120kW AC/DC Bidirectional PCS Application

Pregled repozitorija in seznam predlaganih izboljšav, razvrščenih po prioriteti.

---

## Povzetek

Projekt je **dobro zasnovan** – čista ločitev odgovornosti (protocol → can_iface → controller → CLI/GUI), obsežna implementacija protokola (35+ CAN sporočil) in uporaben simulator za suhi zagon. Spodaj so navedene konkretne izboljšave, razvrščene v 7 kategorij.

---

## 1. Varnost niti (Thread Safety) — VISOKA PRIORITETA

### 1.1 Dirka na `_last_rx_time` v controller.py

`_last_rx_time` se piše v RX niti (vrstica ~290) in bere v glavni niti prek `seconds_since_last_rx`. Ni nobene sinhronizacije.

**Popravek:** Dostop do `_last_rx_time` zaščititi z obstoječim `_lock` ali uporabiti `threading.Event`.

### 1.2 Nesinhroniziran dostop do `_last_reply_data` / `_pending_replies`

V `controller.py` (~vrstica 317-319) se ti slovarji spreminjajo v RX niti in berejo v ukazni niti brez zaklepa.

**Popravek:** Uporabiti `_lock` pri dostopu do obeh slovarjev ali preiti na `queue.Queue`.

### 1.3 Deque dostop v GUI (`main_window.py` ~vrstica 949-989)

`_trend_time`, `_buf_dc_voltage` itd. se polnijo v signalnem handlerju in berejo v plot posodobitvi – brez sinhronizacije.

**Popravek:** Ker Qt signali izvajajo handler v glavnem threadu, je to verjetno varno, a je vredno dodati komentar, ki to potrdi, ali dodati zaklep za varnost.

---

## 2. Validacija vhodov — VISOKA PRIORITETA

### 2.1 CLI `cmd_set` ne lovi napačnih vnosov (`cli.py` ~vrstica 314-355)

```python
voltage = float(values[0])  # Crashne z "abc"
```

Uporabnik lahko sesuje CLI z netipičnim vnosom, npr. `dcdc-pcs set cv abc`.

**Popravek:** Zaviti v `try/except ValueError` z uporabniku prijaznim sporočilom.

### 2.2 Brez preverjanja obsega parametrov

Ni preverjanja ali so napetost, tok, moč v dovoljenih mejah naprave (npr. 0–1500V DC, 0–999A). Neveljaven parameter se pošlje napravi brez opozorila.

**Popravek:** Dodati konstante za min/max meje in preveriti pred pošiljanjem.

### 2.3 `decode_set_reply` nima preverjanja dolžine podatkov (`protocol.py` ~vrstica 899)

```python
def decode_set_reply(data: bytes) -> bool:
    return data[0] == 0x01 or (len(data) > 1 and data[1] == 0x01)
```

Če so `data` prazni, bo `IndexError`.

**Popravek:** Dodati `if not data: return False` na začetek.

---

## 3. Obdelava napak — SREDNJA PRIORITETA

### 3.1 Tihe `except: pass` izjave

Na več mestih se izjeme tiho požrejo:

| Datoteka | Vrstica | Kontekst |
|----------|---------|----------|
| `controller.py` | ~357 | `__exit__` cleanup |
| `can_iface.py` | ~249 | `list_pcan_interfaces` |
| `backend.py` | ~196, ~271, ~344 | Worker thread |
| `simulator.py` | ~128 | `_send()` |

**Popravek:** Zamenjati z `logger.warning(...)` ali vsaj `logger.debug(...)`, da je razhroščevanje mogoče.

### 3.2 Neupoštevanje rezultata `send()` v controller.py

Klici `self.can.send(can_id, data)` v `send_heartbeat`, `enable`, `disable` itd. ne preverjajo uspešnosti.

**Popravek:** Preveriti vrnjen rezultat in logirati napako ob neuspehu.

### 3.3 Brez ponovnih poskusov za neuspešne ukaze

`enable()`, `disable()`, `reset_faults()` izvedejo en sam poskus. Občasne CAN napake povzročijo neuspeh brez ponovnega poskusa.

**Popravek:** Dodati vsaj 1 ponovni poskus za prehodno neuspele ukaze.

### 3.4 Callback napake logirajo na DEBUG nivoju (`controller.py` ~vrstica 326)

```python
logger.debug("Callback error: %s", e)
```

To bi moralo biti vsaj `WARNING`, saj kaže na hrošča v klicatelju.

---

## 4. Testiranje — SREDNJA PRIORITETA

### 4.1 CLI modul nima testov

`cli.py` (615 vrstic) nima nobenih testov. Ukazi za enable, disable, record, status, set – nič od tega ni testirano.

**Popravek:** Dodati `tests/test_cli.py` z uporabo `unittest.mock` za simulacijo CAN vmesnika.

### 4.2 GUI modul nima testov

Celoten `gui/` direktorij nima testov.

**Popravek:** Dodati vsaj teste za `backend.py` logiko (brez dejanske Qt okna).

### 4.3 Simulator nima neposrednih unit testov

Simulator se uporablja v integracijskih testih, a nima lastnih testov za specifično obnašanje.

### 4.4 Manjkajo robni testi za protokol

- Neveljavni CAN ID-ji
- Mejni pogoji (max/min vrednosti)
- Prazni podatki
- Napačni tipi parametrov

### 4.5 Brez merjenja pokritosti kode

Ni konfiguracije za `pytest-cov` ali `coverage.py`.

**Popravek:** Dodati `pytest-cov` v dev dependencies in `[tool.coverage]` v `pyproject.toml`.

---

## 5. Orodja za kakovost kode — SREDNJA PRIORITETA

### 5.1 Ni linterja, formaterja ali type checkerja

`pyproject.toml` nima konfiguracije za `ruff`, `black`, `mypy`, `isort` ali katerokoli drugo orodje.

**Popravek:** Dodati vsaj:

```toml
[tool.ruff]
target-version = "py39"
line-length = 100
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

[tool.ruff.lint.isort]
known-first-party = ["dcdc_app"]

[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
```

### 5.2 Brez pre-commit hookov

Ni `.pre-commit-config.yaml` datoteke.

**Popravek:** Dodati pre-commit konfigurracijo z ruff, mypy in pytest.

### 5.3 Brez CI/CD pipeline

Ni `.github/workflows/` ali drugega CI sistema.

**Popravek:** Dodati GitHub Actions workflow za:
- Poganjanje testov na Python 3.9, 3.10, 3.11, 3.12
- Linting z ruff
- Type checking z mypy

---

## 6. Konfigurabilnost — NIZKA PRIORITETA

### 6.1 Trdo kodirane časovne omejitve

V `controller.py`:
```python
rx_timeout: float = 1.0       # Trdo kodirano
command_timeout: float = 3.0   # Trdo kodirano
```

Te bi morale biti nastavljive prek `ControllerConfig` ali CLI argumentov.

### 6.2 Simulator parametri niso nastavljivi

- Šumni odstotek: trdo kodiran na 0.5%
- Interval periodičnih okvirjev: trdo kodiran na 200ms
- Heartbeat timeout: trdo kodiran na 5.0s

**Popravek:** Narediti parametre konstruktorja.

### 6.3 Neomejeno naraščanje simuliranih vrednosti

Kapaciteta in energija v simulatorju rasteta brez omejitve. Temperature nimajo realističnih mej.

---

## 7. .gitignore — NIZKA PRIORITETA

Manjkajoči vnosi:

```gitignore
# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Type checking / linting cache
.mypy_cache/
.ruff_cache/

# Coverage reports
htmlcov/
.coverage
coverage.xml
```

---

## Prioritiziran akcijski načrt

| # | Naloga | Prioriteta | Trud |
|---|--------|-----------|------|
| 1 | Popraviti race conditions v controller.py | Visoka | Majhen |
| 2 | Dodati validacijo vhodov v CLI | Visoka | Majhen |
| 3 | Dodati `decode_set_reply` preverjanje dolžine | Visoka | Minimalen |
| 4 | Zamenjati tihe `except: pass` z logiranjem | Srednja | Majhen |
| 5 | Dodati ruff/mypy konfiguracijo | Srednja | Majhen |
| 6 | Dodati teste za CLI | Srednja | Srednji |
| 7 | Dodati preverjanje rezultata `send()` | Srednja | Majhen |
| 8 | Dodati pytest-cov in coverage konfiguracijo | Srednja | Minimalen |
| 9 | Dodati pre-commit hooke | Srednja | Majhen |
| 10 | Dodati CI/CD pipeline | Srednja | Srednji |
| 11 | Narediti timeout-e nastavljive | Nizka | Majhen |
| 12 | Dopolniti .gitignore | Nizka | Minimalen |
| 13 | Dodati teste za simulator | Nizka | Srednji |
| 14 | Dodati GUI backend teste | Nizka | Srednji |
