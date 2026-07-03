# Stage 4 Eval Results

- Run: 2026-04-12 23:38:06 UTC
- Model: kimi-k2.5 via Moonshot
- Difficulty filter: easy
- Total: 12 (12 succeeded, 0 errored)
- easy: 12

## Aggregate

- Questions with **perfect source recall** (all expected files cited): 12/12
- Questions that **cited no distractors**: 12/12
- Total distractor citations across all questions: 0

## Summary table

| ID | Difficulty | Source recall | Source precision | Distractors cited | Elapsed (s) |
|---|---|---|---|---|---|
| easy-01 | easy | 1/1 | 1/1 | 0 | 21.2 |
| easy-02 | easy | 1/1 | 1/1 | 0 | 13.4 |
| easy-03 | easy | 1/1 | 1/1 | 0 | 19.9 |
| easy-04 | easy | 1/1 | 1/1 | 0 | 17.6 |
| easy-05 | easy | 1/1 | 1/1 | 0 | 13.6 |
| easy-06 | easy | 1/1 | 1/1 | 0 | 24.3 |
| easy-07 | easy | 1/1 | 1/1 | 0 | 17.9 |
| easy-08 | easy | 1/1 | 1/1 | 0 | 19.3 |
| easy-09 | easy | 1/1 | 1/1 | 0 | 15.7 |
| easy-10 | easy | 1/1 | 1/1 | 0 | 20.4 |
| easy-11 | easy | 2/2 | 2/2 | 0 | 18.1 |
| easy-12 | easy | 1/1 | 1/1 | 0 | 12.5 |

## Per-question results

### easy-01 — easy

**Question:** Which airline operated the flight from Greenville-Spartanburg to Bradley (Hartford)?

**Expected answer:** Breeze Airways (airline code MX).

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/MTH_245_Handout_0.pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight GSP - Hartford Receipt.pdf` (expected)

**Kimi's answer:**

Breeze Airways (listed as "MX - Breeze Airways") operated the flight from Greenville-Spartanburg to Bradley (Hartford).

*Elapsed: 21.2s*

---

### easy-02 — easy

**Question:** What is the hotel booking number for the stay at Graduate by Hilton New Haven?

**Expected answer:** 12473171

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Lab 3 - Tokenizer.pdf`

**Files Kimi cited as sources:**
- `Test Content/Hotel YQuantum Receipt.pdf` (expected)

**Kimi's answer:**

The hotel booking number for the stay at Graduate by Hilton New Haven is 12473171.

*Elapsed: 13.4s*

---

### easy-03 — easy

**Question:** On what date was the return flight from New Haven to Greenville-Spartanburg?

**Expected answer:** 5 April 2026

**Expected source files:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/MLK Letter.pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight Yale - GSP Receipt.pdf` (expected)

**Kimi's answer:**

The return flight from New Haven to Greenville-Spartanburg was on **April 5, 2026** (5 April 2026).

*Elapsed: 19.9s*

---

### easy-04 — easy

**Question:** Who wrote the Letter from Birmingham Jail?

**Expected answer:** Martin Luther King Jr.

**Expected source files:**
- `Test Content/MLK Letter.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Machiavelli Papier.docx`
- `Test Content/Uber GSP - Furman (Reservation).png`

**Files Kimi cited as sources:**
- `Test Content/MLK Letter.pdf` (expected)

**Kimi's answer:**

Martin Luther King Jr. wrote the Letter from Birmingham Jail.

*Elapsed: 17.6s*

---

### easy-05 — easy

**Question:** What is the only keyword in the DEC programming language used in Lab 3?

**Expected answer:** return

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Lab 2 - Symbol Tables.pdf`
- `Test Content/Hotel YQuantum Receipt.pdf`

**Files Kimi cited as sources:**
- `Test Content/Lab 3 - Tokenizer.pdf` (expected)

**Kimi's answer:**

return

*Elapsed: 13.6s*

---

### easy-06 — easy

**Question:** What is the total amount paid for the hotel stay in New Haven?

**Expected answer:** $159.00 USD (room $138.26 + taxes and fees $20.74).

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/Plato's Allegory of the Cave.docx`

**Files Kimi cited as sources:**
- `Test Content/Hotel YQuantum Receipt.pdf` (expected)

**Kimi's answer:**

$159.00

*Elapsed: 24.3s*

---

### easy-07 — easy

**Question:** At what time does check-in start at Graduate by Hilton New Haven?

**Expected answer:** From 4:00 PM.

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Uber Hartford - Yale (Reservation).png`
- `Test Content/MTH_245_Handout_5.pdf`

**Files Kimi cited as sources:**
- `Test Content/Hotel YQuantum Receipt.pdf` (expected)

**Kimi's answer:**

Check-in starts at 4:00 PM.

*Elapsed: 17.9s*

---

### easy-08 — easy

**Question:** On what day of DataFest are the winners announced?

**Expected answer:** Sunday, April 6 (between 1:30 and 2:00 PM, in the Watkins Room of the Trone Center).

**Expected source files:**
- `Test Content/DataFest Schedule.docx`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Files Kimi cited as sources:**
- `Test Content/DataFest Schedule.docx` (expected)

**Kimi's answer:**

The winners are announced on Sunday, April 6th (the final day of DataFest), specifically from 1:30 – 2:00 PM.

*Elapsed: 19.3s*

---

### easy-09 — easy

**Question:** How many novae are studied in the astronomy paper titled 'Period Changes...'?

**Expected answer:** Fourteen (14).

**Expected source files:**
- `Test Content/Period Changes for Fourteen Novae (2023).pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/MTH_245_Handout_10.pdf`
- `Test Content/Plato's Allegory of the Cave.docx`

**Files Kimi cited as sources:**
- `Test Content/Period Changes for Fourteen Novae (2023).pdf` (expected)

**Kimi's answer:**

The astronomy paper titled 'Period Changes...' studies fourteen (14) novae.

*Elapsed: 15.7s*

---

### easy-10 — easy

**Question:** In Lab 7, what class does CFG inherit from?

**Expected answer:** DiGraph<Statement>.

**Expected source files:**
- `Test Content/Lab 7 - Graphs.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Lab 4 - AST.pdf`
- `Test Content/MLK Letter.pdf`

**Files Kimi cited as sources:**
- `Test Content/Lab 7 - Graphs.pdf` (expected)

**Kimi's answer:**

CFG inherits from `DiGraph<Statement>` (the generic DiGraph class).

*Elapsed: 20.4s*

---

### easy-11 — easy

**Question:** What email address is on the Booking.com flight receipts?

**Expected answer:** mridul289agrawal@gmail.com

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Hotel YQuantum Receipt.pdf`
- `Test Content/Lab 0 - Utilities & Xunit Tests.pdf`

**Files Kimi cited as sources:**
- `Test Content/Flight Yale - GSP Receipt.pdf` (expected)
- `Test Content/Flight GSP - Hartford Receipt.pdf` (expected)

**Kimi's answer:**

The email address on the Booking.com flight receipts is **mridul289agrawal@gmail.com**.

*Elapsed: 18.1s*

---

### easy-12 — easy

**Question:** What is the minimum check-in age at the Graduate by Hilton New Haven?

**Expected answer:** 21.

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Distractor files (fed to Kimi but should NOT be cited):**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Artwork Analysis.docx`

**Files Kimi cited as sources:**
- `Test Content/Hotel YQuantum Receipt.pdf` (expected)

**Kimi's answer:**

The minimum check-in age at the Graduate by Hilton New Haven is 21.

*Elapsed: 12.5s*

---

