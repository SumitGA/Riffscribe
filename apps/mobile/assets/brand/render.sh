#!/bin/bash
# Renders every app, store and website icon from the Riffscribe mark (pick.svg). Needs
# rsvg-convert (brew install librsvg). Text uses Helvetica: render on a Mac. Run from anywhere:
#   apps/mobile/assets/brand/render.sh
set -euo pipefail
cd "$(dirname "$0")"
assets=..
site=../../../../infra/site
r() { rsvg-convert -w "$2" -h "$2" "$1" -o "$3"; }
r icon.svg 1024 "${assets}/icon.png"                       # app icon (iOS, fallback)
r foreground.svg 1024 "${assets}/android-icon-foreground.png" # Android adaptive icon
r background.svg 1024 "${assets}/android-icon-background.png"
r monochrome.svg 1024 "${assets}/android-icon-monochrome.png" # Android 13 themed icon
r pick.svg 1024 "${assets}/splash-icon.png"                 # splash screen, on #0D0E11
mkdir -p "${assets}/store"
r icon.svg 512 "${assets}/store/play-icon-512.png"          # Google Play listing icon
r icon.svg 64 "${site}/favicon.png"                         # website
r icon.svg 180 "${site}/apple-touch-icon.png"
echo "icons rendered"
