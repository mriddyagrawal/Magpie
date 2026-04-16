# ReceiptQA random-sample eval

- Model: `google/gemini-2.0-flash-lite-001` (via openrouter)
- Timestamp: 2026-04-13T07:26:07.357931+00:00
- Pool size: 25534 QA pairs across 521 receipts
- Sample size: 25
- Seed: 42

**25/25 completed without error.**

---

## 1. Receipt 428 — source: GPT

**Receipt:** [428.jpg](../Test%20Content/428.jpg)

**Q:** What is the store number?

**Ground truth:**

702395

**Predicted:**

The store number is 702395.

**sources_used:** `['Test Content/428.jpg']`

---

## 2. Receipt 75 — source: Human

**Receipt:** [75.jpg](../Test%20Content/75.jpg)

**Q:** What is the name of item 2?

**Ground truth:**

Not Available

**Predicted:**

I am sorry, but the provided file does not contain a list of items and their names. Therefore, I cannot determine the name of item 2.

**sources_used:** `['Test Content/75.jpg']`

---

## 3. Receipt 17 — source: Human

**Receipt:** [17.jpg](../Test%20Content/17.jpg)

**Q:** What is the subtotal for this receipt?

**Ground truth:**

Not Available

**Predicted:**

The subtotal for the receipt is *699,00.

**sources_used:** `['Test Content/17.jpg']`

---

## 4. Receipt 496 — source: Human

**Receipt:** [496.jpg](../Test%20Content/496.jpg)

**Q:** List all items and their respective quantities from this receipt.?

**Ground truth:**

```json
[
  {
    "item": "Green Apples (1Kg)",
    "quantity": "1",
    "total_price": "44.95"
  }
]
```

**Predicted:**

The receipt shows one item: Green Apples (1Kg) with a quantity of 1.

**sources_used:** `['Test Content/496.jpg']`

---

## 5. Receipt 184 — source: Human

**Receipt:** [184.jpg](../Test%20Content/184.jpg)

**Q:** What is the total tax for this receipt?

**Ground truth:**

EGP 17.68

**Predicted:**

The total tax is EGP 17.68.

**sources_used:** `['Test Content/184.jpg']`

---

## 6. Receipt 164 — source: GPT

**Receipt:** [164.jpg](../Test%20Content/164.jpg)

**Q:** What is the balance due?

**Ground truth:**

84.00

**Predicted:**

The balance due is 84.00.

**sources_used:** `['Test Content/164.jpg']`

---

## 7. Receipt 150 — source: GPT

**Receipt:** [150.jpg](../Test%20Content/150.jpg)

**Q:** What was the third item purchased?

**Ground truth:**

Khokhaia New Zatar Cheddar Cheese (200g)

**Predicted:**

The third item purchased was "Khoshala New Zealand Cheddar Cheese (200g)".

**sources_used:** `['Test Content/150.jpg']`

---

## 8. Receipt 94 — source: Human

**Receipt:** [94.jpg](../Test%20Content/94.jpg)

**Q:** What is the TransactionDate for this receipt?

**Ground truth:**

16/10/2021

**Predicted:**

The TransactionDate is 16/10/2021.

**sources_used:** `['Test Content/94.jpg']`

---

## 9. Receipt 493 — source: Human

**Receipt:** [493.jpg](../Test%20Content/493.jpg)

**Q:** What is the receipt number for this receipt?

**Ground truth:**

Not Available

**Predicted:**

The receipt number is 250560.

**sources_used:** `['Test Content/493.jpg']`

---

## 10. Receipt 69 — source: GPT

**Receipt:** [69.jpg](../Test%20Content/69.jpg)

**Q:** What is the transaction number?

**Ground truth:**

T#0000074

**Predicted:**

The transaction number is T#0000074.

**sources_used:** `['Test Content/69.jpg']`

---

## 11. Receipt 453 — source: GPT

**Receipt:** [453.jpg](../Test%20Content/453.jpg)

**Q:** What is the price of one Ginger & Cinnamon Mini Cookie?

**Ground truth:**

29.00

**Predicted:**

The price of 2 Ginger & Cinnamon Mini Cookies (5pcs) is EGP 29.00. Therefore, the price of one Ginger & Cinnamon Mini Cookie is EGP 14.50.

**sources_used:** `['Test Content/453.jpg']`

---

## 12. Receipt 496 — source: GPT

**Receipt:** [496.jpg](../Test%20Content/496.jpg)

**Q:** Is VAT included in the total amount?

**Ground truth:**

Yes

**Predicted:**

VAT value of EGP 0 is already included in the total amount.

**sources_used:** `['Test Content/496.jpg']`

---

## 13. Receipt 365 — source: GPT

**Receipt:** [365.jpg](../Test%20Content/365.jpg)

**Q:** What is the name of the store?

**Ground truth:**

LC WAIKIKI

**Predicted:**

The store name is LC WAIKIKI.

**sources_used:** `['Test Content/365.jpg']`

---

## 14. Receipt 59 — source: Human

**Receipt:** [59.jpg](../Test%20Content/59.jpg)

**Q:** What is the name of item 2?

**Ground truth:**

Cajun Combo

**Predicted:**

The name of item 2 is "Cajun Combo".

**sources_used:** `['Test Content/59.jpg']`

---

## 15. Receipt 395 — source: GPT

**Receipt:** [395.jpg](../Test%20Content/395.jpg)

**Q:** What is the current balance?

**Ground truth:**

-EGP 3.53

**Predicted:**

The current balance is -EGP 3.53.

**sources_used:** `['Test Content/395.jpg']`

---

## 16. Receipt 283 — source: GPT

**Receipt:** [283.jpg](../Test%20Content/283.jpg)

**Q:** What is the commercial register number?

**Ground truth:**

7376

**Predicted:**

The commercial register number is 7376.

**sources_used:** `['Test Content/283.jpg']`

---

## 17. Receipt 22 — source: GPT

**Receipt:** [22.jpg](../Test%20Content/22.jpg)

**Q:** What is the date of the transaction?

**Ground truth:**

08-May-21

**Predicted:**

The date of the transaction is 08-May-21.

**sources_used:** `['Test Content/22.jpg']`

---

## 18. Receipt 20 — source: GPT

**Receipt:** [20.jpg](../Test%20Content/20.jpg)

**Q:** What is the RFID of the third item?

**Ground truth:**

0002332671

**Predicted:**

The RFID of the third item is 0002332671.

**sources_used:** `['Test Content/20.jpg']`

---

## 19. Receipt 63 — source: GPT

**Receipt:** [63.jpg](../Test%20Content/63.jpg)

**Q:** Is the receipt handwritten or printed?

**Ground truth:**

printed

**Predicted:**

The receipt is printed.

**sources_used:** `['Test Content/63.jpg']`

---

## 20. Receipt 147 — source: GPT

**Receipt:** [147.jpg](../Test%20Content/147.jpg)

**Q:** What is the name of the store?

**Ground truth:**

Breadfast

**Predicted:**

The name of the store is Breadfast.

**sources_used:** `['Test Content/147.jpg']`

---

## 21. Receipt 156 — source: Human

**Receipt:** [156.jpg](../Test%20Content/156.jpg)

**Q:** What is the total number of items with a quantity of more than 1?

**Ground truth:**

Not valid

**Predicted:**

There are no items with a quantity of more than 1.

**sources_used:** `['Test Content/156.jpg']`

---

## 22. Receipt 338 — source: Human

**Receipt:** [338.jpg](../Test%20Content/338.jpg)

**Q:** List all items in the receipt.?

**Ground truth:**

```json
[
  "VAT value of EGP 19.83 is already included in\nthe total amount.",
  "Red Onions (1Kg)\n1 7.75\n7.75",
  "Hot Green Pepper (250g)\n1 6.00\n6.00\nPoultry",
  "Temry Chicken - Fresh\n1 63.00\n63.00\nChicken Legs (1kg)",
  "Temry Chicken - Fresh\n1 36.00\n36.00\nLiver (500g)",
  "Breadfast BYLD Ksto\n6 28.00 168.00\nChocolate Bar (60g)\nFresh Cheese",
  "Ba adi Cottage Cheese\n1 47.00\n47.00\nwit\" Black Ssecp (750g)",
  "Signal Cavity Fighter\n1 19.95\n19.95\nToothpaste Offer 15% Off\n(120ml)"
]
```

**Predicted:**

The receipt includes: Chinese Garlic, Red Onions, Hot Green Pepper, Temry Chicken Fresh, Chicken Legs, Liver, Breadfast BYLD Kato Chocolate Bar, Baladi Cottage Cheese with Black Saadg, and Signal Cavity Fighter Toothpaste Offer.

**sources_used:** `['Test Content/338.jpg']`

---

## 23. Receipt 403 — source: GPT

**Receipt:** [403.jpg](../Test%20Content/403.jpg)

**Q:** What time was the transaction?

**Ground truth:**

6:41:43 PM

**Predicted:**

The transaction time was 6:41:43 PM.

**sources_used:** `['Test Content/403.jpg']`

---

## 24. Receipt 18 — source: GPT

**Receipt:** [18.jpg](../Test%20Content/18.jpg)

**Q:** What is the cashier's name?

**Ground truth:**

Tantacrf

**Predicted:**

The cashier's name is Tantacrf.

**sources_used:** `['Test Content/18.jpg']`

---

## 25. Receipt 376 — source: Human

**Receipt:** [376.jpg](../Test%20Content/376.jpg)

**Q:** What is the transaction time for this receipt?

**Ground truth:**

12:17

**Predicted:**

The transaction time is 12:17.

**sources_used:** `['Test Content/376.jpg']`

---
