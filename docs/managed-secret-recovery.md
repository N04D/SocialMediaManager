# Managed Secret Recovery

Recovery is conservative:

- scan encrypted records read-only;
- remove or quarantine temporary incomplete records;
- report orphan backend records;
- keep consumers blocked until operator action;
- do not overwrite corrupt ciphertext;
- do not try alternate master keys.

Crash during rotation leaves the old active version authoritative.
