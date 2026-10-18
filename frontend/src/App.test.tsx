import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { checkApiProcess, getDatasetCatalog, submitQuestion } from './lib/api';
import type { QueryResponse } from './types/api';

vi.mock('./lib/api', () => ({
  checkApiProcess: vi.fn().mockResolvedValue(false),
  getDatasetCatalog: vi.fn().mockResolvedValue({ default_dataset_id: 'tpch_customer', datasets: [
    { id: 'tpch_customer', name: 'TPC-H Customers', description: 'Snowflake sample customer table.', availability: 'requires_snowflake_credentials', fields: { C_CUSTKEY: { type: 'integer' } }, default: true },
    { id: 'electricity_mix', name: 'Electricity Generation and Energy Mix', description: 'OWID renewable generation.', availability: 'requires_snowflake_credentials', fields: { RENEWABLES_TWH: { type: 'number', unit: 'TWh' } } },
  ] }),
  submitQuestion: vi.fn(),
}));

const success: QueryResponse = {
  answer: 'Customer 42 has the highest returned balance: 950.',
  sql: 'SELECT C_CUSTKEY, C_ACCTBAL FROM CUSTOMER ORDER BY C_ACCTBAL DESC LIMIT 1',
  sql_parameters: ['BUILDING'],
  columns: ['C_CUSTKEY', 'C_ACCTBAL'], rows: [[42, 950]], row_count: 1,
  query_id: 'query-123', assumptions: [], warnings: [],
  validation: { status: 'passed', checks: [{ name: 'single_select', status: 'passed' }] },
  query_plan: { version: 1, status: 'query', dimensions: ['C_CUSTKEY'] },
  plan_validation: { status: 'passed', checks: [{ name: 'plan_schema', status: 'passed' }] },
  outcome: 'success',
  execution: { status: 'succeeded', checks: [] },
  verification: { status: 'passed', checks: [{ name: 'row_count', status: 'passed' }] },
  clarification: { required: false },
};

const clarification: QueryResponse = {
  answer: 'How should I define best? Choose a supported ranking.', sql: null,
  columns: [], rows: [], row_count: 0, query_id: null, assumptions: [], warnings: [],
  validation: { status: 'not_run', checks: [] },
  execution: { status: 'not_run', checks: [] },
  verification: { status: 'not_run', checks: [] },
  outcome: 'clarification',
  clarification: { required: true, question: 'How should I define best?', options: [
    { label: 'Highest account balance', column: 'C_ACCTBAL', direction: 'DESC' },
    { label: 'Customer name A–Z', column: 'C_NAME', direction: 'ASC' },
    { label: 'Customer key ascending', column: 'C_CUSTKEY', direction: 'ASC' },
  ] },
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
    vi.mocked(getDatasetCatalog).mockResolvedValue({ default_dataset_id: 'tpch_customer', datasets: [
      { id: 'tpch_customer', name: 'TPC-H Customers', description: 'Snowflake sample customer table.', availability: 'requires_snowflake_credentials', fields: { C_CUSTKEY: { type: 'integer' } }, default: true },
      { id: 'electricity_mix', name: 'Electricity Generation and Energy Mix', description: 'OWID renewable generation.', availability: 'requires_snowflake_credentials', fields: { RENEWABLES_TWH: { type: 'number', unit: 'TWh' } } },
    ] });
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
    expect(screen.getByText('plan_schema')).toBeInTheDocument();
    expect(screen.getByText('Inspect typed query plan')).toBeInTheDocument();
    expect(screen.getByText('?1 = BUILDING')).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenCalledWith('top balance', 'tpch_customer');
  });

  it('shows clarification without implying SQL or execution', async () => {
    vi.mocked(submitQuestion).mockResolvedValue(clarification);
    render(<App />);
    enterQuestion('best customers');
    expect((await screen.findAllByText('How should I define best?')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Highest account balance' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Customer name A–Z' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Customer key ascending' })).toBeInTheDocument();
    expect(screen.getAllByText('Not run').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/No SQL was executed/).length).toBeGreaterThan(0);
    expect(screen.queryByText('Execution succeeded')).not.toBeInTheDocument();
  });

  it.each([
    ['Highest account balance', 'C_ACCTBAL', 'DESC', 'Show the five customers with the highest account balances.'],
    ['Customer name A–Z', 'C_NAME', 'ASC', 'Show the five customers ordered by customer name A–Z.'],
    ['Customer key ascending', 'C_CUSTKEY', 'ASC', 'Show the five customers ordered by customer key ascending.'],
  ])('submits clarification option %s once through the query API', async (label, _column, _direction, clarifiedQuestion) => {
    vi.mocked(submitQuestion).mockResolvedValueOnce(clarification).mockResolvedValueOnce({
      ...success, answer: `API result for ${label}.`, query_id: `query-${label}`,
      execution: { status: 'succeeded', checks: [] }, outcome: 'success',
    });
    render(<App />);
    enterQuestion('Who are the best customers?');
    await screen.findByRole('button', { name: label });
    fireEvent.click(screen.getByRole('button', { name: label }));

    expect(screen.getByRole('textbox', { name: 'Ask your data' })).toHaveValue(clarifiedQuestion);
    await waitFor(() => expect(submitQuestion).toHaveBeenCalledTimes(2));
    expect(submitQuestion).toHaveBeenNthCalledWith(1, 'Who are the best customers?', 'tpch_customer');
    expect(submitQuestion).toHaveBeenNthCalledWith(2, clarifiedQuestion, 'tpch_customer');
    expect(await screen.findByText(`API result for ${label}.`)).toBeInTheDocument();
    expect(screen.getAllByText(`query-${label}`).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Succeeded').length).toBeGreaterThan(0);
    expect(screen.queryByText('How should I define best?')).not.toBeInTheDocument();
    expect(screen.getAllByText(clarifiedQuestion).length).toBeGreaterThan(0);
  });

  it('uses native keyboard-operable buttons and disables all options while submitting', async () => {
    let resolveQuery!: (value: QueryResponse) => void;
    vi.mocked(submitQuestion).mockResolvedValueOnce(clarification).mockReturnValueOnce(new Promise(resolve => { resolveQuery = resolve; }));
    render(<App />);
    enterQuestion('Who are the best customers?');
    const first = await screen.findByRole('button', { name: 'Highest account balance' });
    expect(first.tagName).toBe('BUTTON');
    expect(first.tabIndex).toBe(0);
    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.click(first);
    fireEvent.click(first);
    expect(await screen.findByRole('button', { name: /Submitting Highest account balance/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Customer name A–Z' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Customer key ascending' })).toBeDisabled();
    expect(submitQuestion).toHaveBeenCalledTimes(2);
    resolveQuery(success);
    await screen.findByText(success.answer);
  });

  it('disables clarification choices it cannot map to a supported customer plan', async () => {
    vi.mocked(submitQuestion).mockResolvedValueOnce({
      ...clarification,
      clarification: { required: true, question: 'Choose a supported order.', options: [
        { label: 'Highest account balance', column: 'C_NAME', direction: 'DROP TABLE' },
      ] },
    });
    render(<App />);
    enterQuestion('Who are the best customers?');
    const unsafe = await screen.findByRole('button', { name: 'Highest account balance' });
    expect(unsafe).toBeDisabled();
    expect(screen.getByText(/cannot be safely mapped to a supported customer query/i)).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenCalledTimes(1);
  });

  it('keeps clarification available after an option request fails and permits retry', async () => {
    const clarifiedQuestion = 'Show the five customers with the highest account balances.';
    vi.mocked(submitQuestion).mockResolvedValueOnce(clarification)
      .mockRejectedValueOnce(new Error('Snowflake is unavailable. Retry this question.'))
      .mockResolvedValueOnce({ ...success, answer: 'Retry returned the real API answer.' });
    render(<App />);
    enterQuestion('Who are the best customers?');
    fireEvent.click(await screen.findByRole('button', { name: 'Highest account balance' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Snowflake is unavailable. Retry this question.');
    expect(screen.getByRole('button', { name: 'Highest account balance' })).toBeEnabled();
    expect(screen.getByRole('textbox', { name: 'Ask your data' })).toHaveValue(clarifiedQuestion);

    fireEvent.click(screen.getByRole('button', { name: 'Highest account balance' }));
    expect(await screen.findByText('Retry returned the real API answer.')).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenNthCalledWith(2, clarifiedQuestion, 'tpch_customer');
    expect(submitQuestion).toHaveBeenNthCalledWith(3, clarifiedQuestion, 'tpch_customer');
  });

  it('keeps a prior successful result visible when a later request fails', async () => {
    vi.mocked(submitQuestion).mockResolvedValueOnce(success).mockRejectedValueOnce(new Error('Temporary backend failure. Retry the query.'));
    render(<App />);
    enterQuestion('first question');
    expect(await screen.findByText(success.answer)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask your data' }), { target: { value: 'second question' } });
    fireEvent.click(screen.getByRole('button', { name: /Analyze data/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Temporary backend failure. Retry the query.');
    expect(screen.getByText(success.answer)).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenCalledTimes(2);
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

  it('shows the catalog failure reason instead of a generic unavailable label', async () => {
    vi.mocked(getDatasetCatalog).mockRejectedValueOnce(new Error('Dataset catalog was not found at http://127.0.0.1:8000/api/datasets. The frontend is calling an older DataMind API.'));
    render(<App />);
    expect(await screen.findByText(/calling an older DataMind API/)).toBeInTheDocument();
    expect(screen.queryByText('Dataset catalog unavailable')).not.toBeInTheDocument();
  });

  it('sends the selected electricity dataset and displays Snowflake execution evidence', async () => {
    vi.mocked(submitQuestion).mockResolvedValue({
      answer: 'Snowflake returned 1 row: ENTITY=India, YEAR=2024, RENEWABLES_TWH=403.39.',
      dataset_id: 'electricity_mix', plan_source: 'ollama', sql: 'SELECT ENTITY, YEAR, RENEWABLES_TWH FROM DATAMIND_DB.ANALYTICS.ELECTRICITY_MIX LIMIT 1',
      columns: ['ENTITY', 'YEAR', 'RENEWABLES_TWH'], rows: [['India', 2024, 403.39]], row_count: 1,
      query_id: 'electricity-snowflake-query-123', assumptions: [], warnings: [], outcome: 'success',
      validation: { status: 'passed', checks: [] }, execution: { status: 'succeeded', engine: 'Snowflake' },
      verification: { status: 'passed', checks: [] },
    });
    render(<App />);
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'electricity_mix' } });
    expect(await screen.findByText(/access to DATAMIND_DB\.ANALYTICS\.ELECTRICITY_MIX/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask your data' }), { target: { value: 'renewables India 2024' } });
    fireEvent.click(screen.getByRole('button', { name: /Analyze data/i }));

    expect(await screen.findByText(/Snowflake returned 1 row/)).toBeInTheDocument();
    expect(submitQuestion).toHaveBeenCalledWith('renewables India 2024', 'electricity_mix');
    expect(screen.getAllByText('electricity-snowflake-query-123').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Snowflake execution').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Dataset capability match').length).toBeGreaterThan(0);
    expect(screen.queryByText(/Local SQLite/)).not.toBeInTheDocument();
    expect(screen.getByText(/Plan source: ollama/)).toBeInTheDocument();
    expect(screen.getByText('403.39')).toBeInTheDocument();
  });
});
