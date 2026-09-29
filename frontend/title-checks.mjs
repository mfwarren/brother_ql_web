import assert from 'node:assert/strict';
import { labelTitle } from './src/api.ts';
assert.equal(labelTitle({ kind: 'text', text: '  Hard drives\nArchive 2026' }), 'Hard drives');
assert.equal(labelTitle({ kind: 'qr', code: 'https://www.example.com/help?token=private', caption: '' }), 'example.com/help');
assert.equal(labelTitle({ kind: 'qr', code: 'ASSET-0042', caption: 'Router' }), 'Router');
assert.equal(labelTitle({ kind: 'image', image: { name: 'shipping-mark.png', mime: 'image/png', base64: '' }, caption: '', mode: 'bw', fit: true }), 'shipping-mark');
assert.equal(labelTitle({ kind: 'text', text: '' }), 'Text label');
console.log('5 smart-title checks passed');
