# Browser Framework Versioning

Browser Framework v1 follows semantic versioning for the browser contract surface.

## Patch Changes

Allowed:

- bug fixes;
- safer error translation;
- internal provider changes;
- extra tests;
- documentation;
- optional health fields;
- performance improvements without behavior changes.

## Minor Changes

Allowed:

- optional capability;
- new optional method;
- new result field with safe default;
- new provider;
- non-breaking target strategy.

## Major Changes

Required for:

- removing a method;
- renaming a method;
- making a parameter mandatory;
- changing error semantics;
- changing locking semantics;
- changing session ownership;
- changing provider selection behavior;
- changing existing target interpretation.

Breaking changes require:

- new contract version;
- migration document;
- compatibility period;
- tests for old and new providers;
- explicit changelog note.

## Deprecation Metadata

Legacy browser helpers, pipeline flows, compatibility modules, and old lock readers should carry:

- `deprecated`;
- `deprecated_since`;
- `replacement`;
- `removal_target`;
- `reason`.

Runtime warnings should be limited to operator-facing paths and must not create log spam.

## Maintainer Checklist

For a new browser provider:

- manifest and contract versions;
- health and conformance payload;
- profile locking;
- artifacts;
- takeover;
- contract tests;
- security checks;
- provider selection tests.

For a new channel plugin:

- no concrete provider imports;
- `BrowserTarget` selectors;
- runtime service;
- capability manifest;
- status translation;
- provider-independent tests.
