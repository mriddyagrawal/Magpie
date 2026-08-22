# Pipeline Eval Results (stages 3 + 4, end-to-end)

- Run: 2026-04-13 06:47:09 UTC
- Model: google/gemini-2.0-flash-lite-001 via Moonshot
- Top-k (Qdrant): 5
- Questions: 11

## Summary

| ID | Difficulty | Retrieval recall | Citation recall | Elapsed (s) |
|---|---|---|---|---|
| hard-01 | hard | 4/6 | 2/6 | 10.1 |
| hard-02 | hard | 2/4 | 1/4 | 2.7 |
| hard-03 | hard | 2/2 | 1/2 | 2.3 |
| hard-04 | hard | 1/1 | 0/1 | 6.7 |
| hard-05 | hard | 3/3 | 3/3 | 4.4 |
| hard-06 | hard | 1/1 | 1/1 | 2.8 |
| hard-07 | hard | 1/1 | 1/1 | 3.2 |
| hard-08 | hard | 1/1 | 1/1 | 2.7 |
| hard-09 | hard | 2/2 | 2/2 | 2.3 |
| hard-10 | hard | 3/5 | 3/5 | 2.5 |
| hard-11 | hard | 1/1 | 1/1 | 4.0 |

## Per-question

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

I am sorry, but the provided documents do not contain the total out-of-pocket cost for the Yale trip, including the flight costs. They only contain information on Uber and hotel costs. The hotel cost was $159 and an Uber ride was $69.93. Therefore, the total cost cannot be determined.

**Sources Kimi cited:**
- `Test Content/Uber Hartford - Yale (Reservation).png`
- `Test Content/Hotel YQuantum Receipt.pdf`

*Elapsed: 10.1s*

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

The Uber reservation to Yale is scheduled for Friday, April 3 at 10:53 PM (EDT). The DataFest schedule includes sessions on Friday, April 4. Thus the Yale trip does conflict with the DataFest schedule. The DataFest schedule includes Check In, Pizza, and Data Reveal on Friday April 4th. The Yale trip pickup is on a prior date, therefore no sessions will be missed.

**Sources Kimi cited:**
- `Test Content/Uber Hartford - Yale (Reservation).png`
- `Test Content/DataFest Schedule.docx`

*Elapsed: 2.7s*

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

Lab 1 introduced the DLL (DoublyLinkedList) data structure. The data structure is a doubly linked list.

**Sources Kimi cited:**
- `Test Content/Lab 2 - Symbol Tables.pdf`
- `Test Content/Lab 1 - Doubly-Linked Lists.pdf`

*Elapsed: 2.3s*

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
| 5 | 0.2500 | `Test Content/Machiavelli Papier.docx` |  |

**Kimi's answer:**

The book's title is "WHAT SO PROUDLY WE HAIL The American Soul in Story, Speech, and Song", edited by Amy A. Kass, Leon R. Kass, and Diana Schaub. The chapter following Martin Luther King, Jr.'s "Letter from Birmingham Jail" is titled "TOWARD A MORE ROBUST CITIZENRY" and does not list an author. 



**Sources Kimi cited:**
- (none)

*Elapsed: 6.7s*

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

Machiavelli divorces political theory from ethics and focuses on results, virtu, and what is necessary for a ruler to maintain the state. He believes a prince must do what is necessary, even if it is considered bad, to maintain power, and thus, does not care about the 'good' of the kingdom, or focuses on the 'effectual truth'. Plato, in contrast, emphasizes the importance of ethics and justice in ruling, with the Philosopher King being the embodiment of virtue. The education system outlined in the text aims to cultivate individuals who can grasp the concept of the Good and act accordingly. Plato believes that the achievements of those who have not seen the truth (those who are not philosophers) are insignificant. Therefore, Plato prioritizes ethical considerations above all, while Machiavelli prioritizes pragmatism and maintaining power, even if it means acting unethically.

**Sources Kimi cited:**
- `Test Content/Machiavelli Papier.docx`
- `Test Content/Artwork Analysis.docx`
- `Test Content/Book VII - Plato's Republic.pdf`
- `Test Content/Artwork Analysis.pdf`
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 4.4s*

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

The Lab 3 assignment explicitly recommends the following `Char` struct methods for tokenization: `IsWhiteSpace`, `IsDigit`, and `IsLetter`. The assignment states that these are to "ease your burden with tokenization".

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

According to the essay, Machiavelli's "virtu" differs from "virtue" in that  "virtu" does not have a “good” connotation, and is strictly about results. The essay mentions the City of Cesena and Ramiro de Lorca under Borgia as a concrete historical example.

**Sources Kimi cited:**
- `Test Content/Machiavelli Papier.docx`

*Elapsed: 3.2s*

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

The essay "Plato's Allegory of the Cave" mentions the film "Rang de Basanti" as a pop-culture reference to illustrate people being 'too used to the prisoner's way' to accept freedom.

**Sources Kimi cited:**
- `Test Content/Plato's Allegory of the Cave.docx`

*Elapsed: 2.7s*

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

Artwork Analysis uses flowcharts to explain algorithms and logic in the context of Plato's educational system, with shapes representing steps or decisions in the educational journey. In the context of Control Flow Graph Generation, flowcharts (CFGs) are used to represent the possible execution paths of a program.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.pdf`
- `Test Content/Artwork Analysis.docx`
- `Test Content/Lab 7 - Graphs.pdf`

*Elapsed: 2.3s*

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

From Lab 3 (Tokenizer) onward, the progression of compiler phases implemented across the CSC-223 lab series is as follows:  Lab 3 implements a Tokenizer; Lab 4 implements an Abstract Syntax Tree (AST) and Builders; Lab 7 implements Control Flow Graph (CFG) generation.

**Sources Kimi cited:**
- `Test Content/Lab 3 - Tokenizer.pdf`
- `Test Content/Lab 4 - AST.pdf`
- `Test Content/Lab 7 - Graphs.pdf`

*Elapsed: 2.5s*

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

MIT's swimming requirement is the physical component of their college that is more intensive, which the Artwork Analysis essay notes as a parallel to Plato's ideal education system.

**Sources Kimi cited:**
- `Test Content/Artwork Analysis.docx`
- `Test Content/Artwork Analysis.pdf`

*Elapsed: 4.0s*

---

