// Jest only: Lucide ships ES modules (.mjs) that jest-expo doesn't transform. Every icon renders
// nothing; tests check text and roles, not icons.
module.exports = new Proxy(
  { __esModule: true },
  { get: (target, name) => (name in target ? target[name] : () => null) },
);
