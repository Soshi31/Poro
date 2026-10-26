# Corpul Poro

`BodyManager` folosește BNO085 la **0x4A** și PCA9685 la **0x40**, canalul
**0** pentru limbă. Magistrala este cea din testele existente: `board.SCL/SDA`.
Nu inițializează camera, ochii sau vocea și nu include LLM.

## Rulare

Cu robotul drept și nemișcat pe masă:

```bash
cd /home/poro/Poro
/usr/bin/python3 body_test.py --imu-only
```

Așteaptă `body_ready`, apoi înclină/ridică/așază robotul. Pentru a include
PCA9685, pornește `body_test.py` fără `--imu-only`. Pornirea nu comandă o
poziție a limbii; ieșirea PWM este inițial dezactivată. Nu rula concomitent
vechile scripturi BNO/ServoKit pe aceeași magistrală cu BodyManager.

```bash
/usr/bin/python3 body_test.py --action tongue_in --duration 8
/usr/bin/python3 body_test.py --action tongue_out --duration 8
/usr/bin/python3 body_test.py --action tongue_blep --duration 10
/usr/bin/python3 body_test.py --action tongue_double_blep --duration 12
```

Dacă BNO085 nu răspunde, verifică separat servo-ul, fără a depinde de IMU:

```bash
/usr/bin/python3 body_test.py --tongue-only --action tongue_in --duration 6
/usr/bin/python3 body_test.py --tongue-only --action tongue_double_blep --duration 10
```

În acest mod nu se publică evenimente de mișcare și starea indică `imu_enabled: false`.

O acțiune se execută o singură dată după stabilizarea IMU. `Ctrl+C`, o eroare
fatală IMU sau încheierea testului dezactivează PWM pe canalul 0. Nu se comandă
o retragere suplimentară la oprire. Dezactivarea PWM nu este o frână mecanică.

## API și bus comun

```python
from core.events import EventBus
from body.body_manager import BodyManager
from vision.perception import PerceptionSystem

bus = EventBus(capacity=64)
stream = bus.subscribe()  # evenimente body + vision, o coadă pentru acest consumator

try:
    with PerceptionSystem(event_bus=bus) as perception, BodyManager(event_bus=bus) as body:
        result = body.tongue_blep()  # Future; nu așteaptă animația
        # Viitorul behavior loop poate citi stream.poll()/stream.drain(),
        # body.get_state() și perception.get_current_scene_state().
        # result.done()/result.result() raportează încheierea sau eroarea.
        result.result(timeout=10)  # așteptare opțională, doar în acest exemplu
finally:
    stream.close()
    bus.close()
```

Acțiuni publice: `tongue_in()`, `tongue_out()`, `tongue_blep()`,
`tongue_double_blep()`. Niciuna nu acceptă grade. `queue.Full` înseamnă că
cele patru locuri în așteptare sunt ocupate. O acțiune poate fi anulată prin
Future înainte să înceapă; `close()` întrerupe și acțiunea activă.
`start()` poate aștepta inițializarea driverelor; după pornire toate
operațiile I2C și animațiile rulează într-un singur worker dedicat.
Folosește `with` sau apelează `close()` la ieșire.

Fiecare abonat primește propria coadă limitată; consumatorii lenți pierd
evenimentele cele mai vechi, fără să blocheze senzorul. Verifică
`subscription.dropped_count` și reîmprospătează starea dacă ai pierderi.
Payload-urile sunt copii JSON, cu `source`, timestamp monotonic, tip și număr
de secvență. `body.subscribe()` filtrează evenimente body; `perception.subscribe()`
filtrează vision. `bus.subscribe()` primește tot. Pentru tipuri viitoare:
`EventBus(extra_types={'behavior_requested'})`. Bus-ul este pentru threaduri
din același proces; nu este IPC. Un modul nu închide un bus primit din exterior.
Importurile vechi `vision.events.EventBus` / `VisionEvent` continuă să funcționeze.

## Evenimente IMU

- `tilted_left`, `tilted_right`, `tilted_forward`, `tilted_back`: gravitație
  filtrată, intrare la 25°, ieșire la 15°, confirmare 0,25 s și cooldown.
- `upside_down`: înclinare totală peste 145°, revenire sub 125°.
- `movement_started`, `movement_stopped`: accelerație liniară/giroscop filtrate,
  praguri cu histerezis, confirmare start 0,12 s / stop 0,7 s.
- `shaken`: minimum trei impulsuri alternante în 0,8 s; o lovitură izolată nu
  este shake. Cooldown de 2 s.
- `picked_up`, `put_down`: impuls vertical, frânare în sens opus și apoi
  stabilizare. Mișcările de scuturare inhibă această estimare. O simplă pauză
  în mână nu produce automat `put_down`.

**Ridicarea/așezarea sunt estimări.** Un IMU nu poate distinge fizic „ținut
nemişcat în mână” de „sprijinit pe masă” și nu măsoară înălțimea absolută.
Pornirea presupune că robotul este sprijinit. Payload-ul pickup/putdown are
`inferred: true`; starea folosește `assumed_supported`, `held_estimate`,
`supported_estimate`. Mișcările foarte lente pot fi ratate, iar o deplasare
în jos urmată de oprire în mână poate semăna cu așezarea. Pentru confirmare
fizică ar fi necesar ulterior un senzor de contact/distanță.

`get_state()` oferă starea, orientările active, accelerația, gyro,
`invalid_imu_packets`, `stale`, `running` și `ready`. Nu se interpretează
valorile inițiale zero ale senzorului. Rapoartele vechi nu pot confirma un
eveniment nou; întreruperea fluxului peste o secundă produce `body_error`
și oprește worker-ul. Pentru repornire creează o instanță nouă.

## Limitele limbii și montaj

În `config.py`: **0° = scoasă**, **175° = retrasă**, limita maximă **175°**,
confirmate de utilizator. PWM 50 Hz, impulsuri 750–2250 µs, aceleași valori
implicite ca vechiul test ServoKit. Nu am extins impulsurile pentru a forța
cursa. Pozițiile fizice depind de servo și mecanism, nu doar de numărul de grade.

`TONGUE_BLEP_FRACTION = 0.5` folosește jumătate de cursă, apoi revine înăuntru.
`TONGUE_SPEED_DEG_PER_SECOND`, durata blep și pauza double-blep sunt configurabile.
Limitele sunt validate înainte de inițializare și din nou înainte de fiecare
comandă hardware. După o secundă de repaus PWM este eliberat; setează
`TONGUE_RELEASE_IDLE_SECONDS = None` dacă montajul necesită menținerea poziției.

Servo-ul nu are encoder: prima acțiune, inclusiv după eliberarea PWM, trimite
poziția de retragere și așteaptă cursa maximă estimată înainte de animație.
Această primă repoziționare nu poate fi interpolată dintr-o poziție fizică
necunoscută. Restul secvenței este limitat ca viteză; Future-ul confirmă
încheierea comenzilor, nu o poziție măsurată sau lipsa blocajului mecanic.

## Reglaje IMU

`BODY_AXIS_MAP` definește +X dreapta, +Y înainte, +Z sus. `(1,2,3)` înseamnă
axele senzorului, `(-1,-2,3)` corectează un montaj întors cu 180° în plan.
Permutările trebuie să păstreze orientarea axelor. Z în sus a fost observat
pe hardware; sensurile X/Y se verifică prin înclinare fizică spre dreapta și
spre față. Schimbarea axelor nu afectează configurația ochilor.

Pragurile `BODY_TILT_*`, `BODY_MOVE_*`, `BODY_SHAKE_*`, `BODY_LIFT_*`, timpii
de smoothing și warmup sunt în `config.py`. Valorile nu se modifică dinamic
în timpul rulării; repornește BodyManager după reglaje.
Rapoarte IMU 20 Hz, worker până la 50 Hz pentru servo. Eventualele pachete I2C
invalide sunt respinse și numărate, cu log limitat, fără a dezactiva timeout-ul.

Cu controlerul hardware I2C1, BNO085 a livrat pachete corupte și apoi a
încetat să livreze rapoarte, inclusiv la 100 kHz. Pe montajul actual este
activat controlerul I2C software al kernelului (`/dev/i2c-3`) pe **aceleași**
GPIO2/SDA și GPIO3/SCL. Nu s-au schimbat firele sau adresele dispozitivelor.
După activare, testul IMU nemișcat a rulat 30 s fără expirare; testul combinat
IMU + `tongue_in` a rulat 15 s, cu PWM dezactivat după acțiune. O probă
suplimentară de 120 s cu ambele dispozitive inițializate a avut 59 de stări
`ready`, zero stări `stale`, zero erori și contorul pachetelor invalide
constant la 20 după pornire. Testele reale
au produs `tilted_left/right/forward/back`, `upside_down`, `shaken`,
`movement_started/stopped`, `picked_up` și `put_down` într-o secvență ghidată.
După pornire apar aproximativ 19–20 pachete inițiale respinse, dar numărul nu a
crescut în aceste probe. Testele logice acoperă toate cele zece tipuri de
evenimente; 34 de teste au trecut. O probă de două minute nu garantează
stabilitate pe termen lung, deci păstrează monitorizarea `stale` și `body_error`.

Scriptul `hardware_tests/i2c_speed.py` afișează întâi schimbarea propusă:

```bash
/usr/bin/python3 hardware_tests/i2c_speed.py --software
sudo /usr/bin/python3 hardware_tests/i2c_speed.py --software --apply
sudo reboot
```

Modul software dezactivează perifericul I2C1 și activează `i2c-gpio` ca
`/dev/i2c-3`. `hardware/i2c.py` selectează automat noul bus după reboot,
pentru ambele dispozitive. Se poate reveni la hardware I2C1/100 kHz cu
`sudo /usr/bin/python3 hardware_tests/i2c_speed.py --baudrate 100000 --apply`
și reboot. Scripturile istorice BNO/ServoKit folosesc același selector de bus.
Scriptul păstrează un backup al configurației inițiale. Nu este necesar să
revii la I2C1 cât timp această configurație funcționează. Pentru context:
[limitările clock stretching pe Raspberry Pi](https://learn.adafruit.com/raspberry-pi-i2c-clock-stretching-fixes?view=all).

## Dependențe și fișiere

Driverele sunt deja instalate în Python-ul de sistem al acestui Poro, fără
virtual environment: Blinka 9.2.0, adafruit-circuitpython-bno08x 1.3.3,
adafruit-circuitpython-pca9685 3.4.22, adafruit-circuitpython-motor 3.5.0.
Adaptorul BNO folosește câteva hook-uri private ale versiunii 1.3.3 pentru
timestamp-uri, validarea pachetelor și evitarea valorilor cache; la actualizarea
driverului trebuie refăcut testul hardware. Nu modifică pachetul instalat.

- `hardware/`: I2C și adaptoarele BNO085/PCA9685.
- `body/`: validare, interpretare IMU, secvențe limbă și BodyManager.
- `core/events.py`: implementarea bus-ului comun.
- `vision/events.py`: compatibilitate; `vision/perception.py`: bus injectabil.
- `body_test.py`, `tests/test_body.py`: test hardware și regresii deterministe.

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```

Referințe: [BNO08x API](https://docs.circuitpython.org/projects/bno08x/en/stable/api.html),
[PWM/ServoKit](https://learn.adafruit.com/16-channel-pwm-servo-driver/python-circuitpython),
[BNO085 pe Raspberry Pi](https://learn.adafruit.com/adafruit-9-dof-orientation-imu-fusion-breakout-bno085/python-circuitpython).
