// iOS 27 stops apps at launch unless they use the scene-based life cycle, and Expo SDK 57's
// generated AppDelegate doesn't (SDK 58's does). This switches on the scene delegate SDK 57
// already ships (ExpoAppSceneDelegate): it creates the window and starts React Native, so the
// AppDelegate stops doing both. iOS only. Delete this plugin when moving to SDK 58 (TD-39).
const { withAppDelegate, withInfoPlist } = require('expo/config-plugins');

const WINDOW_START = /\n#if os\(iOS\) \|\| os\(tvOS\)\n {4}window = UIWindow[\s\S]*?#endif\n/;

module.exports = function withSceneLifecycle(config) {
  config = withInfoPlist(config, (c) => {
    c.modResults.UIApplicationSceneManifest = {
      UIApplicationSupportsMultipleScenes: false,
      UISceneConfigurations: {
        UIWindowSceneSessionRoleApplication: [
          {
            UISceneConfigurationName: 'Default Configuration',
            UISceneDelegateClassName: 'EXExpoAppSceneDelegate',
          },
        ],
      },
    };
    return c;
  });
  return withAppDelegate(config, (c) => {
    let source = c.modResults.contents;
    if (!source.includes('ExpoReactNativeFactoryProvider')) {
      source = source.replace(
        'class AppDelegate: ExpoAppDelegate {',
        'class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {',
      );
    }
    source = source.replace(WINDOW_START, '\n');
    if (!source.includes('ExpoReactNativeFactoryProvider') || WINDOW_START.test(source)) {
      throw new Error('with-scene-lifecycle: the AppDelegate template changed; update the plugin');
    }
    c.modResults.contents = source;
    return c;
  });
};
