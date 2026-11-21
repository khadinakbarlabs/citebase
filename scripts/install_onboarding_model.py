"""Install the fixed, licensed model when the Actor image is built."""
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

REVISION = "389b9f64be5aa4ae7a6bc6fe95ef20ce485ae5da"
BASE = f"https://huggingface.co/minishlab/potion-base-2M/resolve/{REVISION}"
ARTIFACTS = {
    "model.safetensors": (7559256, "f95ffde02ad06f63ae38eb9d400038cd5ccaf8411ec3cb650c6025113f96cbb8"),
    "tokenizer.json": (683666, "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50"),
    "config.json": (200, "b2a89173391ca774c2d7323090a993a9a1553faa5b40eb37bb7cec6685fbea47"),
}


def install(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, checksum) in ARTIFACTS.items():
        with urlopen(f"{BASE}/{name}?download=true", timeout=45) as reply:
            payload = reply.read(size + 1)
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != checksum:
            raise ValueError(f"Model artifact failed integrity validation: {name}")
        (directory / name).write_bytes(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    install(parser.parse_args().directory)
