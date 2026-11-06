// Guards the apps in the stores (TD-38): over-the-air updates (`eas update`) only reach
// installed builds whose native fingerprint matches. store-runtimes.txt holds the fingerprints
// of the Android build on Google Play and the iOS build on the App Store; this fails when the
// code's fingerprint for either platform differs, so a change to native code or config (a new
// native module, a plugin setting, anything in app.json) can't silently cut either app off
// from updates. App releases go to both platforms together (TD-43): when the change is
// intended, it ships as a new build for both (`make mobile-release`), and their fingerprints
// go in the file.
// `node scripts/store-runtimes.js` checks (CI, `make mobile-update`); `--print` shows the
// current fingerprints.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');

function fingerprint(platform) {
  const output = execFileSync(
    'npx',
    ['expo-updates', 'fingerprint:generate', '--platform', platform],
    { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
  );
  return JSON.parse(output.slice(output.indexOf('{'))).hash;
}

// google-services.json (push) counts towards the Android fingerprint, and it is git-ignored:
// EAS gets it from a file variable, CI doesn't have it. The file records it both ways.
const androidKey = fs.existsSync(path.join(root, 'google-services.json'))
  ? 'android-with-google-services'
  : 'android-without-google-services';
const current = { [androidKey]: fingerprint('android'), ios: fingerprint('ios') };

if (process.argv.includes('--print')) {
  for (const [key, value] of Object.entries(current)) console.log(`${key}=${value}`);
  process.exit(0);
}

const recorded = Object.fromEntries(
  fs
    .readFileSync(path.join(root, 'store-runtimes.txt'), 'utf8')
    .split('\n')
    .filter((line) => line.includes('=') && !line.startsWith('#'))
    .map((line) => line.trim().split('=')),
);
const stores = { [androidKey]: 'Google Play', ios: 'the App Store' };
const differ = Object.keys(current).filter((key) => current[key] !== recorded[key]);
if (differ.length) {
  for (const key of differ) {
    console.error(
      `${key} fingerprint ${current[key]} differs from the build on ${stores[key]} (${recorded[key]}).`,
    );
  }
  console.error(
    'Installed apps would get no over-the-air updates from this code. If the native change is ' +
      'intended, it ships as a new build for both platforms (`make mobile-release`, ' +
      'docs/releasing.md); record the new fingerprints in store-runtimes.txt once both are live.',
  );
  process.exit(1);
}
console.log(
  'Fingerprints match the store builds: ' +
    Object.keys(current)
      .map((key) => `${key} ${current[key].slice(0, 8)}`)
      .join(', '),
);
