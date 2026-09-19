// Pure reading of the server's explanation evidence. The panel must never
// present a fact as proof of a reason when the value contradicts that reason.
// A false boolean, a zero count or an empty collection is a recorded fact but
// not support, so the reason it is paired with must be reported as unsupported.

export interface ReasonSupport {
  supported: string[];
  unsupported: string[];
}

// Evidence keys each displacement reason code must justify. A code with no
// entry here needs no local facts and is always treated as supported. For codes
// with an entry, at least one key must carry a confirming value; a code whose
// keys are all false/zero/empty is unsupported.
export const REASON_EVIDENCE_KEYS: Record<string, string[]> = {
  BUFFER_CLOSURE: ["buffer_sectors", "closure_location_count"],
  LIVE_MIRROR: ["opposite_bound_required", "mirrored_location_count"],
  INTERCHANGE: ["interchange_location_count"],
  POSSESSION_MIX: ["access_type", "mix_groups"],
  CO_SHARE_PACKED: ["co_share_group", "co_share_partners"],
  CAPACITY: ["capacity_location", "capacity_limit"],
};

export function isConfirmingEvidence(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return Number.isFinite(value) && value > 0;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return false;
}

export function reasonSupport(
  evidence: Record<string, unknown>,
  reasonCodes: string[],
): ReasonSupport {
  const supported: string[] = [];
  const unsupported: string[] = [];
  for (const code of reasonCodes) {
    const keys = REASON_EVIDENCE_KEYS[code];
    if (!keys) {
      supported.push(code);
      continue;
    }
    if (keys.some((key) => isConfirmingEvidence(evidence[key]))) {
      supported.push(code);
    } else {
      unsupported.push(code);
    }
  }
  return { supported, unsupported };
}

// The evidence keys tied to the reason codes currently on screen. Used to mark
// facts that sit next to a reason but do not confirm it.
export function reasonEvidenceKeys(reasonCodes: string[]): Set<string> {
  const keys = new Set<string>();
  for (const code of reasonCodes) {
    for (const key of REASON_EVIDENCE_KEYS[code] ?? []) keys.add(key);
  }
  return keys;
}

export function evidenceIsNeutral(
  key: string,
  value: unknown,
  reasonKeys: ReadonlySet<string>,
): boolean {
  return reasonKeys.has(key) && !isConfirmingEvidence(value);
}
