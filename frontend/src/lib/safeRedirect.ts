export function getSafeRedirect(value: string | null | undefined, fallback: string): string {
  if (!value) return fallback;

  const redirect = value.trim();
  if (!redirect.startsWith("/") || redirect.startsWith("//")) {
    return fallback;
  }

  return redirect;
}
