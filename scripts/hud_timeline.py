"""Read the battle HUD from every frame into a timeline of map, turn and team HP."""

import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "frames" / "battle"
OUT = ROOT / "data" / "analysis" / "hud_timeline.csv"
RECORDING = Path(r"C:\Users\venes\Downloads\ScreenRecording_10-18-2026 12-52-46_1.mp4")

FPS = 2.0
START_OFFSET = 5.0
DURATION = 281.0
MAX_TEAM_HP = 9296

TEAM_HP_BOX = (795, 1870, 1095, 1960)
MAP_BOX = (370, 128, 460, 176)
TURN_BOX = (368, 183, 442, 232)
POPUP_BOX = (0, 430, 1180, 900)

DIGITS = "--psm 7 -c tessedit_char_whitelist=0123456789/"


def read(image: Image.Image, box: tuple[int, int, int, int]) -> str:
    crop = image.crop(box)
    crop = crop.resize((crop.width * 4, crop.height * 4), Image.LANCZOS)
    return pytesseract.image_to_string(crop, config=DIGITS).strip()


def parse_team_hp(text: str) -> int | None:
    """The '/9296' suffix anchors the reading; OCR garbles the slash itself."""
    digits = re.sub(r"\D", "", text)
    marker = digits.rfind(str(MAX_TEAM_HP))
    if marker <= 0:
        return None
    prefix = digits[:marker]
    for width in (4, 3, 2, 1):
        if len(prefix) >= width:
            value = int(prefix[:width])
            if 0 < value <= MAX_TEAM_HP:
                return value
    return None


def parse_small_int(text: str, limit: int) -> int | None:
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    value = int(digits[:2]) if len(digits) >= 2 else int(digits)
    return value if 0 < value <= limit else None


def find_ffmpeg() -> str:
    """winget installs a shim under Links, but it is not always on PATH here."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [local / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"]
    packages = local / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        candidates.extend(packages.glob("*FFmpeg*/**/bin/ffmpeg.exe"))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("ffmpeg not found")


if "--extract" in sys.argv:
    FOLDER.mkdir(parents=True, exist_ok=True)
    for stale in FOLDER.glob("*.jpg"):
        stale.unlink()
    subprocess.run(
        [
            find_ffmpeg(),
            "-v",
            "error",
            "-nostdin",
            "-ss",
            str(START_OFFSET),
            "-i",
            str(RECORDING),
            "-t",
            str(DURATION),
            "-vf",
            f"fps={FPS}",
            "-q:v",
            "2",
            str(FOLDER / "b_%04d.jpg"),
        ],
        check=True,
    )

frames = sorted(FOLDER.glob("*.jpg"))
print(f"frames={len(frames)}")
OUT.parent.mkdir(parents=True, exist_ok=True)

rows = []
previous_hp = None
for index, frame in enumerate(frames):
    image = Image.open(frame)
    team_hp = parse_team_hp(read(image, TEAM_HP_BOX))

    # Only worth the slow wide-region OCR when HP rose, to tell a heal from a misread.
    note = ""
    if team_hp is not None and previous_hp is not None and team_hp > previous_hp:
        crop = image.crop(POPUP_BOX)
        crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
        text = pytesseract.image_to_string(crop, config="--psm 11")
        note = " ".join(
            line.strip()
            for line in text.splitlines()
            if any(word in line for word in ("Recovery", "Critical", "Boost", "Heal"))
        )
    if team_hp is not None:
        previous_hp = team_hp

    rows.append(
        {
            "frame": frame.name,
            "time_s": round(START_OFFSET + index / FPS, 2),
            "map": parse_small_int(read(image, MAP_BOX), 9),
            "turn": parse_small_int(read(image, TURN_BOX), 99),
            "team_hp": team_hp,
            "note": note,
        }
    )

with OUT.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=["frame", "time_s", "map", "turn", "team_hp", "note"]
    )
    writer.writeheader()
    writer.writerows(rows)

read_hp = sum(1 for r in rows if r["team_hp"] is not None)
read_turn = sum(1 for r in rows if r["turn"] is not None)
read_map = sum(1 for r in rows if r["map"] is not None)
print(f"frames={len(rows)} hp={read_hp} turn={read_turn} map={read_map}")
print(f"wrote {OUT}")
