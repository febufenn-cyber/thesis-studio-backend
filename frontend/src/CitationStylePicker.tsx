"use client";

import { useMemo, useState } from "react";
import {
  useCitationStyles,
  type CitationMechanism,
  type CitationStyle,
} from "./useCitationStyles";

export interface CitationStylePickerProps {
  /** Currently selected style key. */
  value: string;
  /** Called with the newly selected key. Should persist the change. */
  onChange: (newKey: string) => Promise<void>;
  /** Optional extra disabled state from the parent. */
  disabled?: boolean;
}

const MECHANISM_ORDER: CitationMechanism[] = [
  "author_date",
  "numbered",
  "author_page",
];

const MECHANISM_LABELS: Record<CitationMechanism, string> = {
  author_date: "Author-date",
  numbered: "Numbered",
  author_page: "Author-page",
};

export function CitationStylePicker({
  value,
  onChange,
  disabled,
}: CitationStylePickerProps) {
  const { styles, loading, error } = useCitationStyles();
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const map = new Map<CitationMechanism, CitationStyle[]>();
    for (const mech of MECHANISM_ORDER) map.set(mech, []);
    for (const style of styles) {
      if (!map.has(style.mechanism)) map.set(style.mechanism, []);
      map.get(style.mechanism)!.push(style);
    }
    return map;
  }, [styles]);

  async function handleChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newKey = e.target.value;
    if (newKey === value) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onChange(newKey);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save style");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <span style={{ fontSize: 14, color: "#666" }}>Loading styles…</span>;
  }
  if (error) {
    return (
      <span style={{ fontSize: 14, color: "#b00020" }}>
        Could not load citation styles: {error}
      </span>
    );
  }

  const isDisabled = disabled || saving;

  return (
    <div style={{ display: "inline-flex", flexDirection: "column", gap: 4 }}>
      <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>Citation style</span>
        <select
          value={value}
          onChange={handleChange}
          disabled={isDisabled}
          aria-busy={saving}
          style={{
            fontSize: 14,
            padding: "4px 8px",
            borderRadius: 6,
            border: "1px solid #ccc",
            minWidth: 240,
            opacity: isDisabled ? 0.6 : 1,
          }}
        >
          {MECHANISM_ORDER.filter((m) => (grouped.get(m)?.length ?? 0) > 0).map(
            (mech) => (
              <optgroup key={mech} label={MECHANISM_LABELS[mech]}>
                {grouped.get(mech)!.map((style) => (
                  <option key={style.key} value={style.key}>
                    {style.key} ({style.edition})
                  </option>
                ))}
              </optgroup>
            )
          )}
        </select>
        {saving && <span style={{ fontSize: 13, color: "#666" }}>Saving…</span>}
      </label>
      {saveError && (
        <span style={{ fontSize: 13, color: "#b00020" }}>{saveError}</span>
      )}
    </div>
  );
}
