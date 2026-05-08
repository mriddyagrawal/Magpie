/**
 * SearchAITab — the Settings → Search & AI tab.
 *
 * Layout (per Specs/UI/settings_window.md):
 *   - Title + subtitle ("Pick the brain that answers your questions.")
 *   - Two-card binary: Local (private badge) / Cloud (fast badge)
 *   - Privacy tagline below the cards
 *   - Advanced expander (collapsed by default):
 *       - Top K slider (1-20)
 *       - Temperature slider (0.0-2.0)
 *       - "Rewrite ambiguous questions" toggle
 *       - "Cite sources inline" toggle
 *       - Reset to defaults button
 *
 * All knobs PATCH /settings/search with a 250ms debounce so slider
 * drags don't flood the backend. Single-shot toggles fire
 * immediately.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getProviders,
  getSearchSettings,
  patchSearchSettings,
} from "../../api";
import type { ProvidersInfo, SearchSettings, SearchSettingsPatch } from "../../api";

interface Props {
  search: SearchSettings | null;
  setSearch: (s: SearchSettings) => void;
  providers: ProvidersInfo | null;
  setProviders: (p: ProvidersInfo) => void;
}

const DEBOUNCE_MS = 250;

export function SearchAITab({ search, setSearch, providers, setProviders }: Props) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Initial fetch (only if parent didn't already populate).
  useEffect(() => {
    if (search === null) {
      getSearchSettings().then(setSearch).catch((e) => setError((e as Error).message));
    }
    if (providers === null) {
      getProviders().then(setProviders).catch(() => { /* non-fatal */ });
    }
  }, [search, providers, setSearch, setProviders]);

  // Debounced patch helper. The slider's onChange fires up to 60Hz
  // while dragging; we batch into a single PATCH 250ms after the
  // last change.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queuedRef = useRef<SearchSettingsPatch>({});
  const queuePatch = useCallback((p: SearchSettingsPatch) => {
    queuedRef.current = { ...queuedRef.current, ...p };
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const body = queuedRef.current;
      queuedRef.current = {};
      try {
        const updated = await patchSearchSettings(body);
        setSearch(updated);
      } catch (e) {
        setError((e as Error).message);
      }
    }, DEBOUNCE_MS);
  }, [setSearch]);

  // Immediate patch (for toggles + provider switch).
  const immediatePatch = useCallback(async (p: SearchSettingsPatch) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    queuedRef.current = {};
    try {
      const updated = await patchSearchSettings(p);
      setSearch(updated);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [setSearch]);

  const handleProvider = useCallback((p: "local" | "cloud") => {
    immediatePatch({ provider: p });
  }, [immediatePatch]);

  const handleResetDefaults = useCallback(async () => {
    immediatePatch({
      top_k: 5,
      rewrite: false,
      temperature: 0.7,
      cite_sources_inline: true,
    });
  }, [immediatePatch]);

  if (search === null) {
    return (
      <div className="search-ai-tab">
        <p className="search-ai-tab__loading">Loading…</p>
      </div>
    );
  }

  return (
    <div className="search-ai-tab">
      <header className="search-ai-tab__header">
        <h1 className="search-ai-tab__title">Search & AI</h1>
        <p className="search-ai-tab__subtitle">
          Pick the brain that answers your questions. Switch any time.
        </p>
      </header>
      {error && <div className="search-ai-tab__error">⚠ {error}</div>}

      <section className="search-ai-tab__providers">
        <h2 className="search-ai-tab__section-title">Provider</h2>
        <div className="provider-grid">
          <ProviderCard
            label="Local"
            badge="private"
            badgeTone="neutral"
            description={
              providers?.local?.model
                ? `${providers.local.model} · runs on your machine`
                : "Runs on your machine"
            }
            selected={search.provider === "local"}
            onSelect={() => handleProvider("local")}
          />
          <ProviderCard
            label="Cloud"
            badge="fast"
            badgeTone="accent"
            description={
              providers?.cloud?.configured === false
                ? "Not configured yet"
                : "Our free model for faster answers"
            }
            selected={search.provider === "cloud"}
            onSelect={() => handleProvider("cloud")}
            disabled={providers?.cloud?.configured === false}
          />
        </div>
        <p className="search-ai-tab__privacy">
          Local stays on your machine. Cloud only ever sees your
          question, never your files.
        </p>
      </section>

      <section
        className={`advanced-panel ${advancedOpen ? "is-open" : ""}`}
        aria-labelledby="advanced-toggle"
      >
        <header className="advanced-panel__header">
          <button
            id="advanced-toggle"
            type="button"
            className="advanced-panel__toggle"
            onClick={() => setAdvancedOpen(!advancedOpen)}
            aria-expanded={advancedOpen}
          >
            <span className="advanced-panel__chevron" aria-hidden="true">
              {advancedOpen ? "▼" : "▶"}
            </span>
            <span className="advanced-panel__title">Advanced</span>
            <span className="advanced-panel__hint">
              retrieval & generation knobs
            </span>
          </button>
          {advancedOpen && (
            <button
              type="button"
              className="advanced-panel__reset"
              onClick={handleResetDefaults}
            >
              Reset to defaults
            </button>
          )}
        </header>
        {advancedOpen && (
          <div className="advanced-panel__body">
            <div className="advanced-panel__sliders">
              <SliderField
                label="Top K"
                value={search.top_k}
                min={1}
                max={20}
                step={1}
                onChange={(v) => {
                  setSearch({ ...search, top_k: v });
                  queuePatch({ top_k: v });
                }}
                hint="How many sources to retrieve before answering."
              />
              <SliderField
                label="Temperature"
                value={search.temperature}
                min={0}
                max={2}
                step={0.05}
                format={(v) => v.toFixed(2)}
                onChange={(v) => {
                  setSearch({ ...search, temperature: v });
                  queuePatch({ temperature: v });
                }}
                hint="Lower = literal. Higher = creative."
              />
            </div>
            <ToggleField
              label="Rewrite ambiguous questions"
              hint="Slower, more accurate on noisy queries."
              checked={search.rewrite}
              onChange={(v) => immediatePatch({ rewrite: v })}
            />
            <ToggleField
              label="Cite sources inline"
              hint="Number sources in the answer with clickable footnotes."
              checked={search.cite_sources_inline ?? true}
              onChange={(v) => immediatePatch({ cite_sources_inline: v })}
            />
          </div>
        )}
      </section>
    </div>
  );
}

function ProviderCard({
  label,
  badge,
  badgeTone,
  description,
  selected,
  disabled,
  onSelect,
}: {
  label: string;
  badge: string;
  badgeTone: "accent" | "neutral";
  description: string;
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`provider-card ${selected ? "is-selected" : ""} ${disabled ? "is-disabled" : ""}`}
      onClick={() => !disabled && onSelect()}
      disabled={disabled}
    >
      <div className="provider-card__header">
        <span className="provider-card__icon" aria-hidden="true">
          {label === "Local" ? "◐" : "☁"}
        </span>
        <span className="provider-card__label">{label}</span>
        {selected && (
          <span className="provider-card__check" aria-hidden="true">✓</span>
        )}
      </div>
      <div className="provider-card__description">{description}</div>
      <div className={`provider-card__badge provider-card__badge--${badgeTone}`}>
        {badge}
      </div>
    </button>
  );
}

function SliderField({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
  onChange: (v: number) => void;
  hint: string;
}) {
  return (
    <div className="slider-field">
      <div className="slider-field__header">
        <span className="slider-field__label">{label}</span>
        <span className="slider-field__value">{format ? format(value) : value}</span>
      </div>
      <input
        type="range"
        className="slider-field__range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <p className="slider-field__hint">{hint}</p>
    </div>
  );
}

function ToggleField({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="toggle-field">
      <div className="toggle-field__text">
        <span className="toggle-field__label">{label}</span>
        <span className="toggle-field__hint">{hint}</span>
      </div>
      <button
        type="button"
        className={`toggle-switch ${checked ? "is-on" : ""}`}
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-switch__knob" aria-hidden="true" />
      </button>
    </div>
  );
}
