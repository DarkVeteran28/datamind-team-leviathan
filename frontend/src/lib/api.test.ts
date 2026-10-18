import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, checkApiProcess, getDatasetCatalog, submitQuestion } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('DataMind API client', () => {
  it('posts the trimmed question and returns the structured backend response', async () => {
    const result = { answer: '2 rows', rows: [[1], [2]], row_count: 2, query_id: 'qid' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitQuestion('  show two  ')).resolves.toEqual(result);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/query');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: 'show two', dataset_id: 'tpch_customer' });
  });

  it('includes the selected dataset when submitting a query', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ answer: 'local result' }) });
    vi.stubGlobal('fetch', fetchMock);
    await submitQuestion('renewables India', 'electricity_mix');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: 'renewables India', dataset_id: 'electricity_mix' });
  });

  it('loads the supported dataset registry', async () => {
    const catalog = { default_dataset_id: 'tpch_customer', datasets: [{ id: 'tpch_customer' }, { id: 'electricity_mix' }] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => catalog });
    vi.stubGlobal('fetch', fetchMock);
    await expect(getDatasetCatalog()).resolves.toEqual(catalog);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/datasets');
  });

  it('explains a missing catalog endpoint instead of a generic unavailable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 404, json: async () => ({ detail: 'Not Found' }),
    }));
    await expect(getDatasetCatalog()).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: expect.stringContaining('older DataMind API'),
    });
  });

  it('explains a catalog network failure with the API URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(getDatasetCatalog()).rejects.toMatchObject({
      name: 'ApiError',
      message: expect.stringContaining('/api/datasets'),
    });
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
