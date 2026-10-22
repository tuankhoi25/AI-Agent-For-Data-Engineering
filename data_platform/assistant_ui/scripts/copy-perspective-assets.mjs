import { mkdir, copyFile, readFile } from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const version = JSON.parse(await readFile(path.join(root, 'node_modules/@perspective-dev/viewer/package.json'), 'utf8')).version;
const directory = path.join(root, 'public/perspective', version);
await mkdir(directory, { recursive: true });
for (const [source, target] of [
  ['@perspective-dev/client/dist/cdn/perspective.js', 'perspective.js'],
  ['@perspective-dev/viewer/dist/cdn/perspective-viewer.js', 'viewer/dist/cdn/perspective-viewer.js'],
  ['@perspective-dev/viewer-datagrid/dist/cdn/perspective-viewer-datagrid.js', 'perspective-viewer-datagrid.js'],
  ['@perspective-dev/viewer-charts/dist/cdn/perspective-viewer-charts.js', 'perspective-viewer-charts.js'],
  ['@perspective-dev/client/dist/wasm/perspective-js.wasm', 'client.wasm'],
  ['@perspective-dev/server/dist/wasm/perspective-server.wasm', 'server.wasm'],
  ['@perspective-dev/viewer/dist/wasm/perspective-viewer.wasm', 'viewer/dist/wasm/perspective-viewer.wasm'],
]) {
  await mkdir(path.dirname(path.join(directory, target)), { recursive: true });
  await copyFile(path.join(root, 'node_modules', source), path.join(directory, target));
}
console.log(`Prepared local Perspective ${version} WebAssembly assets.`);
