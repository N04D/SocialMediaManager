# Reconciliation Leases

Workers claim reconciliation items with an atomic lease owner and expiry. Heartbeats extend a valid lease. Release requires the owner. Expired leases are recovered at startup or by the recovery API.

Two workers cannot claim the same active item. A crashed worker does not permanently block the queue because expired leases are reclaimed.
