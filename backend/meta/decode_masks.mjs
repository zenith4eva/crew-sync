// Decodes raw SAM 3.1 video output_text into JSON lines, one per (frame, object).
// Masks are arithmetic-coded, so we use Meta's official parser instead of porting it.
// Usage: node decode_masks.mjs <raw.txt> <out.jsonl>
import { readFileSync, writeFileSync } from 'node:fs';
import { decodeMaskToRaster, frameIndexOf, parseVideoStream, recordsOfKind } from '@meta-sam/parser';

const [rawPath, outPath] = process.argv.slice(2);
const text = readFileSync(rawPath, 'utf8');
const lane = { item_id: 'raw', output_index: 0, content_index: 0 };

async function* events() {
  yield { type: 'response.output_text.delta', ...lane, delta: text };
  yield { type: 'response.output_text.done', ...lane, text };
  yield { type: 'response.completed' };
}

const parsed = parseVideoStream(events());
for await (const _ of parsed);
const result = await parsed.finalResult;
for (const d of result.diagnostics) console.error(`${d.code} line ${d.line}: ${d.message}`);

const lines = [];
for (const rec of recordsOfKind(result.records, 'mask')) {
  const raster = decodeMaskToRaster(rec.mask);
  const packed = new Uint8Array(Math.ceil(raster.length / 8));
  for (let i = 0; i < raster.length; i += 1) if (raster[i]) packed[i >> 3] |= 0x80 >> (i & 7);
  const { left, top, right, bottom } = rec.bounds;
  lines.push(JSON.stringify({
    f: frameIndexOf(rec), id: rec.objectId,
    box: [left, top, right, bottom], h: rec.mask.height, w: rec.mask.width,
    bits: Buffer.from(packed).toString('base64'),
  }));
}
writeFileSync(outPath, lines.join('\n') + '\n');
