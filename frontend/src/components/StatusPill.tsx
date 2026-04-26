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

  // Shorten long model strings so the pill stays compact.
  const shortModel = status.llm_model.split("/").pop() ?? status.llm_model;

  return (
    <div className="status-pill">
      <span className="status-pill__dot" />
      <span className="status-pill__text">
        {shortModel} · {status.indexed_count.toLocaleString()} indexed · {status.llm_provider} ▸ qdrant {status.qdrant_provider}
      </span>
    </div>
  );
}
