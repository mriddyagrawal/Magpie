import { useEffect, useState } from "react";
import { getStatus } from "../api";
import type { StatusResponse } from "../types";

import "./StatusPill.css";

export function StatusPill() {
  const [status, setStatus] = useState<StatusResponse | null>(null);

  useEffect(() => {
    getStatus().then(setStatus).catch(() => {
      /* silent — pill just doesn't appear */
    });
  }, []);

  if (!status) return null;

  // Single user-facing fact: how much of their library is indexed.
  // Never expose model name, LLM provider, or storage backend — see
  // IO - Repo Structure.md for the no-tech-leak principle.
  const docsLabel = status.indexed_count === 1 ? "document" : "documents";

  return (
    <div className="status-pill">
      <span className={`status-pill__dot${status.ready ? "" : " status-pill__dot--off"}`} />
      <span className="status-pill__text">
        {status.indexed_count.toLocaleString()} {docsLabel} indexed
      </span>
    </div>
  );
}
