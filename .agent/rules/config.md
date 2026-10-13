# Configuration rules

Applies to `config/**` and `tests/config/**`. Use typed pydantic-settings schemas and the `EW_` prefix.
Use typed central YAML configuration and separate environment secrets. Add schemas only for specified fields.
Config cannot import application packages. Pass validated values from a future outer composition
root into contexts. Keep `.env.example` non-secret and current. Dotenv paths use the working directory.
