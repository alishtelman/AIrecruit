const ROLE_MISMATCH_MARKERS = [
  "account does not match this login type",
  "login type",
];

export function isAccountTypeMismatchError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  const message = error.message.toLowerCase();
  return ROLE_MISMATCH_MARKERS.some((marker) => message.includes(marker));
}
