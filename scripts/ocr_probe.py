import sys
from pathlib import Path

import pytesseract
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

folder = Path(r"C:\Users\venes\Downloads\Photos-1-001")
for path in sorted(folder.glob("*.PNG")):
    image = Image.open(path)
    print(f"\n===== {path.name}  {image.size} =====")
    text = pytesseract.image_to_string(image)
    for line in (ln.strip() for ln in text.splitlines()):
        if line:
            print("   ", line)
