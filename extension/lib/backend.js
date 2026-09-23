/**
 * Backend client for the service worker.
 * Endpoint contract: backend/app/api/routes.py
 */

const DEFAULT_BASE_URL = "http://localhost:8000";
const API_PREFIX = "/api/v1";

export async function getConfig(baseUrl) {
  const res = await fetchJson(new URL(API_PREFIX + "/config", baseUrl));
  return res;
}

export async function getProviders(baseUrl) {
  return fetchJson(new URL(API_PREFIX + "/providers", baseUrl));
}

export async function analyze(baseUrl, apiKey, { question, options }) {
  const body = {
    question,
    options, // [{ id, text }]
  };
  return fetchJson(new URL(API_PREFIX + "/analyze", baseUrl), {
    method: "POST",
    headers: buildHeaders(apiKey),
    body: JSON.stringify(body),
  });
}

export async function explain(baseUrl, apiKey, { question, options, jevResult }) {
  return fetchJson(new URL(API_PREFIX + "/explain", baseUrl), {
    method: "POST",
    headers: buildHeaders(apiKey),
    body: JSON.stringify({
      question,
      options,
      jev_result: jevResult,
    }),
  });
}

function buildHeaders(apiKey) {
  const headers = { "Content-Type": "application/json" };
  if (apiKey) headers["X-API-Key"] = apiKey;
  return headers;
}

async function fetchJson(url, init) {
  let res;
  try {
    res = await fetch(url, init);
  } catch (err) {
    throw new Error(
      `Cannot reach backend at ${url.origin}. Is it running? (${err.message})`
    );
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    /* non-JSON body */
  }

  if (!res.ok) {
    const detail =
      (data && (data.detail || data.error)) || res.statusText || "Request failed";
    throw new Error(`Backend ${res.status}: ${detail}`);
  }
  return data;
}
