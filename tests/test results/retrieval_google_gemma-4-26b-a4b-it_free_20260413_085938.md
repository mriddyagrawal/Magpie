# Retrieval eval (stages 3 + 4)

- Run: 2026-04-13 08:59:38 UTC
- Model: `google/gemma-4-26b-a4b-it:free` (via openrouter)
- Top-k: 10
- Query rewrite: off
- Questions: 20

## Headline

- Retrieval recall @ top-10: **20/20** (100%)
- Retrieval recall @ top-1:     **16/20** (80%)

## Summary

| # | Expected | Hit rank | Elapsed | Question |
|---|---|---|---|---|
| 1 | 30 | #1 | 16.7s | What was the total on my Breadfast order from 25 May 2022 th |
| 2 | 30 | #1 | 10.3s | On the Breadfast order delivered to New Cairo on 25 May 2022 |
| 3 | 31 | #1 | 12.4s | How much did I pay at Emarat Misr for L&M Light Box and Marl |
| 4 | 31 | #3 | 9.7s | What was the transaction number for my Emarat Misr cigarette |
| 5 | 32 | #1 | 11.5s | On the Breadfast receipt with Rich Basturma, Islandoy Cheese |
| 6 | 33 | #1 | 9.4s | What was the final total at Men's Club Collection / Carrefou |
| 7 | 33 | #1 | 8.7s | Which cashier rang up the Men's Club Carrefour receipt on 3/ |
| 8 | 34 | #1 | 11.5s | What was the grand total for my Decathlon Egypt purchase at  |
| 9 | 34 | #2 | 8.1s | On the Decathlon Almaza Mall receipt from September 2021, ho |
| 10 | 35 | #1 | 8.9s | What was the total on the Breadfast order delivered to Al Re |
| 11 | 36 | #1 | 8.9s | On the Breadfast order #108-14006842 delivered to New Cairo  |
| 12 | 36 | #1 | 6.9s | How much was the Cafe Con Leche on the Breadfast receipt del |
| 13 | 37 | #1 | 13.6s | What was the total at Gourmet Food Stores City Stars Naser C |
| 14 | 37 | #2 | 10.7s | Which cashier handled my Gourmet Food Stores Cairo receipt o |
| 15 | 38 | #1 | 7.7s | On the Breadfast order #121-5145529 for aya ali in Mohandise |
| 16 | 38 | #2 | 8.2s | What was the final total for the Breadfast delivery to Mohan |
| 17 | 39 | #1 | 14.8s | What did I pay at LC WAIKIKI TEMA Retail 6th of October on 0 |
| 18 | 39 | #1 | 9.8s | What was the change given back on the LC WAIKIKI 6th of Octo |
| 19 | 40 | #1 | 14.3s | On the Breadfast order #8319-5828179 delivered to Ranal in H |
| 20 | 40 | #1 | 10.7s | How much was the Wonderville Vanilla Cup Ice Cream on my Hel |

## Per-question

### 1. Expected receipt 30

**Q:** What was the total on my Breadfast order from 25 May 2022 that had fresh cheese, cold cuts, candies and yogurt?

**Ground truth:** EGP 107.90

**Search query sent to embedders:**

- `query`: *What was the total on my Breadfast order from 25 May 2022 that had fresh cheese, cold cuts, candies and yogurt?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/30.jpg` | EXPECTED |
| 2 | 0.4103 | `Test Content/227.jpg` |  |
| 3 | 0.3333 | `Test Content/265.jpg` |  |
| 4 | 0.2500 | `Test Content/147.jpg` |  |
| 5 | 0.2500 | `Test Content/206.jpg` |  |
| 6 | 0.2333 | `Test Content/155.jpg` |  |
| 7 | 0.2000 | `Test Content/514.jpg` |  |
| 8 | 0.2000 | `Test Content/186.jpg` |  |
| 9 | 0.1667 | `Test Content/435.jpg` |  |
| 10 | 0.1484 | `Test Content/212.jpg` |  |

**Predicted answer:**

The total for the Breadfast order from 25 May 2022, which included fresh cheese (Roumi - Batarekh), cold cuts (Rich Beef Luncheon Plain), candies (Halls Candies Fresh Mint), and yogurt (Almarai Natural Yogurt Lite), was EGP 107.90.

**sources_used:** `['Test Content/30.jpg']`

*Elapsed: 16.7s*

---

### 2. Expected receipt 30

**Q:** On the Breadfast order delivered to New Cairo on 25 May 2022, what was the delivery fee?

**Ground truth:** EGP 10.00

**Search query sent to embedders:**

- `query`: *On the Breadfast order delivered to New Cairo on 25 May 2022, what was the delivery fee?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.6667 | `Test Content/30.jpg` | EXPECTED |
| 2 | 0.5909 | `Test Content/44.jpg` |  |
| 3 | 0.5000 | `Test Content/513.jpg` |  |
| 4 | 0.4333 | `Test Content/503.jpg` |  |
| 5 | 0.3333 | `Test Content/269.jpg` |  |
| 6 | 0.3000 | `Test Content/487.jpg` |  |
| 7 | 0.2917 | `Test Content/323.jpg` |  |
| 8 | 0.2054 | `Test Content/161.jpg` |  |
| 9 | 0.2000 | `Test Content/291.jpg` |  |
| 10 | 0.1429 | `Test Content/431.jpg` |  |

**Predicted answer:**

On the Breadfast order delivered to New Cairo on 25 May 2022, the delivery fee was EGP 10.00.

**sources_used:** `['Test Content/30.jpg']`

*Elapsed: 10.3s*

---

### 3. Expected receipt 31

**Q:** How much did I pay at Emarat Misr for L&M Light Box and Marlboro Gold on 5 April 2023?

**Ground truth:** LE 186.00

**Search query sent to embedders:**

- `query`: *How much did I pay at Emarat Misr for L&M Light Box and Marlboro Gold on 5 April 2023?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/31.jpg` | EXPECTED |
| 2 | 0.6667 | `Test Content/373.jpg` |  |
| 3 | 0.3333 | `Test Content/515.jpg` |  |
| 4 | 0.3214 | `Test Content/127.jpg` |  |
| 5 | 0.3000 | `Test Content/500.jpg` |  |
| 6 | 0.2625 | `Test Content/498.jpg` |  |
| 7 | 0.2540 | `Test Content/462.jpg` |  |
| 8 | 0.2500 | `Test Content/304.jpg` |  |
| 9 | 0.2500 | `Test Content/122.jpg` |  |
| 10 | 0.2429 | `Test Content/376.jpg` |  |

**Predicted answer:**

On 5 April 2023, you paid 78.00 LE for L&M Light Box (2 pcs @ 39.00) and 108.00 LE for Marlboro Gold (2 pcs @ 54.00) at Emarat Misr.

**sources_used:** `['Test Content/31.jpg']`

*Elapsed: 12.4s*

---

### 4. Expected receipt 31

**Q:** What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?

**Ground truth:** 177444

**Search query sent to embedders:**

- `query`: *What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 3

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/364.jpg` |  |
| 2 | 0.4583 | `Test Content/288.jpg` |  |
| 3 | 0.3929 | `Test Content/31.jpg` | EXPECTED |
| 4 | 0.3333 | `Test Content/376.jpg` |  |
| 5 | 0.3000 | `Test Content/260.jpg` |  |
| 6 | 0.2833 | `Test Content/462.jpg` |  |
| 7 | 0.2500 | `Test Content/202.jpg` |  |
| 8 | 0.2436 | `Test Content/225.jpg` |  |
| 9 | 0.2381 | `Test Content/498.jpg` |  |
| 10 | 0.1838 | `Test Content/127.jpg` |  |

**Predicted answer:**

The transaction number for the Emarat Misr cigarette purchase on 05/04/23 is 177444.

**sources_used:** `['Test Content/31.jpg']`

*Elapsed: 9.7s*

---

### 5. Expected receipt 32

**Q:** On the Breadfast receipt with Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon, what was the subtotal?

**Ground truth:** EGP 235.34 (subtotal before delivery/discount; total EGP 270.25)

**Search query sent to embedders:**

- `query`: *On the Breadfast receipt with Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon, what was the subtotal?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/32.jpg` | EXPECTED |
| 2 | 0.6000 | `Test Content/511.jpg` |  |
| 3 | 0.4242 | `Test Content/227.jpg` |  |
| 4 | 0.3429 | `Test Content/203.jpg` |  |
| 5 | 0.2500 | `Test Content/155.jpg` |  |
| 6 | 0.2500 | `Test Content/235.jpg` |  |
| 7 | 0.2167 | `Test Content/469.jpg` |  |
| 8 | 0.2054 | `Test Content/152.jpg` |  |
| 9 | 0.2000 | `Test Content/230.jpg` |  |
| 10 | 0.1880 | `Test Content/161.jpg` |  |

**Predicted answer:**

The subtotal on the Breadfast receipt containing Rich Basturma (250g), Istanboly Cheese (350g), 12 Brown Eggs, and Chipsy Flaming Hot Lemon (36g) is EGP 210.25.

**sources_used:** `['Test Content/32.jpg']`

*Elapsed: 11.5s*

---

### 6. Expected receipt 33

**Q:** What was the final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount?

**Ground truth:** 249.00

**Search query sent to embedders:**

- `query`: *What was the final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.4583 | `Test Content/325.jpg` |  |
| 3 | 0.4103 | `Test Content/425.jpg` |  |
| 4 | 0.3611 | `Test Content/463.jpg` |  |
| 5 | 0.3250 | `Test Content/92.jpg` |  |
| 6 | 0.3214 | `Test Content/327.jpg` |  |
| 7 | 0.2778 | `Test Content/449.jpg` |  |
| 8 | 0.2769 | `Test Content/437.jpg` |  |
| 9 | 0.2667 | `Test Content/497.jpg` |  |
| 10 | 0.2338 | `Test Content/250.jpg` |  |

**Predicted answer:**

The final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301.00 EGP discount was 249.00.

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 9.4s*

---

### 7. Expected receipt 33

**Q:** Which cashier rang up the Men's Club Carrefour receipt on 3/24/2022?

**Ground truth:** 180ahmed

**Search query sent to embedders:**

- `query`: *Which cashier rang up the Men's Club Carrefour receipt on 3/24/2022?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.5714 | `Test Content/449.jpg` |  |
| 3 | 0.4500 | `Test Content/463.jpg` |  |
| 4 | 0.4167 | `Test Content/92.jpg` |  |
| 5 | 0.4167 | `Test Content/250.jpg` |  |
| 6 | 0.3250 | `Test Content/327.jpg` |  |
| 7 | 0.2917 | `Test Content/437.jpg` |  |
| 8 | 0.2778 | `Test Content/272.jpg` |  |
| 9 | 0.2429 | `Test Content/399.jpg` |  |
| 10 | 0.2429 | `Test Content/497.jpg` |  |

**Predicted answer:**

The cashier who rang up the Men's Club Carrefour receipt on 3/24/2022 was 189ahmed.

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 8.7s*

---

### 8. Expected receipt 34

**Q:** What was the grand total for my Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21 that included a foldable fitness bag and backpack?

**Ground truth:** EE 795.00

**Search query sent to embedders:**

- `query`: *What was the grand total for my Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21 that included a foldable fitness bag and backpack?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/34.jpg` | EXPECTED |
| 2 | 0.6667 | `Test Content/149.jpg` |  |
| 3 | 0.4167 | `Test Content/421.jpg` |  |
| 4 | 0.3667 | `Test Content/454.jpg` |  |
| 5 | 0.3611 | `Test Content/505.jpg` |  |
| 6 | 0.3429 | `Test Content/153.jpg` |  |
| 7 | 0.2679 | `Test Content/20.jpg` |  |
| 8 | 0.2361 | `Test Content/428.jpg` |  |
| 9 | 0.1678 | `Test Content/49.jpg` |  |
| 10 | 0.1556 | `Test Content/336.jpg` |  |

**Predicted answer:**

The grand total for the Decathlon Egypt purchase at City Centre Almaza Mall on 07/09/21, which included a foldable fitness bag and a backpack, was E£ 795.00.

**sources_used:** `['Test Content/34.jpg']`

*Elapsed: 11.5s*

---

### 9. Expected receipt 34

**Q:** On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?

**Ground truth:** 5 items

**Search query sent to embedders:**

- `query`: *On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/336.jpg` |  |
| 2 | 0.5833 | `Test Content/34.jpg` | EXPECTED |
| 3 | 0.5833 | `Test Content/153.jpg` |  |
| 4 | 0.4242 | `Test Content/422.jpg` |  |
| 5 | 0.3667 | `Test Content/149.jpg` |  |
| 6 | 0.3056 | `Test Content/421.jpg` |  |
| 7 | 0.2679 | `Test Content/428.jpg` |  |
| 8 | 0.2436 | `Test Content/504.jpg` |  |
| 9 | 0.2198 | `Test Content/454.jpg` |  |
| 10 | 0.2111 | `Test Content/505.jpg` |  |

**Predicted answer:**

The Decathlon Almaza Mall receipt dated 07/09/21 (September 2021) shows that 5 items were sold.

**sources_used:** `['Test Content/34.jpg']`

*Elapsed: 8.1s*

---

### 10. Expected receipt 35

**Q:** What was the total on the Breadfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha?

**Ground truth:** EGP 165.30

**Search query sent to embedders:**

- `query`: *What was the total on the Breadfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5000 | `Test Content/35.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/163.jpg` |  |
| 3 | 0.4242 | `Test Content/274.jpg` |  |
| 4 | 0.3409 | `Test Content/308.jpg` |  |
| 5 | 0.3333 | `Test Content/276.jpg` |  |
| 6 | 0.2500 | `Test Content/499.jpg` |  |
| 7 | 0.2000 | `Test Content/172.jpg` |  |
| 8 | 0.2000 | `Test Content/334.jpg` |  |
| 9 | 0.1714 | `Test Content/11.jpg` |  |
| 10 | 0.1667 | `Test Content/390.jpg` |  |

**Predicted answer:**

The total on the Breadfast order for ahmed samaha delivered to Al Rehab City on 31 January 2022 was EGP 185.35.

**sources_used:** `['Test Content/35.jpg']`

*Elapsed: 8.9s*

---

### 11. Expected receipt 36

**Q:** On the Breadfast order #108-14006842 delivered to New Cairo with Flat White, Latte and Cafe Con Leche, what was the final total?

**Ground truth:** EGP 317.50

**Search query sent to embedders:**

- `query`: *On the Breadfast order #108-14006842 delivered to New Cairo with Flat White, Latte and Cafe Con Leche, what was the final total?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/36.jpg` | EXPECTED |
| 2 | 0.4103 | `Test Content/513.jpg` |  |
| 3 | 0.3667 | `Test Content/503.jpg` |  |
| 4 | 0.3333 | `Test Content/265.jpg` |  |
| 5 | 0.3026 | `Test Content/30.jpg` |  |
| 6 | 0.2556 | `Test Content/44.jpg` |  |
| 7 | 0.2500 | `Test Content/158.jpg` |  |
| 8 | 0.1909 | `Test Content/161.jpg` |  |
| 9 | 0.1880 | `Test Content/235.jpg` |  |
| 10 | 0.1726 | `Test Content/323.jpg` |  |

**Predicted answer:**

The final total for Breadfast order #108-14006842 was EGP 317.50.

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

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/36.jpg` | EXPECTED |
| 2 | 0.4048 | `Test Content/53.jpg` |  |
| 3 | 0.3333 | `Test Content/229.jpg` |  |
| 4 | 0.3000 | `Test Content/235.jpg` |  |
| 5 | 0.2833 | `Test Content/108.jpg` |  |
| 6 | 0.2500 | `Test Content/148.jpg` |  |
| 7 | 0.2095 | `Test Content/50.jpg` |  |
| 8 | 0.2000 | `Test Content/419.jpg` |  |
| 9 | 0.1714 | `Test Content/456.jpg` |  |
| 10 | 0.1667 | `Test Content/201.jpg` |  |

**Predicted answer:**

The Cafe Con Leche - Full Cream Milk on the Breadfast receipt delivered 10 December 2023 cost 75.00.

**sources_used:** `['Test Content/36.jpg']`

*Elapsed: 6.9s*

---

### 13. Expected receipt 37

**Q:** What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?

**Ground truth:** LE 437.21

**Search query sent to embedders:**

- `query`: *What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/37.jpg` | EXPECTED |
| 2 | 0.5833 | `Test Content/403.jpg` |  |
| 3 | 0.5833 | `Test Content/119.jpg` |  |
| 4 | 0.4000 | `Test Content/27.jpg` |  |
| 5 | 0.3095 | `Test Content/264.jpg` |  |
| 6 | 0.2576 | `Test Content/354.jpg` |  |
| 7 | 0.2338 | `Test Content/332.jpg` |  |
| 8 | 0.2250 | `Test Content/316.jpg` |  |
| 9 | 0.1476 | `Test Content/302.jpg` |  |
| 10 | 0.1325 | `Test Content/347.jpg` |  |

**Predicted answer:**

The total amount for transaction 1089939 at Gourmet Food Stores City Stars Naser City was LE437.21.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 13.6s*

---

### 14. Expected receipt 37

**Q:** Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?

**Ground truth:** m.kara

**Search query sent to embedders:**

- `query`: *Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/264.jpg` |  |
| 2 | 0.5588 | `Test Content/37.jpg` | EXPECTED |
| 3 | 0.4048 | `Test Content/354.jpg` |  |
| 4 | 0.3929 | `Test Content/329.jpg` |  |
| 5 | 0.3333 | `Test Content/316.jpg` |  |
| 6 | 0.3000 | `Test Content/119.jpg` |  |
| 7 | 0.2500 | `Test Content/405.jpg` |  |
| 8 | 0.1909 | `Test Content/285.jpg` |  |
| 9 | 0.1776 | `Test Content/397.jpg` |  |
| 10 | 0.1742 | `Test Content/326.jpg` |  |

**Predicted answer:**

The cashier who handled the Gourmet Food Stores receipt in Cairo on 11/2/2021 was m.kara.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 10.7s*

---

### 15. Expected receipt 38

**Q:** On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?

**Ground truth:** EGP 1.34

**Search query sent to embedders:**

- `query`: *On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/38.jpg` | EXPECTED |
| 2 | 0.6667 | `Test Content/440.jpg` |  |
| 3 | 0.5333 | `Test Content/408.jpg` |  |
| 4 | 0.3333 | `Test Content/338.jpg` |  |
| 5 | 0.2500 | `Test Content/258.jpg` |  |
| 6 | 0.2500 | `Test Content/201.jpg` |  |
| 7 | 0.2381 | `Test Content/306.jpg` |  |
| 8 | 0.1726 | `Test Content/161.jpg` |  |
| 9 | 0.1534 | `Test Content/415.jpg` |  |
| 10 | 0.1429 | `Test Content/291.jpg` |  |

**Predicted answer:**

On the Breadfast order #121-5145529 for aya ali in Mohandiseen, the previous due amount carried over was 1.34.

**sources_used:** `['Test Content/38.jpg']`

*Elapsed: 7.7s*

---

### 16. Expected receipt 38

**Q:** What was the final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken Fresh Chicken Fillet?

**Ground truth:** EGP 243.34

**Search query sent to embedders:**

- `query`: *What was the final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken Fresh Chicken Fillet?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/484.jpg` |  |
| 2 | 0.6667 | `Test Content/38.jpg` | EXPECTED |
| 3 | 0.5833 | `Test Content/440.jpg` |  |
| 4 | 0.4500 | `Test Content/477.jpg` |  |
| 5 | 0.2857 | `Test Content/228.jpg` |  |
| 6 | 0.2500 | `Test Content/179.jpg` |  |
| 7 | 0.2020 | `Test Content/321.jpg` |  |
| 8 | 0.2000 | `Test Content/147.jpg` |  |
| 9 | 0.1667 | `Test Content/369.jpg` |  |
| 10 | 0.1389 | `Test Content/457.jpg` |  |

**Predicted answer:**

The final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken - Fresh Chicken Fillet (1Kg) was EGP 243.34.

**sources_used:** `['Test Content/38.jpg']`

*Elapsed: 8.2s*

---

### 17. Expected receipt 39

**Q:** What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?

**Ground truth:** LE 200.00 cash (item LE 169.00 after discount)

**Search query sent to embedders:**

- `query`: *What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/39.jpg` | EXPECTED |
| 2 | 0.4048 | `Test Content/112.jpg` |  |
| 3 | 0.3429 | `Test Content/374.jpg` |  |
| 4 | 0.3333 | `Test Content/99.jpg` |  |
| 5 | 0.3333 | `Test Content/5.jpg` |  |
| 6 | 0.3167 | `Test Content/46.jpg` |  |
| 7 | 0.2500 | `Test Content/317.jpg` |  |
| 8 | 0.2083 | `Test Content/420.jpg` |  |
| 9 | 0.2000 | `Test Content/123.jpg` |  |
| 10 | 0.1769 | `Test Content/200.jpg` |  |

**Predicted answer:**

On 05-Jan-21, at the LC WAIKIKI TEMA RETAIL 6th of October, you paid LE 169.00 for a WOVEN BLOUSE - SHIRT LONG-SLEEVED (item number 8681385255258).

**sources_used:** `['Test Content/39.jpg']`

*Elapsed: 14.8s*

---

### 18. Expected receipt 39

**Q:** What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?

**Ground truth:** LE 31.00

**Search query sent to embedders:**

- `query`: *What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/39.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/46.jpg` |  |
| 3 | 0.3750 | `Test Content/237.jpg` |  |
| 4 | 0.3429 | `Test Content/123.jpg` |  |
| 5 | 0.3333 | `Test Content/317.jpg` |  |
| 6 | 0.3250 | `Test Content/507.jpg` |  |
| 7 | 0.3000 | `Test Content/509.jpg` |  |
| 8 | 0.2333 | `Test Content/480.jpg` |  |
| 9 | 0.2193 | `Test Content/292.jpg` |  |
| 10 | 0.1497 | `Test Content/383.jpg` |  |

**Predicted answer:**

The change back on the LC WAIKIKI 6th of October receipt from January 2021 (dated 05-Jun-21) was LE 31.00.

**sources_used:** `['Test Content/39.jpg']`

*Elapsed: 9.8s*

---

### 19. Expected receipt 40

**Q:** On the Breadfast order #8319-5828179 delivered to Ranal in Heliopolis on 3 October 2022, what was the total?

**Ground truth:** EGP 76.99

**Search query sent to embedders:**

- `query`: *On the Breadfast order #8319-5828179 delivered to Ranal in Heliopolis on 3 October 2022, what was the total?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5833 | `Test Content/40.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/187.jpg` |  |
| 3 | 0.3409 | `Test Content/265.jpg` |  |
| 4 | 0.3333 | `Test Content/249.jpg` |  |
| 5 | 0.3333 | `Test Content/378.jpg` |  |
| 6 | 0.2500 | `Test Content/362.jpg` |  |
| 7 | 0.2000 | `Test Content/193.jpg` |  |
| 8 | 0.2000 | `Test Content/303.jpg` |  |
| 9 | 0.1667 | `Test Content/305.jpg` |  |
| 10 | 0.1667 | `Test Content/147.jpg` |  |

**Predicted answer:**

The total for Breadfast order #319-5828179 (delivered to Rana I in Heliopolis on 3 October 2022) was EGP 76.99.

**sources_used:** `['Test Content/40.jpg']`

*Elapsed: 14.3s*

---

### 20. Expected receipt 40

**Q:** How much was the Wonderville Vanilla Cup Ice Cream on my Heliopolis Breadfast receipt from 3 October 2022?

**Ground truth:** EGP 13.50 each, 2 qty, total EGP 27.00

**Search query sent to embedders:**

- `query`: *How much was the Wonderville Vanilla Cup Ice Cream on my Heliopolis Breadfast receipt from 3 October 2022?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 1.0000 | `Test Content/40.jpg` | EXPECTED |
| 2 | 0.5333 | `Test Content/35.jpg` |  |
| 3 | 0.4242 | `Test Content/176.jpg` |  |
| 4 | 0.3500 | `Test Content/192.jpg` |  |
| 5 | 0.2500 | `Test Content/482.jpg` |  |
| 6 | 0.2333 | `Test Content/265.jpg` |  |
| 7 | 0.2143 | `Test Content/506.jpg` |  |
| 8 | 0.2000 | `Test Content/36.jpg` |  |
| 9 | 0.1944 | `Test Content/456.jpg` |  |
| 10 | 0.1750 | `Test Content/166.jpg` |  |

**Predicted answer:**

The Wonderville Vanilla Cup Ice Cream (150ml) on the Heliopolis Breadfast receipt from 3 October 2022 was 13.50.

**sources_used:** `['Test Content/40.jpg']`

*Elapsed: 10.7s*

---
