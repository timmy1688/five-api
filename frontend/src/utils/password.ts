/** Mirrors backend/app/services/passwords.py; the server stays the final judge. */
export const MIN_PASSWORD_CHARS = 12
export const MAX_PASSWORD_BYTES = 72
const MIN_CHARACTER_CLASSES = 3

export type PasswordProblem = 'short' | 'long' | 'mix'

function characterClasses(value: string): number {
  return [/\p{Ll}/u, /\p{Lu}/u, /\p{Nd}/u, /[^\p{L}\p{N}]/u].filter(pattern => pattern.test(value)).length
}

/** Return why a new password is rejected, or null when it is acceptable. */
export function passwordProblem(value: string): PasswordProblem | null {
  if (Array.from(value).length < MIN_PASSWORD_CHARS) return 'short'
  if (new TextEncoder().encode(value).length > MAX_PASSWORD_BYTES) return 'long'
  if (characterClasses(value) < MIN_CHARACTER_CLASSES) return 'mix'
  return null
}
