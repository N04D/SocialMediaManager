# CI Import Attestations

A CI import attestation records that this host fetched and technically verified
a specific artifact from a configured CI origin. It binds:

- origin;
- repository and workflow;
- run ID and attempt;
- head SHA;
- artifact ID and name;
- provider digest;
- downloaded checksum;
- evidence package ID and checksum;
- technical verification status;
- optional host signature.

The attestation does not replace an internal package signature when policy
requires that signature.
