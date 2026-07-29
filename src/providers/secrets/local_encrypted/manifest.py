"""Provider manifest for the local encrypted secret backend."""

provider_id = "secret.local_encrypted"
provider_version = "0.1.0"
data_access = "call_scoped_secret_storage"
execution_mode = "built_in_in_process"
cryptographic_primitive = "AES-256-GCM"
