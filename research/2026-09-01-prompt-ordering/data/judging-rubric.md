# Grading rubric — HotpotQA multi-hop answers

You are grading model answers against reference answers. Two different models produced
these answers and they are deliberately mixed together with labels stripped. You cannot
tell which model wrote which answer, and you must not try to infer it.

## The single most important rule

**Answer length is not evidence of correctness.** One model in this pool writes terse
answers ("Duke Cunningham"); the other writes full sentences ("Brent Roger Wilkes was
connected to the Duke Cunningham defense contracting scandal"). Both styles can be right
or wrong. Do NOT reward fluency, hedged sophistication, or extra detail. Do NOT penalise
a bare entity for being bare. Judge only whether the reference answer is correctly and
committedly conveyed.

A previous grading pass is suspected of favouring the verbose model. Your job is to be
indifferent to style.

## Mark CORRECT (1) when

- The gold answer is present AND asserted as the answer, whether terse or wrapped in prose.
- Surface variation only: casing, punctuation, articles, honorifics, nicknames, middle
  names, abbreviation vs expansion ("NYPD's 83rd Precinct" = "New York City Police
  Department's 83rd Precinct"), formal vs common name ("James II" = "King James II of
  England"), date/number formatting ("2000" = "in 2000").
- A more complete or more specific form of the same entity ("Randy \"Duke\" Cunningham"
  for gold "Duke Cunningham"; "Mulberry (1986)" for gold "Mulberry").
- Yes/no questions where the model asserts the same polarity, with or without explanation
  ("Yes, both are dog breeds" = gold "yes").
- The answer is truncated mid-sentence but the gold answer has already been stated
  unambiguously.

## Mark INCORRECT (0) when — the failure modes

Use the reason code in brackets.

- **[WRONG_ENTITY]** A different entity is asserted as the answer.
- **[HEDGE]** No commitment: "it could be X or Y", "possibly X", "the text suggests X
  but also Y". Naming the gold answer among alternatives without choosing it is INCORRECT.
- **[NOT_FOUND]** The model says it cannot determine the answer, the passages don't say,
  or it declines — even if it then speculates correctly.
- **[SHOTGUN]** A list of several candidates without singling one out, where the gold
  answer happens to be among them.
- **[WRONG_RELATION]** The gold entity appears, but in the wrong role. Question asks for
  the *mother*, model names the *son*. Question asks which came *first*, model asserts
  the reverse order. The entity being present is not enough — the relation must be right.
- **[PARTIAL]** The gold answer is a set or compound ("Sears, Nordstrom and Saks") and
  the model supplies only part of it, or substitutes members.
- **[POLARITY]** Yes/no question answered with the opposite polarity.
- **[NUMERIC_MISS]** A number, date, or quantity that differs from gold beyond formatting
  ("almost 8 million" for gold "about 7 million"; wrong year).
- **[CONTRADICTION]** The answer asserts and then denies, or contains mutually exclusive
  claims, so no single answer is committed to.
- **[INCIDENTAL]** The gold string appears only as background context while a different
  answer is the one being given.
- **[OTHER]** Anything else wrong.

For CORRECT items use **[CORRECT_TERSE]** if the answer is essentially just the answer,
or **[CORRECT_VERBOSE]** if it is a sentence or contains extra commentary.

## Ground rules

- Judge only against `gold`. Do not use outside world knowledge to overrule the reference,
  even if you believe gold is wrong.
- Be mechanical and consistent. Do not calibrate leniency to how many you have marked wrong.
- Every uid in your input file gets exactly one verdict.
