"use client";

import { Button } from "@/components/ui/button";

type BulletListEditorProps = {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  emptyHint?: string;
};

export function BulletListEditor({
  label,
  items,
  onChange,
  disabled = false,
  placeholder = "Add a bullet point…",
  emptyHint = "No bullets yet — click Add bullet.",
}: BulletListEditorProps) {
  function updateAt(index: number, value: string) {
    const next = [...items];
    next[index] = value;
    onChange(next);
  }

  function removeAt(index: number) {
    onChange(items.filter((_, i) => i !== index));
  }

  function addBullet() {
    onChange([...items, ""]);
  }

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{label}</p>
      {items.length === 0 ? (
        <p className="text-xs text-slate-500">{emptyHint}</p>
      ) : null}
      <ul className="space-y-2">
        {items.map((item, index) => (
          <li key={index} className="flex gap-2">
            <span className="mt-2 text-slate-400" aria-hidden>
              •
            </span>
            <input
              type="text"
              value={item}
              disabled={disabled}
              placeholder={placeholder}
              onChange={(e) => updateAt(index, e.target.value)}
              className="flex-1 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={() => removeAt(index)}
              className="shrink-0 text-red-600"
            >
              Remove
            </Button>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={addBullet}
      >
        Add bullet
      </Button>
    </div>
  );
}
