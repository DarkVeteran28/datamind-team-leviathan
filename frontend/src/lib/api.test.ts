import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, checkApiProcess, submitQuestion } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('DataMind API client', () => {
  it('posts the trimmed question and returns the structured backend response', async () => {
    const result = { answer: '2 rows', rows: [[1], [2]], row_count: 2, query_id: 'qid' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitQuestion('  show two  ')).resolves.toEqual(result);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/query');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: 'show two' });
  });

  it('uses a safe backend error message and refuses blank input', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 422, json: async () => ({ detail: 'Invalid query request.' }),
    }));
    await expect(submitQuestion('ask')).rejects.toMatchObject({ name: 'ApiError', message: 'Invalid query request.', status: 422 });
    await expect(submitQuestion('  ')).rejects.toBeInstanceOf(ApiError);
  });

  it('reports API process health without claiming dependency health', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    await expect(checkApiProcess()).resolves.toBe(true);
  });
});
