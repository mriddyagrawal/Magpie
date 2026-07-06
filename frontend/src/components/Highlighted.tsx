import { useMemo } from "react";

/**
 * Wraps occurrences of `tokens` within `text` in <mark class="magpie-highlight">.
 * Case-insensitive, boundary-aware, longest-match-first so "reading glasses"
 * beats "reading" + "glasses" as separate highlights.
 */
export function Highlighted({
  text,
  tokens,
}: {
  text: string;
  tokens: string[];
}) {
  const parts = useMemo(() => splitWithTokens(text, tokens), [text, tokens]);
  return (
    <>
      {parts.map((p, i) =>
        p.highlight ? (
          <mark key={i} className="magpie-highlight">
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        )
      )}
    </>
  );
}

export interface Part {
  text: string;
  highlight: boolean;
}

export function splitWithTokens(text: string, tokens: string[]): Part[] {
  if (!tokens.length) return [{ text, highlight: false }];
  const sorted = [...new Set(tokens.filter(Boolean))].sort((a, b) => b.length - a.length);
  const escaped = sorted.map(escapeRegex);
  // Avoid matching tokens inside other words for purely-alphanumeric tokens;
  // allow loose match for phrases containing punctuation/whitespace.
  const alts = escaped.map((e) => (/^\w[\w-]*$/.test(e) ? `\\b${e}\\b` : e));
  const re = new RegExp(alts.join("|"), "gi");
  const parts: Part[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), highlight: false });
    parts.push({ text: m[0], highlight: true });
    last = m.index + m[0].length;
    if (m[0].length === 0) re.lastIndex++;
  }
  if (last < text.length) parts.push({ text: text.slice(last), highlight: false });
  return parts;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Best-effort extraction of "things worth highlighting" from an answer string.
 *
 * Deliberately CONSERVATIVE: only unambiguous "data facts" — currency, dates,
 * times, course codes, and quoted phrases. Earlier versions also highlighted
 * every all-caps token (PDF, API, JSON, LLM…) and every run of capitalised
 * words (section titles, product names, "Git Commit"…). On anything but a
 * business-doc corpus those fired constantly and made highlighting look
 * arbitrary — the exact "it highlights random words" complaint — so they've
 * been removed. Highlight only what a reader would recognise as a concrete
 * figure/date/name-in-quotes worth the eye landing on.
 */
export function extractHighlightTokens(answer: string): string[] {
  const tokens = new Set<string>();
  const patterns: RegExp[] = [
    // Currency with $/€/£, 1-6 digits, optional decimals
    /[\$€£]\s?\d{1,6}(?:[.,]\d{2})?/g,
    // Course codes: "CSC 121", "CSC-121", "PHY 111-01"
    /\b[A-Z]{2,4}[- ]\d{3}(?:-\d{2}L?)?\b/g,
    // Dates: 2024-05-14, 05/14/2024, May 14 2024, 14 May 2024, 25-May-21
    /\b\d{4}-\d{2}-\d{2}\b/g,
    /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/g,
    /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{2,4})?\b/g,
    /\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{2,4})?\b/g,
    // Times: 8:30 AM, 1:15 PM
    /\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)\b/g,
    // Quoted phrases (the model deliberately quoting the source)
    /"[^"]{2,50}"/g,
  ];
  for (const re of patterns) {
    const matches = answer.match(re);
    if (matches) matches.forEach((m) => tokens.add(m.trim()));
  }
  return Array.from(tokens);
}
