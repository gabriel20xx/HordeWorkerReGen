# Uninstall deprecated pynvml package to ensure nvidia-ml-py is used instead
. venv/bin/activate
python -m pip uninstall -y pynvml
