#!/usr/bin/env bash
# Dependențe locale în proiect; fără venv, sudo sau modificări Python OS.
set -euo pipefail
poro_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$poro_root"
for command in cmake g++ make git curl arecord aplay espeak-ng; do
    if ! command -v "$command" >/dev/null; then
        echo "Lipsește $command. Instalează:"
        echo "sudo apt update && sudo apt install build-essential cmake git curl alsa-utils espeak-ng python3-pip python3-numpy"
        exit 1
    fi
done
/usr/bin/python3 -c 'import numpy' || exit 1
if ! /usr/bin/python3 -c 'from voice.dependencies import pocketsphinx; pocketsphinx(); from importlib.metadata import version; assert version("pocketsphinx") == "5.1.1"' 2>/dev/null; then
    /usr/bin/python3 -m pip install --target voice/_vendor --upgrade --no-deps --only-binary=:all: pocketsphinx==5.1.1
fi
whisper_commit=927cfce34f31707e17f2bff35c349632fb9e2c3a
if [[ ! -d third_party/whisper.cpp ]]; then
    mkdir -p third_party
    git clone --depth 1 --branch v1.9.4 https://github.com/ggml-org/whisper.cpp.git third_party/whisper.cpp
fi
if [[ "$(git -C third_party/whisper.cpp rev-parse HEAD)" != "$whisper_commit" ]]; then
    echo "Versiune whisper.cpp diferită de v1.9.4; checkout-ul existent nu a fost modificat."
    exit 1
fi
cmake -S third_party/whisper.cpp -B third_party/whisper.cpp/build \
    -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF \
    -DGGML_OPENMP=OFF -DWHISPER_BUILD_EXAMPLES=ON
cmake --build third_party/whisper.cpp/build --target whisper-cli -j 2
mkdir -p models/voice
model_file=models/voice/ggml-base-q5_1.bin
if [[ ! -f "$model_file" ]]; then
    curl --fail --location --retry 3 \
        https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base-q5_1.bin \
        --output "$model_file.part"
    echo "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898  $model_file.part" | sha256sum --check
    mv "$model_file.part" "$model_file"
fi
echo "422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898  $model_file" | sha256sum --check
echo "Instalare completă. Test: /usr/bin/python3 voice_test.py"
