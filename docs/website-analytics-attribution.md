# Website Analytics Attribution

Attribution priority is deterministic:

1. exact `smm_attribution_id`;
2. campaign plus content ID;
3. exact landing URL;
4. supported UTM source/campaign combination;
5. source-only partial attribution;
6. unattributed.

Conflicting signals are marked `conflicting` and are not silently resolved.
Readmodels expose attribution coverage, exact attribution rate, conflicting
rate, and unattributed rate so incomplete data stays visible.
