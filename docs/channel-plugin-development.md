# Channel Plugin Development

Start with `python -m plugin_sdk.cli create-channel --id channel.example --name Example --mode api-first --capability text --output plugins/community/channel_example`. Use only `from plugin_sdk import ...`.

API-first plugins should build a plugin-local client around the safe HTTP facade and keep OAuth or token state in the secret service. Browser-based plugins request browser access through the public browser facade and never import concrete providers. Runtime methods return standardized SDK models and unsupported operations raise SDK capability errors.
