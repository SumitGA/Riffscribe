// Writes src/about/licenses.json: the open-source notices the Acknowledgements screen shows
// (TD-28). Every package the app ships (npm production dependencies) plus the bundled assets
// that aren't npm packages. Licence texts are stored once and shared: copyright lines differ,
// the permission text usually doesn't.
// `node scripts/licenses.js` regenerates it; `--check` fails if it's out of date (CI).
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const out = path.join(root, 'src', 'about', 'licenses.json');
const LICENSE_FILE = /^(licen[cs]e|copying)(\.(md|txt|markdown))?$/i;
const COPYRIGHT = /^\s*(copyright\s*(\(c\)|©|\d)|\(c\)\s*\d|©)/i;

// Assets bundled outside npm, with the licence files we keep next to them.
const ASSETS = [
  {
    name: 'MuseScore_General (guitar sounds)',
    license: 'MIT',
    file: 'assets/soundfont/MuseScore_General_License.md',
  },
  {
    name: 'Bravura (music font, from alphaTab)',
    license: 'OFL-1.1',
    file: 'node_modules/@coderline/alphatab/dist/font/Bravura-OFL.txt',
  },
  {
    name: 'Sonivox (General MIDI sounds, from alphaTab)',
    license: 'Apache-2.0',
    copyright: ['Copyright (C) 2008 The Android Open Source Project'],
  },
  {
    name: 'Basic Pitch (transcription model, on our server)',
    license: 'Apache-2.0',
    copyright: ['Copyright 2022 Spotify AB'],
  },
];

function productionPackages() {
  let output;
  try {
    output = execFileSync('npm', ['ls', '--omit=dev', '--all', '--parseable'], {
      cwd: root,
      encoding: 'utf8',
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'ignore'],
    });
  } catch (error) {
    // npm ls exits 1 on peer-version warnings ("invalid"); the list it printed is complete.
    output = error.stdout;
  }
  return [...new Set(output.split('\n').filter((p) => p.includes('node_modules')))];
}

function readNotice(dir) {
  const file = fs.readdirSync(dir).find((f) => LICENSE_FILE.test(f));
  return file ? fs.readFileSync(path.join(dir, file), 'utf8') : null;
}

function licenseOf(pkg) {
  const l = pkg.license ?? pkg.licenses;
  if (Array.isArray(l)) return l.map((x) => x.type ?? x).join(' OR ');
  return typeof l === 'object' && l ? l.type : (l ?? 'UNKNOWN');
}

const texts = [];
const textIds = new Map();
function addText(text) {
  if (!text) return null;
  const body = text
    .split('\n')
    .filter((line) => !COPYRIGHT.test(line))
    .join('\n')
    .replace(/\r/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  if (!textIds.has(body)) {
    textIds.set(body, texts.length);
    texts.push(body);
  }
  return textIds.get(body);
}
const copyrightLines = (text) =>
  [...new Set((text ?? '').split('\n').filter((l) => COPYRIGHT.test(l)))].map((l) => l.trim());

// Packages without a licence file (React Native's own, for one) get the standard text of the
// licence they declare, taken from another package that ships it, and their author's name.
const authorOf = (pkg) => (typeof pkg.author === 'string' ? pkg.author : pkg.author?.name);
const missing = [];

const entries = new Map();
for (const dir of productionPackages()) {
  const pkg = JSON.parse(fs.readFileSync(path.join(dir, 'package.json'), 'utf8'));
  if (!pkg.name || pkg.name === 'tabscribe-mobile' || entries.has(pkg.name)) continue;
  // Platform-only build tools (fsevents, lightningcss-darwin-arm64) differ between a Mac and CI
  // and never ship in the app.
  if (pkg.os || pkg.cpu) continue;
  const notice = readNotice(dir);
  const entry = {
    name: pkg.name,
    license: licenseOf(pkg),
    copyright: copyrightLines(notice),
    text: addText(notice),
  };
  if (entry.copyright.length === 0 && authorOf(pkg)) {
    entry.copyright = [`Copyright (c) ${authorOf(pkg)}`];
  }
  if (entry.text === null) missing.push(entry);
  entries.set(pkg.name, entry);
}
const standardText = new Map();
for (const entry of entries.values()) {
  if (entry.text !== null && !standardText.has(entry.license)) {
    standardText.set(entry.license, entry.text);
  }
}
for (const entry of missing) entry.text = standardText.get(entry.license) ?? null;
const packages = [...entries.values()].sort((a, b) => a.name.localeCompare(b.name));
const assets = ASSETS.map(({ file, copyright, ...rest }) => {
  const notice = file ? fs.readFileSync(path.join(root, file), 'utf8') : null;
  const text = addText(notice) ?? standardText.get(rest.license) ?? null;
  return { ...rest, copyright: copyright ?? copyrightLines(notice), text };
});

const json = JSON.stringify({ assets, packages, texts }) + '\n';
if (process.argv.includes('--check')) {
  if (!fs.existsSync(out) || fs.readFileSync(out, 'utf8') !== json) {
    console.error('src/about/licenses.json is out of date: run `node scripts/licenses.js`');
    process.exit(1);
  }
} else {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, json);
  console.log(
    `${packages.length} packages, ${assets.length} assets, ${texts.length} licence texts`,
  );
}
