import { Asset } from 'expo-asset';
import { Directory, File, Paths } from 'expo-file-system';

import { VIEWER_PAGE } from './viewerPage';

// Bump with @coderline/alphatab in package.json: a new folder gets fresh copies.
const ALPHATAB_VERSION = '1.8.4';

export type ViewerFiles = {
  /** file:// URL of the viewer page. */
  page: string;
  /** Its folder, which the WebView may read (iOS needs it named explicitly). */
  folder: string;
};

/**
 * Lays out the score viewer in the app's cache: the page, alphaTab's script, its music font
 * and its soundfont, under their real names so the page can load them by relative URL. The
 * bundled assets (scripts/viewer-assets.js) are copied once per alphaTab version; the page is
 * rewritten every time, as it's tiny and changes with the app.
 */
export async function prepareViewer(): Promise<ViewerFiles> {
  const folder = new Directory(Paths.cache, `score-viewer-${ALPHATAB_VERSION}`);
  const fontFolder = new Directory(folder, 'font');
  folder.create({ idempotent: true, intermediates: true });
  fontFolder.create({ idempotent: true });

  const targets = [
    new File(folder, 'alphaTab.min.js'),
    new File(fontFolder, 'Bravura.woff2'),
    new File(folder, 'sonivox.sf2'),
  ];
  if (targets.some((target) => !target.exists)) {
    // Bundled files (not code) are referenced with require(); Metro turns them into assets.
    /* eslint-disable @typescript-eslint/no-require-imports */
    const assets = await Asset.loadAsync([
      require('../../assets/viewer/alphaTab.txt'),
      require('../../assets/viewer/Bravura.woff2'),
      require('../../assets/viewer/sonivox.sf2'),
    ]);
    /* eslint-enable @typescript-eslint/no-require-imports */
    await Promise.all(
      assets.map(async (asset, i) => {
        const target = targets[i];
        if (!asset.localUri || !target) {
          throw new Error(`score viewer file missing: ${asset.name}`);
        }
        if (!target.exists) {
          await new File(asset.localUri).copy(target);
        }
      }),
    );
  }

  const page = new File(folder, 'index.html');
  page.write(VIEWER_PAGE);
  return { page: page.uri, folder: folder.uri };
}
