import { File, Paths } from 'expo-file-system';

/**
 * Whether this phone has shown the welcome guide: an empty marker file in the app's documents,
 * so it survives restarts and updates and goes away with a reinstall.
 */
const marker = () => new File(Paths.document, 'welcome-seen');

export function hasSeenWelcome(): boolean {
  try {
    return marker().exists;
  } catch {
    return true; // never trap someone in the guide because storage failed
  }
}

export function markWelcomeSeen(): void {
  try {
    marker().create({ overwrite: true });
  } catch (error) {
    console.warn("couldn't remember that the welcome guide was shown", error);
  }
}
