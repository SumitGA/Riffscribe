// Extends app.json with values that only exist at build time (ADR-0010). On EAS, the
// google-services.json for push (git-ignored) comes from the GOOGLE_SERVICES_JSON file
// variable; locally it's the file next to this one.
module.exports = ({ config }) => ({
  ...config,
  android: {
    ...config.android,
    googleServicesFile: process.env.GOOGLE_SERVICES_JSON ?? config.android.googleServicesFile,
  },
});
