import { z } from "zod";

const scalar = z.union([z.string(), z.number().finite(), z.boolean(), z.null()]);
export const filterSchema = z.tuple([z.string(), z.string(), z.union([scalar, z.array(scalar)])]);
const tableSchema = z.strictObject({
  name: z.string().min(1),
  schema: z.record(z.string(), z.enum(["string", "integer", "float", "boolean", "date", "datetime"])),
  rows: z.array(z.record(z.string(), scalar)).max(2000).describe("Verified query rows; numeric strings are converted using schema. Do not invent observations."),
  description: z.string().optional().describe("Data grain, units, query scope and truncation"),
});
const viewSchema = z.strictObject({
  plugin: z.string().describe("Exact installed plugin name from inspect_perspective"),
  columns: z.array(z.string().nullable()).min(1).describe("Column slots in the plugin's inspected order"),
  group_by: z.array(z.string()).optional(),
  split_by: z.array(z.string()).optional(),
  aggregates: z.record(z.string(), z.string()).optional(),
  sort: z.array(z.tuple([z.string(), z.enum(["asc", "desc", "asc abs", "desc abs", "col asc", "col desc"])])).optional(),
  filter: z.array(filterSchema).optional(),
  plugin_config: z.strictObject({
    unit: z.string().optional().describe("Verified unit label; do not infer currency"),
    locale: z.string().optional().describe("Number formatting locale; defaults to vi-VN"),
    decimals: z.number().int().min(0).max(10).optional(),
  }).optional().describe("Formatting options for Number Card only"),
});

export const perspectiveParameters = z.strictObject({
  title: z.string(),
  description: z.string().describe("Scope, grain, units, timezone and limitations. Filters operate on supplied rows, not a new database query."),
  table: tableSchema.describe("One typed query-result table"),
  view: viewSchema.describe("One native Perspective chart, grid or Number Card. No dashboard layout or tabs."),
  height: z.number().int().min(300).max(1000).optional().describe("Viewer height in pixels; defaults to 480"),
});
export type PerspectiveArgs = z.infer<typeof perspectiveParameters>;
export type RenderResult = { status: "ready"; plugin: string; filter_scope: "supplied_table" } | { status: "error"; error: string };

export function validateVisualization(args: PerspectiveArgs, plugins: string[]) {
  const { table, view } = args;
  if (!Object.keys(table.schema).length) throw new Error(`Table ${table.name} needs a schema.`);
  const fields = [...view.columns.filter((name): name is string => name !== null),
    ...(view.group_by ?? []), ...(view.split_by ?? []), ...Object.keys(view.aggregates ?? {}),
    ...(view.sort ?? []).map(([column]) => column), ...(view.filter ?? []).map(([column]) => column)];
  for (const row of table.rows) fields.push(...Object.keys(row));
  for (const field of fields) if (!(field in table.schema)) throw new Error(`Unknown field ${table.name}.${field}.`);
  if (!plugins.includes(view.plugin)) throw new Error(`Unavailable plugin ${view.plugin}. Use inspect_perspective.`);
  if (view.plugin_config && view.plugin !== "Number Card") throw new Error("plugin_config is currently supported only for Number Card.");
  if (view.plugin === "Number Card") {
    const column = view.columns[0];
    if (view.columns.length !== 1 || !column || !["integer", "float"].includes(table.schema[column]) || view.split_by?.length) {
      throw new Error("Number Card requires exactly one numeric column and no split_by.");
    }
    if (view.group_by?.length && !view.aggregates?.[column]) throw new Error(`Number Card requires an explicit aggregate for ${column}.`);
  }
}

export function normalizeRows(table: PerspectiveArgs["table"]) {
  return table.rows.map((row, index) => Object.fromEntries(Object.entries(table.schema).map(([column, type]) => {
    const value = row[column] ?? null;
    if (value === null) return [column, null];
    const fail = () => { throw new Error(`Table ${table.name}, row ${index + 1}: ${column} is not a valid ${type}.`); };
    if (type === "float" || type === "integer") {
      if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) return fail();
      const number = Number(value);
      if (!Number.isFinite(number) || (type === "integer" && !Number.isSafeInteger(number))) return fail();
      return [column, number];
    }
    if (type === "boolean") {
      if (typeof value !== "boolean") return fail();
      return [column, value];
    }
    if (type === "date" || type === "datetime") {
      if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return fail();
      return [column, new Date(value)];
    }
    if (typeof value !== "string") return fail();
    return [column, value];
  })));
}
