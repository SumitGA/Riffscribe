// Copies the score viewer's files out of @coderline/alphatab into assets/viewer/ (git-ignored),
// so the app bundles them and renders offline. Runs on `npm install` (postinstall).
// The JS goes in as .txt: Metro must ship it as a file for the WebView, not bundle it as code.
const fs = require('fs');
const path = require('path');

// The package's main entry is dist/alphaTab.js; its exports map hides the other dist files.
const dist = path.dirname(require.resolve('@coderline/alphatab'));
const out = path.join(__dirname, '..', 'assets', 'viewer');
const files = {
  'alphaTab.min.js': 'alphaTab.txt',
  'font/Bravura.woff2': 'Bravura.woff2',
  'soundfont/sonivox.sf2': 'sonivox.sf2',
};

fs.mkdirSync(out, { recursive: true });
for (const [from, to] of Object.entries(files)) {
  fs.copyFileSync(path.join(dist, from), path.join(out, to));
}
console.log(`score viewer assets copied to ${path.relative(process.cwd(), out)}`);
