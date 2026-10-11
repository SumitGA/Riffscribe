import { apiUrl } from '@/config';

/** The public legal pages, served next to the API (infra/site): terms, privacy, account deletion. */
export function legalUrl(page: 'terms' | 'privacy' | 'delete-account'): string {
  return `${apiUrl()}/${page}`;
}
