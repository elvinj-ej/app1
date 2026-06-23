"use client";

import { currentFyYear } from "@/lib/db/aws-types";

interface Props {
  value: number;
  onChange: (v: number) => void;
}

export function FySelector({ value, onChange }: Props) {
  const cur = currentFyYear();
  const years = [cur - 1, cur, cur + 1];

  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="border rounded px-2 py-1 text-sm bg-white"
    >
      {years.map((y) => (
        <option key={y} value={y}>
          FY{String(y + 1).slice(-2)} (Jul {y} – Jun {y + 1})
        </option>
      ))}
    </select>
  );
}
