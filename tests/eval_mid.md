# Stage 4 Eval Results

- Run: 2026-04-12 23:43:11 UTC
- Model: kimi-k2.5 via Moonshot
- Difficulty filter: medium
- Total: 12 (12 succeeded, 0 errored)
- medium: 12

## Aggregate

- Questions with **perfect source recall** (all expected files cited): 12/12
- Questions that **cited no distractors**: 12/12
- Total distractor citations across all questions: 0

## Summary table

| ID | Difficulty | Source recall | Source precision | Distractors cited | Elapsed (s) |
|---|---|---|---|---|---|
| medium-01 | medium | 1/1 | 1/1 | 0 | 21.9 |
| medium-02 | medium | 1/1 | 1/1 | 0 | 9.3 |
| medium-03 | medium | 2/2 | 2/2 | 0 | 22.7 |
| medium-04 | medium | 1/1 | 1/1 | 0 | 30.4 |
| medium-05 | medium | 1/1 | 1/1 | 0 | 34.0 |
| medium-06 | medium | 1/1 | 1/1 | 0 | 30.2 |
| medium-07 | medium | 1/1 | 1/1 | 0 | 12.0 |
| medium-08 | medium | 1/1 | 1/1 | 0 | 17.2 |
| medium-09 | medium | 1/1 | 1/1 | 0 | 15.5 |
| medium-10 | medium | 1/1 | 1/1 | 0 | 13.9 |
| medium-11 | medium | 1/1 | 1/1 | 0 | 20.5 |
| medium-12 | medium | 1/1 | 1/1 | 0 | 43.2 |

## Per-question results

### medium-01 — medium

**Question:** What token type does the DEC tokenizer assign to the symbol ':='?

**Expected answer:** ASSIGNMENT.

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Lab 5 - Parser.pdf`
- `Test Content/DataFest Schedule.docx`

**Files Kimi cited as sources:**
- `Test Content/Lab 3 - Tokenizer.pdf` (expected)

**Kimi's answer:**

The DEC tokenizer assigns the token type **ASSIGNMENT** to the symbol ':='.

*Elapsed: 21.9s*

---

### medium-02 — medium

**Question:** According to MTH-245 Handout 0, what minimum sample size does the Central Limit Theorem generally require for a test about a population mean?

**Expected answer:** n >= 30.

**Expected source files:**
- `Test Content/MTH_245_Handout_0.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/MTH_245_Handout_5.pdf`
- `Test Content/Lab 1 - Doubly-Linked Lists.pdf`

**Files Kimi cited as sources:**
- `Test Content/MTH_245_Handout_0.pdf` (expected)

**Kimi's answer:**

According to MTH-245 Handout 0, the Central Limit Theorem generally holds when the sample size $n \geq 30$ (i.e., a minimum sample size of 30) for a test or interval about a population mean.

*Elapsed: 9.3s*

---

### medium-03 — medium

**Question:** Who is the travel companion on the Yale trip according to the flight receipts?

**Expected answer:** Rahul Ranjan Sah.

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Hotel YQuantum Receipt.pdf`
- `Test Content/Period Changes for Fourteen Novae (2023).pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight GSP - Hartford Receipt.pdf` (expected)
- `Test Content/Flight Yale - GSP Receipt.pdf` (expected)

**Kimi's answer:**

Rahul Ranjan Sah

*Elapsed: 22.7s*

---

### medium-04 — medium

**Question:** In the Artwork Analysis essay, what three flowchart shapes does the author use, and what does each represent?

**Expected answer:** Rectangles = processing / a learning step; parallelograms = output or an endpoint of the educational journey; diamonds = decision/assessment units.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Plato's Allegory of the Cave.docx`
- `Test Content/Lab 7 - Graphs.pdf`

**Files Kimi cited as sources:**
- `Test Content/Artwork Analysis.docx` (expected)

**Kimi's answer:**

The author uses three flowchart shapes in the artwork: **rectangles** for processing or learning, **parallelograms** for output or for the end of the educational journey, and **diamonds** for decision units or assessments that define the ability of the people and the path they will take.

*Elapsed: 30.4s*

---

### medium-05 — medium

**Question:** In the Letter from Birmingham Jail, what four basic steps does King say every nonviolent campaign undertakes?

**Expected answer:** (1) Collection of facts to determine whether injustices exist, (2) negotiation, (3) self-purification, (4) direct action.

**Expected source files:**
- `Test Content/MLK Letter.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Machiavelli Papier.docx`
- `Test Content/Uber Furman - GSP (Reservation).png`

**Files Kimi cited as sources:**
- `Test Content/MLK Letter.pdf` (expected)

**Kimi's answer:**

According to Martin Luther King Jr.'s 'Letter from Birmingham Jail,' the four basic steps that every nonviolent campaign undertakes are: (1) collection of the facts to determine whether injustices exist; (2) negotiation; (3) self-purification; and (4) direct action.

*Elapsed: 34.0s*

---

### medium-06 — medium

**Question:** In the Plato's Allegory of the Cave essay, what six subjects are listed as the leader's curriculum, in order?

**Expected answer:** Arithmetic, plane geometry, 3D geometry, astronomy, harmonics (the numerical / mathematical study of music), and dialectic.

**Expected source files:**
- `Test Content/Plato's Allegory of the Cave.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Artwork Analysis.docx`
- `Test Content/MTH_245_Handout_5.pdf`

**Files Kimi cited as sources:**
- `Test Content/Plato's Allegory of the Cave.docx` (expected)

**Kimi's answer:**

According to the essay, the six subjects listed as the leader's curriculum, in order, are:

1. Arithmetic
2. Plane geometry
3. 3D geometry
4. Astronomy
5. Harmonics
6. Dialectic

*Elapsed: 30.2s*

---

### medium-07 — medium

**Question:** Which buildings are used during DataFest Saturday's work time?

**Expected answer:** Furman Hall, Johns Hall, and Duke Library (on Saturday, April 5).

**Expected source files:**
- `Test Content/DataFest Schedule.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Lab 0 - Utilities & Xunit Tests.pdf`

**Files Kimi cited as sources:**
- `Test Content/DataFest Schedule.docx` (expected)

**Kimi's answer:**

Furman Hall, Johns Hall, and Duke Library.

*Elapsed: 12.0s*

---

### medium-08 — medium

**Question:** According to the Machiavelli essay, what two kinds of principalities are highlighted?

**Expected answer:** Monarchies and Republics.

**Expected source files:**
- `Test Content/Machiavelli Papier.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Plato's Allegory of the Cave.docx`
- `Test Content/MLK Letter.pdf`

**Files Kimi cited as sources:**
- `Test Content/Machiavelli Papier.docx` (expected)

**Kimi's answer:**

According to the Machiavelli essay, the two kinds of principalities highlighted are **Monarchies** and **Republics**.

*Elapsed: 17.2s*

---

### medium-09 — medium

**Question:** What is the pickup and drop-off of the Uber reserved for April 3 at 10:53 PM, and how much was it?

**Expected answer:** Pickup at Curbside - Outside Curb (Hartford airport), drop-off at Graduate by Hilton New Haven; $69.93.

**Expected source files:**
- `Test Content/Uber Hartford - Yale (Reservation).png`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Uber GSP - Furman (Reservation).png`
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Files Kimi cited as sources:**
- `Test Content/Uber Hartford - Yale (Reservation).png` (expected)

**Kimi's answer:**

The Uber reserved for April 3 at 10:53 PM has a pickup at "Curbside - Outside Curb" and a drop-off at "Graduate by Hilton New Haven". The cost was $69.93.

*Elapsed: 15.5s*

---

### medium-10 — medium

**Question:** What is the customer reference number on the Breeze Airways flight receipt?

**Expected answer:** 40-920412413.

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/MLK Letter.pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight GSP - Hartford Receipt.pdf` (expected)

**Kimi's answer:**

40-920412413

*Elapsed: 13.9s*

---

### medium-11 — medium

**Question:** According to the Artwork Analysis essay, what do students who fail at understanding harmonies in their abstract form go on to become, and what about those who fail astronomy?

**Expected answer:** Those who fail harmonies become 'Harmon-ists' who make, tune, and study instruments. Those who fail astronomy (the pure-logic/math understanding of stellar motions) become Astronomers who build telescopes and study stars.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Plato's Allegory of the Cave.docx`
- `Test Content/Period Changes for Fourteen Novae (2023).pdf`

**Files Kimi cited as sources:**
- `Test Content/Artwork Analysis.docx` (expected)

**Kimi's answer:**

According to the *Artwork Analysis* essay, students who fail at understanding harmonies in their true, abstract form become “Harmon-ists” who make, tune and study instruments. Those who fail at understanding and inferring the motions of stars using pure logic and math (astronomy) become Astronomers who make telescopes and study stars.

*Elapsed: 20.5s*

---

### medium-12 — medium

**Question:** What airline operated the return flight from New Haven to Greenville-Spartanburg, and what is its airline reference?

**Expected answer:** Avelo Airlines (code XP), reference 87K77A.

**Expected source files:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Hotel YQuantum Receipt.pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight Yale - GSP Receipt.pdf` (expected)

**Kimi's answer:**

The return flight from New Haven to Greenville-Spartanburg was operated by **Avelo Airlines** (airline code XP) with airline reference **87K77A**.

*Elapsed: 43.2s*

---

