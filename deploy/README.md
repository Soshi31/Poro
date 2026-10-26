# Pornirea completă a lui Poro

Din `/home/poro/Poro`, fără virtual environment:

```sh
/usr/bin/python3 main.py
```

Pentru un test limitat la 3 minute, fără să aștepți wake word-ul:

```sh
/usr/bin/python3 main.py --text 'Salut, Poro! Cine ești?' --duration 180
```

Pachetele noi pentru vocea română Piper sunt instalabile astfel:

```sh
sudo apt install sox alsa-utils
/usr/bin/python3 -m pip install --user --break-system-packages piper-tts==1.8.0
```

Pentru backend-ul LLM optimizat pe CPU ARM:

```sh
sudo apt install cmake libopenblas-dev
cmake -S third_party/llama.cpp -B third_party/llama.cpp/build-openblas \
  -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON -DGGML_BLAS=ON \
  -DGGML_BLAS_VENDOR=OpenBLAS -DLLAMA_CURL=OFF
cmake --build third_party/llama.cpp/build-openblas -j3 --target llama-server llama-bench
```

Modelul TTS și fișierul său `.onnx.json` se descarcă împreună în `models/tts/`.
Implicit este selectată vocea indicată de `VOICE_TTS_MODEL` din `config.py`.
Difuzorul este acum oprit prin `VOICE_OUTPUT_ENABLED = False`; ascultarea și STT
continuă. Când vei putea folosi din nou boxa, setează `True` și repornește Poro.
Modelele românești folosite la evaluare sunt [Lili](https://huggingface.co/eduardem/piper-tts-romanian)
și [Liana](https://huggingface.co/eduardem/piper-liana-romanian), licență CC-BY-NC-4.0.

Pe Raspberry Pi 4B 8 GB, cu OpenBLAS și LLM pe nucleele 2–3, comparația
Qwen2.5 Q4_K_M a fost:

| Model | Prompt 128 tokeni | Generare 16 tokeni | Răspuns scurt izolat | RAM maxim llama-server |
| --- | ---: | ---: | ---: | ---: |
| 1,5B | 6,96 tok/s | 3,56 tok/s | 19,33 s | 1 245 MiB |
| 3B | 3,28 tok/s | 1,84 tok/s | 36,82 s | 2 238 MiB |

În sistemul complet, 1,5B a răspuns la o întrebare deschisă în 91 s; 3B a
depășit timeout-ul de 120 s. De aceea `LLM_MODEL_PATH` indică 1,5B. Modelul
3B rămâne instalat și poate fi selectat din `config.py`, dar nu este recomandat
pentru conversația simultană cu camera și ochii pe Pi 4.

Pentru pornire automată la boot, după ce testul manual a reușit:

```sh
sudo cp /home/poro/Poro/deploy/poro.service /etc/systemd/system/poro.service
sudo systemctl daemon-reload
sudo systemctl enable --now poro.service
systemctl status poro.service --no-pager
journalctl -u poro.service -f
```

Oprire: `sudo systemctl stop poro.service`. Serviciul folosește exact interpreterul
`/usr/bin/python3` și utilizatorul `poro`, care are acces la grupurile `audio`,
`video`, `spi`, `i2c` și `gpio` pe montajul actual.
