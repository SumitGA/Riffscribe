// Expo's default Metro config, plus the score viewer's file types (scripts/viewer-assets.js):
// alphaTab's JS shipped as text, its music font and its soundfonts (.sf2, our trimmed .sf3).
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
config.resolver.assetExts.push('txt', 'woff2', 'sf2', 'sf3');

module.exports = config;
