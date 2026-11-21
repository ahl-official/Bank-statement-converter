# Bank Statement Converter

Convert a bank statement to Tally voucher XML. Every Payment and Receipt uses the
bank ledger you enter and Suspense as the counterpart. Clear suspense in Tally.

1. Run `run_modern_app.bat` and open http://127.0.0.1:8000.
2. Enter the exact bank ledger name used in your Tally company.
3. Upload a PDF, Excel or CSV statement. Enter the PDF password if prompted.
4. Set From and To dates to limit the download, including both dates. Leave them
   blank for the full statement. Check the amounts and voucher direction, then select the rows to export.
5. Download `tally_import.xml`. In TallyPrime, use **Alt+O → Transactions** to import it.
   Both ledger names must exist in the company.

The supported layouts depend on the statement parser. Check the preview against
the statement, especially the first transaction of a PDF parsed from text. The
converter may need an Excel or CSV export for image-only statements.

`run_app.bat` starts the Streamlit interface for the same workflow.
