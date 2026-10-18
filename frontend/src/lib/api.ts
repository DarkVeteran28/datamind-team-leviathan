import type { QueryRequest, QueryResponse } from '../types/api';

const API_BASE = (import.meta.env.VITE_DATAMIND_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 150_000;

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function submitQuestion(question: string): Promise<QueryResponse> {
  const request: QueryRequest = { question: question.trim() };
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

export async function checkApiProcess(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/health`, { method: 'GET' });
    return response.ok;
  } catch {
    return false;
  }
}
