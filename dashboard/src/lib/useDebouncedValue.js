import { useEffect, useRef, useState } from 'react';

/**
 * A copy of `value` that stops changing while you are still changing it.
 *
 * The live value drives the input you are typing into; the debounced copy drives
 * anything expensive that watches it. Without the split, a preview that costs a
 * few milliseconds to rebuild gets rebuilt on every keystroke, and typing feels
 * like wading.
 *
 * Compares with JSON rather than identity on purpose: the values here are small
 * config objects rebuilt on every render, so an identity check would see a
 * change every time and defeat the whole thing.
 */
export default function useDebouncedValue(value, ms = 250) {
  const [settled, setSettled] = useState(value);
  const lastRef = useRef(JSON.stringify(value));

  useEffect(() => {
    const next = JSON.stringify(value);
    if (next === lastRef.current) return undefined;
    const t = setTimeout(() => {
      lastRef.current = next;
      setSettled(value);
    }, ms);
    return () => clearTimeout(t);
  }, [value, ms]);

  return settled;
}
