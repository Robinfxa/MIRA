# FND-06 distribution identity

Block: tooling. Consumers: package/startup and source restoration. Base: imported foundation ebb578dde665c9c7269e4a64b508182680b2fa66. Resources: offline metadata only, no install or provider.

### FND06-001
Given the source release metadata, package.json, package-lock root and root package metadata, and pyproject project must declare the same name/version. Declared frontend dependencies/engines must agree with the lock root. A mismatch is a documentation/distribution identity failure; it does not alone prove npm ci failure.

No fresh installation, browser or platform compatibility claim follows from these tests.
