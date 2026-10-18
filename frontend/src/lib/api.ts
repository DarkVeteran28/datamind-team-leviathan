import type { DatasetCatalogResponse, QueryRequest, QueryResponse } from '../types/api';

const API_BASE = (import.meta.env.VITE_DATAMIND_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 150_000;

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function submitQuestion(question: string, datasetId = 'tpch_customer'): Promise<QueryResponse> {
  const request: QueryRequest = { question: question.trim(), dataset_id: datasetId };
  if (!request.question) throw new ApiError('Enter a question before submitting.');

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}/api/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!response.ok) {
      let message = 'The DataMind backend could not process this request.';
      try {
        const body = await response.json() as { detail?: unknown };
        if (typeof body.detail === 'string') message = body.detail;
      } catch {
        // Keep the safe generic message when the server did not return JSON.
      }
      throw new ApiError(message, response.status);
    }
    return await response.json() as QueryResponse;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('The request timed out. The backend may still be finishing its model or database call.');
    }
    throw new ApiError('Cannot reach the DataMind API. Start the Python backend and try again.');
  } finally {
    window.clearTimeout(timer);
  }
}

export async function getDatasetCatalog(): Promise<DatasetCatalogResponse> {
  const url = `${API_BASE}/api/datasets`;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      let detail = '';
      try {
        const body = await response.json() as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // Keep a status-based message when the server did not return JSON.
      }
      if (response.status === 404) {
        throw new ApiError(
          `Dataset catalog was not found at ${url}. The frontend is calling an older DataMind API. Start the current API on port 8000, or set VITE_DATAMIND_API_URL to the running API and restart Vite.`,
          response.status,
        );
      }
      throw new ApiError(
        detail || `Dataset catalog request failed with HTTP ${response.status} at ${url}.`,
        response.status,
      );
    }
    return await response.json() as DatasetCatalogResponse;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(`Cannot reach the dataset catalog at ${url}. Start the current DataMind API on port 8000 and retry.`);
  }
}

export async function checkApiProcess(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/health`, { method: 'GET' });
    return response.ok;
  } catch {
    return false;
  }
}
