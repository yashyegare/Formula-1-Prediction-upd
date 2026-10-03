// Resolve hook so Node can import the explorer's Vite-style extensionless
// internal imports ('./geometry') without a build step.

export async function resolve(specifier, context, next) {
  if (specifier.startsWith(".") && !/\.[cm]?js$/.test(specifier)) {
    try {
      return await next(specifier + ".js", context);
    } catch {
      /* fall through to the default error */
    }
  }
  return next(specifier, context);
}
