# Retrieval eval (stages 3 + 4)

- Run: 2026-04-13 08:31:00 UTC
- Model: `google/gemini-2.0-flash-lite-001` (via openrouter)
- Top-k: 10
- Query rewrite: off
- Questions: 20

## Headline

- Retrieval recall @ top-10: **19/20** (95%)
- Retrieval recall @ top-1:     **13/20** (65%)

## Summary

| # | Expected | Hit rank | Elapsed | Question |
|---|---|---|---|---|
| 1 | 30 | #1 | 15.7s | What was the total on my Breadfast order from 25 May 2022 th |
| 2 | 30 | #1 | 9.9s | On the Breadfast order delivered to New Cairo on 25 May 2022 |
| 3 | 31 | #1 | 11.9s | How much did I pay at Emarat Misr for L&M Light Box and Marl |
| 4 | 31 | #6 | 11.7s | What was the transaction number for my Emarat Misr cigarette |
| 5 | 32 | #1 | 10.3s | On the Breadfast receipt with Rich Basturma, Islandoy Cheese |
| 6 | 33 | #1 | 9.5s | What was the final total at Men's Club Collection / Carrefou |
| 7 | 33 | #1 | 8.2s | Which cashier rang up the Men's Club Carrefour receipt on 3/ |
| 8 | 34 | #1 | 8.7s | What was the grand total for my Decathlon Egypt purchase at  |
| 9 | 34 | #1 | 8.6s | On the Decathlon Almaza Mall receipt from September 2021, ho |
| 10 | 35 | #1 | 12.5s | What was the total on the Breadfast order delivered to Al Re |
| 11 | 36 | #1 | 9.9s | On the Breadfast order #108-14006842 delivered to New Cairo  |
| 12 | 36 | #1 | 7.5s | How much was the Cafe Con Leche on the Breadfast receipt del |
| 13 | 37 | #3 | 9.8s | What was the total at Gourmet Food Stores City Stars Naser C |
| 14 | 37 | #9 | 8.2s | Which cashier handled my Gourmet Food Stores Cairo receipt o |
| 15 | 38 | #2 | 4.7s | On the Breadfast order #121-5145529 for aya ali in Mohandise |
| 16 | 38 | #2 | 5.8s | What was the final total for the Breadfast delivery to Mohan |
| 17 | 39 | #6 | 10.5s | What did I pay at LC WAIKIKI TEMA Retail 6th of October on 0 |
| 18 | 39 | **MISS** | 8.4s | What was the change given back on the LC WAIKIKI 6th of Octo |
| 19 | 40 | #1 | 21.6s | On the Breadfast order #8319-5828179 delivered to Ranal in H |
| 20 | 40 | #1 | 11.3s | How much was the Wonderville Vanilla Cup Ice Cream on my Hel |

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
| 1 | 0.7500 | `Test Content/30.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/227.jpg` |  |
| 3 | 0.5000 | `Test Content/485.jpg` |  |
| 4 | 0.3333 | `Test Content/494.jpg` |  |
| 5 | 0.3095 | `Test Content/186.jpg` |  |
| 6 | 0.3000 | `Test Content/90.jpg` |  |
| 7 | 0.2222 | `Test Content/469.jpg` |  |
| 8 | 0.2000 | `Test Content/235.jpg` |  |
| 9 | 0.2000 | `Test Content/248.jpg` |  |
| 10 | 0.1964 | `Test Content/366.jpg` |  |

**Predicted answer:**

The total on your Breadfast order from 25 May 2022 that had fresh cheese, cold cuts, candies and yogurt was EGP 107.90.

**sources_used:** `['Test Content/30.jpg']`

*Elapsed: 15.7s*

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
| 1 | 1.0000 | `Test Content/30.jpg` | EXPECTED |
| 2 | 0.4167 | `Test Content/269.jpg` |  |
| 3 | 0.3611 | `Test Content/465.jpg` |  |
| 4 | 0.3500 | `Test Content/482.jpg` |  |
| 5 | 0.3333 | `Test Content/407.jpg` |  |
| 6 | 0.2667 | `Test Content/44.jpg` |  |
| 7 | 0.2625 | `Test Content/503.jpg` |  |
| 8 | 0.2000 | `Test Content/411.jpg` |  |
| 9 | 0.1667 | `Test Content/445.jpg` |  |
| 10 | 0.1623 | `Test Content/323.jpg` |  |

**Predicted answer:**

The delivery fee was EGP 10.00 via Delivery, as stated in the receipt.



**sources_used:** `['Test Content/30.jpg']`

*Elapsed: 9.9s*

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
| 2 | 0.5000 | `Test Content/373.jpg` |  |
| 3 | 0.4583 | `Test Content/462.jpg` |  |
| 4 | 0.4500 | `Test Content/515.jpg` |  |
| 5 | 0.3429 | `Test Content/122.jpg` |  |
| 6 | 0.3333 | `Test Content/304.jpg` |  |
| 7 | 0.2262 | `Test Content/346.jpg` |  |
| 8 | 0.1825 | `Test Content/498.jpg` |  |
| 9 | 0.1818 | `Test Content/368.jpg` |  |
| 10 | 0.1667 | `Test Content/127.jpg` |  |

**Predicted answer:**

I do not have the information needed to answer this question. The files do not contain a receipt for L&M Light Box and Marlboro Gold on 5 April 2023. 

**sources_used:** `[]`

*Elapsed: 11.9s*

---

### 4. Expected receipt 31

**Q:** What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?

**Ground truth:** 177444

**Search query sent to embedders:**

- `query`: *What was the transaction number for my Emarat Misr cigarette purchase on 05/04/23?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 6

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7000 | `Test Content/364.jpg` |  |
| 2 | 0.5000 | `Test Content/202.jpg` |  |
| 3 | 0.4103 | `Test Content/462.jpg` |  |
| 4 | 0.3929 | `Test Content/260.jpg` |  |
| 5 | 0.3929 | `Test Content/127.jpg` |  |
| 6 | 0.3860 | `Test Content/31.jpg` | EXPECTED |
| 7 | 0.2667 | `Test Content/225.jpg` |  |
| 8 | 0.2500 | `Test Content/288.jpg` |  |
| 9 | 0.2381 | `Test Content/122.jpg` |  |
| 10 | 0.1944 | `Test Content/346.jpg` |  |

**Predicted answer:**

The transaction number for the Emarat Misr cigarette purchase on 05/04/23 was 177444.

**sources_used:** `['Test Content/31.jpg']`

*Elapsed: 11.7s*

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
| 1 | 1.0000 | `Test Content/32.jpg` | EXPECTED |
| 2 | 0.4762 | `Test Content/203.jpg` |  |
| 3 | 0.3810 | `Test Content/469.jpg` |  |
| 4 | 0.3088 | `Test Content/416.jpg` |  |
| 5 | 0.3056 | `Test Content/227.jpg` |  |
| 6 | 0.2436 | `Test Content/155.jpg` |  |
| 7 | 0.2262 | `Test Content/482.jpg` |  |
| 8 | 0.2000 | `Test Content/478.jpg` |  |
| 9 | 0.2000 | `Test Content/230.jpg` |  |
| 10 | 0.1880 | `Test Content/488.jpg` |  |

**Predicted answer:**

I am sorry, but none of the provided receipts list all the items: Rich Basturma, Islandoy Cheese, 12 Brown Eggs and Chewy Farming Hot Lemon. Therefore, I cannot determine the subtotal.

**sources_used:** `[]`

*Elapsed: 10.3s*

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
| 1 | 0.8333 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.5833 | `Test Content/425.jpg` |  |
| 3 | 0.5000 | `Test Content/250.jpg` |  |
| 4 | 0.3667 | `Test Content/325.jpg` |  |
| 5 | 0.3269 | `Test Content/311.jpg` |  |
| 6 | 0.2500 | `Test Content/437.jpg` |  |
| 7 | 0.2361 | `Test Content/463.jpg` |  |
| 8 | 0.2361 | `Test Content/476.jpg` |  |
| 9 | 0.2338 | `Test Content/399.jpg` |  |
| 10 | 0.2000 | `Test Content/327.jpg` |  |

**Predicted answer:**

The final total at Men's Club Collection / Carrefour on 3/24/2022 after a 301 EGP discount was 249.00. 

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 9.5s*

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
| 1 | 0.6000 | `Test Content/33.jpg` | EXPECTED |
| 2 | 0.5909 | `Test Content/92.jpg` |  |
| 3 | 0.5333 | `Test Content/463.jpg` |  |
| 4 | 0.4103 | `Test Content/327.jpg` |  |
| 5 | 0.3611 | `Test Content/425.jpg` |  |
| 6 | 0.3333 | `Test Content/250.jpg` |  |
| 7 | 0.2857 | `Test Content/272.jpg` |  |
| 8 | 0.2833 | `Test Content/399.jpg` |  |
| 9 | 0.2111 | `Test Content/449.jpg` |  |
| 10 | 0.1917 | `Test Content/325.jpg` |  |

**Predicted answer:**

The cashier who rang up the Men's Club Carrefour receipt on 3/24/2022 was 189ahmed.

**sources_used:** `['Test Content/33.jpg']`

*Elapsed: 8.2s*

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
| 3 | 0.5000 | `Test Content/421.jpg` |  |
| 4 | 0.3667 | `Test Content/454.jpg` |  |
| 5 | 0.3667 | `Test Content/153.jpg` |  |
| 6 | 0.2540 | `Test Content/505.jpg` |  |
| 7 | 0.2540 | `Test Content/20.jpg` |  |
| 8 | 0.2500 | `Test Content/428.jpg` |  |
| 9 | 0.2000 | `Test Content/371.jpg` |  |
| 10 | 0.1667 | `Test Content/423.jpg` |  |

**Predicted answer:**

The grand total for a purchase including a foldable fitness bag and backpack at Decathlon Egypt, City Centre Almaza Mall on 07/09/21 was 795.00 E£ according to the provided receipt.

**sources_used:** `[]`

*Elapsed: 8.7s*

---

### 9. Expected receipt 34

**Q:** On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?

**Ground truth:** 5 items

**Search query sent to embedders:**

- `query`: *On the Decathlon Almaza Mall receipt from September 2021, how many items were sold in total?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 1

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/34.jpg` | EXPECTED |
| 2 | 0.5833 | `Test Content/153.jpg` |  |
| 3 | 0.5476 | `Test Content/20.jpg` |  |
| 4 | 0.5000 | `Test Content/336.jpg` |  |
| 5 | 0.3667 | `Test Content/421.jpg` |  |
| 6 | 0.3429 | `Test Content/454.jpg` |  |
| 7 | 0.2500 | `Test Content/149.jpg` |  |
| 8 | 0.2017 | `Test Content/17.jpg` |  |
| 9 | 0.1623 | `Test Content/504.jpg` |  |
| 10 | 0.1500 | `Test Content/215.jpg` |  |

**Predicted answer:**

I am sorry, but I cannot answer the question because the provided files do not contain a receipt from the Decathlon Almaza Mall from September 2021.

**sources_used:** `[]`

*Elapsed: 8.6s*

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
| 1 | 0.7000 | `Test Content/35.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/163.jpg` |  |
| 3 | 0.3333 | `Test Content/499.jpg` |  |
| 4 | 0.3333 | `Test Content/406.jpg` |  |
| 5 | 0.3056 | `Test Content/308.jpg` |  |
| 6 | 0.2500 | `Test Content/274.jpg` |  |
| 7 | 0.2000 | `Test Content/253.jpg` |  |
| 8 | 0.1667 | `Test Content/366.jpg` |  |
| 9 | 0.1667 | `Test Content/193.jpg` |  |
| 10 | 0.1611 | `Test Content/11.jpg` |  |

**Predicted answer:**

I am sorry, but the provided files do not contain the total for the Breakfast order delivered to Al Rehab City on 31 January 2022 for ahmed samaha.

**sources_used:** `[]`

*Elapsed: 12.5s*

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
| 2 | 0.4242 | `Test Content/161.jpg` |  |
| 3 | 0.4167 | `Test Content/503.jpg` |  |
| 4 | 0.4000 | `Test Content/30.jpg` |  |
| 5 | 0.3333 | `Test Content/158.jpg` |  |
| 6 | 0.2500 | `Test Content/482.jpg` |  |
| 7 | 0.2500 | `Test Content/43.jpg` |  |
| 8 | 0.2198 | `Test Content/269.jpg` |  |
| 9 | 0.1667 | `Test Content/235.jpg` |  |
| 10 | 0.1429 | `Test Content/323.jpg` |  |

**Predicted answer:**

The final total for order #108-14006842 delivered to New Cairo with Flat White, Latte and Cafe Con Leche was EGP 317.50.

**sources_used:** `['Test Content/36.jpg']`

*Elapsed: 9.9s*

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
| 1 | 0.7000 | `Test Content/36.jpg` | EXPECTED |
| 2 | 0.6000 | `Test Content/50.jpg` |  |
| 3 | 0.3333 | `Test Content/456.jpg` |  |
| 4 | 0.3333 | `Test Content/146.jpg` |  |
| 5 | 0.2679 | `Test Content/53.jpg` |  |
| 6 | 0.2500 | `Test Content/206.jpg` |  |
| 7 | 0.2500 | `Test Content/148.jpg` |  |
| 8 | 0.2167 | `Test Content/482.jpg` |  |
| 9 | 0.2000 | `Test Content/229.jpg` |  |
| 10 | 0.1667 | `Test Content/158.jpg` |  |

**Predicted answer:**

The Cafe Con Leche on the Breadfast receipt delivered on 10 December 2023 cost 75.00.

**sources_used:** `['Test Content/36.jpg']`

*Elapsed: 7.5s*

---

### 13. Expected receipt 37

**Q:** What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?

**Ground truth:** LE 437.21

**Search query sent to embedders:**

- `query`: *What was the total at Gourmet Food Stores City Stars Naser City for transaction 1089939?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 3

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.7500 | `Test Content/119.jpg` |  |
| 2 | 0.6667 | `Test Content/403.jpg` |  |
| 3 | 0.6667 | `Test Content/37.jpg` | EXPECTED |
| 4 | 0.2500 | `Test Content/27.jpg` |  |
| 5 | 0.2500 | `Test Content/80.jpg` |  |
| 6 | 0.2250 | `Test Content/329.jpg` |  |
| 7 | 0.2143 | `Test Content/382.jpg` |  |
| 8 | 0.2000 | `Test Content/86.jpg` |  |
| 9 | 0.1833 | `Test Content/354.jpg` |  |
| 10 | 0.1778 | `Test Content/302.jpg` |  |

**Predicted answer:**

The total for transaction #1089939 at Gourmet Food Stores City Stars Naser City was LE437.21.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 9.8s*

---

### 14. Expected receipt 37

**Q:** Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?

**Ground truth:** m.kara

**Search query sent to embedders:**

- `query`: *Which cashier handled my Gourmet Food Stores Cairo receipt on 11/2/2021?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 9

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5769 | `Test Content/403.jpg` |  |
| 2 | 0.5000 | `Test Content/405.jpg` |  |
| 3 | 0.4583 | `Test Content/329.jpg` |  |
| 4 | 0.3922 | `Test Content/264.jpg` |  |
| 5 | 0.3611 | `Test Content/119.jpg` |  |
| 6 | 0.3111 | `Test Content/285.jpg` |  |
| 7 | 0.2714 | `Test Content/354.jpg` |  |
| 8 | 0.2500 | `Test Content/326.jpg` |  |
| 9 | 0.2500 | `Test Content/37.jpg` | EXPECTED |
| 10 | 0.2143 | `Test Content/483.jpg` |  |

**Predicted answer:**

m.kara handled the Gourmet Food Stores Cairo receipt on 11/2/2021.

**sources_used:** `['Test Content/37.jpg']`

*Elapsed: 8.2s*

---

### 15. Expected receipt 38

**Q:** On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?

**Ground truth:** EGP 1.34

**Search query sent to embedders:**

- `query`: *On the Breadfast order #121-5145529 for aya ali in Mohandiseen, what was the previous due amount carried over?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 2

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/408.jpg` |  |
| 2 | 0.6111 | `Test Content/38.jpg` | EXPECTED |
| 3 | 0.5833 | `Test Content/440.jpg` |  |
| 4 | 0.4500 | `Test Content/156.jpg` |  |
| 5 | 0.2778 | `Test Content/457.jpg` |  |
| 6 | 0.2588 | `Test Content/378.jpg` |  |
| 7 | 0.1714 | `Test Content/452.jpg` |  |
| 8 | 0.1667 | `Test Content/338.jpg` |  |
| 9 | 0.1458 | `Test Content/306.jpg` |  |
| 10 | 0.1429 | `Test Content/258.jpg` |  |

**Predicted answer:**

The previous due amount carried over for order #121-5145529 for aya ali in Mohandiseen was EGP 1.34.

**sources_used:** `['Test Content/38.jpg']`

*Elapsed: 4.7s*

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
| 1 | 0.7000 | `Test Content/484.jpg` |  |
| 2 | 0.7000 | `Test Content/38.jpg` | EXPECTED |
| 3 | 0.6667 | `Test Content/440.jpg` |  |
| 4 | 0.3611 | `Test Content/477.jpg` |  |
| 5 | 0.3167 | `Test Content/338.jpg` |  |
| 6 | 0.3095 | `Test Content/228.jpg` |  |
| 7 | 0.2679 | `Test Content/179.jpg` |  |
| 8 | 0.2576 | `Test Content/321.jpg` |  |
| 9 | 0.1458 | `Test Content/457.jpg` |  |
| 10 | 0.1270 | `Test Content/150.jpg` |  |

**Predicted answer:**

The final total for the Breadfast delivery to Mohandiseen on 12 August 2022 that included Temry Chicken Fresh Chicken Fillet was EGP 243.34.

**sources_used:** `['Test Content/38.jpg']`

*Elapsed: 5.8s*

---

### 17. Expected receipt 39

**Q:** What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?

**Ground truth:** LE 200.00 cash (item LE 169.00 after discount)

**Search query sent to embedders:**

- `query`: *What did I pay at LC WAIKIKI TEMA Retail 6th of October on 05-Jan-21 for a men's blue long-sleeved shirt?*
- `keywords`: _(none)_

**Retrieval:** HIT at rank 6

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.5588 | `Test Content/280.jpg` |  |
| 2 | 0.5000 | `Test Content/99.jpg` |  |
| 3 | 0.4762 | `Test Content/374.jpg` |  |
| 4 | 0.3833 | `Test Content/317.jpg` |  |
| 5 | 0.3269 | `Test Content/112.jpg` |  |
| 6 | 0.3056 | `Test Content/39.jpg` | EXPECTED |
| 7 | 0.2769 | `Test Content/5.jpg` |  |
| 8 | 0.2667 | `Test Content/223.jpg` |  |
| 9 | 0.2361 | `Test Content/474.jpg` |  |
| 10 | 0.2143 | `Test Content/287.jpg` |  |

**Predicted answer:**

I am sorry, but the provided documents do not contain the price of a men's blue long-sleeved shirt purchased on 05-Jan-21 at LC WAIKIKI TEMA Retail 6th of October. Therefore, I am unable to answer this question.

**sources_used:** `[]`

*Elapsed: 10.5s*

---

### 18. Expected receipt 39

**Q:** What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?

**Ground truth:** LE 31.00

**Search query sent to embedders:**

- `query`: *What was the change given back on the LC WAIKIKI 6th of October receipt from January 2021?*
- `keywords`: _(none)_

**Retrieval:** **MISS** (expected path not in top-k)

**Top-10 retrieved:**

| Rank | Score | Path | Match? |
|---|---|---|---|
| 1 | 0.8333 | `Test Content/507.jpg` |  |
| 2 | 0.6000 | `Test Content/317.jpg` |  |
| 3 | 0.5833 | `Test Content/480.jpg` |  |
| 4 | 0.3088 | `Test Content/237.jpg` |  |
| 5 | 0.3000 | `Test Content/46.jpg` |  |
| 6 | 0.2576 | `Test Content/22.jpg` |  |
| 7 | 0.2000 | `Test Content/474.jpg` |  |
| 8 | 0.1667 | `Test Content/324.jpg` |  |
| 9 | 0.1429 | `Test Content/320.jpg` |  |
| 10 | 0.1429 | `Test Content/383.jpg` |  |

**Predicted answer:**

I am sorry, but none of the provided receipts are from January 2021 and therefore, I cannot answer the question.

**sources_used:** `[]`

*Elapsed: 8.4s*

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
| 1 | 0.5000 | `Test Content/40.jpg` | EXPECTED |
| 2 | 0.5000 | `Test Content/378.jpg` |  |
| 3 | 0.3922 | `Test Content/456.jpg` |  |
| 4 | 0.3333 | `Test Content/496.jpg` |  |
| 5 | 0.3000 | `Test Content/187.jpg` |  |
| 6 | 0.2679 | `Test Content/484.jpg` |  |
| 7 | 0.2500 | `Test Content/249.jpg` |  |
| 8 | 0.2436 | `Test Content/362.jpg` |  |
| 9 | 0.2000 | `Test Content/481.jpg` |  |
| 10 | 0.2000 | `Test Content/465.jpg` |  |

**Predicted answer:**

The total for order #319-5828178 delivered to Ranal in Heliopolis on 3 October 2022 was EGP 78.99.

**sources_used:** `['Test Content/40.jpg']`

*Elapsed: 21.6s*

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
| 2 | 0.4762 | `Test Content/176.jpg` |  |
| 3 | 0.3500 | `Test Content/192.jpg` |  |
| 4 | 0.3333 | `Test Content/274.jpg` |  |
| 5 | 0.3125 | `Test Content/411.jpg` |  |
| 6 | 0.3111 | `Test Content/121.jpg` |  |
| 7 | 0.2769 | `Test Content/506.jpg` |  |
| 8 | 0.2500 | `Test Content/166.jpg` |  |
| 9 | 0.1667 | `Test Content/482.jpg` |  |
| 10 | 0.1667 | `Test Content/35.jpg` |  |

**Predicted answer:**

The Wonderville Vanilla Cup Ice Cream cost EGP 13.50 on the Heliopolis Breadfast receipt from 3 October 2022.

**sources_used:** `['Test Content/40.jpg']`

*Elapsed: 11.3s*

---
