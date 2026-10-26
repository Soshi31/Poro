# Behavior pentru Poro

`BehaviorManager` este singurul modul care comandă `EyeSystem` în aplicația
integrată. Vision furnizează `TrackingTarget`, voice furnizează status/text,
iar body furnizează evenimente pe `EventBus`. Driverul display-urilor,
face tracker-ul, blink engine-ul și controlerul limbii rămân cele existente.
Apelul `update(dt)` se face în același thread cu `eyes.render()` și
`DisplayManager.show_both()`; producătorii nu primesc obiectul `eyes`.

## Pornire pe hardware

```bash
cd /home/poro/Poro
/usr/bin/python3 behavior_test.py
```

Scriptul pornește camera fără preview, ochii, BNO085/PCA9685 și voice local.
`Ctrl+C` sau `quit` închide resursele. Pentru o probă scurtă:

```bash
/usr/bin/python3 behavior_test.py --duration 30
/usr/bin/python3 behavior_test.py --echo-voice
```

`--echo-voice` repetă prin TTS textul recunoscut, fără LLM. Dacă modelul
STT/ALSA este indisponibil, `--no-voice` permite diagnostic pentru restul;
`--no-body` izolează I2C. Ambele opțiuni sunt doar pentru test.

În terminalul interactiv poți tasta `happy`, `curious`, `sleepy`, `neutral`,
`sleep`, `wake`, `person`, `idle`, `look -0.5 0.3`, `blink`, `tongue blep`,
`tongue double_blep`, `tongue in`, `tongue out`, `say Salut` sau `quit`.
Comenzile sunt citite fără a opri animația ochilor.

## Priorități și ownership

Stările inițiale: `IDLE`, `ATTENTIVE`, `LISTENING`, `THINKING`, `SPEAKING`,
`HAPPY`, `CURIOUS`, `SLEEPY`, `SLEEP`, `STARTLED`. La fiecare cadru se alege
prima stare aplicabilă în această ordine: somn explicit, vorbire, reacție
startled, ascultarea comenzii după wake word, thinking după STT, sleepy,
happy, curious, persoană vizibilă/holding, idle. `waiting_wakeword` și
`detecting_wakeword` nu schimbă expresia în `LISTENING`.

Expresia schimbă pupila cu `EyeSystem.set_pupil()`; clipitul automat al
`EyeSystem` continuă. `SLEEPY` folosește pleoapele pe jumătate închise,
`SLEEP` pe cele închise. Doar tranzițiile în/din aceste două stări schimbă
emoția completă a ochilor. Privirea are prioritate separată: reacție
`STARTLED` la centru, comandă manuală temporară, cameră, apoi idle-ul
existent. `look_at_person()` reactivează camera; `release_gaze()` lasă
idle-ul ochilor. Pozițiile sunt filtrate și limitate de API-ul existent
`EyeTrackingController`/`EyeSystem`, identic cu `vision_test.py`.

`shaken`/`upside_down` declanșează `STARTLED`; înclinările și `picked_up`
declanșează `CURIOUS`; `put_down` declanșează `HAPPY`. Reacțiile expiră
singure; evenimentele vechi sunt ignorate. Mișcările corpului **nu** mișcă
automat limba, pentru că `picked_up`/`put_down` sunt estimări IMU. Limba se
mișcă numai la comanda semantică explicită `tongue("blep")` etc.

## API pentru viitorul brain

```python
from behavior import BehaviorManager

# Creează PerceptionSystem și BodyManager cu același EventBus; construiește
# EyeSystem în thread-ul de afișare și trece-l managerului.
behavior = BehaviorManager(eyes, perception=perception, voice=voice,
                           body=body, event_bus=bus)
behavior.set_emotion("happy")
behavior.look_at_person()
behavior.tongue("blep")          # Future; fără grade brute
behavior.sleep()
behavior.wake_up()
behavior.speak("Salut!")         # Future; TTS asincron
behavior.update(dt)              # o dată pe frame, înainte de eyes.render()
text = behavior.listen()         # text STT sau None; non-blocking
state = behavior.get_state()     # stare și proprietarii expresiei/privirii
```

Comenzile pentru ochi merg printr-o coadă limitată și se aplică la următorul
`update()`, inclusiv când brain-ul rulează în alt thread. `tongue()` și
`speak()` trimit sarcini asincrone către managerii hardware existenți și
returnează Future. `sleep()` suspendă VAD/wake/STT prin `VoiceManager`, fără
să închidă microfonul; `wake_up()` le reactivează. Vorbirea TTS deja pornită
nu este întreruptă de `sleep()`; un nou `speak()` în `SLEEP` este refuzat.
Pentru aplicații viitoare care vor întreruperea TTS la somn, este necesar un
cancel per comandă audio.

Pe durata inferenței, agentul apelează `begin_thinking()` și apoi
`finish_thinking()`. Acestea suspendă și reiau VAD/wake/STT, ca să nu
pornească Whisper peste LLM și să nu umple coada cu zgomot. Captura ALSA
rămâne drenată; poarta anti-ecou TTS continuă să funcționeze.

Setările din `config.py` cu prefixul `BEHAVIOR_` controlează duratele
reacțiilor, timpul maxim de thinking și capacitățile cozilor. `SLEEP`
rămâne până la `wake_up()` sau `set_emotion(...)`; `THINKING` se încheie la
`speak()` ori `finish_thinking()`; starea temporară după STT expiră și singură.
Managerul nu implementează
LLM și nu trimite textul recunoscut către un serviciu extern.
