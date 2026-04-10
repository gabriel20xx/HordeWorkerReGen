#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

ignore_hordelib=false

# Parse command line arguments
while [[ $# -gt 0 ]]
do
key="$1"

case $key in
    --hordelib)
    hordelib=true
    shift
    ;;
    --scribe)
    scribe=true
    shift
    ;;
    *)    # unknown option
    echo "Unknown option: $key"
    exit 1
    ;;
esac
shift
done

CONDA_ENVIRONMENT_FILE=environment.rocm.yaml

# Determine if the user has a flash attention supported card (gfx1100-gfx1102 covers 7000/8000/9000 series)
SUPPORTED_CARD=$(rocminfo | grep -c -e gfx908 -e gfx90a -e gfx942 -e gfx950 -e gfx1030 -e gfx1100 -e gfx1101 -e gfx1102 -e gfx1200 -e gfx1201)
if [ "$SUPPORTED_CARD" -gt 0 ]; then
    export FLASH_ATTENTION_TRITON_AMD_ENABLE="${FLASH_ATTENTION_TRITON_AMD_ENABLE:=TRUE}"
fi

# 1. Install/Verify Micromamba
echo "--- Ensuring Micromamba is present ---"
wget -qO- https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64.tar.bz2 | tar -xvj -C "${SCRIPT_DIR}"

# 2. Create/Update Environment
if [ ! -f "$SCRIPT_DIR/conda/envs/linux/bin/python" ]; then
    echo "--- Creating new Micromamba environment ---"
    ${SCRIPT_DIR}/bin/micromamba create --no-shortcuts -r "$SCRIPT_DIR/conda" -n linux -f ${CONDA_ENVIRONMENT_FILE} -y
fi
${SCRIPT_DIR}/bin/micromamba update --no-shortcuts -r "$SCRIPT_DIR/conda" -n linux -f ${CONDA_ENVIRONMENT_FILE} -y

# 3. Clean up "Ghost" folders that break imports
echo "--- Cleaning up potential workspace conflicts ---"
rm -rf "$SCRIPT_DIR/mediapipe" 2>/dev/null

# 4. ROCm 7.2.1 Wheel Installation
WHEEL_DIR="$SCRIPT_DIR/rocm_721_wheels"
mkdir -p "$WHEEL_DIR"
cd "$WHEEL_DIR"

echo "--- Downloading ROCm 7.2.1 Wheels ---"
wget -N https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torch-2.9.1%2Brocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl
wget -N https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchvision-0.24.0%2Brocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl
wget -N https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/triton-3.5.1%2Brocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl
wget -N https://repo.radeon.com/rocm/manylinux/rocm-rel-7.2.1/torchaudio-2.9.0%2Brocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl

echo "--- Installing ROCm 7.2.1 Core Stack ---"
${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip uninstall -y torch torchvision torchaudio triton pynvml nvidia-ml-py
${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip install \
    torch-2.9.1+rocm7.2.1.lw.gitff65f5bc-cp312-cp312-linux_x86_64.whl \
    torchvision-0.24.0+rocm7.2.1.gitb919bd0c-cp312-cp312-linux_x86_64.whl \
    torchaudio-2.9.0+rocm7.2.1.gite3c6ee2b-cp312-cp312-linux_x86_64.whl \
    triton-3.5.1+rocm7.2.1.gita272dfa8-cp312-cp312-linux_x86_64.whl

cd "$SCRIPT_DIR"

# 5. Environment Stabilization (The Mediapipe Fix)
echo "--- Fixing Mediapipe and Protobuf for Python 3.12 ---"
${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip uninstall -y mediapipe protobuf opencv-python opencv-contrib-python
${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip install \
    "protobuf>=3.20.2,<5.0.0" \
    "mediapipe==0.10.13" \
    "opencv-python-headless" \
    --no-cache-dir

# 6. Handle Horde components
echo "--- Installing Horde Libraries ---"
if [ "$hordelib" = true ]; then
    ${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip uninstall -y hordelib horde_engine horde_sdk horde_model_reference
    ${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip install horde_engine horde_model_reference --extra-index-url https://download.pytorch.org/whl/rocm7.0
else
    ${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux python -m pip install -r "$SCRIPT_DIR/requirements.rocm.txt" -U --extra-index-url https://download.pytorch.org/whl/rocm7.0
fi

# 7. WSL2 Patching
#WSL_KERNEL=$(uname -a | grep -c -e WSL2 )
#if [ "$WSL_KERNEL" -gt 0 ]; then
#    export IN_WSL="TRUE"
#    echo "WSL environment detected. Patching ROCm libhsa-runtime64.so"
#    for i in $(find "$SCRIPT_DIR/conda" -iname libhsa-runtime64.so); do
#        cp /opt/rocm/lib/libhsa-runtime64.so "$i"
#    done
#fi

# 8. Performance Optimization
echo "--- Running AMD Performance Optimizations ---"
${SCRIPT_DIR}/bin/micromamba run -r "$SCRIPT_DIR/conda" -n linux "$SCRIPT_DIR/horde_worker_regen/amd_go_fast/install_amd_go_fast.sh"

echo "Installation complete."
