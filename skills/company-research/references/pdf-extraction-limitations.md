# PDF Financial Report Extraction — Limitations and Workarounds

## Problem

When researching company financial reports via `web_extract`, PDF files often
return only partial content (e.g. 2,063 chars from a multi-page interim
financial report). This is insufficient for capturing complete financial
figures like revenue, EBIT, and net profit for the full reporting period.

## Observed Behavior

- PDF URLs passed to `web_extract` may return only the first page, metadata,
  or a truncated head+tail window
- Detailed financial tables (income statement, balance sheet) are frequently
  in later pages or formatted in ways that don't extract cleanly
- Key figures for the reporting period are often missing from the extracted
  text even when the PDF is the official source

## Workarounds (in order of effectiveness)

1. **Find the HTML press release** — Companies frequently publish press releases
   with headline figures (revenue, profit, EPS) in HTML that extracts fully.
   Search for `"<company> <period> results press release"` or check the
   investor relations / press releases page.

2. **Find news coverage** — Financial news sites ( Investing.com, Bloomberg,
   Reuters, local business press) often summarize key figures in article text.
   Search for `"<company> Q2 2026 results"` or `"<company> profit surges"`.

3. **Check investor relations pages** — Some companies provide HTML versions of
   reports or interactive data tables that extract better than PDFs.

4. **Combine multiple sources** — When the primary PDF is incomplete, triangulate
   using press release + news + analyst estimates. Note which figures come from
   which source.

5. **Extract specific pages** — If `web_extract` supports it, try extracting
   specific pages of a PDF rather than the whole document. (Tool-dependent.)

## When to Stop

After 3–4 extraction attempts across different sources, if the key headline
figures (revenue, EBIT/EBITDAR, net profit for the reporting period) remain
unavailable, stop and note the gap explicitly. Partial data (prior-year
comparables, Q1 figures, segment commentary) is still useful context — record
what you have with source annotations, and flag what's missing.

Do NOT guess financial figures. A partial extract with explicit gaps is better
than fabricated numbers.

## Reporting Format

In the dated report file (`reports/YYYY-MM-DD.md`), structure findings as:

- **Figures available** — with source URL for each
- **Figures missing** — explicit note that the primary source PDF did not yield
  these figures despite attempts
- **Context available** — prior period comparables, segment data, commentary
  that DID extract

This makes it clear to future readers what is verified vs. unknown.
