import type { View } from "@perspective-dev/client/inline";
import type { PluginStaticConfig } from "@perspective-dev/viewer";

export type NumberCardConfig = { unit?: string; locale?: string; decimals?: number };

// The engine owns aggregation and filtering. Never sum rows in the renderer.
export async function readNumberCard(view: View) {
  const config = await view.get_config();
  const columns: string[] = config.columns;
  if (columns.length !== 1 || config.split_by?.length) throw new Error("Number Card needs exactly one numeric column and no split_by.");
  const column = columns[0];
  const schema = await view.schema();
  if (!["integer", "float"].includes(schema[column])) throw new Error(`Number Card: ${column} must be numeric.`);
  const rows = await view.to_json({ start_row: 0, end_row: 2 });
  // Native grouped views expose a grand-total row as __ROW_PATH__ = [].
  // Use the root aggregate, not the first group or a JavaScript sum of groups.
  const total = config.group_by?.length ? rows.find(row => Array.isArray(row.__ROW_PATH__) && row.__ROW_PATH__.length === 0) : undefined;
  if (config.group_by?.length && rows.length && !total) throw new Error("Number Card requires the grand-total row from a rollup view.");
  if (rows.length > 1 && !total) throw new Error("Number Card needs a single value. Supply one summary row, or use group_by with an explicit aggregate to obtain the total.");
  const value = (total ?? rows[0])?.[column] ?? null;
  if (value !== null && (typeof value !== "number" || !Number.isFinite(value))) throw new Error("Number Card received a non-finite numeric value.");
  return { column, value: value as number | null, empty: rows.length === 0 };
}

export function registerNumberCard() {
  if (customElements.get("perspective-number-card")) return;
  const Base = customElements.get("perspective-viewer-plugin")!;
  class NumberCard extends Base {
    private config: NumberCardConfig = {};
    private data: Awaited<ReturnType<typeof readNumberCard>> | null = null;
    private label: HTMLElement;
    private value: HTMLElement;
    private unit: HTMLElement;
    private note: HTMLElement;

    constructor() {
      super();
      const shadow = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = `
        :host{display:block;width:100%;height:100%;box-sizing:border-box;color:inherit;font-family:inherit}
        .card{height:100%;box-sizing:border-box;padding:clamp(8px,3%,24px);display:flex;flex-direction:column;justify-content:center;align-items:center;gap:8px;text-align:center}
        .label,.unit,.note{font-size:14px;opacity:.7;overflow-wrap:anywhere;max-width:100%}
        .value{font-weight:650;line-height:1.1;font-variant-numeric:tabular-nums;max-width:100%;overflow-wrap:anywhere}
        .note:empty,.unit:empty{display:none}
      `;
      const card = document.createElement("div");
      card.className = "card";
      card.setAttribute("role", "group");
      const field = (name: string) => {
        const node = document.createElement("div");
        node.className = name;
        card.append(node);
        return node;
      };
      this.label = field("label");
      this.value = field("value");
      this.unit = field("unit");
      this.note = field("note");
      shadow.append(style, card);
    }

    get_static_config(): PluginStaticConfig {
      return { name: "Number Card", category: "Summary", select_mode: "select", min_config_columns: 1,
        config_column_names: ["Value"], max_columns: 1, group_rollup_modes: ["rollup"], split_rollup_modes: ["flat"],
        group_by_role: "Aggregate total", priority: 0 };
    }
    async draw(view: View) { this.data = await readNumberCard(view); this.paint(); }
    async update(view: View) { await this.draw(view); }
    async resize() { this.fit(); }
    restyle() { this.paint(); }
    save() { return { ...this.config }; }
    restore(config: NumberCardConfig | null = {}) {
      config ??= {};
      const decimals = config.decimals ?? 2;
      if (!Number.isInteger(decimals) || decimals < 0 || decimals > 10) throw new Error("Number Card decimals must be an integer from 0 to 10.");
      const locale = config.locale ?? "vi-VN";
      new Intl.NumberFormat(locale); // Validate imported/native config too.
      if (config.unit !== undefined && typeof config.unit !== "string") throw new Error("Number Card unit must be text.");
      this.config = { unit: config.unit ?? "", locale, decimals };
    }
    async clear() { this.data = null; this.paint(); }
    async delete() { this.data = null; this.shadowRoot?.replaceChildren(); }

    private paint() {
      this.label.textContent = this.data?.column ?? "";
      this.value.textContent = this.data?.value == null ? "—" : new Intl.NumberFormat(this.config.locale ?? "vi-VN", {
        maximumFractionDigits: this.config.decimals ?? 2,
      }).format(this.data.value);
      this.unit.textContent = this.config.unit ?? "";
      this.note.textContent = !this.data || this.data.empty ? "No data" : this.data.value === null ? "No value" : "";
      this.setAttribute("aria-label", `${this.label.textContent}: ${this.value.textContent} ${this.unit.textContent}`);
      this.fit();
    }
    private fit() {
      const length = this.value.textContent?.length || 1;
      this.value.style.fontSize = `${Math.max(10, Math.min(64, (this.clientWidth - 32) / (length * 0.65), this.clientHeight * 0.3))}px`;
    }
  }
  customElements.define("perspective-number-card", NumberCard);
  const Viewer = customElements.get("perspective-viewer") as CustomElementConstructor & { registerPlugin(name: string): void };
  Viewer.registerPlugin("perspective-number-card");
}
