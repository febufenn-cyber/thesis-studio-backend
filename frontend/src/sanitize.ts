import DOMPurify from "dompurify";

/**
 * Sanitize server-provided HTML before it is injected via dangerouslySetInnerHTML.
 * citeproc bibliography entries (E5) are the first consumer: they are derived
 * from registry fields, but a field could contain markup, so we allow only the
 * small inline set a citation needs and strip everything else. (FRONTEND_LLD ADR-6.)
 */
const ALLOWED_TAGS = ["i", "em", "b", "strong", "span", "sup", "sub", "a", "br", "u", "small"];
const ALLOWED_ATTR = ["href", "class", "lang", "dir"];

export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
  });
}
