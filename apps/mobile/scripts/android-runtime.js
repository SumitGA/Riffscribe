// Guards the Android app in testers' hands (TD-38): over-the-air updates (`eas update`) only
// reach installed builds whose native fingerprint matches. android-runtime.txt holds the
// fingerprint of the Android build on Google Play; this fails when the code's Android
// fingerprint differs, so a change to native code or config (a new native module, a plugin
// setting, even one meant for iOS) can't silently cut Android off from updates. When the change
// is intended: build and upload a new Android app, then put its fingerprint in the file.
// `node scripts/android-runtime.js` checks (CI); `--print` shows the current fingerprint.
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const output = execFileSync(
  'npx',
  ['expo-updates', 'fingerprint:generate', '--platform', 'android'],
  {
    cwd: root,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  },
);
const current = JSON.parse(output.slice(output.indexOf('{'))).hash;
if (process.argv.includes('--print')) {
  console.log(current);
  process.exit(0);
}
// google-services.json (push) counts towards the fingerprint, and it is git-ignored: EAS gets
// it from a file variable, CI doesn't have it. The file records the fingerprint both ways.
const key = fs.existsSync(path.join(root, 'google-services.json'))
  ? 'with-google-services'
  : 'without-google-services';
const recorded = Object.fromEntries(
  fs
    .readFileSync(path.join(root, 'android-runtime.txt'), 'utf8')
    .split('\n')
    .filter((line) => line.includes('=') && !line.startsWith('#'))
    .map((line) => line.trim().split('=')),
);
const live = recorded[key];
if (current !== live) {
  console.error(
    `Android fingerprint ${current} differs from the build on Google Play (${live}, android-runtime.txt).\n` +
      'Installed Android apps would get no over-the-air updates from this code. If that is intended, ' +
      'build and upload a new Android app and record its fingerprints in android-runtime.txt\n' +
      '(`node scripts/android-runtime.js --print`, with and without google-services.json).',
  );
  process.exit(1);
}
console.log(`Android fingerprint matches the build on Google Play (${key}: ${live.slice(0, 8)})`);
