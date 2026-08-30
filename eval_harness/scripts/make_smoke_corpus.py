"""Generate the frozen smoke-test corpus (eval_harness/datasets/smoke/files/).

Entirely fictional content, authored for exact-match questions. The generated
files are COMMITTED (frozen fixtures - the smoke test's whole point is a
stable baseline); rerun this only to deliberately re-baseline, then re-run
the smoke calibration.

Two PNGs are rendered so the smoke run exercises the visual tier (walker
image routing -> ColQwen/ColSmol indexing -> visual retrieval): every
catastrophic incident the harness has caught so far lived on that path.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "datasets" / "smoke" / "files"

TEXTS = {
    "wifi_and_home.md": """# Home setup notes

Router: TP-Link Archer C7, admin panel 192.168.0.1
Guest wifi network: BlueHeronGuest
Guest wifi password: mango-telescope-42

Electricity account number with Fictional Power Co: FP-8823-1190.
""",
    "car_service.txt": """Service log - 2011 Toyota Corolla (plate WXY 4821)

2026-02-14  Oil change + filter at QuickLube Garage, RM 145.00
2026-05-03  Front brake pads replaced at QuickLube Garage, RM 380.00
Next service due: 2026-11-01 or 68,000 km, whichever first.
""",
    "recipe_pasta.md": """# Nonna's fake carbonara (family version)

Serves 3. Key trick: 45 grams of pecorino per person, never parmesan.
Guanciale: 120 g, cut thick. Two whole eggs plus one yolk.
Salt the water with exactly 1.5 tablespoons of coarse salt.
""",
    "meeting_notes_atlas.md": """# Atlas project sync - 2026-03-12

Attendees: Priya, Tomas, Jun.
Decision: launch date moved to 2026-09-30 (was 2026-08-15).
Budget approved: 24,500 USD for the pilot phase.
Action: Tomas owns the vendor contract with Meridian Labs.
""",
    "library_books.txt": """Borrowed from Riverside Community Library:

1. "The Salt Path" - due 2026-04-18
2. "Thinking in Systems" - due 2026-04-25
3. "The Overstory" - due 2026-05-02

Library card number: RCL-30991.
""",
    "insurance_policy.md": """# Renter's insurance summary

Provider: Sundial Mutual (fictional)
Policy number: SM-77-40213
Annual premium: 312.40 USD, renews every 1st of July.
Coverage cap for electronics: 5,000 USD per incident.
""",
    "gym_plan.txt": """Gym: IronWorks Fitness, membership M-5567.
Monthly fee 89 ringgit, locked until 2026-12-31.
Tuesday: squats 5x5 at 82.5 kg. Friday: deadlift 3x5 at 110 kg.
""",
    "flight_booking.md": """# Trip to Osaka - booking summary

Airline: Pelican Air (fictional), booking reference PLC7QZ.
Outbound: 2026-10-12, flight PA-441, seat 23A.
Return: 2026-10-19, flight PA-442, seat 21C.
Total paid: 2,140 MYR including one checked bag of 23 kg.
""",
}

IMAGES = {
    "parking_receipt.png": [
        "CITYPARK GARAGE - LEVEL B2",
        "Ticket: CP-100482",
        "Entry:  2026-06-02 09:14",
        "Exit:   2026-06-02 17:41",
        "Duration: 8 hr 27 min",
        "TOTAL: RM 26.50",
        "Pay at kiosk before exit",
    ],
    "package_label.png": [
        "SWIFTPOST EXPRESS",
        "Tracking: SP-99-31877-KL",
        "From: Chen's Electronics, Penang",
        "To: Unit 12-3, Jalan Fiksyen 8",
        "Weight: 2.4 kg",
        "COD amount: RM 189.00",
    ],
}


def render_png(path: Path, lines: list[str]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default(size=30)
    except TypeError:  # older Pillow: no size kwarg
        font = ImageFont.load_default()
    w, h = 640, 80 + 48 * len(lines)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for line in lines:
        d.text((40, y), line, fill="black", font=font)
        y += 48
    img.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in TEXTS.items():
        (OUT / name).write_text(text, encoding="utf-8")
    for name, lines in IMAGES.items():
        render_png(OUT / name, lines)
    print(f"smoke corpus: {len(TEXTS)} text + {len(IMAGES)} image files -> {OUT}")


if __name__ == "__main__":
    main()
