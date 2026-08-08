import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

function parseArgs(argv) {
  const positional = [];
  const flags = new Set();
  for (const value of argv) {
    if (value.startsWith("--")) flags.add(value);
    else positional.push(value);
  }
  if (positional.length !== 3) {
    throw new Error(
      "Usage: merge_short_summaries.mjs <input.xlsx> <short_summaries.json> <output.xlsx> [--replace] [--include-medium]",
    );
  }
  return {
    inputPath: path.resolve(positional[0]),
    summaryPath: path.resolve(positional[1]),
    outputPath: path.resolve(positional[2]),
    replace: flags.has("--replace"),
    includeMedium: flags.has("--include-medium"),
  };
}

function sidecarItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload.items)) return payload.items;
  if (Array.isArray(payload.rows)) return payload.rows;
  throw new Error("Summary sidecar must be an array or contain an items/rows array");
}

function normalizeConfidence(value) {
  return String(value ?? "").trim().toLowerCase();
}

const options = parseArgs(process.argv.slice(2));
if (options.inputPath.toLowerCase() === options.outputPath.toLowerCase()) {
  throw new Error("The output workbook must be a new file; overwriting the input workbook is forbidden");
}

const payload = JSON.parse(await fs.readFile(options.summaryPath, "utf8"));
const items = sidecarItems(payload);
const seenSidecarIds = new Set();
for (const item of items) {
  const docId = String(item.doc_id ?? "").trim();
  if (!docId) throw new Error("Every summary item must contain doc_id");
  if (seenSidecarIds.has(docId)) throw new Error(`Duplicate doc_id in sidecar: ${docId}`);
  seenSidecarIds.add(docId);
  if (!String(item.short_summary ?? "").trim()) {
    throw new Error(`Empty short_summary for ${docId}`);
  }
  if (!["high", "medium", "low"].includes(normalizeConfidence(item.confidence))) {
    throw new Error(`Invalid confidence for ${docId}: ${item.confidence}`);
  }
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(options.inputPath));
const sheet = workbook.worksheets.getItem("Документи");
const used = sheet.getUsedRange(true);
if (!used) throw new Error("The Документи sheet is empty");
const values = used.values;
const headers = values[0].map((value) => String(value ?? "").trim());
const idColumn = headers.indexOf("ID документа");
const targetAliases = ["Короткий зміст документа", "Короткий зміст документу", "Опис / пов’язана подія"];
const summaryColumn = headers.findIndex((header) => targetAliases.includes(header));
if (idColumn < 0) throw new Error("Column 'ID документа' was not found");
if (summaryColumn < 0) throw new Error(`Summary column was not found; accepted headers: ${targetAliases.join(", ")}`);

const rowByDocId = new Map();
for (let index = 1; index < values.length; index += 1) {
  const docId = String(values[index][idColumn] ?? "").trim();
  if (!docId) continue;
  if (rowByDocId.has(docId)) throw new Error(`Duplicate ID документа in workbook: ${docId}`);
  rowByDocId.set(docId, index);
}

const applied = [];
const skipped = [];
const unknown = [];
const columnValues = values.map((row) => [row[summaryColumn] ?? null]);
for (const item of items) {
  const docId = String(item.doc_id).trim();
  const confidence = normalizeConfidence(item.confidence);
  const rowIndex = rowByDocId.get(docId);
  if (rowIndex == null) {
    unknown.push(docId);
    continue;
  }
  if (confidence === "low" || (confidence === "medium" && !options.includeMedium)) {
    skipped.push({ doc_id: docId, reason: `confidence=${confidence}` });
    continue;
  }
  const current = String(columnValues[rowIndex][0] ?? "").trim();
  if (current && !options.replace) {
    skipped.push({ doc_id: docId, reason: "target cell is not empty" });
    continue;
  }
  columnValues[rowIndex][0] = String(item.short_summary).trim();
  applied.push(docId);
}

if (unknown.length) {
  throw new Error(`Sidecar contains unknown document IDs: ${unknown.join(", ")}`);
}

sheet.getRangeByIndexes(0, summaryColumn, columnValues.length, 1).values = columnValues;
const populatedSummaryRange = sheet.getRangeByIndexes(1, summaryColumn, Math.max(columnValues.length - 1, 1), 1);
populatedSummaryRange.format.wrapText = true;
populatedSummaryRange.format.autofitRows();
for (let rowIndex = 1; rowIndex < columnValues.length; rowIndex += 1) {
  const rowRange = sheet.getRangeByIndexes(rowIndex, 0, 1, headers.length);
  if (rowRange.format.rowHeightPx > 96) rowRange.format.rowHeightPx = 96;
}
await fs.mkdir(path.dirname(options.outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(options.outputPath);

const verification = await workbook.inspect({
  kind: "table",
  range: `Документи!A1:X${Math.min(values.length, 60)}`,
  include: "values,formulas",
  tableMaxRows: Math.min(values.length, 60),
  tableMaxCols: 24,
  maxChars: 12000,
});
console.log(
  JSON.stringify({
    output: options.outputPath,
    summary_header: headers[summaryColumn],
    applied,
    skipped,
    inspected: Boolean(verification.ndjson),
  }),
);
