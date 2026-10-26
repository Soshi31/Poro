# Voce locală Poro

Pipeline real pe INMP441 + MAX98357A, placa ALSA `sndrpigooglevoi`.
Nu pornește camera/ochii și nu folosește un LLM sau servicii cloud.

## Instalare și test

Pe Raspberry Pi OS, cu Python de sistem (fără virtual environment):

```bash
cd /home/poro/Poro
sudo apt update
sudo apt install build-essential cmake git curl alsa-utils espeak-ng python3-pip python3-numpy
bash voice/setup.sh
/usr/bin/python3 voice_test.py
```

Instalarea descarcă PocketSphinx 5.1.1 în `voice/_vendor`, compilează
whisper.cpp v1.9.4 cu două joburi și descarcă modelul multilingual
`base-q5_1` (~57 MiB). După instalare, rularea este complet offline.
Nu sunt necesare `sudo` sau activarea `.venv` la rulare.

După salutul robotului, spune **Poro**, fă o pauză până apare `WAKE WORD`
în terminal, apoi spune **Salut** / **Cum te cheamă?** / **Cât e ceasul?**.
Poți spune și „Poro, salut” într-o frază. Comanda trebuie să înceapă în
6 secunde după activare; o frază poate dura maximum 8 secunde.
Răspunsurile testului sunt reguli fixe; pentru alte fraze repetă textul auzit.
`Ctrl+C` oprește captura, redarea și procesele de transcriere.

```bash
# Izolează STT/TTS de detectorul de activare:
/usr/bin/python3 voice_test.py --no-wakeword
# Test cu oprire automată:
/usr/bin/python3 voice_test.py --duration 60
```

## API pentru brain

```python
import time
from voice.voice_manager import VoiceManager

with VoiceManager() as voice:
    while True:
        text = voice.listen()  # imediat: str sau None
        if text:
            completion = voice.speak("Am auzit: " + text[:350])
            # completion este Future; verifică done()/result() pentru erori.
        # Aici pot rula logica robotului, ochii și consumatorii perception.
        time.sleep(0.02)
```

`start()` inițializează resursele și poate dura puțin; apoi `listen()` și
`speak()` nu așteaptă transcrierea/redarea. `listen(timeout=...)` permite
opțional așteptare. Proprietățile `is_speaking`, `is_listening` și
`get_status()` expun starea. `check_health()` semnalează oprirea capturii.
`close()` este obligatoriu când nu folosești `with`. Un manager se pornește
o singură dată; pentru repornire creează unul nou.
Un singur consumator trebuie să preia textele din `listen()`.
`speak()` ridică `queue.Full` când coada TTS este plină.

## Separarea procesării

- `microphone.py`: un thread drenează permanent ALSA; cadre PCM16 mono/16 kHz,
  30 ms; coadă limitată cu eliminarea celui mai vechi cadru la suprasarcină.
  `plughw` convertește formatul nativ I2S; se selectează canalul 0 cu semnal.
- `vad.py`: WebRTC VAD inclus în PocketSphinx + prag de energie, pre-roll și
  segmentare după liniște. Frazele și memoria audio au limite explicite.
- `wakeword.py`: keyword spotting PocketSphinx numai pe fraze detectate de VAD.
- `stt.py`: Whisper.cpp, proces separat cu prioritate CPU redusă și două
  threaduri, executat doar pentru comenzi activate. Coada păstrează maximum
  o comandă în așteptare; comenzile suplimentare sunt ignorate și raportate.
- `tts.py`: eSpeak NG română → WAV temporar → `aplay` pe placa configurată.
- `voice_manager.py`: coordonează trei threaduri (VAD/wake, STT, TTS), cozi,
  anulare și starea publică. `process.py` impune timeout și terminarea proceselor.

La `speak()`, intrarea este închisă sincron, STT în curs este anulat, iar
audio/textele vechi sunt invalidate. Microfonul continuă să fie drenat.
Ascultarea revine după redare + 0,5 secunde pentru ecou. Aceasta este operare
half-duplex: utilizatorul trebuie să aștepte terminarea replicii; nu este AEC
și nu permite întreruperea verbală a robotului. Fișierele WAV sunt temporare,
șterse la încheiere; textul recunoscut apare în logul testului.

## Reglaje în `config.py`

| Setare | Efect |
| --- | --- |
| `VOICE_MIC_CHANNEL`, `VOICE_MIC_GAIN` | Canal activ și amplificare software; gain prea mare produce clipping. |
| `VOICE_VAD_MODE` | 0 permisiv, 3 strict. |
| `VOICE_VAD_MIN_DBFS` | Prag energie; valoare mai mare respinge vocea slabă/zgomotul. |
| `VOICE_END_SILENCE_SECONDS` | Pauză care încheie fraza; mărește dacă taie între cuvinte. |
| `VOICE_WAKE_PHONEMES`, `VOICE_WAKE_THRESHOLD` | Pronunția și pragul detectorului „Poro”; necesită calibrare pe voce reală. |
| `VOICE_WAKE_COMMAND_TIMEOUT` | Timp pentru a începe comanda după activare. |
| `VOICE_ECHO_GUARD_SECONDS` | Mărește dacă ecoul difuzorului rămâne după redare. |
| `VOICE_STT_MODEL`, `VOICE_STT_LANGUAGE` | Modelul local și limba; implicit base multilingual cuantizat, română. |
| `VOICE_STT_NORMALIZE_PEAK`, `VOICE_STT_MAX_GAIN` | Normalizare de volum doar pentru STT, implicit peak 0,8 și maximum 16×. |
| `VOICE_STT_THREADS` | Implicit 2 pentru a lăsa CPU și ochilor/perception. |
| `VOICE_STT_AUDIO_CONTEXT` | 512 = 10,24 s; trebuie să acopere limita frazei. |
| `VOICE_TTS_SPEED`, `VOICE_TTS_AMPLITUDE` | Viteza și nivelul vocii sintetice. |

## Limite și diagnostic

eSpeak are voce robotică, iar Whisper base poate greși în română, în special
pe replici scurte/zgomotoase. Nu se pretinde precizie de asistent comercial.
Detectorul „Poro” folosește un model acustic englez cu pronunții configurabile,
**nu un model antrenat dedicat pentru Poro**; poate rata activări sau produce
alarme false. Folosește `--no-wakeword` pentru a testa independent STT/TTS.
Pentru un robot final, calibrăm keyword spotting pe voce reală sau înlocuim
doar `WakeWordDetector`, păstrând API-ul și protecția audio.

Transcrierea este după terminarea frazei, nu streaming. STT poate concura
pentru CPU cu perception; nu este încă o integrare în `main.py`. Nu porni
două procese care folosesc simultan microfonul; verifică `arecord -l`,
`aplay -l` dacă ALSA raportează card indisponibil.

În probele pe acest Pi 4, `base-q5_1` cu context 512 a durat aproximativ
4 secunde/frază. Contextul complet (`VOICE_STT_AUDIO_CONTEXT = 0`) a durat
aproximativ 13 secunde. Modelul `small-q5_1`, descărcat și el pentru comparație,
a durat aproximativ 15 secunde cu context 512 / 48 secunde cu context complet,
fără o îmbunătățire utilă pe captura înfundată; de aceea rămâne implicit base.
Timpii depind de lungimea frazei și încărcarea robotului.

Proba umană la circa 40 cm a avut nivel ~−45…−50 dBFS și cuvinte greu de
înțeles chiar la redarea înregistrării. Captura nativă 48 kHz și modelele
mai mari nu au rezolvat complet problema. Verifică orientarea orificiului
INMP441 către exteriorul carcasei; gain-ul nu poate reface sunete înfundate.
Recunoașterea conversațională în română necesită încă reglaj și retestare;
funcționarea microfonului/TTS și testele de concurență nu înseamnă că STT
are deja precizia dorită.

Testul conversațional pe hardware a confirmat lanțul complet:
`WAKE WORD: poro` → `STT: Salut!` → răspunsul vocal
„Salut! Sunt Poro. Te aud.”. În intervalul observat, captura nu a pierdut
cadre. Această reușită pe o comandă scurtă nu validează încă frazele lungi
sau fiabilitatea activării în zgomot.

Teste automate fără hardware: `/usr/bin/python3 -m unittest tests.test_voice -v`.
Documentație motoare: [Whisper.cpp](https://github.com/ggml-org/whisper.cpp/tree/v1.9.4),
[PocketSphinx](https://pocketsphinx.readthedocs.io/en/latest/pocketsphinx.html),
[eSpeak NG](https://github.com/espeak-ng/espeak-ng).
