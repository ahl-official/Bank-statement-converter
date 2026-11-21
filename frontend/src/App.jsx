import { useState, useEffect } from 'react';
import { Download, FileText, Upload } from 'lucide-react';

const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR' });
const field = 'mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5';
const primary = 'inline-flex items-center justify-center gap-2 rounded-lg bg-teal-300 px-4 py-2.5 font-semibold text-slate-950 hover:bg-teal-200 disabled:opacity-50';

const COMPANY_BANKS = {
  'HAIRLINE SOLUTIONS': ['HDFC BANK'],
  'AESTHETIQUE SOLUTION': ['HDFC BANK'],
  'HAIR ALIVE': ['HDFC BANK'],
  'HAIR LOSS SOLUTION': ['HDFC BANK'],
  'TRICHO HAIR': ['HDFC BANK'],
  'AHL': [
    'HDFC BANK',
    'Central Bank (Saving A/c)',
    'Bank of Baroda (Saving A/c)',
  ],
  'HOUSE OF AESTHETICS': [
    'HDFC Bank (96996)',
    'HDFC Bank (5801) AHL 2',
    'HDFC BANK (2236-SAVING)',
  ],
};

async function responseError(response) {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  const error = new Error(detail?.message || (typeof detail === 'string' ? detail : 'The request failed. Try again.'));
  error.code = detail?.code;
  return error;
}

export default function App() {
  const [selectedCompany, setSelectedCompany] = useState('HAIRLINE SOLUTIONS');
  const [bankLedger, setBankLedger] = useState('HDFC BANK');
  const [customBank, setCustomBank] = useState('');
  const [isCustom, setIsCustom] = useState(false);
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState('');
  const [needsPassword, setNeedsPassword] = useState(false);
  const [rows, setRows] = useState([]);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [statementOpening, setStatementOpening] = useState(null);
  const [statementClosing, setStatementClosing] = useState(null);
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isInstalled, setIsInstalled] = useState(false);

  useEffect(() => {
    const handler = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };
    window.addEventListener('beforeinstallprompt', handler);

    if (window.matchMedia('(display-mode: standalone)').matches) {
      setIsInstalled(true);
    }

    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  async function installApp() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === 'accepted') {
        setIsInstalled(true);
      }
      setDeferredPrompt(null);
    } else {
      alert("To install on Windows (Chrome or Edge):\nClick the 'Install App' icon (small monitor with a down arrow) in your browser's address bar!\n\nOn Mobile (Android/iOS):\nTap your browser menu (⋮ or Share) → 'Add to Home screen'.");
    }
  }

  const invalidRange = Boolean(fromDate && toDate && fromDate > toDate);
  const inDateRange = (row) =>
    (!fromDate || (row.calendar_date && row.calendar_date >= fromDate)) &&
    (!toDate || (row.calendar_date && row.calendar_date <= toDate));
  const visible = invalidRange ? [] : rows.filter(inDateRange);
  const selected = visible.filter((row) => row.selected);
  const total = (type) => selected.reduce((sum, row) => sum + (row.voucher_type === type ? row.amount : 0), 0);

  const currentOpening = (() => {
    if (!visible.length) return null;
    if (!fromDate && statementOpening != null) return statementOpening;
    const firstRow = visible[0];
    if (firstRow.balance != null) {
      return firstRow.voucher_type === 'Receipt'
        ? firstRow.balance - firstRow.amount
        : firstRow.balance + firstRow.amount;
    }
    return statementOpening;
  })();

  const currentClosing = (() => {
    if (!visible.length) return null;
    if (!toDate && statementClosing != null) return statementClosing;
    const lastRow = visible[visible.length - 1];
    if (lastRow.balance != null) {
      return lastRow.balance;
    }
    return statementClosing;
  })();

  function handleCompanyChange(comp) {
    setSelectedCompany(comp);
    setIsCustom(false);
    setCustomBank('');
    const banks = COMPANY_BANKS[comp] || [];
    if (banks.length > 0) {
      setBankLedger(banks[0]);
    } else {
      setBankLedger('');
    }
  }

  function handleBankChange(val) {
    if (val === '__custom__') {
      setIsCustom(true);
      setBankLedger(customBank || '');
    } else {
      setIsCustom(false);
      setBankLedger(val);
    }
  }

  async function upload(statement, pdfPassword = '') {
    if (!statement || busy) return;
    setFile(statement);
    setRows([]);
    setStatementOpening(null);
    setStatementClosing(null);
    setFromDate('');
    setToDate('');
    setError('');
    setMessage('');
    setNeedsPassword(false);
    setPassword('');
    setBusy('upload');
    const form = new FormData();
    form.append('file', statement);
    form.append('password', pdfPassword);
    try {
      const response = await fetch('/api/parse-statement', { method: 'POST', body: form });
      if (!response.ok) throw await responseError(response);
      const data = await response.json();
      if (!Array.isArray(data.transactions) || !data.transactions.length) {
        throw new Error('No transactions found. Check that this is a supported statement with readable text.');
      }
      setRows(data.transactions);
      setStatementOpening(data.opening_balance ?? null);
      setStatementClosing(data.closing_balance ?? null);
    } catch (cause) {
      setNeedsPassword(cause.code === 'pdf_password_required');
      setError(cause.message);
    } finally {
      setBusy('');
    }
  }

  function updateRow(id, changes) {
    setRows((current) => current.map((row) => row.id === id ? { ...row, ...changes } : row));
    setMessage('');
  }

  async function download() {
    if (!selected.length || !bankLedger.trim() || busy) return;
    setBusy('download');
    setError('');
    setMessage('');
    try {
      const response = await fetch('/api/generate-xml', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bank_ledger_name: bankLedger.trim(),
          company_name: selectedCompany,
          date_from: fromDate || null,
          date_to: toDate || null,
          vouchers: selected.map((row) => ({
            voucher_type: row.voucher_type,
            date: row.date,
            amount: row.amount,
            narration: row.original_narration,
            instrument_no: row.instrument_no,
          })),
        }),
      });
      if (!response.ok) throw await responseError(response);
      if (!response.headers.get('content-type')?.includes('xml')) {
        throw new Error('The converter did not return an XML file.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = 'tally_import.xml';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setMessage('Downloaded ' + selected.length + ' vouchers. In TallyPrime, use Alt+O → Transactions to import the XML.');
    } catch (cause) {
      setError(cause.message);
    } finally {
      setBusy('');
    }
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-5 py-10 md:px-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <FileText className="text-teal-300" size={24} />
            <h1 className="text-2xl font-semibold md:text-3xl">Bank Statement Converter</h1>
          </div>
          <p className="text-slate-400 text-sm">Convert bank statements to zero-suspense TallyPrime XML vouchers.</p>
        </div>
        {!isInstalled && (
          <button
            onClick={installApp}
            className="inline-flex items-center gap-2 rounded-lg border border-teal-500/40 bg-teal-500/10 px-3.5 py-2 text-sm font-medium text-teal-300 hover:bg-teal-500/20 transition cursor-pointer"
            title="Install as desktop application"
          >
            <Download size={16} />
            <span>Install App</span>
          </button>
        )}
      </header>

      <section className="grid gap-5 rounded-xl border border-slate-800 bg-slate-900 p-5 md:grid-cols-3">
        <label className="font-medium text-slate-200">
          <span>Company Name</span>
          <span className="block text-xs font-normal text-slate-400 mt-0.5">Select company in Tally</span>
          <select
            className={field + ' cursor-pointer text-slate-100'}
            value={selectedCompany}
            onChange={(e) => handleCompanyChange(e.target.value)}
          >
            {Object.keys(COMPANY_BANKS).map((comp) => (
              <option key={comp} value={comp} className="bg-slate-950 text-slate-100">
                {comp}
              </option>
            ))}
          </select>
        </label>

        <label className="font-medium text-slate-200">
          <span>Bank Ledger Name</span>
          <span className="block text-xs font-normal text-slate-400 mt-0.5">
            {(COMPANY_BANKS[selectedCompany] || []).length > 1
              ? `${(COMPANY_BANKS[selectedCompany] || []).length} banks available`
              : 'Auto-selected for this company'}
          </span>
          <select
            className={field + ' cursor-pointer text-slate-100'}
            value={isCustom ? '__custom__' : bankLedger}
            onChange={(e) => handleBankChange(e.target.value)}
          >
            {(COMPANY_BANKS[selectedCompany] || []).map((bank) => (
              <option key={bank} value={bank} className="bg-slate-950 text-slate-100">
                {bank}
              </option>
            ))}
            <option value="__custom__" className="bg-slate-950 text-slate-400">
              + Other (Type manual ledger)
            </option>
          </select>
          {isCustom && (
            <input
              type="text"
              placeholder="Type exact bank ledger name in Tally"
              className={field + ' mt-2 text-slate-100'}
              value={customBank}
              onChange={(e) => {
                setCustomBank(e.target.value);
                setBankLedger(e.target.value);
              }}
              autoFocus
            />
          )}
        </label>

        <div>
          <p className="font-medium text-slate-200">Counterpart Ledger</p>
          <p className="text-xs text-slate-400 mt-0.5">Assigned for transactions</p>
          <p className={field + ' text-slate-400 select-none'}>Suspense</p>
        </div>
      </section>

      <section
        className="space-y-3 rounded-xl border border-dashed border-slate-700 bg-slate-900/50 p-6 text-center"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => { event.preventDefault(); upload(event.dataTransfer.files[0]); }}
      >
        <label className={primary + ' cursor-pointer focus-within:outline-2 focus-within:outline-offset-4'}>
          <Upload size={17} />
          {busy === 'upload' ? 'Reading statement…' : 'Choose bank statement'}
          <input className="sr-only" type="file" accept=".pdf,.xlsx,.xls,.csv" disabled={Boolean(busy)}
            onChange={(event) => { upload(event.target.files[0]); event.target.value = ''; }} />
        </label>
        <p className="break-all text-slate-400">{file ? file.name : 'Drop a PDF, Excel or CSV file here'}</p>
        {needsPassword && (
          <form className="mx-auto flex max-w-md items-end gap-2" onSubmit={(event) => { event.preventDefault(); upload(file, password); }}>
            <label className="flex-1 text-left">PDF password
              <input className={field} type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </label>
            <button className={primary} type="submit">Unlock</button>
          </form>
        )}
      </section>

      {error && <p role="alert" className="rounded-lg border border-red-900 bg-red-950/50 p-3 text-red-200">{error}</p>}
      {rows.length > 0 && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">Review transactions</h2>
            <button className={primary} onClick={download} disabled={Boolean(busy) || !selected.length || !bankLedger.trim()}>
              <Download size={17} /> {busy === 'download' ? 'Generating…' : 'Download Tally XML'}
            </button>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium text-slate-200">
              From date
              <input className={field} type="date" value={fromDate}
                onChange={(event) => { setFromDate(event.target.value); setMessage(''); }} />
            </label>
            <label className="text-sm font-medium text-slate-200">
              To date
              <input className={field} type="date" value={toDate}
                onChange={(event) => { setToDate(event.target.value); setMessage(''); }} />
            </label>
            {(fromDate || toDate) && (
              <button className="rounded-lg border border-slate-700 px-4 py-2.5 text-sm hover:bg-slate-800 transition" type="button"
                onClick={() => { setFromDate(''); setToDate(''); setMessage(''); }}>Clear dates</button>
            )}
          </div>

          {(currentOpening != null || currentClosing != null) && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-xl border border-slate-800 bg-slate-900/80 p-4">
              <div className="space-y-1">
                <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Opening Balance</span>
                <p className="text-xl font-semibold text-slate-100 tabular-nums">
                  {currentOpening != null ? money.format(currentOpening) : '—'}
                </p>
                <p className="text-xs text-slate-500">
                  {fromDate ? `As of ${fromDate}` : 'Statement Start'}
                </p>
              </div>

              <div className="space-y-1">
                <span className="text-xs font-medium uppercase tracking-wider text-emerald-400">Total Receipts (+)</span>
                <p className="text-xl font-semibold text-emerald-300 tabular-nums">
                  +{money.format(total('Receipt'))}
                </p>
                <p className="text-xs text-slate-500">
                  {selected.filter((r) => r.voucher_type === 'Receipt').length} deposit{selected.filter((r) => r.voucher_type === 'Receipt').length === 1 ? '' : 's'}
                </p>
              </div>

              <div className="space-y-1">
                <span className="text-xs font-medium uppercase tracking-wider text-rose-400">Total Payments (-)</span>
                <p className="text-xl font-semibold text-rose-300 tabular-nums">
                  -{money.format(total('Payment'))}
                </p>
                <p className="text-xs text-slate-500">
                  {selected.filter((r) => r.voucher_type === 'Payment').length} withdrawal{selected.filter((r) => r.voucher_type === 'Payment').length === 1 ? '' : 's'}
                </p>
              </div>

              <div className="space-y-1">
                <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Closing Balance</span>
                <p className="text-xl font-semibold text-slate-100 tabular-nums">
                  {currentClosing != null ? money.format(currentClosing) : '—'}
                </p>
                <p className="text-xs text-slate-500">
                  {toDate ? `As of ${toDate}` : 'Statement End'}
                </p>
              </div>
            </div>
          )}
          {invalidRange && <p role="alert" className="text-red-200">From date must be on or before To date.</p>}
          {!invalidRange && visible.length === 0 && <p role="status" className="text-slate-400">No transactions in the selected dates.</p>}
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-slate-400 tabular-nums">
            <span>{selected.length} of {visible.length} in range selected</span>
            <span>Payments {money.format(total('Payment'))}</span>
            <span>Receipts {money.format(total('Receipt'))}</span>
          </div>
          {message && <p role="status" className="text-teal-200">{message}</p>}
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full min-w-[620px] text-left">
              <thead className="bg-slate-900 text-slate-300">
                <tr>
                  <th className="p-3"><input type="checkbox" aria-label="Select all vouchers in date range"
                    disabled={!visible.length} checked={visible.length > 0 && selected.length === visible.length}
                    onChange={(event) => {
                      const checked = event.target.checked;
                      setRows((current) => current.map((row) => inDateRange(row) ? { ...row, selected: checked } : row));
                      setMessage('');
                    }} /></th>
                  <th className="p-3">Date</th><th className="p-3">Narration</th><th className="p-3">Voucher type</th><th className="p-3 text-right">Amount</th><th className="p-3 text-right">Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {visible.map((row) => (
                  <tr key={row.id}>
                    <td className="p-3"><input type="checkbox" aria-label={'Include voucher ' + row.id} checked={row.selected}
                      onChange={(event) => updateRow(row.id, { selected: event.target.checked })} /></td>
                    <td className="whitespace-nowrap p-3">{row.date}</td>
                    <td className="p-3">{row.original_narration}</td>
                    <td className="p-3">
                      <select aria-label={'Voucher type for ' + row.id} className="rounded border border-slate-700 bg-slate-950 p-1.5"
                        value={row.voucher_type} onChange={(event) => updateRow(row.id, { voucher_type: event.target.value })}>
                        <option>Payment</option><option>Receipt</option>
                      </select>
                    </td>
                    <td className="whitespace-nowrap p-3 text-right tabular-nums">{money.format(row.amount)}</td>
                    <td className="whitespace-nowrap p-3 text-right tabular-nums text-slate-400">{row.balance != null ? money.format(row.balance) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}
