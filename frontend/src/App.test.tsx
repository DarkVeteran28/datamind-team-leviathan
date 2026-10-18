import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { checkApiProcess, submitQuestion } from './lib/api';
import type { QueryResponse } from './types/api';

vi.mock('./lib/api', () => ({
  checkApiProcess: vi.fn().mockResolvedValue(false),
  submitQuestion: vi.fn(),
}));

const success: QueryResponse = {
  answer: 'Customer 42 has the highest returned balance: 950.',
  sql: 'SELECT C_CUSTKEY, C_ACCTBAL FROM CUSTOMER ORDER BY C_ACCTBAL DESC LIMIT 1',
  columns: ['C_CUSTKEY', 'C_ACCTBAL'], rows: [[42, 950]], row_count: 1,
  query_id: 'query-123', assumptions: [], warnings: [],
  validation: { status: 'passed', checks: [{ name: 'single_select', status: 'passed' }] },
  execution: { status: 'succeeded', checks: [] },
  verification: { status: 'passed', checks: [{ name: 'row_count', status: 'passed' }] },
  clarification: { required: false },
};

function enterQuestion(question: string) {
  fireEvent.change(screen.getByRole('textbox', { name: 'Ask your data' }), { target: { value: question } });
  fireEvent.click(screen.getByRole('button', { name: /Analyze data/i }));
}

describe('Trust Console', () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(checkApiProcess).mockResolvedValue(false);
  });

  it('shows actual answer, returned rows, SQL, query ID and evidence', async () => {
    vi.mocked(submitQuestion).mockResolvedValue(success);
    render(<App />);
    enterQuestion('top balance');
    expect(await screen.findByText(success.answer)).toBeInTheDocument();
    expect(screen.getAllByText('query-123').length).toBeGreaterThan(0);
    expect(document.querySelector('.sql-code')?.textContent).toBe('SELECT C_CUSTKEY, C_ACCTBAL FROM CUSTOMER ORDER BY C_ACCTBAL DESC LIMIT 1');
    expect(screen.getAllByText('C_CUSTKEY').length).toBeGreaterThan(0);
    expect(screen.getByText('single_select')).toBeInTheDocument();
    expect(screen.getByText('row_count')).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenCalledWith('top balance');
  });

  it('shows clarification without implying SQL or execution', async () => {
    vi.mocked(submitQuestion).mockResolvedValue({
      answer: 'Which measure should define best?', sql: null, query_id: null,
      columns: [], rows: [], row_count: 0, assumptions: [], warnings: [],
      validation: { status: 'not_run', checks: [] }, execution: { status: 'not_run', checks: [] },
      verification: { status: 'not_run', checks: [] },
      clarification: { required: true, question: 'Which measure should define best?', options: [{ label: 'Highest balance' }] },
    });
    render(<App />);
    enterQuestion('best customers');
    expect((await screen.findAllByText('Which measure should define best?')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Highest balance').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/No SQL was executed/).length).toBeGreaterThan(0);
  });

  it('shows validation rejection and its warning', async () => {
    vi.mocked(submitQuestion).mockResolvedValue({ ...success, answer: 'The SQL proposal was rejected.', sql: 'DELETE FROM CUSTOMER', query_id: null, rows: [], row_count: 0, validation: { status: 'rejected', checks: [] }, execution: { status: 'not_run', checks: [] }, verification: { status: 'not_run', checks: [] }, warnings: ['Only approved SELECT queries are allowed.'] });
    render(<App />);
    enterQuestion('remove customers');
    expect(await screen.findByText('The SQL proposal was rejected.')).toBeInTheDocument();
    expect(screen.getAllByText('Only approved SELECT queries are allowed.').length).toBeGreaterThan(0);
    expect(screen.getByText(/SQL validation rejected the proposal before execution/)).toBeInTheDocument();
  });

  it('shows safe API errors and allows a retry', async () => {
    vi.mocked(submitQuestion).mockRejectedValueOnce(new Error('Cannot reach the DataMind API. Start the Python backend and try again.'));
    render(<App />);
    enterQuestion('count customers');
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the DataMind API.');
    vi.mocked(submitQuestion).mockResolvedValueOnce(success);
    fireEvent.click(screen.getByRole('button', { name: /Analyze data/i }));
    await waitFor(() => expect(screen.getByText(success.answer)).toBeInTheDocument());
  });

  it('keeps history in session and reviewing a result does not requery', async () => {
    vi.mocked(submitQuestion).mockResolvedValue(success);
    render(<App />);
    enterQuestion('top balance');
    await screen.findByText(success.answer);
    fireEvent.click(screen.getByRole('button', { name: /top balance/i }));
    await waitFor(() => expect(submitQuestion).toHaveBeenCalledTimes(1));
    expect(screen.getAllByText('query-123').length).toBeGreaterThan(0);
  });
});
