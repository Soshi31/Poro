# Creierul local Poro

`BrainAgent` folosește `llama-server` pe **127.0.0.1** și un model **GGUF
cuantizat**. Nu există apeluri către cloud. Modelul este încărcat o singură
dată; inferența rulează într-un worker separat, în timp ce ochii, camera,
audio și IMU continuă să funcționeze. Agentul primește doar stări structurate
și evenimente recente, nu cadre video brute.

Modelul inițial pentru Raspberry Pi 4 este
`Qwen2.5-1.5B-Instruct-Q4_K_M` (~1,04 GiB pe disc), publicat de Qwen. Pentru
alt model GGUF schimbă `LLM_MODEL_PATH` în `config.py`; `brain/` nu conține
cod specific familiei de model. Tot acolo poți regla `LLM_CONTEXT_SIZE`,
`LLM_THREADS`, `LLM_BATCH_SIZE`, `LLM_MAX_TOKENS`, temperatura, top-p,
penalty și timeout-urile. Pe montajul testat, `LLM_THREADS=2` și
`LLM_CPU_AFFINITY=(2, 3)` rezervă primele două nuclee pentru ochi,
cameră și audio. Pune `LLM_CPU_AFFINITY=None` pe altă configurație CPU.
Pe Pi-ul actual, cu modelul încărcat, testul complet a produs un răspuns
românesc corect în ~78 s (301 tokeni prompt, 25 generați), cu un vârf
`VmHWM` de ~1245 MiB pentru `llama-server`; ochii au rulat cu ~12,5 FPS
în timpul inferenței. Valorile sunt orientative, nu o promisiune de latență.

## Instalare și verificare

Runtime-ul este construit în `third_party/llama.cpp/build/bin/llama-server`.
Dovada locală a versiunii folosite la validare: commit `4b1a27fa0eb8`.
Dacă trebuie reconstruit:

```bash
cd /home/poro/Poro
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git third_party/llama.cpp
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON
cmake --build third_party/llama.cpp/build --target llama-server llama-bench -j 2
```

Descarcă modelul oficial într-un fișier `.part`, verifică lungimea/hash-ul,
apoi redenumește-l `.gguf`:

```bash
mkdir -p models/llm
curl -L --fail --retry 3 -C - -o models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf.part 'https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true'
echo '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e  models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf.part' | sha256sum -c
mv models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf.part models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Pornește benchmark-ul local fără cameră sau voce:

```bash
/usr/bin/python3 brain_benchmark.py --tokens 64
```

Rezultatul raportează timpul per cerere, tokenii generați, debitul efectiv
tokens/s (include evaluarea promptului) și `VmHWM` al procesului
`llama-server` în MiB. Pentru un benchmark separat al decodării pure:

```bash
taskset --cpu-list 2,3 third_party/llama.cpp/build/bin/llama-bench -m models/llm/qwen2.5-1.5b-instruct-q4_k_m.gguf -t 2 -p 128 -n 64 -r 1
```

Rulează Poro complet:

```bash
/usr/bin/python3 brain_test.py
```

`--text 'Salut, cine ești?' --duration 120` trimite o cerere inițială fără
microfon, utilă pentru diagnostic. În rularea normală, `VoiceManager`
furnizează textul STT după wake word; agentul îl procesează asincron și
trimite răspunsul la TTS prin `BehaviorManager`. La ieșire se opresc serverul
local și toate resursele hardware.

## Arhitectură și contract

- `llm.py`: pornește `llama-server` local, trimite chat completions cu schema
  JSON și măsoară latență/RAM.
- `personality.txt` și `prompts.py`: personalitate și instrucțiuni separate
  de cod; parser JSON strict, limită de lungime și număr de acțiuni.
- `memory.py`: memorie SQLite locală cu tabele separate pentru replicile
  recente, fapte/preferințe persistente și evenimente semantice. Migrează
  automat tabelul vechi `memories`, păstrând datele. Fiecare tabel are limită
  configurabilă; căutarea lexicală folosește cel mult 1000 fapte și 500
  evenimente implicit, fără embeddings/cloud.
- `context.py`: selectează cel mult două amintiri relevante pentru mesajul
  curent și ultimele replici, împreună cu starea scenei/IMU/robotului.
  Evenimentele IMU sunt salvate între prompturi de un worker separat.
- `visual.py`: adaptor on-demand către `PerceptionSystem`; backend-ul vizual
  se alege prin `BRAIN_VISUAL_BACKEND` în `config.py`. Cadrele color sunt
  capturate doar la cerere și nu apar în prompt.
- `tool_registry.py`: allowlist de acțiuni cu validare per tool; nu importă
  GPIO, SPI sau driverele display-urilor. `tongue()` primește doar acțiuni
  semantice, niciodată grade.
- `agent.py`: coadă limitată, un singur worker; cel mult două runde LLM pentru
  citiri suplimentare și maximum patru acțiuni per răspuns. Răspunsul invalid
  este raportat, thinking se încheie, iar următoarea cerere poate continua.
- `intent.py`: câteva imperative românești exacte sunt trimise direct către
  aceeași allowlist de tools, fără inferență. Astfel comenzile fizice clare
  răspund rapid și nu depind de selectarea corectă a tool-ului de către
  modelul mic. Alte formulări și conversația liberă trec prin LLM.

Modelul poate apela `set_emotion`, `look_at_person`, `look_at`, `tongue`,
`speak`, `get_vision_state`, `inspect_scene`, `inspect_center_object`,
`capture_snapshot`, `answer_visual_question`, `get_imu_state`, `remember`,
`recall`, `get_robot_state`, `sleep` și `wake_up`. Acestea sunt apeluri locale
validate către managerii existenți; modelul nu poate executa cod arbitrar.
`inspect_scene` cere o analiză lentă nouă și așteaptă cel mult
`BRAIN_VISUAL_TIMEOUT` în worker-ul agentului, fără să blocheze ochii.
`inspect_center_object` folosește numai detecții de obiecte proaspete;
`capture_snapshot` salvează JPEG local în `snapshots/`, fără să trimită
imaginea LLM-ului; `answer_visual_question(question)` folosește backend-ul
configurat. Implicit, `StructuredVisionBackend` știe doar despre fețe,
mișcare și detecțiile de obiecte disponibile; nu există încă un detector de
obiecte sau un model vizual semantic instalat. De aceea întrebări precum
„Ce am în mână?” primesc un răspuns onest când dovezile sunt insuficiente.
Backend-ul viitor poate folosi un cadru RGB on-demand (`requires_frame=True`)
și întoarce numai JSON structurat, fără schimbări în agent.
Memoria este în `brain/memory.sqlite3`, exclusă din versionare.

API-ul Python pentru viitorul agent:

```python
from brain.memory import MemoryStore

with MemoryStore() as memory:
    memory.remember("Utilizatorului îi place ceaiul", kind="preference")
    memory.remember("Poro are ochi albaștri")  # kind="fact" implicit
    memory.add_event("picked_up", {"source": "bno085"})
    memory.add_turn("user", "Salut")
    memory.add_turn("assistant", "Bună!")
    print(memory.recall("ceai"))           # numai fapte/preferințe
    print(memory.search_memories("ridicat"))  # inclusiv evenimente
    print(memory.recent_events(limit=5))
    print(memory.recent_conversation())
```

`BRAIN_MEMORY_LIMIT`, `BRAIN_CONVERSATION_LIMIT`,
`BRAIN_EVENT_MEMORY_LIMIT`, `BRAIN_HISTORY_TURNS` și
`BRAIN_CONTEXT_MAX_CHARS` se reglează în `config.py`. Nu sunt necesare pachete
noi: SQLite este în biblioteca standard Python.

Limitări practice: modelul de 1,5B poate greși româna, selecția tool-urilor
sau faptele; parserul respinge output-ul invalid, dar nu poate transforma
un model mic într-un planificator perfect. Cu Q4 și 2048 tokeni context,
prompturile sunt scurte; mărește contextul doar după un benchmark de RAM.
TTS deja pornit nu poate fi întrerupt de `sleep()` în VoiceManager actual.
Testul `llama-bench` pe două nuclee a măsurat 4,78 tokeni/s pentru 128 tokeni
de prompt și 3,54 tokeni/s la generarea a 64 tokeni. Modelul alternativ
Qwen2.5 0.5B Q4_K_M este în `models/llm/`, dar într-o probă a repetat
întrebarea utilizatorului; nu este implicit. Wake word/STT existent poate
declanșa rar o recunoaștere falsă după TTS; calibrarea audio rămâne separată.
