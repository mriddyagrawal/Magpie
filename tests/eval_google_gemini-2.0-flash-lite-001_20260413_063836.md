# Pipeline Eval Results (stages 3 + 4, end-to-end)

- Run: 2026-04-13 06:40:25 UTC
- Model: google/gemini-2.0-flash-lite-001 via Moonshot
- Top-k (Qdrant): 5
- Questions: 35

## Summary

| ID | Difficulty | Retrieval recall | Citation recall | Elapsed (s) |
|---|---|---|---|---|
| easy-01 | easy | 1/1 | 1/1 | 10.8 |
| easy-02 | easy | 1/1 | 1/1 | 2.9 |
| easy-03 | easy | 1/1 | 1/1 | 2.1 |
| easy-04 | easy | 1/1 | 1/1 | 5.9 |
| easy-05 | easy | 1/1 | 1/1 | 2.3 |
| easy-06 | easy | 1/1 | 1/1 | 2.3 |
| easy-07 | easy | 1/1 | 1/1 | 1.9 |
| easy-08 | easy | 1/1 | 1/1 | 3.5 |
| easy-09 | easy | 1/1 | 0/1 | 2.6 |
| easy-10 | easy | 1/1 | 1/1 | 2.1 |
| easy-11 | easy | 2/2 | 2/2 | 2.0 |
| easy-12 | easy | 1/1 | 0/1 | 2.4 |
| medium-01 | medium | 1/1 | 1/1 | 2.8 |
| medium-02 | medium | 1/1 | 1/1 | 2.8 |
| medium-03 | medium | 2/2 | 0/2 | 2.5 |
| medium-04 | medium | 1/1 | 1/1 | 3.2 |
| medium-05 | medium | 1/1 | 0/1 | 5.2 |
| medium-06 | medium | 1/1 | 1/1 | 2.6 |
| medium-07 | medium | 1/1 | 1/1 | 2.0 |
| medium-08 | medium | 1/1 | 1/1 | 1.7 |
| medium-09 | medium | 1/1 | 1/1 | 2.3 |
| medium-10 | medium | 1/1 | 1/1 | 2.6 |
| medium-11 | medium | 1/1 | 1/1 | 1.9 |
| medium-12 | medium | 1/1 | 1/1 | 2.6 |
| hard-01 | hard | 4/6 | 0/6 | 3.3 |
| hard-02 | hard | 2/4 | 1/4 | 2.6 |
| hard-03 | hard | 2/2 | 2/2 | 2.5 |
| hard-04 | hard | 1/1 | 1/1 | 6.8 |
| hard-05 | hard | 3/3 | 3/3 | 4.1 |
| hard-06 | hard | 1/1 | 1/1 | 2.8 |
| hard-07 | hard | 1/1 | 1/1 | 3.0 |
| hard-08 | hard | 1/1 | 1/1 | 3.1 |
| hard-09 | hard | 2/2 | 2/2 | 2.5 |
| hard-10 | hard | 3/5 | 3/5 | 2.9 |
| hard-11 | hard | 1/1 | 1/1 | 3.1 |

## Per-question

### easy-01 — easy

**Question:** Which airline operated the flight from Greenville-Spartanburg to Bradley (Hartford)?

**Expected answer:** Breeze Airways (airline code MX).

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Which airline operated the flight from Greenville-Spartanburg to Bradley (Hartford)?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Flight GSP - Hartford Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 3 | 0.5000 | `Test Content/Uber Furman - GSP (Reservation).png` |  |
| 4 | 0.2000 | `Test Content/Lab 6 - AST Visitors.pdf` |  |
| 5 | 0.2000 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |

**Kimi's answer:**

Breeze Airways operated the flight from Greenville-Spartanburg to Bradley.

**Sources Kimi cited:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

*Elapsed: 10.8s*

---

### easy-02 — easy

**Question:** What is the hotel booking number for the stay at Graduate by Hilton New Haven?

**Expected answer:** 12473171

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the hotel booking number for the stay at Graduate by Hilton New Haven?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Hotel YQuantum Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |
| 3 | 0.5000 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 4 | 0.4000 | `Test Content/Flight GSP - Hartford Receipt.pdf` |  |
| 5 | 0.1667 | `Test Content/Book VII - Plato's Republic.pdf` |  |

**Kimi's answer:**

The hotel booking number for the stay at Graduate by Hilton New Haven is 12473171.

**Sources Kimi cited:**
- `Test Content/Hotel YQuantum Receipt.pdf`

*Elapsed: 2.9s*

---

### easy-03 — easy

**Question:** On what date was the return flight from New Haven to Greenville-Spartanburg?

**Expected answer:** 5 April 2026

**Expected source files:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *On what date was the return flight from New Haven to Greenville-Spartanburg?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Flight Yale - GSP Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Flight GSP - Hartford Receipt.pdf` |  |
| 3 | 0.5000 | `Test Content/Uber Furman - GSP (Reservation).png` |  |
| 4 | 0.3250 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |
| 5 | 0.3095 | `Test Content/Hotel YQuantum Receipt.pdf` |  |

**Kimi's answer:**

The return flight from New Haven to Greenville-Spartanburg was on April 5, 2026.

**Sources Kimi cited:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

*Elapsed: 2.1s*

---

### easy-04 — easy

**Question:** Who wrote the Letter from Birmingham Jail?

**Expected answer:** Martin Luther King Jr.

**Expected source files:**
- `Test Content/MLK Letter.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Who wrote the Letter from Birmingham Jail?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/MLK Letter.pdf` | expected |
| 2 | 0.3333 | `Test Content/MTH_245_Handout_6.pdf` |  |
| 3 | 0.2500 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 4 | 0.2000 | `Test Content/Uber GSP - Furman (Reservation).png` |  |
| 5 | 0.1667 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |

**Kimi's answer:**

Martin Luther King Jr. wrote the Letter from Birmingham Jail.

**Sources Kimi cited:**
- `Test Content/MLK Letter.pdf`

*Elapsed: 5.9s*

---

### easy-05 — easy

**Question:** What is the only keyword in the DEC programming language used in Lab 3?

**Expected answer:** return

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the only keyword in the DEC programming language used in Lab 3?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Lab 3 - Tokenizer.pdf` | expected |
| 2 | 0.6667 | `Test Content/Lab 4 - AST.pdf` |  |
| 3 | 0.5833 | `Test Content/Lab 5 - Parser.pdf` |  |
| 4 | 0.4000 | `Test Content/Lab 6 - AST Visitors.pdf` |  |
| 5 | 0.3929 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |

**Kimi's answer:**

The only keyword in the DEC programming language used in Lab 3 is "return".

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`

*Elapsed: 2.3s*

---

### easy-06 — easy

**Question:** What is the total amount paid for the hotel stay in New Haven?

**Expected answer:** $159.00 USD (room $138.26 + taxes and fees $20.74).

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the total amount paid for the hotel stay in New Haven?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Hotel YQuantum Receipt.pdf` | expected |
| 2 | 0.5833 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 3 | 0.5333 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |
| 4 | 0.4167 | `Test Content/Flight GSP - Hartford Receipt.pdf` |  |
| 5 | 0.3667 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |

**Kimi's answer:**

The total amount paid for the hotel stay in New Haven was $159.00.

**Sources Kimi cited:**
- `Test Content/Hotel YQuantum Receipt.pdf`

*Elapsed: 2.3s*

---

### easy-07 — easy

**Question:** At what time does check-in start at Graduate by Hilton New Haven?

**Expected answer:** From 4:00 PM.

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *At what time does check-in start at Graduate by Hilton New Haven?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |
| 2 | 0.8333 | `Test Content/Hotel YQuantum Receipt.pdf` | expected |
| 3 | 0.5000 | `Test Content/DataFest Schedule.docx` |  |
| 4 | 0.3667 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 5 | 0.2000 | `Test Content/holi.md` |  |

**Kimi's answer:**

Check-in at Graduate by Hilton New Haven starts from 4:00 PM.

**Sources Kimi cited:**
- `Test Content/Hotel YQuantum Receipt.pdf`

*Elapsed: 1.9s*

---

### easy-08 — easy

**Question:** On what day of DataFest are the winners announced?

**Expected answer:** Sunday, April 6 (between 1:30 and 2:00 PM, in the Watkins Room of the Trone Center).

**Expected source files:**
- `Test Content/DataFest Schedule.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *On what day of DataFest are the winners announced?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/DataFest Schedule.docx` | expected |
| 2 | 0.5833 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |
| 3 | 0.5833 | `Test Content/Copy of Data Science and Machine Learning Club Budget.xlsx` |  |
| 4 | 0.2000 | `Test Content/holi.md` |  |
| 5 | 0.1667 | `Test Content/Screenshot 2026-04-10 at 10.11.53 AM.png` |  |

**Kimi's answer:**

The winners are announced on Sunday April 6th at 1:30 – 2.

**Sources Kimi cited:**
- `Test Content/DataFest Schedule.docx`

*Elapsed: 3.5s*

---

### easy-09 — easy

**Question:** How many novae are studied in the astronomy paper titled 'Period Changes...'?

**Expected answer:** Fourteen (14).

**Expected source files:**
- `Test Content/Period Changes for Fourteen Novae (2023).pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *How many novae are studied in the astronomy paper titled 'Period Changes...'?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Period Changes for Fourteen Novae (2023).pdf` | expected |
| 2 | 0.6667 | `Test Content/Giovannelli CV Review 2012MmSAI..83..446G.pdf` |  |
| 3 | 0.5000 | `Test Content/Evolutionary Status of CVs stz976.pdf` |  |
| 4 | 0.2000 | `Test Content/MTH_245_Handout_1.pdf` |  |
| 5 | 0.2000 | `Test Content/Book VII - Plato's Republic.pdf` |  |

**Kimi's answer:**

The paper titled 'Period Changes...' studies 14 novae.

**Sources Kimi cited:**
- (none)

*Elapsed: 2.6s*

---

### easy-10 — easy

**Question:** In Lab 7, what class does CFG inherit from?

**Expected answer:** DiGraph<Statement>.

**Expected source files:**
- `Test Content/Lab 7 - Graphs.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *In Lab 7, what class does CFG inherit from?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Lab 7 - Graphs.pdf` | expected |
| 2 | 0.6429 | `Test Content/Lab 4 - AST.pdf` |  |
| 3 | 0.5000 | `Test Content/Lab 3 - Tokenizer.pdf` |  |
| 4 | 0.3929 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 5 | 0.3611 | `Test Content/Lab 0 - Utilities & Xunit Tests.pdf` |  |

**Kimi's answer:**

CFG inherits from DiGraph<Statement>.

**Sources Kimi cited:**
- `Test Content/Lab 7 - Graphs.pdf`

*Elapsed: 2.1s*

---

### easy-11 — easy

**Question:** What email address is on the Booking.com flight receipts?

**Expected answer:** mridul289agrawal@gmail.com

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What email address is on the Booking.com flight receipts?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Flight Yale - GSP Receipt.pdf` | expected |
| 2 | 0.8333 | `Test Content/Flight GSP - Hartford Receipt.pdf` | expected |
| 3 | 0.5000 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 4 | 0.2540 | `Test Content/Uber GSP - Furman (Reservation).png` |  |
| 5 | 0.2000 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |

**Kimi's answer:**

The email address on the flight receipts is mridul289agrawal@gmail.com.

**Sources Kimi cited:**
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/Flight GSP - Hartford Receipt.pdf`

*Elapsed: 2.0s*

---

### easy-12 — easy

**Question:** What is the minimum check-in age at the Graduate by Hilton New Haven?

**Expected answer:** 21.

**Expected source files:**
- `Test Content/Hotel YQuantum Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the minimum check-in age at the Graduate by Hilton New Haven?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Hotel YQuantum Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |
| 3 | 0.4500 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 4 | 0.2679 | `Test Content/MTH_245_Handout_5.pdf` |  |
| 5 | 0.2500 | `Test Content/Evolutionary Status of CVs stz976.pdf` |  |

**Kimi's answer:**

The minimum check-in age for the Graduate by Hilton New Haven is not mentioned in the provided files.

**Sources Kimi cited:**
- (none)

*Elapsed: 2.4s*

---

### medium-01 — medium

**Question:** What token type does the DEC tokenizer assign to the symbol ':='?

**Expected answer:** ASSIGNMENT.

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What token type does the DEC tokenizer assign to the symbol ':='?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Lab 3 - Tokenizer.pdf` | expected |
| 2 | 0.5833 | `Test Content/Lab 5 - Parser.pdf` |  |
| 3 | 0.5000 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 4 | 0.4167 | `Test Content/Lab 4 - AST.pdf` |  |
| 5 | 0.4000 | `Test Content/Lab 6 - AST Visitors.pdf` |  |

**Kimi's answer:**

The DEC tokenizer assigns the ASSIGNMENT token type to the symbol ':='.

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`

*Elapsed: 2.8s*

---

### medium-02 — medium

**Question:** According to MTH-245 Handout 0, what minimum sample size does the Central Limit Theorem generally require for a test about a population mean?

**Expected answer:** n >= 30.

**Expected source files:**
- `Test Content/MTH_245_Handout_0.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *According to MTH-245 Handout 0, what minimum sample size does the Central Limit Theorem generally require for a test about a population mean?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/MTH_245_Handout_0.pdf` | expected |
| 2 | 0.6667 | `Test Content/MTH_245_Handout_1.pdf` |  |
| 3 | 0.4167 | `Test Content/MTH_245_Handout_3.pdf` |  |
| 4 | 0.4167 | `Test Content/MTH_245_Handout_4.pdf` |  |
| 5 | 0.4000 | `Test Content/MTH_245_Handout_6.pdf` |  |

**Kimi's answer:**

According to MTH-245 Handout 0, the Central Limit Theorem generally holds when n ≥ 30 for a test about a population mean.

**Sources Kimi cited:**
- `Test Content/MTH_245_Handout_0.pdf`

*Elapsed: 2.8s*

---

### medium-03 — medium

**Question:** Who is the travel companion on the Yale trip according to the flight receipts?

**Expected answer:** Rahul Ranjan Sah.

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Who is the travel companion on the Yale trip according to the flight receipts?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/Flight GSP - Hartford Receipt.pdf` | expected |
| 2 | 0.6429 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |
| 3 | 0.5833 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 4 | 0.5000 | `Test Content/Flight Yale - GSP Receipt.pdf` | expected |
| 5 | 0.4000 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |

**Kimi's answer:**

According to the flight receipt from New Haven to Greenville-Spartanburg, Mridul Agrawal's travel companion is Rahul Ranjan Sah.

**Sources Kimi cited:**
- (none)

*Elapsed: 2.5s*

---

### medium-04 — medium

**Question:** In the Artwork Analysis essay, what three flowchart shapes does the author use, and what does each represent?

**Expected answer:** Rectangles = processing / a learning step; parallelograms = output or an endpoint of the educational journey; diamonds = decision/assessment units.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *In the Artwork Analysis essay, what three flowchart shapes does the author use, and what does each represent?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Artwork Analysis.docx` | expected |
| 2 | 0.8333 | `Test Content/Artwork Analysis.pdf` |  |
| 3 | 0.5000 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 4 | 0.3000 | `Test Content/Lab 6 - AST Visitors.pdf` |  |
| 5 | 0.2778 | `Test Content/MTH_245_Handout_12.pdf` |  |

**Kimi's answer:**

The Artwork Analysis essay uses the following shapes in its flowcharts:

*   Rectangles: for processing or learning.
*   Parallelograms: for output or for the end of the educational journey.
*   Diamonds: for decision units or assessments that define the ability of the people and the path they will take.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Artwork Analysis.pdf`
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 3.2s*

---

### medium-05 — medium

**Question:** In the Letter from Birmingham Jail, what four basic steps does King say every nonviolent campaign undertakes?

**Expected answer:** (1) Collection of facts to determine whether injustices exist, (2) negotiation, (3) self-purification, (4) direct action.

**Expected source files:**
- `Test Content/MLK Letter.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *In the Letter from Birmingham Jail, what four basic steps does King say every nonviolent campaign undertakes?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/MLK Letter.pdf` | expected |
| 2 | 0.4762 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 3 | 0.3667 | `Test Content/MTH_245_Handout_3.pdf` |  |
| 4 | 0.3333 | `Test Content/Machiavelli Papier.docx` |  |
| 5 | 0.2778 | `Test Content/MTH_245_Handout_0.pdf` |  |

**Kimi's answer:**

King states that every nonviolent campaign includes these four basic steps: collection of the facts to determine whether injustices exist; negotiation; self-purification; and direct action.

**Sources Kimi cited:**
- (none)

*Elapsed: 5.2s*

---

### medium-06 — medium

**Question:** In the Plato's Allegory of the Cave essay, what six subjects are listed as the leader's curriculum, in order?

**Expected answer:** Arithmetic, plane geometry, 3D geometry, astronomy, harmonics (the numerical / mathematical study of music), and dialectic.

**Expected source files:**
- `Test Content/Plato's Allegory of the Cave.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *In the Plato's Allegory of the Cave essay, what six subjects are listed as the leader's curriculum, in order?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Plato's Allegory of the Cave.docx` | expected |
| 2 | 0.6667 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 3 | 0.5000 | `Test Content/Artwork Analysis.pdf` |  |
| 4 | 0.4000 | `Test Content/Artwork Analysis.docx` |  |
| 5 | 0.1667 | `Test Content/Machiavelli Papier.docx` |  |

**Kimi's answer:**

The curriculum for leaders in Plato's Allegory of the Cave includes: Arithmetic, Plane geometry, 3D geometry, Astronomy, Harmonics, and Dialectic.

**Sources Kimi cited:**
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 2.6s*

---

### medium-07 — medium

**Question:** Which buildings are used during DataFest Saturday's work time?

**Expected answer:** Furman Hall, Johns Hall, and Duke Library (on Saturday, April 5).

**Expected source files:**
- `Test Content/DataFest Schedule.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Which buildings are used during DataFest Saturday's work time?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/DataFest Schedule.docx` | expected |
| 2 | 0.5833 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |
| 3 | 0.3750 | `Test Content/Copy of Data Science and Machine Learning Club Budget.xlsx` |  |
| 4 | 0.3333 | `Test Content/Lab 5 - Parser.pdf` |  |
| 5 | 0.2250 | `Test Content/Lab 1 - Doubly-Linked Lists.pdf` |  |

**Kimi's answer:**

During the DataFest Saturday work time, Furman Hall, Johns Hall, and Duke Library are used. 

**Sources Kimi cited:**
- `Test Content/DataFest Schedule.docx`

*Elapsed: 2.0s*

---

### medium-08 — medium

**Question:** According to the Machiavelli essay, what two kinds of principalities are highlighted?

**Expected answer:** Monarchies and Republics.

**Expected source files:**
- `Test Content/Machiavelli Papier.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *According to the Machiavelli essay, what two kinds of principalities are highlighted?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Machiavelli Papier.docx` | expected |
| 2 | 0.6667 | `Test Content/Artwork Analysis.docx` |  |
| 3 | 0.5000 | `Test Content/Artwork Analysis.pdf` |  |
| 4 | 0.2000 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 5 | 0.2000 | `Test Content/MTH_245_Handout_4.pdf` |  |

**Kimi's answer:**

The Machiavelli essay highlights the following two kinds of principalities: Monarchies and Republics.

**Sources Kimi cited:**
- `Test Content/Machiavelli Papier.docx`

*Elapsed: 1.7s*

---

### medium-09 — medium

**Question:** What is the pickup and drop-off of the Uber reserved for April 3 at 10:53 PM, and how much was it?

**Expected answer:** Pickup at Curbside - Outside Curb (Hartford airport), drop-off at Graduate by Hilton New Haven; $69.93.

**Expected source files:**
- `Test Content/Uber Hartford - Yale (Reservation).png`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the pickup and drop-off of the Uber reserved for April 3 at 10:53 PM, and how much was it?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Uber Hartford - Yale (Reservation).png` | expected |
| 2 | 0.6667 | `Test Content/Uber GSP - Furman (Reservation).png` |  |
| 3 | 0.5000 | `Test Content/Uber Furman - GSP (Reservation).png` |  |
| 4 | 0.3000 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |
| 5 | 0.3000 | `Test Content/Hotel YQuantum Receipt.pdf` |  |

**Kimi's answer:**

The Uber reserved for April 3 at 10:53 PM had a pickup at Curbside - Outside Curb and a drop-off at Graduate by Hilton New Haven, costing $69.93.

**Sources Kimi cited:**
- `Test Content/Uber Hartford - Yale (Reservation).png`

*Elapsed: 2.3s*

---

### medium-10 — medium

**Question:** What is the customer reference number on the Breeze Airways flight receipt?

**Expected answer:** 40-920412413.

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the customer reference number on the Breeze Airways flight receipt?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Flight GSP - Hartford Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Flight Yale - GSP Receipt.pdf` |  |
| 3 | 0.4167 | `Test Content/Uber GSP - Furman (Reservation).png` |  |
| 4 | 0.4000 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 5 | 0.2500 | `Test Content/Uber Furman - GSP (Reservation).png` |  |

**Kimi's answer:**

The customer reference number on the Breeze Airways flight receipt is 40-920412413.

**Sources Kimi cited:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`

*Elapsed: 2.6s*

---

### medium-11 — medium

**Question:** According to the Artwork Analysis essay, what do students who fail at understanding harmonies in their abstract form go on to become, and what about those who fail astronomy?

**Expected answer:** Those who fail harmonies become 'Harmon-ists' who make, tune, and study instruments. Those who fail astronomy (the pure-logic/math understanding of stellar motions) become Astronomers who build telescopes and study stars.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *According to the Artwork Analysis essay, what do students who fail at understanding harmonies in their abstract form go on to become, and what about those who fail astronomy?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/Artwork Analysis.docx` | expected |
| 2 | 0.5000 | `Test Content/Lab 5 - Parser.pdf` |  |
| 3 | 0.4762 | `Test Content/Artwork Analysis.pdf` |  |
| 4 | 0.4242 | `Test Content/Lab 4 - AST.pdf` |  |
| 5 | 0.3750 | `Test Content/Plato's Allegory of the Cave.docx` |  |

**Kimi's answer:**

Those who fail at understanding harmonies in their true, abstract form become “Harmon-ists” who make, tune and study instruments. Those who fail at understand and inferring the motions of stars using pure logic and math become Astronomers who make telescopes and study stars.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Artwork Analysis.pdf`
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 1.9s*

---

### medium-12 — medium

**Question:** What airline operated the return flight from New Haven to Greenville-Spartanburg, and what is its airline reference?

**Expected answer:** Avelo Airlines (code XP), reference 87K77A.

**Expected source files:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What airline operated the return flight from New Haven to Greenville-Spartanburg, and what is its airline reference?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Flight Yale - GSP Receipt.pdf` | expected |
| 2 | 0.6667 | `Test Content/Flight GSP - Hartford Receipt.pdf` |  |
| 3 | 0.5000 | `Test Content/Uber Furman - GSP (Reservation).png` |  |
| 4 | 0.3095 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 5 | 0.2917 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |

**Kimi's answer:**

The return flight from New Haven to Greenville-Spartanburg was operated by Avelo Airlines. The airline reference is 87K77A.

**Sources Kimi cited:**
- `Test Content/Flight Yale - GSP Receipt.pdf`

*Elapsed: 2.6s*

---

### hard-01 — hard

**Question:** What was the total out-of-pocket cost of the Yale trip, including both flights, the hotel, and all three Uber rides?

**Expected answer:** $643.44. Breakdown: Flight GSP->Hartford $170.45 + Flight New Haven->GSP $170.18 + Hotel $159.00 + Uber Furman->GSP $36.94 + Uber Hartford->Yale $69.93 + Uber GSP->Furman $36.94.

**Expected source files:**
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/Hotel YQuantum Receipt.pdf`
- `Test Content/Uber Furman - GSP (Reservation).png`
- `Test Content/Uber Hartford - Yale (Reservation).png`
- `Test Content/Uber GSP - Furman (Reservation).png`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What was the total out-of-pocket cost of the Yale trip, including both flights, the hotel, and all three Uber rides?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Uber Hartford - Yale (Reservation).png` | expected |
| 2 | 0.6667 | `Test Content/Uber GSP - Furman (Reservation).png` | expected |
| 3 | 0.5000 | `Test Content/Uber Furman - GSP (Reservation).png` | expected |
| 4 | 0.3429 | `Test Content/Hotel YQuantum Receipt.pdf` | expected |
| 5 | 0.3250 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |

**Kimi's answer:**

I am sorry, but the provided documents do not contain the cost of flights, and the costs of three Uber rides are not specific to the Yale trip. Also, the hotel information does not state the total out-of-pocket cost. Therefore, I am unable to calculate "the total out-of-pocket cost of the Yale trip, including both flights, the hotel, and all three Uber rides."

**Sources Kimi cited:**
- (none)

*Elapsed: 3.3s*

---

### hard-02 — hard

**Question:** Does the Yale trip conflict with the DataFest schedule at Furman? If so, which sessions were missed?

**Expected answer:** Yes, there is a conflict. DataFest runs April 4-6 at Furman, but the trip was April 3 (fly out in the evening) through April 5 (return Uber arriving at Furman around 8:10 PM). That means Friday April 4's check-in / pizza / data reveal (4:30-6 PM) and all of Saturday April 5's 9 AM-5 PM work time at Furman would have been missed; only Sunday April 6 (presentations, judging, winners) would be attendable.

**Expected source files:**
- `Test Content/DataFest Schedule.docx`
- `Test Content/Flight GSP - Hartford Receipt.pdf`
- `Test Content/Flight Yale - GSP Receipt.pdf`
- `Test Content/Uber GSP - Furman (Reservation).png`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Does the Yale trip conflict with the DataFest schedule at Furman? If so, which sessions were missed?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Uber GSP - Furman (Reservation).png` | expected |
| 2 | 0.7500 | `Test Content/DataFest Schedule.docx` | expected |
| 3 | 0.5333 | `Test Content/Uber Furman - GSP (Reservation).png` |  |
| 4 | 0.4167 | `Test Content/DataFest 2026 Budget and Plans.xlsx` |  |
| 5 | 0.3429 | `Test Content/Uber Hartford - Yale (Reservation).png` |  |

**Kimi's answer:**

Yes, there is a conflict. The schedule for DataFest at Furman is April 4-6. A ride is scheduled for Friday April 3 at 6:49 PM (EDT) from Furman University to Greenville-Spartanburg International Airport (GSP) and another ride is scheduled for Friday April 3 at 10:53 PM (EDT) from Hartford to Yale. Based on the schedule provided, the user would miss Check-in, Pizza, and Data Reveal. Also, the user would not be able to attend the breakfast and lunch events on Saturday April 5th.

**Sources Kimi cited:**
- `Test Content/Uber Furman - GSP (Reservation).png`
- `Test Content/DataFest Schedule.docx`
- `Test Content/Uber Hartford - Yale (Reservation).png`

*Elapsed: 2.6s*

---

### hard-03 — hard

**Question:** Lab 7 says DiGraph's adjacency list should use a data structure 'implemented many moons ago'. Which lab introduced that data structure, and what is it?

**Expected answer:** Lab 1 (Doubly-Linked Lists) introduced the DLL class, which Lab 7 reuses as the value type in DiGraph's Dictionary<T, DLL<T>> adjacency list.

**Expected source files:**
- `Test Content/Lab 7 - Graphs.pdf`
- `Test Content/Lab 1 - Doubly-Linked Lists.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Lab 7 says DiGraph's adjacency list should use a data structure 'implemented many moons ago'. Which lab introduced that data structure, and what is it?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Lab 7 - Graphs.pdf` | expected |
| 2 | 0.6667 | `Test Content/Lab 1 - Doubly-Linked Lists.pdf` | expected |
| 3 | 0.4500 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 4 | 0.2679 | `Test Content/Lab 6 - AST Visitors.pdf` |  |
| 5 | 0.2576 | `Test Content/Lab 3 - Tokenizer.pdf` |  |

**Kimi's answer:**

Lab 1 introduced the DLL (DoublyLinkedList) class.  The data structure used in the DiGraph's adjacency list is a DLL.

**Sources Kimi cited:**
- `Test Content/Lab 7 - Graphs.pdf`
- `Test Content/Lab 1 - Doubly-Linked Lists.pdf`

*Elapsed: 2.5s*

---

### hard-04 — hard

**Question:** The Letter from Birmingham Jail appears as a chapter in a larger book. What is the book's title, who edited it, and what is the title and author of the chapter that follows the MLK letter?

**Expected answer:** Book: 'What So Proudly We Hail: The American Soul in Story, Speech, and Song', edited by Amy A. Kass, Leon R. Kass, and Diana Schaub (ISI Books, Wilmington, Delaware). The chapter immediately following MLK's letter is 'A Jury of Her Peers' by Susan Glaspell.

**Expected source files:**
- `Test Content/MLK Letter.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *The Letter from Birmingham Jail appears as a chapter in a larger book. What is the book's title, who edited it, and what is the title and author of the chapter that follows the MLK letter?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/MLK Letter.pdf` | expected |
| 2 | 0.5000 | `Test Content/Hotel YQuantum Receipt.pdf` |  |
| 3 | 0.3333 | `Test Content/MTH_245_Handout_6.pdf` |  |
| 4 | 0.3250 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 5 | 0.2500 | `Test Content/MTH_245_Handout_11.pdf` |  |

**Kimi's answer:**

The book is titled "WHAT SO PROUDLY WE HAIL The American Soul in Story, Speech, and Song". It was edited by Amy A. Kass, Leon R. Kass, and Diana Schaub. The chapter following Martin Luther King, Jr.'s "Letter from Birmingham Jail" is titled "Toward a More Robust Citizenry". The author of this chapter is not specified.

**Sources Kimi cited:**
- `Test Content/MLK Letter.pdf`

*Elapsed: 6.8s*

---

### hard-05 — hard

**Question:** Compare Plato's and Machiavelli's views on the role of ethics in ruling, based on the two essays.

**Expected answer:** Plato's ruler is grounded in ethics as a product of abstract philosophical training - only the 'gold souls' who have grasped eternal truths through arithmetic, geometry, astronomy, harmonics, and dialectic are fit to rule; justice and the good flow from contemplation. Machiavelli divorces political theory from ethics: the prince pursues 'virtu' (results-oriented excellence, with no moral connotation) rather than 'virtue' (which carries a positive moral connotation). A Machiavellian ruler must be willing to be cruel, feared, or deceptive when results demand it, because people are 'uncertain, treacherous, greedy.' Plato's ideal is moral purity achieved through education; Machiavelli's is effectiveness achieved through pragmatism.

**Expected source files:**
- `Test Content/Plato's Allegory of the Cave.docx`
- `Test Content/Machiavelli Papier.docx`
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Compare Plato's and Machiavelli's views on the role of ethics in ruling, based on the two essays.*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Machiavelli Papier.docx` | expected |
| 2 | 0.5333 | `Test Content/Artwork Analysis.pdf` |  |
| 3 | 0.4444 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 4 | 0.4167 | `Test Content/Artwork Analysis.docx` | expected |
| 5 | 0.3667 | `Test Content/Plato's Allegory of the Cave.docx` | expected |

**Kimi's answer:**

Machiavelli divorces political theory from ethics and focuses on results and virtu rather than virtue, emphasizing what a prince must do to maintain the state and themselves, even if it is considered morally "bad." In contrast, Plato's ideal Philosopher King must study pure logic to see the divine in its entirety, showing a focus on being good and just, and understanding the eternal truths to bring order, harmony, and justice to the world.

**Sources Kimi cited:**
- `Test Content/Machiavelli Papier.docx`
- `Test Content/Artwork Analysis.docx`
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 4.1s*

---

### hard-06 — hard

**Question:** Which C# Char methods does the Lab 3 assignment explicitly recommend for tokenization, and why?

**Expected answer:** Char.IsWhiteSpace, Char.IsDigit, and Char.IsLetter - they simplify the character-by-character classification loop inside Tokenize, since each helper method needs to decide whether a character is whitespace, a digit (for numeric literals), or a letter (for variables/keywords).

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Which C# Char methods does the Lab 3 assignment explicitly recommend for tokenization, and why?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Lab 3 - Tokenizer.pdf` | expected |
| 2 | 0.6667 | `Test Content/Lab 5 - Parser.pdf` |  |
| 3 | 0.5000 | `Test Content/Lab 0 - Utilities & Xunit Tests.pdf` |  |
| 4 | 0.4000 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 5 | 0.3095 | `Test Content/Lab 6 - AST Visitors.pdf` |  |

**Kimi's answer:**

The Lab 3 assignment explicitly recommends the following `Char` struct methods for tokenization: `IsWhiteSpace`, `IsDigit`, and `IsLetter`. The reason given is to ease the burden with tokenization.

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`

*Elapsed: 2.8s*

---

### hard-07 — hard

**Question:** According to the Machiavelli essay, what is the distinction between 'virtu' and 'virtue', and what concrete historical example is cited involving Cesare Borgia?

**Expected answer:** 'Virtu' is results-oriented ability / effective excellence and carries no moral connotation; 'virtue' is the classical moral-philosophy term with an inherently positive connotation. The essay cites the City of Cesena and Ramiro de Lorca under Borgia as an example of cold but effective Machiavellian rulership.

**Expected source files:**
- `Test Content/Machiavelli Papier.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *According to the Machiavelli essay, what is the distinction between 'virtu' and 'virtue', and what concrete historical example is cited involving Cesare Borgia?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Machiavelli Papier.docx` | expected |
| 2 | 0.3333 | `Test Content/Artwork Analysis.docx` |  |
| 3 | 0.3333 | `Test Content/MTH_245_Handout_9.pdf` |  |
| 4 | 0.2576 | `Test Content/MTH_245_Handout_3.pdf` |  |
| 5 | 0.2500 | `Test Content/Book VII - Plato's Republic.pdf` |  |

**Kimi's answer:**

According to Machiavelli, 'virtu' differs from 'virtue' in that 'virtu' does not have a positive or 'good' connotation; it is strictly about results. A concrete historical example provided is when Machiavelli discusses the actions of Cesare Borgia, and his actions in the City of Cesena and Ramiro de Lorca. 

**Sources Kimi cited:**
- `Test Content/Machiavelli Papier.docx`

*Elapsed: 3.0s*

---

### hard-08 — hard

**Question:** What pop-culture reference does the Plato's Allegory of the Cave essay use to illustrate people being 'too used to the prisoner's way' to accept freedom?

**Expected answer:** The Indian film Rang de Basanti, specifically the character Cherry offering to free the others.

**Expected source files:**
- `Test Content/Plato's Allegory of the Cave.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What pop-culture reference does the Plato's Allegory of the Cave essay use to illustrate people being 'too used to the prisoner's way' to accept freedom?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 2 | 0.7000 | `Test Content/Plato's Allegory of the Cave.docx` | expected |
| 3 | 0.5833 | `Test Content/Artwork Analysis.pdf` |  |
| 4 | 0.4500 | `Test Content/Artwork Analysis.docx` |  |
| 5 | 0.2679 | `Test Content/MTH_245_Handout_6.pdf` |  |

**Kimi's answer:**

The essay "Plato's Allegory of the Cave" mentions the film "Rang de Basanti" to illustrate how people can become "too used to the prisoner's way," and accustomed to honors.

**Sources Kimi cited:**
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 3.1s*

---

### hard-09 — hard

**Question:** Both the CS Labs and the Artwork Analysis essay reference 'flowcharts' but in completely different contexts. What is each one's context?

**Expected answer:** Lab 3 (Tokenizer) and Lab 7 (CFG) are about control-flow and data-flow graphs in compilers - directed graphs whose nodes are program statements. The Artwork Analysis essay uses flowchart shapes (rectangles/parallelograms/diamonds) as a visual metaphor to depict Plato's multi-stage educational journey for the Philosopher Ruler. Same visual vocabulary, one for software, the other for political philosophy.

**Expected source files:**
- `Test Content/Lab 7 - Graphs.pdf`
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Both the CS Labs and the Artwork Analysis essay reference 'flowcharts' but in completely different contexts. What is each one's context?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Artwork Analysis.pdf` |  |
| 2 | 0.6667 | `Test Content/Artwork Analysis.docx` | expected |
| 3 | 0.4500 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 4 | 0.3333 | `Test Content/Lab 0 - Utilities & Xunit Tests.pdf` |  |
| 5 | 0.2500 | `Test Content/Lab 7 - Graphs.pdf` | expected |

**Kimi's answer:**

Artwork Analysis uses flowcharts to explain algorithms and logic by using standard and contemporary flowchart elements.  CS Labs uses control flow graphs (CFGs) to analyze a program's execution paths.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.pdf`
- `Test Content/Artwork Analysis.docx`
- `Test Content/Lab 7 - Graphs.pdf`

*Elapsed: 2.5s*

---

### hard-10 — hard

**Question:** Across the CSC-223 lab series, what is the progression of compiler phases implemented, from Lab 3 onward?

**Expected answer:** Lab 3: Tokenizer (lexical analysis - raw text into tokens). Lab 4: AST (abstract syntax tree construction). Lab 5: Parser (builds the AST from tokens). Lab 6: AST Visitors (traversal / evaluation / unparsing patterns). Lab 7: Control Flow Graph generation (an optimization/analysis representation built via an AST visitor). This mirrors the classical compiler pipeline: lex -> parse -> AST -> AST analysis -> CFG-based optimization.

**Expected source files:**
- `Test Content/Lab 3 - Tokenizer.pdf`
- `Test Content/Lab 4 - AST.pdf`
- `Test Content/Lab 5 - Parser.pdf`
- `Test Content/Lab 6 - AST Visitors.pdf`
- `Test Content/Lab 7 - Graphs.pdf`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *Across the CSC-223 lab series, what is the progression of compiler phases implemented, from Lab 3 onward?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/Lab 4 - AST.pdf` | expected |
| 2 | 0.6250 | `Test Content/Lab 2 - Symbol Tables.pdf` |  |
| 3 | 0.5333 | `Test Content/Lab 7 - Graphs.pdf` | expected |
| 4 | 0.5000 | `Test Content/Lab 0 - Utilities & Xunit Tests.pdf` |  |
| 5 | 0.3333 | `Test Content/Lab 3 - Tokenizer.pdf` | expected |

**Kimi's answer:**

From Lab 3 (Tokenizer) onward, the progression of compiler phases implemented across the CSC-223 lab series is as follows: Tokenizer (Lab 3), and Abstract Syntax Tree (AST) with Builders (Lab 4), and Control Flow Graph (CFG) (Lab 7).

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`
- `Test Content/Lab 4 - AST.pdf`
- `Test Content/Lab 7 - Graphs.pdf`

*Elapsed: 2.9s*

---

### hard-11 — hard

**Question:** What is the physical requirement at MIT that the Artwork Analysis essay uses to draw a parallel between Plato's ideal education and modern U.S. liberal arts colleges?

**Expected answer:** MIT's swimming requirement. The essay argues that U.S. liberal-arts schools echo Plato's education model, with the physical component generally less intense than Plato's ideal - except for schools like MIT that still maintain a physical requirement, of which swimming is the cited example.

**Expected source files:**
- `Test Content/Artwork Analysis.docx`

**Kimi-rewritten search query** (what actually hit Qdrant):

- `query`: *What is the physical requirement at MIT that the Artwork Analysis essay uses to draw a parallel between Plato's ideal education and modern U.S. liberal arts colleges?*
- `keywords`: (none)

**Retrieved from Qdrant (top-5):**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/Artwork Analysis.docx` | expected |
| 2 | 0.6667 | `Test Content/Artwork Analysis.pdf` |  |
| 3 | 0.5000 | `Test Content/Plato's Allegory of the Cave.docx` |  |
| 4 | 0.4000 | `Test Content/Book VII - Plato's Republic.pdf` |  |
| 5 | 0.1667 | `Test Content/MTH_245_Handout_12.pdf` |  |

**Kimi's answer:**

MIT's swimming requirement is the physical requirement at MIT that the Artwork Analysis essay uses to draw a parallel between Plato's ideal education and modern U.S. liberal arts colleges.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Artwork Analysis.pdf`

*Elapsed: 3.1s*

---

