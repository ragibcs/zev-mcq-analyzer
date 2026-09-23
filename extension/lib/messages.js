/**
 * Message contract between popup, content script and service worker.
 * Keep in sync with backend/app/schemas/api.py.
 */

export const ANALYZE = "analyze";
export const EXPLAIN = "explain";
export const EXTRACT_SELECTION = "extract-selection";
export const PING = "ping";
