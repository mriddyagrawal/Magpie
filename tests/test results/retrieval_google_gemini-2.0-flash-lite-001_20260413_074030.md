# Retrieval eval (stages 3 + 4)

- Run: 2026-04-13 07:40:30 UTC
- Model: `google/gemini-2.0-flash-lite-001` (via openrouter)
- Top-k: 5
- Query rewrite: off
- Questions: 20

## Headline

- Retrieval recall @ top-5: **10/20** (50%)
- Retrieval recall @ top-1:     **7/20** (35%)

## Summary

| # | Expected | Hit rank | Elapsed | Question |
|---|---|---|---|---|
| 1 | 30 | #1 | 18.7s | What was the total on my Breadfast order from 25 May 2022 th |
| 2 | 30 | **MISS** | 7.1s | On the Breadfast order delivered to New Cairo on 25 May 2022 |
| 3 | 31 | #1 | 7.5s | How much did I pay at Emarat Misr for L&M Light Box and Marl |
| 4 | 31 | **MISS** | 7.0s | What was the transaction number for my Emarat Misr cigarette |
| 5 | 32 | **MISS** | 8.9s | On the Breadfast receipt with Rich Basturma, Islandoy Cheese |
| 6 | 33 | #1 | 4.7s | What was the final total at Men's Club Collection / Carrefou |
| 7 | 33 | #1 | 4.4s | Which cashier rang up the Men's Club Carrefour receipt on 3/ |
| 8 | 34 | #2 | 5.3s | What was the grand total for my Decathlon Egypt purchase at  |
| 9 | 34 | **MISS** | 5.5s | On the Decathlon Almaza Mall receipt from September 2021, ho |
| 10 | 35 | **MISS** | 9.5s | What was the total on the Breadfast order delivered to Al Re |
| 11 | 36 | #1 | 8.9s | On the Breadfast order #108-14006842 delivered to New Cairo  |
| 12 | 36 | #1 | 3.6s | How much was the Cafe Con Leche on the Breadfast receipt del |
| 13 | 37 | #4 | 5.9s | What was the total at Gourmet Food Stores City Stars Naser C |
| 14 | 37 | #2 | 6.2s | Which cashier handled my Gourmet Food Stores Cairo receipt o |
| 15 | 38 | **MISS** | 6.0s | On the Breadfast order #121-5145529 for aya ali in Mohandise |
| 16 | 38 | **MISS** | 4.3s | What was the final total for the Breadfast delivery to Mohan |
| 17 | 39 | **MISS** | 12.6s | What did I pay at LC WAIKIKI TEMA Retail 6th of October on 0 |
| 18 | 39 | **MISS** | 11.8s | What was the change given back on the LC WAIKIKI 6th of Octo |
| 19 | 40 | **MISS** | 9.9s | On the Breadfast order #8319-5828179 delivered to Ranal in H |
| 20 | 40 | #1 | 7.4s | How much was the Wonderville Vanilla Cup Ice Cream on my Hel |

## Per-question

### 1. Expected receipt 30

**Q:** What was the total on my Breadfast order from 25 May 2022 that had fresh cheese, cold cuts, candies and yogurt?

**Ground truth:** EGP 107.90

**Search query sent to embedders:**

- `query`: *What was the total on my Breadfast order from 25 May 2022 that had fresh cheese, cold cuts, candies and yogurt?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/30.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/499.jpg` |  |
| 3 | 0.4583 | `Test Content/155.jpg` |  |
| 4 | 0.3333 | `Test Content/227.jpg` |  |
| 5 | 0.2500 | `Test Content/32.jpg` |  |

**Predicted answer:**

The total for the Breadfast order on May 25, 2022, including fresh cheese, cold cuts, candies, and yogurt was EGP 107.90.

**sources_used:** `['Test Content/30.jpg']`

*Elapsed: 18.7s*

---

### 2. Expected receipt 30

**Q:** On the Breadfast order delivered to New Cairo on 25 May 2022, what was the delivery fee?

**Ground truth:** EGP 10.00

**Search query sent to embedders:**

- `query`: *On the Breadfast order delivered to New Cairo on 25 May 2022, what was the delivery fee?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/36.jpg` |  |
| 2 | 0.5000 | `Test Content/366.jpg` |  |
| 3 | 0.3333 | `Test Content/482.jpg` |  |
| 4 | 0.3333 | `Test Content/161.jpg` |  |
| 5 | 0.2500 | `Test Content/487.jpg` |  |

**Predicted answer:**

The delivery fee for the Breadfast order delivered to New Cairo on 25 February 2022 was EGP 10.00 via Delivery.

**sources_used:** `['Test Content/487.jpg']`

*Elapsed: 7.1s*

---

### 3. Expected receipt 31

**Q:** How much did I pay at Emarat Misr for L&M Light Box and Marlboro Gold on 5 April 2023?

**Ground truth:** LE 186.00

**Search query sent to embedders:**

- `query`: *How much did I pay at Emarat Misr for L&M Light Box and Marlboro Gold on 5 April 2023?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/31.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/122.jpg` |  |
| 3 | 0.5000 | `Test Content/373.jpg` |  |
| 4 | 0.4500 | `Test Content/304.jpg` |  |
| 5 | 0.2909 | `Test Content/500.jpg` |  |

**Predicted answer:**

On 05/04/23 at Emarat Misr, you paid 78.00 for L&M LIGHT BOX and 108.00 for MARLBORO GOLD. Thus, the total paid for these items was 186.00.

**sources_used:** `['Test Content/31.jpg']`

*Elapsed: 7.5s*

---

### 4. Expected receipt 31

**Q:** What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?

**Ground truth:** 177444

**Search query sent to embedders:**

- `query`: *What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6429 | `Test Content/498.jpg` |  |
| 2 | 0.5333 | `Test Content/127.jpg` |  |
| 3 | 0.5000 | `Test Content/225.jpg` |  |
| 4 | 0.4583 | `Test Content/364.jpg` |  |
| 5 | 0.3500 | `Test Content/373.jpg` |  |

**Predicted answer:**

The transaction number for the Emarat Misr cigarette purchase on 05/01/23 was 200440.

**sources_used:** `['Test Content/373.jpg']`

*Elapsed: 7.0s*

---

### 5. Expected receipt 32

**Q:** On the Breadfast receipt with Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon, what was the subtotal?

**Ground truth:** EGP 235.34 (subtotal before delivery/discount; total EGP 270.25)

**Search query sent to embedders:**

- `query`: *On the Breadfast receipt with Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon, what was the subtotal?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/187.jpg` |  |
| 2 | 0.5000 | `Test Content/161.jpg` |  |
| 3 | 0.3333 | `Test Content/478.jpg` |  |
| 4 | 0.3333 | `Test Content/148.jpg` |  |
| 5 | 0.2500 | `Test Content/477.jpg` |  |

**Predicted answer:**

I am sorry, but the provided files do not include a receipt with Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon, so it is impossible to determine the subtotal.

**sources_used:** `[]`

*Elapsed: 8.9s*

---

### 6. Expected receipt 33

**Q:** What was the final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount?

**Ground truth:** 249.00

**Search query sent to embedders:**

- `query`: *What was the final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5833 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/425.jpg` |  |
| 3 | 0.5000 | `Test Content/437.jpg` |  |
| 4 | 0.3667 | `Test Content/250.jpg` |  |
| 5 | 0.3333 | `Test Content/272.jpg` |  |

**Predicted answer:**

The final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount was 249.00. 

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 4.7s*

---

### 7. Expected receipt 33

**Q:** Which cashier rang up the Men's Club Carrefour receipt on 3/24/2022?

**Ground truth:** 180ahmed

**Search query sent to embedders:**

- `query`: *Which cashier rang up the Men's Club Carrefour receipt on 3/24/2022?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/497.jpg` |  |
| 3 | 0.4500 | `Test Content/325.jpg` |  |
| 4 | 0.4444 | `Test Content/437.jpg` |  |
| 5 | 0.3250 | `Test Content/425.jpg` |  |

**Predicted answer:**

The cashier who rang up the Men's Club Carrefour receipt on 3/24/2022 was 189Ahmed.

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 4.4s*

---

### 8. Expected receipt 34

**Q:** What was the grand total for my Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21 that included a foldable fitness bag and backpack?

**Ground truth:** EE 795.00

**Search query sent to embedders:**

- `query`: *What was the grand total for my Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21 that included a foldable fitness bag and backpack?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/149.jpg` |  |
| 2 | 0.7500 | `Test Content/34.jpg` | EXPECTED |
| 3 | 0.4762 | `Test Content/505.jpg` |  |
| 4 | 0.4000 | `Test Content/454.jpg` |  |
| 5 | 0.3095 | `Test Content/20.jpg` |  |

**Predicted answer:**

The grand total for your Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21, which included a foldable fitness bag and backpack, was E£ 795.00.

**sources_used:** `['Test Content/34.jpg']`

*Elapsed: 5.3s*

---

### 9. Expected receipt 34

**Q:** On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?

**Ground truth:** 5 items

**Search query sent to embedders:**

- `query`: *On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6667 | `Test Content/454.jpg` |  |
| 2 | 0.6250 | `Test Content/336.jpg` |  |
| 3 | 0.5333 | `Test Content/20.jpg` |  |
| 4 | 0.3929 | `Test Content/505.jpg` |  |
| 5 | 0.3333 | `Test Content/149.jpg` |  |

**Predicted answer:**

I am sorry, but none of the provided receipts are from the Decathlon Almaza Mall and none of them represent a receipt from September 2021. Therefore I cannot answer your question.

**sources_used:** `[]`

*Elapsed: 5.5s*

---

### 10. Expected receipt 35

**Q:** What was the total on the Breadfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha?

**Ground truth:** EGP 165.30

**Search query sent to embedders:**

- `query`: *What was the total on the Breadfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/308.jpg` |  |
| 2 | 0.5000 | `Test Content/499.jpg` |  |
| 3 | 0.3333 | `Test Content/203.jpg` |  |
| 4 | 0.2500 | `Test Content/492.jpg` |  |
| 5 | 0.2500 | `Test Content/168.jpg` |  |

**Predicted answer:**

I am sorry, but the provided files do not contain the total for a Breadfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha.

**sources_used:** `[]`

*Elapsed: 9.5s*

---

### 11. Expected receipt 36

**Q:** On the Breadfast order #108-14006842 delivered to New Cairo with Flat White, Latte and Cafe Con Leche, what was the final total?

**Ground truth:** EGP 317.50

**Search query sent to embedders:**

- `query`: *On the Breadfast order #108-14006842 delivered to New Cairo with Flat White, Latte and Cafe Con Leche, what was the final total?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/36.jpg` | EXPECTED |
| 2 | 0.5333 | `Test Content/161.jpg` |  |
| 3 | 0.3333 | `Test Content/115.jpg` |  |
| 4 | 0.2500 | `Test Content/513.jpg` |  |
| 5 | 0.2500 | `Test Content/45.jpg` |  |

**Predicted answer:**

The final total for order #108-14006842 was EGP 317.50.

**sources_used:** `['Test Content/36.jpg']`

*Elapsed: 8.9s*

---

### 12. Expected receipt 36

**Q:** How much was the Cafe Con Leche on the Breadfast receipt delivered 10 December 2023?

**Ground truth:** EGP 75.00

**Search query sent to embedders:**

- `query`: *How much was the Cafe Con Leche on the Breadfast receipt delivered 10 December 2023?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/36.jpg` | EXPECTED |
| 2 | 0.5333 | `Test Content/499.jpg` |  |
| 3 | 0.5000 | `Test Content/168.jpg` |  |
| 4 | 0.2500 | `Test Content/108.jpg` |  |
| 5 | 0.2500 | `Test Content/494.jpg` |  |

**Predicted answer:**

The Cafe Con Leche on the receipt delivered on December 10, 2023, cost EGP 75.00.

**sources_used:** `['Test Content/36.jpg']`

*Elapsed: 3.6s*

---

### 13. Expected receipt 37

**Q:** What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?

**Ground truth:** LE 437.21

**Search query sent to embedders:**

- `query`: *What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 4

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/27.jpg` |  |
| 2 | 0.4583 | `Test Content/119.jpg` |  |
| 3 | 0.3409 | `Test Content/382.jpg` |  |
| 4 | 0.3333 | `Test Content/37.jpg` | EXPECTED |
| 5 | 0.3000 | `Test Content/302.jpg` |  |

**Predicted answer:**

The total for transaction 1089939 at Gourmet Food Stores City Stars Naser City was LE437.21.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 5.9s*

---

### 14. Expected receipt 37

**Q:** Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?

**Ground truth:** m.kara

**Search query sent to embedders:**

- `query`: *Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6667 | `Test Content/405.jpg` |  |
| 2 | 0.6250 | `Test Content/37.jpg` | EXPECTED |
| 3 | 0.6111 | `Test Content/119.jpg` |  |
| 4 | 0.5000 | `Test Content/329.jpg` |  |
| 5 | 0.2576 | `Test Content/443.jpg` |  |

**Predicted answer:**

The cashier for the Gourmet Food Stores Cairo receipt on 11/2/2021 was m.kara.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 6.2s*

---

### 15. Expected receipt 38

**Q:** On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?

**Ground truth:** EGP 1.34

**Search query sent to embedders:**

- `query`: *On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5000 | `Test Content/375.jpg` |  |
| 2 | 0.5000 | `Test Content/203.jpg` |  |
| 3 | 0.3333 | `Test Content/482.jpg` |  |
| 4 | 0.3333 | `Test Content/485.jpg` |  |
| 5 | 0.2500 | `Test Content/291.jpg` |  |

**Predicted answer:**

I am sorry, but none of the provided files contain the information about the previous due amount carried over for order #121-5145529 for Aya Ali in Mohandiseen.

**sources_used:** `[]`

*Elapsed: 6.0s*

---

### 16. Expected receipt 38

**Q:** What was the final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken Fresh Chicken Fillet?

**Ground truth:** EGP 243.34

**Search query sent to embedders:**

- `query`: *What was the final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken Fresh Chicken Fillet?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/440.jpg` |  |
| 2 | 0.7000 | `Test Content/484.jpg` |  |
| 3 | 0.3611 | `Test Content/477.jpg` |  |
| 4 | 0.3333 | `Test Content/145.jpg` |  |
| 5 | 0.2500 | `Test Content/179.jpg` |  |

**Predicted answer:**

I am sorry, but the provided files do not contain information about an order delivered to Mohandiseen on August 12, 2022, that included Temry Chicken Fresh Chicken Fillet.

**sources_used:** `[]`

*Elapsed: 4.3s*

---

### 17. Expected receipt 39

**Q:** What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?

**Ground truth:** LE 200.00 cash (item LE 169.00 after discount)

**Search query sent to embedders:**

- `query`: *What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/112.jpg` |  |
| 2 | 0.5000 | `Test Content/46.jpg` |  |
| 3 | 0.3429 | `Test Content/468.jpg` |  |
| 4 | 0.3333 | `Test Content/223.jpg` |  |
| 5 | 0.2500 | `Test Content/374.jpg` |  |

**Predicted answer:**

I am sorry, but the provided documents do not contain the information required to answer your question. I can not find any receipt for a men's blue long-sleeved shirt purchased on 05-Jan-21 at LC WAIKIKI TEMA Retail 6th of October.

**sources_used:** `[]`

*Elapsed: 12.6s*

---

### 18. Expected receipt 39

**Q:** What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?

**Ground truth:** LE 31.00

**Search query sent to embedders:**

- `query`: *What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6000 | `Test Content/312.jpg` |  |
| 2 | 0.5000 | `Test Content/324.jpg` |  |
| 3 | 0.3333 | `Test Content/320.jpg` |  |
| 4 | 0.3333 | `Test Content/218.jpg` |  |
| 5 | 0.2500 | `Test Content/480.jpg` |  |

**Predicted answer:**

I am sorry, but the provided files do not contain the answer to the question. The question asks about a receipt from January 2021, and the files contain receipts from different dates.

**sources_used:** `[]`

*Elapsed: 11.8s*

---

### 19. Expected receipt 40

**Q:** On the Breadfast order #8319-5828179 delivered to Ranal in Heliopolis on 3 October 2022, what was the total?

**Ground truth:** EGP 76.99

**Search query sent to embedders:**

- `query`: *On the Breadfast order #8319-5828179 delivered to Ranal in Heliopolis on 3 October 2022, what was the total?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6667 | `Test Content/186.jpg` |  |
| 2 | 0.6429 | `Test Content/203.jpg` |  |
| 3 | 0.5000 | `Test Content/181.jpg` |  |
| 4 | 0.2500 | `Test Content/435.jpg` |  |
| 5 | 0.2500 | `Test Content/499.jpg` |  |

**Predicted answer:**

I am sorry, but I cannot answer the question. None of the provided files contain the requested information about order #8319-5828179 delivered to Ranal in Heliopolis on 3 October 2022.

**sources_used:** `[]`

*Elapsed: 9.9s*

---

### 20. Expected receipt 40

**Q:** How much was the Wonderville Vanilla Cup Ice Cream on my Heliopolis Breadfast receipt from 3 October 2022?

**Ground truth:** EGP 13.50 each, 2 qty, total EGP 27.00

**Search query sent to embedders:**

- `query`: *How much was the Wonderville Vanilla Cup Ice Cream on my Heliopolis Breadfast receipt from 3 October 2022?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-5 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/40.jpg` | EXPECTED |
| 2 | 0.5833 | `Test Content/192.jpg` |  |
| 3 | 0.3611 | `Test Content/176.jpg` |  |
| 4 | 0.3333 | `Test Content/499.jpg` |  |
| 5 | 0.3333 | `Test Content/121.jpg` |  |

**Predicted answer:**

The Wonderville Vanilla Cup Ice Cream cost EGP 13.50 on the receipt from 3 October 2022. 

**sources_used:** `['Test Content/40.jpg']`

*Elapsed: 7.4s*

---
